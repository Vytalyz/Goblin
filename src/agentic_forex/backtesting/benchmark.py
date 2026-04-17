from __future__ import annotations

from pathlib import Path

from agentic_forex.backtesting.engine import run_backtest, run_stress_test
from agentic_forex.backtesting.models import BenchmarkVariantResult, ScalpingBenchmarkReport
from agentic_forex.config import Settings
from agentic_forex.evals.graders import grade_candidate
from agentic_forex.utils.io import write_json
from agentic_forex.workflows.contracts import FilterRule, SetupLogic, StrategySpec


def run_scalping_benchmark(spec: StrategySpec, settings: Settings) -> ScalpingBenchmarkReport:
    if spec.family != "scalping":
        raise ValueError("Scalping benchmark only supports scalping strategy specs.")
    variants = build_scalping_variants(spec)
    results: list[BenchmarkVariantResult] = []
    for variant in variants:
        variant_dir = settings.paths().reports_dir / variant.candidate_id
        variant_dir.mkdir(parents=True, exist_ok=True)
        spec_path = variant_dir / "strategy_spec.json"
        write_json(spec_path, variant.model_dump(mode="json"))
        backtest = run_backtest(variant, settings)
        stress = run_stress_test(variant, settings)
        grades = grade_candidate(backtest, stress, settings)
        ranking_score = compute_candidate_ranking_score(backtest, stress, grades)
        results.append(
            BenchmarkVariantResult(
                candidate_id=variant.candidate_id,
                benchmark_group_id=variant.benchmark_group_id or spec.candidate_id,
                variant_name=variant.variant_name,
                entry_style=variant.entry_style,
                spec_path=spec_path,
                backtest_summary_path=backtest.summary_path,
                stress_report_path=stress.report_path,
                trade_count=backtest.trade_count,
                profit_factor=backtest.profit_factor,
                out_of_sample_profit_factor=backtest.out_of_sample_profit_factor,
                expectancy_pips=backtest.expectancy_pips,
                max_drawdown_pct=backtest.max_drawdown_pct,
                stressed_profit_factor=stress.stressed_profit_factor,
                grades=grades,
                ranking_score=round(ranking_score, 6),
            )
        )
    ordered = sorted(
        results,
        key=lambda item: item.ranking_score,
        reverse=True,
    )
    report = ScalpingBenchmarkReport(
        benchmark_group_id=spec.benchmark_group_id or spec.candidate_id,
        base_candidate_id=spec.candidate_id,
        report_path=_benchmark_report_path(settings, spec),
        variants=ordered,
        recommended_candidate_id=ordered[0].candidate_id,
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    return report


def build_scalping_variants(spec: StrategySpec) -> list[StrategySpec]:
    if spec.family != "scalping":
        raise ValueError("Scalping variants require a scalping strategy spec.")
    benchmark_group_id = spec.benchmark_group_id or spec.candidate_id
    variants = [
        spec.model_copy(
            update={
                "benchmark_group_id": benchmark_group_id,
                "variant_name": "baseline_europe_breakout",
                "notes": list(spec.notes) + ["Benchmark baseline variant."],
            }
        ),
        _variant(
            spec,
            suffix="VOL",
            variant_name="volatility_breakout",
            entry_style="volatility_breakout",
            setup_summary="Trade only the strongest Europe-session expansions when both volatility and directional momentum accelerate together.",
            holding_bars=30,
            signal_threshold=1.8,
            stop_loss_pips=5.5,
            take_profit_pips=9.5,
            allowed_hours=[7, 8, 9, 10, 11],
            filters=[
                ("max_spread_pips", "1.8"),
                ("min_volatility_20", "0.00014"),
                ("require_ret_5_alignment", "true"),
                ("require_mean_location_alignment", "true"),
                ("breakout_zscore_floor", "0.55"),
            ],
            notes=["Benchmark variant emphasizing stronger Europe-session expansion."],
        ),
        _variant(
            spec,
            suffix="PULL",
            variant_name="pullback_continuation",
            entry_style="pullback_continuation",
            setup_summary="Trade pullbacks back into the short-term mean only when the broader intraday move still points in the original direction.",
            holding_bars=24,
            signal_threshold=0.9,
            stop_loss_pips=4.8,
            take_profit_pips=7.2,
            allowed_hours=[7, 8, 9, 10, 11, 12],
            filters=[
                ("max_spread_pips", "2.0"),
                ("min_volatility_20", "0.00008"),
                ("trend_ret_5_min", "0.00008"),
                ("pullback_zscore_limit", "0.45"),
                ("require_recovery_ret_1", "true"),
            ],
            notes=["Benchmark variant focused on continuation after shallow pullbacks."],
        ),
        _variant(
            spec,
            suffix="FADE",
            variant_name="failed_break_fade",
            entry_style="failed_break_fade",
            setup_summary="Fade failed intraday breakouts only after a sharp extension begins to reverse back through the short-term mean.",
            holding_bars=18,
            signal_threshold=1.5,
            stop_loss_pips=4.5,
            take_profit_pips=6.5,
            allowed_hours=[7, 8, 9, 10, 11, 12],
            filters=[
                ("max_spread_pips", "2.0"),
                ("min_volatility_20", "0.00009"),
                ("fade_ret_5_floor", "0.00005"),
                ("fade_momentum_ceiling", "3.2"),
                ("require_reversal_ret_1", "true"),
            ],
            notes=["Benchmark variant targeting failed breakouts rather than clean trend continuation."],
        ),
    ]
    return variants


def _variant(
    spec: StrategySpec,
    *,
    suffix: str,
    variant_name: str,
    entry_style: str,
    setup_summary: str,
    holding_bars: int,
    signal_threshold: float,
    stop_loss_pips: float,
    take_profit_pips: float,
    allowed_hours: list[int],
    filters: list[tuple[str, str]],
    notes: list[str],
) -> StrategySpec:
    candidate_id = f"{spec.candidate_id}-{suffix}"
    benchmark_group_id = spec.benchmark_group_id or spec.candidate_id
    return spec.model_copy(
        update={
            "candidate_id": candidate_id,
            "benchmark_group_id": benchmark_group_id,
            "variant_name": variant_name,
            "entry_style": entry_style,
            "holding_bars": holding_bars,
            "signal_threshold": signal_threshold,
            "stop_loss_pips": stop_loss_pips,
            "take_profit_pips": take_profit_pips,
            "setup_logic": SetupLogic(
                style=entry_style,
                summary=setup_summary,
                trigger_conditions=list(spec.setup_logic.trigger_conditions),
            ),
            "session_policy": spec.session_policy.model_copy(update={"allowed_hours_utc": allowed_hours}),
            "filters": [FilterRule(name=name, rule=rule) for name, rule in filters],
            "entry_logic": list(spec.entry_logic),
            "exit_logic": [
                f"Exit through fixed stop, fixed target, or {holding_bars}-bar timeout.",
            ],
            "risk_policy": spec.risk_policy.model_copy(
                update={
                    "stop_loss_pips": stop_loss_pips,
                    "take_profit_pips": take_profit_pips,
                }
            ),
            "notes": list(spec.notes) + notes,
        }
    )


def compute_candidate_ranking_score(backtest, stress, grades: dict) -> float:
    score = 0.0
    if grades.get("trade_count_ok"):
        score += 20.0
    else:
        score -= 80.0
    if grades.get("profit_factor_ok"):
        score += 30.0
    else:
        score -= 40.0
    if grades.get("expectancy_ok"):
        score += 20.0
    else:
        score -= 20.0
    if grades.get("stress_ok"):
        score += 20.0
    else:
        score -= 30.0
    if grades.get("walk_forward_ok"):
        score += 20.0
    else:
        score -= 20.0
    if grades.get("ready_for_publish"):
        score += 100.0
    score += min(backtest.out_of_sample_profit_factor, 5.0) * 10.0
    score += min(stress.stressed_profit_factor, 5.0) * 6.0
    score += max(backtest.expectancy_pips, -5.0) * 5.0
    score -= min(max(backtest.max_drawdown_pct, 0.0), 200.0) * 0.1
    return score


def _benchmark_report_path(settings: Settings, spec: StrategySpec) -> Path:
    return settings.paths().reports_dir / spec.candidate_id / "scalping_benchmark.json"
