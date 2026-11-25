import subprocess
import unittest
from unittest.mock import Mock

from smart_mount.systemd import (
    SystemdAdapter,
    SystemdError,
)


class SystemdTests(unittest.TestCase):

    def setUp(self):
        self.unit = "example-app.service"

        self.values = {
            "Id": self.unit,
            "LoadState": "loaded",
            "ActiveState": "active",
            "MainPID": "12345",
        }

        self.runner = Mock(side_effect=self.response)
        self.adapter = SystemdAdapter(runner=self.runner)

    def response(self, command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(
                f"{key}={value}"
                for key, value in self.values.items()
            ),
        )

    def test_active_service(self):
        self.assertEqual(
            self.adapter.status(self.unit), "active"
        )
        self.assertEqual(
            self.adapter.main_pid(self.unit), 12345
        )

    def test_inactive_service(self):
        self.values["ActiveState"] = "inactive"
        self.values["MainPID"] = "0"

        self.assertEqual(
            self.adapter.status(self.unit), "inactive"
        )

        with self.assertRaises(SystemdError):
            self.adapter.main_pid(self.unit)

    def test_uncertain_service_states(self):
        for state in (
            "activating",
            "deactivating",
            "reloading",
            "failed",
        ):
            with self.subTest(state=state):
                self.values["ActiveState"] = state

                self.assertEqual(
                    self.adapter.status(self.unit),
                    "unknown",
                )

    def test_missing_service(self):
        self.values["LoadState"] = "not-found"

        with self.assertRaises(SystemdError):
            self.adapter.inspect(self.unit)

    def test_alias_rejected(self):
        self.values["Id"] = "other.service"

        with self.assertRaises(SystemdError):
            self.adapter.inspect(self.unit)

    def test_invalid_pid(self):
        for pid in ("-1", "invalid", "9999999999"):
            with self.subTest(pid=pid):
                self.values["MainPID"] = pid

                with self.assertRaises(SystemdError):
                    self.adapter.inspect(self.unit)

    def test_active_without_main_process(self):
        self.values["MainPID"] = "0"

        with self.assertRaises(SystemdError):
            self.adapter.main_pid(self.unit)

    def test_incomplete_response(self):
        del self.values["MainPID"]

        with self.assertRaises(SystemdError):
            self.adapter.inspect(self.unit)

    def test_timeout(self):
        self.runner.side_effect = subprocess.TimeoutExpired(
            ["systemctl"], 10
        )

        with self.assertRaises(SystemdError):
            self.adapter.inspect(self.unit)

    def test_invalid_service_name(self):
        with self.assertRaises(SystemdError):
            self.adapter.inspect("--invalid.service")

        self.runner.assert_not_called()

    def test_readonly_command(self):
        self.adapter.inspect(self.unit)

        command = self.runner.call_args.args[0]

        self.assertIn("show", command)
        self.assertEqual(command[-2:], ["--", self.unit])

        for action in ("start", "stop", "restart", "enable"):
            self.assertNotIn(action, command)

        self.assertTrue(self.runner.call_args.kwargs["check"])


if __name__ == "__main__":
    unittest.main()
