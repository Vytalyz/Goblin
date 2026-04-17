from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import time
from pathlib import Path

import pandas as pd
import pytest

from agentic_forex.approval.models import ApprovalRecord
from agentic_forex.approval.service import record_approval
from agentic_forex.backtesting.models import BacktestArtifact
from agentic_forex.backtesting.engine import _generate_signal, run_backtest, run_stress_test
from agentic_forex.campaigns import run_bounded_campaign
from agentic_forex.config.models import ProgramLanePolicy
from agentic_forex.forward import run_shadow_forward
from agentic_forex.forward.service import _select_forward_frame_for_minimum_evidence
from agentic_forex.governance import CampaignSpec
from agentic_forex.governance.trial_ledger import append_trial_entry, count_trials
from agentic_forex.market_data.ingest import ingest_oanda_json
from agentic_forex.mt5 import service as mt5_service
from agentic_forex.mt5.ea_generator import render_candidate_ea
from agentic_forex.mt5.models import MT5Packet, MT5ParityReport, MT5RunResult, MT5RunSpec, MT5ValidationReport
from agentic_forex.mt5.service import (
    _is_packet_stale,
    _manual_run_strategy_spec,
    _parity_class_from_report,
    _resolve_effective_parity_policy,
    _resolve_executable_exit,
    _archive_tester_report_bundle,
    _clear_tester_cache,
    _discover_tester_report,
    _prepare_automated_terminal_runtime,
    _stage_existing_build_for_launch,
    _tester_ini,
    generate_mt5_packet,
    validate_mt5_practice,
)
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.policy.calendar import ingest_economic_calendar
from agentic_forex.runtime import ReadPolicy
from agentic_forex.utils.ids import next_candidate_id
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows.contracts import CandidateDraft, MarketContextSummary, RiskPolicy, SessionPolicy, SetupLogic, StrategySpec

from conftest import create_economic_calendar_csv, create_oanda_candles_json


def test_forward_stage_and_trial_ledger_artifacts(settings, tmp_path):
    settings.validation.forward_min_trading_days = 2
    settings.validation.forward_min_trade_count = 10
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    candidate = _candidate("AF-CAND-GOV-FWD", "Governance Forward Candidate")
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)

    run_backtest(spec, settings)
    run_stress_test(spec, settings)
    forward_report = run_shadow_forward(spec, settings)

    assert (settings.paths().reports_dir / spec.candidate_id / "data_provenance.json").exists()
    assert (settings.paths().reports_dir / spec.candidate_id / "environment_snapshot.json").exists()
    assert forward_report.report_path.exists()

    ledger_path = settings.paths().experiments_dir / "trial_ledger.jsonl"
    entries = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    stages = {entry["stage"] for entry in entries if entry["candidate_id"] == spec.candidate_id}
    assert {"backtested", "stress_test", "forward_stage"} <= stages


def test_forward_stage_expands_recent_window_until_minimum_evidence_is_met(settings, tmp_path):
    settings.validation.forward_min_trading_days = 10
    settings.validation.forward_min_trade_count = 25
    candidate = _candidate("AF-CAND-GOV-FWD-EXPAND", "Governance Forward Expansion Candidate")
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)

    timestamps = pd.date_range("2026-01-01T00:00:00Z", periods=15, freq="D", tz="UTC")
    frame = pd.DataFrame({"timestamp_utc": timestamps})
    trade_counts_by_days = {10: 18, 11: 20, 12: 22, 13: 26, 14: 28, 15: 30}
    calls: list[int] = []

    def _fake_evaluator(spec_arg, settings_arg, *, output_prefix, frame):
        observed_days = int(frame["timestamp_utc"].dt.normalize().nunique())
        calls.append(observed_days)
        report_dir = settings.paths().reports_dir / spec_arg.candidate_id
        report_dir.mkdir(parents=True, exist_ok=True)
        return BacktestArtifact(
            candidate_id=spec_arg.candidate_id,
            spec_path=report_dir / "strategy_spec.json",
            trade_ledger_path=report_dir / f"{output_prefix}_trade_ledger.csv",
            summary_path=report_dir / f"{output_prefix}_summary.json",
            trade_count=trade_counts_by_days[observed_days],
            win_rate=0.55,
            profit_factor=1.2,
            expectancy_pips=0.8,
            max_drawdown_pct=0.5,
            out_of_sample_profit_factor=1.1,
            account_metrics={"trading_days_observed": observed_days},
        )

    selected_frame, artifact = _select_forward_frame_for_minimum_evidence(
        frame,
        spec,
        settings,
        evaluator=_fake_evaluator,
    )

    assert artifact.trade_count == 26
    assert artifact.account_metrics["trading_days_observed"] == 13
    assert int(selected_frame["timestamp_utc"].dt.normalize().nunique()) == 13
    assert calls[:4] == [10, 11, 12, 13]


def test_next_candidate_id_advances_past_existing_report_dirs(settings):
    counter_path = settings.paths().state_dir / "candidate_counter.txt"
    counter_path.write_text("140", encoding="utf-8")
    for candidate_id in ("AF-CAND-0149", "AF-CAND-0152", "AF-CAND-0001-FADE"):
        (settings.paths().reports_dir / candidate_id).mkdir(parents=True, exist_ok=True)

    candidate_id = next_candidate_id(settings)

    assert candidate_id == "AF-CAND-0153"
    assert counter_path.read_text(encoding="utf-8").strip() == "153"


def test_next_candidate_id_is_unique_under_concurrent_calls(settings):
    counter_path = settings.paths().state_dir / "candidate_counter.txt"
    counter_path.write_text("200", encoding="utf-8")
    (settings.paths().reports_dir / "AF-CAND-0200").mkdir(parents=True, exist_ok=True)

    with ThreadPoolExecutor(max_workers=6) as executor:
        candidate_ids = list(executor.map(lambda _: next_candidate_id(settings), range(6)))

    assert len(set(candidate_ids)) == 6
    assert set(candidate_ids) == {f"AF-CAND-{sequence:04d}" for sequence in range(201, 207)}
    assert counter_path.read_text(encoding="utf-8").strip() == "206"


def test_count_trials_ignores_malformed_jsonl_lines(settings):
    ledger_path = settings.paths().experiments_dir / "trial_ledger.jsonl"
    ledger_path.write_text(
        "\n".join(
            [
                json.dumps({"candidate_id": "AF-CAND-0201", "family": "europe_open_reclaim_research"}),
                "",
                'Z"}',
                json.dumps({"candidate_id": "AF-CAND-0202", "family": "europe_open_failed_break_research"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert count_trials(settings) == 2
    assert count_trials(settings, family="europe_open_reclaim_research") == 1
    assert count_trials(settings, candidate_id="AF-CAND-0202") == 1


def test_compile_strategy_spec_tool_applies_structure_style_filters_outside_retired_family(settings):
    candidate = CandidateDraft(
        candidate_id="AF-CAND-GOV-STRUCTURE",
        family="structure_transition_research",
        title="Structure Transition Root",
        thesis="Use structure-transition templates under a fresh family without reviving retired day_trading evidence.",
        source_citations=["SRC-TEST"],
        strategy_hypothesis="Structured transition entries should preserve their deterministic filters under a fresh family label.",
        market_context=MarketContextSummary(
            session_focus="overlap_trend_retest",
            volatility_preference="moderate_to_high",
            directional_bias="both",
            execution_notes=["Test structure-transition family mapping."],
            allowed_hours_utc=[10, 11, 12, 13, 14, 15, 16],
        ),
        setup_summary="Require established direction first, then wait for a controlled retest.",
        entry_summary="Enter after a trend retest when direction, retest depth, and recovery align.",
        exit_summary="Exit via fixed stop, fixed target, or timeout.",
        risk_summary="Use one position at a time with explicit spread and session controls.",
        quality_flags=["governed"],
        entry_style="trend_retest",
        holding_bars=96,
        signal_threshold=1.0,
        stop_loss_pips=8.5,
        take_profit_pips=14.0,
    )

    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)
    filters = {item.name: item.rule for item in spec.filters}

    assert spec.family == "structure_transition_research"
    assert filters["trend_ret_5_min"] == "0.00012"
    assert filters["retest_zscore_limit"] == "0.35"
    assert filters["retest_range_position_floor"] == "0.52"
    assert filters["require_recovery_ret_1"] == "true"


def test_compile_strategy_spec_tool_applies_directional_style_filters_outside_retired_family(settings):
    candidate = CandidateDraft(
        candidate_id="AF-CAND-GOV-DIRECTIONAL",
        family="session_edge_research",
        title="Session Breakout Root",
        thesis="Use directional session-breakout templates under a fresh family without reviving retired scalping evidence.",
        source_citations=["SRC-TEST"],
        strategy_hypothesis="Directional session-edge entries should preserve their deterministic filters under a fresh family label.",
        market_context=MarketContextSummary(
            session_focus="extended_session_quality_breakout",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Test directional family mapping."],
            allowed_hours_utc=[6, 7, 8, 9, 10, 11, 12, 13, 14],
        ),
        setup_summary="Broaden the active session to capture more high-quality Europe and early-overlap breakouts.",
        entry_summary="Enter on breakout continuation when momentum, price location, and short-term return align.",
        exit_summary="Exit via fixed stop, fixed target, or timeout.",
        risk_summary="Use one position at a time with explicit spread and session controls.",
        quality_flags=["governed"],
        entry_style="session_breakout",
        holding_bars=26,
        signal_threshold=0.96,
        stop_loss_pips=4.2,
        take_profit_pips=7.4,
    )

    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)
    filters = {item.name: item.rule for item in spec.filters}

    assert spec.family == "session_edge_research"
    assert filters["max_spread_pips"] == "2.0"
    assert filters["min_volatility_20"] == "0.00012"
    assert filters["require_ret_5_alignment"] == "true"
    assert filters["require_mean_location_alignment"] == "true"


def test_compile_strategy_spec_tool_propagates_custom_filters_and_news_blackout(settings):
    candidate = CandidateDraft(
        candidate_id="AF-CAND-GOV-CONTEXT",
        family="context_selective_research",
        title="Context Selective Breakout Root",
        thesis="Propagate explicit context filtering and governed news blackout into the compiled strategy spec.",
        source_citations=["SRC-TEST"],
        strategy_hypothesis="Only trade the supported context slice instead of carrying the full context mix into research.",
        market_context=MarketContextSummary(
            session_focus="europe_context_selective_breakout",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Test context-selective propagation."],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Trade only the filtered Europe breakout slice.",
        entry_summary="Enter on breakout continuation when the allowed context and directional filters align.",
        exit_summary="Exit via fixed stop, fixed target, or timeout.",
        risk_summary="Use one position at a time with explicit spread, session, and news discipline.",
        quality_flags=["governed", "context_selective"],
        custom_filters=[
            {"name": "exclude_context_bucket", "rule": "trend_context"},
            {"name": "breakout_zscore_floor", "rule": "0.45"},
        ],
        enable_news_blackout=True,
        entry_style="session_breakout",
        holding_bars=18,
        signal_threshold=0.98,
        stop_loss_pips=5.0,
        take_profit_pips=9.0,
    )

    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)
    filters = {item.name: item.rule for item in spec.filters}

    assert spec.news_policy.enabled is True
    assert spec.risk_envelope.news_event_policy == "calendar_blackout"
    assert filters["exclude_context_bucket"] == "trend_context"
    assert filters["breakout_zscore_floor"] == "0.45"


def test_mt5_contract_flags_and_campaign_state(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    candidate = _candidate("AF-CAND-GOV-MT5", "Governance MT5 Candidate")
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)
    run_backtest(spec, settings)

    record_approval(
        ApprovalRecord(
            candidate_id=spec.candidate_id,
            stage="mt5_packet",
            decision="approve",
            approver="pytest",
            rationale="Packet generation approved for governance testing.",
        ),
        settings,
    )
    record_approval(
        ApprovalRecord(
            candidate_id=spec.candidate_id,
            stage="mt5_validation",
            decision="approve",
            approver="pytest",
            rationale="Validation approved for governance testing.",
        ),
        settings,
    )

    packet = generate_mt5_packet(spec.candidate_id, settings)
    tester_ini = packet.tester_config_path.read_text(encoding="utf-8")
    assert "AllowLiveTrading=0" in tester_ini
    assert "ShutdownTerminal=1" in tester_ini
    assert packet.ea_source_path.exists()
    ea_source = packet.ea_source_path.read_text(encoding="utf-8")
    assert spec.candidate_id in ea_source
    assert "void OnTick()" in ea_source
    assert packet.run_spec_path.exists()
    assert packet.compile_request_path.exists()
    assert packet.launch_request_path.exists()
    compile_request = read_json(packet.compile_request_path)
    assert compile_request["packet_source_path"] == str(packet.ea_source_path)
    if packet.metaeditor_path and packet.terminal_data_path:
        assert packet.deployed_source_path and packet.deployed_source_path.exists()
        assert packet.compiled_ex5_path and packet.compiled_ex5_path.exists()
        if packet.compile_log_path is not None:
            assert packet.compile_log_path.exists()

    audit_csv = tmp_path / "mt5_audit.csv"
    pd.read_csv(packet.expected_signal_path).to_csv(audit_csv, index=False)
    validation = validate_mt5_practice(spec.candidate_id, settings, audit_csv)
    assert validation.validation_status == "passed"
    assert validation.run_id

    campaign = CampaignSpec(
        campaign_id="campaign-governance-stop",
        family="scalping",
        baseline_candidate_id="AF-CAND-0001",
        target_candidate_ids=["AF-CAND-0014"],
        max_iterations=0,
        trial_cap_per_family=1,
    )
    state = run_bounded_campaign(campaign, settings)
    assert state.state_path.exists()
    assert read_json(state.state_path)["stop_reason"] == "max_iterations_reached"


def test_resolve_effective_parity_policy_ignores_self_parent_lineage_entries(settings):
    candidate = _candidate("AF-CAND-GOV-PARITY-ROOT", "Parity Root Candidate")
    candidate.family = "parity_scope_research"
    candidate.entry_style = "session_breakout"
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="promotion_parity_scope_root",
            family=spec.family,
            hypothesis_class=spec.entry_style,
            seed_candidate_id=spec.candidate_id,
            queue_kind="promotion",
            parity_class="m1_official",
            parity_class_assigned_by="pytest",
            parity_class_assigned_at="2026-03-24T00:00:00Z",
        )
    ]
    append_trial_entry(
        settings,
        candidate_id=spec.candidate_id,
        family=spec.family,
        stage="formalize_rule_candidate",
        parent_candidate_ids=[spec.candidate_id],
        mutation_policy="throughput_rule_formalization",
    )

    started = time.perf_counter()
    policy = _resolve_effective_parity_policy(spec.candidate_id, settings, enforce_official=True)
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0
    assert policy["lineage_root_candidate_id"] == spec.candidate_id
    assert policy["parity_class"] == "m1_official"


def test_generated_mt5_packet_is_not_immediately_stale(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    candidate = _candidate("AF-CAND-GOV-PACKET", "Packet Freshness Candidate")
    candidate.family = "packet_freshness_research"
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)
    run_backtest(spec, settings)

    record_approval(
        ApprovalRecord(
            candidate_id=spec.candidate_id,
            stage="mt5_packet",
            decision="approve",
            approver="pytest",
            rationale="Packet generation approved for freshness regression.",
        ),
        settings,
    )
    record_approval(
        ApprovalRecord(
            candidate_id=spec.candidate_id,
            stage="mt5_validation",
            decision="approve",
            approver="pytest",
            rationale="Validation approved for freshness regression.",
        ),
        settings,
    )

    packet = generate_mt5_packet(spec.candidate_id, settings)

    assert _is_packet_stale(spec.candidate_id, settings, packet) is False


def test_tester_ini_uses_real_login_and_mt5_symbol(settings, tmp_path):
    terminal_root = tmp_path / "mt5-runtime"
    terminal_root.mkdir(parents=True, exist_ok=True)
    (terminal_root / "terminal64.exe").write_text("", encoding="utf-8")
    (terminal_root / "Config").mkdir(parents=True, exist_ok=True)
    (terminal_root / "Config" / "common.ini").write_text("[Common]\nLogin=5087443\n", encoding="utf-8")

    candidate = _candidate("AF-CAND-GOV-SMOKE", "Governance Smoke Candidate")
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)

    run_spec = MT5RunSpec(
        candidate_id=spec.candidate_id,
        run_id="mt5run-smoke",
        install_id="mt5_practice_01",
        terminal_path=str(terminal_root / "terminal64.exe"),
        portable_mode=True,
        tester_mode=settings.mt5_env.tester_mode,
        tick_mode=settings.mt5_env.tester_mode,
        spread_behavior="configured_by_strategy_tester",
        allow_live_trading=False,
        shutdown_terminal=True,
        config_path=tmp_path / "tester.ini",
        report_path=tmp_path / "tester_report.htm",
        compile_target_path=tmp_path / "CandidateEA.mq5",
        compile_request_path=tmp_path / "compile_request.json",
        launch_request_path=tmp_path / "launch_request.json",
        run_dir=tmp_path,
    )
    tester_ini = _tester_ini(
        spec.candidate_id,
        run_spec,
        settings,
        spec,
        pd.DataFrame.from_records(
            [
                {
                    "timestamp_utc": "2024-01-01T00:00:00Z",
                    "exit_timestamp_utc": "2024-01-01T01:00:00Z",
                    "side": "long",
                    "entry_price": 1.1,
                    "exit_price": 1.101,
                    "pnl_pips": 10.0,
                    "candidate_id": spec.candidate_id,
                }
            ]
        ),
    )

    assert "Login=5087443" in tester_ini
    assert "Symbol=EURUSD" in tester_ini
    assert "Report=AF-CAND-GOV-SMOKE-mt5run-smoke-report" in tester_ini


