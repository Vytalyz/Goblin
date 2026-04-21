from __future__ import annotations

import pytest

from agentic_forex.campaigns.portfolio import run_portfolio_cycle
from agentic_forex.config.models import PortfolioSlotPolicy
from agentic_forex.governance.models import AutonomousManagerReport


def test_settings_load_portfolio_slots_from_policy(settings):
    slot_ids = {slot.slot_id for slot in settings.portfolio.slots}

    assert "slot_a" in slot_ids
    assert "slot_b" in slot_ids


def test_active_candidate_slot_requires_mutation_allowed():
    with pytest.raises(ValueError, match="active_candidate slots must allow mutation"):
        PortfolioSlotPolicy(
            slot_id="slot_a",
            mode="active_candidate",
            purpose="active_strategy_under_live_demo",
            active_candidate_id="AF-CAND-0733",
            mutation_allowed=False,
            codex_execution_mode="app_automation_worktree",
        )


def test_blank_slate_slot_rejects_non_blank_inheritance():
    with pytest.raises(ValueError, match="none_from_prior_candidates"):
        PortfolioSlotPolicy(
            slot_id="slot_b",
            mode="blank_slate_research",
            purpose="challenger_blank_slate_research",
            mutation_allowed=True,
            allowed_families=["europe_open_impulse_retest_research"],
            codex_execution_mode="app_automation_worktree",
            strategy_inheritance="borrow_from_prior",
        )


def test_run_portfolio_cycle_active_candidate_slot_routes_into_autonomous_manager(settings, monkeypatch):
    captured = []

    def _fake_run_autonomous_manager(*args, **kwargs):
        captured.append(kwargs["family"])
        return AutonomousManagerReport(
            manager_run_id="manager-slot-a",
            program_id="slot-a-program",
            family=kwargs["family"],
            executed_cycles=1,
            max_cycles=4,
            status="stopped",
            stop_reason="program_loop_max_lanes_reached",
            stop_class="budget_exhausted",
            terminal_boundary="blocked_no_authorized_path",
            policy_snapshot_hash="pytest-policy",
            cycle_summaries=[],
            notification_required=True,
            notification_reason="blocked_no_authorized_path",
            report_path=settings.paths().autonomous_manager_dir / "manager-slot-a.json",
        )

    monkeypatch.setattr("agentic_forex.campaigns.portfolio.run_autonomous_manager", _fake_run_autonomous_manager)

    report = run_portfolio_cycle(settings, slot_id="slot_a")

    assert len(report.slot_reports) == 1
    slot_report = report.slot_reports[0]
    assert slot_report.slot_id == "slot_a"
    assert slot_report.status == "research_manager_blocked"
    assert slot_report.mutation_occurred is False
    assert report.report_path.exists()


def test_run_portfolio_cycle_slot_b_routes_into_autonomous_manager(settings, monkeypatch):
    seen_families = []

    def _fake_run_autonomous_manager(*args, **kwargs):
        seen_families.append(kwargs["family"])
        return AutonomousManagerReport(
            manager_run_id="manager-gap-slot",
            program_id="gap-program",
            family=kwargs["family"],
            executed_cycles=1,
            max_cycles=4,
            status="stopped",
            stop_reason="program_loop_max_lanes_reached",
            stop_class="budget_exhausted",
            terminal_boundary="blocked_no_authorized_path",
            policy_snapshot_hash="pytest-policy",
            cycle_summaries=[],
            notification_required=True,
            notification_reason="blocked_no_authorized_path",
            report_path=settings.paths().autonomous_manager_dir / "manager-gap-slot.json",
        )

    monkeypatch.setattr("agentic_forex.campaigns.portfolio.run_autonomous_manager", _fake_run_autonomous_manager)

    report = run_portfolio_cycle(settings, slot_id="slot_b")

    assert len(report.slot_reports) == 1
    slot_report = report.slot_reports[0]
    assert slot_report.slot_id == "slot_b"
    assert slot_report.status == "research_manager_blocked"
    assert slot_report.mutation_occurred is False
    assert slot_report.last_action == "ran_autonomous_manager:europe_open_impulse_retest_research"
    assert seen_families == ["europe_open_impulse_retest_research"]


