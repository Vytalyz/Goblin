"""Tests for tools/evaluate_strategy_s2_gates.py (Stage 2 gate decision layer)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import evaluate_strategy_s2_gates as s2  # type: ignore  # noqa: E402
import verify_strategy_decisions_schema as vsd  # type: ignore  # noqa: E402

# --- Fixtures ---------------------------------------------------------------


def _passing_backtest_summary() -> dict[str, Any]:
    return {
        "candidate_id": "AF-CAND-9001",
        "out_of_sample_profit_factor": 1.20,
        "expectancy_pips": 0.45,
        "trade_count": 250,
        "in_sample_drawdown_pct": 8.0,
        "max_drawdown_pct": 9.0,  # 12.5% degradation, under 15%
        "stress_profit_factor": 1.10,
        "walk_forward_summary": [
            {"window": 1, "profit_factor": 1.10, "trade_count": 80},
            {"window": 2, "profit_factor": 1.05, "trade_count": 75},
            {"window": 3, "profit_factor": 0.95, "trade_count": 60},
        ],
        "regime_breakdown": {
            "trend_high_vol": {"profit_factor": 1.20, "trade_count": 40},
            "trend_low_vol": {"profit_factor": 1.15, "trade_count": 60},
            "range_high_vol": {"profit_factor": 1.05, "trade_count": 70},
            "range_low_vol": {"profit_factor": 1.10, "trade_count": 80},
        },
    }


def _passing_robustness_report() -> dict[str, Any]:
    return {
        "cscv_pbo_available": True,
        "pbo": 0.20,
        "white_reality_check_available": True,
        "white_reality_check_p_value": 0.05,
        "deflated_sharpe_ratio": 0.5,
    }


def _passing_cost_sweep() -> dict[str, Any]:
    return {"baseline_pf": 1.20, "plus_1pip_pf": 1.05, "plus_2pip_pf": 0.95}


def _thresholds() -> dict[str, float]:
    # Match config defaults exactly so tests don't depend on file I/O.
    return {
        "out_of_sample_profit_factor_floor": 1.05,
        "expectancy_floor": 0.0,
        "minimum_test_trade_count": 100,
        "walk_forward_profit_factor_floor": 0.90,
        "walk_forward_min_trades_per_window": 10,
        "max_relative_drawdown_degradation_pct": 15.0,
        "stress_profit_factor_floor": 1.0,
        "pbo_threshold": 0.35,
        "white_reality_check_pvalue_threshold": 0.10,
        "deflated_sharpe_floor": 0.0,
    }


# --- Happy path -------------------------------------------------------------


def test_all_twelve_gates_pass() -> None:
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id="slot_b",
        backtest_summary=_passing_backtest_summary(),
        robustness_report=_passing_robustness_report(),
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
    )
    assert entry["outcome"] == "pass"
    assert entry["decision_id"] == "DEC-STRAT-AF-CAND-9001-S2-PASS"
    assert entry["stage"] == "S2"
    assert set(entry["gate_results"].keys()) == set(s2.ALL_GATES)
    for gate_name, gate in entry["gate_results"].items():
        assert gate["passed"] is True, f"{gate_name} unexpectedly failed: {gate}"
    assert entry["next_action"].startswith("S3:")
    assert "failure_mode" not in entry


def test_decision_entry_passes_schema_validator() -> None:
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id="slot_b",
        backtest_summary=_passing_backtest_summary(),
        robustness_report=_passing_robustness_report(),
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
    )
    seen_ids: set[str] = set()
    vsd._check_entry(1, entry, seen_ids=seen_ids)
    assert entry["decision_id"] in seen_ids


# --- Per-gate failure modes -------------------------------------------------


def test_oos_pf_below_floor_fails() -> None:
    bs = _passing_backtest_summary()
    bs["out_of_sample_profit_factor"] = 1.04
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id=None,
        backtest_summary=bs,
        robustness_report=_passing_robustness_report(),
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
    )
    assert entry["outcome"] == "fail"
    assert entry["decision_id"] == "DEC-STRAT-AF-CAND-9001-S2-FAIL"
    assert entry["gate_results"][s2.GATE_OOS_PF]["passed"] is False
    assert "oos_profit_factor" in entry["failure_mode"]
    assert entry["next_action"].startswith("RETIRE")


def test_negative_expectancy_fails() -> None:
    bs = _passing_backtest_summary()
    bs["expectancy_pips"] = -0.1
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id=None,
        backtest_summary=bs,
        robustness_report=_passing_robustness_report(),
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
    )
    assert entry["outcome"] == "fail"
    assert entry["gate_results"][s2.GATE_OOS_EXPECTANCY]["passed"] is False


def test_low_trade_count_fails() -> None:
    bs = _passing_backtest_summary()
    bs["trade_count"] = 50
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id=None,
        backtest_summary=bs,
        robustness_report=_passing_robustness_report(),
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
    )
    assert entry["gate_results"][s2.GATE_OOS_TRADE_COUNT]["passed"] is False


def test_walk_forward_pf_below_floor_fails() -> None:
    bs = _passing_backtest_summary()
    bs["walk_forward_summary"][2]["profit_factor"] = 0.85
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id=None,
        backtest_summary=bs,
        robustness_report=_passing_robustness_report(),
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
    )
    assert entry["gate_results"][s2.GATE_WF_PF]["passed"] is False
    assert entry["gate_results"][s2.GATE_WF_PF]["value"] == 0.85


def test_walk_forward_min_trades_fails() -> None:
    bs = _passing_backtest_summary()
    bs["walk_forward_summary"][1]["trade_count"] = 5
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id=None,
        backtest_summary=bs,
        robustness_report=_passing_robustness_report(),
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
    )
    assert entry["gate_results"][s2.GATE_WF_TRADES]["passed"] is False


def test_drawdown_degradation_above_threshold_fails() -> None:
    bs = _passing_backtest_summary()
    bs["in_sample_drawdown_pct"] = 5.0
    bs["max_drawdown_pct"] = 7.0  # 40% degradation
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id=None,
        backtest_summary=bs,
        robustness_report=_passing_robustness_report(),
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
    )
    assert entry["gate_results"][s2.GATE_DD_DEGRADATION]["passed"] is False
    assert entry["gate_results"][s2.GATE_DD_DEGRADATION]["value"] == 40.0


def test_stress_pf_below_floor_fails() -> None:
    bs = _passing_backtest_summary()
    bs["stress_profit_factor"] = 0.95
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id=None,
        backtest_summary=bs,
        robustness_report=_passing_robustness_report(),
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
    )
    assert entry["gate_results"][s2.GATE_STRESS_PF]["passed"] is False


def test_regime_with_negative_pf_fails() -> None:
    bs = _passing_backtest_summary()
    bs["regime_breakdown"]["range_high_vol"]["profit_factor"] = 0.85
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id=None,
        backtest_summary=bs,
        robustness_report=_passing_robustness_report(),
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
    )
    g = entry["gate_results"][s2.GATE_REGIME_NON_NEG]
    assert g["passed"] is False
    assert "range_high_vol" in (g.get("notes") or "")


def test_regime_breakdown_as_list_supported() -> None:
    bs = _passing_backtest_summary()
    bs["regime_breakdown"] = [
        {"regime": "trend_high_vol", "profit_factor": 1.20},
        {"regime": "trend_low_vol", "profit_factor": 1.05},
    ]
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id=None,
        backtest_summary=bs,
        robustness_report=_passing_robustness_report(),
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
    )
    assert entry["gate_results"][s2.GATE_REGIME_NON_NEG]["passed"] is True


def test_cost_persistence_below_floor_fails() -> None:
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id=None,
        backtest_summary=_passing_backtest_summary(),
        robustness_report=_passing_robustness_report(),
        cost_sweep={"plus_1pip_pf": 0.92},
        thresholds=_thresholds(),
    )
    assert entry["gate_results"][s2.GATE_COST_PERSISTENCE]["passed"] is False


def test_missing_cost_sweep_fails_without_provisional() -> None:
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id=None,
        backtest_summary=_passing_backtest_summary(),
        robustness_report=_passing_robustness_report(),
        cost_sweep=None,
        thresholds=_thresholds(),
    )
    g = entry["gate_results"][s2.GATE_COST_PERSISTENCE]
    assert g["passed"] is False
    assert "cost-sensitivity" in (g.get("notes") or "")


def test_pbo_above_threshold_fails() -> None:
    rr = _passing_robustness_report()
    rr["pbo"] = 0.50
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id=None,
        backtest_summary=_passing_backtest_summary(),
        robustness_report=rr,
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
    )
    assert entry["gate_results"][s2.GATE_PBO]["passed"] is False


def test_whites_p_above_threshold_fails() -> None:
    rr = _passing_robustness_report()
    rr["white_reality_check_p_value"] = 0.20
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id=None,
        backtest_summary=_passing_backtest_summary(),
        robustness_report=rr,
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
    )
    assert entry["gate_results"][s2.GATE_WHITES_P]["passed"] is False


def test_dsr_below_floor_fails() -> None:
    rr = _passing_robustness_report()
    rr["deflated_sharpe_ratio"] = -0.1
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id=None,
        backtest_summary=_passing_backtest_summary(),
        robustness_report=rr,
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
    )
    assert entry["gate_results"][s2.GATE_DSR]["passed"] is False


# --- Provisional handling ---------------------------------------------------


def test_unavailable_pbo_fails_without_provisional() -> None:
    rr = _passing_robustness_report()
    rr["cscv_pbo_available"] = False
    rr["pbo"] = None
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id=None,
        backtest_summary=_passing_backtest_summary(),
        robustness_report=rr,
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
        allow_provisional=False,
    )
    assert entry["gate_results"][s2.GATE_PBO]["passed"] is False


def test_unavailable_pbo_passes_with_provisional() -> None:
    rr = _passing_robustness_report()
    rr["cscv_pbo_available"] = False
    rr["pbo"] = None
    rr["white_reality_check_available"] = False
    rr["white_reality_check_p_value"] = None
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id=None,
        backtest_summary=_passing_backtest_summary(),
        robustness_report=rr,
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
        allow_provisional=True,
    )
    assert entry["outcome"] == "pass"
    assert entry["gate_results"][s2.GATE_PBO]["passed"] is True
    assert "provisional" in (entry["gate_results"][s2.GATE_PBO]["notes"] or "")
    assert entry["gate_results"][s2.GATE_WHITES_P]["passed"] is True


# --- Threshold loading ------------------------------------------------------


def test_load_thresholds_from_real_config() -> None:
    th = s2.load_thresholds()
    assert th["out_of_sample_profit_factor_floor"] == 1.05
    assert th["pbo_threshold"] == 0.35
    assert th["white_reality_check_pvalue_threshold"] == 0.10
    assert th["walk_forward_profit_factor_floor"] == 0.90
    assert th["minimum_test_trade_count"] == 100


# --- Append + CLI -----------------------------------------------------------


def test_append_decision_writes_one_line(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    entry = s2.evaluate_s2(
        candidate_id="AF-CAND-9001",
        slot_id="slot_b",
        backtest_summary=_passing_backtest_summary(),
        robustness_report=_passing_robustness_report(),
        cost_sweep=_passing_cost_sweep(),
        thresholds=_thresholds(),
    )
    s2.append_decision(entry, decisions_log=log)
    s2.append_decision(entry, decisions_log=log)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["decision_id"] == "DEC-STRAT-AF-CAND-9001-S2-PASS"


def test_cli_main_passes_with_inline_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    bs_path = tmp_path / "bt.json"
    rr_path = tmp_path / "rb.json"
    cs_path = tmp_path / "cs.json"
    log_path = tmp_path / "decisions.jsonl"
    bs_path.write_text(json.dumps(_passing_backtest_summary()))
    rr_path.write_text(json.dumps(_passing_robustness_report()))
    cs_path.write_text(json.dumps(_passing_cost_sweep()))
    monkeypatch.setattr(s2, "DECISIONS_LOG", log_path)

    rc = s2.main(
        [
            "--candidate-id",
            "AF-CAND-9001",
            "--slot-id",
            "slot_b",
            "--backtest-summary",
            str(bs_path),
            "--robustness-report",
            str(rr_path),
            "--cost-sweep",
            str(cs_path),
            "--json",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["outcome"] == "pass"
    assert log_path.exists()
    assert json.loads(log_path.read_text().splitlines()[0])["decision_id"] == "DEC-STRAT-AF-CAND-9001-S2-PASS"


def test_cli_main_fail_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    bs = _passing_backtest_summary()
    bs["out_of_sample_profit_factor"] = 0.50
    bs_path = tmp_path / "bt.json"
    rr_path = tmp_path / "rb.json"
    log_path = tmp_path / "decisions.jsonl"
    bs_path.write_text(json.dumps(bs))
    rr_path.write_text(json.dumps(_passing_robustness_report()))
    monkeypatch.setattr(s2, "DECISIONS_LOG", log_path)

    rc = s2.main(
        [
            "--candidate-id",
            "AF-CAND-9001",
            "--backtest-summary",
            str(bs_path),
            "--robustness-report",
            str(rr_path),
        ]
    )
    assert rc == 1
    assert log_path.exists()
    line = json.loads(log_path.read_text().splitlines()[0])
    assert line["decision_id"].endswith("S2-FAIL")


def test_cli_main_missing_artifact_returns_2(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = s2.main(
        [
            "--candidate-id",
            "AF-CAND-9001",
            "--backtest-summary",
            str(tmp_path / "missing.json"),
            "--robustness-report",
            str(tmp_path / "missing2.json"),
            "--no-append",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "ERROR" in err
