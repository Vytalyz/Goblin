# Investigation Trace

Goblin investigations are reproducible evidence traces, not conversational summaries.

## Canonical Outputs

- `Goblin/reports/investigations/<candidate_id>/<incident_id>/investigation_pack.json`
- `Goblin/reports/investigations/<candidate_id>/<incident_id>/scenarios/*.json`
- `Goblin/reports/investigations/<candidate_id>/<incident_id>/traces/*.json`
- `Goblin/reports/benchmark_history/<candidate_id>/<incident_id>/benchmark_history.json`
- `Goblin/reports/evaluation_suites/<candidate_id>/<incident_id>/*.json`

## Required Elements

- incident or scenario id
- input evidence references
- tool calls used
- intermediate classifications
- final classification
- confidence
- follow-up actions

## Rules

- Build traces from frozen incident evidence, not ad hoc operator notes.
- Keep scenario ids stable across reruns for the same frozen incident report.
- Treat ids inside the JSON payload as authoritative; filenames may be compacted for Windows path safety.
- Investigation traces remain diagnostic and reproducible even when MT5 replay is only advisory for that incident.

## Scope

Investigation traces are advisory and diagnostic. They do not override validation or governance.
