"""Tests for Phase 1.6 baseline runner (D11/D14/D15 enforcement)."""
from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agentic_forex.governance.errors import (
    CostSensitivityError,
    DatasetSHAMismatchError,
    GovernanceError,
    RegimeNonNegativityError,
)
from agentic_forex.ml import baseline_runner as br


def _toy_dataset(n: int = 600, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "ret_1": rng.normal(0, 1e-4, n),
        "ret_5": rng.normal(0, 1e-4, n),
        "zscore_10": rng.normal(0, 1.0, n),
        "momentum_12": rng.normal(0, 1e-4, n),
        "volatility_20": np.abs(rng.normal(1e-4, 5e-5, n)),
        "intrabar_range_pips": np.abs(rng.normal(2.0, 0.5, n)),
        "range_position_10": rng.uniform(0, 1, n),
        "spread_to_range_10": rng.uniform(0, 0.5, n),
        "spread_pips": np.abs(rng.normal(0.5, 0.1, n)),
        "hour": rng.integers(0, 24, n),
        "regime_label": rng.integers(0, 4, n),
        "label_up": rng.integers(0, 2, n),
        # Outcome with mild positive drift so PF is computable
        "long_outcome_pips": rng.normal(0.05, 2.0, n),
    })
    return df


# ---------------------------------------------------------------------------
# 1.6 / D14 — Regime + cost gates raise on violation
# ---------------------------------------------------------------------------


class TestProfitFactor:
    def test_empty_returns_zero(self):
        assert br.profit_factor(np.array([])) == 0.0

    def test_no_losses_clips_to_ten(self):
        assert br.profit_factor(np.array([1.0, 2.0, 3.0])) == 10.0

    def test_basic_ratio(self):
        # +6 / |-3| = 2.0
        assert br.profit_factor(np.array([1.0, 2.0, 3.0, -1.0, -2.0])) == pytest.approx(2.0)


class TestAssignRegimes:
    def test_four_regimes_present(self):
        ds = _toy_dataset(n=400, seed=1)
        regimes = br.assign_regimes(ds)
        unique = set(regimes.dropna().unique())
        # All four should appear with a uniform-ish toy dataset.
        assert unique == {
            "trend_high_vol", "trend_low_vol", "range_high_vol", "range_low_vol",
        }


class TestEvaluateCandidate:
    def test_runs_end_to_end(self):
        ds = _toy_dataset(n=600, seed=2)
        result = br.evaluate_candidate(
            ds,
            feature_cols=br.BASELINE_FEATURE_COLUMNS,
            candidate_id="TEST-001",
            n_folds=3,
            embargo_bars=10,
            cost_shocks_pips=(0.0, 1.0),
        )
        assert result["candidate_id"] == "TEST-001"
        assert len(result["regime_breakdown"]) == 4
        assert len(result["cost_sweep"]) == 2
        assert result["n_trades_total"] > 0


# ---------------------------------------------------------------------------
# D14 enforcement — assert_gates raises typed errors
# ---------------------------------------------------------------------------


class TestAssertGates:
    def test_regime_negative_raises(self):
        bad = [{
            "candidate_id": "BAD-1",
            "regime_non_negative": False,
            "cost_persistent_at_1pip": True,
            "regime_breakdown": [
                {"regime_id": "trend_high_vol", "pf_lift": -0.5},
                {"regime_id": "range_low_vol", "pf_lift": 0.1},
            ],
        }]
        with pytest.raises(RegimeNonNegativityError):
            br.assert_gates(bad)

    def test_cost_failure_raises(self):
        bad = [{
            "candidate_id": "BAD-2",
            "regime_non_negative": True,
            "cost_persistent_at_1pip": False,
            "regime_breakdown": [],
        }]
        with pytest.raises(CostSensitivityError):
            br.assert_gates(bad)

    def test_clean_passes(self):
        ok = [{
            "candidate_id": "OK",
            "regime_non_negative": True,
            "cost_persistent_at_1pip": True,
            "regime_breakdown": [],
        }]
        br.assert_gates(ok)  # no raise


# ---------------------------------------------------------------------------
# D15 enforcement — dataset SHA pin
# ---------------------------------------------------------------------------


class TestDatasetShaGuard:
    def test_mismatch_raises(self, tmp_path: Path):
        p = tmp_path / "fake.parquet"
        p.write_bytes(b"not a real parquet")
        with pytest.raises(DatasetSHAMismatchError):
            br.assert_dataset_sha(p, "0" * 64)

    def test_match_passes(self, tmp_path: Path):
        p = tmp_path / "ok.bin"
        p.write_bytes(b"hello")
        actual = br.file_sha256(p)
        br.assert_dataset_sha(p, actual)  # no raise


# ---------------------------------------------------------------------------
# Holdout sealing integrity
# ---------------------------------------------------------------------------


class TestHoldoutEncryption:
    def test_fernet_round_trip(self, tmp_path: Path):
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        plaintext = b"\x00\x01\x02 holdout payload \xff"
        cipher = Fernet(key).encrypt(plaintext)
        assert cipher != plaintext
        assert Fernet(key).decrypt(cipher) == plaintext

    def test_fernet_wrong_key_fails(self):
        from cryptography.fernet import Fernet, InvalidToken
        k1 = Fernet.generate_key()
        k2 = Fernet.generate_key()
        cipher = Fernet(k1).encrypt(b"sealed")
        with pytest.raises(InvalidToken):
            Fernet(k2).decrypt(cipher)
