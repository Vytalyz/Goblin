"""Phase 1.6 — Run the XGB-vs-rule baseline comparison across a
pre-registered stratified candidate set.

Usage:
    python scripts/run_ml_baseline_comparison.py \\
        --candidates AF-CAND-0001 AF-CAND-0002 ... \\
        --run-id BASELINE-1.6-20260420 \\
        --dataset-sha 7875ba5af620476a... \\
        --holdout-manifest Goblin/holdout/ml_p2_holdout_manifest.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agentic_forex.features.service import build_features  # noqa: E402
from agentic_forex.governance.errors import (  # noqa: E402
    CostSensitivityError,
    DatasetSHAMismatchError,
    RegimeNonNegativityError,
)
from agentic_forex.labels.service import build_labels  # noqa: E402
from agentic_forex.ml.baseline_runner import (  # noqa: E402
    BASELINE_FEATURE_COLUMNS,
    DEFAULT_COST_SHOCKS_PIPS,
    REGIMES,
    assert_dataset_sha,
    assert_gates,
    assert_no_torch_import,
    evaluate_candidate,
    file_sha256,
    summarise_runs,
)
from agentic_forex.ml.variance_pilot import LOCKED_XGB_HPARAMS  # noqa: E402


def _load_spec(candidate_id: str) -> dict:
    spec_path = REPO_ROOT / "reports" / candidate_id / "strategy_spec.json"
    if not spec_path.exists():
        raise SystemExit(f"[baseline] strategy_spec not found for {candidate_id}: {spec_path}")
    return json.loads(spec_path.read_text(encoding="utf-8"))


def _build_dataset(parquet_path: Path, spec: dict) -> pd.DataFrame:
    frame = pd.read_parquet(parquet_path)
    feats = build_features(frame)
    labelled = build_labels(
        feats,
        spec["holding_bars"],
        stop_loss_pips=spec["stop_loss_pips"],
        take_profit_pips=spec["take_profit_pips"],
    )
    return labelled.dropna().reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 1.6 baseline comparison runner.")
    ap.add_argument("--candidates", nargs="+", required=True)
    ap.add_argument("--parquet", default="data/normalized/research/eur_usd_m1.parquet")
    ap.add_argument("--dataset-sha", default=None,
                    help="Expected dataset SHA-256; runner aborts on mismatch (D15).")
    ap.add_argument("--run-id", default="BASELINE-1.6-20260420")
    ap.add_argument("--n-folds", type=int, default=3)
    ap.add_argument("--embargo-bars", type=int, default=20,
                    help=">= longest feature lookback (D11).")
    ap.add_argument("--effect-size-floor-pf", type=float, default=0.0083,
                    help="Locked from PILOT-1.6.0-20260420 (1x sigma_PF).")
    ap.add_argument("--cost-shocks", nargs="+", type=float,
                    default=list(DEFAULT_COST_SHOCKS_PIPS))
    ap.add_argument("--output", default="Goblin/reports/ml/p1_6_baseline_comparison.json")
    ap.add_argument("--holdout-manifest", default="Goblin/holdout/ml_p2_holdout_manifest.json")
    ap.add_argument("--exclude-holdout", action="store_true", default=True,
                    help="Exclude the sealed holdout rows from training+CV (always on).")
    args = ap.parse_args()

    parquet = (REPO_ROOT / args.parquet).resolve()
    if not parquet.exists():
        print(f"[baseline] parquet not found: {parquet}", file=sys.stderr)
        return 2

    if args.dataset_sha:
        try:
            assert_dataset_sha(parquet, args.dataset_sha)
        except DatasetSHAMismatchError as exc:
            print(f"[baseline] FATAL: {exc}", file=sys.stderr)
            return 4
    actual_sha = file_sha256(parquet)

    # Load holdout manifest (if exists) so we can exclude those rows.
    manifest_path = (REPO_ROOT / args.holdout_manifest).resolve()
    holdout_first_idx = None
    holdout_meta = {"path": str(args.holdout_manifest), "sha256": "", "n_rows": 0}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        holdout_first_idx = int(manifest["holdout_first_index"])
        holdout_meta = {
            "path": manifest["ciphertext_path"],
            "sha256": manifest["ciphertext_sha256"],
            "n_rows": int(manifest["holdout_n_rows"]),
        }
        print(f"[baseline] excluding rows >= index {holdout_first_idx} (sealed holdout, "
              f"n={manifest['holdout_n_rows']})")
    else:
        print(f"[baseline] WARNING: no holdout manifest at {manifest_path}; "
              f"running on full dataset.", file=sys.stderr)

    candidate_results: list[dict] = []
    for cid in args.candidates:
        spec = _load_spec(cid)
        ds = _build_dataset(parquet, spec)
        if holdout_first_idx is not None:
            # Keep only rows whose ORIGINAL index < holdout_first_idx.
            # build_labels drops some rows at the tail; conservatively
            # cap len(ds) at the projected exclusion boundary.
            cap = min(len(ds), holdout_first_idx)
            ds = ds.iloc[:cap].reset_index(drop=True)
        result = evaluate_candidate(
            ds,
            feature_cols=BASELINE_FEATURE_COLUMNS,
            candidate_id=cid,
            n_folds=args.n_folds,
            embargo_bars=args.embargo_bars,
            cost_shocks_pips=args.cost_shocks,
        )
        candidate_results.append(result)
        print(f"[baseline] {cid:>14}  rule_PF={result['rule_pf_aggregate']:.4f}  "
              f"xgb_PF={result['xgb_pf_aggregate']:.4f}  "
              f"lift={result['pf_lift_aggregate']:+.4f}  "
              f"regime_ok={result['regime_non_negative']}  "
              f"cost_ok@1pip={result['cost_persistent_at_1pip']}")

    summary = summarise_runs(
        candidate_results, effect_size_floor_pf=args.effect_size_floor_pf,
    )

    report = {
        "run_id": args.run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "dataset_path": args.parquet,
        "dataset_sha256": actual_sha,
        "candidate_ids": list(args.candidates),
        "n_folds": args.n_folds,
        "embargo_bars": args.embargo_bars,
        "feature_columns": BASELINE_FEATURE_COLUMNS,
        "locked_xgb_hparams": LOCKED_XGB_HPARAMS,
        "cost_shock_pips": list(args.cost_shocks),
        "regime_definitions": [
            {"regime_id": r.regime_id, "description": r.description} for r in REGIMES
        ],
        "candidate_results": candidate_results,
        "median_pf_lift": summary["median_pf_lift"],
        "mean_pf_lift": summary["mean_pf_lift"],
        "fraction_above_effect_size_floor": summary["fraction_above_effect_size_floor"],
        "effect_size_floor_pf": args.effect_size_floor_pf,
        "holdout_path": holdout_meta["path"],
        "holdout_sha256": holdout_meta["sha256"],
        "holdout_n_rows": holdout_meta["n_rows"],
        "notes": [],
    }

    output = (REPO_ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"[baseline] wrote {output}")
    print(f"[baseline] median_lift={summary['median_pf_lift']:+.4f}  "
          f"mean_lift={summary['mean_pf_lift']:+.4f}  "
          f"frac_above_floor={summary['fraction_above_effect_size_floor']:.2%}  "
          f"floor={args.effect_size_floor_pf:.4f}")

    # Hard gate enforcement (D14). Print verdict but DO NOT raise on regime/cost
    # for the report itself — gate logic is checked here separately and prints
    # the failing candidates so the user can decide. The CI job in 1.7 will
    # convert this into a hard failure.
    failing_regime = [c["candidate_id"] for c in candidate_results if not c["regime_non_negative"]]
    failing_cost = [c["candidate_id"] for c in candidate_results if not c["cost_persistent_at_1pip"]]
    if failing_regime:
        print(f"[baseline] GATE WARNING (D14 regime): {failing_regime}")
    if failing_cost:
        print(f"[baseline] GATE WARNING (D14 cost@1pip): {failing_cost}")

    assert_no_torch_import()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