def test_tester_ini_uses_run_spec_tester_mode_override(settings, tmp_path):
    candidate = _candidate("AF-CAND-GOV-PARITY-MODE", "Governance Parity Mode Candidate")
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)

    run_spec = MT5RunSpec(
        candidate_id=spec.candidate_id,
        run_id="mt5run-parity-mode",
        install_id="mt5_practice_01",
        terminal_path=str(tmp_path / "terminal64.exe"),
        portable_mode=True,
        tester_mode="1 minute OHLC",
        tick_mode="1 minute OHLC",
        spread_behavior="configured_by_strategy_tester",
        allow_live_trading=False,
        shutdown_terminal=True,
        config_path=tmp_path / "tester.ini",
        report_path=tmp_path / "tester_report.htm",
        compile_target_path=tmp_path / "CandidateEA.mq5",
        compile_request_path=tmp_path / "compile_request.json",
        launch_request_path=tmp_path / "launch_request.json",
        run_dir=tmp_path,
    )

    tester_ini = _tester_ini(
        spec.candidate_id,
        run_spec,
        settings,
        spec,
        pd.DataFrame.from_records(
            [
                {
                    "timestamp_utc": "2024-01-01T00:00:00Z",
                    "exit_timestamp_utc": "2024-01-01T01:00:00Z",
                    "side": "long",
                    "entry_price": 1.1,
                    "exit_price": 1.101,
                    "pnl_pips": 10.0,
                    "candidate_id": spec.candidate_id,
                }
            ]
        ),
    )

    assert "Model=1" in tester_ini


def test_run_mt5_parity_blocks_when_parity_class_is_unset(settings):
    candidate = _candidate("AF-CAND-GOV-PARITY-UNSET", "Governance Parity Unset Candidate")
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="lane-parity-unset",
            family=spec.family,
            hypothesis_class=spec.entry_style,
            seed_candidate_id=spec.candidate_id,
            queue_kind="promotion",
        )
    ]
    for stage in ("mt5_packet", "mt5_parity_run", "mt5_validation"):
        record_approval(
            ApprovalRecord(
                candidate_id=spec.candidate_id,
                stage=stage,
                decision="approve",
                approver="pytest",
                rationale="Approved for parity policy enforcement testing.",
            ),
            settings,
        )

    with pytest.raises(mt5_service.ParityPolicyError, match="parity_policy_unset"):
        mt5_service.run_mt5_parity(spec.candidate_id, settings)


def test_run_mt5_parity_blocks_when_tick_aware_class_is_required(settings):
    candidate = _candidate("AF-CAND-GOV-PARITY-TICK", "Governance Tick Required Candidate")
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="lane-parity-tick-required",
            family=spec.family,
            hypothesis_class=spec.entry_style,
            seed_candidate_id=spec.candidate_id,
            parity_class="tick_required",
            queue_kind="promotion",
        )
    ]
    for stage in ("mt5_packet", "mt5_parity_run", "mt5_validation"):
        record_approval(
            ApprovalRecord(
                candidate_id=spec.candidate_id,
                stage=stage,
                decision="approve",
                approver="pytest",
                rationale="Approved for parity policy enforcement testing.",
            ),
            settings,
        )

    with pytest.raises(mt5_service.ParityPolicyError, match="parity_policy_blocked"):
        mt5_service.run_mt5_parity(spec.candidate_id, settings)


def test_run_mt5_parity_diagnostic_uses_non_authoritative_real_ticks_mode(settings, tmp_path, monkeypatch):
    settings.mt5_env.parity_diagnostic_tester_mode = "Every tick based on real ticks"
    candidate = _candidate("AF-CAND-GOV-PARITY-DIAG", "Governance Parity Diagnostic Candidate")
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="lane-parity-diagnostic-tick",
            family=spec.family,
            hypothesis_class=spec.entry_style,
            seed_candidate_id=spec.candidate_id,
            parity_class="tick_required",
            queue_kind="promotion",
        )
    ]
    for stage in ("mt5_packet", "mt5_parity_run", "mt5_validation"):
        record_approval(
            ApprovalRecord(
                candidate_id=spec.candidate_id,
                stage=stage,
                decision="approve",
                approver="pytest",
                rationale="Approved for parity diagnostic policy testing.",
            ),
            settings,
        )

    packet_dir = tmp_path / "packet"
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_run_spec_path = tmp_path / "packet_run_spec.json"
    packet_run_spec = MT5RunSpec(
        candidate_id=spec.candidate_id,
        run_id="mt5run-packet",
        install_id="mt5_practice_01",
        terminal_path=str(tmp_path / "terminal64.exe"),
        portable_mode=True,
        tester_mode="1 minute OHLC",
        tick_mode="1 minute OHLC",
        spread_behavior="configured_by_strategy_tester",
        allow_live_trading=False,
        shutdown_terminal=True,
        config_path=tmp_path / "packet_tester.ini",
        report_path=tmp_path / "packet_report.htm",
        compile_target_path=tmp_path / "CandidateEA.mq5",
        compile_request_path=tmp_path / "compile_request.json",
        launch_request_path=tmp_path / "packet_launch_request.json",
        run_dir=tmp_path,
    )
    packet_run_spec_path.write_text(packet_run_spec.model_dump_json(indent=2), encoding="utf-8")
    packet = MT5Packet(
        candidate_id=spec.candidate_id,
        packet_dir=packet_dir,
        logic_manifest_path=packet_dir / "logic_manifest.json",
        expected_signal_path=packet_dir / "expected_signals.csv",
        notes_path=packet_dir / "notes.md",
        ea_source_path=packet_dir / "CandidateEA.mq5",
        run_spec_path=packet_run_spec_path,
        tester_config_path=tmp_path / "tester_config.ini",
        compile_request_path=tmp_path / "compile_request.json",
        launch_request_path=tmp_path / "launch_request.json",
        logic_manifest_hash="logic-hash",
    )

    captured: dict[str, object] = {}

    monkeypatch.setattr(mt5_service, "require_stage_approval", lambda *args, **kwargs: None)
    monkeypatch.setattr(mt5_service, "load_mt5_packet", lambda *args, **kwargs: packet)
    monkeypatch.setattr(mt5_service, "_is_packet_stale", lambda *args, **kwargs: False)
    monkeypatch.setattr(mt5_service, "_load_spec", lambda *args, **kwargs: spec)
    monkeypatch.setattr(
        mt5_service,
        "_load_expected_signal_frame",
        lambda *args, **kwargs: pd.DataFrame(columns=["timestamp_utc", "exit_timestamp_utc"]),
    )

    def _fake_parity_run_spec_from_packet(*args, **kwargs):
        captured["tester_mode_override"] = kwargs.get("tester_mode_override")
        captured["diagnostic_only"] = kwargs.get("diagnostic_only")
        (tmp_path / "diag-run").mkdir(parents=True, exist_ok=True)
        return MT5RunSpec(
            candidate_id=spec.candidate_id,
            run_id="mt5diag-test",
            install_id="mt5_practice_01",
            diagnostic_only=True,
            terminal_path=str(tmp_path / "terminal64.exe"),
            portable_mode=True,
            tester_mode=str(kwargs.get("tester_mode_override")),
            tick_mode=str(kwargs.get("tester_mode_override")),
            spread_behavior="configured_by_strategy_tester",
            allow_live_trading=False,
            shutdown_terminal=True,
            config_path=tmp_path / "diagnostic_tester.ini",
            report_path=tmp_path / "diagnostic_report.htm",
            compile_target_path=tmp_path / "CandidateEA.mq5",
            compile_request_path=tmp_path / "compile_request.json",
            launch_request_path=tmp_path / "diagnostic_launch_request.json",
            run_dir=tmp_path / "diag-run",
        )

    monkeypatch.setattr(mt5_service, "_parity_run_spec_from_packet", _fake_parity_run_spec_from_packet)
    monkeypatch.setattr(mt5_service, "_stage_diagnostic_tick_windows", lambda *args, **kwargs: 0)
    monkeypatch.setattr(mt5_service, "_clear_previous_parity_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        mt5_service,
        "_launch_mt5_tester",
        lambda *args, **kwargs: MT5RunResult(
            candidate_id=spec.candidate_id,
            run_id="mt5diag-test",
            launch_status="completed",
            terminal_path=str(tmp_path / "terminal64.exe"),
            launch_status_path=tmp_path / "launch_status.json",
        ),
    )
    monkeypatch.setattr(
        mt5_service,
        "validate_mt5_practice",
        lambda *args, **kwargs: MT5ValidationReport(
            candidate_id=spec.candidate_id,
            run_id="mt5diag-test",
            validation_status="failed",
            failure_classification="execution_cost_failure",
            parity_rate=0.81,
            audit_rows=12,
            report_path=tmp_path / "validation_report.json",
            diagnostics_report_path=tmp_path / "parity_diagnostics.json",
            matched_trade_diagnostics_path=tmp_path / "matched_trade_diagnostics.csv",
        ),
    )

    class _Snapshot:
        environment_id = "env-test"
        report_path = tmp_path / "environment_snapshot.json"

    monkeypatch.setattr(mt5_service, "build_environment_snapshot", lambda *args, **kwargs: _Snapshot())

    def _capture_trial_entry(*args, **kwargs):
        captured["trial_stage"] = kwargs.get("stage")
        captured["failure_code"] = kwargs.get("failure_code")

    failure_calls: list[dict[str, object]] = []

    monkeypatch.setattr(mt5_service, "append_trial_entry", _capture_trial_entry)
    monkeypatch.setattr(mt5_service, "append_failure_record", lambda *args, **kwargs: failure_calls.append(kwargs))

    report = mt5_service.run_mt5_parity_diagnostic(spec.candidate_id, settings)

    assert captured["tester_mode_override"] == "Every tick based on real ticks"
    assert captured["diagnostic_only"] is True
    assert captured["trial_stage"] == "mt5_parity_diagnostic"
    assert captured["failure_code"] is None
    assert report.diagnostic_only is True
    assert report.lineage_root_candidate_id == spec.candidate_id
    assert report.parity_class == "tick_required"
    assert report.tester_mode == "Every tick based on real ticks"
    assert report.certification_status == "untrusted"
    assert report.tick_provenance == "real_ticks"
    assert report.baseline_reproduction_passed is False
    assert report.certification_report_path is not None
    assert report.certification_report_path.exists()
    assert report.report_path.name == "mt5_parity_diagnostic_report.json"
    assert failure_calls == []


