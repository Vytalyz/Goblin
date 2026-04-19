"""Tests for ML-P1 components: CMA-ES optimizer, GMM regime classifier,
XGBoost signal filter, SHAP interpretability, MT5 feature alignment."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_feature_df(n: int = 400, *, seed: int = 42) -> pd.DataFrame:
    """Return a synthetic DataFrame with all regime + training features."""
    rng = np.random.RandomState(seed)
    return pd.DataFrame({
        "ret_1": rng.randn(n) * 0.01,
        "ret_5": rng.randn(n) * 0.02,
        "zscore_10": rng.randn(n),
        "momentum_12": rng.randn(n) * 0.5,
        "volatility_20": np.abs(rng.randn(n)) * 0.01 + 0.005,
        "intrabar_range_pips": rng.uniform(1, 10, n),
        "range_position_10": rng.uniform(0, 1, n),
        "spread_to_range_10": rng.uniform(0.01, 0.5, n),
        "spread_pips": rng.uniform(0.5, 3.0, n),
        "hour": rng.randint(0, 24, n).astype(float),
    })


# ---------------------------------------------------------------------------
# P1.3 — CMA-ES optimizer data classes
# ---------------------------------------------------------------------------

class TestOptimizerBounds:
    def test_bounds_lower_upper(self):
        from agentic_forex.ml.optimizer import OptimizerBounds

        bounds = OptimizerBounds()
        lo = bounds.lower()
        hi = bounds.upper()
        assert len(lo) == 4
        assert len(hi) == 4
        for l, h in zip(lo, hi):
            assert l < h

    def test_midpoint_within_bounds(self):
        from agentic_forex.ml.optimizer import OptimizerBounds

        bounds = OptimizerBounds()
        mid = bounds.midpoint()
        lo = bounds.lower()
        hi = bounds.upper()
        for m, l, h in zip(mid, lo, hi):
            assert l <= m <= h

    def test_decode_individual_clips(self):
        from agentic_forex.ml.optimizer import OptimizerBounds, _decode_individual

        bounds = OptimizerBounds(
            stop_loss_pips=(10.0, 40.0),
            take_profit_pips=(10.0, 80.0),
            signal_threshold=(0.4, 0.8),
            holding_bars=(10, 60),
        )
        # Values outside bounds should be clipped
        raw = np.array([5.0, 100.0, 0.1, 200.0])
        params = _decode_individual(raw, bounds)
        assert params["stop_loss_pips"] == 10.0
        assert params["take_profit_pips"] == 80.0
        assert params["signal_threshold"] == 0.40
        assert params["holding_bars"] == 60

    def test_decode_individual_rounds_holding_bars(self):
        from agentic_forex.ml.optimizer import OptimizerBounds, _decode_individual

        bounds = OptimizerBounds()
        raw = np.array([20.0, 50.0, 0.55, 37.6])
        params = _decode_individual(raw, bounds)
        assert isinstance(params["holding_bars"], int)
        assert params["holding_bars"] == 38


# ---------------------------------------------------------------------------
# P1.5 — GMM regime classifier
# ---------------------------------------------------------------------------

class TestGMMRegime:
    def test_fit_and_predict(self):
        from agentic_forex.ml.regime import fit_regime_classifier, predict_regime_labels

        data = _make_feature_df(200)
        gmm = fit_regime_classifier(data, n_components=3)
        labels = predict_regime_labels(gmm, data)
        assert len(labels) == len(data)
        unique = set(labels.unique())
        # All labels should be in {0, 1, 2} (3 components)
        assert unique <= {0, 1, 2}

    def test_predict_handles_nan_rows(self):
        from agentic_forex.ml.regime import fit_regime_classifier, predict_regime_labels

        data = _make_feature_df(200)
        gmm = fit_regime_classifier(data, n_components=3)
        # Inject NaN in a subset of rows
        dirty = data.copy()
        dirty.loc[0:9, "volatility_20"] = np.nan
        labels = predict_regime_labels(gmm, dirty)
        # NaN rows should get -1
        assert all(labels.iloc[0:10] == -1)
        # Non-NaN rows should have valid labels
        assert all(labels.iloc[10:] >= 0)

    def test_stability_score_structure(self):
        from agentic_forex.ml.regime import regime_stability_score

        data = _make_feature_df(300)
        result = regime_stability_score(data, n_components=3, n_windows=3)
        assert "agreement" in result
        assert "stable" in result
        assert "window_count" in result
        assert result["window_count"] == 3

    def test_stability_score_insufficient_data(self):
        from agentic_forex.ml.regime import regime_stability_score

        data = _make_feature_df(10)
        result = regime_stability_score(data, n_components=3, n_windows=3)
        assert result["stable"] is False
        assert result["window_count"] == 0

    def test_add_regime_label(self):
        from unittest.mock import MagicMock

        from agentic_forex.ml.regime import add_regime_label

        data = _make_feature_df(200)
        mock_settings = MagicMock()
        mock_settings.regime_classifier.n_components_range = [3, 5]
        result = add_regime_label(data, mock_settings)
        assert "regime_label" in result.columns
        assert len(result) == len(data)


# ---------------------------------------------------------------------------
# P1.7 / P1.8 — XGBoost + SHAP
# ---------------------------------------------------------------------------

class TestXGBoostSHAP:
    def test_shap_values_structure(self):
        import xgboost as xgb

        from agentic_forex.ml.train import _compute_shap_values

        rng = np.random.RandomState(42)
        X = pd.DataFrame({
            "feat_a": rng.randn(100),
            "feat_b": rng.randn(100),
            "feat_c": rng.randn(100),
        })
        y = (rng.rand(100) > 0.5).astype(int)
        clf = xgb.XGBClassifier(n_estimators=10, random_state=42, verbosity=0)
        clf.fit(X, y)

        sv = _compute_shap_values(clf, X)
        assert isinstance(sv, dict)
        assert set(sv.keys()) == {"feat_a", "feat_b", "feat_c"}
        for v in sv.values():
            assert isinstance(v, float)
            assert v >= 0

    def test_feature_columns_includes_regime_label(self):
        from agentic_forex.ml.train import FEATURE_COLUMNS

        assert "regime_label" in FEATURE_COLUMNS


# ---------------------------------------------------------------------------
# P1.9 — MT5 feature alignment
# ---------------------------------------------------------------------------

class TestMT5FeatureAlignment:
    def test_identical_feeds_pass(self):
        from agentic_forex.evals.robustness import mt5_feature_alignment_test

        data = _make_feature_df(200)
        result = mt5_feature_alignment_test(data, data)
        assert result["passed"] is True
        # AUC should be near 0.5 for identical data
        assert result["auc"] <= 0.65

    def test_different_feeds_fail(self):
        from agentic_forex.evals.robustness import mt5_feature_alignment_test

        rng = np.random.RandomState(42)
        oanda = _make_feature_df(200, seed=42)
        # Create systematically different MT5 data
        mt5 = oanda.copy()
        mt5["volatility_20"] = mt5["volatility_20"] + 0.1
        mt5["spread_pips"] = mt5["spread_pips"] * 3
        result = mt5_feature_alignment_test(oanda, mt5, max_auc=0.60)
        # Should detect the difference
        assert result["auc"] > 0.60
        assert result["passed"] is False

    def test_insufficient_data_passes(self):
        from agentic_forex.evals.robustness import mt5_feature_alignment_test

        data = _make_feature_df(10)
        result = mt5_feature_alignment_test(data, data)
        assert result["passed"] is True
        assert "insufficient" in result.get("note", "")
