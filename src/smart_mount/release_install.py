"""Unified installation entry point."""

import argparse
import json
import os
import stat
import subprocess
import tempfile

from pathlib import Path

from .install_plan import (
    PREFIX,
    CONFIG_DIR,
    UNIT_DIR,
    MODULES,
    PlanError,
)

from .stage_install import (
    MANIFEST,
    UNITS,
    build_stage,
    digest,
    read_regular,
    target,
)

from .config import ConfigError
from .terminal import Terminal
from .trusted_config import (
    decode_config,
    load_trusted_config,
)


REPOSITORY = Path(__file__).resolve().parents[2]
CONFIG_PATH = CONFIG_DIR + "/config.toml"

SHARED_DIRECTORIES = (
    "/opt",
    "/etc",
    "/etc/systemd",
    UNIT_DIR,
    "/usr",
    "/usr/local",
    "/usr/local/bin",
)

PRIVATE_DIRECTORIES = (
    (PREFIX, 0o755),
    (PREFIX + "/smart_mount", 0o755),
    (CONFIG_DIR, 0o700),
)


def safe_directory(path):
    info = path.lstat()

    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise PlanError("Unsafe installation directory.")


def trusted_source(path):
    path = Path(path)

    if not path.is_absolute() or path.resolve() != path:
        raise PlanError("Invalid trusted source path.")

    for directory in reversed(path.parents):
        safe_directory(directory)

    if path.is_dir():
        safe_directory(path)
        return

    info = path.lstat()

    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise PlanError("Untrusted installation source.")


def deploy(stage, manifest, root, config_data):
    """Install an already validated image without overwriting files."""

    root = Path(root)

    if not root.is_absolute() or root.resolve() != root:
        raise PlanError("Invalid destination root.")

    safe_directory(root)

    for directory in SHARED_DIRECTORIES:
        safe_directory(target(root, directory))

    records = []

    for item in manifest["files"]:
        data, mode = read_regular(
            target(stage, item["path"])
        )

        if (
            digest(data) != item["sha256"]
            or mode != int(item["mode"], 8)
        ):
            raise PlanError("Installation payload changed.")

        records.append((item["path"], data, mode))

    data, mode = read_regular(
        target(stage, CONFIG_PATH)
    )

    if data != config_data or mode != 0o600:
        raise PlanError("Configuration changed.")

    from .runtime_entry import protection_policy

    protection_policy(decode_config(data))
    records.append((CONFIG_PATH, data, mode))

    data, mode = read_regular(
        target(stage, MANIFEST)
    )

    if json.loads(data) != manifest or mode != 0o644:
        raise PlanError("Installation manifest changed.")

    records.append((MANIFEST, data, mode))

    # Refuse existing installations and foreign files.
    for directory, _ in PRIVATE_DIRECTORIES:
        if os.path.lexists(target(root, directory)):
            raise PlanError("Installation directory already exists.")

    for destination, _, _ in records:
        if os.path.lexists(target(root, destination)):
            raise PlanError("Installation file already exists.")

    created_files = []
    created_dirs = []

    try:
        for directory, mode in PRIVATE_DIRECTORIES:
            path = target(root, directory)

            path.mkdir(mode=mode)
            created_dirs.append(path)
            path.chmod(mode)

        for destination, data, mode in records:
            path = target(root, destination)

            fd = os.open(
                path,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_NOFOLLOW
                | os.O_CLOEXEC,
                mode,
            )

            created_files.append(path)

            with os.fdopen(fd, "wb") as handle:
                os.fchmod(handle.fileno(), mode)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())

        # Validate the resulting installation.
        for destination, expected, mode in records:
            actual, actual_mode = read_regular(
                target(root, destination)
            )

            if actual != expected or actual_mode != mode:
                raise PlanError("Installed file verification failed.")

    except BaseException:
        for path in reversed(created_files):
            path.unlink(missing_ok=True)

        for path in reversed(created_dirs):
            path.rmdir()

        raise

    return len(records)