def test_parity_class_from_report_requires_deployment_grade_certification(settings):
    report = MT5ParityReport(
        candidate_id="AF-CAND-GOV-PARITY-CERT",
        run_id="mt5run-cert",
        tester_mode="1 minute OHLC",
        validation_status="passed",
        parity_rate=0.98,
        audit_rows=18,
        certification_status="research_only",
        report_path=Path("mt5_parity_report.json"),
    )

    assert _parity_class_from_report(report, settings) is None
    certified = report.model_copy(update={"certification_status": "deployment_grade"})
    assert _parity_class_from_report(certified, settings) == "m1_official"


def test_run_mt5_parity_blocks_lineage_class_switch_after_first_official_evidence(settings):
    root_candidate = _candidate("AF-CAND-GOV-PARITY-ROOT", "Governance Parity Root Candidate")
    child_candidate = _candidate("AF-CAND-GOV-PARITY-CHILD", "Governance Parity Child Candidate")
    root_spec = StrategySpec.model_validate(
        compile_strategy_spec_tool(
            payload=root_candidate.model_dump(mode="json"),
            settings=settings,
            config={},
            read_policy=ReadPolicy(project_root=settings.project_root),
        )
    )
    child_spec = StrategySpec.model_validate(
        compile_strategy_spec_tool(
            payload=child_candidate.model_dump(mode="json"),
            settings=settings,
            config={},
            read_policy=ReadPolicy(project_root=settings.project_root),
        )
    )
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="lane-parity-lineage-switch",
            family=root_spec.family,
            hypothesis_class=root_spec.entry_style,
            seed_candidate_id=root_spec.candidate_id,
            parity_class="tick_required",
            queue_kind="promotion",
        )
    ]
    append_trial_entry(
        settings,
        candidate_id=child_spec.candidate_id,
        family=child_spec.family,
        stage="mutate_one_candidate",
        parent_candidate_ids=[root_spec.candidate_id],
    )
    existing_run_dir = settings.paths().mt5_runs_dir / root_spec.candidate_id / "mt5run-existing"
    existing_run_dir.mkdir(parents=True, exist_ok=True)
    existing_report = MT5ParityReport(
        candidate_id=root_spec.candidate_id,
        run_id="mt5run-existing",
        tester_mode="1 minute OHLC",
        packet_reused=True,
        validation_status="failed",
        failure_classification="execution_cost_failure",
        parity_rate=0.81,
        audit_rows=25,
        certification_status="deployment_grade",
        baseline_reproduction_passed=True,
        report_path=existing_run_dir / "mt5_parity_report.json",
    )
    write_json(existing_report.report_path, existing_report.model_dump(mode="json"))
    for stage in ("mt5_packet", "mt5_parity_run", "mt5_validation"):
        record_approval(
            ApprovalRecord(
                candidate_id=child_spec.candidate_id,
                stage=stage,
                decision="approve",
                approver="pytest",
                rationale="Approved for lineage parity policy enforcement testing.",
            ),
            settings,
        )

    with pytest.raises(mt5_service.ParityPolicyError, match="parity_policy_switch_blocked"):
        mt5_service.run_mt5_parity(child_spec.candidate_id, settings)


def test_run_mt5_incident_replay_writes_research_only_certification(settings, tmp_path, monkeypatch):
    candidate = _candidate("AF-CAND-GOV-INCIDENT-REPLAY", "Governance Incident Replay Candidate")
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)
    packet_dir = tmp_path / "packet"
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_run_spec_path = tmp_path / "packet_run_spec.json"
    packet_run_spec = MT5RunSpec(
        candidate_id=spec.candidate_id,
        run_id="mt5run-packet",
        install_id="mt5_practice_01",
        terminal_path=str(tmp_path / "terminal64.exe"),
        portable_mode=True,
        tester_mode="1 minute OHLC",
        tick_mode="1 minute OHLC",
        spread_behavior="configured_by_strategy_tester",
        allow_live_trading=False,
        shutdown_terminal=True,
        config_path=tmp_path / "packet_tester.ini",
        report_path=tmp_path / "packet_report.htm",
        compile_target_path=tmp_path / "CandidateEA.mq5",
        compile_request_path=tmp_path / "compile_request.json",
        launch_request_path=tmp_path / "packet_launch_request.json",
        run_dir=tmp_path,
    )
    packet_run_spec_path.write_text(packet_run_spec.model_dump_json(indent=2), encoding="utf-8")
    packet = MT5Packet(
        candidate_id=spec.candidate_id,
        packet_dir=packet_dir,
        logic_manifest_path=packet_dir / "logic_manifest.json",
        expected_signal_path=packet_dir / "expected_signals.csv",
        notes_path=packet_dir / "notes.md",
        ea_source_path=packet_dir / "CandidateEA.mq5",
        run_spec_path=packet_run_spec_path,
        tester_config_path=tmp_path / "tester_config.ini",
        compile_request_path=tmp_path / "compile_request.json",
        launch_request_path=tmp_path / "launch_request.json",
        logic_manifest_hash="logic-hash",
    )
    tester_report_path = tmp_path / "incident_report.htm"
    tester_report_path.write_text("<td>Total Trades:</td><td><b>8</b></td>", encoding="utf-8")

    monkeypatch.setattr(mt5_service, "require_stage_approval", lambda *args, **kwargs: None)
    monkeypatch.setattr(mt5_service, "load_mt5_packet", lambda *args, **kwargs: packet)
    monkeypatch.setattr(mt5_service, "_is_packet_stale", lambda *args, **kwargs: False)
    monkeypatch.setattr(mt5_service, "_load_spec", lambda *args, **kwargs: spec)
    monkeypatch.setattr(mt5_service, "_clear_previous_parity_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(mt5_service, "_latest_incident_baseline_harness_passed", lambda *args, **kwargs: True)

    def _fake_manual_run_spec_from_packet(*args, **kwargs):
        run_dir = tmp_path / "incident-run"
        run_dir.mkdir(parents=True, exist_ok=True)
        return MT5RunSpec(
            candidate_id=spec.candidate_id,
            run_id="mt5incident-test",
            install_id="mt5_practice_01",
            diagnostic_only=True,
            terminal_path=str(tmp_path / "terminal64.exe"),
            portable_mode=True,
            tester_mode="Every tick based on real ticks",
            tick_mode="Every tick based on real ticks",
            spread_behavior="configured_by_strategy_tester",
            allow_live_trading=False,
            shutdown_terminal=True,
            config_path=run_dir / "tester_config.ini",
            report_path=run_dir / "tester_report.htm",
            compile_target_path=run_dir / "CandidateEA.mq5",
            compile_request_path=run_dir / "compile_request.json",
            launch_request_path=run_dir / "launch_request.json",
            run_dir=run_dir,
            tester_inputs_profile_path=run_dir / "MQL5" / "Profiles" / "Tester" / "AF-CAND-GOV-INCIDENT-REPLAY.set",
        )

    monkeypatch.setattr(mt5_service, "_manual_run_spec_from_packet", _fake_manual_run_spec_from_packet)
    monkeypatch.setattr(
        mt5_service,
        "_launch_mt5_tester",
        lambda *args, **kwargs: MT5RunResult(
            candidate_id=spec.candidate_id,
            run_id="mt5incident-test",
            launch_status="completed",
            terminal_path=str(tmp_path / "terminal64.exe"),
            tester_report_path=tester_report_path,
            launch_status_path=tmp_path / "launch_status.json",
        ),
    )

    report = mt5_service.run_mt5_incident_replay(
        spec.candidate_id,
        settings,
        window_start="2026-03-24T09:00:00Z",
        window_end="2026-03-24T11:00:00Z",
        incident_id="incident-test-certification",
    )

    assert report.harness_status == "replay_ready"
    assert report.certification_status == "research_only"
    assert report.tick_provenance == "real_ticks"
    assert report.baseline_reproduction_passed is True
    assert report.certification_report_path is not None
    assert report.certification_report_path.exists()


def test_write_diagnostic_tick_analysis_flags_subminute_stop_before_timeout(tmp_path):
    diagnostics_report_path = tmp_path / "parity_diagnostics.json"
    diagnostics_report_path.write_text(json.dumps({"top_breaches": []}, indent=2), encoding="utf-8")
    diagnostic_windows_path = tmp_path / "diagnostic_tick_windows.csv"
    diagnostic_windows_path.write_text(
        "\n".join(
            [
                "window_id,start_broker,end_broker,side,expected_exit_reason,actual_exit_reason,expected_exit_utc,actual_exit_utc,likely_cause,expected_stop_loss_price,actual_stop_loss_price,expected_take_profit_price,actual_take_profit_price",
                "breach-01,2026.03.24 10:08:00,2026.03.24 10:10:00,short,timeout,stop_loss,2026-03-24T10:10:00Z,2026-03-24T10:09:00Z,timeout_rule_mismatch,1.1010,1.1010,1.0990,1.0990",
            ]
        ),
        encoding="utf-8",
    )
    diagnostic_ticks_csv_path = tmp_path / "diagnostic_ticks.csv"
    diagnostic_ticks_csv_path.write_text(
        "\n".join(
            [
                "window_id,timestamp_utc,bid,ask,last,volume,flags,expected_exit_utc,actual_exit_utc,likely_cause",
                "breach-01,2026.03.24 10:08:30Z,1.1008,1.1009,1.1009,0,0,2026-03-24T10:10:00Z,2026-03-24T10:09:00Z,timeout_rule_mismatch",
                "breach-01,2026.03.24 10:08:45Z,1.1009,1.1011,1.1010,0,0,2026-03-24T10:10:00Z,2026-03-24T10:09:00Z,timeout_rule_mismatch",
            ]
        ),
        encoding="utf-8",
    )

    analysis_path = mt5_service._write_diagnostic_tick_analysis(
        candidate_id="AF-CAND-GOV-TICK-ANALYSIS",
        run_id="mt5diag-analysis",
        diagnostics_report_path=diagnostics_report_path,
        diagnostic_windows_path=diagnostic_windows_path,
        diagnostic_ticks_csv_path=diagnostic_ticks_csv_path,
        destination_dir=tmp_path,
    )

    assert analysis_path is not None and analysis_path.exists()
    payload = read_json(analysis_path)
    assert len(payload["window_analyses"]) == 1
    analysis = payload["window_analyses"][0]
    assert analysis["actual_stop_hit_utc"] == "2026-03-24T10:08:45Z"
    assert analysis["supports_actual_exit_reason"] is True
    assert analysis["supports_expected_exit_reason"] is False


def test_prepare_runtime_and_stage_existing_build(settings, tmp_path):
    install_root = tmp_path / "OANDA MetaTrader 5 Terminal"
    data_root = tmp_path / "TerminalData"
    for binary_name in ("terminal64.exe", "MetaEditor64.exe", "metatester64.exe"):
        (install_root / binary_name).parent.mkdir(parents=True, exist_ok=True)
        (install_root / binary_name).write_text(binary_name, encoding="utf-8")
    (install_root / "Tester").mkdir(parents=True, exist_ok=True)
    (install_root / "Tester" / "dummy.txt").write_text("tester", encoding="utf-8")
    (data_root / "config").mkdir(parents=True, exist_ok=True)
    (data_root / "config" / "common.ini").write_text("[Common]\nLogin=5087443\n", encoding="utf-8")
    (data_root / "MQL5" / "Files").mkdir(parents=True, exist_ok=True)
    (data_root / "MQL5" / "Files" / "mt5_event_calendar.csv").write_text("ts,event\n", encoding="utf-8")

    runtime_terminal, runtime_data, runtime_metaeditor = _prepare_automated_terminal_runtime(
        settings,
        terminal_path=install_root / "terminal64.exe",
        terminal_data_path=data_root,
    )

    assert runtime_terminal is not None and runtime_terminal.exists()
    assert runtime_data is not None and runtime_data.exists()
    assert runtime_metaeditor is not None and runtime_metaeditor.exists()
    assert (runtime_data / "Config" / "common.ini").exists()
    assert (runtime_data / "Tester" / "dummy.txt").exists()
    assert (runtime_data / "MQL5" / "Files" / "mt5_event_calendar.csv").exists()

    source_path = tmp_path / "CandidateEA.mq5"
    ex5_path = tmp_path / "CandidateEA.ex5"
    source_path.write_text("// source", encoding="utf-8")
    ex5_path.write_text("binary", encoding="utf-8")

    staged_source_path, staged_ex5_path = _stage_existing_build_for_launch(
        source_path=source_path,
        compiled_ex5_path=ex5_path,
        compile_target_relative_path=Path(settings.mt5_env.compile_target_relative_path),
        terminal_data_path=runtime_data,
    )

    assert staged_source_path.exists()
    assert staged_ex5_path is not None and staged_ex5_path.exists()


def test_clear_tester_cache_removes_stale_profiles_and_discovers_runtime_report(settings, tmp_path):
    terminal_root = tmp_path / "mt5-runtime"
    profiles_dir = terminal_root / "MQL5" / "Profiles" / "Tester"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (terminal_root / "Tester" / "cache").mkdir(parents=True, exist_ok=True)
    (terminal_root / "Tester" / "cache" / "stale.cache").write_text("stale", encoding="utf-8")
    (profiles_dir / "AF-CAND-TEST.set").write_text("stale", encoding="utf-8")
    (profiles_dir / "ReportTester-stale.html").write_text("stale", encoding="utf-8")
    (profiles_dir / "ReportTester-stale.xlsx").write_text("stale", encoding="utf-8")
    (terminal_root / "AF-CAND-TEST-run-report.htm").write_text("stale", encoding="utf-8")
    (terminal_root / "AF-CAND-TEST-run-report.xlsx").write_text("stale", encoding="utf-8")

    _clear_tester_cache(terminal_root)

    assert not (terminal_root / "Tester" / "cache" / "stale.cache").exists()
    assert not (profiles_dir / "AF-CAND-TEST.set").exists()
    assert not (profiles_dir / "ReportTester-stale.html").exists()
    assert not (profiles_dir / "ReportTester-stale.xlsx").exists()
    assert not (terminal_root / "AF-CAND-TEST-run-report.htm").exists()
    assert not (terminal_root / "AF-CAND-TEST-run-report.xlsx").exists()

    candidate = _candidate("AF-CAND-GOV-REPORT", "Governance Report Candidate")
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)

    run_spec = MT5RunSpec(
        candidate_id=spec.candidate_id,
        run_id="mt5run-report",
        install_id="mt5_practice_01",
        terminal_path=str(terminal_root / "terminal64.exe"),
        portable_mode=True,
        tester_mode=settings.mt5_env.tester_mode,
        tick_mode=settings.mt5_env.tester_mode,
        spread_behavior="configured_by_strategy_tester",
        allow_live_trading=False,
        shutdown_terminal=True,
        config_path=tmp_path / "tester.ini",
        report_path=tmp_path / "tester_report.htm",
        compile_target_path=tmp_path / "CandidateEA.mq5",
        compile_request_path=tmp_path / "compile_request.json",
        launch_request_path=tmp_path / "launch_request.json",
        run_dir=tmp_path,
    )
    runtime_report = terminal_root / "AF-CAND-GOV-REPORT-mt5run-report-report.htm"
    runtime_report.write_text("<html>report</html>", encoding="utf-8")

    discovered = _discover_tester_report(run_spec, settings)

    assert discovered == runtime_report


