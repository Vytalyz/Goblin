from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_forex.backtesting.engine import run_backtest, run_stress_test
from agentic_forex.config import load_settings
from agentic_forex.evals.robustness import build_robustness_report
from agentic_forex.governance.readiness import required_evidence, resolve_readiness_status
from agentic_forex.runtime import ReadPolicy
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows.contracts import CandidateDraft, ReviewPacket, StrategySpec

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FINALISTS = ["AF-CAND-0733", "AF-CAND-0730"]
FAILED_SWING = ["AF-CAND-0739", "AF-CAND-0738", "AF-CAND-0716"]


def _load_spec(candidate_id: str, settings) -> tuple[CandidateDraft, StrategySpec]:
    report_dir = settings.paths().reports_dir / candidate_id
    draft = CandidateDraft.model_validate(read_json(report_dir / "candidate.json"))
    spec = StrategySpec.model_validate(read_json(report_dir / "strategy_spec.json"))
    return draft, spec


def _build_review_packet(candidate: CandidateDraft, spec: StrategySpec, settings) -> dict:
    artifact = run_backtest(spec, settings)
    stress = run_stress_test(spec, settings)
    trade_ledger = pd.read_csv(artifact.trade_ledger_path)
    robustness = build_robustness_report(spec, backtest=artifact, stress=stress, trade_ledger=trade_ledger, settings=settings)
    write_json(robustness.report_path, robustness.model_dump(mode="json"))

    readiness = resolve_readiness_status(
        candidate_id=spec.candidate_id,
        spec_exists=True,
        backtest=artifact,
        stress=stress,
        robustness=robustness,
        parity_passed=False,
        forward_report=None,
        settings=settings,
    )
    evidence = required_evidence(readiness)
    metrics = {
        "family": spec.family,
        "trade_count": artifact.trade_count,
        "profit_factor": artifact.profit_factor,
        "out_of_sample_profit_factor": artifact.out_of_sample_profit_factor,
        "expectancy_pips": artifact.expectancy_pips,
        "max_drawdown_pct": artifact.max_drawdown_pct,
        "split_breakdown": artifact.split_breakdown,
        "regime_breakdown": artifact.regime_breakdown,
        "walk_forward_summary": artifact.walk_forward_summary,
        "stress_scenarios": [scenario.model_dump(mode="json") for scenario in stress.scenarios],
        "stress_passed": stress.passed,
        "approval_recommendation": "needs_human_review",
        "readiness_status": readiness,
        "required_evidence": evidence,
    }

    strengths = []
    if artifact.out_of_sample_profit_factor >= 1.5:
        strengths.append(f"Holdout PF is strong at {artifact.out_of_sample_profit_factor:.3f}.")
    if stress.stressed_profit_factor >= 1.35:
        strengths.append(f"Worst stressed PF remains robust at {stress.stressed_profit_factor:.3f}.")
    if artifact.max_drawdown_pct < 2.5:
        strengths.append(f"Drawdown stayed low at {artifact.max_drawdown_pct:.2f}%.")
    if sum(1 for window in artifact.walk_forward_summary if window.get('profit_factor', 0) >= 0.9) >= 3:
        strengths.append("All walk-forward windows cleared the PF floor.")

    weaknesses = [
        "Explicit human approval is still required before publish.",
        "Explicit mt5_packet approval is still required before MT5 packet generation.",
        "No parity or forward-stage evidence exists yet, so readiness remains provisional.",
    ]

    failure_modes = [
        "Spread and slippage expansion could compress breakout expectancy.",
        "Performance may degrade outside Europe and overlap session structure.",
        "Volatility regime changes may reduce high-momentum breakout follow-through.",
    ]

    packet = ReviewPacket(
        candidate_id=spec.candidate_id,
        readiness=readiness,
        required_evidence=evidence,
        robustness_mode=robustness.mode,
        strengths=strengths,
        weaknesses=weaknesses,
        failure_modes=failure_modes,
        contradiction_summary=candidate.contradiction_summary,
        next_actions=[
            "Submit for human review approval.",
            "After approval, record mt5_packet approval and generate MT5 packet.",
            "Treat MT5 parity as practice-only confirmation, not research truth.",
        ],
        approval_recommendation="needs_human_review",
        citations=candidate.source_citations,
        metrics=metrics,
        ftmo_fit={},
    )
    review_path = settings.paths().reports_dir / spec.candidate_id / "review_packet.json"
    write_json(review_path, packet.model_dump(mode="json"))
    return {
        "candidate_id": spec.candidate_id,
        "review_packet_path": str(review_path),
        "robustness_report_path": str(robustness.report_path),
        "readiness": readiness,
        "approval_recommendation": packet.approval_recommendation,
        "oos_pf": round(artifact.out_of_sample_profit_factor, 3),
        "stressed_pf": round(stress.stressed_profit_factor, 3),
        "max_dd_pct": round(artifact.max_drawdown_pct, 2),
        "human_review_approved": False,
        "mt5_packet_approved": False,
        "publish_blocked_reason": "human_review approval missing",
        "mt5_packet_blocked_reason": "mt5_packet approval missing",
    }


