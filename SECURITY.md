# Security Policy

## Status

Grotaxe Smart Mount is experimental software.

Do not use it as the sole protection for important data.

## Safety principles

- Explicit filesystem identity verification.
- Strict configuration validation.
- Read-only diagnostic operations.
- Restricted service action targets.
- Trusted configuration requirements.
- Runtime locking and atomic state replacement.
- Conservative recovery authorization.
- Installation conflict detection.

## Known limitations

- Periodic monitoring cannot prevent every unsafe write.
- Privileged adversaries are outside the threat model.
- Cloned filesystems can have duplicate UUIDs.
- Filesystem identifier information can be stale.
- Namespace validation focuses on MainPID.
- Service dependency side effects require further testing.
- Systemd timeouts do not guarantee job cancellation.
- Rollback is best-effort, not fully transactional.
- Protection may be unavailable if runtime locking fails.
- Persistent recovery inhibition is not guaranteed if
  its state cannot be written.
- Installation manifests verify integrity, not authenticity.
- Privileged installation and service actions have not
  completed production acceptance testing.
- Privileged automatic recovery is disabled.
- Automatic remounting is not implemented.
- Production upgrade and uninstall are not supported.

## Reporting

Use the repository host's private vulnerability
reporting mechanism if it is enabled.

A dedicated security contact has not yet been published.

Do not post vulnerability details, credentials,
operational configuration or raw private system logs
in public issues.