def test_discover_tester_report_falls_back_to_reporttester_xlsx(settings, tmp_path):
    terminal_root = tmp_path / "mt5-runtime"
    profiles_dir = terminal_root / "MQL5" / "Profiles" / "Tester"
    profiles_dir.mkdir(parents=True, exist_ok=True)

    run_spec = MT5RunSpec(
        candidate_id="AF-CAND-GOV-REPORT-XLSX",
        run_id="mt5run-report-xlsx",
        install_id="mt5_practice_01",
        terminal_path=str(terminal_root / "terminal64.exe"),
        portable_mode=True,
        tester_mode=settings.mt5_env.tester_mode,
        tick_mode=settings.mt5_env.tester_mode,
        spread_behavior="configured_by_strategy_tester",
        allow_live_trading=False,
        shutdown_terminal=True,
        config_path=tmp_path / "tester.ini",
        report_path=tmp_path / "tester_report.htm",
        compile_target_path=tmp_path / "CandidateEA.mq5",
        compile_request_path=tmp_path / "compile_request.json",
        launch_request_path=tmp_path / "launch_request.json",
        run_dir=tmp_path,
    )
    fallback_report = profiles_dir / "ReportTester-5087443.xlsx"
    fallback_report.write_text("xlsx-report", encoding="utf-8")

    discovered = _discover_tester_report(run_spec, settings)

    assert discovered == fallback_report


def test_archive_tester_report_bundle_copies_companion_pngs(tmp_path):
    source_dir = tmp_path / "runtime"
    source_dir.mkdir(parents=True, exist_ok=True)
    report_path = source_dir / "AF-CAND-0263-report.htm"
    report_path.write_text("<html><img src='AF-CAND-0263-report.png'></html>", encoding="utf-8")
    (source_dir / "AF-CAND-0263-report.png").write_text("png", encoding="utf-8")
    (source_dir / "AF-CAND-0263-report-hst.png").write_text("hst", encoding="utf-8")

    destination_dir = tmp_path / "archived"
    archived_path = _archive_tester_report_bundle(report_path, destination_dir)

    assert archived_path == destination_dir / report_path.name
    assert archived_path.exists()
    assert (destination_dir / "AF-CAND-0263-report.png").exists()
    assert (destination_dir / "AF-CAND-0263-report-hst.png").exists()


def test_clear_tester_cache_ignores_locked_profile_images(tmp_path, monkeypatch):
    terminal_root = tmp_path / "mt5-runtime"
    profiles_dir = terminal_root / "MQL5" / "Profiles" / "Tester"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (terminal_root / "Tester" / "cache").mkdir(parents=True, exist_ok=True)
    locked_image = profiles_dir / "ReportTester10-locked.png"
    stale_report = profiles_dir / "ReportTester-stale.html"
    locked_image.write_text("locked", encoding="utf-8")
    stale_report.write_text("stale", encoding="utf-8")

    original_unlink = Path.unlink

    def fake_unlink(path: Path, *args, **kwargs):
        if path == locked_image:
            raise PermissionError("locked")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fake_unlink)

    _clear_tester_cache(terminal_root)

    assert locked_image.exists()
    assert not stale_report.exists()


def test_run_mt5_manual_test_reuses_packet_and_archives_outputs(settings, tmp_path, monkeypatch):
    candidate_id = "AF-CAND-GOV-MANUAL"
    spec = StrategySpec.model_validate(
        compile_strategy_spec_tool(
            payload=_candidate(candidate_id, "Governance Manual MT5 Candidate").model_dump(mode="json"),
            settings=settings,
            config={},
            read_policy=ReadPolicy(project_root=settings.project_root),
        )
    )
    packet = MT5Packet(
        candidate_id=candidate_id,
        packet_dir=tmp_path / "packet",
        logic_manifest_path=tmp_path / "packet" / "logic_manifest.json",
        expected_signal_path=tmp_path / "packet" / "expected_signals.csv",
        notes_path=tmp_path / "packet" / "notes.md",
        ea_source_path=tmp_path / "packet" / "CandidateEA.mq5",
        run_spec_path=tmp_path / "packet" / "run_spec.json",
        tester_config_path=tmp_path / "packet" / "tester_config.ini",
        compile_request_path=tmp_path / "packet" / "compile_request.json",
        launch_request_path=tmp_path / "packet" / "launch_request.json",
        compiled_ex5_path=tmp_path / "packet" / "CandidateEA.ex5",
    )
    packet.packet_dir.mkdir(parents=True, exist_ok=True)
    packet.expected_signal_path.write_text("timestamp_utc\n", encoding="utf-8")
    packet.compiled_ex5_path.write_text("binary", encoding="utf-8")

    run_spec = MT5RunSpec(
        candidate_id=candidate_id,
        run_id="mt5manual-test",
        install_id="mt5_practice_01",
        terminal_path=str(tmp_path / "terminal64.exe"),
        portable_mode=True,
        tester_mode=settings.mt5_env.tester_mode,
        tick_mode=settings.mt5_env.tester_mode,
        spread_behavior="configured_by_strategy_tester",
        allow_live_trading=False,
        shutdown_terminal=True,
        config_path=tmp_path / "manual-run" / "tester_config.ini",
        report_path=tmp_path / "manual-run" / "tester_report.htm",
        compile_target_path=tmp_path / "manual-run" / "CandidateEA.mq5",
        compile_request_path=tmp_path / "manual-run" / "compile_request.json",
        launch_request_path=tmp_path / "manual-run" / "launch_request.json",
        run_dir=tmp_path / "manual-run",
    )
    run_spec.run_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(mt5_service, "require_stage_approval", lambda *args, **kwargs: None)
    monkeypatch.setattr(mt5_service, "load_mt5_packet", lambda *args, **kwargs: packet)
    monkeypatch.setattr(mt5_service, "_is_packet_stale", lambda *args, **kwargs: False)
    monkeypatch.setattr(mt5_service, "_manual_run_spec_from_packet", lambda *args, **kwargs: run_spec)
    monkeypatch.setattr(mt5_service, "_load_spec", lambda *args, **kwargs: spec)
    monkeypatch.setattr(mt5_service, "_load_expected_signal_frame", lambda *args, **kwargs: pd.DataFrame({"timestamp_utc": []}))
    monkeypatch.setattr(mt5_service, "_clear_previous_parity_outputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        mt5_service,
        "_launch_mt5_tester",
        lambda *args, **kwargs: MT5RunResult(
            candidate_id=candidate_id,
            run_id="mt5manual-test",
            launch_status="completed",
            tester_report_path=run_spec.run_dir / "ReportTester-5087443.xlsx",
            audit_csv_path=run_spec.run_dir / "audit.csv",
            broker_history_csv_path=run_spec.run_dir / "broker_history.csv",
            diagnostic_ticks_csv_path=run_spec.run_dir / "diagnostic_ticks.csv",
            launch_status_path=run_spec.run_dir / "launch_status.json",
        ),
    )

    report = mt5_service.run_mt5_manual_test(candidate_id, settings)

    assert report.candidate_id == candidate_id
    assert report.packet_reused is True
    assert report.tester_mode == settings.mt5_env.tester_mode
    assert report.tester_report_path == run_spec.run_dir / "ReportTester-5087443.xlsx"
    assert report.report_path.exists()


