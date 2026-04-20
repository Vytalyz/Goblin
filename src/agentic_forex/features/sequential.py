"""Phase 1.6b — Six hand-crafted sequential features.

These extend the Phase 1.6 baseline feature set (11 features) to 17,
without introducing torch. Each feature is a deterministic rolling-window
transform of existing OHLC/feature columns.

Per plan section 6: a primary endpoint (aggregate PF lift across all 6)
is pre-registered in the Decision Log; per-feature secondaries are
checked with BH-FDR at q=0.10. ADF/KPSS stationarity tests run via
``ml/stationarity.py`` and any flagged feature gets rolling-z-score
normalization at the runner layer.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SEQUENTIAL_FEATURE_NAMES: list[str] = [
    "momentum_acceleration",
    "vol_of_vol_5",
    "range_compression_ratio",
    "rsi_slope_10",
    "realized_skew_20",
    "realized_kurt_20",
]


def _safe_div(num: pd.Series, den: pd.Series) -> pd.Series:
    return num / den.replace(0, 1e-9)


def add_sequential_features(data: pd.DataFrame) -> pd.DataFrame:
    """Append the 6 sequential features in-place-style; returns ``data``.

    All features are computed from columns produced by
    ``features.service.build_features``: ``momentum_12``, ``volatility_20``,
    ``intrabar_range_pips``, ``range_width_10_pips``, ``rsi_14``, ``ret_1``.
    Missing columns are filled with zeros so the function never crashes.
    """
    out = data
    # 1. momentum_acceleration: change in momentum over 5 bars (jerk-like).
    if "momentum_12" in out.columns:
        out["momentum_acceleration"] = out["momentum_12"].diff(5).fillna(0.0)
    else:
        out["momentum_acceleration"] = 0.0

    # 2. vol_of_vol_5: rolling std of volatility_20 over 5 bars.
    if "volatility_20" in out.columns:
        out["vol_of_vol_5"] = out["volatility_20"].rolling(5).std().bfill().fillna(0.0)
    else:
        out["vol_of_vol_5"] = 0.0

    # 3. range_compression_ratio: current intrabar range / 20-bar mean intrabar range.
    if "intrabar_range_pips" in out.columns:
        mean20 = out["intrabar_range_pips"].rolling(20).mean().bfill()
        out["range_compression_ratio"] = _safe_div(
            out["intrabar_range_pips"], mean20
        ).clip(lower=0.0, upper=10.0).fillna(1.0)
    else:
        out["range_compression_ratio"] = 1.0

    # 4. rsi_slope_10: 10-bar slope of RSI-14 (linear-fit gradient via diff/10).
    if "rsi_14" in out.columns:
        out["rsi_slope_10"] = out["rsi_14"].diff(10).fillna(0.0) / 10.0
    else:
        out["rsi_slope_10"] = 0.0

    # 5. realized_skew_20: rolling 20-bar skew of 1-bar returns.
    if "ret_1" in out.columns:
        out["realized_skew_20"] = (
            out["ret_1"].rolling(20).skew().fillna(0.0).clip(-10.0, 10.0)
        )
    else:
        out["realized_skew_20"] = 0.0

    # 6. realized_kurt_20: rolling 20-bar excess kurtosis of 1-bar returns.
    if "ret_1" in out.columns:
        out["realized_kurt_20"] = (
            out["ret_1"].rolling(20).kurt().fillna(0.0).clip(-10.0, 50.0)
        )
    else:
        out["realized_kurt_20"] = 0.0

    return out


__all__ = ["SEQUENTIAL_FEATURE_NAMES", "add_sequential_features"]
