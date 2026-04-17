# GOBLIN-P05: Live Demo Observability And Broker Reconciliation

## Objective

Make live-demo evidence operationally trustworthy and externally reconcilable.

## Dependencies

- `GOBLIN-P04`

## Inputs

- none

## Build Scope

- Define live attach manifests, runtime summaries, heartbeats, and broker/account reconciliation outputs.
- Separate EA audit files from independent broker reconciliation so live truth is not self-referential.
- Codify chaos and failure scenarios for terminal closure, sleep/wake, account changes, and audit gaps.

## Outputs

- runtime contract
- broker reconciliation pipeline
- ops incident triggers

## Expected Artifacts

- `Goblin/contracts/live-demo-contract.md`
- `Goblin/contracts/broker-reconciliation.md`

## Checkpoint Targets

- Live-demo contract exists with runtime observability requirements.
- Broker reconciliation contract exists and is treated as external truth.

## Authoritative Artifacts

- `Goblin/contracts/live-demo-contract.md`
- `Goblin/contracts/broker-reconciliation.md`

## Regenerable Artifacts

- `Goblin/phases/GOBLIN-P05.md`

## Resume And Verify

- Resume: `goblin goblin-phase-update --phase-id GOBLIN-P05 --status in_progress`
- Verify: `goblin goblin-status`
- Rerun mode: `resume_from_last_checkpoint`

## Exit Criteria

- Live/demo no longer relies only on EA audit files.
