# GOBLIN-P08: Investigation And Evaluation Framework

## Objective

Add a Holmes-style, repo-native investigation and eval layer without making it critical-path runtime.

## Dependencies

- `GOBLIN-P06`

## Inputs

- none

## Build Scope

- Define a repo-native investigation framework inspired by Holmes-style structured investigations and eval loops.
- Make incident diagnosis reproducible through scenarios, traces, and benchmark history.
- Keep investigation tooling advisory and outside the critical runtime path.

## Outputs

- investigation scenarios
- evaluation suite
- benchmark history
- investigation pack

## Expected Artifacts

- `Goblin/contracts/investigation-trace.md`
- `Goblin/contracts/evaluation-suite.md`

## Checkpoint Targets

- Investigation trace contract exists.
- Evaluation suite contract exists and separates deterministic regression from replay-backed reliability runs.
- At least one serious incident produces a reproducible investigation pack.

## Authoritative Artifacts

- `Goblin/contracts/investigation-trace.md`
- `Goblin/contracts/evaluation-suite.md`

## Regenerable Artifacts

- `Goblin/phases/GOBLIN-P08.md`

## Resume And Verify

- Resume: `goblin goblin-phase-update --phase-id GOBLIN-P08 --status in_progress`
- Verify: `goblin goblin-status`
- Rerun mode: `resume_from_last_checkpoint`

## Exit Criteria

- Serious incidents have reproducible investigation packs.