def test_manual_run_strategy_spec_scales_fixed_lots_for_small_accounts(settings):
    spec = StrategySpec.model_validate(
        compile_strategy_spec_tool(
            payload=_candidate("AF-CAND-GOV-MANUAL-SCALE", "Governance Manual Scale Candidate").model_dump(mode="json"),
            settings=settings,
            config={},
            read_policy=ReadPolicy(project_root=settings.project_root),
        )
    )
    spec.account_model.initial_balance = 100000.0
    spec.account_model.max_total_exposure_lots = 5.0

    manual_spec, overrides = _manual_run_strategy_spec(
        spec,
        deposit=100.0,
        leverage=33.0,
        fixed_lots=None,
        auto_scale_lots=True,
        min_lot=0.01,
        lot_step=0.01,
    )

    assert manual_spec.account_model.initial_balance == 100.0
    assert manual_spec.account_model.leverage == 33.0
    assert manual_spec.risk_envelope.leverage == 33.0
    assert manual_spec.account_model.max_total_exposure_lots == 0.01
    assert overrides["sizing_mode"] == "scaled_from_canonical"
    assert overrides["effective_fixed_lots"] == 0.01


def test_render_candidate_ea_supports_throughput_entry_styles(settings):
    candidate_ids = [
        ("AF-CAND-0147", "volatility_expansion"),
        ("AF-CAND-0148", "trend_pullback_retest"),
        ("AF-CAND-0149", "session_extreme_reversion"),
    ]
    for candidate_id, entry_style in candidate_ids:
        spec_path = (
            Path(r".")
            / "reports"
            / candidate_id
            / "strategy_spec.json"
        )
        spec = StrategySpec.model_validate(read_json(spec_path))
        source = render_candidate_ea(spec)
        assert f'if(InpEntryStyle == "{entry_style}")' in source


@pytest.mark.parametrize(
    "entry_style",
    [
        "overlap_persistence_band",
        "session_momentum_band",
        "compression_reversion",
        "drift_reclaim",
        "balance_area_breakout",
        "volatility_retest_breakout",
        "overlap_event_retest_breakout",
        "overlap_persistence_retest",
        "high_vol_overlap_persistence_retest",
        "compression_breakout",
        "compression_retest_breakout",
        "range_reclaim",
        "trend_retest",
    ],
)
def test_render_candidate_ea_supports_market_structure_entry_styles(entry_style):
    spec = StrategySpec(
        candidate_id=f"AF-CAND-TEST-{entry_style}",
        family="market_structure_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=[8, 9, 10, 11]),
        setup_logic=SetupLogic(style=entry_style, summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=8.0, take_profit_pips=12.0),
        source_citations=["SRC-TEST"],
        entry_style=entry_style,
        holding_bars=24,
        signal_threshold=0.85,
        stop_loss_pips=8.0,
        take_profit_pips=12.0,
    )

    source = render_candidate_ea(spec)
    assert f'"{entry_style}"' in source


def test_render_candidate_ea_uses_mid_adjusted_rates_for_session_momentum_band():
    spec = StrategySpec(
        candidate_id="AF-CAND-TEST-SMB-RATES",
        family="session_momentum_band_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=[14, 15, 16]),
        setup_logic=SetupLogic(style="session_momentum_band", summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=7.0, take_profit_pips=14.5),
        source_citations=["SRC-TEST"],
        entry_style="session_momentum_band",
        holding_bars=54,
        signal_threshold=0.76,
        stop_loss_pips=7.0,
        take_profit_pips=14.5,
    )

    source = render_candidate_ea(spec)

    assert "CopyRates(_Symbol, PERIOD_M1, 0, 40, rates)" in source
    assert "closes[i] = rates[i].close + mid_offset;" in source
    assert "highs[i] = rates[i].high + mid_offset;" in source
    assert "lows[i] = rates[i].low + mid_offset;" in source
    assert "double range_high_10 = MaxValue(highs, 1, 10);" in source
    assert "double range_low_10 = MinValue(lows, 1, 10);" in source


def test_render_candidate_ea_converts_broker_time_to_utc_for_session_and_audit():
    spec = StrategySpec(
        candidate_id="AF-CAND-TEST-TZ",
        family="parity_alignment_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=[13, 14, 15, 16]),
        setup_logic=SetupLogic(style="overlap_event_retest_breakout", summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=5.0, take_profit_pips=8.0),
        source_citations=["SRC-TEST"],
        entry_style="overlap_event_retest_breakout",
        holding_bars=24,
        signal_threshold=0.9,
        stop_loss_pips=5.0,
        take_profit_pips=8.0,
    )

    source = render_candidate_ea(spec, broker_timezone="Europe/Prague")

    assert 'input string InpBrokerTimezone = "Europe/Prague";' in source
    assert "int trade_hour = HourUtc(current_bar);" in source
    assert "ConvertBrokerTimeToUtc" in source
    assert "PragueUtcOffsetSeconds" in source
    assert 'return TimeToString(ConvertBrokerTimeToUtc(value), TIME_DATE | TIME_SECONDS) + "Z";' in source


def test_render_candidate_ea_exports_broker_history():
    spec = StrategySpec(
        candidate_id="AF-CAND-TEST-HISTORY-EXPORT",
        family="parity_alignment_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=[13, 14, 15, 16]),
        setup_logic=SetupLogic(style="session_momentum_band", summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=7.0, take_profit_pips=14.5),
        source_citations=["SRC-TEST"],
        entry_style="session_momentum_band",
        holding_bars=54,
        signal_threshold=0.76,
        stop_loss_pips=7.0,
        take_profit_pips=14.5,
    )

    source = render_candidate_ea(spec, broker_history_relative_path="AgenticForex\\Audit\\broker_history.csv")

    assert 'input string InpBrokerHistoryRelativePath = "AgenticForex\\\\Audit\\\\broker_history.csv";' in source
    assert "void OnDeinit(const int reason)" in source
    assert "ExportBrokerHistory();" in source
    assert "FileOpen(InpBrokerHistoryRelativePath, FILE_WRITE | FILE_CSV | FILE_COMMON | FILE_ANSI, ',')" in source
    assert "struct ExportMinuteBar" in source
    assert "CopyTicksRange(_Symbol, ticks, COPY_TICKS_ALL" in source


def test_render_candidate_ea_prefers_tick_aggregated_broker_history():
    spec = StrategySpec(
        candidate_id="AF-CAND-TEST-TICK-HISTORY",
        family="parity_alignment_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=[13, 14, 15, 16]),
        setup_logic=SetupLogic(style="session_momentum_band", summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=7.0, take_profit_pips=14.5),
        source_citations=["SRC-TEST"],
        entry_style="session_momentum_band",
        holding_bars=54,
        signal_threshold=0.76,
        stop_loss_pips=7.0,
        take_profit_pips=14.5,
    )

    source = render_candidate_ea(spec)

    assert "BuildTickMinuteBars" in source
    assert "use_tick_bar" in source
    assert "volume = tick_bars[tick_index].tick_count;" in source
    assert "spread_pips = pip_size <= 0.0 ? 0.0 : (ask_o - bid_o) / pip_size;" in source
    assert "ExportDiagnosticTicks();" in source
    assert "CopyTicksRange(_Symbol, ticks, COPY_TICKS_ALL" in source


def test_render_candidate_ea_supports_targeted_diagnostic_tick_windows():
    spec = StrategySpec(
        candidate_id="AF-CAND-TEST-DIAGNOSTIC-TICKS",
        family="parity_alignment_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=[13, 14, 15, 16]),
        setup_logic=SetupLogic(style="session_momentum_band", summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=7.0, take_profit_pips=14.5),
        source_citations=["SRC-TEST"],
        entry_style="session_momentum_band",
        holding_bars=54,
        signal_threshold=0.76,
        stop_loss_pips=7.0,
        take_profit_pips=14.5,
    )

    source = render_candidate_ea(
        spec,
        diagnostic_windows_relative_path="AgenticForex\\Audit\\candidate_windows.csv",
        diagnostic_ticks_relative_path="AgenticForex\\Audit\\candidate_ticks.csv",
    )

    assert 'input string InpDiagnosticWindowsRelativePath = "AgenticForex\\\\Audit\\\\candidate_windows.csv";' in source
    assert 'input string InpDiagnosticTicksRelativePath = "AgenticForex\\\\Audit\\\\candidate_ticks.csv";' in source
    assert "void ExportDiagnosticTicks()" in source
    assert "ExportTicksForWindow(" in source


def test_render_candidate_ea_writes_exit_reason_and_collision_audit_fields():
    spec = StrategySpec(
        candidate_id="AF-CAND-TEST-EXIT-AUDIT",
        family="parity_alignment_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=[13, 14, 15, 16]),
        setup_logic=SetupLogic(style="session_momentum_band", summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=7.0, take_profit_pips=14.5),
        source_citations=["SRC-TEST"],
        entry_style="session_momentum_band",
        holding_bars=54,
        signal_threshold=0.76,
        stop_loss_pips=7.0,
        take_profit_pips=14.5,
    )

    source = render_candidate_ea(spec)

    assert "string MapExitReason(int deal_reason)" in source
    assert "bool ExitBarCollision(string side, double stop_price, double take_profit_price, datetime exit_time)" in source
    assert '"exit_reason",' in source
    assert '"same_bar_collision"' in source
    assert "g_timeout_exit_pending && exit_reason == \"expert\"" in source


def test_render_candidate_ea_anchors_timeout_and_audit_to_entry_bar_time():
    spec = StrategySpec(
        candidate_id="AF-CAND-TEST-ENTRY-BAR-TIME",
        family="parity_alignment_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=[13, 14, 15, 16]),
        setup_logic=SetupLogic(style="session_momentum_band", summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=7.0, take_profit_pips=14.5),
        source_citations=["SRC-TEST"],
        entry_style="session_momentum_band",
        holding_bars=54,
        signal_threshold=0.76,
        stop_loss_pips=7.0,
        take_profit_pips=14.5,
    )

    source = render_candidate_ea(spec)

    assert "datetime g_entry_bar_time = 0;" in source
    assert "datetime g_pending_entry_bar_time = 0;" in source
    assert "g_pending_entry_bar_time = current_bar;" in source
    assert "g_entry_bar_time = current_bar;" in source
    assert "g_entry_bar_time = g_pending_entry_bar_time > 0 ? g_pending_entry_bar_time : NormalizeBarOpen(g_entry_time);" in source
    assert "datetime anchor_bar = g_entry_bar_time > 0 ? g_entry_bar_time : NormalizeBarOpen(g_entry_time);" in source
    assert "WriteAuditRow(\n      g_entry_bar_time," in source
    assert "datetime NormalizeBarOpen(datetime value)" in source


def test_render_candidate_ea_shadow_mode_guards_trade_execution():
    spec = StrategySpec(
        candidate_id="AF-CAND-TEST-SHADOW",
        family="shadow_test_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=[8, 9, 10]),
        setup_logic=SetupLogic(style="volatility_breakout", summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=7.0, take_profit_pips=24.0),
        source_citations=["SRC-TEST"],
        entry_style="volatility_breakout",
        holding_bars=150,
        signal_threshold=2.5,
        stop_loss_pips=7.0,
        take_profit_pips=24.0,
    )

    source = render_candidate_ea(spec, shadow_mode_only=True)

    assert "input bool InpShadowModeOnly = true;" in source
    assert "if(InpShadowModeOnly)" in source
    # Signal generation and trace still active in shadow mode
    assert "int signal = GenerateSignal();" in source
    assert "WriteSignalTraceRow(current_bar, signal, spread_pips);" in source
    # trade.Buy and trade.Sell are in else branch, still present but guarded
    assert "trade.Buy(" in source
    assert "trade.Sell(" in source


def test_render_candidate_ea_shadow_mode_defaults_to_false():
    spec = StrategySpec(
        candidate_id="AF-CAND-TEST-SHADOW-OFF",
        family="shadow_test_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=[8, 9, 10]),
        setup_logic=SetupLogic(style="volatility_breakout", summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=7.0, take_profit_pips=24.0),
        source_citations=["SRC-TEST"],
        entry_style="volatility_breakout",
        holding_bars=150,
        signal_threshold=2.5,
        stop_loss_pips=7.0,
        take_profit_pips=24.0,
    )

    source = render_candidate_ea(spec)

    assert "input bool InpShadowModeOnly = false;" in source


