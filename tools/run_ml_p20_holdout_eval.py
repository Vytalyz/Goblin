"""ML-P2.0 holdout evaluation -- called by the sealed holdout ceremony.

Usage (invoked by tools/run_ml_p20_ceremony.py via holdout_access_ceremony.py):
    python tools/run_ml_p20_holdout_eval.py <plaintext_parquet_path>

The decrypted holdout parquet path is passed as a single positional argument.
The ceremony shreds that parquet immediately after this script exits, regardless
of exit code.

Exit codes:
  0 = evaluation complete, report written, DEC-ML-2.0-RE-GATE appended
  1 = evaluation failed (ceremony logs ABORTED, counts against HARD_CAP)

Pre-conditions (checked at startup; exit 1 if violated -- prevents ceremony INITIATED):
  - Both MIDPOINT and TRIGGER predictions must be in predictions.jsonl
  - Dataset SHA must match the pre-registered pin (EX-7)
  - Frozen regime thresholds must match [ml_regime] in eval_gates.toml (EX-6)

Statistical procedure (per DEC-ML-2.0-TARGET):
  - PRIMARY: aggregate PF lift of XGB-vs-rule on n=6 survivors on sealed holdout
  - BCa moving-block bootstrap: block=max(20,sqrt(n)/4), n_resamples=10000, seed=20260420
  - 4 regime sub-tests at Bonferroni alpha=0.0025 each (family alpha=0.01)
  - Q1 secondary cohort (fragile 5): descriptive; CONDITIONAL_RESTRICTED / NO_GO modifiers
  - Verdict bands: GO>=0.10 PF AND bca_ci_lower>0; CONDITIONAL>=0.055; NO_GO otherwise

Outputs:
  - Goblin/reports/ml/p2_0_holdout_evaluation.json
  - Goblin/decisions/ml_decisions.jsonl  (DEC-ML-2.0-RE-GATE appended)
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import traceback
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.stats as ss
import xgboost as xgb

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agentic_forex.features.service import build_features  # noqa: E402
from agentic_forex.labels.service import build_labels  # noqa: E402
from agentic_forex.ml.baseline_runner import (  # noqa: E402
    BASELINE_FEATURE_COLUMNS,
    assert_dataset_sha,
    file_sha256,
    profit_factor,
    rule_baseline_signal,
    xgb_signal,
)
from agentic_forex.ml.variance_pilot import LOCKED_XGB_HPARAMS  # noqa: E402

# ---------------------------------------------------------------------------
# Pre-registered constants (DEC-ML-2.0-*)
# ---------------------------------------------------------------------------

SURVIVORS: tuple[str, ...] = (
    "AF-CAND-0734",
    "AF-CAND-0322",
    "AF-CAND-0323",
    "AF-CAND-0007",
    "AF-CAND-0002",
    "AF-CAND-0290",
)
FRAGILES: tuple[str, ...] = (
    "AF-CAND-0716",
    "AF-CAND-0738",
    "AF-CAND-0739",
    "AF-CAND-0009",
    "AF-CAND-0001",
)

N_IN_SAMPLE: int = 155_775
DATASET_SHA = "7875ba5af620476aaba80cdec0c86680b343f70a02bf19eb40695517378ed8f1"
PARQUET_REL = "data/normalized/research/eur_usd_m1.parquet"
HOLDOUT_REPORT_REL = "Goblin/reports/ml/p2_0_holdout_evaluation.json"
DECISIONS_LOG = REPO_ROOT / "Goblin" / "decisions" / "ml_decisions.jsonl"
PREDICTIONS_LOG = REPO_ROOT / "Goblin" / "decisions" / "predictions.jsonl"
EVAL_GATES_TOML = REPO_ROOT / "config" / "eval_gates.toml"

# Frozen regime thresholds (EX-6 / [ml_regime])
FROZEN_MOM_MEDIAN: float = 1.9
FROZEN_VOL_MEDIAN: float = 0.0000741639

# Statistical parameters (DEC-ML-2.0-TARGET)
GO_THRESHOLD: float = 0.10
CONDITIONAL_THRESHOLD: float = 0.055
SIGMA_CROSS: float = 0.0211004853
BOOTSTRAP_N_RESAMPLES: int = 10_000
BOOTSTRAP_RNG_SEED: int = 20260420
BONFERRONI_PER_TEST_CI_ALPHA: float = 0.0025  # 99.75% CI per regime sub-test
REGIME_IDS: tuple[str, ...] = (
    "trend_high_vol",
    "trend_low_vol",
    "range_high_vol",
    "range_low_vol",
)

# Single seed for final full-in-sample XGB fit (no CV at evaluation time)
FINAL_FIT_SEED: int = 42


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
        raise RuntimeError(f"strategy_spec not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s:
            out.append(json.loads(s))
    return out


def _append_jsonl(path: Path, entry: dict) -> None:
    line = json.dumps(entry, separators=(",", ":"), sort_keys=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _load_frozen_thresholds_from_toml() -> tuple[float, float]:
    """Parse [ml_regime] from eval_gates.toml and verify against hardcoded constants."""
    text = EVAL_GATES_TOML.read_text(encoding="utf-8")
    in_block = False
    vals: dict[str, float] = {}
    for line in text.splitlines():
        s = line.strip()
        if s == "[ml_regime]":
            in_block = True
            continue
        if in_block:
            if s.startswith("[") and s.endswith("]"):
                break
            if "=" in s and not s.startswith("#"):
                k, _, v = s.partition("=")
                try:
                    vals[k.strip()] = float(v.strip().strip('"'))
                except ValueError:
                    pass
    mom = vals.get("abs_momentum_12_median", FROZEN_MOM_MEDIAN)
    vol = vals.get("volatility_20_median", FROZEN_VOL_MEDIAN)
    if abs(mom - FROZEN_MOM_MEDIAN) > 1e-9 or abs(vol - FROZEN_VOL_MEDIAN) > 1e-10:
        raise RuntimeError(
            f"[ml_regime] thresholds in eval_gates.toml (mom={mom}, vol={vol}) "
            f"do not match pre-registered constants "
            f"(mom={FROZEN_MOM_MEDIAN}, vol={FROZEN_VOL_MEDIAN}). "
            "Integrity violation -- cannot proceed."
        )
    return float(mom), float(vol)


def _assign_regimes_frozen(
    df: pd.DataFrame,
    mom_median: float,
    vol_median: float,
) -> pd.Series:
    """Assign regime labels using pre-registered (frozen) median thresholds.

    Returns a Series with the same index as ``df``.
    """
    abs_mom = df["momentum_12"].abs()
    is_trend = abs_mom > mom_median
    is_high_vol = df["volatility_20"] > vol_median
    regime = pd.Series("unknown", index=df.index, dtype="object")
    regime[is_trend & is_high_vol] = "trend_high_vol"
    regime[is_trend & ~is_high_vol] = "trend_low_vol"
    regime[~is_trend & is_high_vol] = "range_high_vol"
    regime[~is_trend & ~is_high_vol] = "range_low_vol"
    return regime


def _outcome_pips(df: pd.DataFrame, side: np.ndarray) -> np.ndarray:
    """Realized pips per trade: long_outcome_pips * direction (+1/-1)."""
    return df["long_outcome_pips"].to_numpy() * side


# ---------------------------------------------------------------------------
# BCa moving-block bootstrap
# ---------------------------------------------------------------------------


def bca_block_bootstrap_pf_lift(
    xgb_out: np.ndarray,
    rule_out: np.ndarray,
    *,
    block_size: int,
    n_resamples: int,
    rng_seed: int,
    ci_alpha: float = 0.05,
) -> tuple[float, float, float, np.ndarray]:
    """BCa moving-block bootstrap CI for PF lift = PF(xgb) - PF(rule).

    Returns (observed_lift, ci_lower, ci_upper, boot_lifts_array).

    Algorithm:
      1. Moving-block bootstrap: sample ceil(n/block_size) blocks with
         replacement from the n overlapping blocks of length block_size.
      2. BCa bias-correction (z0) and acceleration (a) via capped jackknife.
      3. BCa-adjusted quantiles applied to the bootstrap distribution.
    """
    n = len(xgb_out)
    if len(rule_out) != n:
        raise ValueError("xgb_out and rule_out must have the same length")

    observed_lift = profit_factor(xgb_out) - profit_factor(rule_out)

    rng = np.random.default_rng(rng_seed)
    n_blocks = math.ceil(n / block_size)
    max_start = max(n - block_size, 0)

    boot_lifts = np.empty(n_resamples)
    for i in range(n_resamples):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        x_parts = [xgb_out[s : s + block_size] for s in starts]
        r_parts = [rule_out[s : s + block_size] for s in starts]
        x_samp = np.concatenate(x_parts)[:n]
        r_samp = np.concatenate(r_parts)[:n]
        boot_lifts[i] = profit_factor(x_samp) - profit_factor(r_samp)

    # BCa bias-correction z0
    prop_less = float(np.mean(boot_lifts < observed_lift))
    prop_less = float(np.clip(prop_less, 1e-10, 1 - 1e-10))
    z0 = float(ss.norm.ppf(prop_less))

    # Acceleration via capped observation-wise jackknife
    max_jk = min(n, 500)
    step = max(n // max_jk, 1)
    jk_lifts = [
        profit_factor(np.delete(xgb_out, i)) - profit_factor(np.delete(rule_out, i))
        for i in range(0, n, step)
    ]
    jk_arr = np.asarray(jk_lifts, dtype=float)
    jk_mean = float(np.mean(jk_arr))
    diff = jk_mean - jk_arr
    numer = float(np.sum(diff**3))
    denom = 6.0 * float(np.sum(diff**2) ** 1.5)
    a = numer / denom if abs(denom) > 1e-10 else 0.0

    def _bca_q(z_q: float) -> float:
        arg = z0 + (z0 + z_q) / (1.0 - a * (z0 + z_q))
        return float(np.clip(ss.norm.cdf(arg), 1e-10, 1 - 1e-10))

    q_lo = _bca_q(float(ss.norm.ppf(ci_alpha / 2)))
    q_hi = _bca_q(float(ss.norm.ppf(1.0 - ci_alpha / 2)))

    ci_lo = float(np.percentile(boot_lifts, 100.0 * q_lo))
    ci_hi = float(np.percentile(boot_lifts, 100.0 * q_hi))
    return observed_lift, ci_lo, ci_hi, boot_lifts


# ---------------------------------------------------------------------------
# Verdict determination
# ---------------------------------------------------------------------------


def determine_verdict(
    aggregate_lift: float,
    bca_ci_lower: float,
    *,
    q1_nogo: bool = False,
    q1_conditional_restricted: bool = False,
) -> str:
    """Apply pre-registered verdict bands (DEC-ML-2.0-TARGET).

    Primary bands (applied first):
      GO          : aggregate_lift >= 0.10 AND bca_ci_lower > 0
      CONDITIONAL : aggregate_lift >= 0.055
      NO_GO       : otherwise

    Q1 secondary modifiers (applied after primary):
      q1_nogo                  : overrides to NO_GO
      q1_conditional_restricted: demotes GO -> CONDITIONAL
    """
    if q1_nogo:
        return "NO_GO"

    if (
        aggregate_lift >= GO_THRESHOLD
        and not math.isnan(bca_ci_lower)
        and bca_ci_lower > 0.0
    ):
        verdict = "GO"
    elif aggregate_lift >= CONDITIONAL_THRESHOLD:
        verdict = "CONDITIONAL"
    else:
        verdict = "NO_GO"

    if verdict == "GO" and q1_conditional_restricted:
        verdict = "CONDITIONAL"

    return verdict


# ---------------------------------------------------------------------------
# Per-candidate train-on-insample / predict-on-holdout
# ---------------------------------------------------------------------------


def _evaluate_candidate_holdout(
    full_features: pd.DataFrame,
    candidate_id: str,
) -> dict:
    """Train XGB on in-sample rows, predict on holdout rows.

    Returns a dict with outcome arrays and original holdout indices
    (needed for regime sub-test alignment).  Keys prefixed with ``_``
    are internal and should be stripped before serialisation.
    """
    spec = _load_spec(candidate_id)
    labelled = build_labels(
        full_features.copy(),
        spec["holding_bars"],
        stop_loss_pips=spec["stop_loss_pips"],
        take_profit_pips=spec["take_profit_pips"],
    ).dropna()
    # Preserve original index to split on in-sample / holdout boundary.
    in_sample = labelled[labelled.index < N_IN_SAMPLE].reset_index(drop=True)
    holdout_ds = labelled[labelled.index >= N_IN_SAMPLE]

    if len(in_sample) == 0:
        raise RuntimeError(f"{candidate_id}: no in-sample rows after build_labels+dropna")
    if len(holdout_ds) == 0:
        raise RuntimeError(f"{candidate_id}: no holdout rows after build_labels+dropna")

    feature_cols = [c for c in BASELINE_FEATURE_COLUMNS if c in in_sample.columns]
    X_train = in_sample[feature_cols]
    y_train = in_sample["label_up"]

    model = xgb.XGBClassifier(**LOCKED_XGB_HPARAMS, random_state=FINAL_FIT_SEED)
    model.fit(X_train, y_train)

    # Keep original indices for regime matching; reset for array indexing.
    original_holdout_indices = holdout_ds.index.to_numpy()
    holdout_reset = holdout_ds.reset_index(drop=True)

    X_holdout = holdout_reset[feature_cols]
    xgb_side = xgb_signal(model, X_holdout)
    rule_side = rule_baseline_signal(holdout_reset)
    xgb_out = _outcome_pips(holdout_reset, xgb_side)
    rule_out = _outcome_pips(holdout_reset, rule_side)

    xgb_pf = profit_factor(xgb_out)
    rule_pf = profit_factor(rule_out)

    return {
        "candidate_id": candidate_id,
        "n_holdout_trades": int(len(xgb_out)),
        "xgb_pf": float(xgb_pf),
        "rule_pf": float(rule_pf),
        "pf_lift": float(xgb_pf - rule_pf),
        # Internal arrays (stripped before JSON serialisation)
        "_xgb_out": xgb_out,
        "_rule_out": rule_out,
        "_original_holdout_indices": original_holdout_indices,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(holdout_parquet_path: str) -> int:  # noqa: C901 (complexity acceptable)
    try:
        # ------------------------------------------------------------------
        # Pre-condition 1: both predictions must be filed
        # ------------------------------------------------------------------
        pred_entries = _load_jsonl(PREDICTIONS_LOG)
        midpoint_preds = [e for e in pred_entries if e.get("phase") == "midpoint"]
        trigger_preds = [e for e in pred_entries if e.get("phase") == "trigger"]
        if not midpoint_preds:
            print(
                "[p20-holdout] FATAL: no midpoint prediction found in predictions.jsonl.\n"
                "  Run tools/run_ml_p20_insample.py, file the prediction, then retry.",
                file=sys.stderr,
            )
            return 1
        if not trigger_preds:
            print(
                "[p20-holdout] FATAL: no trigger prediction found in predictions.jsonl.\n"
                "  File the trigger prediction before running the ceremony.",
                file=sys.stderr,
            )
            return 1

        # ------------------------------------------------------------------
        # Pre-condition 2: frozen regime thresholds integrity
        # ------------------------------------------------------------------
        mom_thresh, vol_thresh = _load_frozen_thresholds_from_toml()

        # ------------------------------------------------------------------
        # Pre-condition 3: full parquet SHA
        # ------------------------------------------------------------------
        full_parquet = (REPO_ROOT / PARQUET_REL).resolve()
        assert_dataset_sha(full_parquet, DATASET_SHA)
        actual_sha = file_sha256(full_parquet)

        # Record holdout parquet SHA for audit trail
        holdout_path = Path(holdout_parquet_path)
        holdout_sha = file_sha256(holdout_path)
        holdout_raw_n = len(pd.read_parquet(holdout_path))
        print(f"[p20-holdout] holdout: {holdout_raw_n} rows, sha256={holdout_sha[:12]}...")

        # ------------------------------------------------------------------
        # Build features on full dataset (GMM context spans in-sample+holdout)
        # ------------------------------------------------------------------
        print("[p20-holdout] loading full parquet ...", flush=True)
        full_frame = pd.read_parquet(full_parquet)
        print("[p20-holdout] building features on full dataset ...", flush=True)
        full_features = build_features(full_frame)

        # ------------------------------------------------------------------
        # Evaluate primary cohort (6 survivors)
        # ------------------------------------------------------------------
        print("[p20-holdout] evaluating primary cohort (6 survivors) ...", flush=True)
        survivor_results: list[dict] = []
        pooled_xgb_outs: list[np.ndarray] = []
        pooled_rule_outs: list[np.ndarray] = []

        for cid in SURVIVORS:
            print(f"[p20-holdout]   {cid} ...", flush=True)
            r = _evaluate_candidate_holdout(full_features, cid)
            survivor_results.append(r)
            pooled_xgb_outs.append(r["_xgb_out"])
            pooled_rule_outs.append(r["_rule_out"])
            print(
                f"[p20-holdout]   {cid:>14}  "
                f"xgb_pf={r['xgb_pf']:.4f}  "
                f"rule_pf={r['rule_pf']:.4f}  "
                f"lift={r['pf_lift']:+.4f}",
                flush=True,
            )

        pooled_xgb = np.concatenate(pooled_xgb_outs)
        pooled_rule = np.concatenate(pooled_rule_outs)
        aggregate_xgb_pf = profit_factor(pooled_xgb)
        aggregate_rule_pf = profit_factor(pooled_rule)
        mean_cand_lift = float(np.mean([r["pf_lift"] for r in survivor_results]))

        # ------------------------------------------------------------------
        # BCa moving-block bootstrap
        # ------------------------------------------------------------------
        n_trades = len(pooled_xgb)
        block_size = max(20, int(math.sqrt(n_trades) / 4))
        print(
            f"[p20-holdout] BCa bootstrap: n_trades={n_trades}, "
            f"block_size={block_size}, n_resamples={BOOTSTRAP_N_RESAMPLES} ...",
            flush=True,
        )
        aggregate_lift, bca_lo, bca_hi, boot_lifts = bca_block_bootstrap_pf_lift(
            pooled_xgb,
            pooled_rule,
            block_size=block_size,
            n_resamples=BOOTSTRAP_N_RESAMPLES,
            rng_seed=BOOTSTRAP_RNG_SEED,
        )
        print(
            f"[p20-holdout] aggregate_lift={aggregate_lift:+.4f}  "
            f"BCa 95% CI=[{bca_lo:+.4f}, {bca_hi:+.4f}]",
            flush=True,
        )

        # ------------------------------------------------------------------
        # Regime sub-tests (Bonferroni family of 4)
        # ------------------------------------------------------------------
        print("[p20-holdout] regime sub-tests ...", flush=True)
        holdout_features = full_features[full_features.index >= N_IN_SAMPLE].copy()
        holdout_frozen_regime = _assign_regimes_frozen(
            holdout_features, mom_thresh, vol_thresh
        )

        regime_results: list[dict] = []
        for regime_id in REGIME_IDS:
            r_xgb_parts: list[np.ndarray] = []
            r_rule_parts: list[np.ndarray] = []
            for sr in survivor_results:
                orig_idx = sr["_original_holdout_indices"]
                # Map original row indices -> frozen regime labels
                regime_labels = holdout_frozen_regime.reindex(orig_idx).fillna("unknown").values
                mask = regime_labels == regime_id
                r_xgb_parts.append(sr["_xgb_out"][mask])
                r_rule_parts.append(sr["_rule_out"][mask])

            r_xgb_pool = (
                np.concatenate(r_xgb_parts) if r_xgb_parts else np.array([], dtype=float)
            )
            r_rule_pool = (
                np.concatenate(r_rule_parts) if r_rule_parts else np.array([], dtype=float)
            )
            r_xgb_pf = profit_factor(r_xgb_pool)
            r_rule_pf = profit_factor(r_rule_pool)
            r_lift = r_xgb_pf - r_rule_pf

            r_bca_lo: float = float("nan")
            r_bca_hi: float = float("nan")
            r_fragile: bool = r_lift < 0.0

            if len(r_xgb_pool) >= 10:
                r_block = max(20, int(math.sqrt(len(r_xgb_pool)) / 4))
                try:
                    _, r_bca_lo, r_bca_hi, _ = bca_block_bootstrap_pf_lift(
                        r_xgb_pool,
                        r_rule_pool,
                        block_size=r_block,
                        n_resamples=2_000,
                        rng_seed=BOOTSTRAP_RNG_SEED,
                        ci_alpha=BONFERRONI_PER_TEST_CI_ALPHA,
                    )
                    r_fragile = r_bca_lo < 0.0
                except Exception as e:
                    print(
                        f"[p20-holdout] WARNING: regime {regime_id} bootstrap failed: {e}",
                        file=sys.stderr,
                    )

            regime_results.append(
                {
                    "regime_id": regime_id,
                    "n_trades": int(len(r_xgb_pool)),
                    "xgb_pf": float(r_xgb_pf),
                    "rule_pf": float(r_rule_pf),
                    "pf_lift": float(r_lift),
                    "bca_ci_lower_bonferroni_corrected": float(r_bca_lo),
                    "bca_ci_upper_bonferroni_corrected": float(r_bca_hi),
                    "fragile_flag": bool(r_fragile),
                }
            )
            print(
                f"[p20-holdout]   {regime_id:>20}  "
                f"n={len(r_xgb_pool):>5}  lift={r_lift:+.4f}  "
                f"fragile={r_fragile}",
                flush=True,
            )

        # ------------------------------------------------------------------
        # Q1 secondary cohort (fragile 5, descriptive)
        # ------------------------------------------------------------------
        print("[p20-holdout] evaluating secondary cohort (fragile 5, descriptive) ...", flush=True)
        fragile_results: list[dict] = []
        for cid in FRAGILES:
            try:
                r = _evaluate_candidate_holdout(full_features, cid)
                fragile_results.append(r)
                print(
                    f"[p20-holdout]   {cid:>14}  "
                    f"xgb_pf={r['xgb_pf']:.4f}  lift={r['pf_lift']:+.4f}",
                    flush=True,
                )
            except Exception as exc:
                print(
                    f"[p20-holdout]   {cid:>14}  FAILED: {exc}",
                    file=sys.stderr,
                )
                fragile_results.append(
                    {"candidate_id": cid, "pf_lift": float("nan"), "_failed": True}
                )

        fragile_valid_lifts = [
            r["pf_lift"] for r in fragile_results if not r.get("_failed") and not math.isnan(r["pf_lift"])
        ]
        mean_fragile_lift = float(np.mean(fragile_valid_lifts)) if fragile_valid_lifts else float("nan")
        n_fragile_negative = sum(1 for v in fragile_valid_lifts if v < 0.0)

        q1_conditional_restricted = (
            not math.isnan(mean_fragile_lift)
            and mean_fragile_lift < -1.0 * SIGMA_CROSS
        )
        q1_nogo = (
            not math.isnan(mean_fragile_lift)
            and mean_fragile_lift < -2.0 * SIGMA_CROSS
            and n_fragile_negative >= 3
        )

        # ------------------------------------------------------------------
        # Verdict
        # ------------------------------------------------------------------
        verdict = determine_verdict(
            aggregate_lift,
            bca_lo,
            q1_nogo=q1_nogo,
            q1_conditional_restricted=q1_conditional_restricted,
        )

        head_sha = _head_sha()

        # ------------------------------------------------------------------
        # Build report
        # ------------------------------------------------------------------
        report = {
            "evaluation_id": (
                f"DEC-ML-2.0-RE-GATE-"
                f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
            ),
            "generated_utc": _utc_now(),
            "commit_sha": head_sha,
            "dataset_sha256": actual_sha,
            "holdout_parquet_sha256": holdout_sha,
            "holdout_n_rows_raw": holdout_raw_n,
            "n_in_sample_rows": N_IN_SAMPLE,
            "verdict": verdict,
            "aggregate_lift": float(aggregate_lift),
            "aggregate_xgb_pf": float(aggregate_xgb_pf),
            "aggregate_rule_pf": float(aggregate_rule_pf),
            "mean_candidate_lift": float(mean_cand_lift),
            "bca_ci_lower_95": float(bca_lo),
            "bca_ci_upper_95": float(bca_hi),
            "bca_block_size": int(block_size),
            "bca_n_resamples": BOOTSTRAP_N_RESAMPLES,
            "bca_rng_seed": BOOTSTRAP_RNG_SEED,
            "go_threshold": GO_THRESHOLD,
            "conditional_threshold": CONDITIONAL_THRESHOLD,
            "primary_cohort_results": [
                {k: v for k, v in r.items() if not k.startswith("_")}
                for r in survivor_results
            ],
            "regime_sub_tests": regime_results,
            "secondary_cohort_q1": {
                "mean_fragile_lift": float(mean_fragile_lift),
                "n_fragile_negative": int(n_fragile_negative),
                "q1_conditional_restricted_triggered": bool(q1_conditional_restricted),
                "q1_nogo_triggered": bool(q1_nogo),
                "sigma_cross": SIGMA_CROSS,
                "conditional_restricted_threshold": -1.0 * SIGMA_CROSS,
                "nogo_threshold": -2.0 * SIGMA_CROSS,
                "fragile_results": [
                    {k: v for k, v in r.items() if not k.startswith("_")}
                    for r in fragile_results
                ],
            },
            "midpoint_prediction": midpoint_preds[-1] if midpoint_preds else None,
            "trigger_prediction": trigger_preds[-1] if trigger_preds else None,
        }

        # ------------------------------------------------------------------
        # Write report (before decisions log append)
        # ------------------------------------------------------------------
        out_path = (REPO_ROOT / HOLDOUT_REPORT_REL).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"[p20-holdout] report written: {out_path.relative_to(REPO_ROOT)}", flush=True)

        # ------------------------------------------------------------------
        # Append DEC-ML-2.0-RE-GATE to decisions log
        # ------------------------------------------------------------------
        gate_entry = {
            "decision_id": "DEC-ML-2.0-RE-GATE",
            "phase": "ML-2.0",
            "decision_type": "holdout_evaluation_verdict",
            "verdict": verdict,
            "decided_by": "owner",
            "decided_at": _utc_now(),
            "aggregate_lift_pf": float(aggregate_lift),
            "bca_ci_lower_95": float(bca_lo),
            "bca_ci_upper_95": float(bca_hi),
            "go_threshold_pf": GO_THRESHOLD,
            "conditional_threshold_pf": CONDITIONAL_THRESHOLD,
            "q1_nogo_triggered": bool(q1_nogo),
            "q1_conditional_restricted_triggered": bool(q1_conditional_restricted),
            "rationale": (
                f"Phase 2.0 holdout evaluation complete. "
                f"aggregate_lift={aggregate_lift:.4f}, "
                f"BCa 95% CI=[{bca_lo:.4f}, {bca_hi:.4f}]. "
                f"Verdict: {verdict}."
            ),
            "evidence_uris": [
                HOLDOUT_REPORT_REL,
                "Goblin/decisions/predictions.jsonl",
                "Goblin/holdout/ml_p2_holdout.parquet.enc",
            ],
        }
        _append_jsonl(DECISIONS_LOG, gate_entry)
        print("[p20-holdout] DEC-ML-2.0-RE-GATE appended to decisions log.", flush=True)

        print()
        print("=" * 68)
        print(f"ML-P2.0 HOLDOUT EVALUATION VERDICT: {verdict}")
        print(f"  Aggregate PF lift   : {aggregate_lift:+.4f}")
        print(f"  BCa 95% CI          : [{bca_lo:+.4f}, {bca_hi:+.4f}]")
        print(f"  GO threshold        : {GO_THRESHOLD}")
        print(f"  CONDITIONAL threshold: {CONDITIONAL_THRESHOLD}")
        print(f"  Q1 NO_GO triggered  : {q1_nogo}")
        print(f"  Q1 COND_RESTR       : {q1_conditional_restricted}")
        print("=" * 68)
        return 0

    except Exception as exc:  # noqa: BLE001
        print(
            f"[p20-holdout] FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: run_ml_p20_holdout_eval.py <plaintext_holdout_parquet_path>",
            file=sys.stderr,
        )
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
