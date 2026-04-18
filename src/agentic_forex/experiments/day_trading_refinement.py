from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agentic_forex.config import Settings
from agentic_forex.experiments.models import DayTradingRefinementReport, DayTradingRefinementVariant
from agentic_forex.experiments.service import compare_experiments
from agentic_forex.llm import MockLLMClient
from agentic_forex.nodes import build_tool_registry
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.runtime import ReadPolicy, WorkflowEngine
from agentic_forex.utils.ids import next_candidate_id
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows import WorkflowRepository
from agentic_forex.workflows.contracts import CandidateDraft, FilterRule, ReviewPacket, StrategySpec


def refine_day_trading_target(
    settings: Settings,
    *,
    target_candidate_id: str,
    family_override: str | None = None,
) -> DayTradingRefinementReport:
    target_candidate = _load_candidate(settings, target_candidate_id)
    target_spec = _load_spec(settings, target_candidate_id)
    templates = _templates_for_variant(
        target_spec.entry_style,
        variant_name=target_spec.variant_name,
        family=target_candidate.family,
    )

    review_engine = WorkflowEngine(
        settings=settings,
        llm_client=MockLLMClient(),
        tool_registry=build_tool_registry(),
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    review_workflow = WorkflowRepository(settings.paths()).load(settings.workflows.review_workflow_id)

    variants: list[DayTradingRefinementVariant] = []
    comparison_ids = [target_candidate_id]
    challenger_family = family_override
    for template in templates:
        candidate = _variant_candidate(
            target_candidate,
            settings,
            template,
            family_override=family_override,
        )
        challenger_family = challenger_family or candidate.family
        candidate_path = settings.paths().reports_dir / candidate.candidate_id / "candidate.json"
        write_json(candidate_path, candidate.model_dump(mode="json"))
        spec_payload = compile_strategy_spec_tool(
            payload=candidate.model_dump(mode="json"),
            settings=settings,
            config={},
            read_policy=ReadPolicy(project_root=settings.project_root),
        )
        spec = StrategySpec.model_validate(spec_payload)
        spec = _apply_day_trading_refinement(spec, template, resolved_family=candidate.family)
        spec_path = settings.paths().reports_dir / candidate.candidate_id / "strategy_spec.json"
        write_json(spec_path, spec.model_dump(mode="json"))

        review_trace = review_engine.run(review_workflow, spec.model_dump(mode="json"))
        if review_trace.output_payload is None:
            error = next((item.error for item in review_trace.node_traces if item.error), "Review workflow failed.")
            raise RuntimeError(error)
        review_packet = ReviewPacket.model_validate(review_trace.output_payload)
        metrics = review_packet.metrics
        trade_count = int(metrics["trade_count"])
        oos_pf = float(metrics["out_of_sample_profit_factor"])
        stressed_pf = float(metrics["stress_scenarios"][-1]["profit_factor"])
        expectancy = float(metrics["expectancy_pips"])
        drawdown = float(metrics["max_drawdown_pct"])
        stress_passed = bool(metrics["stress_passed"])
        meets_requirement_subset = bool(
            trade_count >= spec.validation_profile.minimum_test_trade_count
            and oos_pf >= spec.validation_profile.out_of_sample_profit_factor_floor
            and expectancy > spec.validation_profile.expectancy_floor
            and stress_passed
        )
        refinement_score = _refinement_score(
            trade_count=trade_count,
            oos_profit_factor=oos_pf,
            stressed_profit_factor=stressed_pf,
            expectancy_pips=expectancy,
            max_drawdown_pct=drawdown,
            stress_passed=stress_passed,
            meets_requirement_subset=meets_requirement_subset,
        )
        variants.append(
            DayTradingRefinementVariant(
                candidate_id=candidate.candidate_id,
                variant_label=template["variant_label"],
                title=candidate.title,
                family=candidate.family,
                trade_count=trade_count,
                out_of_sample_profit_factor=oos_pf,
                stressed_profit_factor=stressed_pf,
                stress_passed=stress_passed,
                expectancy_pips=expectancy,
                max_drawdown_pct=drawdown,
                meets_requirement_subset=meets_requirement_subset,
                refinement_score=round(refinement_score, 6),
                candidate_path=candidate_path,
                spec_path=spec_path,
                review_packet_path=settings.paths().reports_dir / candidate.candidate_id / "review_packet.json",
            )
        )
        comparison_ids.append(candidate.candidate_id)

    ordered = sorted(variants, key=lambda item: item.refinement_score, reverse=True)
    comparison = compare_experiments(settings, candidate_ids=comparison_ids)
    report_path = _report_path(settings, target_candidate_id)
    report = DayTradingRefinementReport(
        target_candidate_id=target_candidate_id,
        target_family=target_candidate.family,
        challenger_family=challenger_family,
        objective=_objective_for_entry_style(target_spec.entry_style),
        comparison_report_path=comparison.report_path,
        report_path=report_path,
        recommended_candidate_id=ordered[0].candidate_id if ordered else None,
        variants=ordered,
    )
    write_json(report_path, report.model_dump(mode="json"))
    return report


def _load_candidate(settings: Settings, candidate_id: str) -> CandidateDraft:
    path = settings.paths().reports_dir / candidate_id / "candidate.json"
    if not path.exists():
        raise FileNotFoundError(f"Candidate draft not found for {candidate_id}: {path}")
    return CandidateDraft.model_validate(read_json(path))


def _load_spec(settings: Settings, candidate_id: str) -> StrategySpec:
    path = settings.paths().reports_dir / candidate_id / "strategy_spec.json"
    if not path.exists():
        raise FileNotFoundError(f"Strategy spec not found for {candidate_id}: {path}")
    return StrategySpec.model_validate(read_json(path))


def _variant_candidate(
    target: CandidateDraft,
    settings: Settings,
    template: dict[str, object],
    *,
    family_override: str | None,
) -> CandidateDraft:
    candidate_family = str(family_override or template.get("family") or target.family)
    new_quality_flags = list(target.quality_flags)
    for flag in ("bounded_refinement", "gap_blank_slate_candidate"):
        if flag not in new_quality_flags:
            new_quality_flags.append(flag)
    return target.model_copy(
        update={
            "candidate_id": next_candidate_id(settings),
            "family": candidate_family,
            "title": template["title"],
            "thesis": f"{template['thesis']} Derived from {target.candidate_id} under the bounded day-trading refinement lane.",
            "setup_summary": template["setup_summary"],
            "entry_summary": template["entry_summary"],
            "exit_summary": template["exit_summary"],
            "risk_summary": template["risk_summary"],
            "market_context": target.market_context.model_copy(
                update={
                    "session_focus": template["session_focus"],
                    "volatility_preference": template["volatility_preference"],
                    "allowed_hours_utc": template["allowed_hours_utc"],
                    "execution_notes": list(target.market_context.execution_notes)
                    + [f"Refinement variant: {template['variant_label']}."],
                }
            ),
            "notes": list(target.notes) + [f"Bounded refinement candidate derived from {target.candidate_id}."],
            "quality_flags": new_quality_flags,
            "custom_filters": [{"name": name, "rule": rule} for name, rule in template["custom_filters"].items()],
            "enable_news_blackout": bool(template["enable_news_blackout"]),
            "entry_style": target.entry_style,
            "holding_bars": int(template["holding_bars"]),
            "signal_threshold": float(template["signal_threshold"]),
            "stop_loss_pips": float(template["stop_loss_pips"]),
            "take_profit_pips": float(template["take_profit_pips"]),
        }
    )


def _apply_day_trading_refinement(
    spec: StrategySpec,
    template: dict[str, object],
    *,
    resolved_family: str,
) -> StrategySpec:
    rules = {item.name: item.rule for item in spec.filters}
    rules.update(template["custom_filters"])
    session_policy = spec.session_policy.model_copy(update={"allowed_hours_utc": template["allowed_hours_utc"]})
    risk_policy = spec.risk_policy.model_copy(
        update={
            "stop_loss_pips": template["stop_loss_pips"],
            "take_profit_pips": template["take_profit_pips"],
        }
    )
    news_policy = spec.news_policy.model_copy(update={"enabled": bool(template["enable_news_blackout"])})
    risk_envelope = spec.risk_envelope.model_copy(
        update={
            "session_boundaries_utc": template["allowed_hours_utc"],
            "news_event_policy": "calendar_blackout"
            if template["enable_news_blackout"]
            else spec.risk_envelope.news_event_policy,
        }
    )
    updated = spec.model_copy(
        update={
            "family": resolved_family,
            "variant_name": template["variant_label"],
            "session_policy": session_policy,
            "filters": [FilterRule(name=name, rule=rule) for name, rule in rules.items()],
            "risk_policy": risk_policy,
            "news_policy": news_policy,
            "risk_envelope": risk_envelope,
            "holding_bars": int(template["holding_bars"]),
            "signal_threshold": float(template["signal_threshold"]),
            "stop_loss_pips": float(template["stop_loss_pips"]),
            "take_profit_pips": float(template["take_profit_pips"]),
            "entry_logic": [
                template["entry_summary"],
                f"Signal threshold {template['signal_threshold']}",
            ],
            "exit_logic": [
                template["exit_summary"],
                f"Time exit after {template['holding_bars']} bars",
            ],
            "notes": list(spec.notes) + [f"Refinement label: {template['variant_label']}."],
        }
    )
    return StrategySpec.model_validate(updated.model_dump(mode="json"))


def _templates_for_entry_style(entry_style: str) -> list[dict[str, object]]:
    return _templates_for_variant(entry_style, variant_name=None, family=None)


def _templates_for_variant(
    entry_style: str,
    *,
    variant_name: str | None,
    family: str | None,
) -> list[dict[str, object]]:
    normalized = entry_style.strip().lower()
    if normalized == "compression_reversion":
        return _compression_reversion_templates()
    if normalized == "compression_breakout":
        return _compression_breakout_templates()
    if normalized == "balance_area_breakout":
        if (variant_name or "").strip().lower() == "high_vol_core_release":
            return _balance_area_breakout_follow_on_templates()
        return _balance_area_breakout_templates()
    if normalized == "failed_break_fade":
        if (variant_name or "").strip().lower() == "open_release_cost_guard":
            return _failed_break_fade_follow_on_templates()
        return _failed_break_fade_templates()
    if normalized == "session_breakout":
        return _session_breakout_templates()
    if normalized == "range_reclaim":
        if (variant_name or "").strip().lower() == "early_london_buffered":
            return _range_reclaim_follow_on_templates()
        return _range_reclaim_templates()
    if normalized == "drift_reclaim":
        if (variant_name or "").strip().lower() == "daytype_spread_guard_density":
            return _drift_reclaim_daytype_density_follow_on_templates()
        if (variant_name or "").strip().lower() == "daytype_spread_guard":
            return _drift_reclaim_daytype_follow_on_templates()
        if (variant_name or "").strip().lower() in {"bridge_density_extension", "europe_handoff_reclaim"}:
            return _drift_reclaim_follow_on_templates()
        return _drift_reclaim_templates()
    if normalized == "pullback_continuation":
        if (family or "").strip().lower() == "europe_open_high_vol_pullback_regime_research":
            return _pullback_continuation_regime_templates()
        if (variant_name or "").strip().lower() == "balanced_pre_overlap_pullback":
            return _pullback_continuation_follow_on_templates()
        if (variant_name or "").strip().lower() == "late_window_high_vol_pullback":
            return _pullback_continuation_density_templates()
        return _pullback_continuation_templates()
    if normalized == "volatility_retest_breakout":
        return _volatility_retest_breakout_templates()
    if normalized == "trend_retest":
        return _trend_retest_templates()
    raise ValueError(f"Day-trading refinement does not support entry_style={entry_style!r}.")


def _objective_for_entry_style(entry_style: str) -> str:
    normalized = entry_style.strip().lower()
    if normalized == "compression_reversion":
        return (
            "Concentrate the Europe compression-reversion thesis on the cleanest compressed extremes, tighten reclaim "
            "geometry and cost discipline, and keep the family orthogonal to reclaim and breakout search."
        )
    if normalized == "compression_breakout":
        return (
            "Narrow the Europe-session compression breakout into a smaller release window with tighter quality gates, "
            "news blackout discipline, and lower time-in-trade so expectancy and stressed robustness improve without "
            "collapsing trade count."
        )
    if normalized == "balance_area_breakout":
        return (
            "Concentrate the Europe-open balance breakout on the cleanest release pockets, preserve only the range "
            "exits that still have directional follow-through, and tighten execution discipline so the breakout can "
            "stay selective without collapsing below the validation trade floor."
        )
    if normalized == "failed_break_fade":
        return (
            "Concentrate the Europe-open failed-break fade on the cleaner medium-volatility reversal pockets, tighten "
            "cost discipline, and remove the weakest context slice so expectancy can turn positive without losing the "
            "trade count needed for validation."
        )
    if normalized == "session_breakout":
        return (
            "Concentrate the Europe-open breakout on the cleaner release windows, keep the directional follow-through "
            "that survives costs, and suppress the weakest mean-reversion context so stressed robustness improves "
            "without losing the trade count needed for validation."
        )
    if normalized == "range_reclaim":
        return (
            "Concentrate the London reclaim thesis on the early London window, suppress the weakest trend-context slice, "
            "and shorten hold time so the reclaim edge survives costs with less regime bleed."
        )
    if normalized == "drift_reclaim":
        return (
            "Concentrate the Asia-to-Europe drift-reclaim thesis on the high-volatility transition state, widen only where "
            "density can improve without losing stress survival, and test whether the weak trend-context slice should stay blocked."
        )
    if normalized == "trend_retest":
        return (
            "Concentrate the Europe-open retest-continuation thesis on the cleanest retest pockets, suppress mean-reversion "
            "bleed, and shorten hold time so continuation expectancy improves without reopening breakout chase behavior."
        )
    if normalized == "volatility_retest_breakout":
        return (
            "Concentrate the Europe-open retest-breakout thesis on the cleanest continuation retests, widen only enough to "
            "restore usable trade density, and keep the family distinct from strict breakout chase and reclaim reversal logic."
        )
    if normalized == "pullback_continuation":
        return (
            "Concentrate the Europe-open pullback-continuation thesis on the cleanest shallow pullbacks, restore usable "
            "trade density, and keep the family between sparse strict retests and overbroad breakout-release behavior."
        )
    return "Run bounded day-trading refinement without broadening the hypothesis class."


def _compression_reversion_templates() -> list[dict[str, object]]:
    challenger_family = "europe_open_compression_reversion_research"
    return [
        {
            "variant_label": "core_release_reversion",
            "title": "Core Release Compression Reversion",
            "family": challenger_family,
            "thesis": "Trade only the core Europe compression extremes where reversal pressure appears quickly enough to outrun spread and slippage.",
            "session_focus": "europe_core_compression_reversion",
            "volatility_preference": "low_to_moderate",
            "allowed_hours_utc": [8, 9],
            "holding_bars": 28,
            "signal_threshold": 1.08,
            "stop_loss_pips": 5.4,
            "take_profit_pips": 7.2,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "max_range_width_10_pips": "6.8",
                "reclaim_range_position_floor": "0.22",
                "reclaim_range_position_ceiling": "0.40",
                "reclaim_momentum_ceiling": "2.8",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Restrict the family to the tightest Europe-core compression extremes where a reversal starts quickly enough to remain a true snapback rather than a slow drift.",
            "entry_summary": "Enter on a core compression reversion when the local range remains very tight, z-score extension is extreme, reversal confirmation is present, and price has reclaimed only into the tighter recovery band.",
            "exit_summary": "Exit via fixed stop, fixed target, or 28-bar timeout.",
            "risk_summary": "Core Europe compression reversion tuned to protect costs and keep the family distinct from failed-break and range-reclaim logic.",
        },
        {
            "variant_label": "open_to_release_reversion",
            "title": "Open-To-Release Compression Reversion",
            "family": challenger_family,
            "thesis": "Keep the opening and release pockets together if the compressed-extreme snapback is stable enough to support a broader non-overlap sample.",
            "session_focus": "europe_open_to_release_compression_reversion",
            "volatility_preference": "low_to_moderate",
            "allowed_hours_utc": [7, 8, 9],
            "holding_bars": 30,
            "signal_threshold": 1.04,
            "stop_loss_pips": 5.6,
            "take_profit_pips": 7.6,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.1",
                "max_range_width_10_pips": "7.0",
                "reclaim_range_position_floor": "0.20",
                "reclaim_range_position_ceiling": "0.42",
                "reclaim_momentum_ceiling": "3.0",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Trade the compressed extremes from the opening through the release pocket, but only when the balance remains tight enough that the reversal can still mean-revert before broad continuation takes over.",
            "entry_summary": "Enter on an open-to-release compression reversion when the range is still compressed, the extension is extreme, the reclaim is controlled, and the one-bar reversal confirms direction.",
            "exit_summary": "Exit via fixed stop, fixed target, or 30-bar timeout.",
            "risk_summary": "Broader pocket variant that preserves density while staying anchored to compressed-extreme snapback instead of breakout release.",
        },
        {
            "variant_label": "late_morning_cost_guard",
            "title": "Late Morning Cost-Guard Compression Reversion",
            "family": challenger_family,
            "thesis": "Shift toward the quieter late Europe pocket and enforce tighter cost control so the snapback only trades when the compressed extreme is still clean.",
            "session_focus": "late_morning_compression_reversion",
            "volatility_preference": "low",
            "allowed_hours_utc": [9, 10, 11],
            "holding_bars": 26,
            "signal_threshold": 1.06,
            "stop_loss_pips": 5.2,
            "take_profit_pips": 7.0,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "max_range_width_10_pips": "6.6",
                "reclaim_range_position_floor": "0.22",
                "reclaim_range_position_ceiling": "0.39",
                "reclaim_momentum_ceiling": "2.6",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Trade only the quieter late-Europe compressed extremes where spread is tighter and the move has not already turned into broad directional continuation.",
            "entry_summary": "Enter on a late-morning compression reversion when spread is controlled, range compression is still tight, and reversal confirmation appears inside the narrow reclaim band.",
            "exit_summary": "Exit via fixed stop, fixed target, or 26-bar timeout.",
            "risk_summary": "Cost-guard late-morning variant intended to improve stress resilience without reopening release-window churn.",
        },
        {
            "variant_label": "balanced_three_hour_reversion",
            "title": "Balanced Three-Hour Compression Reversion",
            "family": challenger_family,
            "thesis": "Use the middle Europe pocket with slightly looser geometry if the family needs more trade count without degenerating into a generic reclaim strategy.",
            "session_focus": "balanced_compression_reversion",
            "volatility_preference": "low_to_moderate",
            "allowed_hours_utc": [8, 9, 10],
            "holding_bars": 32,
            "signal_threshold": 1.02,
            "stop_loss_pips": 5.8,
            "take_profit_pips": 7.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.1",
                "max_range_width_10_pips": "7.2",
                "reclaim_range_position_floor": "0.19",
                "reclaim_range_position_ceiling": "0.43",
                "reclaim_momentum_ceiling": "3.1",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Keep the family centered on the middle Europe hours with just enough room for additional density if the compressed-extreme reversal still behaves consistently.",
            "entry_summary": "Enter on a balanced compression reversion when the range remains tight, the extreme is clear, and price has already recovered into the controlled reclaim zone with reversal confirmation.",
            "exit_summary": "Exit via fixed stop, fixed target, or 32-bar timeout.",
            "risk_summary": "Balanced density variant that stays inside compressed-extreme behavior instead of bleeding into breakout or reclaim families.",
        },
    ]


def _compression_breakout_templates() -> list[dict[str, object]]:
    challenger_family = "europe_open_compression_research"
    return [
        {
            "variant_label": "core_release_strict",
            "title": "Core Release Strict Compression Breakout",
            "family": challenger_family,
            "thesis": "Focus only on the core Europe release pocket and demand cleaner compression before the break so the variant stops leaking across the broader window.",
            "session_focus": "europe_core_release_compression",
            "volatility_preference": "high",
            "allowed_hours_utc": [9],
            "holding_bars": 24,
            "signal_threshold": 1.0,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "max_range_width_10_pips": "7.0",
                "breakout_zscore_floor": "0.58",
                "compression_range_position_floor": "0.72",
                "min_volatility_20": "0.00010",
                "required_volatility_bucket": "high",
                "require_ret_1_confirmation": "true",
            },
            "setup_summary": "Restrict the strategy to the core Europe release hour and only trade the cleaner compressions that are already showing higher local volatility.",
            "entry_summary": "Enter on a Europe-core compression break only when momentum clears a stricter threshold, the local range is still tight, and the release is already showing high-volatility participation.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Tight, high-volatility release-window variant intended to cut medium-volatility churn and late-session drift.",
        },
        {
            "variant_label": "core_release_balanced",
            "title": "Core Release Balanced Compression Breakout",
            "family": challenger_family,
            "thesis": "Center the breakout around the release pocket but keep enough surrounding time to preserve a publishable trade count if the cleaner setup still generalizes.",
            "session_focus": "europe_core_release_balanced",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8, 9, 10],
            "holding_bars": 24,
            "signal_threshold": 0.98,
            "stop_loss_pips": 5.4,
            "take_profit_pips": 8.1,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.1",
                "max_range_width_10_pips": "7.4",
                "breakout_zscore_floor": "0.54",
                "compression_range_position_floor": "0.70",
                "min_volatility_20": "0.00008",
                "require_ret_1_confirmation": "true",
            },
            "setup_summary": "Trim the session to the core release band and only take breaks when the setup still shows tighter compression and better local volatility than the exploration seed.",
            "entry_summary": "Enter on a balanced Europe-release compression break when momentum, z-score, and range position all confirm a cleaner expansion than the baseline seed.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Balanced release-window variant aimed at improving expectancy without collapsing trade density below the validation floor.",
        },
        {
            "variant_label": "post_release_cost_guard",
            "title": "Post-Release Cost Guard Compression Breakout",
            "family": challenger_family,
            "thesis": "Keep the stronger part of the Europe morning but enforce tighter cost and compression rules so later drift trades stop dominating the sample.",
            "session_focus": "europe_post_release_cost_guard",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [9, 10, 11],
            "holding_bars": 20,
            "signal_threshold": 1.02,
            "stop_loss_pips": 4.8,
            "take_profit_pips": 7.2,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "max_range_width_10_pips": "6.8",
                "breakout_zscore_floor": "0.60",
                "compression_range_position_floor": "0.72",
                "min_volatility_20": "0.00009",
                "require_ret_1_confirmation": "true",
            },
            "setup_summary": "Trade only the immediate post-release continuations where compression stayed tight enough that the move can still outrun spread and slippage.",
            "entry_summary": "Enter on post-release compression continuation only when momentum, z-score, and range position all clear a more defensive cost-aware threshold.",
            "exit_summary": "Exit via fixed stop, fixed target, or 20-bar timeout.",
            "risk_summary": "Cost-guard variant designed to cut the long tail of time exits that dominated the broad window seed.",
        },
        {
            "variant_label": "trend_excluded_release",
            "title": "Trend-Excluded Release Compression Breakout",
            "family": challenger_family,
            "thesis": "Suppress the weaker trend-context slice and keep the release window centered on the hours where mean-reverting release behavior showed the least damage in the seed.",
            "session_focus": "europe_release_mean_reversion",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [9, 10],
            "holding_bars": 18,
            "signal_threshold": 0.96,
            "stop_loss_pips": 4.6,
            "take_profit_pips": 6.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "max_range_width_10_pips": "7.2",
                "breakout_zscore_floor": "0.52",
                "compression_range_position_floor": "0.69",
                "min_volatility_20": "0.00008",
                "exclude_context_bucket": "trend_context",
                "require_ret_1_confirmation": "true",
            },
            "setup_summary": "Restrict the setup to the release band and ignore the trend-context slice so the variant concentrates on the less-damaging release behavior found in the seed diagnostics.",
            "entry_summary": "Enter on release-window compression breaks only when momentum and range position confirm the move and the current bar is not in the blocked trend-context regime.",
            "exit_summary": "Exit via fixed stop, fixed target, or 18-bar timeout.",
            "risk_summary": "Release-window variant that trades less but avoids the weakest trend-context continuation behavior.",
        },
        {
            "variant_label": "pre_release_buffered",
            "title": "Pre-Release Buffered Compression Breakout",
            "family": challenger_family,
            "thesis": "Allow the hour before the core release only when volatility and compression both tighten enough to justify earlier participation.",
            "session_focus": "europe_pre_release_buffered",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [7, 8, 9],
            "holding_bars": 22,
            "signal_threshold": 1.04,
            "stop_loss_pips": 5.2,
            "take_profit_pips": 7.6,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "max_range_width_10_pips": "6.9",
                "breakout_zscore_floor": "0.57",
                "compression_range_position_floor": "0.71",
                "min_volatility_20": "0.00009",
                "require_ret_1_confirmation": "true",
            },
            "setup_summary": "Open the session slightly earlier, but only when the setup still shows tighter compression and more volatile participation than the baseline.",
            "entry_summary": "Enter on a pre-release buffered compression break when momentum, z-score, and range position all clear the stricter breakout gate before the release becomes stale.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Buffered pre-release variant intended to preserve trade count while keeping the search centered on the Europe release complex.",
        },
    ]


