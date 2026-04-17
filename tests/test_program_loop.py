from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from agentic_forex.campaigns import run_program_loop
from agentic_forex.config.models import ProgramLanePolicy
from agentic_forex.goblin.controls import write_strategy_rationale_card
from agentic_forex.governance.models import CandidateDiagnosticReport, GovernedLoopReport, NextStepControllerReport
from agentic_forex.utils.ids import next_campaign_id
from agentic_forex.utils.io import read_json, write_json


def test_next_campaign_id_avoids_existing_campaign_directory(settings, monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 3, 22, 16, 37, 25, 0, tzinfo=UTC)

    monkeypatch.setattr("agentic_forex.utils.ids.datetime", FrozenDateTime)

    existing_dir = settings.paths().campaigns_dir / "campaign-20260322T163725000000Z-next-step"
    existing_dir.mkdir(parents=True, exist_ok=True)

    campaign_id = next_campaign_id(settings, suffix="-next-step")

    assert campaign_id == "campaign-20260322T163725000000Z-01-next-step"


def test_run_program_loop_rejects_throughput_lane_missing_required_family_evidence(settings):
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="overnight_cross_rate_af_cand_evidence",
            family="research",
            hypothesis_class="mean_reversion_pullback",
            seed_candidate_id="AF-CAND-EVIDENCE-MISSING",
            queue_kind="throughput",
            required_evidence_tags=["mean_reversion_stationarity", "mean_reversion_half_life"],
            orthogonality_metadata={
                "market_hypothesis": "cross_rate_reversion",
                "trigger_family": "spread_reversion",
                "holding_profile": "overnight_reversion",
                "session_profile": "asia",
                "regime_dependency": "range",
            },
            max_steps=5,
        )
    ]
    report_dir = settings.paths().reports_dir / "AF-CAND-EVIDENCE-MISSING"
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        report_dir / "candidate.json",
        {
            "candidate_id": "AF-CAND-EVIDENCE-MISSING",
            "family": "research",
            "title": "Overnight Cross-Rate Root",
            "thesis": "Trade an overnight FX spread with deterministic rules.",
            "source_citations": ["SRC-TEST"],
            "strategy_hypothesis": "Use an overnight cross-rate setup without yet proving stationarity or half-life.",
            "market_context": {
                "session_focus": "asia_overnight",
                "volatility_preference": "moderate",
                "directional_bias": "both",
                "execution_notes": ["This is still a hypothesis-level root."],
                "allowed_hours_utc": [20, 21, 22, 23],
            },
            "market_rationale": {
                "market_behavior": "An overnight FX spread may revert after a controlled extension.",
                "edge_mechanism": "Trade a deterministic pullback into the overnight range.",
                "persistence_reason": "The overnight session can remain orderly enough for a bounded reversion test.",
                "failure_regimes": ["Spread widening can erase the edge."],
                "validation_focus": ["Confirm the setup survives the governed overnight filter."],
            },
            "setup_summary": "Wait for the spread to stretch overnight.",
            "entry_summary": "Enter on a deterministic reversion cue.",
            "exit_summary": "Exit on target, stop, or timeout.",
            "risk_summary": "Single overnight position with explicit risk limits.",
            "notes": ["Seed intentionally missing family-specific evidence."],
            "quality_flags": ["throughput_seed"],
            "contradiction_summary": [],
            "critic_notes": [],
            "entry_style": "mean_reversion_pullback",
            "holding_bars": 180,
            "signal_threshold": 1.0,
            "stop_loss_pips": 10.0,
            "take_profit_pips": 15.0,
        },
    )
    write_strategy_rationale_card(settings, family="research", thesis="Overnight cross-rate reversion seed requiring explicit invalidation and regime controls.", invalidation_conditions=["spread fails stationarity check"], hostile_regimes=["spread widening regime"], execution_assumptions=["bounded overnight spread"], non_deployable_conditions=["walk-forward instability"])

    report = run_program_loop(
        settings,
        family="research",
        program_id="program-missing-evidence",
        max_lanes=1,
    )

    assert report.executed_lanes == 0
    assert report.stop_class == "policy_decision"
    assert report.stop_reason == (
        "program_loop_missing_family_evidence:"
        "overnight_cross_rate_af_cand_evidence:"
        "mean_reversion_stationarity,mean_reversion_half_life"
    )


def test_run_program_loop_accepts_throughput_lane_when_family_evidence_present(settings, monkeypatch):
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="overnight_cross_rate_af_cand_evidence",
            family="research",
            hypothesis_class="mean_reversion_pullback",
            seed_candidate_id="AF-CAND-EVIDENCE-PRESENT",
            queue_kind="throughput",
            required_evidence_tags=["mean_reversion_stationarity", "mean_reversion_half_life"],
            orthogonality_metadata={
                "market_hypothesis": "cross_rate_reversion",
                "trigger_family": "spread_reversion",
                "holding_profile": "overnight_reversion",
                "session_profile": "asia",
                "regime_dependency": "range",
            },
            max_steps=5,
        )
    ]
    report_dir = settings.paths().reports_dir / "AF-CAND-EVIDENCE-PRESENT"
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        report_dir / "candidate.json",
        {
            "candidate_id": "AF-CAND-EVIDENCE-PRESENT",
            "family": "research",
            "title": "Overnight Cross-Rate Root",
            "thesis": "Use a common quote currency and set the lookback from the half-life of the mean-reverting spread.",
            "source_citations": ["SRC-TEST"],
            "strategy_hypothesis": "Require ADF and variance ratio checks before letting the spread into throughput.",
            "market_context": {
                "session_focus": "asia_overnight",
                "volatility_preference": "moderate",
                "directional_bias": "both",
                "execution_notes": ["Use common-quote FX math and stationarity checks."],
                "allowed_hours_utc": [20, 21, 22, 23],
            },
            "setup_summary": "Wait for a stationary spread to stretch overnight.",
            "entry_summary": "Enter when the mean-reverting spread deviates beyond the governed threshold.",
            "exit_summary": "Exit on target, stop, or timeout.",
            "risk_summary": "Single overnight position with explicit carry awareness.",
            "market_rationale": {
                "market_behavior": "The spread is expected to be stationary after the ADF and variance ratio checks pass.",
                "edge_mechanism": "Trade reversion in a common-quote FX spread.",
                "persistence_reason": "Half-life keeps the holding period practical.",
                "failure_regimes": ["Regime change breaks stationarity."],
                "validation_focus": ["Confirm stationarity before seeding."],
            },
            "notes": ["Seed carries the required mean-reversion evidence."],
            "quality_flags": ["throughput_seed"],
            "contradiction_summary": [],
            "critic_notes": [],
            "entry_style": "mean_reversion_pullback",
            "holding_bars": 180,
            "signal_threshold": 1.0,
            "stop_loss_pips": 10.0,
            "take_profit_pips": 15.0,
        },
    )

    def _fake_run_governed_loop(
        settings,
        *,
        family="research",
        parent_campaign_id=None,
        loop_id=None,
        max_steps=8,
        allowed_step_types=None,
    ):
        report_path = settings.paths().campaigns_dir / "campaign-evidence-pass" / "next_step_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            report_path,
            NextStepControllerReport(
                campaign_id="campaign-evidence-pass",
                parent_campaign_id=parent_campaign_id,
                selected_step_type="formalize_rule_candidate",
                step_reason="Throughput lane started after family evidence gate passed.",
                status="completed",
                stop_reason="formalize_rule_candidate_completed",
                candidate_scope=["AF-CAND-EVIDENCE-PRESENT"],
                continuation_status="stop",
                stop_class="ambiguity",
                auto_continue_allowed=False,
                transition_status="hard_stop",
                report_path=report_path,
            ).model_dump(mode="json"),
        )
        loop_report = GovernedLoopReport(
            loop_id=loop_id or "loop-evidence-pass",
            family=family,
            initial_parent_campaign_id=parent_campaign_id,
            final_parent_campaign_id="campaign-evidence-pass",
            executed_steps=1,
            max_steps=max_steps,
            status="completed",
            stop_reason="formalize_rule_candidate_completed",
            stop_class="ambiguity",
            final_report_path=report_path,
            report_path=settings.paths().governed_loops_dir / "loop-evidence-pass.json",
        )
        write_json(loop_report.report_path, loop_report.model_dump(mode="json"))
        return loop_report

    monkeypatch.setattr("agentic_forex.campaigns.program_loop.run_governed_loop", _fake_run_governed_loop)
    write_strategy_rationale_card(settings, family="research", thesis="Overnight cross-rate reversion seed requiring explicit invalidation and regime controls.", invalidation_conditions=["spread fails stationarity check"], hostile_regimes=["spread widening regime"], execution_assumptions=["bounded overnight spread"], non_deployable_conditions=["walk-forward instability"])

    report = run_program_loop(
        settings,
        family="research",
        program_id="program-evidence-pass",
        max_lanes=1,
    )

    assert report.executed_lanes == 1
    assert report.stop_reason == "formalize_rule_candidate_completed"
    assert report.lane_summaries[0].lane_id == "overnight_cross_rate_af_cand_evidence"


