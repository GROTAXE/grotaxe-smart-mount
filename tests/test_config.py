import copy
import tempfile
import tomllib
import unittest
from pathlib import Path

from smart_mount.config import (
    ConfigError,
    load_config,
    validate,
)

EXAMPLE = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "smart-mount.toml"
)


class ConfigTests(unittest.TestCase):

    def setUp(self):
        self.raw = tomllib.loads(EXAMPLE.read_text())

    def test_valid_example(self):
        result = load_config(EXAMPLE)
        self.assertIn("primary", result["volumes"])
        self.assertFalse(result["groups"][0]["auto_recovery"])

    def test_unknown_keys(self):
        self.raw["unexpected"] = True
        with self.assertRaises(ConfigError):
            validate(self.raw)

    def test_duplicate_volume(self):
        self.raw["volumes"].append(
            copy.deepcopy(self.raw["volumes"][0])
        )
        with self.assertRaises(ConfigError):
            validate(self.raw)

    def test_invalid_volume_settings(self):
        for key, value in (
            ("uuid", "invalid"),
            ("target", "relative/path"),
            ("target", "/mnt/../other"),
            ("mode", "invalid"),
            ("required_dirs", ["../other"]),
        ):
            with self.subTest(key=key, value=value):
                raw = copy.deepcopy(self.raw)
                raw["volumes"][0][key] = value
                with self.assertRaises(ConfigError):
                    validate(raw)

    def test_unknown_dependency(self):
        self.raw["groups"][0]["volumes"] = ["unknown"]
        with self.assertRaises(ConfigError):
            validate(self.raw)

    def test_invalid_bind(self):
        for key, value in (
            ("source", "/mnt/unrelated/data"),
            ("destination", "/mnt/example-storage/data"),
            ("marker", "../marker"),
            ("source_mode", "invalid"),
        ):
            with self.subTest(key=key):
                raw = copy.deepcopy(self.raw)
                raw["groups"][0]["binds"][0][key] = value
                with self.assertRaises(ConfigError):
                    validate(raw)

    def test_invalid_service(self):
        for unit in (
            "--invalid.service",
            "example.timer",
            "example@.service",
        ):
            with self.subTest(unit=unit):
                raw = copy.deepcopy(self.raw)
                raw["groups"][0]["units"] = [unit]
                with self.assertRaises(ConfigError):
                    validate(raw)

    def test_duplicate_service_ownership(self):
        other = copy.deepcopy(self.raw["groups"][0])
        other["name"] = "another"
        self.raw["groups"].append(other)
        with self.assertRaises(ConfigError):
            validate(self.raw)

    def test_runtime_limits(self):
        for value in (0, -1, True, 3601, "30"):
            with self.subTest(value=value):
                raw = copy.deepcopy(self.raw)
                raw["runtime"]["interval_seconds"] = value
                with self.assertRaises(ConfigError):
                    validate(raw)

    def test_malformed_toml(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.toml"
            path.write_text("[invalid")
            with self.assertRaises(ConfigError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