def _range_reclaim_templates() -> list[dict[str, object]]:
    challenger_family = "europe_open_reclaim_research"
    return [
        {
            "variant_label": "early_london_trend_excluded",
            "title": "Early London Trend-Excluded Reclaim",
            "family": challenger_family,
            "thesis": "Focus the reclaim thesis on the early London window and suppress the weaker trend-context slice where the baseline leaked most of its edge.",
            "session_focus": "early_london_reclaim",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [7, 8, 9, 10],
            "holding_bars": 24,
            "signal_threshold": 1.08,
            "stop_loss_pips": 5.8,
            "take_profit_pips": 8.2,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.4",
                "extension_zscore_floor": "1.12",
                "reclaim_range_position_floor": "0.14",
                "reclaim_range_position_ceiling": "0.34",
                "reclaim_momentum_ceiling": "3.2",
                "exclude_context_bucket": "trend_context",
                "require_reclaim_ret_1": "true",
            },
            "setup_summary": "Trade only the tighter early-London reclaim setups and drop the trend-context continuation slice that degraded the baseline.",
            "entry_summary": "Enter on an early-London range reclaim only when the extension is larger, the reclaim happens deeper inside the prior range, and the current context is not in the blocked trend bucket.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Early-London reclaim variant that cuts hold time and suppresses the weakest trend-continuation behavior.",
        },
        {
            "variant_label": "early_london_cost_guard",
            "title": "Early London Cost Guard Reclaim",
            "family": challenger_family,
            "thesis": "Keep the reclaim idea in the early London window but demand tighter spread and stricter extension before taking the fade back into range.",
            "session_focus": "early_london_cost_guard_reclaim",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [7, 8, 9, 10],
            "holding_bars": 20,
            "signal_threshold": 1.12,
            "stop_loss_pips": 5.6,
            "take_profit_pips": 7.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.2",
                "extension_zscore_floor": "1.16",
                "reclaim_range_position_floor": "0.15",
                "reclaim_range_position_ceiling": "0.33",
                "reclaim_momentum_ceiling": "3.0",
                "exclude_context_bucket": "trend_context",
                "require_reclaim_ret_1": "true",
            },
            "setup_summary": "Fade failed London extensions only when execution costs are still controlled and the reclaim is happening from a tighter, cleaner reversal pocket.",
            "entry_summary": "Enter on an early-London reclaim only when the extension is clearly stretched, spread is controlled, and price has already recovered into the tighter reclaim zone outside the blocked trend context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 20-bar timeout.",
            "risk_summary": "Cost-aware reclaim variant aimed at lifting stressed behavior without losing too much throughput.",
        },
        {
            "variant_label": "london_neutral_reclaim",
            "title": "London Neutral-Favoring Reclaim",
            "family": challenger_family,
            "thesis": "Bias the reclaim toward the calmer non-trend states where the baseline already showed positive mean trade value in the early London window.",
            "session_focus": "london_neutral_reclaim",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [7, 8, 9, 10, 11],
            "holding_bars": 24,
            "signal_threshold": 1.06,
            "stop_loss_pips": 5.9,
            "take_profit_pips": 8.4,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.4",
                "extension_zscore_floor": "1.10",
                "reclaim_range_position_floor": "0.15",
                "reclaim_range_position_ceiling": "0.35",
                "reclaim_momentum_ceiling": "3.3",
                "exclude_context_bucket": "trend_context",
                "require_reclaim_ret_1": "true",
            },
            "setup_summary": "Trade reclaims across the London morning but keep the tighter reclaim geometry and skip the trend-context slice that destabilized the baseline.",
            "entry_summary": "Enter on a London-morning reclaim only when the extension is stretched, the reclaim zone is tighter, and the trade is not occurring in the blocked trend context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "London-morning reclaim variant that tries to preserve trade count while keeping the weaker trend-context slice out of sample.",
        },
        {
            "variant_label": "late_london_reclaim",
            "title": "Late London Reclaim",
            "family": challenger_family,
            "thesis": "Shift the reclaim focus toward the late London window where the baseline recovered into positive territory near the end of the non-overlap block.",
            "session_focus": "late_london_reclaim",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [10, 11, 12, 13],
            "holding_bars": 22,
            "signal_threshold": 1.04,
            "stop_loss_pips": 5.7,
            "take_profit_pips": 8.0,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.4",
                "extension_zscore_floor": "1.10",
                "reclaim_range_position_floor": "0.14",
                "reclaim_range_position_ceiling": "0.35",
                "reclaim_momentum_ceiling": "3.2",
                "exclude_context_bucket": "trend_context",
                "require_reclaim_ret_1": "true",
            },
            "setup_summary": "Trade the later London reclaim pocket with tighter reclaim geometry and shorter hold time, still suppressing the blocked trend-context slice.",
            "entry_summary": "Enter on a late-London reclaim when the extension is sufficiently stretched, the price has already recovered into the tighter reclaim zone, and the trade is outside the blocked trend context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Late-London reclaim variant intended to keep the positive tail at the end of the non-overlap window while cutting stale drift.",
        },
        {
            "variant_label": "early_london_buffered",
            "title": "Early London Buffered Reclaim",
            "family": challenger_family,
            "thesis": "Use the early London window but relax the reclaim band slightly so trade count stays healthy while trend-context losses remain blocked.",
            "session_focus": "early_london_buffered_reclaim",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [7, 8, 9, 10],
            "holding_bars": 28,
            "signal_threshold": 1.04,
            "stop_loss_pips": 6.0,
            "take_profit_pips": 8.6,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.5",
                "extension_zscore_floor": "1.08",
                "reclaim_range_position_floor": "0.14",
                "reclaim_range_position_ceiling": "0.36",
                "reclaim_momentum_ceiling": "3.4",
                "exclude_context_bucket": "trend_context",
                "require_reclaim_ret_1": "true",
            },
            "setup_summary": "Keep the reclaim centered on the early London window with the trend-context slice removed, but allow a slightly wider reclaim band to preserve throughput.",
            "entry_summary": "Enter on an early-London reclaim when extension and reclaim-zone recovery are both present, the trend-context slice is excluded, and the broader reclaim band still clears the tighter execution filters.",
            "exit_summary": "Exit via fixed stop, fixed target, or 28-bar timeout.",
            "risk_summary": "Buffered early-London reclaim variant that trades more than the stricter cost-guard version while keeping the worst context suppressed.",
        },
    ]