def test_run_program_loop_seeds_next_approved_lane_after_retirement(settings, monkeypatch):
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="failed_break_fade_af_cand_0001",
            family="scalping",
            hypothesis_class="failed_break_fade",
            seed_candidate_id="AF-CAND-0001-FADE",
            max_steps=4,
        ),
        ProgramLanePolicy(
            lane_id="failed_break_fade_af_cand_0015",
            family="scalping",
            hypothesis_class="failed_break_fade",
            seed_candidate_id="AF-CAND-0015-FADE",
            max_steps=4,
        ),
    ]
    for candidate_id, entry_style in (
        ("AF-CAND-0001-FADE", "failed_break_fade"),
        ("AF-CAND-0015-FADE", "failed_break_fade"),
    ):
        report_dir = settings.paths().reports_dir / candidate_id
        report_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            report_dir / "strategy_spec.json",
            {
                "candidate_id": candidate_id,
                "family": "scalping",
                "entry_style": entry_style,
            },
        )

    calls: list[str | None] = []

    def _fake_run_governed_loop(
        settings,
        *,
        family="scalping",
        parent_campaign_id=None,
        loop_id=None,
        max_steps=8,
        allowed_step_types=None,
    ):
        calls.append(parent_campaign_id)
        loop_dir = settings.paths().governed_loops_dir
        if len(calls) == 1:
            report_path = settings.paths().campaigns_dir / "campaign-retired-final" / "next_step_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(
                report_path,
                NextStepControllerReport(
                    campaign_id="campaign-retired-final",
                    parent_campaign_id=parent_campaign_id,
                    selected_step_type="data_regime_audit",
                    step_reason="Retire the old lane.",
                    status="completed",
                    stop_reason="data_regime_audit_completed_retire_lane",
                    candidate_scope=["AF-CAND-0027"],
                    continuation_status="stop",
                    stop_class="policy_decision",
                    auto_continue_allowed=False,
                    transition_status="move_to_next_lane",
                    report_path=report_path,
                ).model_dump(mode="json"),
            )
            loop_report = GovernedLoopReport(
                loop_id=loop_id or "loop-1",
                family=family,
                initial_parent_campaign_id=parent_campaign_id,
                final_parent_campaign_id="campaign-retired-final",
                executed_steps=1,
                max_steps=max_steps,
                status="completed",
                stop_reason="data_regime_audit_completed_retire_lane",
                stop_class="policy_decision",
                final_report_path=report_path,
                report_path=loop_dir / "loop-1.json",
            )
            write_json(loop_report.report_path, loop_report.model_dump(mode="json"))
            return loop_report

        seed_dir = settings.paths().campaigns_dir / parent_campaign_id
        seed_spec = read_json(seed_dir / "spec.json")
        seed_recommendations = read_json(seed_dir / "next_recommendations.json")
        assert seed_spec["baseline_candidate_id"] == "AF-CAND-0001-FADE"
        assert seed_spec["parent_campaign_id"] == "campaign-retired-final"
        assert seed_recommendations[0]["step_payload"]["mutation_type"] == "refresh_execution_cost_defaults"

        report_path = settings.paths().campaigns_dir / "campaign-fade-final" / "next_step_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            report_path,
            NextStepControllerReport(
                campaign_id="campaign-fade-final",
                parent_campaign_id=parent_campaign_id,
                selected_step_type="re_evaluate_one_candidate",
                step_reason="The new lane stopped after reevaluation.",
                status="completed",
                stop_reason="re_evaluation_completed_no_supported_next_step",
                candidate_scope=["AF-CAND-FADE-REFRESH"],
                continuation_status="stop",
                stop_class="ambiguity",
                auto_continue_allowed=False,
                transition_status="hard_stop",
                report_path=report_path,
            ).model_dump(mode="json"),
        )
        loop_report = GovernedLoopReport(
            loop_id=loop_id or "loop-2",
            family=family,
            initial_parent_campaign_id=parent_campaign_id,
            final_parent_campaign_id="campaign-fade-final",
            executed_steps=1,
            max_steps=max_steps,
            status="completed",
            stop_reason="re_evaluation_completed_no_supported_next_step",
            stop_class="ambiguity",
            final_report_path=report_path,
            report_path=loop_dir / "loop-2.json",
        )
        write_json(loop_report.report_path, loop_report.model_dump(mode="json"))
        return loop_report

    monkeypatch.setattr("agentic_forex.campaigns.program_loop.run_governed_loop", _fake_run_governed_loop)

    report = run_program_loop(
        settings,
        family="scalping",
        parent_campaign_id="campaign-retired-root",
        program_id="program-test",
        max_lanes=3,
    )

    assert report.executed_lanes == 1
    assert report.stop_reason == "re_evaluation_completed_no_supported_next_step"
    assert report.stop_class == "ambiguity"
    assert report.final_parent_campaign_id == "campaign-fade-final"
    assert [summary.lane_id for summary in report.lane_summaries] == ["failed_break_fade_af_cand_0001"]
    assert report.report_path.exists()
    assert len(calls) == 2


