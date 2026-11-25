import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from smart_mount.config import load_config
from smart_mount.guard import evaluate, probe_volume
from smart_mount.identity import MountError


EXAMPLE = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "smart-mount.toml"
)


class GuardTests(unittest.TestCase):

    def setUp(self):
        self.config = load_config(EXAMPLE)
        self.group = self.config["groups"][0]
        self.units = self.group["units"]
        self.states = dict.fromkeys(self.units, "active")

        self.probe = Mock(return_value={})
        self.namespace = Mock(return_value=True)

    def run_guard(self):
        return evaluate(
            self.config,
            status=self.states.__getitem__,
            verify_bind=self.namespace,
            probe=self.probe,
        )

    def test_healthy(self):
        result = self.run_guard()
        self.assertTrue(result["safe"])
        self.assertEqual(
            result["groups"][0]["health"], "HEALTHY"
        )
        self.assertEqual(self.namespace.call_count, 2)

    def test_idle(self):
        self.states = dict.fromkeys(self.units, "inactive")
        result = self.run_guard()["groups"][0]

        self.assertEqual(result["health"], "IDLE")
        self.assertEqual(result["stop_order"], [])
        self.namespace.assert_not_called()

    def test_partial(self):
        self.states[self.units[0]] = "inactive"
        result = self.run_guard()["groups"][0]

        self.assertEqual(result["health"], "PARTIAL")
        self.assertEqual(result["stop_order"], [])

    def test_volume_failure(self):
        self.probe.side_effect = MountError("Unavailable")
        result = self.run_guard()

        self.assertFalse(result["safe"])
        group = result["groups"][0]

        self.assertEqual(group["health"], "BLOCKED")
        self.assertEqual(
            group["stop_order"], self.units[::-1]
        )

    def test_namespace_failure(self):
        self.namespace.return_value = False

        result = self.run_guard()["groups"][0]

        self.assertEqual(result["health"], "BLOCKED")
        self.assertEqual(
            result["stop_order"], self.units[::-1]
        )

    def test_missing_namespace_checker(self):
        self.namespace = None
        result = self.run_guard()["groups"][0]
        self.assertEqual(result["health"], "BLOCKED")

    def test_unknown_service(self):
        self.states[self.units[0]] = "unknown"

        result = self.run_guard()["groups"][0]
        self.assertEqual(result["health"], "BLOCKED")
        self.assertIn(self.units[0], result["stop_order"])

    def test_status_exception(self):
        def unavailable(unit):
            raise OSError("Manager unavailable")

        result = evaluate(
            self.config,
            status=unavailable,
            probe=self.probe,
        )

        self.assertFalse(result["safe"])
        self.assertEqual(
            result["groups"][0]["health"], "BLOCKED"
        )

    def test_required_directory_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            volume = dict(self.config["volumes"]["primary"])
            volume["target"] = str(Path(temp).resolve())

            with patch(
                "smart_mount.guard.check", return_value={}
            ):
                with self.assertRaises(MountError):
                    probe_volume(volume)

    def test_required_directory_nested_mount(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "data").mkdir()

            volume = dict(self.config["volumes"]["primary"])
            volume["target"] = str(root)

            with patch(
                "smart_mount.guard.check",
                return_value={"target": str(root)},
            ), patch(
                "smart_mount.guard.mount_at",
                return_value={"target": str(root / "data")},
            ):
                with self.assertRaises(MountError):
                    probe_volume(volume)

    def test_required_directory_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "other").mkdir()
            (root / "data").symlink_to(root / "other")

            volume = dict(self.config["volumes"]["primary"])
            volume["target"] = str(root)

            with patch(
                "smart_mount.guard.check", return_value={}
            ):
                with self.assertRaises(MountError):
                    probe_volume(volume)

    def test_required_directory_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            (root / "data").mkdir()

            volume = dict(self.config["volumes"]["primary"])
            volume["target"] = str(root)
            identity = {"target": str(root)}

            with patch(
                "smart_mount.guard.check",
                return_value=identity,
            ), patch(
                "smart_mount.guard.mount_at",
                return_value=identity,
            ):
                self.assertEqual(
                    probe_volume(volume), identity
                )


if __name__ == "__main__":
    unittest.main()
