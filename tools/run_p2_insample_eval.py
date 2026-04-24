"""
ML-P2.0 — In-sample evaluation of XGB on the 6 pre-registered survivors.

Runs purged walk-forward CV on the in-sample period (rows 0:N_IN_SAMPLE)
to produce the "first non-error PF on non-holdout data" that triggers the
R4-11 midpoint-prediction obligation.

The holdout rows are NEVER loaded.  This tool exists to:
  1. Confirm the training pipeline works before ceremony.
  2. Provide the point estimate for the midpoint prediction entry.
  3. Record the in-sample baseline for midpoint-to-trigger drift auditing.

After this tool exits 0, file the midpoint prediction:
  python tools/log_p2_prediction.py --phase midpoint --verdict <...> ...

Exit codes:
  0 = all 6 candidates evaluated successfully
  1 = fatal error (SHA mismatch, missing spec, etc.)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agentic_forex.features.service import build_features  # noqa: E402
from agentic_forex.labels.service import build_labels  # noqa: E402
from agentic_forex.ml.baseline_runner import (  # noqa: E402
    BASELINE_FEATURE_COLUMNS,
    DEFAULT_COST_SHOCKS_PIPS,
    evaluate_candidate,
    file_sha256,
    summarise_runs,
)

# ---------------------------------------------------------------------------
# Governance constants
# ---------------------------------------------------------------------------

DATASET_SHA = "7875ba5af620476aaba80cdec0c86680b343f70a02bf19eb40695517378ed8f1"
N_IN_SAMPLE = 155_775

PRIMARY_CANDIDATES: list[str] = [
    "AF-CAND-0734",
    "AF-CAND-0322",
    "AF-CAND-0323",
    "AF-CAND-0007",
    "AF-CAND-0002",
    "AF-CAND-0290",
]

DEFAULT_PARQUET = "data/normalized/research/eur_usd_m1.parquet"
DEFAULT_REPORT_OUT = "Goblin/reports/ml/p2_0_insample_eval.json"
DEFAULT_N_FOLDS = 3
DEFAULT_EMBARGO_BARS = 20


def _utc_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_spec(candidate_id: str, repo_root: Path = REPO_ROOT) -> dict:
    spec_path = repo_root / "reports" / candidate_id / "strategy_spec.json"
    if not spec_path.exists():
        raise FileNotFoundError(f"strategy_spec not found: {spec_path}")
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


def run_insample_eval(
    candidates: list[str],
    parquet_path: Path,
    *,
    n_folds: int = DEFAULT_N_FOLDS,
    embargo_bars: int = DEFAULT_EMBARGO_BARS,
    cost_shocks: tuple[float, ...] = DEFAULT_COST_SHOCKS_PIPS,
    seed: int = 42,
    repo_root: Path = REPO_ROOT,
) -> list[dict]:
    """Run purged-CV XGB eval on each candidate, return list of result dicts."""
    candidate_results: list[dict] = []

    for cid in candidates:
        spec = _load_spec(cid, repo_root=repo_root)
        ds = _build_dataset(parquet_path, spec)
        # Strictly in-sample only
        cap = min(len(ds), N_IN_SAMPLE)
        ds = ds.iloc[:cap].reset_index(drop=True)

        result = evaluate_candidate(
            ds,
            feature_cols=BASELINE_FEATURE_COLUMNS,
            candidate_id=cid,
            n_folds=n_folds,
            embargo_bars=embargo_bars,
            cost_shocks_pips=list(cost_shocks),
            seed=seed,
        )
        candidate_results.append(result)
        print(
            f"[p2-insample] {cid:>14}  "
            f"rule_PF={result['rule_pf_aggregate']:.4f}  "
            f"xgb_PF={result['xgb_pf_aggregate']:.4f}  "
            f"lift={result['pf_lift_aggregate']:+.4f}  "
            f"regime_ok={result['regime_non_negative']}  "
            f"cost_ok@1pip={result['cost_persistent_at_1pip']}"
        )

    return candidate_results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ML-P2.0 in-sample evaluation (pre-ceremony)")
    ap.add_argument("--parquet", default=DEFAULT_PARQUET)
    ap.add_argument("--n-folds", type=int, default=DEFAULT_N_FOLDS)
    ap.add_argument("--embargo-bars", type=int, default=DEFAULT_EMBARGO_BARS)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--output", default=DEFAULT_REPORT_OUT)
    args = ap.parse_args(argv)

    parquet_path = (REPO_ROOT / args.parquet).resolve()
    output_path = (REPO_ROOT / args.output).resolve()

    if not parquet_path.exists():
        print(f"FATAL: parquet not found: {parquet_path}", file=sys.stderr)
        return 1

    print("[p2-insample] verifying dataset SHA...")
    actual_sha = file_sha256(parquet_path)
    if actual_sha != DATASET_SHA:
        print(f"FATAL: SHA mismatch: {actual_sha}", file=sys.stderr)
        return 1
    print(f"[p2-insample] SHA OK: {actual_sha[:16]}...")

    print(f"[p2-insample] evaluating {len(PRIMARY_CANDIDATES)} primary candidates (in-sample only)...")

    try:
        candidate_results = run_insample_eval(
            PRIMARY_CANDIDATES,
            parquet_path,
            n_folds=args.n_folds,
            embargo_bars=args.embargo_bars,
            seed=args.seed,
        )
    except FileNotFoundError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1

    summary = summarise_runs(candidate_results, effect_size_floor_pf=0.0083)

    print("\n[p2-insample] --- Summary ---")
    print(f"[p2-insample] mean PF lift  : {summary['mean_pf_lift']:+.4f}")
    print(f"[p2-insample] median PF lift: {summary['median_pf_lift']:+.4f}")
    print(
        f"[p2-insample] frac above floor: {summary['fraction_above_effect_size_floor']:.2f}"
    )
    print(
        f"\n[p2-insample] NEXT STEP: file midpoint prediction:\n"
        f"  python tools/log_p2_prediction.py "
        f"--phase midpoint --verdict <GO|CONDITIONAL|NO_GO> "
        f"--point-estimate {summary['mean_pf_lift']:.4f} "
        f"--ci-low <...> --ci-high <...> "
        f"--rationale '<...>' --attestation '<...>'"
    )

    # Write report
    lifts = [c["pf_lift_aggregate"] for c in candidate_results]
    report = {
        "report_id": f"P2-INSAMPLE-EVAL-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "generated_utc": _utc_iso(),
        "n_in_sample_rows": N_IN_SAMPLE,
        "dataset_sha256": DATASET_SHA,
        "n_folds": args.n_folds,
        "embargo_bars": args.embargo_bars,
        "primary_candidates": PRIMARY_CANDIDATES,
        "candidate_results": candidate_results,
        "summary": {
            "mean_pf_lift": float(np.mean(lifts)),
            "median_pf_lift": float(np.median(lifts)),
            "min_pf_lift": float(np.min(lifts)),
            "max_pf_lift": float(np.max(lifts)),
            "fraction_above_0083_floor": float(
                np.mean([lift_value >= 0.0083 for lift_value in lifts])
            ),
        },
        "governance_note": (
            "In-sample CV result only. Holdout NOT loaded. "
            "File midpoint prediction before ceremony."
        ),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n[p2-insample] report written: {output_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
