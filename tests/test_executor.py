import unittest

from smart_mount.executor import (
    start_recovery,
    stop_blocked,
)


class FakeBackend:

    def __init__(self, units):
        self.states = dict.fromkeys(units, "inactive")
        self.actions = []
        self.fail_start = set()
        self.fail_stop = set()

    def status(self, unit):
        return self.states[unit]

    def start(self, unit):
        self.actions.append(("start", unit))

        if unit in self.fail_start:
            raise OSError("Simulated start failure")

        self.states[unit] = "active"

    def stop(self, unit):
        self.actions.append(("stop", unit))

        if unit in self.fail_stop:
            raise OSError("Simulated stop failure")

        self.states[unit] = "inactive"


class ExecutorTests(unittest.TestCase):

    def setUp(self):
        self.units = [
            "example-api.service",
            "example-worker.service",
        ]

        self.group = {
            "name": "application",
            "units": self.units,
            "auto_recovery": True,
        }

        self.backend = FakeBackend(self.units)
        self.unsafe = False
        self.pause = False
        self.fail_after_start = False

    def assess(self):
        states = dict(self.backend.states)

        blocked = (
            self.unsafe
            or any(
                value not in ("active", "inactive")
                for value in states.values()
            )
            or (
                self.fail_after_start
                and "active" in states.values()
            )
        )

        count = list(states.values()).count("active")

        health = (
            "BLOCKED" if blocked
            else "IDLE" if count == 0
            else "HEALTHY" if count == len(states)
            else "PARTIAL"
        )

        return {
            "name": self.group["name"],
            "health": health,
            "services": states,
            "errors": (
                [{"code": "UNSAFE"}] if blocked else []
            ),
            "stop_order": [
                unit for unit in reversed(self.units)
                if states[unit] != "inactive"
            ] if blocked else [],
        }

    def recover(self, order=None, *, apply=True):
        return start_recovery(
            self.group,
            self.units if order is None else order,
            self.assess,
            self.backend,
            paused=lambda: self.pause,
            apply=apply,
        )

    def protect(self, *, apply=True):
        return stop_blocked(
            self.group,
            self.assess,
            self.backend,
            apply=apply,
        )

    def activate(self):
        self.backend.states = dict.fromkeys(
            self.units, "active"
        )

    def test_stop_dry_run(self):
        self.activate()
        self.unsafe = True

        result = self.protect(apply=False)

        self.assertEqual(result["planned"], self.units[::-1])
        self.assertEqual(self.backend.actions, [])

    def test_stop_reverse_order(self):
        self.activate()
        self.unsafe = True

        result = self.protect()

        self.assertEqual(result["confirmed"], self.units[::-1])
        self.assertEqual(
            self.backend.actions,
            [("stop", unit) for unit in self.units[::-1]],
        )

    def test_healthy_group_not_stopped(self):
        self.activate()
        self.protect()
        self.assertEqual(self.backend.actions, [])

    def test_stop_failure_continues(self):
        self.activate()
        self.unsafe = True
        self.backend.fail_stop.add(self.units[1])

        result = self.protect()

        self.assertEqual(result["failed"], [self.units[1]])
        self.assertEqual(result["confirmed"], [self.units[0]])

    def test_unknown_state_not_authorized(self):
        self.backend.states[self.units[0]] = "unknown"

        result = self.protect()

        self.assertEqual(result["confirmed"], [])
        self.assertEqual(
            self.backend.states[self.units[0]], "inactive"
        )

    def test_start_dry_run(self):
        result = self.recover(apply=False)

        self.assertTrue(result["ok"])
        self.assertEqual(self.backend.actions, [])

    def test_start_order(self):
        result = self.recover()

        self.assertTrue(result["ok"])
        self.assertEqual(
            self.backend.actions,
            [("start", unit) for unit in self.units],
        )

    def test_recovery_disabled(self):
        self.group["auto_recovery"] = False

        self.assertFalse(self.recover()["ok"])
        self.assertEqual(self.backend.actions, [])

    def test_invalid_recovery_order(self):
        for order in (
            self.units[::-1],
            [self.units[0]] * 2,
            ["foreign.service"],
            [],
        ):
            with self.subTest(order=order):
                self.assertFalse(self.recover(order)["ok"])

        self.assertEqual(self.backend.actions, [])

    def test_administrator_pause(self):
        self.pause = True

        self.assertFalse(self.recover()["ok"])
        self.assertEqual(self.backend.actions, [])

    def test_unsafe_storage(self):
        self.unsafe = True

        self.assertFalse(self.recover()["ok"])
        self.assertEqual(self.backend.actions, [])

    def test_unexpected_active_service(self):
        self.backend.states[self.units[0]] = "active"

        self.assertFalse(self.recover()["ok"])
        self.assertEqual(self.backend.actions, [])

    def test_start_failure_rolls_back(self):
        self.backend.fail_start.add(self.units[1])

        result = self.recover()

        self.assertFalse(result["ok"])
        self.assertEqual(result["rollback_failed"], [])
        self.assertEqual(
            self.backend.states,
            dict.fromkeys(self.units, "inactive"),
        )

    def test_post_start_validation_failure(self):
        self.fail_after_start = True

        result = self.recover()

        self.assertFalse(result["ok"])
        self.assertEqual(
            self.backend.actions,
            [
                ("start", self.units[0]),
                ("stop", self.units[0]),
            ],
        )

    def test_start_timeout_after_effect_rolls_back(self):
        import subprocess
        from unittest.mock import patch

        original = self.backend.start

        def delayed_start(unit):
            original(unit)

            if unit == self.units[1]:
                raise subprocess.TimeoutExpired(
                    ["synthetic-start"], 10
                )

        with patch.object(
            self.backend,
            "start",
            side_effect=delayed_start,
        ):
            result = self.recover()

        self.assertFalse(result["ok"])
        self.assertEqual(result["rollback_failed"], [])

        self.assertEqual(
            self.backend.actions,
            [
                ("start", self.units[0]),
                ("start", self.units[1]),
                ("stop", self.units[1]),
                ("stop", self.units[0]),
            ],
        )

        self.assertEqual(
            self.backend.states,
            dict.fromkeys(self.units, "inactive"),
        )

    def test_stop_timeout_not_authorized(self):
        import subprocess
        from unittest.mock import patch

        self.activate()
        self.unsafe = True

        original = self.backend.stop

        def delayed_stop(unit):
            original(unit)

            if unit == self.units[1]:
                raise subprocess.TimeoutExpired(
                    ["synthetic-stop"], 10
                )

        with patch.object(
            self.backend,
            "stop",
            side_effect=delayed_stop,
        ):
            result = self.protect()

        self.assertEqual(
            result["failed"], [self.units[1]]
        )
        self.assertEqual(
            result["confirmed"], [self.units[0]]
        )

    def test_pause_during_recovery_rolls_back(self):
        from unittest.mock import patch

        original = self.backend.start

        def start_and_pause(unit):
            original(unit)
            self.pause = True

        with patch.object(
            self.backend,
            "start",
            side_effect=start_and_pause,
        ):
            result = self.recover()

        self.assertFalse(result["ok"])
        self.assertEqual(result["rollback_failed"], [])

        self.assertEqual(
            self.backend.actions,
            [
                ("start", self.units[0]),
                ("stop", self.units[0]),
            ],
        )

    def test_rollback_failure_reported(self):
        self.fail_after_start = True
        self.backend.fail_stop.add(self.units[0])

        result = self.recover()

        self.assertFalse(result["ok"])
        self.assertEqual(
            result["rollback_failed"], [self.units[0]]
        )


if __name__ == "__main__":
    unittest.main()
