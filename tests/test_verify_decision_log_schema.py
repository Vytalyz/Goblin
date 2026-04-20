"""Tests for tools/verify_decision_log_schema.py (ML-1.7).

Black-box tests against the validator: well-formed entries pass, missing
required fields fail, incomplete bias self-audits fail.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.verify_decision_log_schema import (  # noqa: E402
    BIAS_KEYS,
    REQUIRED_TOP_LEVEL,
    DecisionLogSchemaError,
    validate_file,
    validate_lines,
)


def _well_formed_entry() -> dict:
    return {
        "decision_id": "DEC-ML-TEST-1",
        "phase": "ML-test",
        "decision_type": "completion",
        "verdict": "go",
        "decided_by": "owner",
        "decided_at": "2026-04-20T00:00:00Z",
        "rationale": "Test entry.",
        "bias_self_audit": {f"{k}_considered": True for k in BIAS_KEYS}
        | {f"{k}_note": "considered." for k in BIAS_KEYS},
    }


def test_well_formed_entry_passes() -> None:
    raw = json.dumps(_well_formed_entry())
    assert validate_lines([raw]) == 1


def test_blank_lines_skipped() -> None:
    raw = json.dumps(_well_formed_entry())
    assert validate_lines(["", raw, "   ", raw, ""]) == 2


def test_missing_top_level_field_fails() -> None:
    for field in REQUIRED_TOP_LEVEL:
        entry = _well_formed_entry()
        del entry[field]
        with pytest.raises(DecisionLogSchemaError, match=f"missing required field '{field}'"):
            validate_lines([json.dumps(entry)])


def test_empty_string_top_level_fails() -> None:
    entry = _well_formed_entry()
    entry["rationale"] = "   "
    with pytest.raises(DecisionLogSchemaError, match="rationale"):
        validate_lines([json.dumps(entry)])


def test_bias_audit_must_be_dict() -> None:
    entry = _well_formed_entry()
    entry["bias_self_audit"] = "yes I considered them"
    with pytest.raises(DecisionLogSchemaError, match="must be an object"):
        validate_lines([json.dumps(entry)])


def test_missing_bias_field_fails() -> None:
    for bias in BIAS_KEYS:
        entry = _well_formed_entry()
        del entry["bias_self_audit"][f"{bias}_considered"]
        with pytest.raises(DecisionLogSchemaError, match=f"{bias}_considered"):
            validate_lines([json.dumps(entry)])


def test_bias_considered_must_be_true() -> None:
    entry = _well_formed_entry()
    entry["bias_self_audit"]["confirmation_bias_considered"] = False
    with pytest.raises(DecisionLogSchemaError, match="must be true"):
        validate_lines([json.dumps(entry)])


def test_bias_note_must_be_nonempty_string() -> None:
    entry = _well_formed_entry()
    entry["bias_self_audit"]["recency_note"] = ""
    with pytest.raises(DecisionLogSchemaError, match="recency_note"):
        validate_lines([json.dumps(entry)])


def test_invalid_json_fails() -> None:
    with pytest.raises(DecisionLogSchemaError, match="invalid JSON"):
        validate_lines(["{not valid"])


def test_validate_file_missing_path() -> None:
    with pytest.raises(DecisionLogSchemaError, match="not found"):
        validate_file(Path("/no/such/path/decisions.jsonl"))


def test_validate_file_roundtrip(tmp_path: Path) -> None:
    log = tmp_path / "ml_decisions.jsonl"
    log.write_text(
        json.dumps(_well_formed_entry()) + "\n" + json.dumps(_well_formed_entry()) + "\n",
        encoding="utf-8",
    )
    assert validate_file(log) == 2


def test_real_decision_log_passes() -> None:
    """The actual ML decision log committed to the repo must validate."""
    log = REPO_ROOT / "Goblin" / "decisions" / "ml_decisions.jsonl"
    if not log.exists():
        pytest.skip("ml_decisions.jsonl not present")
    assert validate_file(log) >= 1
