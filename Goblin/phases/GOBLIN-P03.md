# GOBLIN-P03: Time, Session, And Data Normalization

## Objective

Eliminate hidden ambiguity in time handling and source-specific data interpretation.

## Dependencies

- `GOBLIN-P02`

## Inputs

- none

## Build Scope

- Define a canonical time/session model for broker offsets, DST boundaries, holidays, and overlap windows.
- Freeze the reproducibility contract for OANDA research downloads including price component and alignment settings.
- Add data-quality gates for missing bars, duplicates, spread anomalies, session gaps, and malformed exports.

## Outputs

- time/session contract
- research data contract
- data quality gates

## Expected Artifacts

- `Goblin/contracts/time-session-contract.md`
- `Goblin/contracts/research-data-contract.md`

## Checkpoint Targets

- Time/session contract exists and declares the comparison time basis.
- Research-data contract exists and captures the OANDA query settings that make research reproducible.

## Authoritative Artifacts

- `Goblin/contracts/time-session-contract.md`
- `Goblin/contracts/research-data-contract.md`

## Regenerable Artifacts

- `Goblin/phases/GOBLIN-P03.md`

## Resume And Verify

- Resume: `goblin goblin-phase-update --phase-id GOBLIN-P03 --status in_progress`
- Verify: `goblin goblin-status`
- Rerun mode: `resume_from_last_checkpoint`

## Exit Criteria

- All comparisons share the same declared time basis.
- OANDA research is reproducible.
