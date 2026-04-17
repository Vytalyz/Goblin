from __future__ import annotations

import pandas as pd
import pytest

from agentic_forex.approval.models import ApprovalRecord
from agentic_forex.approval.service import publish_candidate, record_approval
from agentic_forex.backtesting.engine import _passes_common_filters, run_backtest, run_stress_test
from agentic_forex.features.service import build_features
from agentic_forex.llm import MockLLMClient
from agentic_forex.labels.service import build_labels
from agentic_forex.market_data.ingest import ingest_oanda_json
from agentic_forex.ml.train import train_models
from agentic_forex.mt5.service import generate_mt5_packet, validate_mt5_practice
from agentic_forex.nodes import build_tool_registry
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.policy.calendar import ingest_economic_calendar
from agentic_forex.runtime import ReadPolicy, WorkflowEngine
from agentic_forex.workflows import WorkflowRepository
from agentic_forex.workflows.contracts import CandidateDraft, MarketContextSummary, ReviewPacket, StrategySpec

from conftest import create_economic_calendar_csv, create_oanda_candles_json


def test_build_labels_uses_path_aware_exit_geometry(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=120)
    ingest_oanda_json(oanda_json, settings)
    parquet_path = settings.paths().normalized_research_dir / "eur_usd_m1.parquet"
    frame = pd.read_parquet(parquet_path)

    labeled = build_labels(
        build_features(frame),
        holding_bars=12,
        stop_loss_pips=4.0,
        take_profit_pips=6.0,
    )

    assert {"long_exit_reason", "short_exit_reason", "long_outcome_pips", "short_outcome_pips"}.issubset(labeled.columns)
    assert labeled["label_up"].dropna().isin([0, 1]).all()
    assert labeled["label_down"].dropna().isin([0, 1]).all()
    assert set(labeled["long_exit_reason"].dropna().unique()).issubset({"take_profit", "stop_loss", "time_exit"})


def test_build_features_emits_regime_quality_columns(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=120)
    ingest_oanda_json(oanda_json, settings)
    parquet_path = settings.paths().normalized_research_dir / "eur_usd_m1.parquet"
    frame = pd.read_parquet(parquet_path)

    featured = build_features(frame)

    assert {
        "volatility_5",
        "volatility_ratio_5_to_20",
        "intrabar_range_pips",
        "spread_to_range_10",
        "spread_shock_20",
        "range_efficiency_10",
    }.issubset(featured.columns)
    assert featured["volatility_ratio_5_to_20"].dropna().ge(0.0).all()
    assert featured["spread_shock_20"].dropna().ge(0.0).all()
    assert featured["range_efficiency_10"].dropna().between(0.0, 2.0).all()


def test_common_filters_support_daytype_quality_columns(settings):
    candidate = CandidateDraft(
        candidate_id="AF-CAND-DAYTYPE-FILTER",
        family="asia_europe_transition_daytype_reclaim_research",
        title="Day-Type Filter Candidate",
        thesis="Synthetic day-type filter validation candidate.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Transition-day quality filters should block noisy bridge states before reclaim logic is evaluated.",
        market_context=MarketContextSummary(
            session_focus="asia_europe_transition_daytype_reclaim",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Synthetic day-type filter case."],
            allowed_hours_utc=[6, 7, 8],
        ),
        setup_summary="Synthetic setup.",
        entry_summary="Synthetic entry.",
        exit_summary="Synthetic exit.",
        risk_summary="Synthetic risk.",
        custom_filters=[
            {"name": "max_spread_pips", "rule": "2.0"},
            {"name": "max_spread_shock_20", "rule": "1.10"},
            {"name": "min_volatility_20", "rule": "0.00005"},
            {"name": "min_volatility_ratio_5_to_20", "rule": "1.00"},
            {"name": "min_range_efficiency_10", "rule": "0.40"},
        ],
        open_anchor_hour_utc=6,
        entry_style="drift_reclaim",
        holding_bars=16,
        signal_threshold=0.88,
        stop_loss_pips=5.0,
        take_profit_pips=7.0,
    )
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)

    base_row = {
        "spread_pips": 1.2,
        "spread_shock_20": 1.05,
        "spread_to_range_10": 0.2,
        "volatility_20": 0.00020,
        "volatility_5": 0.00024,
        "volatility_ratio_5_to_20": 1.20,
        "intrabar_range_pips": 1.4,
        "range_width_10_pips": 5.5,
        "range_efficiency_10": 0.46,
        "zscore_10": 0.05,
        "momentum_12": 0.10,
        "hour": 7,
    }

    valid_row = pd.Series(base_row)
    spread_shock_fail_row = pd.Series({**base_row, "spread_shock_20": 1.22})
    efficiency_fail_row = pd.Series({**base_row, "range_efficiency_10": 0.31})

    assert _passes_common_filters(valid_row, spec) is True
    assert _passes_common_filters(spread_shock_fail_row, spec) is False
    assert _passes_common_filters(efficiency_fail_row, spec) is False


