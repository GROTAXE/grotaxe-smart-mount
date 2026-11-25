# GROTAXE SMART MOUNT

```text
                  G R O T A X E

                   SMART MOUNT
            LINUX STORAGE PROTECTION
```

**Know what is mounted. Protect what matters.**

An independent Linux storage protection toolkit
designed to detect missing or incorrect filesystem
mounts and protect dependent applications from
unsafe storage locations.

**Status: experimental software. Evaluation use only.**

## The problem

When a storage device becomes unavailable, its
mountpoint may remain accessible as an ordinary
directory on the underlying filesystem.

Applications may continue writing into that directory.

Two important consequences are:

- The underlying filesystem fills up with misplaced data.
- Files written during the outage become hidden when
  the intended filesystem is mounted again.

Checking whether a directory exists is not enough.

Grotaxe Smart Mount verifies filesystem identity,
mount access policies and storage requirements.

## Why not just systemd?

systemd provides mount-aware mechanisms such as
`RequiresMountsFor=`, `BindsTo=` and
`ConditionPathIsMountPoint=`.

These mechanisms remain useful for startup ordering,
dependency management and mount-aware services.

Smart Mount complements them with:

- Expected filesystem UUID, type and root checks.
- Bind mount and process namespace validation.
- Ordered protective stopping of service groups.
- Boot-scoped recovery authorization and inhibition.

Smart Mount does not replace native systemd
or mount-level protections.

## Features

| Capability | Status |
|---|---|
| Filesystem identity verification | Available |
| Read-only and read-write policies | Available |
| Required directory and marker checks | Available |
| Bind mount validation | Available |
| Process namespace validation | MainPID scope |
| Runtime state and locking | Available |
| Systemd protective stopping | Experimental |
| Recovery planning | Implemented and tested |
| Privileged automatic recovery | Disabled |
| Automatic remounting | Not implemented |
| Interactive configuration wizard | Available |
| Retro terminal interface | Available |
| CLI and JSON diagnostics | Available |
| Isolated installation | Verified |
| Privileged installation | Experimental |
| Production upgrade and uninstall | Not supported |

Docker-specific integration and advanced hotplug
management are outside the current scope.

## Requirements

- Linux.
- Python 3.11 or newer.
- systemd and systemd-analyze.
- util-linux, including findmnt.
- procfs.

The implementation uses the Python standard library.
No third-party Python packages are required.

Some process namespace inspections require additional
permissions.

## Quick start

Run as an ordinary user.

Check the installation package:

```bash
./install.sh --check
```

Open the interactive configuration wizard:

```bash
./install.sh
```

Run system diagnostics:

```bash
PYTHONPATH=src python3 -B -m smart_mount doctor
```

Validate the synthetic example configuration:

```bash
PYTHONPATH=src python3 -B -m smart_mount config examples/smart-mount.toml
```

## Protection cycle

Illustrative example, not literal CLI output:

```text
Storage verified
Service group HEALTHY

Storage identity mismatch
Service group BLOCKED
Protective stop requested in reverse service order
```

The privileged runtime is currently protection-only.
Automatic service recovery is disabled there.

## Documentation

- [Installation](docs/INSTALLATION.md)
- [Configuration](docs/CONFIGURATION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Command line interface](docs/CLI.md)
- [Security and limitations](SECURITY.md)
- [Changelog](CHANGELOG.md)
- [License](LICENSE)

## Project status

This software is intended for evaluation.

Privileged installation, production service activation,
privileged service actions and production uninstall
have not completed acceptance testing.

Do not run a development checkout with sudo.

Periodic monitoring cannot prevent every unsafe write.
Do not rely on Smart Mount as the sole protection
for important data.

## Testing

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
    python3 -m unittest discover -s tests -q
```

Automated tests passed: 239.

Documentation validation date: 2026-11-25 UTC.

Previous development validation has included isolated
mount experiments, temporary user-systemd lifecycle
tests and staged launcher execution.

These results do not establish universal compatibility
or production readiness.

## Privacy

All supplied examples use synthetic data.

Keep operational configuration, runtime state, logs,
filesystem identifiers and diagnostic exports outside
the public repository.

## License

Apache License, Version 2.0.

See [LICENSE](LICENSE).

---

**GROTAXE SMART MOUNT**

Independent Linux storage protection.
