import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_mount import namespace
from smart_mount.identity import MountError

UUID = "11111111-2222-3333-4444-555555555555"


class NamespaceTests(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        self.root = Path(temp.name).resolve()
        self.disk = self.root / "disk"
        self.source = self.disk / "payload"
        self.destination = self.root / "alias"

        self.source.mkdir(parents=True)
        self.destination.mkdir()

        self.origin = {
            "target": str(self.disk),
            "uuid": UUID,
            "fstype": "ext4",
            "fsroot": "/",
            "vfs-options": "ro",
            "fs-options": "rw",
        }

        self.target = {
            **self.origin,
            "target": str(self.destination),
            "fsroot": "/payload",
            "vfs-options": "rw",
        }

        self.nested = False

    def findmnt(self, command, **kwargs):
        path = command[command.index("--target") + 1]

        if path == str(self.destination):
            entry = self.target
        elif path == str(self.source) and self.nested:
            entry = {
                **self.origin,
                "target": str(self.source),
            }
        else:
            entry = self.origin

        return subprocess.CompletedProcess(
            command, 0,
            stdout=json.dumps({"filesystems": [entry]}),
        )

    def verify(self, *, mock_inode=True, **kwargs):
        with patch(
            "smart_mount.identity.subprocess.run",
            side_effect=self.findmnt,
        ):
            if mock_inode:
                with patch.object(
                    namespace,
                    "_directory_identity",
                    return_value=(1, 100),
                ):
                    return self.run_check(**kwargs)

            return self.run_check(**kwargs)

    def run_check(self, **kwargs):
        return namespace.check_bind(
            self.source,
            self.destination,
            UUID,
            source_mount=self.disk,
            **kwargs,
        )

    def test_valid_bind(self):
        self.assertTrue(self.verify()["verified"])

    def test_wrong_uuid(self):
        self.target["uuid"] = (
            "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        )
        with self.assertRaises(MountError):
            self.verify()

    def test_wrong_fsroot(self):
        self.target["fsroot"] = "/other"
        with self.assertRaises(MountError):
            self.verify()

    def test_wrong_filesystem(self):
        self.target["fstype"] = "xfs"
        with self.assertRaises(MountError):
            self.verify()

    def test_source_not_readonly(self):
        self.origin["vfs-options"] = "rw"
        with self.assertRaises(MountError):
            self.verify()

    def test_destination_not_writable(self):
        self.target["vfs-options"] = "ro"
        with self.assertRaises(MountError):
            self.verify()

    def test_inode_mismatch(self):
        with self.assertRaises(MountError):
            self.verify(mock_inode=False)

    def test_nested_mount(self):
        self.nested = True
        with self.assertRaises(MountError):
            self.verify()

    def test_missing_marker(self):
        with self.assertRaises(MountError):
            self.verify(marker=".storage-owner")

    def test_valid_marker(self):
        for path in (self.source, self.destination):
            (path / ".storage-owner").touch()

        self.assertTrue(
            self.verify(marker=".storage-owner")["verified"]
        )

    def test_invalid_marker_name(self):
        with self.assertRaises(MountError):
            self.verify(marker="../other")

    def test_symlink_marker(self):
        for path in (self.source, self.destination):
            (path / "regular").touch()
            (path / ".storage-owner").symlink_to("regular")

        with self.assertRaises(MountError):
            self.verify(marker=".storage-owner")


if __name__ == "__main__":
    unittest.main()
