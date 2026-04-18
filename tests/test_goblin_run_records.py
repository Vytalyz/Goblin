"""Tests for P14 — Session-Aware Run Logging.

Validates:
- classify_session_window deterministic derivation
- GoblinRunRecord model round-trip
- start / finalize helpers write append-only JSONL
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from agentic_forex.config import Settings
from agentic_forex.goblin.controls import (
    classify_session_window,
    finalize_goblin_run_record,
    start_goblin_run_record,
)
from agentic_forex.goblin.models import GoblinRunRecord

# ---------------------------------------------------------------------------
# classify_session_window
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hour, expected",
    [
        (3, "tokyo"),
        (8, "london"),
        (14, "london_new_york_overlap"),
        (18, "new_york"),
        (23, "off_hours"),
        (0, "tokyo"),
        (7, "london"),
        (12, "london_new_york_overlap"),
        (15, "london_new_york_overlap"),
        (16, "new_york"),
        (20, "new_york"),
        (21, "off_hours"),
        (9, "london"),
    ],
)
def test_classify_session_window_by_hour(hour: int, expected: str) -> None:
    ts = datetime(2026, 4, 14, hour, 30, 0, tzinfo=UTC)
    assert classify_session_window(ts) == expected


def test_classify_session_window_from_iso_string() -> None:
    assert classify_session_window("2026-04-14T14:00:00+00:00") == "london_new_york_overlap"


# ---------------------------------------------------------------------------
# GoblinRunRecord model
# ---------------------------------------------------------------------------


def test_goblin_run_record_round_trip() -> None:
    record = GoblinRunRecord(
        run_id="test-run-001",
        session_window="london",
        family="scalping",
        started_utc="2026-04-14T08:00:00+00:00",
        entrypoint="run_program_loop",
    )
    payload = record.model_dump(mode="json")
    restored = GoblinRunRecord.model_validate(payload)
    assert restored.run_id == "test-run-001"
    assert restored.session_window == "london"
    assert restored.family == "scalping"
    assert restored.ended_utc is None
    assert restored.notes == []


# ---------------------------------------------------------------------------
# start + finalize helpers
# ---------------------------------------------------------------------------


def test_start_goblin_run_record_populates_session_window() -> None:
    record = start_goblin_run_record(
        run_id="test-start-001",
        entrypoint="run_portfolio_cycle",
        family="scalping",
    )
    assert record.run_id == "test-start-001"
    assert record.entrypoint == "run_portfolio_cycle"
    assert record.session_window in {
        "tokyo",
        "london",
        "london_new_york_overlap",
        "new_york",
        "off_hours",
    }
    assert record.started_utc is not None
    assert record.ended_utc is None


def test_finalize_writes_jsonl(tmp_path: str) -> None:
    settings = Settings(_env_file="", project_root=str(tmp_path))
    record = start_goblin_run_record(
        run_id="test-finalize-001",
        entrypoint="run_autonomous_manager",
        family="scalping",
        candidate_id="AF-CAND-9999",
    )
    result_path = finalize_goblin_run_record(
        settings,
        record,
        trace_id="trace-abc",
        trial_id="trial-xyz",
        notes=["test note"],
    )
    assert result_path.exists()
    lines = result_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["run_id"] == "test-finalize-001"
    assert payload["candidate_id"] == "AF-CAND-9999"
    assert payload["trace_id"] == "trace-abc"
    assert payload["trial_id"] == "trial-xyz"
    assert "test note" in payload["notes"]
    assert payload["ended_utc"] is not None
    assert payload["session_window"] in {
        "tokyo",
        "london",
        "london_new_york_overlap",
        "new_york",
        "off_hours",
    }


def test_finalize_appends_multiple_records(tmp_path: str) -> None:
    settings = Settings(_env_file="", project_root=str(tmp_path))
    for i in range(3):
        record = start_goblin_run_record(
            run_id=f"test-multi-{i}",
            entrypoint="run_portfolio_cycle",
        )
        finalize_goblin_run_record(settings, record)
    records_path = settings.paths().goblin_run_records_dir / "run_records.jsonl"
    lines = records_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    run_ids = [json.loads(line)["run_id"] for line in lines]
    assert run_ids == ["test-multi-0", "test-multi-1", "test-multi-2"]