def test_run_portfolio_cycle_slot_b_falls_through_empty_queue_family(settings, monkeypatch):
    settings.portfolio.slot_by_id("slot_b").allowed_families = [
        "europe_open_impulse_retest_research",
        "europe_open_opening_range_retest_research",
    ]
    seen_families = []

    def _fake_run_autonomous_manager(*args, **kwargs):
        family = kwargs["family"]
        seen_families.append(family)
        if family == "europe_open_impulse_retest_research":
            return AutonomousManagerReport(
                manager_run_id="manager-gap-slot-empty",
                program_id="gap-program-empty",
                family=family,
                executed_cycles=1,
                max_cycles=4,
                status="stopped",
                stop_reason="program_loop_no_pending_approved_lanes",
                stop_class="blocked_no_candidates",
                terminal_boundary="blocked_no_authorized_path",
                policy_snapshot_hash="pytest-policy",
                cycle_summaries=[],
                notification_required=True,
                notification_reason="blocked_no_authorized_path",
                report_path=settings.paths().autonomous_manager_dir / "manager-gap-slot-empty.json",
            )
        return AutonomousManagerReport(
            manager_run_id="manager-gap-slot-live",
            program_id="gap-program-live",
            family=family,
            executed_cycles=1,
            max_cycles=4,
            status="stopped",
            stop_reason="program_loop_max_lanes_reached",
            stop_class="budget_exhausted",
            terminal_boundary="blocked_no_authorized_path",
            policy_snapshot_hash="pytest-policy",
            cycle_summaries=[
                {
                    "cycle_index": 1,
                    "lane_id": "lane-live",
                    "stop_reason": "program_loop_max_lanes_reached",
                    "stop_class": "budget_exhausted",
                    "material_transition": True,
                    "approvals_issued": [],
                }
            ],
            notification_required=True,
            notification_reason="blocked_no_authorized_path",
            report_path=settings.paths().autonomous_manager_dir / "manager-gap-slot-live.json",
        )

    monkeypatch.setattr("agentic_forex.campaigns.portfolio.run_autonomous_manager", _fake_run_autonomous_manager)

    report = run_portfolio_cycle(settings, slot_id="slot_b")

    slot_report = report.slot_reports[0]
    assert slot_report.status == "research_manager_executed"
    assert slot_report.mutation_occurred is True
    assert slot_report.last_action == "ran_autonomous_manager:europe_open_opening_range_retest_research"
    assert seen_families == ["europe_open_impulse_retest_research", "europe_open_opening_range_retest_research"]
    assert (
        "europe_open_impulse_retest_research: slot fallback triggered (program_loop_no_pending_approved_lanes), "
        "trying next allowed family."
    ) in slot_report.notes


def test_run_portfolio_cycle_slot_b_falls_through_low_novelty_family(settings, monkeypatch):
    settings.portfolio.slot_by_id("slot_b").allowed_families = [
        "europe_open_impulse_retest_research",
        "europe_open_early_follow_through_research",
    ]
    seen_families = []

    def _fake_run_autonomous_manager(*args, **kwargs):
        family = kwargs["family"]
        seen_families.append(family)
        if family == "europe_open_impulse_retest_research":
            return AutonomousManagerReport(
                manager_run_id="manager-gap-slot-europe",
                program_id="gap-program-europe",
                family=family,
                executed_cycles=1,
                max_cycles=4,
                status="stopped",
                stop_reason="program_loop_low_novelty_seed:europe_open_impulse_retest_af_cand_0601:AF-CAND-0600:0.91",
                stop_class="policy_decision",
                terminal_boundary="blocked_no_authorized_path",
                policy_snapshot_hash="pytest-policy",
                cycle_summaries=[],
                notification_required=True,
                notification_reason="blocked_no_authorized_path",
                report_path=settings.paths().autonomous_manager_dir / "manager-gap-slot-europe.json",
            )
        return AutonomousManagerReport(
            manager_run_id="manager-gap-slot-us",
            program_id="gap-program-us",
            family=family,
            executed_cycles=1,
            max_cycles=4,
            status="stopped",
            stop_reason="program_loop_max_lanes_reached",
            stop_class="budget_exhausted",
            terminal_boundary="blocked_no_authorized_path",
            policy_snapshot_hash="pytest-policy",
            cycle_summaries=[
                {
                    "cycle_index": 1,
                    "lane_id": "lane-live",
                    "stop_reason": "program_loop_max_lanes_reached",
                    "stop_class": "budget_exhausted",
                    "material_transition": True,
                    "approvals_issued": [],
                }
            ],
            notification_required=True,
            notification_reason="blocked_no_authorized_path",
            report_path=settings.paths().autonomous_manager_dir / "manager-gap-slot-us.json",
        )

    monkeypatch.setattr("agentic_forex.campaigns.portfolio.run_autonomous_manager", _fake_run_autonomous_manager)

    report = run_portfolio_cycle(settings, slot_id="slot_b")

    slot_report = report.slot_reports[0]
    assert slot_report.status == "research_manager_executed"
    assert slot_report.mutation_occurred is True
    assert slot_report.last_action == "ran_autonomous_manager:europe_open_early_follow_through_research"
    assert seen_families == ["europe_open_impulse_retest_research", "europe_open_early_follow_through_research"]


def test_run_portfolio_cycle_all_slots_builds_combined_report(settings, monkeypatch):
    def _fake_run_autonomous_manager(*args, **kwargs):
        return AutonomousManagerReport(
            manager_run_id="manager-gap-slot",
            program_id="gap-program",
            family=kwargs["family"],
            executed_cycles=0,
            max_cycles=4,
            status="stopped",
            stop_reason="program_loop_no_pending_approved_lanes",
            stop_class="blocked_no_candidates",
            terminal_boundary="blocked_no_authorized_path",
            policy_snapshot_hash="pytest-policy",
            notification_required=True,
            notification_reason="blocked_no_authorized_path",
            report_path=settings.paths().autonomous_manager_dir / "manager-gap-slot.json",
        )

    monkeypatch.setattr("agentic_forex.campaigns.portfolio.run_autonomous_manager", _fake_run_autonomous_manager)

    report = run_portfolio_cycle(settings, run_all_slots=True)

    assert len(report.slot_reports) == 2
    assert settings.paths().portfolio_reports_dir.joinpath("portfolio_cycle_latest.json").exists()


