import json
import shutil
import tempfile
import unittest

from pathlib import Path

from smart_mount.install_plan import (
    MODULES,
    PREFIX,
    CONFIG_DIR,
    UNIT_DIR,
    PlanError,
)

from smart_mount.stage_install import (
    MANIFEST,
    LAUNCHERS,
    UNITS,
    build_stage,
    target,
    verify_files,
)


ROOT = Path(__file__).resolve().parents[1]


class StageTests(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        self.root = Path(temp.name).resolve()

        self.source = self.root / "source"
        self.units = self.root / "units"
        self.parent = self.root / "staging"

        shutil.copytree(
            ROOT / "src/smart_mount",
            self.source,
        )

        shutil.copytree(
            ROOT / "packaging/systemd",
            self.units,
        )

        self.parent.mkdir(mode=0o700)

        self.config = (
            ROOT / "examples/smart-mount.toml"
        ).read_bytes()

    def build(self):
        return build_stage(
            self.source,
            self.units,
            self.config,
            self.parent,
        )

    def test_complete_payload(self):
        stage, manifest = self.build()

        self.assertEqual(
            len(manifest["files"]),
            len(MODULES) + len(LAUNCHERS) + len(UNITS),
        )

        for name in MODULES:
            self.assertTrue(target(
                stage,
                PREFIX + "/smart_mount/" + name,
            ).is_file())

    def test_file_permissions(self):
        stage, manifest = self.build()

        verify_files(stage, manifest["files"])

        for path in LAUNCHERS:
            self.assertEqual(
                target(stage, path).stat().st_mode & 0o777,
                0o755,
            )

    def test_private_configuration(self):
        stage, _ = self.build()

        path = target(
            stage,
            CONFIG_DIR + "/config.toml",
        )

        self.assertEqual(path.read_bytes(), self.config)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_manifest(self):
        stage, manifest = self.build()

        saved = json.loads(
            target(stage, MANIFEST).read_text()
        )

        self.assertEqual(saved, manifest)
        self.assertFalse(saved["activation"])
        self.assertTrue(
            saved["configuration"]["preserve_on_uninstall"]
        )

        self.assertNotIn(
            str(self.root),
            json.dumps(saved),
        )

        self.assertNotIn(
            "sha256",
            saved["configuration"],
        )

    def test_extra_files_excluded(self):
        (self.source / "private-notes.txt").touch()

        stage, _ = self.build()

        self.assertFalse(target(
            stage,
            PREFIX + "/smart_mount/private-notes.txt",
        ).exists())

    def test_unique_staging_directory(self):
        first, _ = self.build()
        second, _ = self.build()

        self.assertNotEqual(first, second)

    def test_missing_unit_cleanup(self):
        (self.units / UNITS[0]).unlink()

        with self.assertRaises(OSError):
            self.build()

        self.assertEqual(list(self.parent.iterdir()), [])

    def test_symlink_unit_rejected(self):
        path = self.units / UNITS[0]
        path.unlink()
        path.symlink_to(self.units / UNITS[1])

        with self.assertRaises(OSError):
            self.build()

        self.assertEqual(list(self.parent.iterdir()), [])

    def test_modified_payload_detected(self):
        stage, manifest = self.build()

        target(
            stage,
            manifest["files"][0]["path"],
        ).write_text("# Modified")

        with self.assertRaises(PlanError):
            verify_files(stage, manifest["files"])

    def test_unsafe_staging_directory(self):
        self.parent.chmod(0o755)

        with self.assertRaises(PlanError):
            self.build()

    def test_permissive_umask_directory_permissions(self):
        import os

        previous = os.umask(0o000)

        try:
            stage, manifest = self.build()
        finally:
            os.umask(previous)

        verify_files(stage, manifest["files"])

        for path in stage.rglob("*"):
            if path.is_dir():
                self.assertEqual(
                    path.stat().st_mode & 0o022,
                    0,
                )

        self.assertEqual(
            target(stage, CONFIG_DIR).stat().st_mode & 0o777,
            0o700,
        )

    def test_invalid_destination(self):
        with self.assertRaises(PlanError):
            target(self.parent, "/opt/../example")


if __name__ == "__main__":
    unittest.main()
