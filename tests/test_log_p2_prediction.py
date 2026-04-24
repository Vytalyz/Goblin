"""Tests for tools/log_p2_prediction.py — R4-11 prediction logger.

Covers: midpoint/trigger write paths, field validation, CI ordering,
prediction ID uniqueness, verdict enum enforcement, and dry-run mode.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import log_p2_prediction as logger  # noqa: E402

# ---------------------------------------------------------------------------
# Minimal valid entry factories
# ---------------------------------------------------------------------------

VALID_COMMIT_SHA = "a" * 40

def _midpoint_entry(**overrides) -> dict:
    base = {
        "prediction_id": "PRED-ML-2.0-MIDPOINT-1",
        "phase": "midpoint",
        "predicted_verdict": "CONDITIONAL",
        "predicted_point_estimate_pf": 0.067,
        "predicted_ci_low": 0.020,
        "predicted_ci_high": 0.120,
        "commit_sha_at_prediction": VALID_COMMIT_SHA,
        "wallclock_utc": "2026-04-20T22:00:00Z",
        "rationale_note": "X" * 55,
        "predictor_attestation": "A" * 35,
    }
    base.update(overrides)
    return base


def _trigger_entry(**overrides) -> dict:
    base = {
        "prediction_id": "PRED-ML-2.0-TRIGGER-1",
        "phase": "trigger",
        "predicted_verdict": "CONDITIONAL",
        "predicted_point_estimate_pf": 0.072,
        "predicted_ci_low": 0.025,
        "predicted_ci_high": 0.125,
        "commit_sha_at_prediction": VALID_COMMIT_SHA,
        "wallclock_utc": "2026-04-20T23:00:00Z",
        "rationale_note": "Y" * 55,
        "predictor_attestation": "B" * 35,
        "commit_sha_of_midpoint_prediction": VALID_COMMIT_SHA,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# validate_prediction_entry
# ---------------------------------------------------------------------------

class TestValidatePredictionEntry:
    def test_valid_midpoint_has_no_errors(self):
        assert logger.validate_prediction_entry(_midpoint_entry()) == []

    def test_valid_trigger_has_no_errors(self):
        assert logger.validate_prediction_entry(_trigger_entry()) == []

    def test_invalid_verdict_rejected(self):
        errors = logger.validate_prediction_entry(_midpoint_entry(predicted_verdict="MAYBE"))
        assert any("predicted_verdict" in e for e in errors)

    def test_invalid_phase_rejected(self):
        errors = logger.validate_prediction_entry(_midpoint_entry(phase="uncertain"))
        assert any("phase" in e for e in errors)

    def test_ci_ordering_violated(self):
        # ci_low > point_estimate
        errors = logger.validate_prediction_entry(
            _midpoint_entry(predicted_ci_low=0.10, predicted_point_estimate_pf=0.05)
        )
        assert any("ci_low" in e or "ci_high" in e or "point_estimate" in e for e in errors)

    def test_rationale_too_short(self):
        errors = logger.validate_prediction_entry(_midpoint_entry(rationale_note="short"))
        assert any("rationale" in e for e in errors)

    def test_attestation_too_short(self):
        errors = logger.validate_prediction_entry(_midpoint_entry(predictor_attestation="short"))
        assert any("attestation" in e for e in errors)

    def test_trigger_requires_midpoint_sha(self):
        entry = _trigger_entry()
        del entry["commit_sha_of_midpoint_prediction"]
        errors = logger.validate_prediction_entry(entry)
        assert any("midpoint" in e.lower() or "trigger" in e.lower() for e in errors)

    def test_invalid_commit_sha_rejected(self):
        errors = logger.validate_prediction_entry(
            _midpoint_entry(commit_sha_at_prediction="not-a-sha")
        )
        assert any("commit_sha" in e for e in errors)


# ---------------------------------------------------------------------------
# append_prediction / _read_log round-trip
# ---------------------------------------------------------------------------

class TestAppendAndRead:
    def test_midpoint_written_and_readable(self, tmp_path):
        log = tmp_path / "predictions.jsonl"
        entry = _midpoint_entry()
        logger.append_prediction(log, entry)
        entries = logger._read_log(log)
        assert len(entries) == 1
        assert entries[0]["phase"] == "midpoint"
        assert entries[0]["predicted_verdict"] == "CONDITIONAL"

    def test_trigger_written_after_midpoint(self, tmp_path):
        log = tmp_path / "predictions.jsonl"
        logger.append_prediction(log, _midpoint_entry())
        logger.append_prediction(log, _trigger_entry())
        entries = logger._read_log(log)
        assert len(entries) == 2
        assert entries[0]["phase"] == "midpoint"
        assert entries[1]["phase"] == "trigger"

    def test_empty_log_returns_empty_list(self, tmp_path):
        log = tmp_path / "nonexistent.jsonl"
        assert logger._read_log(log) == []


# ---------------------------------------------------------------------------
# _next_prediction_id
# ---------------------------------------------------------------------------

class TestNextPredictionId:
    def test_first_midpoint_id_is_1(self):
        assert logger._next_prediction_id([], "midpoint") == "PRED-ML-2.0-MIDPOINT-1"

    def test_first_trigger_id_is_1(self):
        assert logger._next_prediction_id([], "trigger") == "PRED-ML-2.0-TRIGGER-1"

    def test_second_midpoint_id_is_2(self):
        entries = [{"prediction_id": "PRED-ML-2.0-MIDPOINT-1"}]
        assert logger._next_prediction_id(entries, "midpoint") == "PRED-ML-2.0-MIDPOINT-2"

    def test_trigger_counter_independent_of_midpoint(self):
        entries = [
            {"prediction_id": "PRED-ML-2.0-MIDPOINT-1"},
            {"prediction_id": "PRED-ML-2.0-MIDPOINT-2"},
        ]
        assert logger._next_prediction_id(entries, "trigger") == "PRED-ML-2.0-TRIGGER-1"


# ---------------------------------------------------------------------------
# CLI main (dry-run and write)
# ---------------------------------------------------------------------------

class TestCLIMain:
    _BASE_ARGS = [
        "--phase", "midpoint",
        "--verdict", "CONDITIONAL",
        "--point-estimate", "0.067",
        "--ci-low", "0.020",
        "--ci-high", "0.120",
        "--rationale", "X" * 55,
        "--attestation", "A" * 35,
        "--commit-sha", VALID_COMMIT_SHA,
    ]

    def test_dry_run_exits_zero(self, tmp_path):
        log = tmp_path / "predictions.jsonl"
        rc = logger.main(self._BASE_ARGS + ["--log", str(log), "--dry-run"])
        assert rc == 0
        assert not log.exists()

    def test_write_exits_zero_and_file_created(self, tmp_path):
        log = tmp_path / "predictions.jsonl"
        rc = logger.main(self._BASE_ARGS + ["--log", str(log)])
        assert rc == 0
        assert log.exists()
        entries = logger._read_log(log)
        assert len(entries) == 1

    def test_invalid_ci_order_exits_nonzero(self, tmp_path):
        log = tmp_path / "predictions.jsonl"
        args = [
            "--phase", "midpoint",
            "--verdict", "CONDITIONAL",
            "--point-estimate", "0.01",   # below ci_low
            "--ci-low", "0.05",
            "--ci-high", "0.10",
            "--rationale", "X" * 55,
            "--attestation", "A" * 35,
            "--commit-sha", VALID_COMMIT_SHA,
            "--log", str(log),
        ]
        rc = logger.main(args)
        assert rc != 0
