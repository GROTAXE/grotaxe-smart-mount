import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from smart_mount.config import load_config
from smart_mount.identity import MountError
from smart_mount.runtime import RuntimeEngine
from smart_mount.state import locked_state, StateError


EXAMPLE = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "smart-mount.toml"
)

BOOT = "11111111-2222-3333-4444-555555555555"


class FakeBackend:

    def __init__(self, units):
        self.states = dict.fromkeys(units, "active")
        self.actions = []
        self.fail_stop = set()
        self.fail_start = set()

    def status(self, unit):
        return self.states[unit]

    def stop(self, unit):
        self.actions.append(("stop", unit))

        if unit in self.fail_stop:
            raise OSError("Simulated stop failure")

        self.states[unit] = "inactive"

    def start(self, unit):
        self.actions.append(("start", unit))

        if unit in self.fail_start:
            raise OSError("Simulated start failure")

        self.states[unit] = "active"


class RuntimeTests(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        self.directory = Path(temp.name)
        self.directory.chmod(0o700)

        self.config = load_config(EXAMPLE)
        self.group = self.config["groups"][0]
        self.group["auto_recovery"] = True
        self.units = self.group["units"]

        self.backend = FakeBackend(self.units)

        self.unsafe = False
        self.pause = False
        self.now = 100

        self.engine = RuntimeEngine(
            self.config,
            self.backend,
            verify_bind=lambda *args: True,
            probe=self.probe,
            paused=lambda name: self.pause,
            clock=lambda: self.now,
        )

    def probe(self, volume):
        if self.unsafe:
            raise MountError("Simulated storage failure")

        return {}

    def store(self):
        return locked_state(
            self.directory,
            self.config,
            boot_id=BOOT,
        )

    def step(self, now=100):
        self.now = now

        with self.store() as store:
            return self.engine.cycle(
                store=store,
                apply=True,
            )

    def saved(self):
        with self.store() as store:
            return store.load()

    def outage(self):
        self.unsafe = True
        result = self.step()
        self.unsafe = False
        return result

    def test_preview_no_mutation(self):
        self.unsafe = True

        result = self.engine.cycle()

        self.assertTrue(result["dry_run"])
        self.assertFalse(result["assessment"]["safe"])
        self.assertEqual(self.backend.actions, [])
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_full_recovery_cycle(self):
        result = self.outage()

        self.assertEqual(
            result["groups"][0]["action"], "protect"
        )

        self.assertEqual(
            self.backend.actions,
            [("stop", unit) for unit in self.units[::-1]],
        )

        self.step(130)
        self.assertEqual(len(self.backend.actions), 2)

        result = self.step(160)

        self.assertTrue(result["ok"])
        self.assertEqual(
            result["groups"][0]["action"], "recover"
        )

        self.assertEqual(
            self.backend.actions[-2:],
            [("start", unit) for unit in self.units],
        )

        self.assertEqual(self.saved(), {})

    def test_manually_stopped_group_not_started(self):
        self.backend.states = dict.fromkeys(
            self.units, "inactive"
        )

        self.step(100)
        self.step(130)

        self.assertEqual(self.backend.actions, [])

    def test_pause_revokes_recovery(self):
        self.outage()
        self.step(130)

        self.pause = True
        self.step(160)

        self.pause = False
        self.step(190)
        self.step(220)

        self.assertEqual(len(self.backend.actions), 2)
        self.assertEqual(self.saved(), {})

    def test_stop_failure_revokes_authorization(self):
        self.backend.fail_stop.add(self.units[1])

        result = self.outage()

        self.assertFalse(result["ok"])
        self.assertEqual(self.saved(), {})

    def test_start_failure_rolls_back(self):
        self.outage()
        self.step(130)

        self.backend.fail_start.add(self.units[1])

        result = self.step(160)

        self.assertFalse(result["ok"])
        self.assertEqual(self.saved(), {})
        self.assertEqual(
            self.backend.states,
            dict.fromkeys(self.units, "inactive"),
        )

    def test_corrupt_state_preserves_protection(self):
        with self.store() as store:
            store.save({})

        state_file = self.directory / "state.json"
        state_file.write_text("{invalid")

        self.unsafe = True
        result = self.step()

        self.assertTrue(result["degraded"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["latch_persisted"])

        self.assertEqual(
            self.backend.actions,
            [("stop", unit) for unit in self.units[::-1]],
        )

        self.assertEqual(state_file.read_text(), "{invalid")

    def test_write_failure_preserves_protection(self):
        self.unsafe = True

        with self.store() as store:
            with patch.object(
                store,
                "save",
                side_effect=OSError("Simulated write failure"),
            ):
                result = self.engine.cycle(
                    store=store, apply=True
                )

        self.assertTrue(result["degraded"])
        self.assertTrue(result["latch_persisted"])
        self.assertEqual(
            self.backend.actions,
            [("stop", unit) for unit in self.units[::-1]],
        )

    def test_write_failure_prohibits_recovery(self):
        self.outage()
        self.step(130)
        self.now = 160

        with self.store() as store:
            with patch.object(
                store,
                "save",
                side_effect=OSError("Simulated write failure"),
            ):
                result = self.engine.cycle(
                    store=store, apply=True
                )

        self.assertTrue(result["recovery_disabled"])
        self.assertEqual(len(self.backend.actions), 2)

        self.step(190)
        self.step(220)

        self.assertEqual(len(self.backend.actions), 2)

    def test_latch_survives_valid_state(self):
        self.outage()

        with self.store() as store:
            store.inhibit_recovery()
            self.assertTrue(store.recovery_inhibited())

        self.step(130)
        self.step(160)

        self.assertEqual(len(self.backend.actions), 2)

    def test_expired_lock_prohibits_actions(self):
        with self.store() as store:
            pass

        self.unsafe = True

        with self.assertRaises(StateError):
            self.engine.cycle(store=store, apply=True)

        self.assertEqual(self.backend.actions, [])

    def test_config_change_revokes_authorization(self):
        self.outage()

        self.config["runtime"]["interval_seconds"] = 60

        self.step(160)
        self.step(220)

        self.assertEqual(len(self.backend.actions), 2)
        self.assertEqual(self.saved(), {})

    def test_manual_start_revokes_pending_recovery(self):
        self.outage()

        self.backend.states[self.units[0]] = "active"

        self.step(130)

        self.assertEqual(self.saved(), {})

    def test_authorization_consumed_before_start(self):
        self.outage()
        self.step(130)

        self.now = 160
        original_start = self.backend.start

        with self.store() as store:

            def checked_start(unit):
                self.assertEqual(store.load(), {})
                original_start(unit)

            with patch.object(
                self.backend,
                "start",
                side_effect=checked_start,
            ):
                result = self.engine.cycle(
                    store=store,
                    apply=True,
                )

        self.assertTrue(result["ok"])

    def test_namespace_failure_never_arms_recovery(self):
        self.engine.verify_bind = lambda *args: False

        result = self.step(100)

        self.assertEqual(
            result["groups"][0]["action"], "protect"
        )
        self.assertEqual(
            self.backend.actions,
            [("stop", unit) for unit in self.units[::-1]],
        )
        self.assertEqual(self.saved(), {})

        self.engine.verify_bind = lambda *args: True

        self.step(130)
        self.step(160)

        self.assertEqual(len(self.backend.actions), 2)

    def test_partial_outage_never_arms_recovery(self):
        self.backend.states[self.units[1]] = "inactive"

        self.outage()

        self.assertEqual(
            self.backend.actions,
            [("stop", self.units[0])],
        )

        self.assertEqual(self.saved(), {})

        self.step(130)
        self.step(160)

        self.assertEqual(len(self.backend.actions), 1)

    def test_unknown_state_never_arms_recovery(self):
        self.backend.states[self.units[1]] = "unknown"

        self.outage()

        self.assertEqual(self.saved(), {})

        self.step(130)
        self.step(160)

        self.assertFalse(
            any(
                action == "start"
                for action, unit in self.backend.actions
            )
        )

    def test_failed_inhibit_prohibits_current_recovery(self):
        self.outage()
        self.step(130)
        self.now = 160

        with self.store() as store:
            with (
                patch.object(
                    store,
                    "save",
                    side_effect=OSError("Simulated write failure"),
                ),
                patch.object(
                    store,
                    "inhibit_recovery",
                    side_effect=OSError("Simulated latch failure"),
                ),
            ):
                result = self.engine.cycle(
                    store=store,
                    apply=True,
                )

        self.assertTrue(result["degraded"])
        self.assertTrue(result["recovery_disabled"])
        self.assertFalse(result["latch_persisted"])
        self.assertFalse(result["ok"])
        self.assertEqual(len(self.backend.actions), 2)

    def test_repeated_outage_resets_confirmation(self):
        self.outage()
        self.step(130)

        self.unsafe = True
        self.step(160)

        self.unsafe = False
        self.step(190)

        self.assertEqual(len(self.backend.actions), 2)

        self.step(220)

        self.assertEqual(len(self.backend.actions), 4)


if __name__ == "__main__":
    unittest.main()
