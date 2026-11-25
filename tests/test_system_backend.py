import os
import stat
import subprocess
import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from smart_mount.config import ConfigError
from smart_mount.system_backend import (
    SYSTEMCTL,
    SAFE_ENV,
    SystemBackend,
)
from smart_mount.systemd import SystemdError
from smart_mount.trusted_config import (
    check_metadata,
    decode_config,
    load_trusted_config,
)


UNIT = "example-app.service"
CONFIG = {"groups": [{"units": [UNIT]}]}


class BackendTests(unittest.TestCase):

    def setUp(self):
        self.state = "inactive"
        self.identity = UNIT

        self.runner = Mock(side_effect=self.response)

        self.backend = SystemBackend(
            CONFIG,
            apply=True,
            runner=self.runner,
        )

        root = patch(
            "smart_mount.system_backend.os.geteuid",
            return_value=0,
        )

        root.start()
        self.addCleanup(root.stop)

    def response(self, command, **kwargs):
        output = ""

        if "show" in command:
            output = (
                f"Id={self.identity}\n"
                "LoadState=loaded\n"
                f"ActiveState={self.state}\n"
                "MainPID=123\n"
            )

        elif "start" in command:
            self.state = "active"

        elif "stop" in command:
            self.state = "inactive"

        return subprocess.CompletedProcess(
            command, 0, stdout=output
        )

    def test_readonly_status(self):
        self.assertEqual(
            self.backend.status(UNIT), "inactive"
        )

        self.assertIn(
            "show", self.runner.call_args.args[0]
        )

    def test_default_actions_disabled(self):
        backend = SystemBackend(
            CONFIG, runner=self.runner
        )

        with self.assertRaises(SystemdError):
            backend.start(UNIT)

        self.runner.assert_not_called()

    def test_foreign_service_rejected(self):
        with self.assertRaises(SystemdError):
            self.backend.start("foreign.service")

        self.runner.assert_not_called()

    def test_nonroot_rejected(self):
        with patch(
            "smart_mount.system_backend.os.geteuid",
            return_value=1000,
        ):
            with self.assertRaises(SystemdError):
                self.backend.start(UNIT)

        self.runner.assert_not_called()

    def test_start_and_stop(self):
        self.backend.start(UNIT)
        self.assertEqual(self.state, "active")

        self.backend.stop(UNIT)
        self.assertEqual(self.state, "inactive")

    def test_alias_rejected(self):
        self.identity = "other.service"

        with self.assertRaises(SystemdError):
            self.backend.start(UNIT)

    def test_already_inactive_stop_rejected(self):
        with self.assertRaises(SystemdError):
            self.backend.stop(UNIT)

    def test_environment_isolation(self):
        with patch.dict(
            os.environ,
            {"DBUS_SYSTEM_BUS_ADDRESS": "invalid"},
        ):
            self.backend.start(UNIT)

        for call in self.runner.call_args_list:
            command = call.args[0]

            self.assertEqual(command[0], SYSTEMCTL)
            self.assertEqual(call.kwargs["env"], SAFE_ENV)
            self.assertEqual(call.kwargs["cwd"], "/")

    def test_timeout_rejected(self):
        self.runner.side_effect = subprocess.TimeoutExpired(
            ["systemctl"], 10
        )

        with self.assertRaises(SystemdError):
            self.backend.start(UNIT)


class TrustedConfigTests(unittest.TestCase):

    def test_valid_metadata(self):
        info = SimpleNamespace(
            st_uid=0,
            st_mode=stat.S_IFREG | 0o600,
            st_nlink=1,
        )

        check_metadata(info, directory=False)

    def test_foreign_owner_rejected(self):
        info = SimpleNamespace(
            st_uid=1000,
            st_mode=stat.S_IFREG | 0o600,
            st_nlink=1,
        )

        with self.assertRaises(ConfigError):
            check_metadata(info, directory=False)

    def test_unsafe_file_permissions(self):
        info = SimpleNamespace(
            st_uid=0,
            st_mode=stat.S_IFREG | 0o644,
            st_nlink=1,
        )

        with self.assertRaises(ConfigError):
            check_metadata(info, directory=False)

    def test_writable_directory_rejected(self):
        info = SimpleNamespace(
            st_uid=0,
            st_mode=stat.S_IFDIR | 0o777,
        )

        with self.assertRaises(ConfigError):
            check_metadata(info, directory=True)

    def test_hardlinked_file_rejected(self):
        info = SimpleNamespace(
            st_uid=0,
            st_mode=stat.S_IFREG | 0o600,
            st_nlink=2,
        )

        with self.assertRaises(ConfigError):
            check_metadata(info, directory=False)

    def test_untrusted_path_rejected(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as temp:
            path = Path(temp) / "config.toml"
            path.write_text("schema_version = 1")
            path.chmod(0o600)

            with self.assertRaises(ConfigError):
                load_trusted_config(path)

    def test_generic_configuration(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "smart-mount.toml"
        )

        result = decode_config(path.read_bytes())
        self.assertEqual(result["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
