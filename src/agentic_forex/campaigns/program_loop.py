from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from agentic_forex.campaigns.governed_loop import run_governed_loop
from agentic_forex.campaigns.next_step import run_next_step
from agentic_forex.config import Settings
from agentic_forex.config.models import ProgramLanePolicy
from agentic_forex.goblin.controls import enforce_strategy_governance, finalize_goblin_run_record, start_goblin_run_record
from agentic_forex.governance.control_plane import policy_snapshot_hash
from agentic_forex.governance.models import CampaignSpec, CampaignState, NextStepControllerReport, ProgramLoopLaneSummary, ProgramLoopReport
from agentic_forex.nodes.toolkit import default_execution_cost_fields
from agentic_forex.utils.ids import next_campaign_id
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows.contracts import CandidateDraft


def run_program_loop(
    settings: Settings,
    *,
    family: str = "scalping",
    parent_campaign_id: str | None = None,
    program_id: str | None = None,
    max_lanes: int | None = None,
) -> ProgramLoopReport:
    enforce_strategy_governance(settings, family=family)
    program_identifier = program_id or f"program-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    report_path = settings.paths().program_loops_dir / f"{program_identifier}.json"
    run_record = start_goblin_run_record(
        run_id=program_identifier,
        entrypoint="run_program_loop",
        family=family,
        campaign_id=parent_campaign_id,
    )
    if not settings.program.active:
        report = ProgramLoopReport(
            program_id=program_identifier,
            family=family,
            initial_parent_campaign_id=parent_campaign_id,
            final_parent_campaign_id=parent_campaign_id,
            executed_lanes=0,
            max_lanes=max_lanes or settings.program.max_lanes_per_run,
            status="stopped",
            stop_reason="program_loop_inactive",
            stop_class="policy_decision",
            report_path=report_path,
        )
        write_json(report_path, report.model_dump(mode="json"))
        return report
    lane_budget = max_lanes or settings.program.max_lanes_per_run
    approved_lanes = [lane for lane in settings.program.approved_lanes if lane.family == family]

    lane_summaries: list[ProgramLoopLaneSummary] = []
    executed_lane_ids: set[str] = _historical_terminal_lane_ids(settings, family=family, approved_lanes=approved_lanes)
    seeded_lane_ids: set[str] = set()
    current_parent_campaign_id = parent_campaign_id
    carry_forward_parent_campaign_id = parent_campaign_id
    stop_reason = "program_loop_no_steps_executed"
    stop_class = "ambiguity"
    final_audit_report_path: Path | None = None

    initial_lane = _active_lane_placeholder(family=family) if parent_campaign_id else None
    current_lane = initial_lane
    initial_transition_status = _campaign_transition_status(settings, parent_campaign_id) if parent_campaign_id else None
    resuming_active_lane = bool(parent_campaign_id and initial_transition_status != "move_to_next_lane")
    if initial_transition_status == "move_to_next_lane":
        current_parent_campaign_id = None
    elif initial_transition_status == "hard_stop":
        report = ProgramLoopReport(
            program_id=program_identifier,
            family=family,
            initial_parent_campaign_id=parent_campaign_id,
            final_parent_campaign_id=parent_campaign_id,
            executed_lanes=0,
            max_lanes=lane_budget,
            status="stopped",
            stop_reason="program_loop_parent_lane_hard_stop",
            stop_class="policy_decision",
            report_path=report_path,
        )
        write_json(report_path, report.model_dump(mode="json"))
        return report

    if not resuming_active_lane:
        invalid_throughput_pairs = settings.program.invalid_throughput_lane_pairs(family=family)
        if invalid_throughput_pairs:
            report = ProgramLoopReport(
                program_id=program_identifier,
                family=family,
                initial_parent_campaign_id=parent_campaign_id,
                final_parent_campaign_id=parent_campaign_id,
                executed_lanes=0,
                max_lanes=lane_budget,
                status="stopped",
                stop_reason=f"program_loop_invalid_throughput_orthogonality:{invalid_throughput_pairs[0][0]}:{invalid_throughput_pairs[0][1]}",
                stop_class="policy_decision",
                report_path=report_path,
            )
            write_json(report_path, report.model_dump(mode="json"))
            return report
        invalid_seed_identity = _first_invalid_seed_identity(settings, approved_lanes=approved_lanes)
        if invalid_seed_identity is not None:
            lane_id, mismatch_reason = invalid_seed_identity
            report = ProgramLoopReport(
                program_id=program_identifier,
                family=family,
                initial_parent_campaign_id=parent_campaign_id,
                final_parent_campaign_id=parent_campaign_id,
                executed_lanes=0,
                max_lanes=lane_budget,
                status="stopped",
                stop_reason=f"program_loop_seed_candidate_truth_mismatch:{lane_id}:{mismatch_reason}",
                stop_class="integrity_issue",
                report_path=report_path,
            )
            write_json(report_path, report.model_dump(mode="json"))
            return report
        missing_family_evidence = _first_missing_family_evidence_lane(settings, approved_lanes=approved_lanes)
        if missing_family_evidence is not None:
            lane_id, missing_tags = missing_family_evidence
            report = ProgramLoopReport(
                program_id=program_identifier,
                family=family,
                initial_parent_campaign_id=parent_campaign_id,
                final_parent_campaign_id=parent_campaign_id,
                executed_lanes=0,
                max_lanes=lane_budget,
                status="stopped",
                stop_reason=f"program_loop_missing_family_evidence:{lane_id}:{','.join(missing_tags)}",
                stop_class="policy_decision",
                report_path=report_path,
            )
            write_json(report_path, report.model_dump(mode="json"))
            return report
        retired_archetype = _first_retired_throughput_archetype(settings, approved_lanes=approved_lanes)
        if retired_archetype is not None:
            lane_id, hypothesis_class, failure_count = retired_archetype
            report = ProgramLoopReport(
                program_id=program_identifier,
                family=family,
                initial_parent_campaign_id=parent_campaign_id,
                final_parent_campaign_id=parent_campaign_id,
                executed_lanes=0,
                max_lanes=lane_budget,
                status="stopped",
                stop_reason=f"program_loop_archetype_retired:{lane_id}:{hypothesis_class}:{failure_count}",
                stop_class="policy_decision",
                report_path=report_path,
            )
            write_json(report_path, report.model_dump(mode="json"))
            return report
        low_novelty_seed = _first_low_novelty_throughput_lane(settings, approved_lanes=approved_lanes)
        if low_novelty_seed is not None:
            lane_id, archived_candidate_id, similarity_score = low_novelty_seed
            report = ProgramLoopReport(
                program_id=program_identifier,
                family=family,
                initial_parent_campaign_id=parent_campaign_id,
                final_parent_campaign_id=parent_campaign_id,
                executed_lanes=0,
                max_lanes=lane_budget,
                status="stopped",
                stop_reason=f"program_loop_low_novelty_seed:{lane_id}:{archived_candidate_id}:{similarity_score:.2f}",
                stop_class="policy_decision",
                report_path=report_path,
            )
            write_json(report_path, report.model_dump(mode="json"))
            return report

    cycle_index = 0
    max_cycles = max(lane_budget * 4, 4)
    while cycle_index < max_cycles:
        cycle_index += 1
        if current_parent_campaign_id is None:
            current_lane = _next_pending_lane(settings, approved_lanes=approved_lanes, executed_lane_ids=executed_lane_ids)
            if current_lane is None:
                if carry_forward_parent_campaign_id and _family_requires_post_queue_audit(approved_lanes):
                    final_audit = run_next_step(
                        settings,
                        family=family,
                        parent_campaign_id=carry_forward_parent_campaign_id,
                        allowed_step_types=["data_feature_audit"],
                    )
                    final_audit_report_path = final_audit.report_path
                    carry_forward_parent_campaign_id = final_audit.campaign_id
                    current_parent_campaign_id = final_audit.campaign_id
                    stop_reason = final_audit.stop_reason
                    stop_class = final_audit.stop_class
                    if final_audit.transition_status == "continue_lane":
                        current_lane = _active_lane_placeholder(family=family)
                        continue
                    if (
                        final_audit.selected_step_type == "data_feature_audit"
                        and final_audit.data_feature_audit_reports
                        and final_audit.data_feature_audit_reports[0].family_decision == "retire_family"
                    ):
                        final_label_audit = run_next_step(
                            settings,
                            family=family,
                            parent_campaign_id=final_audit.campaign_id,
                            allowed_step_types=["data_label_audit"],
                        )
                        final_audit_report_path = final_label_audit.report_path
                        carry_forward_parent_campaign_id = final_label_audit.campaign_id
                        current_parent_campaign_id = final_label_audit.campaign_id
                        stop_reason = final_label_audit.stop_reason
                        stop_class = final_label_audit.stop_class
                else:
                    stop_reason = "program_loop_no_pending_approved_lanes"
                    stop_class = "policy_decision"
                break
            if len(seeded_lane_ids) >= lane_budget:
                stop_reason = "program_loop_max_lanes_reached"
                stop_class = "budget_exhausted"
                break
            seed_campaign_id = _seed_program_lane(
                settings,
                lane=current_lane,
                parent_campaign_id=carry_forward_parent_campaign_id,
            )
            current_parent_campaign_id = seed_campaign_id
            executed_lane_ids.add(current_lane.lane_id)
            seeded_lane_ids.add(current_lane.lane_id)
        elif current_lane is not None and current_lane.lane_id != f"{family}-active":
            executed_lane_ids.add(current_lane.lane_id)

        lane_initial_parent = current_parent_campaign_id
        loop_report = run_governed_loop(
            settings,
            family=family,
            parent_campaign_id=current_parent_campaign_id,
            loop_id=f"{program_identifier}-lane-{cycle_index:02d}",
            max_steps=current_lane.max_steps if current_lane is not None else 8,
        )
        final_report = _load_final_program_report(loop_report.final_report_path)
        stop_reason = loop_report.stop_reason
        stop_class = loop_report.stop_class
        transition_status = final_report.transition_status if final_report else "hard_stop"
        if current_lane is not None and current_lane.lane_id != f"{family}-active":
            lane_summaries.append(
                ProgramLoopLaneSummary(
                    lane_index=cycle_index,
                    lane_id=current_lane.lane_id,
                    family=family,
                    hypothesis_class=current_lane.hypothesis_class,
                    seed_candidate_id=current_lane.seed_candidate_id,
                    queue_kind=current_lane.queue_kind,
                    seed_campaign_id=current_parent_campaign_id if current_parent_campaign_id and current_parent_campaign_id.endswith("-seed") else None,
                    initial_parent_campaign_id=lane_initial_parent,
                    final_parent_campaign_id=loop_report.final_parent_campaign_id,
                    governed_loop_report_path=loop_report.report_path,
                    status=loop_report.status,
                    stop_reason=loop_report.stop_reason,
                    stop_class=loop_report.stop_class,
                    transition_status=transition_status,
                    transition_intent=_transition_intent_from_status(transition_status),
                )
            )

        carry_forward_parent_campaign_id = loop_report.final_parent_campaign_id
        if transition_status == "continue_lane":
            current_parent_campaign_id = loop_report.final_parent_campaign_id
            if current_lane is None:
                current_lane = _active_lane_placeholder(family=family)
            continue
        if transition_status == "move_to_next_lane":
            current_parent_campaign_id = None
            current_lane = None
            continue
        current_parent_campaign_id = loop_report.final_parent_campaign_id
        break
    else:
        stop_reason = "program_loop_max_cycles_reached"
        stop_class = "budget_exhausted"

    report = ProgramLoopReport(
        program_id=program_identifier,
        family=family,
        initial_parent_campaign_id=parent_campaign_id,
        final_parent_campaign_id=current_parent_campaign_id or carry_forward_parent_campaign_id,
        executed_lanes=len(seeded_lane_ids) if seeded_lane_ids else len({summary.lane_id for summary in lane_summaries}),
        max_lanes=lane_budget,
        status="completed" if lane_summaries else "stopped",
        stop_reason=stop_reason,
        stop_class=stop_class,
        transition_intent=_transition_intent_from_status(
            lane_summaries[-1].transition_status if lane_summaries else "hard_stop"
        ),
        lane_summaries=lane_summaries,
        final_audit_report_path=final_audit_report_path,
        policy_snapshot_hash=policy_snapshot_hash(settings),
        report_path=report_path,
    )
    write_json(report_path, report.model_dump(mode="json"))
    finalize_goblin_run_record(settings, run_record, notes=[f"status={report.status}", f"stop_reason={report.stop_reason}"])
    return report


