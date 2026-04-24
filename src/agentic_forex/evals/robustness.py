from __future__ import annotations

import itertools
import math
import random
from pathlib import Path
from typing import NamedTuple

import pandas as pd

from agentic_forex.backtesting.models import BacktestArtifact, StressTestReport
from agentic_forex.config import Settings
from agentic_forex.governance.models import ExperimentDataProvenance, RobustnessReport
from agentic_forex.governance.trial_ledger import count_trials
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows.contracts import StrategySpec


class _ComparableUniverseSignature(NamedTuple):
    family: str
    instrument: str
    entry_style: str
    execution_cost_model_version: str
    dataset_source: str
    dataset_instrument: str
    dataset_start_utc: str | None
    dataset_end_utc: str | None
    parquet_path: str
    feature_version_id: str
    label_version_id: str
    calendar_version_id: str | None


def build_robustness_report(
    spec: StrategySpec,
    *,
    backtest: BacktestArtifact,
    stress: StressTestReport,
    trade_ledger: pd.DataFrame,
    settings: Settings,
) -> RobustnessReport:
    observed_sharpe = _observed_sharpe(trade_ledger)
    trial_count_family = count_trials(settings, family=spec.family)
    trial_count_candidate = count_trials(settings, candidate_id=spec.candidate_id)
    dsr = _deflated_sharpe_ratio(observed_sharpe, trade_ledger, max(trial_count_family, 1))
    candidate_ledgers, contract = _family_candidate_ledgers(spec, settings)
    cscv_result = _estimate_family_cscv_pbo_from_ledgers(
        candidate_ledgers,
        desired_partition_count=settings.validation.cscv_partition_count,
        contract=contract,
    )
    white_reality_check = _estimate_family_white_reality_check_from_ledgers(
        candidate_ledgers, settings=settings, contract=contract
    )
    walk_forward_ok = (
        all(window.get("profit_factor", 0.0) > 0.9 for window in backtest.walk_forward_summary)
        if backtest.walk_forward_summary
        else False
    )
    warnings: list[str] = []
    if trial_count_family >= 10:
        warnings.append(
            f"Family has already consumed {trial_count_family} recorded trials; search-adjusted caution is required."
        )
    if not walk_forward_ok:
        warnings.append("Walk-forward windows are not uniformly stable.")
    if not stress.passed:
        warnings.append("Stress scenarios failed the configured floor.")
    if cscv_result["available"]:
        if cscv_result["pbo"] > settings.validation.pbo_threshold:
            warnings.append(
                f"CSCV/PBO overfit risk is elevated at {cscv_result['pbo']:.3f}, above the configured threshold "
                f"{settings.validation.pbo_threshold:.3f}."
            )
        else:
            warnings.append(
                f"CSCV/PBO is available for {cscv_result['candidate_count']} comparable family candidates across "
                f"{cscv_result['partition_count']} partitions."
            )
    else:
        warnings.append(
            "CSCV/PBO is not yet available for this family universe; this robustness assessment remains provisional."
        )
    if white_reality_check["available"]:
        if white_reality_check["p_value"] <= settings.validation.white_reality_check_pvalue_threshold:
            warnings.append(
                f"White's Reality Check supports the apparent winner across {white_reality_check['candidate_count']} comparable candidates "
                f"(p={white_reality_check['p_value']:.3f}, threshold {settings.validation.white_reality_check_pvalue_threshold:.3f})."
            )
        else:
            warnings.append(
                f"White's Reality Check does not support the apparent winner (p={white_reality_check['p_value']:.3f}, "
                f"threshold {settings.validation.white_reality_check_pvalue_threshold:.3f})."
            )
    else:
        warnings.append(
            "White's Reality Check is not yet available for this family universe; search-adjusted robustness remains provisional."
        )
    status = (
        "robustness_passed"
        if cscv_result["available"]
        and white_reality_check["available"]
        and cscv_result["pbo"] <= settings.validation.pbo_threshold
        and white_reality_check["p_value"] <= settings.validation.white_reality_check_pvalue_threshold
        and dsr >= settings.validation.deflated_sharpe_floor
        and walk_forward_ok
        and stress.passed
        else "robustness_provisional"
    )
    report = RobustnessReport(
        candidate_id=spec.candidate_id,
        mode="full_search_adjusted_robustness"
        if cscv_result["available"] or white_reality_check["available"]
        else "staged_proxy_only",
        cscv_pbo_available=bool(cscv_result["available"]),
        cscv_partition_count=int(cscv_result["partition_count"]),
        cscv_candidate_count=int(cscv_result["candidate_count"]),
        white_reality_check_available=bool(white_reality_check["available"]),
        white_reality_check_candidate_count=int(white_reality_check["candidate_count"]),
        white_reality_check_bootstrap_samples=int(white_reality_check["bootstrap_samples"]),
        white_reality_check_best_candidate_id=white_reality_check["best_candidate_id"],
        white_reality_check_p_value=round(white_reality_check["p_value"], 6)
        if white_reality_check["p_value"] is not None
        else None,
        white_reality_check_pvalue_threshold=settings.validation.white_reality_check_pvalue_threshold,
        candidate_universe=list(cscv_result["candidate_ids"]),
        comparable_universe_contract=dict(cscv_result["contract"]),
        pbo=round(cscv_result["pbo"], 6) if cscv_result["pbo"] is not None else None,
        pbo_threshold=settings.validation.pbo_threshold,
        observed_sharpe=round(observed_sharpe, 6),
        deflated_sharpe_ratio=round(dsr, 6),
        deflated_sharpe_floor=settings.validation.deflated_sharpe_floor,
        trial_count_family=trial_count_family,
        trial_count_candidate=trial_count_candidate,
        walk_forward_ok=walk_forward_ok,
        stress_ok=stress.passed,
        warnings=warnings,
        status=status,
        artifact_references={
            "dataset_snapshot": backtest.artifact_references.get("dataset_snapshot", {}),
            "feature_build": backtest.artifact_references.get("feature_build", {}),
            "data_provenance": backtest.artifact_references.get("data_provenance", {}),
            "environment_snapshot": backtest.artifact_references.get("environment_snapshot", {}),
            "execution_cost_model": spec.execution_cost_model.model_dump(mode="json"),
            "risk_envelope": spec.risk_envelope.model_dump(mode="json"),
        },
        report_path=settings.paths().reports_dir / spec.candidate_id / "robustness_report.json",
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    return report


def _observed_sharpe(trade_ledger: pd.DataFrame) -> float:
    if trade_ledger.empty or "pnl_dollars" not in trade_ledger.columns:
        return 0.0
    pnl = pd.to_numeric(trade_ledger["pnl_dollars"], errors="coerce").fillna(0.0)
    std = float(pnl.std(ddof=1))
    if len(pnl) < 2 or std <= 1e-9:
        return 0.0
    return float((pnl.mean() / std) * math.sqrt(len(pnl)))


def _deflated_sharpe_ratio(observed_sharpe: float, trade_ledger: pd.DataFrame, trials: int) -> float:
    sample_count = max(len(trade_ledger), 1)
    search_penalty = math.sqrt(max(2.0 * math.log(max(trials, 1)), 0.0)) / math.sqrt(sample_count)
    return observed_sharpe - search_penalty


def _estimate_family_cscv_pbo(spec: StrategySpec, settings: Settings) -> dict[str, object]:
    candidate_ledgers, contract = _family_candidate_ledgers(spec, settings)
    return _estimate_family_cscv_pbo_from_ledgers(
        candidate_ledgers,
        desired_partition_count=settings.validation.cscv_partition_count,
        contract=contract,
    )


def _estimate_family_cscv_pbo_from_ledgers(
    candidate_ledgers: list[tuple[str, pd.Series]],
    *,
    desired_partition_count: int,
    contract: dict[str, object],
) -> dict[str, object]:
    candidate_count = len(candidate_ledgers)
    if candidate_count < 2:
        return {
            "available": False,
            "pbo": None,
            "partition_count": 0,
            "candidate_count": candidate_count,
            "candidate_ids": [candidate_id for candidate_id, _ in candidate_ledgers],
            "contract": contract,
        }
    partition_count = _effective_partition_count(
        desired=desired_partition_count,
        min_trade_count=min(len(ledger) for _, ledger in candidate_ledgers),
    )
    if partition_count < 4:
        return {
            "available": False,
            "pbo": None,
            "partition_count": partition_count,
            "candidate_count": candidate_count,
            "candidate_ids": [candidate_id for candidate_id, _ in candidate_ledgers],
            "contract": contract,
        }
    partitioned = {
        candidate_id: [chunk.reset_index(drop=True) for chunk in _partition_series(ledger, partition_count)]
        for candidate_id, ledger in candidate_ledgers
    }
    overfit_events: list[bool] = []
    split_size = partition_count // 2
    combinations = [combo for combo in itertools.combinations(range(partition_count), split_size) if 0 in combo]
    for train_indices in combinations:
        test_indices = tuple(index for index in range(partition_count) if index not in train_indices)
        train_metrics = {
            candidate_id: _observed_sharpe_from_series(_combine_partitions(partitions, train_indices))
            for candidate_id, partitions in partitioned.items()
        }
        test_metrics = {
            candidate_id: _observed_sharpe_from_series(_combine_partitions(partitions, test_indices))
            for candidate_id, partitions in partitioned.items()
        }
        best_candidate_id = max(train_metrics, key=train_metrics.get)
        ranked = sorted(test_metrics.items(), key=lambda item: item[1], reverse=True)
        out_of_sample_rank = next(
            index + 1 for index, (candidate_id, _) in enumerate(ranked) if candidate_id == best_candidate_id
        )
        overfit_events.append(out_of_sample_rank > (candidate_count / 2.0))
    return {
        "available": bool(overfit_events),
        "pbo": float(sum(overfit_events) / len(overfit_events)) if overfit_events else None,
        "partition_count": partition_count,
        "candidate_count": candidate_count,
        "candidate_ids": [candidate_id for candidate_id, _ in candidate_ledgers],
        "contract": contract,
    }


def _estimate_family_white_reality_check_from_ledgers(
    candidate_ledgers: list[tuple[str, pd.Series]],
    *,
    settings: Settings,
    contract: dict[str, object],
) -> dict[str, object]:
    candidate_count = len(candidate_ledgers)
    if candidate_count < 2:
        return {
            "available": False,
            "p_value": None,
            "candidate_count": candidate_count,
            "candidate_ids": [candidate_id for candidate_id, _ in candidate_ledgers],
            "best_candidate_id": None,
            "bootstrap_samples": 0,
            "contract": contract,
        }
    observed_means = {
        candidate_id: float(pd.to_numeric(ledger, errors="coerce").fillna(0.0).mean())
        for candidate_id, ledger in candidate_ledgers
    }
    best_candidate_id, observed_best_mean = max(observed_means.items(), key=lambda item: item[1])
    bootstrap_samples = max(int(settings.validation.white_reality_check_bootstrap_samples), 1)
    if observed_best_mean <= 0.0:
        return {
            "available": True,
            "p_value": 1.0,
            "candidate_count": candidate_count,
            "candidate_ids": [candidate_id for candidate_id, _ in candidate_ledgers],
            "best_candidate_id": best_candidate_id,
            "bootstrap_samples": bootstrap_samples,
            "contract": contract,
        }
    rng = random.Random(settings.validation.white_reality_check_random_seed)
    exceedances = 0
    centered_ledgers = [
        (
            candidate_id,
            pd.to_numeric(ledger, errors="coerce").fillna(0.0).reset_index(drop=True)
            - float(pd.to_numeric(ledger, errors="coerce").fillna(0.0).mean()),
        )
        for candidate_id, ledger in candidate_ledgers
    ]
    for _ in range(bootstrap_samples):
        bootstrap_best_mean = max(
            _moving_block_bootstrap_mean(
                ledger,
                block_size=settings.validation.white_reality_check_block_size,
                rng=rng,
            )
            for _, ledger in centered_ledgers
        )
        if bootstrap_best_mean >= observed_best_mean - 1e-12:
            exceedances += 1
    p_value = float((exceedances + 1) / (bootstrap_samples + 1))
    return {
        "available": True,
        "p_value": p_value,
        "candidate_count": candidate_count,
        "candidate_ids": [candidate_id for candidate_id, _ in candidate_ledgers],
        "best_candidate_id": best_candidate_id,
        "bootstrap_samples": bootstrap_samples,
        "contract": contract,
    }


def _family_candidate_ledgers(
    spec: StrategySpec, settings: Settings
) -> tuple[list[tuple[str, pd.Series]], dict[str, object]]:
    target_signature = _load_comparable_universe_signature(settings.paths().reports_dir / spec.candidate_id)
    contract = _signature_to_contract(spec, target_signature)
    ledgers: list[tuple[str, pd.Series]] = []
    if target_signature is None:
        return ledgers, contract
    for spec_path in settings.paths().reports_dir.glob("AF-CAND-*/strategy_spec.json"):
        report_dir = spec_path.parent
        trade_ledger_path = report_dir / "trade_ledger.csv"
        if not trade_ledger_path.exists():
            continue
        try:
            candidate_spec = StrategySpec.model_validate(read_json(spec_path))
            if candidate_spec.family != spec.family:
                continue
            if candidate_spec.instrument != spec.instrument or candidate_spec.entry_style != spec.entry_style:
                continue
            candidate_signature = _load_comparable_universe_signature(report_dir)
            if candidate_signature != target_signature:
                continue
            trade_ledger = pd.read_csv(trade_ledger_path)
        except Exception:
            continue
        if trade_ledger.empty or "pnl_dollars" not in trade_ledger.columns:
            continue
        pnl = pd.to_numeric(trade_ledger["pnl_dollars"], errors="coerce").dropna().reset_index(drop=True)
        if len(pnl) < 8:
            continue
        ledgers.append((candidate_spec.candidate_id, pnl))
    return sorted(ledgers, key=lambda item: item[0]), contract


def _load_comparable_universe_signature(report_dir: Path) -> _ComparableUniverseSignature | None:
    spec_path = report_dir / "strategy_spec.json"
    provenance_path = report_dir / "data_provenance.json"
    if not spec_path.exists() or not provenance_path.exists():
        return None
    try:
        spec = StrategySpec.model_validate(read_json(spec_path))
        provenance = ExperimentDataProvenance.model_validate(read_json(provenance_path))
    except Exception:
        return None
    dataset_snapshot = provenance.dataset_snapshot
    feature_build = provenance.feature_build
    return _ComparableUniverseSignature(
        family=spec.family,
        instrument=spec.instrument,
        entry_style=spec.entry_style,
        execution_cost_model_version=provenance.execution_cost_model_version,
        dataset_source=dataset_snapshot.source,
        dataset_instrument=dataset_snapshot.instrument,
        dataset_start_utc=dataset_snapshot.dataset_start_utc,
        dataset_end_utc=dataset_snapshot.dataset_end_utc,
        parquet_path=_normalize_path(dataset_snapshot.parquet_path),
        feature_version_id=feature_build.feature_version_id,
        label_version_id=feature_build.label_version_id,
        calendar_version_id=provenance.calendar_version_id,
    )


def _signature_to_contract(spec: StrategySpec, signature: _ComparableUniverseSignature | None) -> dict[str, object]:
    if signature is None:
        return {
            "family": spec.family,
            "instrument": spec.instrument,
            "entry_style": spec.entry_style,
            "status": "missing_target_provenance",
            "required_fields": [
                "execution_cost_model_version",
                "dataset_snapshot.source",
                "dataset_snapshot.instrument",
                "dataset_snapshot.dataset_start_utc",
                "dataset_snapshot.dataset_end_utc",
                "dataset_snapshot.parquet_path",
                "feature_build.feature_version_id",
                "feature_build.label_version_id",
            ],
        }
    return {
        "family": signature.family,
        "instrument": signature.instrument,
        "entry_style": signature.entry_style,
        "execution_cost_model_version": signature.execution_cost_model_version,
        "dataset_identity": {
            "source": signature.dataset_source,
            "instrument": signature.dataset_instrument,
            "dataset_start_utc": signature.dataset_start_utc,
            "dataset_end_utc": signature.dataset_end_utc,
            "parquet_path": signature.parquet_path,
        },
        "feature_build_identity": {
            "feature_version_id": signature.feature_version_id,
            "label_version_id": signature.label_version_id,
            "calendar_version_id": signature.calendar_version_id,
        },
        "status": "active",
    }


def _normalize_path(path: Path | str | None) -> str:
    if path is None:
        return ""
    return str(Path(path)).replace("/", "\\").lower()


def _effective_partition_count(*, desired: int, min_trade_count: int) -> int:
    partition_count = min(max(desired, 4), min_trade_count)
    if partition_count % 2:
        partition_count -= 1
    while partition_count >= 4 and (min_trade_count // partition_count) < 3:
        partition_count -= 2
    return max(partition_count, 0)


def _partition_series(series: pd.Series, partition_count: int) -> list[pd.Series]:
    partitions: list[pd.Series] = []
    base_size, remainder = divmod(len(series), partition_count)
    start = 0
    for index in range(partition_count):
        stop = start + base_size + (1 if index < remainder else 0)
        partitions.append(series.iloc[start:stop].reset_index(drop=True))
        start = stop
    return [chunk for chunk in partitions if not chunk.empty]


def _combine_partitions(partitions: list[pd.Series], indices: tuple[int, ...]) -> pd.Series:
    if not indices:
        return pd.Series(dtype=float)
    return pd.concat([partitions[index] for index in indices], ignore_index=True)


def _observed_sharpe_from_series(pnl: pd.Series) -> float:
    if pnl.empty:
        return 0.0
    numeric = pd.to_numeric(pnl, errors="coerce").fillna(0.0)
    std = float(numeric.std(ddof=1))
    if len(numeric) < 2 or std <= 1e-9:
        return 0.0
    return float((numeric.mean() / std) * math.sqrt(len(numeric)))


def _moving_block_bootstrap_mean(pnl: pd.Series, *, block_size: int, rng: random.Random) -> float:
    numeric = pd.to_numeric(pnl, errors="coerce").fillna(0.0).reset_index(drop=True)
    sample_size = len(numeric)
    if sample_size == 0:
        return 0.0
    effective_block_size = min(max(int(block_size), 1), sample_size)
    values: list[float] = []
    while len(values) < sample_size:
        start = rng.randrange(sample_size)
        for offset in range(effective_block_size):
            values.append(float(numeric.iloc[(start + offset) % sample_size]))
            if len(values) >= sample_size:
                break
    return float(sum(values) / sample_size)

# ---------------------------------------------------------------------------
# MT5 feature alignment test  (ML-P1.9)
# ---------------------------------------------------------------------------

def mt5_feature_alignment_test(
    oanda_features: pd.DataFrame,
    mt5_features: pd.DataFrame,
    *,
    feature_cols: list[str] | None = None,
    max_auc: float = 0.60,
) -> dict:
    """Adversarial test: can a classifier distinguish OANDA vs MT5 features?

    Builds a combined dataset labelling each row by source, trains a
    stratified k-fold classifier, and computes the mean OOS AUC.  If
    AUC exceeds *max_auc* the two feeds are materially different and
    any model trained on OANDA may not transfer to MT5.
    """
    import numpy as np
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold

    cols = feature_cols or [
        c for c in oanda_features.columns
        if c in mt5_features.columns and oanda_features[c].dtype.kind in "fi"
    ]

    oa = oanda_features[cols].dropna().copy()
    mt = mt5_features[cols].dropna().copy()
    oa["_source"] = 0
    mt["_source"] = 1
    combined = pd.concat([oa, mt], ignore_index=True)

    X = combined[cols]
    y = combined["_source"]

    if len(X) < 40:
        return {"auc": 0.5, "passed": True, "note": "insufficient data"}

    skf = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
    aucs = []
    for train_idx, test_idx in skf.split(X, y):
        clf = RandomForestClassifier(n_estimators=50, random_state=42)
        clf.fit(X.iloc[train_idx], y.iloc[train_idx])
        prob = clf.predict_proba(X.iloc[test_idx])[:, 1]
        aucs.append(float(roc_auc_score(y.iloc[test_idx], prob)))

    mean_auc = float(np.mean(aucs))
    return {
        "auc": round(mean_auc, 4),
        "per_fold_auc": [round(a, 4) for a in aucs],
        "max_auc_threshold": max_auc,
        "passed": mean_auc <= max_auc,
    }
