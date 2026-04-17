# Release And Rollback

This runbook governs how to issue a deployment bundle, advance the deployment
ladder, and roll back if needed.  The authoritative contracts are
`Goblin/contracts/deployment-bundle.md`, `Goblin/contracts/deployment-ladder.md`,
and `Goblin/contracts/environment-reproducibility.md`.

## Issuing a Deployment Bundle

Call `build_deployment_bundle(settings, candidate_id=..., bundle_id=...)`.

Every bundle captures:

- `ea_build_hash` — hash of the EA `.ex5` binary
- `inputs_hash` — hash of the `.set` inputs file
- `validation_packet_hash` — hash of the truth alignment report or review packet
- `symbol_assumptions` — instrument and execution granularity from settings
- `account_assumptions` — currency, initial balance, leverage, max exposure
- `approval_refs` — references to operator approvals on record
- `rollback_criteria` — conditions that trigger rollback

A bundle is a release identity, not an operational readiness decision.
Holding a valid bundle does not grant any ladder state above `shadow_only`.

## Pre-Attach Hash Checks (Config Drift Detection)

Before every live or demo attach, call
`validate_attach_against_bundle(settings, manifest=..., bundle=...)`.

If `inputs_hash` on the manifest does not match `inputs_hash` on the bundle, a
`release_integrity_failure` S1 incident is opened automatically and the attach
must not proceed.  This check uses existing hashes already captured by
`build_deployment_bundle` and `write_live_attach_manifest` — no new tooling required.

## Attaching With Ladder State

Every `LiveAttachManifest` must carry:

- `bundle_id` — the approved bundle being used
- `ladder_state` — the current deployment ladder state for this candidate

Do not attach without a declared ladder state.  The ladder state at attach is
evidence for audit and incident closure.

## Deployment Ladder Advancement

The ladder states in order are:

1. `shadow_only` — observation only, no orders
2. `limited_demo` — demo account, active monitoring, reduced scope
3. `observed_demo` — full-configuration demo, full scope
4. `challenger_demo` — head-to-head with benchmark candidate
5. `eligible_for_replacement` — all promotion criteria satisfied

Transition requirements for each state are defined in `deployment-ladder.md`.

**Never skip a state.**  Evidence for each state must exist before advancing.

**S1 incidents block advancement.**  An open S1 incident suspends the candidate
at its current ladder state.

**New bundle resets the ladder.**  If the EA is recompiled or config changes,
the new bundle re-enters at `shadow_only` unless the operator explicitly accepts
continuation with documented rationale.

## Rollback Procedure

1. Open an S1 or S2 incident for the triggering condition.
2. Halt new order placement per the suspension rules in `incident-severity-matrix.md`.
3. Identify the last known-good bundle by checking `Goblin/reports/deployment_bundles/`.
4. Reissue or reattach using the known-good bundle.
5. Confirm the `inputs_hash` and `ea_build_hash` match the known-good bundle before reattaching.
6. Update the incident record with the rollback bundle identity.
7. Close the incident after verifying the rollback resolved the triggering condition.

## Environment Reproducibility Checks

Before attaching after any terminal update or machine change:

- Confirm `terminal_build` on the attach manifest matches the certification report.
- If the build changed, confirm it is non-material or trigger recertification.
- Confirm `broker_server` class matches the certification run.

If terminal build changed without recertification, this opens a
`terminal_build_change_without_recertification` S3 incident automatically.

## Evidence Retention

The following paths must not be deleted and should be backed up off-machine:

- `Goblin/reports/deployment_bundles/`
- `Goblin/reports/mt5_certification/`
- `Goblin/reports/live_demo/`
- `Goblin/reports/broker_account_history/`
- `Goblin/reports/incidents/`
- `Goblin/state/`
- `Goblin/checkpoints/`
