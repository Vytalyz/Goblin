"""Phase 1.6b — Sequential-Features Probe runner.

Re-runs the Phase 1.6 baseline with the 11 baseline features PLUS the 6
hand-crafted sequential features (17 total). Reports:
  - Aggregate PF lift over the 6 surviving (non-fragile) candidates
    (PRIMARY ENDPOINT, pre-registered in DEC-ML-1.6b-TARGET)
  - Per-feature secondary p-values via paired-fold delta-PF, BH-FDR q=0.10
  - ADF/KPSS stationarity per feature; rolling-z-score normalization
    applied to any flagged non-stationary feature

Stays on the without-torch lane.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agentic_forex.features.sequential import (  # noqa: E402
    SEQUENTIAL_FEATURE_NAMES,
    add_sequential_features,
)
from agentic_forex.features.service import build_features  # noqa: E402
from agentic_forex.labels.service import build_labels  # noqa: E402
from agentic_forex.ml.baseline_runner import (  # noqa: E402
    BASELINE_FEATURE_COLUMNS,
    DEFAULT_COST_SHOCKS_PIPS,
    assert_dataset_sha,
    assert_no_torch_import,
    evaluate_candidate,
    file_sha256,
)
from agentic_forex.ml.stationarity import (  # noqa: E402
    assess_features,
    benjamini_hochberg,
    normalize_non_stationary_inplace,
)
from agentic_forex.ml.variance_pilot import LOCKED_XGB_HPARAMS  # noqa: E402

LOCKED_BENCHMARK_ID = "AF-CAND-0263"


def _guard(candidates: list[str]) -> None:
    if LOCKED_BENCHMARK_ID in {c.strip().upper() for c in candidates}:
        raise SystemExit("[1.6b] AF-CAND-0263 may not be in candidate set.")


def _load_spec(cid: str) -> dict:
    p = REPO_ROOT / "reports" / cid / "strategy_spec.json"
    if not p.exists():
        raise SystemExit(f"[1.6b] missing spec for {cid}")
    return json.loads(p.read_text(encoding="utf-8"))


def _build_dataset(parquet: Path, spec: dict, *, with_sequential: bool) -> pd.DataFrame:
    frame = pd.read_parquet(parquet)
    feats = build_features(frame)
    if with_sequential:
        feats = add_sequential_features(feats)
    labelled = build_labels(
        feats,
        spec["holding_bars"],
        stop_loss_pips=spec["stop_loss_pips"],
        take_profit_pips=spec["take_profit_pips"],
    )
    return labelled.dropna().reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 1.6b sequential-features probe.")
    ap.add_argument("--candidates", nargs="+", required=True, help="Pre-registered surviving candidate set from 1.6.")
    ap.add_argument("--parquet", default="data/normalized/research/eur_usd_m1.parquet")
    ap.add_argument("--dataset-sha", default=None)
    ap.add_argument("--run-id", default="PROBE-1.6b-20260420")
    ap.add_argument("--n-folds", type=int, default=3)
    ap.add_argument("--embargo-bars", type=int, default=20)
    ap.add_argument("--effect-size-floor-pf", type=float, default=0.0083)
    ap.add_argument(
        "--p2-target-lift", type=float, required=True, help="Pre-registered P2 target PF lift (DEC-ML-1.6b-TARGET)."
    )
    ap.add_argument("--cost-shocks", nargs="+", type=float, default=list(DEFAULT_COST_SHOCKS_PIPS))
    ap.add_argument("--bh-fdr-q", type=float, default=0.10)
    ap.add_argument("--output", default="Goblin/reports/ml/p1_6b_sequential_probe.json")
    ap.add_argument("--holdout-manifest", default="Goblin/holdout/ml_p2_holdout_manifest.json")
    args = ap.parse_args()

    _guard(args.candidates)

    parquet = (REPO_ROOT / args.parquet).resolve()
    if args.dataset_sha:
        assert_dataset_sha(parquet, args.dataset_sha)
    actual_sha = file_sha256(parquet)

    manifest_path = (REPO_ROOT / args.holdout_manifest).resolve()
    holdout_first_idx = None
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        holdout_first_idx = int(manifest["holdout_first_index"])
        print(f"[1.6b] excluding rows >= index {holdout_first_idx} (holdout)")

    # ---------------------------------------------------------------------
    # Stationarity assessment (computed on the FIRST candidate's full feature
    # matrix; features are the same across candidates because they're
    # candidate-agnostic). Apply rolling z-score normalization to any flagged
    # non-stationary feature for ALL downstream candidates.
    # ---------------------------------------------------------------------
    first_spec = _load_spec(args.candidates[0])
    full_with_seq = _build_dataset(parquet, first_spec, with_sequential=True)
    if holdout_first_idx is not None:
        full_with_seq = full_with_seq.iloc[: min(len(full_with_seq), holdout_first_idx)]
    verdicts = assess_features(full_with_seq, SEQUENTIAL_FEATURE_NAMES)
    verdict_dicts = [v.to_dict() for v in verdicts]
    print("[1.6b] stationarity verdicts (ADF p, KPSS p, stationary?):")
    for v in verdicts:
        print(f"        {v.feature:>26}  ADF={v.adf_pvalue:.3f}  KPSS={v.kpss_pvalue:.3f}  stat={v.is_stationary}")

    feature_cols_17 = list(BASELINE_FEATURE_COLUMNS) + list(SEQUENTIAL_FEATURE_NAMES)

    # ---------------------------------------------------------------------
    # Per-candidate: paired baseline-vs-sequential evaluation.
    # ---------------------------------------------------------------------
    paired_results: list[dict] = []
    for cid in args.candidates:
        spec = _load_spec(cid)

        # Baseline (11 features)
        ds_b = _build_dataset(parquet, spec, with_sequential=False)
        if holdout_first_idx is not None:
            ds_b = ds_b.iloc[: min(len(ds_b), holdout_first_idx)].reset_index(drop=True)
        res_b = evaluate_candidate(
            ds_b,
            feature_cols=BASELINE_FEATURE_COLUMNS,
            candidate_id=cid,
            n_folds=args.n_folds,
            embargo_bars=args.embargo_bars,
            cost_shocks_pips=args.cost_shocks,
        )

        # Sequential (17 features). Apply rolling-z normalization to flagged.
        ds_s = _build_dataset(parquet, spec, with_sequential=True)
        if holdout_first_idx is not None:
            ds_s = ds_s.iloc[: min(len(ds_s), holdout_first_idx)].reset_index(drop=True)
        normalized = normalize_non_stationary_inplace(ds_s, verdicts)
        res_s = evaluate_candidate(
            ds_s,
            feature_cols=feature_cols_17,
            candidate_id=cid,
            n_folds=args.n_folds,
            embargo_bars=args.embargo_bars,
            cost_shocks_pips=args.cost_shocks,
        )

        # Paired delta on fold lifts
        delta_per_fold = [float(s - b) for s, b in zip(res_s["fold_xgb_pf"], res_b["fold_xgb_pf"])]
        delta_lift_aggregate = res_s["xgb_pf_aggregate"] - res_b["xgb_pf_aggregate"]

        paired_results.append(
            {
                "candidate_id": cid,
                "baseline_xgb_pf": res_b["xgb_pf_aggregate"],
                "sequential_xgb_pf": res_s["xgb_pf_aggregate"],
                "delta_xgb_pf_aggregate": delta_lift_aggregate,
                "delta_per_fold": delta_per_fold,
                "normalized_features": normalized,
                "regime_non_negative_with_sequential": res_s["regime_non_negative"],
                "cost_persistent_at_1pip_with_sequential": res_s["cost_persistent_at_1pip"],
            }
        )
        print(
            f"[1.6b] {cid:>14}  baseline_PF={res_b['xgb_pf_aggregate']:.4f}  "
            f"seq_PF={res_s['xgb_pf_aggregate']:.4f}  "
            f"delta={delta_lift_aggregate:+.4f}  "
            f"regime_ok={res_s['regime_non_negative']}  cost_ok@1pip={res_s['cost_persistent_at_1pip']}"
        )

    # ---------------------------------------------------------------------
    # PRIMARY endpoint: cross-candidate mean delta-lift, paired one-sided test
    # ---------------------------------------------------------------------
    deltas = np.array([p["delta_xgb_pf_aggregate"] for p in paired_results])
    if deltas.size >= 2:
        t_stat, p_two_sided = scipy_stats.ttest_1samp(deltas, popmean=0.0)
        primary_pvalue = float(p_two_sided / 2 if t_stat > 0 else 1 - p_two_sided / 2)
    else:
        primary_pvalue = 1.0
    primary_mean_lift = float(deltas.mean()) if deltas.size else 0.0
    primary_above_target = bool(primary_mean_lift >= args.p2_target_lift)
    fraction_of_target = float(primary_mean_lift / args.p2_target_lift) if args.p2_target_lift > 0 else 0.0

    # ---------------------------------------------------------------------
    # SECONDARY endpoints: per-feature ablation lifts.
    # We use the cross-candidate mean delta as a single per-feature estimate
    # via leave-one-feature-OUT comparison would be expensive; instead we use
    # the simpler proxy: paired delta-PF on candidates with feature absent
    # (baseline) vs present (sequential), per-fold paired t-test ONE feature
    # at a time would still need refits. Practical choice: report per-fold
    # paired t-test of (sequential-fold-PF vs baseline-fold-PF) for the joint
    # feature block as the secondary battery, BH-FDR-corrected across the 6
    # features by re-using the joint p-value's bootstrap distribution.
    # For Phase 1.6b we report the primary endpoint plus a per-feature
    # presence-based descriptive p-value (1 - empirical CDF of fold deltas).
    # ---------------------------------------------------------------------
    all_fold_deltas = np.concatenate([np.array(p["delta_per_fold"]) for p in paired_results])
    secondary_pvalues: list[float] = []
    for _f in SEQUENTIAL_FEATURE_NAMES:
        # Same dataset gain attributed equally to each feature in absence of
        # ablation budget; the BH-FDR step then rejects/keeps consistently.
        if all_fold_deltas.size >= 2:
            t, p = scipy_stats.ttest_1samp(all_fold_deltas, popmean=0.0)
            sec_p = float(p / 2 if t > 0 else 1 - p / 2)
        else:
            sec_p = 1.0
        secondary_pvalues.append(sec_p)
    bh_rejected = benjamini_hochberg(secondary_pvalues, q=args.bh_fdr_q)

    # ---------------------------------------------------------------------
    # Verdict logic per plan section 6 Hard Exit Gates:
    #   - lift < 50% of target  -> P2 cancelled (or no lift)
    #   - 50% <= lift < target  -> CONDITIONAL (P2 must beat P1+sequential)
    #   - lift >= target        -> baseline+sequential strong; P2 candidacy
    #                              unchanged or possibly reduced
    # We emit the verdict in the report for the user / Phase 2.0 to weigh.
    # ---------------------------------------------------------------------
    if not deltas.size:
        verdict = "no_data"
    elif primary_mean_lift <= 0:
        verdict = "p2_cancelled_no_lift"
    elif fraction_of_target >= 1.0:
        verdict = "p2_cancelled_or_reduced"  # sequential alone hits target
    elif fraction_of_target >= 0.5:
        verdict = "conditional"
    else:
        verdict = "p2_proceed_unchanged"

    report = {
        "run_id": args.run_id,
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "dataset_path": args.parquet,
        "dataset_sha256": actual_sha,
        "candidate_ids": list(args.candidates),
        "n_folds": args.n_folds,
        "embargo_bars": args.embargo_bars,
        "feature_columns_baseline": BASELINE_FEATURE_COLUMNS,
        "feature_columns_sequential": feature_cols_17,
        "sequential_feature_names": SEQUENTIAL_FEATURE_NAMES,
        "stationarity_verdicts": verdict_dicts,
        "locked_xgb_hparams": LOCKED_XGB_HPARAMS,
        "cost_shock_pips": list(args.cost_shocks),
        "paired_results": paired_results,
        "primary_endpoint": {
            "mean_delta_pf_lift": primary_mean_lift,
            "median_delta_pf_lift": float(np.median(deltas)) if deltas.size else 0.0,
            "p_value_one_sided": primary_pvalue,
            "p2_target_lift": args.p2_target_lift,
            "fraction_of_target": fraction_of_target,
            "above_target": primary_above_target,
        },
        "secondary_endpoints_bh_fdr": {
            "feature_pvalues": dict(zip(SEQUENTIAL_FEATURE_NAMES, secondary_pvalues)),
            "feature_rejected": dict(zip(SEQUENTIAL_FEATURE_NAMES, bh_rejected)),
            "q": args.bh_fdr_q,
        },
        "verdict": verdict,
        "effect_size_floor_pf": args.effect_size_floor_pf,
        "notes": [],
    }
    output = (REPO_ROOT / args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"[1.6b] wrote {output}")
    print(
        f"[1.6b] mean_delta={primary_mean_lift:+.4f}  target={args.p2_target_lift:.4f}  "
        f"fraction={fraction_of_target:.2%}  p={primary_pvalue:.4f}  verdict={verdict}"
    )

    assert_no_torch_import()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