def _active_lane_placeholder(*, family: str) -> ProgramLanePolicy:
    return ProgramLanePolicy(
        lane_id=f"{family}-active",
        family=family,
        hypothesis_class="active_lane",
        seed_candidate_id="",
        queue_kind="promotion",
        max_steps=8,
        notes=["Program loop placeholder for an already active lane."],
    )


def _next_pending_lane(
    settings: Settings,
    *,
    approved_lanes: list[ProgramLanePolicy],
    executed_lane_ids: set[str],
) -> ProgramLanePolicy | None:
    for lane in approved_lanes:
        if lane.lane_id in executed_lane_ids:
            continue
        if _seed_candidate_archived(settings, lane.seed_candidate_id):
            continue
        report_dir = settings.paths().reports_dir / lane.seed_candidate_id
        if lane.queue_kind == "throughput":
            if not ((report_dir / "candidate.json").exists() or (report_dir / "strategy_spec.json").exists()):
                continue
        elif not (report_dir / "strategy_spec.json").exists():
            continue
        return lane
    return None


def _first_invalid_seed_identity(
    settings: Settings,
    *,
    approved_lanes: list[ProgramLanePolicy],
) -> tuple[str, str] | None:
    for lane in approved_lanes:
        mismatch_reason = _seed_candidate_identity_mismatch(settings, lane=lane)
        if mismatch_reason is not None:
            return lane.lane_id, mismatch_reason
    return None


