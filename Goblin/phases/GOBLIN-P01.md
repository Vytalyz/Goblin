# GOBLIN-P01: Four-Channel Truth Stack

## Objective

Replace the old three-layer hierarchy with a four-channel decision-specific truth stack.

## Dependencies

- `GOBLIN-P00`

## Inputs

- none

## Build Scope

- Define the four decision-specific truth channels: research, MT5 replay, live demo, and broker/account reconciliation.
- Write the comparison matrix that distinguishes structural consistency from executable parity and strict reconciliation.
- Update governance wording so channels are no longer treated as interchangeable or globally identical.

## Outputs

- truth-stack contract
- comparison matrix
- governance language update

## Expected Artifacts

- `Goblin/contracts/truth-stack.md`
- `Goblin/contracts/comparison-matrix.md`

## Checkpoint Targets

- Truth-stack contract is written and accepted as the repo-wide reference.
- Comparison rules exist for research <-> MT5, MT5 <-> live, and live <-> broker.

## Authoritative Artifacts

- `Goblin/contracts/truth-stack.md`
- `Goblin/contracts/comparison-matrix.md`

## Regenerable Artifacts

- `Goblin/phases/GOBLIN-P01.md`

## Resume And Verify

- Resume: `goblin goblin-phase-update --phase-id GOBLIN-P01 --status in_progress`
- Verify: `goblin goblin-status`
- Rerun mode: `resume_from_last_checkpoint`

## Exit Criteria

- Promotion logic references the correct comparison rule for each channel pair.
