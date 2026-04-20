"""Phase 1.6.0 — Variance Pilot.

Measures σ_PF across multiple XGBoost seeds × candidates using the
existing purged walk-forward CV helper, so the downstream phases
(1.6 baseline, 1.6b sequential probe, 2.x ML-P2) can lock their
MDE and effect-size floor to a number grounded in observed noise
rather than a guess.

This module is deliberately numpy/scipy/xgboost only. Importing
torch here would break the without-torch CI lane (Phase 1.7 / D7).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd
import xgboost as xgb

# Locked XGBoost hyperparameters for baseline comparability (plan §1,
# decision in Revision 3 §13: "Locked HPs for baseline comparability").
# Do not tune these inside the pilot — the whole point is to measure
# seed-induced variance holding HPs constant.
#
# ``subsample`` and ``colsample_bytree`` are deliberately < 1.0 so the
# ``random_state`` argument actually produces seed-dependent fits.
# Without these two, XGBoost training on a fixed dataset is effectively
# deterministic regardless of seed and the pilot would falsely report
# σ_PF ≈ 0.
LOCKED_XGB_HPARAMS: dict[str, object] = {
    "n_estimators": 100,
    "max_leaves": 31,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "eval_metric": "logloss",
    "verbosity": 0,
}

# Standard normal critical values used in the required-n calculation.
# α = 0.01 (two-sided → one-sided z = 2.326), power = 0.8 → z_β = 0.842.
Z_ALPHA_001 = 2.3263478740408408
Z_BETA_080 = 0.8416212335729143


@dataclass(frozen=True)
class SeedOutcome:
    """Result of training XGBoost with a single seed on a single candidate."""

    candidate_id: str
    seed: int
    fold_profit_factors: tuple[float, ...]
    aggregate_profit_factor: float
    trade_count: int


@dataclass(frozen=True)
class PilotSummary:
    """Aggregate statistics across all (candidate, seed) pairs."""

    sigma_pf: float
    mean_pf: float
    mde_pf: float
    effect_size_floor_pf: float
    required_n_candidates: int
    n_candidates: int
    n_seeds: int


def _purged_folds(
    n_samples: int,
    *,
    n_folds: int = 3,
    embargo_bars: int = 10,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Minimal copy of `train._purged_walk_forward_folds` to keep the
    variance pilot self-contained and side-effect free."""
    if n_samples < n_folds * 2:
        split = max(int(n_samples * 0.7), 1)
        return [(np.arange(split), np.arange(split, n_samples))]
    fold_size = n_samples // (n_folds + 1)
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for i in range(n_folds):
        train_end = fold_size * (i + 1)
        test_start = train_end + embargo_bars
        test_end = min(train_end + fold_size, n_samples)
        if test_start >= test_end:
            continue
        folds.append((np.arange(train_end), np.arange(test_start, test_end)))
    if not folds:
        split = max(int(n_samples * 0.7), 1)
        folds.append(
            (np.arange(split), np.arange(min(split + embargo_bars, n_samples), n_samples))
        )
    return folds


def _profit_factor(outcomes_pips: np.ndarray) -> float:
    """Profit factor = sum(positive outcomes) / |sum(negative outcomes)|.

    Returns 0.0 if there are no trades. Clips to 10.0 if there are
    no losing trades so the statistic remains finite and bounded.
    """
    if outcomes_pips.size == 0:
        return 0.0
    wins = outcomes_pips[outcomes_pips > 0].sum()
    losses = outcomes_pips[outcomes_pips < 0].sum()
    if losses == 0.0:
        return 10.0 if wins > 0 else 0.0
    return float(wins / abs(losses))


