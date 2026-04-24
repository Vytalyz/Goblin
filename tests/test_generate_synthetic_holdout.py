"""Tests for tools/generate_synthetic_holdout.py (EX-8)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import generate_synthetic_holdout as gsh  # noqa: E402

PARQUET = REPO_ROOT / "data" / "normalized" / "research" / "eur_usd_m1.parquet"
MANIFEST = REPO_ROOT / "Goblin" / "holdout" / "ml_p2_holdout_manifest.json"


def _skip_if_data_missing():
    if not PARQUET.exists() or not MANIFEST.exists():
        pytest.skip("dataset or holdout manifest not present (LFS / sealed)")


def test_generate_writes_requested_rows(tmp_path):
    _skip_if_data_missing()
    out = tmp_path / "synth.parquet"
    meta = gsh.generate(
        parquet_path=PARQUET,
        holdout_manifest=MANIFEST,
        out_path=out,
        n_rows=2000,
        seed=20260420,
    )
    assert out.exists()
    assert meta["n_rows_written"] == 2000


def test_generate_is_deterministic_under_same_seed(tmp_path):
    _skip_if_data_missing()
    out1 = tmp_path / "a.parquet"
    out2 = tmp_path / "b.parquet"
    gsh.generate(parquet_path=PARQUET, holdout_manifest=MANIFEST, out_path=out1, n_rows=1000, seed=99)
    gsh.generate(parquet_path=PARQUET, holdout_manifest=MANIFEST, out_path=out2, n_rows=1000, seed=99)
    import pandas as pd

    a = pd.read_parquet(out1)
    b = pd.read_parquet(out2)
    pd.testing.assert_frame_equal(a, b)


def test_generate_different_seeds_differ(tmp_path):
    _skip_if_data_missing()
    out1 = tmp_path / "s1.parquet"
    out2 = tmp_path / "s2.parquet"
    gsh.generate(parquet_path=PARQUET, holdout_manifest=MANIFEST, out_path=out1, n_rows=500, seed=1)
    gsh.generate(parquet_path=PARQUET, holdout_manifest=MANIFEST, out_path=out2, n_rows=500, seed=2)
    import pandas as pd

    a = pd.read_parquet(out1)
    b = pd.read_parquet(out2)
    # Different seeds → different row selection / permutation; high probability they differ
    assert not a.equals(b)


def test_4_regime_coverage_under_frozen_thresholds(tmp_path):
    _skip_if_data_missing()
    out = tmp_path / "synth.parquet"
    gsh.generate(parquet_path=PARQUET, holdout_manifest=MANIFEST, out_path=out, n_rows=10000, seed=20260420)
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    cfg = tomllib.loads((REPO_ROOT / "config" / "eval_gates.toml").read_text())
    regimes = gsh.assert_4_regime_coverage(out, ml_regime_cfg=cfg["ml_regime"])
    # All four regimes present and >= 1% (asserted inside function); also sanity-check sum
    assert sum(regimes.values()) == 10000
    assert all(n > 0 for n in regimes.values()), f"empty regime: {regimes}"
