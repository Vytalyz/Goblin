# Strategy Decisions Log — Schema

The append-only JSON-Lines file `Goblin/decisions/strategy_decisions.jsonl` records every gate-level outcome for the **Goblin Strategy Development Loop** (S1 → S6, plus retirements). Each line is one decision.

This log is the canonical record of which strategies passed/failed which gates and why. It is written by the per-stage runner tools (`tools/run_strategy_s2_eval.py`, `tools/run_strategy_s3_eval.py`, etc.) and by the operator when promoting/retiring a candidate.

## Required top-level fields

| Field | Type | Description |
|---|---|---|
| `decision_id` | string | Unique. Format: `DEC-STRAT-<CAND>-<STAGE>-<OUTCOME>` (e.g. `DEC-STRAT-AF-CAND-1001-S2-PASS`). |
| `candidate_id` | string | The candidate this decision applies to (e.g. `AF-CAND-1001`). |
| `stage` | string | One of: `S1`, `S2`, `S3`, `S4`, `S5`, `S6`, `S7`, `RETIREMENT`. |
| `outcome` | string | One of: `pass`, `fail`, `pending`, `retired`, `promoted`. |
| `decided_by` | string | `owner` for human gate decisions, `runner` for automated tool outcomes. |
| `decided_at` | string | ISO-8601 UTC timestamp (e.g. `2026-04-21T12:34:56Z`). |
| `rationale` | string | Non-empty. ≥ 30 characters. Why this decision was made / what evidence supports it. |
| `gate_results` | object | Map `gate_name → { value, threshold, passed }`. May be empty for `S1` design entries. |
| `evidence_uris` | array of strings | Paths or URIs to the supporting reports/artifacts. May be empty. |
| `next_action` | string | Free-text or one of: `proceed_to_<stage>`, `retire`, `await_owner_decision`, `none`. |

## Optional fields

| Field | Type | Description |
|---|---|---|
| `slot_id` | string | `slot_a` or `slot_b` if the decision affects portfolio slot assignment. |
| `prior_decision_id` | string | Cross-references the immediately preceding decision in the candidate's history. |
| `failure_mode` | string | For `fail`/`retired`: one of `regime_mismatch`, `cost_drag`, `execution_drift`, `signal_weakness`, `parity_drift`, `data_mismatch`, `governance_block`, `other`. |
| `post_mortem_uri` | string | For retirements: link to the post-mortem note. |
| `commit_sha` | string | Repo SHA at decision time. |
| `tool_version` | string | Version of the runner that produced the entry. |

## Append-only invariant

- Entries MUST be appended; never edited or removed.
- Each line is independently valid JSON. No multi-line objects.
- The validator `tools/verify_strategy_decisions_schema.py` enforces the required-field set and the `decision_id` uniqueness invariant within the file.

## Relationship to other logs

- `Goblin/decisions/ml_decisions.jsonl` records ML-program-level decisions (cohort selection, holdout access, verdict bands). It is governed by `tools/verify_decision_log_schema.py`.
- `Goblin/decisions/predictions.jsonl` records pre-registered mid-process predictions (R4-11 audit trail).
- This file (`strategy_decisions.jsonl`) records per-strategy gate outcomes in the Strategy Development Loop and is independent of the ML phase log.

## Example entry

```json
{
  "decision_id": "DEC-STRAT-AF-CAND-1001-S2-PASS",
  "candidate_id": "AF-CAND-1001",
  "stage": "S2",
  "outcome": "pass",
  "decided_by": "runner",
  "decided_at": "2026-04-22T14:32:11Z",
  "rationale": "All 12 S2 gates met: PF=1.34, expectancy=0.18 pips, robustness coverage 88%, regime non-negativity 4/4, cost persistence at +1.0pip.",
  "gate_results": {
    "profit_factor": {"value": 1.34, "threshold": 1.10, "passed": true},
    "expectancy_pips": {"value": 0.18, "threshold": 0.05, "passed": true}
  },
  "evidence_uris": ["Goblin/reports/strategy_loop/AF-CAND-1001/s2_eval.json"],
  "next_action": "proceed_to_S3",
  "slot_id": "slot_b",
  "commit_sha": "abc123def456..."
}
```
