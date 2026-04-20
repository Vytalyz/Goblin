"""Phase 1.6b stationarity helpers (ADF + KPSS + BH-FDR + rolling z-score).

ADF null   : series HAS a unit root  (i.e. NOT stationary). Reject -> stationary.
KPSS null  : series IS stationary.                          Reject -> non-stationary.

Combined verdict per plan section 6:
    stationary if ADF rejects (p<0.05) AND KPSS does NOT reject (p>=0.05)
A feature flagged as non-stationary gets rolling-z-score normalization
before model training.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class StationarityVerdict:
    feature: str
    adf_pvalue: float
    kpss_pvalue: float
    is_stationary: bool

    def to_dict(self) -> dict:
        return {
            "feature": self.feature,
            "adf_pvalue": float(self.adf_pvalue),
            "kpss_pvalue": float(self.kpss_pvalue),
            "is_stationary": bool(self.is_stationary),
        }


def adf_pvalue(series: pd.Series, *, max_n: int = 5000) -> float:
    """Return the ADF p-value. Sub-samples to ``max_n`` rows for speed.

    Returns 1.0 (i.e. fail to reject unit root) on numerical failure so
    the caller treats the feature as non-stationary by default.
    """
    from statsmodels.tsa.stattools import adfuller

    s = series.dropna().astype(float)
    if len(s) < 30:
        return 1.0
    if len(s) > max_n:
        s = s.iloc[-max_n:]
    try:
        result = adfuller(s.values, autolag="AIC")
        return float(result[1])
    except Exception:
        return 1.0


def kpss_pvalue(series: pd.Series, *, max_n: int = 5000) -> float:
    """Return the KPSS p-value (level-stationarity null).

    Returns 0.0 (i.e. reject stationary null) on numerical failure so the
    caller treats the feature as non-stationary by default.
    """
    from statsmodels.tsa.stattools import kpss

    s = series.dropna().astype(float)
    if len(s) < 30:
        return 0.0
    if len(s) > max_n:
        s = s.iloc[-max_n:]
    try:
        # KPSS prints an InterpolationWarning on extreme p-values; suppressed by caller.
        result = kpss(s.values, regression="c", nlags="auto")
        return float(result[1])
    except Exception:
        return 0.0


def assess(series: pd.Series, name: str) -> StationarityVerdict:
    adf_p = adf_pvalue(series)
    kpss_p = kpss_pvalue(series)
    is_stat = (adf_p < 0.05) and (kpss_p >= 0.05)
    return StationarityVerdict(name, adf_p, kpss_p, is_stat)


def assess_features(data: pd.DataFrame, features: list[str]) -> list[StationarityVerdict]:
    import warnings
    verdicts: list[StationarityVerdict] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for f in features:
            if f not in data.columns:
                verdicts.append(StationarityVerdict(f, 1.0, 0.0, False))
                continue
            verdicts.append(assess(data[f], f))
    return verdicts


def rolling_zscore(series: pd.Series, window: int = 200) -> pd.Series:
    """Rolling-window z-score: (x - mean_w) / std_w. Clipped to +-5 to
    keep the fitted XGB happy. NaNs at the warm-up are filled with 0.
    """
    mean = series.rolling(window, min_periods=10).mean()
    std = series.rolling(window, min_periods=10).std().replace(0, 1e-9)
    z = (series - mean) / std
    return z.fillna(0.0).clip(-5.0, 5.0)


def normalize_non_stationary_inplace(
    data: pd.DataFrame, verdicts: list[StationarityVerdict], window: int = 200,
) -> list[str]:
    """Rolling-z-score-normalize any non-stationary feature in place.
    Returns the list of feature names that were normalized.
    """
    normalized: list[str] = []
    for v in verdicts:
        if not v.is_stationary and v.feature in data.columns:
            data[v.feature] = rolling_zscore(data[v.feature], window=window)
            normalized.append(v.feature)
    return normalized


def benjamini_hochberg(pvalues: list[float], q: float = 0.10) -> list[bool]:
    """Return a list of booleans (same order as ``pvalues``) indicating
    which hypotheses are rejected under BH-FDR at level ``q``.

    Implementation follows the standard step-up procedure.
    """
    m = len(pvalues)
    if m == 0:
        return []
    indexed = sorted(enumerate(pvalues), key=lambda t: t[1])
    threshold_idx = -1
    for k, (_orig_idx, p) in enumerate(indexed, start=1):
        if p <= (k / m) * q:
            threshold_idx = k
    rejected = [False] * m
    if threshold_idx > 0:
        for k, (orig_idx, _p) in enumerate(indexed, start=1):
            if k <= threshold_idx:
                rejected[orig_idx] = True
    return rejected


__all__ = [
    "StationarityVerdict",
    "adf_pvalue",
    "assess",
    "assess_features",
    "benjamini_hochberg",
    "kpss_pvalue",
    "normalize_non_stationary_inplace",
    "rolling_zscore",
]
