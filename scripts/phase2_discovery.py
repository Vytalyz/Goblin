"""Phase 2: Blank-slate strategy discovery — generate, spec, backtest, triage.

This script creates 10 CandidateDraft specs (5 scalping, 5 swing), compiles
each into a StrategySpec, runs a backtest, and prints a triage table.

Triage gates: >= 50 trades AND profit_factor >= 1.0
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_forex.backtesting.engine import run_backtest
from agentic_forex.config import load_settings
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.runtime import ReadPolicy
from agentic_forex.utils.io import write_json
from agentic_forex.workflows.contracts import CandidateDraft, MarketContextSummary, StrategySpec


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _scalping_candidates() -> list[dict]:
    """5 EU-open scalping candidates — short holds, tight SL/TP, fixed exits."""
    base_context = {
        "session_focus": "europe_open_breakout",
        "volatility_preference": "moderate_to_high",
        "directional_bias": "both",
        "execution_notes": ["Enter only during EU open 08-14 UTC. Tight spread filter."],
        "allowed_hours_utc": [8, 9, 10, 11, 12, 13],
    }
    return [
        # S1: Session breakout — classic directional momentum at EU open
        {
            "candidate_id": "AF-CAND-0700",
            "family": "europe_open_impulse_retest_research",
            "title": "EU Open Session Breakout Scalp",
            "thesis": "EU session open generates directional momentum as London liquidity enters. Breakout on momentum confirmation with trend alignment.",
            "source_citations": ["blank-slate-scalping-v1"],
            "strategy_hypothesis": "Opening momentum impulse at London open creates short-lived directional edge when momentum and price location align.",
            "market_context": base_context,
            "setup_summary": "Wait for EU open momentum spike above threshold with ret_5 trend alignment.",
            "entry_summary": "Enter on momentum_12 breakout above threshold with mean location confirmation.",
            "exit_summary": "Fixed stop, target, or timeout.",
            "risk_summary": "Tight stop 6 pips, target 10 pips, max 45 bar hold.",
            "entry_style": "session_breakout",
            "holding_bars": 45,
            "signal_threshold": 1.5,
            "stop_loss_pips": 6.0,
            "take_profit_pips": 10.0,
            "custom_filters": [
                {"name": "breakout_zscore_floor", "rule": "0.3"},
                {"name": "require_ret_5_alignment", "rule": "true"},
            ],
        },
        # S2: Mean reversion pullback — fade Z-score extremes during EU session
        {
            "candidate_id": "AF-CAND-0701",
            "family": "europe_open_impulse_retest_research",
            "title": "EU Open Mean Reversion Scalp",
            "thesis": "Intraday Z-score extremes during EU session revert as institutional flow absorbs. Fade with ret_1 reversal confirmation.",
            "source_citations": ["blank-slate-scalping-v1"],
            "strategy_hypothesis": "Z-score extremes during high-liquidity EU hours revert faster than during low-liquidity periods.",
            "market_context": base_context,
            "setup_summary": "Z-score extends beyond threshold during EU session; wait for ret_1 reversal.",
            "entry_summary": "Enter mean reversion when Z-score extreme + ret_1 reversal seen.",
            "exit_summary": "Fixed stop, target, or timeout.",
            "risk_summary": "Stop 5 pips, target 7 pips, max 30 bar hold.",
            "entry_style": "mean_reversion_pullback",
            "holding_bars": 30,
            "signal_threshold": 1.2,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.0,
            "custom_filters": [
                {"name": "require_reversal_ret_1", "rule": "true"},
            ],
        },
        # S3: Volatility breakout — breakout when volatility rises
        {
            "candidate_id": "AF-CAND-0702",
            "family": "europe_open_impulse_retest_research",
            "title": "EU Open Volatility Breakout Scalp",
            "thesis": "Rising volatility at EU open signals directional breakout. Enter on momentum + Z-score confirmation above volatility floor.",
            "source_citations": ["blank-slate-scalping-v1"],
            "strategy_hypothesis": "Volatility expansion at London open precedes directional follow-through when Z-score confirms momentum direction.",
            "market_context": base_context,
            "setup_summary": "Volatility_20 above floor + momentum above threshold + Z-score confirms direction.",
            "entry_summary": "Enter breakout when momentum and volatility conditions align.",
            "exit_summary": "Fixed stop, target, or timeout.",
            "risk_summary": "Stop 7 pips, target 12 pips, max 60 bar hold.",
            "entry_style": "volatility_breakout",
            "holding_bars": 60,
            "signal_threshold": 1.8,
            "stop_loss_pips": 7.0,
            "take_profit_pips": 12.0,
            "custom_filters": [
                {"name": "breakout_zscore_floor", "rule": "0.45"},
                {"name": "require_ret_5_alignment", "rule": "true"},
                {"name": "min_volatility_20", "rule": "0.00004"},
            ],
        },
        # S4: Session extreme reversion — fade large moves
        {
            "candidate_id": "AF-CAND-0703",
            "family": "europe_open_impulse_retest_research",
            "title": "EU Session Extreme Reversion Scalp",
            "thesis": "Large intrabar moves during EU session tend to partially revert. Fade extreme Z-score with ret_1 reversal.",
            "source_citations": ["blank-slate-scalping-v1"],
            "strategy_hypothesis": "Extreme Z-scores during EU hours revert when ret_1 confirms early reversal and momentum not excessive.",
            "market_context": base_context,
            "setup_summary": "Extreme Z-score + ret_1 reversal + momentum capped.",
            "entry_summary": "Fade extreme with reversal confirmation.",
            "exit_summary": "Fixed stop, target, or timeout.",
            "risk_summary": "Stop 5 pips, target 6 pips, max 25 bar hold.",
            "entry_style": "session_extreme_reversion",
            "holding_bars": 25,
            "signal_threshold": 0.85,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 6.0,
            "custom_filters": [
                {"name": "fade_ret_5_floor", "rule": "0.00003"},
                {"name": "fade_momentum_ceiling", "rule": "4.5"},
            ],
        },
        # S5: Compression breakout — breakout from tight range
        {
            "candidate_id": "AF-CAND-0704",
            "family": "europe_open_impulse_retest_research",
            "title": "EU Open Compression Breakout Scalp",
            "thesis": "Tight pre-open range compresses price. EU open liquidity breaks the compression with directional momentum.",
            "source_citations": ["blank-slate-scalping-v1"],
            "strategy_hypothesis": "Range compression before EU open creates predictable breakout opportunities when momentum confirms.",
            "market_context": base_context,
            "setup_summary": "Range compressed (tight range_width_10_pips) + momentum breakout + Z-score direction.",
            "entry_summary": "Enter breakout from compression zone.",
            "exit_summary": "Fixed stop, target, or timeout.",
            "risk_summary": "Stop 6 pips, target 9 pips, max 40 bar hold.",
            "entry_style": "compression_breakout",
            "holding_bars": 40,
            "signal_threshold": 1.3,
            "stop_loss_pips": 6.0,
            "take_profit_pips": 9.0,
            "custom_filters": [
                {"name": "max_range_width_10_pips", "rule": "7.0"},
            ],
        },
    ]


def _swing_candidates() -> list[dict]:
    """5 EU-open swing candidates — longer holds, trailing stops, wider SL."""
    base_context = {
        "session_focus": "europe_open_follow_through",
        "volatility_preference": "moderate_to_high",
        "directional_bias": "both",
        "execution_notes": ["Enter during EU session 08-14 UTC. Ride directional moves for hours."],
        "allowed_hours_utc": [8, 9, 10, 11, 12, 13],
    }
    return [
        # W1: Pullback continuation — enter on pullback in established trend
        {
            "candidate_id": "AF-CAND-0705",
            "family": "europe_open_early_follow_through_research",
            "title": "EU Pullback Continuation Swing",
            "thesis": "Intraday trends established at EU open offer pullback entry points for multi-hour continuation. Trailing stop captures extended moves.",
            "source_citations": ["blank-slate-swing-v1"],
            "strategy_hypothesis": "Trend direction established by ret_5 and momentum persists for hours when entered on pullback.",
            "market_context": base_context,
            "setup_summary": "Ret_5 confirms trend + Z-score pulls back toward zero + recovery ret_1.",
            "entry_summary": "Enter trend continuation after pullback with recovery confirmation.",
            "exit_summary": "Trailing stop 8 pips, fixed SL 12 pips, TP 25 pips, or 4-hour timeout.",
            "risk_summary": "Trailing captures extended moves. Fixed SL is absolute floor.",
            "entry_style": "pullback_continuation",
            "holding_bars": 240,
            "signal_threshold": 1.2,
            "stop_loss_pips": 12.0,
            "take_profit_pips": 25.0,
            "trailing_stop_enabled": True,
            "trailing_stop_pips": 8.0,
            "custom_filters": [
                {"name": "trend_ret_5_min", "rule": "0.00006"},
                {"name": "pullback_zscore_limit", "rule": "0.50"},
                {"name": "require_recovery_ret_1", "rule": "true"},
            ],
        },
        # W2: Trend pullback retest — simpler trend entry
        {
            "candidate_id": "AF-CAND-0706",
            "family": "europe_open_early_follow_through_research",
            "title": "EU Trend Retest Swing",
            "thesis": "Simple trend-following entry: enter on ret_5 trend + ret_1 confirmation + Z-score pullback zone.",
            "source_citations": ["blank-slate-swing-v1"],
            "strategy_hypothesis": "Trend retests during EU hours follow through for several hours when ret_1 confirms direction.",
            "market_context": base_context,
            "setup_summary": "Ret_5 trend + ret_1 confirmation + Z-score in pullback range.",
            "entry_summary": "Enter on straightforward trend retest with directional confirmation.",
            "exit_summary": "Trailing stop 10 pips, fixed SL 15 pips, TP 30 pips, or 6-hour timeout.",
            "risk_summary": "Wider trailing gives room. Fixed SL capped at 15.",
            "entry_style": "trend_pullback_retest",
            "holding_bars": 360,
            "signal_threshold": 1.0,
            "stop_loss_pips": 15.0,
            "take_profit_pips": 30.0,
            "trailing_stop_enabled": True,
            "trailing_stop_pips": 10.0,
            "custom_filters": [
                {"name": "trend_ret_5_min", "rule": "0.00005"},
                {"name": "pullback_zscore_limit", "rule": "0.60"},
            ],
        },
        # W3: Session momentum band — ride established momentum
        {
            "candidate_id": "AF-CAND-0707",
            "family": "europe_open_early_follow_through_research",
            "title": "EU Momentum Band Swing",
            "thesis": "Sustained momentum during EU session stays in a Z-score band. Enter within the band and ride for hours with trailing stop.",
            "source_citations": ["blank-slate-swing-v1"],
            "strategy_hypothesis": "Momentum persistence within a Z-score continuation band signals multi-hour directional follow-through.",
            "market_context": base_context,
            "setup_summary": "Momentum above floor + Z-score in continuation band + range position confirms direction.",
            "entry_summary": "Enter momentum band continuation for swing ride.",
            "exit_summary": "Trailing stop 9 pips, fixed SL 12 pips, TP 22 pips, or 5-hour timeout.",
            "risk_summary": "Medium trailing, capped SL at 12.",
            "entry_style": "session_momentum_band",
            "holding_bars": 300,
            "signal_threshold": 1.0,
            "stop_loss_pips": 12.0,
            "take_profit_pips": 22.0,
            "trailing_stop_enabled": True,
            "trailing_stop_pips": 9.0,
            "custom_filters": [
                {"name": "trend_ret_5_min", "rule": "0.00006"},
                {"name": "continuation_zscore_floor", "rule": "0.15"},
                {"name": "continuation_zscore_ceiling", "rule": "0.90"},
                {"name": "continuation_range_position_floor", "rule": "0.58"},
                {"name": "min_volatility_20", "rule": "0.00004"},
            ],
        },
        # W4: Volatility expansion — enter on vol expansion for multi-hour follow-through
        {
            "candidate_id": "AF-CAND-0708",
            "family": "europe_open_early_follow_through_research",
            "title": "EU Volatility Expansion Swing",
            "thesis": "Volatility expansion at EU open indicates regime shift. Enter directionally for multi-hour follow-through with trailing stop.",
            "source_citations": ["blank-slate-swing-v1"],
            "strategy_hypothesis": "Volatility expansion during EU session persists directionally for hours when momentum and returns confirm.",
            "market_context": base_context,
            "setup_summary": "Volatility above floor + momentum + Z-score confirms + ret_1/ret_5 alignment.",
            "entry_summary": "Enter on volatility expansion with full directional confirmation.",
            "exit_summary": "Trailing stop 10 pips, fixed SL 14 pips, TP 28 pips, or 4-hour timeout.",
            "risk_summary": "Trailing captures extended vol moves. Fixed SL at 14.",
            "entry_style": "volatility_expansion",
            "holding_bars": 240,
            "signal_threshold": 1.5,
            "stop_loss_pips": 14.0,
            "take_profit_pips": 28.0,
            "trailing_stop_enabled": True,
            "trailing_stop_pips": 10.0,
            "custom_filters": [
                {"name": "min_volatility_20", "rule": "0.00004"},
                {"name": "ret_5_floor", "rule": "0.00005"},
                {"name": "breakout_zscore_floor", "rule": "0.55"},
            ],
        },
        # W5: Pullback continuation — variant with tighter entry, longer hold
        {
            "candidate_id": "AF-CAND-0709",
            "family": "europe_open_early_follow_through_research",
            "title": "EU Tight Pullback Long Swing",
            "thesis": "Tighter pullback entry zone during EU session captures cleaner continuation signals for extended rides.",
            "source_citations": ["blank-slate-swing-v1"],
            "strategy_hypothesis": "Narrower pullback zone + mean location alignment filters noise; surviving signals carry further.",
            "market_context": base_context,
            "setup_summary": "Tight Z-score pullback zone + mean location alignment + recovery ret_1.",
            "entry_summary": "Enter tight pullback continuation with mean alignment filter.",
            "exit_summary": "Trailing stop 7 pips, fixed SL 10 pips, TP 20 pips, or 8-hour timeout.",
            "risk_summary": "Tighter trail for clean entries. SL at 10.",
            "entry_style": "pullback_continuation",
            "holding_bars": 480,
            "signal_threshold": 1.0,
            "stop_loss_pips": 10.0,
            "take_profit_pips": 20.0,
            "trailing_stop_enabled": True,
            "trailing_stop_pips": 7.0,
            "custom_filters": [
                {"name": "trend_ret_5_min", "rule": "0.00008"},
                {"name": "pullback_zscore_limit", "rule": "0.35"},
                {"name": "require_recovery_ret_1", "rule": "true"},
                {"name": "require_mean_location_alignment", "rule": "true"},
            ],
        },
    ]


def main():
    settings = load_settings(project_root=PROJECT_ROOT)
    read_policy = ReadPolicy(project_root=PROJECT_ROOT)

    all_candidates = _scalping_candidates() + _swing_candidates()
    results = []

    for i, raw_spec in enumerate(all_candidates, 1):
        cid = raw_spec["candidate_id"]
        style_label = "scalp" if i <= 5 else "swing"
        print(f"\n[{i}/10] {cid} ({style_label}) — {raw_spec['entry_style']} ...", flush=True)

        # Validate as CandidateDraft
        draft = CandidateDraft(**raw_spec)

        # Save candidate JSON
        candidate_dir = settings.paths().reports_dir / cid
        candidate_dir.mkdir(parents=True, exist_ok=True)
        candidate_path = candidate_dir / "candidate.json"
        write_json(candidate_path, draft.model_dump(mode="json"))

        # Compile to StrategySpec (deterministic)
        spec_payload = compile_strategy_spec_tool(
            payload=draft.model_dump(mode="json"),
            settings=settings,
            config={},
            read_policy=read_policy,
        )
        spec = StrategySpec.model_validate(spec_payload)

        # Backtest
        artifact = run_backtest(spec, settings)

        passed = artifact.trade_count >= 50 and artifact.profit_factor >= 1.0
        results.append({
            "candidate_id": cid,
            "type": style_label,
            "entry_style": raw_spec["entry_style"],
            "trades": artifact.trade_count,
            "pf": round(artifact.profit_factor, 3),
            "win_rate": round(artifact.win_rate, 3),
            "expectancy": round(artifact.expectancy_pips, 3),
            "max_dd": round(artifact.max_drawdown_pct, 2),
            "oos_pf": round(artifact.out_of_sample_profit_factor, 3),
            "trailing": "yes" if raw_spec.get("trailing_stop_enabled") else "no",
            "passed_triage": passed,
        })
        status = "PASS" if passed else "FAIL"
        print(f"   -> {artifact.trade_count} trades | PF {artifact.profit_factor:.3f} | WR {artifact.win_rate:.1%} | [{status}]")

    # Summary table
    print("\n" + "=" * 100)
    print(f"{'ID':<16} {'Type':<7} {'Style':<28} {'Trades':>6} {'PF':>7} {'WR':>6} {'Exp':>8} {'DD%':>6} {'OOS_PF':>7} {'Trail':>5} {'Gate':>6}")
    print("-" * 100)
    for r in results:
        gate = "PASS" if r["passed_triage"] else "FAIL"
        print(f"{r['candidate_id']:<16} {r['type']:<7} {r['entry_style']:<28} {r['trades']:>6} {r['pf']:>7.3f} {r['win_rate']:>5.1%} {r['expectancy']:>8.3f} {r['max_dd']:>5.2f}% {r['oos_pf']:>7.3f} {r['trailing']:>5} {gate:>6}")
    print("=" * 100)

    passed_count = sum(1 for r in results if r["passed_triage"])
    print(f"\nTriage: {passed_count}/10 candidates passed (>= 50 trades AND PF >= 1.0)")

    # Save full triage report
    triage_path = PROJECT_ROOT / "reports" / "phase2_triage_results.json"
    write_json(triage_path, results)
    print(f"Full results saved to: {triage_path}")


if __name__ == "__main__":
    main()
