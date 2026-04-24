"""Tests for Phase 1.6b sequential features + stationarity helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agentic_forex.features.sequential import (
    SEQUENTIAL_FEATURE_NAMES,
    add_sequential_features,
)
from agentic_forex.ml.stationarity import (
    StationarityVerdict,
    assess,
    assess_features,
    benjamini_hochberg,
    normalize_non_stationary_inplace,
    rolling_zscore,
)


def _seed_frame(n: int = 600, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        {
            "ret_1": rng.normal(0, 1e-4, n),
            "momentum_12": rng.normal(0, 1e-3, n),
            "volatility_20": np.abs(rng.normal(1e-4, 5e-5, n)),
            "intrabar_range_pips": np.abs(rng.normal(2.0, 0.5, n)),
            "rsi_14": rng.uniform(20, 80, n),
        }
    )
    return df


# ---------------------------------------------------------------------------
# Sequential features
# ---------------------------------------------------------------------------


class TestSequentialFeatures:
    def test_all_six_columns_added(self):
        df = _seed_frame(n=300, seed=1)
        out = add_sequential_features(df.copy())
        for col in SEQUENTIAL_FEATURE_NAMES:
            assert col in out.columns, f"missing {col}"

    def test_no_nans(self):
        df = _seed_frame(n=300, seed=2)
        out = add_sequential_features(df.copy())
        for col in SEQUENTIAL_FEATURE_NAMES:
            assert out[col].isna().sum() == 0, f"{col} has NaNs"

    def test_deterministic(self):
        df = _seed_frame(n=300, seed=3)
        a = add_sequential_features(df.copy())[SEQUENTIAL_FEATURE_NAMES]
        b = add_sequential_features(df.copy())[SEQUENTIAL_FEATURE_NAMES]
        pd.testing.assert_frame_equal(a, b)

    def test_missing_columns_graceful(self):
        df = pd.DataFrame({"ret_1": [0.0] * 50})
        out = add_sequential_features(df.copy())
        for col in SEQUENTIAL_FEATURE_NAMES:
            assert col in out.columns


# ---------------------------------------------------------------------------
# Stationarity
# ---------------------------------------------------------------------------


class TestStationarity:
    def test_white_noise_is_stationary(self):
        rng = np.random.default_rng(0)
        s = pd.Series(rng.normal(0, 1, 1000))
        v = assess(s, "wn")
        # White noise: ADF rejects (low p), KPSS does not reject (high p).
        assert v.is_stationary is True

    def test_random_walk_is_non_stationary(self):
        rng = np.random.default_rng(0)
        s = pd.Series(np.cumsum(rng.normal(0, 1, 500)))
        v = assess(s, "rw")
        # Random walk: ADF cannot reject (high p) -> not stationary.
        assert v.is_stationary is False

    def test_assess_features_returns_one_per_feature(self):
        df = _seed_frame(n=400, seed=7)
        out = add_sequential_features(df.copy())
        verdicts = assess_features(out, SEQUENTIAL_FEATURE_NAMES)
        assert len(verdicts) == 6
        names = [v.feature for v in verdicts]
        assert names == SEQUENTIAL_FEATURE_NAMES


class TestRollingZScore:
    def test_clipped_and_no_nans(self):
        rng = np.random.default_rng(0)
        s = pd.Series(rng.normal(0, 1, 500))
        z = rolling_zscore(s, window=50)
        assert z.isna().sum() == 0
        assert z.abs().max() <= 5.0

    def test_normalize_non_stationary_inplace_modifies_only_flagged(self):
        df = pd.DataFrame({"a": np.cumsum(np.ones(400)), "b": np.random.default_rng(0).normal(0, 1, 400)})
        verdicts = [
            StationarityVerdict("a", 1.0, 0.0, False),
            StationarityVerdict("b", 0.001, 0.5, True),
        ]
        before_a = df["a"].copy()
        before_b = df["b"].copy()
        normalized = normalize_non_stationary_inplace(df, verdicts, window=50)
        assert normalized == ["a"]
        assert not df["a"].equals(before_a)
        pd.testing.assert_series_equal(df["b"], before_b)


# ---------------------------------------------------------------------------
# Benjamini-Hochberg FDR
# ---------------------------------------------------------------------------


class TestBenjaminiHochberg:
    def test_all_significant_at_low_p(self):
        # p=[0.001, 0.002, 0.003, 0.004, 0.005, 0.006] all clearly below q=0.10
        rejected = benjamini_hochberg([0.001, 0.002, 0.003, 0.004, 0.005, 0.006], q=0.10)
        assert all(rejected)

    def test_none_significant_at_high_p(self):
        rejected = benjamini_hochberg([0.5, 0.6, 0.7, 0.8, 0.9, 0.95], q=0.10)
        assert not any(rejected)

    def test_empty_input(self):
        assert benjamini_hochberg([], q=0.10) == []

    def test_step_up_property_rejects_largest_below_threshold(self):
        # Standard BH example: m=4, q=0.20 -> ranks: p1=0.01, p2=0.04, p3=0.05, p4=0.20
        # Thresholds k/m * q = 0.05, 0.10, 0.15, 0.20.
        # Largest k with p <= k/m*q: k=4 (0.20<=0.20). So reject all 4.
        rejected = benjamini_hochberg([0.01, 0.04, 0.05, 0.20], q=0.20)
        assert all(rejected)
