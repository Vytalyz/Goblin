from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from agentic_forex.approval.service import approval_status, issue_machine_approval
from agentic_forex.campaigns.program_loop import run_program_loop
from agentic_forex.config import Settings
from agentic_forex.goblin.controls import (
    enforce_strategy_governance,
    finalize_goblin_run_record,
    start_goblin_run_record,
)
from agentic_forex.goblin.models import GoblinRunRecord
from agentic_forex.governance.control_plane import (
    acquire_lease,
    append_event,
    authoritative_state_snapshot_hash,
    campaign_state_version,
    heartbeat_lease,
    latest_evaluation_revision,
    load_idempotency_record,
    policy_snapshot_hash,
    record_idempotency_result,
    release_lease,
    stable_hash,
    write_incident,
)
from agentic_forex.governance.models import (
    AutonomousManagerCycleSummary,
    AutonomousManagerReport,
    IntegrityIncident,
    OperatorSafetyEnvelope,
    ProgramEvent,
    ProgramLoopReport,
    ReproducibilityManifest,
)
from agentic_forex.mt5.models import MT5Packet
from agentic_forex.mt5.service import load_latest_mt5_validation
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows.contracts import StrategySpec


def run_autonomous_manager(
    settings: Settings,
    *,
    family: str = "scalping",
    parent_campaign_id: str | None = None,
    program_id: str | None = None,
    manager_run_id: str | None = None,
    max_cycles: int | None = None,
) -> AutonomousManagerReport:
    enforce_strategy_governance(settings, family=family)
    manager_identifier = manager_run_id or f"manager-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    program_identifier = program_id or f"{manager_identifier}-program"
    report_path = settings.paths().autonomous_manager_dir / f"{manager_identifier}.json"
    run_record = start_goblin_run_record(
        run_id=manager_identifier,
        entrypoint="run_autonomous_manager",
        family=family,
        campaign_id=parent_campaign_id,
    )
    policy_hash = policy_snapshot_hash(settings)
    cycle_budget = max_cycles or settings.autonomy.max_cycles_per_manager_run
    request_payload = {
        "family": family,
        "parent_campaign_id": parent_campaign_id,
        "program_id": program_identifier,
        "max_cycles": cycle_budget,
        "policy_snapshot_hash": policy_hash,
    }
    idempotency_key = f"autonomous_manager:{manager_identifier}"
    payload_fingerprint = stable_hash(request_payload)
    existing = load_idempotency_record(settings, idempotency_key)
    if existing is not None:
        if existing.payload_fingerprint != payload_fingerprint:
            return _integrity_exception_report(
                settings,
                manager_run_id=manager_identifier,
                program_id=program_identifier,
                family=family,
                parent_campaign_id=parent_campaign_id,
                policy_hash=policy_hash,
                report_path=report_path,
                exception_class="idempotency_conflict",
                attempted_action="run_autonomous_manager",
                related_ids={"idempotency_key": idempotency_key},
            )
        if existing.outcome_path and Path(existing.outcome_path).exists():
            return AutonomousManagerReport.model_validate(read_json(Path(existing.outcome_path)))

    current_parent_campaign_id = parent_campaign_id
    cycle_summaries: list[AutonomousManagerCycleSummary] = []
    repeated_stop_reason: str | None = None
    repeated_stop_count = 0
    same_candidate: str | None = None
    same_candidate_count = 0
    no_material_transition_cycles = 0

    for cycle_index in range(1, cycle_budget + 1):
        lane_id = _resolve_lane_id(current_parent_campaign_id)
        previous_parent_campaign_id = current_parent_campaign_id
        lease_key = f"{program_identifier}:{family}:{lane_id}"
        try:
            lease = acquire_lease(
                settings,
                lease_key=lease_key,
                owner_id="autonomous_manager",
                manager_run_id=manager_identifier,
                policy_hash=policy_hash,
                state_version_at_acquire=campaign_state_version(settings, current_parent_campaign_id),
                ttl_seconds=settings.autonomy.lease_ttl_seconds,
            )
        except PermissionError:
            return _integrity_exception_report(
                settings,
                manager_run_id=manager_identifier,
                program_id=program_identifier,
                family=family,
                parent_campaign_id=current_parent_campaign_id,
                policy_hash=policy_hash,
                report_path=report_path,
                exception_class="lease_conflict",
                attempted_action="acquire_lease",
                related_ids={"lease_key": lease_key},
            )

        append_event(
            settings,
            ProgramEvent(
                event_type="lease_acquired",
                family=family,
                campaign_id=current_parent_campaign_id,
                details={"lease_key": lease_key, "fencing_token": lease.fencing_token},
            ),
        )
        try:
            program_report = run_program_loop(
                settings,
                family=family,
                parent_campaign_id=current_parent_campaign_id,
                program_id=f"{program_identifier}-cycle-{cycle_index:02d}",
                max_lanes=settings.program.max_lanes_per_run,
            )
            heartbeat_lease(
                settings,
                lease_key=lease_key,
                owner_id="autonomous_manager",
                fencing_token=lease.fencing_token,
                ttl_seconds=settings.autonomy.lease_ttl_seconds,
            )
            final_report = _load_final_report(settings, program_report)
            current_parent_campaign_id = program_report.final_parent_campaign_id

            approvals_issued = _maybe_issue_machine_approvals(
                settings,
                final_report=final_report,
                policy_hash=policy_hash,
                manager_run_id=manager_identifier,
                cycle_index=cycle_index,
            )
            material_transition = _material_transition(
                program_report,
                approvals_issued,
                previous_parent_campaign_id=previous_parent_campaign_id,
            )
            no_material_transition_cycles = 0 if material_transition else no_material_transition_cycles + 1

            candidate_id = _candidate_from_report(final_report)
            if candidate_id and candidate_id == same_candidate and not material_transition:
                same_candidate_count += 1
            else:
                same_candidate_count = 1 if candidate_id else 0
            same_candidate = candidate_id
            repeated_stop_count = repeated_stop_count + 1 if program_report.stop_reason == repeated_stop_reason else 1
            repeated_stop_reason = program_report.stop_reason

            cycle_summaries.append(
                AutonomousManagerCycleSummary(
                    cycle_index=cycle_index,
                    lane_id=lane_id,
                    program_report_path=program_report.report_path,
                    stop_reason=program_report.stop_reason,
                    stop_class=program_report.stop_class,
                    material_transition=material_transition,
                    approvals_issued=approvals_issued,
                )
            )

            if approvals_issued:
                _append_approval_events(
                    settings,
                    family=family,
                    candidate_id=candidate_id,
                    campaign_id=current_parent_campaign_id,
                    stages=approvals_issued,
                )
                continue

            handoff = _maybe_build_ea_test_ready_handoff(settings, final_report=final_report, policy_hash=policy_hash)
            if handoff is not None:
                return _finalize_manager_report(
                    settings,
                    report=AutonomousManagerReport(
                        manager_run_id=manager_identifier,
                        program_id=program_identifier,
                        family=family,
                        initial_parent_campaign_id=parent_campaign_id,
                        final_parent_campaign_id=current_parent_campaign_id,
                        executed_cycles=len(cycle_summaries),
                        max_cycles=cycle_budget,
                        status="completed",
                        stop_reason="ea_test_ready",
                        stop_class="ea_test_ready",
                        terminal_boundary="ea_test_ready",
                        policy_snapshot_hash=policy_hash,
                        cycle_summaries=cycle_summaries,
                        notification_required=True,
                        notification_reason="ea_test_ready",
                        handoff_candidate_id=handoff["candidate_id"],
                        handoff_artifact_paths=handoff["artifact_paths"],
                        report_path=report_path,
                    ),
                    idempotency_key=idempotency_key,
                    payload_fingerprint=payload_fingerprint,
                    manager_run_id=manager_identifier,
                    event_type="ea_test_ready",
                    event_candidate_id=handoff["candidate_id"],
                    run_record=run_record,
                )

            if _program_cycle_can_resume(program_report, final_report):
                continue

            watchdog_boundary = _watchdog_boundary(
                settings,
                manager_run_id=manager_identifier,
                program_id=program_identifier,
                family=family,
                parent_campaign_id=current_parent_campaign_id,
                policy_hash=policy_hash,
                report_path=report_path,
                cycle_budget=cycle_budget,
                cycle_summaries=cycle_summaries,
                no_material_transition_cycles=no_material_transition_cycles,
                repeated_stop_reason=repeated_stop_reason,
                repeated_stop_count=repeated_stop_count,
                same_candidate_count=same_candidate_count,
            )
            if watchdog_boundary is not None:
                return _finalize_manager_report(
                    settings,
                    report=watchdog_boundary,
                    idempotency_key=idempotency_key,
                    payload_fingerprint=payload_fingerprint,
                    manager_run_id=manager_identifier,
                    event_type="blocked_no_authorized_path",
                    event_candidate_id=candidate_id,
                    run_record=run_record,
                )

            terminal_boundary, stop_class, stop_reason = _map_program_terminal_boundary(program_report, final_report)
            if terminal_boundary is not None:
                return _finalize_manager_report(
                    settings,
                    report=AutonomousManagerReport(
                        manager_run_id=manager_identifier,
                        program_id=program_identifier,
                        family=family,
                        initial_parent_campaign_id=parent_campaign_id,
                        final_parent_campaign_id=current_parent_campaign_id,
                        executed_cycles=len(cycle_summaries),
                        max_cycles=cycle_budget,
                        status="stopped",
                        stop_reason=stop_reason,
                        stop_class=stop_class,
                        terminal_boundary=terminal_boundary,
                        policy_snapshot_hash=policy_hash,
                        cycle_summaries=cycle_summaries,
                        notification_required=True,
                        notification_reason=terminal_boundary,
                        report_path=report_path,
                    ),
                    idempotency_key=idempotency_key,
                    payload_fingerprint=payload_fingerprint,
                    manager_run_id=manager_identifier,
                    event_type=terminal_boundary,
                    event_candidate_id=candidate_id,
                    run_record=run_record,
                )
        finally:
            release_lease(
                settings,
                lease_key=lease_key,
                owner_id="autonomous_manager",
                fencing_token=lease.fencing_token,
            )

    return _finalize_manager_report(
        settings,
        report=AutonomousManagerReport(
            manager_run_id=manager_identifier,
            program_id=program_identifier,
            family=family,
            initial_parent_campaign_id=parent_campaign_id,
            final_parent_campaign_id=current_parent_campaign_id,
            executed_cycles=len(cycle_summaries),
            max_cycles=cycle_budget,
            status="stopped",
            stop_reason="autonomous_manager_max_cycles_reached",
            stop_class="blocked_budget",
            terminal_boundary="blocked_no_authorized_path",
            policy_snapshot_hash=policy_hash,
            cycle_summaries=cycle_summaries,
            notification_required=True,
            notification_reason="blocked_no_authorized_path",
            report_path=report_path,
        ),
        idempotency_key=idempotency_key,
        payload_fingerprint=payload_fingerprint,
        manager_run_id=manager_identifier,
        event_type="blocked_no_authorized_path",
        event_candidate_id=same_candidate,
        run_record=run_record,
    )


