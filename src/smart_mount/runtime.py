"""Integrated storage protection and recovery orchestration."""

import time

from .executor import (
    ACTION_ERRORS,
    start_recovery,
    stop_blocked,
)
from .guard import evaluate, probe_volume
from .recovery import (
    RecoveryState,
    record_stopped,
    recovery_plan,
    reset_confirmation,
)
from .state import config_fingerprint, StateError


class StateUnavailable(StateError):
    """Runtime state cannot be used safely."""


def state_io(operation, *args):
    try:
        return operation(*args)
    except (StateError, OSError) as exc:
        raise StateUnavailable(
            "Runtime state unavailable."
        ) from exc


class RuntimeEngine:

    def __init__(
        self,
        config,
        backend,
        *,
        verify_bind=None,
        probe=probe_volume,
        paused=lambda name: False,
        clock=time.monotonic,
    ):
        self.config = config
        self.backend = backend
        self.verify_bind = verify_bind
        self.probe = probe
        self.paused = paused
        self.clock = clock

    def preview(self):
        """Read-only assessment without persistent state changes."""

        return evaluate(
            self.config,
            status=self.backend.status,
            verify_bind=self.verify_bind,
            probe=self.probe,
        )

    def assess_group(self, group):
        scoped = {
            "volumes": {
                name: self.config["volumes"][name]
                for name in group["volumes"]
            },
            "groups": [group],
        }

        return evaluate(
            scoped,
            status=self.backend.status,
            verify_bind=self.verify_bind,
            probe=self.probe,
        )["groups"][0]

    def is_paused(self, name):
        try:
            return self.paused(name) is not False
        except ACTION_ERRORS:
            return True

    def cycle(self, *, store=None, apply=False):
        """Run one cycle using an explicitly authorized backend.

        Mutating operation requires a locked StateStore.
        Recovery authorization is persisted as consumed
        before a start operation is attempted.
        """

        if not apply:
            return {
                "dry_run": True,
                "assessment": self.preview(),
            }

        if store is None:
            raise StateError("Locked runtime state required.")

        if store.fingerprint != config_fingerprint(self.config):
            raise StateError("Runtime configuration mismatch.")

        store._require_lock()

        try:
            if state_io(store.recovery_inhibited):
                return self._degraded(store)

            return self._cycle_locked(store)

        except StateUnavailable:
            return self._degraded(store)

    def _degraded(self, store):
        """Retain protective stops, prohibit all recovery."""

        store._require_lock()

        try:
            store.inhibit_recovery()
            persisted = store.recovery_inhibited()
        except (StateError, OSError):
            persisted = False

        reports = []

        for group in self.config["groups"]:

            def assess():
                return self.assess_group(group)

            current = assess()

            report = {
                "name": group["name"],
                "health_before": current["health"],
                "action": "none",
                "recovery_pending": [],
            }

            if current["health"] == "BLOCKED":
                report["action"] = "protect"
                report["result"] = stop_blocked(
                    group,
                    assess,
                    self.backend,
                    apply=True,
                )

            report["health_after"] = assess()["health"]
            reports.append(report)

        return {
            "dry_run": False,
            "degraded": True,
            "recovery_disabled": True,
            "latch_persisted": persisted,
            "reason": "STATE_UNAVAILABLE_OR_INHIBITED",
            "groups": reports,
            "assessment": self.preview(),
            "ok": False,
        }

    def _cycle_locked(self, store):
        states = state_io(store.load)
        reports = []

        def persist(name, state):
            if state == RecoveryState():
                states.pop(name, None)
            else:
                states[name] = state

            state_io(store.save, states)

        for group in self.config["groups"]:
            name = group["name"]
            state = states.get(name, RecoveryState())

            def assess():
                return self.assess_group(group)

            current = assess()
            paused = self.is_paused(name)

            if paused or not group["auto_recovery"]:
                state = RecoveryState()

            report = {
                "name": name,
                "health_before": current["health"],
                "action": "none",
            }

            if current["health"] == "BLOCKED":
                state = reset_confirmation(state)

                if current["stop_order"]:
                    # Revoke older recovery authorizations.
                    persist(name, RecoveryState())

                    result = stop_blocked(
                        group,
                        assess,
                        self.backend,
                        apply=True,
                    )

                    state = RecoveryState()

                    if (
                        not result["failed"]
                        and result["before"]["errors"]
                        and all(
                            error["code"] == "VOLUME_UNAVAILABLE"
                            for error in result["before"]["errors"]
                        )
                        and all(
                            value == "active"
                            for value in result["before"]["services"].values()
                        )
                        and set(result["confirmed"]) == set(group["units"])
                        and not self.is_paused(name)
                        and all(
                            value == "inactive"
                            for value in result["after"].values()
                        )
                    ):
                        state = record_stopped(
                            group,
                            state,
                            before=result["before"],
                            after=result["after"],
                            confirmed_stops=result["confirmed"],
                        )

                    persist(name, state)

                    report["action"] = "protect"
                    report["result"] = result

                else:
                    persist(name, state)

            elif current["health"] == "IDLE":
                state, order = recovery_plan(
                    group,
                    current,
                    state,
                    self.config["runtime"],
                    now=self.clock(),
                    paused=paused,
                )

                # Consume authorization before executing it.
                persist(name, state)

                if order:
                    report["action"] = "recover"

                    report["result"] = start_recovery(
                        group,
                        order,
                        assess,
                        self.backend,
                        paused=lambda: self.is_paused(name),
                        apply=True,
                    )

            else:
                # A healthy or partially active group may
                # have been started manually.
                persist(name, RecoveryState())

            report["health_after"] = assess()["health"]
            report["recovery_pending"] = list(
                states.get(name, RecoveryState()).pending
            )

            reports.append(report)

        final = self.preview()

        return {
            "dry_run": False,
            "groups": reports,
            "assessment": final,
            "ok": (
                final["safe"]
                and all(
                    not item.get("result", {}).get("failed")
                    and item.get("result", {}).get("ok", True)
                    for item in reports
                )
            ),
        }
