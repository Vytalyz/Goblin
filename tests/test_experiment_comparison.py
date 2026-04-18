from __future__ import annotations

import csv
import json

import pytest
from conftest import create_economic_calendar_csv, create_oanda_candles_json

from agentic_forex.backtesting.benchmark import run_scalping_benchmark
from agentic_forex.backtesting.models import BacktestArtifact, StressTestReport
from agentic_forex.experiments import compare_experiments
from agentic_forex.market_data.ingest import ingest_oanda_json
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.policy.calendar import ingest_economic_calendar
from agentic_forex.runtime import ReadPolicy
from agentic_forex.workflows.contracts import CandidateDraft, MarketContextSummary, StrategySpec


def test_compare_experiments_writes_ranked_registry_with_ftmo_fit(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    candidate = CandidateDraft(
        candidate_id="AF-CAND-COMPARE",
        family="scalping",
        title="Comparison Seed",
        thesis="Rank deterministic scalping variants on the same canonical dataset and include FTMO fit in the comparison view.",
        source_citations=["SRC-001", "SRC-002"],
        strategy_hypothesis="Benchmark variants should be directly comparable once they share the same data and evaluation rules.",
        market_context=MarketContextSummary(
            session_focus="europe_open_breakout",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Use the same OANDA EUR/USD slice for every comparison row."],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Comparison seed for deterministic scalping benchmark variants.",
        entry_summary="Use the base session-breakout rules as the seed variant.",
        exit_summary="Exit on fixed stop, target, or timeout.",
        risk_summary="Single-position scalping only.",
        notes=["Seed candidate for comparison-layer testing."],
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

    benchmark_report = run_scalping_benchmark(spec, settings)

    report = compare_experiments(settings, family="scalping")

    assert report.registry_path.exists()
    assert report.report_path.exists()
    assert report.latest_report_path.exists()
    assert report.total_records >= 4
    if report.recommended_candidate_id is not None:
        assert any(record.candidate_id == report.recommended_candidate_id for record in report.records)
    assert report.records[0].comparison_score >= report.records[-1].comparison_score
    assert any(record.candidate_id == benchmark_report.base_candidate_id for record in report.records)
    assert all(record.ftmo_fit_score is not None for record in report.records)
    assert all(record.dataset_start_utc is not None for record in report.records)
    assert all(record.dataset_end_utc is not None for record in report.records)
    assert any(record.benchmark_report_path == benchmark_report.report_path for record in report.records)
    assert any(record.readiness == "unreviewed" for record in report.records)

    with report.registry_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == report.total_records
    assert rows[0]["candidate_id"] == report.records[0].candidate_id
    assert rows[0]["ftmo_fit_score"] != ""


def test_compare_experiments_does_not_auto_recommend_non_viable_candidate(settings):
    base_candidate = CandidateDraft(
        candidate_id="AF-CAND-COMPARE-WEAK",
        family="scalping",
        title="Weak Comparison Seed",
        thesis="Weak candidate should remain visible in comparison output without being auto-recommended.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Weak branches with sparse trades and negative expectancy should not be auto-promoted.",
        market_context=MarketContextSummary(
            session_focus="europe_open_breakout",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Comparison baseline candidate."],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Weak seed for comparison recommendation tests.",
        entry_summary="Use deterministic entry rules.",
        exit_summary="Exit on fixed stop, target, or timeout.",
        risk_summary="Single-position scalping only.",
        notes=[],
        quality_flags=["comparison_test"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="session_breakout",
        holding_bars=30,
        signal_threshold=1.15,
        stop_loss_pips=5.0,
        take_profit_pips=7.5,
    )
    weak_spec_payload = compile_strategy_spec_tool(
        payload=base_candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    weak_spec = StrategySpec.model_validate(weak_spec_payload)
    strong_spec = weak_spec.model_copy(
        update={
            "candidate_id": "AF-CAND-COMPARE-STRONG",
            "benchmark_group_id": "AF-CAND-COMPARE-STRONG",
            "variant_name": "strong",
        }
    )

    _write_comparison_candidate(
        settings,
        weak_spec,
        trade_count=24,
        profit_factor=0.71,
        out_of_sample_profit_factor=6.31,
        expectancy_pips=-0.67,
        max_drawdown_pct=1.33,
        stress_passed=False,
        stressed_profit_factor=0.58,
    )
    _write_comparison_candidate(
        settings,
        strong_spec,
        trade_count=140,
        profit_factor=1.18,
        out_of_sample_profit_factor=1.23,
        expectancy_pips=0.24,
        max_drawdown_pct=2.4,
        stress_passed=True,
        stressed_profit_factor=1.04,
    )

    report = compare_experiments(
        settings,
        candidate_ids=["AF-CAND-COMPARE-WEAK", "AF-CAND-COMPARE-STRONG"],
    )

    assert report.total_records == 2
    assert report.recommended_candidate_id == "AF-CAND-COMPARE-STRONG"
    record_by_candidate = {record.candidate_id: record for record in report.records}
    assert (
        record_by_candidate["AF-CAND-COMPARE-STRONG"].comparison_score
        > record_by_candidate["AF-CAND-COMPARE-WEAK"].comparison_score
    )


def test_compare_experiments_rejects_invalid_requested_candidate(settings):
    candidate = CandidateDraft(
        candidate_id="AF-CAND-COMPARE-INVALID",
        family="scalping",
        title="Invalid comparison candidate",
        thesis="Explicit comparison requests must reject artifacts that violate comparison contracts.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Missing split and regime accounting should hard-fail explicit comparison requests.",
        market_context=MarketContextSummary(
            session_focus="europe_open_breakout",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Comparison contract violation fixture."],
            allowed_hours_utc=[7, 8, 9, 10],
        ),
        setup_summary="Invalid comparison fixture.",
        entry_summary="Deterministic entry.",
        exit_summary="Deterministic exit.",
        risk_summary="Single-position.",
        entry_style="session_breakout",
        holding_bars=20,
        signal_threshold=1.1,
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

    candidate_dir = settings.paths().reports_dir / spec.candidate_id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    spec_path = candidate_dir / "strategy_spec.json"
    summary_path = candidate_dir / "backtest_summary.json"
    stress_path = candidate_dir / "stress_test.json"
    trade_ledger_path = candidate_dir / "trade_ledger.csv"

    spec_path.write_text(json.dumps(spec.model_dump(mode="json"), indent=2), encoding="utf-8")
    trade_ledger_path.write_text("", encoding="utf-8")
    invalid_backtest = BacktestArtifact(
        candidate_id=spec.candidate_id,
        spec_path=spec_path,
        trade_ledger_path=trade_ledger_path,
        summary_path=summary_path,
        trade_count=20,
        win_rate=0.5,
        profit_factor=1.1,
        expectancy_pips=0.1,
        max_drawdown_pct=1.0,
        out_of_sample_profit_factor=1.0,
        split_breakdown={},
        regime_breakdown={},
        walk_forward_summary=[],
        failure_attribution={},
        account_metrics={},
        artifact_references={},
    )
    summary_path.write_text(json.dumps(invalid_backtest.model_dump(mode="json"), indent=2), encoding="utf-8")
    stress = StressTestReport(
        candidate_id=spec.candidate_id,
        base_profit_factor=1.1,
        stressed_profit_factor=1.0,
        spread_multiplier=spec.cost_model.spread_multiplier,
        slippage_pips=spec.cost_model.slippage_pips,
        passed=True,
        scenarios=[],
        artifact_references={},
        report_path=stress_path,
    )
    stress_path.write_text(json.dumps(stress.model_dump(mode="json"), indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid comparison inputs rejected"):
        compare_experiments(settings, candidate_ids=[spec.candidate_id])


def _write_comparison_candidate(
    settings,
    spec: StrategySpec,
    *,
    trade_count: int,
    profit_factor: float,
    out_of_sample_profit_factor: float,
    expectancy_pips: float,
    max_drawdown_pct: float,
    stress_passed: bool,
    stressed_profit_factor: float,
) -> None:
    candidate_dir = settings.paths().reports_dir / spec.candidate_id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    spec_path = candidate_dir / "strategy_spec.json"
    trade_ledger_path = candidate_dir / "trade_ledger.csv"
    summary_path = candidate_dir / "backtest_summary.json"
    stress_path = candidate_dir / "stress_test.json"

    spec_path.write_text(json.dumps(spec.model_dump(mode="json"), indent=2), encoding="utf-8")
    trade_ledger_path.write_text("", encoding="utf-8")

    backtest = BacktestArtifact(
        candidate_id=spec.candidate_id,
        spec_path=spec_path,
        trade_ledger_path=trade_ledger_path,
        summary_path=summary_path,
        trade_count=trade_count,
        win_rate=0.5,
        profit_factor=profit_factor,
        expectancy_pips=expectancy_pips,
        max_drawdown_pct=max_drawdown_pct,
        out_of_sample_profit_factor=out_of_sample_profit_factor,
        split_breakdown={
            "in_sample": {
                "trade_count": max(trade_count - 20, 1),
                "profit_factor": max(profit_factor - 0.05, 0.01),
                "expectancy_pips": max(expectancy_pips - 0.05, -10.0),
            },
            "out_of_sample": {
                "trade_count": max(min(20, trade_count), 1),
                "profit_factor": max(out_of_sample_profit_factor, 0.01),
                "expectancy_pips": expectancy_pips,
            },
        },
        regime_breakdown={
            "session_bucket": {
                "london_open": {
                    "trade_count": max(trade_count // 2, 1),
                    "mean_pnl_pips": expectancy_pips,
                    "profit_factor": max(profit_factor, 0.01),
                }
            },
            "volatility_bucket": {
                "normal": {
                    "trade_count": max(trade_count // 2, 1),
                    "mean_pnl_pips": expectancy_pips,
                    "profit_factor": max(profit_factor, 0.01),
                }
            },
            "context_bucket": {
                "trend": {
                    "trade_count": max(trade_count // 2, 1),
                    "mean_pnl_pips": expectancy_pips,
                    "profit_factor": max(profit_factor, 0.01),
                }
            },
        },
        walk_forward_summary=[
            {
                "window": 1,
                "start_utc": "2025-01-01T00:00:00Z",
                "end_utc": "2025-01-15T00:00:00Z",
                "trade_count": max(trade_count // 2, 1),
                "profit_factor": max(profit_factor, 0.01),
                "expectancy_pips": expectancy_pips,
                "passed": True,
                "mode": "anchored_time_windows",
            },
            {
                "window": 2,
                "start_utc": "2025-01-15T00:00:00Z",
                "end_utc": "2025-01-31T00:00:00Z",
                "trade_count": max(trade_count - max(trade_count // 2, 1), 1),
                "profit_factor": max(out_of_sample_profit_factor, 0.01),
                "expectancy_pips": expectancy_pips,
                "passed": True,
                "mode": "anchored_time_windows",
            },
        ],
        failure_attribution={},
        account_metrics={},
        artifact_references={},
    )
    summary_path.write_text(json.dumps(backtest.model_dump(mode="json"), indent=2), encoding="utf-8")

    stress = StressTestReport(
        candidate_id=spec.candidate_id,
        base_profit_factor=profit_factor,
        stressed_profit_factor=stressed_profit_factor,
        spread_multiplier=spec.cost_model.spread_multiplier,
        slippage_pips=spec.cost_model.slippage_pips,
        fill_delay_ms=getattr(spec.cost_model, "fill_delay_ms", 0),
        commission_per_standard_lot_usd=getattr(spec.cost_model, "commission_per_standard_lot_usd", 0.0),
        passed=stress_passed,
        scenarios=[],
        artifact_references={},
        report_path=stress_path,
    )
    stress_path.write_text(json.dumps(stress.model_dump(mode="json"), indent=2), encoding="utf-8")
