"""Restricted systemd action backend."""

import os
import subprocess

from .config import service_name
from .systemd import SystemdAdapter, SystemdError


SYSTEMCTL = "/usr/bin/systemctl"

SAFE_ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
    "SYSTEMD_COLORS": "0",
    "SYSTEMD_PAGER": "cat",
}


class SystemBackend:

    def __init__(
        self,
        config,
        *,
        apply=False,
        timeout=60,
        runner=subprocess.run,
    ):
        self.allowed = frozenset(
            service_name(unit)
            for group in config["groups"]
            for unit in group["units"]
        )

        self._apply = apply is True
        self._runner = runner
        self.timeout = timeout

        self.reader = SystemdAdapter(
            timeout=10,
            runner=self._inspect_runner,
        )

    def _require_allowed(self, unit):
        if not isinstance(unit, str) or unit not in self.allowed:
            raise SystemdError("Service is not authorized.")

    def _run(self, command, *, timeout):
        try:
            result = self._runner(
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout,
                env=dict(SAFE_ENV),
                cwd="/",
            )

            if result.returncode != 0:
                raise SystemdError("Systemd operation failed.")

            return result

        except (
            OSError,
            subprocess.SubprocessError,
            UnicodeError,
        ) as exc:
            raise SystemdError(
                "Systemd operation failed."
            ) from exc

    def _inspect_runner(self, command, **kwargs):
        if not command or command[0] != "systemctl":
            raise SystemdError("Invalid inspection command.")

        return self._run(
            [SYSTEMCTL, *command[1:]],
            timeout=kwargs.get("timeout", 10),
        )

    def inspect(self, unit):
        self._require_allowed(unit)
        return self.reader.inspect(unit)

    def status(self, unit):
        return self.inspect(unit).status

    def main_pid(self, unit):
        self._require_allowed(unit)
        return self.reader.main_pid(unit)

    def _action(self, action, unit):
        self._require_allowed(unit)

        if not self._apply:
            raise SystemdError("System actions are disabled.")

        if os.geteuid() != 0:
            raise SystemdError("Root privileges required.")

        if action not in {"start", "stop"}:
            raise SystemdError("Unsupported action.")

        before = self.inspect(unit)

        if action == "start" and before.status != "inactive":
            raise SystemdError("Service is not inactive.")

        if action == "stop" and before.status == "inactive":
            raise SystemdError("Service was already inactive.")

        self._run(
            [
                SYSTEMCTL,
                "--system",
                "--no-pager",
                "--no-ask-password",
                "--job-mode=fail",
                action,
                "--",
                unit,
            ],
            timeout=self.timeout,
        )

        expected = (
            "active" if action == "start" else "inactive"
        )

        if self.status(unit) != expected:
            raise SystemdError("Action result not confirmed.")

    def start(self, unit):
        self._action("start", unit)

    def stop(self, unit):
        self._action("stop", unit)