def _load_final_report(settings: Settings, program_report: ProgramLoopReport):
    if program_report.final_audit_report_path and Path(program_report.final_audit_report_path).exists():
        from agentic_forex.governance.models import NextStepControllerReport

        return NextStepControllerReport.model_validate(read_json(Path(program_report.final_audit_report_path)))
    if not program_report.final_parent_campaign_id:
        return None
    report_path = settings.paths().campaigns_dir / program_report.final_parent_campaign_id / "next_step_report.json"
    if not report_path.exists():
        return None
    from agentic_forex.governance.models import NextStepControllerReport

    return NextStepControllerReport.model_validate(read_json(report_path))


def _resolve_lane_id(parent_campaign_id: str | None) -> str:
    return parent_campaign_id or "policy_queue"


def _candidate_from_report(final_report) -> str | None:
    if final_report is None:
        return None
    if final_report.next_recommendations:
        for recommendation in final_report.next_recommendations:
            if recommendation.candidate_id:
                return recommendation.candidate_id
    if final_report.forward_reports:
        return final_report.forward_reports[0].candidate_id
    if final_report.reevaluation_reports:
        return final_report.reevaluation_reports[0].candidate_id
    if final_report.candidate_scope:
        return final_report.candidate_scope[0]
    return None


def _append_approval_events(
    settings: Settings,
    *,
    family: str,
    candidate_id: str | None,
    campaign_id: str | None,
    stages: list[str],
) -> None:
    for stage in stages:
        append_event(
            settings,
            ProgramEvent(
                event_type="approval_issued",
                family=family,
                candidate_id=candidate_id,
                campaign_id=campaign_id,
                details={"stage": stage},
            ),
        )