def test_validate_mt5_practice_prefers_exported_broker_history(settings, tmp_path, monkeypatch):
    settings.validation.parity_min_closed_trades = 1
    candidate = _candidate("AF-CAND-GOV-BROKER-PARITY", "Governance Broker History Candidate")
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)
    report_dir = settings.paths().reports_dir / spec.candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "strategy_spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")

    record_approval(
        ApprovalRecord(
            candidate_id=spec.candidate_id,
            stage="mt5_validation",
            decision="approve",
            approver="pytest",
            rationale="Validation approved for broker history parity testing.",
        ),
        settings,
    )

    packet_dir = settings.paths().approvals_dir / "mt5_packets" / spec.candidate_id
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_expected = pd.DataFrame.from_records(
        [
            {
                "timestamp_utc": "2024-01-01T00:00:00Z",
                "exit_timestamp_utc": "2024-01-01T00:10:00Z",
                "side": "long",
                "entry_price": 1.1000,
                "exit_price": 1.1005,
                "pnl_pips": 5.0,
                "candidate_id": spec.candidate_id,
            }
        ]
    )
    packet_expected.to_csv(packet_dir / "expected_signals.csv", index=False)

    broker_history_csv = tmp_path / "broker_history.csv"
    broker_history_csv.write_text("timestamp_utc\n2024-01-01T00:00:00Z\n", encoding="utf-8")
    broker_expected = pd.DataFrame.from_records(
        [
            {
                "timestamp_utc": "2024-01-01T00:01:00Z",
                "exit_timestamp_utc": "2024-01-01T00:06:00Z",
                "side": "short",
                "entry_price": 1.2000,
                "exit_price": 1.1990,
                "pnl_pips": 10.0,
                "candidate_id": spec.candidate_id,
            }
        ]
    )
    monkeypatch.setattr(
        mt5_service,
        "_broker_history_expected_signal_frame",
        lambda *args, **kwargs: broker_expected,
    )

    audit_csv = tmp_path / "mt5_audit.csv"
    broker_expected.to_csv(audit_csv, index=False)

    validation = validate_mt5_practice(
        spec.candidate_id,
        settings,
        audit_csv,
        broker_history_csv=broker_history_csv,
        run_id="mt5run-broker-history",
        report_dir=tmp_path,
    )

    assert validation.validation_status == "passed"
    assert validation.expected_signal_source == "broker_history_executable_baseline"
    assert validation.expected_trade_count == 1
    assert validation.matched_trade_count == 1
    assert validation.broker_history_csv_path == broker_history_csv
    assert validation.diagnostics_report_path is not None and validation.diagnostics_report_path.exists()
    assert validation.matched_trade_diagnostics_path is not None and validation.matched_trade_diagnostics_path.exists()

    diagnostics = read_json(validation.diagnostics_report_path)
    assert diagnostics["primary_failure_mode"] == "within_tolerance"
    assert diagnostics["matched_trade_count"] == 1
    assert diagnostics["expected_signal_source"] == "broker_history_executable_baseline"


def test_validate_mt5_practice_prefers_signal_trace_for_broker_history_entries(settings, tmp_path, monkeypatch):
    settings.validation.parity_min_closed_trades = 1
    candidate = _candidate("AF-CAND-GOV-SIGNAL-TRACE-BASELINE", "Governance Signal Trace Baseline Candidate")
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)
    report_dir = settings.paths().reports_dir / spec.candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "strategy_spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")

    record_approval(
        ApprovalRecord(
            candidate_id=spec.candidate_id,
            stage="mt5_validation",
            decision="approve",
            approver="pytest",
            rationale="Validation approved for signal trace baseline testing.",
        ),
        settings,
    )

    packet_dir = settings.paths().approvals_dir / "mt5_packets" / spec.candidate_id
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_expected = pd.DataFrame.from_records(
        [
            {
                "timestamp_utc": "2024-01-01T00:00:00Z",
                "exit_timestamp_utc": "2024-01-01T00:02:00Z",
                "side": "long",
                "entry_price": 1.1000,
                "exit_price": 1.1003,
                "pnl_pips": 3.0,
                "candidate_id": spec.candidate_id,
            }
        ]
    )
    packet_expected.to_csv(packet_dir / "expected_signals.csv", index=False)

    broker_history_csv = tmp_path / "broker_history.csv"
    pd.DataFrame.from_records(
        [
            {"timestamp_utc": "2024-01-01T00:00:00Z", "bid_o": 1.1000, "bid_h": 1.1001, "bid_l": 1.0999, "bid_c": 1.1000, "ask_o": 1.1002, "ask_h": 1.1003, "ask_l": 1.1001, "ask_c": 1.1002, "spread_pips": 2.0, "volume": 10},
        ]
    ).to_csv(broker_history_csv, index=False)

    signal_trace_csv = tmp_path / "signal_trace.csv"
    pd.DataFrame.from_records(
        [
            {"timestamp_utc": "2024-01-01T00:01:00Z", "candidate_id": spec.candidate_id, "run_id": "mt5run-test", "signal": 1, "spread_pips": 0.2, "bars_processed": 100}
        ]
    ).to_csv(signal_trace_csv, index=False)

    monkeypatch.setattr(
        mt5_service,
        "_signal_trace_expected_signal_frame",
        lambda **kwargs: pd.DataFrame.from_records(
            [
                {
                    "timestamp_utc": "2024-01-01T00:01:00Z",
                    "exit_timestamp_utc": "2024-01-01T00:02:00Z",
                    "side": "long",
                    "entry_price": 1.1003,
                    "exit_price": 1.1003,
                    "pnl_pips": 0.0,
                    "candidate_id": spec.candidate_id,
                    "exit_reason": "timeout",
                    "stop_loss_price": 1.0993,
                    "take_profit_price": 1.1005,
                    "same_bar_collision": False,
                    "collision_resolution": "",
                }
            ]
        ),
    )

    audit_csv = tmp_path / "mt5_audit.csv"
    pd.DataFrame.from_records(
        [
            {
                "timestamp_utc": "2024-01-01T00:01:00Z",
                "exit_timestamp_utc": "2024-01-01T00:02:00Z",
                "side": "long",
                "entry_price": 1.1003,
                "exit_price": 1.1003,
                "pnl_pips": 0.0,
                "candidate_id": spec.candidate_id,
                "exit_reason": "timeout",
            }
        ]
    ).to_csv(audit_csv, index=False)

    validation = validate_mt5_practice(
        spec.candidate_id,
        settings,
        audit_csv,
        broker_history_csv=broker_history_csv,
        signal_trace_csv=signal_trace_csv,
        run_id="mt5run-signal-trace",
        report_dir=tmp_path,
    )

    assert validation.expected_signal_source == "broker_history_signal_trace_baseline"
    assert validation.expected_trade_count == 1


def test_validate_mt5_practice_flags_exit_semantics_mismatches(settings, tmp_path, monkeypatch):
    settings.validation.parity_min_closed_trades = 1
    candidate = _candidate("AF-CAND-GOV-EXIT-SEMANTICS", "Governance Exit Semantics Candidate")
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)
    report_dir = settings.paths().reports_dir / spec.candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "strategy_spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")

    record_approval(
        ApprovalRecord(
            candidate_id=spec.candidate_id,
            stage="mt5_validation",
            decision="approve",
            approver="pytest",
            rationale="Validation approved for exit semantics parity testing.",
        ),
        settings,
    )

    packet_dir = settings.paths().approvals_dir / "mt5_packets" / spec.candidate_id
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_expected = pd.DataFrame.from_records(
        [
            {
                "timestamp_utc": "2024-01-01T00:00:00Z",
                "exit_timestamp_utc": "2024-01-01T00:10:00Z",
                "side": "long",
                "entry_price": 1.1000,
                "exit_price": 1.1005,
                "pnl_pips": 5.0,
                "candidate_id": spec.candidate_id,
                "exit_reason": "timeout",
                "same_bar_collision": False,
            }
        ]
    )
    packet_expected.to_csv(packet_dir / "expected_signals.csv", index=False)

    audit_csv = tmp_path / "mt5_audit.csv"
    packet_expected.assign(exit_reason="take_profit", same_bar_collision=True).to_csv(audit_csv, index=False)

    mismatch_match = {
        "expected_index": 0,
        "actual_index": 0,
        "side": "long",
        "expected_timestamp_utc": "2024-01-01T00:00:00Z",
        "actual_timestamp_utc": "2024-01-01T00:00:00Z",
        "expected_exit_timestamp_utc": "2024-01-01T00:10:00Z",
        "actual_exit_timestamp_utc": "2024-01-01T00:10:00Z",
        "expected_entry_price": 1.1000,
        "actual_entry_price": 1.1000,
        "expected_exit_price": 1.1005,
        "actual_exit_price": 1.1005,
        "expected_pnl_pips": 5.0,
        "actual_pnl_pips": 5.0,
        "expected_exit_reason": "timeout",
        "actual_exit_reason": "take_profit",
        "exit_reason_match": False,
        "expected_stop_loss_price": 1.0990,
        "actual_stop_loss_price": 1.0990,
        "expected_take_profit_price": 1.1012,
        "actual_take_profit_price": 1.1012,
        "expected_same_bar_collision": False,
        "actual_same_bar_collision": True,
        "same_bar_collision_match": False,
        "expected_collision_resolution": "",
        "entry_price_delta_pips": 0.0,
        "exit_price_delta_pips": 0.0,
        "fill_delta_pips": 0.0,
        "close_timing_delta_seconds": 0.0,
    }
    monkeypatch.setattr(mt5_service, "_match_expected_to_actual", lambda *args, **kwargs: [mismatch_match])

    validation = validate_mt5_practice(
        spec.candidate_id,
        settings,
        audit_csv,
        run_id="mt5run-exit-semantics",
        report_dir=tmp_path,
    )

    assert validation.validation_status == "failed"
    assert validation.failure_classification == "execution_cost_failure"
    diagnostics = read_json(validation.diagnostics_report_path)
    assert diagnostics["breach_counts"]["exit_reason_mismatch"] == 1
    assert diagnostics["breach_counts"]["same_bar_collision_mismatch"] == 1
    assert diagnostics["primary_failure_mode"] == "timeout_rule_mismatch"


def test_resolve_executable_exit_prioritizes_timeout_at_expiry_bar_open():
    spec = StrategySpec(
        candidate_id="AF-CAND-TEST-TIMEOUT-PRIORITY",
        family="parity_alignment_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=[13, 14, 15, 16]),
        setup_logic=SetupLogic(style="session_momentum_band", summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=5.0, take_profit_pips=10.0),
        source_citations=["SRC-TEST"],
        entry_style="session_momentum_band",
        holding_bars=2,
        signal_threshold=0.76,
        stop_loss_pips=5.0,
        take_profit_pips=10.0,
    )
    features = pd.DataFrame.from_records(
        [
            {
                "bid_o": 1.1000,
                "bid_h": 1.1004,
                "bid_l": 1.0998,
                "bid_c": 1.1001,
                "ask_o": 1.1002,
                "ask_h": 1.1006,
                "ask_l": 1.1000,
                "ask_c": 1.1003,
            },
            {
                "bid_o": 1.1001,
                "bid_h": 1.1008,
                "bid_l": 1.0999,
                "bid_c": 1.1002,
                "ask_o": 1.1003,
                "ask_h": 1.1010,
                "ask_l": 1.1001,
                "ask_c": 1.1004,
            },
            {
                "bid_o": 1.1005,
                "bid_h": 1.1014,
                "bid_l": 1.1004,
                "bid_c": 1.1011,
                "ask_o": 1.1007,
                "ask_h": 1.1016,
                "ask_l": 1.1006,
                "ask_c": 1.1013,
            },
        ]
    )

    exit_result = mt5_service._resolve_executable_exit(
        features=features,
        entry_index=0,
        signal=1,
        entry_price=1.1002,
        spec=spec,
        pip_scale=10000.0,
    )

    assert exit_result is not None
    assert exit_result["exit_index"] == 2
    assert exit_result["exit_reason"] == "timeout"
    assert exit_result["exit_price"] == pytest.approx(1.1005)


