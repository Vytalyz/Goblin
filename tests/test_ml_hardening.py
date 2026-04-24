"""Tests for ML-P0 hardening gates: purged CV, feature importance,
label randomization, adversarial validation, and model persistence."""

from __future__ import annotations

import numpy as np
import pandas as pd

from agentic_forex.ml.train import (
    FEATURE_COLUMNS,
    _adversarial_validation,
    _compute_feature_importance,
    _feature_set_hash,
    _label_randomization_test,
    _purged_walk_forward_folds,
    _top_k_importance_share,
)

# ---------------------------------------------------------------------------
# P0.1 / P0.2 — Purged walk-forward CV with embargo
# ---------------------------------------------------------------------------


class TestPurgedWalkForwardFolds:
    def test_basic_fold_structure(self):
        folds = _purged_walk_forward_folds(400, n_folds=3, embargo_bars=10)
        assert len(folds) == 3
        for train_idx, test_idx in folds:
            assert len(train_idx) > 0
            assert len(test_idx) > 0
            # Embargo: test starts at least embargo_bars after train ends
            assert test_idx[0] >= train_idx[-1] + 10

    def test_no_overlap_between_train_and_test(self):
        folds = _purged_walk_forward_folds(400, n_folds=3, embargo_bars=10)
        for train_idx, test_idx in folds:
            overlap = set(train_idx) & set(test_idx)
            assert len(overlap) == 0

    def test_embargo_gap_respected(self):
        folds = _purged_walk_forward_folds(500, n_folds=3, embargo_bars=20)
        for train_idx, test_idx in folds:
            gap = test_idx[0] - train_idx[-1]
            assert gap >= 20

    def test_small_dataset_degenerates_to_single_split(self):
        folds = _purged_walk_forward_folds(5, n_folds=3, embargo_bars=10)
        assert len(folds) == 1
        train_idx, test_idx = folds[0]
        assert len(train_idx) + len(test_idx) <= 5

    def test_folds_are_anchored(self):
        """Each fold's train starts from index 0."""
        folds = _purged_walk_forward_folds(400, n_folds=3, embargo_bars=10)
        for train_idx, _ in folds:
            assert train_idx[0] == 0


# ---------------------------------------------------------------------------
# P0.3 — Feature importance
# ---------------------------------------------------------------------------


def _make_synthetic_data(n_samples: int = 200) -> tuple[pd.DataFrame, pd.Series]:
    rng = np.random.RandomState(42)
    X = pd.DataFrame(rng.randn(n_samples, len(FEATURE_COLUMNS)), columns=FEATURE_COLUMNS)
    y = pd.Series((X["ret_1"] > 0).astype(int), name="label_up")
    return X, y


class TestFeatureImportance:
    def test_importance_keys_match_features(self):
        from sklearn.ensemble import RandomForestClassifier

        X, y = _make_synthetic_data()
        model = RandomForestClassifier(n_estimators=10, random_state=42)
        model.fit(X, y)
        importance = _compute_feature_importance(model, X, y, n_repeats=3)
        assert set(importance.keys()) == set(FEATURE_COLUMNS)

    def test_top_k_importance_share_range(self):
        importance = {"a": 0.3, "b": 0.2, "c": 0.1, "d": 0.05}
        share = _top_k_importance_share(importance, k=3)
        # top 3 sum = 0.6, total = 0.65, so share ≈ 0.923
        assert 0.0 <= share <= 1.0
        assert share > 0.5

    def test_top_k_importance_share_all_zero(self):
        importance = {"a": 0.0, "b": 0.0}
        share = _top_k_importance_share(importance, k=3)
        assert share == 0.0


# ---------------------------------------------------------------------------
# P0.4 — Label randomization test
# ---------------------------------------------------------------------------


class TestLabelRandomization:
    def test_shuffled_accuracy_near_chance(self):
        X, y = _make_synthetic_data(300)
        split = 200
        result = _label_randomization_test(
            X.iloc[:split],
            y.iloc[:split],
            X.iloc[split:],
            y.iloc[split:],
        )
        assert "shuffled_accuracy" in result
        # With shuffled labels, accuracy should be near 0.5 (not great)
        assert result["shuffled_accuracy"] <= 0.75  # loose bound; conceptual check

    def test_result_has_expected_keys(self):
        X, y = _make_synthetic_data()
        split = 140
        result = _label_randomization_test(
            X.iloc[:split],
            y.iloc[:split],
            X.iloc[split:],
            y.iloc[split:],
        )
        assert "shuffled_accuracy" in result


# ---------------------------------------------------------------------------
# P0.5 — Adversarial validation
# ---------------------------------------------------------------------------


class TestAdversarialValidation:
    def test_identical_distributions_low_auc(self):
        rng = np.random.RandomState(42)
        X = pd.DataFrame(rng.randn(200, 3), columns=["a", "b", "c"])
        result = _adversarial_validation(X.iloc[:100], X.iloc[100:])
        assert "adversarial_auc" in result
        # Same distribution — AUC should be close to 0.5
        # We use a generous bound because RF can overfit on small data
        assert result["adversarial_auc"] <= 0.85

    def test_distinct_distributions_high_auc(self):
        rng = np.random.RandomState(42)
        X_train = pd.DataFrame(rng.randn(100, 3), columns=["a", "b", "c"])
        X_test = pd.DataFrame(rng.randn(100, 3) + 5, columns=["a", "b", "c"])
        result = _adversarial_validation(X_train, X_test)
        # Very different distributions — AUC should be near 1.0
        assert result["adversarial_auc"] >= 0.90


# ---------------------------------------------------------------------------
# P0.6 — Model persistence helpers
# ---------------------------------------------------------------------------


class TestModelPersistence:
    def test_feature_set_hash_deterministic(self):
        h1 = _feature_set_hash(["a", "b", "c"])
        h2 = _feature_set_hash(["a", "b", "c"])
        assert h1 == h2

    def test_feature_set_hash_order_independent(self):
        h1 = _feature_set_hash(["a", "b", "c"])
        h2 = _feature_set_hash(["c", "a", "b"])
        assert h1 == h2

    def test_feature_set_hash_changes_with_different_features(self):
        h1 = _feature_set_hash(["a", "b", "c"])
        h2 = _feature_set_hash(["a", "b", "d"])
        assert h1 != h2


# ---------------------------------------------------------------------------
# P0.7 — Config thresholds
# ---------------------------------------------------------------------------


class TestMLHardeningConfig:
    def test_settings_has_ml_hardening_section(self, settings):
        assert hasattr(settings, "ml_hardening")
        assert settings.ml_hardening.label_randomization_accuracy_ceiling == 0.55
        assert settings.ml_hardening.adversarial_auc_threshold == 0.55
        assert settings.ml_hardening.purged_cv_embargo_minimum_bars == 10
        assert settings.ml_hardening.feature_importance_top3_floor == 0.40
        assert settings.ml_hardening.model_persistence_format == "joblib"