def _material_transition(
    program_report: ProgramLoopReport,
    approvals_issued: list[str],
    *,
    previous_parent_campaign_id: str | None,
) -> bool:
    return bool(
        program_report.executed_lanes
        or program_report.lane_summaries
        or program_report.final_audit_report_path
        or approvals_issued
        or program_report.final_parent_campaign_id != previous_parent_campaign_id
    )


def _program_cycle_can_resume(program_report: ProgramLoopReport, final_report) -> bool:
    if (
        program_report.stop_reason == "program_loop_max_cycles_reached"
        and final_report is not None
        and (final_report.auto_continue_allowed or final_report.transition_status == "continue_lane")
    ):
        return True
    return (
        program_report.stop_reason == "program_loop_max_lanes_reached"
        and program_report.transition_intent == "advance_next_lane"
        and program_report.executed_lanes > 0
    )


def _maybe_issue_machine_approvals(
    settings: Settings,
    *,
    final_report,
    policy_hash: str,
    manager_run_id: str,
    cycle_index: int,
) -> list[str]:
    if final_report is None or final_report.stop_class != "approval_required":
        return []
    if final_report.recommended_follow_on_step != "run_parity":
        return []
    candidate_id = _candidate_from_report(final_report)
    if not candidate_id or not _candidate_is_parity_ready(candidate_id, settings):
        return []
    issued: list[str] = []
    evidence_paths = _machine_approval_evidence_paths(candidate_id, settings)
    for stage in ("mt5_packet", "mt5_parity_run", "mt5_validation"):
        if stage not in settings.autonomy.machine_approvable_stages:
            continue
        status = approval_status(candidate_id, stage, settings, current_policy_snapshot_hash=policy_hash)
        if status["approved"] and status["fresh"] and not status["superseded"]:
            continue
        issue_machine_approval(
            candidate_id,
            stage,
            settings,
            evidence_paths=evidence_paths,
            rationale=(
                f"Autonomous manager issued {stage} after {candidate_id} cleared the research-stage parity gate."
            ),
            idempotency_key=f"{manager_run_id}:{cycle_index}:{candidate_id}:{stage}",
        )
        issued.append(stage)
    return issued