def test_resolve_executable_exit_does_not_promote_one_point_near_miss_to_stop_loss():
    spec = StrategySpec(
        candidate_id="AF-CAND-TEST-EXACT-BOUNDARY",
        family="parity_alignment_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=[13, 14, 15, 16]),
        setup_logic=SetupLogic(style="session_momentum_band", summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=7.0, take_profit_pips=24.0),
        source_citations=["SRC-TEST"],
        entry_style="session_momentum_band",
        holding_bars=2,
        signal_threshold=0.76,
        stop_loss_pips=7.0,
        take_profit_pips=24.0,
    )
    features = pd.DataFrame.from_records(
        [
            {
                "bid_o": 1.17355,
                "bid_h": 1.17363,
                "bid_l": 1.17352,
                "bid_c": 1.17354,
                "ask_o": 1.17355,
                "ask_h": 1.17363,
                "ask_l": 1.17352,
                "ask_c": 1.17354,
            },
            {
                "bid_o": 1.17292,
                "bid_h": 1.17292,
                "bid_l": 1.17287,
                "bid_c": 1.17287,
                "ask_o": 1.17294,
                "ask_h": 1.17294,
                "ask_l": 1.17289,
                "ask_c": 1.17289,
            },
            {
                "bid_o": 1.17505,
                "bid_h": 1.17510,
                "bid_l": 1.17500,
                "bid_c": 1.17505,
                "ask_o": 1.17507,
                "ask_h": 1.17512,
                "ask_l": 1.17502,
                "ask_c": 1.17507,
            },
        ]
    )

    exit_result = mt5_service._resolve_executable_exit(
        features=features,
        entry_index=0,
        signal=1,
        entry_price=1.17356,
        spec=spec,
        pip_scale=10000.0,
    )

    assert exit_result is not None
    assert exit_result["exit_reason"] == "timeout"
    assert exit_result["exit_price"] == pytest.approx(1.17505)


def test_validate_mt5_practice_suppresses_boundary_ambiguous_exit_semantics(settings, tmp_path, monkeypatch):
    settings.validation.parity_min_closed_trades = 1
    candidate = _candidate("AF-CAND-GOV-BOUNDARY-AMBIG", "Governance Boundary Ambiguity Candidate")
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)
    report_dir = settings.paths().reports_dir / spec.candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "strategy_spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")

    record_approval(
        ApprovalRecord(
            candidate_id=spec.candidate_id,
            stage="mt5_validation",
            decision="approve",
            approver="pytest",
            rationale="Validation approved for boundary ambiguity parity testing.",
        ),
        settings,
    )

    packet_dir = settings.paths().approvals_dir / "mt5_packets" / spec.candidate_id
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_expected = pd.DataFrame.from_records(
        [
            {
                "timestamp_utc": "2024-01-01T00:00:00Z",
                "exit_timestamp_utc": "2024-01-01T00:10:00Z",
                "side": "long",
                "entry_price": 1.1000,
                "exit_price": 1.1005,
                "pnl_pips": 5.0,
                "candidate_id": spec.candidate_id,
                "exit_reason": "take_profit",
                "same_bar_collision": False,
            }
        ]
    )
    packet_expected.to_csv(packet_dir / "expected_signals.csv", index=False)

    audit_csv = tmp_path / "mt5_audit.csv"
    packet_expected.assign(exit_reason="stop_loss").to_csv(audit_csv, index=False)

    ambiguous_match = {
        "expected_index": 0,
        "actual_index": 0,
        "side": "long",
        "expected_timestamp_utc": "2024-01-01T00:00:00Z",
        "actual_timestamp_utc": "2024-01-01T00:00:00Z",
        "expected_exit_timestamp_utc": "2024-01-01T00:10:00Z",
        "actual_exit_timestamp_utc": "2024-01-01T00:09:40Z",
        "expected_entry_price": 1.1000,
        "actual_entry_price": 1.1000,
        "expected_exit_price": 1.1005,
        "actual_exit_price": 1.0993,
        "expected_pnl_pips": 5.0,
        "actual_pnl_pips": -7.0,
        "expected_exit_reason": "take_profit",
        "actual_exit_reason": "stop_loss",
        "exit_reason_match": False,
        "expected_stop_loss_price": 1.0993,
        "actual_stop_loss_price": 1.0993,
        "expected_take_profit_price": 1.1005,
        "actual_take_profit_price": 1.1005,
        "expected_same_bar_collision": False,
        "actual_same_bar_collision": False,
        "same_bar_collision_match": True,
        "expected_collision_resolution": "",
        "comparison_basis": "actual_fill_adjusted_executable",
        "boundary_ambiguous_close_timing": False,
        "boundary_ambiguous_exit_semantics": True,
        "entry_price_delta_pips": 0.0,
        "exit_price_delta_pips": 12.0,
        "fill_delta_pips": 12.0,
        "close_timing_delta_seconds": 20.0,
    }
    monkeypatch.setattr(mt5_service, "_match_expected_to_actual", lambda *args, **kwargs: [ambiguous_match])

    validation = validate_mt5_practice(
        spec.candidate_id,
        settings,
        audit_csv,
        run_id="mt5run-boundary-ambiguous",
        report_dir=tmp_path,
    )

    assert validation.validation_status == "passed"
    diagnostics = read_json(validation.diagnostics_report_path)
    assert diagnostics["breach_counts"]["exit_reason_mismatch"] == 0
    assert diagnostics["breach_counts"]["exit_price"] == 0


@pytest.mark.parametrize(
    ("entry_style", "signal_threshold", "allowed_hours", "row"),
    [
        (
            "volatility_expansion",
            1.05,
            [8, 9, 10],
            {
                "hour": 8,
                "spread_pips": 0.8,
                "volatility_20": 0.00008,
                "zscore_10": 1.1,
                "momentum_12": 1.2,
                "ret_5": 0.00009,
                "ret_1": 0.00003,
                "mid_c": 1.1010,
                "rolling_mean_10": 1.1000,
                "range_position_10": 0.82,
                "range_width_10_pips": 6.0,
            },
        ),
        (
            "trend_pullback_retest",
            0.88,
            [12, 13, 14],
            {
                "hour": 13,
                "spread_pips": 0.8,
                "volatility_20": 0.00007,
                "zscore_10": 0.2,
                "momentum_12": 0.6,
                "ret_5": 0.00008,
                "ret_1": 0.00004,
                "mid_c": 1.1012,
                "rolling_mean_10": 1.1005,
                "range_position_10": 0.68,
                "range_width_10_pips": 7.0,
            },
        ),
        (
            "session_extreme_reversion",
            0.72,
            [13, 14, 15],
            {
                "hour": 14,
                "spread_pips": 0.9,
                "volatility_20": 0.00009,
                "zscore_10": -0.9,
                "momentum_12": 0.25,
                "ret_5": -0.00007,
                "ret_1": 0.00004,
                "mid_c": 1.0992,
                "rolling_mean_10": 1.1000,
                "range_position_10": 0.25,
                "range_width_10_pips": 8.0,
            },
        ),
        (
            "compression_reversion",
            0.85,
            [9, 10, 11, 12],
            {
                "hour": 10,
                "spread_pips": 0.8,
                "volatility_20": 0.00006,
                "zscore_10": -0.96,
                "momentum_12": 0.35,
                "ret_5": -0.00003,
                "ret_1": 0.00003,
                "mid_c": 1.0995,
                "rolling_mean_10": 1.1001,
                "range_position_10": 0.28,
                "range_width_10_pips": 6.5,
            },
        ),
        (
            "drift_reclaim",
            0.9,
            [13, 14, 15, 16],
            {
                "hour": 14,
                "spread_pips": 0.9,
                "volatility_20": 0.00008,
                "zscore_10": -1.0,
                "momentum_12": 0.4,
                "ret_5": -0.00008,
                "ret_1": 0.00004,
                "mid_c": 1.0997,
                "rolling_mean_10": 1.1002,
                "range_position_10": 0.44,
                "range_width_10_pips": 8.4,
            },
        ),
        (
            "balance_area_breakout",
            0.78,
            [7, 8, 9, 10],
            {
                "hour": 8,
                "spread_pips": 0.7,
                "volatility_20": 0.00007,
                "zscore_10": 0.7,
                "momentum_12": 0.85,
                "ret_5": 0.00007,
                "ret_1": 0.00003,
                "mid_c": 1.1009,
                "rolling_mean_10": 1.1001,
                "range_position_10": 0.76,
                "range_width_10_pips": 7.2,
            },
        ),
        (
            "compression_breakout",
            1.0,
            [8, 9, 10, 11],
            {
                "hour": 9,
                "spread_pips": 0.7,
                "volatility_20": 0.00005,
                "zscore_10": 0.72,
                "momentum_12": 1.12,
                "ret_5": 0.00004,
                "ret_1": 0.00003,
                "mid_c": 1.1007,
                "rolling_mean_10": 1.1000,
                "range_position_10": 0.78,
                "range_width_10_pips": 6.8,
            },
        ),
        (
            "volatility_retest_breakout",
            0.90,
            [12, 13, 14, 15],
            {
                "hour": 13,
                "spread_pips": 0.8,
                "volatility_20": 0.00007,
                "zscore_10": 0.22,
                "momentum_12": 0.72,
                "ret_5": 0.00010,
                "ret_1": 0.00003,
                "mid_c": 1.1010,
                "rolling_mean_10": 1.1002,
                "range_position_10": 0.67,
                "range_width_10_pips": 7.0,
            },
        ),
        (
            "overlap_event_retest_breakout",
            0.90,
            [13, 14, 15, 16],
            {
                "hour": 14,
                "spread_pips": 0.7,
                "volatility_20": 0.00008,
                "zscore_10": 0.24,
                "momentum_12": 0.78,
                "ret_5": 0.00011,
                "ret_1": 0.00004,
                "mid_c": 1.1014,
                "rolling_mean_10": 1.1005,
                "range_position_10": 0.70,
                "range_width_10_pips": 7.2,
            },
        ),
        (
            "overlap_persistence_retest",
            0.90,
            [13, 14, 15, 16],
            {
                "hour": 14,
                "spread_pips": 0.7,
                "volatility_20": 0.00008,
                "zscore_10": 0.24,
                "momentum_12": 0.78,
                "ret_5": 0.00011,
                "ret_1": 0.00004,
                "mid_c": 1.1014,
                "rolling_mean_10": 1.1005,
                "range_position_10": 0.70,
                "range_width_10_pips": 7.2,
            },
        ),
        (
            "high_vol_overlap_persistence_retest",
            0.90,
            [13, 14, 15, 16],
            {
                "hour": 14,
                "spread_pips": 0.7,
                "volatility_20": 0.00013,
                "zscore_10": 0.24,
                "momentum_12": 0.78,
                "ret_5": 0.00011,
                "ret_1": 0.00004,
                "mid_c": 1.1014,
                "rolling_mean_10": 1.1005,
                "range_position_10": 0.70,
                "range_width_10_pips": 7.2,
            },
        ),
        (
            "overlap_persistence_band",
            0.86,
            [13, 14, 15, 16],
            {
                "hour": 14,
                "spread_pips": 0.7,
                "volatility_20": 0.00009,
                "zscore_10": 0.28,
                "momentum_12": 0.82,
                "ret_5": 0.00011,
                "ret_1": 0.00004,
                "mid_c": 1.1014,
                "rolling_mean_10": 1.1006,
                "range_position_10": 0.68,
                "range_width_10_pips": 7.2,
            },
        ),
        (
            "session_momentum_band",
            0.88,
            [12, 13, 14, 15, 16],
            {
                "hour": 14,
                "spread_pips": 0.7,
                "volatility_20": 0.00008,
                "zscore_10": 0.42,
                "momentum_12": 0.96,
                "ret_5": 0.00010,
                "ret_1": 0.00003,
                "mid_c": 1.1017,
                "rolling_mean_10": 1.1009,
                "range_position_10": 0.72,
                "range_width_10_pips": 7.4,
            },
        ),
        (
            "compression_retest_breakout",
            0.86,
            [8, 9, 10, 11, 12],
            {
                "hour": 9,
                "spread_pips": 0.7,
                "volatility_20": 0.00006,
                "zscore_10": 0.18,
                "momentum_12": 0.72,
                "ret_5": 0.00009,
                "ret_1": 0.00003,
                "mid_c": 1.1008,
                "rolling_mean_10": 1.1001,
                "range_position_10": 0.62,
                "range_width_10_pips": 6.4,
            },
        ),
        (
            "range_reclaim",
            0.9,
            [7, 8, 9, 10],
            {
                "hour": 8,
                "spread_pips": 0.7,
                "volatility_20": 0.00006,
                "zscore_10": -1.15,
                "momentum_12": 1.0,
                "ret_5": -0.00004,
                "ret_1": 0.00003,
                "mid_c": 1.0996,
                "rolling_mean_10": 1.1002,
                "range_position_10": 0.26,
                "range_width_10_pips": 7.4,
            },
        ),
        (
            "trend_retest",
            0.95,
            [12, 13, 14, 15],
            {
                "hour": 13,
                "spread_pips": 0.8,
                "volatility_20": 0.00007,
                "zscore_10": 0.16,
                "momentum_12": 1.05,
                "ret_5": 0.00014,
                "ret_1": 0.00002,
                "mid_c": 1.1011,
                "rolling_mean_10": 1.1005,
                "range_position_10": 0.66,
                "range_width_10_pips": 7.1,
            },
        ),
    ],
)
def test_backtesting_engine_supports_throughput_entry_styles(entry_style, signal_threshold, allowed_hours, row):
    spec = StrategySpec(
        candidate_id=f"AF-CAND-TEST-{entry_style}",
        family="throughput_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=allowed_hours),
        setup_logic=SetupLogic(style=entry_style, summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=8.0, take_profit_pips=12.0),
        source_citations=["SRC-TEST"],
        entry_style=entry_style,
        holding_bars=24,
        signal_threshold=signal_threshold,
        stop_loss_pips=8.0,
        take_profit_pips=12.0,
    )

    assert _generate_signal(pd.Series(row), spec) != 0


