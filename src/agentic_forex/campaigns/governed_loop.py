from __future__ import annotations

from datetime import UTC, datetime

from agentic_forex.campaigns.next_step import SUPPORTED_STEP_TYPES, run_next_step
from agentic_forex.config import Settings
from agentic_forex.goblin.controls import enforce_strategy_governance
from agentic_forex.governance.control_plane import policy_snapshot_hash
from agentic_forex.governance.models import GovernedLoopReport, GovernedLoopStepSummary, NextStepType
from agentic_forex.utils.io import write_json


DEFAULT_GOVERNED_LOOP_STEP_TYPES: list[NextStepType] = [
    step_type
    for step_type in sorted(SUPPORTED_STEP_TYPES)
    if step_type != "human_review"
]


def run_governed_loop(
    settings: Settings,
    *,
    family: str = "scalping",
    parent_campaign_id: str | None = None,
    loop_id: str | None = None,
    max_steps: int = 8,
    allowed_step_types: list[NextStepType] | None = None,
) -> GovernedLoopReport:
    enforce_strategy_governance(settings, family=family)
    loop_identifier = loop_id or f"loop-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    report_path = settings.paths().governed_loops_dir / f"{loop_identifier}.json"
    allowed = list(dict.fromkeys(allowed_step_types or DEFAULT_GOVERNED_LOOP_STEP_TYPES))

    current_parent_campaign_id = parent_campaign_id
    executed_campaign_ids: list[str] = []
    step_summaries: list[GovernedLoopStepSummary] = []
    final_report = None
    stop_reason = "governed_loop_no_steps_executed"
    stop_class = "ambiguity"

    for index in range(1, max_steps + 1):
        step_report = run_next_step(
            settings,
            family=family,
            parent_campaign_id=current_parent_campaign_id,
            allowed_step_types=allowed,
        )
        final_report = step_report
        executed_campaign_ids.append(step_report.campaign_id)
        step_summaries.append(
            GovernedLoopStepSummary(
                step_index=index,
                campaign_id=step_report.campaign_id,
                selected_step_type=step_report.selected_step_type,
                status=step_report.status,
                stop_reason=step_report.stop_reason,
                continuation_status=step_report.continuation_status,
                stop_class=step_report.stop_class,
                auto_continue_allowed=step_report.auto_continue_allowed,
                recommended_follow_on_step=step_report.recommended_follow_on_step,
                transition_status=step_report.transition_status,
                transition_intent=step_report.transition_intent,
                report_path=step_report.report_path,
            )
        )
        current_parent_campaign_id = step_report.campaign_id
        stop_reason = step_report.stop_reason
        stop_class = step_report.stop_class
        if not step_report.auto_continue_allowed:
            break
    else:
        stop_reason = "governed_loop_max_steps_reached"
        stop_class = "budget_exhausted"

    loop_report = GovernedLoopReport(
        loop_id=loop_identifier,
        family=family,
        initial_parent_campaign_id=parent_campaign_id,
        final_parent_campaign_id=current_parent_campaign_id,
        executed_steps=len(step_summaries),
        max_steps=max_steps,
        status="completed" if final_report and final_report.status == "completed" else "stopped",
        stop_reason=stop_reason,
        stop_class=stop_class,
        transition_intent=final_report.transition_intent if final_report else "stop_terminal",
        final_report_path=final_report.report_path if final_report else None,
        final_recommendations=final_report.next_recommendations if final_report else [],
        executed_campaign_ids=executed_campaign_ids,
        step_summaries=step_summaries,
        policy_snapshot_hash=policy_snapshot_hash(settings),
        report_path=report_path,
    )
    write_json(report_path, loop_report.model_dump(mode="json"))
    return loop_report
