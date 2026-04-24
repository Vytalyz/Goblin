"""Tests for tools/run_ml_p20_insample.py and tools/run_ml_p20_holdout_eval.py.

Covers:
  - Constants in run_ml_p20_insample (survivors, N_IN_SAMPLE, SHA)
  - bca_block_bootstrap_pf_lift:  trivial case, positive-lift case, direction
  - determine_verdict:            all four outcome branches
  - _assign_regimes_frozen:       four regimes produced, frozen thresholds used
  - Predictions-log gate in run_ml_p20_holdout_eval.main (exit 1 without preds)
  - run_ml_p20_ceremony pre-condition guard (exit 1 without preds)

All tests are offline (no parquet / full feature pipeline required).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
INSAMPLE_SCRIPT = REPO_ROOT / "tools" / "run_ml_p20_insample.py"
HOLDOUT_EVAL_SCRIPT = REPO_ROOT / "tools" / "run_ml_p20_holdout_eval.py"
CEREMONY_SCRIPT = REPO_ROOT / "tools" / "run_ml_p20_ceremony.py"


# ---------------------------------------------------------------------------
# Module loaders
# ---------------------------------------------------------------------------


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# run_ml_p20_insample — constants
# ---------------------------------------------------------------------------


class TestInSampleConstants:
    def setup_method(self):
        self.mod = _load_module(INSAMPLE_SCRIPT, "run_ml_p20_insample")

    def test_survivors_set(self):
        assert set(self.mod.SURVIVORS) == {
            "AF-CAND-0734",
            "AF-CAND-0322",
            "AF-CAND-0323",
            "AF-CAND-0007",
            "AF-CAND-0002",
            "AF-CAND-0290",
        }

    def test_n_in_sample(self):
        assert self.mod.N_IN_SAMPLE == 155_775

    def test_dataset_sha(self):
        assert self.mod.DATASET_SHA == ("7875ba5af620476aaba80cdec0c86680b343f70a02bf19eb40695517378ed8f1")

    def test_effect_size_floor(self):
        assert abs(self.mod.EFFECT_SIZE_FLOOR_PF - 0.0083) < 1e-9


# ---------------------------------------------------------------------------
# bca_block_bootstrap_pf_lift — unit tests
# ---------------------------------------------------------------------------


class TestBcaBootstrap:
    def setup_method(self):
        self.mod = _load_module(HOLDOUT_EVAL_SCRIPT, "run_ml_p20_holdout_eval")
        self.fn = self.mod.bca_block_bootstrap_pf_lift

    def _make_outcomes(self, n: int, xgb_edge: float, rule_edge: float, seed: int = 0):
        rng = np.random.default_rng(seed)
        # XGB: positive pips with probability 0.5+xgb_edge
        xgb_out = np.where(rng.random(n) < 0.5 + xgb_edge, 1.0, -1.0)
        rule_out = np.where(rng.random(n) < 0.5 + rule_edge, 1.0, -1.0)
        return xgb_out, rule_out

    def test_returns_four_tuple(self):
        xgb, rule = self._make_outcomes(200, 0.05, 0.0)
        result = self.fn(xgb, rule, block_size=20, n_resamples=100, rng_seed=42)
        assert len(result) == 4
        lift, ci_lo, ci_hi, boot = result
        assert isinstance(float(lift), float)
        assert isinstance(float(ci_lo), float)
        assert isinstance(float(ci_hi), float)
        assert boot.shape == (100,)

    def test_ci_lower_le_ci_upper(self):
        xgb, rule = self._make_outcomes(300, 0.1, 0.0)
        _, ci_lo, ci_hi, _ = self.fn(xgb, rule, block_size=20, n_resamples=200, rng_seed=1)
        assert ci_lo <= ci_hi

    def test_positive_edge_ci_lower_positive(self):
        """When XGB clearly beats the rule, BCa CI lower bound should be > 0."""
        rng = np.random.default_rng(99)
        n = 500
        # XGB wins 60% of time, rule wins 40%
        xgb_out = np.where(rng.random(n) < 0.60, 2.0, -1.0)
        rule_out = np.where(rng.random(n) < 0.40, 2.0, -1.0)
        _, ci_lo, _, _ = self.fn(xgb_out, rule_out, block_size=20, n_resamples=500, rng_seed=2)
        assert ci_lo > 0.0, f"Expected ci_lo > 0 but got {ci_lo}"

    def test_no_edge_ci_spans_zero(self):
        """When XGB and rule are equivalent, CI should span zero."""
        rng = np.random.default_rng(7)
        n = 300
        outcomes = np.where(rng.random(n) < 0.5, 1.0, -1.0)
        _, ci_lo, ci_hi, _ = self.fn(outcomes, outcomes, block_size=20, n_resamples=200, rng_seed=3)
        # Identical arrays → lift = 0; CI should straddle 0
        assert ci_lo <= 0.0 <= ci_hi

    def test_observed_lift_equals_pf_diff(self):
        from agentic_forex.ml.baseline_runner import profit_factor

        sys.path.insert(0, str(REPO_ROOT / "src"))
        xgb = np.array([2.0, -1.0, 2.0, 2.0, -1.0])
        rule = np.array([-1.0, 2.0, -1.0, 2.0, -1.0])
        lift, _, _, _ = self.fn(xgb, rule, block_size=2, n_resamples=50, rng_seed=0)
        expected = profit_factor(xgb) - profit_factor(rule)
        assert abs(lift - expected) < 1e-9


# ---------------------------------------------------------------------------
# determine_verdict
# ---------------------------------------------------------------------------


class TestDetermineVerdict:
    def setup_method(self):
        self.mod = _load_module(HOLDOUT_EVAL_SCRIPT, "run_ml_p20_holdout_eval")
        self.fn = self.mod.determine_verdict

    def test_go(self):
        assert self.fn(0.12, 0.02) == "GO"

    def test_go_requires_positive_ci(self):
        # lift >= 0.10 but CI lower <= 0 -> CONDITIONAL
        assert self.fn(0.12, -0.01) == "CONDITIONAL"

    def test_conditional(self):
        assert self.fn(0.07, -0.05) == "CONDITIONAL"

    def test_nogo_below_conditional_floor(self):
        assert self.fn(0.03, -0.10) == "NO_GO"

    def test_q1_nogo_overrides_go(self):
        assert self.fn(0.15, 0.05, q1_nogo=True) == "NO_GO"

    def test_q1_conditional_restricted_demotes_go(self):
        assert self.fn(0.15, 0.05, q1_conditional_restricted=True) == "CONDITIONAL"

    def test_exact_go_threshold(self):
        assert self.fn(0.10, 0.001) == "GO"

    def test_exact_conditional_threshold(self):
        assert self.fn(0.055, -0.01) == "CONDITIONAL"

    def test_just_below_conditional(self):
        assert self.fn(0.054, -0.01) == "NO_GO"


# ---------------------------------------------------------------------------
# _assign_regimes_frozen
# ---------------------------------------------------------------------------


class TestAssignRegimesFrozen:
    def setup_method(self):
        self.mod = _load_module(HOLDOUT_EVAL_SCRIPT, "run_ml_p20_holdout_eval")
        self.fn = self.mod._assign_regimes_frozen
        self.MOM = 1.9
        self.VOL = 0.0000741639

    def _make_df(self, n: int, mom_vals, vol_vals, idx_start: int = 0) -> pd.DataFrame:
        return pd.DataFrame(
            {"momentum_12": mom_vals, "volatility_20": vol_vals},
            index=range(idx_start, idx_start + n),
        )

    def test_four_regimes_produced(self):
        df = self._make_df(
            4,
            [2.0, 2.0, 0.5, 0.5],
            [0.0001, 0.00005, 0.0001, 0.00005],
        )
        series = self.fn(df, self.MOM, self.VOL)
        assert set(series.values) == {
            "trend_high_vol",
            "trend_low_vol",
            "range_high_vol",
            "range_low_vol",
        }

    def test_trend_high_vol(self):
        df = self._make_df(1, [3.0], [0.0001])  # abs > 1.9, vol > threshold
        assert self.fn(df, self.MOM, self.VOL).iloc[0] == "trend_high_vol"

    def test_range_low_vol(self):
        df = self._make_df(1, [0.1], [0.00001])
        assert self.fn(df, self.MOM, self.VOL).iloc[0] == "range_low_vol"

    def test_index_preserved(self):
        df = self._make_df(3, [3.0, 0.1, -3.0], [0.0001, 0.0001, 0.0001], idx_start=155775)
        series = self.fn(df, self.MOM, self.VOL)
        assert list(series.index) == [155775, 155776, 155777]

    def test_negative_momentum_uses_abs(self):
        # abs(-2.5) = 2.5 > 1.9 -> trend
        df = self._make_df(1, [-2.5], [0.0001])
        assert self.fn(df, self.MOM, self.VOL).iloc[0] == "trend_high_vol"


# ---------------------------------------------------------------------------
# Predictions-log gate (holdout eval exits 1 without preds)
# ---------------------------------------------------------------------------


class TestPredictionsGate:
    def setup_method(self):
        self.mod = _load_module(HOLDOUT_EVAL_SCRIPT, "run_ml_p20_holdout_eval")

    def test_exits_1_no_midpoint(self, tmp_path, monkeypatch):
        """main() should return 1 when no midpoint prediction exists."""
        pred_log = tmp_path / "predictions.jsonl"
        pred_log.write_text("")  # empty
        monkeypatch.setattr(self.mod, "PREDICTIONS_LOG", pred_log)
        result = self.mod.main(str(tmp_path / "fake_holdout.parquet"))
        assert result == 1

    def test_exits_1_no_trigger(self, tmp_path, monkeypatch):
        """main() should return 1 when midpoint exists but trigger is missing."""
        pred_log = tmp_path / "predictions.jsonl"
        midpoint_entry = json.dumps(
            {
                "prediction_id": "PRED-ML-2.0-MIDPOINT-1",
                "phase": "midpoint",
                "predicted_verdict": "CONDITIONAL",
                "predicted_point_estimate_pf": 0.07,
                "predicted_ci_low": 0.01,
                "predicted_ci_high": 0.13,
                "commit_sha_at_prediction": "a" * 40,
                "wallclock_utc": "2026-04-20T22:00:00Z",
                "rationale_note": "In-sample CV shows consistent positive lift across 6 survivors.",
                "predictor_attestation": "Owner attestation: no holdout peek at prediction time.",
            }
        )
        pred_log.write_text(midpoint_entry + "\n")
        monkeypatch.setattr(self.mod, "PREDICTIONS_LOG", pred_log)
        result = self.mod.main(str(tmp_path / "fake_holdout.parquet"))
        assert result == 1


# ---------------------------------------------------------------------------
# Ceremony pre-condition guard
# ---------------------------------------------------------------------------


class TestCeremonyPreConditions:
    def setup_method(self):
        self.mod = _load_module(CEREMONY_SCRIPT, "run_ml_p20_ceremony")

    def test_exits_1_empty_predictions(self, tmp_path, monkeypatch):
        pred_log = tmp_path / "predictions.jsonl"
        pred_log.write_text("")
        monkeypatch.setattr(self.mod, "PREDICTIONS_LOG", pred_log)
        result = self.mod.main(["--key-path", str(tmp_path / "fake.key")])
        assert result == 1

    def test_exits_1_missing_trigger(self, tmp_path, monkeypatch):
        pred_log = tmp_path / "predictions.jsonl"
        pred_log.write_text(json.dumps({"phase": "midpoint", "prediction_id": "PRED-X"}) + "\n")
        monkeypatch.setattr(self.mod, "PREDICTIONS_LOG", pred_log)
        result = self.mod.main(["--key-path", str(tmp_path / "fake.key")])
        assert result == 1
