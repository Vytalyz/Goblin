from __future__ import annotations

from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score

from agentic_forex.backtesting.engine import run_backtest, run_stress_test
from agentic_forex.config import Settings
from agentic_forex.features.service import build_features
from agentic_forex.labels.service import build_labels
from agentic_forex.utils.io import write_json
from agentic_forex.workflows.contracts import StrategySpec


def train_models(spec: StrategySpec, settings: Settings) -> Path:
    parquet_path = settings.paths().normalized_research_dir / f"{spec.instrument.lower()}_{spec.execution_granularity.lower()}.parquet"
    frame = pd.read_parquet(parquet_path)
    dataset = build_labels(
        build_features(frame),
        spec.holding_bars,
        stop_loss_pips=spec.stop_loss_pips,
        take_profit_pips=spec.take_profit_pips,
    ).dropna().reset_index(drop=True)
    feature_columns = [
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
    ]
    split = max(int(len(dataset) * 0.7), 1)
    train = dataset.iloc[:split]
    test = dataset.iloc[split:] if split < len(dataset) else dataset.iloc[-1:]
    X_train = train[feature_columns]
    y_train = train["label_up"]
    X_test = test[feature_columns]
    y_test = test["label_up"]

    logit = LogisticRegression(max_iter=500)
    forest = RandomForestClassifier(n_estimators=100, random_state=42)
    logit.fit(X_train, y_train)
    forest.fit(X_train, y_train)
    logit_prob = logit.predict_proba(X_test)[:, 1]
    forest_prob = forest.predict_proba(X_test)[:, 1]
    hybrid_prob = (logit_prob + forest_prob) / 2

    rule_backtest = run_backtest(spec, settings, output_prefix="shadow_rule_baseline")
    stress = run_stress_test(spec, settings)
    payload = {
        "candidate_id": spec.candidate_id,
        "shadow_only": True,
        "primary_signal_allowed": False,
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
            "ml_primary": _binary_metrics(y_test, (logit_prob >= 0.5).astype(int)),
            "ml_filter": _binary_metrics(y_test[logit_prob >= 0.55], (forest_prob[logit_prob >= 0.55] >= 0.5).astype(int))
            if (logit_prob >= 0.55).any()
            else {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "sample_count": 0},
            "hybrid": _binary_metrics(y_test, (hybrid_prob >= 0.5).astype(int)),
            "rule_only": {
                "sample_count": int(len(y_test)),
                "note": "Rule-only decision quality is measured through deterministic backtest artifacts.",
            },
        },
    }
    report_path = settings.paths().reports_dir / spec.candidate_id / "model_metrics.json"
    write_json(report_path, payload)
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
