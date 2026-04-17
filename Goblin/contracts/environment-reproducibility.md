# Environment Reproducibility

This contract defines the requirements for making the execution environment reproducible enough to trust that two runs of the same candidate are comparable. It focuses on MT5 terminal pinning, config drift detection, secrets location policy, and critical-state backup — using existing repo infrastructure rather than new subsystems.

## MT5 Terminal Build Pinning

The MT5 terminal build number must be recorded in every certification report (`MT5CertificationReport.terminal_build`) and every live attach manifest (`LiveAttachManifest.terminal_build`).

**Rule:** If the terminal build changes between a certification run and a live attach, the live attach must note the build change in the attach manifest and the operator must confirm the change is non-material or trigger a recertification.

**Auto-open incident:** `terminal_build_change_without_recertification` (S3) if build changes between bundle issue and attach without documented operator confirmation.

## Broker Server Class Pinning

The broker server (demo vs live, server address class) must be recorded in certification reports and attach manifests. Switching broker server classes between certification and live attach is a parity risk.

**Rule:** MT5 certification at `deployment_grade` is only valid for the broker server class it was performed on. Switching broker server requires recertification or a documented rationale that the server classes are equivalent.

## Config Drift Detection

A deployment bundle captures hashes of the EA binary, inputs `.set` file, and validation packet at bundle issue time. Before attaching:
- The EA binary hash must match the bundle's `ea_build_hash`.
- The inputs file hash must match the bundle's `inputs_hash`.

If either hash mismatches, this is a `release_integrity_failure` (S1 incident). Do not proceed with the attach.

This check does not require new tooling — the `build_deployment_bundle` function in `controls.py` already captures these hashes.

## Repository Config Drift

The Goblin program assumes that `config/` directory settings (particularly `eval_gates.toml`, `mt5_env.toml`, and `data_contract.toml`) are stable within a live run window. If `config/` changes between bundle issue and attach, the operator must review the diff and confirm the changes do not affect execution assumptions.

**Recommended practice:** commit config changes before issuing a new bundle, not after.

## Secrets Location Policy

Secrets (broker API tokens, OANDA tokens) must be stored in the Windows Credential Manager or environment variables, not in committed files. The existing `resolve_secret()` function in `utils/secrets.py` implements this policy. No new secrets subsystem is required.

**Rule:** Any secret that needs to be available for live execution must be resolvable via `resolve_secret(env_var=..., credential_targets=...)`. Hard-coded secrets in config files are a policy violation.

## Critical State Backup

Critical state is defined as:
- Current approved deployment bundles (`Goblin/reports/deployment_bundles/`)
- MT5 certification reports (`Goblin/reports/mt5_certification/`)
- Live-demo channel reports (`Goblin/reports/live_demo/`)
- Broker account history reports (`Goblin/reports/broker_account_history/`)
- Incident records (`Goblin/reports/incidents/`)
- Phase state and checkpoints (`Goblin/state/`, `Goblin/checkpoints/`)

These paths must be included in any backup or sync strategy. The repo itself (via git) is the backup mechanism for contracts, configs, and source code. The `Goblin/reports/` directory may be excluded from git if it grows large, but should then be backed up separately.

**Minimum requirement:** at least one backup copy of critical state exists that is not on the same machine as the trading terminal.

## Machine Fingerprint (Advisory)

Optionally, the `LiveAttachManifest` may record the machine hostname and OS version. This is advisory context only — it cannot prevent drift but helps identify when runs were performed on different machines. Not required for governance compliance.
