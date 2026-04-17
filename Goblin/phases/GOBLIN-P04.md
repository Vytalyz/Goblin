# GOBLIN-P04: MT5 Harness And Executable Certification

## Objective

Make MT5 the authoritative executable validation layer for MT5-targeted deployment.

## Dependencies

- `GOBLIN-P03`

## Inputs

- none

## Build Scope

- Define the MT5 certification envelope including tester mode, delay model, tick provenance, and symbol/account snapshots.
- Require baseline known-good reproduction before treating incident replays as trustworthy.
- Classify deterministic engines as `deployment_grade`, `research_only`, or `untrusted` based on MT5 parity.

## Outputs

- MT5 certification contract
- deterministic-vs-MT5 certification

## Expected Artifacts

- `Goblin/contracts/mt5-certification.md`

## Checkpoint Targets

- MT5 certification contract exists and includes tick provenance.
- Harness trust status is separated from candidate alpha claims.

## Authoritative Artifacts

- `Goblin/contracts/mt5-certification.md`

## Regenerable Artifacts

- `Goblin/phases/GOBLIN-P04.md`

## Resume And Verify

- Resume: `goblin goblin-phase-update --phase-id GOBLIN-P04 --status in_progress`
- Verify: `goblin goblin-status`
- Rerun mode: `resume_from_last_checkpoint`

## Exit Criteria

- No MT5 replay is treated as authoritative without harness certification.
