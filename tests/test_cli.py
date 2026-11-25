import contextlib
import io
import json
import unittest

from pathlib import Path
from unittest.mock import patch

from smart_mount.cli import main
from smart_mount.identity import MountError
from smart_mount.terminal import Terminal, safe_text


EXAMPLE = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "smart-mount.toml"
)

UUID = "11111111-2222-3333-4444-555555555555"


class CLITests(unittest.TestCase):

    def invoke(self, *args):
        output = io.StringIO()
        errors = io.StringIO()

        with contextlib.redirect_stdout(output):
            with contextlib.redirect_stderr(errors):
                code = main(list(args))

        return code, output.getvalue(), errors.getvalue()

    def test_about(self):
        code, output, _ = self.invoke("--plain", "about")

        self.assertEqual(code, 0)
        self.assertIn("GROTAXE SMART MOUNT", output)

    def test_json_output(self):
        code, output, _ = self.invoke("--json", "about")

        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output)["ok"])

    def test_config_validation(self):
        code, output, _ = self.invoke(
            "--json", "config", str(EXAMPLE)
        )

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["volumes"], 1)

    def test_config_failure(self):
        with patch(
            "smart_mount.cli.load_config",
            side_effect=OSError("Private diagnostic data"),
        ):
            code, output, errors = self.invoke(
                "--json", "config", "/example.toml"
            )

        self.assertEqual(code, 1)
        self.assertFalse(json.loads(output)["ok"])
        self.assertNotIn("Private diagnostic data", output)

    def test_check_success(self):
        with patch(
            "smart_mount.cli.check",
            return_value={"uuid": UUID},
        ):
            code, output, _ = self.invoke(
                "--json", "check", "/mnt/example", UUID
            )

        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(output)["identity"]["uuid"], UUID
        )

    def test_check_failure(self):
        with patch(
            "smart_mount.cli.check",
            side_effect=MountError("Mismatch"),
        ):
            code, _, errors = self.invoke(
                "--plain", "check", "/mnt/example", UUID
            )

        self.assertEqual(code, 1)
        self.assertIn("[FAIL]", errors)

    def test_status_readonly_backend(self):
        with patch("smart_mount.cli.SystemBackend") as backend:
            with patch("smart_mount.cli.RuntimeEngine") as engine:
                engine.return_value.preview.return_value = {
                    "safe": True,
                    "volumes": {},
                    "groups": [],
                }

                code, output, _ = self.invoke(
                    "--json", "status", str(EXAMPLE)
                )

        self.assertEqual(code, 0)
        self.assertFalse(backend.call_args.kwargs["apply"])
        self.assertTrue(json.loads(output)["read_only"])
        engine.return_value.cycle.assert_not_called()

    def test_unsafe_status_exit_code(self):
        with patch("smart_mount.cli.SystemBackend"):
            with patch("smart_mount.cli.RuntimeEngine") as engine:
                engine.return_value.preview.return_value = {
                    "safe": False,
                    "volumes": {},
                    "groups": [],
                }

                code, _, _ = self.invoke(
                    "--json", "status", str(EXAMPLE)
                )

        self.assertEqual(code, 1)

    def test_doctor_failure(self):
        with patch(
            "smart_mount.cli.doctor",
            return_value={
                "ok": False,
                "checks": {"example": False},
            },
        ):
            code, output, _ = self.invoke(
                "--plain", "doctor"
            )

        self.assertEqual(code, 1)
        self.assertIn("[FAIL]", output)

    def test_plain_output_has_no_ansi(self):
        stream = io.StringIO()
        ui = Terminal(stream, plain=True)

        ui.banner()
        ui.status(True, "Verified")

        self.assertNotIn("\033", stream.getvalue())

    def test_terminal_control_injection(self):
        result = safe_text("\033[31mexample\n")
        self.assertNotIn("\033", result)
        self.assertNotIn("\n", result)

    def test_relative_inspection_rejected(self):
        code, _, _ = self.invoke(
            "--json", "inspect", "relative/path"
        )

        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
