"""Locked, boot-scoped runtime recovery state."""

import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat

from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .identity import MountError, UUID_PATTERN
from .recovery import RecoveryState


STATE_FILE = "state.json"
LOCK_FILE = "runtime.lock"
INHIBIT_FILE = "recovery.disabled"
MAX_SIZE = 1024 * 1024
STATE_VERSION = 1


class StateError(MountError):
    """Unsafe or invalid runtime state."""


class LockBusy(StateError):
    """Another runtime operation holds the lock."""


def require(condition, message):
    if not condition:
        raise StateError(message)


def encode(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def config_fingerprint(config):
    return hashlib.sha256(encode(config)).hexdigest()


def current_boot_id():
    try:
        value = Path(
            "/proc/sys/kernel/random/boot_id"
        ).read_text().strip()
    except OSError as exc:
        raise StateError("Cannot identify current boot.") from exc

    return validate_boot_id(value)


def validate_boot_id(value):
    require(
        isinstance(value, str)
        and re.fullmatch(UUID_PATTERN, value),
        "Invalid boot identity.",
    )
    return value.lower()


def validate_directory(fd):
    info = os.fstat(fd)

    require(
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o700,
        "Unsafe runtime directory permissions.",
    )


def validate_file(fd):
    info = os.fstat(fd)

    require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.geteuid()
        and info.st_nlink == 1
        and stat.S_IMODE(info.st_mode) == 0o600,
        "Unsafe runtime file permissions or identity.",
    )


def reject_duplicate_keys(items):
    result = {}

    for key, value in items:
        require(key not in result, "Duplicate state key.")
        result[key] = value

    return result


class StateStore:

    def __init__(self, fd, config, boot_id):
        self._fd = fd
        self.fingerprint = config_fingerprint(config)
        self.boot_id = validate_boot_id(boot_id)
        self.groups = {
            group["name"]: tuple(group["units"])
            for group in config["groups"]
        }

    def _require_lock(self):
        require(
            self._fd is not None,
            "Runtime state lock is not held.",
        )

    def recovery_inhibited(self):
        self._require_lock()

        try:
            os.stat(
                INHIBIT_FILE,
                dir_fd=self._fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return False

        return True

    def inhibit_recovery(self):
        """Persist a fail-closed recovery latch."""

        self._require_lock()

        try:
            fd = os.open(
                INHIBIT_FILE,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_NOFOLLOW
                | os.O_CLOEXEC,
                0o600,
                dir_fd=self._fd,
            )
        except FileExistsError:
            return

        try:
            os.fsync(fd)
        finally:
            os.close(fd)

        os.fsync(self._fd)

    def _validate_states(self, raw):
        require(type(raw) is dict, "Invalid group state.")

        result = {}

        for name, value in raw.items():
            require(name in self.groups, "Unknown state group.")

            require(
                type(value) is dict
                and set(value) == {
                    "pending",
                    "confirmations",
                    "last_success",
                },
                "Invalid recovery state fields.",
            )

            pending = value["pending"]
            count = value["confirmations"]
            last = value["last_success"]

            require(
                type(pending) is list
                and all(type(unit) is str for unit in pending),
                "Invalid pending services.",
            )

            expected = [
                unit for unit in self.groups[name]
                if unit in pending
            ]

            require(
                pending == expected,
                "Invalid pending service identity or order.",
            )

            require(
                type(count) is int and 0 <= count <= 10,
                "Invalid confirmation count.",
            )

            require(
                (
                    count == 0 and last is None
                ) or (
                    count > 0
                    and type(last) in (int, float)
                    and 0 <= last <= 10**15
                ),
                "Invalid confirmation timestamp.",
            )

            require(
                bool(pending) or count == 0,
                "Confirmation without recovery authorization.",
            )

            result[name] = RecoveryState(
                pending=tuple(pending),
                confirmations=count,
                last_success=last,
            )

        return result

    def _open_existing(self):
        self._require_lock()

        try:
            fd = os.open(
                STATE_FILE,
                os.O_RDONLY
                | os.O_NOFOLLOW
                | os.O_NONBLOCK
                | os.O_CLOEXEC,
                dir_fd=self._fd,
            )
        except FileNotFoundError:
            return None

        try:
            validate_file(fd)
        except BaseException:
            os.close(fd)
            raise

        return fd

    def load(self):
        fd = self._open_existing()

        if fd is None:
            return {}

        with os.fdopen(fd, "rb") as handle:
            data = handle.read(MAX_SIZE + 1)

        require(len(data) <= MAX_SIZE, "State too large.")

        try:
            raw = json.loads(
                data,
                object_pairs_hook=reject_duplicate_keys,
            )
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise StateError("Invalid runtime state.") from exc

        require(
            type(raw) is dict
            and set(raw) == {
                "version",
                "boot_id",
                "config",
                "groups",
            },
            "Invalid state schema.",
        )

        require(
            type(raw["version"]) is int
            and raw["version"] == STATE_VERSION,
            "Unsupported state version.",
        )

        require(
            isinstance(raw["config"], str)
            and re.fullmatch(r"[a-f0-9]{64}", raw["config"]),
            "Invalid configuration fingerprint.",
        )

        if (
            validate_boot_id(raw["boot_id"]) != self.boot_id
            or raw["config"] != self.fingerprint
        ):
            return {}

        return self._validate_states(raw["groups"])

    def save(self, states):
        self._require_lock()

        require(
            type(states) is dict
            and all(
                isinstance(value, RecoveryState)
                for value in states.values()
            ),
            "Invalid recovery state objects.",
        )

        groups = {
            name: asdict(value)
            for name, value in states.items()
        }

        for value in groups.values():
            value["pending"] = list(value["pending"])

        self._validate_states(groups)

        payload = encode({
            "version": STATE_VERSION,
            "boot_id": self.boot_id,
            "config": self.fingerprint,
            "groups": groups,
        })

        require(len(payload) <= MAX_SIZE, "State too large.")

        existing = self._open_existing()

        if existing is not None:
            os.close(existing)

        temporary = ".state-" + secrets.token_hex(16)

        fd = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | os.O_CLOEXEC,
            0o600,
            dir_fd=self._fd,
        )

        try:
            with os.fdopen(fd, "wb") as handle:
                os.fchmod(handle.fileno(), 0o600)
                validate_file(handle.fileno())

                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(
                temporary,
                STATE_FILE,
                src_dir_fd=self._fd,
                dst_dir_fd=self._fd,
            )

            os.fsync(self._fd)

        finally:
            try:
                os.unlink(temporary, dir_fd=self._fd)
            except FileNotFoundError:
                pass


@contextmanager
def locked_state(directory, config, *, boot_id=None):
    """Open an existing private directory under a trusted parent."""

    directory_fd = os.open(
        directory,
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | os.O_CLOEXEC,
    )

    try:
        validate_directory(directory_fd)

        lock_fd = os.open(
            LOCK_FILE,
            os.O_RDWR
            | os.O_CREAT
            | os.O_NOFOLLOW
            | os.O_NONBLOCK
            | os.O_CLOEXEC,
            0o600,
            dir_fd=directory_fd,
        )

        try:
            validate_file(lock_fd)

            try:
                fcntl.flock(
                    lock_fd,
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
            except OSError as exc:
                if exc.errno in (errno.EAGAIN, errno.EACCES):
                    raise LockBusy("Runtime lock is busy.") from exc
                raise

            store = StateStore(
                directory_fd,
                config,
                current_boot_id() if boot_id is None else boot_id,
            )

            try:
                yield store
            finally:
                store._fd = None

        finally:
            os.close(lock_fd)

    finally:
        os.close(directory_fd)
