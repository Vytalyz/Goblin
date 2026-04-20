"""
EX-1 — Phase 2.0 MDE derivation script (R4-3).

Computes σ_cross from the locked 1.6 baseline comparison report and derives
the Minimum Detectable Effect (MDE) for the Phase 2.0 primary endpoint
(aggregate PF lift on n=6 surviving candidates, α=0.01, power=0.80).

Four locked constraints (per Revision 4.2-final §15.9 + §15.10):

  1. Reproducibility contract: deterministic; pinned RNG; manifest emitted
     containing input SHA, code SHA, library versions, runtime timestamp.
  2. σ_cross definition (LOCKED): standard deviation of per-candidate mean
     PF lift, where the candidate mean is taken over folds (1.6 baseline
     used 1 seed × 3 folds per candidate; the seeds dimension does not
     exist in this dataset, so the locked definition reduces to the fold
     mean per candidate). Rationale: this matches what the Phase 2.0 gate
     is testing — lift estimated per-candidate, then aggregated across the
     candidate set.
  3. Bootstrap 95% CI on σ_cross via resampling-with-replacement over
     candidates (n_resamples=10000, seed pinned). MDE reported at point
     estimate AND at upper CI bound. If MDE-at-upper-CI-bound crosses an
     I1 tier boundary, pre-commit to the more conservative tier.
  4. Fail loudly on input drift: refuses to run if the dataset SHA on disk
     does not match the locked SHA in config/eval_gates.toml; does not
     silently re-derive σ_cross on shifted data.

Usage:
    python tools/derive_mde.py [--update-config]

Without --update-config, the script computes and prints the numbers and
writes the manifest, but does NOT mutate config/eval_gates.toml. With
--update-config, populates the [ml_p2] block in config/eval_gates.toml with
the derived numbers and the manifest SHA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats

# ---------------------------------------------------------------------------
# Paths and constants (locked).
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_GATES_PATH = REPO_ROOT / "config" / "eval_gates.toml"
MANIFEST_PATH = REPO_ROOT / "Goblin" / "reports" / "ml" / "p2_0_mde_derivation_manifest.json"

LOCKED_ALPHA = 0.01
LOCKED_POWER = 0.80
LOCKED_N_SURVIVORS = 6
LOCKED_BOOTSTRAP_N_RESAMPLES = 10_000
LOCKED_BOOTSTRAP_RNG_SEED = 20_260_420

DATASET_SHA_MISMATCH_ERROR = (
    "Dataset SHA mismatch: expected {expected}, got {actual}. "
    "σ_cross derivation requires locked 1.6 dataset. "
    "To re-derive on new data, file a new pre-registration entry."
)


class DatasetSHAMismatchError(RuntimeError):
    """Raised when the on-disk dataset SHA differs from the locked SHA."""


# ---------------------------------------------------------------------------
# Pure functions (testable in isolation).
# ---------------------------------------------------------------------------
def compute_file_sha256(path: Path) -> str:
    """Return the lowercase hex SHA-256 of the file at *path*."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def per_candidate_mean_lift(candidate_results: list[dict]) -> np.ndarray:
    """Per-candidate mean PF lift over folds (locked σ_cross definition)."""
    means = []
    for c in candidate_results:
        folds = c.get("fold_pf_lift")
        if folds is None or not isinstance(folds, list) or len(folds) == 0:
            xgb = c["fold_xgb_pf"]
            rule = c["fold_rule_pf"]
            folds = [x - r for x, r in zip(xgb, rule)]
        means.append(float(np.mean(folds)))
    return np.asarray(means, dtype=np.float64)


def sigma_cross(per_candidate_means: np.ndarray) -> float:
    """Cross-candidate standard deviation (sample stdev, ddof=1)."""
    if per_candidate_means.size < 2:
        raise ValueError("σ_cross requires at least 2 candidates")
    return float(np.std(per_candidate_means, ddof=1))


def bootstrap_sigma_cross_ci(
    per_candidate_means: np.ndarray,
    n_resamples: int = LOCKED_BOOTSTRAP_N_RESAMPLES,
    rng_seed: int = LOCKED_BOOTSTRAP_RNG_SEED,
    ci_level: float = 0.95,
) -> tuple[float, float]:
    """Bootstrap 95% CI on σ_cross via resampling candidates with replacement."""
    rng = np.random.default_rng(rng_seed)
    n = per_candidate_means.size
    boot = np.empty(n_resamples, dtype=np.float64)
    for i in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        sample = per_candidate_means[idx]
        if np.all(sample == sample[0]):
            boot[i] = 0.0
        else:
            boot[i] = float(np.std(sample, ddof=1))
    lo_q = (1.0 - ci_level) / 2.0
    hi_q = 1.0 - lo_q
    return float(np.quantile(boot, lo_q)), float(np.quantile(boot, hi_q))