def test_phase_bucket_filter_blocks_early_follow_through_and_keeps_late_decay(settings):
    candidate = CandidateDraft(
        candidate_id="AF-CAND-PHASE-FILTER",
        family="asia_europe_transition_reclaim_research",
        title="Phase Filter Candidate",
        thesis="Synthetic phase-filter validation candidate.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Later handoff reclaim states should be distinguishable from earlier follow-through states.",
        market_context=MarketContextSummary(
            session_focus="asia_europe_transition_reclaim",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Synthetic phase filter case."],
            allowed_hours_utc=[7, 8],
        ),
        setup_summary="Synthetic setup.",
        entry_summary="Synthetic entry.",
        exit_summary="Synthetic exit.",
        risk_summary="Synthetic risk.",
        custom_filters=[
            {"name": "max_spread_pips", "rule": "2.0"},
            {"name": "min_volatility_20", "rule": "0.00005"},
            {"name": "min_volatility_ratio_5_to_20", "rule": "0.90"},
            {"name": "required_volatility_bucket", "rule": "high"},
            {"name": "required_phase_bucket", "rule": "late_morning_decay"},
        ],
        open_anchor_hour_utc=6,
        entry_style="drift_reclaim",
        holding_bars=12,
        signal_threshold=0.9,
        stop_loss_pips=5.0,
        take_profit_pips=7.0,
    )
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload).model_copy(update={"open_anchor_hour_utc": 6})

    base_row = {
        "spread_pips": 1.0,
        "spread_to_range_10": 0.2,
        "volatility_20": 0.00020,
        "volatility_5": 0.00024,
        "volatility_ratio_5_to_20": 1.20,
        "intrabar_range_pips": 1.4,
        "range_width_10_pips": 5.5,
        "zscore_10": 0.05,
        "momentum_12": 0.10,
    }

    early_follow_through_row = pd.Series({**base_row, "hour": 7})
    late_decay_row = pd.Series({**base_row, "hour": 8})

    assert _passes_common_filters(early_follow_through_row, spec) is False
    assert _passes_common_filters(late_decay_row, spec) is True


