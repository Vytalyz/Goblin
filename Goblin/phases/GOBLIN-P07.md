# GOBLIN-P07: Release, Approval, And Change Management

## Objective

Make every deployable artifact a governed release bundle with a declared deployment ladder state, so bundle approval and operational readiness are never conflated.

## Dependencies

- `GOBLIN-P05`

Note: P07 depends on P05, not P06. P07 outputs (bundle identity, ladder state) are consumed by P06 for incident closure packets. Both P06 and P07 may be executed after P05; in practice P07 should be authored early because P06 incident closure requires bundle identity.

## Inputs

- `Goblin/contracts/live-demo-contract.md`
- `Goblin/contracts/broker-reconciliation.md`
- `Goblin/contracts/execution-cost-contract.md`

## Build Scope

- Define the deployment bundle, approval boundaries, rollback criteria, and immutable evidence retention policy.
- Define the deployment ladder: shadow_only → limited_demo → observed_demo → challenger_demo → eligible_for_replacement.
- Enforce that bundle approval does not imply operational readiness; every live/demo attach must reference both a release bundle and a ladder state.
- Define environment reproducibility requirements: terminal build pinning, config drift detection, secrets location policy, and critical-state backup.
- Document the manual approval surfaces required before demo or production-facing changes.
- Add ladder state to `LiveAttachManifest` and incident closure packet models.

## Outputs

- deployment bundle schema
- deployment ladder contract
- environment reproducibility contract
- approval boundary policy
- retention runbooks

## Expected Artifacts

- `Goblin/contracts/deployment-bundle.md`
- `Goblin/contracts/deployment-ladder.md`
- `Goblin/contracts/environment-reproducibility.md`
- `Goblin/runbooks/RELEASE_AND_ROLLBACK.md`

## Checkpoint Targets

- Deployment ladder defines all five states with verifiable transition requirements.
- Environment reproducibility covers terminal build pinning, config drift, and secrets policy.
- Release and rollback runbook references the ladder and bundle contracts.
- `LiveAttachManifest` carries ladder state.
- Bundle approval cannot be treated as permission to advance the ladder.

## Authoritative Artifacts

- `Goblin/contracts/deployment-bundle.md`
- `Goblin/contracts/deployment-ladder.md`
- `Goblin/contracts/environment-reproducibility.md`
- `Goblin/runbooks/RELEASE_AND_ROLLBACK.md`

## Regenerable Artifacts

- `Goblin/phases/GOBLIN-P07.md`

## Resume And Verify

- Resume: `goblin goblin-phase-update --phase-id GOBLIN-P07 --status in_progress`
- Verify: `goblin goblin-status`
- Rerun mode: `resume_from_last_checkpoint`

## Exit Criteria

- No live/demo attachment occurs without a deployable bundle and a declared ladder state.
- Config hash mismatch between bundle and attach triggers a release integrity incident.
