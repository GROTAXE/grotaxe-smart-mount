#!/usr/bin/env python3
"""Read-only Linux storage identity validation."""

import argparse
import json
import re
import subprocess
from pathlib import Path

UUID_PATTERN = (
    r"[A-Fa-f0-9]{8}-[A-Fa-f0-9]{4}-"
    r"[A-Fa-f0-9]{4}-[A-Fa-f0-9]{4}-"
    r"[A-Fa-f0-9]{12}"
)


class MountError(RuntimeError):
    """Storage identity or access policy violation."""


def mount_at(path, *, mode="rw"):
    if mode not in {"rw", "ro"}:
        raise MountError("Invalid access policy.")

    try:
        result = subprocess.run(
            [
                "/usr/bin/findmnt", "--json", "--list",
                "--target", str(path),
                "--output",
                "TARGET,UUID,FSTYPE,FSROOT,"
                "VFS-OPTIONS,FS-OPTIONS",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
            cwd="/",
            env={
                "PATH": "/usr/bin:/bin",
                "LC_ALL": "C",
            },
        )

        entries = json.loads(result.stdout)["filesystems"]

        if not isinstance(entries, list) or len(entries) != 1:
            raise MountError("Expected exactly one filesystem.")

        entry = entries[0]

        identity = {
            key: entry[key]
            for key in ("target", "uuid", "fstype", "fsroot")
        }

        if not all(
            isinstance(value, str) and value
            for value in identity.values()
        ):
            raise MountError("Incomplete filesystem identity.")

        if not re.fullmatch(UUID_PATTERN, identity["uuid"]):
            raise MountError("Unsupported filesystem UUID.")

        vfs = set(entry["vfs-options"].split(","))
        fs = set(entry["fs-options"].split(","))

    except (
        OSError, subprocess.SubprocessError,
        ValueError, KeyError, TypeError, AttributeError
    ) as exc:
        raise MountError("Cannot identify filesystem.") from exc

    if mode == "rw":
        if "rw" not in vfs or "ro" in vfs:
            raise MountError("VFS mount is not read-write.")
        if "rw" not in fs or "ro" in fs:
            raise MountError("Filesystem is not read-write.")

    elif "ro" not in vfs or "rw" in vfs:
        raise MountError("VFS mount is not read-only.")

    identity["uuid"] = identity["uuid"].lower()
    return identity


def check(path, uuid, *, mode="rw", fstype=None, fsroot=None):
    path = Path(path)

    try:
        if (
            not path.is_absolute()
            or not path.is_dir()
            or path.resolve(strict=True) != path
        ):
            raise MountError("Invalid or noncanonical mountpoint.")
    except (OSError, RuntimeError) as exc:
        raise MountError("Cannot validate mountpoint.") from exc

    if not isinstance(uuid, str) or not re.fullmatch(
        UUID_PATTERN, uuid
    ):
        raise MountError("Invalid filesystem UUID.")

    actual = mount_at(path, mode=mode)

    if actual["target"] != str(path):
        raise MountError("Expected mountpoint is unavailable.")

    if actual["uuid"] != uuid.lower():
        raise MountError("Filesystem UUID mismatch.")

    if fstype is not None and actual["fstype"] != fstype:
        raise MountError("Filesystem type mismatch.")

    if fsroot is not None and actual["fsroot"] != fsroot:
        raise MountError("Filesystem root mismatch.")

    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument("mountpoint", type=Path)
    parser.add_argument("uuid")
    parser.add_argument("--mode", choices=("rw", "ro"), default="rw")
    parser.add_argument("--fstype")
    parser.add_argument("--fsroot")
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args()

    try:
        result = check(
            args.mountpoint,
            args.uuid,
            mode=args.mode,
            fstype=args.fstype,
            fsroot=args.fsroot,
        )
    except MountError as exc:
        parser.exit(1, f"[FAIL] {exc}\n")

    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print("[ OK ] Storage identity verified.")


if __name__ == "__main__":
    main()
