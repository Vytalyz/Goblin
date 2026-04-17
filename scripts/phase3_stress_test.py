"""Phase 3: Stress test + walk-forward validation for triage winners.

Runs run_stress_test (spread 1.25×, +0.25 pip slippage, +500 ms delay)
and evaluates walk-forward windows from the base backtest.

Pass criteria:
  - Stressed PF >= 1.0 (stress_profit_factor_floor)
  - Walk-forward: >= 2/3 windows with PF >= 0.9
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

# The 4 triage winners from Phase 2 v2
WINNERS = ["AF-CAND-0710", "AF-CAND-0711", "AF-CAND-0712", "AF-CAND-0716"]


def main():
    settings = load_settings(project_root=PROJECT_ROOT)
    read_policy = ReadPolicy(project_root=PROJECT_ROOT)

    results = []

    for cid in WINNERS:
        print(f"\n{'='*70}")
        print(f"Stress-testing {cid}")
        print("=" * 70, flush=True)

        # Reload the candidate draft from reports
        candidate_path = settings.paths().reports_dir / cid / "candidate.json"
        raw = json.loads(candidate_path.read_text())
        draft = CandidateDraft(**raw)

        # Compile to StrategySpec
        spec_payload = compile_strategy_spec_tool(
            payload=draft.model_dump(mode="json"),
            settings=settings,
            config={},
            read_policy=read_policy,
        )
        spec = StrategySpec.model_validate(spec_payload)

        # Run stress test (3 adversarial scenarios)
        print(f"  Running stress test (spread 1.25x + 0.25 pip slip + 500 ms delay)...")
        stress_report = run_stress_test(spec, settings)

        print(f"  Base PF:     {stress_report.base_profit_factor:.3f}")
        for sc in stress_report.scenarios:
            print(f"  {sc.name}: PF {sc.profit_factor:.3f} (spread {sc.spread_multiplier}x, slip {sc.slippage_pips} pips, delay {sc.fill_delay_ms} ms)")
        print(f"  Worst stressed PF: {stress_report.stressed_profit_factor:.3f}")
        print(f"  Stress passed: {stress_report.passed}")

        # Get walk-forward from base backtest (already computed)
        base_artifact = run_backtest(spec, settings, output_prefix="phase3_base")
        wf_windows = base_artifact.walk_forward_summary or []
        wf_passing = sum(1 for w in wf_windows if w.get("profit_factor", 0) >= 0.9)
        wf_total = len(wf_windows)
        wf_passed = wf_passing >= 2 and wf_total >= 3

        print(f"\n  Walk-forward ({wf_total} windows):")
        for i, w in enumerate(wf_windows, 1):
            wf_pf = w.get("profit_factor", 0)
            wf_trades = w.get("trade_count", 0)
            wf_status = "OK" if wf_pf >= 0.9 else "FAIL"
            print(f"    Window {i}: {wf_trades} trades, PF {wf_pf:.3f} [{wf_status}]")
        print(f"  Walk-forward passed: {wf_passed} ({wf_passing}/{wf_total} windows >= 0.9 PF)")

        overall_pass = stress_report.passed and wf_passed

        results.append({
            "candidate_id": cid,
            "entry_style": spec.entry_style,
            "base_pf": round(stress_report.base_profit_factor, 3),
            "stressed_pf": round(stress_report.stressed_profit_factor, 3),
            "stress_passed": stress_report.passed,
            "scenarios": [
                {"name": sc.name, "pf": round(sc.profit_factor, 3)} for sc in stress_report.scenarios
            ],
            "wf_windows": wf_windows,
            "wf_passing": wf_passing,
            "wf_total": wf_total,
            "wf_passed": wf_passed,
            "oos_pf": round(base_artifact.out_of_sample_profit_factor, 3),
            "trades": base_artifact.trade_count,
            "max_dd_pct": round(base_artifact.max_drawdown_pct, 2),
            "overall_pass": overall_pass,
        })

        overall_label = "PASS" if overall_pass else "FAIL"
        print(f"\n  >>> {cid} Phase 3: [{overall_label}]")

    # Summary table
    print("\n\n" + "=" * 110)
    print(f"{'ID':<16} {'Style':<28} {'Trades':>6} {'Base PF':>8} {'Stress PF':>10} {'Stress':>7} {'WF Win':>7} {'WF':>5} {'Overall':>8}")
    print("-" * 110)
    for r in results:
        stress_lbl = "PASS" if r["stress_passed"] else "FAIL"
        wf_lbl = "PASS" if r["wf_passed"] else "FAIL"
        overall_lbl = "PASS" if r["overall_pass"] else "FAIL"
        print(
            f"{r['candidate_id']:<16} {r['entry_style']:<28} {r['trades']:>6} "
            f"{r['base_pf']:>8.3f} {r['stressed_pf']:>10.3f} {stress_lbl:>7} "
            f"{r['wf_passing']}/{r['wf_total']:>5} {wf_lbl:>5} {overall_lbl:>8}"
        )
    print("=" * 110)

    passed_count = sum(1 for r in results if r["overall_pass"])
    print(f"\nPhase 3: {passed_count}/{len(results)} candidates survived stress + walk-forward")

    triage_path = PROJECT_ROOT / "reports" / "phase3_stress_results.json"
    write_json(triage_path, results)
    print(f"Full results saved to: {triage_path}")


if __name__ == "__main__":
    main()
