from __future__ import annotations

import math
from datetime import UTC
from pathlib import Path

import pandas as pd

from agentic_forex.backtesting.models import BacktestArtifact, StressScenarioResult, StressTestReport
from agentic_forex.config import Settings
from agentic_forex.features.service import build_features
from agentic_forex.governance.provenance import build_data_provenance, build_environment_snapshot
from agentic_forex.governance.trial_ledger import append_trial_entry
from agentic_forex.policy.calendar import build_blackout_windows, is_in_blackout, load_relevant_calendar_events
from agentic_forex.utils.io import write_json
from agentic_forex.workflows.contracts import StrategySpec

TRADE_LEDGER_COLUMNS = [
    "timestamp_utc",
    "exit_timestamp_utc",
    "split",
    "side",
    "entry_price",
    "exit_price",
    "pnl_pips",
    "pnl_dollars",
    "position_size_lots",
    "balance_after",
    "margin_utilization_pct",
    "session_bucket",
    "volatility_bucket",
    "context_bucket",
    "exit_reason",
    "spread_cost_pips",
    "slippage_cost_pips",
    "delay_cost_pips",
    "commission_cost_pips",
    "commission_cost_usd",
    "total_cost_pips",
    "fill_delay_ms",
    "broker_fee_model",
]


def _scan_trailing_exit(
    features: pd.DataFrame,
    entry_index: int,
    exit_index: int,
    signal: int,
    spec: StrategySpec,
) -> tuple[int, str, float] | None:
    """Bar-by-bar scan for trailing stop, fixed SL, or TP hits during holding period.

    Returns ``(exit_bar_index, exit_reason, gross_pips)`` or ``None``.
    *gross_pips* is the raw signed P&L in pips at the trigger level (before costs).
    """
    if not getattr(spec, "trailing_stop_enabled", False) or not spec.trailing_stop_pips:
        return None

    entry_price = float(features.iloc[entry_index]["mid_c"])
    running_extreme = entry_price
    has_hl = "mid_h" in features.columns
    trail_pips = spec.trailing_stop_pips
    sl_pips = spec.stop_loss_pips
    tp_pips = spec.take_profit_pips

    for idx in range(entry_index + 1, exit_index + 1):
        bar = features.iloc[idx]
        bar_h = float(bar["mid_h"]) if has_hl else float(bar["mid_c"])
        bar_l = float(bar["mid_l"]) if has_hl else float(bar["mid_c"])

        if signal > 0:  # long
            running_extreme = max(running_extreme, bar_h)
            trail_price = running_extreme - trail_pips * 0.0001
            sl_price = entry_price - sl_pips * 0.0001
            tp_price = entry_price + tp_pips * 0.0001

            if bar_l <= sl_price:
                return idx, "stop_loss", -sl_pips
            if trail_price > sl_price and bar_l <= trail_price:
                pips = (trail_price - entry_price) * 10000
                return idx, "trailing_stop", pips
            if bar_h >= tp_price:
                return idx, "take_profit", tp_pips
        else:  # short
            running_extreme = min(running_extreme, bar_l)
            trail_price = running_extreme + trail_pips * 0.0001
            sl_price = entry_price + sl_pips * 0.0001
            tp_price = entry_price - tp_pips * 0.0001

            if bar_h >= sl_price:
                return idx, "stop_loss", -sl_pips
            if trail_price < sl_price and bar_h >= trail_price:
                pips = (entry_price - trail_price) * 10000
                return idx, "trailing_stop", pips
            if bar_l <= tp_price:
                return idx, "take_profit", tp_pips

    return None