def _candidate_is_parity_ready(candidate_id: str, settings: Settings) -> bool:
    review_path = settings.paths().reports_dir / candidate_id / "review_packet.json"
    robustness_path = settings.paths().reports_dir / candidate_id / "robustness_report.json"
    if not review_path.exists() or not robustness_path.exists():
        return False
    review_payload = read_json(review_path)
    metrics = review_payload.get("metrics") or {}
    grades = metrics.get("grades") or {}
    robustness = read_json(robustness_path)
    if int(metrics.get("trade_count") or 0) < settings.validation.minimum_test_trade_count:
        return False
    if float(metrics.get("out_of_sample_profit_factor") or 0.0) < settings.validation.out_of_sample_profit_factor_floor:
        return False
    if float(metrics.get("expectancy_pips") or 0.0) <= settings.validation.expectancy_floor:
        return False
    if not bool(metrics.get("stress_passed")) or not bool(grades.get("walk_forward_ok")):
        return False
    pbo = robustness.get("pbo")
    if pbo is not None and float(pbo) > settings.validation.pbo_threshold:
        return False
    wrc_p = robustness.get("white_reality_check_p_value")
    threshold = (
        robustness.get("white_reality_check_pvalue_threshold")
        or settings.validation.white_reality_check_pvalue_threshold
    )
    if wrc_p is not None and float(wrc_p) > float(threshold):
        return False
    return True


