"""Root-owned configuration loading for privileged operation."""

import os
import stat
import tomllib

from pathlib import PurePosixPath

from .config import ConfigError, path_value, validate


MAX_SIZE = 1024 * 1024

DIR_FLAGS = (
    os.O_RDONLY
    | os.O_DIRECTORY
    | os.O_NOFOLLOW
    | os.O_CLOEXEC
)


def check_metadata(info, *, directory):
    if info.st_uid != 0:
        raise ConfigError("Configuration path is not root-owned.")

    mode = stat.S_IMODE(info.st_mode)

    if directory:
        if not stat.S_ISDIR(info.st_mode) or mode & 0o022:
            raise ConfigError("Unsafe configuration directory.")
    else:
        if (
            not stat.S_ISREG(info.st_mode)
            or mode != 0o600
            or info.st_nlink != 1
        ):
            raise ConfigError("Unsafe configuration file.")


def fingerprint(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def decode_config(data):
    if len(data) > MAX_SIZE:
        raise ConfigError("Configuration too large.")

    try:
        return validate(tomllib.loads(data.decode("utf-8")))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError("Invalid TOML configuration.") from exc


def load_trusted_config(value):
    """Reject symlinks and untrusted parent directories."""

    path = PurePosixPath(path_value(str(value)))

    if len(path.parts) < 2:
        raise ConfigError("Expected a configuration file.")

    try:
        current = os.open("/", DIR_FLAGS)

        try:
            check_metadata(
                os.fstat(current), directory=True
            )

            for part in path.parts[1:-1]:
                next_fd = os.open(
                    part,
                    DIR_FLAGS,
                    dir_fd=current,
                )

                os.close(current)
                current = next_fd

                check_metadata(
                    os.fstat(current), directory=True
                )

            fd = os.open(
                path.name,
                os.O_RDONLY
                | os.O_NOFOLLOW
                | os.O_NONBLOCK
                | os.O_CLOEXEC,
                dir_fd=current,
            )

            with os.fdopen(fd, "rb") as handle:
                before = os.fstat(handle.fileno())
                check_metadata(before, directory=False)

                data = handle.read(MAX_SIZE + 1)

                after = os.fstat(handle.fileno())
                check_metadata(after, directory=False)

                if fingerprint(before) != fingerprint(after):
                    raise ConfigError("Configuration changed.")

        finally:
            os.close(current)

    except OSError as exc:
        raise ConfigError(
            "Cannot open trusted configuration."
        ) from exc

    return decode_config(data)
