# Knowledge Lineage

Goblin stores structured lineage for incidents, approvals, rationale, and evaluation history.

## Minimum Lineage Subjects

- incidents
- trade diff reports
- runtime summaries
- scorecards
- rationale cards
- approvals
- postmortems

## Structured Event Store

- lineage events are append-only in `Goblin/reports/knowledge/events/knowledge_events.jsonl`
- every event must include: event id, event type, subject type/id, artifact refs, and UTC timestamp
- event writes are deterministic and machine-readable for replay and audit

## Retrieval Document Requirements

- retrieval documents are stored in `Goblin/reports/knowledge/retrieval_documents/`
- each document stores source hash and optional evidence channel metadata
- any retrieval output must cite document id and source hash

## Bounded Agent Roles

- bounded roles are persisted in `Goblin/reports/knowledge/agent_roles/`
- bounded roles may retrieve/summarize/draft, but cannot approve, promote, deploy, or bypass governance
- role enforcement is mandatory before executing agent actions
