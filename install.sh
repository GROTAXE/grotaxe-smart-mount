#!/bin/sh
set -eu
umask 077

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"

case "${1:-}" in
    --check|--install)
        MODULE=release_install
        ;;
    --help)
        printf '%s\n' \
            "GROTAXE SMART MOUNT" \
            "" \
            "./install.sh" \
            "./install.sh --check" \
            "./install.sh --install --config FILE" \
            "" \
            "Installation does not activate services."
        exit 0
        ;;
    *)
        MODULE=wizard
        ;;
esac

exec /usr/bin/python3 -I -B -S -c '
import sys
from importlib import import_module

root = sys.argv.pop(1)
module = sys.argv.pop(1)

import os
import stat
from pathlib import Path

if os.geteuid() == 0:
    def reject():
        print(
            "Privileged execution requires a trusted installation source.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if module != "release_install" or sys.argv[1:2] != ["--install"]:
        reject()

    def trusted(path, directory):
        info = path.lstat()

        correct_type = (
            stat.S_ISDIR(info.st_mode)
            if directory
            else stat.S_ISREG(info.st_mode)
        )

        if (
            not correct_type
            or info.st_uid != 0
            or info.st_mode & 0o022
            or (not directory and info.st_nlink != 1)
        ):
            reject()

    try:
        base = Path(root)
        package = base / "src" / "smart_mount"

        for directory in (
            *reversed(base.parents),
            base,
            base / "src",
            package,
        ):
            trusted(directory, True)

        trusted(base / "install.sh", False)

        for entry in package.iterdir():
            if entry.suffix != ".py":
                reject()

            trusted(entry, False)

    except OSError:
        reject()

sys.path.insert(0, root + "/src")

raise SystemExit(
    import_module("smart_mount." + module).main()
)
' "$ROOT" "$MODULE" "$@"
