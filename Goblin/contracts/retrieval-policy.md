# Retrieval Policy

Vector retrieval is advisory and provenance-cited only.

## Rules

- structured ledgers remain the system of record
- vector similarity cannot promote, approve, or invalidate a candidate by itself
- retrieval outputs must cite source artifacts
- retrieval is secondary to validation and governance, never a replacement for them

## Indexing Scope

- vector memory is built from structured retrieval documents under `Goblin/reports/knowledge/retrieval_documents/`
- retrieval index artifacts are stored under `Goblin/reports/knowledge/vector_memory/`
- retrieval query reports are stored under `Goblin/reports/knowledge/retrieval_queries/`

## Governance Boundary

- retrieval responses are advisory only and cannot issue deployment, promotion, or approval decisions
- role-based action checks must prevent bounded agents from governance-authority actions