def test_run_portfolio_cycle_slot_b_reports_no_selected_family_when_all_fallbacks(settings, monkeypatch):
    def _fake_run_autonomous_manager(*args, **kwargs):
        family = kwargs["family"]
        return AutonomousManagerReport(
            manager_run_id=f"manager-{family}",
            program_id=f"program-{family}",
            family=family,
            executed_cycles=1,
            max_cycles=4,
            status="stopped",
            stop_reason="program_loop_no_pending_approved_lanes",
            stop_class="blocked_no_candidates",
            terminal_boundary="blocked_no_authorized_path",
            policy_snapshot_hash="pytest-policy",
            cycle_summaries=[],
            notification_required=True,
            notification_reason="blocked_no_authorized_path",
            report_path=settings.paths().autonomous_manager_dir / f"manager-{family}.json",
        )

    monkeypatch.setattr("agentic_forex.campaigns.portfolio.run_autonomous_manager", _fake_run_autonomous_manager)

    report = run_portfolio_cycle(settings, slot_id="slot_b")

    slot_report = report.slot_reports[0]
    assert slot_report.status == "research_manager_blocked"
    assert slot_report.last_action == "ran_autonomous_manager_fallbacks"
    assert "No family advanced past the slot fallback boundary." in slot_report.notes
    assert "Final fallback family: europe_open_early_follow_through_research" in slot_report.notes


def test_run_portfolio_cycle_blocks_challenger_without_promotion_packet(settings, monkeypatch):
    challenger_id = "AF-CAND-GAP-1001"

    def _fake_run_autonomous_manager(*args, **kwargs):
        return AutonomousManagerReport(
            manager_run_id="manager-gap-challenger",
            program_id="gap-program",
            family=kwargs["family"],
            executed_cycles=1,
            max_cycles=4,
            status="stopped",
            stop_reason="ea_test_ready",
            stop_class="ea_test_ready",
            terminal_boundary="ea_test_ready",
            policy_snapshot_hash="pytest-policy",
            cycle_summaries=[],
            notification_required=True,
            notification_reason="ea_test_ready",
            handoff_candidate_id=challenger_id,
            report_path=settings.paths().autonomous_manager_dir / "manager-gap-challenger.json",
        )

    monkeypatch.setattr("agentic_forex.campaigns.portfolio.run_autonomous_manager", _fake_run_autonomous_manager)

    report = run_portfolio_cycle(settings, slot_id="slot_b")
    slot_report = report.slot_reports[0]

    assert slot_report.status == "research_manager_blocked"
    assert slot_report.mutation_occurred is False
    assert any("challenger_missing_promotion_packet" in note for note in slot_report.notes)


def test_run_portfolio_cycle_accepts_challenger_with_promotion_packet(settings, monkeypatch):
    challenger_id = "AF-CAND-GAP-1002"
    packet_dir = settings.paths().goblin_deployment_bundles_dir / challenger_id
    packet_dir.mkdir(parents=True, exist_ok=True)
    (packet_dir / "promotion_decision_packet.json").write_text(
        """
{
  "candidate_id": "AF-CAND-GAP-1002",
  "decision_status": "pending",
  "statistical_policy_keys": [
    "validation.minimum_test_trade_count",
    "validation.parity_min_match_rate",
    "validation.parity_price_tolerance_pips",
    "validation.parity_timestamp_tolerance_seconds"
  ],
  "deployment_ladder_state": "observed_demo",
  "approval_refs": [],
  "search_bias_summary": [],
  "deployment_fit_change_requires_new_bundle": false,
  "notes": [],
  "report_path": "placeholder.json"
}
        """.strip(),
        encoding="utf-8",
    )

    def _fake_run_autonomous_manager(*args, **kwargs):
        return AutonomousManagerReport(
            manager_run_id="manager-gap-challenger-ok",
            program_id="gap-program",
            family=kwargs["family"],
            executed_cycles=1,
            max_cycles=4,
            status="stopped",
            stop_reason="ea_test_ready",
            stop_class="ea_test_ready",
            terminal_boundary="ea_test_ready",
            policy_snapshot_hash="pytest-policy",
            cycle_summaries=[],
            notification_required=True,
            notification_reason="ea_test_ready",
            handoff_candidate_id=challenger_id,
            report_path=settings.paths().autonomous_manager_dir / "manager-gap-challenger-ok.json",
        )

    monkeypatch.setattr("agentic_forex.campaigns.portfolio.run_autonomous_manager", _fake_run_autonomous_manager)

    report = run_portfolio_cycle(settings, slot_id="slot_b")
    slot_report = report.slot_reports[0]

    assert slot_report.status == "research_manager_executed"
    assert slot_report.mutation_occurred is True
    assert "challenger_promotion_packet_path" in slot_report.artifact_paths
