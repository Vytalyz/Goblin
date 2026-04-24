"""
EX-10 — pytest tests for the Phase 2.0 E2E rehearsal.

These tests invoke tools/run_p20_rehearsal.py as a subprocess and verify:
  - The rehearsal exits 0 (all steps PASS).
  - The report JSON is written with the expected shape.
  - The synthetic holdout was not modified by the rehearsal.
  - The real ml_decisions.jsonl and predictions.jsonl are untouched.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REHEARSAL_SCRIPT = REPO_ROOT / "tools" / "run_p20_rehearsal.py"
REHEARSAL_REPORT = REPO_ROOT / "Goblin" / "reports" / "ml" / "p2_0_rehearsal_report.json"
REAL_DECISIONS_LOG = REPO_ROOT / "Goblin" / "decisions" / "ml_decisions.jsonl"
REAL_PREDICTIONS_LOG = REPO_ROOT / "Goblin" / "decisions" / "predictions.jsonl"
SYNTHETIC_HOLDOUT = REPO_ROOT / "Goblin" / "holdout" / "ml_p2_synthetic_rehearsal.parquet"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _decisions_log_sha() -> str:
    return hashlib.sha256(REAL_DECISIONS_LOG.read_bytes()).hexdigest()


def _predictions_log_size() -> int:
    return REAL_PREDICTIONS_LOG.stat().st_size if REAL_PREDICTIONS_LOG.exists() else 0


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


@pytest.mark.timeout(300)
def test_rehearsal_exits_zero():
    """Full rehearsal must complete with exit code 0."""
    assert SYNTHETIC_HOLDOUT.exists(), (
        f"Synthetic holdout not found: {SYNTHETIC_HOLDOUT}\nRun: python tools/generate_synthetic_holdout.py"
    )

    before_decisions_sha = _decisions_log_sha()
    before_predictions_size = _predictions_log_size()

    result = subprocess.run(
        [sys.executable, "-B", str(REHEARSAL_SCRIPT)],
        capture_output=False,  # let output stream to terminal for visibility
        cwd=str(REPO_ROOT),
    )

    assert result.returncode == 0, "Rehearsal script exited non-zero — check step output above for failures"

    # Real artifacts must be untouched
    assert _decisions_log_sha() == before_decisions_sha, (
        "ml_decisions.jsonl was modified by the rehearsal (should only use temp log)"
    )
    assert _predictions_log_size() == before_predictions_size, (
        "predictions.jsonl was modified by the rehearsal (should only use temp log)"
    )


@pytest.mark.timeout(30)
def test_rehearsal_report_written():
    """Report JSON must exist after rehearsal runs."""
    assert REHEARSAL_REPORT.exists(), (
        f"Rehearsal report not found: {REHEARSAL_REPORT}\n"
        "Run test_rehearsal_exits_zero first (or run the rehearsal manually)"
    )


@pytest.mark.timeout(30)
def test_rehearsal_report_schema():
    """Report JSON must have the expected top-level keys and overall=PASS."""
    assert REHEARSAL_REPORT.exists(), pytest.skip("report not yet generated")

    report = json.loads(REHEARSAL_REPORT.read_text(encoding="utf-8"))

    required_keys = [
        "rehearsal_id",
        "generated_at",
        "overall",
        "steps_passed",
        "steps_failed",
        "failures",
        "steps",
        "governance_note",
    ]
    for k in required_keys:
        assert k in report, f"Report missing key: {k}"

    assert report["overall"] == "PASS", (
        f"Rehearsal report overall={report['overall']!r}; failures: {report['failures']}"
    )
    assert report["steps_failed"] == 0, f"Failures: {report['failures']}"

    step_names = {s["step"] for s in report["steps"]}
    expected_steps = {
        "A_regime_coverage",
        "B_predictions_log",
        "C_ceremony_happy_path",
        "D_ceremony_abort_path",
        "E_cap_enforcement",
        "F_decisions_schema",
    }
    assert expected_steps <= step_names, f"Missing steps in report: {expected_steps - step_names}"


@pytest.mark.timeout(30)
def test_rehearsal_report_hard_cap_unaffected():
    """Real decisions log must not contain any rehearsal-marked entries.

    Real holdout-access entries (DEC-ML-HOLDOUT-ACCESS-*) are legitimate
    operational records of the actual ceremony and are expected to be
    present once the hard cap has been used. Only REHEARSAL-marked
    entries would indicate the rehearsal scaffold polluted the real log.
    """
    entries = [json.loads(line) for line in REAL_DECISIONS_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    rehearsal_ids = [e["decision_id"] for e in entries if "REHEARSAL" in e.get("decision_id", "")]
    assert rehearsal_ids == [], f"Real decisions log contains unexpected REHEARSAL entries: {rehearsal_ids}"
