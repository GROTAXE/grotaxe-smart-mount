# Architecture

Smart Mount separates verification, policy evaluation,
service actions and runtime state management.

```text
Configuration
      |
      v
Storage Identity + Namespace Validation
      |
      v
Runtime Guard
      |
      +---- Unsafe ----> Protective Stop
      |
      +---- Safe ------> Recovery Policy
                              |
                              v
                       Action Executor
                              |
                              v
                       State and Locking
```

## Threat model

The tool is intended to reduce accidental damage from:

- Writes into unmounted mountpoint directories.
- Incorrect filesystem identity.
- Unsafe bind mount or namespace states.
- Unintended service recovery after a storage failure.

It does not defend against a privileged adversary,
kernel failures, hardware failures or all races
between storage checks and application writes.

## Storage identity

The identity layer verifies the expected mountpoint,
filesystem UUID, filesystem type, filesystem root
and access mode.

Filesystem identifiers obtained through system tools
can be unavailable or stale. UUID uniqueness is
not guaranteed when filesystems are cloned.

## Runtime guard

| State | Meaning |
|---|---|
| HEALTHY | Checks pass and all services are active |
| IDLE | Checks pass and all services are inactive |
| PARTIAL | Checks pass with mixed service activity |
| BLOCKED | Storage or service checks fail |

## Action executor

Protective stops use reverse service order.

The recovery executor implements ordered startup,
revalidation and best-effort rollback.

## Recovery policy

Recovery authorization requires confirmed
guard-initiated stops and successful observations
separated by the configured interval.

The integrated runtime restricts authorization to
eligible storage failures affecting fully active groups.

Authorization is consumed before startup.

Automatic recovery is disabled in the privileged
runtime.

## Runtime state

State is associated with a boot identifier and
configuration fingerprint.

State operations use file locking and atomic
file replacement.

Invalid state inhibits recovery. Protective stops
can remain available when the runtime lock is held.

## System integration

The service performs one runtime cycle.
The timer schedules recurring checks.

This is periodic userspace monitoring, not
kernel-enforced write prevention.

Native mount and application protections remain
important.
