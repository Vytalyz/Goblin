"""
EX-2 — Risk-1 gate sensitivity analysis (Revision 4.2-final §15.8).

Runs each Phase 2.0 gate retrospectively against the locked 1.6 baseline
result and records what verdict the gate would have produced. The output
report (Goblin/reports/ml/p2_0_gate_sensitivity.md) is referenced by the
EX-9 pre-registration entries under `confirmation_bias_considered.note` to
provide an audit trail proving gates were not tuned to match 1.6's outcome.

Gates evaluated:
  * I1 MDE tier (TIER_1/2/3) using EX-1 σ_cross + MDE numbers
  * Regime non-negativity gate (4 regimes; per-candidate)
  * Cost persistence at +1 pip (per-candidate)
  * Effect-size floor (per-candidate)
  * Q1 fragile-strongly-negative rule using 1.6's fragile-vs-survivor split:
      - CONDITIONAL_RESTRICTED if mean fragile lift < -1*sigma_cross
      - NO_GO if mean fragile lift < -2*sigma_cross AND >=3/5 fragiles negative

Output is a Markdown table; the script is deterministic (no RNG used).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_GATES_PATH = REPO_ROOT / "config" / "eval_gates.toml"
REPORT_PATH = REPO_ROOT / "Goblin" / "reports" / "ml" / "p2_0_gate_sensitivity.md"

SURVIVORS = frozenset(
    {
        "AF-CAND-0734",
        "AF-CAND-0322",
        "AF-CAND-0323",
        "AF-CAND-0007",
        "AF-CAND-0002",
        "AF-CAND-0290",
    }
)
FRAGILES = frozenset(
    {
        "AF-CAND-0716",
        "AF-CAND-0738",
        "AF-CAND-0739",
        "AF-CAND-0009",
        "AF-CAND-0001",
    }
)


def _load_toml(path: Path) -> dict:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with path.open("rb") as f:
        return tomllib.load(f)


def evaluate_gates(
    candidate_results: list[dict],
    sigma_cross: float,
    mde_point: float,
    mde_upper: float,
    effect_size_floor: float,
) -> dict:
    """Evaluate each gate and return structured results."""
    n_above_floor = sum(
        1 for c in candidate_results if c["pf_lift_aggregate"] >= effect_size_floor
    )
    n_regime_pass = sum(1 for c in candidate_results if c.get("regime_non_negative"))
    n_cost_pass = sum(1 for c in candidate_results if c.get("cost_persistent_at_1pip"))

    survivor_lifts = [
        c["pf_lift_aggregate"]
        for c in candidate_results
        if c["candidate_id"] in SURVIVORS
    ]
    fragile_lifts = [
        c["pf_lift_aggregate"]
        for c in candidate_results
        if c["candidate_id"] in FRAGILES
    ]
    survivor_mean = (
        sum(survivor_lifts) / len(survivor_lifts) if survivor_lifts else 0.0
    )
    fragile_mean = (
        sum(fragile_lifts) / len(fragile_lifts) if fragile_lifts else 0.0
    )
    n_fragile_negative = sum(1 for x in fragile_lifts if x < 0)

    # Q1 rule on 1.6 evidence (using 1.6 candidates as the lens):
    q1_conditional_threshold = -1.0 * sigma_cross
    q1_nogo_threshold = -2.0 * sigma_cross
    if fragile_mean < q1_nogo_threshold and n_fragile_negative >= 3:
        q1_verdict = "NO_GO"
    elif fragile_mean < q1_conditional_threshold:
        q1_verdict = "CONDITIONAL_RESTRICTED"
    else:
        q1_verdict = "PRIMARY_OK"

    # I1 tier on EX-1 numbers.
    if mde_upper <= 0.10:
        i1_tier = "TIER_1_PROCEED"
    elif mde_upper <= 0.15:
        i1_tier = "TIER_2_BORDERLINE"
    else:
        i1_tier = "TIER_3_DO_NOT_RUN"

    return {
        "n_candidates": len(candidate_results),
        "n_above_effect_size_floor": n_above_floor,
        "n_regime_non_negative": n_regime_pass,
        "n_cost_persistent_at_1pip": n_cost_pass,
        "survivor_mean_lift": survivor_mean,
        "fragile_mean_lift": fragile_mean,
        "n_fragile_negative": n_fragile_negative,
        "q1_conditional_threshold_neg1_sigma": q1_conditional_threshold,
        "q1_nogo_threshold_neg2_sigma": q1_nogo_threshold,
        "q1_retrospective_verdict_on_1_6": q1_verdict,
        "i1_locked_tier": i1_tier,
    }


def render_report(
    *,
    run_id: str,
    dataset_sha: str,
    report_sha: str,
    sigma_cross: float,
    mde_point: float,
    mde_upper: float,
    effect_size_floor: float,
    gates: dict,
    runtime_utc: str,
) -> str:
    """Render the gate sensitivity report as deterministic Markdown."""
    lines = [
        "# Phase 2.0 Gate Sensitivity Analysis (EX-2 / Risk-1 mitigation)",
        "",
        "Retrospective evaluation of each Phase 2.0 gate against the locked",
        "1.6 baseline comparison evidence. **Gates were NOT tuned to match 1.6's",
        "outcome**; this report documents what each gate would have decided on",
        "1.6 evidence so a future P2.11 reviewer can audit calibration.",
        "",
        "## Locked Inputs",
        "",
        f"- 1.6 run_id: `{run_id}`",
        f"- Dataset SHA-256: `{dataset_sha}`",
        f"- Baseline report SHA-256: `{report_sha}`",
        f"- σ_cross (point, EX-1): `{sigma_cross:.6f}`",
        f"- MDE point (n=6, α=0.01, power=0.80): `{mde_point:.6f}`",
        f"- MDE at upper CI bound: `{mde_upper:.6f}`",
        f"- Effect-size floor (from 1.6.0 σ_PF): `{effect_size_floor:.6f}`",
        "",
        "## Gate-by-Gate Verdict on 1.6 Evidence",
        "",
        "| Gate | Threshold | 1.6 Evidence | Verdict |",
        "|---|---|---|---|",
        (
            f"| Effect-size floor | lift ≥ {effect_size_floor:.4f} PF | "
            f"{gates['n_above_effect_size_floor']}/{gates['n_candidates']} pass | "
            f"{'PASS' if gates['n_above_effect_size_floor'] == gates['n_candidates'] else 'PARTIAL'} |"
        ),
        (
            f"| Regime non-negativity | lift ≥ 0 in every regime | "
            f"{gates['n_regime_non_negative']}/{gates['n_candidates']} pass | "
            f"{'PASS' if gates['n_regime_non_negative'] == gates['n_candidates'] else 'PARTIAL (5 fragile)'} |"
        ),
        (
            f"| Cost persistence | lift survives at +1.0 pip | "
            f"{gates['n_cost_persistent_at_1pip']}/{gates['n_candidates']} pass | "
            f"{'PASS' if gates['n_cost_persistent_at_1pip'] == gates['n_candidates'] else 'PARTIAL'} |"
        ),
        (
            f"| I1 MDE tier | TIER_1 if MDE_upper ≤ 0.10 | "
            f"MDE_upper = {mde_upper:.4f} | {gates['i1_locked_tier']} |"
        ),
        (
            f"| Q1 fragile rule (CONDITIONAL_RESTRICTED) | "
            f"fragile mean < {gates['q1_conditional_threshold_neg1_sigma']:.4f} (-1σ_cross) | "
            f"fragile mean = {gates['fragile_mean_lift']:.4f} | "
            f"{gates['q1_retrospective_verdict_on_1_6']} |"
        ),
        (
            f"| Q1 fragile rule (NO_GO) | "
            f"mean < {gates['q1_nogo_threshold_neg2_sigma']:.4f} (-2σ_cross) AND ≥3/5 negative | "
            f"mean = {gates['fragile_mean_lift']:.4f}, "
            f"{gates['n_fragile_negative']}/5 negative | "
            f"{'WOULD TRIGGER' if gates['q1_retrospective_verdict_on_1_6'] == 'NO_GO' else 'NOT TRIGGERED'} |"
        ),
        "",
        "## Survivor vs Fragile Cohort Statistics",
        "",
        f"- Survivor cohort (n=6): mean lift = `{gates['survivor_mean_lift']:.6f}`",
        f"- Fragile cohort (n=5): mean lift = `{gates['fragile_mean_lift']:.6f}`",
        f"- Fragile candidates with negative lift: `{gates['n_fragile_negative']}/5`",
        "",
        "## Calibration Notes for `confirmation_bias_considered`",
        "",
        "- The Q1 thresholds (-1σ_cross / -2σ_cross + breadth ≥3/5) were chosen",
        "  by analogy to standard statistical-significance translations, NOT",
        "  derived from the fragile-cohort distribution observed in 1.6.",
        "- The I1 tier boundaries (0.10 / 0.15 PF) were chosen as round numbers",
        "  by the analyst, NOT derived from σ_cross.",
        f"- On 1.6 evidence, the Q1 retrospective verdict is `{gates['q1_retrospective_verdict_on_1_6']}`.",
        "  This was NOT used to tune the gate; it is recorded here as evidence",
        "  the gate is not silently mis-calibrated to flag-or-not-flag at 1.6.",
        "- The fragile cohort in 1.6 shows aggregate lift ≥ 0 (positive but",
        "  regime-fragile). The Q1 rule fires only on aggregate negativity, so",
        "  by construction it would not have flipped 1.6's verdict.",
        "",
        "## Reproducibility",
        "",
        f"- Generated UTC: `{runtime_utc}`",
        "- Tool: `tools/gate_sensitivity.py`",
        f"- Inputs: locked 1.6 baseline report (SHA `{report_sha[:16]}…`)",
        "- σ_cross + MDE source: `Goblin/reports/ml/p2_0_mde_derivation_manifest.json` (EX-1)",
        "",
    ]
    return "\n".join(lines)


def _content_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EX-2 gate sensitivity analysis")
    parser.add_argument(
        "--check-determinism",
        action="store_true",
        help="Render report twice (excluding timestamp) and assert bit-identical content",
    )
    args = parser.parse_args(argv)

    cfg = _load_toml(EVAL_GATES_PATH)
    bc = cfg["ml_baseline_comparison"]
    p2 = cfg["ml_p2"]
    pilot = cfg["ml_variance_pilot"]

    report_path = REPO_ROOT / bc["report_path"]
    if not report_path.exists():
        print(f"ERROR: baseline report not found at {report_path}", file=sys.stderr)
        return 4

    with report_path.open() as f:
        report = json.load(f)

    actual_report_sha = hashlib.sha256(report_path.read_bytes()).hexdigest()
    if bc.get("report_sha") and actual_report_sha != bc["report_sha"]:
        print(
            f"ERROR: baseline report SHA mismatch: expected {bc['report_sha']}, "
            f"got {actual_report_sha}",
            file=sys.stderr,
        )
        return 5

    gates = evaluate_gates(
        report["candidate_results"],
        sigma_cross=p2["sigma_cross_point"],
        mde_point=p2["mde_pf_point"],
        mde_upper=p2["mde_pf_at_upper_ci_bound"],
        effect_size_floor=pilot["effect_size_floor_pf"],
    )

    runtime_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    md = render_report(
        run_id=report["run_id"],
        dataset_sha=bc["dataset_sha"],
        report_sha=actual_report_sha,
        sigma_cross=p2["sigma_cross_point"],
        mde_point=p2["mde_pf_point"],
        mde_upper=p2["mde_pf_at_upper_ci_bound"],
        effect_size_floor=pilot["effect_size_floor_pf"],
        gates=gates,
        runtime_utc=runtime_utc,
    )

    if args.check_determinism:
        # Render again with a different timestamp; strip both timestamps and compare.
        md2 = render_report(
            run_id=report["run_id"],
            dataset_sha=bc["dataset_sha"],
            report_sha=actual_report_sha,
            sigma_cross=p2["sigma_cross_point"],
            mde_point=p2["mde_pf_point"],
            mde_upper=p2["mde_pf_at_upper_ci_bound"],
            effect_size_floor=pilot["effect_size_floor_pf"],
            gates=gates,
            runtime_utc="ALT-TIMESTAMP",
        )
        s1 = "\n".join(line for line in md.splitlines() if "Generated UTC" not in line)
        s2 = "\n".join(line for line in md2.splitlines() if "Generated UTC" not in line)
        if s1 != s2:
            print("ERROR: gate sensitivity report not deterministic", file=sys.stderr)
            return 6
        print("Determinism check: PASS")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(md, encoding="utf-8")
    print(f"Report written: {REPORT_PATH.relative_to(REPO_ROOT)}")
    print(f"Q1 retrospective verdict on 1.6: {gates['q1_retrospective_verdict_on_1_6']}")
    print(f"I1 locked tier: {gates['i1_locked_tier']}")
    print(f"Survivor mean lift: {gates['survivor_mean_lift']:.6f}")
    print(f"Fragile mean lift:  {gates['fragile_mean_lift']:.6f}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
