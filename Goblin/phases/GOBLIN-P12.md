# GOBLIN-P12: Knowledge Store, Vector Memory, And Agentic Layer

## Objective

Add retrieval and richer agent support without turning them into the source of truth.

## Dependencies

- `GOBLIN-P11`

## Inputs

- none

## Build Scope

- Add a structured knowledge store first, then optional vector retrieval with provenance-cited outputs.
- Define bounded Goblin agent roles that accelerate review without becoming the source of truth.
- Keep the repo operational even if Codex is closed or the Goblin agent layer is unavailable.

## Outputs

- knowledge lineage model
- retrieval index
- bounded Goblin agent roles

## Expected Artifacts

- `Goblin/contracts/knowledge-lineage.md`
- `Goblin/contracts/retrieval-policy.md`

## Checkpoint Targets

- Knowledge-lineage contract exists.
- Retrieval-policy contract exists and keeps vector memory advisory only.

## Authoritative Artifacts

- `Goblin/contracts/knowledge-lineage.md`
- `Goblin/contracts/retrieval-policy.md`

## Regenerable Artifacts

- `Goblin/phases/GOBLIN-P12.md`

## Resume And Verify

- Resume: `goblin goblin-phase-update --phase-id GOBLIN-P12 --status in_progress`
- Verify: `goblin goblin-status`
- Rerun mode: `resume_from_last_checkpoint`

## Exit Criteria

- Agentic features do not weaken governance or runtime truth.
