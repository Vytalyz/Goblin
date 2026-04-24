from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score

from agentic_forex.backtesting.engine import run_backtest, run_stress_test
from agentic_forex.config import Settings
from agentic_forex.features.service import build_features
from agentic_forex.labels.service import build_labels
from agentic_forex.utils.io import write_json
from agentic_forex.workflows.contracts import StrategySpec

FEATURE_COLUMNS: list[str] = [
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


# ---------------------------------------------------------------------------
# Purged walk-forward CV  (P0.1 / P0.2)
# ---------------------------------------------------------------------------


def _purged_walk_forward_folds(
    n_samples: int,
    *,
    n_folds: int = 3,
    embargo_bars: int = 10,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Return (train_idx, test_idx) arrays with an embargo gap between them.

    Each fold is anchored: the test window slides forward while the train
    always starts at index 0.  Embargo removes *embargo_bars* rows after
    the train boundary so that label look-ahead cannot leak.
    """
    if n_samples < n_folds * 2:
        # Dataset too small for proper CV; degenerate to single split.
        split = max(int(n_samples * 0.7), 1)
        return [(np.arange(split), np.arange(split, n_samples))]

    fold_size = n_samples // (n_folds + 1)  # reserve 1 portion for anchor
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
        folds.append((np.arange(split), np.arange(min(split + embargo_bars, n_samples), n_samples)))
    return folds


# ---------------------------------------------------------------------------
# Permutation feature importance  (P0.3)
# ---------------------------------------------------------------------------


def _compute_feature_importance(
    model: Any,
    X: pd.DataFrame,
    y: pd.Series,
    *,
    n_repeats: int = 5,
    random_state: int = 42,
) -> dict[str, float]:
    result = permutation_importance(
        model,
        X,
        y,
        n_repeats=n_repeats,
        random_state=random_state,
        scoring="accuracy",
    )
    importance: dict[str, float] = {}
    for col_idx, col_name in enumerate(X.columns):
        importance[col_name] = float(result.importances_mean[col_idx])
    return importance


def _top_k_importance_share(importance: dict[str, float], k: int = 3) -> float:
    """Return cumulative importance share of the top-*k* features."""
    total = sum(abs(v) for v in importance.values())
    if total <= 0:
        return 0.0
    sorted_vals = sorted(importance.values(), reverse=True)
    return float(sum(sorted_vals[:k]) / total)


# ---------------------------------------------------------------------------
# SHAP interpretability  (P1.8)
# ---------------------------------------------------------------------------


def _compute_shap_values(
    model: Any,
    X: pd.DataFrame,
) -> dict[str, float]:
    """Compute mean absolute SHAP values per feature using TreeExplainer."""
    import shap

    explainer = shap.TreeExplainer(model)
    sv = explainer.shap_values(X)
    # For binary classification, shap_values may be a list of two arrays.
    if isinstance(sv, list):
        sv = sv[1]
    mean_abs = np.abs(sv).mean(axis=0)
    return {col: round(float(v), 6) for col, v in zip(X.columns, mean_abs)}


# ---------------------------------------------------------------------------
# Label randomization test  (P0.4)
# ---------------------------------------------------------------------------


def _label_randomization_test(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    *,
    random_state: int = 42,
) -> dict[str, float]:
    """Retrain on shuffled labels; accuracy should be near chance (≤ ceiling)."""
    rng = np.random.RandomState(random_state)
    y_shuffled = y_train.sample(frac=1.0, random_state=rng).reset_index(drop=True)
    model = LogisticRegression(max_iter=500)
    model.fit(X_train.reset_index(drop=True), y_shuffled)
    preds = model.predict(X_test)
    acc = float(accuracy_score(y_test, preds))
    return {"shuffled_accuracy": round(acc, 6)}


# ---------------------------------------------------------------------------
# Adversarial validation  (P0.5)
# ---------------------------------------------------------------------------


def _adversarial_validation(
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    *,
    random_state: int = 42,
    n_splits: int = 3,
) -> dict[str, float]:
    """Train a classifier to distinguish train vs test; AUC near 0.5 = good.

    Uses stratified k-fold cross-validation so the score reflects genuine
    distributional difference rather than in-sample memorisation.
    """
    from sklearn.model_selection import StratifiedKFold

    combined = pd.concat([X_train, X_test], ignore_index=True)
    labels = np.concatenate([np.zeros(len(X_train)), np.ones(len(X_test))])
    oof_proba = np.full(len(labels), np.nan)
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=random_state)
    for fold_train, fold_test in skf.split(combined, labels):
        clf = RandomForestClassifier(n_estimators=50, random_state=random_state)
        clf.fit(combined.iloc[fold_train], labels[fold_train])
        oof_proba[fold_test] = clf.predict_proba(combined.iloc[fold_test])[:, 1]
    auc = float(roc_auc_score(labels, oof_proba))
    return {"adversarial_auc": round(auc, 6)}


# ---------------------------------------------------------------------------
# Model persistence helpers  (P0.6)
# ---------------------------------------------------------------------------


def _feature_set_hash(feature_columns: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(feature_columns)).encode()).hexdigest()[:16]


def _persist_model_artifact(
    settings: Settings,
    candidate_id: str,
    *,
    feature_columns: list[str],
    fold_metrics: list[dict[str, Any]],
    feature_importance: dict[str, float],
    label_randomization: dict[str, float],
    adversarial_validation: dict[str, float],
    embargo_bars: int,
    n_folds: int,
) -> Path:
    """Write model lineage artifact alongside the training report."""
    artifact = {
        "candidate_id": candidate_id,
        "training_timestamp": datetime.now(UTC).isoformat(),
        "feature_set_hash": _feature_set_hash(feature_columns),
        "feature_columns": feature_columns,
        "n_folds": n_folds,
        "embargo_bars": embargo_bars,
        "fold_metrics": fold_metrics,
        "feature_importance": feature_importance,
        "top3_importance_share": round(_top_k_importance_share(feature_importance, k=3), 6),
        "label_randomization": label_randomization,
        "adversarial_validation": adversarial_validation,
    }
    artifact_path = settings.paths().reports_dir / candidate_id / "model_artifact.json"
    write_json(artifact_path, artifact)
    return artifact_path


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def train_models(spec: StrategySpec, settings: Settings) -> Path:
    parquet_path = (
        settings.paths().normalized_research_dir
        / f"{spec.instrument.lower()}_{spec.execution_granularity.lower()}.parquet"
    )
    frame = pd.read_parquet(parquet_path)
    dataset = (
        build_labels(
            build_features(frame),
            spec.holding_bars,
            stop_loss_pips=spec.stop_loss_pips,
            take_profit_pips=spec.take_profit_pips,
        )
        .dropna()
        .reset_index(drop=True)
    )

    # Determine available feature columns — gracefully degrade if regime_label
    # is missing (e.g. when the feature pipeline was run without enough data).
    feature_cols = [c for c in FEATURE_COLUMNS if c in dataset.columns]

    embargo_bars = max(spec.holding_bars, 10)
    n_folds = getattr(settings.validation, "walk_forward_windows", 3)
    folds = _purged_walk_forward_folds(
        len(dataset),
        n_folds=n_folds,
        embargo_bars=embargo_bars,
    )

    # Aggregate OOS predictions across folds
    all_y_test = []
    all_logit_prob = []
    all_forest_prob = []
    fold_metrics: list[dict[str, Any]] = []

    for fold_idx, (train_idx, test_idx) in enumerate(folds):
        train = dataset.iloc[train_idx]
        test = dataset.iloc[test_idx]
        X_train = train[feature_cols]
        y_train = train["label_up"]
        X_test = test[feature_cols]
        y_test = test["label_up"]

        logit = LogisticRegression(max_iter=500)
        xgb_clf = xgb.XGBClassifier(
            n_estimators=100,
            max_leaves=settings.signal_filter.max_leaves,
            random_state=42,
            eval_metric="logloss",
            verbosity=0,
        )
        logit.fit(X_train, y_train)
        xgb_clf.fit(X_train, y_train)
        logit_prob = logit.predict_proba(X_test)[:, 1]
        xgb_prob = xgb_clf.predict_proba(X_test)[:, 1]

        all_y_test.append(y_test)
        all_logit_prob.append(logit_prob)
        all_forest_prob.append(xgb_prob)

        fold_metrics.append(
            {
                "fold": fold_idx,
                "train_size": len(train_idx),
                "test_size": len(test_idx),
                "logit_accuracy": float(accuracy_score(y_test, (logit_prob >= 0.5).astype(int))),
                "xgb_accuracy": float(accuracy_score(y_test, (xgb_prob >= 0.5).astype(int))),
            }
        )

    # Concatenate OOS predictions from all folds
    y_oos = pd.concat(all_y_test, ignore_index=True)
    logit_prob_oos = np.concatenate(all_logit_prob)
    forest_prob_oos = np.concatenate(all_forest_prob)
    hybrid_prob_oos = (logit_prob_oos + forest_prob_oos) / 2

    # Feature importance: permutation + SHAP (ML-P1.8)
    importance = _compute_feature_importance(xgb_clf, X_test, y_test)
    shap_values = _compute_shap_values(xgb_clf, X_test)

    # Label randomization test using first fold split
    first_train = dataset.iloc[folds[0][0]]
    first_test = dataset.iloc[folds[0][1]]
    label_rand = _label_randomization_test(
        first_train[feature_cols],
        first_train["label_up"],
        first_test[feature_cols],
        first_test["label_up"],
    )

    # Adversarial validation using first fold split
    adv_val = _adversarial_validation(
        first_train[feature_cols],
        first_test[feature_cols],
    )

    rule_backtest = run_backtest(spec, settings, output_prefix="shadow_rule_baseline")
    stress = run_stress_test(spec, settings)
    payload = {
        "candidate_id": spec.candidate_id,
        "shadow_only": True,
        "primary_signal_allowed": False,
        "training_method": "purged_walk_forward_cv",
        "embargo_bars": embargo_bars,
        "n_folds": len(folds),
        "promotion_gate": {
            "must_beat_rule_oos_pf": spec.validation_profile.out_of_sample_profit_factor_floor,
            "must_improve_expectancy": True,
            "max_relative_drawdown_degradation_pct": settings.validation.max_relative_drawdown_degradation_pct,
            "must_survive_stress": True,
        },
        "rule_baseline": {
            "out_of_sample_profit_factor": rule_backtest.out_of_sample_profit_factor,
            "expectancy_pips": rule_backtest.expectancy_pips,
            "max_drawdown_pct": rule_backtest.max_drawdown_pct,
            "stress_passed": stress.passed,
        },
        "modes": {
            "ml_primary": _binary_metrics(y_oos, (logit_prob_oos >= 0.5).astype(int)),
            "ml_filter": _binary_metrics(
                y_oos[logit_prob_oos >= 0.55],
                (forest_prob_oos[logit_prob_oos >= 0.55] >= 0.5).astype(int),
            )
            if (logit_prob_oos >= 0.55).any()
            else {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "sample_count": 0},
            "hybrid": _binary_metrics(y_oos, (hybrid_prob_oos >= 0.5).astype(int)),
            "rule_only": {
                "sample_count": int(len(y_oos)),
                "note": "Rule-only decision quality is measured through deterministic backtest artifacts.",
            },
        },
        "feature_importance": importance,
        "shap_values": shap_values,
        "top3_importance_share": round(_top_k_importance_share(importance, k=3), 6),
        "label_randomization": label_rand,
        "adversarial_validation": adv_val,
        "fold_metrics": fold_metrics,
    }
    report_path = settings.paths().reports_dir / spec.candidate_id / "model_metrics.json"
    write_json(report_path, payload)

    # Persist model lineage artifact (P0.6)
    _persist_model_artifact(
        settings,
        spec.candidate_id,
        feature_columns=feature_cols,
        fold_metrics=fold_metrics,
        feature_importance=importance,
        label_randomization=label_rand,
        adversarial_validation=adv_val,
        embargo_bars=embargo_bars,
        n_folds=len(folds),
    )

    return report_path


def _binary_metrics(y_true: pd.Series, y_pred) -> dict:
    if len(y_true) == 0:
        return {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "sample_count": 0}
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "sample_count": int(len(y_true)),
    }