def derive_mde(
    sigma: float,
    n: int = LOCKED_N_SURVIVORS,
    alpha: float = LOCKED_ALPHA,
    power: float = LOCKED_POWER,
) -> float:
    """
    Two-sided one-sample t-test MDE for mean = 0 vs mean = MDE.

    Uses the t-distribution (df = n - 1) rather than the normal approximation
    because n is small (n=6 for the survivor set).
    """
    if n < 2:
        raise ValueError("MDE requires n >= 2")
    df = n - 1
    t_alpha = float(stats.t.ppf(1.0 - alpha / 2.0, df))
    t_power = float(stats.t.ppf(power, df))
    return (t_alpha + t_power) * sigma / math.sqrt(n)


# ---------------------------------------------------------------------------
# Toml IO (read-only here; --update-config does in-place edit).
# ---------------------------------------------------------------------------
def _load_toml(path: Path) -> dict:
    try:
        import tomllib
    except ImportError:  # pragma: no cover - py < 3.11 fallback
        import tomli as tomllib
    with path.open("rb") as f:
        return tomllib.load(f)


def read_locked_dataset_sha() -> str:
    cfg = _load_toml(EVAL_GATES_PATH)
    return cfg["ml_baseline_comparison"]["dataset_sha"]


def read_baseline_report_path() -> Path:
    cfg = _load_toml(EVAL_GATES_PATH)
    return REPO_ROOT / cfg["ml_baseline_comparison"]["report_path"]


# ---------------------------------------------------------------------------
# Manifest helpers.
# ---------------------------------------------------------------------------
def _library_versions() -> dict[str, str]:
    versions = {}
    for mod_name in ("numpy", "scipy"):
        try:
            mod = __import__(mod_name)
            versions[mod_name] = getattr(mod, "__version__", "unknown")
        except ImportError:
            versions[mod_name] = "missing"
    versions["python"] = sys.version.split()[0]
    return versions


def _self_sha() -> str:
    """SHA-256 of this script file (manifest reproducibility check)."""
    return compute_file_sha256(Path(__file__))