def run_backtest(
    spec: StrategySpec,
    settings: Settings,
    output_prefix: str | None = None,
    frame: pd.DataFrame | None = None,
) -> BacktestArtifact:
    parquet_path = settings.paths().normalized_research_dir / f"{spec.instrument.lower()}_{spec.execution_granularity.lower()}.parquet"
    frame = frame.copy() if frame is not None else pd.read_parquet(parquet_path)
    features = build_features(frame).reset_index(drop=True)
    blackout_windows = _load_blackout_windows(spec, settings)
    trade_rows = []
    train_cutoff, validation_cutoff = _split_boundaries(len(features), spec.time_split)
    balance = spec.account_model.initial_balance
    next_available_index = 20
    news_blocked_entries = 0
    bar_duration_ms = _granularity_to_milliseconds(spec.execution_granularity)
    delay_bars, delay_fraction = _split_fill_delay(spec.cost_model.fill_delay_ms, bar_duration_ms)
    for index in range(20, len(features) - spec.holding_bars - (delay_bars * 2) - 1):
        if index < next_available_index:
            continue
        row = features.iloc[index]
        if spec.session_policy.allowed_hours_utc and int(row["hour"]) not in spec.session_policy.allowed_hours_utc:
            continue
        if is_in_blackout(row["timestamp_utc"], blackout_windows):
            news_blocked_entries += 1
            continue
        signal = _generate_signal(row, spec)
        if signal == 0:
            continue
        entry_index = index + delay_bars
        exit_signal_index = entry_index + spec.holding_bars
        exit_index = exit_signal_index + delay_bars
        if exit_index >= len(features):
            continue
        entry_row = features.iloc[entry_index]
        trailing_result = _scan_trailing_exit(features, entry_index, exit_index, signal, spec)
        if trailing_result is not None:
            exit_index = trailing_result[0]
        exit_row = features.iloc[exit_index]
        position_size_lots = _position_size_lots(balance, entry_row, spec)
        if position_size_lots <= 0:
            continue
        if trailing_result is not None:
            gross_pips = trailing_result[2]
        else:
            gross_pips = (exit_row["mid_c"] - entry_row["mid_c"]) * 10000 * signal
        spread_cost_pips = ((float(entry_row["spread_pips"]) + float(exit_row["spread_pips"])) / 2.0) * spec.cost_model.spread_multiplier
        delay_cost_pips = _fill_delay_penalty_pips(
            fill_row=entry_row,
            signal=signal,
            delay_fraction=delay_fraction,
            phase="entry",
        ) + _fill_delay_penalty_pips(
            fill_row=exit_row,
            signal=signal,
            delay_fraction=delay_fraction,
            phase="exit",
        )
        slippage_cost_pips = spec.cost_model.slippage_pips
        commission_cost_usd = spec.cost_model.commission_per_standard_lot_usd * position_size_lots
        commission_cost_pips = (
            commission_cost_usd / (spec.account_model.pip_value_per_standard_lot * position_size_lots)
            if position_size_lots > 0
            else 0.0
        )
        price_adjusted_pips = gross_pips - spread_cost_pips - slippage_cost_pips - delay_cost_pips
        if trailing_result is not None:
            exit_reason = trailing_result[1]
            if exit_reason == "trailing_stop":
                net_pips = price_adjusted_pips - commission_cost_pips
            elif exit_reason == "take_profit":
                net_pips = spec.take_profit_pips - commission_cost_pips
            else:
                net_pips = -spec.stop_loss_pips - commission_cost_pips
        else:
            net_pips = price_adjusted_pips - commission_cost_pips
            exit_reason = "time_exit"
            if price_adjusted_pips >= spec.take_profit_pips:
                net_pips = spec.take_profit_pips - commission_cost_pips
                exit_reason = "take_profit"
            elif price_adjusted_pips <= -spec.stop_loss_pips:
                net_pips = -spec.stop_loss_pips - commission_cost_pips
                exit_reason = "stop_loss"
        pnl_dollars = net_pips * spec.account_model.pip_value_per_standard_lot * position_size_lots
        balance = balance + pnl_dollars
        margin_utilization_pct = _margin_utilization_pct(float(entry_row["mid_c"]), balance - pnl_dollars, position_size_lots, spec)
        trade_rows.append(
            {
                "timestamp_utc": str(entry_row["timestamp_utc"]),
                "exit_timestamp_utc": str(exit_row["timestamp_utc"]),
                "split": _split_label(entry_index, train_cutoff, validation_cutoff),
                "side": "long" if signal > 0 else "short",
                "entry_price": float(entry_row["mid_c"]),
                "exit_price": float(exit_row["mid_c"]),
                "pnl_pips": float(net_pips),
                "pnl_dollars": float(pnl_dollars),
                "position_size_lots": float(position_size_lots),
                "balance_after": float(balance),
                "margin_utilization_pct": float(margin_utilization_pct),
                "session_bucket": _session_bucket(int(entry_row["hour"])),
                "volatility_bucket": _volatility_bucket(float(entry_row["volatility_20"])),
                "context_bucket": _context_bucket(float(entry_row["zscore_10"]), float(entry_row["momentum_12"])),
                "exit_reason": exit_reason,
                "spread_cost_pips": float(spread_cost_pips),
                "slippage_cost_pips": float(slippage_cost_pips),
                "delay_cost_pips": float(delay_cost_pips),
                "commission_cost_pips": float(commission_cost_pips),
                "commission_cost_usd": float(commission_cost_usd),
                "total_cost_pips": float(spread_cost_pips + slippage_cost_pips + delay_cost_pips + commission_cost_pips),
                "fill_delay_ms": int(spec.cost_model.fill_delay_ms),
                "broker_fee_model": spec.cost_model.broker_fee_model,
            }
        )
        if spec.risk_policy.max_open_positions <= 1:
            next_available_index = exit_index + 1
    trade_ledger = pd.DataFrame.from_records(trade_rows)
    if trade_ledger.empty:
        trade_ledger = pd.DataFrame(columns=TRADE_LEDGER_COLUMNS)
    candidate_dir = settings.paths().reports_dir / spec.candidate_id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    if output_prefix:
        trade_ledger_path = candidate_dir / f"{output_prefix}_trade_ledger.csv"
        summary_path = candidate_dir / f"{output_prefix}_summary.json"
        artifact_references = {}
    else:
        trade_ledger_path = candidate_dir / "trade_ledger.csv"
        summary_path = candidate_dir / "backtest_summary.json"
        data_provenance = build_data_provenance(spec, settings, stage="backtested")
        environment_snapshot = build_environment_snapshot(settings, candidate_id=spec.candidate_id)
        artifact_references = {
            "dataset_snapshot": data_provenance.dataset_snapshot.model_dump(mode="json"),
            "feature_build": data_provenance.feature_build.model_dump(mode="json"),
            "data_provenance": {
                "provenance_id": data_provenance.provenance_id,
                "report_path": str(data_provenance.report_path),
                "execution_cost_model_version": data_provenance.execution_cost_model_version,
                "risk_envelope_version": data_provenance.risk_envelope_version,
                "strategy_spec_version": data_provenance.strategy_spec_version,
            },
            "environment_snapshot": {
                "environment_id": environment_snapshot.environment_id,
                "report_path": str(environment_snapshot.report_path),
                "python_version": environment_snapshot.python_version,
                "dependency_snapshot_hash": environment_snapshot.dependency_snapshot_hash,
            },
            "execution_cost_model": spec.execution_cost_model.model_dump(mode="json"),
            "risk_envelope": spec.risk_envelope.model_dump(mode="json"),
        }
    trade_ledger.to_csv(trade_ledger_path, index=False)

    summary = _summarize_backtest(
        trade_ledger,
        spec.validation_profile,
        initial_balance=spec.account_model.initial_balance,
        news_blocked_entries=news_blocked_entries,
        leverage=spec.account_model.leverage,
    )
    summary.update(
        {
            "candidate_id": spec.candidate_id,
            "entry_style": spec.entry_style,
            "spread_multiplier": spec.cost_model.spread_multiplier,
            "slippage_pips": spec.cost_model.slippage_pips,
            "fill_delay_ms": spec.cost_model.fill_delay_ms,
            "commission_per_standard_lot_usd": spec.cost_model.commission_per_standard_lot_usd,
            "broker_fee_model": spec.cost_model.broker_fee_model,
            "spec_path": str(candidate_dir / "strategy_spec.json"),
            "trade_ledger_path": str(trade_ledger_path),
            "summary_path": str(summary_path),
            "artifact_references": artifact_references,
        }
    )
    write_json(summary_path, summary)
    if output_prefix is None:
        append_trial_entry(
            settings,
            candidate_id=spec.candidate_id,
            family=spec.family,
            stage="backtested",
            artifact_paths={
                "backtest_summary_path": str(summary_path),
                "trade_ledger_path": str(trade_ledger_path),
                "data_provenance_path": str(data_provenance.report_path),
                "environment_snapshot_path": str(environment_snapshot.report_path),
            },
            provenance_id=data_provenance.provenance_id,
            environment_snapshot_id=environment_snapshot.environment_id,
            gate_outcomes={
                "trade_count": summary["trade_count"],
                "out_of_sample_profit_factor": summary["out_of_sample_profit_factor"],
                "expectancy_pips": summary["expectancy_pips"],
            },
        )
    return BacktestArtifact(
        candidate_id=spec.candidate_id,
        spec_path=Path(summary["spec_path"]),
        trade_ledger_path=trade_ledger_path,
        summary_path=summary_path,
        trade_count=summary["trade_count"],
        win_rate=summary["win_rate"],
        profit_factor=summary["profit_factor"],
        expectancy_pips=summary["expectancy_pips"],
        max_drawdown_pct=summary["max_drawdown_pct"],
        out_of_sample_profit_factor=summary["out_of_sample_profit_factor"],
        split_breakdown=summary["split_breakdown"],
        regime_breakdown=summary["regime_breakdown"],
        walk_forward_summary=summary["walk_forward_summary"],
        failure_attribution=summary["failure_attribution"],
        account_metrics=summary["account_metrics"],
        artifact_references=summary["artifact_references"],
    )