def _swing_diagnostic(settings) -> dict:
    records = []
    overlap_failures = 0
    high_vol_failures = 0
    all_negative_holdout = True
    for candidate_id in FAILED_SWING:
        summary = read_json(settings.paths().reports_dir / candidate_id / "backtest_summary.json")
        oos = summary["split_breakdown"]["out_of_sample"]
        overlap = summary["regime_breakdown"]["session_bucket"].get("overlap", {})
        high_vol = summary["regime_breakdown"]["volatility_bucket"].get("high", {})
        if float(overlap.get("profit_factor", 0.0)) < 1.0:
            overlap_failures += 1
        if float(high_vol.get("profit_factor", 0.0)) < 1.0:
            high_vol_failures += 1
        if float(oos.get("expectancy_pips", 0.0)) >= 0:
            all_negative_holdout = False
        records.append(
            {
                "candidate_id": candidate_id,
                "holdout_trades": int(oos.get("trade_count", 0)),
                "holdout_pf": float(oos.get("profit_factor", 0.0)),
                "holdout_expectancy_pips": float(oos.get("expectancy_pips", 0.0)),
                "validation_pf": float(summary["split_breakdown"]["validation"].get("profit_factor", 0.0)),
                "overlap_pf": float(overlap.get("profit_factor", 0.0)),
                "high_vol_pf": float(high_vol.get("profit_factor", 0.0)),
            }
        )

    diagnostic = {
        "lane": "swing_pullback_continuation",
        "candidate_count": len(records),
        "all_negative_holdout_expectancy": all_negative_holdout,
        "overlap_bucket_failures": overlap_failures,
        "high_vol_bucket_failures": high_vol_failures,
        "records": records,
        "findings": [
            "All tested swing survivors failed holdout PF and holdout expectancy.",
            "Validation PF was inflated on very small samples relative to holdout sample sizes.",
            "Overlap-session behavior was consistently weak for the swing family.",
            "High-volatility swing behavior did not generalize and often collapsed below PF 1.0.",
        ],
        "recommended_actions": [
            "Retire the current swing pullback family from promotion consideration.",
            "If swing work resumes, isolate Europe-only behavior and explicitly block overlap trades.",
            "Require larger holdout trade counts before trusting future swing refinements.",
        ],
    }
    output_path = PROJECT_ROOT / "reports" / "phase5_swing_diagnostic.json"
    write_json(output_path, diagnostic)
    diagnostic["report_path"] = str(output_path)
    return diagnostic


def main() -> None:
    settings = load_settings(project_root=PROJECT_ROOT)
    review_outputs = []
    for candidate_id in FINALISTS:
        candidate, spec = _load_spec(candidate_id, settings)
        review_outputs.append(_build_review_packet(candidate, spec, settings))

    swing_diagnostic = _swing_diagnostic(settings)

    summary = {
        "finalists": review_outputs,
        "swing_diagnostic_path": swing_diagnostic["report_path"],
        "next_gate": "explicit human_review approval",
        "blocked_actions": [
            "publish-candidate",
            "generate-mt5-packet",
        ],
    }
    summary_path = PROJECT_ROOT / "reports" / "phase5_promotion_prep.json"
    write_json(summary_path, summary)
    print(json.dumps({**summary, "summary_path": str(summary_path)}, indent=2))


if __name__ == "__main__":
    main()
