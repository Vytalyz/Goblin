from __future__ import annotations

import pandas as pd

from agentic_forex.backtesting.engine import _generate_signal, run_backtest, run_stress_test
from agentic_forex.evals.robustness import build_robustness_report, _estimate_family_white_reality_check_from_ledgers
from agentic_forex.market_data.ingest import ingest_oanda_json
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.policy.calendar import ingest_economic_calendar
from agentic_forex.runtime import ReadPolicy
from agentic_forex.utils.io import write_json
from agentic_forex.workflows.contracts import CandidateDraft, FilterRule, MarketContextSummary, StrategySpec

from conftest import create_economic_calendar_csv, create_oanda_candles_json


def test_family_cscv_pbo_is_emitted_when_comparable_candidates_exist(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    active_hours = list(range(24))
    primary = _build_candidate("AF-CAND-ANTI-01", "Anti-Overfit Primary", signal_threshold=0.75, allowed_hours=active_hours)
    secondary = _build_candidate("AF-CAND-ANTI-02", "Anti-Overfit Secondary", signal_threshold=0.65, allowed_hours=active_hours)

    primary_spec = _compile_candidate(primary, settings)
    secondary_spec = _compile_candidate(secondary, settings)

    primary_backtest = run_backtest(primary_spec, settings)
    primary_stress = run_stress_test(primary_spec, settings)
    run_backtest(secondary_spec, settings)

    robustness = build_robustness_report(
        primary_spec,
        backtest=primary_backtest,
        stress=primary_stress,
        trade_ledger=_read_trade_ledger(primary_backtest.trade_ledger_path),
        settings=settings,
    )

    assert robustness.cscv_pbo_available is True
    assert robustness.mode == "full_search_adjusted_robustness"
    assert robustness.cscv_candidate_count >= 2
    assert robustness.pbo is not None
    assert robustness.white_reality_check_available is True
    assert robustness.white_reality_check_p_value is not None
    assert robustness.white_reality_check_candidate_count == robustness.cscv_candidate_count
    assert primary_spec.candidate_id in robustness.candidate_universe
    assert secondary_spec.candidate_id in robustness.candidate_universe
    assert robustness.comparable_universe_contract["execution_cost_model_version"] == primary_backtest.artifact_references["data_provenance"]["execution_cost_model_version"]


def test_family_cscv_pbo_excludes_non_comparable_execution_contracts(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    active_hours = list(range(24))
    primary = _build_candidate("AF-CAND-ANTI-COMP-01", "Comparable Primary", signal_threshold=0.75, allowed_hours=active_hours)
    secondary = _build_candidate("AF-CAND-ANTI-COMP-02", "Comparable Secondary", signal_threshold=0.65, allowed_hours=active_hours)

    primary_spec = _compile_candidate(primary, settings)
    secondary_spec = _compile_candidate(secondary, settings)
    non_comparable_spec = secondary_spec.model_copy(
        update={
            "candidate_id": "AF-CAND-ANTI-COMP-03",
            "benchmark_group_id": "AF-CAND-ANTI-COMP-03",
            "variant_name": "non_comparable_execution_contract",
            "cost_model": secondary_spec.cost_model.model_copy(
                update={
                    "fill_delay_ms": 60_000,
                    "commission_per_standard_lot_usd": 7.0,
                    "slippage_pips": 0.15,
                }
            ),
            "execution_cost_model": secondary_spec.execution_cost_model.model_copy(
                update={
                    "fill_delay_ms": 60_000,
                    "commission_per_standard_lot_usd": 7.0,
                    "slippage_pips": 0.15,
                }
            ),
        }
    )
    write_json(
        settings.paths().reports_dir / non_comparable_spec.candidate_id / "strategy_spec.json",
        non_comparable_spec.model_dump(mode="json"),
    )

    primary_backtest = run_backtest(primary_spec, settings)
    primary_stress = run_stress_test(primary_spec, settings)
    run_backtest(secondary_spec, settings)
    run_backtest(non_comparable_spec, settings)

    robustness = build_robustness_report(
        primary_spec,
        backtest=primary_backtest,
        stress=primary_stress,
        trade_ledger=_read_trade_ledger(primary_backtest.trade_ledger_path),
        settings=settings,
    )

    assert primary_spec.candidate_id in robustness.candidate_universe
    assert secondary_spec.candidate_id in robustness.candidate_universe
    assert non_comparable_spec.candidate_id not in robustness.candidate_universe
    assert robustness.cscv_candidate_count == 2
    assert robustness.white_reality_check_candidate_count == 2


def test_family_white_reality_check_supports_clear_winner(settings):
    candidate_ledgers = [
        ("AF-CAND-WRC-01", pd.Series([2.0] * 64)),
        ("AF-CAND-WRC-02", pd.Series([-0.5] * 64)),
    ]

    result = _estimate_family_white_reality_check_from_ledgers(
        candidate_ledgers,
        settings=settings,
        contract={"status": "active"},
    )

    assert result["available"] is True
    assert result["best_candidate_id"] == "AF-CAND-WRC-01"
    assert result["p_value"] is not None
    assert result["p_value"] <= settings.validation.white_reality_check_pvalue_threshold


def test_fill_delay_and_commission_reduce_scalping_edge(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    candidate = _build_candidate("AF-CAND-COST-BASE", "Execution Realism Baseline", signal_threshold=1.2, allowed_hours=[7, 8, 9, 10, 11, 12])
    base_spec = _compile_candidate(candidate, settings)
    stressed_cost_spec = base_spec.model_copy(
        update={
            "candidate_id": "AF-CAND-COST-DELAYED",
            "benchmark_group_id": "AF-CAND-COST-DELAYED",
            "variant_name": "delay_and_commission",
            "cost_model": base_spec.cost_model.model_copy(
                update={
                    "fill_delay_ms": 60_000,
                    "commission_per_standard_lot_usd": 7.0,
                    "slippage_pips": 0.15,
                }
            ),
            "execution_cost_model": base_spec.execution_cost_model.model_copy(
                update={
                    "fill_delay_ms": 60_000,
                    "commission_per_standard_lot_usd": 7.0,
                    "slippage_pips": 0.15,
                }
            ),
        }
    )
    write_json(
        settings.paths().reports_dir / stressed_cost_spec.candidate_id / "strategy_spec.json",
        stressed_cost_spec.model_dump(mode="json"),
    )

    base_backtest = run_backtest(base_spec, settings)
    stressed_backtest = run_backtest(stressed_cost_spec, settings)
    stress_report = run_stress_test(base_spec, settings)

    assert stressed_backtest.expectancy_pips < base_backtest.expectancy_pips
    assert stressed_backtest.profit_factor <= base_backtest.profit_factor
    assert any(scenario.name == "spread_slippage_delay" and scenario.fill_delay_ms > 0 for scenario in stress_report.scenarios)


def test_exclude_context_bucket_filter_removes_target_context_trades(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    calendar_csv = create_economic_calendar_csv(tmp_path)
    ingest_oanda_json(oanda_json, settings)
    ingest_economic_calendar(calendar_csv, settings)

    candidate = _build_candidate("AF-CAND-CONTEXT-BASE", "Context Filter Baseline", signal_threshold=1.0, allowed_hours=[7, 8, 9, 10, 11, 12])
    base_spec = _compile_candidate(candidate, settings)
    filtered_spec = base_spec.model_copy(
        update={
            "candidate_id": "AF-CAND-CONTEXT-FILTERED",
            "benchmark_group_id": "AF-CAND-CONTEXT-FILTERED",
            "variant_name": "exclude_mean_reversion_context",
            "filters": list(base_spec.filters) + [FilterRule(name="exclude_context_bucket", rule="mean_reversion_context")],
        }
    )
    write_json(
        settings.paths().reports_dir / filtered_spec.candidate_id / "strategy_spec.json",
        filtered_spec.model_dump(mode="json"),
    )

    base_backtest = run_backtest(base_spec, settings)
    filtered_backtest = run_backtest(filtered_spec, settings)

    base_trades = pd.read_csv(base_backtest.trade_ledger_path)
    filtered_trades = pd.read_csv(filtered_backtest.trade_ledger_path)

    assert (base_trades["context_bucket"] == "mean_reversion_context").any()
    assert not (filtered_trades["context_bucket"] == "mean_reversion_context").any()
    assert filtered_backtest.trade_count < base_backtest.trade_count


def test_pullback_regime_quality_filters_reduce_low_quality_continuation_entries(settings):
    candidate = CandidateDraft(
        candidate_id="AF-CAND-PULLBACK-BASE",
        family="europe_open_high_vol_pullback_regime_research",
        title="Pullback Regime Baseline",
        thesis="Synthetic pullback-continuation baseline for regime-quality filter validation.",
        source_citations=["SRC-001"],
        strategy_hypothesis="High-volatility pullback continuation needs explicit regime-quality gates.",
        market_context=MarketContextSummary(
            session_focus="bridge_to_pre_overlap_pullback_regime_test",
            volatility_preference="high_to_persistent",
            directional_bias="both",
            execution_notes=["Synthetic pullback candidate."],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12],
        ),
        setup_summary="Synthetic pullback setup.",
        entry_summary="Enter on pullback continuation when trend resumes.",
        exit_summary="Exit on stop, target, or timeout.",
        risk_summary="Synthetic pullback risk policy.",
        entry_style="pullback_continuation",
        holding_bars=22,
        signal_threshold=0.88,
        stop_loss_pips=5.2,
        take_profit_pips=7.6,
    )
    base_spec = _compile_candidate(candidate, settings)
    filtered_spec = base_spec.model_copy(
        update={
            "candidate_id": "AF-CAND-PULLBACK-FILTERED",
            "benchmark_group_id": "AF-CAND-PULLBACK-FILTERED",
            "variant_name": "regime_quality_filter",
            "filters": list(base_spec.filters)
            + [
                FilterRule(name="min_volatility_ratio_5_to_20", rule="0.95"),
                FilterRule(name="pullback_range_position_floor", rule="0.50"),
                FilterRule(name="recovery_zscore_floor", rule="0.0"),
                FilterRule(name="require_mean_location_alignment", rule="true"),
                FilterRule(name="min_intrabar_range_pips", rule="1.0"),
            ],
        }
    )
    row = pd.Series(
        {
            "momentum_12": 1.25,
            "ret_5": 0.00011,
            "zscore_10": 0.06,
            "ret_1": 0.00002,
            "mid_c": 1.1012,
            "rolling_mean_10": 1.1010,
            "range_position_10": 0.56,
            "spread_pips": 1.6,
            "spread_to_range_10": 0.28,
            "volatility_20": 0.00009,
            "volatility_5": 0.00011,
            "volatility_ratio_5_to_20": 1.22,
            "intrabar_range_pips": 1.4,
            "range_width_10_pips": 5.8,
        }
    )
    weak_row = row.copy()
    weak_row["mid_c"] = 1.1008
    weak_row["rolling_mean_10"] = 1.1010
    weak_row["range_position_10"] = 0.44
    weak_row["volatility_ratio_5_to_20"] = 0.78
    weak_row["intrabar_range_pips"] = 0.7

    assert _generate_signal(row, base_spec) == 1
    assert _generate_signal(row, filtered_spec) == 1
    assert _generate_signal(weak_row, base_spec) == 1
    assert _generate_signal(weak_row, filtered_spec) == 0


def _build_candidate(candidate_id: str, title: str, *, signal_threshold: float, allowed_hours: list[int]) -> CandidateDraft:
    return CandidateDraft(
        candidate_id=candidate_id,
        family="scalping",
        title=title,
        thesis="Europe-session breakout candidate for robustness and execution-realism testing.",
        source_citations=["SRC-001", "SRC-002"],
        strategy_hypothesis="A deterministic breakout can be tested under anti-overfit and execution realism controls.",
        market_context=MarketContextSummary(
            session_focus="europe_open_breakout",
            volatility_preference="moderate_to_high",
            directional_bias="both",
            execution_notes=["Test candidate."],
            allowed_hours_utc=allowed_hours,
        ),
        setup_summary="Europe-session breakout setup.",
        entry_summary="Enter on momentum confirmation with spread and mean-location alignment.",
        exit_summary="Exit on stop, target, or timeout.",
        risk_summary="Single-position deterministic breakout with explicit cost controls.",
        notes=["Generated for execution-realism and robustness testing."],
        quality_flags=["quant_reviewed"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style="session_breakout",
        holding_bars=45,
        signal_threshold=signal_threshold,
        stop_loss_pips=5.0,
        take_profit_pips=8.0,
    )


def _compile_candidate(candidate: CandidateDraft, settings) -> StrategySpec:
    spec_payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    return StrategySpec.model_validate(spec_payload)


def _read_trade_ledger(path):
    return pd.read_csv(path)
