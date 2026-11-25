"""Read-only Smart Mount command line interface."""

import argparse
import json
import os
import platform
import sys

from .config import ConfigError, load_config
from .identity import MountError, check, mount_at
from .process_namespace import ProcessNamespaceAdapter
from .runtime import RuntimeEngine
from .system_backend import SystemBackend
from .terminal import Terminal, TITLE


def parser():
    root = argparse.ArgumentParser(
        prog="smart-mount",
        description=TITLE + " | Linux Storage Protection",
    )

    output = root.add_mutually_exclusive_group()

    output.add_argument("--plain", action="store_true")
    output.add_argument("--json", action="store_true")

    commands = root.add_subparsers(
        dest="command",
        required=True,
    )

    verify = commands.add_parser(
        "check", help="Verify storage identity"
    )

    verify.add_argument("mountpoint")
    verify.add_argument("uuid")
    verify.add_argument("--fstype")
    verify.add_argument("--fsroot")

    inspect = commands.add_parser(
        "inspect", help="Inspect mounted storage"
    )

    inspect.add_argument("path")

    for command in (verify, inspect):
        command.add_argument(
            "--mode",
            choices=("rw", "ro"),
            default="rw",
        )

    config = commands.add_parser(
        "config", help="Validate TOML configuration"
    )
    config.add_argument("file")

    status = commands.add_parser(
        "status", help="Evaluate protection status"
    )
    status.add_argument("file")

    commands.add_parser("doctor", help="Check dependencies")
    commands.add_parser("about", help="Project information")

    return root


def doctor():
    checks = {
        "linux": platform.system() == "Linux",
        "python": sys.version_info >= (3, 11),
        "findmnt": os.access("/usr/bin/findmnt", os.X_OK),
        "systemctl": os.access("/usr/bin/systemctl", os.X_OK),
        "procfs": os.access("/proc/self/mountinfo", os.R_OK),
    }

    return {
        "ok": all(checks.values()),
        "checks": checks,
    }


def execute(args):
    if args.command == "about":
        return {
            "ok": True,
            "project": TITLE,
            "description": "Linux Storage Protection",
            "channel": "development",
        }

    if args.command == "doctor":
        return doctor()

    if args.command == "check":
        identity = check(
            args.mountpoint,
            args.uuid,
            mode=args.mode,
            fstype=args.fstype,
            fsroot=args.fsroot,
        )

        return {
            "ok": True,
            "identity": identity,
            "mode": args.mode,
        }

    if args.command == "inspect":
        if not os.path.isabs(args.path):
            raise MountError("Expected an absolute path.")

        return {
            "ok": True,
            "identity": mount_at(
                args.path, mode=args.mode
            ),
            "mode": args.mode,
        }

    config = load_config(args.file)

    if args.command == "config":
        return {
            "ok": True,
            "schema_version": config["schema_version"],
            "volumes": len(config["volumes"]),
            "groups": len(config["groups"]),
        }

    backend = SystemBackend(config, apply=False)
    namespace = ProcessNamespaceAdapter(backend)

    engine = RuntimeEngine(
        config,
        backend,
        verify_bind=namespace.verify_bind,
    )

    assessment = engine.preview()

    return {
        "ok": assessment["safe"],
        "read_only": True,
        "assessment": assessment,
    }


def render(ui, args, result):
    ui.banner()
    ui.heading(args.command.upper())

    if "identity" in result:
        for key, value in result["identity"].items():
            ui.field(key.upper(), value)

        ui.field("ACCESS POLICY", result["mode"])

    elif "checks" in result:
        for key, value in result["checks"].items():
            ui.status(value, key.upper())

    elif "assessment" in result:
        assessment = result["assessment"]

        ui.heading("VOLUMES")

        for name, healthy in assessment["volumes"].items():
            ui.status(healthy, name)

        ui.heading("SERVICE GROUPS")

        for group in assessment["groups"]:
            ui.field(group["name"], group["health"])

            for error in group["errors"]:
                ui.field("REASON", error["code"])

    else:
        for key, value in result.items():
            if key != "ok":
                ui.field(key.upper(), value)

    ui.line()
    ui.status(result["ok"], "Complete" if result["ok"] else "Check failed")


def main(argv=None):
    args = parser().parse_args(argv)
    ui = Terminal(plain=args.plain)

    try:
        result = execute(args)

    except (MountError, ConfigError, OSError):
        result = {
            "ok": False,
            "error": "Verification failed. Check configuration and permissions.",
        }

    if args.json:
        print(json.dumps(result, sort_keys=True))
    elif "error" in result:
        Terminal(sys.stderr, plain=args.plain).status(
            False, result["error"]
        )
    else:
        render(ui, args, result)

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
