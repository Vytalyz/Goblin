"""Tests for tools/verify_strategy_decisions_schema.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from verify_strategy_decisions_schema import (  # noqa: E402
    StrategyDecisionLogError,
    validate_file,
    validate_lines,
)


def _well_formed_entry(**overrides) -> dict:
    base = {
        "decision_id": "DEC-STRAT-AF-CAND-1001-S2-PASS",
        "candidate_id": "AF-CAND-1001",
        "stage": "S2",
        "outcome": "pass",
        "decided_by": "runner",
        "decided_at": "2026-04-22T14:32:11Z",
        "rationale": "All twelve S2 gates met with comfortable margins on in-sample evaluation.",
        "gate_results": {
            "profit_factor": {"value": 1.34, "threshold": 1.10, "passed": True},
        },
        "evidence_uris": ["Goblin/reports/strategy_loop/AF-CAND-1001/s2_eval.json"],
        "next_action": "proceed_to_S3",
    }
    base.update(overrides)
    return base


def test_well_formed_entry_validates() -> None:
    assert validate_lines([json.dumps(_well_formed_entry())]) == 1


def test_empty_log_validates() -> None:
    assert validate_lines([]) == 0
    assert validate_lines(["", "  ", "\n"]) == 0


@pytest.mark.parametrize(
    "missing",
    [
        "decision_id",
        "candidate_id",
        "stage",
        "outcome",
        "decided_by",
        "decided_at",
        "rationale",
        "gate_results",
        "evidence_uris",
        "next_action",
    ],
)
def test_missing_required_field_rejected(missing: str) -> None:
    entry = _well_formed_entry()
    del entry[missing]
    with pytest.raises(StrategyDecisionLogError, match=f"missing required field '{missing}'"):
        validate_lines([json.dumps(entry)])


def test_bad_decision_id_rejected() -> None:
    entry = _well_formed_entry(decision_id="not-a-valid-id")
    with pytest.raises(StrategyDecisionLogError, match="does not match required format"):
        validate_lines([json.dumps(entry)])


def test_duplicate_decision_id_rejected() -> None:
    line = json.dumps(_well_formed_entry())
    with pytest.raises(StrategyDecisionLogError, match="duplicate decision_id"):
        validate_lines([line, line])


def test_invalid_stage_rejected() -> None:
    entry = _well_formed_entry(
        stage="S99",
        decision_id="DEC-STRAT-AF-CAND-1001-S2-PASS",
    )
    with pytest.raises(StrategyDecisionLogError, match="stage 'S99' not in"):
        validate_lines([json.dumps(entry)])


def test_invalid_outcome_rejected() -> None:
    entry = _well_formed_entry(outcome="maybe")
    with pytest.raises(StrategyDecisionLogError, match="outcome 'maybe' not in"):
        validate_lines([json.dumps(entry)])


def test_invalid_decided_by_rejected() -> None:
    entry = _well_formed_entry(decided_by="agent")
    with pytest.raises(StrategyDecisionLogError, match="decided_by 'agent' not in"):
        validate_lines([json.dumps(entry)])


def test_non_iso_decided_at_rejected() -> None:
    entry = _well_formed_entry(decided_at="2026-04-22 14:32:11")
    with pytest.raises(StrategyDecisionLogError, match="not ISO-8601 UTC"):
        validate_lines([json.dumps(entry)])


def test_short_rationale_rejected() -> None:
    entry = _well_formed_entry(rationale="too short")
    with pytest.raises(StrategyDecisionLogError, match="at least 30"):
        validate_lines([json.dumps(entry)])


def test_gate_results_missing_passed_rejected() -> None:
    entry = _well_formed_entry(gate_results={"profit_factor": {"value": 1.34, "threshold": 1.10}})
    with pytest.raises(StrategyDecisionLogError, match="missing 'passed'"):
        validate_lines([json.dumps(entry)])


def test_gate_results_passed_must_be_bool() -> None:
    entry = _well_formed_entry(gate_results={"profit_factor": {"value": 1.34, "threshold": 1.10, "passed": "yes"}})
    with pytest.raises(StrategyDecisionLogError, match="must be a boolean"):
        validate_lines([json.dumps(entry)])


def test_evidence_uris_must_be_list_of_strings() -> None:
    entry = _well_formed_entry(evidence_uris="not-a-list")
    with pytest.raises(StrategyDecisionLogError, match="must be a list of strings"):
        validate_lines([json.dumps(entry)])


def test_invalid_json_rejected() -> None:
    with pytest.raises(StrategyDecisionLogError, match="invalid JSON"):
        validate_lines(["{not json}"])


def test_validate_file_missing_path() -> None:
    with pytest.raises(StrategyDecisionLogError, match="not found"):
        validate_file(Path("/no/such/strategy_decisions.jsonl"))


def test_validate_file_roundtrip(tmp_path: Path) -> None:
    log = tmp_path / "strategy_decisions.jsonl"
    e1 = _well_formed_entry(decision_id="DEC-STRAT-AF-CAND-1001-S2-PASS")
    e2 = _well_formed_entry(decision_id="DEC-STRAT-AF-CAND-1001-S3-PASS", stage="S3")
    log.write_text(json.dumps(e1) + "\n" + json.dumps(e2) + "\n", encoding="utf-8")
    assert validate_file(log) == 2


def test_real_strategy_decisions_log_passes() -> None:
    """The actual strategy decisions log committed to the repo must validate (empty is ok)."""
    log = REPO_ROOT / "Goblin" / "decisions" / "strategy_decisions.jsonl"
    if not log.exists():
        pytest.skip("strategy_decisions.jsonl not present")
    assert validate_file(log) >= 0
