from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from pandas.errors import EmptyDataError

from agentic_forex.backtesting.benchmark import compute_candidate_ranking_score
from agentic_forex.backtesting.models import BacktestArtifact, ScalpingBenchmarkReport, StressTestReport
from agentic_forex.config import Settings
from agentic_forex.evals.graders import grade_candidate
from agentic_forex.experiments.models import ExperimentComparisonRecord, ExperimentComparisonReport
from agentic_forex.policy.ftmo import score_ftmo_fit
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows.contracts import FTMOFitReport, ReviewPacket, StrategySpec


def compare_experiments(
    settings: Settings,
    *,
    family: str | None = None,
    candidate_ids: list[str] | None = None,
    limit: int | None = None,
) -> ExperimentComparisonReport:
    benchmark_index = _load_benchmark_index(settings)
    requested = None if candidate_ids is None else set(candidate_ids)
    records: list[ExperimentComparisonRecord] = []
    excluded_candidates: dict[str, list[str]] = {}
    explicitly_rejected: dict[str, list[str]] = {}
    for candidate_dir in sorted(path for path in settings.paths().reports_dir.iterdir() if path.is_dir()):
        candidate_id = candidate_dir.name
        if requested is not None and candidate_id not in requested:
            continue
        spec_path = candidate_dir / "strategy_spec.json"
        backtest_path = candidate_dir / "backtest_summary.json"
        if not spec_path.exists() or not backtest_path.exists():
            continue
        spec = StrategySpec.model_validate(read_json(spec_path))
        if family and spec.family != family:
            continue
        stress_path = candidate_dir / "stress_test.json"
        review_path = candidate_dir / "review_packet.json"
        backtest = BacktestArtifact.model_validate(read_json(backtest_path))
        validation_errors = _comparison_validation_errors(backtest)
        if validation_errors:
            excluded_candidates[candidate_id] = validation_errors
            if requested is not None and candidate_id in requested:
                explicitly_rejected[candidate_id] = validation_errors
            continue
        record = _build_record(
            spec=spec,
            backtest=backtest,
            stress=StressTestReport.model_validate(read_json(stress_path)) if stress_path.exists() else None,
            review=ReviewPacket.model_validate(read_json(review_path)) if review_path.exists() else None,
            benchmark_meta=benchmark_index.get(candidate_id, {}),
            settings=settings,
        )
        records.append(record)
    if explicitly_rejected:
        reasons = "; ".join(
            f"{candidate_id}: {', '.join(details)}"
            for candidate_id, details in sorted(explicitly_rejected.items())
        )
        raise ValueError(f"Invalid comparison inputs rejected: {reasons}")
    ordered = sorted(records, key=lambda item: item.comparison_score, reverse=True)
    if limit is not None:
        ordered = ordered[:limit]
    recommended_record = next((record for record in ordered if _is_recommendable_candidate(record, settings)), None)
    report_path, latest_path = _comparison_paths(settings)
    registry_path = settings.paths().experiments_dir / "registry.csv"
    report = ExperimentComparisonReport(
        family_filter=family,
        candidate_filters=sorted(requested or []),
        total_records=len(ordered),
        registry_path=registry_path,
        report_path=report_path,
        latest_report_path=latest_path,
        recommended_candidate_id=recommended_record.candidate_id if recommended_record else None,
        excluded_candidates=excluded_candidates,
        records=ordered,
    )
    _write_registry_csv(registry_path, ordered)
    payload = report.model_dump(mode="json")
    write_json(report_path, payload)
    write_json(latest_path, payload)
    return report


