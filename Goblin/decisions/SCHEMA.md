# Goblin ML Decision Log — Schema (Bootstrap)

**Status:** bootstrap stub created in Phase 1.6.0.
**Canonical expansion:** Phase 1.7 (D11–D15) — see `Goblin/ML_EVOLUTION_PLAN.md`.

## Purpose

`ml_decisions.jsonl` is the append-only authoritative record of every
ML-phase GO / NO-GO / CONDITIONAL / OVERRIDE / holdout-access event.

## Format

- One JSON object per line.
- Append-only: line modification or deletion is a CI failure (enforced
  by the `decision-log-append-only` job added in Phase 1.7).
- GPG-signed commits required on any change to `Goblin/decisions/**`
  (enforced by branch protection + the `decision-log-verify-commit`
  CI job added in Phase 1.7).

## Required fields

Every entry must include at minimum:

| Field | Type | Notes |
|---|---|---|
| `decision_id` | string | e.g. `DEC-ML-2026-04-20-001` |
| `phase` | string | e.g. `ML-1.6.0`, `ML-1.6`, `ML-2.0` |
| `decision_type` | string | `go_no_go`, `gate_result`, `holdout_access`, `candidate_preregistration` |
| `verdict` | string | `go`, `no_go`, `conditional`, `completed`, `opened` |
| `decided_by` | string | owner / operator identity |
| `decided_at` | RFC3339 string | UTC timestamp |
| `rationale` | string | 1-3 sentences |
| `evidence_uris` | list[string] | committed report paths |

## Bias self-audit (added in Phase 1.7)

Phase 1.7 will extend every entry with a YAML bias self-audit block
containing 8 required `*_considered` booleans + 8 required non-empty
`*_note` strings. Entries written during Phase 1.6.0 are minimal and
are grandfathered — Phase 1.7 will migrate them or note the exemption
in the migration entry.

## Examples

Minimal Phase 1.6.0 entry (bootstrap shape):

```json
{"decision_id":"DEC-ML-2026-04-20-001","phase":"ML-1.6.0","decision_type":"candidate_preregistration","verdict":"completed","decided_by":"owner","decided_at":"2026-04-20T00:00:00Z","rationale":"Variance pilot candidate set pre-registered.","evidence_uris":["Goblin/reports/ml/p1_6_0_variance_pilot.json"],"candidate_set":["AF-CAND-0278","AF-CAND-0375","AF-CAND-0700"]}
```
