import json
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from smart_mount.install_plan import (
    PREFIX,
    PlanError,
)

from smart_mount.stage_install import (
    MANIFEST,
    build_stage,
    target,
)

from smart_mount.lifecycle import (
    CONFIG_PATH,
    prepare_upgrade,
    uninstall,
    verify_installation,
)


ROOT = Path(__file__).resolve().parents[1]


class LifecycleTests(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        self.parent = Path(temp.name).resolve()
        self.parent.chmod(0o700)

        self.source = ROOT / "src/smart_mount"
        self.units = ROOT / "packaging/systemd"

        self.config = (
            ROOT / "examples/smart-mount.toml"
        ).read_bytes()

        self.stage, self.manifest = build_stage(
            self.source,
            self.units,
            self.config,
            self.parent,
        )

    def verify(self):
        return verify_installation(
            self.stage,
            self.parent,
        )

    def remove(self, *, apply=False):
        return uninstall(
            self.stage,
            self.parent,
            apply=apply,
        )

    def update_manifest(self, manifest):
        target(self.stage, MANIFEST).write_text(
            json.dumps(manifest)
        )

    def test_verify_complete_installation(self):
        self.assertEqual(
            self.verify(), self.manifest
        )

    def test_upgrade_preserves_configuration(self):
        config = target(self.stage, CONFIG_PATH)

        modified = (
            self.config + b"\n# Local settings\n"
        )

        config.write_bytes(modified)

        replacement, _ = prepare_upgrade(
            self.stage,
            self.parent,
            self.source,
            self.units,
        )

        self.assertNotEqual(replacement, self.stage)

        self.assertEqual(
            target(replacement, CONFIG_PATH).read_bytes(),
            modified,
        )

        self.assertEqual(
            config.read_bytes(), modified
        )

        self.verify()
        verify_installation(replacement, self.parent)

    def test_uninstall_dry_run(self):
        result = self.remove()

        self.assertTrue(result["dry_run"])
        self.assertEqual(result["removed"], [])

        self.verify()

    def test_uninstall_preserves_configuration(self):
        result = self.remove(apply=True)

        self.assertEqual(
            result["removed"], result["planned"]
        )

        self.assertEqual(
            target(self.stage, CONFIG_PATH).read_bytes(),
            self.config,
        )

        for path in result["removed"]:
            self.assertFalse(
                target(self.stage, path).exists()
            )

    def test_foreign_files_preserved(self):
        foreign = target(
            self.stage,
            PREFIX + "/local-notes.txt",
        )

        foreign.write_text("Synthetic local data")

        self.remove(apply=True)

        self.assertEqual(
            foreign.read_text(),
            "Synthetic local data",
        )

    def test_modified_file_blocks_uninstall(self):
        path = target(
            self.stage,
            self.manifest["files"][0]["path"],
        )

        path.write_text("# Modified")

        with self.assertRaises(PlanError):
            self.remove(apply=True)

        self.assertTrue(path.exists())
        self.assertTrue(
            target(self.stage, MANIFEST).exists()
        )

        for item in self.manifest["files"]:
            self.assertTrue(
                target(self.stage, item["path"]).exists()
            )

    def test_foreign_manifest_path_rejected(self):
        self.manifest["files"][0]["path"] = (
            "/etc/example-foreign.conf"
        )

        self.update_manifest(self.manifest)

        with self.assertRaises(PlanError):
            self.remove(apply=True)

    def test_duplicate_manifest_record_rejected(self):
        self.manifest["files"].append(
            self.manifest["files"][0]
        )

        self.update_manifest(self.manifest)

        with self.assertRaises(PlanError):
            self.verify()

    def test_missing_manifest_record_rejected(self):
        self.manifest["files"].pop()

        self.update_manifest(self.manifest)

        with self.assertRaises(PlanError):
            self.verify()

    def test_symlink_directory_rejected(self):
        directory = target(
            self.stage,
            PREFIX + "/smart_mount",
        )

        moved = directory.with_name("moved")
        directory.rename(moved)
        directory.symlink_to(moved)

        with self.assertRaises(PlanError):
            self.remove(apply=True)

        self.assertTrue(moved.exists())

    def test_foreign_stage_rejected(self):
        foreign = self.parent / "unregistered"
        foreign.mkdir(mode=0o700)

        with self.assertRaises(PlanError):
            uninstall(
                foreign,
                self.parent,
                apply=True,
            )

    def test_lifecycle_with_permissive_umask(self):
        import os

        previous = os.umask(0o002)

        try:
            stage, manifest = build_stage(
                self.source,
                self.units,
                self.config,
                self.parent,
            )

            self.assertEqual(
                verify_installation(stage, self.parent),
                manifest,
            )

            result = uninstall(
                stage,
                self.parent,
                apply=True,
            )

            self.assertEqual(
                result["removed"],
                result["planned"],
            )

            self.assertEqual(
                target(stage, CONFIG_PATH).read_bytes(),
                self.config,
            )

        finally:
            os.umask(previous)

    def test_privileged_operation_rejected(self):
        with patch(
            "smart_mount.lifecycle.os.geteuid",
            return_value=0,
        ):
            with self.assertRaises(PlanError):
                self.remove(apply=True)


if __name__ == "__main__":
    unittest.main()