def _maybe_build_ea_test_ready_handoff(
    settings: Settings, *, final_report, policy_hash: str
) -> dict[str, object] | None:
    if final_report is None or final_report.recommended_follow_on_step != "human_review":
        return None
    candidate_id = _candidate_from_report(final_report)
    if not candidate_id or not _candidate_is_ea_test_ready(candidate_id, settings, policy_hash=policy_hash):
        return None
    handoff_dir = settings.paths().reports_dir / candidate_id / "ea_handoff"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    spec = StrategySpec.model_validate(read_json(settings.paths().reports_dir / candidate_id / "strategy_spec.json"))
    safety_envelope = OperatorSafetyEnvelope(
        max_spread_guard_pips=spec.risk_envelope.max_spread_allowed_pips,
        max_slippage_pips=spec.execution_cost_model.slippage_pips,
        max_concurrent_positions=spec.risk_envelope.max_simultaneous_positions,
        max_daily_loss_pct=spec.risk_envelope.max_daily_loss_pct,
        session_no_trade_windows_utc=list(spec.risk_envelope.session_boundaries_utc),
        kill_switch_conditions=list(spec.risk_envelope.kill_switch_conditions),
        broker_session_assumptions=[spec.news_policy.event_source, spec.session_policy.name],
        symbol_spec_assumptions=[spec.instrument, spec.execution_granularity],
        position_sizing_rule=spec.risk_envelope.sizing_rule,
        fail_safe_behaviors=["halt_on_missing_price_ack", "halt_on_missing_order_ack"],
    )
    safety_path = handoff_dir / "operator_safety_envelope.json"
    write_json(safety_path, safety_envelope.model_dump(mode="json"))

    packet = MT5Packet.model_validate(
        read_json(settings.paths().approvals_dir / "mt5_packets" / candidate_id / "packet.json")
    )
    parity_report = load_latest_mt5_validation(candidate_id, settings)
    review_path = settings.paths().reports_dir / candidate_id / "review_packet.json"
    robustness_path = settings.paths().reports_dir / candidate_id / "robustness_report.json"
    forward_path = settings.paths().reports_dir / candidate_id / "forward_stage_report.json"
    provenance_path = settings.paths().reports_dir / candidate_id / "data_provenance.json"
    provenance = read_json(provenance_path)
    manifest = ReproducibilityManifest(
        candidate_id=candidate_id,
        evaluation_revision=max(
            latest_evaluation_revision(candidate_id, "robustness", settings),
            latest_evaluation_revision(candidate_id, "forward_stage", settings),
        ),
        research_contract_version=str(provenance.get("provenance_id") or "unknown"),
        label_contract_version=str(((provenance.get("feature_build") or {}).get("label_version_id")) or "unknown"),
        dataset_snapshot_id=((provenance.get("dataset_snapshot") or {}).get("snapshot_id")),
        feature_version_id=((provenance.get("feature_build") or {}).get("feature_version_id")),
        execution_cost_model_version=str(provenance.get("execution_cost_model_version") or "unknown"),
        policy_snapshot_hash=policy_hash,
        terminal_build=None,
        ea_source_hash=_sha256_file(packet.ea_source_path),
        ex5_hash=_sha256_file(packet.compiled_ex5_path) if packet.compiled_ex5_path else None,
        tester_config_hash=_sha256_file(packet.tester_config_path),
        forward_harness_version="oanda_shadow_v1",
        report_hashes={
            "review_packet": _sha256_file(review_path) or "",
            "robustness_report": _sha256_file(robustness_path) or "",
            "forward_stage_report": _sha256_file(forward_path) or "",
            "mt5_validation_report": _sha256_file(parity_report.report_path) if parity_report else "",
        },
        report_path=handoff_dir / "reproducibility_manifest.json",
    )
    write_json(manifest.report_path, manifest.model_dump(mode="json"))
    return {
        "candidate_id": candidate_id,
        "artifact_paths": {
            "review_packet_path": str(review_path),
            "robustness_report_path": str(robustness_path),
            "forward_stage_report_path": str(forward_path),
            "mt5_validation_report_path": str(parity_report.report_path) if parity_report else "",
            "mt5_packet_path": str(settings.paths().approvals_dir / "mt5_packets" / candidate_id / "packet.json"),
            "operator_safety_envelope_path": str(safety_path),
            "reproducibility_manifest_path": str(manifest.report_path),
            "ea_source_path": str(packet.ea_source_path),
            "compiled_ex5_path": str(packet.compiled_ex5_path) if packet.compiled_ex5_path else "",
            "tester_config_path": str(packet.tester_config_path),
        },
    }


