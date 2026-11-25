"""Read-only validation inside the current mount namespace."""

import stat
from pathlib import Path, PurePosixPath

from .identity import MountError, check, mount_at


def _canonical_directory(value):
    path = Path(value)

    try:
        if (
            not path.is_absolute()
            or path.resolve(strict=True) != path
            or not path.is_dir()
        ):
            raise MountError("Invalid canonical directory.")
    except (OSError, RuntimeError) as exc:
        raise MountError("Cannot validate directory.") from exc

    return path


def _directory_identity(path):
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise MountError("Cannot inspect directory.") from exc

    if not stat.S_ISDIR(info.st_mode):
        raise MountError("Expected a directory.")

    return info.st_dev, info.st_ino


def _check_marker(path, marker):
    try:
        info = (path / marker).stat(follow_symlinks=False)
    except OSError as exc:
        raise MountError("Required storage marker is missing.") from exc

    if not stat.S_ISREG(info.st_mode):
        raise MountError("Storage marker is not a regular file.")


def check_bind(
    source,
    destination,
    uuid,
    *,
    source_mount,
    source_mode="ro",
    destination_mode="rw",
    fstype=None,
    marker=None,
):
    """Validate source and bind target in the current namespace."""

    source = _canonical_directory(source)
    destination = _canonical_directory(destination)
    source_mount = _canonical_directory(source_mount)

    if source == destination:
        raise MountError("Source and destination must differ.")

    try:
        relative = source.relative_to(source_mount)
    except ValueError as exc:
        raise MountError("Source is outside the expected mount.") from exc

    if marker is not None:
        if (
            not isinstance(marker, str)
            or not marker
            or marker in {".", ".."}
            or Path(marker).name != marker
        ):
            raise MountError("Invalid storage marker name.")

    origin = check(
        source_mount,
        uuid,
        mode=source_mode,
        fstype=fstype,
    )

    actual_source = mount_at(source, mode=source_mode)

    if actual_source != origin:
        raise MountError("Unexpected nested source mount.")

    root = PurePosixPath(origin["fsroot"])

    if not root.is_absolute():
        raise MountError("Invalid filesystem root.")

    expected_root = str(root / relative.as_posix())

    target = check(
        destination,
        uuid,
        mode=destination_mode,
        fstype=origin["fstype"],
        fsroot=expected_root,
    )

    if _directory_identity(source) != _directory_identity(destination):
        raise MountError("Bind directory identity mismatch.")

    if marker is not None:
        _check_marker(source, marker)
        _check_marker(destination, marker)

    return {
        "source": str(source),
        "destination": str(destination),
        "uuid": target["uuid"],
        "fstype": target["fstype"],
        "fsroot": target["fsroot"],
        "source_mode": source_mode,
        "destination_mode": destination_mode,
        "verified": True,
    }