def test_validation_publish_and_mt5_flow(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_result = ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    candidate = CandidateDraft(
        candidate_id="AF-CAND-0101",
        family="scalping",
        title="Europe Session Breakout Prototype",
        thesis="Trade Europe-session EUR/USD directional expansion with deterministic breakout rules.",
        source_citations=["SRC-001", "SRC-002"],
        strategy_hypothesis="Europe-session breakout structure plus explicit execution filters can support deterministic scalping entries.",
        market_context=MarketContextSummary(
            session_focus="europe_open_breakout",
            volatility_preference="moderate_to_high",
            directional_bias="both",
            execution_notes=["Canonical research source is OANDA.", "Constrain execution to Europe-session hours."],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Monitor Europe-session directional expansion when momentum and price location align.",
        entry_summary="Enter on deterministic breakout confirmation when 12-bar momentum and 5-bar return align with price above or below the short-term mean.",
        exit_summary="Exit via fixed stop, target, or 45-bar timeout.",
        risk_summary="One open position with fixed stop, target, spread cap, and volatility floor only.",
        notes=["Synthetic candidate for integration testing."],
        quality_flags=["quant_reviewed", "risk_reviewed", "execution_reviewed"],
        contradiction_summary=["Breakout and fade sources disagree on optimal timing."],
        critic_notes=["ExecutionRealist: keep MT5 parity separate from research data."],
        entry_style="session_breakout",
        holding_bars=45,
        signal_threshold=1.2,
        stop_loss_pips=5.0,
        take_profit_pips=8.0,
    )
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)

    backtest = run_backtest(spec, settings)
    stress = run_stress_test(spec, settings)
    model_report = train_models(spec, settings)

    assert ingest_result.source == "oanda"
    assert ingest_result.namespace == "research"
    assert backtest.trade_count > 0
    assert backtest.split_breakdown["out_of_sample"]["trade_count"] >= 0
    assert "session_bucket" in backtest.regime_breakdown
    assert stress.report_path.exists()
    assert len(stress.scenarios) == 3
    assert any(scenario.fill_delay_ms > 0 for scenario in stress.scenarios)
    assert model_report.exists()

    review_engine = WorkflowEngine(
        settings=settings,
        llm_client=MockLLMClient(),
        tool_registry=build_tool_registry(),
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    review_workflow = WorkflowRepository(settings.paths()).load(settings.workflows.review_workflow_id)
    review_trace = review_engine.run(review_workflow, spec.model_dump(mode="json"))
    review_packet = ReviewPacket.model_validate(review_trace.output_payload)

    assert review_packet.candidate_id == spec.candidate_id
    assert review_packet.approval_recommendation in {"approve_for_publish", "needs_human_review"}
    assert review_packet.ftmo_fit["ruleset_id"] == settings.policy.ftmo_ruleset_id
    assert "fit_score_0_100" in review_packet.ftmo_fit
    assert not any("CSCV/PBO is not yet integrated" in weakness for weakness in review_packet.weaknesses)
    assert (settings.paths().reports_dir / spec.candidate_id / "review_packet.json").exists()

    with pytest.raises(PermissionError):
        publish_candidate(spec.candidate_id, settings)

    record_approval(
        ApprovalRecord(
            candidate_id=spec.candidate_id,
            stage="human_review",
            decision="approve",
            approver="pytest",
            rationale="Research snapshot approved for integration testing.",
        ),
        settings,
    )

    manifest = publish_candidate(spec.candidate_id, settings)
    assert manifest.manifest_path.exists()
    assert "review_packet.json" in manifest.artifacts
    assert manifest.publication_type == "research_archive"
    assert manifest.deployment_ready is False

    with pytest.raises(PermissionError):
        generate_mt5_packet(spec.candidate_id, settings)

    record_approval(
        ApprovalRecord(
            candidate_id=spec.candidate_id,
            stage="mt5_packet",
            decision="approve",
            approver="pytest",
            rationale="Packet generation approved for testing.",
        ),
        settings,
    )
    record_approval(
        ApprovalRecord(
            candidate_id=spec.candidate_id,
            stage="mt5_validation",
            decision="approve",
            approver="pytest",
            rationale="Practice validation approved for testing.",
        ),
        settings,
    )

    packet = generate_mt5_packet(spec.candidate_id, settings)
    assert packet.logic_manifest_path.exists()
    assert packet.expected_signal_path.exists()

    audit_csv = tmp_path / "mt5_audit.csv"
    pd.read_csv(packet.expected_signal_path).to_csv(audit_csv, index=False)
    validation = validate_mt5_practice(spec.candidate_id, settings, audit_csv)
    assert validation.validation_status == "passed"
    assert validation.parity_rate == 1.0


def test_validate_mt5_practice_insufficient_evidence(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    candidate = CandidateDraft(
        candidate_id="AF-CAND-0102",
        family="scalping",
        title="Insufficient Evidence Candidate",
        thesis="Synthetic MT5 validation edge case.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Synthetic controller validation candidate.",
        market_context=MarketContextSummary(
            session_focus="europe_open_breakout",
            volatility_preference="moderate_to_high",
            directional_bias="both",
            execution_notes=["Synthetic validation case."],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Synthetic setup.",
        entry_summary="Synthetic entry.",
        exit_summary="Synthetic exit.",
        risk_summary="Synthetic risk.",
        entry_style="session_breakout",
        holding_bars=45,
        signal_threshold=1.2,
        stop_loss_pips=5.0,
        take_profit_pips=8.0,
    )
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
            rationale="Packet generation approved for insufficient evidence test.",
        ),
        settings,
    )
    record_approval(
        ApprovalRecord(
            candidate_id=spec.candidate_id,
            stage="mt5_validation",
            decision="approve",
            approver="pytest",
            rationale="Validation approved for insufficient evidence test.",
        ),
        settings,
    )

    packet = generate_mt5_packet(spec.candidate_id, settings)
    audit_csv = tmp_path / "mt5_insufficient.csv"
    audit_frame = pd.read_csv(packet.expected_signal_path).head(5)
    audit_frame.to_csv(audit_csv, index=False)
    validation = validate_mt5_practice(spec.candidate_id, settings, audit_csv)

    assert validation.validation_status == "insufficient_evidence"
    assert validation.failure_classification is None


def test_validate_mt5_practice_classifies_execution_cost_failure(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    candidate = CandidateDraft(
        candidate_id="AF-CAND-0103",
        family="scalping",
        title="Execution Cost Failure Candidate",
        thesis="Synthetic MT5 validation tolerance case.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Synthetic controller validation candidate.",
        market_context=MarketContextSummary(
            session_focus="europe_open_breakout",
            volatility_preference="moderate_to_high",
            directional_bias="both",
            execution_notes=["Synthetic validation case."],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Synthetic setup.",
        entry_summary="Synthetic entry.",
        exit_summary="Synthetic exit.",
        risk_summary="Synthetic risk.",
        entry_style="session_breakout",
        holding_bars=45,
        signal_threshold=1.2,
        stop_loss_pips=5.0,
        take_profit_pips=8.0,
    )
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
            rationale="Packet generation approved for execution cost failure test.",
        ),
        settings,
    )
    record_approval(
        ApprovalRecord(
            candidate_id=spec.candidate_id,
            stage="mt5_validation",
            decision="approve",
            approver="pytest",
            rationale="Validation approved for execution cost failure test.",
        ),
        settings,
    )

    packet = generate_mt5_packet(spec.candidate_id, settings)
    audit_csv = tmp_path / "mt5_exec_cost_failure.csv"
    audit_frame = pd.read_csv(packet.expected_signal_path)
    audit_frame["entry_price"] = audit_frame["entry_price"] + 0.00008
    audit_frame["exit_price"] = audit_frame["exit_price"] + 0.00008
    audit_frame["pnl_pips"] = audit_frame["pnl_pips"] - 1.0
    audit_frame.to_csv(audit_csv, index=False)
    validation = validate_mt5_practice(spec.candidate_id, settings, audit_csv)

    assert validation.validation_status == "failed"
    assert validation.failure_classification == "execution_cost_failure"
