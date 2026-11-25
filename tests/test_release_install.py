import os
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from smart_mount.config import ConfigError
from smart_mount.install_plan import (
    PREFIX,
    CONFIG_DIR,
    UNIT_DIR,
    PlanError,
)
from smart_mount.release_install import (
    SHARED_DIRECTORIES,
    deploy,
    install_system,
)
from smart_mount.stage_install import (
    build_stage,
    target,
    UNITS,
)


ROOT = Path(__file__).resolve().parents[1]


class ReleaseInstallTests(unittest.TestCase):

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)

        self.parent = Path(temporary.name).resolve()
        self.root = self.parent / "destination"
        self.root.mkdir(mode=0o700)

        for directory in SHARED_DIRECTORIES:
            path = target(self.root, directory)
            path.mkdir(mode=0o755)
            path.chmod(0o755)

        self.data = (
            ROOT / "examples/smart-mount.toml"
        ).read_bytes()

        self.stage, self.manifest = self.build(self.data)

    def build(self, data):
        return build_stage(
            ROOT / "src/smart_mount",
            ROOT / "packaging/systemd",
            data,
            self.parent,
        )

    def deploy(self):
        return deploy(
            self.stage,
            self.manifest,
            self.root,
            self.data,
        )

    def assert_no_installation(self):
        self.assertFalse(
            target(self.root, PREFIX).exists()
        )
        self.assertFalse(
            target(self.root, CONFIG_DIR).exists()
        )

    def test_foreign_file_preserved(self):
        foreign = target(
            self.root,
            UNIT_DIR + "/" + UNITS[0],
        )

        foreign.write_text("Synthetic existing file")

        with self.assertRaises(PlanError):
            self.deploy()

        self.assertEqual(
            foreign.read_text(),
            "Synthetic existing file",
        )

        self.assert_no_installation()

    def test_symlink_directory_rejected(self):
        path = target(self.root, "/usr/local/bin")
        path.rmdir()

        foreign = self.parent / "foreign"
        foreign.mkdir()
        path.symlink_to(foreign)

        with self.assertRaises(PlanError):
            self.deploy()

        self.assertEqual(list(foreign.iterdir()), [])
        self.assert_no_installation()

    def test_modified_payload_rejected(self):
        path = target(
            self.stage,
            self.manifest["files"][0]["path"],
        )

        path.write_text("# Modified")

        with self.assertRaises(PlanError):
            self.deploy()

        self.assert_no_installation()

    def test_write_failure_rolls_back(self):
        with patch(
            "smart_mount.release_install.os.fsync",
            side_effect=OSError("Synthetic write failure"),
        ):
            with self.assertRaises(OSError):
                self.deploy()

        self.assert_no_installation()

        self.assertEqual(
            list(target(self.root, UNIT_DIR).iterdir()),
            [],
        )

        self.assertEqual(
            list(target(
                self.root, "/usr/local/bin"
            ).iterdir()),
            [],
        )

    def test_self_management_rejected(self):
        data = self.data.replace(
            b"example-api.service",
            b"grotaxe-smart-mount.service",
        )

        self.assertNotEqual(data, self.data)

        stage, manifest = self.build(data)

        with self.assertRaises(ConfigError):
            deploy(stage, manifest, self.root, data)

        self.assert_no_installation()

    def test_unprivileged_system_install_rejected(self):
        with patch(
            "smart_mount.release_install.os.geteuid",
            return_value=1000,
        ):
            with self.assertRaises(PlanError):
                install_system("/example.toml", None)


if __name__ == "__main__":
    unittest.main()