def test_run_program_loop_skips_historically_terminal_lane_on_new_manager_run(settings, monkeypatch):
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="compression_breakout_af_cand_0060",
            family="day_trading",
            hypothesis_class="compression_breakout",
            seed_candidate_id="AF-CAND-0060",
            max_steps=4,
        ),
        ProgramLanePolicy(
            lane_id="range_reclaim_af_cand_0061",
            family="day_trading",
            hypothesis_class="range_reclaim",
            seed_candidate_id="AF-CAND-0061",
            max_steps=4,
        ),
    ]
    for candidate_id, entry_style in (
        ("AF-CAND-0060", "compression_breakout"),
        ("AF-CAND-0061", "range_reclaim"),
    ):
        report_dir = settings.paths().reports_dir / candidate_id
        report_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            report_dir / "strategy_spec.json",
            {
                "candidate_id": candidate_id,
                "family": "day_trading",
                "entry_style": entry_style,
            },
        )

    prior_report = {
        "program_id": "program-prior",
        "family": "day_trading",
        "lane_summaries": [
            {
                "lane_id": "compression_breakout_af_cand_0060",
                "transition_status": "hard_stop",
            }
        ],
    }
    write_json(settings.paths().program_loops_dir / "program-prior.json", prior_report)

    def _fake_run_governed_loop(
        settings,
        *,
        family="day_trading",
        parent_campaign_id=None,
        loop_id=None,
        max_steps=8,
        allowed_step_types=None,
    ):
        seed_dir = settings.paths().campaigns_dir / parent_campaign_id
        seed_spec = read_json(seed_dir / "spec.json")
        assert seed_spec["baseline_candidate_id"] == "AF-CAND-0061"

        report_path = settings.paths().campaigns_dir / "campaign-range-final" / "next_step_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            report_path,
            NextStepControllerReport(
                campaign_id="campaign-range-final",
                parent_campaign_id=parent_campaign_id,
                selected_step_type="re_evaluate_one_candidate",
                step_reason="Range reclaim lane stopped after reevaluation.",
                status="completed",
                stop_reason="re_evaluation_completed_no_supported_next_step",
                candidate_scope=["AF-CAND-0061"],
                continuation_status="stop",
                stop_class="ambiguity",
                auto_continue_allowed=False,
                transition_status="hard_stop",
                report_path=report_path,
            ).model_dump(mode="json"),
        )
        loop_report = GovernedLoopReport(
            loop_id=loop_id or "loop-range",
            family=family,
            initial_parent_campaign_id=parent_campaign_id,
            final_parent_campaign_id="campaign-range-final",
            executed_steps=1,
            max_steps=max_steps,
            status="completed",
            stop_reason="re_evaluation_completed_no_supported_next_step",
            stop_class="ambiguity",
            final_report_path=report_path,
            report_path=settings.paths().governed_loops_dir / "loop-range.json",
        )
        write_json(loop_report.report_path, loop_report.model_dump(mode="json"))
        return loop_report

    monkeypatch.setattr("agentic_forex.campaigns.program_loop.run_governed_loop", _fake_run_governed_loop)

    report = run_program_loop(
        settings,
        family="day_trading",
        program_id="program-skip-terminal",
        max_lanes=2,
    )

    assert report.executed_lanes == 1
    assert [summary.lane_id for summary in report.lane_summaries] == ["range_reclaim_af_cand_0061"]


def test_run_program_loop_executes_final_family_audit_when_queue_exhausts(settings, monkeypatch):
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="failed_break_fade_af_cand_0001",
            family="scalping",
            hypothesis_class="failed_break_fade",
            seed_candidate_id="AF-CAND-0001-FADE",
            max_steps=4,
        ),
    ]
    report_dir = settings.paths().reports_dir / "AF-CAND-0001-FADE"
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        report_dir / "strategy_spec.json",
        {
            "candidate_id": "AF-CAND-0001-FADE",
            "family": "scalping",
            "entry_style": "failed_break_fade",
        },
    )

    def _fake_run_governed_loop(
        settings,
        *,
        family="scalping",
        parent_campaign_id=None,
        loop_id=None,
        max_steps=8,
        allowed_step_types=None,
    ):
        loop_dir = settings.paths().governed_loops_dir
        report_path = settings.paths().campaigns_dir / "campaign-retired-final" / "next_step_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            report_path,
            NextStepControllerReport(
                campaign_id="campaign-retired-final",
                parent_campaign_id=parent_campaign_id,
                selected_step_type="data_regime_audit",
                step_reason="Retire the only approved lane.",
                status="completed",
                stop_reason="data_regime_audit_completed_retire_lane",
                candidate_scope=["AF-CAND-0040"],
                continuation_status="stop",
                stop_class="policy_decision",
                auto_continue_allowed=False,
                transition_status="move_to_next_lane",
                report_path=report_path,
            ).model_dump(mode="json"),
        )
        loop_report = GovernedLoopReport(
            loop_id=loop_id or "loop-1",
            family=family,
            initial_parent_campaign_id=parent_campaign_id,
            final_parent_campaign_id="campaign-retired-final",
            executed_steps=1,
            max_steps=max_steps,
            status="completed",
            stop_reason="data_regime_audit_completed_retire_lane",
            stop_class="policy_decision",
            final_report_path=report_path,
            report_path=loop_dir / "loop-1.json",
        )
        write_json(loop_report.report_path, loop_report.model_dump(mode="json"))
        return loop_report

    next_step_calls: list[list[str] | None] = []

    def _fake_run_next_step(
        settings,
        *,
        family="scalping",
        parent_campaign_id=None,
        campaign_id=None,
        allowed_step_types=None,
    ):
        next_step_calls.append(allowed_step_types)
        if allowed_step_types == ["data_feature_audit"]:
            report_path = settings.paths().campaigns_dir / "campaign-family-audit" / "next_step_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            return NextStepControllerReport(
                campaign_id="campaign-family-audit",
                parent_campaign_id=parent_campaign_id,
                selected_step_type="data_feature_audit",
                step_reason="Run the family audit after queue exhaustion.",
                status="completed",
                stop_reason="data_feature_audit_completed_retire_family",
                candidate_scope=["AF-CAND-0027", "AF-CAND-0040"],
                data_feature_audit_reports=[
                    {
                        "family": "scalping",
                        "audited_candidate_ids": ["AF-CAND-0027", "AF-CAND-0040"],
                        "reference_candidate_id": "AF-CAND-0027",
                        "family_decision": "retire_family",
                        "summary": "Retire the family before contract audit.",
                    }
                ],
                continuation_status="stop",
                stop_class="policy_decision",
                auto_continue_allowed=False,
                transition_status="hard_stop",
                report_path=report_path,
            )
        assert allowed_step_types == ["data_label_audit"]
        report_path = settings.paths().campaigns_dir / "campaign-label-audit" / "next_step_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        return NextStepControllerReport(
            campaign_id="campaign-label-audit",
            parent_campaign_id=parent_campaign_id,
            selected_step_type="data_label_audit",
            step_reason="Run the label audit after family retirement.",
            status="completed",
            stop_reason="data_label_audit_completed_upstream_contract_change_required",
            candidate_scope=["AF-CAND-0027", "AF-CAND-0040"],
            continuation_status="stop",
            stop_class="policy_decision",
            auto_continue_allowed=False,
            transition_status="hard_stop",
            report_path=report_path,
        )

    monkeypatch.setattr("agentic_forex.campaigns.program_loop.run_governed_loop", _fake_run_governed_loop)
    monkeypatch.setattr("agentic_forex.campaigns.program_loop.run_next_step", _fake_run_next_step)

    report = run_program_loop(
        settings,
        family="scalping",
        parent_campaign_id="campaign-retired-root",
        program_id="program-audit",
        max_lanes=1,
    )

    assert report.executed_lanes == 1
    assert report.stop_reason == "data_label_audit_completed_upstream_contract_change_required"
    assert report.stop_class == "policy_decision"
    assert report.final_parent_campaign_id == "campaign-label-audit"
    assert report.final_audit_report_path == settings.paths().campaigns_dir / "campaign-label-audit" / "next_step_report.json"
    assert next_step_calls == [["data_feature_audit"], ["data_label_audit"]]


