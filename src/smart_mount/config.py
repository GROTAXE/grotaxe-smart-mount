"""Strict TOML configuration validation."""

import re
import tomllib
from pathlib import Path, PurePosixPath

from .identity import UUID_PATTERN


class ConfigError(ValueError):
    """Invalid Smart Mount configuration."""


def require(condition, message):
    if not condition:
        raise ConfigError(message)


def table(value, required, optional=()):
    require(type(value) is dict, "Expected a TOML table.")
    keys = set(value)
    require(set(required) <= keys, "Missing configuration keys.")
    require(
        keys <= set(required) | set(optional),
        "Unknown configuration keys.",
    )
    return value


def array(value):
    require(type(value) is list, "Expected an array.")
    return value


def identifier(value):
    require(
        isinstance(value, str)
        and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value),
        "Invalid configuration identifier.",
    )
    return value


def path_value(value, *, absolute=True):
    require(
        isinstance(value, str)
        and bool(value)
        and not any(ord(c) < 32 or ord(c) == 127 for c in value),
        "Invalid path.",
    )

    path = PurePosixPath(value)

    require(
        path.is_absolute() == absolute
        and ".." not in path.parts
        and not value.startswith("//")
        and str(path) == value
        and value != ".",
        "Expected a canonical path.",
    )

    return value


def access_mode(value):
    require(
        isinstance(value, str) and value in {"ro", "rw"},
        "Access mode must be ro or rw.",
    )
    return value


def integer(value, minimum, maximum):
    require(
        type(value) is int and minimum <= value <= maximum,
        "Integer setting outside permitted range.",
    )
    return value


def boolean(value):
    require(type(value) is bool, "Expected a boolean.")
    return value


def unique(values):
    require(len(values) == len(set(values)), "Duplicate entry.")
    return values


def service_name(value):
    require(
        isinstance(value, str)
        and len(value) <= 255
        and re.fullmatch(
            r"[A-Za-z0-9_][A-Za-z0-9_.:-]*"
            r"(?:@[A-Za-z0-9_.:-]+)?\.service",
            value,
        ),
        "Invalid systemd service name.",
    )
    return value


def beneath(path, parent):
    return PurePosixPath(path).is_relative_to(
        PurePosixPath(parent)
    )


def volume(raw):
    table(
        raw,
        ("name", "target", "uuid"),
        ("mode", "fstype", "fsroot", "required_dirs"),
    )

    uuid = raw["uuid"]

    require(
        isinstance(uuid, str)
        and re.fullmatch(UUID_PATTERN, uuid),
        "Invalid filesystem UUID.",
    )

    fstype = raw.get("fstype")

    if fstype is not None:
        require(
            isinstance(fstype, str)
            and re.fullmatch(r"[a-zA-Z0-9_.-]+", fstype),
            "Invalid filesystem type.",
        )

    return {
        "name": identifier(raw["name"]),
        "target": path_value(raw["target"]),
        "uuid": uuid.lower(),
        "mode": access_mode(raw.get("mode", "rw")),
        "fstype": fstype,
        "fsroot": path_value(raw.get("fsroot", "/")),
        "required_dirs": unique([
            path_value(item, absolute=False)
            for item in array(raw.get("required_dirs", []))
        ]),
    }


def bind(raw, volumes, dependencies):
    table(
        raw,
        ("volume", "source", "destination"),
        ("source_mode", "destination_mode", "marker"),
    )

    name = identifier(raw["volume"])

    require(
        name in dependencies and name in volumes,
        "Bind references an undeclared dependency.",
    )

    source = path_value(raw["source"])
    destination = path_value(raw["destination"])

    require(
        beneath(source, volumes[name]["target"]),
        "Bind source is outside the expected volume.",
    )

    require(
        not beneath(source, destination)
        and not beneath(destination, source),
        "Overlapping bind source and destination.",
    )

    marker = raw.get("marker")

    if marker is not None:
        path_value(marker, absolute=False)
        require("/" not in marker, "Invalid marker name.")

    return {
        "volume": name,
        "source": source,
        "destination": destination,
        "source_mode": access_mode(raw.get("source_mode", "ro")),
        "destination_mode": access_mode(
            raw.get("destination_mode", "rw")
        ),
        "marker": marker,
    }


def group(raw, volumes):
    table(
        raw,
        ("name", "volumes", "units"),
        ("auto_recovery", "binds"),
    )

    dependencies = unique([
        identifier(item) for item in array(raw["volumes"])
    ])

    require(
        bool(dependencies)
        and all(name in volumes for name in dependencies),
        "Unknown or empty volume dependencies.",
    )

    units = unique([
        service_name(item) for item in array(raw["units"])
    ])

    require(bool(units), "Empty service group.")

    binds = [
        bind(item, volumes, dependencies)
        for item in array(raw.get("binds", []))
    ]

    destinations = unique([
        item["destination"] for item in binds
    ])

    for index, target in enumerate(destinations):
        require(
            not any(
                beneath(target, other) or beneath(other, target)
                for other in destinations[:index]
            ),
            "Overlapping bind destinations.",
        )

    return {
        "name": identifier(raw["name"]),
        "volumes": dependencies,
        "units": units,
        "auto_recovery": boolean(
            raw.get("auto_recovery", False)
        ),
        "binds": binds,
    }


def validate(raw):
    table(
        raw,
        ("schema_version", "volumes"),
        ("runtime", "groups"),
    )

    integer(raw["schema_version"], 1, 1)

    runtime = table(
        raw.get("runtime", {}),
        (),
        ("interval_seconds", "recovery_confirmations"),
    )

    entries = [volume(item) for item in array(raw["volumes"])]

    require(bool(entries), "No volumes configured.")
    unique([item["name"] for item in entries])
    unique([item["target"] for item in entries])

    volumes = {item["name"]: item for item in entries}

    groups = [
        group(item, volumes)
        for item in array(raw.get("groups", []))
    ]

    unique([item["name"] for item in groups])
    unique([unit for item in groups for unit in item["units"]])

    return {
        "schema_version": 1,
        "runtime": {
            "interval_seconds": integer(
                runtime.get("interval_seconds", 30), 5, 3600
            ),
            "recovery_confirmations": integer(
                runtime.get("recovery_confirmations", 2), 2, 10
            ),
        },
        "volumes": volumes,
        "groups": groups,
    }


def load_config(path):
    try:
        with Path(path).open("rb") as handle:
            data = handle.read(1024 * 1024 + 1)

        require(len(data) <= 1024 * 1024, "Configuration too large.")
        raw = tomllib.loads(data.decode("utf-8"))

    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError("Cannot read TOML configuration.") from exc

    return validate(raw)
