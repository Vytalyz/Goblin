"""GMM regime classifier for market state detection (ML-P1.5).

Fits a Gaussian Mixture Model on rolling windows of market features to
produce a discrete ``regime_label`` for each bar.  The regime labels are
validated for stability across walk-forward windows — unstable labels
indicate the classifier is not capturing durable market structure.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
from sklearn.mixture import GaussianMixture

from agentic_forex.config import Settings

logger = logging.getLogger(__name__)

REGIME_FEATURES: list[str] = [
    "volatility_20",
    "momentum_12",
    "zscore_10",
    "spread_to_range_10",
    "hour",
]

REGIME_NAMES: list[str] = ["steady", "volatile", "crisis", "transitional", "extreme"]


def fit_regime_classifier(
    data: pd.DataFrame,
    *,
    n_components: int = 4,
    random_state: int = 42,
) -> GaussianMixture:
    """Fit a GMM on the regime feature subset and return the fitted model."""
    X = data[REGIME_FEATURES].dropna()
    gmm = GaussianMixture(
        n_components=n_components,
        covariance_type="full",
        random_state=random_state,
        n_init=3,
        max_iter=200,
    )
    gmm.fit(X)
    return gmm


def predict_regime_labels(
    gmm: GaussianMixture,
    data: pd.DataFrame,
) -> pd.Series:
    """Predict integer regime labels for each row in *data*.

    Returns a Series aligned with *data*'s index.  Rows with NaN in
    regime features receive label -1.
    """
    mask = data[REGIME_FEATURES].notna().all(axis=1)
    labels = pd.Series(-1, index=data.index, dtype=int, name="regime_label")
    if mask.any():
        X = data.loc[mask, REGIME_FEATURES]
        labels.loc[mask] = gmm.predict(X)
    return labels


def regime_stability_score(
    data: pd.DataFrame,
    *,
    n_components: int = 4,
    n_windows: int = 3,
    random_state: int = 42,
) -> dict[str, Any]:
    """Measure regime label stability across walk-forward windows.

    Splits *data* into *n_windows* equal chunks, fits a GMM on each,
    and computes the fraction of bars where adjacent windows agree on
    the label.  The agreement fraction must exceed the policy threshold
    for the classifier to be considered stable.
    """
    clean = data.dropna(subset=REGIME_FEATURES).reset_index(drop=True)
    n = len(clean)
    if n < n_windows * 20:
        return {"agreement": 0.0, "window_count": 0, "stable": False}

    chunk_size = n // n_windows
    window_labels: list[np.ndarray] = []

    for w in range(n_windows):
        start = w * chunk_size
        end = start + chunk_size if w < n_windows - 1 else n
        window_data = clean.iloc[start:end]
        gmm = fit_regime_classifier(
            window_data, n_components=n_components, random_state=random_state + w,
        )
        # Predict on the full dataset from each window's model.
        full_labels = gmm.predict(clean[REGIME_FEATURES])
        window_labels.append(full_labels)

    # Compare adjacent windows on overlapping predictions.
    agreements = []
    for i in range(len(window_labels) - 1):
        agree = (window_labels[i] == window_labels[i + 1]).mean()
        agreements.append(float(agree))

    mean_agreement = float(np.mean(agreements)) if agreements else 0.0

    return {
        "agreement": round(mean_agreement, 4),
        "window_count": n_windows,
        "per_window_agreement": [round(a, 4) for a in agreements],
        "stable": mean_agreement >= 0.60,
    }


def add_regime_label(
    data: pd.DataFrame,
    settings: Settings,
    *,
    n_components: int | None = None,
    random_state: int = 42,
) -> pd.DataFrame:
    """Add a ``regime_label`` column to *data* using a GMM fitted on the data.

    Falls back to ``settings.regime_classifier.n_components_range[0]`` when
    *n_components* is not supplied.
    """
    n = n_components or settings.regime_classifier.n_components_range[0]
    gmm = fit_regime_classifier(data, n_components=n, random_state=random_state)
    result = data.copy()
    result["regime_label"] = predict_regime_labels(gmm, data)
    return result