def test_run_program_loop_resumes_lane_after_bounded_data_feature_audit(settings, monkeypatch):
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="session_breakout_af_cand_0163",
            family="scalping",
            hypothesis_class="session_breakout",
            seed_candidate_id="AF-CAND-0163",
            max_steps=4,
        ),
    ]
    report_dir = settings.paths().reports_dir / "AF-CAND-0163"
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        report_dir / "strategy_spec.json",
        {
            "candidate_id": "AF-CAND-0163",
            "family": "scalping",
            "entry_style": "session_breakout",
        },
    )

    governed_calls: list[str | None] = []
    next_step_calls: list[list[str] | None] = []

    def _fake_run_governed_loop(
        settings,
        *,
        family="scalping",
        parent_campaign_id=None,
        loop_id=None,
        max_steps=8,
        allowed_step_types=None,
    ):
        governed_calls.append(parent_campaign_id)
        if len(governed_calls) == 1:
            seed_dir = settings.paths().campaigns_dir / parent_campaign_id
            seed_spec = read_json(seed_dir / "spec.json")
            assert seed_spec["baseline_candidate_id"] == "AF-CAND-0163"
            loop_dir = settings.paths().governed_loops_dir
            report_path = settings.paths().campaigns_dir / "campaign-retired-final" / "next_step_report.json"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            write_json(
                report_path,
                NextStepControllerReport(
                    campaign_id="campaign-retired-final",
                    parent_campaign_id=parent_campaign_id,
                    selected_step_type="data_regime_audit",
                    step_reason="Retire the only approved lane.",
                    status="completed",
                    stop_reason="data_regime_audit_completed_retire_lane",
                    candidate_scope=["AF-CAND-0163"],
                    continuation_status="stop",
                    stop_class="policy_decision",
                    auto_continue_allowed=False,
                    transition_status="move_to_next_lane",
                    report_path=report_path,
                ).model_dump(mode="json"),
            )
            loop_report = GovernedLoopReport(
                loop_id=loop_id or "loop-1",
                family=family,
                initial_parent_campaign_id=parent_campaign_id,
                final_parent_campaign_id="campaign-retired-final",
                executed_steps=1,
                max_steps=max_steps,
                status="completed",
                stop_reason="data_regime_audit_completed_retire_lane",
                stop_class="policy_decision",
                final_report_path=report_path,
                report_path=loop_dir / "loop-1.json",
            )
            write_json(loop_report.report_path, loop_report.model_dump(mode="json"))
            return loop_report

        assert parent_campaign_id == "campaign-family-audit"
        loop_dir = settings.paths().governed_loops_dir
        report_path = settings.paths().campaigns_dir / "campaign-correction-final" / "next_step_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            report_path,
            NextStepControllerReport(
                campaign_id="campaign-correction-final",
                parent_campaign_id=parent_campaign_id,
                selected_step_type="diagnose_existing_candidates",
                step_reason="Run the bounded correction diagnosis.",
                status="completed",
                stop_reason="diagnosis_completed_with_supported_recommendation",
                candidate_scope=["AF-CAND-0163"],
                continuation_status="stop",
                stop_class="ambiguity",
                auto_continue_allowed=False,
                transition_status="hard_stop",
                report_path=report_path,
            ).model_dump(mode="json"),
        )
        loop_report = GovernedLoopReport(
            loop_id=loop_id or "loop-2",
            family=family,
            initial_parent_campaign_id=parent_campaign_id,
            final_parent_campaign_id="campaign-correction-final",
            executed_steps=1,
            max_steps=max_steps,
            status="completed",
            stop_reason="diagnosis_completed_with_supported_recommendation",
            stop_class="ambiguity",
            final_report_path=report_path,
            report_path=loop_dir / "loop-2.json",
        )
        write_json(loop_report.report_path, loop_report.model_dump(mode="json"))
        return loop_report

    def _fake_run_next_step(
        settings,
        *,
        family="scalping",
        parent_campaign_id=None,
        campaign_id=None,
        allowed_step_types=None,
    ):
        next_step_calls.append(allowed_step_types)
        assert allowed_step_types == ["data_feature_audit"]
        report_path = settings.paths().campaigns_dir / "campaign-family-audit" / "next_step_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        return NextStepControllerReport(
            campaign_id="campaign-family-audit",
            parent_campaign_id=parent_campaign_id,
            selected_step_type="data_feature_audit",
            step_reason="Run the family audit after queue exhaustion.",
            status="completed",
            stop_reason="data_feature_audit_completed_bounded_correction_supported",
            candidate_scope=["AF-CAND-0163", "AF-CAND-0165"],
            data_feature_audit_reports=[
                {
                    "family": "scalping",
                    "audited_candidate_ids": ["AF-CAND-0163", "AF-CAND-0165"],
                    "reference_candidate_id": "AF-CAND-0163",
                    "family_decision": "bounded_correction_supported",
                    "summary": "Mixed cost-model evidence supports one bounded correction.",
                }
            ],
            next_recommendations=[
                {
                    "step_type": "diagnose_existing_candidates",
                    "candidate_id": "AF-CAND-0163",
                    "rationale": "Run one bounded correction diagnosis on the strongest reference branch.",
                    "binding": True,
                    "evidence_status": "supported",
                }
            ],
            continuation_status="continue",
            stop_class="none",
            auto_continue_allowed=True,
            recommended_follow_on_step="diagnose_existing_candidates",
            transition_status="continue_lane",
            report_path=report_path,
        )

    monkeypatch.setattr("agentic_forex.campaigns.program_loop.run_governed_loop", _fake_run_governed_loop)
    monkeypatch.setattr("agentic_forex.campaigns.program_loop.run_next_step", _fake_run_next_step)

    report = run_program_loop(
        settings,
        family="scalping",
        program_id="program-bounded-feature-audit",
        max_lanes=1,
    )

    assert len(governed_calls) == 2
    assert governed_calls[1] == "campaign-family-audit"
    assert next_step_calls == [["data_feature_audit"]]
    assert report.executed_lanes == 1
    assert report.stop_reason == "diagnosis_completed_with_supported_recommendation"
    assert report.stop_class == "ambiguity"
    assert report.final_parent_campaign_id == "campaign-correction-final"


def test_run_program_loop_resumes_parent_lane_after_ambiguous_post_correction_diagnosis(settings, monkeypatch):
    settings.program.approved_lanes = []
    parent_campaign_id = "campaign-parent-post-correction-diagnosis"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        parent_dir / "state.json",
        {
            "campaign_id": parent_campaign_id,
            "family": "impulse_transition_research",
            "status": "completed",
            "baseline_candidate_id": "AF-CAND-0172",
            "active_candidate_ids": ["AF-CAND-0172", "AF-CAND-0173"],
            "last_report_path": str(parent_dir / "next_step_report.json"),
        },
    )
    write_json(
        parent_dir / "next_step_report.json",
        NextStepControllerReport(
            campaign_id=parent_campaign_id,
            parent_campaign_id="campaign-grandparent",
            selected_step_type="diagnose_existing_candidates",
            step_reason="The bounded correction did not justify another mutation.",
            status="completed",
            stop_reason="diagnosis_ambiguous_no_mutation_justified",
            candidate_scope=["AF-CAND-0173"],
            candidate_reports=[
                CandidateDiagnosticReport(
                    candidate_id="AF-CAND-0173",
                    readiness_status="robustness_provisional",
                    walk_forward_failed_window=1,
                    first_window_trade_count=41,
                    later_window_trade_count=82,
                    first_window_profit_factor=0.66,
                    later_window_profit_factor=0.42,
                    first_window_expectancy_pips=-1.15,
                    later_window_expectancy_pips=-1.75,
                    supported_slices=[],
                    primary_issue=None,
                    recommended_mutation=None,
                )
            ],
            continuation_status="stop",
            stop_class="ambiguity",
            auto_continue_allowed=False,
            report_path=parent_dir / "next_step_report.json",
        ).model_dump(mode="json"),
    )
    governed_calls: list[str | None] = []

    def _fake_run_governed_loop(
        settings,
        *,
        family="impulse_transition_research",
        parent_campaign_id=None,
        loop_id=None,
        max_steps=8,
        allowed_step_types=None,
    ):
        governed_calls.append(parent_campaign_id)
        assert parent_campaign_id == "campaign-parent-post-correction-diagnosis"
        report_path = settings.paths().campaigns_dir / "campaign-hypothesis-audit-final" / "next_step_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            report_path,
            NextStepControllerReport(
                campaign_id="campaign-hypothesis-audit-final",
                parent_campaign_id=parent_campaign_id,
                selected_step_type="hypothesis_audit",
                step_reason="Escalated after no further bounded mutation was justified.",
                status="completed",
                stop_reason="hypothesis_audit_completed_retire_lane",
                candidate_scope=["AF-CAND-0172", "AF-CAND-0173"],
                continuation_status="stop",
                stop_class="policy_decision",
                auto_continue_allowed=False,
                transition_status="move_to_next_lane",
                report_path=report_path,
            ).model_dump(mode="json"),
        )
        loop_report = GovernedLoopReport(
            loop_id=loop_id or "loop-post-correction",
            family=family,
            initial_parent_campaign_id=parent_campaign_id,
            final_parent_campaign_id="campaign-hypothesis-audit-final",
            executed_steps=1,
            max_steps=max_steps,
            status="completed",
            stop_reason="hypothesis_audit_completed_retire_lane",
            stop_class="policy_decision",
            final_report_path=report_path,
            report_path=settings.paths().governed_loops_dir / "loop-post-correction.json",
        )
        write_json(loop_report.report_path, loop_report.model_dump(mode="json"))
        return loop_report

    monkeypatch.setattr("agentic_forex.campaigns.program_loop.run_governed_loop", _fake_run_governed_loop)

    report = run_program_loop(
        settings,
        family="impulse_transition_research",
        parent_campaign_id=parent_campaign_id,
        program_id="program-post-correction-resume",
        max_lanes=1,
    )

    assert governed_calls == ["campaign-parent-post-correction-diagnosis"]
    assert report.stop_reason == "program_loop_no_pending_approved_lanes"
    assert report.final_parent_campaign_id == "campaign-hypothesis-audit-final"
    assert report.transition_intent == "stop_terminal"


