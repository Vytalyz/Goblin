from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from agentic_forex.approval.service import publish_candidate
from agentic_forex.governance.incident import (
    candidate_validation_suspended,
    compare_trade_ledgers,
    parse_tester_report_trade_count,
    run_production_incident_analysis,
)
from agentic_forex.mt5.models import MT5RunSpec
from agentic_forex.mt5.service import (
    _latest_incident_baseline_harness_passed,
    _tester_ini,
    _tester_inputs_profile_content,
)
from agentic_forex.workflows.contracts import RiskPolicy, SessionPolicy, SetupLogic, StrategySpec


def test_parse_tester_report_trade_count_html(tmp_path: Path):
    report_path = tmp_path / "report.htm"
    report_path.write_text("<td>Total Trades:</td><td><b>130</b></td>", encoding="utf-8")

    assert parse_tester_report_trade_count(report_path) == 130


def test_trade_diff_classifies_missing_extra_and_path_delta(settings, tmp_path: Path):
    reference_csv = tmp_path / "reference.csv"
    observed_csv = tmp_path / "observed.csv"
    _write_ledger(
        reference_csv,
        [
            ("2026-04-01T13:00:00Z", "2026-04-01T14:00:00Z", "long", 1.1000, 1.1020, 20.0, "take_profit", 0.01),
            ("2026-04-01T15:00:00Z", "2026-04-01T16:00:00Z", "short", 1.1050, 1.1030, 20.0, "take_profit", 0.01),
        ],
    )
    _write_ledger(
        observed_csv,
        [
            ("2026-04-01T13:00:30Z", "2026-04-01T14:00:30Z", "long", 1.1001, 1.0988, -13.0, "stop_loss", 0.01),
            ("2026-04-01T17:00:00Z", "2026-04-01T18:00:00Z", "long", 1.1000, 1.1010, 10.0, "timeout", 0.01),
        ],
    )

    summary = compare_trade_ledgers(
        reference_csv=reference_csv,
        observed_csv=observed_csv,
        reference_name="mt5_replay_audit",
        observed_name="live_audit",
        output_csv=tmp_path / "diff.csv",
        settings=settings,
    )

    assert summary.matched_count == 1
    assert summary.missing_observed_count == 1
    assert summary.extra_observed_count == 1
    assert summary.classifications["stop_target_timeout_path_delta"] == 1
    assert summary.diff_csv_path and summary.diff_csv_path.exists()


def test_production_incident_marks_harness_untrusted_without_baseline(settings, tmp_path: Path):
    live_csv = tmp_path / "live.csv"
    _write_ledger(live_csv, [("2026-04-01T13:00:00Z", "2026-04-01T14:00:00Z", "long", 1.1000, 1.0988, -12.0, "stop_loss", 0.01)])

    report = run_production_incident_analysis(
        settings,
        candidate_id="AF-CAND-0263",
        live_audit_csv=live_csv,
        incident_id="incident-test-harness",
    )

    assert report.workflow_status == "harness_untrusted"
    assert report.attribution_bucket == "harness_failure"
    assert report.validation_suspended is True
    assert "AF-CAND-0332" in report.blocked_candidate_ids


def test_production_incident_attributes_implementation_delta_after_clean_harness(settings, tmp_path: Path):
    baseline_report = tmp_path / "baseline.htm"
    baseline_report.write_text("<td>Total Trades:</td><td><b>130</b></td>", encoding="utf-8")
    mt5_csv = tmp_path / "mt5.csv"
    live_csv = tmp_path / "live.csv"
    _write_ledger(
        mt5_csv,
        [
            ("2026-04-01T13:00:00Z", "2026-04-01T14:00:00Z", "long", 1.1000, 1.1020, 20.0, "take_profit", 0.01),
        ],
    )
    _write_ledger(
        live_csv,
        [
            ("2026-04-01T13:00:20Z", "2026-04-01T14:00:20Z", "long", 1.1000, 1.1020, 20.0, "take_profit", 0.01),
            ("2026-04-01T15:00:00Z", "2026-04-01T16:00:00Z", "short", 1.1050, 1.1062, -12.0, "stop_loss", 0.01),
        ],
    )

    report = run_production_incident_analysis(
        settings,
        candidate_id="AF-CAND-0263",
        live_audit_csv=live_csv,
        mt5_replay_audit_csv=mt5_csv,
        baseline_tester_report=baseline_report,
        incident_id="incident-test-attribution",
    )

    assert report.workflow_status == "attribution_complete"
    assert report.harness_check.status == "passed"
    assert report.attribution_bucket == "implementation_delta"


