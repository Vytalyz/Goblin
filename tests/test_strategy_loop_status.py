"""Tests for tools/strategy_loop_status.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import strategy_loop_status as sls  # noqa: E402


def _entry(**overrides) -> dict:
    base = {
        "decision_id": "DEC-STRAT-AF-CAND-1001-S2-PASS",
        "candidate_id": "AF-CAND-1001",
        "stage": "S2",
        "outcome": "pass",
        "decided_by": "runner",
        "decided_at": "2026-04-22T14:32:11Z",
        "rationale": "All twelve S2 gates met with comfortable margins on in-sample evaluation.",
        "gate_results": {},
        "evidence_uris": [],
        "next_action": "proceed_to_S3",
    }
    base.update(overrides)
    return base


def test_latest_per_candidate_returns_last_entry_per_candidate() -> None:
    entries = [
        _entry(decision_id="DEC-STRAT-AF-CAND-1001-S2-PASS", stage="S2"),
        _entry(decision_id="DEC-STRAT-AF-CAND-1001-S3-PASS", stage="S3"),
        _entry(
            decision_id="DEC-STRAT-AF-CAND-1002-S1-PASS",
            stage="S1",
            candidate_id="AF-CAND-1002",
        ),
    ]
    latest = sls._latest_per_candidate(entries)
    assert list(latest.keys()) == ["AF-CAND-1001", "AF-CAND-1002"]
    assert latest["AF-CAND-1001"]["stage"] == "S3"
    assert latest["AF-CAND-1002"]["stage"] == "S1"


def test_latest_per_candidate_skips_entries_without_candidate_id() -> None:
    entries = [{"foo": "bar"}, _entry()]
    latest = sls._latest_per_candidate(entries)
    assert "AF-CAND-1001" in latest
    assert len(latest) == 1


def test_build_status_with_real_repo_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke test against the real (likely empty) decisions log."""
    status = sls.build_status()
    assert "slots" in status
    assert "decisions_total" in status
    assert "candidates_tracked" in status
    assert isinstance(status["slots"], list)


def test_build_status_with_isolated_log(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log = tmp_path / "strategy_decisions.jsonl"
    log.write_text(
        json.dumps(_entry())
        + "\n"
        + json.dumps(_entry(decision_id="DEC-STRAT-AF-CAND-1001-S3-PASS", stage="S3"))
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sls, "DECISIONS_LOG", log)

    status = sls.build_status(candidate_filter="AF-CAND-1001")
    assert status["decisions_total"] == 2
    assert status["candidates_tracked"] == 1
    assert status["candidate_filter"] == "AF-CAND-1001"
    assert status["candidate_history_count"] == 2


def test_build_status_with_missing_log_does_not_raise(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sls, "DECISIONS_LOG", tmp_path / "does_not_exist.jsonl")
    status = sls.build_status()
    assert status["decisions_total"] == 0
    assert status["candidates_tracked"] == 0


def test_build_status_with_invalid_json_skips_line(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log = tmp_path / "strategy_decisions.jsonl"
    log.write_text(
        "{not valid json}\n" + json.dumps(_entry()) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sls, "DECISIONS_LOG", log)

    status = sls.build_status()
    assert status["decisions_total"] == 1


def test_format_text_is_non_empty() -> None:
    status = sls.build_status()
    text = sls._format_text(status)
    assert "Goblin Strategy Loop" in text
    assert "Portfolio slots" in text


def test_main_emits_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    rc = sls.main(["--json"])
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert "slots" in payload


def test_main_emits_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = sls.main([])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Goblin Strategy Loop" in captured.out


def test_main_with_candidate_filter(capsys: pytest.CaptureFixture[str]) -> None:
    rc = sls.main(["--candidate", "AF-CAND-DOES-NOT-EXIST"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "AF-CAND-DOES-NOT-EXIST" in captured.out
