"""
ML-P2.0 — Holdout evaluation pipeline.

Invoked by the holdout access ceremony (EX-4) with the decrypted parquet path
as its single positional argument.  Trains XGB on in-sample data, evaluates on
the sealed holdout, runs BCa moving-block bootstrap + Bonferroni 4 regime
sub-tests, applies the Q1 secondary-cohort diagnostic, renders the
pre-registered verdict, and writes the report.

Pre-registration reference: DEC-ML-2.0-TARGET (Goblin/decisions/ml_decisions.jsonl)
Amendment A1: DEC-ML-1.6b-A1-AUTHORIZATION (sequential CNN excluded from primary)

Exit codes:
  0 = verdict rendered (GO / CONDITIONAL / CONDITIONAL_RESTRICTED / NO_GO)
  1 = fatal error (data missing, SHA mismatch, spec load failure, etc.)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agentic_forex.features.service import build_features  # noqa: E402
from agentic_forex.labels.service import build_labels  # noqa: E402
from agentic_forex.ml.baseline_runner import (  # noqa: E402
    BASELINE_FEATURE_COLUMNS,
    assign_regimes,
    file_sha256,
    profit_factor,
    rule_baseline_signal,
    xgb_signal,
)
from agentic_forex.ml.variance_pilot import LOCKED_XGB_HPARAMS  # noqa: E402

# ---------------------------------------------------------------------------
# Governance constants — locked by DEC-ML-2.0-TARGET / DEC-ML-2.0-CANDIDATES
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

FRAGILE_CANDIDATES: list[str] = [
    "AF-CAND-0716",
    "AF-CAND-0738",
    "AF-CAND-0739",
    "AF-CAND-0009",
    "AF-CAND-0001",
]

# Verdict bands
TARGET_PF_LIFT_GO: float = 0.10
CONDITIONAL_FLOOR: float = 0.055
SIGMA_CROSS: float = 0.0211004853
Q1_CONDITIONAL_THRESHOLD: float = -1.0 * SIGMA_CROSS   # -0.0211…
Q1_NOGO_THRESHOLD: float = -2.0 * SIGMA_CROSS          # -0.0422…
Q1_BREADTH_N_FRAGILE_NEGATIVE: int = 3

# BCa bootstrap parameters
BOOTSTRAP_N: int = 10_000
BOOTSTRAP_SEED: int = 20_260_420
BOOTSTRAP_BLOCK_SIZE_MIN: int = 20

# Bonferroni
BONFERRONI_FAMILY: int = 4
BONFERRONI_PER_TEST_ALPHA: float = 0.0025  # 0.01 / 4

REGIME_IDS: tuple[str, ...] = (
    "trend_high_vol",
    "trend_low_vol",
    "range_high_vol",
    "range_low_vol",
)

DEFAULT_INSAMPLE_PARQUET = "data/normalized/research/eur_usd_m1.parquet"
DEFAULT_REPORT_OUT = "Goblin/reports/ml/p2_0_holdout_eval_report.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_spec(candidate_id: str, repo_root: Path = REPO_ROOT) -> dict:
    spec_path = repo_root / "reports" / candidate_id / "strategy_spec.json"
    if not spec_path.exists():
        raise FileNotFoundError(f"strategy_spec not found: {spec_path}")
    return json.loads(spec_path.read_text(encoding="utf-8"))


def _build_dataset(raw: pd.DataFrame, spec: dict) -> pd.DataFrame:
    feats = build_features(raw)
    labelled = build_labels(
        feats,
        spec["holding_bars"],
        stop_loss_pips=spec["stop_loss_pips"],
        take_profit_pips=spec["take_profit_pips"],
    )
    return labelled


def _train_xgb(
    insample_df: pd.DataFrame,
    feature_cols: list[str],
    seed: int = 42,
) -> xgb.XGBClassifier:
    """Train XGB on full in-sample data (no CV — holdout IS the test set)."""
    valid = insample_df[feature_cols + ["label_up"]].dropna()
    X = valid[feature_cols]
    y = valid["label_up"]
    model = xgb.XGBClassifier(**LOCKED_XGB_HPARAMS, random_state=seed)
    model.fit(X, y)
    return model


def _outcome_pips(dataset: pd.DataFrame, side: np.ndarray) -> np.ndarray:
    return dataset["long_outcome_pips"].to_numpy() * side


# ---------------------------------------------------------------------------
# BCa moving-block bootstrap
# ---------------------------------------------------------------------------

def bca_moving_block_bootstrap(
    xgb_out: np.ndarray,
    rule_out: np.ndarray,
    n_resamples: int = BOOTSTRAP_N,
    seed: int = BOOTSTRAP_SEED,
    block_size_min: int = BOOTSTRAP_BLOCK_SIZE_MIN,
) -> dict:
    """BCa moving-block bootstrap CI on mean per-trade lift (XGB - rule).

    Returns a dict with keys: mean, ci_low_95, ci_high_95, n_trades, block_size.
    """
    from scipy.stats import norm

    lift = xgb_out - rule_out
    n = len(lift)
    if n == 0:
        return {"mean": 0.0, "ci_low_95": 0.0, "ci_high_95": 0.0, "n_trades": 0, "block_size": 0}

    observed_mean = float(lift.mean())

    block_size = max(block_size_min, int(np.sqrt(n) / 4))
    n_blocks = int(np.ceil(n / block_size))
    starts = np.arange(n - block_size + 1) if n >= block_size else np.array([0])

    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_resamples)

    for i in range(n_resamples):
        chosen = rng.choice(starts, size=n_blocks, replace=True)
        idx = np.concatenate([np.arange(s, s + block_size) for s in chosen])[:n]
        boot_means[i] = lift[idx].mean()

    # Bias correction z0
    prop_less = float(np.mean(boot_means < observed_mean))
    prop_less = max(1e-9, min(1.0 - 1e-9, prop_less))
    z0 = float(norm.ppf(prop_less))

    # Acceleration via jackknife (capped at 500 obs for speed)
    jack_n = min(n, 500)
    step = max(1, n // jack_n)
    jack_idx = list(range(0, n, step))[:jack_n]
    jack_means = np.array([
        np.delete(lift, j).mean() if n > 1 else 0.0
        for j in jack_idx
    ])
    jack_bar = jack_means.mean()
    diff = jack_bar - jack_means
    num = float((diff ** 3).sum())
    den = float(6.0 * (diff ** 2).sum() ** 1.5)
    a_hat = num / den if abs(den) > 1e-15 else 0.0

    z_low = float(norm.ppf(0.025))
    z_high = float(norm.ppf(0.975))

    def _adj_pctile(z_a: float) -> float:
        inner = z0 + z_a
        denom = 1.0 - a_hat * inner
        if abs(denom) < 1e-9:
            denom = 1e-9
        return float(norm.cdf(z0 + inner / denom))

    p_low = max(0.001, min(0.999, _adj_pctile(z_low)))
    p_high = max(0.001, min(0.999, _adj_pctile(z_high)))

    ci_low = float(np.percentile(boot_means, 100.0 * p_low))
    ci_high = float(np.percentile(boot_means, 100.0 * p_high))

    return {
        "mean": observed_mean,
        "ci_low_95": ci_low,
        "ci_high_95": ci_high,
        "n_trades": n,
        "block_size": block_size,
        "n_resamples": n_resamples,
        "seed": seed,
    }


# ---------------------------------------------------------------------------
# Bonferroni regime sub-tests
# ---------------------------------------------------------------------------

def run_bonferroni_regime_tests(
    pooled_xgb: np.ndarray,
    pooled_rule: np.ndarray,
    regime_series: pd.Series,
) -> list[dict]:
    """Wilcoxon signed-rank test on per-trade lift within each of 4 regimes.

    Bonferroni-corrected at per_test_alpha = 0.0025 (family alpha = 0.01 / 4).
    """
    from scipy.stats import wilcoxon

    lift = pooled_xgb - pooled_rule
    results: list[dict] = []

    for regime_id in REGIME_IDS:
        mask = (regime_series == regime_id).to_numpy()
        n = int(mask.sum())
        if n < 10:
            results.append({
                "regime_id": regime_id,
                "n_trades": n,
                "mean_lift": 0.0,
                "p_value": 1.0,
                "significant_at_bonferroni": False,
                "note": "insufficient_trades",
            })
            continue

        region_lift = lift[mask]
        mean_lift = float(region_lift.mean())

        if np.all(region_lift == 0.0):
            p_value = 1.0
        else:
            try:
                _, p_value = wilcoxon(region_lift, alternative="greater")
            except ValueError:
                p_value = 1.0

        results.append({
            "regime_id": regime_id,
            "n_trades": n,
            "mean_lift": mean_lift,
            "p_value": float(p_value),
            "significant_at_bonferroni": float(p_value) < BONFERRONI_PER_TEST_ALPHA,
        })

    return results


# ---------------------------------------------------------------------------
# Q1 secondary-cohort diagnostic
# ---------------------------------------------------------------------------

def apply_q1_rule(fragile_lifts: list[float]) -> dict:
    """Apply Q1 fragile-strongly-negative rule (from DEC-ML-2.0-TARGET).

    Returns verdict: Q1_OK | Q1_CONDITIONAL_RESTRICTED | Q1_NOGO | NO_FRAGILE_DATA
    """
    if not fragile_lifts:
        return {
            "q1_verdict": "NO_FRAGILE_DATA",
            "mean_fragile_lift": None,
            "n_fragile_negative": 0,
            "q1_conditional_threshold": Q1_CONDITIONAL_THRESHOLD,
            "q1_nogo_threshold": Q1_NOGO_THRESHOLD,
        }

    mean_lift = float(np.mean(fragile_lifts))
    n_negative = sum(1 for lift in fragile_lifts if lift < 0.0)

    if mean_lift < Q1_NOGO_THRESHOLD and n_negative >= Q1_BREADTH_N_FRAGILE_NEGATIVE:
        q1_verdict = "Q1_NOGO"
    elif mean_lift < Q1_CONDITIONAL_THRESHOLD:
        q1_verdict = "Q1_CONDITIONAL_RESTRICTED"
    else:
        q1_verdict = "Q1_OK"

    return {
        "q1_verdict": q1_verdict,
        "mean_fragile_lift": mean_lift,
        "n_fragile_negative": n_negative,
        "q1_conditional_threshold": Q1_CONDITIONAL_THRESHOLD,
        "q1_nogo_threshold": Q1_NOGO_THRESHOLD,
    }


# ---------------------------------------------------------------------------
# Verdict renderer
# ---------------------------------------------------------------------------

def render_verdict(
    aggregate_lift: float,
    bca_ci_low: float,
    q1_result: dict,
) -> str:
    """Apply pre-registered verdict bands (DEC-ML-2.0-TARGET).

    GO           : aggregate_lift >= 0.10 AND BCa 95% CI lower > 0
    CONDITIONAL  : 0.055 <= aggregate_lift < 0.10
    NO_GO        : aggregate_lift < 0.055  OR  Q1_NOGO fires
    CONDITIONAL_RESTRICTED : CONDITIONAL overridden by Q1_CONDITIONAL_RESTRICTED
    """
    if q1_result.get("q1_verdict") == "Q1_NOGO":
        return "NO_GO"

    if aggregate_lift >= TARGET_PF_LIFT_GO and bca_ci_low > 0.0:
        verdict = "GO"
    elif aggregate_lift >= CONDITIONAL_FLOOR:
        verdict = "CONDITIONAL"
    else:
        verdict = "NO_GO"

    if q1_result.get("q1_verdict") == "Q1_CONDITIONAL_RESTRICTED" and verdict == "CONDITIONAL":
        verdict = "CONDITIONAL_RESTRICTED"

    return verdict


# ---------------------------------------------------------------------------
# Per-candidate holdout evaluation
# ---------------------------------------------------------------------------

def evaluate_candidate_on_holdout(
    candidate_id: str,
    insample_df: pd.DataFrame,
    holdout_df: pd.DataFrame,
    feature_cols: list[str],
    seed: int = 42,
) -> dict:
    """Train on insample, evaluate on holdout. Returns per-candidate result."""
    model = _train_xgb(insample_df, feature_cols, seed=seed)

    eval_df = holdout_df.dropna(
        subset=feature_cols + ["label_up", "long_outcome_pips"]
    ).reset_index(drop=True)

    if eval_df.empty:
        return {
            "candidate_id": candidate_id,
            "n_trades": 0,
            "xgb_pf": 0.0,
            "rule_pf": 0.0,
            "pf_lift": 0.0,
            "xgb_outcomes": np.array([]),
            "rule_outcomes": np.array([]),
            "regime_breakdown": [],
        }

    X_eval = eval_df[feature_cols]
    xgb_side = xgb_signal(model, X_eval)
    rule_side = rule_baseline_signal(eval_df)

    xgb_out = _outcome_pips(eval_df, xgb_side)
    rule_out = _outcome_pips(eval_df, rule_side)

    xgb_pf = profit_factor(xgb_out)
    rule_pf = profit_factor(rule_out)
    pf_lift = xgb_pf - rule_pf

    regimes = assign_regimes(eval_df)
    regime_breakdown: list[dict] = []
    for regime_id in REGIME_IDS:
        mask = (regimes == regime_id).to_numpy()
        n = int(mask.sum())
        if n == 0:
            regime_breakdown.append({
                "regime_id": regime_id, "n_trades": 0,
                "xgb_pf": 0.0, "rule_pf": 0.0, "pf_lift": 0.0,
            })
            continue
        r_xgb = profit_factor(xgb_out[mask])
        r_rule = profit_factor(rule_out[mask])
        regime_breakdown.append({
            "regime_id": regime_id, "n_trades": n,
            "xgb_pf": r_xgb, "rule_pf": r_rule, "pf_lift": r_xgb - r_rule,
        })

    return {
        "candidate_id": candidate_id,
        "n_trades": int(xgb_out.size),
        "xgb_pf": xgb_pf,
        "rule_pf": rule_pf,
        "pf_lift": pf_lift,
        "xgb_outcomes": xgb_out,
        "rule_outcomes": rule_out,
        "regime_breakdown": regime_breakdown,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:  # noqa: C901
    ap = argparse.ArgumentParser(description="ML-P2.0 holdout evaluation pipeline")
    ap.add_argument(
        "holdout_parquet", type=Path,
        help="Decrypted holdout parquet path (positional, provided by ceremony)",
    )
    ap.add_argument(
        "--insample-parquet",
        default=DEFAULT_INSAMPLE_PARQUET,
        help="In-sample parquet path (relative to repo root)",
    )
    ap.add_argument(
        "--output", default=DEFAULT_REPORT_OUT,
        help="Report output path (relative to repo root)",
    )
    ap.add_argument(
        "--seed", type=int, default=42,
        help="XGBoost training seed",
    )
    args = ap.parse_args(argv)

    holdout_path = Path(args.holdout_parquet).resolve()
    insample_path = (REPO_ROOT / args.insample_parquet).resolve()
    output_path = (REPO_ROOT / args.output).resolve()

    print(f"[p2-eval] holdout  : {holdout_path}")
    print(f"[p2-eval] insample : {insample_path}")

    if not holdout_path.exists():
        print(f"FATAL: holdout parquet not found: {holdout_path}", file=sys.stderr)
        return 1
    if not insample_path.exists():
        print(f"FATAL: in-sample parquet not found: {insample_path}", file=sys.stderr)
        return 1

    # Verify in-sample SHA (governance guard)
    print("[p2-eval] verifying in-sample SHA...")
    insample_sha = file_sha256(insample_path)
    if insample_sha != DATASET_SHA:
        print(f"FATAL: in-sample SHA mismatch: got {insample_sha}", file=sys.stderr)
        return 1

    holdout_sha = file_sha256(holdout_path)
    print(f"[p2-eval] holdout SHA  : {holdout_sha}")

    print("[p2-eval] loading parquets...")
    insample_raw = pd.read_parquet(insample_path).iloc[:N_IN_SAMPLE]
    holdout_raw = pd.read_parquet(holdout_path)
    print(f"[p2-eval] in-sample rows: {len(insample_raw)}, holdout rows: {len(holdout_raw)}")

    # Concatenate for rolling-window feature correctness at boundary
    combined_raw = pd.concat([insample_raw, holdout_raw], ignore_index=True)

    # --- Primary cohort (6 survivors) ---
    primary_results: list[dict] = []
    all_xgb_out: list[np.ndarray] = []
    all_rule_out: list[np.ndarray] = []
    all_regimes_list: list[pd.Series] = []

    for cid in PRIMARY_CANDIDATES:
        print(f"[p2-eval] primary: {cid}")
        try:
            spec = _load_spec(cid)
        except FileNotFoundError as exc:
            print(f"FATAL: {exc}", file=sys.stderr)
            return 1

        full_ds = _build_dataset(combined_raw.copy(), spec)
        insample_ds = (
            full_ds.iloc[:N_IN_SAMPLE]
            .dropna(subset=BASELINE_FEATURE_COLUMNS + ["label_up", "long_outcome_pips"])
            .reset_index(drop=True)
        )
        holdout_ds = (
            full_ds.iloc[N_IN_SAMPLE:]
            .dropna(subset=BASELINE_FEATURE_COLUMNS + ["label_up", "long_outcome_pips"])
            .reset_index(drop=True)
        )

        result = evaluate_candidate_on_holdout(
            cid, insample_ds, holdout_ds, BASELINE_FEATURE_COLUMNS, seed=args.seed
        )
        primary_results.append(result)
        all_xgb_out.append(result["xgb_outcomes"])
        all_rule_out.append(result["rule_outcomes"])
        all_regimes_list.append(assign_regimes(holdout_ds))

        print(
            f"[p2-eval]   rule_PF={result['rule_pf']:.4f}  "
            f"xgb_PF={result['xgb_pf']:.4f}  lift={result['pf_lift']:+.4f}"
        )

    # Aggregate lift
    primary_lifts = [r["pf_lift"] for r in primary_results]
    aggregate_lift = float(np.mean(primary_lifts))
    print(f"[p2-eval] aggregate primary PF lift: {aggregate_lift:+.4f}")

    # BCa bootstrap on pooled per-trade lift
    pooled_xgb = np.concatenate(all_xgb_out) if all_xgb_out else np.array([])
    pooled_rule = np.concatenate(all_rule_out) if all_rule_out else np.array([])

    print(f"[p2-eval] BCa bootstrap (n={BOOTSTRAP_N}, seed={BOOTSTRAP_SEED})...")
    bca = bca_moving_block_bootstrap(pooled_xgb, pooled_rule)
    print(
        f"[p2-eval] BCa mean={bca['mean']:+.6f}  "
        f"95% CI=[{bca['ci_low_95']:+.6f}, {bca['ci_high_95']:+.6f}]"
    )

    # Bonferroni regime sub-tests
    combined_regimes = (
        pd.concat(all_regimes_list, ignore_index=True)
        if all_regimes_list else pd.Series([], dtype="object")
    )
    regime_tests = run_bonferroni_regime_tests(pooled_xgb, pooled_rule, combined_regimes)

    # --- Secondary (fragile) cohort for Q1 diagnostic ---
    print("[p2-eval] secondary (fragile) cohort for Q1...")
    fragile_lifts: list[float] = []
    secondary_results: list[dict] = []

    for cid in FRAGILE_CANDIDATES:
        print(f"[p2-eval] fragile: {cid}")
        try:
            spec = _load_spec(cid)
        except FileNotFoundError as exc:
            print(f"FATAL: {exc}", file=sys.stderr)
            return 1

        full_ds = _build_dataset(combined_raw.copy(), spec)
        insample_ds = (
            full_ds.iloc[:N_IN_SAMPLE]
            .dropna(subset=BASELINE_FEATURE_COLUMNS + ["label_up", "long_outcome_pips"])
            .reset_index(drop=True)
        )
        holdout_ds = (
            full_ds.iloc[N_IN_SAMPLE:]
            .dropna(subset=BASELINE_FEATURE_COLUMNS + ["label_up", "long_outcome_pips"])
            .reset_index(drop=True)
        )

        result = evaluate_candidate_on_holdout(
            cid, insample_ds, holdout_ds, BASELINE_FEATURE_COLUMNS, seed=args.seed
        )
        secondary_results.append(result)
        fragile_lifts.append(result["pf_lift"])
        print(f"[p2-eval]   lift={result['pf_lift']:+.4f}")

    q1_result = apply_q1_rule(fragile_lifts)
    print(f"[p2-eval] Q1: {q1_result['q1_verdict']}  mean={q1_result.get('mean_fragile_lift', 'N/A')}")

    # --- Verdict ---
    verdict = render_verdict(aggregate_lift, bca["ci_low_95"], q1_result)

    print(f"\n[p2-eval] =================================================")
    print(f"[p2-eval] VERDICT        : {verdict}")
    print(f"[p2-eval] aggregate_lift : {aggregate_lift:+.6f}")
    print(f"[p2-eval] BCa CI low     : {bca['ci_low_95']:+.6f}")
    print(f"[p2-eval] GO >= 0.10     CONDITIONAL >= 0.055")
    print(f"[p2-eval] =================================================\n")

    # --- Write report (strip numpy arrays) ---
    def _strip_arrays(r: dict) -> dict:
        return {k: v for k, v in r.items() if k not in ("xgb_outcomes", "rule_outcomes")}

    report = {
        "report_id": f"P2-HOLDOUT-EVAL-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "generated_utc": _utc_iso(),
        "verdict": verdict,
        "aggregate_primary_pf_lift": aggregate_lift,
        "bca_bootstrap": bca,
        "verdict_bands": {
            "go_threshold": TARGET_PF_LIFT_GO,
            "conditional_floor": CONDITIONAL_FLOOR,
        },
        "bonferroni_regime_tests": regime_tests,
        "q1_diagnostic": q1_result,
        "primary_candidate_results": [_strip_arrays(r) for r in primary_results],
        "secondary_candidate_results": [_strip_arrays(r) for r in secondary_results],
        "governance": {
            "dataset_sha256": DATASET_SHA,
            "holdout_sha256_at_eval": holdout_sha,
            "n_in_sample": N_IN_SAMPLE,
            "pre_registration_decision": "DEC-ML-2.0-TARGET",
            "amendment_a1": "DEC-ML-1.6b-A1-AUTHORIZATION",
            "sigma_cross": SIGMA_CROSS,
            "bootstrap_method": (
                f"BCa moving-block n={BOOTSTRAP_N} "
                f"seed={BOOTSTRAP_SEED} block_min={BOOTSTRAP_BLOCK_SIZE_MIN}"
            ),
            "bonferroni_family": BONFERRONI_FAMILY,
            "bonferroni_per_test_alpha": BONFERRONI_PER_TEST_ALPHA,
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[p2-eval] report written: {output_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
