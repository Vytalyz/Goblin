# GOBLIN-P00: Program Foundation And Naming

## Objective

Create Goblin as the tracked umbrella program without destabilizing the current runtime kernel.

## Dependencies

- `none`

## Inputs

- none

## Build Scope

- Create the Goblin umbrella directory tree and machine-readable phase ledger.
- Preserve `src/agentic_forex` as the runtime kernel while introducing Goblin at the control-plane layer.
- Add the `goblin` CLI alias and the Goblin operator-orchestrator terminology to repo docs.
- Record the first authoritative checkpoint so later phases can resume from a known-good foundation.

## Outputs

- Goblin master docs
- phase ledger
- naming ADR
- CLI alias plan

## Expected Artifacts

- `Goblin/PROGRAM.md`
- `Goblin/ROADMAP.md`
- `Goblin/state/program_status.json`

## Checkpoint Targets

- Goblin directory tree exists under `/Goblin` with state, phases, contracts, decisions, templates, and runbooks.
- CLI exposes `goblin-init`, `goblin-status`, `goblin-phase-update`, and `goblin-checkpoint`.
- Phase state JSON exists for `GOBLIN-P00` through `GOBLIN-P12`.

## Authoritative Artifacts

- `Goblin/PROGRAM.md`
- `Goblin/ROADMAP.md`
- `Goblin/state/program_status.json`
- `Goblin/state/phases/GOBLIN-P00.json`
- `Goblin/decisions/ADR-0001-goblin-umbrella-program.md`
- `src/agentic_forex/goblin/service.py`
- `src/agentic_forex/goblin/models.py`

## Regenerable Artifacts

- `Goblin/STATUS.md`
- `Goblin/phases/GOBLIN-P00.md`

## Resume And Verify

- Resume: `goblin goblin-phase-update --phase-id GOBLIN-P00 --status in_progress`
- Verify: `goblin goblin-status`
- Rerun mode: `resume_from_last_checkpoint`

## Exit Criteria

- Goblin exists as the canonical program layer.
- All later phases have dependency graphs and state files.
