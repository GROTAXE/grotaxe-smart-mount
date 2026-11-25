import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from smart_mount.process_namespace import (
    NamespaceError,
    access,
    directory_at,
    exact_mount,
    opened,
    DIR_FLAGS,
    parse_mountinfo,
    start_time,
    verify_mounts,
)

MOUNTINFO = (
    "10 1 8:1 / /mnt/example ro - ext4 /dev/example rw\n"
    "11 1 8:1 /data /srv/example rw - ext4 /dev/example rw\n"
)


class ProcessNamespaceTests(unittest.TestCase):

    def setUp(self):
        self.entries = parse_mountinfo(MOUNTINFO)

        self.volume = {
            "target": "/mnt/example",
            "fsroot": "/",
        }

        self.policy = {
            "source": "/mnt/example/data",
            "destination": "/srv/example",
            "source_mode": "ro",
            "destination_mode": "rw",
        }

    def verify(self):
        verify_mounts(
            self.entries,
            self.policy,
            self.volume,
            (8, 1),
            "ext4",
        )

    def test_valid_topology(self):
        self.verify()

    def test_invalid_mountinfo(self):
        with self.assertRaises(NamespaceError):
            parse_mountinfo("invalid")

    def test_empty_mountinfo(self):
        with self.assertRaises(NamespaceError):
            parse_mountinfo("")

    def test_escaped_paths(self):
        entries = parse_mountinfo(
            r"10 1 8:1 / /mnt/example\040disk rw"
            " - ext4 /dev/example rw"
        )

        self.assertEqual(
            entries[0].target,
            "/mnt/example disk",
        )

    def test_duplicate_mountpoint(self):
        self.entries.append(self.entries[0])

        with self.assertRaises(NamespaceError):
            self.verify()

    def test_device_mismatch(self):
        self.entries[1] = replace(
            self.entries[1], device=(8, 2)
        )

        with self.assertRaises(NamespaceError):
            self.verify()

    def test_root_mismatch(self):
        self.entries[1] = replace(
            self.entries[1], root="/other"
        )

        with self.assertRaises(NamespaceError):
            self.verify()

    def test_access_mismatch(self):
        self.entries[1] = replace(
            self.entries[1], options=frozenset({"ro"})
        )

        with self.assertRaises(NamespaceError):
            self.verify()

    def test_readonly_superblock(self):
        entry = replace(
            self.entries[1],
            fs_options=frozenset({"ro"}),
        )

        with self.assertRaises(NamespaceError):
            access(entry, "rw")

    def test_nested_mount(self):
        self.entries.append(replace(
            self.entries[0],
            target="/mnt/example/data/nested",
        ))

        with self.assertRaises(NamespaceError):
            self.verify()

    def test_process_starttime(self):
        fields = [b"S"] + [b"0"] * 18 + [b"12345"]
        data = b"100 (example process) " + b" ".join(fields)

        self.assertEqual(start_time(data), 12345)

    def test_opaque_unrelated_mount(self):
        self.entries.extend(parse_mountinfo(
            "12 1 0:42 net:[12345] /run/example-ns "
            "rw - nsfs nsfs rw"
        ))

        self.assertEqual(self.entries[-1].root, "net:[12345]")
        self.verify()

    def test_opaque_protected_source_rejected(self):
        self.entries[0] = replace(
            self.entries[0], root="opaque:[12345]"
        )

        with self.assertRaises(NamespaceError):
            self.verify()

    def test_opaque_protected_target_rejected(self):
        self.entries[1] = replace(
            self.entries[1], root="opaque:[12345]"
        )

        with self.assertRaises(NamespaceError):
            self.verify()

    def test_nonabsolute_mountpoint_rejected(self):
        with self.assertRaises(NamespaceError):
            parse_mountinfo(
                "12 1 0:42 / invalid-target rw - nsfs nsfs rw"
            )

    def test_directory_symlink_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "real").mkdir()
            (root / "alias").symlink_to("real")

            with opened(root, DIR_FLAGS) as fd:
                with self.assertRaises(OSError):
                    with directory_at(fd, "/alias"):
                        pass


if __name__ == "__main__":
    unittest.main()
