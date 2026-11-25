# Installation and Evaluation

## Requirements

Linux, Python 3.11+, systemd, systemd-analyze,
util-linux and procfs.

Run the supported evaluation workflow unprivileged.

## 1. Installation check

```bash
./install.sh --check
```

The installer creates a temporary installation,
checks the payload and file permissions, verifies
CLI execution and validates systemd templates.

The temporary installation is removed afterwards.

No services are activated.

## 2. Configuration wizard

```bash
./install.sh
```

The menu provides:

- Automatic configuration.
- Manual configuration.
- System diagnostics.
- About Grotaxe Smart Mount.
- Exit.

Automatic configuration imports an existing TOML file.
It does not automatically discover or configure disks.

Manual configuration registers volumes and service
groups. Advanced bind policies can be configured
through TOML.

Save operational configuration outside the repository.
Existing files are not overwritten.

## 3. Validate configuration

```bash
PYTHONPATH=src python3 -B -m smart_mount config /absolute/path/config.toml
```

## 4. Preview protection status

```bash
PYTHONPATH=src python3 -B -m smart_mount status /absolute/path/config.toml
```

Namespace inspection may require additional permissions.

## Installation layout

| Location | Purpose |
|---|---|
| `/opt/grotaxe-smart-mount` | Program files |
| `/etc/grotaxe-smart-mount` | Configuration |
| `/run/grotaxe-smart-mount` | Runtime state |
| `/usr/local/bin/smart-mount` | CLI |
| `/usr/local/bin/smart-mount-wizard` | Wizard |
| `/etc/systemd/system` | Service and timer |

## Privileged installation

An experimental installation interface exists.

It requires a trusted root-owned source tree and
configuration and refuses existing destination files.

Installation does not automatically activate services.

Privileged installation and activation have not
completed production acceptance testing.

No supported production activation procedure is
provided in this release candidate.

Do not execute the development checkout with sudo.

## Upgrade and uninstall

Upgrade and uninstall routines have been tested only
against isolated installation images.

They are not supported production workflows.

See [Security](../SECURITY.md) for limitations.
