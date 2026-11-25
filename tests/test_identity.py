import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_mount.identity import check, MountError

UUID = "11111111-2222-3333-4444-555555555555"


class IdentityTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.path = Path(self.temp.name).resolve()

        self.entry = {
            "target": str(self.path),
            "uuid": UUID,
            "fstype": "ext4",
            "fsroot": "/",
            "vfs-options": "rw,noatime",
            "fs-options": "rw",
        }

    def verify(self, **kwargs):
        response = subprocess.CompletedProcess(
            [], 0,
            stdout=json.dumps({"filesystems": [self.entry]}),
        )

        with patch(
            "smart_mount.identity.subprocess.run",
            return_value=response,
        ):
            return check(self.path, UUID, **kwargs)

    def test_findmnt_environment_isolated(self):
        response = subprocess.CompletedProcess(
            [], 0,
            stdout=json.dumps({"filesystems": [self.entry]}),
        )

        with patch(
            "smart_mount.identity.subprocess.run",
            return_value=response,
        ) as runner:
            check(self.path, UUID)

        command = runner.call_args.args[0]
        options = runner.call_args.kwargs

        self.assertEqual(command[0], "/usr/bin/findmnt")
        self.assertEqual(options["cwd"], "/")
        self.assertEqual(
            options["env"],
            {"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )

    def test_valid_mount(self):
        self.assertEqual(self.verify()["uuid"], UUID)

    def test_wrong_uuid(self):
        self.entry["uuid"] = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        with self.assertRaises(MountError):
            self.verify()

    def test_parent_mount_rejected(self):
        self.entry["target"] = "/"
        with self.assertRaises(MountError):
            self.verify()

    def test_readonly_rejected(self):
        self.entry["vfs-options"] = "ro"
        with self.assertRaises(MountError):
            self.verify()

    def test_readonly_policy(self):
        self.entry["vfs-options"] = "ro"
        self.verify(mode="ro")

    def test_writable_mount_rejected_by_ro_policy(self):
        with self.assertRaises(MountError):
            self.verify(mode="ro")

    def test_readonly_superblock(self):
        self.entry["fs-options"] = "ro"
        with self.assertRaises(MountError):
            self.verify()

    def test_filesystem_policy(self):
        with self.assertRaises(MountError):
            self.verify(fstype="xfs")

    def test_fsroot_policy(self):
        self.entry["fsroot"] = "/unexpected"
        with self.assertRaises(MountError):
            self.verify(fsroot="/")

    def test_invalid_response(self):
        del self.entry["vfs-options"]
        with self.assertRaises(MountError):
            self.verify()


if __name__ == "__main__":
    unittest.main()
