# Command Line Interface

## Invocation

From the source directory:

```bash
PYTHONPATH=src python3 -B -m smart_mount --help
```

The experimental installed launcher is `smart-mount`.

The wizard launcher is `smart-mount-wizard`.
From the source directory, use `./install.sh`.

## Commands

| Command | Purpose |
|---|---|
| doctor | System dependency checks |
| config FILE | Validate TOML configuration |
| status FILE | Read-only protection assessment |
| check MOUNTPOINT UUID | Verify storage identity |
| inspect PATH | Inspect mounted storage |
| about | Project information |

## Storage check options

The `check` command supports:

- `--mode rw` or `--mode ro`
- `--fstype TYPE`
- `--fsroot ROOT`

The `inspect` command supports `--mode`.

## Output

Global output options precede the subcommand:

```bash
PYTHONPATH=src python3 -B -m smart_mount --json doctor
```

```bash
PYTHONPATH=src python3 -B -m smart_mount --plain about
```

The JSON schema is not yet declared stable.

Diagnostic output can contain real storage identifiers,
paths and service names. Review it before sharing.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Successful verification |
| 1 | Verification or operation failed |
| 2 | Invalid command-line arguments |
| 75 | Runtime lock contention, runtime entry point |

## Installer

```bash
./install.sh --help
./install.sh --check
./install.sh
```

The supported public workflow is unprivileged
evaluation and configuration preparation.
