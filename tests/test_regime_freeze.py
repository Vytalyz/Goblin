"""
EX-6 — Asserts the frozen regime split thresholds in [ml_regime] are not modified.

The thresholds in config/eval_gates.toml [ml_regime] were computed once from
the in-sample portion of the locked dataset (SHA 7875ba5a...). Any change
shifts the regime composition for every subsequent gate evaluation, breaking
cross-candidate comparability of the regime non-negativity gate. Modifying
these values is allowed only via:
  1. A new EX-6.x decision log entry recording the recomputation, AND
  2. CODEOWNERS review on config/eval_gates.toml.

If either expected value below changes, this test fails LOUDLY and the
modifier must update the test in the SAME commit (forcing visibility).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_eval_gates() -> dict:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with (REPO_ROOT / "config" / "eval_gates.toml").open("rb") as f:
        return tomllib.load(f)


# Locked at EX-6 from the 1.6 in-sample portion (155,775 rows; rows
# [0:holdout_first_index]) of dataset SHA 7875ba5af620476a...
EXPECTED_ABS_MOMENTUM_12_MEDIAN = 1.9000000000
EXPECTED_VOLATILITY_20_MEDIAN = 0.0000741639
EXPECTED_N_ROWS = 155775
EXPECTED_DATASET_SHA = (
    "7875ba5af620476aaba80cdec0c86680b343f70a02bf19eb40695517378ed8f1"
)


class TestRegimeFreezeImmutable:
    def test_block_present(self):
        cfg = _load_eval_gates()
        assert "ml_regime" in cfg, (
            "[ml_regime] missing from config/eval_gates.toml. "
            "EX-6 froze these values; do not delete the block."
        )

    def test_abs_momentum_median_unchanged(self):
        cfg = _load_eval_gates()
        assert cfg["ml_regime"]["abs_momentum_12_median"] == EXPECTED_ABS_MOMENTUM_12_MEDIAN, (
            "abs_momentum_12_median changed since EX-6 freeze. Recomputation "
            "requires a new EX-6.x decision log entry; update this test in "
            "the same commit."
        )

    def test_volatility_median_unchanged(self):
        cfg = _load_eval_gates()
        assert cfg["ml_regime"]["volatility_20_median"] == EXPECTED_VOLATILITY_20_MEDIAN, (
            "volatility_20_median changed since EX-6 freeze. Recomputation "
            "requires a new EX-6.x decision log entry; update this test in "
            "the same commit."
        )

    def test_in_sample_row_count_unchanged(self):
        cfg = _load_eval_gates()
        assert cfg["ml_regime"]["n_in_sample_rows_used"] == EXPECTED_N_ROWS

    def test_dataset_sha_at_freeze_matches_baseline_pin(self):
        cfg = _load_eval_gates()
        assert cfg["ml_regime"]["dataset_sha256_at_freeze"] == EXPECTED_DATASET_SHA
        # Cross-check: matches the [ml_baseline_comparison] pin
        assert (
            cfg["ml_regime"]["dataset_sha256_at_freeze"]
            == cfg["ml_baseline_comparison"]["dataset_sha"]
        )


class TestRegimeFreezePropertyConsistency:
    """If someone recomputes the medians from the same dataset+slice, they
    must get the same numbers. This is a property test of stability."""

    def test_recompute_matches_frozen_value(self):
        import json
        import sys

        sys.path.insert(0, str(REPO_ROOT / "src"))
        import pandas as pd  # noqa: PLC0415
        from agentic_forex.features.service import build_features  # noqa: PLC0415

        parquet = REPO_ROOT / "data" / "normalized" / "research" / "eur_usd_m1.parquet"
        manifest = REPO_ROOT / "Goblin" / "holdout" / "ml_p2_holdout_manifest.json"
        if not parquet.exists() or not manifest.exists():
            import pytest

            pytest.skip("dataset or holdout manifest not present (LFS / sealed)")

        m = json.loads(manifest.read_text())
        holdout_first_idx = int(m["holdout_first_index"])
        raw = pd.read_parquet(parquet)
        in_sample = raw.iloc[:holdout_first_idx].reset_index(drop=True)
        feats = build_features(in_sample)
        both = feats[["momentum_12", "volatility_20"]].dropna()
        recomputed_mom = float(both["momentum_12"].abs().median())
        recomputed_vol = float(both["volatility_20"].median())

        assert abs(recomputed_mom - EXPECTED_ABS_MOMENTUM_12_MEDIAN) < 1e-9
        # Allow tiny floating tolerance for the volatility figure (it has more decimals)
        assert abs(recomputed_vol - EXPECTED_VOLATILITY_20_MEDIAN) < 1e-10
