"""Restricted system service entry point."""

import argparse
import copy
import json
import os

from pathlib import Path

from .config import ConfigError
from .identity import MountError
from .process_namespace import ProcessNamespaceAdapter
from .runtime import RuntimeEngine
from .state import locked_state, LockBusy
from .system_backend import SystemBackend
from .trusted_config import (
    check_metadata,
    load_trusted_config,
)


PREFIX = Path("/opt/grotaxe-smart-mount")
CONFIG = Path("/etc/grotaxe-smart-mount/config.toml")
RUNTIME = Path("/run/grotaxe-smart-mount")


def require_installed():
    """Prevent privileged execution from a development checkout."""

    if os.geteuid() != 0:
        raise MountError("Root privileges required.")

    expected = PREFIX / "smart_mount" / "runtime_entry.py"
    actual = Path(__file__).absolute()

    if actual != expected or actual.resolve() != expected:
        raise MountError("Installed runtime required.")

    for directory in (
        Path("/"),
        Path("/opt"),
        PREFIX,
        PREFIX / "smart_mount",
        Path("/run"),
        RUNTIME,
    ):
        check_metadata(
            directory.lstat(),
            directory=True,
        )

    check_metadata(
        RUNTIME.lstat(),
        directory=True,
    )

    if RUNTIME.stat().st_mode & 0o777 != 0o700:
        raise MountError("Unsafe runtime directory.")


def protection_policy(config):
    """Disable automatic service recovery for this release stage."""

    policy = copy.deepcopy(config)

    for group in policy["groups"]:
        if "grotaxe-smart-mount.service" in group["units"]:
            raise ConfigError(
                "The protection service cannot protect itself."
            )

        group["auto_recovery"] = False

    return policy


def run_once(*, apply=False):
    if apply:
        require_installed()

    config = protection_policy(
        load_trusted_config(CONFIG)
    )

    backend = SystemBackend(
        config,
        apply=apply,
    )

    namespace = ProcessNamespaceAdapter(backend)

    engine = RuntimeEngine(
        config,
        backend,
        verify_bind=namespace.verify_bind,
        paused=lambda name: True,
    )

    if apply:
        with locked_state(RUNTIME, config) as store:
            result = engine.cycle(
                store=store,
                apply=True,
            )
    else:
        result = engine.cycle()

    assessment = result["assessment"]

    # Do not disclose service names, paths, UUIDs,
    # configuration contents or boot identifiers.
    return {
        "ok": result.get("ok", assessment["safe"]),
        "mode": "protection" if apply else "preview",
        "safe": assessment["safe"],
        "recovery_disabled": True,
        "degraded": result.get("degraded", False),
        "volumes": len(assessment["volumes"]),
        "blocked_groups": sum(
            group["health"] == "BLOCKED"
            for group in assessment["groups"]
        ),
        "failed_actions": sum(
            len(group.get("result", {}).get("failed", []))
            for group in result.get("groups", [])
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="smart-mount-runtime",
    )

    mode = parser.add_mutually_exclusive_group()

    mode.add_argument(
        "--preview",
        action="store_true",
    )

    mode.add_argument(
        "--apply-protection",
        action="store_true",
    )

    args = parser.parse_args(argv)

    try:
        result = run_once(
            apply=args.apply_protection,
        )

    except LockBusy:
        print(json.dumps({
            "ok": False,
            "reason": "RUNTIME_LOCK_BUSY",
        }))
        return 75

    except (MountError, ConfigError, OSError):
        print(json.dumps({
            "ok": False,
            "reason": "RUNTIME_CHECK_FAILED",
        }))
        return 1

    print(json.dumps(result, sort_keys=True))

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