def _balance_area_breakout_templates() -> list[dict[str, object]]:
    challenger_family = "europe_open_balance_breakout_research"
    return [
        {
            "variant_label": "open_release_selective",
            "title": "Open-Release Selective Balance Breakout",
            "family": challenger_family,
            "thesis": "Keep the Europe-open release pocket but only trade the tighter balance breaks that already show clean directional follow-through outside the weakest mean-reversion context.",
            "session_focus": "europe_balance_release_selective",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [7, 8, 9],
            "holding_bars": 22,
            "signal_threshold": 0.92,
            "stop_loss_pips": 5.2,
            "take_profit_pips": 7.4,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "required_volatility_bucket": "high",
                "exclude_context_bucket": "mean_reversion_context",
            },
            "setup_summary": "Trade only the open-release balance exits where compression stayed tight enough and directional participation is already strong.",
            "entry_summary": "Enter on an open-release balance breakout when the range is still tight, momentum is active, and the trade is outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Selective balance-breakout variant aimed at preserving only the cleanest release moves.",
        },
        {
            "variant_label": "full_window_cost_guard",
            "title": "Full-Window Cost-Guard Balance Breakout",
            "family": challenger_family,
            "thesis": "Keep the full Europe-open window but force tighter costs and a slightly stronger balance-release threshold so weaker middle-window breaks stop dominating the sample.",
            "session_focus": "europe_balance_cost_guard_breakout",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [7, 8, 9, 10, 11],
            "holding_bars": 24,
            "signal_threshold": 0.90,
            "stop_loss_pips": 5.4,
            "take_profit_pips": 7.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "exclude_context_bucket": "mean_reversion_context",
            },
            "setup_summary": "Trade the full Europe-open balance release only when spread remains controlled and the breakout already clears the tighter directional threshold.",
            "entry_summary": "Enter on a full-window balance breakout when directional release is present, the range is still tight, and the trade is outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Cost-aware balance-breakout variant that keeps throughput while trying to cut the weakest directional releases.",
        },
        {
            "variant_label": "late_morning_balance_release",
            "title": "Late-Morning Balance Release Breakout",
            "family": challenger_family,
            "thesis": "Shift the balance breakout toward the later Europe morning where opening noise fades but directional releases can still carry into pre-overlap.",
            "session_focus": "late_morning_balance_release",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [9, 10, 11],
            "holding_bars": 24,
            "signal_threshold": 0.88,
            "stop_loss_pips": 5.5,
            "take_profit_pips": 7.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "exclude_context_bucket": "mean_reversion_context",
            },
            "setup_summary": "Trade later Europe-morning balance releases where directional participation remains active but the most disorderly open swings are gone.",
            "entry_summary": "Enter on a late-morning balance breakout when momentum and range position confirm the release and the current bar is outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Later-window balance-breakout variant intended to reduce opening noise without giving up non-overlap coverage.",
        },
        {
            "variant_label": "high_vol_core_release",
            "title": "High-Vol Core Release Balance Breakout",
            "family": challenger_family,
            "thesis": "Trade only the higher-volatility core balance releases where the breakout has enough energy to justify a stricter threshold and shorter hold time.",
            "session_focus": "high_vol_core_balance_release",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9],
            "holding_bars": 20,
            "signal_threshold": 0.96,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.2,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.8",
                "required_volatility_bucket": "high",
                "exclude_context_bucket": "mean_reversion_context",
            },
            "setup_summary": "Trade only the core high-volatility balance releases where directional participation is strong enough to justify tighter geometry.",
            "entry_summary": "Enter on a high-volatility balance breakout when the range stays tight, directional release is strong, and the current bar is outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 20-bar timeout.",
            "risk_summary": "Strict balance-breakout variant that trades less but prioritizes cleaner directional releases first.",
        },
    ]


def _balance_area_breakout_follow_on_templates() -> list[dict[str, object]]:
    challenger_family = "europe_open_balance_breakout_research"
    return [
        {
            "variant_label": "high_vol_dual_hour_buffered",
            "title": "High-Vol Dual-Hour Buffered Balance Breakout",
            "family": challenger_family,
            "thesis": "Keep the high-volatility core release branch but trim it to the two best Europe hours with tighter cost and hold-time discipline so the best release states can survive longer-term validation.",
            "session_focus": "high_vol_dual_hour_balance_release",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9],
            "holding_bars": 18,
            "signal_threshold": 0.98,
            "stop_loss_pips": 4.8,
            "take_profit_pips": 6.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.7",
                "required_volatility_bucket": "high",
                "exclude_context_bucket": "mean_reversion_context",
            },
            "setup_summary": "Trade only the two strongest high-volatility balance releases with shorter hold time and tighter costs than the first-wave core-release winner.",
            "entry_summary": "Enter on a high-volatility dual-hour balance breakout when the range is tight, directional release is strong, and the current bar is outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 18-bar timeout.",
            "risk_summary": "Dual-hour balance-breakout follow-on aimed at protecting expectancy without dropping below the trade-count floor.",
        },
        {
            "variant_label": "open_release_high_vol_buffered",
            "title": "Open-Release High-Vol Buffered Balance Breakout",
            "family": challenger_family,
            "thesis": "Reintroduce the open hour alongside the high-volatility release pocket, but keep the tighter spread and shorter hold-time discipline that reduced drawdown in the first-wave winner.",
            "session_focus": "open_release_high_vol_balance",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8, 9],
            "holding_bars": 18,
            "signal_threshold": 0.96,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.0,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.8",
                "required_volatility_bucket": "high",
                "exclude_context_bucket": "mean_reversion_context",
            },
            "setup_summary": "Trade the open plus release high-volatility balance breakouts, but keep the tighter execution discipline that cut the catastrophic base-seed overtrading.",
            "entry_summary": "Enter on an open-release high-volatility balance breakout when directional release is strong, the range is tight, and the trade is outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 18-bar timeout.",
            "risk_summary": "Buffered open-release follow-on intended to add throughput without bringing back the broad-window drag.",
        },
        {
            "variant_label": "high_vol_release_short_hold",
            "title": "High-Vol Release Short-Hold Balance Breakout",
            "family": challenger_family,
            "thesis": "Keep the high-volatility release branch but shorten time-in-trade further so only the first directional expansion is monetized and the weaker later bars stop leaking edge.",
            "session_focus": "high_vol_release_short_hold",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9],
            "holding_bars": 14,
            "signal_threshold": 1.0,
            "stop_loss_pips": 4.6,
            "take_profit_pips": 6.6,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.7",
                "required_volatility_bucket": "high",
                "exclude_context_bucket": "mean_reversion_context",
            },
            "setup_summary": "Trade only the first high-volatility balance release burst and force a shorter hold so the edge lives or dies on immediate follow-through.",
            "entry_summary": "Enter on a short-hold high-volatility balance breakout when directional release is strong, the range is tight, and the trade is outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 14-bar timeout.",
            "risk_summary": "Short-hold balance-breakout follow-on aimed at converting the first-wave winner into a cleaner immediate-expansion strategy.",
        },
        {
            "variant_label": "core_release_buffered",
            "title": "Core-Release Buffered Balance Breakout",
            "family": challenger_family,
            "thesis": "Add the 10:00 release extension back to the core high-volatility branch, but keep the tighter threshold and context suppression to test whether trade count can improve without losing the first-wave drawdown gains.",
            "session_focus": "core_release_buffered_balance",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9, 10],
            "holding_bars": 20,
            "signal_threshold": 0.94,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.2,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.8",
                "required_volatility_bucket": "high",
                "exclude_context_bucket": "mean_reversion_context",
            },
            "setup_summary": "Trade the core release balance exits with the 10:00 extension restored, but keep the tighter threshold and blocked mean-reversion context from the first-wave winner.",
            "entry_summary": "Enter on a buffered core-release balance breakout when directional release is strong, the range is tight, and the trade is outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 20-bar timeout.",
            "risk_summary": "Buffered core-release follow-on that tests whether modestly higher throughput can coexist with the first-wave risk cleanup.",
        },
    ]


