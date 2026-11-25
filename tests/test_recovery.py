import unittest

from smart_mount.recovery import (
    RecoveryState,
    record_stopped,
    recovery_plan,
)


class RecoveryTests(unittest.TestCase):

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

        self.runtime = {
            "interval_seconds": 30,
            "recovery_confirmations": 2,
        }

        self.blocked = {
            "name": "application",
            "health": "BLOCKED",
            "services": dict.fromkeys(self.units, "active"),
            "stop_order": self.units[::-1],
            "errors": [{"code": "VOLUME_UNAVAILABLE"}],
        }

        self.idle = {
            "name": "application",
            "health": "IDLE",
            "services": dict.fromkeys(self.units, "inactive"),
            "stop_order": [],
            "errors": [],
        }

        self.state = self.record(self.units)

    def record(self, confirmed):
        return record_stopped(
            self.group,
            RecoveryState(),
            before=self.blocked,
            after=self.idle["services"],
            confirmed_stops=confirmed,
        )

    def step(self, now, *, assessment=None, paused=False):
        self.state, order = recovery_plan(
            self.group,
            assessment if assessment is not None else self.idle,
            self.state,
            self.runtime,
            now=now,
            paused=paused,
        )

        return order

    def test_confirmed_stops_recorded(self):
        self.assertEqual(
            self.state.pending, tuple(self.units)
        )

    def test_no_authorization(self):
        self.state = RecoveryState()
        self.assertEqual(self.step(100), ())
        self.assertEqual(self.step(130), ())

    def test_disabled_recovery(self):
        self.group["auto_recovery"] = False
        self.assertEqual(self.step(100), ())
        self.assertFalse(self.state.pending)

    def test_manual_stop_not_recorded(self):
        self.state = self.record([])
        self.assertFalse(self.state.pending)

    def test_previously_inactive_service_excluded(self):
        self.blocked["services"][self.units[1]] = "inactive"
        self.state = self.record(self.units)

        self.assertEqual(
            self.state.pending, (self.units[0],)
        )

    def test_unknown_service_excluded(self):
        self.blocked["services"][self.units[1]] = "unknown"
        self.state = self.record(self.units)

        self.assertEqual(
            self.state.pending, (self.units[0],)
        )

    def test_two_confirmations(self):
        self.assertEqual(self.step(100), ())
        self.assertEqual(
            self.step(130), tuple(self.units)
        )

    def test_minimum_interval(self):
        self.step(100)
        self.assertEqual(self.step(101), ())
        self.assertEqual(self.state.confirmations, 1)
        self.assertEqual(
            self.step(130), tuple(self.units)
        )

    def test_stale_confirmation(self):
        self.step(100)
        self.assertEqual(self.step(200), ())
        self.assertEqual(self.state.confirmations, 1)

    def test_clock_rollback(self):
        self.step(100)
        self.assertEqual(self.step(90), ())
        self.assertEqual(self.state.confirmations, 1)

    def test_pause_revokes_authorization(self):
        self.step(100)
        self.assertEqual(self.step(130, paused=True), ())
        self.assertFalse(self.state.pending)
        self.assertEqual(self.step(160), ())

    def test_failure_resets_confirmation(self):
        self.step(100)
        self.step(130, assessment=self.blocked)
        self.assertEqual(self.state.confirmations, 0)
        self.assertEqual(self.step(160), ())

    def test_partial_group_not_restarted(self):
        partial = {
            **self.idle,
            "health": "PARTIAL",
            "services": {
                self.units[0]: "active",
                self.units[1]: "inactive",
            },
        }

        self.step(100)
        self.assertEqual(
            self.step(130, assessment=partial), ()
        )

    def test_recovery_plan_is_one_shot(self):
        self.step(100)
        self.assertEqual(
            self.step(130), tuple(self.units)
        )
        self.assertEqual(self.step(160), ())
        self.assertFalse(self.state.pending)


if __name__ == "__main__":
    unittest.main()
