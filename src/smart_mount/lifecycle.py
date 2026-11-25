"""Installation lifecycle for isolated, unprivileged images."""

import json
import os
import re
import stat

from pathlib import Path

from .install_plan import (
    MODULES,
    PREFIX,
    CONFIG_DIR,
    UNIT_DIR,
    PlanError,
    source_directory,
)

from .stage_install import (
    MANIFEST,
    LAUNCHERS,
    UNITS,
    build_stage,
    digest,
    read_regular,
    target,
)

from .trusted_config import decode_config


CONFIG_PATH = CONFIG_DIR + "/config.toml"


def expected_files():
    return {
        **{
            PREFIX + "/smart_mount/" + name: "0644"
            for name in MODULES
        },
        **{
            path: "0755"
            for path in LAUNCHERS
        },
        **{
            UNIT_DIR + "/" + name: "0644"
            for name in UNITS
        },
    }


def check_directory(path, *, private=False):
    info = path.lstat()
    mode = stat.S_IMODE(info.st_mode)

    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or mode & 0o022
        or (private and mode != 0o700)
    ):
        raise PlanError("Unsafe staging directory.")


def require_stage(stage, parent):
    """Accept only private, unprivileged staging images."""

    if os.geteuid() == 0:
        raise PlanError("Privileged lifecycle is disabled.")

    stage = Path(stage)
    parent = source_directory(parent)

    check_directory(parent, private=True)

    if (
        not stage.is_absolute()
        or stage.parent != parent
        or not stage.name.startswith("grotaxe-stage-")
        or stage.resolve(strict=True) != stage
    ):
        raise PlanError("Invalid staging image.")

    check_directory(stage, private=True)

    return stage


def checked_target(stage, destination):
    path = target(stage, destination)
    current = stage

    for part in path.relative_to(stage).parts[:-1]:
        current = current / part
        check_directory(current)

    info = path.lstat()

    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
    ):
        raise PlanError("Unsafe staged file.")

    return path


def unique_keys(items):
    result = {}

    for key, value in items:
        if key in result:
            raise PlanError("Duplicate manifest key.")

        result[key] = value

    return result


def load_manifest(stage):
    path = checked_target(stage, MANIFEST)
    data, mode = read_regular(path)

    if mode != 0o644:
        raise PlanError("Unsafe manifest permissions.")

    try:
        manifest = json.loads(
            data,
            object_pairs_hook=unique_keys,
        )
    except (ValueError, RecursionError) as exc:
        raise PlanError("Invalid installation manifest.") from exc

    if (
        type(manifest) is not dict
        or set(manifest) != {
            "manifest_version",
            "product",
            "files",
            "configuration",
            "activation",
        }
        or type(manifest["manifest_version"]) is not int
        or manifest["manifest_version"] != 1
        or manifest["product"] != "GROTAXE SMART MOUNT"
        or manifest["activation"] is not False
        or type(manifest["files"]) is not list
        or manifest["configuration"] != {
            "path": CONFIG_PATH,
            "mode": "0600",
            "preserve_on_uninstall": True,
        }
    ):
        raise PlanError("Unexpected manifest schema.")

    expected = expected_files()
    seen = set()

    for item in manifest["files"]:
        if (
            type(item) is not dict
            or set(item) != {"path", "mode", "sha256"}
            or type(item["path"]) is not str
            or item["path"] not in expected
            or item["path"] in seen
            or item["mode"] != expected[item["path"]]
            or type(item["sha256"]) is not str
            or not re.fullmatch(
                r"[a-f0-9]{64}", item["sha256"]
            )
        ):
            raise PlanError("Invalid manifest record.")

        seen.add(item["path"])

    if seen != set(expected):
        raise PlanError("Incomplete installation manifest.")

    return manifest


def verify_installation(stage, parent):
    stage = require_stage(stage, parent)
    manifest = load_manifest(stage)

    for item in manifest["files"]:
        path = checked_target(stage, item["path"])
        data, mode = read_regular(path)

        if (
            digest(data) != item["sha256"]
            or mode != int(item["mode"], 8)
        ):
            raise PlanError("Installed file changed.")

    return manifest


def prepare_upgrade(stage, parent, source, unit_source):
    """Prepare a replacement image without changing the old one."""

    stage = require_stage(stage, parent)

    verify_installation(stage, parent)

    config_path = checked_target(stage, CONFIG_PATH)
    config_data, mode = read_regular(config_path)

    if mode != 0o600:
        raise PlanError("Unsafe configuration permissions.")

    decode_config(config_data)

    replacement, manifest = build_stage(
        source,
        unit_source,
        config_data,
        parent,
    )

    verify_installation(replacement, parent)

    return replacement, manifest


def uninstall(stage, parent, *, apply=False):
    """Remove only verified program files from a staged image."""

    stage = require_stage(stage, parent)
    manifest = verify_installation(stage, parent)

    removal = [
        item["path"]
        for item in manifest["files"]
    ]

    removal.append(MANIFEST)

    result = {
        "dry_run": apply is not True,
        "planned": removal,
        "removed": [],
        "preserved": [CONFIG_PATH],
        "system_changes": False,
    }

    if apply is not True:
        return result

    # Never recursively remove directories.
    # Configuration and unrelated files remain untouched.

    for destination in removal:
        path = checked_target(stage, destination)
        path.unlink()

        result["removed"].append(destination)

    return result
