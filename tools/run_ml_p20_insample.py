"""ML-P2.0 — In-sample evaluation on 6 primary survivors (midpoint evidence).

Trains XGB via purged walk-forward CV on the in-sample partition
(rows 0..N_IN_SAMPLE-1 = 155774) for each of the 6 pre-registered
survivors.  Uses the same LOCKED_XGB_HPARAMS and BASELINE_FEATURE_COLUMNS
as Phase 1.6 (no new hyper-parameters, no new features).

Output: Goblin/reports/ml/p2_0_insample_evaluation.json

After this script exits 0, the owner must file a MIDPOINT prediction in
Goblin/decisions/predictions.jsonl before holdout access (see printed
instructions).  The prediction must satisfy the schema documented in
Goblin/decisions/PREDICTIONS_SCHEMA.md.

Pre-registered constants enforced here:
  - SURVIVORS  = {0734, 0322, 0323, 0007, 0002, 0290}   (DEC-ML-2.0-CANDIDATES)
  - N_IN_SAMPLE = 155_775                                (EX-6 / [ml_regime])
  - DATASET_SHA  = 7875ba5a…                             (EX-7 pin)
  - LOCKED_XGB_HPARAMS                                   (PILOT-1.6.0-20260420)
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agentic_forex.features.service import build_features  # noqa: E402
from agentic_forex.labels.service import build_labels  # noqa: E402
from agentic_forex.ml.baseline_runner import (  # noqa: E402
    BASELINE_FEATURE_COLUMNS,
    DEFAULT_COST_SHOCKS_PIPS,
    assert_dataset_sha,
    assert_no_torch_import,
    evaluate_candidate,
    file_sha256,
    summarise_runs,
)
from agentic_forex.ml.variance_pilot import LOCKED_XGB_HPARAMS  # noqa: E402

# ---------------------------------------------------------------------------
# Pre-registered constants
# ---------------------------------------------------------------------------

SURVIVORS: tuple[str, ...] = (
    "AF-CAND-0734",
    "AF-CAND-0322",
    "AF-CAND-0323",
    "AF-CAND-0007",
    "AF-CAND-0002",
    "AF-CAND-0290",
)

N_IN_SAMPLE: int = 155_775
DATASET_SHA = "7875ba5af620476aaba80cdec0c86680b343f70a02bf19eb40695517378ed8f1"
PARQUET_REL = "data/normalized/research/eur_usd_m1.parquet"
OUTPUT_REL = "Goblin/reports/ml/p2_0_insample_evaluation.json"
EFFECT_SIZE_FLOOR_PF: float = 0.0083  # locked from PILOT-1.6.0-20260420


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _head_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=str(REPO_ROOT),
        )
        return r.stdout.strip()
    except Exception:
        return "unknown"


def _load_spec(candidate_id: str) -> dict:
    path = REPO_ROOT / "reports" / candidate_id / "strategy_spec.json"
    if not path.exists():
        raise SystemExit(f"[p20-insample] strategy_spec not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    assert_no_torch_import()

    parquet = (REPO_ROOT / PARQUET_REL).resolve()
    if not parquet.exists():
        print(f"[p20-insample] FATAL: parquet not found: {parquet}", file=sys.stderr)
        return 2

    assert_dataset_sha(parquet, DATASET_SHA)
    actual_sha = file_sha256(parquet)

    # Build features on the in-sample slice only (avoids GMM on 194K rows
    # while still providing proper rolling-window context per bar).
    print("[p20-insample] loading parquet (in-sample slice) ...", flush=True)
    frame_insample = pd.read_parquet(parquet).iloc[:N_IN_SAMPLE]
    print("[p20-insample] building features ...", flush=True)
    full_features = build_features(frame_insample)

    candidate_results: list[dict] = []
    for cid in SURVIVORS:
        spec = _load_spec(cid)
        labelled = (
            build_labels(
                full_features.copy(),
                spec["holding_bars"],
                stop_loss_pips=spec["stop_loss_pips"],
                take_profit_pips=spec["take_profit_pips"],
            )
            .dropna()
            .reset_index(drop=True)
        )

        result = evaluate_candidate(
            labelled,
            feature_cols=BASELINE_FEATURE_COLUMNS,
            candidate_id=cid,
            n_folds=3,
            embargo_bars=20,
            cost_shocks_pips=list(DEFAULT_COST_SHOCKS_PIPS),
        )
        candidate_results.append(result)
        print(
            f"[p20-insample] {cid:>14}  "
            f"rule_PF={result['rule_pf_aggregate']:.4f}  "
            f"xgb_PF={result['xgb_pf_aggregate']:.4f}  "
            f"lift={result['pf_lift_aggregate']:+.4f}",
            flush=True,
        )

    summary = summarise_runs(candidate_results, effect_size_floor_pf=EFFECT_SIZE_FLOOR_PF)
    head_sha = _head_sha()

    report = {
        "run_id": f"P20-INSAMPLE-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        "stage": "midpoint_evidence",
        "evaluation_type": "in_sample_purged_cv",
        "generated_utc": _utc_now(),
        "commit_sha": head_sha,
        "dataset_sha256": actual_sha,
        "n_in_sample_rows": N_IN_SAMPLE,
        "survivors": list(SURVIVORS),
        "locked_xgb_hparams": LOCKED_XGB_HPARAMS,
        "n_folds": 3,
        "embargo_bars": 20,
        "effect_size_floor_pf": EFFECT_SIZE_FLOOR_PF,
        "summary": summary,
        "candidate_results": candidate_results,
    }

    out_path = (REPO_ROOT / OUTPUT_REL).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print()
    print("=" * 68)
    print("ML-P2.0 IN-SAMPLE EVALUATION COMPLETE (midpoint evidence)")
    print("=" * 68)
    print(f"  Mean PF lift (XGB vs rule, in-sample CV) : {summary['mean_pf_lift']:+.4f}")
    print(f"  Median PF lift                           : {summary['median_pf_lift']:+.4f}")
    print(f"  Report                                   : {out_path.relative_to(REPO_ROOT)}")
    print()
    print("NEXT STEP -- file MIDPOINT prediction BEFORE holdout access:")
    print("  prediction_id             : PRED-ML-2.0-MIDPOINT-1")
    print("  phase                     : midpoint")
    print(f"  commit_sha_at_prediction  : {head_sha}")
    print("  Append to                 : Goblin/decisions/predictions.jsonl")
    print("  Schema                    : Goblin/decisions/PREDICTIONS_SCHEMA.md")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
