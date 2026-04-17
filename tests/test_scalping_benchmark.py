from __future__ import annotations

from agentic_forex.backtesting.benchmark import build_scalping_variants, run_scalping_benchmark
from agentic_forex.market_data.ingest import ingest_oanda_json
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.runtime import ReadPolicy
from agentic_forex.workflows.contracts import CandidateDraft, MarketContextSummary, StrategySpec

from conftest import create_oanda_candles_json


def test_scalping_benchmark_generates_ranked_variants(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    candidate = CandidateDraft(
        candidate_id="AF-CAND-BENCH",
        family="scalping",
        title="Scalping Benchmark Seed",
        thesis="Benchmark several deterministic Europe-session scalping variants on the same canonical dataset.",
        source_citations=["SRC-001", "SRC-002"],
        strategy_hypothesis="Different deterministic scalping structures should be compared before promotion.",
        market_context=MarketContextSummary(
            session_focus="europe_open_breakout",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Benchmark against the same OANDA EUR/USD dataset."],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Base benchmark seed for Europe-session deterministic scalping.",
        entry_summary="Use deterministic session-breakout confirmation as the baseline variant.",
        exit_summary="Exit on fixed stop, fixed target, or timeout.",
        risk_summary="Single-position scalping only.",
        notes=["Benchmark seed candidate."],
        quality_flags=["benchmark_seed"],
        contradiction_summary=[],
        critic_notes=[],
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

    variants = build_scalping_variants(spec)
    assert [item.variant_name for item in variants] == [
        "baseline_europe_breakout",
        "volatility_breakout",
        "pullback_continuation",
        "failed_break_fade",
    ]
    assert len({item.candidate_id for item in variants}) == 4

    report = run_scalping_benchmark(spec, settings)

    assert report.report_path.exists()
    assert len(report.variants) == 4
    assert report.recommended_candidate_id == report.variants[0].candidate_id
    assert report.variants[0].ranking_score >= report.variants[-1].ranking_score
    assert {item.entry_style for item in report.variants} == {
        "session_breakout",
        "volatility_breakout",
        "pullback_continuation",
        "failed_break_fade",
    }
    for variant in report.variants:
        assert variant.spec_path.exists()
        assert variant.backtest_summary_path.exists()
        assert variant.stress_report_path.exists()
        assert variant.benchmark_group_id == "AF-CAND-BENCH"