def test_executable_exit_rounds_fx_prices_before_bar_hit_comparison():
    spec = StrategySpec(
        candidate_id="AF-CAND-TEST-PARITY-ROUNDING",
        family="overlap_resolution_bridge_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=[13, 14, 15, 16, 17]),
        setup_logic=SetupLogic(style="overlap_persistence_retest", summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=12.0, take_profit_pips=22.0),
        source_citations=["SRC-TEST"],
        entry_style="overlap_persistence_retest",
        holding_bars=3,
        signal_threshold=0.84,
        stop_loss_pips=12.0,
        take_profit_pips=22.0,
    )
    features = pd.DataFrame(
        [
            {
                "timestamp_utc": "2025-12-05T16:09:00Z",
                "bid_o": 1.16470,
                "bid_h": 1.16483,
                "bid_l": 1.16452,
                "bid_c": 1.16481,
                "ask_o": 1.16470,
                "ask_h": 1.16483,
                "ask_l": 1.16452,
                "ask_c": 1.16481,
            },
            {
                "timestamp_utc": "2025-12-05T16:10:00Z",
                "bid_o": 1.16482,
                "bid_h": 1.16505,
                "bid_l": 1.16480,
                "bid_c": 1.16491,
                "ask_o": 1.16482,
                "ask_h": 1.16505,
                "ask_l": 1.16480,
                "ask_c": 1.16491,
            },
            {
                "timestamp_utc": "2025-12-05T16:37:00Z",
                "bid_o": 1.16578,
                "bid_h": 1.16590,
                "bid_l": 1.16570,
                "bid_c": 1.16571,
                "ask_o": 1.16578,
                "ask_h": 1.16590,
                "ask_l": 1.16570,
                "ask_c": 1.16571,
            },
            {
                "timestamp_utc": "2025-12-05T16:38:00Z",
                "bid_o": 1.16571,
                "bid_h": 1.16585,
                "bid_l": 1.16567,
                "bid_c": 1.16585,
                "ask_o": 1.16571,
                "ask_h": 1.16585,
                "ask_l": 1.16567,
                "ask_c": 1.16585,
            },
        ]
    )

    exit_result = _resolve_executable_exit(features, 0, -1, 1.16470, spec, 10000.0)

    assert exit_result is not None
    assert exit_result["exit_reason"] == "stop_loss"
    assert exit_result["exit_price"] == pytest.approx(1.1659)


def test_executable_exit_treats_one_point_boundary_near_miss_as_timeout_for_fx_stop():
    spec = StrategySpec(
        candidate_id="AF-CAND-TEST-PARITY-BOUNDARY",
        family="overlap_resolution_bridge_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=[13, 14, 15, 16, 17]),
        setup_logic=SetupLogic(style="overlap_persistence_retest", summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=12.0, take_profit_pips=22.0),
        source_citations=["SRC-TEST"],
        entry_style="overlap_persistence_retest",
        holding_bars=3,
        signal_threshold=0.84,
        stop_loss_pips=12.0,
        take_profit_pips=22.0,
    )
    features = pd.DataFrame(
        [
            {
                "timestamp_utc": "2025-10-08T17:03:00Z",
                "bid_o": 1.16053,
                "bid_h": 1.16053,
                "bid_l": 1.16042,
                "bid_c": 1.16048,
                "ask_o": 1.16053,
                "ask_h": 1.16053,
                "ask_l": 1.16042,
                "ask_c": 1.16048,
            },
            {
                "timestamp_utc": "2025-10-08T19:16:00Z",
                "bid_o": 1.16016,
                "bid_h": 1.16172,
                "bid_l": 1.16015,
                "bid_c": 1.16110,
                "ask_o": 1.16016,
                "ask_h": 1.16172,
                "ask_l": 1.16015,
                "ask_c": 1.16110,
            },
            {
                "timestamp_utc": "2025-10-08T19:17:00Z",
                "bid_o": 1.16108,
                "bid_h": 1.16129,
                "bid_l": 1.16089,
                "bid_c": 1.16112,
                "ask_o": 1.16108,
                "ask_h": 1.16129,
                "ask_l": 1.16089,
                "ask_c": 1.16112,
            },
            {
                "timestamp_utc": "2025-10-08T19:18:00Z",
                "bid_o": 1.16111,
                "bid_h": 1.16121,
                "bid_l": 1.16079,
                "bid_c": 1.16088,
                "ask_o": 1.16111,
                "ask_h": 1.16121,
                "ask_l": 1.16079,
                "ask_c": 1.16088,
            },
        ]
    )

    exit_result = _resolve_executable_exit(features, 0, -1, 1.16053, spec, 10000.0)

    assert exit_result is not None
    assert exit_result["exit_reason"] == "timeout"
    assert exit_result["exit_price"] == pytest.approx(1.16111)
    assert exit_result["exit_index"] == 3


def test_executable_exit_prefers_exact_hit_timing_over_earlier_one_point_boundary_hit():
    spec = StrategySpec(
        candidate_id="AF-CAND-TEST-PARITY-EXACT-FIRST",
        family="overlap_resolution_bridge_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=[13, 14, 15, 16, 17]),
        setup_logic=SetupLogic(style="overlap_persistence_retest", summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=12.0, take_profit_pips=22.0),
        source_citations=["SRC-TEST"],
        entry_style="overlap_persistence_retest",
        holding_bars=4,
        signal_threshold=0.84,
        stop_loss_pips=12.0,
        take_profit_pips=22.0,
    )
    features = pd.DataFrame(
        [
            {
                "timestamp_utc": "2025-12-05T16:09:00Z",
                "bid_o": 1.16470,
                "bid_h": 1.16483,
                "bid_l": 1.16452,
                "bid_c": 1.16481,
                "ask_o": 1.16470,
                "ask_h": 1.16483,
                "ask_l": 1.16452,
                "ask_c": 1.16481,
            },
            {
                "timestamp_utc": "2025-12-05T16:35:00Z",
                "bid_o": 1.16578,
                "bid_h": 1.16588,
                "bid_l": 1.16574,
                "bid_c": 1.16575,
                "ask_o": 1.16579,
                "ask_h": 1.16589,
                "ask_l": 1.16575,
                "ask_c": 1.16576,
            },
            {
                "timestamp_utc": "2025-12-05T16:36:00Z",
                "bid_o": 1.16576,
                "bid_h": 1.16586,
                "bid_l": 1.16566,
                "bid_c": 1.16567,
                "ask_o": 1.16576,
                "ask_h": 1.16586,
                "ask_l": 1.16566,
                "ask_c": 1.16567,
            },
            {
                "timestamp_utc": "2025-12-05T16:37:00Z",
                "bid_o": 1.16578,
                "bid_h": 1.16590,
                "bid_l": 1.16570,
                "bid_c": 1.16571,
                "ask_o": 1.16578,
                "ask_h": 1.16590,
                "ask_l": 1.16570,
                "ask_c": 1.16571,
            },
            {
                "timestamp_utc": "2025-12-05T16:38:00Z",
                "bid_o": 1.16571,
                "bid_h": 1.16585,
                "bid_l": 1.16567,
                "bid_c": 1.16585,
                "ask_o": 1.16571,
                "ask_h": 1.16585,
                "ask_l": 1.16567,
                "ask_c": 1.16585,
            },
        ]
    )

    exit_result = _resolve_executable_exit(features, 0, -1, 1.16470, spec, 10000.0)

    assert exit_result is not None
    assert exit_result["exit_reason"] == "stop_loss"
    assert exit_result["exit_price"] == pytest.approx(1.1659)
    assert exit_result["exit_index"] == 3


def test_executable_exit_keeps_timeout_when_no_exact_boundary_touch_occurs():
    spec = StrategySpec(
        candidate_id="AF-CAND-TEST-PARITY-EXACT-FALLBACK",
        family="overlap_resolution_bridge_research",
        session_policy=SessionPolicy(name="test", allowed_sessions=["intraday_active_windows"], allowed_hours_utc=[13, 14, 15, 16, 17]),
        setup_logic=SetupLogic(style="overlap_persistence_retest", summary="test"),
        risk_policy=RiskPolicy(stop_loss_pips=12.0, take_profit_pips=22.0),
        source_citations=["SRC-TEST"],
        entry_style="overlap_persistence_retest",
        holding_bars=3,
        signal_threshold=0.84,
        stop_loss_pips=12.0,
        take_profit_pips=22.0,
    )
    features = pd.DataFrame(
        [
            {
                "timestamp_utc": "2025-12-05T16:09:00Z",
                "bid_o": 1.16470,
                "bid_h": 1.16483,
                "bid_l": 1.16452,
                "bid_c": 1.16481,
                "ask_o": 1.16470,
                "ask_h": 1.16483,
                "ask_l": 1.16452,
                "ask_c": 1.16481,
            },
            {
                "timestamp_utc": "2025-12-05T16:35:00Z",
                "bid_o": 1.16578,
                "bid_h": 1.16588,
                "bid_l": 1.16574,
                "bid_c": 1.16575,
                "ask_o": 1.16579,
                "ask_h": 1.16589,
                "ask_l": 1.16575,
                "ask_c": 1.16576,
            },
            {
                "timestamp_utc": "2025-12-05T16:36:00Z",
                "bid_o": 1.16576,
                "bid_h": 1.16586,
                "bid_l": 1.16566,
                "bid_c": 1.16567,
                "ask_o": 1.16576,
                "ask_h": 1.16586,
                "ask_l": 1.16566,
                "ask_c": 1.16567,
            },
            {
                "timestamp_utc": "2025-12-05T16:38:00Z",
                "bid_o": 1.16571,
                "bid_h": 1.16585,
                "bid_l": 1.16567,
                "bid_c": 1.16585,
                "ask_o": 1.16571,
                "ask_h": 1.16585,
                "ask_l": 1.16567,
                "ask_c": 1.16585,
            },
        ]
    )

    exit_result = _resolve_executable_exit(features, 0, -1, 1.16470, spec, 10000.0)

    assert exit_result is not None
    assert exit_result["exit_reason"] == "timeout"
    assert exit_result["exit_price"] == pytest.approx(1.16571)
    assert exit_result["exit_index"] == 3


def _candidate(candidate_id: str, title: str) -> CandidateDraft:
    return CandidateDraft(
        candidate_id=candidate_id,
        family="scalping",
        title=title,
        thesis="Governed deterministic Europe-session breakout scalp.",
        source_citations=["SRC-001", "SRC-002"],
        strategy_hypothesis="Deterministic breakout rules can be governed by provenance, trial-ledger, and MT5 contract controls.",
        market_context=MarketContextSummary(
            session_focus="europe_open_breakout",
            volatility_preference="moderate_to_high",
            directional_bias="both",
            execution_notes=["Governance-focused candidate."],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Europe-session breakout setup for governance-layer testing.",
        entry_summary="Enter on deterministic breakout confirmation when momentum, return alignment, and price location confirm.",
        exit_summary="Exit via fixed stop, target, or timeout.",
        risk_summary="One open position with explicit spread and session controls.",
        notes=["Governance test candidate."],
        quality_flags=["governed"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="session_breakout",
        holding_bars=45,
        signal_threshold=1.2,
        stop_loss_pips=5.0,
        take_profit_pips=8.0,
    )