def _failed_break_fade_templates() -> list[dict[str, object]]:
    challenger_family = "europe_open_failed_break_research"
    return [
        {
            "variant_label": "medium_vol_neutral_core",
            "title": "Medium-Vol Neutral Core Failed Break Fade",
            "family": challenger_family,
            "thesis": "Concentrate the Europe-open fade on the medium-volatility reversal pocket and remove the weaker mean-reversion context slice that dominated the baseline losses.",
            "session_focus": "europe_failed_break_neutral_core",
            "volatility_preference": "medium",
            "allowed_hours_utc": [8, 9, 10],
            "holding_bars": 42,
            "signal_threshold": 1.10,
            "stop_loss_pips": 5.8,
            "take_profit_pips": 8.6,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.00009",
                "fade_ret_5_floor": "0.00007",
                "fade_momentum_ceiling": "2.8",
                "required_volatility_bucket": "medium",
                "exclude_context_bucket": "mean_reversion_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Fade failed Europe breaks only in the core morning pocket where volatility is active but not disorderly, and the trade is outside the weaker mean-reversion context slice.",
            "entry_summary": "Enter on a failed break fade when extension is stretched, medium-volatility conditions are present, reversal pressure is visible, and the current bar is not in the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 42-bar timeout.",
            "risk_summary": "Core Europe-open failure-fade variant designed to improve expectancy first by cutting the noisiest context and worst cost pocket.",
        },
        {
            "variant_label": "open_release_cost_guard",
            "title": "Open Release Cost-Guard Failed Break Fade",
            "family": challenger_family,
            "thesis": "Keep the open and release hours, but demand tighter spread and stronger exhaustion before fading so the edge does not disappear into early-session cost drag.",
            "session_focus": "europe_failed_break_cost_guard",
            "volatility_preference": "medium",
            "allowed_hours_utc": [7, 8, 9],
            "holding_bars": 38,
            "signal_threshold": 1.12,
            "stop_loss_pips": 5.6,
            "take_profit_pips": 8.0,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.8",
                "min_volatility_20": "0.00009",
                "fade_ret_5_floor": "0.00008",
                "fade_momentum_ceiling": "2.6",
                "required_volatility_bucket": "medium",
                "exclude_context_bucket": "mean_reversion_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Take Europe-open failure fades only when spread is controlled, the extension has clearly exhausted, and the move is happening in the cleaner medium-volatility band.",
            "entry_summary": "Enter on an open-release failed break fade only when spread is below the tighter cap, the exhaustion move is larger, and reversal pressure appears outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 38-bar timeout.",
            "risk_summary": "Cost-aware Europe-open failure fade intended to reduce the negative train-window bleed seen in the baseline seed.",
        },
        {
            "variant_label": "late_morning_neutral",
            "title": "Late Morning Neutral Failed Break Fade",
            "family": challenger_family,
            "thesis": "Shift the fade toward the later Europe morning where the baseline stabilizes, while still removing the weaker mean-reversion context slice.",
            "session_focus": "late_morning_failed_break_fade",
            "volatility_preference": "medium",
            "allowed_hours_utc": [9, 10, 11],
            "holding_bars": 40,
            "signal_threshold": 1.06,
            "stop_loss_pips": 5.7,
            "take_profit_pips": 8.2,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.00008",
                "fade_ret_5_floor": "0.00006",
                "fade_momentum_ceiling": "2.9",
                "exclude_context_bucket": "mean_reversion_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Fade later Europe-morning failures where reversal pressure remains visible but the initial open noise has already cleared.",
            "entry_summary": "Enter on a late-morning failed break fade when extension is stretched, reversal pressure is present, and the trade is not occurring in the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 40-bar timeout.",
            "risk_summary": "Later Europe-morning fade variant aimed at reducing open-hour noise while preserving non-overlap coverage.",
        },
        {
            "variant_label": "trend_excluded_medium",
            "title": "Trend-Excluded Medium Failed Break Fade",
            "family": challenger_family,
            "thesis": "Test whether the failure-fade works better as a calmer, non-trend reversal inside the medium-volatility pocket rather than as a broad Europe reversal bet.",
            "session_focus": "medium_vol_failed_break_non_trend",
            "volatility_preference": "medium",
            "allowed_hours_utc": [8, 9, 10, 11],
            "holding_bars": 42,
            "signal_threshold": 1.08,
            "stop_loss_pips": 5.8,
            "take_profit_pips": 8.4,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.00009",
                "fade_ret_5_floor": "0.00007",
                "fade_momentum_ceiling": "2.8",
                "required_volatility_bucket": "medium",
                "exclude_context_bucket": "trend_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Fade failed breaks only when the move is occurring in the medium-volatility pocket and not in the blocked trend context that kept bleeding in the baseline.",
            "entry_summary": "Enter on a medium-volatility failed break fade when extension is stretched, reversal pressure is present, and the current bar is outside the blocked trend context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 42-bar timeout.",
            "risk_summary": "Non-trend failure-fade variant that checks whether the baseline improves by staying inside calmer reversal conditions.",
        },
    ]


def _failed_break_fade_follow_on_templates() -> list[dict[str, object]]:
    challenger_family = "europe_open_failed_break_research"
    return [
        {
            "variant_label": "open_release_balanced_density",
            "title": "Open-Release Balanced-Density Failed Break Fade",
            "family": challenger_family,
            "thesis": "Keep the open-release failed-break branch but reopen the late Europe hour with only a slight relaxation of the exhaustion gate so trade density can recover without giving back the cost discipline that nearly passed stress.",
            "session_focus": "europe_failed_break_balanced_density",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [7, 8, 9, 10],
            "holding_bars": 32,
            "signal_threshold": 1.08,
            "stop_loss_pips": 5.7,
            "take_profit_pips": 8.1,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.00008",
                "fade_ret_5_floor": "0.00007",
                "fade_momentum_ceiling": "2.7",
                "required_volatility_bucket": "medium",
                "exclude_context_bucket": "mean_reversion_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Trade the open plus late Europe-release failed breaks only when the move still sits in the medium-volatility pocket and the looser density recovery remains outside the blocked mean-reversion context.",
            "entry_summary": "Enter on a balanced-density failed break fade when spread is still controlled, the exhaustion move clears the slightly relaxed threshold, and reversal pressure appears outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 32-bar timeout.",
            "risk_summary": "Density-restoration follow-on intended to lift trade count without giving back the cost discipline that kept the first-wave winner near stress pass.",
        },
        {
            "variant_label": "open_release_short_hold_guard",
            "title": "Open-Release Short-Hold Guard Failed Break Fade",
            "family": challenger_family,
            "thesis": "Keep the same open-release medium-volatility pocket as the first-wave winner, but shorten time-in-trade and tighten reversal geometry so the branch either survives costs immediately or gets out faster.",
            "session_focus": "europe_failed_break_short_hold_guard",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [7, 8, 9],
            "holding_bars": 24,
            "signal_threshold": 1.10,
            "stop_loss_pips": 5.2,
            "take_profit_pips": 7.2,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.8",
                "min_volatility_20": "0.00009",
                "fade_ret_5_floor": "0.00008",
                "fade_momentum_ceiling": "2.5",
                "required_volatility_bucket": "medium",
                "exclude_context_bucket": "mean_reversion_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Trade only the original open-release failed-break pocket, but insist on tighter reversal confirmation and a faster exit so cost leakage cannot accumulate late in the hold.",
            "entry_summary": "Enter on a short-hold failed break fade only when spread stays below the strict cap, the reversal snap is already present, and the trade remains outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Stress-first follow-on designed to turn the near-pass into a true cost-surviving branch before worrying about larger throughput gains.",
        },
        {
            "variant_label": "release_plus_late_medium",
            "title": "Release-Plus-Late Medium Failed Break Fade",
            "family": challenger_family,
            "thesis": "Shift the recovery attempt toward the release and late Europe hours where failed breaks are still active, but keep the branch in the medium-volatility pocket so the later density does not import the high-volatility damage seen in the broader seed.",
            "session_focus": "release_plus_late_failed_break_medium",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [8, 9, 10],
            "holding_bars": 30,
            "signal_threshold": 1.08,
            "stop_loss_pips": 5.5,
            "take_profit_pips": 7.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.00008",
                "fade_ret_5_floor": "0.00007",
                "fade_momentum_ceiling": "2.7",
                "required_volatility_bucket": "medium",
                "exclude_context_bucket": "mean_reversion_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Trade the release-plus-late failed-break branch only when volatility remains medium, reversal pressure is already visible, and the trade stays out of the blocked mean-reversion context.",
            "entry_summary": "Enter on a release-plus-late failed break fade when the exhaustion move clears the slightly wider gate, reversal pressure is present, and the current bar is outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 30-bar timeout.",
            "risk_summary": "Late-density follow-on intended to restore sample size while preserving the medium-volatility profile that made the first-wave winner economically interesting.",
        },
        {
            "variant_label": "open_release_dual_vol_buffered",
            "title": "Open-Release Dual-Vol Buffered Failed Break Fade",
            "family": challenger_family,
            "thesis": "Reintroduce higher-volatility failed breaks inside the original open-release window, but only behind a tighter spread and exhaustion gate so the branch can test whether selective dual-volatility participation restores throughput without collapsing back into the base seed.",
            "session_focus": "europe_failed_break_dual_vol_buffered",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [7, 8, 9],
            "holding_bars": 28,
            "signal_threshold": 1.16,
            "stop_loss_pips": 5.3,
            "take_profit_pips": 7.6,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.8",
                "min_volatility_20": "0.00010",
                "fade_ret_5_floor": "0.00009",
                "fade_momentum_ceiling": "2.4",
                "exclude_context_bucket": "mean_reversion_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Trade failed breaks in the original open-release window when the reversal snap is strong enough to justify letting both medium and high-volatility pockets through a stricter gate.",
            "entry_summary": "Enter on a dual-volatility failed break fade only when spread stays below the strict cap, the exhaustion bar is larger, and the reversal trigger appears outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 28-bar timeout.",
            "risk_summary": "Dual-volatility follow-on intended to test whether throughput can recover inside the best window without reopening the broad, weak base profile.",
        },
    ]


def _session_breakout_templates() -> list[dict[str, object]]:
    challenger_family = "europe_open_breakout_research"
    return [
        {
            "variant_label": "full_window_trend_selective",
            "title": "Full-Window Trend-Selective Breakout",
            "family": challenger_family,
            "thesis": "Keep the full Europe-open window but cut the weakest mean-reversion slice so the breakout is only taking directional release states with cleaner follow-through.",
            "session_focus": "europe_open_trend_selective_breakout",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "holding_bars": 28,
            "signal_threshold": 0.94,
            "stop_loss_pips": 5.8,
            "take_profit_pips": 8.2,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.1",
                "breakout_zscore_floor": "0.34",
                "ret_5_floor": "0.00007",
                "exclude_context_bucket": "mean_reversion_context",
                "require_ret_1_confirmation": "true",
            },
            "setup_summary": "Trade Europe-open breakouts across the full non-overlap window, but only when the release is directional and not sitting inside the blocked mean-reversion context.",
            "entry_summary": "Enter on a Europe-open breakout when momentum, z-score, and range position confirm a real directional release and the current bar is outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 28-bar timeout.",
            "risk_summary": "Full-window breakout variant meant to preserve trade count while filtering the context most likely to collapse into reversion.",
        },
        {
            "variant_label": "open_release_cost_guard",
            "title": "Open-Release Cost-Guard Breakout",
            "family": challenger_family,
            "thesis": "Focus on the opening release window and demand tighter spread plus stronger expansion so the breakout still outruns costs after the first impulse.",
            "session_focus": "europe_open_cost_guard_breakout",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [7, 8, 9],
            "holding_bars": 24,
            "signal_threshold": 0.98,
            "stop_loss_pips": 5.4,
            "take_profit_pips": 7.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "breakout_zscore_floor": "0.40",
                "ret_5_floor": "0.00008",
                "min_volatility_20": "0.00008",
                "exclude_context_bucket": "mean_reversion_context",
                "require_ret_1_confirmation": "true",
            },
            "setup_summary": "Trade only the Europe-open release pocket where spreads are controlled and the breakout still has enough local volatility to outrun execution drag.",
            "entry_summary": "Enter on an open-release breakout only when spread is controlled, the expansion clears a stronger z-score floor, and the current bar is outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Cost-aware Europe-open breakout intended to keep the directional edge without carrying later-session drift.",
        },
        {
            "variant_label": "late_morning_continuation",
            "title": "Late Morning Continuation Breakout",
            "family": challenger_family,
            "thesis": "Shift the breakout toward the later Europe morning where the opening noise is reduced but directional continuation can still persist into pre-overlap.",
            "session_focus": "late_morning_breakout_continuation",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [9, 10, 11],
            "holding_bars": 26,
            "signal_threshold": 0.92,
            "stop_loss_pips": 5.7,
            "take_profit_pips": 8.0,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "breakout_zscore_floor": "0.32",
                "ret_5_floor": "0.00006",
                "exclude_context_bucket": "mean_reversion_context",
                "require_ret_1_confirmation": "true",
            },
            "setup_summary": "Trade later Europe-morning continuations where breakout pressure remains but the noisiest opening swings have already cleared.",
            "entry_summary": "Enter on a late-morning breakout when direction, z-score, and range position all confirm continuation and the trade is outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 26-bar timeout.",
            "risk_summary": "Later-window breakout variant aimed at reducing opening noise while preserving non-overlap continuation.",
        },
        {
            "variant_label": "high_vol_release_strict",
            "title": "High-Vol Release Strict Breakout",
            "family": challenger_family,
            "thesis": "Concentrate on the higher-volatility release states only, using a stricter breakout floor so weaker balanced conditions do not leak into the sample.",
            "session_focus": "high_vol_release_breakout",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9, 10],
            "holding_bars": 22,
            "signal_threshold": 1.0,
            "stop_loss_pips": 5.2,
            "take_profit_pips": 7.6,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "breakout_zscore_floor": "0.44",
                "ret_5_floor": "0.00009",
                "min_volatility_20": "0.00010",
                "required_volatility_bucket": "high",
                "exclude_context_bucket": "mean_reversion_context",
                "require_ret_1_confirmation": "true",
            },
            "setup_summary": "Trade only the stronger Europe release bursts where volatility is already active enough to justify a stricter breakout threshold.",
            "entry_summary": "Enter on a high-volatility release breakout when spread is controlled, z-score clears the stricter floor, and the move is outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Strict breakout variant that trades less but aims to protect expectancy and stress resilience first.",
        },
    ]