def _seed_candidate_identity_mismatch(settings: Settings, *, lane: ProgramLanePolicy) -> str | None:
    report_dir = settings.paths().reports_dir / lane.seed_candidate_id
    candidate_path = report_dir / "candidate.json"
    spec_path = report_dir / "strategy_spec.json"
    if not candidate_path.exists() or not spec_path.exists():
        return None

    candidate_payload = read_json(candidate_path)
    spec_payload = read_json(spec_path)
    mismatches: list[str] = []

    candidate_candidate_id = str(candidate_payload.get("candidate_id") or "")
    spec_candidate_id = str(spec_payload.get("candidate_id") or "")
    candidate_family = str(candidate_payload.get("family") or "")
    spec_family = str(spec_payload.get("family") or "")
    candidate_entry_style = str(candidate_payload.get("entry_style") or "")
    spec_entry_style = str(spec_payload.get("entry_style") or "")

    if candidate_candidate_id and candidate_candidate_id != lane.seed_candidate_id:
        mismatches.append("candidate_json_candidate_id")
    if spec_candidate_id and spec_candidate_id != lane.seed_candidate_id:
        mismatches.append("strategy_spec_candidate_id")
    if candidate_family and candidate_family != lane.family:
        mismatches.append("candidate_json_family")
    if spec_family and spec_family != lane.family:
        mismatches.append("strategy_spec_family")
    if candidate_family and spec_family and candidate_family != spec_family:
        mismatches.append("candidate_strategy_family")
    if candidate_entry_style and spec_entry_style and candidate_entry_style != spec_entry_style:
        mismatches.append("candidate_strategy_entry_style")
    if lane.hypothesis_class:
        if candidate_entry_style and candidate_entry_style != lane.hypothesis_class:
            mismatches.append("candidate_json_entry_style")
        if spec_entry_style and spec_entry_style != lane.hypothesis_class:
            mismatches.append("strategy_spec_entry_style")

    if not mismatches:
        return None
    return ",".join(dict.fromkeys(mismatches))