def _build_record(
    *,
    spec: StrategySpec,
    backtest: BacktestArtifact,
    stress: StressTestReport | None,
    review: ReviewPacket | None,
    benchmark_meta: dict,
    settings: Settings,
) -> ExperimentComparisonRecord:
    trade_ledger = _normalize_trade_ledger(_read_trade_ledger(backtest.trade_ledger_path), spec)
    coverage = _coverage_from_trade_ledger(trade_ledger, fallback_parquet=_research_dataset_path(spec, settings))
    resolved_stress = stress or StressTestReport(
        candidate_id=spec.candidate_id,
        base_profit_factor=backtest.profit_factor,
        stressed_profit_factor=backtest.profit_factor,
        spread_multiplier=spec.cost_model.spread_multiplier,
        slippage_pips=spec.cost_model.slippage_pips,
        passed=False,
        report_path=backtest.summary_path.parent / "stress_test.json",
    )
    grades = review.metrics.get("grades") if review else None
    if not isinstance(grades, dict):
        grades = grade_candidate(backtest, resolved_stress, settings)
    walk_forward_ok = grades.get("walk_forward_ok") if isinstance(grades.get("walk_forward_ok"), bool) else None
    ftmo_fit = FTMOFitReport.model_validate(review.ftmo_fit) if review and review.ftmo_fit else score_ftmo_fit(
        spec=spec,
        backtest=backtest,
        stress=resolved_stress,
        trade_ledger=trade_ledger,
        settings=settings,
    )
    empirical_score = benchmark_meta.get("benchmark_ranking_score")
    if empirical_score is None:
        empirical_score = compute_candidate_ranking_score(backtest, resolved_stress, grades)
    comparison_score = _comparison_score(
        empirical_score=float(empirical_score),
        ftmo_fit_score=ftmo_fit.fit_score_0_100 if ftmo_fit else None,
        trade_count=backtest.trade_count,
        out_of_sample_profit_factor=backtest.out_of_sample_profit_factor,
        expectancy_pips=backtest.expectancy_pips,
        stress_passed=resolved_stress.passed,
        readiness=review.readiness if review else "unreviewed",
        approval_recommendation=review.approval_recommendation if review else "not_reviewed",
        ready_for_publish=bool(grades.get("ready_for_publish")),
        settings=settings,
    )
    return ExperimentComparisonRecord(
        candidate_id=spec.candidate_id,
        family=spec.family,
        instrument=spec.instrument,
        entry_style=spec.entry_style,
        benchmark_group_id=spec.benchmark_group_id,
        variant_name=spec.variant_name,
        dataset_start_utc=coverage["dataset_start_utc"],
        dataset_end_utc=coverage["dataset_end_utc"],
        trading_days_observed=coverage["trading_days_observed"],
        trade_count=backtest.trade_count,
        profit_factor=backtest.profit_factor,
        out_of_sample_profit_factor=backtest.out_of_sample_profit_factor,
        expectancy_pips=backtest.expectancy_pips,
        max_drawdown_pct=backtest.max_drawdown_pct,
        stressed_profit_factor=resolved_stress.stressed_profit_factor,
        stress_passed=resolved_stress.passed,
        ftmo_fit_score=ftmo_fit.fit_score_0_100 if ftmo_fit else None,
        ftmo_fit_band=ftmo_fit.fit_band if ftmo_fit else None,
        readiness=review.readiness if review else "unreviewed",
        approval_recommendation=review.approval_recommendation if review else "not_reviewed",
        ready_for_publish=bool(grades.get("ready_for_publish")),
        walk_forward_ok=walk_forward_ok,
        benchmark_ranking_score=benchmark_meta.get("benchmark_ranking_score"),
        comparison_score=round(comparison_score, 6),
        spec_path=backtest.spec_path,
        backtest_summary_path=backtest.summary_path,
        stress_report_path=resolved_stress.report_path if resolved_stress.report_path.exists() else None,
        review_packet_path=backtest.summary_path.parent / "review_packet.json" if review else None,
        benchmark_report_path=benchmark_meta.get("benchmark_report_path"),
    )


def _coverage_from_trade_ledger(
    trade_ledger: pd.DataFrame,
    *,
    fallback_parquet: Path | None = None,
) -> dict[str, str | int | None]:
    if trade_ledger.empty or "timestamp_utc" not in trade_ledger.columns:
        return _coverage_from_dataset(fallback_parquet)
    timestamps = pd.to_datetime(trade_ledger["timestamp_utc"], utc=True)
    trading_days = timestamps.dt.floor("D").nunique()
    return {
        "dataset_start_utc": timestamps.min().isoformat().replace("+00:00", "Z"),
        "dataset_end_utc": timestamps.max().isoformat().replace("+00:00", "Z"),
        "trading_days_observed": int(trading_days),
    }


def _coverage_from_dataset(path: Path | None) -> dict[str, str | int | None]:
    if path is None or not path.exists():
        return {
            "dataset_start_utc": None,
            "dataset_end_utc": None,
            "trading_days_observed": 0,
        }
    frame = pd.read_parquet(path, columns=["timestamp_utc"])
    if frame.empty:
        return {
            "dataset_start_utc": None,
            "dataset_end_utc": None,
            "trading_days_observed": 0,
        }
    timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
    return {
        "dataset_start_utc": timestamps.min().isoformat().replace("+00:00", "Z"),
        "dataset_end_utc": timestamps.max().isoformat().replace("+00:00", "Z"),
        "trading_days_observed": int(timestamps.dt.floor("D").nunique()),
    }