def check_installation(config_data, ui):
    if os.geteuid() == 0:
        raise PlanError("Run installation checks unprivileged.")

    with tempfile.TemporaryDirectory(
        prefix="smart-mount-release-"
    ) as temporary:

        parent = Path(temporary).resolve()

        stage, manifest = build_stage(
            REPOSITORY / "src/smart_mount",
            REPOSITORY / "packaging/systemd",
            config_data,
            parent,
        )

        root = parent / "root"
        root.mkdir(mode=0o700)

        for directory in SHARED_DIRECTORIES:
            path = target(root, directory)
            path.mkdir(mode=0o755)
            path.chmod(0o755)

        count = deploy(
            stage, manifest, root, config_data
        )

        ui.status(True, "Unified installation verified")
        ui.field("INSTALLED FILES", count)

        try:
            deploy(stage, manifest, root, config_data)
        except PlanError:
            ui.status(True, "Existing installation protected")
        else:
            raise PlanError("Overwrite protection failed.")

        result = subprocess.run(
            [
                "/usr/bin/python3", "-I", "-B", "-c",
                "import sys; "
                "sys.path.insert(0, sys.argv.pop(1)); "
                "from smart_mount.cli import main; "
                "raise SystemExit(main())",
                str(target(root, PREFIX)),
                "--json", "about",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
            cwd="/",
        )

        if not json.loads(result.stdout)["ok"]:
            raise PlanError("Installed CLI verification failed.")

        ui.status(True, "Installed CLI operational")

        subprocess.run(
            [
                "/usr/bin/systemd-analyze", "verify",
                *[
                    str(target(root, UNIT_DIR + "/" + unit))
                    for unit in UNITS
                ],
            ],
            capture_output=True,
            check=True,
            timeout=60,
        )

        ui.status(True, "Installed systemd templates verified")

    ui.status(True, "Temporary installation removed")
    ui.field("SYSTEM CHANGES", "none")


def install_system(config_path, ui):
    if os.geteuid() != 0:
        raise PlanError("System installation requires root.")

    source = REPOSITORY / "src/smart_mount"
    units = REPOSITORY / "packaging/systemd"

    for directory in (REPOSITORY, source, units):
        trusted_source(directory)

    for name in (
        *MODULES,
        "install_plan.py",
        "stage_install.py",
        "release_install.py",
    ):
        trusted_source(source / name)

    for unit in UNITS:
        trusted_source(units / unit)

    config_path = Path(config_path)

    expected = load_trusted_config(config_path)
    data, mode = read_regular(config_path)

    if mode != 0o600 or decode_config(data) != expected:
        raise PlanError("Untrusted configuration.")

    with tempfile.TemporaryDirectory(
        prefix="smart-mount-install-",
        dir="/run",
    ) as temporary:

        stage, manifest = build_stage(
            source, units, data, Path(temporary)
        )

        count = deploy(
            stage, manifest, Path("/"), data
        )

    ui.field("INSTALLED FILES", count)
    ui.field("SERVICE ACTIVATION", "disabled")
    ui.status(True, "Installation complete")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="GROTAXE SMART MOUNT Installer"
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--install", action="store_true")

    parser.add_argument("--config")

    args = parser.parse_args(argv)
    ui = Terminal()

    ui.banner("INSTALLATION WIZARD")
    ui.heading("INSTALLATION")

    try:
        if args.check:
            path = Path(args.config) if args.config else (
                REPOSITORY / "examples/smart-mount.toml"
            )

            data, _ = read_regular(path)
            check_installation(data, ui)

        else:
            if not args.config:
                raise PlanError("Trusted configuration required.")

            install_system(args.config, ui)

    except (
        PlanError,
        ConfigError,
        OSError,
        ValueError,
        subprocess.SubprocessError,
    ):
        ui.status(False, "Installation failed safely.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