def _historical_terminal_lane_ids(
    settings: Settings,
    *,
    family: str,
    approved_lanes: list[ProgramLanePolicy],
) -> set[str]:
    approved_lane_ids = {lane.lane_id for lane in approved_lanes}
    latest_status_by_lane: dict[str, str] = {}
    for report_path in sorted(settings.paths().program_loops_dir.glob("*.json")):
        try:
            payload = read_json(report_path)
        except json.JSONDecodeError:
            continue
        if str(payload.get("family") or "") != family:
            continue
        for lane_summary in payload.get("lane_summaries") or []:
            lane_id = str(lane_summary.get("lane_id") or "")
            if lane_id not in approved_lane_ids:
                continue
            latest_status_by_lane[lane_id] = str(lane_summary.get("transition_status") or "")
    return {
        lane_id
        for lane_id, transition_status in latest_status_by_lane.items()
        if transition_status in {"move_to_next_lane", "hard_stop"}
    }


def _seed_candidate_archived(settings: Settings, candidate_id: str) -> bool:
    failure_path = settings.paths().observational_knowledge_dir / "failure_records.jsonl"
    if not failure_path.exists():
        return False
    for line in failure_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if str(payload.get("candidate_id") or "") != candidate_id:
            continue
        decision = str((payload.get("details") or {}).get("decision") or "")
        if decision.startswith("archive_"):
            return True
    return False


