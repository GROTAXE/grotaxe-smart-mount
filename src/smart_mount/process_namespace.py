"""Read-only mount namespace inspection through Linux procfs."""

import os
import re
import stat

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath

from .identity import MountError, check, mount_at
from .systemd import SystemdAdapter


class NamespaceError(MountError):
    """Unable to establish process mount identity."""


@dataclass(frozen=True)
class MountEntry:
    device: tuple
    root: str
    target: str
    options: frozenset
    fstype: str
    fs_options: frozenset


def unescape(value):
    escapes = {
        "040": " ",
        "011": "\t",
        "012": "\n",
        "134": "\\",
    }

    return re.sub(
        r"\\(040|011|012|134)",
        lambda match: escapes[match.group(1)],
        value,
    )


def parse_mountinfo(text):
    """Parse the kernel mountinfo representation."""

    entries = []

    try:
        for line in text.splitlines():
            left, right = line.split(" - ", 1)
            fields = left.split()
            extra = right.split()

            if len(fields) < 6 or len(extra) != 3:
                raise ValueError("Invalid field count")

            major, minor = map(int, fields[2].split(":"))

            root = unescape(fields[3])
            target = unescape(fields[4])

            if (
                major < 0
                or minor < 0
                or not root
                or not target.startswith("/")
            ):
                raise ValueError("Invalid mount identity")

            entries.append(MountEntry(
                device=(major, minor),
                root=root,
                target=target,
                options=frozenset(fields[5].split(",")),
                fstype=extra[0],
                fs_options=frozenset(extra[2].split(",")),
            ))

    except (ValueError, IndexError) as exc:
        raise NamespaceError("Invalid mountinfo.") from exc

    if not entries:
        raise NamespaceError("Empty mountinfo.")

    return entries


def beneath(path, parent):
    return PurePosixPath(path).is_relative_to(
        PurePosixPath(parent)
    )


def exact_mount(entries, path):
    matches = [
        entry for entry in entries
        if entry.target == path
    ]

    if len(matches) != 1:
        raise NamespaceError(
            "Missing or ambiguous mountpoint."
        )

    return matches[0]


def access(entry, mode):
    if mode == "ro":
        valid = (
            "ro" in entry.options
            and "rw" not in entry.options
        )
    elif mode == "rw":
        valid = (
            "rw" in entry.options
            and "ro" not in entry.options
            and "rw" in entry.fs_options
            and "ro" not in entry.fs_options
        )
    else:
        valid = False

    if not valid:
        raise NamespaceError("Mount access policy mismatch.")


def verify_mounts(entries, policy, volume, device, fstype):
    """Validate namespace mount topology."""

    source = policy["source"]
    destination = policy["destination"]
    mountpoint = volume["target"]

    if not beneath(source, mountpoint):
        raise NamespaceError("Source outside expected volume.")

    origin = exact_mount(entries, mountpoint)
    target = exact_mount(entries, destination)

    if (
        origin.device != device
        or target.device != device
        or origin.fstype != fstype
        or target.fstype != fstype
    ):
        raise NamespaceError("Mount device or type mismatch.")

    if not origin.root.startswith("/") or not target.root.startswith("/"):
        raise NamespaceError("Unsupported protected filesystem root.")

    if origin.root != volume["fsroot"]:
        raise NamespaceError("Source filesystem root mismatch.")

    relative = PurePosixPath(source).relative_to(mountpoint)
    expected_root = str(PurePosixPath(origin.root) / relative)

    if target.root != expected_root:
        raise NamespaceError("Bind filesystem root mismatch.")

    for entry in entries:
        if (
            entry.target != mountpoint
            and beneath(entry.target, mountpoint)
            and beneath(source, entry.target)
        ):
            raise NamespaceError("Nested source mount.")

        if (
            entry.target != source
            and beneath(entry.target, source)
        ):
            raise NamespaceError("Nested source subtree mount.")

        if (
            entry.target != destination
            and beneath(entry.target, destination)
        ):
            raise NamespaceError("Nested bind target mount.")

    access(origin, policy["source_mode"])
    access(target, policy["destination_mode"])


@contextmanager
def opened(path, flags, *, dir_fd=None):
    fd = os.open(
        path,
        flags | os.O_CLOEXEC,
        dir_fd=dir_fd,
    )

    try:
        yield fd
    finally:
        os.close(fd)


DIR_FLAGS = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW


@contextmanager
def directory_at(root_fd, path):
    """Walk directory components without following symlinks."""

    path = PurePosixPath(path)

    if not path.is_absolute() or ".." in path.parts:
        raise NamespaceError("Invalid directory path.")

    current = os.dup(root_fd)

    try:
        for part in path.parts[1:]:
            next_fd = os.open(
                part,
                DIR_FLAGS | os.O_CLOEXEC,
                dir_fd=current,
            )

            os.close(current)
            current = next_fd

        yield current

    finally:
        os.close(current)


