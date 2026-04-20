"""Phase 1.6 — Baseline Evidence Foundation runner.

Computes XGB-vs-rule profit-factor lift across pre-registered stratified
candidates, broken out by regime and swept across transaction-cost
shocks. Uses the purged walk-forward CV with embargo from
``ml.train`` (D11 enforcement).

This module is numpy/pandas/xgboost only — no torch import (without-torch
CI lane stays green through Phase 1.7).
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
import xgboost as xgb

from agentic_forex.features.service import build_features
from agentic_forex.governance.errors import (
    CostSensitivityError,
    DatasetSHAMismatchError,
    RegimeNonNegativityError,
)
from agentic_forex.labels.service import build_labels
from agentic_forex.ml.train import _purged_walk_forward_folds
from agentic_forex.ml.variance_pilot import LOCKED_XGB_HPARAMS

# ---------------------------------------------------------------------------
# Config / constants
# ---------------------------------------------------------------------------

BASELINE_FEATURE_COLUMNS: list[str] = [
    "ret_1",
    "ret_5",
    "zscore_10",
    "momentum_12",
    "volatility_20",
    "intrabar_range_pips",
    "range_position_10",
    "spread_to_range_10",
    "spread_pips",
    "hour",
    "regime_label",
]

DEFAULT_COST_SHOCKS_PIPS: tuple[float, ...] = (0.0, 0.5, 1.0, 2.0)


@dataclass(frozen=True)
class RegimeDefinition:
    """A regime is a label assigned to each bar based on simple,
    auditable thresholds (no black box). Used for Phase 1.6 regime
    non-negativity gate (D14).
    """

    regime_id: str
    description: str


REGIMES: tuple[RegimeDefinition, ...] = (
    RegimeDefinition("trend_high_vol", "|momentum_12| above median AND volatility_20 above median"),
    RegimeDefinition("trend_low_vol",  "|momentum_12| above median AND volatility_20 below median"),
    RegimeDefinition("range_high_vol", "|momentum_12| below median AND volatility_20 above median"),
    RegimeDefinition("range_low_vol",  "|momentum_12| below median AND volatility_20 below median"),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def assert_dataset_sha(parquet_path: Path, expected_sha: str) -> None:
    """Raise if working-tree parquet SHA does not match Decision-Log pin."""
    actual = file_sha256(parquet_path)
    if actual != expected_sha:
        raise DatasetSHAMismatchError(
            f"Dataset SHA mismatch for {parquet_path}: "
            f"expected {expected_sha!r}, got {actual!r}"
        )


def profit_factor(outcomes_pips: np.ndarray) -> float:
    """Profit factor: sum(positives) / |sum(negatives)|.

    Returns 0.0 if no trades. Clips to 10.0 if no losing trades.
    Same convention as ``variance_pilot._profit_factor``.
    """
    if outcomes_pips.size == 0:
        return 0.0
    wins = outcomes_pips[outcomes_pips > 0].sum()
    losses = outcomes_pips[outcomes_pips < 0].sum()
    if losses == 0.0:
        return 10.0 if wins > 0 else 0.0
    return float(wins / abs(losses))


def assign_regimes(dataset: pd.DataFrame) -> pd.Series:
    """Return a regime_id Series indexed like ``dataset``.

    Splits each bar into one of four regimes by the median of
    ``|momentum_12|`` and ``volatility_20``. Median splits are
    auditable, deterministic, and require no fitted model.
    """
    abs_mom = dataset["momentum_12"].abs()
    vol = dataset["volatility_20"]
    mom_med = float(abs_mom.median())
    vol_med = float(vol.median())

    is_trend = abs_mom > mom_med
    is_high_vol = vol > vol_med

    regime = pd.Series(index=dataset.index, dtype="object")
    regime[is_trend & is_high_vol] = "trend_high_vol"
    regime[is_trend & ~is_high_vol] = "trend_low_vol"
    regime[~is_trend & is_high_vol] = "range_high_vol"
    regime[~is_trend & ~is_high_vol] = "range_low_vol"
    return regime


def rule_baseline_signal(dataset: pd.DataFrame) -> np.ndarray:
    """Heuristic rule baseline: long when ret_5 >= 0, short otherwise.

    Returns an array of +1/-1 the same length as ``dataset``. Used as
    the no-ML comparison so the XGB lift measures the value-add of
    the model over a trivial momentum rule.
    """
    return np.where(dataset["ret_5"].to_numpy() >= 0.0, 1, -1)


def xgb_signal(model: xgb.XGBClassifier, X: pd.DataFrame) -> np.ndarray:
    proba = model.predict_proba(X)[:, 1]
    return np.where(proba >= 0.5, 1, -1)


def _outcome_pips(dataset: pd.DataFrame, side: np.ndarray) -> np.ndarray:
    """Realized pips per trade given trade direction (+1/-1).

    Uses the long_outcome_pips column; flips sign for shorts. This is
    the same convention the variance pilot uses.
    """
    long_pips = dataset["long_outcome_pips"].to_numpy()
    return long_pips * side


# ---------------------------------------------------------------------------
# Per-candidate evaluation
# ---------------------------------------------------------------------------


def evaluate_candidate(
    dataset: pd.DataFrame,
    *,
    feature_cols: Sequence[str],
    candidate_id: str,
    n_folds: int,
    embargo_bars: int,
    cost_shocks_pips: Sequence[float],
    seed: int = 42,
) -> dict:
    """Run XGB-vs-rule comparison on a single candidate's labelled
    dataset. Returns a dict matching ``CandidateBaselineResult``.
    """
    folds = _purged_walk_forward_folds(
        len(dataset), n_folds=n_folds, embargo_bars=embargo_bars,
    )

    fold_xgb_pf: list[float] = []
    fold_rule_pf: list[float] = []
    fold_pf_lift: list[float] = []

    all_test_idx: list[np.ndarray] = []
    all_xgb_outcomes: list[np.ndarray] = []
    all_rule_outcomes: list[np.ndarray] = []

    feature_cols = [c for c in feature_cols if c in dataset.columns]

    for train_idx, test_idx in folds:
        train = dataset.iloc[train_idx]
        test = dataset.iloc[test_idx]
        X_train = train[feature_cols]
        y_train = train["label_up"]
        X_test = test[feature_cols]

        model = xgb.XGBClassifier(**LOCKED_XGB_HPARAMS, random_state=seed)
        model.fit(X_train, y_train)

        xgb_side = xgb_signal(model, X_test)
        rule_side = rule_baseline_signal(test)
        xgb_out = _outcome_pips(test, xgb_side)
        rule_out = _outcome_pips(test, rule_side)

        fold_xgb_pf.append(profit_factor(xgb_out))
        fold_rule_pf.append(profit_factor(rule_out))
        fold_pf_lift.append(fold_xgb_pf[-1] - fold_rule_pf[-1])

        all_test_idx.append(test_idx)
        all_xgb_outcomes.append(xgb_out)
        all_rule_outcomes.append(rule_out)

    # Aggregate
    full_xgb_out = np.concatenate(all_xgb_outcomes) if all_xgb_outcomes else np.array([])
    full_rule_out = np.concatenate(all_rule_outcomes) if all_rule_outcomes else np.array([])
    rule_pf_agg = profit_factor(full_rule_out)
    xgb_pf_agg = profit_factor(full_xgb_out)
    pf_lift_agg = xgb_pf_agg - rule_pf_agg

    # Regime breakdown
    full_test = pd.concat(
        [dataset.iloc[idx] for idx in all_test_idx], ignore_index=False
    ) if all_test_idx else dataset.iloc[0:0]
    regimes_for_test = assign_regimes(full_test)

    regime_rows: list[dict] = []
    regime_non_negative = True
    for rdef in REGIMES:
        mask = (regimes_for_test == rdef.regime_id).to_numpy()
        n = int(mask.sum())
        if n == 0:
            regime_rows.append({
                "regime_id": rdef.regime_id,
                "regime_description": rdef.description,
                "n_trades": 0,
                "rule_pf": 0.0,
                "xgb_pf": 0.0,
                "pf_lift": 0.0,
            })
            continue
        r_xgb = profit_factor(full_xgb_out[mask])
        r_rule = profit_factor(full_rule_out[mask])
        lift = r_xgb - r_rule
        if lift < 0:
            regime_non_negative = False
        regime_rows.append({
            "regime_id": rdef.regime_id,
            "regime_description": rdef.description,
            "n_trades": n,
            "rule_pf": r_rule,
            "xgb_pf": r_xgb,
            "pf_lift": lift,
        })

    # Cost-sensitivity sweep
    cost_rows: list[dict] = []
    cost_persistent_at_1pip = True
    for cost in cost_shocks_pips:
        # Apply cost as a per-trade pip subtraction in the trade direction:
        # outcome_after_cost = outcome - cost  (cost is always a drag on PF)
        xgb_after = full_xgb_out - cost
        rule_after = full_rule_out - cost
        r_xgb = profit_factor(xgb_after)
        r_rule = profit_factor(rule_after)
        lift = r_xgb - r_rule
        cost_rows.append({
            "cost_pips": float(cost),
            "rule_pf": r_rule,
            "xgb_pf": r_xgb,
            "pf_lift": lift,
        })
        if math.isclose(cost, 1.0, abs_tol=1e-9) and lift <= 0:
            cost_persistent_at_1pip = False

    return {
        "candidate_id": candidate_id,
        "n_trades_total": int(full_xgb_out.size),
        "rule_pf_aggregate": rule_pf_agg,
        "xgb_pf_aggregate": xgb_pf_agg,
        "pf_lift_aggregate": pf_lift_agg,
        "fold_xgb_pf": fold_xgb_pf,
        "fold_rule_pf": fold_rule_pf,
        "fold_pf_lift": fold_pf_lift,
        "regime_breakdown": regime_rows,
        "cost_sweep": cost_rows,
        "regime_non_negative": regime_non_negative,
        "cost_persistent_at_1pip": cost_persistent_at_1pip,
    }


def assert_no_torch_import() -> None:
    """Fail loudly if torch was imported during a baseline run."""
    if "torch" in sys.modules:
        raise RuntimeError(
            "torch was imported during the baseline run. The without-torch CI "
            "lane forbids torch in Phase 1.6/1.6b/1.7."
        )


def summarise_runs(
    candidate_results: list[dict],
    *,
    effect_size_floor_pf: float,
) -> dict:
    """Aggregate cross-candidate stats and gate verdict flags."""
    lifts = np.array([c["pf_lift_aggregate"] for c in candidate_results])
    fraction_above = float((lifts >= effect_size_floor_pf).mean()) if lifts.size else 0.0
    return {
        "median_pf_lift": float(np.median(lifts)) if lifts.size else 0.0,
        "mean_pf_lift": float(np.mean(lifts)) if lifts.size else 0.0,
        "fraction_above_effect_size_floor": fraction_above,
    }


def assert_gates(candidate_results: list[dict]) -> None:
    """Raise on any hard gate failure (D14)."""
    for c in candidate_results:
        if not c["regime_non_negative"]:
            offenders = [r["regime_id"] for r in c["regime_breakdown"] if r["pf_lift"] < 0]
            raise RegimeNonNegativityError(
                f"{c['candidate_id']}: PF lift negative in regimes {offenders}"
            )
        if not c["cost_persistent_at_1pip"]:
            raise CostSensitivityError(
                f"{c['candidate_id']}: PF lift does not persist at +1.0 pip cost"
            )


__all__ = [
    "BASELINE_FEATURE_COLUMNS",
    "DEFAULT_COST_SHOCKS_PIPS",
    "REGIMES",
    "RegimeDefinition",
    "assert_dataset_sha",
    "assert_gates",
    "assert_no_torch_import",
    "assign_regimes",
    "evaluate_candidate",
    "file_sha256",
    "profit_factor",
    "rule_baseline_signal",
    "summarise_runs",
    "xgb_signal",
]
