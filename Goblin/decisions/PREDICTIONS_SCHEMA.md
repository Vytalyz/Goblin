# Phase 2.0 Predictions Log Schema (R4-11 + L2)

The predictions log captures **time-separated pre-commitments** by authorized
ceremony triggerers (R4-11). It exists to provide calibration data and a
forcing function for honest priors **before** the sealed holdout is opened.

## File

- Path: `Goblin/decisions/predictions.jsonl`
- Format: append-only JSON Lines (one JSON object per line)
- Mutability: enforced append-only via `predictions-log-append-only` CI job
- Signing: requires signed commits on `main`
- Ownership: extends `Goblin/decisions/**` CODEOWNERS rule

## Required Fields

| Field | Type | Constraint |
|---|---|---|
| `prediction_id` | string | Unique across the log (e.g. `PRED-ML-2.0-MIDPOINT-1`) |
| `phase` | enum | `midpoint` or `trigger` |
| `predicted_verdict` | enum | `GO`, `CONDITIONAL`, `CONDITIONAL_RESTRICTED`, `NO_GO` |
| `predicted_point_estimate_pf` | float | Predicted aggregate PF lift on 6 survivors |
| `predicted_ci_low` | float | Lower bound of predicted 80% CI; required to bound the prediction |
| `predicted_ci_high` | float | Upper bound; must satisfy `ci_low <= point_estimate <= ci_high` |
| `commit_sha_at_prediction` | string | Full 40-char git SHA of HEAD at prediction time |
| `wallclock_utc` | string | ISO 8601 UTC timestamp |
| `rationale_note` | string | ≥ 50 characters; one-word predictions rejected |
| `predictor_attestation` | string | ≥ 30 chars; for solo owner: explicit non-peek attestation |

## Conditional Fields

For `phase = "trigger"`:

| Field | Type | Constraint |
|---|---|---|
| `commit_sha_of_midpoint_prediction` | string | Must reference the SHA of an existing `phase=midpoint` entry |
| `predicted_delta_from_midpoint_pf` | float | Computed: `trigger.point_estimate − midpoint.point_estimate` |

## Validator

`tools/verify_predictions_log_schema.py` enforces all field constraints,
the `ci_low ≤ point_estimate ≤ ci_high` invariant, the rationale-note
length floor, and (for `phase=trigger`) the cross-reference to a midpoint
entry by commit SHA.

## CI Coverage

| CI Job | Purpose |
|---|---|
| `predictions-log-append-only` | Diff-against-parent must be pure-append |
| `predictions-log-schema-check` | Validator runs on every PR touching the log |
| `predictions-log-verify-commit` | `git verify-commit` on every commit touching the log |
| `midpoint-prediction-trigger` | Watches for first eval-pipeline success on P2-tagged commit; emits reminder issue if no `phase=midpoint` entry within 24h (L1) |

## Calibration Use

The `DEC-ML-2.0-RE-GATE` decision log entry will surface:
- `midpoint.point_estimate`
- `trigger.point_estimate`
- `delta = trigger − midpoint`
- `actual_oos_pf_lift_on_holdout`
- `prediction_error_midpoint = actual − midpoint.point_estimate`
- `prediction_error_trigger = actual − trigger.point_estimate`

A large positive `delta` between midpoint and trigger predictions is itself
a signal of in-development belief drift (potential implicit peek) and will
be flagged in the `confirmation_bias_considered.note` of the re-gate entry.
