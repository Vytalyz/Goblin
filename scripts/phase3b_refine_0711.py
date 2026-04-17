"""Phase 3b: Focused refinement of AF-CAND-0711 (missed stress by 0.012 PF).

Base params: volatility_breakout, threshold 2.5, zscore_floor 0.75,
             SL 8, TP 20, hold 120, spread <= 2.0

Strategy: 5 narrow single/dual-parameter tweaks, each immediately stress-tested.
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


def _base() -> dict:
    """Return AF-CAND-0711 base params as a mutable dict."""
    return {
        "family": "europe_open_impulse_retest_research",
        "source_citations": ["blank-slate-scalping-v2-refinement"],
        "strategy_hypothesis": "Focused refinement of AF-CAND-0711 to clear stress floor.",
        "market_context": {
            "session_focus": "europe_open_breakout",
            "volatility_preference": "moderate_to_high",
            "directional_bias": "both",
            "execution_notes": ["Enter only during EU open 08-14 UTC. Spread-filtered."],
            "allowed_hours_utc": [8, 9, 10, 11, 12, 13],
        },
        "setup_summary": "Very high momentum + Z-score + ret_5 + mean location + tight spread.",
        "entry_summary": "Enter strongest volatility breakout signals.",
        "risk_summary": "Selective entry, spread-filtered.",
        "entry_style": "volatility_breakout",
        "holding_bars": 120,
        "signal_threshold": 2.5,
        "stop_loss_pips": 8.0,
        "take_profit_pips": 20.0,
        "trailing_stop_enabled": False,
        "trailing_stop_pips": None,
        "custom_filters": [
            {"name": "breakout_zscore_floor", "rule": "0.75"},
            {"name": "require_ret_5_alignment", "rule": "true"},
            {"name": "require_mean_location_alignment", "rule": "true"},
            {"name": "min_volatility_20", "rule": "0.00006"},
            {"name": "max_spread_pips", "rule": "2.0"},
        ],
    }


def _variants() -> list[dict]:
    """5 narrow refinements — each changes 1-2 parameters from the base."""

    # V1: Wider TP (20 → 24) — more reward per winner
    v1 = _base()
    v1.update({
        "candidate_id": "AF-CAND-0720",
        "title": "0711 Refinement: Wider TP 24",
        "thesis": "Wider TP gives breakout winners more room to run, improving reward vs fixed cost.",
        "exit_summary": "Fixed stop 8 pips, target 24 pips, 120-bar timeout.",
        "take_profit_pips": 24.0,
    })

    # V2: Wider TP (22) + longer hold (150 bars)
    v2 = _base()
    v2.update({
        "candidate_id": "AF-CAND-0721",
        "title": "0711 Refinement: TP 22 + Hold 150",
        "thesis": "Slightly wider TP + more bars gives marginal winners time to reach target.",
        "exit_summary": "Fixed stop 8 pips, target 22 pips, 150-bar timeout.",
        "take_profit_pips": 22.0,
        "holding_bars": 150,
    })

    # V3: Tighter spread (2.0 → 1.5) — reject costliest bars
    v3 = _base()
    v3.update({
        "candidate_id": "AF-CAND-0722",
        "title": "0711 Refinement: Tight Spread 1.5",
        "thesis": "Tighter spread filter eliminates trades where cost eats the edge.",
        "exit_summary": "Fixed stop 8 pips, target 20 pips, 120-bar timeout.",
    })
    v3["custom_filters"] = [
        {"name": "breakout_zscore_floor", "rule": "0.75"},
        {"name": "require_ret_5_alignment", "rule": "true"},
        {"name": "require_mean_location_alignment", "rule": "true"},
        {"name": "min_volatility_20", "rule": "0.00006"},
        {"name": "max_spread_pips", "rule": "1.5"},
    ]

    # V4: Higher threshold (2.5 → 2.8) + wider TP (22)
    v4 = _base()
    v4.update({
        "candidate_id": "AF-CAND-0723",
        "title": "0711 Refinement: Threshold 2.8 + TP 22",
        "thesis": "Higher momentum threshold selects only the most extreme breakouts; wider TP captures them.",
        "exit_summary": "Fixed stop 8 pips, target 22 pips, 120-bar timeout.",
        "signal_threshold": 2.8,
        "take_profit_pips": 22.0,
    })

    # V5: Tighter spread (1.5) + wider TP (22) + longer hold (150)
    v5 = _base()
    v5.update({
        "candidate_id": "AF-CAND-0724",
        "title": "0711 Refinement: Spread 1.5 + TP 22 + Hold 150",
        "thesis": "Combine tighter spread, wider TP, and longer hold to maximize edge survival under cost stress.",
        "exit_summary": "Fixed stop 8 pips, target 22 pips, 150-bar timeout.",
        "take_profit_pips": 22.0,
        "holding_bars": 150,
    })
    v5["custom_filters"] = [
        {"name": "breakout_zscore_floor", "rule": "0.75"},
        {"name": "require_ret_5_alignment", "rule": "true"},
        {"name": "require_mean_location_alignment", "rule": "true"},
        {"name": "min_volatility_20", "rule": "0.00006"},
        {"name": "max_spread_pips", "rule": "1.5"},
    ]

    return [v1, v2, v3, v4, v5]


def main():
    settings = load_settings(project_root=PROJECT_ROOT)
    read_policy = ReadPolicy(project_root=PROJECT_ROOT)

    variants = _variants()
    results = []

    for i, raw in enumerate(variants, 1):
        cid = raw["candidate_id"]
        print(f"\n[{i}/5] {cid} — {raw['title']}", flush=True)

        draft = CandidateDraft(**raw)

        candidate_dir = settings.paths().reports_dir / cid
        candidate_dir.mkdir(parents=True, exist_ok=True)
        write_json(candidate_dir / "candidate.json", draft.model_dump(mode="json"))

        spec_payload = compile_strategy_spec_tool(
            payload=draft.model_dump(mode="json"),
            settings=settings,
            config={},
            read_policy=read_policy,
        )
        spec = StrategySpec.model_validate(spec_payload)

        # Quick base backtest
        artifact = run_backtest(spec, settings)
        print(f"  Base: {artifact.trade_count} trades, PF {artifact.profit_factor:.3f}, WR {artifact.win_rate:.1%}, DD {artifact.max_drawdown_pct:.2f}%, OOS PF {artifact.out_of_sample_profit_factor:.3f}")

        if artifact.trade_count < 50 or artifact.profit_factor < 1.0:
            print(f"  Skipping stress — didn't pass triage (trades={artifact.trade_count}, PF={artifact.profit_factor:.3f})")
            results.append({
                "candidate_id": cid,
                "title": raw["title"],
                "trades": artifact.trade_count,
                "base_pf": round(artifact.profit_factor, 3),
                "stressed_pf": 0.0,
                "stress_passed": False,
                "wf_passing": 0,
                "wf_total": 0,
                "wf_passed": False,
                "oos_pf": round(artifact.out_of_sample_profit_factor, 3),
                "max_dd_pct": round(artifact.max_drawdown_pct, 2),
                "overall_pass": False,
            })
            continue

        # Stress test
        print(f"  Running stress test...")
        stress = run_stress_test(spec, settings)
        for sc in stress.scenarios:
            print(f"    {sc.name}: PF {sc.profit_factor:.3f}")
        print(f"  Worst stressed PF: {stress.stressed_profit_factor:.3f} {'PASS' if stress.passed else 'FAIL'}")

        # Walk-forward
        wf = artifact.walk_forward_summary or []
        wf_passing = sum(1 for w in wf if w.get("profit_factor", 0) >= 0.9)
        wf_total = len(wf)
        wf_passed = wf_passing >= 2 and wf_total >= 3
        for j, w in enumerate(wf, 1):
            pf = w.get("profit_factor", 0)
            tc = w.get("trade_count", 0)
            print(f"    WF {j}: {tc} trades, PF {pf:.3f} [{'OK' if pf >= 0.9 else 'FAIL'}]")
        print(f"  Walk-forward: {wf_passing}/{wf_total} pass")

        overall = stress.passed and wf_passed
        results.append({
            "candidate_id": cid,
            "title": raw["title"],
            "trades": artifact.trade_count,
            "base_pf": round(stress.base_profit_factor, 3),
            "stressed_pf": round(stress.stressed_profit_factor, 3),
            "stress_passed": stress.passed,
            "wf_passing": wf_passing,
            "wf_total": wf_total,
            "wf_passed": wf_passed,
            "oos_pf": round(artifact.out_of_sample_profit_factor, 3),
            "max_dd_pct": round(artifact.max_drawdown_pct, 2),
            "overall_pass": overall,
        })
        label = "PASS" if overall else "FAIL"
        print(f"  >>> {cid}: [{label}]")

    # Summary
    print("\n\n" + "=" * 120)
    print(f"{'ID':<16} {'Title':<40} {'Trades':>6} {'Base PF':>8} {'Str PF':>8} {'Stress':>7} {'WF':>5} {'OOS PF':>7} {'DD%':>6} {'Result':>7}")
    print("-" * 120)
    for r in results:
        s = "PASS" if r["stress_passed"] else "FAIL"
        w = f"{r['wf_passing']}/{r['wf_total']}"
        o = "PASS" if r["overall_pass"] else "FAIL"
        print(f"{r['candidate_id']:<16} {r['title']:<40} {r['trades']:>6} {r['base_pf']:>8.3f} {r['stressed_pf']:>8.3f} {s:>7} {w:>5} {r['oos_pf']:>7.3f} {r['max_dd_pct']:>5.2f}% {o:>7}")
    print("=" * 120)

    passed = sum(1 for r in results if r["overall_pass"])
    print(f"\nRefinement: {passed}/5 variants passed stress + walk-forward")

    write_json(PROJECT_ROOT / "reports" / "phase3b_refinement_results.json", results)
    print(f"Saved to: reports/phase3b_refinement_results.json")


if __name__ == "__main__":
    main()
