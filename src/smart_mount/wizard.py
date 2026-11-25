"""Interactive, unprivileged configuration preparation."""

import argparse
import json
import os
import sys
import tempfile

from pathlib import Path

from . import cli
from .config import ConfigError, validate
from .terminal import Terminal
from .trusted_config import decode_config, MAX_SIZE


def read_template(path):
    with Path(path).open("rb") as handle:
        data = handle.read(MAX_SIZE + 1)

    decode_config(data)
    return data


def quote(value):
    return json.dumps(value, ensure_ascii=False)


def render_config(raw):
    validate(raw)

    lines = [
        "# GROTAXE SMART MOUNT",
        "# Locally generated configuration",
        "schema_version = 1",
        "",
        "[runtime]",
        "interval_seconds = 30",
        "recovery_confirmations = 2",
    ]

    for volume in raw["volumes"]:
        lines.extend(["", "[[volumes]]"])

        for key in ("name", "target", "uuid", "mode"):
            lines.append(f"{key} = {quote(volume[key])}")

        if volume.get("fstype"):
            lines.append(
                "fstype = " + quote(volume["fstype"])
            )

    for group in raw.get("groups", []):
        lines.extend([
            "",
            "[[groups]]",
            "name = " + quote(group["name"]),
            "volumes = " + quote(group["volumes"]),
            "units = " + quote(group["units"]),
            "auto_recovery = false",
        ])

    data = ("\n".join(lines) + "\n").encode("utf-8")

    decode_config(data)
    return data


def yes_no(ask, prompt):
    while True:
        answer = ask(prompt + " [y/N]: ").strip().lower()

        if answer in ("", "n", "no"):
            return False

        if answer in ("y", "yes"):
            return True


def manual_config(ask):
    raw = {
        "schema_version": 1,
        "volumes": [],
        "groups": [],
    }

    while True:
        volume = {
            "name": ask("Volume name: ").strip(),
            "target": ask("Absolute mountpoint: ").strip(),
            "uuid": ask("Filesystem UUID: ").strip(),
            "mode": ask("Access mode [rw]: ").strip() or "rw",
        }

        fstype = ask(
            "Filesystem type [optional]: "
        ).strip()

        if fstype:
            volume["fstype"] = fstype

        validate({
            "schema_version": 1,
            "volumes": raw["volumes"] + [volume],
        })

        raw["volumes"].append(volume)

        if not yes_no(ask, "Register another volume?"):
            break

    while yes_no(ask, "Register a service group?"):
        group = {
            "name": ask("Group name: ").strip(),
            "volumes": [
                item.strip()
                for item in ask(
                    "Volume names, comma separated: "
                ).split(",")
            ],
            "units": [
                item.strip()
                for item in ask(
                    "Systemd services, comma separated: "
                ).split(",")
            ],
            "auto_recovery": False,
        }

        raw["groups"].append(group)
        validate(raw)

    return render_config(raw)


def save_new(path, data):
    """Publish a validated file without replacing existing files."""

    decode_config(data)

    path = Path(path)

    if not path.is_absolute():
        raise ConfigError("Output path must be absolute.")

    parent = path.parent

    if parent.resolve(strict=True) != parent:
        raise ConfigError("Noncanonical output directory.")

    if not parent.is_dir():
        raise ConfigError("Output directory unavailable.")

    fd, temporary = tempfile.mkstemp(
        prefix=".smart-mount-",
        dir=parent,
    )

    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), 0o600)

            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

        # Atomic publication; fails if destination exists.
        os.link(
            temporary,
            path,
            follow_symlinks=False,
        )

    finally:
        os.unlink(temporary)


def preview(ui, data):
    config = decode_config(data)

    ui.heading("CONFIGURATION PLAN")

    ui.field("SCHEMA", config["schema_version"])
    ui.field("VOLUMES", len(config["volumes"]))
    ui.field("SERVICE GROUPS", len(config["groups"]))

    ui.heading("STORAGE")

    for volume in config["volumes"].values():
        ui.field(volume["name"], volume["target"])
        ui.field("ACCESS", volume["mode"])

    ui.heading("SERVICE PROTECTION")

    for group in config["groups"]:
        ui.field("GROUP", group["name"])

        for unit in group["units"]:
            ui.field("SERVICE", unit)

        ui.field(
            "AUTO RECOVERY",
            "enabled" if group["auto_recovery"] else "disabled",
        )

    ui.line()
    ui.field("SYSTEM CHANGES", "none")


def menu(ui, ask):
    while True:
        ui.banner("INSTALLATION WIZARD")
        ui.heading("MAIN MENU / INSTALLATION")

        for option, label in (
            ("01", "Automatic configuration"),
            ("02", "Manual configuration"),
            ("03", "System diagnostics"),
            ("04", "About Grotaxe Smart Mount"),
            ("Q", "Exit"),
        ):
            ui.menu_item(option, label)

        ui.emit()
        ui.line()

        choice = ask(
            ui.paint("SELECT OPTION > ", "green")
        ).strip().lower()

        if choice in ("1", "01"):
            return read_template(
                ask("TOML configuration path: ").strip()
            )

        if choice in ("2", "02"):
            return manual_config(ask)

        if choice in ("3", "03"):
            cli.main(["doctor"])

        elif choice in ("4", "04"):
            cli.main(["about"])

        elif choice == "q":
            return None


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="smart-mount-wizard",
        description="Prepare Smart Mount configuration",
    )

    mode = parser.add_mutually_exclusive_group()

    mode.add_argument("--config")
    mode.add_argument("--manual", action="store_true")

    parser.add_argument("--output")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--plain", action="store_true")

    args = parser.parse_args(argv)

    ui = Terminal(plain=args.plain)
    interactive = sys.stdin.isatty()

    try:
        if args.config:
            data = read_template(args.config)

        elif not interactive:
            raise ConfigError("Interactive terminal required.")

        elif args.manual:
            ui.banner("INSTALLATION WIZARD")
            ui.heading("MANUAL CONFIGURATION")
            data = manual_config(input)

        else:
            data = menu(ui, input)

        if data is None:
            ui.status(True, "Cancelled")
            return 0

        preview(ui, data)

        if args.dry_run:
            ui.status(True, "Dry run complete")
            return 0

        output = args.output

        if not output and interactive:
            output = input(
                "Absolute output file path: "
            ).strip()

        if not output:
            raise ConfigError("Output path required.")

        if not args.yes:
            if not interactive:
                raise ConfigError("Confirmation required.")

            if not yes_no(input, "Save configuration?"):
                ui.status(True, "Cancelled")
                return 0

        save_new(output, data)

        ui.status(True, "Configuration saved")
        ui.field("SYSTEM INSTALLATION", "not performed")

        return 0

    except (KeyboardInterrupt, EOFError):
        ui.status(False, "Cancelled")
        return 130

    except (ConfigError, OSError, UnicodeError, ValueError):
        ui.status(
            False,
            "Configuration preparation failed.",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
