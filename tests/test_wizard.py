import contextlib
import io
import tempfile
import unittest

from pathlib import Path

from smart_mount.config import ConfigError
from smart_mount.trusted_config import decode_config
from smart_mount.wizard import (
    main,
    manual_config,
    read_template,
    save_new,
)


EXAMPLE = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "smart-mount.toml"
)

UUID = "11111111-2222-3333-4444-555555555555"


class WizardTests(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        self.root = Path(temp.name).resolve()
        self.output = self.root / "config.toml"
        self.data = read_template(EXAMPLE)

    def invoke(self, *args):
        with contextlib.redirect_stdout(io.StringIO()):
            return main(list(args))

    def test_template_validation(self):
        self.assertEqual(
            decode_config(self.data)["schema_version"], 1
        )

    def test_invalid_template(self):
        self.output.write_text("[invalid")

        with self.assertRaises(ConfigError):
            read_template(self.output)

    def test_save_private_file(self):
        save_new(self.output, self.data)

        self.assertEqual(
            self.output.read_bytes(), self.data
        )

        self.assertEqual(
            self.output.stat().st_mode & 0o777, 0o600
        )

    def test_existing_file_not_replaced(self):
        self.output.write_text("original")

        with self.assertRaises(FileExistsError):
            save_new(self.output, self.data)

        self.assertEqual(
            self.output.read_text(), "original"
        )

    def test_symlink_not_replaced(self):
        target = self.root / "target"
        target.write_text("original")

        self.output.symlink_to(target)

        with self.assertRaises(FileExistsError):
            save_new(self.output, self.data)

        self.assertEqual(target.read_text(), "original")
        self.assertTrue(self.output.is_symlink())

    def test_invalid_config_not_written(self):
        with self.assertRaises(ConfigError):
            save_new(self.output, b"[invalid")

        self.assertFalse(self.output.exists())

    def test_dry_run(self):
        code = self.invoke(
            "--config", str(EXAMPLE),
            "--output", str(self.output),
            "--dry-run",
        )

        self.assertEqual(code, 0)
        self.assertFalse(self.output.exists())

    def test_explicit_automatic_save(self):
        code = self.invoke(
            "--config", str(EXAMPLE),
            "--output", str(self.output),
            "--yes",
        )

        self.assertEqual(code, 0)
        self.assertTrue(self.output.exists())

    def test_manual_configuration(self):
        answers = iter([
            "storage",
            "/mnt/example",
            UUID,
            "",
            "ext4",
            "n",
            "y",
            "application",
            "storage",
            "example.service",
            "n",
        ])

        data = manual_config(lambda _: next(answers))
        config = decode_config(data)

        self.assertIn("storage", config["volumes"])
        self.assertFalse(
            config["groups"][0]["auto_recovery"]
        )

    def test_manual_invalid_uuid(self):
        answers = iter([
            "storage",
            "/mnt/example",
            "invalid",
            "",
            "ext4",
        ])

        with self.assertRaises(ConfigError):
            manual_config(lambda _: next(answers))


if __name__ == "__main__":
    unittest.main()
