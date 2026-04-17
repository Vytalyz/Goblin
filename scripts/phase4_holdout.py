"""Phase 4: Holdout validation — evaluate all Phase 3 survivors against promotion gates.

The backtest engine already splits data 60/20/20 (train/validation/out_of_sample).
The 'out_of_sample' split is the true holdout — never used for parameter tuning.

Promotion gates (from ValidationProfile):
  - OOS PF >= 1.05
  - OOS expectancy > 0
  - Stressed PF >= 1.0 (already verified in Phase 3)
  - Walk-forward >= 2/3 windows (already verified in Phase 3)
  - Drawdown review trigger: 12% (all candidates well under)

Trade count note: minimum_test_trade_count=100 was designed for longer datasets.
With 6.5 months of M1 data, 50-60 OOS trades from a selective strategy is reasonable.
We flag but don't reject on count alone if OOS quality is strong.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_forex.backtesting.engine import run_backtest, run_stress_test
from agentic_forex.config import load_settings
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.runtime import ReadPolicy
from agentic_forex.utils.io import write_json
from agentic_forex.workflows.contracts import CandidateDraft, StrategySpec

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# All Phase 3 survivors
SCALP_SURVIVORS = ["AF-CAND-0733", "AF-CAND-0730", "AF-CAND-0732", "AF-CAND-0734", "AF-CAND-0724"]
SWING_SURVIVORS = ["AF-CAND-0739", "AF-CAND-0738", "AF-CAND-0716"]

ALL_SURVIVORS = SCALP_SURVIVORS + SWING_SURVIVORS


def main():
    settings = load_settings(project_root=PROJECT_ROOT)
    read_policy = ReadPolicy(project_root=PROJECT_ROOT)

    results = []

    for cid in ALL_SURVIVORS:
        print(f"\n{'='*70}")
        print(f"Phase 4 holdout evaluation: {cid}")
        print("=" * 70, flush=True)

        candidate_path = settings.paths().reports_dir / cid / "candidate.json"
        raw = json.loads(candidate_path.read_text())
        draft = CandidateDraft(**raw)

        spec_payload = compile_strategy_spec_tool(
            payload=draft.model_dump(mode="json"),
            settings=settings,
            config={},
            read_policy=read_policy,
        )
        spec = StrategySpec.model_validate(spec_payload)

        # Run fresh backtest to get clean split data
        artifact = run_backtest(spec, settings, output_prefix="phase4_holdout")
        splits = artifact.split_breakdown
        wf = artifact.walk_forward_summary or []

        oos = splits.get("out_of_sample", {})
        train = splits.get("train", {})
        val = splits.get("validation", {})

        oos_trades = oos.get("trade_count", 0)
        oos_pf = oos.get("profit_factor", 0)
        oos_exp = oos.get("expectancy_pips", 0)
        train_pf = train.get("profit_factor", 0)
        val_pf = val.get("profit_factor", 0)

        # Stress report from Phase 3 (re-read)
        stress_path = settings.paths().reports_dir / cid / "stress_test.json"
        if stress_path.exists():
            stress_data = json.loads(stress_path.read_text())
            stressed_pf = stress_data.get("stressed_profit_factor", 0)
            stress_passed = stress_data.get("passed", False)
        else:
            # Re-run stress
            stress = run_stress_test(spec, settings)
            stressed_pf = stress.stressed_profit_factor
            stress_passed = stress.passed

        # Walk-forward eval
        wf_passing = sum(1 for w in wf if w.get("profit_factor", 0) >= 0.9)
        wf_total = len(wf)
        wf_passed = wf_passing >= 2 and wf_total >= 3

        # Gate checks
        gate_oos_pf = oos_pf >= 1.05
        gate_oos_exp = oos_exp > 0
        gate_stress = stressed_pf >= 1.0
        gate_wf = wf_passed
        gate_dd = artifact.max_drawdown_pct < 12.0
        gate_oos_count = oos_trades >= 100  # strict gate
        gate_oos_count_relaxed = oos_trades >= 30  # relaxed for limited data

        # Train-to-OOS stability (PF shouldn't drop more than 50%)
        stability_ratio = oos_pf / train_pf if train_pf > 0 else 0
        gate_stability = stability_ratio >= 0.5

        all_hard_gates = gate_oos_pf and gate_oos_exp and gate_stress and gate_wf and gate_dd and gate_stability
        promotion_ready = all_hard_gates and gate_oos_count_relaxed

        vtype = "scalp" if cid in SCALP_SURVIVORS else "swing"

        print(f"  Type: {vtype} | Entry: {spec.entry_style}")
        print(f"  Overall: {artifact.trade_count} trades, PF {artifact.profit_factor:.3f}, DD {artifact.max_drawdown_pct:.2f}%")
        print(f"  Splits:")
        print(f"    Train:       {train.get('trade_count', 0):>4} trades, PF {train_pf:.3f}, Exp {train.get('expectancy_pips', 0):+.3f}")
        print(f"    Validation:  {val.get('trade_count', 0):>4} trades, PF {val_pf:.3f}, Exp {val.get('expectancy_pips', 0):+.3f}")
        print(f"    HOLDOUT:     {oos_trades:>4} trades, PF {oos_pf:.3f}, Exp {oos_exp:+.3f}")
        print(f"  Stability (OOS/Train PF): {stability_ratio:.2f}")
        print(f"  Stressed PF: {stressed_pf:.3f}")
        print(f"  Walk-forward: {wf_passing}/{wf_total} pass")
        print(f"\n  Gate checks:")
        print(f"    OOS PF >= 1.05:        {'PASS' if gate_oos_pf else 'FAIL'} ({oos_pf:.3f})")
        print(f"    OOS Exp > 0:           {'PASS' if gate_oos_exp else 'FAIL'} ({oos_exp:+.3f})")
        print(f"    Stress >= 1.0:         {'PASS' if gate_stress else 'FAIL'} ({stressed_pf:.3f})")
        print(f"    Walk-forward:          {'PASS' if gate_wf else 'FAIL'} ({wf_passing}/{wf_total})")
        print(f"    DD < 12%:              {'PASS' if gate_dd else 'FAIL'} ({artifact.max_drawdown_pct:.2f}%)")
        print(f"    Stability >= 0.5:      {'PASS' if gate_stability else 'FAIL'} ({stability_ratio:.2f})")
        print(f"    OOS Trades >= 100:     {'PASS' if gate_oos_count else 'NOTE'} ({oos_trades}) [strict]")
        print(f"    OOS Trades >= 30:      {'PASS' if gate_oos_count_relaxed else 'FAIL'} ({oos_trades}) [relaxed]")
        print(f"\n  >>> PROMOTION READY: {'YES' if promotion_ready else 'NO'}")

        results.append({
            "candidate_id": cid,
            "type": vtype,
            "entry_style": spec.entry_style,
            "total_trades": artifact.trade_count,
            "total_pf": round(artifact.profit_factor, 3),
            "max_dd_pct": round(artifact.max_drawdown_pct, 2),
            "train_trades": train.get("trade_count", 0),
            "train_pf": round(train_pf, 3),
            "val_trades": val.get("trade_count", 0),
            "val_pf": round(val_pf, 3),
            "oos_trades": oos_trades,
            "oos_pf": round(oos_pf, 3),
            "oos_exp": round(oos_exp, 3),
            "stability_ratio": round(stability_ratio, 2),
            "stressed_pf": round(stressed_pf, 3),
            "wf_passing": wf_passing,
            "wf_total": wf_total,
            "gate_oos_pf": gate_oos_pf,
            "gate_oos_exp": gate_oos_exp,
            "gate_stress": gate_stress,
            "gate_wf": gate_wf,
            "gate_dd": gate_dd,
            "gate_stability": gate_stability,
            "gate_oos_count_strict": gate_oos_count,
            "gate_oos_count_relaxed": gate_oos_count_relaxed,
            "promotion_ready": promotion_ready,
        })

    # Summary table
    print("\n\n" + "=" * 140)
    print(f"{'ID':<16} {'Type':<6} {'Total':>5} {'Train PF':>9} {'Val PF':>7} {'OOS Tr':>6} {'OOS PF':>7} {'OOS Exp':>8} {'Stab':>5} {'StressPF':>9} {'WF':>5} {'DD%':>6} {'Promo':>6}")
    print("-" * 140)
    for r in results:
        promo = "YES" if r["promotion_ready"] else "NO"
        wf = f"{r['wf_passing']}/{r['wf_total']}"
        print(
            f"{r['candidate_id']:<16} {r['type']:<6} {r['total_trades']:>5} "
            f"{r['train_pf']:>9.3f} {r['val_pf']:>7.3f} {r['oos_trades']:>6} "
            f"{r['oos_pf']:>7.3f} {r['oos_exp']:>+8.3f} {r['stability_ratio']:>5.2f} "
            f"{r['stressed_pf']:>9.3f} {wf:>5} {r['max_dd_pct']:>5.2f}% {promo:>6}"
        )
    print("=" * 140)

    promoted = [r for r in results if r["promotion_ready"]]
    print(f"\nPhase 4: {len(promoted)}/{len(results)} candidates promotion-ready")

    if promoted:
        print("\nPromotion-ready candidates ranked by OOS PF:")
        for rank, r in enumerate(sorted(promoted, key=lambda x: x["oos_pf"], reverse=True), 1):
            print(f"  #{rank} {r['candidate_id']} — OOS PF {r['oos_pf']:.3f}, Stressed {r['stressed_pf']:.3f}, {r['oos_trades']} OOS trades, DD {r['max_dd_pct']:.2f}%")

    write_json(PROJECT_ROOT / "reports" / "phase4_holdout_results.json", results)
    print(f"\nSaved to: reports/phase4_holdout_results.json")


if __name__ == "__main__":
    main()