def _drift_reclaim_templates() -> list[dict[str, object]]:
    challenger_family = "asia_europe_transition_reclaim_research"
    return [
        {
            "variant_label": "bridge_mean_reversion_focus",
            "title": "Bridge Mean-Reversion Focus Reclaim",
            "family": challenger_family,
            "thesis": "Keep the high-volatility Asia-Europe reclaim thesis but block the weaker trend-context slice so the handoff reversal concentrates on the only context bucket that was strongly positive in the seed.",
            "session_focus": "asia_europe_transition_mean_reversion_focus",
            "volatility_preference": "high",
            "allowed_hours_utc": [5, 6, 7],
            "holding_bars": 16,
            "signal_threshold": 0.88,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.0,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.00006",
                "min_volatility_ratio_5_to_20": "1.05",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.70",
                "reclaim_confirmation_floor": "0.40",
                "exclude_context_bucket": "trend_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Trade only the high-volatility bridge reclaims where the overnight drift is stretched and the reversal is not occurring in the weaker trend-context slice.",
            "entry_summary": "Enter on a bridge mean-reversion reclaim when the handoff drift is extended, volatility remains high, reclaim confirmation is present, and the trade is outside the blocked trend context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 16-bar timeout with same-day flat only.",
            "risk_summary": "Context-focused transition reclaim variant intended to preserve the seed's positive expectancy and stress profile.",
        },
        {
            "variant_label": "handoff_core_short_hold",
            "title": "Handoff Core Short-Hold Reclaim",
            "family": challenger_family,
            "thesis": "Tighten the high-volatility reclaim around the core handoff hours and shorten the hold so the reversal either proves itself quickly or exits before Europe-open continuation takes control.",
            "session_focus": "asia_europe_handoff_core_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [6, 7],
            "holding_bars": 12,
            "signal_threshold": 0.92,
            "stop_loss_pips": 4.8,
            "take_profit_pips": 6.6,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.000065",
                "min_volatility_ratio_5_to_20": "1.08",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.76",
                "reclaim_confirmation_floor": "0.45",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Keep the reclaim inside the core Asia-Europe handoff and force the reversal to prove itself under a shorter holding horizon.",
            "entry_summary": "Enter on a short-hold handoff reclaim when the drift is stretched, volatility is high, reclaim confirmation is clean, and the reversal starts before the full Europe-open continuation phase.",
            "exit_summary": "Exit via fixed stop, fixed target, or 12-bar timeout with same-day flat only.",
            "risk_summary": "Short-hold handoff reclaim variant aimed at improving stress stability without reopening broad bridge noise.",
        },
        {
            "variant_label": "bridge_density_extension",
            "title": "Bridge Density Extension Reclaim",
            "family": challenger_family,
            "thesis": "Allow the bridge to start one hour earlier and extend one hour later, but keep the same high-volatility reclaim logic so the family tests whether density can improve without giving back the seed's economics.",
            "session_focus": "asia_europe_bridge_density_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [4, 5, 6, 7, 8],
            "holding_bars": 18,
            "signal_threshold": 0.88,
            "stop_loss_pips": 5.3,
            "take_profit_pips": 7.4,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.000055",
                "min_volatility_ratio_5_to_20": "1.00",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.68",
                "reclaim_confirmation_floor": "0.38",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Widen the bridge window cautiously so the family can test for more valid reclaims without dropping the high-volatility requirement.",
            "entry_summary": "Enter on a bridge density reclaim when the transition drift is stretched, volatility remains high, reclaim confirmation is present, and the reversal starts inside the extended handoff block.",
            "exit_summary": "Exit via fixed stop, fixed target, or 18-bar timeout with same-day flat only.",
            "risk_summary": "Density-restoration transition reclaim variant that widens time support but keeps the same high-volatility reclaim logic.",
        },
        {
            "variant_label": "europe_handoff_reclaim",
            "title": "Europe Handoff Reclaim",
            "family": challenger_family,
            "thesis": "Bias the transition reclaim toward the Europe side of the handoff where the seed already had the better session-level mean trade value, while keeping the same high-volatility reversal logic.",
            "session_focus": "europe_handoff_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [6, 7, 8],
            "holding_bars": 14,
            "signal_threshold": 0.90,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 6.9,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.95",
                "min_volatility_20": "0.00006",
                "min_volatility_ratio_5_to_20": "1.06",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.72",
                "reclaim_confirmation_floor": "0.42",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Keep the bridge reclaim anchored to the later handoff hours where the Europe side of the seed was stronger, without turning it into a Europe-open breakout family.",
            "entry_summary": "Enter on a Europe-handoff reclaim when the overnight drift is stretched, volatility remains high, reclaim confirmation is present, and the reversal forms in the later transition block.",
            "exit_summary": "Exit via fixed stop, fixed target, or 14-bar timeout with same-day flat only.",
            "risk_summary": "Later-handoff transition reclaim variant intended to test whether the stronger Europe-side pocket can lift density without losing stress pass.",
        },
    ]


def _drift_reclaim_follow_on_templates() -> list[dict[str, object]]:
    challenger_family = "asia_europe_transition_reclaim_research"
    return [
        {
            "variant_label": "daytype_spread_guard",
            "title": "Day-Type Spread-Guard Reclaim",
            "family": challenger_family,
            "thesis": "Keep the later Asia-Europe reclaim shape, but only on transition days where spread remains near its rolling bridge norm and the weak neutral-context slice is blocked.",
            "session_focus": "asia_europe_daytype_spread_guard_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [6, 7, 8],
            "holding_bars": 14,
            "signal_threshold": 0.89,
            "stop_loss_pips": 4.9,
            "take_profit_pips": 6.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "max_spread_shock_20": "1.18",
                "min_volatility_20": "0.000055",
                "min_volatility_ratio_5_to_20": "1.00",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.70",
                "reclaim_confirmation_floor": "0.40",
                "exclude_context_bucket": "neutral_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Keep the later handoff reclaim intact, but only when spread has not blown out relative to its own recent bridge baseline.",
            "entry_summary": "Enter on a day-type spread-guard reclaim when the drift is stretched, volatility remains high, spread shock stays controlled, and the transition is outside the blocked neutral context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 14-bar timeout with same-day flat only.",
            "risk_summary": "Soft day-type guard intended to improve quality with less density loss than the hard day-type family.",
        },
        {
            "variant_label": "daytype_quality_soft",
            "title": "Day-Type Soft-Quality Reclaim",
            "family": challenger_family,
            "thesis": "Add only the lightest transition-day quality filter set so the reclaim keeps most of the original handoff density while screening out the noisiest bridge states.",
            "session_focus": "asia_europe_daytype_soft_quality_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [6, 7, 8],
            "holding_bars": 16,
            "signal_threshold": 0.88,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.0,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.95",
                "max_spread_shock_20": "1.22",
                "min_volatility_20": "0.000055",
                "min_volatility_ratio_5_to_20": "0.98",
                "min_range_efficiency_10": "0.22",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.68",
                "reclaim_confirmation_floor": "0.39",
                "exclude_context_bucket": "neutral_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Admit the same later-handoff reclaim, but only when the transition day still shows enough directional efficiency and spread control to justify a reclaim instead of generic bridge churn.",
            "entry_summary": "Enter on a day-type soft-quality reclaim when the drift is stretched, the bridge remains moderately efficient, reclaim confirmation is present, and the trade is outside neutral context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 16-bar timeout with same-day flat only.",
            "risk_summary": "Soft quality-gated reclaim intended to test whether transition-day classification can help without collapsing the branch into single-digit trade counts.",
        },
        {
            "variant_label": "late_decay_cost_guard",
            "title": "Late-Decay Cost-Guard Reclaim",
            "family": challenger_family,
            "thesis": "Keep the revived handoff block inside the supported 07:00-08:59 UTC window, tighten execution costs, and drop the weak neutral context so the family only continues where the later reclaim still outruns friction.",
            "session_focus": "asia_europe_late_decay_cost_guard_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8],
            "holding_bars": 14,
            "signal_threshold": 0.92,
            "stop_loss_pips": 4.9,
            "take_profit_pips": 6.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.85",
                "min_volatility_20": "0.00006",
                "min_volatility_ratio_5_to_20": "1.02",
                "required_volatility_bucket": "high",
                "required_phase_bucket": "late_morning_decay",
                "drift_zscore_floor": "0.70",
                "reclaim_confirmation_floor": "0.40",
                "exclude_context_bucket": "neutral_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Trade only the later transition reclaim block where the family audit found repeatable support, and tighten spread discipline so added density does not come from low-quality handoff noise.",
            "entry_summary": "Enter on a late-decay cost-guard reclaim when the overnight drift is stretched, volatility remains high, reclaim confirmation is present, and the trade is outside the blocked neutral context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 14-bar timeout with same-day flat only.",
            "risk_summary": "Late-decay transition reclaim variant focused on preserving stress survival while keeping the revived 07:00-08:59 block actionable.",
        },
        {
            "variant_label": "late_decay_density_restoration",
            "title": "Late-Decay Density Restoration Reclaim",
            "family": challenger_family,
            "thesis": "Stay inside the revived 07:00-08:59 UTC block, relax the reclaim guard only slightly, and test whether the later handoff can add usable density without reopening the weak early bridge.",
            "session_focus": "asia_europe_late_decay_density_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8],
            "holding_bars": 16,
            "signal_threshold": 0.88,
            "stop_loss_pips": 5.1,
            "take_profit_pips": 7.1,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.000055",
                "min_volatility_ratio_5_to_20": "0.98",
                "required_volatility_bucket": "high",
                "required_phase_bucket": "late_morning_decay",
                "drift_zscore_floor": "0.67",
                "reclaim_confirmation_floor": "0.37",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Allow slightly looser reclaim geometry inside the revived late-handoff block, but keep the family entirely out of the earlier bridge hours that kept collapsing in the weak middle window.",
            "entry_summary": "Enter on a late-decay density reclaim when the transition drift is stretched, volatility remains high, reclaim confirmation is present, and the reversal begins in the later handoff block.",
            "exit_summary": "Exit via fixed stop, fixed target, or 16-bar timeout with same-day flat only.",
            "risk_summary": "Density-restoration follow-on intended to lift trade count without reopening weak early bridge states.",
        },
        {
            "variant_label": "late_decay_short_hold",
            "title": "Late-Decay Short-Hold Reclaim",
            "family": challenger_family,
            "thesis": "Treat the revived block as a quick-rotation reclaim problem, forcing the reversal to prove itself quickly before the handoff drifts into weak continuation decay.",
            "session_focus": "asia_europe_late_decay_short_hold_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8],
            "holding_bars": 10,
            "signal_threshold": 0.94,
            "stop_loss_pips": 4.7,
            "take_profit_pips": 6.4,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.85",
                "min_volatility_20": "0.00006",
                "min_volatility_ratio_5_to_20": "1.04",
                "required_volatility_bucket": "high",
                "required_phase_bucket": "late_morning_decay",
                "drift_zscore_floor": "0.72",
                "reclaim_confirmation_floor": "0.43",
                "exclude_context_bucket": "neutral_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Trade only later handoff reclaims that reverse quickly enough to avoid decaying back into the same weak middle-window churn the audit flagged.",
            "entry_summary": "Enter on a late-decay short-hold reclaim when the drift is stretched, volatility is high, reclaim confirmation is clean, and the reversal starts in the revived later handoff block.",
            "exit_summary": "Exit via fixed stop, fixed target, or 10-bar timeout with same-day flat only.",
            "risk_summary": "Short-hold late-decay follow-on intended to preserve edge quality by cutting slow reclaims before they leak expectancy.",
        },
        {
            "variant_label": "late_decay_europe_bias",
            "title": "Late-Decay Europe-Bias Reclaim",
            "family": challenger_family,
            "thesis": "Bias the revived block toward the Europe side of the handoff, where the family already showed stronger mean trade value, while preserving the later-hour reclaim structure that survived the density audit.",
            "session_focus": "asia_europe_late_decay_europe_bias_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8],
            "holding_bars": 12,
            "signal_threshold": 0.90,
            "stop_loss_pips": 4.8,
            "take_profit_pips": 6.7,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.00006",
                "min_volatility_ratio_5_to_20": "1.03",
                "required_volatility_bucket": "high",
                "required_phase_bucket": "late_morning_decay",
                "drift_zscore_floor": "0.71",
                "reclaim_confirmation_floor": "0.41",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Keep the reclaim inside the revived later handoff block and bias the branch toward the Europe side that was already stronger in the first bounded refinement.",
            "entry_summary": "Enter on a late-decay Europe-bias reclaim when the overnight drift is stretched, volatility remains high, reclaim confirmation is present, and the later transition reversal forms into the Europe handoff.",
            "exit_summary": "Exit via fixed stop, fixed target, or 12-bar timeout with same-day flat only.",
            "risk_summary": "Europe-biased late-decay follow-on intended to preserve the stronger later-handoff pocket while staying inside the revived contiguous audit block.",
        },
    ]


