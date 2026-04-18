from __future__ import annotations

from pathlib import Path

import pytest

from agentic_forex.approval.models import ApprovalRecord
from agentic_forex.approval.service import issue_machine_approval, latest_stage_record, record_approval
from agentic_forex.campaigns import run_autonomous_manager
from agentic_forex.governance.models import NextStepControllerReport, NextStepRecommendation, ProgramLoopReport
from agentic_forex.mt5.models import MT5Packet, MT5ValidationReport
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows.contracts import RiskPolicy, SessionPolicy, SetupLogic, StrategySpec


def test_record_approval_idempotency_same_payload_is_noop_and_conflict_raises(settings):
    record = ApprovalRecord(
        candidate_id="AF-CAND-IDEMP",
        stage="mt5_packet",
        decision="approve",
        approver="pytest",
        rationale="Approve packet generation.",
        approval_idempotency_key="approval-key-1",
    )

    record_approval(record, settings)
    record_approval(record, settings)

    log_path = settings.paths().approvals_dir / "approval_log.jsonl"
    entries = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(entries) == 1

    conflicting = record.model_copy(update={"rationale": "Changed payload."})
    with pytest.raises(ValueError, match="approval_idempotency_conflict"):
        record_approval(conflicting, settings)


def test_issue_machine_approval_rejects_human_review(settings):
    with pytest.raises(PermissionError, match="human_review"):
        issue_machine_approval(
            "AF-CAND-HUMAN",
            "human_review",
            settings,
            evidence_paths={},
            rationale="Should never auto-approve human review.",
        )


def test_run_autonomous_manager_returns_cached_outcome_for_same_idempotency(settings, monkeypatch):
    calls = {"count": 0}

    def _fake_run_program_loop(*args, **kwargs):
        calls["count"] += 1
        return ProgramLoopReport(
            program_id=kwargs["program_id"],
            family=kwargs["family"],
            initial_parent_campaign_id=kwargs.get("parent_campaign_id"),
            final_parent_campaign_id=None,
            executed_lanes=0,
            max_lanes=4,
            status="stopped",
            stop_reason="data_label_audit_completed_upstream_contract_change_required",
            stop_class="policy_decision",
            report_path=settings.paths().program_loops_dir / f"{kwargs['program_id']}.json",
        )

    monkeypatch.setattr("agentic_forex.campaigns.autonomous_manager.run_program_loop", _fake_run_program_loop)

    first = run_autonomous_manager(settings, family="scalping", manager_run_id="manager-cache", max_cycles=1)
    second = run_autonomous_manager(settings, family="scalping", manager_run_id="manager-cache", max_cycles=1)

    assert calls["count"] == 1
    assert first.report_path == second.report_path
    assert second.terminal_boundary == "blocked_no_authorized_path"
    assert second.stop_class == "blocked_upstream_contract"


def test_run_autonomous_manager_integrity_exception_on_idempotency_conflict(settings, monkeypatch):
    def _fake_run_program_loop(*args, **kwargs):
        return ProgramLoopReport(
            program_id=kwargs["program_id"],
            family=kwargs["family"],
            initial_parent_campaign_id=kwargs.get("parent_campaign_id"),
            final_parent_campaign_id=None,
            executed_lanes=0,
            max_lanes=4,
            status="stopped",
            stop_reason="program_loop_no_pending_approved_lanes",
            stop_class="policy_decision",
            report_path=settings.paths().program_loops_dir / f"{kwargs['program_id']}.json",
        )

    monkeypatch.setattr("agentic_forex.campaigns.autonomous_manager.run_program_loop", _fake_run_program_loop)

    run_autonomous_manager(settings, family="scalping", manager_run_id="manager-conflict", max_cycles=1)
    report = run_autonomous_manager(settings, family="scalping", manager_run_id="manager-conflict", max_cycles=2)

    assert report.terminal_boundary == "integrity_exception"
    assert report.stop_class == "integrity_exception"
    assert report.incident_report_path and report.incident_report_path.exists()