def test_run_program_loop_resumes_parent_lane_after_structural_regime_instability(settings, monkeypatch):
    settings.program.approved_lanes = []
    parent_campaign_id = "campaign-parent-structural-regime"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        parent_dir / "state.json",
        {
            "campaign_id": parent_campaign_id,
            "family": "impulse_transition_research",
            "status": "completed",
            "baseline_candidate_id": "AF-CAND-0172",
            "active_candidate_ids": ["AF-CAND-0172", "AF-CAND-0173"],
            "last_report_path": str(parent_dir / "next_step_report.json"),
        },
    )
    write_json(
        parent_dir / "next_step_report.json",
        {
            "campaign_id": parent_campaign_id,
            "parent_campaign_id": "campaign-grandparent",
            "selected_step_type": "data_regime_audit",
            "status": "completed",
            "stop_reason": "data_regime_audit_completed_structural_regime_instability",
            "transition_status": "hard_stop",
            "candidate_scope": ["AF-CAND-0173", "AF-CAND-0172"],
            "data_regime_audit_reports": [
                {
                    "family": "impulse_transition_research",
                    "audited_candidate_ids": ["AF-CAND-0173", "AF-CAND-0172"],
                    "reference_candidate_id": "AF-CAND-0173",
                    "focus_candidate_id": "AF-CAND-0173",
                    "lane_decision": "structural_regime_instability",
                }
            ],
        },
    )
    governed_calls: list[str | None] = []

    def _fake_run_governed_loop(
        settings,
        *,
        family="impulse_transition_research",
        parent_campaign_id=None,
        loop_id=None,
        max_steps=8,
        allowed_step_types=None,
    ):
        governed_calls.append(parent_campaign_id)
        report_path = settings.paths().campaigns_dir / "campaign-feature-audit-final" / "next_step_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            report_path,
            NextStepControllerReport(
                campaign_id="campaign-feature-audit-final",
                parent_campaign_id=parent_campaign_id,
                selected_step_type="data_feature_audit",
                step_reason="Escalated to family audit after structural instability.",
                status="completed",
                stop_reason="data_feature_audit_completed_retire_family",
                candidate_scope=["AF-CAND-0172", "AF-CAND-0173"],
                continuation_status="stop",
                stop_class="policy_decision",
                auto_continue_allowed=False,
                transition_status="hard_stop",
                report_path=report_path,
            ).model_dump(mode="json"),
        )
        loop_report = GovernedLoopReport(
            loop_id=loop_id or "loop-structural",
            family=family,
            initial_parent_campaign_id=parent_campaign_id,
            final_parent_campaign_id="campaign-feature-audit-final",
            executed_steps=1,
            max_steps=max_steps,
            status="completed",
            stop_reason="data_feature_audit_completed_retire_family",
            stop_class="policy_decision",
            final_report_path=report_path,
            report_path=settings.paths().governed_loops_dir / "loop-structural.json",
        )
        write_json(loop_report.report_path, loop_report.model_dump(mode="json"))
        return loop_report

    monkeypatch.setattr("agentic_forex.campaigns.program_loop.run_governed_loop", _fake_run_governed_loop)

    report = run_program_loop(
        settings,
        family="impulse_transition_research",
        parent_campaign_id=parent_campaign_id,
        program_id="program-structural-resume",
        max_lanes=1,
    )

    assert governed_calls == []
    assert report.stop_reason == "program_loop_no_pending_approved_lanes"
    assert report.stop_class == "policy_decision"


def test_run_program_loop_seeds_current_contract_root_with_direct_reevaluation(settings):
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="mean_reversion_pullback_af_cand_0058",
            family="scalping",
            hypothesis_class="mean_reversion_pullback",
            seed_candidate_id="AF-CAND-0058",
            max_steps=4,
        ),
    ]
    report_dir = settings.paths().reports_dir / "AF-CAND-0058"
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        report_dir / "candidate.json",
        {
            "candidate_id": "AF-CAND-0058",
            "family": "scalping",
            "market_context": {
                "session_focus": "europe_exhaustion_reversal",
            },
        },
    )
    write_json(
        report_dir / "strategy_spec.json",
        {
            "candidate_id": "AF-CAND-0058",
            "family": "scalping",
            "entry_style": "mean_reversion_pullback",
            "cost_model": {
                "canonical_source": "oanda",
                "spread_mode": "bid_ask",
                "broker_fee_model": "oanda_spread_only",
                "spread_multiplier": 1.0,
                "slippage_pips": 0.05,
                "commission_per_standard_lot_usd": 0.0,
                "fill_delay_ms": 250,
                "liquidity_session_assumption": "europe_exhaustion_reversal",
                "tick_model_assumption": "oanda_bid_ask_m1",
                "notes": [
                    "Canonical research source is OANDA bid/ask data.",
                    "Versioned execution model for research, parity, and forward-stage evaluation.",
                    "OANDA spot FX is modeled as spread-only by default unless a non-zero commission is specified.",
                    "Scalping defaults include explicit fill-delay and round-turn broker-cost assumptions.",
                ],
            },
            "execution_cost_model": {
                "canonical_source": "oanda",
                "spread_mode": "bid_ask",
                "broker_fee_model": "oanda_spread_only",
                "spread_multiplier": 1.0,
                "slippage_pips": 0.05,
                "commission_per_standard_lot_usd": 0.0,
                "fill_delay_ms": 250,
                "liquidity_session_assumption": "europe_exhaustion_reversal",
                "tick_model_assumption": "oanda_bid_ask_m1",
                "notes": [
                    "Canonical research source is OANDA bid/ask data.",
                    "Versioned execution model for research, parity, and forward-stage evaluation.",
                    "OANDA spot FX is modeled as spread-only by default unless a non-zero commission is specified.",
                    "Scalping defaults include explicit fill-delay and round-turn broker-cost assumptions.",
                ],
            },
        },
    )

    def _fake_run_governed_loop(
        settings,
        *,
        family="scalping",
        parent_campaign_id=None,
        loop_id=None,
        max_steps=8,
        allowed_step_types=None,
    ):
        report_path = settings.paths().campaigns_dir / "campaign-current-root-final" / "next_step_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            report_path,
            NextStepControllerReport(
                campaign_id="campaign-current-root-final",
                parent_campaign_id=parent_campaign_id,
                selected_step_type="re_evaluate_one_candidate",
                step_reason="Current-contract root was reevaluated directly.",
                status="completed",
                stop_reason="re_evaluation_completed_no_supported_next_step",
                candidate_scope=["AF-CAND-0058"],
                continuation_status="stop",
                stop_class="ambiguity",
                auto_continue_allowed=False,
                transition_status="hard_stop",
                report_path=report_path,
            ).model_dump(mode="json"),
        )
        loop_report = GovernedLoopReport(
            loop_id=loop_id or "loop-current-root",
            family=family,
            initial_parent_campaign_id=parent_campaign_id,
            final_parent_campaign_id="campaign-current-root-final",
            executed_steps=1,
            max_steps=max_steps,
            status="completed",
            stop_reason="re_evaluation_completed_no_supported_next_step",
            stop_class="ambiguity",
            final_report_path=report_path,
            report_path=settings.paths().governed_loops_dir / "loop-current-root.json",
        )
        write_json(loop_report.report_path, loop_report.model_dump(mode="json"))
        return loop_report

    from agentic_forex.campaigns import program_loop as program_loop_module

    original_run_governed_loop = program_loop_module.run_governed_loop
    program_loop_module.run_governed_loop = _fake_run_governed_loop
    try:
        report = run_program_loop(
            settings,
            family="scalping",
            program_id="program-current-root",
            max_lanes=1,
        )
    finally:
        program_loop_module.run_governed_loop = original_run_governed_loop

    seed_dir = settings.paths().campaigns_dir / report.lane_summaries[0].seed_campaign_id
    seed_spec = read_json(seed_dir / "spec.json")
    seed_recommendations = read_json(seed_dir / "next_recommendations.json")
    assert seed_spec["allowed_step_types"] == ["re_evaluate_one_candidate"]
    assert seed_recommendations[0]["step_type"] == "re_evaluate_one_candidate"


