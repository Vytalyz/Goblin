"""Phase 1.6.0 — Variance Pilot tests.

Covered:
- reproducibility: same seed => identical PF
- variability: different seeds => different PF (on synthetic noisy data)
- σ_PF math: summarise() agrees with numpy std(ddof=1)
- required-n math: matches the one-sample power formula
- profit-factor edge cases (no trades, no losses, no wins)
- AF-CAND-0263 guard in the script driver
- no-torch-import assertion
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from agentic_forex.ml import variance_pilot as vp

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Synthetic fixture
# ---------------------------------------------------------------------------

def _synthetic_dataset(n: int = 300, *, seed: int = 17) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    features = {
        "f_a": rng.randn(n),
        "f_b": rng.randn(n),
        "f_c": rng.randn(n),
    }
    # Label is a noisy linear function of f_a so XGB has genuine signal
    # but plenty of residual variance for seed effects to show up.
    logits = 0.8 * features["f_a"] + 0.3 * rng.randn(n)
    label_up = (logits > 0).astype(int)
    # Outcome pips roughly tracks label with mean-reverting noise.
    long_outcome_pips = np.where(
        label_up == 1,
        rng.uniform(1.0, 5.0, n),
        -rng.uniform(1.0, 5.0, n),
    )
    return pd.DataFrame({
        **features,
        "label_up": label_up,
        "long_outcome_pips": long_outcome_pips,
    })


FEATURE_COLS = ["f_a", "f_b", "f_c"]


# ---------------------------------------------------------------------------
# Profit-factor helper
# ---------------------------------------------------------------------------

class TestProfitFactor:
    def test_no_trades_returns_zero(self):
        assert vp._profit_factor(np.array([])) == 0.0

    def test_no_losers_is_clipped(self):
        assert vp._profit_factor(np.array([1.0, 2.0, 3.0])) == 10.0

    def test_no_winners_is_zero(self):
        assert vp._profit_factor(np.array([-1.0, -2.0])) == 0.0

    def test_typical_case(self):
        pf = vp._profit_factor(np.array([2.0, -1.0, 3.0, -2.0]))
        assert pf == pytest.approx(5.0 / 3.0)


# ---------------------------------------------------------------------------
# run_seed reproducibility + variability
# ---------------------------------------------------------------------------

class TestRunSeed:
    def test_same_seed_is_deterministic(self):
        ds = _synthetic_dataset()
        a = vp.run_seed(
            ds,
            feature_cols=FEATURE_COLS,
            label_col="label_up",
            outcome_col="long_outcome_pips",
            candidate_id="SYN-A",
            seed=7,
            n_folds=2,
            embargo_bars=5,
        )
        b = vp.run_seed(
            ds,
            feature_cols=FEATURE_COLS,
            label_col="label_up",
            outcome_col="long_outcome_pips",
            candidate_id="SYN-A",
            seed=7,
            n_folds=2,
            embargo_bars=5,
        )
        assert a.aggregate_profit_factor == b.aggregate_profit_factor
        assert a.fold_profit_factors == b.fold_profit_factors

    def test_different_seeds_produce_different_pf(self):
        ds = _synthetic_dataset()
        pfs = []
        for seed in (1, 2, 3, 4, 5):
            out = vp.run_seed(
                ds,
                feature_cols=FEATURE_COLS,
                label_col="label_up",
                outcome_col="long_outcome_pips",
                candidate_id="SYN-A",
                seed=seed,
                n_folds=2,
                embargo_bars=5,
            )
            pfs.append(out.aggregate_profit_factor)
        # At least two distinct values — the whole point of the pilot is
        # that seeds actually shift the outcome.
        assert len(set(pfs)) >= 2


# ---------------------------------------------------------------------------
# summarise() statistics
# ---------------------------------------------------------------------------

class TestSummarise:
    def _outcomes(self, pfs: list[float]) -> list[vp.SeedOutcome]:
        return [
            vp.SeedOutcome(
                candidate_id=f"SYN-{i // 3}",
                seed=i,
                fold_profit_factors=(pf,),
                aggregate_profit_factor=pf,
                trade_count=100,
            )
            for i, pf in enumerate(pfs)
        ]

    def test_sigma_matches_numpy_ddof1(self):
        pfs = [1.05, 1.12, 0.98, 1.20, 0.91, 1.03, 1.15, 0.95, 1.08, 1.01]
        s = vp.summarise(self._outcomes(pfs))
        assert s.sigma_pf == pytest.approx(float(np.std(pfs, ddof=1)))
        assert s.mean_pf == pytest.approx(float(np.mean(pfs)))

    def test_required_n_power_formula(self):
        # With MDE = k*sigma, required_n simplifies to ((z_a + z_b)/k)^2.
        pfs = [1.0, 1.1, 0.9, 1.2, 0.8]
        s = vp.summarise(self._outcomes(pfs), mde_multiplier=1.0)
        expected = int(
            np.ceil(((vp.Z_ALPHA_001 + vp.Z_BETA_080) / 1.0) ** 2)
        )
        assert s.required_n_candidates == expected

    def test_required_n_scales_inversely_with_mde(self):
        pfs = [1.0, 1.1, 0.9, 1.2, 0.8, 1.05, 0.95]
        small = vp.summarise(self._outcomes(pfs), mde_multiplier=0.5)
        large = vp.summarise(self._outcomes(pfs), mde_multiplier=2.0)
        assert small.required_n_candidates > large.required_n_candidates

    def test_floor_defaults_to_one_sigma(self):
        pfs = [1.0, 1.05, 0.95, 1.10, 0.90]
        s = vp.summarise(self._outcomes(pfs))
        assert s.effect_size_floor_pf == pytest.approx(s.sigma_pf)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            vp.summarise([])


# ---------------------------------------------------------------------------
# No-torch-import guard
# ---------------------------------------------------------------------------

class TestNoTorchImport:
    def test_module_does_not_pull_torch(self):
        # Run a tiny subprocess that imports the pilot module and asserts
        # torch is not in sys.modules. We use a subprocess so any prior
        # test (or the user's session) having torch loaded doesn't leak in.
        code = (
            "import sys;"
            "import agentic_forex.ml.variance_pilot;"
            "assert 'torch' not in sys.modules, 'torch leaked into variance_pilot import graph';"
            "print('ok')"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", code],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"variance_pilot import leaked torch.\nstdout:{result.stdout}\nstderr:{result.stderr}"
        )

    def test_assert_helper_raises_when_torch_present(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "torch", object())
        with pytest.raises(RuntimeError, match="torch was imported"):
            vp.assert_no_torch_import()

    def test_assert_helper_passes_when_torch_absent(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "torch", raising=False)
        # Should not raise.
        vp.assert_no_torch_import()


# ---------------------------------------------------------------------------
# Script driver — AF-CAND-0263 guard
# ---------------------------------------------------------------------------

class TestScriptGuard:
    def test_af_cand_0263_rejected(self, tmp_path):
        # Import the script module and call its main() — it should
        # SystemExit before touching data when AF-CAND-0263 is in the
        # candidate list.
        script_path = REPO_ROOT / "scripts" / "run_ml_variance_pilot.py"
        assert script_path.exists()
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(script_path),
                "--candidates", "AF-CAND-0263",
                "--seeds", "0",
                "--output", str(tmp_path / "out.json"),
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "AF-CAND-0263" in combined
        assert "locked" in combined.lower() or "benchmark" in combined.lower()