def _drift_reclaim_daytype_follow_on_templates() -> list[dict[str, object]]:
    challenger_family = "asia_europe_transition_reclaim_research"
    return [
        {
            "variant_label": "daytype_spread_guard_density",
            "title": "Day-Type Spread-Guard Density Reclaim",
            "family": challenger_family,
            "thesis": "Keep the spread-shock guard and neutral-context block, but relax reclaim geometry slightly so the later handoff can recover more valid transition days without reopening the weakest bridge noise.",
            "session_focus": "asia_europe_daytype_spread_guard_density_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [6, 7, 8],
            "holding_bars": 16,
            "signal_threshold": 0.86,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.0,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.95",
                "max_spread_shock_20": "1.20",
                "min_volatility_20": "0.000055",
                "min_volatility_ratio_5_to_20": "0.98",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.66",
                "reclaim_confirmation_floor": "0.36",
                "exclude_context_bucket": "neutral_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Preserve the spread-shock guard, but let slightly more handoff reversals qualify before they become generic Europe-open continuation.",
            "entry_summary": "Enter on a spread-guard density reclaim when bridge spread stays controlled, the drift is still stretched, reclaim confirmation is present, and the transition remains outside neutral context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 16-bar timeout with same-day flat only.",
            "risk_summary": "Density-restoration follow-on that keeps the soft day-type guard intact while testing for better middle-window participation.",
        },
        {
            "variant_label": "daytype_spread_guard_late_core",
            "title": "Day-Type Spread-Guard Late-Core Reclaim",
            "family": challenger_family,
            "thesis": "Concentrate the spread-guard reclaim on the later 07:00-08:59 UTC handoff where the audit kept reviving the family, but avoid the harder phase filter that previously collapsed density.",
            "session_focus": "asia_europe_daytype_spread_guard_late_core_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8],
            "holding_bars": 14,
            "signal_threshold": 0.88,
            "stop_loss_pips": 4.8,
            "take_profit_pips": 6.7,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "max_spread_shock_20": "1.16",
                "min_volatility_20": "0.000055",
                "min_volatility_ratio_5_to_20": "1.00",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.69",
                "reclaim_confirmation_floor": "0.38",
                "exclude_context_bucket": "neutral_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Keep the spread guard and later handoff bias, but do not add another explicit phase veto on top of the time window.",
            "entry_summary": "Enter on a late-core spread-guard reclaim when the handoff drift is stretched, spread shock stays controlled, reclaim confirmation is present, and the later transition stays outside neutral context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 14-bar timeout with same-day flat only.",
            "risk_summary": "Later-handoff follow-on intended to preserve the quality gain without repeating the phase-gated density collapse.",
        },
        {
            "variant_label": "daytype_spread_guard_short_hold",
            "title": "Day-Type Spread-Guard Short-Hold Reclaim",
            "family": challenger_family,
            "thesis": "Keep the soft day-type and spread-shock guards, but force the reclaim to prove itself more quickly so the branch can add trades without bleeding back into slow middle-window churn.",
            "session_focus": "asia_europe_daytype_spread_guard_short_hold_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [6, 7, 8],
            "holding_bars": 12,
            "signal_threshold": 0.89,
            "stop_loss_pips": 4.8,
            "take_profit_pips": 6.6,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "max_spread_shock_20": "1.18",
                "min_volatility_20": "0.000055",
                "min_volatility_ratio_5_to_20": "1.00",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.68",
                "reclaim_confirmation_floor": "0.39",
                "exclude_context_bucket": "neutral_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Admit the same spread-guard reclaim days, but make the reversal pay quickly instead of waiting through slower bridge noise.",
            "entry_summary": "Enter on a short-hold spread-guard reclaim when the drift is stretched, bridge spread stays controlled, reclaim confirmation is present, and the transition stays outside neutral context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 12-bar timeout with same-day flat only.",
            "risk_summary": "Short-hold follow-on intended to preserve stress pass while giving the later handoff a chance to lift usable density.",
        },
    ]


def _drift_reclaim_daytype_density_follow_on_templates() -> list[dict[str, object]]:
    challenger_family = "asia_europe_transition_reclaim_research"
    return [
        {
            "variant_label": "daytype_density_handoff_bridge",
            "title": "Day-Type Density Handoff Bridge Reclaim",
            "family": challenger_family,
            "thesis": "Concentrate the spread-guard density reclaim on the supported 07:00-08:59 UTC bridge, relax only the least-destructive day-type thresholds, and test whether the weak middle window can add trades without reopening the earlier negative slice.",
            "session_focus": "asia_europe_daytype_density_handoff_bridge_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8],
            "holding_bars": 16,
            "signal_threshold": 0.84,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 6.9,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.95",
                "max_spread_shock_20": "1.22",
                "min_volatility_20": "0.000055",
                "min_volatility_ratio_5_to_20": "0.95",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.63",
                "reclaim_confirmation_floor": "0.34",
                "exclude_context_bucket": "neutral_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Trade only the supported 07:00-08:59 UTC handoff, while relaxing the least-destructive day-type thresholds enough to test whether the middle walk-forward window can contribute more valid reclaim days.",
            "entry_summary": "Enter on a handoff-bridge reclaim when spread shock stays controlled, the overnight drift remains stretched, reclaim confirmation is present, and the supported 07:00-08:59 UTC transition stays outside neutral context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 16-bar timeout with same-day flat only.",
            "risk_summary": "Bridge-restoration follow-on intended to raise weak-window participation without reintroducing the earlier negative early-handoff slice.",
        },
        {
            "variant_label": "daytype_density_early_follow",
            "title": "Day-Type Density Early-Follow Reclaim",
            "family": challenger_family,
            "thesis": "Isolate the supported early follow-through reclaim on hour 07:00 UTC, keep the spread-shock guard soft, and test whether the revived weak-window hour can stand on its own without the broader bridge noise.",
            "session_focus": "asia_europe_daytype_density_early_follow_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8],
            "holding_bars": 15,
            "signal_threshold": 0.83,
            "stop_loss_pips": 4.9,
            "take_profit_pips": 6.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.95",
                "max_spread_shock_20": "1.22",
                "min_volatility_20": "0.000055",
                "min_volatility_ratio_5_to_20": "0.95",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.62",
                "reclaim_confirmation_floor": "0.33",
                "required_phase_bucket": "early_follow_through",
                "exclude_context_bucket": "neutral_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Focus the reclaim only on the revived early follow-through phase so the weak window is tested directly instead of blended with the stronger later decay pocket.",
            "entry_summary": "Enter on an early-follow reclaim when the handoff drift is stretched, spread shock stays controlled, reclaim confirmation is present, and the setup lands in the supported early follow-through phase.",
            "exit_summary": "Exit via fixed stop, fixed target, or 15-bar timeout with same-day flat only.",
            "risk_summary": "Phase-isolation follow-on intended to prove whether the revived hour-07 pocket is reusable or still too sparse for EA progression.",
        },
        {
            "variant_label": "daytype_density_late_decay",
            "title": "Day-Type Density Late-Decay Reclaim",
            "family": challenger_family,
            "thesis": "Keep the spread-guard density reclaim inside the later supported hour-08 phase, relax only enough to test whether the stronger late-decay pocket can add trades without losing its stress-surviving behavior.",
            "session_focus": "asia_europe_daytype_density_late_decay_reclaim",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8],
            "holding_bars": 16,
            "signal_threshold": 0.84,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 6.9,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.95",
                "max_spread_shock_20": "1.22",
                "min_volatility_20": "0.000055",
                "min_volatility_ratio_5_to_20": "0.95",
                "required_volatility_bucket": "high",
                "drift_zscore_floor": "0.63",
                "reclaim_confirmation_floor": "0.34",
                "required_phase_bucket": "late_morning_decay",
                "exclude_context_bucket": "neutral_context",
                "require_reversal_ret_1": "true",
            },
            "setup_summary": "Trade only the supported late-decay reclaim pocket in the 07:00-08:59 UTC bridge so density can improve without drifting back into the earlier weak slice.",
            "entry_summary": "Enter on a late-decay reclaim when spread shock stays controlled, the overnight drift remains stretched, reclaim confirmation is present, and the setup lands in the supported late-decay phase.",
            "exit_summary": "Exit via fixed stop, fixed target, or 16-bar timeout with same-day flat only.",
            "risk_summary": "Late-decay density follow-on intended to test whether the stronger supported phase can scale before the branch is retired.",
        },
    ]


def _range_reclaim_follow_on_templates() -> list[dict[str, object]]:
    challenger_family = "europe_open_reclaim_research"
    return [
        {
            "variant_label": "dual_pocket_buffered",
            "title": "Dual Pocket Buffered Reclaim",
            "family": challenger_family,
            "thesis": "Keep the two London reclaim pockets that remained positive after trend exclusion and remove the weak bridging hour that kept expectancy below zero.",
            "session_focus": "dual_pocket_london_reclaim",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [7, 9],
            "holding_bars": 24,
            "signal_threshold": 1.04,
            "stop_loss_pips": 5.8,
            "take_profit_pips": 8.4,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.4",
                "extension_zscore_floor": "1.10",
                "reclaim_range_position_floor": "0.15",
                "reclaim_range_position_ceiling": "0.35",
                "reclaim_momentum_ceiling": "3.3",
                "exclude_context_bucket": "trend_context",
                "require_reclaim_ret_1": "true",
            },
            "setup_summary": "Trade only the two reclaim pockets that stayed positive after the first refinement, while keeping the weaker bridging hour out of the sample.",
            "entry_summary": "Enter on a dual-pocket London reclaim when extension and reclaim recovery align inside the tighter reclaim band, the blocked trend context is absent, and the setup occurs in one of the retained London pockets.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Dual-pocket reclaim variant that keeps throughput above the minimum floor while removing the weakest bridging hour from the first refinement winner.",
        },
        {
            "variant_label": "dual_pocket_cost_guard",
            "title": "Dual Pocket Cost Guard Reclaim",
            "family": challenger_family,
            "thesis": "Use the same two London reclaim pockets but tighten execution cost tolerance and reclaim geometry so stressed performance improves first.",
            "session_focus": "dual_pocket_cost_guard_reclaim",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [7, 9],
            "holding_bars": 20,
            "signal_threshold": 1.08,
            "stop_loss_pips": 5.6,
            "take_profit_pips": 7.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.2",
                "extension_zscore_floor": "1.14",
                "reclaim_range_position_floor": "0.16",
                "reclaim_range_position_ceiling": "0.33",
                "reclaim_momentum_ceiling": "3.0",
                "exclude_context_bucket": "trend_context",
                "require_reclaim_ret_1": "true",
            },
            "setup_summary": "Take only the cleaner dual-pocket reclaims where spread, extension, and reclaim depth are all more defensive than the buffered follow-on seed.",
            "entry_summary": "Enter on a dual-pocket reclaim only when the move is more stretched, spread is controlled, the reclaim is tighter, and the blocked trend context is absent.",
            "exit_summary": "Exit via fixed stop, fixed target, or 20-bar timeout.",
            "risk_summary": "Dual-pocket cost-guard variant aimed at moving stressed PF closer to the research floor without collapsing trade count.",
        },
        {
            "variant_label": "dual_pocket_mean_reversion",
            "title": "Dual Pocket Mean-Reversion Reclaim",
            "family": challenger_family,
            "thesis": "Retain the two London pockets but lean harder into the mean-reversion reclaim geometry that carried the stronger part of the 09:00 slice.",
            "session_focus": "dual_pocket_mean_reversion_reclaim",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [7, 9],
            "holding_bars": 22,
            "signal_threshold": 1.06,
            "stop_loss_pips": 5.7,
            "take_profit_pips": 8.0,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.3",
                "extension_zscore_floor": "1.12",
                "reclaim_range_position_floor": "0.16",
                "reclaim_range_position_ceiling": "0.34",
                "reclaim_momentum_ceiling": "3.1",
                "require_reclaim_ret_1": "true",
            },
            "setup_summary": "Trade only the two London reclaim pockets with a tighter reclaim zone that still allows the mean-reversion-driven core of the 09:00 slice to participate.",
            "entry_summary": "Enter on a dual-pocket reclaim when the extension is clearly stretched and the reclaim has already recovered into the tighter mean-reversion zone.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Dual-pocket reclaim variant that removes the blocked trend slice at 07:00 and 09:00 by geometry rather than explicit context exclusion.",
        },
        {
            "variant_label": "open_plus_release_reclaim",
            "title": "Open Plus Release Reclaim",
            "family": challenger_family,
            "thesis": "Keep the open pocket and the release pocket together, but reintroduce 10:00 only under tighter spread and reclaim gates in case the weak hour can be salvaged without 08:00 drag.",
            "session_focus": "open_plus_release_reclaim",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [7, 9, 10],
            "holding_bars": 22,
            "signal_threshold": 1.08,
            "stop_loss_pips": 5.7,
            "take_profit_pips": 8.0,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.2",
                "extension_zscore_floor": "1.14",
                "reclaim_range_position_floor": "0.16",
                "reclaim_range_position_ceiling": "0.34",
                "reclaim_momentum_ceiling": "3.0",
                "exclude_context_bucket": "trend_context",
                "require_reclaim_ret_1": "true",
            },
            "setup_summary": "Trade the open and release reclaim pockets together, but only when tighter spread and reclaim rules suggest 10:00 is not just reintroducing stale drift.",
            "entry_summary": "Enter on an open-plus-release reclaim only when the extension is large, the reclaim zone is tight, the blocked trend context is absent, and the trade lands in one of the retained London hours.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Follow-on reclaim variant that tests whether 10:00 can still contribute without bringing back the full early-London drag.",
        },
    ]


def _trend_retest_templates() -> list[dict[str, object]]:
    challenger_family = "europe_open_trend_retest_research"
    return [
        {
            "variant_label": "core_release_trend_retest",
            "title": "Core Release Trend Retest",
            "family": challenger_family,
            "thesis": "Concentrate the Europe-open retest on the core release hours where directional follow-through is strongest after the first pullback.",
            "session_focus": "core_release_trend_retest",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8, 9, 10],
            "holding_bars": 24,
            "signal_threshold": 0.96,
            "stop_loss_pips": 5.4,
            "take_profit_pips": 7.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.00007",
                "trend_ret_5_min": "0.00011",
                "retest_zscore_limit": "0.30",
                "retest_range_position_floor": "0.58",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade the core Europe release only after a directional impulse has already formed and the pullback remains controlled enough to look like a retest instead of a reversal.",
            "entry_summary": "Enter on a core-release trend retest when the short-horizon trend remains intact, the pullback sits inside the tighter retest band, and the recovery bar confirms continuation outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Core retest-continuation variant aimed at preserving breakout follow-through while cutting outright chase entries.",
        },
        {
            "variant_label": "open_to_pre_overlap_balanced",
            "title": "Open-To-Pre-Overlap Balanced Trend Retest",
            "family": challenger_family,
            "thesis": "Keep the broader Europe non-overlap window if retest continuation remains stable enough to carry more sample without collapsing back into generic breakout chase.",
            "session_focus": "open_to_pre_overlap_trend_retest",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "holding_bars": 28,
            "signal_threshold": 0.90,
            "stop_loss_pips": 5.7,
            "take_profit_pips": 8.2,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.1",
                "min_volatility_20": "0.00006",
                "trend_ret_5_min": "0.00009",
                "retest_zscore_limit": "0.34",
                "retest_range_position_floor": "0.56",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade retests across the broader non-overlap window only when the directional release is already established and the retest remains controlled enough to look like continuation rather than stale drift.",
            "entry_summary": "Enter on a balanced trend retest when the pullback stays inside the retest band, the trend leg remains active, and the current bar resumes continuation outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 28-bar timeout.",
            "risk_summary": "Balanced retest-continuation variant intended to preserve sample size while staying distinct from the breakout and reclaim families.",
        },
        {
            "variant_label": "high_vol_dual_hour_retest",
            "title": "High-Vol Dual-Hour Trend Retest",
            "family": challenger_family,
            "thesis": "Keep only the two highest-energy Europe hours so the retest branch monetizes the cleanest continuation states and avoids slower mid-window bleed.",
            "session_focus": "high_vol_dual_hour_trend_retest",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9],
            "holding_bars": 20,
            "signal_threshold": 1.00,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.2,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.00008",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00012",
                "retest_zscore_limit": "0.28",
                "retest_range_position_floor": "0.60",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade only the highest-energy Europe retests where the initial release was strong enough that a short controlled pullback still leaves room for continuation.",
            "entry_summary": "Enter on a high-volatility trend retest when the core release remains active, the pullback is shallow, and the continuation bar fires outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 20-bar timeout.",
            "risk_summary": "Strict high-volatility retest variant intended to maximize directional quality first and throughput second.",
        },
        {
            "variant_label": "late_morning_cost_guard",
            "title": "Late-Morning Cost-Guard Trend Retest",
            "family": challenger_family,
            "thesis": "Shift the retest branch into the later Europe morning where spreads remain acceptable but the opening whipsaw has already cleared, and tighten execution discipline accordingly.",
            "session_focus": "late_morning_trend_retest",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [9, 10, 11],
            "holding_bars": 22,
            "signal_threshold": 0.88,
            "stop_loss_pips": 5.3,
            "take_profit_pips": 7.4,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.00006",
                "trend_ret_5_min": "0.00009",
                "retest_zscore_limit": "0.30",
                "retest_range_position_floor": "0.57",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade later Europe-morning retests only when the release is still directional and the retest remains controlled enough to avoid slipping into stagnant continuation.",
            "entry_summary": "Enter on a late-morning trend retest when the trend leg is active, the pullback remains bounded, and the resumption bar confirms direction outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Late-morning retest variant designed to reduce opening noise and keep the continuation thesis cost-aware.",
        },
    ]


