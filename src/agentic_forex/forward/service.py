from __future__ import annotations

import hashlib
from collections.abc import Callable

import pandas as pd

from agentic_forex.backtesting.models import BacktestArtifact
from agentic_forex.backtesting.engine import run_backtest
from agentic_forex.config import Settings
from agentic_forex.governance.models import ForwardStageReport
from agentic_forex.governance.provenance import build_data_provenance, build_environment_snapshot
from agentic_forex.governance.trial_ledger import append_failure_record, append_trial_entry
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows.contracts import StrategySpec


def run_shadow_forward(spec: StrategySpec, settings: Settings) -> ForwardStageReport:
    parquet_path = settings.paths().normalized_research_dir / f"{spec.instrument.lower()}_{spec.execution_granularity.lower()}.parquet"
    frame = pd.read_parquet(parquet_path)
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    forward_frame, artifact = _select_forward_frame_for_minimum_evidence(frame, spec, settings)
    baseline_oos_expectancy = _baseline_oos_expectancy(spec, settings)
    degradation_pct = _expectancy_degradation_pct(artifact.expectancy_pips, baseline_oos_expectancy)
    risk_violations = []
    max_daily_loss = float(artifact.account_metrics.get("max_daily_loss_pct", 0.0))
    if max_daily_loss > spec.risk_envelope.max_daily_loss_pct:
        risk_violations.append("max_daily_loss_pct_exceeded")
    if artifact.trade_count < settings.validation.forward_min_trade_count:
        risk_violations.append("minimum_forward_trade_count_not_met")
    if artifact.account_metrics.get("trading_days_observed", 0) < settings.validation.forward_min_trading_days:
        risk_violations.append("minimum_forward_trading_days_not_met")
    if artifact.profit_factor < settings.validation.forward_profit_factor_floor:
        risk_violations.append("forward_profit_factor_below_floor")
    if artifact.expectancy_pips <= settings.validation.forward_expectancy_floor:
        risk_violations.append("forward_expectancy_below_floor")
    if degradation_pct > settings.validation.forward_expectancy_degradation_limit_pct:
        risk_violations.append("forward_expectancy_drift_exceeded")
    report = ForwardStageReport(
        candidate_id=spec.candidate_id,
        mode="oanda_shadow",
        forward_dataset_snapshot_id=_forward_dataset_snapshot_id(forward_frame, spec),
        trading_days_observed=int(artifact.account_metrics.get("trading_days_observed", 0)),
        trade_count=artifact.trade_count,
        profit_factor=artifact.profit_factor,
        expectancy_pips=artifact.expectancy_pips,
        oos_expectancy_pips=baseline_oos_expectancy,
        expectancy_degradation_pct=round(degradation_pct, 6),
        risk_violations=risk_violations,
        passed=not risk_violations,
        artifact_references={
            "dataset_snapshot": artifact.artifact_references.get("dataset_snapshot", {}),
            "feature_build": artifact.artifact_references.get("feature_build", {}),
            "data_provenance": artifact.artifact_references.get("data_provenance", {}),
            "environment_snapshot": artifact.artifact_references.get("environment_snapshot", {}),
            "execution_cost_model": spec.execution_cost_model.model_dump(mode="json"),
            "risk_envelope": spec.risk_envelope.model_dump(mode="json"),
        },
        report_path=settings.paths().reports_dir / spec.candidate_id / "forward_stage_report.json",
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    data_provenance = build_data_provenance(spec, settings, stage="forward_stage")
    environment_snapshot = build_environment_snapshot(settings, candidate_id=spec.candidate_id)
    append_trial_entry(
        settings,
        candidate_id=spec.candidate_id,
        family=spec.family,
        stage="forward_stage",
        artifact_paths={
            "forward_stage_report_path": str(report.report_path),
            "forward_trade_ledger_path": str(artifact.trade_ledger_path),
            "data_provenance_path": str(data_provenance.report_path),
            "environment_snapshot_path": str(environment_snapshot.report_path),
        },
        provenance_id=data_provenance.provenance_id,
        environment_snapshot_id=environment_snapshot.environment_id,
        gate_outcomes={
            "passed": report.passed,
            "trade_count": report.trade_count,
            "profit_factor": report.profit_factor,
            "expectancy_pips": report.expectancy_pips,
            "expectancy_degradation_pct": report.expectancy_degradation_pct,
        },
        failure_code="forward_failure" if not report.passed else None,
    )
    if not report.passed:
        append_failure_record(
            settings,
            candidate_id=spec.candidate_id,
            stage="forward_stage",
            failure_code="forward_failure",
            details={"risk_violations": report.risk_violations},
            artifact_paths={"forward_stage_report_path": str(report.report_path)},
        )
    return report


def load_forward_stage_report(candidate_id: str, settings: Settings) -> ForwardStageReport | None:
    path = settings.paths().reports_dir / candidate_id / "forward_stage_report.json"
    if not path.exists():
        return None
    return ForwardStageReport.model_validate(read_json(path))


def _baseline_oos_expectancy(spec: StrategySpec, settings: Settings) -> float:
    backtest_path = settings.paths().reports_dir / spec.candidate_id / "backtest_summary.json"
    if not backtest_path.exists():
        return 0.0
    payload = read_json(backtest_path)
    split = payload.get("split_breakdown", {}).get("out_of_sample", {})
    return float(split.get("expectancy_pips", payload.get("expectancy_pips", 0.0)))


def _expectancy_degradation_pct(forward_expectancy: float, baseline_expectancy: float) -> float:
    if baseline_expectancy <= 0:
        return 0.0 if forward_expectancy > 0 else 100.0
    return max(((baseline_expectancy - forward_expectancy) / baseline_expectancy) * 100.0, 0.0)


def _forward_dataset_snapshot_id(frame: pd.DataFrame, spec: StrategySpec) -> str:
    if frame.empty:
        return "forward-empty"
    payload = (
        f"{spec.instrument}|{spec.execution_granularity}|"
        f"{frame['timestamp_utc'].min().isoformat()}|{frame['timestamp_utc'].max().isoformat()}|{len(frame)}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _select_forward_frame_for_minimum_evidence(
    frame: pd.DataFrame,
    spec: StrategySpec,
    settings: Settings,
    *,
    evaluator: Callable[..., BacktestArtifact] = run_backtest,
) -> tuple[pd.DataFrame, BacktestArtifact]:
    if frame.empty:
        artifact = evaluator(spec, settings, output_prefix="forward_shadow", frame=frame.copy())
        return frame.copy(), artifact

    normalized = frame.copy()
    normalized["trade_date_utc"] = normalized["timestamp_utc"].dt.normalize()
    unique_trade_dates = list(pd.Index(normalized["trade_date_utc"].dropna().unique()).sort_values())
    if not unique_trade_dates:
        artifact = evaluator(spec, settings, output_prefix="forward_shadow", frame=normalized.drop(columns=["trade_date_utc"]))
        return normalized.drop(columns=["trade_date_utc"]), artifact

    min_days = max(int(settings.validation.forward_min_trading_days), 1)
    min_trades = max(int(settings.validation.forward_min_trade_count), 0)
    last_frame = normalized.drop(columns=["trade_date_utc"]).copy()
    last_artifact: BacktestArtifact | None = None

    for trading_day_window in range(min(min_days, len(unique_trade_dates)), len(unique_trade_dates) + 1):
        cutoff_date = pd.Timestamp(unique_trade_dates[-trading_day_window])
        candidate = normalized.loc[normalized["trade_date_utc"] >= cutoff_date].drop(columns=["trade_date_utc"]).copy()
        artifact = evaluator(spec, settings, output_prefix="forward_shadow", frame=candidate)
        last_frame = candidate
        last_artifact = artifact
        observed_days = int(artifact.account_metrics.get("trading_days_observed", 0))
        if observed_days >= min_days and artifact.trade_count >= min_trades:
            return candidate, artifact
    if last_artifact is None:
        last_artifact = evaluator(spec, settings, output_prefix="forward_shadow", frame=last_frame)
    return last_frame, last_artifact
