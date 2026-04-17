# GOBLIN-P02: Provenance And Artifact Contracts

## Objective

Make provenance a hard gate everywhere.

## Dependencies

- `GOBLIN-P01`

## Inputs

- none

## Build Scope

- Define artifact provenance fields and explicit `evidence_channel` tagging across governed artifacts.
- Replace heuristic evidence discovery with channel-owned indexes and immutable run identity.
- Treat ambiguous provenance as a hard validation failure rather than an operator warning.

## Outputs

- artifact provenance contract
- channel-owned artifact indexes

## Expected Artifacts

- `Goblin/contracts/artifact-provenance.md`

## Checkpoint Targets

- Artifact provenance contract is written and referenced from validation and incident flows.
- Channel-owned artifact resolution replaces wildcard audit discovery in governed paths.

## Authoritative Artifacts

- `Goblin/contracts/artifact-provenance.md`

## Regenerable Artifacts

- `Goblin/phases/GOBLIN-P02.md`

## Resume And Verify

- Resume: `goblin goblin-phase-update --phase-id GOBLIN-P02 --status in_progress`
- Verify: `goblin goblin-status`
- Rerun mode: `resume_from_last_checkpoint`

## Exit Criteria

- Ambiguous provenance becomes impossible in governed workflows.
