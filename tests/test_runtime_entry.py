import contextlib
import io
import json
import unittest

from pathlib import Path
from unittest.mock import patch

from smart_mount.identity import MountError
from smart_mount.install_plan import MODULES
from smart_mount.runtime_entry import (
    main,
    protection_policy,
    require_installed,
    run_once,
)
from smart_mount.state import LockBusy


ROOT = Path(__file__).resolve().parents[1]

CONFIG = {
    "groups": [{
        "name": "application",
        "units": ["example.service"],
        "auto_recovery": True,
    }],
}

ASSESSMENT = {
    "safe": True,
    "volumes": {"storage": True},
    "groups": [{"health": "HEALTHY"}],
}


class RuntimeEntryTests(unittest.TestCase):

    def test_recovery_disabled(self):
        policy = protection_policy(CONFIG)

        self.assertFalse(
            policy["groups"][0]["auto_recovery"]
        )

        self.assertTrue(
            CONFIG["groups"][0]["auto_recovery"]
        )

    def test_self_protection_rejected(self):
        config = {
            "groups": [{
                "name": "example",
                "units": ["grotaxe-smart-mount.service"],
                "auto_recovery": False,
            }],
        }

        from smart_mount.config import ConfigError

        with self.assertRaises(ConfigError):
            protection_policy(config)

    def test_mixed_self_protection_rejected(self):
        config = {
            "groups": [
                CONFIG["groups"][0],
                {
                    "name": "other",
                    "units": [
                        "example-worker.service",
                        "grotaxe-smart-mount.service",
                    ],
                    "auto_recovery": True,
                },
            ],
        }

        from smart_mount.config import ConfigError

        with self.assertRaises(ConfigError):
            protection_policy(config)

    def test_self_protection_blocks_backend_creation(self):
        config = {
            "groups": [{
                "name": "example",
                "units": ["grotaxe-smart-mount.service"],
                "auto_recovery": False,
            }],
        }

        from smart_mount.config import ConfigError

        with (
            patch(
                "smart_mount.runtime_entry.load_trusted_config",
                return_value=config,
            ),
            patch(
                "smart_mount.runtime_entry.SystemBackend"
            ) as backend,
        ):
            with self.assertRaises(ConfigError):
                run_once()

        backend.assert_not_called()

    def test_nonroot_apply_rejected(self):
        with patch(
            "smart_mount.runtime_entry.os.geteuid",
            return_value=1000,
        ):
            with self.assertRaises(MountError):
                require_installed()

    def test_development_checkout_rejected(self):
        with patch(
            "smart_mount.runtime_entry.os.geteuid",
            return_value=0,
        ):
            with self.assertRaises(MountError):
                require_installed()

    def test_preview_no_mutation(self):
        with (
            patch(
                "smart_mount.runtime_entry.load_trusted_config",
                return_value=CONFIG,
            ),
            patch(
                "smart_mount.runtime_entry.SystemBackend"
            ) as backend,
            patch(
                "smart_mount.runtime_entry.RuntimeEngine"
            ) as engine,
            patch(
                "smart_mount.runtime_entry.locked_state"
            ) as store,
        ):
            engine.return_value.cycle.return_value = {
                "assessment": ASSESSMENT,
            }

            result = run_once()

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "preview")
        self.assertTrue(result["recovery_disabled"])
        self.assertFalse(
            backend.call_args.kwargs["apply"]
        )

        store.assert_not_called()
        engine.return_value.cycle.assert_called_once_with()

    def test_apply_uses_locked_state(self):
        with (
            patch(
                "smart_mount.runtime_entry.require_installed"
            ) as trusted,
            patch(
                "smart_mount.runtime_entry.load_trusted_config",
                return_value=CONFIG,
            ),
            patch(
                "smart_mount.runtime_entry.SystemBackend"
            ) as backend,
            patch(
                "smart_mount.runtime_entry.RuntimeEngine"
            ) as engine,
            patch(
                "smart_mount.runtime_entry.locked_state"
            ) as store,
        ):
            engine.return_value.cycle.return_value = {
                "ok": True,
                "assessment": ASSESSMENT,
            }

            result = run_once(apply=True)

        trusted.assert_called_once()
        self.assertTrue(result["ok"])

        self.assertTrue(
            backend.call_args.kwargs["apply"]
        )

        policy = backend.call_args.args[0]

        self.assertFalse(
            policy["groups"][0]["auto_recovery"]
        )

        engine.return_value.cycle.assert_called_once_with(
            store=store.return_value.__enter__.return_value,
            apply=True,
        )

    def test_default_cli_is_preview(self):
        with patch(
            "smart_mount.runtime_entry.run_once",
            return_value={"ok": True},
        ) as run:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([]), 0)

        run.assert_called_once_with(apply=False)

    def test_lock_contention_exit_code(self):
        output = io.StringIO()

        with patch(
            "smart_mount.runtime_entry.run_once",
            side_effect=LockBusy("Busy"),
        ):
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([]), 75)

        self.assertEqual(
            json.loads(output.getvalue())["reason"],
            "RUNTIME_LOCK_BUSY",
        )

    def test_error_output_is_sanitized(self):
        output = io.StringIO()

        with patch(
            "smart_mount.runtime_entry.run_once",
            side_effect=MountError("Sensitive details"),
        ):
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([]), 1)

        self.assertNotIn(
            "Sensitive details",
            output.getvalue(),
        )

    def test_runtime_in_payload(self):
        self.assertIn("runtime_entry.py", MODULES)

    def test_service_template(self):
        service = (
            ROOT / "packaging/systemd"
            / "grotaxe-smart-mount.service"
        ).read_text()

        self.assertIn("Type=oneshot", service)
        self.assertIn("RuntimeDirectoryMode=0700", service)
        self.assertIn("RuntimeDirectoryPreserve=yes", service)
        self.assertIn("/usr/bin/python3 -I -B", service)
        self.assertIn("--apply-protection", service)
        self.assertNotIn("[Install]", service)

    def test_timer_template(self):
        timer = (
            ROOT / "packaging/systemd"
            / "grotaxe-smart-mount.timer"
        ).read_text()

        self.assertIn("OnUnitInactiveSec=30s", timer)
        self.assertIn(
            "Unit=grotaxe-smart-mount.service",
            timer,
        )
        self.assertIn("WantedBy=timers.target", timer)


if __name__ == "__main__":
    unittest.main()
