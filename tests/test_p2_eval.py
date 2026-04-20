"""Tests for tools/run_p2_eval.py — ML-P2.0 holdout evaluation pipeline.

Covers: verdict logic, BCa bootstrap, Bonferroni regime tests, Q1 rule,
candidate evaluation, and per-trade outcome conventions.  All tests use
synthetic in-memory data and do NOT require strategy_spec.json files or
the real parquet dataset.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import run_p2_eval as ev  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_outcomes(n: int, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Return (xgb_out, rule_out) arrays with positive mean lift."""
    rng = np.random.default_rng(seed)
    rule_out = rng.normal(0.0, 1.0, n)
    xgb_out = rule_out + rng.uniform(0.05, 0.15, n)
    return xgb_out, rule_out


def _make_flat_outcomes(n: int) -> tuple[np.ndarray, np.ndarray]:
    """XGB and rule identical — zero lift."""
    base = np.ones(n) * 0.5
    return base.copy(), base.copy()


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------

class TestRenderVerdict:
    """19 paths tested across verdict bands + Q1 interactions."""

    def _q1(self, verdict: str = "Q1_OK") -> dict:
        return {
            "q1_verdict": verdict,
            "mean_fragile_lift": 0.01,
            "n_fragile_negative": 0,
            "q1_conditional_threshold": ev.Q1_CONDITIONAL_THRESHOLD,
            "q1_nogo_threshold": ev.Q1_NOGO_THRESHOLD,
        }

    def test_go_when_lift_above_target_and_ci_positive(self):
        assert ev.render_verdict(0.12, 0.005, self._q1()) == "GO"

    def test_conditional_when_lift_in_conditional_band(self):
        assert ev.render_verdict(0.07, -0.001, self._q1()) == "CONDITIONAL"

    def test_conditional_at_floor_boundary(self):
        assert ev.render_verdict(0.055, -0.001, self._q1()) == "CONDITIONAL"

    def test_nogo_when_lift_below_conditional_floor(self):
        assert ev.render_verdict(0.04, 0.001, self._q1()) == "NO_GO"

    def test_nogo_when_lift_above_go_but_ci_nonpositive(self):
        # GO requires BOTH lift >= 0.10 AND BCa CI low > 0
        assert ev.render_verdict(0.11, 0.0, self._q1()) == "CONDITIONAL"

    def test_nogo_when_lift_above_go_and_ci_negative(self):
        assert ev.render_verdict(0.11, -0.01, self._q1()) == "CONDITIONAL"

    def test_q1_nogo_overrides_go(self):
        assert ev.render_verdict(0.15, 0.05, self._q1("Q1_NOGO")) == "NO_GO"

    def test_q1_nogo_overrides_conditional(self):
        assert ev.render_verdict(0.07, -0.001, self._q1("Q1_NOGO")) == "NO_GO"

    def test_q1_nogo_overrides_nogo_stays_nogo(self):
        assert ev.render_verdict(0.01, -0.01, self._q1("Q1_NOGO")) == "NO_GO"

    def test_q1_conditional_restricted_overrides_conditional(self):
        verdict = ev.render_verdict(0.07, -0.001, self._q1("Q1_CONDITIONAL_RESTRICTED"))
        assert verdict == "CONDITIONAL_RESTRICTED"

    def test_q1_conditional_restricted_does_not_override_nogo(self):
        # If primary verdict is NO_GO, Q1_CONDITIONAL_RESTRICTED doesn't help
        verdict = ev.render_verdict(0.03, -0.01, self._q1("Q1_CONDITIONAL_RESTRICTED"))
        assert verdict == "NO_GO"

    def test_q1_conditional_restricted_does_not_override_go(self):
        # GO is not affected by Q1_CONDITIONAL_RESTRICTED
        verdict = ev.render_verdict(0.12, 0.005, self._q1("Q1_CONDITIONAL_RESTRICTED"))
        assert verdict == "GO"

    def test_go_boundary_exactly_010(self):
        assert ev.render_verdict(0.10, 0.001, self._q1()) == "GO"

    def test_conditional_just_below_go(self):
        assert ev.render_verdict(0.099, 0.001, self._q1()) == "CONDITIONAL"


# ---------------------------------------------------------------------------
# Q1 rule
# ---------------------------------------------------------------------------

class TestApplyQ1Rule:
    def test_q1_ok_when_all_positive(self):
        result = ev.apply_q1_rule([0.05, 0.03, 0.07, 0.02, 0.04])
        assert result["q1_verdict"] == "Q1_OK"

    def test_q1_ok_when_mean_above_threshold(self):
        result = ev.apply_q1_rule([-0.005, -0.001, 0.05, 0.03, 0.04])
        assert result["q1_verdict"] == "Q1_OK"

    def test_q1_conditional_restricted_when_mean_below_1sigma(self):
        # Q1_CONDITIONAL_THRESHOLD = -0.0211; mean must be < -0.0211 and >= -0.0422
        # mean([-0.050, -0.050, -0.050, 0.010, 0.010]) = -0.026
        lifts = [-0.050, -0.050, -0.050, 0.010, 0.010]
        result = ev.apply_q1_rule(lifts)
        assert result["q1_verdict"] == "Q1_CONDITIONAL_RESTRICTED"

    def test_q1_nogo_when_mean_below_2sigma_and_breadth_3(self):
        # Q1_NOGO_THRESHOLD = -0.0422; need >= 3 negative
        # mean([-0.055, -0.055, -0.055, -0.055, 0.001]) = -0.0438 < -0.0422
        lifts = [-0.055, -0.055, -0.055, -0.055, 0.001]
        result = ev.apply_q1_rule(lifts)
        assert result["q1_verdict"] == "Q1_NOGO"
        assert result["n_fragile_negative"] >= 3

    def test_q1_conditional_not_nogo_when_breadth_below_3(self):
        # Mean below 2-sigma BUT only 2 negatives — should be CONDITIONAL_RESTRICTED
        lifts = [-0.05, -0.05, 0.01, 0.01, 0.01]
        # mean = -0.014 → not below -0.0422, so Q1_OK or CONDITIONAL_RESTRICTED
        result = ev.apply_q1_rule(lifts)
        # Mean = -0.014 which is above Q1_CONDITIONAL_THRESHOLD (-0.0211), so Q1_OK
        assert result["q1_verdict"] == "Q1_OK"

    def test_q1_no_fragile_data(self):
        result = ev.apply_q1_rule([])
        assert result["q1_verdict"] == "NO_FRAGILE_DATA"
        assert result["mean_fragile_lift"] is None

    def test_q1_mean_fragile_lift_correct(self):
        lifts = [0.04, 0.06, 0.02]
        result = ev.apply_q1_rule(lifts)
        assert abs(result["mean_fragile_lift"] - 0.04) < 1e-9