def _read_trade_ledger(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame(
            columns=[
                "timestamp_utc",
                "exit_timestamp_utc",
                "entry_price",
                "pnl_pips",
                "pnl_dollars",
                "balance_after",
                "position_size_lots",
                "margin_utilization_pct",
            ]
        )


def _research_dataset_path(spec: StrategySpec, settings: Settings) -> Path:
    return settings.paths().normalized_research_dir / f"{spec.instrument.lower()}_{spec.execution_granularity.lower()}.parquet"


def _normalize_trade_ledger(trade_ledger: pd.DataFrame, spec: StrategySpec) -> pd.DataFrame:
    if trade_ledger.empty:
        return trade_ledger
    ledger = trade_ledger.copy()
    if "exit_timestamp_utc" not in ledger.columns:
        ledger["exit_timestamp_utc"] = ledger.get("timestamp_utc")
    if "position_size_lots" not in ledger.columns:
        ledger["position_size_lots"] = spec.account_model.max_total_exposure_lots
    if "pnl_dollars" not in ledger.columns and {"pnl_pips", "position_size_lots"}.issubset(ledger.columns):
        ledger["pnl_dollars"] = (
            pd.to_numeric(ledger["pnl_pips"], errors="coerce").fillna(0.0)
            * spec.account_model.pip_value_per_standard_lot
            * pd.to_numeric(ledger["position_size_lots"], errors="coerce").fillna(spec.account_model.max_total_exposure_lots)
        )
    if "balance_after" not in ledger.columns:
        pnl_dollars = pd.to_numeric(ledger["pnl_dollars"], errors="coerce").fillna(0.0)
        ledger["balance_after"] = spec.account_model.initial_balance + pnl_dollars.cumsum()
    if "margin_utilization_pct" not in ledger.columns:
        if "entry_price" in ledger.columns:
            entry_price = pd.to_numeric(ledger["entry_price"], errors="coerce").fillna(1.0)
        else:
            entry_price = pd.Series([1.0] * len(ledger), index=ledger.index, dtype="float64")
        lots = pd.to_numeric(ledger["position_size_lots"], errors="coerce").fillna(spec.account_model.max_total_exposure_lots)
        notional = entry_price * spec.account_model.contract_size * lots
        required_margin = notional / max(spec.account_model.leverage, 1e-9)
        ledger["margin_utilization_pct"] = (required_margin / spec.account_model.initial_balance) * 100
    return ledger


def _load_benchmark_index(settings: Settings) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for report_path in sorted(settings.paths().reports_dir.glob("*/scalping_benchmark.json")):
        report = ScalpingBenchmarkReport.model_validate(read_json(report_path))
        for variant in report.variants:
            index[variant.candidate_id] = {
                "benchmark_group_id": variant.benchmark_group_id,
                "variant_name": variant.variant_name,
                "benchmark_ranking_score": variant.ranking_score,
                "benchmark_report_path": report_path,
            }
    return index


def _comparison_score(
    *,
    empirical_score: float,
    ftmo_fit_score: float | None,
    trade_count: int,
    out_of_sample_profit_factor: float,
    expectancy_pips: float,
    stress_passed: bool,
    readiness: str,
    approval_recommendation: str,
    ready_for_publish: bool,
    settings: Settings,
) -> float:
    score = empirical_score
    if ftmo_fit_score is not None:
        score += min(max(ftmo_fit_score, 0.0), 100.0) * 0.2
    validation = settings.validation
    if trade_count < validation.minimum_test_trade_count:
        trade_gap = (validation.minimum_test_trade_count - trade_count) / max(validation.minimum_test_trade_count, 1)
        score -= min(trade_gap, 1.0) * 30.0
    if out_of_sample_profit_factor < validation.out_of_sample_profit_factor_floor:
        pf_gap = (validation.out_of_sample_profit_factor_floor - out_of_sample_profit_factor) / max(
            validation.out_of_sample_profit_factor_floor,
            1e-9,
        )
        score -= min(max(pf_gap, 0.0), 1.0) * 25.0
    if expectancy_pips <= validation.expectancy_floor:
        score -= 20.0
    if not stress_passed:
        score -= 20.0
    if ready_for_publish:
        score += 15.0
    if readiness == "approval_ready":
        score += 10.0
    elif readiness == "needs_review":
        score += 2.0
    elif readiness == "rejected":
        score -= 15.0
    if approval_recommendation == "approve_for_publish":
        score += 10.0
    elif approval_recommendation == "needs_human_review":
        score += 3.0
    elif approval_recommendation == "reject":
        score -= 20.0
    return score


def _is_recommendable_candidate(record: ExperimentComparisonRecord, settings: Settings) -> bool:
    validation = settings.validation
    if record.trade_count < validation.minimum_test_trade_count:
        return False
    if record.out_of_sample_profit_factor < validation.out_of_sample_profit_factor_floor:
        return False
    if record.expectancy_pips <= validation.expectancy_floor:
        return False
    if not record.stress_passed:
        return False
    if record.readiness == "rejected" or record.approval_recommendation == "reject":
        return False
    return True


def _comparison_paths(settings: Settings) -> tuple[Path, Path]:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = settings.paths().experiments_dir / f"comparison_{timestamp}.json"
    latest_path = settings.paths().experiments_dir / "comparison_latest.json"
    return report_path, latest_path


def _comparison_validation_errors(backtest: BacktestArtifact) -> list[str]:
    if backtest.trade_count <= 0:
        return []
    errors: list[str] = []
    split_breakdown = backtest.split_breakdown if isinstance(backtest.split_breakdown, dict) else {}
    in_sample = split_breakdown.get("in_sample") or split_breakdown.get("train")
    out_of_sample = split_breakdown.get("out_of_sample")
    if not isinstance(in_sample, dict) or int(in_sample.get("trade_count") or 0) <= 0:
        errors.append("in_sample_vs_out_of_sample_requires_in_sample_split")
    if not isinstance(out_of_sample, dict) or int(out_of_sample.get("trade_count") or 0) <= 0:
        errors.append("in_sample_vs_out_of_sample_requires_out_of_sample_split")

    walk_forward = list(backtest.walk_forward_summary or [])
    if len(walk_forward) < 2:
        errors.append("cross_window_comparison_requires_multiple_walk_forward_windows")
    else:
        window_bounds: list[tuple[pd.Timestamp, pd.Timestamp]] = []
        for item in walk_forward:
            start = pd.to_datetime(item.get("start_utc"), utc=True, errors="coerce")
            end = pd.to_datetime(item.get("end_utc"), utc=True, errors="coerce")
            if pd.isna(start) or pd.isna(end) or end <= start:
                errors.append("cross_window_comparison_requires_valid_window_bounds")
                window_bounds = []
                break
            window_bounds.append((start, end))
        if window_bounds:
            ordered = sorted(window_bounds, key=lambda item: item[0])
            for index in range(1, len(ordered)):
                if ordered[index][0] < ordered[index - 1][1]:
                    errors.append("cross_window_comparison_requires_non_overlapping_windows")
                    break

    regime_breakdown = backtest.regime_breakdown if isinstance(backtest.regime_breakdown, dict) else {}
    populated_buckets = [
        bucket
        for bucket in ("session_bucket", "volatility_bucket", "context_bucket")
        if isinstance(regime_breakdown.get(bucket), dict) and regime_breakdown.get(bucket)
    ]
    if not populated_buckets:
        errors.append("cross_window_comparison_requires_regime_accounting")

    return errors


def _write_registry_csv(path: Path, records: list[ExperimentComparisonRecord]) -> Path:
    fieldnames = [
        "candidate_id",
        "family",
        "instrument",
        "entry_style",
        "benchmark_group_id",
        "variant_name",
        "dataset_start_utc",
        "dataset_end_utc",
        "trading_days_observed",
        "trade_count",
        "profit_factor",
        "out_of_sample_profit_factor",
        "expectancy_pips",
        "max_drawdown_pct",
        "stressed_profit_factor",
        "stress_passed",
        "ftmo_fit_score",
        "ftmo_fit_band",
        "readiness",
        "approval_recommendation",
        "ready_for_publish",
        "walk_forward_ok",
        "benchmark_ranking_score",
        "comparison_score",
        "spec_path",
        "backtest_summary_path",
        "stress_report_path",
        "review_packet_path",
        "benchmark_report_path",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record.model_dump(mode="json"))
    return path
