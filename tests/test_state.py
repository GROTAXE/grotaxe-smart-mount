import copy
import os
import tempfile
import unittest

from pathlib import Path

from smart_mount.recovery import RecoveryState
from smart_mount.state import (
    StateError,
    LockBusy,
    locked_state,
)


BOOT = "11111111-2222-3333-4444-555555555555"
OTHER_BOOT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class StateTests(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        self.directory = Path(temp.name)
        self.directory.chmod(0o700)

        self.config = {
            "groups": [{
                "name": "application",
                "units": [
                    "example-api.service",
                    "example-worker.service",
                ],
            }],
            "runtime": {"interval_seconds": 30},
        }

        self.states = {
            "application": RecoveryState(
                pending=("example-api.service",),
                confirmations=1,
                last_success=100.0,
            ),
        }

    def store(self, *, config=None, boot=BOOT):
        return locked_state(
            self.directory,
            self.config if config is None else config,
            boot_id=boot,
        )

    def save(self):
        with self.store() as store:
            store.save(self.states)

    def test_missing_state(self):
        with self.store() as store:
            self.assertEqual(store.load(), {})

    def test_roundtrip(self):
        self.save()

        with self.store() as store:
            self.assertEqual(store.load(), self.states)

        mode = (self.directory / "state.json").stat().st_mode
        self.assertEqual(mode & 0o777, 0o600)

    def test_lock_contention(self):
        with self.store():
            with self.assertRaises(LockBusy):
                with self.store():
                    pass

        with self.store():
            pass

    def test_unsafe_directory(self):
        self.directory.chmod(0o755)

        with self.assertRaises(StateError):
            with self.store():
                pass

    def test_symlink_directory(self):
        real = self.directory / "real"
        real.mkdir(mode=0o700)

        alias = self.directory / "alias"
        alias.symlink_to(real)

        with self.assertRaises(OSError):
            with locked_state(alias, self.config, boot_id=BOOT):
                pass

    def test_symlink_state(self):
        target = self.directory / "target"
        target.write_text("unchanged")

        (self.directory / "state.json").symlink_to(target)

        with self.store() as store:
            with self.assertRaises(OSError):
                store.load()

            with self.assertRaises(OSError):
                store.save(self.states)

        self.assertEqual(target.read_text(), "unchanged")

    def test_symlink_lock(self):
        target = self.directory / "target"
        target.touch()

        (self.directory / "runtime.lock").symlink_to(target)

        with self.assertRaises(OSError):
            with self.store():
                pass

    def test_unsafe_state_permissions(self):
        self.save()
        (self.directory / "state.json").chmod(0o644)

        with self.store() as store:
            with self.assertRaises(StateError):
                store.load()

    def test_hardlinked_state(self):
        self.save()

        os.link(
            self.directory / "state.json",
            self.directory / "alias",
        )

        with self.store() as store:
            with self.assertRaises(StateError):
                store.load()

    def test_boot_change_revokes_state(self):
        self.save()

        with self.store(boot=OTHER_BOOT) as store:
            self.assertEqual(store.load(), {})

    def test_config_change_revokes_state(self):
        self.save()

        changed = copy.deepcopy(self.config)
        changed["runtime"]["interval_seconds"] = 60

        with self.store(config=changed) as store:
            self.assertEqual(store.load(), {})

    def test_foreign_service_rejected(self):
        with self.store() as store:
            with self.assertRaises(StateError):
                store.save({
                    "application": RecoveryState(
                        pending=("foreign.service",),
                    ),
                })

    def test_corrupt_state(self):
        self.save()
        (self.directory / "state.json").write_text("{invalid")

        with self.store() as store:
            with self.assertRaises(StateError):
                store.load()

    def test_expired_lock_handle(self):
        with self.store() as store:
            pass

        with self.assertRaises(StateError):
            store.load()

        with self.assertRaises(StateError):
            store.save(self.states)


if __name__ == "__main__":
    unittest.main()
