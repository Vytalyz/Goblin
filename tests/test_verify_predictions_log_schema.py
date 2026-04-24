"""Unit tests for tools/verify_predictions_log_schema.py (EX-3, L2)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import verify_predictions_log_schema as v  # noqa: E402

VALID_MIDPOINT = {
    "prediction_id": "PRED-ML-2.0-MIDPOINT-1",
    "phase": "midpoint",
    "predicted_verdict": "GO",
    "predicted_point_estimate_pf": 0.07,
    "predicted_ci_low": 0.04,
    "predicted_ci_high": 0.10,
    "commit_sha_at_prediction": "a" * 40,
    "wallclock_utc": "2026-04-20T12:00:00Z",
    "rationale_note": (
        "Midpoint prediction based on architecture-level evidence; sequential "
        "features absent per A1 amendment; expecting modest gain."
    ),
    "predictor_attestation": (
        "Reviewed model card commit only; no holdout access."
    ),
}
VALID_TRIGGER = {
    "prediction_id": "PRED-ML-2.0-TRIGGER-1",
    "phase": "trigger",
    "predicted_verdict": "GO",
    "predicted_point_estimate_pf": 0.08,
    "predicted_ci_low": 0.05,
    "predicted_ci_high": 0.11,
    "commit_sha_at_prediction": "b" * 40,
    "wallclock_utc": "2026-05-10T16:30:00Z",
    "rationale_note": (
        "Trigger prediction; final tuning complete; mild upward revision from "
        "midpoint reflects validation-fold consistency."
    ),
    "predictor_attestation": (
        "No peeks at holdout; eval pipeline ran only on validation folds."
    ),
    "commit_sha_of_midpoint_prediction": "a" * 40,
}


class TestValidateEntry:
    def test_valid_midpoint(self):
        assert v.validate_entry(VALID_MIDPOINT, midpoint_shas=set()) == []

    def test_valid_trigger(self):
        assert v.validate_entry(VALID_TRIGGER, midpoint_shas={"a" * 40}) == []

    def test_missing_field(self):
        e = dict(VALID_MIDPOINT)
        del e["rationale_note"]
        errs = v.validate_entry(e, midpoint_shas=set())
        assert any("rationale_note" in x for x in errs)

    def test_invalid_phase(self):
        e = dict(VALID_MIDPOINT, phase="random")
        errs = v.validate_entry(e, midpoint_shas=set())
        assert any("phase must be" in x for x in errs)

    def test_invalid_verdict(self):
        e = dict(VALID_MIDPOINT, predicted_verdict="MAYBE")
        errs = v.validate_entry(e, midpoint_shas=set())
        assert any("predicted_verdict" in x for x in errs)

    def test_ci_ordering_violation_low_above_point(self):
        e = dict(VALID_MIDPOINT, predicted_ci_low=0.09, predicted_point_estimate_pf=0.07)
        errs = v.validate_entry(e, midpoint_shas=set())
        assert any("violated" in x for x in errs)

    def test_ci_ordering_violation_high_below_point(self):
        e = dict(VALID_MIDPOINT, predicted_ci_high=0.05, predicted_point_estimate_pf=0.07)
        errs = v.validate_entry(e, midpoint_shas=set())
        assert any("violated" in x for x in errs)

    def test_short_rationale_rejected(self):
        e = dict(VALID_MIDPOINT, rationale_note="too short")
        errs = v.validate_entry(e, midpoint_shas=set())
        assert any(">= 50" in x for x in errs)

    def test_short_attestation_rejected(self):
        e = dict(VALID_MIDPOINT, predictor_attestation="brief")
        errs = v.validate_entry(e, midpoint_shas=set())
        assert any(">= 30" in x for x in errs)

    def test_invalid_sha_format(self):
        e = dict(VALID_MIDPOINT, commit_sha_at_prediction="not-a-sha")
        errs = v.validate_entry(e, midpoint_shas=set())
        assert any("40-char" in x for x in errs)

    def test_invalid_timestamp(self):
        e = dict(VALID_MIDPOINT, wallclock_utc="2026-04-20 12:00:00")
        errs = v.validate_entry(e, midpoint_shas=set())
        assert any("YYYY-MM-DD" in x for x in errs)

    def test_trigger_missing_midpoint_ref(self):
        e = dict(VALID_TRIGGER)
        del e["commit_sha_of_midpoint_prediction"]
        errs = v.validate_entry(e, midpoint_shas={"a" * 40})
        assert any("commit_sha_of_midpoint_prediction" in x for x in errs)

    def test_trigger_referencing_nonexistent_midpoint(self):
        e = dict(VALID_TRIGGER, commit_sha_of_midpoint_prediction="c" * 40)
        errs = v.validate_entry(e, midpoint_shas={"a" * 40})
        assert any("does not appear" in x for x in errs)


class TestValidateFile:
    def test_empty_file_valid(self, tmp_path):
        p = tmp_path / "predictions.jsonl"
        p.write_text("")
        ok, errors = v.validate_file(p)
        assert ok
        assert errors == []

    def test_missing_file_invalid(self, tmp_path):
        ok, errors = v.validate_file(tmp_path / "nope.jsonl")
        assert not ok
        assert any("not found" in e for e in errors)

    def test_valid_pair_midpoint_then_trigger(self, tmp_path):
        p = tmp_path / "predictions.jsonl"
        p.write_text(json.dumps(VALID_MIDPOINT) + "\n" + json.dumps(VALID_TRIGGER) + "\n")
        ok, errors = v.validate_file(p)
        assert ok, f"unexpected errors: {errors}"

    def test_duplicate_prediction_id(self, tmp_path):
        p = tmp_path / "predictions.jsonl"
        e2 = dict(VALID_MIDPOINT)  # same prediction_id
        p.write_text(json.dumps(VALID_MIDPOINT) + "\n" + json.dumps(e2) + "\n")
        ok, errors = v.validate_file(p)
        assert not ok
        assert any("duplicate prediction_id" in e for e in errors)

    def test_invalid_json_line(self, tmp_path):
        p = tmp_path / "predictions.jsonl"
        p.write_text("this is not json\n")
        ok, errors = v.validate_file(p)
        assert not ok
        assert any("invalid JSON" in e for e in errors)


class TestRealLogIsValid:
    """The committed predictions.jsonl in the repo must pass the validator."""

    def test_repo_predictions_log_is_valid(self):
        log = REPO_ROOT / "Goblin" / "decisions" / "predictions.jsonl"
        ok, errors = v.validate_file(log)
        assert ok, f"committed predictions.jsonl invalid: {errors}"
