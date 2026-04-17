from __future__ import annotations

import pandas as pd

from agentic_forex.backtesting.engine import run_backtest
from agentic_forex.config.models import ProgramLanePolicy
from agentic_forex.governance.models import AutonomousManagerReport
from agentic_forex.market_data.ingest import ingest_oanda_json
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.policy.calendar import ingest_economic_calendar
from agentic_forex.policy.parity_scope import build_parity_scope_audit
from agentic_forex.runtime import ReadPolicy
from agentic_forex.utils.io import write_json
from agentic_forex.workflows.contracts import CandidateDraft, MarketContextSummary, StrategySpec

from conftest import create_economic_calendar_csv, create_oanda_candles_json


def _candidate() -> CandidateDraft:
    return CandidateDraft(
        candidate_id="AF-CAND-POLICY",
        family="scalping",
        title="Policy Benchmark Seed",
        thesis="Verify news blackout and FTMO-policy scaffolding on a deterministic scalping strategy.",
        source_citations=["SRC-001"],
        strategy_hypothesis="A Europe-session breakout baseline should expose policy-layer behavior in tests.",
        market_context=MarketContextSummary(
            session_focus="europe_open_breakout",
            volatility_preference="moderate_to_high",
            directional_bias="both",
            execution_notes=["Use EUR and USD high-impact event blackouts."],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Europe-session breakout baseline for policy testing.",
        entry_summary="Enter on deterministic momentum confirmation with spread and volatility filters.",
        exit_summary="Exit on stop, target, or timeout.",
        risk_summary="Single-position scalping with fixed stop, target, and defined risk.",
        notes=["Policy test seed."],
        quality_flags=["quant_reviewed"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="session_breakout",
        holding_bars=45,
        signal_threshold=1.2,
        stop_loss_pips=5.0,
        take_profit_pips=8.0,
    )


def test_calendar_blackout_and_account_metrics(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    candidate = _candidate()
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)

    with_news = run_backtest(spec, settings)
    without_news = run_backtest(spec.model_copy(update={"news_policy": spec.news_policy.model_copy(update={"enabled": False})}), settings)

    assert with_news.trade_count <= without_news.trade_count
    assert with_news.account_metrics["news_blocked_entries"] > 0
    assert without_news.account_metrics["average_position_size_lots"] > 0
    assert without_news.account_metrics["max_margin_utilization_pct"] > 0
    ledger = pd.read_csv(without_news.trade_ledger_path)
    assert "pnl_dollars" in ledger.columns
    assert "position_size_lots" in ledger.columns
    assert "margin_utilization_pct" in ledger.columns


def test_compile_strategy_spec_propagates_market_rationale_and_walk_forward_contract(settings):
    candidate = _candidate()

    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)

    assert spec.market_rationale.market_behavior
    assert spec.market_rationale.edge_mechanism
    assert spec.market_rationale.persistence_reason
    assert spec.market_rationale.failure_regimes
    assert spec.market_rationale.evidence_tags == []
    assert spec.validation_profile.walk_forward_mode == "anchored_time_windows"
    assert spec.validation_profile.walk_forward_profit_factor_floor == settings.validation.walk_forward_profit_factor_floor
    assert spec.validation_profile.walk_forward_min_trades_per_window == settings.validation.walk_forward_min_trades_per_window
    assert spec.validation_profile.walk_forward_min_window_days == settings.validation.walk_forward_min_window_days


def test_backtest_walk_forward_summary_uses_anchored_time_windows(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    candidate = _candidate()
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    spec = StrategySpec.model_validate(spec_payload)

    artifact = run_backtest(spec, settings)

    assert len(artifact.walk_forward_summary) == settings.validation.walk_forward_windows
    assert all(window["mode"] == "anchored_time_windows" for window in artifact.walk_forward_summary)
    assert all("passed" in window for window in artifact.walk_forward_summary)
    assert all("failure_reasons" in window for window in artifact.walk_forward_summary)


def test_market_rationale_infers_family_evidence_tags():
    candidate = CandidateDraft(
        candidate_id="AF-CAND-EVIDENCE",
        family="research",
        title="FX Cross-Rate Mean Reversion",
        thesis="Use a common quote currency and include rollover handling for an overnight mean-reversion family.",
        source_citations=["SRC-TEST"],
        strategy_hypothesis="Run ADF and variance ratio checks, then size the lookback from the half-life of reversion.",
        market_context=MarketContextSummary(
            session_focus="overnight_cross_rate",
            volatility_preference="moderate",
            directional_bias="both",
            execution_notes=["Common quote currency handling is required."],
            allowed_hours_utc=[20, 21, 22, 23],
        ),
        market_rationale={
            "market_behavior": "Stationarity and cointegration should support the spread.",
            "edge_mechanism": "Exploit the mean reversion of a common quote currency portfolio.",
            "persistence_reason": "Half-life keeps the holding period practical.",
            "failure_regimes": ["Carry regime changes can break the setup."],
            "validation_focus": [
                "Confirm ADF and Hurst evidence before seeding.",
                "Model rollover interest if the trade is held overnight.",
            ],
        },
        setup_summary="Build a stationary cross-rate spread before entering.",
        entry_summary="Enter when the spread deviates and the portfolio remains cointegrated.",
        exit_summary="Exit on mean reversion, stop, or timeout.",
        risk_summary="Single position with explicit overnight risk controls.",
        entry_style="mean_reversion_pullback",
        holding_bars=180,
        signal_threshold=1.1,
        stop_loss_pips=10.0,
        take_profit_pips=15.0,
    )

    assert candidate.market_rationale.evidence_tags == [
        "fx_common_quote_realism",
        "fx_rollover_realism",
        "mean_reversion_half_life",
        "mean_reversion_stationarity",
    ]


def test_build_parity_scope_audit_generates_scope_docs_and_counts(settings):
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="live-throughput",
            family="live_family",
            hypothesis_class="trend_retest",
            seed_candidate_id="AF-CAND-1001",
            parity_class="m1_official",
            parity_class_assigned_by="pytest",
            parity_class_assigned_at="2026-03-24T12:00:00Z",
            queue_kind="throughput",
        ),
        ProgramLanePolicy(
            lane_id="live-promotion",
            family="live_family",
            hypothesis_class="trend_retest",
            seed_candidate_id="AF-CAND-1001",
            parity_class="m1_official",
            parity_class_assigned_by="pytest",
            parity_class_assigned_at="2026-03-24T12:00:00Z",
            queue_kind="promotion",
        ),
        ProgramLanePolicy(
            lane_id="review-throughput",
            family="review_family",
            hypothesis_class="session_breakout",
            seed_candidate_id="AF-CAND-1002",
            queue_kind="throughput",
        ),
        ProgramLanePolicy(
            lane_id="archival-throughput",
            family="archival_family",
            hypothesis_class="range_reclaim",
            seed_candidate_id="AF-CAND-1003",
            queue_kind="throughput",
        ),
        ProgramLanePolicy(
            lane_id="tick-promotion",
            family="tick_family",
            hypothesis_class="micro_path_probe",
            seed_candidate_id="AF-CAND-1004",
            parity_class="tick_required",
            parity_class_assigned_by="pytest",
            parity_class_assigned_at="2026-03-24T12:05:00Z",
            queue_kind="promotion",
        ),
    ]

    _write_manager_report(
        settings,
        file_name="manager-review.json",
        family="review_family",
        stop_reason="watchdog_repeated_stop_reason:program_loop_max_cycles_reached",
    )
    _write_manager_report(
        settings,
        file_name="manager-archival.json",
        family="archival_family",
        stop_reason="data_label_audit_completed_family_retire_confirmed",
    )
    frozen_status_path = settings.paths().reports_dir / "AF-CAND-0239" / "operational_status.md"
    frozen_status_path.parent.mkdir(parents=True, exist_ok=True)
    frozen_status_path.write_text(
        "\n".join(
            [
                "# AF-CAND-0239 Operational Status",
                "",
                "- Candidate: `AF-CAND-0239`",
                "- Family: `live_family`",
                "- Hypothesis class: `trend_retest`",
                "- Official parity class: `m1_official`",
                "- Frozen status:",
                "  - `research-valid, parity-blocked, operationally unproven under current official M1 parity standard`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = build_parity_scope_audit(settings)

    assert report.total_lineages == 4
    assert report.explicit_parity_class_lineages == 2
    assert report.tick_required_lineages == 1
    assert report.unresolved_review_needed_lineages == 1
    assert report.archival_reference_only_lineages == 1
    assert report.unset_parity_class_lineages == 2
    assert report.conflicting_parity_class_lineages == 0

    lineages = {(lineage.family, lineage.hypothesis_class): lineage for lineage in report.lineages}
    assert lineages[("live_family", "trend_retest")].current_scope_status == "in_scope_under_current_m1"
    assert lineages[("review_family", "session_breakout")].current_scope_status == "review_needed_before_official_parity"
    assert lineages[("archival_family", "range_reclaim")].current_scope_status == "archival_or_reference_only"
    assert lineages[("tick_family", "micro_path_probe")].current_scope_status == "blocked_tick_required_pending_official_standard"

    assert report.frozen_reference_candidates[0].candidate_id == "AF-CAND-0239"
    assert settings.paths().knowledge_dir.joinpath("parity-lineage-audit.md").exists()
    assert settings.paths().knowledge_dir.joinpath("parity-operator-matrix.md").exists()
    assert settings.paths().policy_reports_dir.joinpath("parity_scope_audit.json").exists()


def _write_manager_report(settings, *, file_name: str, family: str, stop_reason: str) -> None:
    report_path = settings.paths().autonomous_manager_dir / file_name
    report = AutonomousManagerReport(
        manager_run_id=file_name.replace(".json", ""),
        program_id=f"{family}-program",
        family=family,
        executed_cycles=1,
        max_cycles=4,
        status="stopped",
        stop_reason=stop_reason,
        stop_class="blocked_policy",
        terminal_boundary="blocked_no_authorized_path",
        policy_snapshot_hash="pytest-policy-hash",
        notification_required=True,
        notification_reason="blocked_no_authorized_path",
        report_path=report_path,
    )
    write_json(report_path, report.model_dump(mode="json"))