def test_run_program_loop_respects_max_lanes_before_seeding_next_lane(settings, monkeypatch):
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="throughput-lane-a",
            family="throughput_research",
            hypothesis_class="volatility_expansion",
            seed_candidate_id="AF-CAND-THRU-A",
            queue_kind="throughput",
            throughput_target_count=10,
            compile_budget=6,
            smoke_budget=5,
            orthogonality_metadata={
                "market_hypothesis": "directional_follow_through",
                "trigger_family": "volatility_expansion",
                "holding_profile": "intraday_continuation",
                "session_profile": "london_open",
                "regime_dependency": "high_vol_trend",
            },
            max_steps=4,
        ),
        ProgramLanePolicy(
            lane_id="throughput-lane-b",
            family="throughput_research",
            hypothesis_class="trend_pullback_retest",
            seed_candidate_id="AF-CAND-THRU-B",
            queue_kind="throughput",
            throughput_target_count=10,
            compile_budget=6,
            smoke_budget=5,
            orthogonality_metadata={
                "market_hypothesis": "trend_resumption",
                "trigger_family": "pullback_retest",
                "holding_profile": "intraday_retest",
                "session_profile": "overlap",
                "regime_dependency": "moderate_vol_trend",
            },
            max_steps=4,
        ),
    ]
    for candidate_id in ("AF-CAND-THRU-A", "AF-CAND-THRU-B"):
        report_dir = settings.paths().reports_dir / candidate_id
        report_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            report_dir / "candidate.json",
            {
                "candidate_id": candidate_id,
                "family": "throughput_research",
                "entry_style": "throughput_seed",
            },
        )

    call_count = 0

    def _fake_run_governed_loop(
        settings,
        *,
        family="throughput_research",
        parent_campaign_id=None,
        loop_id=None,
        max_steps=8,
        allowed_step_types=None,
    ):
        nonlocal call_count
        call_count += 1
        seed_dir = settings.paths().campaigns_dir / parent_campaign_id
        seed_spec = read_json(seed_dir / "spec.json")
        assert seed_spec["baseline_candidate_id"] == "AF-CAND-THRU-A"

        report_path = settings.paths().campaigns_dir / "campaign-throughput-final" / "next_step_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            report_path,
            NextStepControllerReport(
                campaign_id="campaign-throughput-final",
                parent_campaign_id=parent_campaign_id,
                selected_step_type="triage_reviewable_candidate",
                step_reason="Throughput lane triaged cleanly.",
                status="completed",
                stop_reason="triage_completed_send_to_research_lane",
                candidate_scope=["AF-CAND-THRU-A"],
                continuation_status="stop",
                stop_class="policy_decision",
                auto_continue_allowed=False,
                transition_status="move_to_next_lane",
                report_path=report_path,
            ).model_dump(mode="json"),
        )
        loop_report = GovernedLoopReport(
            loop_id=loop_id or "loop-throughput-max-lanes",
            family=family,
            initial_parent_campaign_id=parent_campaign_id,
            final_parent_campaign_id="campaign-throughput-final",
            executed_steps=1,
            max_steps=max_steps,
            status="completed",
            stop_reason="triage_completed_send_to_research_lane",
            stop_class="policy_decision",
            final_report_path=report_path,
            report_path=settings.paths().governed_loops_dir / "loop-throughput-max-lanes.json",
        )
        write_json(loop_report.report_path, loop_report.model_dump(mode="json"))
        return loop_report

    monkeypatch.setattr("agentic_forex.campaigns.program_loop.run_governed_loop", _fake_run_governed_loop)

    report = run_program_loop(
        settings,
        family="throughput_research",
        program_id="program-throughput-max-lanes",
        max_lanes=1,
    )

    assert call_count == 1
    assert report.executed_lanes == 1
    assert [summary.lane_id for summary in report.lane_summaries] == ["throughput-lane-a"]
    assert report.stop_reason == "program_loop_max_lanes_reached"


def test_run_program_loop_stops_on_seed_candidate_truth_mismatch(settings):
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="promotion_europe_pullback_continuation_af_cand_0177",
            family="session_alignment_research",
            hypothesis_class="pullback_continuation",
            seed_candidate_id="AF-CAND-0177",
            queue_kind="promotion",
            max_steps=6,
        ),
    ]
    report_dir = settings.paths().reports_dir / "AF-CAND-0177"
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        report_dir / "candidate.json",
        {
            "candidate_id": "AF-CAND-0177",
            "family": "session_alignment_research",
            "entry_style": "pullback_continuation",
        },
    )
    write_json(
        report_dir / "strategy_spec.json",
        {
            "candidate_id": "AF-CAND-0177",
            "family": "quality_gate_research",
            "entry_style": "session_breakout",
        },
    )
    write_strategy_rationale_card(settings, family="session_alignment_research", thesis="Session alignment seed requiring explicit invalidation and regime controls.", invalidation_conditions=["session structure breaks"], hostile_regimes=["macro-event dislocation"], execution_assumptions=["bounded session window"], non_deployable_conditions=["walk-forward instability"])

    report = run_program_loop(
        settings,
        family="session_alignment_research",
        program_id="program-seed-truth-mismatch",
        max_lanes=1,
    )

    assert report.executed_lanes == 0
    assert report.stop_class == "integrity_issue"
    assert "program_loop_seed_candidate_truth_mismatch" in report.stop_reason
    assert "promotion_europe_pullback_continuation_af_cand_0177" in report.stop_reason


def test_run_program_loop_rejects_retired_throughput_archetype(settings):
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="throughput-pullback-seed",
            family="throughput_research",
            hypothesis_class="pullback_continuation",
            seed_candidate_id="AF-CAND-THRU-RETIRE",
            queue_kind="throughput",
            throughput_target_count=10,
            compile_budget=6,
            smoke_budget=5,
            orthogonality_metadata={
                "market_hypothesis": "trend_resumption",
                "trigger_family": "pullback_continuation",
                "holding_profile": "intraday_continuation",
                "session_profile": "overlap",
                "regime_dependency": "moderate_vol_trend",
            },
        )
    ]
    _seed_candidate_payload(
        settings,
        candidate_id="AF-CAND-THRU-RETIRE",
        family="throughput_research",
        entry_style="pullback_continuation",
        allowed_hours=[10, 11, 12, 13],
    )
    for index in range(7):
        archived_candidate_id = f"AF-CAND-ARCH-{index:04d}"
        _seed_candidate_payload(
            settings,
            candidate_id=archived_candidate_id,
            family="archived_research",
            entry_style="pullback_continuation",
            allowed_hours=[10, 11, 12, 13],
        )
        _append_failure_record(
            settings,
            candidate_id=archived_candidate_id,
            recorded_utc="2099-03-23T10:00:00Z",
            decision="retire_lane",
        )

    report = run_program_loop(
        settings,
        family="throughput_research",
        program_id="program-retired-archetype",
        max_lanes=1,
    )

    assert report.executed_lanes == 0
    assert report.stop_class == "policy_decision"
    assert report.stop_reason == "program_loop_archetype_retired:throughput-pullback-seed:pullback_continuation:7"


