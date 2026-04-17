# Run Record Contract

**Phase**: GOBLIN-P14  
**Status**: Active  
**Owner**: GoblinOrchestrator

## Purpose

Every governed campaign run emits a `GoblinRunRecord` that captures the forex session context at execution time. This enables root-cause analysis that can distinguish "wrong model" from "wrong session window" when investigating incidents.

## Model: `GoblinRunRecord`

| Field | Type | Required | Source |
|-------|------|----------|--------|
| `run_id` | `str` | yes | Campaign-generated identifier |
| `session_window` | `str` | yes | Derived deterministically by `classify_session_window()` |
| `strategy_archetype` | `str \| None` | no | Strategy family archetype if known |
| `family` | `str \| None` | no | Strategy family (e.g., `"scalping"`) |
| `candidate_id` | `str \| None` | no | Active candidate (if known at start) |
| `campaign_id` | `str \| None` | no | Parent campaign ID |
| `trace_id` | `str \| None` | no | Correlated WorkflowTrace ID |
| `trial_id` | `str \| None` | no | Correlated TrialLedgerEntry ID |
| `slot_id` | `str \| None` | no | Portfolio slot ID |
| `started_utc` | `str` | yes | ISO-8601 UTC timestamp at run start |
| `ended_utc` | `str \| None` | no | ISO-8601 UTC timestamp at run end |
| `entrypoint` | `str` | yes | Function name that initiated the run |
| `notes` | `list[str]` | no | Contextual notes appended during execution |

## Session Window Classification

`classify_session_window(timestamp_utc)` maps a UTC timestamp to one of:

| Window | UTC Hour Range |
|--------|----------------|
| `tokyo` | 00:00–08:59 |
| `london` | 07:00–11:59 (before overlap) |
| `london_new_york_overlap` | 12:00–15:59 |
| `new_york` | 16:00–20:59 (after overlap) |
| `off_hours` | 21:00–23:59 |

Classification is deterministic — the session window is never self-declared by the strategy.

## Storage

- Format: Append-only JSONL
- Path: `Goblin/reports/run_records/run_records.jsonl`
- One JSON line per record, written by `finalize_goblin_run_record()`

## Integration Points

| Entrypoint | File | Emits At |
|-----------|------|----------|
| `run_portfolio_cycle` | `campaigns/portfolio.py` | Start and end of cycle |
| `run_program_loop` | `campaigns/program_loop.py` | Start and end of loop |
| `run_autonomous_manager` | `campaigns/autonomous_manager.py` | Start and each exit path |

## Correlation

Run records correlate with existing artifacts via shared IDs:

- `trace_id` → `WorkflowTrace.trace_id`
- `trial_id` → `TrialLedgerEntry.trial_id`
- `campaign_id` → Campaign chain parentage
- `run_id` → `ArtifactProvenance.run_id`

## Governance Rules

1. Session window is always server-derived from UTC timestamp — never caller-supplied.
2. Records are append-only; existing records must never be modified or deleted.
3. Every campaign entrypoint must emit a run record, even for early exits.
4. The `notes` field captures stop reasons and status for post-hoc analysis.