def _volatility_retest_breakout_templates() -> list[dict[str, object]]:
    challenger_family = "europe_open_retest_breakout_research"
    return [
        {
            "variant_label": "core_release_retest_breakout",
            "title": "Core Release Retest Breakout",
            "family": challenger_family,
            "thesis": "Concentrate the Europe-open retest breakout on the core release hours where continuation survives the first pullback most cleanly.",
            "session_focus": "core_release_retest_breakout",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8, 9, 10],
            "holding_bars": 24,
            "signal_threshold": 0.98,
            "stop_loss_pips": 5.4,
            "take_profit_pips": 7.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.00006",
                "breakout_zscore_floor": "0.50",
                "trend_ret_5_min": "0.00009",
                "retest_zscore_limit": "0.32",
                "retest_range_position_floor": "0.57",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade only the core Europe release retests where volatility remains active enough that the second directional push can still outrun costs.",
            "entry_summary": "Enter on a core-release retest breakout when the pullback remains controlled, the directional leg is still active, and the continuation bar fires outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Core retest-breakout variant aimed at preserving directional edge while avoiding broad-window continuation drag.",
        },
        {
            "variant_label": "balanced_pre_overlap_retest",
            "title": "Balanced Pre-Overlap Retest Breakout",
            "family": challenger_family,
            "thesis": "Keep the broader Europe non-overlap window if retest breakout continuation remains stable enough to support a practical sample size.",
            "session_focus": "balanced_pre_overlap_retest_breakout",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "holding_bars": 28,
            "signal_threshold": 0.92,
            "stop_loss_pips": 5.7,
            "take_profit_pips": 8.4,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.1",
                "min_volatility_20": "0.00005",
                "breakout_zscore_floor": "0.46",
                "trend_ret_5_min": "0.00008",
                "retest_zscore_limit": "0.35",
                "retest_range_position_floor": "0.55",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade retest breakouts across the full Europe non-overlap block only when volatility stays active and the retest remains controlled instead of turning into a fresh reversal.",
            "entry_summary": "Enter on a balanced retest breakout when volatility is active, the pullback remains inside the retest band, and the continuation bar resumes the move outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 28-bar timeout.",
            "risk_summary": "Balanced retest-breakout variant intended to restore useful throughput without drifting back into loose breakout chase.",
        },
        {
            "variant_label": "high_vol_core_retest",
            "title": "High-Vol Core Retest Breakout",
            "family": challenger_family,
            "thesis": "Trade only the highest-energy core release retests where the breakout is most likely to survive costs and continue cleanly after the pullback.",
            "session_focus": "high_vol_core_retest_breakout",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9],
            "holding_bars": 20,
            "signal_threshold": 1.00,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.2,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.00007",
                "required_volatility_bucket": "high",
                "breakout_zscore_floor": "0.52",
                "trend_ret_5_min": "0.00010",
                "retest_zscore_limit": "0.30",
                "retest_range_position_floor": "0.58",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade only the strongest Europe release retests where both the initial impulse and the resumed leg are happening in the high-volatility bucket.",
            "entry_summary": "Enter on a high-volatility retest breakout when the pullback remains shallow, volatility is elevated, and the continuation bar resumes the move outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 20-bar timeout.",
            "risk_summary": "High-volatility retest-breakout variant that sacrifices some sample size to prioritize cleaner continuation quality.",
        },
        {
            "variant_label": "late_morning_cost_guard_retest",
            "title": "Late-Morning Cost-Guard Retest Breakout",
            "family": challenger_family,
            "thesis": "Shift the retest breakout branch into the later Europe morning where opening whipsaw is lower, but keep tighter execution discipline so slower continuation does not leak edge.",
            "session_focus": "late_morning_retest_breakout",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [9, 10, 11],
            "holding_bars": 22,
            "signal_threshold": 0.90,
            "stop_loss_pips": 5.3,
            "take_profit_pips": 7.6,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.00005",
                "breakout_zscore_floor": "0.44",
                "trend_ret_5_min": "0.00008",
                "retest_zscore_limit": "0.33",
                "retest_range_position_floor": "0.56",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade later Europe retest breakouts only when the directional release is still active and the retest remains controlled enough to justify a renewed breakout.",
            "entry_summary": "Enter on a late-morning retest breakout when volatility and direction remain aligned, the pullback stays inside the retest band, and the continuation bar resumes the move outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Late-morning retest-breakout variant designed to reduce open noise while keeping continuation behavior explicit.",
        },
    ]


def _pullback_continuation_templates() -> list[dict[str, object]]:
    challenger_family = "europe_open_pullback_continuation_research"
    return [
        {
            "variant_label": "core_release_pullback",
            "title": "Core Release Pullback Continuation",
            "family": challenger_family,
            "thesis": "Concentrate the Europe-open pullback branch on the core release hours where shallow continuation pullbacks still have room to extend cleanly.",
            "session_focus": "core_release_pullback_continuation",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8, 9, 10],
            "holding_bars": 24,
            "signal_threshold": 0.96,
            "stop_loss_pips": 5.4,
            "take_profit_pips": 7.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.00006",
                "trend_ret_5_min": "0.00009",
                "pullback_zscore_limit": "0.34",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade only the core Europe pullback-continuation states where the initial release is already directional and the pullback remains shallow enough to still look like continuation.",
            "entry_summary": "Enter on a core-release pullback continuation when the directional leg is active, the pullback stays inside the tighter continuation band, and the recovery bar resumes the move outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Core pullback-continuation variant aimed at preserving continuation quality while reducing first-impulse chase.",
        },
        {
            "variant_label": "balanced_pre_overlap_pullback",
            "title": "Balanced Pre-Overlap Pullback Continuation",
            "family": challenger_family,
            "thesis": "Keep the broader Europe non-overlap window if shallow continuation pullbacks remain clean enough to support a practical trade sample.",
            "session_focus": "balanced_pre_overlap_pullback_continuation",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "holding_bars": 28,
            "signal_threshold": 0.90,
            "stop_loss_pips": 5.7,
            "take_profit_pips": 8.4,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.1",
                "min_volatility_20": "0.00005",
                "trend_ret_5_min": "0.00008",
                "pullback_zscore_limit": "0.38",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade pullback-continuation states across the Europe non-overlap window only when the initial release is already established and the pullback stays shallow enough to avoid slipping into full retest or reversal behavior.",
            "entry_summary": "Enter on a balanced pullback continuation when trend direction is still active, the pullback remains inside the allowed continuation band, and the recovery bar resumes outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 28-bar timeout.",
            "risk_summary": "Balanced pullback-continuation variant intended to restore useful throughput while staying cleaner than broad release-breakout families.",
        },
        {
            "variant_label": "high_vol_core_pullback",
            "title": "High-Vol Core Pullback Continuation",
            "family": challenger_family,
            "thesis": "Trade only the highest-energy core release pullbacks where continuation should have enough force to survive costs and shorter hold-time constraints.",
            "session_focus": "high_vol_core_pullback_continuation",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9],
            "holding_bars": 20,
            "signal_threshold": 1.00,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.2,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.00007",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00010",
                "pullback_zscore_limit": "0.32",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade only the highest-energy Europe pullback continuations where the initial release is strong enough that a shallow pullback still preserves immediate continuation potential.",
            "entry_summary": "Enter on a high-volatility pullback continuation when the release is active, the pullback remains tight, and the recovery bar resumes the move outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 20-bar timeout.",
            "risk_summary": "High-volatility pullback-continuation variant that prioritizes directional quality first and throughput second.",
        },
        {
            "variant_label": "late_morning_cost_guard_pullback",
            "title": "Late-Morning Cost-Guard Pullback Continuation",
            "family": challenger_family,
            "thesis": "Shift the pullback-continuation branch into the later Europe morning where open noise is lower, but keep tighter execution discipline so slower continuation does not leak edge.",
            "session_focus": "late_morning_pullback_continuation",
            "volatility_preference": "moderate",
            "allowed_hours_utc": [9, 10, 11],
            "holding_bars": 22,
            "signal_threshold": 0.88,
            "stop_loss_pips": 5.3,
            "take_profit_pips": 7.6,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.00005",
                "trend_ret_5_min": "0.00008",
                "pullback_zscore_limit": "0.36",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade later Europe pullback continuations only when the directional release is still active and the pullback remains shallow enough that the move has not already decayed into drift.",
            "entry_summary": "Enter on a late-morning pullback continuation when volatility and direction remain aligned, the pullback stays inside the continuation band, and the recovery bar resumes the move outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Late-morning pullback-continuation variant designed to reduce open whipsaw while keeping continuation behavior explicit.",
        },
    ]


def _pullback_continuation_follow_on_templates() -> list[dict[str, object]]:
    challenger_family = "europe_open_pullback_continuation_research"
    return [
        {
            "variant_label": "balanced_high_vol_pullback",
            "title": "Balanced High-Vol Pullback Continuation",
            "family": challenger_family,
            "thesis": "Keep the useful pre-overlap pullback branch, but allow only the high-volatility continuation states that already showed positive economics in the first-wave balanced seed.",
            "session_focus": "balanced_high_vol_pullback_continuation",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9, 10, 11],
            "holding_bars": 24,
            "signal_threshold": 0.94,
            "stop_loss_pips": 5.3,
            "take_profit_pips": 7.6,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.00007",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00009",
                "pullback_zscore_limit": "0.34",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade balanced pre-overlap pullbacks only when the initial release and the pullback both occur in the higher-volatility continuation pocket that remained positive in the first-wave seed.",
            "entry_summary": "Enter on a balanced high-volatility pullback continuation when the directional leg is active, the pullback stays inside the tighter continuation band, and the recovery bar resumes outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "High-volatility pullback follow-on aimed at turning the balanced seed into a stress-resilient branch without reopening medium-volatility drag.",
        },
        {
            "variant_label": "open_plus_release_high_vol_pullback",
            "title": "Open-Plus-Release High-Vol Pullback Continuation",
            "family": challenger_family,
            "thesis": "Reintroduce the open hour alongside the better release pocket, but keep the pullback branch restricted to higher-volatility continuation states so throughput can recover without restoring medium-volatility drift.",
            "session_focus": "open_release_high_vol_pullback_continuation",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8, 9, 10],
            "holding_bars": 22,
            "signal_threshold": 0.96,
            "stop_loss_pips": 5.2,
            "take_profit_pips": 7.4,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.00007",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00009",
                "pullback_zscore_limit": "0.33",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade open-plus-release pullbacks only when the move stays in the higher-volatility continuation pocket and the pullback remains shallow enough to still look like continuation instead of retest drift.",
            "entry_summary": "Enter on an open-plus-release high-volatility pullback continuation when the release is already active, the pullback stays shallow, and the recovery bar resumes outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Throughput-restoration pullback follow-on intended to recover sample size while preserving the positive high-volatility edge from the balanced seed.",
        },
        {
            "variant_label": "late_window_high_vol_pullback",
            "title": "Late-Window High-Vol Pullback Continuation",
            "family": challenger_family,
            "thesis": "Shift the pullback branch deeper into pre-overlap, where the later continuation window may still support high-volatility follow-through without the medium-volatility noise that destabilized the balanced seed.",
            "session_focus": "late_window_high_vol_pullback_continuation",
            "volatility_preference": "high",
            "allowed_hours_utc": [9, 10, 11, 12],
            "holding_bars": 22,
            "signal_threshold": 0.94,
            "stop_loss_pips": 5.2,
            "take_profit_pips": 7.4,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.00007",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00009",
                "pullback_zscore_limit": "0.34",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade late Europe-window pullbacks only when the continuation leg remains in the higher-volatility pocket and the pullback stays tight enough to avoid turning into a full retest.",
            "entry_summary": "Enter on a late-window high-volatility pullback continuation when the directional move stays active, the pullback remains inside the tighter band, and the recovery bar resumes outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Late-window continuation follow-on intended to keep the positive high-volatility slice while dropping the weaker medium-volatility middle patch.",
        },
        {
            "variant_label": "balanced_short_hold_cost_guard_pullback",
            "title": "Balanced Short-Hold Cost-Guard Pullback Continuation",
            "family": challenger_family,
            "thesis": "Keep the broader balanced pullback window, but shorten time-in-trade and tighten cost discipline so the branch either survives costs quickly or gets out before medium-volatility decay dominates expectancy.",
            "session_focus": "balanced_short_hold_pullback_continuation",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [8, 9, 10, 11],
            "holding_bars": 18,
            "signal_threshold": 0.96,
            "stop_loss_pips": 5.1,
            "take_profit_pips": 7.0,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.00006",
                "trend_ret_5_min": "0.00009",
                "pullback_zscore_limit": "0.34",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade the balanced pullback branch only when costs are tighter, the pullback remains controlled, and the move either resumes quickly or exits before later bars start leaking edge.",
            "entry_summary": "Enter on a balanced short-hold pullback continuation when the release is already active, the pullback stays inside the tighter band, and the recovery bar resumes outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 18-bar timeout.",
            "risk_summary": "Stress-first pullback follow-on intended to push expectancy and stressed PF up without reopening the full broad-window hold profile.",
        },
    ]