def test_run_program_loop_allows_materially_distinct_archetype_despite_shared_entry_style(settings):
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="throughput-breakout-seed",
            family="throughput_research",
            hypothesis_class="session_breakout",
            seed_candidate_id="AF-CAND-THRU-BREAKOUT",
            queue_kind="throughput",
            throughput_target_count=10,
            compile_budget=6,
            smoke_budget=5,
            orthogonality_metadata={
                "market_hypothesis": "europe_open_breakout_quality",
                "trigger_family": "session_breakout",
                "holding_profile": "pre_overlap_breakout",
                "session_profile": "europe_open",
                "regime_dependency": "high_vol_breakout",
            },
        )
    ]
    _seed_candidate_payload(
        settings,
        candidate_id="AF-CAND-THRU-BREAKOUT",
        family="throughput_research",
        entry_style="session_breakout",
        allowed_hours=[7, 8, 9, 10, 11, 12],
        custom_filters=[
            {"name": "breakout_zscore_floor", "rule": "0.35"},
            {"name": "exclude_context_bucket", "rule": "mean_reversion_context"},
        ],
    )
    for index in range(7):
        archived_candidate_id = f"AF-CAND-ARCH-BREAK-{index:04d}"
        _seed_candidate_payload(
            settings,
            candidate_id=archived_candidate_id,
            family="archived_research",
            entry_style="session_breakout",
            allowed_hours=[13, 14, 15, 16],
            custom_filters=[{"name": "breakout_zscore_floor", "rule": "0.32"}],
        )
        _append_failure_record(
            settings,
            candidate_id=archived_candidate_id,
            recorded_utc="2099-03-23T10:00:00Z",
            decision="retire_lane",
        )

    report = run_program_loop(
        settings,
        family="throughput_research",
        program_id="program-breakout-not-retired",
        max_lanes=1,
    )

    assert report.stop_reason != "program_loop_archetype_retired:throughput-breakout-seed:session_breakout:7"


def test_run_program_loop_allows_new_pullback_family_despite_generic_archived_entry_style_overlap(settings, monkeypatch):
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="throughput-high-vol-pullback-seed",
            family="europe_open_high_vol_pullback_persistence_research",
            hypothesis_class="pullback_continuation",
            seed_candidate_id="AF-CAND-THRU-PULLBACK",
            queue_kind="throughput",
            throughput_target_count=10,
            compile_budget=6,
            smoke_budget=5,
            orthogonality_metadata={
                "market_hypothesis": "europe_bridge_to_pre_overlap_high_vol_persistence",
                "trigger_family": "pullback_continuation",
                "holding_profile": "short_intraday_continuation",
                "session_profile": "bridge_to_pre_overlap",
                "regime_dependency": "high_vol_trend_persistence",
            },
        )
    ]
    _seed_candidate_payload(
        settings,
        candidate_id="AF-CAND-THRU-PULLBACK",
        family="europe_open_high_vol_pullback_persistence_research",
        entry_style="pullback_continuation",
        allowed_hours=[7, 8, 9, 10, 11, 12],
        custom_filters=[
            {"name": "required_volatility_bucket", "rule": "high"},
            {"name": "exclude_context_bucket", "rule": "mean_reversion_context"},
            {"name": "pullback_zscore_limit", "rule": "0.35"},
        ],
    )
    for index in range(9):
        archived_candidate_id = f"AF-CAND-ARCH-PULL-{index:04d}"
        _seed_candidate_payload(
            settings,
            candidate_id=archived_candidate_id,
            family="archived_research",
            entry_style="pullback_continuation",
            allowed_hours=[7, 8, 9, 10, 11, 12],
        )
        _append_failure_record(
            settings,
            candidate_id=archived_candidate_id,
            recorded_utc="2099-03-23T10:00:00Z",
            decision="retire_lane",
        )

    def _fake_run_governed_loop(
        settings,
        *,
        family="europe_open_high_vol_pullback_persistence_research",
        parent_campaign_id=None,
        loop_id=None,
        max_steps=8,
        allowed_step_types=None,
    ):
        report_path = settings.paths().campaigns_dir / "campaign-pullback-final" / "next_step_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            report_path,
            NextStepControllerReport(
                campaign_id="campaign-pullback-final",
                parent_campaign_id=parent_campaign_id,
                selected_step_type="formalize_rule_candidate",
                step_reason="Seed survived retirement screening.",
                status="completed",
                stop_reason="rule_formalization_completed_with_supported_recommendation",
                candidate_scope=["AF-CAND-THRU-PULLBACK"],
                continuation_status="stop",
                stop_class="ambiguity",
                auto_continue_allowed=False,
                transition_status="hard_stop",
                report_path=report_path,
            ).model_dump(mode="json"),
        )
        loop_report = GovernedLoopReport(
            loop_id=loop_id or "loop-pullback-distinct",
            family=family,
            initial_parent_campaign_id=parent_campaign_id,
            final_parent_campaign_id="campaign-pullback-final",
            executed_steps=1,
            max_steps=max_steps,
            status="completed",
            stop_reason="rule_formalization_completed_with_supported_recommendation",
            stop_class="ambiguity",
            final_report_path=report_path,
            report_path=settings.paths().governed_loops_dir / "loop-pullback-distinct.json",
        )
        write_json(loop_report.report_path, loop_report.model_dump(mode="json"))
        return loop_report

    monkeypatch.setattr("agentic_forex.campaigns.program_loop.run_governed_loop", _fake_run_governed_loop)
    write_strategy_rationale_card(settings, family="europe_open_high_vol_pullback_persistence_research", thesis="High-vol pullback persistence seed requiring explicit invalidation and regime controls.", invalidation_conditions=["pullback depth exceeds threshold"], hostile_regimes=["low-vol compression"], execution_assumptions=["bounded spread envelope"], non_deployable_conditions=["walk-forward instability"])

    report = run_program_loop(
        settings,
        family="europe_open_high_vol_pullback_persistence_research",
        program_id="program-pullback-not-retired",
        max_lanes=1,
    )

    assert report.stop_reason != "program_loop_archetype_retired:throughput-high-vol-pullback-seed:pullback_continuation:9"
    assert report.executed_lanes == 1


def test_run_program_loop_rejects_low_novelty_seed_against_archived_candidate(settings):
    settings.program.archetype_retirement_enabled = False
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="throughput-balance-seed",
            family="throughput_research",
            hypothesis_class="balance_area_breakout",
            seed_candidate_id="AF-CAND-THRU-NOVEL",
            queue_kind="throughput",
            throughput_target_count=10,
            compile_budget=6,
            smoke_budget=5,
            orthogonality_metadata={
                "market_hypothesis": "balance_transition",
                "trigger_family": "balance_breakout",
                "holding_profile": "intraday_continuation",
                "session_profile": "london_open",
                "regime_dependency": "low_vol_transition",
            },
        )
    ]
    _seed_candidate_payload(
        settings,
        candidate_id="AF-CAND-THRU-NOVEL",
        family="throughput_research",
        entry_style="balance_area_breakout",
        allowed_hours=[7, 8, 9, 10, 11],
        custom_filters=[{"name": "breakout_zscore_floor", "rule": "0.45"}],
    )
    _seed_candidate_payload(
        settings,
        candidate_id="AF-CAND-ARCH-NOVEL",
        family="archived_research",
        entry_style="balance_area_breakout",
        allowed_hours=[7, 8, 9, 10, 11],
        custom_filters=[{"name": "breakout_zscore_floor", "rule": "0.45"}],
    )
    _append_failure_record(
        settings,
        candidate_id="AF-CAND-ARCH-NOVEL",
        recorded_utc="2099-03-23T10:00:00Z",
        decision="archive_descendant_branch",
    )

    report = run_program_loop(
        settings,
        family="throughput_research",
        program_id="program-low-novelty",
        max_lanes=1,
    )

    assert report.executed_lanes == 0
    assert report.stop_class == "policy_decision"
    assert report.stop_reason.startswith("program_loop_low_novelty_seed:throughput-balance-seed:AF-CAND-ARCH-NOVEL:")


