"""
EX-8 — Synthetic holdout generator for the EX-10 end-to-end rehearsal.

Strategy: sample rows from the in-sample (chronologically-earliest 80%)
portion, apply build_features, then SHUFFLE rows and PERMUTE labels.
Shuffling preserves marginal distributions of features (so all 4 regimes
remain represented under the EX-6 frozen thresholds) but destroys the
temporal sequence; permuting labels destroys any signal so the rehearsal
cannot leak information about the true sealed holdout's behavior.

Usage:
    python tools/generate_synthetic_holdout.py \\
        --out Goblin/holdout/ml_p2_synthetic_rehearsal.parquet \\
        --n-rows 38944 \\
        --seed 20260420
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def generate(
    *,
    parquet_path: Path,
    holdout_manifest: Path,
    out_path: Path,
    n_rows: int,
    seed: int,
) -> dict:
    """Generate the synthetic holdout. Returns a metadata dict."""
    sys.path.insert(0, str(REPO_ROOT / "src"))
    import numpy as np
    import pandas as pd

    from agentic_forex.features.service import build_features  # noqa: PLC0415
    from agentic_forex.labels.service import build_labels  # noqa: PLC0415

    if not parquet_path.exists():
        raise SystemExit(f"FAIL: parquet not found: {parquet_path}")
    manifest = json.loads(holdout_manifest.read_text())
    holdout_first_idx = int(manifest["holdout_first_index"])

    raw = pd.read_parquet(parquet_path)
    in_sample = raw.iloc[:holdout_first_idx].reset_index(drop=True)
    feats = build_features(in_sample)
    # Use a generic 5-bar holding window for label generation; rehearsal
    # only cares that columns exist, not their economic interpretation.
    labelled = build_labels(feats, holding_bars=5, stop_loss_pips=10.0, take_profit_pips=10.0)
    labelled = labelled.dropna().reset_index(drop=True)

    rng = np.random.default_rng(seed)
    n_avail = len(labelled)
    if n_rows > n_avail:
        raise SystemExit(f"FAIL: requested {n_rows} rows but only {n_avail} available in-sample")
    # Sample (without replacement) and shuffle.
    chosen_idx = rng.choice(n_avail, size=n_rows, replace=False)
    shuffled = labelled.iloc[chosen_idx].reset_index(drop=True)

    # Permute label columns (any column starting with 'label_' or 'outcome_')
    # to destroy signal while preserving regime composition.
    permuted = shuffled.copy()
    label_cols = [c for c in permuted.columns if c.startswith("label_") or c.startswith("outcome_")]
    perm = rng.permutation(len(permuted))
    for col in label_cols:
        permuted[col] = permuted[col].to_numpy()[perm]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    permuted.to_parquet(out_path, index=False)

    try:
        rel_out = str(out_path.relative_to(REPO_ROOT))
    except ValueError:
        rel_out = str(out_path)
    return {
        "out_path": rel_out,
        "n_rows_written": int(len(permuted)),
        "n_in_sample_available": int(n_avail),
        "seed": int(seed),
        "label_columns_permuted": label_cols,
        "source_dataset_sha256_inputs": str(parquet_path),
    }


def assert_4_regime_coverage(parquet_path: Path, *, ml_regime_cfg: dict) -> dict:
    """Verify all 4 regimes have at least 1% of rows under the frozen thresholds."""
    import pandas as pd

    df = pd.read_parquet(parquet_path)
    abs_mom = df["momentum_12"].abs()
    vol = df["volatility_20"]
    mom_thr = ml_regime_cfg["abs_momentum_12_median"]
    vol_thr = ml_regime_cfg["volatility_20_median"]

    regimes = {
        "trend_high_vol": int(((abs_mom > mom_thr) & (vol > vol_thr)).sum()),
        "trend_low_vol": int(((abs_mom > mom_thr) & (vol <= vol_thr)).sum()),
        "range_high_vol": int(((abs_mom <= mom_thr) & (vol > vol_thr)).sum()),
        "range_low_vol": int(((abs_mom <= mom_thr) & (vol <= vol_thr)).sum()),
    }
    total = sum(regimes.values())
    floor = max(1, total // 100)  # at least 1% per regime
    missing = [r for r, n in regimes.items() if n < floor]
    if missing:
        raise AssertionError(f"4-regime coverage failed: {missing} have < 1% of rows. Counts: {regimes}, total={total}")
    return regimes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EX-8 synthetic holdout generator")
    parser.add_argument(
        "--parquet",
        type=Path,
        default=REPO_ROOT / "data" / "normalized" / "research" / "eur_usd_m1.parquet",
    )
    parser.add_argument(
        "--holdout-manifest",
        type=Path,
        default=REPO_ROOT / "Goblin" / "holdout" / "ml_p2_holdout_manifest.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "Goblin" / "holdout" / "ml_p2_synthetic_rehearsal.parquet",
    )
    parser.add_argument("--n-rows", type=int, default=38944)
    parser.add_argument("--seed", type=int, default=20260420)
    parser.add_argument(
        "--check-coverage",
        action="store_true",
        help="After writing, assert all 4 regimes >= 1% of rows",
    )
    args = parser.parse_args(argv)

    meta = generate(
        parquet_path=args.parquet,
        holdout_manifest=args.holdout_manifest,
        out_path=args.out,
        n_rows=args.n_rows,
        seed=args.seed,
    )
    print(json.dumps(meta, indent=2))

    if args.check_coverage:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        cfg = tomllib.loads((REPO_ROOT / "config" / "eval_gates.toml").read_text())
        regimes = assert_4_regime_coverage(args.out, ml_regime_cfg=cfg["ml_regime"])
        print("4-regime coverage:", regimes)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
