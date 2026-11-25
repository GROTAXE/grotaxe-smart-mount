"""Conservative recovery planning without system mutations."""

import math
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class RecoveryState:
    pending: tuple = ()
    confirmations: int = 0
    last_success: float | None = None


def reset_confirmation(state):
    return replace(
        state,
        confirmations=0,
        last_success=None,
    )


def record_stopped(
    group,
    state,
    *,
    before,
    after,
    confirmed_stops,
):
    """Record only confirmed, guard-initiated service stops.

    confirmed_stops must originate from the trusted executor,
    not merely from an observed inactive service.
    """

    if not group["auto_recovery"]:
        return RecoveryState()

    if (
        before["name"] != group["name"]
        or before["health"] != "BLOCKED"
    ):
        return state

    eligible = {
        unit
        for unit in confirmed_stops
        if unit in group["units"]
        and unit in before["stop_order"]
        and before["services"].get(unit) == "active"
        and after.get(unit) == "inactive"
    }

    if not eligible:
        return state

    pending = set(state.pending) | eligible

    return RecoveryState(
        pending=tuple(
            unit
            for unit in group["units"]
            if unit in pending
        ),
    )


def recovery_plan(
    group,
    assessment,
    state,
    runtime,
    *,
    now,
    paused=False,
):
    """Return updated state and a one-shot advisory start plan."""

    if paused or not group["auto_recovery"]:
        return RecoveryState(), ()

    if not state.pending:
        return RecoveryState(), ()

    if not set(state.pending) <= set(group["units"]):
        return RecoveryState(), ()

    services = assessment["services"]

    if (
        assessment["name"] != group["name"]
        or assessment["health"] != "IDLE"
        or assessment["errors"]
        or set(services) != set(group["units"])
        or any(
            status != "inactive"
            for status in services.values()
        )
    ):
        return reset_confirmation(state), ()

    if (
        type(now) not in (int, float)
        or not math.isfinite(now)
        or now < 0
    ):
        return reset_confirmation(state), ()

    interval = runtime["interval_seconds"]
    required = runtime["recovery_confirmations"]
    previous = state.last_success

    if (
        previous is None
        or now < previous
        or now - previous > interval * 3
    ):
        return replace(
            state,
            confirmations=1,
            last_success=now,
        ), ()

    if now - previous < interval:
        return state, ()

    updated = replace(
        state,
        confirmations=state.confirmations + 1,
        last_success=now,
    )

    if updated.confirmations < required:
        return updated, ()

    order = tuple(
        unit
        for unit in group["units"]
        if unit in updated.pending
    )

    # Consume authorization when issuing the plan.
    # The future executor must revalidate before starting.
    return RecoveryState(), order