def _seed_program_lane(
    settings: Settings,
    *,
    lane: ProgramLanePolicy,
    parent_campaign_id: str | None,
) -> str:
    campaign_id = next_campaign_id(settings, suffix=f"-{lane.lane_id}-seed")
    parent_id = parent_campaign_id or _latest_completed_campaign_id(settings, family=lane.family)
    campaign_dir = settings.paths().campaigns_dir / campaign_id
    refresh_required = lane.queue_kind == "promotion" and _seed_requires_execution_refresh(settings, lane.seed_candidate_id)
    step_type = "formalize_rule_candidate" if lane.queue_kind == "throughput" else ("mutate_one_candidate" if refresh_required else "re_evaluate_one_candidate")
    allowed_step_types = [step_type]
    spec = CampaignSpec(
        campaign_id=campaign_id,
        family=lane.family,
        baseline_candidate_id=lane.seed_candidate_id,
        target_candidate_ids=[lane.seed_candidate_id],
        parent_campaign_id=parent_id,
        queue_kind=lane.queue_kind,
        throughput_target_count=lane.throughput_target_count,
        orthogonality_metadata=lane.orthogonality_metadata.model_dump(mode="json") if lane.orthogonality_metadata else {},
        compile_budget=lane.compile_budget,
        smoke_budget=lane.smoke_budget,
        max_rule_spec_reformulations_per_hypothesis=lane.max_rule_spec_reformulations_per_hypothesis,
        max_ea_spec_rewrites_per_candidate=lane.max_ea_spec_rewrites_per_candidate,
        max_compile_retries_per_candidate=lane.max_compile_retries_per_candidate,
        max_smoke_retries_per_candidate=lane.max_smoke_retries_per_candidate,
        step_type=step_type,
        allowed_step_types=allowed_step_types,
        max_iterations=1,
        max_new_candidates=1,
        trial_cap_per_family=1,
        stop_on_review_eligible_provisional=False,
        notes=[
            "Program-loop bounded seed campaign.",
            f"Approved lane: {lane.lane_id}.",
            (
                "Throughput lane starts from deterministic rule formalization and MT5 executability checks."
                if lane.queue_kind == "throughput"
                else (
                    "Seed candidate requires execution-cost refresh before reevaluation."
                    if refresh_required
                    else "Seed candidate already matches the current execution-cost contract; reevaluate directly."
                )
            ),
            *lane.notes,
        ],
    )
    state = CampaignState(
        campaign_id=campaign_id,
        family=lane.family,
        status="completed",
        baseline_candidate_id=lane.seed_candidate_id,
        parent_campaign_id=parent_id,
        current_step_type=step_type,
        active_candidate_ids=[lane.seed_candidate_id],
        stop_reason="program_seed_requested",
        state_path=campaign_dir / "state.json",
        updated_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    recommendation = _seed_recommendation(lane, refresh_required=refresh_required)
    write_json(campaign_dir / "spec.json", spec.model_dump(mode="json"))
    write_json(state.state_path, state.model_dump(mode="json"))
    write_json(campaign_dir / "next_recommendations.json", [recommendation])
    return campaign_id


def _seed_recommendation(lane: ProgramLanePolicy, *, refresh_required: bool) -> dict[str, object]:
    if lane.queue_kind == "throughput":
        return {
            "candidate_id": lane.seed_candidate_id,
            "evidence_status": "supported",
            "step_type": "formalize_rule_candidate",
            "rationale": (
                f"{lane.seed_candidate_id} is an approved throughput root for {lane.hypothesis_class}. "
                "Start by freezing a deterministic rule specification before EA-spec generation, compile, and MT5 smoke."
            ),
            "step_payload": {
                "source_candidate_id": lane.seed_candidate_id,
                "queue_kind": lane.queue_kind,
            },
            "binding": True,
        }
    if refresh_required:
        return {
            "candidate_id": lane.seed_candidate_id,
            "evidence_status": "supported",
            "step_type": "mutate_one_candidate",
            "rationale": (
                f"{lane.seed_candidate_id} should be refreshed to the current governed execution-cost defaults "
                f"before {lane.hypothesis_class} lane evaluation."
            ),
            "step_payload": {
                "mutation_type": "refresh_execution_cost_defaults",
                "source_candidate_id": lane.seed_candidate_id,
                "refresh_reason": (
                    f"align {lane.seed_candidate_id} to the current {lane.family} execution-cost contract before "
                    f"{lane.hypothesis_class} lane evaluation"
                ),
            },
            "binding": True,
        }
    return {
        "candidate_id": lane.seed_candidate_id,
        "evidence_status": "supported",
        "step_type": "re_evaluate_one_candidate",
        "rationale": (
            f"{lane.seed_candidate_id} already matches the current governed execution-cost contract. "
            f"Re-evaluate it directly before {lane.hypothesis_class} lane progression."
        ),
        "step_payload": {
            "source_candidate_id": lane.seed_candidate_id,
            "stale_packet_policy": "reuse_current_contract_root",
        },
        "binding": True,
    }


def _seed_requires_execution_refresh(settings: Settings, candidate_id: str) -> bool:
    report_dir = settings.paths().reports_dir / candidate_id
    spec_path = report_dir / "strategy_spec.json"
    if not spec_path.exists():
        return True

    spec_payload = read_json(spec_path)
    candidate_path = report_dir / "candidate.json"
    session_focus = str(
        ((read_json(candidate_path).get("market_context") or {}).get("session_focus"))
        if candidate_path.exists()
        else ((spec_payload.get("execution_cost_model") or {}).get("liquidity_session_assumption") or "")
    )
    if not session_focus:
        return True

    cost_defaults = default_execution_cost_fields(
        settings,
        family=str(spec_payload.get("family") or "scalping"),
        session_focus=session_focus,
    )
    cost_model = spec_payload.get("cost_model") or {}
    execution_cost_model = spec_payload.get("execution_cost_model") or {}
    return not all(
        cost_model.get(key) == value and execution_cost_model.get(key) == value
        for key, value in cost_defaults.items()
    )


def _latest_completed_campaign_id(settings: Settings, *, family: str) -> str | None:
    states: list[CampaignState] = []
    for state_path in settings.paths().campaigns_dir.glob("*/state.json"):
        payload = read_json(state_path)
        state = CampaignState.model_validate(payload)
        if state.family == family and state.status == "completed":
            states.append(state)
    if not states:
        return None
    return max(states, key=lambda item: item.updated_utc).campaign_id


def _load_final_program_report(report_path: Path | None) -> NextStepControllerReport | None:
    if report_path is None or not Path(report_path).exists():
        return None
    return NextStepControllerReport.model_validate(read_json(Path(report_path)))


def _campaign_transition_status(settings: Settings, campaign_id: str | None) -> str | None:
    if not campaign_id:
        return None
    state_path = settings.paths().campaigns_dir / campaign_id / "state.json"
    if not state_path.exists():
        return None
    state_payload = read_json(state_path)
    report_path = state_payload.get("last_report_path")
    if not report_path:
        return None
    report_file = Path(report_path)
    if not report_file.exists():
        return None
    payload = read_json(report_file)
    if payload.get("selected_step_type") == "data_feature_audit":
        audit_payloads = payload.get("data_feature_audit_reports") or []
        if audit_payloads and str(audit_payloads[0].get("family_decision") or "") in {
            "retire_family",
            "bounded_correction_supported",
        }:
            return "continue_lane"
    if (
        payload.get("selected_step_type") == "diagnose_existing_candidates"
        and str(payload.get("stop_reason") or "") == "diagnosis_ambiguous_no_mutation_justified"
    ):
        candidate_reports = payload.get("candidate_reports") or []
        if candidate_reports and all(
            not report.get("supported_slices") and not report.get("recommended_mutation")
            for report in candidate_reports
        ):
            return "continue_lane"
    if payload.get("selected_step_type") == "data_regime_audit":
        audit_payloads = payload.get("data_regime_audit_reports") or []
        if audit_payloads:
            lane_decision = str(audit_payloads[0].get("lane_decision") or "")
            if lane_decision == "narrow_correction_supported":
                return "continue_lane"
            if lane_decision in {"retire_lane", "structural_regime_instability"}:
                return "move_to_next_lane"
    if payload.get("selected_step_type") == "data_label_audit":
        return "hard_stop"
    transition_status = payload.get("transition_status")
    if transition_status:
        return str(transition_status)
    stop_reason = str(payload.get("stop_reason") or "")
    if "retire_lane" in stop_reason or "structural_regime_instability" in stop_reason:
        return "move_to_next_lane"
    if "hold_reference_blocked_by_robustness" in stop_reason or "lane_exhausted" in stop_reason:
        return "continue_lane"
    return "hard_stop"


def _transition_intent_from_status(status: str | None) -> str:
    if status == "continue_lane":
        return "advance_same_lane"
    if status == "move_to_next_lane":
        return "advance_next_lane"
    return "stop_terminal"


def _family_requires_post_queue_audit(approved_lanes: list[ProgramLanePolicy]) -> bool:
    return any(lane.queue_kind == "promotion" for lane in approved_lanes)


def _first_retired_throughput_archetype(
    settings: Settings,
    *,
    approved_lanes: list[ProgramLanePolicy],
) -> tuple[str, str, int] | None:
    if not settings.program.archetype_retirement_enabled:
        return None
    threshold = max(int(settings.program.archetype_retirement_failure_threshold or 0), 1)
    for lane in approved_lanes:
        if lane.queue_kind != "throughput":
            continue
        seed_profile = _load_seed_profile(settings, lane.seed_candidate_id)
        if seed_profile is None:
            continue
        failure_count = _terminal_failure_count_for_seed_profile(settings, seed_profile)
        if failure_count >= threshold:
            return lane.lane_id, seed_profile["entry_style"], failure_count
    return None


def _first_missing_family_evidence_lane(
    settings: Settings,
    *,
    approved_lanes: list[ProgramLanePolicy],
) -> tuple[str, list[str]] | None:
    if not settings.program.family_evidence_guard_enabled:
        return None
    for lane in approved_lanes:
        if lane.queue_kind != "throughput" or not lane.required_evidence_tags:
            continue
        seed_profile = _load_seed_profile(settings, lane.seed_candidate_id)
        if seed_profile is None:
            continue
        available_tags = {str(tag).strip() for tag in seed_profile.get("evidence_tags") or () if str(tag).strip()}
        missing_tags = [tag for tag in lane.required_evidence_tags if tag not in available_tags]
        if missing_tags:
            return lane.lane_id, missing_tags
    return None


def _first_low_novelty_throughput_lane(
    settings: Settings,
    *,
    approved_lanes: list[ProgramLanePolicy],
) -> tuple[str, str, float] | None:
    if not settings.program.novelty_guard_enabled:
        return None
    archived_profiles = _archived_seed_profiles(settings)
    if not archived_profiles:
        return None
    threshold = float(settings.program.novelty_similarity_threshold or 0.8)
    for lane in approved_lanes:
        if lane.queue_kind != "throughput":
            continue
        seed_profile = _load_seed_profile(settings, lane.seed_candidate_id)
        if seed_profile is None:
            continue
        closest_match: tuple[str, float] | None = None
        for archived_profile in archived_profiles:
            if archived_profile["candidate_id"] == lane.seed_candidate_id:
                continue
            similarity_score = _seed_profile_similarity(seed_profile, archived_profile)
            if closest_match is None or similarity_score > closest_match[1]:
                closest_match = (archived_profile["candidate_id"], similarity_score)
        if closest_match and closest_match[1] >= threshold:
            return lane.lane_id, closest_match[0], closest_match[1]
    return None


def _terminal_failure_count_for_seed_profile(settings: Settings, seed_profile: dict[str, object]) -> int:
    archived_profiles: dict[str, dict[str, object]] = {}
    similarity_floor = max(float(settings.program.novelty_similarity_threshold or 0.0), 0.8)
    for failure_payload in _iter_recent_failure_payloads(settings):
        decision = str((failure_payload.get("details") or {}).get("decision") or "")
        if decision not in {
            "retire_lane",
            "retire_family",
            "family_retire_confirmed",
            "structural_regime_instability",
            "upstream_contract_change_required",
        }:
            continue
        candidate_id = str(failure_payload.get("candidate_id") or "")
        if not candidate_id or candidate_id in archived_profiles:
            continue
        failed_profile = _load_seed_profile(settings, candidate_id)
        if failed_profile is None:
            continue
        archived_profiles[candidate_id] = failed_profile
    return sum(
        1
        for archived_profile in archived_profiles.values()
        if _seed_profile_similarity(seed_profile, archived_profile) >= similarity_floor
    )


def _archived_seed_profiles(settings: Settings) -> list[dict[str, object]]:
    profiles: list[dict[str, object]] = []
    seen_candidate_ids: set[str] = set()
    for failure_payload in _iter_recent_failure_payloads(settings):
        decision = str((failure_payload.get("details") or {}).get("decision") or "")
        if not decision or not (
            decision.startswith("archive_")
            or decision
            in {
                "retire_lane",
                "retire_family",
                "family_retire_confirmed",
                "structural_regime_instability",
                "hold_reference_blocked_by_robustness",
                "stop_lane_keep_reference_branch",
                "upstream_contract_change_required",
            }
        ):
            continue
        candidate_id = str(failure_payload.get("candidate_id") or "")
        if not candidate_id or candidate_id in seen_candidate_ids:
            continue
        seed_profile = _load_seed_profile(settings, candidate_id)
        if seed_profile is None:
            continue
        seen_candidate_ids.add(candidate_id)
        profiles.append(seed_profile)
    return profiles


def _iter_recent_failure_payloads(settings: Settings) -> list[dict[str, object]]:
    failure_path = settings.paths().observational_knowledge_dir / "failure_records.jsonl"
    if not failure_path.exists():
        return []
    payloads: list[dict[str, object]] = []
    cutoff = datetime.now(UTC).timestamp() - (max(int(settings.program.archetype_retirement_lookback_days or 0), 1) * 86_400)
    for line in failure_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        recorded_utc = str(payload.get("recorded_utc") or "")
        try:
            recorded_ts = datetime.fromisoformat(recorded_utc.replace("Z", "+00:00")).timestamp()
        except ValueError:
            recorded_ts = 0.0
        if recorded_ts < cutoff:
            continue
        payloads.append(payload)
    return payloads


def _load_seed_profile(settings: Settings, candidate_id: str) -> dict[str, object] | None:
    report_dir = settings.paths().reports_dir / candidate_id
    candidate_path = report_dir / "candidate.json"
    spec_path = report_dir / "strategy_spec.json"
    if not candidate_path.exists() and not spec_path.exists():
        return None

    candidate_payload = read_json(candidate_path) if candidate_path.exists() else {}
    spec_payload = read_json(spec_path) if spec_path.exists() else {}
    candidate = None
    if candidate_payload:
        try:
            candidate = CandidateDraft.model_validate(candidate_payload)
        except Exception:  # noqa: BLE001
            candidate = None
    if candidate is not None:
        allowed_hours = tuple(sorted(candidate.market_context.allowed_hours_utc))
        custom_filters = tuple(
            sorted(
                f"{str(item.get('name') or '').strip()}={str(item.get('rule') or '').strip()}"
                for item in candidate.custom_filters
                if str(item.get("name") or "").strip()
            )
        )
        side_policy = candidate.market_context.directional_bias
        news_blackout = bool(candidate.enable_news_blackout)
        entry_style = candidate.entry_style
        holding_bars = int(candidate.holding_bars)
        stop_loss_pips = float(candidate.stop_loss_pips)
        take_profit_pips = float(candidate.take_profit_pips)
        evidence_tags = tuple(sorted(candidate.market_rationale.evidence_tags))
    else:
        session_policy = spec_payload.get("session_policy") or {}
        market_context = candidate_payload.get("market_context") or {}
        filters = candidate_payload.get("custom_filters") or spec_payload.get("filters") or []
        market_rationale = candidate_payload.get("market_rationale") or spec_payload.get("market_rationale") or {}
        inferred_candidate_evidence_tags: tuple[str, ...] = ()
        if candidate_payload:
            try:
                inferred_candidate_evidence_tags = tuple(
                    CandidateDraft.model_validate(candidate_payload).market_rationale.evidence_tags
                )
            except Exception:  # noqa: BLE001
                inferred_candidate_evidence_tags = ()
        allowed_hours = tuple(
            sorted(
                int(item)
                for item in (
                    market_context.get("allowed_hours_utc")
                    or session_policy.get("allowed_hours_utc")
                    or []
                )
            )
        )
        custom_filters = tuple(
            sorted(
                f"{str(item.get('name') or '').strip()}={str(item.get('rule') or '').strip()}"
                for item in filters
                if str(item.get("name") or "").strip()
            )
        )
        side_policy = str(
            market_context.get("directional_bias")
            or spec_payload.get("side_policy")
            or "both"
        )
        news_blackout = bool(
            candidate_payload.get("enable_news_blackout")
            or (spec_payload.get("news_policy") or {}).get("enabled")
        )
        entry_style = str(candidate_payload.get("entry_style") or spec_payload.get("entry_style") or "")
        holding_bars = int(candidate_payload.get("holding_bars") or spec_payload.get("holding_bars") or 0)
        stop_loss_pips = float(candidate_payload.get("stop_loss_pips") or spec_payload.get("stop_loss_pips") or 0.0)
        take_profit_pips = float(candidate_payload.get("take_profit_pips") or spec_payload.get("take_profit_pips") or 0.0)
        evidence_tags = tuple(
            sorted(
                {
                    str(tag).strip()
                    for tag in (
                        (market_rationale.get("evidence_tags") or [])
                        + list(inferred_candidate_evidence_tags)
                    )
                    if str(tag).strip()
                }
            )
        )

    if not entry_style:
        return None
    rr_ratio = round((take_profit_pips / stop_loss_pips), 3) if stop_loss_pips > 0 else 0.0
    return {
        "candidate_id": candidate_id,
        "family": str(candidate_payload.get("family") or spec_payload.get("family") or ""),
        "entry_style": entry_style,
        "allowed_hours": allowed_hours,
        "filter_signature": custom_filters,
        "holding_profile": _holding_profile_bucket(holding_bars),
        "risk_reward_ratio": rr_ratio,
        "news_blackout": news_blackout,
        "side_policy": side_policy,
        "evidence_tags": evidence_tags,
    }


def _seed_profile_similarity(left: dict[str, object], right: dict[str, object]) -> float:
    family_similarity = 1.0 if left.get("family") and left.get("family") == right.get("family") else 0.0
    entry_style_match = 1.0 if left["entry_style"] == right["entry_style"] else 0.0
    hours_similarity = _jaccard_similarity(left["allowed_hours"], right["allowed_hours"])
    filter_similarity = _jaccard_similarity(left["filter_signature"], right["filter_signature"])
    evidence_similarity = _jaccard_similarity(left["evidence_tags"], right["evidence_tags"])
    holding_similarity = 1.0 if left["holding_profile"] == right["holding_profile"] else 0.0
    risk_reward_similarity = max(
        0.0,
        1.0 - min(abs(float(left["risk_reward_ratio"]) - float(right["risk_reward_ratio"])), 1.5) / 1.5,
    )
    news_similarity = 1.0 if left["news_blackout"] == right["news_blackout"] else 0.0
    side_similarity = 1.0 if left["side_policy"] == right["side_policy"] else 0.0
    return (
        (0.25 * entry_style_match)
        + (0.15 * hours_similarity)
        + (0.20 * filter_similarity)
        + (0.15 * family_similarity)
        + (0.10 * holding_similarity)
        + (0.10 * risk_reward_similarity)
        + (0.05 * evidence_similarity)
        + (0.03 * news_similarity)
        + (0.02 * side_similarity)
    )


def _jaccard_similarity(left: object, right: object) -> float:
    left_set = {str(item) for item in (left or [])}
    right_set = {str(item) for item in (right or [])}
    if not left_set and not right_set:
        return 1.0
    union = left_set | right_set
    if not union:
        return 1.0
    return len(left_set & right_set) / len(union)


def _holding_profile_bucket(holding_bars: int) -> str:
    if holding_bars <= 24:
        return "short_intraday"
    if holding_bars <= 96:
        return "medium_intraday"
    return "extended_intraday"
