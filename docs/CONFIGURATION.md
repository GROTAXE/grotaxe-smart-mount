# Configuration

Smart Mount uses TOML configuration files.

See [the synthetic example](../examples/smart-mount.toml).

The configuration validator is authoritative.
Validate the file after every change.

## Schema

Configuration schema version: `1`.

## Runtime settings

| Parameter | Meaning |
|---|---|
| interval_seconds | Recovery observation interval, 5-3600 seconds |
| recovery_confirmations | Required observations, 2-10 |

The experimental systemd timer uses
`OnUnitInactiveSec=30s`.

Changing interval_seconds does not change the
monitoring timer.

**The timer is not a guaranteed 30-second protection
deadline.** Detection and stopping also depend on
cycle duration, scheduling, command execution and
systemd job completion.

There is no guaranteed maximum detection time.

## Volumes

| Parameter | Meaning |
|---|---|
| name | Unique logical identifier |
| target | Expected absolute mountpoint |
| uuid | Expected filesystem UUID |
| mode | Required access: ro or rw |
| fstype | Optional expected filesystem type |
| fsroot | Expected filesystem root |
| required_dirs | Required relative directories |

Use the filesystem UUID, not PARTUUID or a LUKS
container UUID.

UUID uniqueness is assumed. Cloned filesystems can
share identifiers.

## Service groups

| Parameter | Meaning |
|---|---|
| name | Unique group identifier |
| volumes | Required volume names |
| units | Ordered systemd service names |
| auto_recovery | Explicit recovery opt-in |
| binds | Optional bind mount policies |

Services are listed in their intended startup order.
Protective stopping uses reverse order.

Automatic recovery defaults to false and is disabled
in the privileged runtime regardless of configuration.

## Bind mount policies

| Parameter | Meaning |
|---|---|
| volume | Associated volume |
| source | Expected source directory |
| destination | Expected destination directory |
| source_mode | Required source access |
| destination_mode | Required destination access |
| marker | Optional regular-file marker |

The process namespace adapter checks the service
MainPID rather than every process in its cgroup.

## Validation

```bash
PYTHONPATH=src python3 -B -m smart_mount config /absolute/path/config.toml
```

## Privacy

Never commit operational configuration, actual
filesystem identifiers or private storage paths.