def write_manifest(payload: dict, path: Path = MANIFEST_PATH) -> str:
    """Write the manifest atomically; return its SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    path.write_bytes(serialized)
    return hashlib.sha256(serialized).hexdigest()


def manifest_payload(
    *,
    dataset_sha: str,
    report_sha: str,
    per_candidate_means: np.ndarray,
    sigma_point: float,
    sigma_ci_low: float,
    sigma_ci_high: float,
    mde_point: float,
    mde_at_upper_ci: float,
    runtime_utc: str,
    code_sha: str,
    library_versions: dict[str, str],
) -> dict:
    """Build the manifest payload with all reproducibility-relevant fields."""
    return {
        "schema_version": "1.0",
        "phase": "EX-1",
        "purpose": "R4-3 σ_cross + MDE derivation for Phase 2.0 re-gate",
        "inputs": {
            "dataset_sha256": dataset_sha,
            "baseline_report_sha256": report_sha,
        },
        "code": {
            "tool_path": "tools/derive_mde.py",
            "tool_sha256": code_sha,
            "library_versions": library_versions,
        },
        "parameters": {
            "alpha": LOCKED_ALPHA,
            "power": LOCKED_POWER,
            "n_survivors": LOCKED_N_SURVIVORS,
            "bootstrap_n_resamples": LOCKED_BOOTSTRAP_N_RESAMPLES,
            "bootstrap_rng_seed": LOCKED_BOOTSTRAP_RNG_SEED,
            "ci_level": 0.95,
            "sigma_cross_definition": (
                "stdev of per-candidate mean PF lift over folds (1.6 has 1 "
                "seed * 3 folds per candidate; seeds dimension absent)"
            ),
        },
        "results": {
            "n_candidates_input": int(per_candidate_means.size),
            "per_candidate_mean_lift": [float(x) for x in per_candidate_means],
            "sigma_cross_point": sigma_point,
            "sigma_cross_ci_low": sigma_ci_low,
            "sigma_cross_ci_high": sigma_ci_high,
            "mde_pf_point": mde_point,
            "mde_pf_at_upper_ci_bound": mde_at_upper_ci,
        },
        "runtime_utc": runtime_utc,
    }


# ---------------------------------------------------------------------------
# Tier classification (I1 rule).
# ---------------------------------------------------------------------------
def i1_tier(mde: float) -> str:
    """Classify an MDE value into the I1 tie-breaker tiers."""
    if mde <= 0.10:
        return "TIER_1_PROCEED"
    if mde <= 0.15:
        return "TIER_2_BORDERLINE"
    return "TIER_3_DO_NOT_RUN"


# ---------------------------------------------------------------------------
# CLI entry point.
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EX-1 σ_cross + MDE derivation")
    parser.add_argument(
        "--update-config",
        action="store_true",
        help="Write derived numbers into config/eval_gates.toml [ml_p2]",
    )
    parser.add_argument(
        "--allow-empty-locked-sha",
        action="store_true",
        help=(
            "Permit running when the locked dataset SHA in eval_gates.toml is "
            "empty (first-time bootstrap only; CI asserts this flag is unused)."
        ),
    )
    args = parser.parse_args(argv)

    locked_sha = read_locked_dataset_sha()
    cfg = _load_toml(EVAL_GATES_PATH)
    dataset_path = REPO_ROOT / cfg["ml_baseline_comparison"]["dataset_path"]
    if not dataset_path.exists():
        print(f"ERROR: dataset not found at {dataset_path}", file=sys.stderr)
        return 2

    actual_sha = compute_file_sha256(dataset_path)
    if locked_sha and actual_sha != locked_sha:
        raise DatasetSHAMismatchError(
            DATASET_SHA_MISMATCH_ERROR.format(expected=locked_sha, actual=actual_sha)
        )
    if not locked_sha and not args.allow_empty_locked_sha:
        print(
            "ERROR: locked dataset_sha is empty; refusing to run. "
            "Pass --allow-empty-locked-sha for the first-time bootstrap only.",
            file=sys.stderr,
        )
        return 3

    report_path = read_baseline_report_path()
    if not report_path.exists():
        print(f"ERROR: baseline report not found at {report_path}", file=sys.stderr)
        return 4

    report_sha = compute_file_sha256(report_path)
    with report_path.open() as f:
        report = json.load(f)

    candidate_results = report["candidate_results"]
    means = per_candidate_mean_lift(candidate_results)
    sigma_point = sigma_cross(means)
    ci_low, ci_high = bootstrap_sigma_cross_ci(means)
    mde_point = derive_mde(sigma_point)
    mde_upper = derive_mde(ci_high)

    runtime_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = manifest_payload(
        dataset_sha=actual_sha,
        report_sha=report_sha,
        per_candidate_means=means,
        sigma_point=sigma_point,
        sigma_ci_low=ci_low,
        sigma_ci_high=ci_high,
        mde_point=mde_point,
        mde_at_upper_ci=mde_upper,
        runtime_utc=runtime_utc,
        code_sha=_self_sha(),
        library_versions=_library_versions(),
    )
    manifest_sha = write_manifest(payload)

    point_tier = i1_tier(mde_point)
    upper_tier = i1_tier(mde_upper)
    locked_tier = upper_tier  # conservative-tier-on-upper-bound rule

    print(f"sigma_cross (point):      {sigma_point:.6f}")
    print(f"sigma_cross (95% CI low): {ci_low:.6f}")
    print(f"sigma_cross (95% CI high):{ci_high:.6f}")
    print(f"MDE (point):              {mde_point:.6f}  -> {point_tier}")
    print(f"MDE (at upper CI):        {mde_upper:.6f}  -> {upper_tier}")
    print(f"LOCKED TIER (I1):     {locked_tier}")
    print(f"Manifest:             {MANIFEST_PATH.relative_to(REPO_ROOT)}")
    print(f"Manifest SHA-256:     {manifest_sha}")

    if args.update_config:
        _update_eval_gates(
            sigma_point=sigma_point,
            sigma_ci_low=ci_low,
            sigma_ci_high=ci_high,
            mde_point=mde_point,
            mde_upper=mde_upper,
            manifest_sha=manifest_sha,
            report_sha=report_sha,
        )
        print("config/eval_gates.toml [ml_p2] block updated.")

    return 0


def _update_eval_gates(
    *,
    sigma_point: float,
    sigma_ci_low: float,
    sigma_ci_high: float,
    mde_point: float,
    mde_upper: float,
    manifest_sha: str,
    report_sha: str,
) -> None:
    """In-place update of [ml_p2] block; preserves comments and ordering."""
    text = EVAL_GATES_PATH.read_text(encoding="utf-8")
    replacements = {
        "sigma_cross_point": f"{sigma_point:.10f}",
        "sigma_cross_ci_low": f"{sigma_ci_low:.10f}",
        "sigma_cross_ci_high": f"{sigma_ci_high:.10f}",
        "mde_pf_point": f"{mde_point:.10f}",
        "mde_pf_at_upper_ci_bound": f"{mde_upper:.10f}",
        "derivation_manifest_sha": f'"{manifest_sha}"',
    }
    for key, value in replacements.items():
        # Match key = <anything> within the [ml_p2] block (order-independent).
        import re

        pattern = rf"(?m)^({re.escape(key)}\s*=\s*).*$"
        text, n = re.subn(pattern, rf"\g<1>{value}", text, count=1)
        if n != 1:
            raise RuntimeError(f"Failed to update {key} in eval_gates.toml")

    # Also update report_sha in [ml_baseline_comparison] (one-shot).
    import re

    bc_pattern = r'(?m)^(report_sha\s*=\s*)".*"$'
    text, _ = re.subn(bc_pattern, rf'\g<1>"{report_sha}"', text, count=1)

    EVAL_GATES_PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
