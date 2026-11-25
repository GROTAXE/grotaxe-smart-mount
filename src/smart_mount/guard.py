"""Storage protection policy and read-only evaluation engine."""

import subprocess
from pathlib import Path

from .identity import MountError, check, mount_at


PROBE_ERRORS = (
    MountError,
    OSError,
    subprocess.SubprocessError,
)


def probe_volume(volume):
    """Validate a configured volume and required directories."""

    target = Path(volume["target"])

    identity = check(
        target,
        volume["uuid"],
        mode=volume["mode"],
        fstype=volume["fstype"],
        fsroot=volume["fsroot"],
    )

    for relative in volume["required_dirs"]:
        path = target / relative

        try:
            if (
                path.resolve(strict=True) != path
                or not path.is_dir()
            ):
                raise MountError(
                    "Invalid required directory."
                )
        except (OSError, RuntimeError) as exc:
            raise MountError(
                "Required directory unavailable."
            ) from exc

        if mount_at(path, mode=volume["mode"]) != identity:
            raise MountError(
                "Required directory crosses a mount boundary."
            )

    return identity


def evaluate(
    config,
    *,
    status,
    verify_bind=None,
    probe=probe_volume,
):
    """Evaluate protection policies without changing the system.

    status(unit) must return active or inactive.
    Unknown states are treated conservatively.

    verify_bind(unit, policy, volume) must return True
    after successful namespace validation.

    The returned stop order is advisory only.
    """

    volumes = config["volumes"]
    volume_results = {}

    for name, volume in volumes.items():
        try:
            probe(volume)
        except PROBE_ERRORS:
            volume_results[name] = False
        else:
            volume_results[name] = True

    groups = []

    for group in config["groups"]:
        errors = []
        states = {}

        for name in group["volumes"]:
            if not volume_results[name]:
                errors.append({
                    "code": "VOLUME_UNAVAILABLE",
                    "volume": name,
                })

        for unit in group["units"]:
            try:
                current = status(unit)
            except PROBE_ERRORS:
                current = "unknown"

            if current not in ("active", "inactive"):
                current = "unknown"

                errors.append({
                    "code": "SERVICE_STATE_UNKNOWN",
                    "unit": unit,
                })

            states[unit] = current

        if not errors:
            for unit, current in states.items():
                if current != "active":
                    continue

                for policy in group["binds"]:
                    try:
                        verified = (
                            verify_bind is not None
                            and verify_bind(
                                unit,
                                policy,
                                volumes[policy["volume"]],
                            ) is True
                        )
                    except PROBE_ERRORS:
                        verified = False

                    if not verified:
                        errors.append({
                            "code": "NAMESPACE_UNVERIFIED",
                            "unit": unit,
                            "volume": policy["volume"],
                        })

        active_count = sum(
            value == "active"
            for value in states.values()
        )

        if errors:
            health = "BLOCKED"
        elif active_count == 0:
            health = "IDLE"
        elif active_count == len(states):
            health = "HEALTHY"
        else:
            health = "PARTIAL"

        stop_order = []

        if health == "BLOCKED":
            stop_order = [
                unit
                for unit in reversed(group["units"])
                if states[unit] != "inactive"
            ]

        groups.append({
            "name": group["name"],
            "health": health,
            "services": states,
            "errors": errors,
            "stop_order": stop_order,
        })

    return {
        "volumes": volume_results,
        "groups": groups,
        "safe": (
            all(volume_results.values())
            and all(
                group["health"] != "BLOCKED"
                for group in groups
            )
        ),
    }
