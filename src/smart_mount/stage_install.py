"""Build an isolated installation image without system changes."""

import hashlib
import json
import os
import shutil
import stat
import tempfile

from pathlib import Path, PurePosixPath

from .install_plan import (
    PREFIX,
    CONFIG_DIR,
    UNIT_DIR,
    MAX_MODULE_SIZE,
    PlanError,
    build_plan,
    source_directory,
)


MANIFEST = PREFIX + "/install-manifest.json"

UNITS = (
    "grotaxe-smart-mount.service",
    "grotaxe-smart-mount.timer",
)

LAUNCHERS = {
    "/usr/local/bin/smart-mount": "cli",
    "/usr/local/bin/smart-mount-wizard": "wizard",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_regular(path):
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
            or before.st_size > MAX_MODULE_SIZE
        ):
            raise PlanError("Invalid installation file.")

        data = bytearray()

        while len(data) <= MAX_MODULE_SIZE:
            chunk = os.read(
                fd,
                min(65536, MAX_MODULE_SIZE + 1 - len(data)),
            )

            if not chunk:
                break

            data.extend(chunk)

        after = os.fstat(fd)

        if (
            len(data) > MAX_MODULE_SIZE
            or len(data) != after.st_size
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
            or after.st_nlink != 1
        ):
            raise PlanError("Installation file changed.")

        return bytes(data), stat.S_IMODE(after.st_mode)

    finally:
        os.close(fd)


def target(stage, destination):
    path = PurePosixPath(destination)

    if (
        not path.is_absolute()
        or ".." in path.parts
        or path.anchor != "/"
        or str(path) != destination
        or len(path.parts) < 2
    ):
        raise PlanError("Invalid installation destination.")

    return stage.joinpath(*path.parts[1:])


def make_stage_directory(stage, path, *, mode=0o755):
    """Create safe directories independently of caller umask."""

    current = stage

    for part in path.relative_to(stage).parts:
        current = current / part
        requested = mode if current == path else 0o755

        try:
            current.mkdir(mode=requested)
        except FileExistsError:
            pass
        else:
            current.chmod(requested)

        info = current.lstat()

        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise PlanError("Unsafe staging directory.")


def put_file(stage, destination, data, mode):
    path = target(stage, destination)

    make_stage_directory(stage, path.parent)

    fd = os.open(
        path,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_NOFOLLOW
        | os.O_CLOEXEC,
        mode,
    )

    with os.fdopen(fd, "wb") as handle:
        os.fchmod(handle.fileno(), mode)
        handle.write(data)

    return {
        "path": destination,
        "mode": f"{mode:04o}",
        "sha256": digest(data),
    }


def launcher(module):
    if module not in LAUNCHERS.values():
        raise PlanError("Invalid launcher module.")

    return (
        "#!/bin/sh\n"
        "/usr/bin/true\n"
        "exec /usr/bin/python3 -I -B -c "
        f"'import sys; sys.path.insert(0, \"{PREFIX}\"); "
        f"from smart_mount.{module} import main; "
        'raise SystemExit(main())\' "$@"\n'
    ).encode("utf-8")


def verify_files(stage, records):
    """Verify files against trusted in-memory records."""

    for item in records:
        data, mode = read_regular(
            target(stage, item["path"])
        )

        if (
            digest(data) != item["sha256"]
            or mode != int(item["mode"], 8)
        ):
            raise PlanError("Staged file verification failed.")


def build_stage(source, unit_source, config_data, parent):
    source = source_directory(source)
    unit_source = source_directory(unit_source)
    parent = source_directory(parent)

    info = parent.stat()

    if (
        info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise PlanError("Private staging directory required.")

    plan = build_plan(source, config_data)

    stage = Path(tempfile.mkdtemp(
        prefix="grotaxe-stage-",
        dir=parent,
    ))

    try:
        for item in plan["directories"]:
            path = target(stage, item["path"])

            make_stage_directory(
                stage,
                path,
                mode=int(item["mode"], 8),
            )

        records = []

        for item in plan["payload"]:
            data, _ = read_regular(
                source / item["module"]
            )

            if digest(data) != item["sha256"]:
                raise PlanError("Source payload changed.")

            records.append(put_file(
                stage,
                item["destination"],
                data,
                0o644,
            ))

        for destination, module in LAUNCHERS.items():
            records.append(put_file(
                stage,
                destination,
                launcher(module),
                0o755,
            ))

        for name in UNITS:
            data, _ = read_regular(
                unit_source / name
            )

            records.append(put_file(
                stage,
                UNIT_DIR + "/" + name,
                data,
                0o644,
            ))

        config_record = put_file(
            stage,
            CONFIG_DIR + "/config.toml",
            config_data,
            0o600,
        )

        manifest = {
            "manifest_version": 1,
            "product": "GROTAXE SMART MOUNT",
            "files": records,
            "configuration": {
                "path": CONFIG_DIR + "/config.toml",
                "mode": "0600",
                "preserve_on_uninstall": True,
            },
            "activation": False,
        }

        manifest_data = (
            json.dumps(
                manifest,
                indent=2,
                sort_keys=True,
            ) + "\n"
        ).encode("utf-8")

        manifest_record = put_file(
            stage,
            MANIFEST,
            manifest_data,
            0o644,
        )

        verify_files(
            stage,
            records + [config_record, manifest_record],
        )

        return stage, manifest

    except BaseException:
        shutil.rmtree(stage)
        raise
