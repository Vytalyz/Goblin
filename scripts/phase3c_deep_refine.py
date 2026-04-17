"""Phase 3c: Deep refinement — push both champions to their best.

AF-CAND-0724 (scalp, volatility_breakout): base PF 1.498, stressed 1.375
AF-CAND-0716 (swing, pullback_continuation): base PF 1.170, stressed 1.051

6 variants each = 12 total. Each immediately stress-tested + walk-forward.
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


# ── AF-CAND-0724 scalp base ────────────────────────────────────────────────
def _scalp_base() -> dict:
    return {
        "family": "europe_open_impulse_retest_research",
        "source_citations": ["blank-slate-scalping-v3-refinement"],
        "strategy_hypothesis": "Deep refinement of AF-CAND-0724 volatility breakout scalp.",
        "market_context": {
            "session_focus": "europe_open_breakout",
            "volatility_preference": "moderate_to_high",
            "directional_bias": "both",
            "execution_notes": ["EU open 08-14 UTC. Spread-filtered."],
            "allowed_hours_utc": [8, 9, 10, 11, 12, 13],
        },
        "setup_summary": "High momentum + Z-score + ret_5 + mean location + tight spread.",
        "entry_summary": "Enter strongest volatility breakout signals.",
        "risk_summary": "Selective entry, spread-filtered.",
        "entry_style": "volatility_breakout",
        "holding_bars": 150,
        "signal_threshold": 2.5,
        "stop_loss_pips": 8.0,
        "take_profit_pips": 22.0,
        "trailing_stop_enabled": False,
        "trailing_stop_pips": None,
        "custom_filters": [
            {"name": "breakout_zscore_floor", "rule": "0.75"},
            {"name": "require_ret_5_alignment", "rule": "true"},
            {"name": "require_mean_location_alignment", "rule": "true"},
            {"name": "min_volatility_20", "rule": "0.00006"},
            {"name": "max_spread_pips", "rule": "1.5"},
        ],
    }


def _scalp_variants() -> list[dict]:
    # R1: Wider TP 25 + hold 180 — more room for winners
    r1 = _scalp_base()
    r1.update({
        "candidate_id": "AF-CAND-0730",
        "title": "0724-R1: TP 25 + Hold 180",
        "thesis": "Push TP wider and give more hold time for large breakout follow-through.",
        "exit_summary": "Fixed stop 8 pips, target 25 pips, 180-bar timeout.",
        "take_profit_pips": 25.0,
        "holding_bars": 180,
    })

    # R2: Tighter spread 1.2 + TP 24 — eliminate most costly entries
    r2 = _scalp_base()
    r2.update({
        "candidate_id": "AF-CAND-0731",
        "title": "0724-R2: Spread 1.2 + TP 24",
        "thesis": "Ultra-tight spread filter ensures every entry has minimal cost drag.",
        "exit_summary": "Fixed stop 8 pips, target 24 pips, 150-bar timeout.",
        "take_profit_pips": 24.0,
    })
    r2["custom_filters"] = [
        {"name": "breakout_zscore_floor", "rule": "0.75"},
        {"name": "require_ret_5_alignment", "rule": "true"},
        {"name": "require_mean_location_alignment", "rule": "true"},
        {"name": "min_volatility_20", "rule": "0.00006"},
        {"name": "max_spread_pips", "rule": "1.2"},
    ]

    # R3: Higher Z-score floor 0.85 + TP 24 — more selective signal
    r3 = _scalp_base()
    r3.update({
        "candidate_id": "AF-CAND-0732",
        "title": "0724-R3: Zscore 0.85 + TP 24",
        "thesis": "Higher Z-score floor selects only directionally committed breakouts.",
        "exit_summary": "Fixed stop 8 pips, target 24 pips, 150-bar timeout.",
        "take_profit_pips": 24.0,
    })
    r3["custom_filters"] = [
        {"name": "breakout_zscore_floor", "rule": "0.85"},
        {"name": "require_ret_5_alignment", "rule": "true"},
        {"name": "require_mean_location_alignment", "rule": "true"},
        {"name": "min_volatility_20", "rule": "0.00006"},
        {"name": "max_spread_pips", "rule": "1.5"},
    ]

    # R4: Tighter SL 7 + TP 24 — better R:R ratio
    r4 = _scalp_base()
    r4.update({
        "candidate_id": "AF-CAND-0733",
        "title": "0724-R4: SL 7 + TP 24",
        "thesis": "Tighter stop loss improves R:R (3.4:1) and reduces per-trade downside.",
        "exit_summary": "Fixed stop 7 pips, target 24 pips, 150-bar timeout.",
        "stop_loss_pips": 7.0,
        "take_profit_pips": 24.0,
    })

    # R5: Higher vol floor 0.00007 + TP 24 + hold 180
    r5 = _scalp_base()
    r5.update({
        "candidate_id": "AF-CAND-0734",
        "title": "0724-R5: Vol 0.00007 + TP 24 + Hold 180",
        "thesis": "Higher volatility floor ensures adequate directional range for wider TP.",
        "exit_summary": "Fixed stop 8 pips, target 24 pips, 180-bar timeout.",
        "take_profit_pips": 24.0,
        "holding_bars": 180,
    })
    r5["custom_filters"] = [
        {"name": "breakout_zscore_floor", "rule": "0.75"},
        {"name": "require_ret_5_alignment", "rule": "true"},
        {"name": "require_mean_location_alignment", "rule": "true"},
        {"name": "min_volatility_20", "rule": "0.00007"},
        {"name": "max_spread_pips", "rule": "1.5"},
    ]

    # R6: Combined best — spread 1.2 + zscore 0.85 + TP 25 + hold 180
    r6 = _scalp_base()
    r6.update({
        "candidate_id": "AF-CAND-0735",
        "title": "0724-R6: Spread 1.2 + Zsc 0.85 + TP 25 + H 180",
        "thesis": "Stack the strongest individual tweaks into one ultra-selective variant.",
        "exit_summary": "Fixed stop 8 pips, target 25 pips, 180-bar timeout.",
        "take_profit_pips": 25.0,
        "holding_bars": 180,
    })
    r6["custom_filters"] = [
        {"name": "breakout_zscore_floor", "rule": "0.85"},
        {"name": "require_ret_5_alignment", "rule": "true"},
        {"name": "require_mean_location_alignment", "rule": "true"},
        {"name": "min_volatility_20", "rule": "0.00006"},
        {"name": "max_spread_pips", "rule": "1.2"},
    ]

    return [r1, r2, r3, r4, r5, r6]


# ── AF-CAND-0716 swing base ────────────────────────────────────────────────
def _swing_base() -> dict:
    return {
        "family": "europe_open_early_follow_through_research",
        "source_citations": ["blank-slate-swing-v3-refinement"],
        "strategy_hypothesis": "Deep refinement of AF-CAND-0716 pullback continuation swing.",
        "market_context": {
            "session_focus": "europe_open_follow_through",
            "volatility_preference": "moderate_to_high",
            "directional_bias": "both",
            "execution_notes": ["EU session 08-14 UTC. Ride directional moves."],
            "allowed_hours_utc": [8, 9, 10, 11, 12, 13],
        },
        "setup_summary": "Trend + pullback + mean alignment + recovery + trailing.",
        "entry_summary": "Enter pullback with mean location confirmation.",
        "risk_summary": "Wide trailing. R:R > 2:1.",
        "entry_style": "pullback_continuation",
        "holding_bars": 480,
        "signal_threshold": 0.8,
        "stop_loss_pips": 18.0,
        "take_profit_pips": 45.0,
        "trailing_stop_enabled": True,
        "trailing_stop_pips": 15.0,
        "custom_filters": [
            {"name": "trend_ret_5_min", "rule": "0.00004"},
            {"name": "pullback_zscore_limit", "rule": "0.70"},
            {"name": "require_recovery_ret_1", "rule": "true"},
            {"name": "require_mean_location_alignment", "rule": "true"},
            {"name": "max_spread_pips", "rule": "3.0"},
        ],
    }


def _swing_variants() -> list[dict]:
    # W1: Wider trail 18 + TP 55 — let winners run further
    w1 = _swing_base()
    w1.update({
        "candidate_id": "AF-CAND-0736",
        "title": "0716-W1: Trail 18 + TP 55",
        "thesis": "Wider trailing stop and TP lets genuine trends develop fully.",
        "exit_summary": "Trailing stop 18 pips, fixed SL 20 pips, TP 55 pips, 8-hour timeout.",
        "trailing_stop_pips": 18.0,
        "stop_loss_pips": 20.0,
        "take_profit_pips": 55.0,
    })

    # W2: Wider trail 20 + TP 60 + hold 600 — maximum room
    w2 = _swing_base()
    w2.update({
        "candidate_id": "AF-CAND-0737",
        "title": "0716-W2: Trail 20 + TP 60 + Hold 600",
        "thesis": "Maximum room for trend development — widest trail and hold.",
        "exit_summary": "Trailing stop 20 pips, fixed SL 22 pips, TP 60 pips, 10-hour timeout.",
        "trailing_stop_pips": 20.0,
        "stop_loss_pips": 22.0,
        "take_profit_pips": 60.0,
        "holding_bars": 600,
    })

    # W3: Tighter spread 2.5 + TP 50 — reduce cost impact
    w3 = _swing_base()
    w3.update({
        "candidate_id": "AF-CAND-0738",
        "title": "0716-W3: Spread 2.5 + TP 50",
        "thesis": "Tighter spread filter improves cost efficiency on swing entries.",
        "exit_summary": "Trailing stop 15 pips, fixed SL 18 pips, TP 50 pips, 8-hour timeout.",
        "take_profit_pips": 50.0,
    })
    w3["custom_filters"] = [
        {"name": "trend_ret_5_min", "rule": "0.00004"},
        {"name": "pullback_zscore_limit", "rule": "0.70"},
        {"name": "require_recovery_ret_1", "rule": "true"},
        {"name": "require_mean_location_alignment", "rule": "true"},
        {"name": "max_spread_pips", "rule": "2.5"},
    ]

    # W4: Lower threshold 0.6 + wider pullback 0.80 — more trades
    w4 = _swing_base()
    w4.update({
        "candidate_id": "AF-CAND-0739",
        "title": "0716-W4: Threshold 0.6 + Pullback 0.80",
        "thesis": "Relax entry criteria to increase trade count while keeping mean alignment and recovery filters.",
        "exit_summary": "Trailing stop 15 pips, fixed SL 18 pips, TP 45 pips, 8-hour timeout.",
        "signal_threshold": 0.6,
    })
    w4["custom_filters"] = [
        {"name": "trend_ret_5_min", "rule": "0.00003"},
        {"name": "pullback_zscore_limit", "rule": "0.80"},
        {"name": "require_recovery_ret_1", "rule": "true"},
        {"name": "require_mean_location_alignment", "rule": "true"},
        {"name": "max_spread_pips", "rule": "3.0"},
    ]

    # W5: Trail 18 + spread 2.5 + TP 50 — combined cost + room
    w5 = _swing_base()
    w5.update({
        "candidate_id": "AF-CAND-0740",
        "title": "0716-W5: Trail 18 + Spread 2.5 + TP 50",
        "thesis": "Combine tighter spread with wider trail and TP for best cost-adjusted performance.",
        "exit_summary": "Trailing stop 18 pips, fixed SL 20 pips, TP 50 pips, 8-hour timeout.",
        "trailing_stop_pips": 18.0,
        "stop_loss_pips": 20.0,
        "take_profit_pips": 50.0,
    })
    w5["custom_filters"] = [
        {"name": "trend_ret_5_min", "rule": "0.00004"},
        {"name": "pullback_zscore_limit", "rule": "0.70"},
        {"name": "require_recovery_ret_1", "rule": "true"},
        {"name": "require_mean_location_alignment", "rule": "true"},
        {"name": "max_spread_pips", "rule": "2.5"},
    ]

    # W6: Best-of stack — trail 18 + spread 2.5 + TP 55 + hold 600 + threshold 0.7
    w6 = _swing_base()
    w6.update({
        "candidate_id": "AF-CAND-0741",
        "title": "0716-W6: Trail 18 + Spr 2.5 + TP 55 + H 600",
        "thesis": "Stack strongest swing tweaks — wider room + cost reduction + relaxed threshold.",
        "exit_summary": "Trailing stop 18 pips, fixed SL 20 pips, TP 55 pips, 10-hour timeout.",
        "signal_threshold": 0.7,
        "trailing_stop_pips": 18.0,
        "stop_loss_pips": 20.0,
        "take_profit_pips": 55.0,
        "holding_bars": 600,
    })
    w6["custom_filters"] = [
        {"name": "trend_ret_5_min", "rule": "0.00004"},
        {"name": "pullback_zscore_limit", "rule": "0.75"},
        {"name": "require_recovery_ret_1", "rule": "true"},
        {"name": "require_mean_location_alignment", "rule": "true"},
        {"name": "max_spread_pips", "rule": "2.5"},
    ]

    return [w1, w2, w3, w4, w5, w6]


def main():
    settings = load_settings(project_root=PROJECT_ROOT)
    read_policy = ReadPolicy(project_root=PROJECT_ROOT)

    all_variants = _scalp_variants() + _swing_variants()
    results = []

    for i, raw in enumerate(all_variants, 1):
        cid = raw["candidate_id"]
        vtype = "scalp" if int(cid.split("-")[-1]) <= 735 else "swing"
        print(f"\n[{i}/12] {cid} ({vtype}) — {raw['title']}", flush=True)

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

        # Base backtest
        artifact = run_backtest(spec, settings)
        print(f"  Base: {artifact.trade_count} trades, PF {artifact.profit_factor:.3f}, WR {artifact.win_rate:.1%}, DD {artifact.max_drawdown_pct:.2f}%, OOS {artifact.out_of_sample_profit_factor:.3f}")

        if artifact.trade_count < 50 or artifact.profit_factor < 1.0:
            print(f"  Skip stress — triage fail (trades={artifact.trade_count}, PF={artifact.profit_factor:.3f})")
            results.append({
                "candidate_id": cid, "type": vtype, "title": raw["title"],
                "trades": artifact.trade_count, "base_pf": round(artifact.profit_factor, 3),
                "stressed_pf": 0.0, "stress_passed": False,
                "wf_passing": 0, "wf_total": 0, "wf_passed": False,
                "oos_pf": round(artifact.out_of_sample_profit_factor, 3),
                "max_dd_pct": round(artifact.max_drawdown_pct, 2),
                "overall_pass": False,
            })
            continue

        # Stress test
        print(f"  Stress testing...")
        stress = run_stress_test(spec, settings)
        for sc in stress.scenarios:
            print(f"    {sc.name}: PF {sc.profit_factor:.3f}")
        print(f"  Worst: {stress.stressed_profit_factor:.3f} {'PASS' if stress.passed else 'FAIL'}")

        # Walk-forward
        wf = artifact.walk_forward_summary or []
        wf_passing = sum(1 for w in wf if w.get("profit_factor", 0) >= 0.9)
        wf_total = len(wf)
        wf_passed = wf_passing >= 2 and wf_total >= 3
        for j, w in enumerate(wf, 1):
            print(f"    WF {j}: {w.get('trade_count', 0)} trades, PF {w.get('profit_factor', 0):.3f}")
        print(f"  WF: {wf_passing}/{wf_total} pass")

        overall = stress.passed and wf_passed
        results.append({
            "candidate_id": cid, "type": vtype, "title": raw["title"],
            "trades": artifact.trade_count,
            "base_pf": round(stress.base_profit_factor, 3),
            "stressed_pf": round(stress.stressed_profit_factor, 3),
            "stress_passed": stress.passed,
            "wf_passing": wf_passing, "wf_total": wf_total, "wf_passed": wf_passed,
            "oos_pf": round(artifact.out_of_sample_profit_factor, 3),
            "max_dd_pct": round(artifact.max_drawdown_pct, 2),
            "overall_pass": overall,
        })
        print(f"  >>> {cid}: [{'PASS' if overall else 'FAIL'}]")

    # Summary
    print("\n\n" + "=" * 130)
    print(f"{'ID':<16} {'Type':<6} {'Title':<42} {'Trades':>6} {'Base':>6} {'Stress':>7} {'S?':>4} {'WF':>5} {'OOS':>6} {'DD%':>6} {'OK':>5}")
    print("-" * 130)
    for r in results:
        s = "Y" if r["stress_passed"] else "N"
        w = f"{r['wf_passing']}/{r['wf_total']}"
        o = "PASS" if r["overall_pass"] else "FAIL"
        print(f"{r['candidate_id']:<16} {r['type']:<6} {r['title']:<42} {r['trades']:>6} {r['base_pf']:>6.3f} {r['stressed_pf']:>7.3f} {s:>4} {w:>5} {r['oos_pf']:>6.3f} {r['max_dd_pct']:>5.2f}% {o:>5}")
    print("=" * 130)

    passed = [r for r in results if r["overall_pass"]]
    print(f"\nDeep refinement: {len(passed)}/12 variants passed")

    # Rank by stressed PF
    if passed:
        print("\nRanked by stressed PF:")
        for rank, r in enumerate(sorted(passed, key=lambda x: x["stressed_pf"], reverse=True), 1):
            print(f"  #{rank} {r['candidate_id']} — stressed {r['stressed_pf']:.3f}, OOS {r['oos_pf']:.3f}, DD {r['max_dd_pct']:.2f}%, {r['trades']} trades")

    write_json(PROJECT_ROOT / "reports" / "phase3c_deep_refinement_results.json", results)
    print(f"\nSaved to: reports/phase3c_deep_refinement_results.json")


if __name__ == "__main__":
    main()