def run_stress_test(spec: StrategySpec, settings: Settings) -> StressTestReport:
    base_artifact = run_backtest(spec, settings, output_prefix="stress_base")
    spread_spec = spec.model_copy(
        update={
            "cost_model": spec.cost_model.model_copy(
                update={"spread_multiplier": spec.validation_profile.stress_spread_multiplier}
            )
        }
    )
    spread_artifact = run_backtest(spread_spec, settings, output_prefix="stress_spread")
    slippage_spec = spec.model_copy(
        update={
            "cost_model": spec.cost_model.model_copy(
                update={
                    "spread_multiplier": spec.validation_profile.stress_spread_multiplier,
                    "slippage_pips": spec.validation_profile.stress_slippage_pips,
                }
            )
        }
    )
    slippage_artifact = run_backtest(slippage_spec, settings, output_prefix="stress_spread_slippage")
    delay_spec = spec.model_copy(
        update={
            "cost_model": spec.cost_model.model_copy(
                update={
                    "spread_multiplier": spec.validation_profile.stress_spread_multiplier,
                    "slippage_pips": spec.validation_profile.stress_slippage_pips,
                    "fill_delay_ms": max(spec.validation_profile.stress_fill_delay_ms, spec.cost_model.fill_delay_ms),
                }
            )
        }
    )
    delay_artifact = run_backtest(delay_spec, settings, output_prefix="stress_spread_slippage_delay")
    scenarios = [
        StressScenarioResult(
            name="spread_only",
            spread_multiplier=spread_spec.cost_model.spread_multiplier,
            slippage_pips=spread_spec.cost_model.slippage_pips,
            fill_delay_ms=spread_spec.cost_model.fill_delay_ms,
            commission_per_standard_lot_usd=spread_spec.cost_model.commission_per_standard_lot_usd,
            profit_factor=spread_artifact.profit_factor,
            expectancy_pips=spread_artifact.expectancy_pips,
        ),
        StressScenarioResult(
            name="spread_plus_slippage",
            spread_multiplier=slippage_spec.cost_model.spread_multiplier,
            slippage_pips=slippage_spec.cost_model.slippage_pips,
            fill_delay_ms=slippage_spec.cost_model.fill_delay_ms,
            commission_per_standard_lot_usd=slippage_spec.cost_model.commission_per_standard_lot_usd,
            profit_factor=slippage_artifact.profit_factor,
            expectancy_pips=slippage_artifact.expectancy_pips,
        ),
        StressScenarioResult(
            name="spread_slippage_delay",
            spread_multiplier=delay_spec.cost_model.spread_multiplier,
            slippage_pips=delay_spec.cost_model.slippage_pips,
            fill_delay_ms=delay_spec.cost_model.fill_delay_ms,
            commission_per_standard_lot_usd=delay_spec.cost_model.commission_per_standard_lot_usd,
            profit_factor=delay_artifact.profit_factor,
            expectancy_pips=delay_artifact.expectancy_pips,
        ),
    ]
    worst = min(scenarios, key=lambda item: item.profit_factor)
    report = StressTestReport(
        candidate_id=spec.candidate_id,
        base_profit_factor=base_artifact.profit_factor,
        stressed_profit_factor=worst.profit_factor,
        spread_multiplier=worst.spread_multiplier,
        slippage_pips=worst.slippage_pips,
        fill_delay_ms=worst.fill_delay_ms,
        commission_per_standard_lot_usd=worst.commission_per_standard_lot_usd,
        passed=worst.profit_factor >= spec.validation_profile.stress_profit_factor_floor,
        scenarios=scenarios,
        artifact_references={
            "dataset_snapshot": base_artifact.artifact_references.get("dataset_snapshot", {}),
            "feature_build": base_artifact.artifact_references.get("feature_build", {}),
            "data_provenance": base_artifact.artifact_references.get("data_provenance", {}),
            "environment_snapshot": base_artifact.artifact_references.get("environment_snapshot", {}),
            "execution_cost_model": spec.execution_cost_model.model_dump(mode="json"),
            "risk_envelope": spec.risk_envelope.model_dump(mode="json"),
        },
        report_path=settings.paths().reports_dir / spec.candidate_id / "stress_test.json",
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    append_trial_entry(
        settings,
        candidate_id=spec.candidate_id,
        family=spec.family,
        stage="stress_test",
        artifact_paths={"stress_report_path": str(report.report_path)},
        gate_outcomes={"stressed_profit_factor": report.stressed_profit_factor, "stress_passed": report.passed},
    )
    return report


def _generate_signal(row: pd.Series, spec: StrategySpec) -> int:
    if not _passes_common_filters(row, spec):
        return 0
    if spec.entry_style == "mean_reversion_pullback":
        if row["zscore_10"] <= -abs(spec.signal_threshold):
            if _filter_enabled(spec, "require_reversal_ret_1") and row["ret_1"] <= 0:
                return 0
            if _filter_enabled(spec, "require_reversal_momentum") and row["momentum_12"] >= 0:
                return 0
            return 1
        if row["zscore_10"] >= abs(spec.signal_threshold):
            if _filter_enabled(spec, "require_reversal_ret_1") and row["ret_1"] >= 0:
                return 0
            if _filter_enabled(spec, "require_reversal_momentum") and row["momentum_12"] <= 0:
                return 0
            return -1
        return 0
    if spec.entry_style == "session_breakout":
        breakout_floor = _filter_float(spec, "breakout_zscore_floor")
        ret_5_floor = _filter_float(spec, "ret_5_floor")
        if row["momentum_12"] >= spec.signal_threshold:
            if _filter_enabled(spec, "require_ret_5_alignment") and row["ret_5"] <= 0:
                return 0
            if ret_5_floor is not None and row["ret_5"] < ret_5_floor:
                return 0
            if _filter_enabled(spec, "require_mean_location_alignment") and row["mid_c"] <= row["rolling_mean_10"]:
                return 0
            if breakout_floor is not None and row["zscore_10"] < breakout_floor:
                return 0
            return 1
        if row["momentum_12"] <= -spec.signal_threshold:
            if _filter_enabled(spec, "require_ret_5_alignment") and row["ret_5"] >= 0:
                return 0
            if ret_5_floor is not None and row["ret_5"] > -ret_5_floor:
                return 0
            if _filter_enabled(spec, "require_mean_location_alignment") and row["mid_c"] >= row["rolling_mean_10"]:
                return 0
            if breakout_floor is not None and row["zscore_10"] > -breakout_floor:
                return 0
            return -1
        return 0
    if spec.entry_style == "volatility_breakout":
        breakout_floor = _filter_float(spec, "breakout_zscore_floor") or 0.55
        if row["momentum_12"] >= spec.signal_threshold:
            if _filter_enabled(spec, "require_ret_5_alignment") and row["ret_5"] <= 0:
                return 0
            if _filter_enabled(spec, "require_mean_location_alignment") and row["mid_c"] <= row["rolling_mean_10"]:
                return 0
            if row["zscore_10"] < breakout_floor:
                return 0
            return 1
        if row["momentum_12"] <= -spec.signal_threshold:
            if _filter_enabled(spec, "require_ret_5_alignment") and row["ret_5"] >= 0:
                return 0
            if _filter_enabled(spec, "require_mean_location_alignment") and row["mid_c"] >= row["rolling_mean_10"]:
                return 0
            if row["zscore_10"] > -breakout_floor:
                return 0
            return -1
        return 0
    if spec.entry_style == "volatility_expansion":
        breakout_floor = _filter_float(spec, "breakout_zscore_floor") or max(spec.signal_threshold * 0.85, 0.65)
        minimum_ret_5 = _filter_float(spec, "ret_5_floor") or 0.00006
        minimum_volatility = max(_filter_float(spec, "min_volatility_20") or 0.0, 0.00003)
        if row["volatility_20"] < minimum_volatility:
            return 0
        if row["momentum_12"] >= spec.signal_threshold and row["zscore_10"] >= breakout_floor:
            if row["ret_5"] < minimum_ret_5:
                return 0
            if row["ret_1"] <= 0:
                return 0
            return 1
        if row["momentum_12"] <= -spec.signal_threshold and row["zscore_10"] <= -breakout_floor:
            if row["ret_5"] > -minimum_ret_5:
                return 0
            if row["ret_1"] >= 0:
                return 0
            return -1
        return 0
    if spec.entry_style in {"volatility_retest_breakout", "overlap_event_retest_breakout"}:
        breakout_floor = _filter_float(spec, "breakout_zscore_floor") or 0.55
        trend_ret_5_min = _filter_float(spec, "trend_ret_5_min") or 0.00008
        retest_limit = _filter_float(spec, "retest_zscore_limit") or 0.35
        retest_position_floor = _filter_float(spec, "retest_range_position_floor") or 0.55
        minimum_volatility = max(_filter_float(spec, "min_volatility_20") or 0.0, 0.00004)
        momentum_floor = max(spec.signal_threshold * 0.65, 0.55)
        if row["volatility_20"] < minimum_volatility:
            return 0
        if row["momentum_12"] >= momentum_floor and row["ret_5"] >= trend_ret_5_min:
            if not (-retest_limit <= row["zscore_10"] <= breakout_floor):
                return 0
            if row["range_position_10"] < retest_position_floor:
                return 0
            if _filter_enabled(spec, "require_mean_location_alignment") and row["mid_c"] <= row["rolling_mean_10"]:
                return 0
            if _filter_enabled(spec, "require_recovery_ret_1") and row["ret_1"] <= 0:
                return 0
            return 1
        if row["momentum_12"] <= -momentum_floor and row["ret_5"] <= -trend_ret_5_min:
            if not (-breakout_floor <= row["zscore_10"] <= retest_limit):
                return 0
            if row["range_position_10"] > (1 - retest_position_floor):
                return 0
            if _filter_enabled(spec, "require_mean_location_alignment") and row["mid_c"] >= row["rolling_mean_10"]:
                return 0
            if _filter_enabled(spec, "require_recovery_ret_1") and row["ret_1"] >= 0:
                return 0
            return -1
        return 0
    if spec.entry_style == "overlap_persistence_band":
        trend_ret_5_min = _filter_float(spec, "trend_ret_5_min") or 0.00008
        continuation_floor = _filter_float(spec, "continuation_zscore_floor") or 0.08
        continuation_ceiling = _filter_float(spec, "continuation_zscore_ceiling") or 0.72
        continuation_position_floor = _filter_float(spec, "continuation_range_position_floor") or 0.60
        minimum_volatility = max(_filter_float(spec, "min_volatility_20") or 0.0, 0.00005)
        momentum_floor = max(spec.signal_threshold * 0.70, 0.60)
        if row["volatility_20"] < minimum_volatility:
            return 0
        if row["momentum_12"] >= momentum_floor and row["ret_5"] >= trend_ret_5_min:
            if not (continuation_floor <= row["zscore_10"] <= continuation_ceiling):
                return 0
            if row["range_position_10"] < continuation_position_floor:
                return 0
            if _filter_enabled(spec, "require_mean_location_alignment") and row["mid_c"] <= row["rolling_mean_10"]:
                return 0
            if _filter_enabled(spec, "require_recovery_ret_1") and row["ret_1"] <= 0:
                return 0
            return 1
        if row["momentum_12"] <= -momentum_floor and row["ret_5"] <= -trend_ret_5_min:
            if not (-continuation_ceiling <= row["zscore_10"] <= -continuation_floor):
                return 0
            if row["range_position_10"] > (1 - continuation_position_floor):
                return 0
            if _filter_enabled(spec, "require_mean_location_alignment") and row["mid_c"] >= row["rolling_mean_10"]:
                return 0
            if _filter_enabled(spec, "require_recovery_ret_1") and row["ret_1"] >= 0:
                return 0
            return -1
        return 0
    if spec.entry_style == "session_momentum_band":
        trend_ret_5_min = _filter_float(spec, "trend_ret_5_min") or 0.00007
        continuation_floor = _filter_float(spec, "continuation_zscore_floor") or 0.20
        continuation_ceiling = _filter_float(spec, "continuation_zscore_ceiling") or 1.05
        continuation_position_floor = _filter_float(spec, "continuation_range_position_floor") or 0.64
        minimum_volatility = max(_filter_float(spec, "min_volatility_20") or 0.0, 0.00004)
        momentum_floor = max(spec.signal_threshold, 0.75)
        if row["volatility_20"] < minimum_volatility:
            return 0
        if row["momentum_12"] >= momentum_floor and row["ret_5"] >= trend_ret_5_min:
            if not (continuation_floor <= row["zscore_10"] <= continuation_ceiling):
                return 0
            if row["range_position_10"] < continuation_position_floor:
                return 0
            if _filter_enabled(spec, "require_mean_location_alignment") and row["mid_c"] <= row["rolling_mean_10"]:
                return 0
            if _filter_enabled(spec, "require_ret_1_confirmation") and row["ret_1"] <= 0:
                return 0
            return 1
        if row["momentum_12"] <= -momentum_floor and row["ret_5"] <= -trend_ret_5_min:
            if not (-continuation_ceiling <= row["zscore_10"] <= -continuation_floor):
                return 0
            if row["range_position_10"] > (1 - continuation_position_floor):
                return 0
            if _filter_enabled(spec, "require_mean_location_alignment") and row["mid_c"] >= row["rolling_mean_10"]:
                return 0
            if _filter_enabled(spec, "require_ret_1_confirmation") and row["ret_1"] >= 0:
                return 0
            return -1
        return 0
    if spec.entry_style == "overlap_persistence_retest":
        breakout_floor = _filter_float(spec, "breakout_zscore_floor") or 0.57
        trend_ret_5_min = _filter_float(spec, "trend_ret_5_min") or 0.00009
        retest_limit = _filter_float(spec, "retest_zscore_limit") or 0.32
        retest_position_floor = _filter_float(spec, "retest_range_position_floor") or 0.58
        minimum_volatility = max(_filter_float(spec, "min_volatility_20") or 0.0, 0.00006)
        momentum_floor = max(spec.signal_threshold * 0.70, 0.60)
        if row["volatility_20"] < minimum_volatility:
            return 0
        if row["momentum_12"] >= momentum_floor and row["ret_5"] >= trend_ret_5_min:
            if not (-retest_limit <= row["zscore_10"] <= breakout_floor):
                return 0
            if row["range_position_10"] < retest_position_floor:
                return 0
            if _filter_enabled(spec, "require_mean_location_alignment") and row["mid_c"] <= row["rolling_mean_10"]:
                return 0
            if _filter_enabled(spec, "require_recovery_ret_1") and row["ret_1"] <= 0:
                return 0
            return 1
        if row["momentum_12"] <= -momentum_floor and row["ret_5"] <= -trend_ret_5_min:
            if not (-breakout_floor <= row["zscore_10"] <= retest_limit):
                return 0
            if row["range_position_10"] > (1 - retest_position_floor):
                return 0
            if _filter_enabled(spec, "require_mean_location_alignment") and row["mid_c"] >= row["rolling_mean_10"]:
                return 0
            if _filter_enabled(spec, "require_recovery_ret_1") and row["ret_1"] >= 0:
                return 0
            return -1
        return 0
    if spec.entry_style == "high_vol_overlap_persistence_retest":
        breakout_floor = _filter_float(spec, "breakout_zscore_floor") or 0.57
        trend_ret_5_min = _filter_float(spec, "trend_ret_5_min") or 0.00009
        retest_limit = _filter_float(spec, "retest_zscore_limit") or 0.32
        retest_position_floor = _filter_float(spec, "retest_range_position_floor") or 0.58
        minimum_volatility = max(_filter_float(spec, "min_volatility_20") or 0.0, 0.00006)
        momentum_floor = max(spec.signal_threshold * 0.70, 0.60)
        if row["volatility_20"] < minimum_volatility:
            return 0
        if _volatility_bucket(float(row["volatility_20"])) != "high":
            return 0
        if row["momentum_12"] >= momentum_floor and row["ret_5"] >= trend_ret_5_min:
            if not (-retest_limit <= row["zscore_10"] <= breakout_floor):
                return 0
            if row["range_position_10"] < retest_position_floor:
                return 0
            if _filter_enabled(spec, "require_mean_location_alignment") and row["mid_c"] <= row["rolling_mean_10"]:
                return 0
            if _filter_enabled(spec, "require_recovery_ret_1") and row["ret_1"] <= 0:
                return 0
            return 1
        if row["momentum_12"] <= -momentum_floor and row["ret_5"] <= -trend_ret_5_min:
            if not (-breakout_floor <= row["zscore_10"] <= retest_limit):
                return 0
            if row["range_position_10"] > (1 - retest_position_floor):
                return 0
            if _filter_enabled(spec, "require_mean_location_alignment") and row["mid_c"] >= row["rolling_mean_10"]:
                return 0
            if _filter_enabled(spec, "require_recovery_ret_1") and row["ret_1"] >= 0:
                return 0
            return -1
        return 0
    if spec.entry_style == "pullback_continuation":
        trend_ret_5_min = _filter_float(spec, "trend_ret_5_min") or 0.00008
        pullback_limit = _filter_float(spec, "pullback_zscore_limit") or 0.45
        require_recovery = _filter_enabled(spec, "require_recovery_ret_1")
        require_mean_location_alignment = _filter_enabled(spec, "require_mean_location_alignment")
        pullback_range_position_floor = _filter_float(spec, "pullback_range_position_floor")
        recovery_zscore_floor = _filter_float(spec, "recovery_zscore_floor")
        if row["momentum_12"] >= spec.signal_threshold and row["ret_5"] >= trend_ret_5_min:
            if not (-pullback_limit <= row["zscore_10"] <= 0.15):
                return 0
            if require_mean_location_alignment and row["mid_c"] < row["rolling_mean_10"]:
                return 0
            if pullback_range_position_floor is not None and row["range_position_10"] < pullback_range_position_floor:
                return 0
            if recovery_zscore_floor is not None and row["zscore_10"] < recovery_zscore_floor:
                return 0
            if require_recovery and row["ret_1"] <= 0:
                return 0
            return 1
        if row["momentum_12"] <= -spec.signal_threshold and row["ret_5"] <= -trend_ret_5_min:
            if not (-0.15 <= row["zscore_10"] <= pullback_limit):
                return 0
            if require_mean_location_alignment and row["mid_c"] > row["rolling_mean_10"]:
                return 0
            if pullback_range_position_floor is not None and row["range_position_10"] > (1 - pullback_range_position_floor):
                return 0
            if recovery_zscore_floor is not None and row["zscore_10"] > -recovery_zscore_floor:
                return 0
            if require_recovery and row["ret_1"] >= 0:
                return 0
            return -1
        return 0
    if spec.entry_style == "trend_pullback_retest":
        trend_ret_5_min = _filter_float(spec, "trend_ret_5_min") or 0.00005
        pullback_limit = _filter_float(spec, "pullback_zscore_limit") or 0.55
        long_momentum_floor = spec.signal_threshold * 0.5
        if row["ret_5"] >= trend_ret_5_min and row["ret_1"] > 0 and -pullback_limit <= row["zscore_10"] <= 0.35:
            if row["momentum_12"] < long_momentum_floor:
                return 0
            return 1
        if row["ret_5"] <= -trend_ret_5_min and row["ret_1"] < 0 and -0.35 <= row["zscore_10"] <= pullback_limit:
            if row["momentum_12"] > -long_momentum_floor:
                return 0
            return -1
        return 0
    if spec.entry_style == "failed_break_fade":
        fade_ret_5_floor = _filter_float(spec, "fade_ret_5_floor") or 0.00005
        fade_momentum_ceiling = _filter_float(spec, "fade_momentum_ceiling") or 3.2
        if row["zscore_10"] <= -abs(spec.signal_threshold):
            if abs(row["momentum_12"]) > fade_momentum_ceiling:
                return 0
            if row["ret_5"] >= -fade_ret_5_floor:
                return 0
            if _filter_enabled(spec, "require_reversal_ret_1") and row["ret_1"] <= 0:
                return 0
            return 1
        if row["zscore_10"] >= abs(spec.signal_threshold):
            if abs(row["momentum_12"]) > fade_momentum_ceiling:
                return 0
            if row["ret_5"] <= fade_ret_5_floor:
                return 0
            if _filter_enabled(spec, "require_reversal_ret_1") and row["ret_1"] >= 0:
                return 0
            return -1
        return 0
    if spec.entry_style == "session_extreme_reversion":
        extreme_floor = max(abs(spec.signal_threshold), 0.65)
        fade_ret_5_floor = _filter_float(spec, "fade_ret_5_floor") or 0.00004
        fade_momentum_ceiling = _filter_float(spec, "fade_momentum_ceiling") or 4.0
        if row["zscore_10"] <= -extreme_floor:
            if row["ret_5"] > -fade_ret_5_floor:
                return 0
            if row["ret_1"] <= 0:
                return 0
            if abs(row["momentum_12"]) > fade_momentum_ceiling:
                return 0
            return 1
        if row["zscore_10"] >= extreme_floor:
            if row["ret_5"] < fade_ret_5_floor:
                return 0
            if row["ret_1"] >= 0:
                return 0
            if abs(row["momentum_12"]) > fade_momentum_ceiling:
                return 0
            return -1
        return 0
    if spec.entry_style == "compression_reversion":
        compression_ceiling = _filter_float(spec, "max_range_width_10_pips") or 8.0
        extreme_floor = max(abs(spec.signal_threshold), 0.9)
        reclaim_floor = _filter_float(spec, "reclaim_range_position_floor") or 0.18
        reclaim_ceiling = _filter_float(spec, "reclaim_range_position_ceiling") or 0.45
        momentum_ceiling = _filter_float(spec, "reclaim_momentum_ceiling") or 3.6
        if row["range_width_10_pips"] > compression_ceiling:
            return 0
        if row["zscore_10"] <= -extreme_floor:
            if not (reclaim_floor <= row["range_position_10"] <= reclaim_ceiling):
                return 0
            if _filter_enabled(spec, "require_reversal_ret_1") and row["ret_1"] <= 0:
                return 0
            if abs(row["momentum_12"]) > momentum_ceiling:
                return 0
            return 1
        if row["zscore_10"] >= extreme_floor:
            if not ((1 - reclaim_ceiling) <= row["range_position_10"] <= (1 - reclaim_floor)):
                return 0
            if _filter_enabled(spec, "require_reversal_ret_1") and row["ret_1"] >= 0:
                return 0
            if abs(row["momentum_12"]) > momentum_ceiling:
                return 0
            return -1
        return 0
    if spec.entry_style == "drift_reclaim":
        extension_floor = max(abs(spec.signal_threshold) * 0.95, 0.85)
        drift_floor = 0.00005
        reclaim_floor = 0.30
        reclaim_ceiling = 0.58
        momentum_ceiling = 5.0
        if row["zscore_10"] <= -extension_floor:
            if row["ret_5"] > -drift_floor:
                return 0
            if not (reclaim_floor <= row["range_position_10"] <= reclaim_ceiling):
                return 0
            if row["ret_1"] <= 0:
                return 0
            if abs(row["momentum_12"]) > momentum_ceiling:
                return 0
            return 1
        if row["zscore_10"] >= extension_floor:
            if row["ret_5"] < drift_floor:
                return 0
            if not ((1 - reclaim_ceiling) <= row["range_position_10"] <= (1 - reclaim_floor)):
                return 0
            if row["ret_1"] >= 0:
                return 0
            if abs(row["momentum_12"]) > momentum_ceiling:
                return 0
            return -1
        return 0
    if spec.entry_style == "balance_area_breakout":
        compression_ceiling = 8.5
        breakout_floor = max(spec.signal_threshold * 0.7, 0.45)
        range_position_floor = 0.60
        momentum_floor = spec.signal_threshold * 0.8
        if row["range_width_10_pips"] > compression_ceiling:
            return 0
        if row["momentum_12"] >= momentum_floor:
            if row["zscore_10"] < breakout_floor:
                return 0
            if row["range_position_10"] < range_position_floor:
                return 0
            if row["ret_5"] <= 0 or row["ret_1"] <= 0:
                return 0
            return 1
        if row["momentum_12"] <= -momentum_floor:
            if row["zscore_10"] > -breakout_floor:
                return 0
            if row["range_position_10"] > (1 - range_position_floor):
                return 0
            if row["ret_5"] >= 0 or row["ret_1"] >= 0:
                return 0
            return -1
        return 0
    if spec.entry_style == "compression_breakout":
        breakout_floor = _filter_float(spec, "breakout_zscore_floor") or 0.45
        compression_ceiling = _filter_float(spec, "max_range_width_10_pips") or 9.0
        range_position_floor = _filter_float(spec, "compression_range_position_floor") or 0.65
        if row["range_width_10_pips"] > compression_ceiling:
            return 0
        if row["momentum_12"] >= spec.signal_threshold:
            if row["zscore_10"] < breakout_floor:
                return 0
            if row["range_position_10"] < range_position_floor:
                return 0
            if _filter_enabled(spec, "require_ret_1_confirmation") and row["ret_1"] <= 0:
                return 0
            return 1
        if row["momentum_12"] <= -spec.signal_threshold:
            if row["zscore_10"] > -breakout_floor:
                return 0
            if row["range_position_10"] > (1 - range_position_floor):
                return 0
            if _filter_enabled(spec, "require_ret_1_confirmation") and row["ret_1"] >= 0:
                return 0
            return -1
        return 0
    if spec.entry_style == "compression_retest_breakout":
        compression_ceiling = _filter_float(spec, "max_range_width_10_pips") or 8.5
        breakout_floor = _filter_float(spec, "breakout_zscore_floor") or 0.40
        trend_ret_5_min = _filter_float(spec, "trend_ret_5_min") or 0.00008
        retest_limit = _filter_float(spec, "retest_zscore_limit") or 0.30
        retest_position_floor = _filter_float(spec, "retest_range_position_floor") or 0.56
        momentum_floor = max(spec.signal_threshold * 0.7, 0.55)
        if row["range_width_10_pips"] > compression_ceiling:
            return 0
        if row["momentum_12"] >= momentum_floor and row["ret_5"] >= trend_ret_5_min:
            if not (-retest_limit <= row["zscore_10"] <= breakout_floor):
                return 0
            if row["range_position_10"] < retest_position_floor:
                return 0
            if row["mid_c"] <= row["rolling_mean_10"]:
                return 0
            if _filter_enabled(spec, "require_recovery_ret_1") and row["ret_1"] <= 0:
                return 0
            return 1
        if row["momentum_12"] <= -momentum_floor and row["ret_5"] <= -trend_ret_5_min:
            if not (-breakout_floor <= row["zscore_10"] <= retest_limit):
                return 0
            if row["range_position_10"] > (1 - retest_position_floor):
                return 0
            if row["mid_c"] >= row["rolling_mean_10"]:
                return 0
            if _filter_enabled(spec, "require_recovery_ret_1") and row["ret_1"] >= 0:
                return 0
            return -1
        return 0
    if spec.entry_style == "range_reclaim":
        extension_floor = _filter_float(spec, "extension_zscore_floor") or 1.05
        reclaim_floor = _filter_float(spec, "reclaim_range_position_floor") or 0.12
        reclaim_ceiling = _filter_float(spec, "reclaim_range_position_ceiling") or 0.42
        momentum_ceiling = _filter_float(spec, "reclaim_momentum_ceiling") or 4.0
        if row["zscore_10"] <= -extension_floor:
            if abs(row["momentum_12"]) > momentum_ceiling:
                return 0
            if not (reclaim_floor <= row["range_position_10"] <= reclaim_ceiling):
                return 0
            if _filter_enabled(spec, "require_reclaim_ret_1") and row["ret_1"] <= 0:
                return 0
            return 1
        if row["zscore_10"] >= extension_floor:
            if abs(row["momentum_12"]) > momentum_ceiling:
                return 0
            if not ((1 - reclaim_ceiling) <= row["range_position_10"] <= (1 - reclaim_floor)):
                return 0
            if _filter_enabled(spec, "require_reclaim_ret_1") and row["ret_1"] >= 0:
                return 0
            return -1
        return 0
    if spec.entry_style == "trend_retest":
        trend_ret_5_min = _filter_float(spec, "trend_ret_5_min") or 0.00012
        retest_limit = _filter_float(spec, "retest_zscore_limit") or 0.35
        retest_position_floor = _filter_float(spec, "retest_range_position_floor") or 0.52
        if row["momentum_12"] >= spec.signal_threshold and row["ret_5"] >= trend_ret_5_min:
            if not (-retest_limit <= row["zscore_10"] <= 0.25):
                return 0
            if row["range_position_10"] < retest_position_floor:
                return 0
            if _filter_enabled(spec, "require_recovery_ret_1") and row["ret_1"] <= 0:
                return 0
            return 1
        if row["momentum_12"] <= -spec.signal_threshold and row["ret_5"] <= -trend_ret_5_min:
            if not (-0.25 <= row["zscore_10"] <= retest_limit):
                return 0
            if row["range_position_10"] > (1 - retest_position_floor):
                return 0
            if _filter_enabled(spec, "require_recovery_ret_1") and row["ret_1"] >= 0:
                return 0
            return -1
        return 0
    return 0


def _summarize_backtest(
    trade_ledger: pd.DataFrame,
    validation_profile,
    *,
    initial_balance: float,
    news_blocked_entries: int,
    leverage: float,
) -> dict:
    if trade_ledger.empty:
        return {
            "trade_count": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy_pips": 0.0,
            "max_drawdown_pct": 0.0,
            "out_of_sample_profit_factor": 0.0,
            "split_breakdown": {},
            "regime_breakdown": {},
            "walk_forward_summary": [],
            "failure_attribution": {},
            "account_metrics": {
                "initial_balance": initial_balance,
                "final_balance": initial_balance,
                "total_return_pct": 0.0,
                "max_daily_loss_pct": 0.0,
                "average_position_size_lots": 0.0,
                "max_margin_utilization_pct": 0.0,
                "average_total_cost_pips": 0.0,
                "total_commission_usd": 0.0,
                "average_fill_delay_ms": 0.0,
                "news_blocked_entries": news_blocked_entries,
                "configured_leverage": leverage,
                "trading_days_observed": 0,
            },
        }
    pnl = trade_ledger["pnl_pips"]
    gross_profit = pnl[pnl > 0].sum()
    gross_loss = abs(pnl[pnl < 0].sum()) or 1e-9
    balance_curve = trade_ledger["balance_after"]
    running_peak = balance_curve.cummax()
    drawdown_pct = ((running_peak - balance_curve) / running_peak.replace(0, 1e-9)) * 100
    oos = trade_ledger[trade_ledger["split"] == "out_of_sample"]
    oos_profit = oos["pnl_pips"][oos["pnl_pips"] > 0].sum()
    oos_loss = abs(oos["pnl_pips"][oos["pnl_pips"] < 0].sum()) or 1e-9
    daily_pnl = _daily_pnl(trade_ledger)
    worst_daily_loss = abs(min(daily_pnl.min(), 0.0)) if not daily_pnl.empty else 0.0
    final_balance = float(balance_curve.iloc[-1]) if not balance_curve.empty else initial_balance
    return {
        "trade_count": int(len(trade_ledger)),
        "win_rate": float((pnl > 0).mean()),
        "profit_factor": float(gross_profit / gross_loss),
        "expectancy_pips": float(pnl.mean()),
        "max_drawdown_pct": float(drawdown_pct.max() if not drawdown_pct.empty else 0.0),
        "out_of_sample_profit_factor": float(oos_profit / oos_loss),
        "split_breakdown": {
            split: {
                "trade_count": int(len(group)),
                "profit_factor": float(_profit_factor(group["pnl_pips"])),
                "expectancy_pips": float(group["pnl_pips"].mean()),
            }
            for split, group in trade_ledger.groupby("split")
        },
        "regime_breakdown": {
            "session_bucket": _group_metrics(trade_ledger, "session_bucket"),
            "volatility_bucket": _group_metrics(trade_ledger, "volatility_bucket"),
            "context_bucket": _group_metrics(trade_ledger, "context_bucket"),
        },
        "walk_forward_summary": _walk_forward_summary(trade_ledger, validation_profile),
        "failure_attribution": {
            reason: int(count)
            for reason, count in trade_ledger["exit_reason"].value_counts().to_dict().items()
        },
        "account_metrics": {
            "initial_balance": initial_balance,
            "final_balance": final_balance,
            "total_return_pct": float(((final_balance - initial_balance) / initial_balance) * 100 if initial_balance else 0.0),
            "max_daily_loss_pct": float((worst_daily_loss / initial_balance) * 100 if initial_balance else 0.0),
            "average_position_size_lots": float(trade_ledger["position_size_lots"].mean()),
            "max_margin_utilization_pct": float(trade_ledger["margin_utilization_pct"].max()),
            "average_total_cost_pips": float(trade_ledger.get("total_cost_pips", pd.Series(dtype=float)).mean() if "total_cost_pips" in trade_ledger.columns else 0.0),
            "total_commission_usd": float(trade_ledger.get("commission_cost_usd", pd.Series(dtype=float)).sum() if "commission_cost_usd" in trade_ledger.columns else 0.0),
            "average_fill_delay_ms": float(trade_ledger.get("fill_delay_ms", pd.Series(dtype=float)).mean() if "fill_delay_ms" in trade_ledger.columns else 0.0),
            "news_blocked_entries": int(news_blocked_entries),
            "configured_leverage": float(leverage),
            "trading_days_observed": int(_daily_pnl(trade_ledger).shape[0]),
        },
    }


def _group_metrics(frame: pd.DataFrame, column: str) -> dict:
    return {
        label: {
            "trade_count": int(len(group)),
            "mean_pnl_pips": float(group["pnl_pips"].mean()),
            "profit_factor": float(_profit_factor(group["pnl_pips"])),
        }
        for label, group in frame.groupby(column)
    }


def _walk_forward_summary(frame: pd.DataFrame, validation_profile) -> list[dict]:
    if frame.empty:
        return []
    mode = getattr(validation_profile, "walk_forward_mode", "equal_trade_windows")
    if mode == "anchored_time_windows":
        summary = _anchored_time_walk_forward_summary(frame, validation_profile)
        if summary:
            return summary
    return _equal_trade_walk_forward_summary(frame, validation_profile)


def _equal_trade_walk_forward_summary(frame: pd.DataFrame, validation_profile) -> list[dict]:
    windows = max(int(getattr(validation_profile, "walk_forward_windows", 1) or 1), 1)
    window_size = max(math.floor(len(frame) / windows), 1)
    summary: list[dict] = []
    for window_index in range(windows):
        start = window_index * window_size
        end = len(frame) if window_index == windows - 1 else min((window_index + 1) * window_size, len(frame))
        chunk = frame.iloc[start:end].copy()
        summary.append(_walk_forward_window_summary(chunk, window_index=window_index + 1, validation_profile=validation_profile))
    return summary


def _anchored_time_walk_forward_summary(frame: pd.DataFrame, validation_profile) -> list[dict]:
    windows = max(int(getattr(validation_profile, "walk_forward_windows", 1) or 1), 1)
    ordered = frame.copy()
    ordered["exit_timestamp_utc"] = pd.to_datetime(ordered["exit_timestamp_utc"], utc=True, errors="coerce")
    ordered = ordered.dropna(subset=["exit_timestamp_utc"]).sort_values("exit_timestamp_utc").reset_index(drop=True)
    if ordered.empty:
        return []

    start = ordered["exit_timestamp_utc"].min().floor("D")
    end = ordered["exit_timestamp_utc"].max().ceil("D")
    if start >= end:
        return []

    window_span = (end - start) / windows
    summary: list[dict] = []
    for window_index in range(windows):
        window_start = start + (window_span * window_index)
        window_end = end if window_index == windows - 1 else start + (window_span * (window_index + 1))
        if window_index == windows - 1:
            chunk = ordered[(ordered["exit_timestamp_utc"] >= window_start) & (ordered["exit_timestamp_utc"] <= window_end)].copy()
        else:
            chunk = ordered[(ordered["exit_timestamp_utc"] >= window_start) & (ordered["exit_timestamp_utc"] < window_end)].copy()
        summary.append(
            _walk_forward_window_summary(
                chunk,
                window_index=window_index + 1,
                validation_profile=validation_profile,
                window_start=window_start,
                window_end=window_end,
                mode="anchored_time_windows",
            )
        )
    return summary


def _walk_forward_window_summary(
    chunk: pd.DataFrame,
    *,
    window_index: int,
    validation_profile,
    window_start: pd.Timestamp | None = None,
    window_end: pd.Timestamp | None = None,
    mode: str = "equal_trade_windows",
) -> dict:
    min_trades = int(getattr(validation_profile, "walk_forward_min_trades_per_window", 1) or 1)
    min_days = int(getattr(validation_profile, "walk_forward_min_window_days", 1) or 1)
    profit_factor_floor = float(getattr(validation_profile, "walk_forward_profit_factor_floor", 0.9) or 0.9)
    start_utc = _timestamp(window_start if window_start is not None else (pd.to_datetime(chunk["exit_timestamp_utc"], utc=True, errors="coerce").min() if not chunk.empty and "exit_timestamp_utc" in chunk.columns else None))
    end_utc = _timestamp(window_end if window_end is not None else (pd.to_datetime(chunk["exit_timestamp_utc"], utc=True, errors="coerce").max() if not chunk.empty and "exit_timestamp_utc" in chunk.columns else None))
    window_days = _window_day_span(window_start, window_end, chunk)
    trade_count = int(len(chunk))
    profit_factor = float(_profit_factor(chunk["pnl_pips"])) if trade_count else 0.0
    expectancy_pips = float(chunk["pnl_pips"].mean()) if trade_count else 0.0
    failure_reasons: list[str] = []
    if trade_count < min_trades:
        failure_reasons.append("insufficient_trades")
    if window_days < min_days:
        failure_reasons.append("insufficient_time_span")
    if profit_factor < profit_factor_floor:
        failure_reasons.append("profit_factor_below_floor")
    return {
        "window": window_index,
        "mode": mode,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "window_days": window_days,
        "trade_count": trade_count,
        "profit_factor": profit_factor,
        "expectancy_pips": expectancy_pips,
        "profit_factor_floor": profit_factor_floor,
        "min_trades_floor": min_trades,
        "min_window_days_floor": min_days,
        "passed": not failure_reasons,
        "failure_reasons": failure_reasons,
    }


def _window_day_span(
    window_start: pd.Timestamp | None,
    window_end: pd.Timestamp | None,
    chunk: pd.DataFrame,
) -> int:
    if window_start is not None and window_end is not None:
        duration = window_end - window_start
        return max(int(math.ceil(duration.total_seconds() / 86_400)), 1)
    if chunk.empty or "exit_timestamp_utc" not in chunk.columns:
        return 0
    timestamps = pd.to_datetime(chunk["exit_timestamp_utc"], utc=True, errors="coerce").dropna()
    if timestamps.empty:
        return 0
    duration = timestamps.max() - timestamps.min()
    return max(int(math.ceil(duration.total_seconds() / 86_400)), 1)


def _timestamp(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().astimezone(UTC).isoformat().replace("+00:00", "Z")
    try:
        timestamp = pd.Timestamp(value)
    except Exception:  # noqa: BLE001
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.to_pydatetime().astimezone(UTC).isoformat().replace("+00:00", "Z")


def _profit_factor(pnl: pd.Series) -> float:
    gross_profit = pnl[pnl > 0].sum()
    gross_loss = abs(pnl[pnl < 0].sum()) or 1e-9
    return float(gross_profit / gross_loss)


def _split_boundaries(length: int, split: tuple[float, float, float]) -> tuple[int, int]:
    train_cutoff = int(length * split[0])
    validation_cutoff = int(length * (split[0] + split[1]))
    return train_cutoff, validation_cutoff


def _split_label(index: int, train_cutoff: int, validation_cutoff: int) -> str:
    if index < train_cutoff:
        return "train"
    if index < validation_cutoff:
        return "validation"
    return "out_of_sample"


def _session_bucket(hour: int) -> str:
    if 0 <= hour < 7:
        return "asia"
    if 7 <= hour < 13:
        return "europe"
    if 13 <= hour < 17:
        return "overlap"
    return "us_late"


def _volatility_bucket(volatility: float) -> str:
    if volatility <= 0.00005:
        return "low"
    if volatility <= 0.00012:
        return "medium"
    return "high"


def _context_bucket(zscore: float, momentum: float) -> str:
    if abs(zscore) >= 1.2:
        return "mean_reversion_context"
    if abs(momentum) >= 0.8:
        return "trend_context"
    return "neutral_context"


def _filter_rules(spec: StrategySpec) -> dict[str, str]:
    return {item.name: item.rule for item in spec.filters}


def _filter_enabled(spec: StrategySpec, name: str) -> bool:
    return _filter_rules(spec).get(name, "").strip().lower() in {"1", "true", "yes", "on", "required"}


def _filter_value(spec: StrategySpec, name: str) -> str | None:
    raw = _filter_rules(spec).get(name)
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _filter_float(spec: StrategySpec, name: str) -> float | None:
    raw = _filter_rules(spec).get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _passes_common_filters(row: pd.Series, spec: StrategySpec) -> bool:
    max_spread = _filter_float(spec, "max_spread_pips")
    if max_spread is not None and float(row["spread_pips"]) > max_spread:
        return False
    max_spread_shock = _filter_float(spec, "max_spread_shock_20")
    if max_spread_shock is not None and float(row["spread_shock_20"]) > max_spread_shock:
        return False
    max_spread_to_range = _filter_float(spec, "max_spread_to_range_10")
    if max_spread_to_range is not None and float(row["spread_to_range_10"]) > max_spread_to_range:
        return False
    min_volatility = _filter_float(spec, "min_volatility_20")
    if min_volatility is not None and float(row["volatility_20"]) < min_volatility:
        return False
    min_volatility_5 = _filter_float(spec, "min_volatility_5")
    if min_volatility_5 is not None and float(row["volatility_5"]) < min_volatility_5:
        return False
    min_volatility_ratio = _filter_float(spec, "min_volatility_ratio_5_to_20")
    if min_volatility_ratio is not None and float(row["volatility_ratio_5_to_20"]) < min_volatility_ratio:
        return False
    min_intrabar_range = _filter_float(spec, "min_intrabar_range_pips")
    if min_intrabar_range is not None and float(row["intrabar_range_pips"]) < min_intrabar_range:
        return False
    min_range_width = _filter_float(spec, "min_range_width_10_pips")
    if min_range_width is not None and float(row["range_width_10_pips"]) < min_range_width:
        return False
    min_range_efficiency = _filter_float(spec, "min_range_efficiency_10")
    if min_range_efficiency is not None and float(row["range_efficiency_10"]) < min_range_efficiency:
        return False
    max_range_efficiency = _filter_float(spec, "max_range_efficiency_10")
    if max_range_efficiency is not None and float(row["range_efficiency_10"]) > max_range_efficiency:
        return False
    required_volatility_bucket = _filter_value(spec, "required_volatility_bucket")
    if required_volatility_bucket and _volatility_bucket(float(row["volatility_20"])) != required_volatility_bucket:
        return False
    required_phase_bucket = _filter_value(spec, "required_phase_bucket")
    if required_phase_bucket:
        open_anchor_hour_utc = spec.open_anchor_hour_utc
        if open_anchor_hour_utc is None:
            open_anchor_hour_utc = min(spec.session_policy.allowed_hours_utc) if spec.session_policy.allowed_hours_utc else 7
        if _phase_bucket_for_hour(int(row["hour"]), open_anchor_hour_utc=open_anchor_hour_utc) != required_phase_bucket:
            return False
    blocked_context = _filter_value(spec, "exclude_context_bucket")
    if blocked_context and _context_bucket(float(row["zscore_10"]), float(row["momentum_12"])) == blocked_context:
        return False
    return True


def _phase_bucket_for_hour(hour_utc: int, *, open_anchor_hour_utc: int) -> str:
    if hour_utc <= open_anchor_hour_utc:
        return "open_impulse"
    if hour_utc == open_anchor_hour_utc + 1:
        return "early_follow_through"
    if hour_utc <= open_anchor_hour_utc + 4:
        return "late_morning_decay"
    return "outside_anchor"


def _position_size_lots(balance: float, row: pd.Series, spec: StrategySpec) -> float:
    if balance <= 0:
        return 0.0
    risk_pct = min(spec.account_model.risk_per_trade_pct, spec.risk_policy.max_risk_per_trade_pct)
    risk_dollars = balance * (risk_pct / 100)
    per_lot_risk = spec.stop_loss_pips * spec.account_model.pip_value_per_standard_lot
    if per_lot_risk <= 0:
        return 0.0
    risk_based_lots = risk_dollars / per_lot_risk
    margin_based_lots = _margin_cap_lots(float(row["mid_c"]), balance, spec)
    return max(min(risk_based_lots, margin_based_lots, spec.account_model.max_total_exposure_lots), 0.0)


def _margin_cap_lots(entry_price: float, balance: float, spec: StrategySpec) -> float:
    if spec.account_model.leverage <= 0 or entry_price <= 0 or balance <= 0:
        return 0.0
    margin_per_lot = (entry_price * spec.account_model.contract_size) / spec.account_model.leverage
    usable_margin = balance * max(1 - (spec.account_model.margin_buffer_pct / 100), 0)
    if margin_per_lot <= 0:
        return 0.0
    return usable_margin / margin_per_lot


def _margin_utilization_pct(entry_price: float, balance_before_trade: float, position_size_lots: float, spec: StrategySpec) -> float:
    if balance_before_trade <= 0 or spec.account_model.leverage <= 0:
        return 0.0
    margin_used = (entry_price * spec.account_model.contract_size * position_size_lots) / spec.account_model.leverage
    return (margin_used / balance_before_trade) * 100


def _load_blackout_windows(spec: StrategySpec, settings: Settings) -> pd.DataFrame:
    if not spec.news_policy.enabled:
        return pd.DataFrame(columns=["start_utc", "end_utc", "currency", "impact", "title"])
    events = load_relevant_calendar_events(
        settings,
        currencies=spec.news_policy.currencies,
        minimum_impact=spec.news_policy.minimum_impact,
    )
    return build_blackout_windows(
        events,
        minutes_before=spec.news_policy.blackout_minutes_before,
        minutes_after=spec.news_policy.blackout_minutes_after,
    )


def _daily_pnl(trade_ledger: pd.DataFrame) -> pd.Series:
    if trade_ledger.empty:
        return pd.Series(dtype=float)
    daily_frame = trade_ledger.copy()
    daily_frame["exit_timestamp_utc"] = pd.to_datetime(daily_frame["exit_timestamp_utc"], utc=True)
    daily_frame["day_utc"] = daily_frame["exit_timestamp_utc"].dt.date
    return daily_frame.groupby("day_utc")["pnl_dollars"].sum()


def _granularity_to_milliseconds(granularity: str) -> int:
    token = granularity.strip().upper()
    if token.endswith("S"):
        return max(int(token[:-1]), 1) * 1000
    if token.endswith("M"):
        return max(int(token[:-1]), 1) * 60_000
    if token.endswith("H"):
        return max(int(token[:-1]), 1) * 3_600_000
    return 60_000


def _split_fill_delay(fill_delay_ms: int, bar_duration_ms: int) -> tuple[int, float]:
    if fill_delay_ms <= 0 or bar_duration_ms <= 0:
        return 0, 0.0
    whole_bars, remainder = divmod(fill_delay_ms, bar_duration_ms)
    return int(whole_bars), float(remainder / bar_duration_ms)


def _fill_delay_penalty_pips(
    *,
    fill_row: pd.Series,
    signal: int,
    delay_fraction: float,
    phase: str,
) -> float:
    if delay_fraction <= 0:
        return 0.0
    if phase == "entry":
        if signal > 0:
            adverse_move = max(float(fill_row["ask_h"]) - float(fill_row["ask_o"]), 0.0)
        else:
            adverse_move = max(float(fill_row["bid_o"]) - float(fill_row["bid_l"]), 0.0)
    else:
        if signal > 0:
            adverse_move = max(float(fill_row["bid_c"]) - float(fill_row["bid_l"]), 0.0)
        else:
            adverse_move = max(float(fill_row["ask_h"]) - float(fill_row["ask_c"]), 0.0)
    return adverse_move * 10_000 * delay_fraction
