"""Phase 2 — Refined batch v2: parameter-tuned candidates from batch 1 learnings.

Key refinements vs batch 1:
 - All candidates now include max_spread_pips filter (reject high-cost bars)
 - Scalping: higher signal thresholds, wider TP, add momentum/mean-location filters
 - Swing: wider trailing stops (12-15 pips), wider TP, relaxed entry to boost trade count
 - New entry styles tried: volatility_retest_breakout

Triage gates: >= 50 trades AND profit_factor >= 1.0
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_forex.backtesting.engine import run_backtest
from agentic_forex.config import load_settings
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.runtime import ReadPolicy
from agentic_forex.utils.io import write_json
from agentic_forex.workflows.contracts import CandidateDraft, StrategySpec

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _scalping_candidates() -> list[dict]:
    """5 refined EU-open scalping candidates — tighter selection, wider TP."""
    base_context = {
        "session_focus": "europe_open_breakout",
        "volatility_preference": "moderate_to_high",
        "directional_bias": "both",
        "execution_notes": ["Enter only during EU open 08-14 UTC. Spread-filtered."],
        "allowed_hours_utc": [8, 9, 10, 11, 12, 13],
    }
    return [
        # S1: volatility_breakout v2 — was best IS (PF 0.894) & OOS (1.094)
        #     Raise thresholds, wider TP, add spread filter + mean location
        {
            "candidate_id": "AF-CAND-0710",
            "family": "europe_open_impulse_retest_research",
            "title": "EU Vol Breakout Scalp v2",
            "thesis": "Volatility breakout with tighter selection and wider TP to overcome spread cost.",
            "source_citations": ["blank-slate-scalping-v2"],
            "strategy_hypothesis": "Higher momentum threshold + Z-score floor + mean location dramatically improves signal quality.",
            "market_context": base_context,
            "setup_summary": "High momentum + wide Z-score confirmation + mean location + low spread.",
            "entry_summary": "Enter breakout with full directional confirmation stack.",
            "exit_summary": "Fixed stop 7 pips, target 16 pips, 90-bar timeout.",
            "risk_summary": "R:R > 2:1, spread-filtered execution.",
            "entry_style": "volatility_breakout",
            "holding_bars": 90,
            "signal_threshold": 2.2,
            "stop_loss_pips": 7.0,
            "take_profit_pips": 16.0,
            "custom_filters": [
                {"name": "breakout_zscore_floor", "rule": "0.65"},
                {"name": "require_ret_5_alignment", "rule": "true"},
                {"name": "require_mean_location_alignment", "rule": "true"},
                {"name": "min_volatility_20", "rule": "0.00005"},
                {"name": "max_spread_pips", "rule": "2.5"},
            ],
        },
        # S2: volatility_breakout v3 — aggressive selectivity, very wide TP
        {
            "candidate_id": "AF-CAND-0711",
            "family": "europe_open_impulse_retest_research",
            "title": "EU Vol Breakout Scalp v3 Selective",
            "thesis": "Very selective volatility breakout — only strongest signals, widest TP for maximum R:R.",
            "source_citations": ["blank-slate-scalping-v2"],
            "strategy_hypothesis": "Extreme selectivity (top momentum + Z-score events) yields high enough win rate to justify wide TP.",
            "market_context": base_context,
            "setup_summary": "Very high momentum + strong Z-score + ret_5 alignment + tight spread.",
            "entry_summary": "Enter only strongest breakout signals.",
            "exit_summary": "Fixed stop 8 pips, target 20 pips, 120-bar timeout.",
            "risk_summary": "R:R 2.5:1, highly selective, low frequency.",
            "entry_style": "volatility_breakout",
            "holding_bars": 120,
            "signal_threshold": 2.5,
            "stop_loss_pips": 8.0,
            "take_profit_pips": 20.0,
            "custom_filters": [
                {"name": "breakout_zscore_floor", "rule": "0.75"},
                {"name": "require_ret_5_alignment", "rule": "true"},
                {"name": "require_mean_location_alignment", "rule": "true"},
                {"name": "min_volatility_20", "rule": "0.00006"},
                {"name": "max_spread_pips", "rule": "2.0"},
            ],
        },
        # S3: mean_reversion_pullback v2 — add momentum confirmation, wider TP
        #     Was PF 0.855, WR 43.5%. Add require_reversal_momentum.
        {
            "candidate_id": "AF-CAND-0712",
            "family": "europe_open_impulse_retest_research",
            "title": "EU Mean Reversion Scalp v2",
            "thesis": "Mean reversion with stricter confirmation: Z-score extreme + ret_1 reversal + momentum reversal + spread filter.",
            "source_citations": ["blank-slate-scalping-v2"],
            "strategy_hypothesis": "Adding momentum reversal confirmation eliminates false Z-score extremes that don't revert.",
            "market_context": base_context,
            "setup_summary": "Z-score extreme + ret_1 reversal + momentum reversal + low spread.",
            "entry_summary": "Fade extreme Z-score with full reversal confirmation.",
            "exit_summary": "Fixed stop 5 pips, target 10 pips, 45-bar timeout.",
            "risk_summary": "R:R 2:1 with dual reversal confirmation.",
            "entry_style": "mean_reversion_pullback",
            "holding_bars": 45,
            "signal_threshold": 1.6,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 10.0,
            "custom_filters": [
                {"name": "require_reversal_ret_1", "rule": "true"},
                {"name": "require_reversal_momentum", "rule": "true"},
                {"name": "max_spread_pips", "rule": "2.5"},
            ],
        },
        # S4: mean_reversion_pullback v3 — very selective, wider TP
        {
            "candidate_id": "AF-CAND-0713",
            "family": "europe_open_impulse_retest_research",
            "title": "EU Mean Reversion Scalp v3 Deep",
            "thesis": "Only fade very deep Z-score extremes with full confirmation. Higher threshold catches strong reversions.",
            "source_citations": ["blank-slate-scalping-v2"],
            "strategy_hypothesis": "Z-score threshold 2.0 only catches tradeable extremes where reversion is most likely.",
            "market_context": base_context,
            "setup_summary": "Very deep Z-score extreme + ret_1 + momentum reversal + tight spread.",
            "entry_summary": "Fade only deepest Z-score extremes.",
            "exit_summary": "Fixed stop 6 pips, target 12 pips, 50-bar timeout.",
            "risk_summary": "R:R 2:1, very selective.",
            "entry_style": "mean_reversion_pullback",
            "holding_bars": 50,
            "signal_threshold": 2.0,
            "stop_loss_pips": 6.0,
            "take_profit_pips": 12.0,
            "custom_filters": [
                {"name": "require_reversal_ret_1", "rule": "true"},
                {"name": "require_reversal_momentum", "rule": "true"},
                {"name": "max_spread_pips", "rule": "2.0"},
            ],
        },
        # S5: session_breakout v2 — raise all thresholds, wider TP, add filters
        #     Was PF 0.765. Needs significantly more selectivity.
        {
            "candidate_id": "AF-CAND-0714",
            "family": "europe_open_impulse_retest_research",
            "title": "EU Session Breakout Scalp v2",
            "thesis": "Raise all breakout filters to only capture strongest EU open directional momentum with mean location alignment.",
            "source_citations": ["blank-slate-scalping-v2"],
            "strategy_hypothesis": "Strong momentum + Z-score + ret_5 alignment + mean location together filter noise at EU open.",
            "market_context": base_context,
            "setup_summary": "High momentum + Z-score floor + ret_5 + mean location + low spread.",
            "entry_summary": "Enter strongest session breakout signals with triple confirmation.",
            "exit_summary": "Fixed stop 7 pips, target 15 pips, 75-bar timeout.",
            "risk_summary": "R:R > 2:1, multi-filter selection.",
            "entry_style": "session_breakout",
            "holding_bars": 75,
            "signal_threshold": 2.2,
            "stop_loss_pips": 7.0,
            "take_profit_pips": 15.0,
            "custom_filters": [
                {"name": "breakout_zscore_floor", "rule": "0.50"},
                {"name": "require_ret_5_alignment", "rule": "true"},
                {"name": "require_mean_location_alignment", "rule": "true"},
                {"name": "ret_5_floor", "rule": "0.00003"},
                {"name": "max_spread_pips", "rule": "2.5"},
            ],
        },
    ]


def _swing_candidates() -> list[dict]:
    """5 refined EU-open swing candidates — wider trailing, bigger TP."""
    base_context = {
        "session_focus": "europe_open_follow_through",
        "volatility_preference": "moderate_to_high",
        "directional_bias": "both",
        "execution_notes": ["Enter during EU session 08-14 UTC. Ride directional moves for hours."],
        "allowed_hours_utc": [8, 9, 10, 11, 12, 13],
    }
    return [
        # W1: pullback_continuation v2 — wider trailing (12), wider TP (35)
        #     Was 93 trades, PF 0.842, DD 2.32%. Relax slightly to boost count.
        {
            "candidate_id": "AF-CAND-0715",
            "family": "europe_open_early_follow_through_research",
            "title": "EU Pullback Swing v2 Wide Trail",
            "thesis": "Wider trailing stop gives winners room to breathe. Relaxed entry threshold for more opportunities.",
            "source_citations": ["blank-slate-swing-v2"],
            "strategy_hypothesis": "8-pip trailing was cutting winners in M1 noise. 12 pips lets genuine trends develop.",
            "market_context": base_context,
            "setup_summary": "Moderate trend + pullback to Z-score zone + ret_1 recovery + low spread.",
            "entry_summary": "Enter pullback continuation with recovery confirmation.",
            "exit_summary": "Trailing stop 12 pips, fixed SL 15 pips, TP 35 pips, 6-hour timeout.",
            "risk_summary": "Wide trailing captures extended moves. R:R > 2:1.",
            "entry_style": "pullback_continuation",
            "holding_bars": 360,
            "signal_threshold": 1.0,
            "stop_loss_pips": 15.0,
            "take_profit_pips": 35.0,
            "trailing_stop_enabled": True,
            "trailing_stop_pips": 12.0,
            "custom_filters": [
                {"name": "trend_ret_5_min", "rule": "0.00005"},
                {"name": "pullback_zscore_limit", "rule": "0.60"},
                {"name": "require_recovery_ret_1", "rule": "true"},
                {"name": "max_spread_pips", "rule": "2.5"},
            ],
        },
        # W2: pullback_continuation v3 — very wide trailing (15), mean alignment
        {
            "candidate_id": "AF-CAND-0716",
            "family": "europe_open_early_follow_through_research",
            "title": "EU Pullback Swing v3 Mean Aligned",
            "thesis": "Mean location alignment + very wide trailing lets only clean trend continuations through.",
            "source_citations": ["blank-slate-swing-v2"],
            "strategy_hypothesis": "Mean alignment + 15-pip trailing creates asymmetric payoff: small losses, occasional large wins.",
            "market_context": base_context,
            "setup_summary": "Trend + pullback + mean alignment + recovery + wide trailing.",
            "entry_summary": "Enter pullback with mean location confirmation.",
            "exit_summary": "Trailing stop 15 pips, fixed SL 18 pips, TP 45 pips, 8-hour timeout.",
            "risk_summary": "Very wide trailing. R:R > 2:1.",
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
        },
        # W3: volatility_retest_breakout — NEW entry style, sophisticated retest
        {
            "candidate_id": "AF-CAND-0717",
            "family": "europe_open_early_follow_through_research",
            "title": "EU Vol Retest Breakout Swing",
            "thesis": "Volatility + trend establish direction, then price retests into a Z-score zone. Entry on range_position confirmation.",
            "source_citations": ["blank-slate-swing-v2"],
            "strategy_hypothesis": "Post-breakout retests during EU session offer lower-risk entries for multi-hour continuation.",
            "market_context": base_context,
            "setup_summary": "Trend + volatility floor + retest into Z-score zone + range_position confirmation.",
            "entry_summary": "Enter volatility retest breakout after directional confirmation.",
            "exit_summary": "Trailing stop 12 pips, fixed SL 15 pips, TP 35 pips, 6-hour timeout.",
            "risk_summary": "Retest entry reduces adverse excursion. R:R > 2:1.",
            "entry_style": "volatility_retest_breakout",
            "holding_bars": 360,
            "signal_threshold": 1.5,
            "stop_loss_pips": 15.0,
            "take_profit_pips": 35.0,
            "trailing_stop_enabled": True,
            "trailing_stop_pips": 12.0,
            "custom_filters": [
                {"name": "breakout_zscore_floor", "rule": "0.55"},
                {"name": "trend_ret_5_min", "rule": "0.00008"},
                {"name": "retest_zscore_limit", "rule": "0.35"},
                {"name": "retest_range_position_floor", "rule": "0.55"},
                {"name": "min_volatility_20", "rule": "0.00004"},
                {"name": "require_recovery_ret_1", "rule": "true"},
                {"name": "max_spread_pips", "rule": "2.5"},
            ],
        },
        # W4: volatility_expansion v2 — raise thresholds, wider trailing
        #     Was PF 0.642. Needs much more selectivity.
        {
            "candidate_id": "AF-CAND-0718",
            "family": "europe_open_early_follow_through_research",
            "title": "EU Vol Expansion Swing v2",
            "thesis": "Highly selective volatility expansion — only strongest signals with higher vol floor and wider TP/trail.",
            "source_citations": ["blank-slate-swing-v2"],
            "strategy_hypothesis": "Very strong momentum + high volatility + Z-score confirmation reduces false starts.",
            "market_context": base_context,
            "setup_summary": "High momentum + high volatility + Z-score + ret_5 + ret_1 alignment.",
            "entry_summary": "Enter only strongest volatility expansion signals.",
            "exit_summary": "Trailing stop 12 pips, fixed SL 15 pips, TP 35 pips, 6-hour timeout.",
            "risk_summary": "Selective entry with wide trailing. R:R > 2:1.",
            "entry_style": "volatility_expansion",
            "holding_bars": 360,
            "signal_threshold": 2.0,
            "stop_loss_pips": 15.0,
            "take_profit_pips": 35.0,
            "trailing_stop_enabled": True,
            "trailing_stop_pips": 12.0,
            "custom_filters": [
                {"name": "min_volatility_20", "rule": "0.00005"},
                {"name": "ret_5_floor", "rule": "0.00008"},
                {"name": "breakout_zscore_floor", "rule": "0.80"},
                {"name": "max_spread_pips", "rule": "2.5"},
            ],
        },
        # W5: trend_pullback_retest v2 — tighter pullback zone, wider trailing
        #     Was PF 0.680, 293 trades.
        {
            "candidate_id": "AF-CAND-0719",
            "family": "europe_open_early_follow_through_research",
            "title": "EU Trend Retest Swing v2",
            "thesis": "Tighter pullback zone and higher trend requirement select only genuine trend retests.",
            "source_citations": ["blank-slate-swing-v2"],
            "strategy_hypothesis": "Stronger trend requirement (ret_5) + tighter pullback zone improves retest quality.",
            "market_context": base_context,
            "setup_summary": "Strong ret_5 trend + tight pullback zone + ret_1 confirmation + low spread.",
            "entry_summary": "Enter on strong-trend retest within tight Z-score range.",
            "exit_summary": "Trailing stop 12 pips, fixed SL 15 pips, TP 35 pips, 6-hour timeout.",
            "risk_summary": "Tight pullback zone filters noise. R:R > 2:1.",
            "entry_style": "trend_pullback_retest",
            "holding_bars": 360,
            "signal_threshold": 1.2,
            "stop_loss_pips": 15.0,
            "take_profit_pips": 35.0,
            "trailing_stop_enabled": True,
            "trailing_stop_pips": 12.0,
            "custom_filters": [
                {"name": "trend_ret_5_min", "rule": "0.00008"},
                {"name": "pullback_zscore_limit", "rule": "0.40"},
                {"name": "max_spread_pips", "rule": "2.5"},
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

        draft = CandidateDraft(**raw_spec)

        candidate_dir = settings.paths().reports_dir / cid
        candidate_dir.mkdir(parents=True, exist_ok=True)
        candidate_path = candidate_dir / "candidate.json"
        write_json(candidate_path, draft.model_dump(mode="json"))

        spec_payload = compile_strategy_spec_tool(
            payload=draft.model_dump(mode="json"),
            settings=settings,
            config={},
            read_policy=read_policy,
        )
        spec = StrategySpec.model_validate(spec_payload)
        artifact = run_backtest(spec, settings)

        passed = artifact.trade_count >= 50 and artifact.profit_factor >= 1.0
        results.append(
            {
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
            }
        )
        status = "PASS" if passed else "FAIL"
        print(
            f"   -> {artifact.trade_count} trades | PF {artifact.profit_factor:.3f} | WR {artifact.win_rate:.1%} | [{status}]"
        )

    # Summary table
    print("\n" + "=" * 100)
    print(
        f"{'ID':<16} {'Type':<7} {'Style':<28} {'Trades':>6} {'PF':>7} {'WR':>6} {'Exp':>8} {'DD%':>6} {'OOS_PF':>7} {'Trail':>5} {'Gate':>6}"
    )
    print("-" * 100)
    for r in results:
        gate = "PASS" if r["passed_triage"] else "FAIL"
        print(
            f"{r['candidate_id']:<16} {r['type']:<7} {r['entry_style']:<28} {r['trades']:>6} {r['pf']:>7.3f} {r['win_rate']:>5.1%} {r['expectancy']:>8.3f} {r['max_dd']:>5.2f}% {r['oos_pf']:>7.3f} {r['trailing']:>5} {gate:>6}"
        )
    print("=" * 100)

    passed_count = sum(1 for r in results if r["passed_triage"])
    print(f"\nTriage: {passed_count}/10 candidates passed (>= 50 trades AND PF >= 1.0)")

    triage_path = PROJECT_ROOT / "reports" / "phase2_triage_v2_results.json"
    write_json(triage_path, results)
    print(f"Full results saved to: {triage_path}")


if __name__ == "__main__":
    main()
