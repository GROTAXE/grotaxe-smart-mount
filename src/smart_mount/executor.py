"""Conservative service action orchestration.

The backend and assessment callbacks must be trusted.
No system commands are executed by this module directly.
"""

import subprocess

from .identity import MountError


ACTION_ERRORS = (
    MountError,
    OSError,
    subprocess.SubprocessError,
)


def service_status(backend, unit):
    try:
        state = backend.status(unit)
    except ACTION_ERRORS:
        return "unknown"

    if state not in ("active", "inactive"):
        return "unknown"

    return state


def assessment(group, assess):
    result = assess()

    if (
        result["name"] != group["name"]
        or set(result["services"]) != set(group["units"])
    ):
        raise MountError("Assessment identity mismatch.")

    return result


def stop_blocked(group, assess, backend, *, apply=False):
    """Stop an unsafe group in reverse dependency order."""

    before = assessment(group, assess)

    order = [
        unit for unit in reversed(group["units"])
        if before["services"][unit] != "inactive"
    ] if before["health"] == "BLOCKED" else []

    result = {
        "dry_run": not apply,
        "planned": order,
        "confirmed": [],
        "failed": [],
        "before": before,
        "after": dict(before["services"]),
    }

    if not apply:
        return result

    for unit in order:
        initial = service_status(backend, unit)

        if initial == "inactive":
            continue

        try:
            backend.stop(unit)

            if service_status(backend, unit) != "inactive":
                raise MountError("Stop not confirmed.")

        except ACTION_ERRORS:
            result["failed"].append(unit)
            continue

        # Only confirmed stops of previously active
        # services may authorize future recovery.
        if initial == "active":
            result["confirmed"].append(unit)

    result["after"] = {
        unit: service_status(backend, unit)
        for unit in group["units"]
    }

    for unit in order:
        if (
            result["after"][unit] != "inactive"
            and unit not in result["failed"]
        ):
            result["failed"].append(unit)

    return result


def require_safe(group, assess, active, paused):
    if paused() is not False:
        raise MountError("Recovery paused.")

    current = assessment(group, assess)

    if current["errors"] or current["health"] == "BLOCKED":
        raise MountError("Storage protection check failed.")

    expected = {
        unit: "active" if unit in active else "inactive"
        for unit in group["units"]
    }

    if current["services"] != expected:
        raise MountError("Unexpected service state.")

    health = (
        "IDLE" if not active
        else "HEALTHY" if len(active) == len(group["units"])
        else "PARTIAL"
    )

    if current["health"] != health:
        raise MountError("Inconsistent group assessment.")


def rollback(backend, attempted):
    failed = []

    for unit in reversed(attempted):
        if service_status(backend, unit) == "inactive":
            continue

        try:
            backend.stop(unit)

            if service_status(backend, unit) != "inactive":
                raise MountError("Rollback not confirmed.")

        except ACTION_ERRORS:
            failed.append(unit)

    return failed


def start_recovery(
    group,
    order,
    assess,
    backend,
    *,
    paused,
    apply=False,
):
    """Execute an authorized, ordered recovery plan.

    The caller must consume the recovery authorization
    before invoking this function with apply=True.
    """

    order = tuple(order)

    expected = tuple(
        unit for unit in group["units"] if unit in order
    )

    result = {
        "dry_run": not apply,
        "planned": list(order),
        "started": [],
        "rollback_failed": [],
        "ok": False,
        "reason": None,
    }

    if (
        not group["auto_recovery"]
        or not order
        or order != expected
    ):
        result["reason"] = "INVALID_RECOVERY_PLAN"
        return result

    attempted = []
    active = set()

    try:
        require_safe(group, assess, active, paused)

        if not apply:
            result["ok"] = True
            return result

        for unit in order:
            require_safe(group, assess, active, paused)

            if service_status(backend, unit) != "inactive":
                raise MountError("Service state changed.")

            attempted.append(unit)
            backend.start(unit)

            if service_status(backend, unit) != "active":
                raise MountError("Start not confirmed.")

            active.add(unit)

            require_safe(group, assess, active, paused)

            result["started"].append(unit)

        result["ok"] = True

    except ACTION_ERRORS:
        result["reason"] = "RECOVERY_FAILED"
        result["rollback_failed"] = rollback(
            backend, attempted
        )

    return result