def run_seed(
    dataset: pd.DataFrame,
    *,
    feature_cols: Sequence[str],
    label_col: str,
    outcome_col: str,
    candidate_id: str,
    seed: int,
    n_folds: int = 3,
    embargo_bars: int = 10,
) -> SeedOutcome:
    """Train XGBoost with `seed` on the purged walk-forward folds of
    `dataset` and return the OOS profit factor aggregated across folds.

    Parameters
    ----------
    dataset:
        DataFrame containing at minimum `feature_cols`, `label_col`
        (binary 0/1), and `outcome_col` (signed realized pips per trade).
    feature_cols / label_col / outcome_col:
        Column names into `dataset`.
    seed:
        Random seed — the only stochastic input the pilot varies.
    """
    folds = _purged_folds(
        len(dataset), n_folds=n_folds, embargo_bars=embargo_bars
    )
    fold_pfs: list[float] = []
    all_outcomes: list[np.ndarray] = []

    for train_idx, test_idx in folds:
        train = dataset.iloc[train_idx]
        test = dataset.iloc[test_idx]

        clf = xgb.XGBClassifier(random_state=seed, **LOCKED_XGB_HPARAMS)
        clf.fit(train[list(feature_cols)], train[label_col])
        proba = clf.predict_proba(test[list(feature_cols)])[:, 1]

        # Long-only entries when predicted probability ≥ 0.5.
        mask = proba >= 0.5
        outcomes = test.loc[mask, outcome_col].to_numpy(dtype="float64")
        outcomes = outcomes[~np.isnan(outcomes)]
        fold_pfs.append(_profit_factor(outcomes))
        all_outcomes.append(outcomes)

    aggregate = _profit_factor(
        np.concatenate(all_outcomes) if all_outcomes else np.empty(0)
    )
    trade_count = int(sum(a.size for a in all_outcomes))
    return SeedOutcome(
        candidate_id=candidate_id,
        seed=seed,
        fold_profit_factors=tuple(fold_pfs),
        aggregate_profit_factor=aggregate,
        trade_count=trade_count,
    )


def summarise(
    outcomes: Sequence[SeedOutcome],
    *,
    mde_multiplier: float = 1.0,
    floor_multiplier: float = 1.0,
) -> PilotSummary:
    """Compute σ_PF, MDE, effect-size floor, and required-n.

    Parameters
    ----------
    mde_multiplier:
        MDE = mde_multiplier × σ_PF. Default 1.0 (detect a one-sigma
        deviation at α=0.01, power=0.8).
    floor_multiplier:
        effect_size_floor = floor_multiplier × σ_PF. Default 1.0 so
        the floor never sits inside the noise band.
    """
    if not outcomes:
        raise ValueError("summarise() requires at least one SeedOutcome.")

    pfs = np.array([o.aggregate_profit_factor for o in outcomes], dtype="float64")
    # ddof=1 for sample standard deviation — we are estimating σ_PF
    # from a finite sample of (candidate, seed) pairs, not the
    # population variance.
    sigma = float(pfs.std(ddof=1)) if pfs.size > 1 else 0.0
    mean_pf = float(pfs.mean())

    mde = mde_multiplier * sigma
    floor = floor_multiplier * sigma

    # One-sample one-sided power formula:
    # n ≥ ((z_α + z_β) · σ / MDE)²
    # With MDE = k · σ this collapses to ((z_α + z_β) / k)².
    if mde > 0.0:
        required_n = int(math.ceil(((Z_ALPHA_001 + Z_BETA_080) * sigma / mde) ** 2))
    else:
        required_n = 0

    n_candidates = len({o.candidate_id for o in outcomes})
    n_seeds = len({o.seed for o in outcomes})

    return PilotSummary(
        sigma_pf=sigma,
        mean_pf=mean_pf,
        mde_pf=mde,
        effect_size_floor_pf=floor,
        required_n_candidates=required_n,
        n_candidates=n_candidates,
        n_seeds=n_seeds,
    )


def assert_no_torch_import() -> None:
    """Fail loudly if torch ended up in sys.modules during pilot execution.

    Phase 1.7 / D7 requires the without-torch CI lane to stay green at
    this phase's test count. Some scipy / statsmodels codepaths transitively
    pull torch; this guard exists so a regression is caught at the pilot
    boundary rather than at CI-matrix time.
    """
    import sys

    if "torch" in sys.modules:
        raise RuntimeError(
            "torch was imported during the variance pilot; "
            "Phase 1.6.0 must remain on the without-torch CI lane."
        )
