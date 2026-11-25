"""Read-only installation planning with an explicit payload."""

import argparse
import hashlib
import json
import os
import stat

from pathlib import Path

from .config import ConfigError
from .identity import MountError
from .terminal import Terminal
from .trusted_config import decode_config
from .wizard import read_template


PREFIX = "/opt/grotaxe-smart-mount"
CONFIG_DIR = "/etc/grotaxe-smart-mount"
RUNTIME_DIR = "/run/grotaxe-smart-mount"
UNIT_DIR = "/etc/systemd/system"

MODULES = (
    "__init__.py",
    "__main__.py",
    "identity.py",
    "namespace.py",
    "config.py",
    "guard.py",
    "systemd.py",
    "process_namespace.py",
    "recovery.py",
    "executor.py",
    "state.py",
    "runtime.py",
    "runtime_entry.py",
    "system_backend.py",
    "trusted_config.py",
    "terminal.py",
    "cli.py",
    "wizard.py",
)

MAX_MODULE_SIZE = 1024 * 1024


class PlanError(MountError):
    """Invalid installation payload."""


def source_directory(value):
    path = Path(value)

    if (
        not path.is_absolute()
        or path.resolve(strict=True) != path
        or not path.is_dir()
    ):
        raise PlanError("Invalid source directory.")

    return path


def module_digest(path):
    fd = os.open(
        path,
        os.O_RDONLY
        | os.O_NOFOLLOW
        | os.O_NONBLOCK
        | os.O_CLOEXEC,
    )

    try:
        before = os.fstat(fd)

        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
        ):
            raise PlanError("Invalid payload file.")

        if before.st_size > MAX_MODULE_SIZE:
            raise PlanError("Payload file too large.")

        chunks = []
        remaining = MAX_MODULE_SIZE + 1

        while remaining:
            chunk = os.read(fd, min(65536, remaining))

            if not chunk:
                break

            chunks.append(chunk)
            remaining -= len(chunk)

        data = b"".join(chunks)

        if len(data) > MAX_MODULE_SIZE:
            raise PlanError("Payload file too large.")

        after = os.fstat(fd)

        if (
            not stat.S_ISREG(after.st_mode)
            or after.st_nlink != 1
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or len(data) != after.st_size
        ):
            raise PlanError("Payload changed during inspection.")

        return hashlib.sha256(data).hexdigest()

    finally:
        os.close(fd)


def build_plan(source, config_data):
    config = decode_config(config_data)
    source = source_directory(source)

    payload = []

    for name in MODULES:
        payload.append({
            "module": name,
            "destination": (
                f"{PREFIX}/smart_mount/{name}"
            ),
            "mode": "0644",
            "sha256": module_digest(source / name),
        })

    directories = [
        {"path": PREFIX, "mode": "0755"},
        {"path": PREFIX + "/smart_mount", "mode": "0755"},
        {"path": CONFIG_DIR, "mode": "0700"},
        {"path": RUNTIME_DIR, "mode": "0700"},
    ]

    configuration = {
        "destination": CONFIG_DIR + "/config.toml",
        "mode": "0600",
        "volumes": len(config["volumes"]),
        "groups": len(config["groups"]),
        "auto_recovery_groups": sum(
            group["auto_recovery"]
            for group in config["groups"]
        ),
    }

    pending = [
        "/usr/local/bin/smart-mount",
        "/usr/local/bin/smart-mount-wizard",
        UNIT_DIR + "/grotaxe-smart-mount.service",
        UNIT_DIR + "/grotaxe-smart-mount.timer",
    ]

    return {
        "plan_version": 1,
        "dry_run": True,
        "system_changes": False,
        "ready_for_install": False,
        "directories": directories,
        "payload": payload,
        "configuration": configuration,
        "pending_artifacts": pending,
        "activate_services": False,
    }


def render(ui, plan):
    ui.banner()
    ui.heading("INSTALLATION PLAN")

    ui.heading("01 / PROGRAM FILES")
    ui.field("LOCATION", PREFIX)
    ui.field("MODULES", len(plan["payload"]))
    ui.status(True, "Payload inspected")

    ui.heading("02 / CONFIGURATION")
    config = plan["configuration"]
    ui.field("DESTINATION", config["destination"])
    ui.field("PERMISSIONS", config["mode"])
    ui.field("VOLUMES", config["volumes"])
    ui.field("SERVICE GROUPS", config["groups"])
    ui.field(
        "AUTO RECOVERY GROUPS",
        config["auto_recovery_groups"],
    )

    ui.heading("03 / SYSTEM INTEGRATION")
    ui.field("RUNTIME", RUNTIME_DIR)
    ui.field("SERVICE ACTIVATION", "disabled")
    ui.field(
        "PENDING ARTIFACTS",
        len(plan["pending_artifacts"]),
    )

    ui.heading("04 / SAFETY")
    ui.field("SYSTEM CHANGES", "none")
    ui.field("INSTALLATION", "not performed")
    ui.field("MODE", "dry run")

    ui.line()
    ui.status(True, "Installation plan prepared")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Smart Mount installation planner",
    )

    parser.add_argument("--source", required=True)
    parser.add_argument("--config", required=True)

    output = parser.add_mutually_exclusive_group()
    output.add_argument("--plain", action="store_true")
    output.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    ui = Terminal(plain=args.plain)

    try:
        plan = build_plan(
            args.source,
            read_template(args.config),
        )

    except (PlanError, ConfigError, OSError, RuntimeError):
        if args.json:
            print(json.dumps({
                "ok": False,
                "error": "Installation planning failed.",
            }))
        else:
            ui.status(False, "Installation planning failed.")

        return 1

    if args.json:
        print(json.dumps(
            {"ok": True, **plan},
            sort_keys=True,
        ))
    else:
        render(ui, plan)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
