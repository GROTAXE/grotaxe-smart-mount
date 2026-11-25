import contextlib
import io
import json
import tempfile
import unittest

from pathlib import Path

from smart_mount.config import ConfigError
from smart_mount.install_plan import (
    MODULES,
    PREFIX,
    PlanError,
    build_plan,
    main,
)


EXAMPLE = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "smart-mount.toml"
)


class InstallationPlanTests(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        self.root = Path(temp.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()

        for name in MODULES:
            (self.source / name).write_text(
                "# Synthetic module\n"
            )

        self.config = EXAMPLE.read_bytes()

    def plan(self):
        return build_plan(self.source, self.config)

    def test_complete_payload(self):
        plan = self.plan()

        self.assertEqual(
            len(plan["payload"]), len(MODULES)
        )

        for item in plan["payload"]:
            self.assertEqual(
                item["destination"],
                PREFIX + "/smart_mount/" + item["module"],
            )
            self.assertEqual(len(item["sha256"]), 64)

    def test_unlisted_files_excluded(self):
        (self.source / "local-notes.txt").touch()
        (self.source / "private-config.toml").touch()

        payload = self.plan()["payload"]

        self.assertEqual(
            {item["module"] for item in payload},
            set(MODULES),
        )

    def test_missing_module_rejected(self):
        (self.source / MODULES[0]).unlink()

        with self.assertRaises(OSError):
            self.plan()

    def test_symlink_module_rejected(self):
        path = self.source / MODULES[0]
        path.unlink()
        path.symlink_to(self.source / MODULES[1])

        with self.assertRaises(OSError):
            self.plan()

    def test_symlink_source_rejected(self):
        alias = self.root / "alias"
        alias.symlink_to(self.source)

        with self.assertRaises(PlanError):
            build_plan(alias, self.config)

    def test_invalid_config_rejected(self):
        with self.assertRaises(ConfigError):
            build_plan(self.source, b"[invalid")

    def test_deterministic_plan(self):
        self.assertEqual(self.plan(), self.plan())

    def test_no_service_activation(self):
        plan = self.plan()

        self.assertTrue(plan["dry_run"])
        self.assertFalse(plan["system_changes"])
        self.assertFalse(plan["activate_services"])
        self.assertFalse(plan["ready_for_install"])
        self.assertEqual(
            len(plan["pending_artifacts"]), 4
        )

    def test_directory_payload_rejected(self):
        path = self.source / MODULES[0]
        path.unlink()
        path.mkdir()

        with self.assertRaises(PlanError):
            self.plan()

    def test_fifo_payload_rejected(self):
        import os

        path = self.source / MODULES[0]
        path.unlink()
        os.mkfifo(path)

        with self.assertRaises(PlanError):
            self.plan()

    def test_hardlinked_payload_rejected(self):
        import os

        os.link(
            self.source / MODULES[0],
            self.source / "alias",
        )

        with self.assertRaises(PlanError):
            self.plan()

    def test_oversized_payload_rejected(self):
        from smart_mount.install_plan import MAX_MODULE_SIZE

        path = self.source / MODULES[0]
        path.write_bytes(b"x" * (MAX_MODULE_SIZE + 1))

        with self.assertRaises(PlanError):
            self.plan()

    def test_json_cli_is_readonly(self):
        before = sorted(self.source.iterdir())
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            code = main([
                "--source", str(self.source),
                "--config", str(EXAMPLE),
                "--json",
            ])

        self.assertEqual(code, 0)

        result = json.loads(output.getvalue())

        self.assertTrue(result["ok"])
        self.assertFalse(result["system_changes"])
        self.assertNotIn(str(self.root), output.getvalue())

        self.assertEqual(
            sorted(self.source.iterdir()), before
        )


if __name__ == "__main__":
    unittest.main()