def _candidate_is_ea_test_ready(candidate_id: str, settings: Settings, *, policy_hash: str) -> bool:
    if not _candidate_is_parity_ready(candidate_id, settings):
        return False
    for stage in ("mt5_packet", "mt5_parity_run", "mt5_validation"):
        status = approval_status(candidate_id, stage, settings, current_policy_snapshot_hash=policy_hash)
        if not status["approved"] or not status["fresh"] or status["superseded"]:
            return False
    forward_path = settings.paths().reports_dir / candidate_id / "forward_stage_report.json"
    if not forward_path.exists():
        return False
    forward = read_json(forward_path)
    if not bool(forward.get("passed")):
        return False
    if int(forward.get("trade_count") or 0) < settings.validation.forward_min_trade_count:
        return False
    if int(forward.get("trading_days_observed") or 0) < settings.validation.forward_min_trading_days:
        return False
    if float(forward.get("profit_factor") or 0.0) < settings.validation.forward_profit_factor_floor:
        return False
    if float(forward.get("expectancy_pips") or 0.0) <= settings.validation.forward_expectancy_floor:
        return False
    if (
        float(forward.get("expectancy_degradation_pct") or 100.0)
        > settings.validation.forward_expectancy_degradation_limit_pct
    ):
        return False
    if list(forward.get("risk_violations") or []):
        return False
    robustness = read_json(settings.paths().reports_dir / candidate_id / "robustness_report.json")
    if str(robustness.get("status") or "") != "robustness_passed":
        return False
    packet_path = settings.paths().approvals_dir / "mt5_packets" / candidate_id / "packet.json"
    if not packet_path.exists():
        return False
    packet = MT5Packet.model_validate(read_json(packet_path))
    if not packet.ea_source_path.exists() or not packet.tester_config_path.exists():
        return False
    if packet.compiled_ex5_path is not None and not packet.compiled_ex5_path.exists():
        return False
    parity_report = load_latest_mt5_validation(candidate_id, settings)
    return parity_report is not None and parity_report.validation_status == "passed"


def _machine_approval_evidence_paths(candidate_id: str, settings: Settings) -> dict[str, str]:
    report_dir = settings.paths().reports_dir / candidate_id
    return {
        "strategy_spec_path": str(report_dir / "strategy_spec.json"),
        "review_packet_path": str(report_dir / "review_packet.json"),
        "robustness_report_path": str(report_dir / "robustness_report.json"),
        "backtest_summary_path": str(report_dir / "backtest_summary.json"),
        "data_provenance_path": str(report_dir / "data_provenance.json"),
    }


def _watchdog_boundary(
    settings: Settings,
    *,
    manager_run_id: str,
    program_id: str,
    family: str,
    parent_campaign_id: str | None,
    policy_hash: str,
    report_path: Path,
    cycle_budget: int,
    cycle_summaries: list[AutonomousManagerCycleSummary],
    no_material_transition_cycles: int,
    repeated_stop_reason: str | None,
    repeated_stop_count: int,
    same_candidate_count: int,
) -> AutonomousManagerReport | None:
    if no_material_transition_cycles >= settings.autonomy.watchdog_no_material_transition_cycles:
        stop_reason = "watchdog_no_material_transition"
    elif repeated_stop_reason and repeated_stop_count >= settings.autonomy.watchdog_same_blocked_reason_cycles:
        stop_reason = f"watchdog_repeated_stop_reason:{repeated_stop_reason}"
    elif same_candidate_count >= settings.autonomy.watchdog_same_candidate_cycles:
        stop_reason = "watchdog_same_candidate_without_advancement"
    else:
        return None
    return AutonomousManagerReport(
        manager_run_id=manager_run_id,
        program_id=program_id,
        family=family,
        initial_parent_campaign_id=parent_campaign_id,
        final_parent_campaign_id=parent_campaign_id,
        executed_cycles=len(cycle_summaries),
        max_cycles=cycle_budget,
        status="stopped",
        stop_reason=stop_reason,
        stop_class="blocked_policy",
        terminal_boundary="blocked_no_authorized_path",
        policy_snapshot_hash=policy_hash,
        cycle_summaries=cycle_summaries,
        notification_required=True,
        notification_reason="blocked_no_authorized_path",
        report_path=report_path,
    )