def test_run_program_loop_resumes_active_parent_lane_without_reapplying_seed_gates(settings, monkeypatch):
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="throughput-trend-retest-seed",
            family="horizon_momentum_research",
            hypothesis_class="trend_retest",
            seed_candidate_id="AF-CAND-THRU-TREND-RETEST",
            queue_kind="throughput",
            throughput_target_count=10,
            required_evidence_tags=["momentum_horizon_correlation"],
            orthogonality_metadata={
                "market_hypothesis": "lagged_retest_momentum",
                "trigger_family": "trend_retest",
                "holding_profile": "medium_intraday_retest",
                "session_profile": "overlap_core",
                "regime_dependency": "moderate_vol_trend",
            },
        )
    ]
    _seed_candidate_payload(
        settings,
        candidate_id="AF-CAND-THRU-TREND-RETEST",
        family="horizon_momentum_research",
        entry_style="trend_retest",
        allowed_hours=[11, 12, 13, 14],
    )
    for index in range(7):
        archived_candidate_id = f"AF-CAND-TREND-ARCH-{index:04d}"
        _seed_candidate_payload(
            settings,
            candidate_id=archived_candidate_id,
            family="archived_research",
            entry_style="trend_retest",
            allowed_hours=[11, 12, 13, 14],
        )
        _append_failure_record(
            settings,
            candidate_id=archived_candidate_id,
            recorded_utc="2099-03-23T10:00:00Z",
            decision="retire_lane",
        )

    parent_campaign_id = "campaign-active-parent"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        parent_dir / "state.json",
        {
            "campaign_id": parent_campaign_id,
            "family": "horizon_momentum_research",
            "status": "completed",
            "baseline_candidate_id": "AF-CAND-THRU-TREND-RETEST",
            "active_candidate_ids": ["AF-CAND-THRU-TREND-RETEST"],
            "last_report_path": str(parent_dir / "next_step_report.json"),
        },
    )
    write_json(
        parent_dir / "next_step_report.json",
        NextStepControllerReport(
            campaign_id=parent_campaign_id,
            parent_campaign_id="campaign-grandparent",
            selected_step_type="hypothesis_audit",
            step_reason="Resume the active audit lane.",
            status="completed",
            stop_reason="hypothesis_audit_completed_hold_reference_blocked_by_robustness",
            candidate_scope=["AF-CAND-THRU-TREND-RETEST"],
            continuation_status="stop",
            stop_class="policy_decision",
            auto_continue_allowed=False,
            transition_status="continue_lane",
            report_path=parent_dir / "next_step_report.json",
        ).model_dump(mode="json"),
    )

    governed_calls: list[str | None] = []

    def _fake_run_governed_loop(
        settings,
        *,
        family="horizon_momentum_research",
        parent_campaign_id=None,
        loop_id=None,
        max_steps=8,
        allowed_step_types=None,
    ):
        governed_calls.append(parent_campaign_id)
        report_path = settings.paths().campaigns_dir / "campaign-active-parent-final" / "next_step_report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(
            report_path,
            NextStepControllerReport(
                campaign_id="campaign-active-parent-final",
                parent_campaign_id=parent_campaign_id,
                selected_step_type="hypothesis_audit",
                step_reason="Continue the already active lane.",
                status="completed",
                stop_reason="hypothesis_audit_completed_hold_reference_blocked_by_robustness",
                candidate_scope=["AF-CAND-THRU-TREND-RETEST"],
                continuation_status="stop",
                stop_class="policy_decision",
                auto_continue_allowed=False,
                transition_status="hard_stop",
                report_path=report_path,
            ).model_dump(mode="json"),
        )
        loop_report = GovernedLoopReport(
            loop_id=loop_id or "loop-active-parent",
            family=family,
            initial_parent_campaign_id=parent_campaign_id,
            final_parent_campaign_id="campaign-active-parent-final",
            executed_steps=1,
            max_steps=max_steps,
            status="completed",
            stop_reason="hypothesis_audit_completed_hold_reference_blocked_by_robustness",
            stop_class="policy_decision",
            final_report_path=report_path,
            report_path=settings.paths().governed_loops_dir / "loop-active-parent.json",
        )
        write_json(loop_report.report_path, loop_report.model_dump(mode="json"))
        return loop_report

    monkeypatch.setattr("agentic_forex.campaigns.program_loop.run_governed_loop", _fake_run_governed_loop)
    write_strategy_rationale_card(settings, family="horizon_momentum_research", thesis="Horizon momentum retest seed requiring explicit invalidation and regime controls.", invalidation_conditions=["momentum horizon breaks"], hostile_regimes=["volatility regime shift"], execution_assumptions=["bounded retest window"], non_deployable_conditions=["walk-forward instability"])

    report = run_program_loop(
        settings,
        family="horizon_momentum_research",
        parent_campaign_id=parent_campaign_id,
        program_id="program-resume-active-parent",
        max_lanes=1,
    )

    assert governed_calls == [parent_campaign_id]
    assert report.final_parent_campaign_id == "campaign-active-parent-final"
    assert report.stop_reason == "hypothesis_audit_completed_hold_reference_blocked_by_robustness"


def _seed_candidate_payload(
    settings,
    *,
    candidate_id: str,
    family: str,
    entry_style: str,
    allowed_hours: list[int],
    custom_filters: list[dict[str, str]] | None = None,
) -> None:
    report_dir = settings.paths().reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        report_dir / "candidate.json",
        {
            "candidate_id": candidate_id,
            "family": family,
            "title": f"Seed {candidate_id}",
            "thesis": "Deterministic seed candidate.",
            "source_citations": ["SRC-001"],
            "strategy_hypothesis": "Explicit session-conditioned hypothesis.",
            "market_context": {
                "session_focus": "test_session",
                "volatility_preference": "moderate",
                "directional_bias": "both",
                "execution_notes": ["test seed"],
                "allowed_hours_utc": allowed_hours,
            },
            "setup_summary": "Wait for the deterministic trigger.",
            "entry_summary": "Enter when the trigger and filters align.",
            "exit_summary": "Exit via fixed stop, target, or timeout.",
            "risk_summary": "Single-position bounded test seed.",
            "entry_style": entry_style,
            "holding_bars": 48,
            "signal_threshold": 0.9,
            "stop_loss_pips": 6.0,
            "take_profit_pips": 9.0,
            "custom_filters": custom_filters or [],
            "enable_news_blackout": True,
            "notes": [],
            "quality_flags": [],
            "contradiction_summary": [],
            "critic_notes": [],
        },
    )


def _append_failure_record(settings, *, candidate_id: str, recorded_utc: str, decision: str) -> None:
    failure_path = settings.paths().observational_knowledge_dir / "failure_records.jsonl"
    failure_path.parent.mkdir(parents=True, exist_ok=True)
    with failure_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "failure_id": f"failure-{candidate_id}",
                    "candidate_id": candidate_id,
                    "stage": "archive_decision",
                    "failure_code": "empirical_failure",
                    "details": {"decision": decision},
                    "artifact_paths": {},
                    "recorded_utc": recorded_utc,
                }
            )
            + "\n"
        )
