from __future__ import annotations

from conftest import create_economic_calendar_csv, create_oanda_candles_json

from agentic_forex.experiments import iterate_scalping_target
from agentic_forex.market_data.ingest import ingest_oanda_json
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.policy.calendar import ingest_economic_calendar
from agentic_forex.runtime import ReadPolicy
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows.contracts import CandidateDraft, MarketContextSummary, StrategySpec


def test_iterate_scalping_target_generates_variants_and_report(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    baseline = CandidateDraft(
        candidate_id="AF-CAND-BASE",
        family="scalping",
        title="Baseline Breakout",
        thesis="Active baseline breakout scalp.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Baseline favors Europe-session breakout continuation.",
        market_context=MarketContextSummary(
            session_focus="europe_open_breakout",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Baseline candidate."],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Baseline breakout setup.",
        entry_summary="Enter on breakout continuation when momentum, ret_5, and price-location align.",
        exit_summary="Exit via fixed stop, target, or 45-bar timeout.",
        risk_summary="Single-position breakout baseline.",
        notes=[],
        quality_flags=["baseline"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="session_breakout",
        holding_bars=45,
        signal_threshold=1.2,
        stop_loss_pips=5.0,
        take_profit_pips=8.0,
    )
    target = CandidateDraft(
        candidate_id="AF-CAND-TARGET",
        family="scalping",
        title="Target Breakout",
        thesis="Stress-sensitive breakout target for iteration.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Target candidate broadens throughput at the cost of stressed robustness.",
        market_context=MarketContextSummary(
            session_focus="europe_open_retest",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[7, 8, 9, 10, 11],
        ),
        setup_summary="Target breakout setup.",
        entry_summary="Enter on breakout continuation when momentum, ret_5, and price-location align through the retest window.",
        exit_summary="Exit via fixed stop, target, or 36-bar timeout.",
        risk_summary="Single-position retest breakout target.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="session_breakout",
        holding_bars=36,
        signal_threshold=1.0,
        stop_loss_pips=4.5,
        take_profit_pips=7.0,
    )
    for candidate in (baseline, target):
        candidate_path = settings.paths().reports_dir / candidate.candidate_id / "candidate.json"
        write_json(candidate_path, candidate.model_dump(mode="json"))
        compile_strategy_spec_tool(
            payload=candidate.model_dump(mode="json"),
            settings=settings,
            config={},
            read_policy=ReadPolicy(project_root=settings.project_root),
        )

    report = iterate_scalping_target(
        settings,
        baseline_candidate_id=baseline.candidate_id,
        target_candidate_id=target.candidate_id,
    )

    assert report.report_path.exists()
    assert report.comparison_report_path.exists()
    assert report.baseline_candidate_id == baseline.candidate_id
    assert report.target_candidate_id == target.candidate_id
    assert report.recommended_candidate_id in {variant.candidate_id for variant in report.variants}
    assert len(report.variants) == 4
    assert report.oos_guardrail_profit_factor >= 1.05
    for variant in report.variants:
        assert variant.spec_path.exists()
        assert variant.review_packet_path.exists()


def test_iterate_scalping_target_uses_cost_guard_follow_on_templates(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    baseline = CandidateDraft(
        candidate_id="AF-CAND-BASE-CG",
        family="scalping",
        title="Baseline Breakout",
        thesis="Active baseline breakout scalp.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Baseline favors Europe-session breakout continuation.",
        market_context=MarketContextSummary(
            session_focus="europe_open_breakout",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Baseline candidate."],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Baseline breakout setup.",
        entry_summary="Enter on breakout continuation when momentum, ret_5, and price-location align.",
        exit_summary="Exit via fixed stop, target, or 45-bar timeout.",
        risk_summary="Single-position breakout baseline.",
        notes=[],
        quality_flags=["baseline"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="session_breakout",
        holding_bars=45,
        signal_threshold=1.2,
        stop_loss_pips=5.0,
        take_profit_pips=8.0,
    )
    target = CandidateDraft(
        candidate_id="AF-CAND-TARGET-CG",
        family="scalping",
        title="Cost Guard Breakout",
        thesis="Stress-aware cost-guard target for follow-on iteration.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Target candidate protects stressed performance but needs more trades.",
        market_context=MarketContextSummary(
            session_focus="europe_cost_guard_breakout",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Target candidate."],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Cost-guard breakout setup.",
        entry_summary="Enter only when momentum, ret_5, and price-location align under cost-aware conditions.",
        exit_summary="Exit via fixed stop, target, or 28-bar timeout.",
        risk_summary="Single-position cost-guard breakout target.",
        notes=[],
        quality_flags=["target"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="session_breakout",
        holding_bars=28,
        signal_threshold=1.02,
        stop_loss_pips=4.2,
        take_profit_pips=7.4,
    )
    for candidate in (baseline, target):
        candidate_path = settings.paths().reports_dir / candidate.candidate_id / "candidate.json"
        write_json(candidate_path, candidate.model_dump(mode="json"))
        compile_strategy_spec_tool(
            payload=candidate.model_dump(mode="json"),
            settings=settings,
            config={},
            read_policy=ReadPolicy(project_root=settings.project_root),
        )

    target_spec_path = settings.paths().reports_dir / target.candidate_id / "strategy_spec.json"
    target_spec = StrategySpec.model_validate(read_json(target_spec_path))
    target_spec = target_spec.model_copy(update={"variant_name": "cost_guard_breakout"})
    write_json(target_spec_path, target_spec.model_dump(mode="json"))

    report = iterate_scalping_target(
        settings,
        baseline_candidate_id=baseline.candidate_id,
        target_candidate_id=target.candidate_id,
    )

    variant_labels = {variant.variant_label for variant in report.variants}
    assert variant_labels == {
        "extended_session_quality",
        "extended_session_tight_spread",
        "extended_session_buffered_ret5",
        "pre_overlap_balanced",
    }