def _map_program_terminal_boundary(program_report: ProgramLoopReport, final_report) -> tuple[str | None, str, str]:
    reason = str(program_report.stop_reason or "")
    if "upstream_contract" in reason:
        return "blocked_no_authorized_path", "blocked_upstream_contract", reason
    if "no_pending_approved_lanes" in reason:
        return "blocked_no_authorized_path", "blocked_no_candidates", reason
    if program_report.stop_class in {"integrity_issue", "blocked_integrity", "integrity_exception"}:
        return "integrity_exception", "integrity_exception", reason
    if final_report is not None and final_report.recommended_follow_on_step == "human_review":
        return "blocked_no_authorized_path", "blocked_human_required", reason or "human_review_required"
    if program_report.stop_class in {
        "policy_decision",
        "blocked_policy",
        "blocked_budget",
        "blocked_human_required",
        "blocked_evidence_stale",
        "budget_exhausted",
        "approval_required",
        "ambiguity",
    }:
        mapped = "blocked_policy"
        if program_report.stop_class == "budget_exhausted":
            mapped = "blocked_budget"
        elif program_report.stop_class == "approval_required":
            mapped = "blocked_human_required"
        elif program_report.stop_class == "blocked_evidence_stale":
            mapped = "blocked_evidence_stale"
        return "blocked_no_authorized_path", mapped, reason
    return None, program_report.stop_class, reason


def _finalize_manager_report(
    settings: Settings,
    *,
    report: AutonomousManagerReport,
    idempotency_key: str,
    payload_fingerprint: str,
    manager_run_id: str,
    event_type: str,
    event_candidate_id: str | None,
    run_record: GoblinRunRecord | None = None,
) -> AutonomousManagerReport:
    write_json(report.report_path, report.model_dump(mode="json"))
    record_idempotency_result(
        settings,
        idempotency_key=idempotency_key,
        payload_fingerprint=payload_fingerprint,
        manager_run_id=manager_run_id,
        outcome_path=report.report_path,
        metadata={"terminal_boundary": report.terminal_boundary},
    )
    append_event(
        settings,
        ProgramEvent(
            event_type=event_type,
            severity="warning" if event_type != "integrity_exception" else "error",
            family=report.family,
            candidate_id=event_candidate_id,
            campaign_id=report.final_parent_campaign_id,
            report_path=report.report_path,
            notification_eligible=True,
            details={"stop_class": report.stop_class, "stop_reason": report.stop_reason},
        ),
    )
    if run_record is not None:
        finalize_goblin_run_record(
            settings,
            run_record,
            notes=[f"status={report.status}", f"stop_reason={report.stop_reason}"],
        )
    return report


def _integrity_exception_report(
    settings: Settings,
    *,
    manager_run_id: str,
    program_id: str,
    family: str,
    parent_campaign_id: str | None,
    policy_hash: str,
    report_path: Path,
    exception_class: str,
    attempted_action: str,
    related_ids: dict[str, str],
) -> AutonomousManagerReport:
    incident_id = f"incident-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    incident_path = settings.paths().incidents_dir / f"{incident_id}.json"
    incident = IntegrityIncident(
        incident_id=incident_id,
        exception_class=exception_class,
        attempted_action=attempted_action,
        family=family,
        program_id=program_id,
        lease_key=related_ids.get("lease_key"),
        expected_base_state_version=campaign_state_version(settings, parent_campaign_id),
        actual_base_state_version=campaign_state_version(settings, parent_campaign_id),
        related_ids=related_ids,
        triggering_policy_snapshot_hash=policy_hash,
        authoritative_state_snapshot_hash=authoritative_state_snapshot_hash(settings, campaign_id=parent_campaign_id),
        halt_scope="program",
        report_path=incident_path,
    )
    write_incident(settings, incident)
    report = AutonomousManagerReport(
        manager_run_id=manager_run_id,
        program_id=program_id,
        family=family,
        initial_parent_campaign_id=parent_campaign_id,
        final_parent_campaign_id=parent_campaign_id,
        executed_cycles=0,
        max_cycles=settings.autonomy.max_cycles_per_manager_run,
        status="stopped",
        stop_reason=exception_class,
        stop_class="integrity_exception",
        terminal_boundary="integrity_exception",
        policy_snapshot_hash=policy_hash,
        notification_required=True,
        notification_reason="integrity_exception",
        incident_report_path=incident_path,
        report_path=report_path,
    )
    return _finalize_manager_report(
        settings,
        report=report,
        idempotency_key=f"autonomous_manager:{manager_run_id}",
        payload_fingerprint=stable_hash(
            {
                "family": family,
                "parent_campaign_id": parent_campaign_id,
                "program_id": program_id,
                "policy_snapshot_hash": policy_hash,
            }
        ),
        manager_run_id=manager_run_id,
        event_type="integrity_exception",
        event_candidate_id=None,
    )


def _sha256_file(path: Path | None) -> str | None:
    if path is None or not Path(path).exists():
        return None
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