def test_tester_ini_uses_explicit_profile_and_date_override(settings, tmp_path: Path):
    spec = _strategy_spec("AF-CAND-TEST")
    run_spec = MT5RunSpec(
        candidate_id=spec.candidate_id,
        run_id="mt5incident-test",
        install_id="mt5_practice_01",
        terminal_path=str(tmp_path / "terminal64.exe"),
        portable_mode=True,
        tester_mode="Every tick based on real ticks",
        tick_mode="Every tick based on real ticks",
        spread_behavior="configured_by_strategy_tester",
        allow_live_trading=False,
        shutdown_terminal=True,
        config_path=tmp_path / "tester_config.ini",
        report_path=tmp_path / "tester_report.htm",
        compile_target_path=tmp_path / "MQL5" / "Experts" / "AgenticForex" / "AF-CAND-TEST.mq5",
        compile_request_path=tmp_path / "compile_request.json",
        launch_request_path=tmp_path / "launch_request.json",
        run_dir=tmp_path,
        audit_relative_path="AgenticForex\\Audit\\audit.csv",
        broker_history_relative_path="AgenticForex\\Audit\\broker.csv",
        runtime_summary_relative_path="AgenticForex\\Audit\\runtime.json",
        signal_trace_relative_path="AgenticForex\\Audit\\trace.csv",
        tester_inputs_profile_path=tmp_path / "MQL5" / "Profiles" / "Tester" / "AF-CAND-TEST.set",
        tester_from_date="2026.03.25",
        tester_to_date="2026.04.11",
    )

    ini = _tester_ini(spec.candidate_id, run_spec, settings, spec, pd.DataFrame(columns=["timestamp_utc"]))
    profile = _tester_inputs_profile_content(run_spec, spec)

    assert "ExpertParameters=AF-CAND-TEST.set" in ini
    assert "FromDate=2026.03.25" in ini
    assert "ToDate=2026.04.11" in ini
    assert "InpRuntimeSummaryRelativePath=AgenticForex\\Audit\\runtime.json" in profile
    assert "InpSignalTraceRelativePath=AgenticForex\\Audit\\trace.csv" in profile


def test_publish_blocks_validation_suspended_candidate(settings, tmp_path: Path):
    report_dir = settings.paths().reports_dir / "AF-CAND-0263"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "review_packet.json").write_text('{"family":"scalping","readiness":"human_review_passed"}', encoding="utf-8")
    run_production_incident_analysis(
        settings,
        candidate_id="AF-CAND-0263",
        incident_id="incident-test-publish-block",
    )

    with pytest.raises(PermissionError, match="validation-suspended"):
        publish_candidate("AF-CAND-0263", settings)


def test_related_candidates_are_suspended_by_incident_blocklist(settings):
    run_production_incident_analysis(
        settings,
        candidate_id="AF-CAND-0263",
        incident_id="incident-test-related-block",
    )

    assert candidate_validation_suspended("AF-CAND-0320", settings) is True
    assert candidate_validation_suspended("AF-CAND-0332", settings) is True


def test_incident_replay_requires_repaired_baseline_harness(settings, tmp_path: Path):
    run_production_incident_analysis(
        settings,
        candidate_id="AF-CAND-0263",
        incident_id="incident-test-untrusted-baseline",
    )
    assert _latest_incident_baseline_harness_passed("AF-CAND-0263", settings) is False

    baseline_report = tmp_path / "known_good.htm"
    baseline_report.write_text("<td>Total Trades:</td><td><b>135</b></td>", encoding="utf-8")
    run_production_incident_analysis(
        settings,
        candidate_id="AF-CAND-0263",
        baseline_tester_report=baseline_report,
        incident_id="incident-test-passed-baseline",
    )
    assert _latest_incident_baseline_harness_passed("AF-CAND-0263", settings) is True


def test_harness_check_uses_candidate_configured_baseline_window(settings, tmp_path: Path):
    report_dir = settings.paths().reports_dir / "AF-CAND-CFG-BASELINE"
    report_dir.mkdir(parents=True, exist_ok=True)
    spec = _strategy_spec("AF-CAND-CFG-BASELINE")
    spec = spec.model_copy(
        update={
            "validation_profile": spec.validation_profile.model_copy(
                update={
                    "incident_baseline_window_start": "2026-01-01",
                    "incident_baseline_window_end": "2026-01-31",
                    "incident_baseline_expected_min_trade_count": 12,
                }
            )
        }
    )
    (report_dir / "strategy_spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    baseline_report = tmp_path / "configured_known_good.htm"
    baseline_report.write_text("<td>Total Trades:</td><td><b>12</b></td>", encoding="utf-8")

    report = run_production_incident_analysis(
        settings,
        candidate_id="AF-CAND-CFG-BASELINE",
        baseline_tester_report=baseline_report,
        incident_id="incident-test-configured-baseline",
    )

    assert report.harness_check.status == "passed"
    assert report.harness_check.baseline_window_start == "2026-01-01"
    assert report.harness_check.baseline_window_end == "2026-01-31"
    assert report.harness_check.expected_min_trade_count == 12


def _write_ledger(path: Path, rows: list[tuple[str, str, str, float, float, float, str, float]]) -> None:
    frame = pd.DataFrame(
        rows,
        columns=[
            "timestamp_utc",
            "exit_timestamp_utc",
            "side",
            "entry_price",
            "exit_price",
            "pnl_pips",
            "exit_reason",
            "position_size_lots",
        ],
    )
    frame.to_csv(path, index=False)


def _strategy_spec(candidate_id: str) -> StrategySpec:
    return StrategySpec(
        candidate_id=candidate_id,
        family="scalping",
        instrument="EUR_USD",
        execution_granularity="M1",
        session_policy=SessionPolicy(name="overlap", allowed_hours_utc=[13, 14, 15, 16, 17]),
        setup_logic=SetupLogic(style="overlap", summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=12.0, take_profit_pips=22.0),
        source_citations=["SRC-TEST"],
        entry_style="overlap_persistence_retest",
        holding_bars=144,
        signal_threshold=0.84,
        stop_loss_pips=12.0,
        take_profit_pips=22.0,
    )
