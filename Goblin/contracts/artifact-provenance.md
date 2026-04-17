# Artifact Provenance

Every governed artifact must declare:

- `candidate_id`
- `run_id`
- `artifact_origin`
- `evidence_channel`
- `terminal_id`
- `terminal_build`
- `broker_server`
- `symbol`
- `timezone_basis`
- `created_at_utc`
- `artifact_hash`

## Rules

- Promotion, incident, and review workflows must consume explicit artifact references or channel-owned indexes only.
- Replay artifacts cannot be treated as live/demo evidence.
- Missing provenance fields are validation failures.
- Ambiguous provenance is a validation failure, not a warning.