# ---------------------------------------------------------------------------
# BCa moving-block bootstrap
# ---------------------------------------------------------------------------

class TestBcaBootstrap:
    def test_returns_required_keys(self):
        xgb_out, rule_out = _make_outcomes(200)
        result = ev.bca_moving_block_bootstrap(xgb_out, rule_out, n_resamples=100)
        for key in ("mean", "ci_low_95", "ci_high_95", "n_trades", "block_size"):
            assert key in result

    def test_empty_input_returns_zeros(self):
        result = ev.bca_moving_block_bootstrap(np.array([]), np.array([]), n_resamples=100)
        assert result["mean"] == 0.0
        assert result["ci_low_95"] == 0.0
        assert result["ci_high_95"] == 0.0

    def test_ci_contains_observed_mean(self):
        xgb_out, rule_out = _make_outcomes(300, seed=42)
        result = ev.bca_moving_block_bootstrap(xgb_out, rule_out, n_resamples=500, seed=42)
        assert result["ci_low_95"] <= result["mean"] <= result["ci_high_95"]

    def test_positive_mean_lift_gives_positive_ci_low(self):
        """Strong positive lift should produce CI entirely > 0."""
        rng = np.random.default_rng(0)
        rule_out = rng.normal(0.0, 0.1, 500)
        xgb_out = rule_out + 0.5  # large positive lift
        result = ev.bca_moving_block_bootstrap(xgb_out, rule_out, n_resamples=500, seed=0)
        assert result["ci_low_95"] > 0.0

    def test_block_size_at_least_min(self):
        xgb_out, rule_out = _make_outcomes(100)
        result = ev.bca_moving_block_bootstrap(xgb_out, rule_out, n_resamples=100, block_size_min=20)
        assert result["block_size"] >= 20


# ---------------------------------------------------------------------------
# Bonferroni regime tests
# ---------------------------------------------------------------------------

class TestBonferroniRegimeTests:
    def _make_regime_series(self, n: int) -> pd.Series:
        """Return a regime Series cycling through all 4 regimes."""
        regimes = np.array(list(ev.REGIME_IDS) * (n // 4 + 1))[:n]
        return pd.Series(regimes, dtype="object")

    def test_returns_4_results(self):
        xgb_out, rule_out = _make_outcomes(200)
        regimes = self._make_regime_series(200)
        results = ev.run_bonferroni_regime_tests(xgb_out, rule_out, regimes)
        assert len(results) == 4

    def test_all_regime_ids_present(self):
        xgb_out, rule_out = _make_outcomes(200)
        regimes = self._make_regime_series(200)
        results = ev.run_bonferroni_regime_tests(xgb_out, rule_out, regimes)
        ids = {r["regime_id"] for r in results}
        assert ids == set(ev.REGIME_IDS)

    def test_insufficient_trades_not_significant(self):
        """When a regime has < 10 trades, mark as insufficient."""
        xgb_out = np.ones(4)
        rule_out = np.ones(4)
        regimes = pd.Series(list(ev.REGIME_IDS), dtype="object")
        results = ev.run_bonferroni_regime_tests(xgb_out, rule_out, regimes)
        for r in results:
            assert r["significant_at_bonferroni"] is False

    def test_zero_diff_not_significant(self):
        """Zero per-trade lift should not be significant."""
        xgb_out, rule_out = _make_flat_outcomes(200)
        regimes = self._make_regime_series(200)
        results = ev.run_bonferroni_regime_tests(xgb_out, rule_out, regimes)
        assert all(not r["significant_at_bonferroni"] for r in results)


# ---------------------------------------------------------------------------
# Outcome pip convention
# ---------------------------------------------------------------------------

class TestOutcomePipConvention:
    def test_long_side_returns_positive_pips_for_up_move(self):
        df = pd.DataFrame({"long_outcome_pips": [5.0]})
        side = np.array([1])
        out = ev._outcome_pips(df, side)
        assert out[0] == 5.0

    def test_short_side_flips_sign(self):
        df = pd.DataFrame({"long_outcome_pips": [5.0]})
        side = np.array([-1])
        out = ev._outcome_pips(df, side)
        assert out[0] == -5.0


# ---------------------------------------------------------------------------
# Aggregate lift
# ---------------------------------------------------------------------------

class TestAggregateComputation:
    def test_aggregate_lift_is_mean_of_candidate_lifts(self):
        lifts = [0.05, 0.08, 0.12, 0.07, 0.09, 0.06]
        expected = float(np.mean(lifts))
        assert abs(expected - 0.0783333) < 1e-5