def test_run_autonomous_manager_issues_machine_approvals_for_parity(settings, monkeypatch):
    candidate_id = "AF-CAND-PARITY"
    _seed_parity_ready_candidate(settings, candidate_id)
    _seed_next_step_report(
        settings,
        campaign_id="campaign-parity-blocked",
        candidate_id=candidate_id,
        selected_step_type="re_evaluate_one_candidate",
        stop_class="approval_required",
        stop_reason="re_evaluation_completed_with_supported_recommendation",
        recommended_step="run_parity",
    )

    calls = {"count": 0}

    def _fake_run_program_loop(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return ProgramLoopReport(
                program_id=kwargs["program_id"],
                family=kwargs["family"],
                initial_parent_campaign_id=kwargs.get("parent_campaign_id"),
                final_parent_campaign_id="campaign-parity-blocked",
                executed_lanes=0,
                max_lanes=4,
                status="stopped",
                stop_reason="approval_required_for_run_parity",
                stop_class="approval_required",
                report_path=settings.paths().program_loops_dir / f"{kwargs['program_id']}.json",
            )
        return ProgramLoopReport(
            program_id=kwargs["program_id"],
            family=kwargs["family"],
            initial_parent_campaign_id=kwargs.get("parent_campaign_id"),
            final_parent_campaign_id=None,
            executed_lanes=0,
            max_lanes=4,
            status="stopped",
            stop_reason="program_loop_no_pending_approved_lanes",
            stop_class="policy_decision",
            report_path=settings.paths().program_loops_dir / f"{kwargs['program_id']}.json",
        )

    monkeypatch.setattr("agentic_forex.campaigns.autonomous_manager.run_program_loop", _fake_run_program_loop)

    report = run_autonomous_manager(settings, family="scalping", manager_run_id="manager-approvals", max_cycles=2)

    assert report.terminal_boundary == "blocked_no_authorized_path"
    assert calls["count"] == 2
    assert report.cycle_summaries[0].approvals_issued == ["mt5_packet", "mt5_parity_run", "mt5_validation"]
    assert latest_stage_record(candidate_id, "mt5_packet", settings).source == "policy_engine"
    assert latest_stage_record(candidate_id, "mt5_validation", settings).attestation["freshness_verified"] is True


def test_run_autonomous_manager_continues_across_program_cycle_budget_chunks(settings, monkeypatch):
    calls = {"count": 0}
    _seed_next_step_report(
        settings,
        campaign_id="campaign-progress",
        candidate_id="AF-CAND-PROGRESS",
        selected_step_type="mutate_one_candidate",
        stop_class="none",
        stop_reason="mutation_completed_with_supported_recommendation",
        recommended_step="re_evaluate_one_candidate",
    )
    progress_payload = read_json(settings.paths().campaigns_dir / "campaign-progress" / "next_step_report.json")
    progress_payload["continuation_status"] = "continue"
    progress_payload["stop_class"] = "none"
    progress_payload["auto_continue_allowed"] = True
    progress_payload["transition_status"] = "continue_lane"
    progress_payload["transition_intent"] = "advance_same_lane"
    write_json(settings.paths().campaigns_dir / "campaign-progress" / "next_step_report.json", progress_payload)

    _seed_next_step_report(
        settings,
        campaign_id="campaign-final-block",
        candidate_id="AF-CAND-PROGRESS",
        selected_step_type="data_label_audit",
        stop_class="policy_decision",
        stop_reason="program_loop_no_pending_approved_lanes",
        recommended_step="diagnose_existing_candidates",
    )
    final_payload = read_json(settings.paths().campaigns_dir / "campaign-final-block" / "next_step_report.json")
    final_payload["next_recommendations"] = []
    final_payload["continuation_status"] = "stop"
    final_payload["stop_class"] = "policy_decision"
    final_payload["auto_continue_allowed"] = False
    final_payload["recommended_follow_on_step"] = None
    final_payload["transition_status"] = "hard_stop"
    final_payload["transition_intent"] = "stop_terminal"
    write_json(settings.paths().campaigns_dir / "campaign-final-block" / "next_step_report.json", final_payload)

    def _fake_run_program_loop(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return ProgramLoopReport(
                program_id=kwargs["program_id"],
                family=kwargs["family"],
                initial_parent_campaign_id=kwargs.get("parent_campaign_id"),
                final_parent_campaign_id="campaign-progress",
                executed_lanes=0,
                max_lanes=4,
                status="completed",
                stop_reason="program_loop_max_cycles_reached",
                stop_class="budget_exhausted",
                report_path=settings.paths().program_loops_dir / f"{kwargs['program_id']}.json",
            )
        return ProgramLoopReport(
            program_id=kwargs["program_id"],
            family=kwargs["family"],
            initial_parent_campaign_id=kwargs.get("parent_campaign_id"),
            final_parent_campaign_id="campaign-final-block",
            executed_lanes=0,
            max_lanes=4,
            status="stopped",
            stop_reason="program_loop_no_pending_approved_lanes",
            stop_class="policy_decision",
            report_path=settings.paths().program_loops_dir / f"{kwargs['program_id']}.json",
        )

    monkeypatch.setattr("agentic_forex.campaigns.autonomous_manager.run_program_loop", _fake_run_program_loop)

    report = run_autonomous_manager(settings, family="day_trading", manager_run_id="manager-budget-chunk", max_cycles=2)

    assert calls["count"] == 2
    assert report.terminal_boundary == "blocked_no_authorized_path"
    assert report.cycle_summaries[0].material_transition is True


def test_run_autonomous_manager_resumes_max_cycle_chunk_on_continue_lane_transition(settings, monkeypatch):
    calls = {"count": 0}
    _seed_next_step_report(
        settings,
        campaign_id="campaign-continue-lane-progress",
        candidate_id="AF-CAND-CONTINUE",
        selected_step_type="hypothesis_audit",
        stop_class="policy_decision",
        stop_reason="hypothesis_audit_completed_hold_reference_blocked_by_robustness",
        recommended_step="diagnose_existing_candidates",
    )
    progress_payload = read_json(
        settings.paths().campaigns_dir / "campaign-continue-lane-progress" / "next_step_report.json"
    )
    progress_payload["next_recommendations"] = []
    progress_payload["continuation_status"] = "stop"
    progress_payload["stop_class"] = "policy_decision"
    progress_payload["auto_continue_allowed"] = False
    progress_payload["recommended_follow_on_step"] = None
    progress_payload["transition_status"] = "continue_lane"
    progress_payload["transition_intent"] = "advance_same_lane"
    write_json(
        settings.paths().campaigns_dir / "campaign-continue-lane-progress" / "next_step_report.json",
        progress_payload,
    )

    _seed_next_step_report(
        settings,
        campaign_id="campaign-continue-lane-final",
        candidate_id="AF-CAND-CONTINUE",
        selected_step_type="data_label_audit",
        stop_class="policy_decision",
        stop_reason="program_loop_no_pending_approved_lanes",
        recommended_step="diagnose_existing_candidates",
    )
    final_payload = read_json(settings.paths().campaigns_dir / "campaign-continue-lane-final" / "next_step_report.json")
    final_payload["next_recommendations"] = []
    final_payload["continuation_status"] = "stop"
    final_payload["stop_class"] = "policy_decision"
    final_payload["auto_continue_allowed"] = False
    final_payload["recommended_follow_on_step"] = None
    final_payload["transition_status"] = "hard_stop"
    final_payload["transition_intent"] = "stop_terminal"
    write_json(settings.paths().campaigns_dir / "campaign-continue-lane-final" / "next_step_report.json", final_payload)

    def _fake_run_program_loop(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return ProgramLoopReport(
                program_id=kwargs["program_id"],
                family=kwargs["family"],
                initial_parent_campaign_id=kwargs.get("parent_campaign_id"),
                final_parent_campaign_id="campaign-continue-lane-progress",
                executed_lanes=1,
                max_lanes=3,
                status="completed",
                stop_reason="program_loop_max_cycles_reached",
                stop_class="budget_exhausted",
                report_path=settings.paths().program_loops_dir / f"{kwargs['program_id']}.json",
            )
        return ProgramLoopReport(
            program_id=kwargs["program_id"],
            family=kwargs["family"],
            initial_parent_campaign_id=kwargs.get("parent_campaign_id"),
            final_parent_campaign_id="campaign-continue-lane-final",
            executed_lanes=0,
            max_lanes=3,
            status="stopped",
            stop_reason="program_loop_no_pending_approved_lanes",
            stop_class="policy_decision",
            report_path=settings.paths().program_loops_dir / f"{kwargs['program_id']}.json",
        )

    monkeypatch.setattr("agentic_forex.campaigns.autonomous_manager.run_program_loop", _fake_run_program_loop)

    report = run_autonomous_manager(
        settings,
        family="throughput_research",
        manager_run_id="manager-continue-lane-resume",
        max_cycles=2,
    )

    assert calls["count"] == 2
    assert report.terminal_boundary == "blocked_no_authorized_path"
    assert report.stop_reason == "program_loop_no_pending_approved_lanes"


def test_run_autonomous_manager_continues_after_max_lanes_when_advancing_next_lane(settings, monkeypatch):
    calls = {"count": 0}
    _seed_next_step_report(
        settings,
        campaign_id="campaign-throughput-reviewable",
        candidate_id="AF-CAND-THROUGHPUT",
        selected_step_type="triage_reviewable_candidate",
        stop_class="policy_decision",
        stop_reason="triage_completed_send_to_research_lane",
        recommended_step="re_evaluate_one_candidate",
    )
    throughput_payload = read_json(
        settings.paths().campaigns_dir / "campaign-throughput-reviewable" / "next_step_report.json"
    )
    throughput_payload["next_recommendations"] = []
    throughput_payload["continuation_status"] = "stop"
    throughput_payload["stop_class"] = "policy_decision"
    throughput_payload["auto_continue_allowed"] = False
    throughput_payload["recommended_follow_on_step"] = None
    throughput_payload["transition_status"] = "move_to_next_lane"
    throughput_payload["transition_intent"] = "advance_next_lane"
    write_json(
        settings.paths().campaigns_dir / "campaign-throughput-reviewable" / "next_step_report.json", throughput_payload
    )

    _seed_next_step_report(
        settings,
        campaign_id="campaign-post-promotion-stop",
        candidate_id="AF-CAND-THROUGHPUT",
        selected_step_type="data_label_audit",
        stop_class="policy_decision",
        stop_reason="program_loop_no_pending_approved_lanes",
        recommended_step="diagnose_existing_candidates",
    )
    final_payload = read_json(settings.paths().campaigns_dir / "campaign-post-promotion-stop" / "next_step_report.json")
    final_payload["next_recommendations"] = []
    final_payload["continuation_status"] = "stop"
    final_payload["stop_class"] = "policy_decision"
    final_payload["auto_continue_allowed"] = False
    final_payload["recommended_follow_on_step"] = None
    final_payload["transition_status"] = "hard_stop"
    final_payload["transition_intent"] = "stop_terminal"
    write_json(settings.paths().campaigns_dir / "campaign-post-promotion-stop" / "next_step_report.json", final_payload)

    def _fake_run_program_loop(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return ProgramLoopReport(
                program_id=kwargs["program_id"],
                family=kwargs["family"],
                initial_parent_campaign_id=kwargs.get("parent_campaign_id"),
                final_parent_campaign_id="campaign-throughput-reviewable",
                executed_lanes=3,
                max_lanes=3,
                status="completed",
                stop_reason="program_loop_max_lanes_reached",
                stop_class="budget_exhausted",
                transition_intent="advance_next_lane",
                report_path=settings.paths().program_loops_dir / f"{kwargs['program_id']}.json",
            )
        return ProgramLoopReport(
            program_id=kwargs["program_id"],
            family=kwargs["family"],
            initial_parent_campaign_id=kwargs.get("parent_campaign_id"),
            final_parent_campaign_id="campaign-post-promotion-stop",
            executed_lanes=0,
            max_lanes=3,
            status="stopped",
            stop_reason="program_loop_no_pending_approved_lanes",
            stop_class="policy_decision",
            report_path=settings.paths().program_loops_dir / f"{kwargs['program_id']}.json",
        )

    monkeypatch.setattr("agentic_forex.campaigns.autonomous_manager.run_program_loop", _fake_run_program_loop)

    report = run_autonomous_manager(
        settings,
        family="throughput_research",
        manager_run_id="manager-max-lanes-resume",
        max_cycles=2,
    )

    assert calls["count"] == 2
    assert report.terminal_boundary == "blocked_no_authorized_path"
    assert report.cycle_summaries[0].stop_reason == "program_loop_max_lanes_reached"


def test_run_autonomous_manager_emits_ea_ready_handoff(settings, monkeypatch):
    candidate_id = "AF-CAND-READY"
    _seed_ea_ready_candidate(settings, candidate_id)
    _seed_next_step_report(
        settings,
        campaign_id="campaign-forward-complete",
        candidate_id=candidate_id,
        selected_step_type="run_forward",
        stop_class="approval_required",
        stop_reason="forward_completed_with_supported_recommendation",
        recommended_step="human_review",
    )

    def _fake_run_program_loop(*args, **kwargs):
        return ProgramLoopReport(
            program_id=kwargs["program_id"],
            family=kwargs["family"],
            initial_parent_campaign_id=kwargs.get("parent_campaign_id"),
            final_parent_campaign_id="campaign-forward-complete",
            executed_lanes=1,
            max_lanes=4,
            status="completed",
            stop_reason="forward_completed_with_supported_recommendation",
            stop_class="approval_required",
            report_path=settings.paths().program_loops_dir / f"{kwargs['program_id']}.json",
        )

    monkeypatch.setattr("agentic_forex.campaigns.autonomous_manager.run_program_loop", _fake_run_program_loop)

    report = run_autonomous_manager(settings, family="scalping", manager_run_id="manager-ready", max_cycles=1)

    assert report.terminal_boundary == "ea_test_ready"
    assert report.handoff_candidate_id == candidate_id
    assert Path(report.handoff_artifact_paths["operator_safety_envelope_path"]).exists()
    assert Path(report.handoff_artifact_paths["reproducibility_manifest_path"]).exists()


def _seed_next_step_report(
    settings,
    *,
    campaign_id: str,
    candidate_id: str,
    selected_step_type: str,
    stop_class: str,
    stop_reason: str,
    recommended_step: str,
):
    campaign_dir = settings.paths().campaigns_dir / campaign_id
    campaign_dir.mkdir(parents=True, exist_ok=True)
    report = NextStepControllerReport(
        campaign_id=campaign_id,
        parent_campaign_id=None,
        selected_step_type=selected_step_type,
        step_reason="pytest seed",
        status="completed",
        stop_reason=stop_reason,
        candidate_scope=[candidate_id],
        next_recommendations=[
            NextStepRecommendation(
                step_type=recommended_step,
                candidate_id=candidate_id,
                rationale="pytest recommendation",
                binding=True,
                evidence_status="supported",
            )
        ],
        continuation_status="stop",
        stop_class=stop_class,
        auto_continue_allowed=False,
        recommended_follow_on_step=recommended_step,
        report_path=campaign_dir / "next_step_report.json",
    )
    write_json(report.report_path, report.model_dump(mode="json"))


def _seed_parity_ready_candidate(settings, candidate_id: str):
    report_dir = settings.paths().reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    spec = _strategy_spec(candidate_id)
    write_json(report_dir / "strategy_spec.json", spec.model_dump(mode="json"))
    write_json(report_dir / "backtest_summary.json", {"candidate_id": candidate_id})
    write_json(
        report_dir / "review_packet.json",
        {
            "candidate_id": candidate_id,
            "readiness": "robustness_provisional",
            "metrics": {
                "trade_count": 160,
                "out_of_sample_profit_factor": 1.2,
                "expectancy_pips": 0.3,
                "stress_passed": True,
                "grades": {"walk_forward_ok": True},
            },
        },
    )
    write_json(
        report_dir / "robustness_report.json",
        {
            "candidate_id": candidate_id,
            "evaluation_revision": 1,
            "status": "robustness_passed",
            "pbo": 0.2,
            "white_reality_check_p_value": 0.05,
            "white_reality_check_pvalue_threshold": 0.10,
        },
    )
    write_json(
        report_dir / "data_provenance.json",
        {
            "provenance_id": f"prov-{candidate_id}",
            "dataset_snapshot": {"snapshot_id": "snap-001"},
            "feature_build": {"feature_version_id": "feat-v1", "label_version_id": "label-v2"},
            "execution_cost_model_version": "cost-v1",
        },
    )


def _seed_ea_ready_candidate(settings, candidate_id: str):
    _seed_parity_ready_candidate(settings, candidate_id)
    report_dir = settings.paths().reports_dir / candidate_id
    packet_dir = settings.paths().approvals_dir / "mt5_packets" / candidate_id
    run_dir = settings.paths().mt5_runs_dir / candidate_id / "run-001"
    packet_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    ea_source = packet_dir / "CandidateEA.mq5"
    ex5 = packet_dir / "CandidateEA.ex5"
    tester_ini = run_dir / "tester_config.ini"
    expected_signal = packet_dir / "expected_signals.csv"
    logic_manifest = packet_dir / "logic_manifest.json"
    notes = packet_dir / "notes.md"
    run_spec = run_dir / "run_spec.json"
    compile_request = run_dir / "compile_request.json"
    launch_request = run_dir / "launch_request.json"
    for path, content in (
        (ea_source, "// ea source"),
        (ex5, "compiled"),
        (tester_ini, "[Tester]"),
        (expected_signal, "timestamp_utc"),
        (notes, "notes"),
    ):
        path.write_text(content, encoding="utf-8")
    write_json(logic_manifest, {"candidate_id": candidate_id})
    write_json(run_spec, {"candidate_id": candidate_id})
    write_json(compile_request, {"candidate_id": candidate_id})
    write_json(launch_request, {"candidate_id": candidate_id})
    packet = MT5Packet(
        candidate_id=candidate_id,
        packet_dir=packet_dir,
        logic_manifest_path=logic_manifest,
        expected_signal_path=expected_signal,
        notes_path=notes,
        ea_source_path=ea_source,
        compiled_ex5_path=ex5,
        run_spec_path=run_spec,
        tester_config_path=tester_ini,
        compile_request_path=compile_request,
        launch_request_path=launch_request,
    )
    write_json(packet_dir / "packet.json", packet.model_dump(mode="json"))

    validation = MT5ValidationReport(
        candidate_id=candidate_id,
        run_id="run-001",
        validation_status="passed",
        parity_rate=1.0,
        audit_rows=15,
        expected_trade_count=15,
        actual_trade_count=15,
        matched_trade_count=15,
        report_path=run_dir / "validation_report.json",
    )
    write_json(validation.report_path, validation.model_dump(mode="json"))

    write_json(
        report_dir / "forward_stage_report.json",
        {
            "candidate_id": candidate_id,
            "evaluation_revision": 1,
            "passed": True,
            "trading_days_observed": 12,
            "trade_count": 32,
            "profit_factor": 1.2,
            "expectancy_pips": 0.2,
            "oos_expectancy_pips": 0.25,
            "expectancy_degradation_pct": 20.0,
            "risk_violations": [],
            "report_path": str(report_dir / "forward_stage_report.json"),
        },
    )

    for stage in ("mt5_packet", "mt5_parity_run", "mt5_validation"):
        issue_machine_approval(
            candidate_id,
            stage,
            settings,
            evidence_paths={
                "strategy_spec_path": str(report_dir / "strategy_spec.json"),
                "review_packet_path": str(report_dir / "review_packet.json"),
                "robustness_report_path": str(report_dir / "robustness_report.json"),
                "data_provenance_path": str(report_dir / "data_provenance.json"),
            },
            rationale=f"Approve {stage} for pytest.",
            idempotency_key=f"{candidate_id}-{stage}",
        )


def _strategy_spec(candidate_id: str) -> StrategySpec:
    return StrategySpec(
        candidate_id=candidate_id,
        family="scalping",
        benchmark_group_id=candidate_id,
        variant_name="pytest",
        session_policy=SessionPolicy(
            name="pytest_session", allowed_sessions=["europe"], allowed_hours_utc=[7, 8, 9, 10]
        ),
        side_policy="both",
        setup_logic=SetupLogic(style="session_breakout", summary="pytest", trigger_conditions=["breakout"]),
        entry_logic=["entry"],
        exit_logic=["exit"],
        risk_policy=RiskPolicy(stop_loss_pips=5.0, take_profit_pips=8.0),
        source_citations=["SRC-001"],
        notes=["pytest"],
        entry_style="session_breakout",
        holding_bars=24,
        signal_threshold=1.0,
        stop_loss_pips=5.0,
        take_profit_pips=8.0,
    )
