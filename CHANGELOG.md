# Changelog

## v0.1.0-rc.1 - 2026-11-25

Initial public release candidate.

### Added

- Filesystem identity and access verification.
- Bind mount and process namespace validation.
- TOML configuration.
- Runtime guard and service action executor.
- Conservative recovery planning.
- Locked runtime state.
- Restricted systemd backend.
- Diagnostic CLI and JSON output.
- Retro terminal interface.
- Interactive configuration wizard.
- Unified installation entry point.
- Isolated installation lifecycle.
- Experimental systemd service and timer.

### Validation

- 239 automated tests passed.
- Isolated installation checks passed.
- Development testing included real mount namespace
  and temporary user-systemd lifecycle experiments.

### Limitations

Experimental evaluation release.

Privileged installation acceptance, privileged
automatic recovery, automatic remounting and
production uninstall remain incomplete.

Docker-specific integration and advanced hotplug
management are outside the current scope.

Licensed under Apache License 2.0.
