from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agentic_forex.backtesting.engine import run_backtest, run_stress_test
from agentic_forex.config import Settings
from agentic_forex.evals.graders import grade_candidate
from agentic_forex.experiments.models import ScalpingIterationReport, ScalpingIterationVariant
from agentic_forex.experiments.service import compare_experiments
from agentic_forex.llm import MockLLMClient
from agentic_forex.nodes import build_tool_registry
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.runtime import ReadPolicy, WorkflowEngine
from agentic_forex.utils.ids import next_candidate_id
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows import WorkflowRepository
from agentic_forex.workflows.contracts import CandidateDraft, FilterRule, ReviewPacket, StrategySpec


def iterate_scalping_target(
    settings: Settings,
    *,
    baseline_candidate_id: str,
    target_candidate_id: str,
) -> ScalpingIterationReport:
    baseline_spec = _load_spec(settings, baseline_candidate_id)
    target_candidate = _load_candidate(settings, target_candidate_id)
    target_spec = _load_spec(settings, target_candidate_id)
    if target_spec.family != "scalping" or target_spec.entry_style != "session_breakout":
        raise ValueError("Target iteration currently supports scalping session_breakout candidates only.")

    _ensure_candidate_evaluated(settings, baseline_spec)
    target_review = _ensure_candidate_evaluated(settings, target_spec)
    oos_guardrail = _oos_guardrail(target_review)

    review_engine = WorkflowEngine(
        settings=settings,
        llm_client=MockLLMClient(),
        tool_registry=build_tool_registry(),
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    review_workflow = WorkflowRepository(settings.paths()).load(settings.workflows.review_workflow_id)

    variants: list[ScalpingIterationVariant] = []
    comparison_ids = [baseline_candidate_id, target_candidate_id]
    for template in _iteration_templates(target_spec):
        candidate = _variant_candidate(target_candidate, settings, template)
        candidate_path = settings.paths().reports_dir / candidate.candidate_id / "candidate.json"
        write_json(candidate_path, candidate.model_dump(mode="json"))
        spec_payload = compile_strategy_spec_tool(
            payload=candidate.model_dump(mode="json"),
            settings=settings,
            config={},
            read_policy=ReadPolicy(project_root=settings.project_root),
        )
        spec = StrategySpec.model_validate(spec_payload)
        spec = _apply_session_breakout_filters(spec, template)
        spec_path = settings.paths().reports_dir / candidate.candidate_id / "strategy_spec.json"
        write_json(spec_path, spec.model_dump(mode="json"))

        review_trace = review_engine.run(review_workflow, spec.model_dump(mode="json"))
        if review_trace.output_payload is None:
            error = next((item.error for item in review_trace.node_traces if item.error), "Review workflow failed.")
            raise RuntimeError(error)
        review_packet = ReviewPacket.model_validate(review_trace.output_payload)
        backtest_summary = review_packet.metrics
        grades = backtest_summary["grades"]
        trade_count = int(backtest_summary["trade_count"])
        oos_pf = float(backtest_summary["out_of_sample_profit_factor"])
        stressed_pf = float(backtest_summary["stress_scenarios"][-1]["profit_factor"])
        expectancy = float(backtest_summary["expectancy_pips"])
        drawdown = float(backtest_summary["max_drawdown_pct"])
        stress_passed = bool(backtest_summary["stress_passed"])
        kept_oos_guardrail = oos_pf >= oos_guardrail
        meets_iteration_objective = bool(stress_passed and trade_count >= target_review.metrics["trade_count"] and kept_oos_guardrail)
        iteration_score = _iteration_score(
            target_trade_count=int(target_review.metrics["trade_count"]),
            trade_count=trade_count,
            oos_profit_factor=oos_pf,
            stressed_profit_factor=stressed_pf,
            expectancy_pips=expectancy,
            max_drawdown_pct=drawdown,
            kept_oos_guardrail=kept_oos_guardrail,
            stress_passed=stress_passed,
            ready_for_publish=bool(grades.get("ready_for_publish")),
        )
        variants.append(
            ScalpingIterationVariant(
                candidate_id=candidate.candidate_id,
                variant_label=template["variant_label"],
                title=candidate.title,
                trade_count=trade_count,
                out_of_sample_profit_factor=oos_pf,
                stressed_profit_factor=stressed_pf,
                stress_passed=stress_passed,
                expectancy_pips=expectancy,
                max_drawdown_pct=drawdown,
                kept_oos_guardrail=kept_oos_guardrail,
                meets_iteration_objective=meets_iteration_objective,
                iteration_score=round(iteration_score, 6),
                spec_path=spec_path,
                review_packet_path=settings.paths().reports_dir / candidate.candidate_id / "review_packet.json",
            )
        )
        comparison_ids.append(candidate.candidate_id)

    ordered = sorted(variants, key=lambda item: item.iteration_score, reverse=True)
    comparison = compare_experiments(settings, family="scalping", candidate_ids=comparison_ids)
    report_path = _report_path(settings, target_candidate_id)
    report = ScalpingIterationReport(
        baseline_candidate_id=baseline_candidate_id,
        target_candidate_id=target_candidate_id,
        objective="Improve stress resilience and trade count versus the target without collapsing out-of-sample profit factor.",
        oos_guardrail_profit_factor=round(oos_guardrail, 6),
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


def _ensure_candidate_evaluated(settings: Settings, spec: StrategySpec) -> ReviewPacket:
    report_dir = settings.paths().reports_dir / spec.candidate_id
    review_path = report_dir / "review_packet.json"
    if review_path.exists():
        return ReviewPacket.model_validate(read_json(review_path))
    review_engine = WorkflowEngine(
        settings=settings,
        llm_client=MockLLMClient(),
        tool_registry=build_tool_registry(),
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    review_workflow = WorkflowRepository(settings.paths()).load(settings.workflows.review_workflow_id)
    review_trace = review_engine.run(review_workflow, spec.model_dump(mode="json"))
    if review_trace.output_payload is None:
        error = next((item.error for item in review_trace.node_traces if item.error), "Review workflow failed.")
        raise RuntimeError(error)
    return ReviewPacket.model_validate(review_trace.output_payload)


def _oos_guardrail(target_review: ReviewPacket) -> float:
    target_oos = float(target_review.metrics["out_of_sample_profit_factor"])
    return max(1.05, min(target_oos, 3.0) * 0.5)


def _variant_candidate(target: CandidateDraft, settings: Settings, template: dict) -> CandidateDraft:
    return target.model_copy(
        update={
            "candidate_id": next_candidate_id(settings),
            "title": template["title"],
            "thesis": f'{template["thesis"]} Derived from {target.candidate_id} as an iteration target.',
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
                    + [f'Iteration variant: {template["variant_label"]}.'],
                }
            ),
            "notes": list(target.notes) + [f'Iteration target derived from {target.candidate_id}.'],
            "entry_style": "session_breakout",
            "holding_bars": template["holding_bars"],
            "signal_threshold": template["signal_threshold"],
            "stop_loss_pips": template["stop_loss_pips"],
            "take_profit_pips": template["take_profit_pips"],
        }
    )


def _apply_session_breakout_filters(spec: StrategySpec, template: dict) -> StrategySpec:
    rules = {item.name: item.rule for item in spec.filters}
    rules.update(
        {
            "max_spread_pips": template["max_spread_pips"],
            "min_volatility_20": template["min_volatility_20"],
            "require_ret_5_alignment": "true",
            "require_mean_location_alignment": "true",
            "breakout_zscore_floor": template["breakout_zscore_floor"],
            "ret_5_floor": template["ret_5_floor"],
        }
    )
    session_policy = spec.session_policy.model_copy(update={"allowed_hours_utc": template["allowed_hours_utc"]})
    risk_policy = spec.risk_policy.model_copy(
        update={
            "stop_loss_pips": template["stop_loss_pips"],
            "take_profit_pips": template["take_profit_pips"],
        }
    )
    updated = spec.model_copy(
        update={
            "variant_name": template["variant_label"],
            "session_policy": session_policy,
            "filters": [FilterRule(name=name, rule=rule) for name, rule in rules.items()],
            "risk_policy": risk_policy,
            "holding_bars": template["holding_bars"],
            "signal_threshold": template["signal_threshold"],
            "stop_loss_pips": template["stop_loss_pips"],
            "take_profit_pips": template["take_profit_pips"],
            "entry_logic": [
                template["entry_summary"],
                f'Signal threshold {template["signal_threshold"]}',
            ],
            "exit_logic": [
                template["exit_summary"],
                f'Time exit after {template["holding_bars"]} bars',
            ],
            "notes": list(spec.notes) + [f'Iteration label: {template["variant_label"]}.'],
        }
    )
    return StrategySpec.model_validate(updated.model_dump(mode="json"))


def _iteration_templates(target_spec: StrategySpec) -> list[dict[str, object]]:
    if target_spec.variant_name == "cost_guard_breakout":
        return _cost_guard_follow_on_templates()
    return _default_iteration_templates()


def _default_iteration_templates() -> list[dict[str, object]]:
    return [
        {
            "variant_label": "balanced_extension",
            "title": "Balanced Extension Breakout",
            "thesis": "Extend the session window slightly and tighten breakout quality so trade count improves without handing too much edge back to costs.",
            "session_focus": "europe_breakout_extension",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "holding_bars": 30,
            "signal_threshold": 0.95,
            "stop_loss_pips": 4.5,
            "take_profit_pips": 7.2,
            "max_spread_pips": "1.9",
            "min_volatility_20": "0.00011",
            "breakout_zscore_floor": "0.25",
            "ret_5_floor": "0.00005",
            "setup_summary": "Trade Europe-session breakouts with a slightly broader window but only after price extension and return alignment both clear modest quality gates.",
            "entry_summary": "Enter on Europe-session breakout continuation when momentum clears a moderate threshold, 5-bar return is directionally positive, and short-term extension is already visible.",
            "exit_summary": "Exit via fixed stop, fixed target, or 30-bar timeout.",
            "risk_summary": "Balanced breakout variant intended to raise throughput without losing cost discipline.",
        },
        {
            "variant_label": "cost_guard_breakout",
            "title": "Cost Guard Breakout",
            "thesis": "Prioritize stress resilience by insisting on stronger short-term extension and tighter spread tolerance before entering.",
            "session_focus": "europe_cost_guard_breakout",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "holding_bars": 28,
            "signal_threshold": 1.02,
            "stop_loss_pips": 4.2,
            "take_profit_pips": 7.4,
            "max_spread_pips": "1.8",
            "min_volatility_20": "0.00012",
            "breakout_zscore_floor": "0.32",
            "ret_5_floor": "0.00008",
            "setup_summary": "Trade only the cleaner breakout continuations where both directional return and visible short-term extension suggest enough edge to absorb stressed costs.",
            "entry_summary": "Enter on Europe-session breakout continuation only when momentum, price location, return alignment, and short-term extension all confirm a cleaner expansion.",
            "exit_summary": "Exit via fixed stop, fixed target, or 28-bar timeout.",
            "risk_summary": "Cost-aware breakout variant aimed at preserving expectancy under stressed spread and slippage assumptions.",
        },
        {
            "variant_label": "throughput_breakout",
            "title": "Throughput Breakout",
            "thesis": "Increase trade count by lowering the trigger slightly and using a shorter holding window, while still rejecting the weakest breakouts through light extension filters.",
            "session_focus": "europe_throughput_breakout",
            "volatility_preference": "moderate_to_high",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "holding_bars": 24,
            "signal_threshold": 0.9,
            "stop_loss_pips": 4.0,
            "take_profit_pips": 6.6,
            "max_spread_pips": "1.9",
            "min_volatility_20": "0.00010",
            "breakout_zscore_floor": "0.18",
            "ret_5_floor": "0.00004",
            "setup_summary": "Open the trigger slightly and shorten the holding window so more eligible breakouts become trades without turning into unrestricted noise.",
            "entry_summary": "Enter on Europe-session breakout continuation when momentum and 5-bar return clear a slightly easier threshold but the move still shows visible short-term extension.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Throughput-oriented breakout variant focused on generating more decision-worthy trades.",
        },
        {
            "variant_label": "persistence_breakout",
            "title": "Persistence Breakout",
            "thesis": "Hold stronger breakouts slightly longer and require cleaner directional persistence so the variant favors moves with more follow-through.",
            "session_focus": "europe_persistence_breakout",
            "volatility_preference": "high",
            "allowed_hours_utc": [7, 8, 9, 10, 11, 12],
            "holding_bars": 42,
            "signal_threshold": 1.08,
            "stop_loss_pips": 4.8,
            "take_profit_pips": 8.0,
            "max_spread_pips": "1.8",
            "min_volatility_20": "0.00012",
            "breakout_zscore_floor": "0.35",
            "ret_5_floor": "0.00008",
            "setup_summary": "Trade only the cleaner continuation structures and allow them a slightly longer holding window to capture follow-through rather than forcing early exits.",
            "entry_summary": "Enter on Europe-session breakout continuation only when momentum, short-term return, and price extension all point to stronger directional persistence.",
            "exit_summary": "Exit via fixed stop, fixed target, or 42-bar timeout.",
            "risk_summary": "Persistence-oriented breakout variant intended to protect OOS edge while improving stressed behavior.",
        },
    ]


def _cost_guard_follow_on_templates() -> list[dict[str, object]]:
    return [
        {
            "variant_label": "extended_session_quality",
            "title": "Extended Session Quality Breakout",
            "thesis": "Extend the research window into the pre-Europe and early-overlap hours while keeping the cost-guard structure tight enough to preserve stressed expectancy.",
            "session_focus": "extended_session_quality_breakout",
            "volatility_preference": "high",
            "allowed_hours_utc": [6, 7, 8, 9, 10, 11, 12, 13, 14],
            "holding_bars": 26,
            "signal_threshold": 0.96,
            "stop_loss_pips": 4.2,
            "take_profit_pips": 7.4,
            "max_spread_pips": "1.9",
            "min_volatility_20": "0.00012",
            "breakout_zscore_floor": "0.32",
            "ret_5_floor": "0.00005",
            "setup_summary": "Broaden the active session to capture more high-quality Europe and early-overlap breakouts without relaxing the core cost-aware structure.",
            "entry_summary": "Enter on breakout continuation from the extended Europe window when momentum, price location, and short-term return stay aligned under the original cost-guard discipline.",
            "exit_summary": "Exit via fixed stop, fixed target, or 26-bar timeout.",
            "risk_summary": "Primary follow-on variant for lifting trade count while preserving stressed robustness.",
        },
        {
            "variant_label": "extended_session_tight_spread",
            "title": "Extended Session Tight Spread Breakout",
            "thesis": "Use the broader session extension but keep the tighter spread ceiling so added throughput still comes from cleaner execution conditions.",
            "session_focus": "extended_session_tight_spread_breakout",
            "volatility_preference": "high",
            "allowed_hours_utc": [6, 7, 8, 9, 10, 11, 12, 13, 14],
            "holding_bars": 26,
            "signal_threshold": 0.96,
            "stop_loss_pips": 4.2,
            "take_profit_pips": 7.4,
            "max_spread_pips": "1.8",
            "min_volatility_20": "0.00012",
            "breakout_zscore_floor": "0.32",
            "ret_5_floor": "0.00005",
            "setup_summary": "Trade the extended session only when spread remains inside the tighter execution envelope.",
            "entry_summary": "Enter on extended-session breakout continuation when directional return, mean-location alignment, and tighter spread discipline all stay intact.",
            "exit_summary": "Exit via fixed stop, fixed target, or 26-bar timeout.",
            "risk_summary": "Extended-session variant that favors cleaner execution over absolute throughput.",
        },
        {
            "variant_label": "extended_session_buffered_ret5",
            "title": "Extended Session Buffered Return Breakout",
            "thesis": "Keep the broader session but require a slightly stronger five-bar return so additional trades still arrive from moves with visible short-term participation.",
            "session_focus": "extended_session_buffered_ret5_breakout",
            "volatility_preference": "high",
            "allowed_hours_utc": [6, 7, 8, 9, 10, 11, 12, 13, 14],
            "holding_bars": 26,
            "signal_threshold": 0.96,
            "stop_loss_pips": 4.2,
            "take_profit_pips": 7.4,
            "max_spread_pips": "1.9",
            "min_volatility_20": "0.00012",
            "breakout_zscore_floor": "0.32",
            "ret_5_floor": "0.00006",
            "setup_summary": "Capture more extended-session breakouts, but only when the short-term return already shows better participation than the looser throughput variants.",
            "entry_summary": "Enter on extended-session breakout continuation only when momentum, price location, and a stronger short-term return floor all confirm the move.",
            "exit_summary": "Exit via fixed stop, fixed target, or 26-bar timeout.",
            "risk_summary": "Buffered-return extension variant designed to preserve OOS and stress while broadening the session.",
        },
        {
            "variant_label": "pre_overlap_balanced",
            "title": "Pre-Overlap Balanced Breakout",
            "thesis": "Extend modestly into pre-Europe and early-overlap hours while shortening the hold so added throughput does not come from stale late-session trades.",
            "session_focus": "pre_overlap_balanced_breakout",
            "volatility_preference": "high",
            "allowed_hours_utc": [6, 7, 8, 9, 10, 11, 12, 13],
            "holding_bars": 24,
            "signal_threshold": 0.96,
            "stop_loss_pips": 4.2,
            "take_profit_pips": 7.4,
            "max_spread_pips": "1.9",
            "min_volatility_20": "0.00012",
            "breakout_zscore_floor": "0.32",
            "ret_5_floor": "0.00006",
            "setup_summary": "Open the session slightly on both sides but cut the holding window so throughput improves without relying on late drift.",
            "entry_summary": "Enter on balanced breakout continuation across pre-Europe and early-overlap hours when momentum, price location, and short-term return all stay aligned.",
            "exit_summary": "Exit via fixed stop, fixed target, or 24-bar timeout.",
            "risk_summary": "Balanced extension variant aimed at increasing trade count without giving back the new stress pass.",
        },
    ]


def _iteration_score(
    *,
    target_trade_count: int,
    trade_count: int,
    oos_profit_factor: float,
    stressed_profit_factor: float,
    expectancy_pips: float,
    max_drawdown_pct: float,
    kept_oos_guardrail: bool,
    stress_passed: bool,
    ready_for_publish: bool,
) -> float:
    score = 0.0
    score += (trade_count - target_trade_count) * 1.25
    score += min(stressed_profit_factor, 2.0) * 40.0
    score += min(oos_profit_factor, 4.0) * 10.0
    score += max(expectancy_pips, -3.0) * 8.0
    score -= min(max_drawdown_pct, 25.0) * 1.5
    if kept_oos_guardrail:
        score += 20.0
    else:
        score -= 40.0
    if stress_passed:
        score += 40.0
    else:
        score -= 20.0
    if ready_for_publish:
        score += 25.0
    return score


def _report_path(settings: Settings, target_candidate_id: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return settings.paths().experiments_dir / f"{target_candidate_id.lower()}_iteration_{timestamp}.json"