def _pullback_continuation_density_templates() -> list[dict[str, object]]:
    challenger_family = "europe_open_pullback_continuation_research"
    return [
        {
            "variant_label": "full_pre_overlap_high_vol_pullback",
            "title": "Full Pre-Overlap High-Vol Pullback Continuation",
            "family": challenger_family,
            "thesis": "Keep the high-volatility late-window pullback branch but restore the earlier pre-overlap hour so the continuation pattern can collect more trades without reopening the weak medium-volatility slice.",
            "session_focus": "full_pre_overlap_high_vol_pullback_continuation",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "holding_bars": 22,
            "signal_threshold": 0.92,
            "stop_loss_pips": 5.3,
            "take_profit_pips": 7.6,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.00007",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00008",
                "pullback_zscore_limit": "0.35",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade high-volatility pullbacks across the full pre-overlap block only when the initial release remains active and the pullback stays inside the buffered continuation band.",
            "entry_summary": "Enter on a full pre-overlap high-volatility pullback continuation when the release is already active, volatility remains high, the pullback stays shallow, and the recovery bar resumes outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Density-restoration follow-on that adds the earlier pre-overlap hour while keeping the branch fully inside the high-volatility continuation slice.",
        },
        {
            "variant_label": "late_window_high_vol_buffered",
            "title": "Late-Window High-Vol Buffered Pullback Continuation",
            "family": challenger_family,
            "thesis": "Keep the same late-window high-volatility branch, but widen the allowed pullback band and cost cap slightly so more valid continuation resets can pass without reopening the base family.",
            "session_focus": "late_window_high_vol_buffered_pullback",
            "volatility_preference": "high",
            "allowed_hours_utc": [9, 10, 11, 12],
            "holding_bars": 24,
            "signal_threshold": 0.90,
            "stop_loss_pips": 5.4,
            "take_profit_pips": 7.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.1",
                "min_volatility_20": "0.00006",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00008",
                "pullback_zscore_limit": "0.36",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade late-window high-volatility pullbacks when the move remains directional, the pullback stays inside the buffered continuation band, and execution costs remain controlled.",
            "entry_summary": "Enter on a buffered late-window high-volatility pullback continuation when the directional move is active, the pullback remains controlled, and the recovery bar resumes outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Buffered high-volatility follow-on intended to lift trade count from the sparse winner while keeping the branch stress-resilient.",
        },
        {
            "variant_label": "late_window_dual_vol_guarded_pullback",
            "title": "Late-Window Dual-Vol Guarded Pullback Continuation",
            "family": challenger_family,
            "thesis": "Test whether a guarded moderate-to-high-volatility late-window pullback can recover density, but keep the threshold, pullback band, and cost control tighter than the broad balanced seed.",
            "session_focus": "late_window_dual_vol_guarded_pullback_continuation",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [9, 10, 11, 12],
            "holding_bars": 20,
            "signal_threshold": 0.96,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.0,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.8",
                "min_volatility_20": "0.00008",
                "trend_ret_5_min": "0.00010",
                "pullback_zscore_limit": "0.32",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade guarded late-window pullbacks only when the directional release remains active, the pullback stays very shallow, and the trade still clears the tighter cost gate even if volatility is not strictly high.",
            "entry_summary": "Enter on a late-window dual-volatility guarded pullback continuation when the move remains directional, the pullback stays inside the tight band, and the recovery bar resumes outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 20-bar timeout.",
            "risk_summary": "Guarded density-restoration follow-on that tests whether a small amount of non-high-volatility participation can add trades without collapsing expectancy.",
        },
        {
            "variant_label": "open_to_late_high_vol_short_hold",
            "title": "Open-To-Late High-Vol Short-Hold Pullback Continuation",
            "family": challenger_family,
            "thesis": "Restore the full late Europe window including the early release hour, but shorten time-in-trade so only the immediate high-volatility continuation resets survive.",
            "session_focus": "open_to_late_high_vol_short_hold_pullback",
            "volatility_preference": "high",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "holding_bars": 18,
            "signal_threshold": 0.96,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.0,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.9",
                "min_volatility_20": "0.00007",
                "required_volatility_bucket": "high",
                "trend_ret_5_min": "0.00009",
                "pullback_zscore_limit": "0.34",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Trade high-volatility pullbacks from the release hour through late Europe only when the initial continuation is already active and the move either resumes quickly or exits before later bars begin leaking edge.",
            "entry_summary": "Enter on an open-to-late high-volatility short-hold pullback continuation when the release is directional, the pullback remains tight, and the recovery bar resumes outside the blocked mean-reversion context.",
            "exit_summary": "Exit via fixed stop, fixed target, or 18-bar timeout.",
            "risk_summary": "Short-hold density-restoration follow-on intended to recover sample size while preserving the stress profile of the sparse winner.",
        },
    ]


def _pullback_continuation_regime_templates() -> list[dict[str, object]]:
    challenger_family = "europe_open_high_vol_pullback_regime_research"
    return [
        {
            "variant_label": "bridge_relaxed_regime_quality",
            "title": "Bridge Relaxed Regime-Quality Pullback",
            "family": challenger_family,
            "thesis": "Relax the regime-quality pullback clue just enough to recover density through the bridge-to-pre-overlap block, while keeping the continuation state anchored by realized-activity persistence, range efficiency, and mean-location alignment.",
            "session_focus": "bridge_relaxed_high_vol_pullback_regime_quality",
            "volatility_preference": "high_to_persistent",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "holding_bars": 20,
            "signal_threshold": 0.87,
            "stop_loss_pips": 5.2,
            "take_profit_pips": 7.4,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.00005",
                "min_volatility_ratio_5_to_20": "0.80",
                "trend_ret_5_min": "0.00005",
                "pullback_zscore_limit": "0.46",
                "pullback_range_position_floor": "0.46",
                "recovery_zscore_floor": "-0.02",
                "require_mean_location_alignment": "true",
                "max_spread_to_range_10": "0.48",
                "min_intrabar_range_pips": "0.9",
                "min_range_width_10_pips": "4.2",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Allow the bridge hour and a looser regime-quality reset, but keep the branch anchored to realized-activity persistence, usable range, and mean-location alignment so added trades still look like continuation rather than balance drift.",
            "entry_summary": "Enter on a bridge relaxed regime-quality pullback continuation when the release remains active, the reset stays controlled, realized activity still supports continuation, and the recovery resumes on the correct side of the mean.",
            "exit_summary": "Exit via fixed stop, fixed target, or 20-bar timeout.",
            "risk_summary": "Density-restoration regime variant intended to add trades before the family slips back into weak late-reset states.",
        },
        {
            "variant_label": "core_relaxed_regime_quality",
            "title": "Core Relaxed Regime-Quality Pullback",
            "family": challenger_family,
            "thesis": "Keep the pullback clue inside the core pre-overlap block, but relax the regime-quality guards enough to admit more valid continuation resets while still blocking weak mean-reversion handoffs.",
            "session_focus": "core_relaxed_high_vol_pullback_regime_quality",
            "volatility_preference": "high_to_persistent",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "holding_bars": 22,
            "signal_threshold": 0.86,
            "stop_loss_pips": 5.3,
            "take_profit_pips": 7.6,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.00005",
                "min_volatility_ratio_5_to_20": "0.78",
                "trend_ret_5_min": "0.00005",
                "pullback_zscore_limit": "0.48",
                "pullback_range_position_floor": "0.45",
                "recovery_zscore_floor": "-0.03",
                "require_mean_location_alignment": "true",
                "max_spread_to_range_10": "0.50",
                "min_intrabar_range_pips": "0.85",
                "min_range_width_10_pips": "4.0",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Allow a looser regime-quality pullback inside the core pre-overlap block, but preserve realized-activity persistence and mean-location alignment so the extra density still comes from continuation resets.",
            "entry_summary": "Enter on a core relaxed regime-quality pullback continuation when the directional release is already active, the reset remains controlled, realized activity stays live, and the recovery resumes on the continuation side of the mean.",
            "exit_summary": "Exit via fixed stop, fixed target, or 22-bar timeout.",
            "risk_summary": "Core density-restoration regime variant that tries to turn the sparse clue into a usable non-overlap branch.",
        },
        {
            "variant_label": "persistent_reset_density",
            "title": "Persistent Reset Density Pullback",
            "family": challenger_family,
            "thesis": "Lower the regime-quality floor from strict high-volatility to persistent reset quality, so the pullback clue can recover density in quieter windows without reopening broad medium-volatility drift.",
            "session_focus": "persistent_reset_density_pullback_regime_quality",
            "volatility_preference": "persistent",
            "allowed_hours_utc": [8, 9, 10, 11, 12],
            "holding_bars": 24,
            "signal_threshold": 0.85,
            "stop_loss_pips": 5.4,
            "take_profit_pips": 7.8,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "2.0",
                "min_volatility_20": "0.00005",
                "min_volatility_ratio_5_to_20": "0.74",
                "trend_ret_5_min": "0.00005",
                "pullback_zscore_limit": "0.50",
                "pullback_range_position_floor": "0.44",
                "recovery_zscore_floor": "-0.03",
                "require_mean_location_alignment": "true",
                "max_spread_to_range_10": "0.52",
                "min_intrabar_range_pips": "0.8",
                "min_range_width_10_pips": "3.9",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Treat the branch as a persistent-reset problem first, then allow slightly quieter but still live continuation states if the reset remains shallow and the recovery still confirms continuation.",
            "entry_summary": "Enter on a persistent reset density pullback continuation when realized activity remains supportive versus the background window, the reset stays inside the live range, and the recovery resumes on the correct side of the mean.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Density-first regime variant that widens the usable continuation state without reopening weak mean-reversion resets.",
        },
        {
            "variant_label": "short_hold_density_regime_quality",
            "title": "Short-Hold Density Regime-Quality Pullback",
            "family": challenger_family,
            "thesis": "Accept a slightly larger regime-qualified opportunity set, but shorten the hold so the branch either proves the continuation quickly or exits before late-reset weakness destroys stress performance.",
            "session_focus": "short_hold_density_pullback_regime_quality",
            "volatility_preference": "high_to_persistent",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "holding_bars": 18,
            "signal_threshold": 0.88,
            "stop_loss_pips": 5.0,
            "take_profit_pips": 7.1,
            "enable_news_blackout": True,
            "custom_filters": {
                "max_spread_pips": "1.95",
                "min_volatility_20": "0.00005",
                "min_volatility_ratio_5_to_20": "0.82",
                "trend_ret_5_min": "0.00005",
                "pullback_zscore_limit": "0.47",
                "pullback_range_position_floor": "0.46",
                "recovery_zscore_floor": "-0.02",
                "require_mean_location_alignment": "true",
                "max_spread_to_range_10": "0.48",
                "min_intrabar_range_pips": "0.9",
                "min_range_width_10_pips": "4.1",
                "exclude_context_bucket": "mean_reversion_context",
                "require_recovery_ret_1": "true",
            },
            "setup_summary": "Allow more regime-qualified reset states across the bridge-to-pre-overlap block, but force the continuation to prove itself quickly under the shorter hold horizon.",
            "entry_summary": "Enter on a short-hold density regime-quality pullback continuation when the release is active, the reset stays controlled, realized activity remains supportive, and the recovery resumes with mean-location alignment.",
            "exit_summary": "Exit via fixed stop, fixed target, or 18-bar timeout.",
            "risk_summary": "Short-hold density-restoration regime variant that trades a wider state set without tolerating slow continuation decay.",
        },
    ]


def _refinement_score(
    *,
    trade_count: int,
    oos_profit_factor: float,
    stressed_profit_factor: float,
    expectancy_pips: float,
    max_drawdown_pct: float,
    stress_passed: bool,
    meets_requirement_subset: bool,
) -> float:
    score = 0.0
    score += min(trade_count, 250) * 0.18
    score += min(oos_profit_factor, 4.0) * 18.0
    score += min(stressed_profit_factor, 2.0) * 40.0
    score += max(expectancy_pips, -3.0) * 22.0
    score -= min(max_drawdown_pct, 25.0) * 1.8
    if trade_count >= 100:
        score += 18.0
    else:
        score -= 20.0
    if expectancy_pips > 0:
        score += 20.0
    if stress_passed:
        score += 28.0
    else:
        score -= 18.0
    if meets_requirement_subset:
        score += 35.0
    return score


def _report_path(settings: Settings, target_candidate_id: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return settings.paths().experiments_dir / f"{target_candidate_id.lower()}_day_trading_refinement_{timestamp}.json"
