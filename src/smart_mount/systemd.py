"""Read-only systemd service inspection."""

import os
import re
import subprocess
from dataclasses import dataclass

from .config import ConfigError, service_name
from .identity import MountError


class SystemdError(MountError):
    """Unable to establish trusted service state."""


@dataclass(frozen=True)
class ServiceState:
    unit: str
    active_state: str
    main_pid: int

    @property
    def status(self):
        if self.active_state in {"active", "inactive"}:
            return self.active_state

        return "unknown"


class SystemdAdapter:

    PROPERTIES = (
        "Id",
        "LoadState",
        "ActiveState",
        "MainPID",
    )

    def __init__(self, *, timeout=10, runner=subprocess.run):
        self.timeout = timeout
        self.runner = runner

    def inspect(self, unit):
        try:
            service_name(unit)
        except ConfigError as exc:
            raise SystemdError("Invalid service name.") from exc

        command = [
            "systemctl",
            "--system",
            "--no-pager",
            "--no-ask-password",
            "show",
            "--property=" + ",".join(self.PROPERTIES),
            "--",
            unit,
        ]

        try:
            result = self.runner(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=True,
                env={**os.environ, "LC_ALL": "C"},
            )

        except (
            OSError,
            subprocess.SubprocessError,
            UnicodeError,
        ) as exc:
            raise SystemdError(
                "Systemd inspection failed."
            ) from exc

        values = {}

        for line in result.stdout.splitlines():
            if not line:
                continue

            key, separator, value = line.partition("=")

            if (
                not separator
                or key not in self.PROPERTIES
                or key in values
            ):
                raise SystemdError(
                    "Invalid systemd response."
                )

            values[key] = value

        if set(values) != set(self.PROPERTIES):
            raise SystemdError(
                "Incomplete systemd response."
            )

        if values["LoadState"] != "loaded":
            raise SystemdError("Service is not loaded.")

        if values["Id"] != unit:
            raise SystemdError(
                "Service identity mismatch."
            )

        pid = values["MainPID"]

        if (
            not re.fullmatch(r"[0-9]{1,10}", pid)
            or int(pid) > 2147483647
        ):
            raise SystemdError("Invalid service PID.")

        if not re.fullmatch(
            r"[a-z-]+", values["ActiveState"]
        ):
            raise SystemdError("Invalid service state.")

        return ServiceState(
            unit=unit,
            active_state=values["ActiveState"],
            main_pid=int(pid),
        )

    def status(self, unit):
        return self.inspect(unit).status

    def main_pid(self, unit):
        state = self.inspect(unit)

        if state.status != "active" or state.main_pid <= 0:
            raise SystemdError(
                "No active main process available."
            )

        return state.main_pid