def inode(info):
    return info.st_dev, info.st_ino


def device_number(info):
    return os.major(info.st_dev), os.minor(info.st_dev)


def read_proc(proc_fd, name, limit):
    with opened(
        name,
        os.O_RDONLY | os.O_NOFOLLOW,
        dir_fd=proc_fd,
    ) as fd:
        chunks = []
        remaining = limit + 1

        while remaining:
            data = os.read(fd, min(65536, remaining))

            if not data:
                break

            chunks.append(data)
            remaining -= len(data)

        result = b"".join(chunks)

    if len(result) > limit:
        raise NamespaceError("Procfs response too large.")

    return result


def start_time(data):
    try:
        fields = data.rsplit(b")", 1)[1].split()
        value = int(fields[19])

        if value < 0:
            raise ValueError

        return value

    except (ValueError, IndexError) as exc:
        raise NamespaceError("Invalid process identity.") from exc


def snapshot(proc_fd):
    return (
        start_time(read_proc(proc_fd, "stat", 65536)),
        inode(os.stat("ns/mnt", dir_fd=proc_fd)),
        inode(os.stat("root", dir_fd=proc_fd)),
        read_proc(proc_fd, "mountinfo", 8 * 1024 * 1024),
    )


def check_marker(fd, marker):
    if (
        not isinstance(marker, str)
        or not marker
        or marker in {".", ".."}
        or "/" in marker
    ):
        raise NamespaceError("Invalid marker name.")

    info = os.stat(
        marker,
        dir_fd=fd,
        follow_symlinks=False,
    )

    if not stat.S_ISREG(info.st_mode):
        raise NamespaceError("Invalid storage marker.")


def verify_directories(host_fd, process_fd, policy, device):
    source = policy["source"]
    destination = policy["destination"]
    marker = policy.get("marker")

    with directory_at(host_fd, source) as host_source:
        with directory_at(process_fd, source) as process_source:
            with directory_at(
                process_fd, destination
            ) as process_target:

                descriptors = (
                    host_source,
                    process_source,
                    process_target,
                )

                identities = [
                    os.fstat(fd) for fd in descriptors
                ]

                if any(
                    device_number(info) != device
                    for info in identities
                ):
                    raise NamespaceError(
                        "Directory device mismatch."
                    )

                if len({
                    inode(info) for info in identities
                }) != 1:
                    raise NamespaceError(
                        "Directory inode mismatch."
                    )

                if marker is not None:
                    for fd in descriptors:
                        check_marker(fd, marker)


class ProcessNamespaceAdapter:

    def __init__(self, systemd=None):
        self.systemd = systemd or SystemdAdapter()

    def verify_bind(self, unit, policy, volume):
        """Validate a service bind policy without setns."""

        try:
            pid = self.systemd.main_pid(unit)

            if type(pid) is not int or pid <= 0:
                raise NamespaceError("Invalid process PID.")

            host_identity = check(
                volume["target"],
                volume["uuid"],
                mode=volume["mode"],
                fstype=volume["fstype"],
                fsroot=volume["fsroot"],
            )

            if mount_at(
                policy["source"],
                mode=volume["mode"],
            ) != host_identity:
                raise NamespaceError(
                    "Unexpected host source mount."
                )

            proc_path = f"/proc/{pid}"

            with opened(
                proc_path,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            ) as proc_fd:

                before = snapshot(proc_fd)

                with opened("/", DIR_FLAGS) as host_fd:
                    with opened(
                        "root",
                        os.O_PATH | os.O_DIRECTORY,
                        dir_fd=proc_fd,
                    ) as process_fd:

                        if inode(os.fstat(process_fd)) != before[2]:
                            raise NamespaceError(
                                "Process root changed."
                            )

                        with directory_at(
                            host_fd, volume["target"]
                        ) as volume_fd:
                            device = device_number(
                                os.fstat(volume_fd)
                            )

                        entries = parse_mountinfo(
                            os.fsdecode(before[3])
                        )

                        verify_mounts(
                            entries,
                            policy,
                            volume,
                            device,
                            host_identity["fstype"],
                        )

                        verify_directories(
                            host_fd,
                            process_fd,
                            policy,
                            device,
                        )

                if snapshot(proc_fd) != before:
                    raise NamespaceError(
                        "Process mount state changed."
                    )

                if (
                    inode(os.stat(proc_path))
                    != inode(os.fstat(proc_fd))
                    or self.systemd.main_pid(unit) != pid
                ):
                    raise NamespaceError(
                        "Service process changed."
                    )

            return True

        except OSError as exc:
            raise NamespaceError(
                "Cannot inspect process namespace."
            ) from exc
