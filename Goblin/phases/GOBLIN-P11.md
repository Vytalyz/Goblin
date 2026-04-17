# GOBLIN-P11: Governed ML And Self-Learning

## Objective

Add learning only after labels and provenance are trustworthy.

## Dependencies

- `GOBLIN-P10`

## Inputs

- none

## Build Scope

- Add a governed model registry and trusted label policy for offline learning only.
- Start with low-risk ML layers such as anomaly detection and regime classification.
- Require offline validation, holdouts, and MT5-compatible replay if model output touches live decision logic.

## Outputs

- model registry
- label policy
- governed offline training cycle

## Expected Artifacts

- `Goblin/contracts/model-registry.md`

## Checkpoint Targets

- Model registry contract exists.
- Offline-only self-learning rule is documented and linked to governance.

## Authoritative Artifacts

- `Goblin/contracts/model-registry.md`

## Regenerable Artifacts

- `Goblin/phases/GOBLIN-P11.md`

## Resume And Verify

- Resume: `goblin goblin-phase-update --phase-id GOBLIN-P11 --status in_progress`
- Verify: `goblin goblin-status`
- Rerun mode: `resume_from_last_checkpoint`

## Exit Criteria

- No online self-tuning exists in live/demo execution.
