from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from conftest import create_oanda_candles_json

from agentic_forex.approval.models import ApprovalRecord
from agentic_forex.approval.service import record_approval
from agentic_forex.campaigns import run_governed_loop, run_next_step
from agentic_forex.campaigns.next_step import _apply_continuation_metadata, _build_next_recommendations
from agentic_forex.governance import CampaignSpec, CampaignState
from agentic_forex.governance.models import (
    CandidateDiagnosticReport,
    CandidateReevaluationReport,
    DiagnosticSliceReport,
    ForwardStageReport,
    HypothesisAuditReport,
    NextStepControllerReport,
    NextStepRecommendation,
)
from agentic_forex.governance.trial_ledger import append_failure_record
from agentic_forex.market_data.ingest import ingest_oanda_json
from agentic_forex.mt5.models import MT5ParityReport, MT5ValidationReport
from agentic_forex.mt5.service import ParityPolicyError
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows.contracts import (
    CandidateDraft,
    MarketContextSummary,
    RiskPolicy,
    SessionPolicy,
    SetupLogic,
    StrategySpec,
)


def test_run_next_step_creates_child_campaign_and_diagnostic_recommendation(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    parent_campaign_id = "campaign-parent-bounded"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-BASE",
        target_candidate_ids=["AF-CAND-0014", "AF-CAND-0015"],
        max_iterations=1,
        max_new_candidates=0,
        trial_cap_per_family=12,
        notes=["Parent comparison campaign for next-step testing."],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-BASE",
        active_candidate_ids=["AF-CAND-BASE", "AF-CAND-0014", "AF-CAND-0015"],
        iterations_run=3,
        trials_consumed=9,
        stop_reason="bounded_comparison_completed",
        state_path=parent_dir / "state.json",
        updated_utc="2026-03-21T02:15:45Z",
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))

    _seed_candidate_reports(settings.paths().reports_dir / "AF-CAND-0014", "AF-CAND-0014")
    _seed_candidate_reports(settings.paths().reports_dir / "AF-CAND-0015", "AF-CAND-0015")

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-next-step",
        allowed_step_types=["diagnose_existing_candidates"],
    )

    assert report.selected_step_type == "diagnose_existing_candidates"
    assert report.status == "completed"
    assert report.parent_campaign_id == parent_campaign_id
    assert report.candidate_scope == ["AF-CAND-0014", "AF-CAND-0015"]
    assert report.report_path.exists()
    assert len(report.candidate_reports) == 2
    assert report.next_recommendations
    assert report.next_recommendations[0].step_type == "mutate_one_candidate"
    assert report.next_recommendations[0].candidate_id == "AF-CAND-0014"
    assert "overlap" in report.next_recommendations[0].rationale

    child_dir = settings.paths().campaigns_dir / "campaign-child-next-step"
    child_state = read_json(child_dir / "state.json")
    assert child_state["parent_campaign_id"] == parent_campaign_id
    assert child_state["current_step_type"] == "diagnose_existing_candidates"
    assert child_state["status"] == "completed"
    assert child_state["trials_consumed"] == 11
    assert (child_dir / "next_recommendations.json").exists()

    ledger_path = settings.paths().experiments_dir / "trial_ledger.jsonl"
    entries = [item for item in ledger_path.read_text(encoding="utf-8").splitlines() if item.strip()]
    assert len(entries) == 2
    assert all("diagnose_existing_candidates" in item for item in entries)


def test_build_next_recommendations_supports_single_candidate_session_mutation(settings):
    report_dir = settings.paths().reports_dir / "AF-CAND-DIAG-SINGLE"
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        report_dir / "strategy_spec.json",
        {
            "candidate_id": "AF-CAND-DIAG-SINGLE",
            "family": "day_trading",
            "session_policy": {"allowed_hours_utc": [6, 7, 8, 9]},
        },
    )

    candidate_report = CandidateDiagnosticReport(
        candidate_id="AF-CAND-DIAG-SINGLE",
        readiness_status="robustness_provisional",
        supported_slices=[
            DiagnosticSliceReport(
                slice_type="session_bucket",
                slice_label="asia",
                first_window_trade_count=18,
                later_window_trade_count=42,
                first_window_expectancy_pips=-2.1,
                later_window_expectancy_pips=0.8,
                expectancy_improvement_pips=2.9,
                first_window_loss_share=0.41,
                evidence_score=6.5,
                supported=True,
            )
        ],
        primary_issue="session_bucket:asia",
        recommended_mutation="Trim asia exposure by removing allowed_hours_utc [6].",
        artifact_paths={"review_packet_path": str(report_dir / "review_packet.json")},
    )

    recommendations = _build_next_recommendations(
        settings,
        candidate_reports=[candidate_report],
        candidate_scope=["AF-CAND-DIAG-SINGLE"],
    )

    assert len(recommendations) == 1
    recommendation = recommendations[0]
    assert recommendation.step_type == "mutate_one_candidate"
    assert recommendation.step_payload["mutation_type"] == "trim_allowed_hours"
    assert recommendation.step_payload["removed_hours_utc"] == [6]


@pytest.mark.parametrize("family", ["throughput_research", "market_structure_research"])
def test_build_next_recommendations_supports_throughput_overlap_trim_with_news_blackout(settings, family):
    report_dir = settings.paths().reports_dir / f"AF-CAND-DIAG-THRU-{family}"
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        report_dir / "strategy_spec.json",
        {
            "candidate_id": f"AF-CAND-DIAG-THRU-{family}",
            "family": family,
            "session_policy": {"allowed_hours_utc": [12, 13, 14, 15, 16]},
            "news_policy": {"enabled": False},
        },
    )

    candidate_report = CandidateDiagnosticReport(
        candidate_id=f"AF-CAND-DIAG-THRU-{family}",
        readiness_status="robustness_provisional",
        supported_slices=[
            DiagnosticSliceReport(
                slice_type="session_bucket",
                slice_label="overlap",
                first_window_trade_count=30,
                later_window_trade_count=53,
                first_window_expectancy_pips=-1.14,
                later_window_expectancy_pips=-0.01,
                expectancy_improvement_pips=1.13,
                first_window_loss_share=1.0,
                evidence_score=4.4,
                supported=True,
            )
        ],
        primary_issue="session_bucket:overlap",
        recommended_mutation="Trim overlap exposure by removing allowed_hours_utc [13, 14, 15, 16].",
        artifact_paths={"review_packet_path": str(report_dir / "review_packet.json")},
    )

    recommendations = _build_next_recommendations(
        settings,
        candidate_reports=[candidate_report],
        candidate_scope=[f"AF-CAND-DIAG-THRU-{family}"],
    )

    assert len(recommendations) == 1
    recommendation = recommendations[0]
    assert recommendation.step_type == "mutate_one_candidate"
    assert recommendation.step_payload["mutation_type"] == "trim_allowed_hours"
    assert recommendation.step_payload["removed_hours_utc"] == [13, 14, 15, 16]
    assert recommendation.step_payload["enable_news_blackout"] is True


def test_build_next_recommendations_rejects_session_trim_that_clears_schedule(settings):
    report_dir = settings.paths().reports_dir / "AF-CAND-DIAG-CLEAR-SCHEDULE"
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        report_dir / "strategy_spec.json",
        {
            "candidate_id": "AF-CAND-DIAG-CLEAR-SCHEDULE",
            "family": "market_structure_research",
            "session_policy": {"allowed_hours_utc": [13, 14, 15, 16]},
            "news_policy": {"enabled": False},
        },
    )

    candidate_report = CandidateDiagnosticReport(
        candidate_id="AF-CAND-DIAG-CLEAR-SCHEDULE",
        readiness_status="robustness_provisional",
        supported_slices=[
            DiagnosticSliceReport(
                slice_type="session_bucket",
                slice_label="overlap",
                first_window_trade_count=22,
                later_window_trade_count=39,
                first_window_expectancy_pips=-1.02,
                later_window_expectancy_pips=-0.18,
                expectancy_improvement_pips=0.84,
                first_window_loss_share=0.92,
                evidence_score=4.1,
                supported=True,
            )
        ],
        primary_issue="session_bucket:overlap",
        recommended_mutation="Trim overlap exposure.",
        artifact_paths={"review_packet_path": str(report_dir / "review_packet.json")},
    )

    recommendations = _build_next_recommendations(
        settings,
        candidate_reports=[candidate_report],
        candidate_scope=["AF-CAND-DIAG-CLEAR-SCHEDULE"],
    )

    assert len(recommendations) == 1
    recommendation = recommendations[0]
    assert recommendation.step_type == "hypothesis_audit"
    assert recommendation.candidate_id == "AF-CAND-DIAG-CLEAR-SCHEDULE"


def test_build_next_recommendations_rejects_shared_session_trim_that_clears_schedule(settings):
    candidate_ids = ["AF-CAND-DIAG-CLEAR-SHARED-A", "AF-CAND-DIAG-CLEAR-SHARED-B"]
    candidate_reports = []
    for candidate_id in candidate_ids:
        report_dir = settings.paths().reports_dir / candidate_id
        report_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            report_dir / "strategy_spec.json",
            {
                "candidate_id": candidate_id,
                "family": "market_structure_research",
                "session_policy": {"allowed_hours_utc": [7, 8, 9, 10]},
                "news_policy": {"enabled": False},
            },
        )
        candidate_reports.append(
            CandidateDiagnosticReport(
                candidate_id=candidate_id,
                readiness_status="robustness_provisional",
                supported_slices=[
                    DiagnosticSliceReport(
                        slice_type="session_bucket",
                        slice_label="europe",
                        first_window_trade_count=18,
                        later_window_trade_count=29,
                        first_window_expectancy_pips=-0.91,
                        later_window_expectancy_pips=-0.15,
                        expectancy_improvement_pips=0.76,
                        first_window_loss_share=0.88,
                        evidence_score=4.0,
                        supported=True,
                    )
                ],
                primary_issue="session_bucket:europe",
                recommended_mutation="Trim Europe exposure.",
                artifact_paths={"review_packet_path": str(report_dir / "review_packet.json")},
            )
        )

    recommendations = _build_next_recommendations(
        settings,
        candidate_reports=candidate_reports,
        candidate_scope=candidate_ids,
    )

    assert len(recommendations) == 1
    recommendation = recommendations[0]
    assert recommendation.step_type == "hypothesis_audit"
    assert recommendation.candidate_id == "AF-CAND-DIAG-CLEAR-SHARED-A"


def test_build_next_recommendations_falls_back_to_single_candidate_context_mutation(settings):
    report_dir = settings.paths().reports_dir / "AF-CAND-DIAG-CONTEXT"
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        report_dir / "strategy_spec.json",
        {
            "candidate_id": "AF-CAND-DIAG-CONTEXT",
            "family": "day_trading",
            "session_policy": {"allowed_hours_utc": [7, 8, 9, 10, 11, 12]},
        },
    )

    candidate_report = CandidateDiagnosticReport(
        candidate_id="AF-CAND-DIAG-CONTEXT",
        readiness_status="robustness_provisional",
        supported_slices=[
            DiagnosticSliceReport(
                slice_type="session_bucket",
                slice_label="europe",
                first_window_trade_count=44,
                later_window_trade_count=90,
                first_window_expectancy_pips=-1.1,
                later_window_expectancy_pips=1.0,
                expectancy_improvement_pips=2.1,
                first_window_loss_share=1.0,
                evidence_score=5.4,
                supported=True,
            ),
            DiagnosticSliceReport(
                slice_type="context_bucket",
                slice_label="trend_context",
                first_window_trade_count=44,
                later_window_trade_count=90,
                first_window_expectancy_pips=-1.1,
                later_window_expectancy_pips=1.0,
                expectancy_improvement_pips=2.1,
                first_window_loss_share=1.0,
                evidence_score=5.3,
                supported=True,
            ),
        ],
        primary_issue="session_bucket:europe",
        recommended_mutation="Suppress trend-context entries before broader lane retirement.",
        artifact_paths={"review_packet_path": str(report_dir / "review_packet.json")},
    )

    recommendations = _build_next_recommendations(
        settings,
        candidate_reports=[candidate_report],
        candidate_scope=["AF-CAND-DIAG-CONTEXT"],
    )

    assert len(recommendations) == 1
    recommendation = recommendations[0]
    assert recommendation.step_type == "mutate_one_candidate"
    assert recommendation.step_payload["mutation_type"] == "suppress_context_bucket"
    assert recommendation.step_payload["context_bucket"] == "trend_context"


def test_build_next_recommendations_redirects_duplicate_context_mutation_to_hypothesis_audit(settings):
    _seed_contract_context_candidate(
        settings,
        candidate_id="AF-CAND-DIAG-DUP-SOURCE",
        exclude_context_bucket="trend_context",
    )
    _seed_contract_context_candidate(
        settings,
        candidate_id="AF-CAND-DIAG-DUP-EQUIV",
        exclude_context_bucket="mean_reversion_context",
    )
    report_dir = settings.paths().reports_dir / "AF-CAND-DIAG-DUP-SOURCE"
    candidate_report = CandidateDiagnosticReport(
        candidate_id="AF-CAND-DIAG-DUP-SOURCE",
        readiness_status="robustness_provisional",
        supported_slices=[
            DiagnosticSliceReport(
                slice_type="context_bucket",
                slice_label="mean_reversion_context",
                first_window_trade_count=40,
                later_window_trade_count=88,
                first_window_expectancy_pips=-1.4,
                later_window_expectancy_pips=0.8,
                expectancy_improvement_pips=2.2,
                first_window_loss_share=0.61,
                evidence_score=5.8,
                supported=True,
            )
        ],
        primary_issue="context_bucket:mean_reversion_context",
        recommended_mutation="Suppress mean-reversion entries before further search.",
        artifact_paths={"review_packet_path": str(report_dir / "review_packet.json")},
    )

    recommendations = _build_next_recommendations(
        settings,
        candidate_reports=[candidate_report],
        candidate_scope=["AF-CAND-DIAG-DUP-SOURCE"],
    )

    assert len(recommendations) == 1
    recommendation = recommendations[0]
    assert recommendation.step_type == "hypothesis_audit"
    assert recommendation.candidate_id == "AF-CAND-DIAG-DUP-SOURCE"


def test_run_next_step_stops_when_binding_recommendation_is_unsupported(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    parent_campaign_id = "campaign-parent-binding"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-BASE",
        target_candidate_ids=["AF-CAND-0014", "AF-CAND-0015"],
        notes=["Parent campaign with binding recommendation."],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-BASE",
        active_candidate_ids=["AF-CAND-BASE", "AF-CAND-0014", "AF-CAND-0015"],
        iterations_run=1,
        trials_consumed=2,
        stop_reason="diagnosis_completed_with_supported_recommendation",
        state_path=parent_dir / "state.json",
        updated_utc="2026-03-21T03:00:00Z",
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(
        parent_dir / "next_recommendations.json",
        [
            {
                "step_type": "mutate_one_candidate",
                "candidate_id": "AF-CAND-0014",
                "rationale": "Use the supported session adjustment next.",
                "binding": True,
                "evidence_status": "supported",
            }
        ],
    )

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-stop",
        allowed_step_types=["diagnose_existing_candidates"],
    )

    assert report.status == "stopped"
    assert report.selected_step_type is None
    assert report.stop_reason == "binding_recommendation_outside_allowed_step_types"
    assert not report.next_recommendations
    assert report.report_path.exists()


def test_run_next_step_mutates_candidate_from_binding_recommendation(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    parent_campaign_id = "campaign-parent-mutate"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-BASE",
        target_candidate_ids=["AF-CAND-0014"],
        notes=["Parent campaign with binding mutation recommendation."],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-BASE",
        active_candidate_ids=["AF-CAND-BASE", "AF-CAND-0014"],
        iterations_run=1,
        trials_consumed=2,
        stop_reason="diagnosis_completed_with_supported_recommendation",
        state_path=parent_dir / "state.json",
        updated_utc="2026-03-21T04:00:00Z",
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(
        parent_dir / "next_recommendations.json",
        [
            {
                "step_type": "mutate_one_candidate",
                "candidate_id": "AF-CAND-0014",
                "rationale": "Remove overlap hours [13, 14] from allowed_hours_utc, then re-evaluate without broadening scope.",
                "binding": True,
                "evidence_status": "supported",
                "step_payload": {
                    "mutation_type": "trim_allowed_hours",
                    "removed_hours_utc": [13, 14],
                },
            }
        ],
    )
    _seed_candidate_spec(settings, candidate_id="AF-CAND-0014", allowed_hours=[6, 7, 8, 9, 10, 11, 12, 13, 14])

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-mutate",
        allowed_step_types=["mutate_one_candidate"],
    )

    assert report.selected_step_type == "mutate_one_candidate"
    assert report.status == "completed"
    assert len(report.mutation_reports) == 1
    mutation_report = report.mutation_reports[0]
    assert mutation_report.source_candidate_id == "AF-CAND-0014"
    assert mutation_report.readiness_status == "ea_spec_complete"
    assert report.next_recommendations
    assert report.next_recommendations[0].step_type == "re_evaluate_one_candidate"
    assert report.next_recommendations[0].candidate_id == mutation_report.mutated_candidate_id
    assert report.continuation_status == "continue"
    assert report.stop_class == "none"
    assert report.auto_continue_allowed is True
    assert report.recommended_follow_on_step == "re_evaluate_one_candidate"
    assert report.max_safe_follow_on_steps == 1

    mutated_spec = read_json(Path(mutation_report.artifact_paths["spec_path"]))
    assert mutated_spec["session_policy"]["allowed_hours_utc"] == [6, 7, 8, 9, 10, 11, 12]
    assert Path(mutation_report.artifact_paths["data_provenance_path"]).exists()
    assert Path(mutation_report.artifact_paths["environment_snapshot_path"]).exists()

    ledger_path = settings.paths().experiments_dir / "trial_ledger.jsonl"
    entries = [item for item in ledger_path.read_text(encoding="utf-8").splitlines() if item.strip()]
    assert len(entries) == 1
    assert "mutate_one_candidate" in entries[0]


def test_run_next_step_mutates_throughput_candidate_with_news_blackout(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    candidate_id = "AF-CAND-THRU-MUTATE"
    report_dir = settings.paths().reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    candidate = CandidateDraft(
        candidate_id=candidate_id,
        family="throughput_research",
        title="Throughput Trend Retest",
        thesis="Bounded throughput candidate.",
        source_citations=["SRC-THRU"],
        strategy_hypothesis="Trend pullback retest under overlap conditions.",
        market_context=MarketContextSummary(
            session_focus="overlap_trend_retest",
            volatility_preference="moderate",
            directional_bias="both",
            execution_notes=["Throughput controller test seed."],
            allowed_hours_utc=[12, 13, 14, 15, 16],
        ),
        setup_summary="Test throughput setup.",
        entry_summary="Test throughput entry summary.",
        exit_summary="Test throughput exit summary.",
        risk_summary="Test throughput risk summary.",
        entry_style="trend_pullback_retest",
        holding_bars=36,
        signal_threshold=0.88,
        stop_loss_pips=9.0,
        take_profit_pips=15.0,
    )
    spec = StrategySpec(
        candidate_id=candidate_id,
        family="throughput_research",
        benchmark_group_id=candidate_id,
        variant_name="controller_seed",
        session_policy=SessionPolicy(
            name="candidate_defined_intraday",
            allowed_sessions=["intraday_active_windows"],
            allowed_hours_utc=[12, 13, 14, 15, 16],
            notes=["controller_seed"],
        ),
        side_policy="both",
        setup_logic=SetupLogic(
            style="trend_pullback_retest", summary="Test throughput setup.", trigger_conditions=["Retest confirmation"]
        ),
        filters=[{"name": "volatility_preference", "rule": "moderate"}],
        risk_policy=RiskPolicy(stop_loss_pips=9.0, take_profit_pips=15.0, notes=["Controller test risk policy."]),
        source_citations=["SRC-THRU"],
        notes=["Seeded for throughput next-step controller tests."],
        entry_style="trend_pullback_retest",
        holding_bars=36,
        signal_threshold=0.88,
        stop_loss_pips=9.0,
        take_profit_pips=15.0,
        news_policy={"enabled": False, "currencies": ["EUR", "USD"]},
    )
    write_json(report_dir / "candidate.json", candidate.model_dump(mode="json"))
    write_json(report_dir / "strategy_spec.json", spec.model_dump(mode="json"))

    parent_campaign_id = "campaign-parent-throughput-mutate"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="throughput_research",
        baseline_candidate_id=candidate_id,
        target_candidate_ids=[candidate_id],
        queue_kind="promotion",
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="throughput_research",
        status="completed",
        baseline_candidate_id=candidate_id,
        active_candidate_ids=[candidate_id],
        iterations_run=1,
        trials_consumed=1,
        stop_reason="diagnosis_completed_with_supported_recommendation",
        state_path=parent_dir / "state.json",
        updated_utc="2026-03-22T21:10:00Z",
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(
        parent_dir / "next_recommendations.json",
        [
            {
                "step_type": "mutate_one_candidate",
                "candidate_id": candidate_id,
                "rationale": "Remove overlap hours [13, 14, 15, 16] from allowed_hours_utc and enable the governed calendar blackout, then re-evaluate without broadening scope.",
                "binding": True,
                "evidence_status": "supported",
                "step_payload": {
                    "mutation_type": "trim_allowed_hours",
                    "removed_hours_utc": [13, 14, 15, 16],
                    "enable_news_blackout": True,
                },
            }
        ],
    )

    report = run_next_step(
        settings,
        family="throughput_research",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-throughput-mutate",
        allowed_step_types=["mutate_one_candidate"],
    )

    mutation_report = report.mutation_reports[0]
    mutated_spec = read_json(Path(mutation_report.artifact_paths["spec_path"]))
    assert mutated_spec["session_policy"]["allowed_hours_utc"] == [12]
    assert mutated_spec["news_policy"]["enabled"] is True
    assert mutated_spec["risk_envelope"]["news_event_policy"] == "calendar_blackout"


def test_run_next_step_stops_on_candidate_id_collision(settings, monkeypatch):
    parent_campaign_id = "campaign-parent-collision"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-BASE",
        target_candidate_ids=["AF-CAND-0014"],
        notes=["Parent campaign for collision test."],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-BASE",
        active_candidate_ids=["AF-CAND-BASE", "AF-CAND-0014"],
        stop_reason="diagnosis_completed_with_supported_recommendation",
        state_path=parent_dir / "state.json",
        updated_utc="2026-03-22T21:58:00Z",
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(
        parent_dir / "next_recommendations.json",
        [
            {
                "step_type": "mutate_one_candidate",
                "candidate_id": "AF-CAND-0014",
                "rationale": "Use the supported session adjustment next.",
                "binding": True,
                "evidence_status": "supported",
                "step_payload": {
                    "mutation_type": "trim_allowed_hours",
                    "removed_hours_utc": [13, 14],
                },
            }
        ],
    )

    _seed_candidate_spec(settings, candidate_id="AF-CAND-0014", allowed_hours=[6, 7, 8, 9, 10, 11, 12, 13, 14])
    occupied_dir = settings.paths().reports_dir / "AF-CAND-0999"
    occupied_dir.mkdir(parents=True, exist_ok=True)
    write_json(occupied_dir / "candidate.json", {"candidate_id": "AF-CAND-0999", "sentinel": "keep"})

    monkeypatch.setattr("agentic_forex.campaigns.next_step.next_candidate_id", lambda settings: "AF-CAND-0999")

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-collision",
        allowed_step_types=["mutate_one_candidate"],
    )

    assert report.selected_step_type == "mutate_one_candidate"
    assert report.status == "stopped"
    assert report.stop_reason == "candidate_id_collision_detected"
    assert report.stop_class == "integrity_issue"
    assert read_json(occupied_dir / "candidate.json")["sentinel"] == "keep"


def test_run_next_step_redirects_duplicate_mutation_to_hypothesis_audit(settings):
    source_candidate_id = "AF-CAND-DUP-SOURCE"
    equivalent_candidate_id = "AF-CAND-DUP-EQUIV"
    _seed_contract_context_candidate(
        settings,
        candidate_id=source_candidate_id,
        exclude_context_bucket="trend_context",
    )
    _seed_contract_context_candidate(
        settings,
        candidate_id=equivalent_candidate_id,
        exclude_context_bucket="mean_reversion_context",
    )

    parent_campaign_id = "campaign-parent-duplicate-mutation"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="day_trading",
        baseline_candidate_id="AF-CAND-BASE",
        target_candidate_ids=[source_candidate_id],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="day_trading",
        status="completed",
        baseline_candidate_id="AF-CAND-BASE",
        active_candidate_ids=[source_candidate_id],
        iterations_run=1,
        trials_consumed=1,
        stop_reason="diagnosis_completed_with_supported_recommendation",
        state_path=parent_dir / "state.json",
        updated_utc="2026-03-22T17:30:00Z",
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(
        parent_dir / "next_recommendations.json",
        [
            {
                "step_type": "mutate_one_candidate",
                "candidate_id": source_candidate_id,
                "rationale": "Suppress mean-reversion entries under the bounded controller.",
                "binding": True,
                "evidence_status": "supported",
                "step_payload": {
                    "mutation_type": "suppress_context_bucket",
                    "context_bucket": "mean_reversion_context",
                },
            }
        ],
    )

    report = run_next_step(
        settings,
        family="day_trading",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-duplicate-mutation",
        allowed_step_types=["mutate_one_candidate"],
    )

    assert report.selected_step_type == "mutate_one_candidate"
    assert report.status == "completed"
    assert not report.mutation_reports
    assert report.stop_reason == "mutation_duplicate_variant_redirected_to_hypothesis_audit"
    assert report.next_recommendations
    assert report.next_recommendations[0].step_type == "hypothesis_audit"
    assert report.continuation_status == "continue"
    assert report.stop_class == "none"
    assert report.auto_continue_allowed is True


def test_run_next_step_re_evaluates_mutated_candidate_from_binding_recommendation(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)
    _seed_candidate_spec(settings, candidate_id="AF-CAND-0014", allowed_hours=[6, 7, 8, 9, 10, 11, 12, 13, 14])

    parent_campaign_id = "campaign-parent-reeval-seed"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-BASE",
        target_candidate_ids=["AF-CAND-0014"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-BASE",
        active_candidate_ids=["AF-CAND-BASE", "AF-CAND-0014"],
        iterations_run=1,
        trials_consumed=1,
        stop_reason="diagnosis_completed_with_supported_recommendation",
        state_path=parent_dir / "state.json",
        updated_utc="2026-03-21T05:00:00Z",
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(
        parent_dir / "next_recommendations.json",
        [
            {
                "step_type": "mutate_one_candidate",
                "candidate_id": "AF-CAND-0014",
                "rationale": "Remove overlap hours [13, 14] from allowed_hours_utc, then re-evaluate without broadening scope.",
                "binding": True,
                "evidence_status": "supported",
                "step_payload": {
                    "mutation_type": "trim_allowed_hours",
                    "removed_hours_utc": [13, 14],
                },
            }
        ],
    )
    mutation_report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-mutate-for-reeval",
        allowed_step_types=["mutate_one_candidate"],
    )
    mutated_candidate_id = mutation_report.next_recommendations[0].candidate_id

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id="campaign-child-mutate-for-reeval",
        campaign_id="campaign-child-reeval",
        allowed_step_types=["re_evaluate_one_candidate"],
    )

    assert report.selected_step_type == "re_evaluate_one_candidate"
    assert report.status == "completed"
    assert len(report.reevaluation_reports) == 1
    reevaluation_report = report.reevaluation_reports[0]
    assert reevaluation_report.candidate_id == mutated_candidate_id
    assert Path(reevaluation_report.artifact_paths["review_packet_path"]).exists()
    assert Path(reevaluation_report.artifact_paths["backtest_summary_path"]).exists()
    assert Path(reevaluation_report.artifact_paths["robustness_report_path"]).exists()
    assert reevaluation_report.artifact_references["dataset_snapshot"]
    assert reevaluation_report.artifact_references["environment_snapshot"]
    assert report.next_recommendations
    assert report.next_recommendations[0].step_type in {"diagnose_existing_candidates", "run_parity"}

    ledger_path = settings.paths().experiments_dir / "trial_ledger.jsonl"
    entries = [item for item in ledger_path.read_text(encoding="utf-8").splitlines() if item.strip()]
    assert any("mutate_one_candidate" in item for item in entries)
    assert any("re_evaluate_one_candidate" in item for item in entries)


def test_run_next_step_refreshes_execution_cost_defaults(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)
    _seed_candidate_spec(settings, candidate_id="AF-CAND-0018", allowed_hours=[6, 7, 8, 9, 10, 11, 12])

    parent_campaign_id = "campaign-parent-refresh"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0001",
        target_candidate_ids=["AF-CAND-0018"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0001",
        active_candidate_ids=["AF-CAND-0001", "AF-CAND-0018"],
        iterations_run=1,
        trials_consumed=1,
        stop_reason="manual_alignment_refresh",
        state_path=parent_dir / "state.json",
        updated_utc="2026-03-21T09:00:00Z",
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(
        parent_dir / "next_recommendations.json",
        [
            {
                "step_type": "mutate_one_candidate",
                "candidate_id": "AF-CAND-0018",
                "rationale": "Clone AF-CAND-0018 and refresh it to the current governed scalping execution-cost defaults before further diagnosis.",
                "binding": True,
                "evidence_status": "supported",
                "step_payload": {
                    "mutation_type": "refresh_execution_cost_defaults",
                    "refresh_reason": "align stale execution-cost assumptions with the current governed scalping defaults",
                },
            }
        ],
    )

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-refresh",
        allowed_step_types=["mutate_one_candidate"],
    )

    assert report.selected_step_type == "mutate_one_candidate"
    assert report.status == "completed"
    mutation_report = report.mutation_reports[0]
    mutated_spec = read_json(Path(mutation_report.artifact_paths["spec_path"]))
    assert mutated_spec["variant_name"] == "execution_refresh"
    assert mutated_spec["cost_model"]["slippage_pips"] == 0.05
    assert mutated_spec["cost_model"]["fill_delay_ms"] == 250
    assert mutated_spec["execution_cost_model"]["slippage_pips"] == 0.05
    assert mutated_spec["execution_cost_model"]["fill_delay_ms"] == 250
    assert report.next_recommendations[0].step_type == "re_evaluate_one_candidate"


def test_run_next_step_prefers_context_mutation_when_shared_session_is_too_broad(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)

    parent_campaign_id = "campaign-parent-compare-context"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0014",
        target_candidate_ids=["AF-CAND-0019", "AF-CAND-0015"],
        max_iterations=1,
        max_new_candidates=0,
        trial_cap_per_family=2,
        notes=["Parent comparison campaign for context-first diagnosis."],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0014",
        active_candidate_ids=["AF-CAND-0014", "AF-CAND-0019", "AF-CAND-0015"],
        iterations_run=1,
        trials_consumed=2,
        stop_reason="bounded_comparison_completed",
        state_path=parent_dir / "state.json",
        updated_utc="2026-03-21T10:00:00Z",
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))

    _seed_context_comparison_reports(settings.paths().reports_dir / "AF-CAND-0019", "AF-CAND-0019")
    _seed_context_comparison_reports(settings.paths().reports_dir / "AF-CAND-0015", "AF-CAND-0015")

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-compare-context",
        allowed_step_types=["diagnose_existing_candidates"],
    )

    assert report.selected_step_type == "diagnose_existing_candidates"
    assert report.status == "completed"
    assert report.next_recommendations
    recommendation = report.next_recommendations[0]
    assert recommendation.step_type == "mutate_one_candidate"
    assert recommendation.step_payload["mutation_type"] == "suppress_context_bucket"
    assert recommendation.step_payload["context_bucket"] == "trend_context"


def test_run_next_step_mutates_candidate_with_context_suppression(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)
    _seed_candidate_spec(settings, candidate_id="AF-CAND-0019", allowed_hours=[6, 7, 8, 9, 10, 11, 12])

    parent_campaign_id = "campaign-parent-context-mutate"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0014",
        target_candidate_ids=["AF-CAND-0019"],
        notes=["Parent campaign with binding context mutation recommendation."],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0014",
        active_candidate_ids=["AF-CAND-0014", "AF-CAND-0019"],
        iterations_run=1,
        trials_consumed=1,
        stop_reason="diagnosis_completed_with_supported_recommendation",
        state_path=parent_dir / "state.json",
        updated_utc="2026-03-21T10:05:00Z",
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(
        parent_dir / "next_recommendations.json",
        [
            {
                "step_type": "mutate_one_candidate",
                "candidate_id": "AF-CAND-0019",
                "rationale": "Suppress trend_context entries inside the current breakout family, then re-evaluate without broadening scope.",
                "binding": True,
                "evidence_status": "supported",
                "step_payload": {
                    "mutation_type": "suppress_context_bucket",
                    "context_bucket": "trend_context",
                },
            }
        ],
    )

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-context-mutate",
        allowed_step_types=["mutate_one_candidate"],
    )

    assert report.selected_step_type == "mutate_one_candidate"
    assert report.status == "completed"
    mutation_report = report.mutation_reports[0]
    mutated_spec = read_json(Path(mutation_report.artifact_paths["spec_path"]))
    context_filters = [item for item in mutated_spec["filters"] if item["name"] == "exclude_context_bucket"]
    assert context_filters == [{"name": "exclude_context_bucket", "rule": "trend_context"}]
    assert report.next_recommendations[0].step_type == "re_evaluate_one_candidate"


def test_run_next_step_stops_when_run_parity_binding_lacks_approval(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)
    _seed_candidate_spec(settings, candidate_id="AF-CAND-0099", allowed_hours=[7, 8, 9, 10, 11, 12])
    _seed_candidate_review_packet(
        settings.paths().reports_dir / "AF-CAND-0099", "AF-CAND-0099", walk_forward_ok=True, stress_passed=True
    )

    parent_campaign_id = "campaign-parent-parity-blocked"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0001",
        target_candidate_ids=["AF-CAND-0099"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0001",
        active_candidate_ids=["AF-CAND-0001", "AF-CAND-0099"],
        state_path=parent_dir / "state.json",
        updated_utc="2026-03-21T12:00:00Z",
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(
        parent_dir / "next_recommendations.json",
        [
            {
                "step_type": "run_parity",
                "candidate_id": "AF-CAND-0099",
                "rationale": "Candidate cleared the research-stage gates and should enter practice parity next.",
                "binding": True,
                "evidence_status": "supported",
            }
        ],
    )

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-parity-blocked",
        allowed_step_types=["run_parity"],
    )

    assert report.status == "stopped"
    assert report.stop_reason == "binding_recommendation_missing_required_approval"
    assert report.continuation_status == "stop"
    assert report.stop_class == "approval_required"
    assert report.auto_continue_allowed is False


def test_run_next_step_keeps_binding_recommendation_when_newer_child_is_unrelated(settings, tmp_path, monkeypatch):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)
    _seed_candidate_spec(settings, candidate_id="AF-CAND-0099", allowed_hours=[7, 8, 9, 10, 11, 12])
    _seed_candidate_review_packet(
        settings.paths().reports_dir / "AF-CAND-0099", "AF-CAND-0099", walk_forward_ok=True, stress_passed=True
    )
    _seed_candidate_spec(settings, candidate_id="AF-CAND-0101", allowed_hours=[7, 8, 9, 10, 11, 12])
    _seed_candidate_review_packet(
        settings.paths().reports_dir / "AF-CAND-0101", "AF-CAND-0101", walk_forward_ok=True, stress_passed=True
    )

    parent_campaign_id = "campaign-parent-diagnose-binding"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0001",
        target_candidate_ids=["AF-CAND-0099"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0001",
        active_candidate_ids=["AF-CAND-0001", "AF-CAND-0099"],
        state_path=parent_dir / "state.json",
        updated_utc="2026-03-21T12:20:00Z",
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(
        parent_dir / "next_recommendations.json",
        [
            {
                "step_type": "diagnose_existing_candidates",
                "candidate_id": "AF-CAND-0099",
                "rationale": "Parity failure on AF-CAND-0099 requires diagnosis.",
                "binding": True,
                "evidence_status": "supported",
            }
        ],
    )

    sibling_dir = settings.paths().campaigns_dir / "campaign-sibling-unrelated"
    sibling_state = CampaignState(
        campaign_id="campaign-sibling-unrelated",
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0001",
        parent_campaign_id=parent_campaign_id,
        current_step_type="re_evaluate_one_candidate",
        active_candidate_ids=["AF-CAND-0101"],
        state_path=sibling_dir / "state.json",
        updated_utc="2026-03-21T12:25:00Z",
    )
    write_json(sibling_dir / "state.json", sibling_state.model_dump(mode="json"))

    def _fake_diagnose(
        settings, *, child_spec, state, parent_spec, candidate_ids, step_reason, report_path, recommendations_path
    ):
        report = NextStepControllerReport(
            campaign_id=child_spec.campaign_id,
            parent_campaign_id=child_spec.parent_campaign_id,
            selected_step_type="diagnose_existing_candidates",
            step_reason=step_reason,
            status="completed",
            stop_reason="diagnosis_completed_with_supported_recommendation",
            candidate_scope=list(candidate_ids),
            report_path=report_path,
        )
        write_json(report_path, report.model_dump(mode="json"))
        write_json(recommendations_path, [])
        return report

    monkeypatch.setattr("agentic_forex.campaigns.next_step._run_diagnose_existing_candidates", _fake_diagnose)

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-diagnose-binding",
        allowed_step_types=["diagnose_existing_candidates"],
    )

    assert report.selected_step_type == "diagnose_existing_candidates"
    assert report.status == "completed"
    assert report.candidate_scope == ["AF-CAND-0099"]


def test_run_next_step_executes_run_parity_and_emits_run_forward(settings, tmp_path, monkeypatch):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)
    _seed_candidate_spec(settings, candidate_id="AF-CAND-0100", allowed_hours=[7, 8, 9, 10, 11, 12])
    _seed_candidate_review_packet(
        settings.paths().reports_dir / "AF-CAND-0100", "AF-CAND-0100", walk_forward_ok=True, stress_passed=True
    )
    for stage in ("mt5_packet", "mt5_parity_run", "mt5_validation"):
        record_approval(
            ApprovalRecord(
                candidate_id="AF-CAND-0100",
                stage=stage,
                decision="approve",
                approver="pytest",
                rationale="Approved for controller parity test.",
            ),
            settings,
        )

    parent_campaign_id = "campaign-parent-parity"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0001",
        target_candidate_ids=["AF-CAND-0100"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0001",
        active_candidate_ids=["AF-CAND-0001", "AF-CAND-0100"],
        state_path=parent_dir / "state.json",
        updated_utc="2026-03-21T12:15:00Z",
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(
        parent_dir / "next_recommendations.json",
        [
            {
                "step_type": "run_parity",
                "candidate_id": "AF-CAND-0100",
                "rationale": "Practice parity is the next governed step.",
                "binding": True,
                "evidence_status": "supported",
            }
        ],
    )

    def _fake_run_mt5_parity(candidate_id, settings):
        run_dir = settings.paths().mt5_runs_dir / candidate_id / "mt5run-test"
        run_dir.mkdir(parents=True, exist_ok=True)
        report = MT5ParityReport(
            candidate_id=candidate_id,
            run_id="mt5run-test",
            packet_reused=True,
            logic_manifest_hash="abc",
            validation_status="passed",
            failure_classification=None,
            parity_rate=0.95,
            audit_rows=12,
            tester_report_path=run_dir / "tester_report.htm",
            audit_csv_path=run_dir / "audit.csv",
            launch_status_path=run_dir / "launch_status.json",
            validation_report_path=run_dir / "validation_report.json",
            report_path=run_dir / "mt5_parity_report.json",
        )
        write_json(report.report_path, report.model_dump(mode="json"))
        write_json(
            report.validation_report_path,
            MT5ValidationReport(
                candidate_id=candidate_id,
                run_id="mt5run-test",
                validation_status="passed",
                parity_rate=0.95,
                audit_rows=12,
                expected_trade_count=12,
                actual_trade_count=12,
                matched_trade_count=12,
                unmatched_expected_count=0,
                unmatched_actual_count=0,
                report_path=report.validation_report_path,
            ).model_dump(mode="json"),
        )
        return report

    monkeypatch.setattr("agentic_forex.campaigns.next_step.run_mt5_parity", _fake_run_mt5_parity)

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-parity",
        allowed_step_types=["run_parity"],
    )

    assert report.selected_step_type == "run_parity"
    assert report.status == "completed"
    assert report.next_recommendations[0].step_type == "run_forward"
    assert report.continuation_status == "continue"
    assert report.stop_class == "none"
    assert report.auto_continue_allowed is True
    assert report.recommended_follow_on_step == "run_forward"
    child_state = read_json(settings.paths().campaigns_dir / "campaign-child-parity" / "state.json")
    assert child_state["operational_runs_consumed"] == 1
    assert child_state["mt5_parity_retries_by_candidate"]["AF-CAND-0100"] == 1


def test_run_next_step_stops_when_parity_policy_blocks_official_run(settings, tmp_path, monkeypatch):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)
    _seed_candidate_spec(settings, candidate_id="AF-CAND-0100P", allowed_hours=[7, 8, 9, 10, 11, 12])
    _seed_candidate_review_packet(
        settings.paths().reports_dir / "AF-CAND-0100P", "AF-CAND-0100P", walk_forward_ok=True, stress_passed=True
    )
    for stage in ("mt5_packet", "mt5_parity_run", "mt5_validation"):
        record_approval(
            ApprovalRecord(
                candidate_id="AF-CAND-0100P",
                stage=stage,
                decision="approve",
                approver="pytest",
                rationale="Approved for controller parity policy-block test.",
            ),
            settings,
        )

    parent_campaign_id = "campaign-parent-parity-policy"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0001",
        target_candidate_ids=["AF-CAND-0100P"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0001",
        active_candidate_ids=["AF-CAND-0001", "AF-CAND-0100P"],
        state_path=parent_dir / "state.json",
        updated_utc="2026-03-24T12:20:00Z",
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(
        parent_dir / "next_recommendations.json",
        [
            {
                "step_type": "run_parity",
                "candidate_id": "AF-CAND-0100P",
                "rationale": "Practice parity is the next governed step.",
                "binding": True,
                "evidence_status": "supported",
            }
        ],
    )

    monkeypatch.setattr(
        "agentic_forex.campaigns.next_step.run_mt5_parity",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ParityPolicyError("parity_policy_blocked:lineage_root=AF-CAND-0100P:parity_class=tick_required")
        ),
    )

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-parity-policy",
        allowed_step_types=["run_parity"],
    )

    assert report.selected_step_type == "run_parity"
    assert report.status == "stopped"
    assert "parity_policy_blocked" in str(report.stop_reason)
    assert report.continuation_status == "stop"
    assert report.stop_class == "policy_decision"
    assert report.auto_continue_allowed is False


def test_run_next_step_executes_run_forward_and_emits_human_review(settings, tmp_path, monkeypatch):
    oanda_json = create_oanda_candles_json(tmp_path, rows=5000)
    ingest_oanda_json(oanda_json, settings)
    _seed_candidate_spec(settings, candidate_id="AF-CAND-0101", allowed_hours=[7, 8, 9, 10, 11, 12])
    _seed_candidate_review_packet(
        settings.paths().reports_dir / "AF-CAND-0101", "AF-CAND-0101", walk_forward_ok=True, stress_passed=True
    )
    run_dir = settings.paths().mt5_runs_dir / "AF-CAND-0101" / "mt5run-test"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "validation_report.json",
        MT5ValidationReport(
            candidate_id="AF-CAND-0101",
            run_id="mt5run-test",
            validation_status="passed",
            parity_rate=0.9,
            audit_rows=12,
            expected_trade_count=12,
            actual_trade_count=12,
            matched_trade_count=12,
            unmatched_expected_count=0,
            unmatched_actual_count=0,
            report_path=run_dir / "validation_report.json",
        ).model_dump(mode="json"),
    )

    parent_campaign_id = "campaign-parent-forward"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0001",
        target_candidate_ids=["AF-CAND-0101"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0001",
        active_candidate_ids=["AF-CAND-0001", "AF-CAND-0101"],
        state_path=parent_dir / "state.json",
        updated_utc="2026-03-21T12:30:00Z",
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(
        parent_dir / "next_recommendations.json",
        [
            {
                "step_type": "run_forward",
                "candidate_id": "AF-CAND-0101",
                "rationale": "Parity passed, so the next governed step is OANDA shadow-forward.",
                "binding": True,
                "evidence_status": "supported",
            }
        ],
    )

    def _fake_run_shadow_forward(spec, settings):
        report_path = settings.paths().reports_dir / spec.candidate_id / "forward_stage_report.json"
        report = ForwardStageReport(
            candidate_id=spec.candidate_id,
            trading_days_observed=12,
            trade_count=28,
            profit_factor=1.1,
            expectancy_pips=0.2,
            oos_expectancy_pips=0.3,
            expectancy_degradation_pct=33.0,
            risk_violations=[],
            passed=True,
            artifact_references={},
            report_path=report_path,
        )
        write_json(report_path, report.model_dump(mode="json"))
        return report

    monkeypatch.setattr("agentic_forex.campaigns.next_step.run_shadow_forward", _fake_run_shadow_forward)

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-forward",
        allowed_step_types=["run_forward"],
    )

    assert report.selected_step_type == "run_forward"
    assert report.status == "completed"
    assert report.next_recommendations[0].step_type == "human_review"
    assert report.continuation_status == "stop"
    assert report.stop_class == "approval_required"
    assert report.auto_continue_allowed is False
    assert report.recommended_follow_on_step == "human_review"


def test_run_next_step_marks_nonviable_reevaluation_as_lane_exhausted(settings, tmp_path):
    report_path = tmp_path / "report.json"
    report = NextStepControllerReport(
        campaign_id="campaign-child-lane-stop",
        parent_campaign_id="campaign-parent",
        selected_step_type="re_evaluate_one_candidate",
        step_reason="Controller reevaluated a weak branch.",
        status="completed",
        stop_reason="re_evaluation_completed_with_supported_recommendation",
        candidate_scope=["AF-CAND-WEAK"],
        reevaluation_reports=[
            CandidateReevaluationReport(
                candidate_id="AF-CAND-WEAK",
                source_candidate_id="AF-CAND-BASE",
                readiness_status="robustness_provisional",
                trade_count=24,
                out_of_sample_profit_factor=0.82,
                expectancy_pips=-0.61,
                stressed_profit_factor=0.58,
                walk_forward_ok=False,
                stress_passed=False,
            )
        ],
        next_recommendations=[
            NextStepRecommendation(
                step_type="diagnose_existing_candidates",
                candidate_id="AF-CAND-WEAK",
                rationale="Diagnose the weak branch before any further mutation.",
                binding=True,
                evidence_status="supported",
            )
        ],
        report_path=report_path,
    )

    from agentic_forex.campaigns.next_step import _apply_continuation_metadata

    _apply_continuation_metadata(settings, report)

    assert report.continuation_status == "stop"
    assert report.stop_class == "lane_exhausted"
    assert report.auto_continue_allowed is False
    assert report.recommended_follow_on_step == "diagnose_existing_candidates"


def test_run_next_step_marks_low_trade_reevaluation_as_lane_exhausted_even_with_spiky_oos_pf(settings, tmp_path):
    report_path = tmp_path / "report.json"
    report = NextStepControllerReport(
        campaign_id="campaign-child-lane-stop-low-trade",
        parent_campaign_id="campaign-parent",
        selected_step_type="re_evaluate_one_candidate",
        step_reason="Controller reevaluated a weak low-trade branch.",
        status="completed",
        stop_reason="re_evaluation_completed_with_supported_recommendation",
        candidate_scope=["AF-CAND-SPIKY"],
        reevaluation_reports=[
            CandidateReevaluationReport(
                candidate_id="AF-CAND-SPIKY",
                source_candidate_id="AF-CAND-BASE",
                readiness_status="robustness_provisional",
                trade_count=24,
                out_of_sample_profit_factor=6.31,
                expectancy_pips=-0.67,
                stressed_profit_factor=0.58,
                walk_forward_ok=False,
                stress_passed=False,
            )
        ],
        next_recommendations=[
            NextStepRecommendation(
                step_type="diagnose_existing_candidates",
                candidate_id="AF-CAND-SPIKY",
                rationale="Diagnose before any further mutation.",
            )
        ],
        report_path=report_path,
    )

    assert report.stop_class == "ambiguity"
    assert report.auto_continue_allowed is False

    from agentic_forex.campaigns.next_step import _apply_continuation_metadata

    _apply_continuation_metadata(settings, report)

    assert report.continuation_status == "stop"
    assert report.stop_class == "lane_exhausted"
    assert report.auto_continue_allowed is False
    assert report.recommended_follow_on_step == "diagnose_existing_candidates"


def test_run_next_step_marks_post_correction_low_sample_diagnosis_as_lane_exhausted(settings, tmp_path):
    report_path = tmp_path / "report.json"
    report = NextStepControllerReport(
        campaign_id="campaign-child-diagnosis-lane-stop",
        parent_campaign_id="campaign-parent",
        selected_step_type="diagnose_existing_candidates",
        step_reason="Controller diagnosed a post-correction low-sample branch.",
        status="completed",
        stop_reason="diagnosis_ambiguous_no_mutation_justified",
        candidate_scope=["AF-CAND-THIN"],
        candidate_reports=[
            CandidateDiagnosticReport(
                candidate_id="AF-CAND-THIN",
                readiness_status="robustness_provisional",
                walk_forward_failed_window=1,
                first_window_trade_count=4,
                later_window_trade_count=9,
                first_window_profit_factor=10.87,
                later_window_profit_factor=0.49,
                first_window_expectancy_pips=5.92,
                later_window_expectancy_pips=-1.70,
                supported_slices=[],
                primary_issue=None,
                recommended_mutation=None,
            )
        ],
        next_recommendations=[],
        report_path=report_path,
    )

    from agentic_forex.campaigns.next_step import _apply_continuation_metadata

    _apply_continuation_metadata(settings, report)

    assert report.continuation_status == "stop"
    assert report.stop_class == "lane_exhausted"
    assert report.auto_continue_allowed is False
    assert report.recommended_follow_on_step is None
    assert report.transition_status == "continue_lane"


def test_run_next_step_executes_hypothesis_audit_after_lane_exhaustion(settings):
    parent_campaign_id = "campaign-parent-audit"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_report_path = parent_dir / "next_step_report.json"
    parent_recommendations_path = parent_dir / "next_recommendations.json"
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0001",
        target_candidate_ids=["AF-CAND-0032"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0001",
        active_candidate_ids=["AF-CAND-0001", "AF-CAND-0032"],
        stop_reason="re_evaluation_completed_with_supported_recommendation",
        state_path=parent_dir / "state.json",
        last_report_path=parent_report_path,
        next_recommendations_path=parent_recommendations_path,
        updated_utc="2026-03-22T00:39:23Z",
    )
    parent_report = NextStepControllerReport(
        campaign_id=parent_campaign_id,
        parent_campaign_id="campaign-grandparent",
        selected_step_type="re_evaluate_one_candidate",
        step_reason="The previous reevaluation produced a weak descendant.",
        status="completed",
        stop_reason="re_evaluation_completed_with_supported_recommendation",
        candidate_scope=["AF-CAND-0032"],
        next_recommendations=[
            NextStepRecommendation(
                step_type="diagnose_existing_candidates",
                candidate_id="AF-CAND-0032",
                rationale="Diagnose before any further mutation.",
                binding=True,
                evidence_status="supported",
            )
        ],
        continuation_status="stop",
        stop_class="lane_exhausted",
        auto_continue_allowed=False,
        recommended_follow_on_step="diagnose_existing_candidates",
        report_path=parent_report_path,
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(parent_report_path, parent_report.model_dump(mode="json"))
    write_json(
        parent_recommendations_path,
        [item.model_dump(mode="json") for item in parent_report.next_recommendations],
    )

    _seed_hypothesis_audit_candidate(
        settings.paths().reports_dir / "AF-CAND-0027",
        "AF-CAND-0027",
        trade_count=370,
        profit_factor=1.19,
        out_of_sample_profit_factor=1.65,
        expectancy_pips=0.36,
        stress_passed=True,
        walk_forward_ok=False,
        pbo=0.80,
        white_reality_check_p_value=0.31,
    )
    _seed_hypothesis_audit_candidate(
        settings.paths().reports_dir / "AF-CAND-0031",
        "AF-CAND-0031",
        trade_count=139,
        profit_factor=0.65,
        out_of_sample_profit_factor=0.84,
        expectancy_pips=-0.64,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=0.92,
        white_reality_check_p_value=0.42,
    )
    _seed_hypothesis_audit_candidate(
        settings.paths().reports_dir / "AF-CAND-0032",
        "AF-CAND-0032",
        trade_count=24,
        profit_factor=0.71,
        out_of_sample_profit_factor=6.31,
        expectancy_pips=-0.67,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=0.95,
        white_reality_check_p_value=0.47,
    )

    append_failure_record(
        settings,
        candidate_id="AF-CAND-0027",
        stage="lane_stop_decision",
        failure_code="robustness_failure",
        details={"decision": "stop_lane_keep_reference_branch", "reference_branch": True},
    )
    append_failure_record(
        settings,
        candidate_id="AF-CAND-0031",
        stage="archive_decision",
        failure_code="empirical_failure",
        details={"decision": "archive_orthogonal_root_refresh_branch"},
    )
    append_failure_record(
        settings,
        candidate_id="AF-CAND-0032",
        stage="archive_decision",
        failure_code="empirical_failure",
        details={"decision": "archive_final_untouched_root_branch"},
    )

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-audit",
        allowed_step_types=["hypothesis_audit"],
    )

    assert report.selected_step_type == "hypothesis_audit"
    assert report.status == "completed"
    assert report.next_recommendations == []
    assert report.continuation_status == "stop"
    assert report.stop_class == "policy_decision"
    assert report.auto_continue_allowed is False
    assert len(report.hypothesis_audit_reports) == 1
    audit_report = report.hypothesis_audit_reports[0]
    assert set(audit_report.audited_candidate_ids) == {"AF-CAND-0027", "AF-CAND-0031", "AF-CAND-0032"}
    assert audit_report.reference_candidate_id == "AF-CAND-0027"
    assert audit_report.lane_decision == "hold_reference_blocked_by_robustness"

    ledger_path = settings.paths().experiments_dir / "trial_ledger.jsonl"
    entries = [item for item in ledger_path.read_text(encoding="utf-8").splitlines() if item.strip()]
    assert len(entries) == 3
    assert all("hypothesis_audit" in item for item in entries)


def test_run_next_step_hypothesis_audit_recommends_one_more_bounded_correction(settings):
    parent_campaign_id = "campaign-parent-audit-narrow-correction"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_report_path = parent_dir / "next_step_report.json"
    parent_recommendations_path = parent_dir / "next_recommendations.json"
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0001",
        target_candidate_ids=["AF-CAND-0032"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0001",
        active_candidate_ids=["AF-CAND-0001", "AF-CAND-0032"],
        stop_reason="diagnosis_ambiguous_no_mutation_justified",
        state_path=parent_dir / "state.json",
        last_report_path=parent_report_path,
        next_recommendations_path=parent_recommendations_path,
        updated_utc="2026-03-24T00:00:00Z",
    )
    parent_report = NextStepControllerReport(
        campaign_id=parent_campaign_id,
        parent_campaign_id="campaign-grandparent",
        selected_step_type="re_evaluate_one_candidate",
        step_reason="The latest reevaluation exhausted the active descendant and now requires a hypothesis audit.",
        status="completed",
        stop_reason="re_evaluation_completed_with_supported_recommendation",
        candidate_scope=["AF-CAND-0032"],
        candidate_reports=[],
        next_recommendations=[],
        continuation_status="stop",
        stop_class="lane_exhausted",
        auto_continue_allowed=False,
        report_path=parent_report_path,
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(parent_report_path, parent_report.model_dump(mode="json"))
    write_json(parent_recommendations_path, [])

    _seed_hypothesis_audit_candidate(
        settings.paths().reports_dir / "AF-CAND-0027",
        "AF-CAND-0027",
        trade_count=170,
        profit_factor=1.24,
        out_of_sample_profit_factor=1.31,
        expectancy_pips=0.44,
        stress_passed=True,
        walk_forward_ok=True,
        pbo=0.12,
        white_reality_check_p_value=0.04,
    )
    _seed_hypothesis_audit_candidate(
        settings.paths().reports_dir / "AF-CAND-0031",
        "AF-CAND-0031",
        trade_count=84,
        profit_factor=0.72,
        out_of_sample_profit_factor=0.88,
        expectancy_pips=-0.31,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=0.68,
        white_reality_check_p_value=0.27,
    )
    _seed_hypothesis_audit_candidate(
        settings.paths().reports_dir / "AF-CAND-0032",
        "AF-CAND-0032",
        trade_count=12,
        profit_factor=1.91,
        out_of_sample_profit_factor=0.0,
        expectancy_pips=0.73,
        stress_passed=True,
        walk_forward_ok=False,
        pbo=0.91,
        white_reality_check_p_value=0.35,
    )

    append_failure_record(
        settings,
        candidate_id="AF-CAND-0031",
        stage="archive_decision",
        failure_code="empirical_failure",
        details={"decision": "archive_orthogonal_root_refresh_branch"},
    )
    append_failure_record(
        settings,
        candidate_id="AF-CAND-0032",
        stage="archive_decision",
        failure_code="empirical_failure",
        details={"decision": "archive_final_untouched_root_branch"},
    )

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-audit-narrow-correction",
        allowed_step_types=["hypothesis_audit", "diagnose_existing_candidates"],
    )

    assert report.selected_step_type == "hypothesis_audit"
    assert report.status == "completed"
    assert report.continuation_status == "continue"
    assert report.stop_class == "none"
    assert report.auto_continue_allowed is True
    assert report.recommended_follow_on_step == "diagnose_existing_candidates"
    assert len(report.next_recommendations) == 1
    recommendation = report.next_recommendations[0]
    assert recommendation.step_type == "diagnose_existing_candidates"
    assert recommendation.candidate_id == "AF-CAND-0027"
    assert recommendation.binding is True
    assert recommendation.evidence_status == "supported"
    assert report.hypothesis_audit_reports[0].lane_decision == "narrow_correction_supported"


def test_run_next_step_hypothesis_audit_holds_reference_after_exhausted_diagnosis(settings):
    parent_campaign_id = "campaign-parent-audit-hold-after-diagnosis"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_report_path = parent_dir / "next_step_report.json"
    parent_recommendations_path = parent_dir / "next_recommendations.json"
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0001",
        target_candidate_ids=["AF-CAND-0027"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0001",
        active_candidate_ids=["AF-CAND-0001", "AF-CAND-0027"],
        stop_reason="diagnosis_completed_with_supported_recommendation",
        state_path=parent_dir / "state.json",
        last_report_path=parent_report_path,
        next_recommendations_path=parent_recommendations_path,
        updated_utc="2026-03-24T00:00:00Z",
    )
    parent_report = NextStepControllerReport(
        campaign_id=parent_campaign_id,
        parent_campaign_id="campaign-grandparent",
        selected_step_type="diagnose_existing_candidates",
        step_reason="A fresh diagnosis found structural weakness but no bounded mutation narrow enough to apply.",
        status="completed",
        stop_reason="diagnosis_completed_with_supported_recommendation",
        candidate_scope=["AF-CAND-0027"],
        candidate_reports=[],
        next_recommendations=[
            NextStepRecommendation(
                step_type="hypothesis_audit",
                candidate_id="AF-CAND-0027",
                rationale="Escalate to hypothesis audit before further search.",
                binding=True,
                evidence_status="supported",
            )
        ],
        continuation_status="continue",
        stop_class="none",
        auto_continue_allowed=True,
        recommended_follow_on_step="hypothesis_audit",
        report_path=parent_report_path,
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(parent_report_path, parent_report.model_dump(mode="json"))
    write_json(
        parent_recommendations_path,
        [item.model_dump(mode="json") for item in parent_report.next_recommendations],
    )

    _seed_hypothesis_audit_candidate(
        settings.paths().reports_dir / "AF-CAND-0027",
        "AF-CAND-0027",
        trade_count=170,
        profit_factor=1.24,
        out_of_sample_profit_factor=1.31,
        expectancy_pips=0.44,
        stress_passed=True,
        walk_forward_ok=True,
        pbo=0.12,
        white_reality_check_p_value=0.04,
    )

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-audit-hold-after-diagnosis",
        allowed_step_types=["hypothesis_audit"],
    )

    assert report.selected_step_type == "hypothesis_audit"
    assert report.next_recommendations == []
    assert report.continuation_status == "stop"
    assert report.stop_class == "policy_decision"
    assert report.auto_continue_allowed is False
    assert report.hypothesis_audit_reports[0].lane_decision == "hold_reference_blocked_by_robustness"


def test_run_next_step_escalates_ambiguous_post_correction_diagnosis_to_hypothesis_audit(settings):
    parent_campaign_id = "campaign-parent-post-correction-diagnosis"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_report_path = parent_dir / "next_step_report.json"
    parent_recommendations_path = parent_dir / "next_recommendations.json"
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="impulse_transition_research",
        baseline_candidate_id="AF-CAND-0172",
        target_candidate_ids=["AF-CAND-0173"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="impulse_transition_research",
        status="completed",
        baseline_candidate_id="AF-CAND-0172",
        active_candidate_ids=["AF-CAND-0172", "AF-CAND-0173"],
        stop_reason="diagnosis_ambiguous_no_mutation_justified",
        state_path=parent_dir / "state.json",
        last_report_path=parent_report_path,
        next_recommendations_path=parent_recommendations_path,
        updated_utc="2026-03-22T23:14:19Z",
    )
    parent_report = NextStepControllerReport(
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
        next_recommendations=[],
        continuation_status="stop",
        stop_class="ambiguity",
        auto_continue_allowed=False,
        report_path=parent_report_path,
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(parent_report_path, parent_report.model_dump(mode="json"))
    write_json(parent_recommendations_path, [])

    _seed_hypothesis_audit_candidate(
        settings.paths().reports_dir / "AF-CAND-0172",
        "AF-CAND-0172",
        trade_count=177,
        profit_factor=0.67,
        out_of_sample_profit_factor=1.29,
        expectancy_pips=-0.95,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=None,
        white_reality_check_p_value=None,
        family="impulse_transition_research",
        entry_style="session_extreme_reversion",
    )
    _seed_hypothesis_audit_candidate(
        settings.paths().reports_dir / "AF-CAND-0173",
        "AF-CAND-0173",
        trade_count=123,
        profit_factor=0.50,
        out_of_sample_profit_factor=1.19,
        expectancy_pips=-1.55,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=0.2,
        white_reality_check_p_value=1.0,
        family="impulse_transition_research",
        entry_style="session_extreme_reversion",
    )

    report = run_next_step(
        settings,
        family="impulse_transition_research",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-post-correction-audit",
        allowed_step_types=["hypothesis_audit"],
    )

    assert report.selected_step_type == "hypothesis_audit"
    assert report.status == "completed"
    assert report.next_recommendations == []
    assert report.continuation_status == "stop"
    assert report.stop_class == "policy_decision"
    assert report.auto_continue_allowed is False
    audit_report = report.hypothesis_audit_reports[0]
    assert set(audit_report.audited_candidate_ids) == {"AF-CAND-0172", "AF-CAND-0173"}
    assert audit_report.reference_candidate_id in {"AF-CAND-0172", "AF-CAND-0173"}


def test_run_next_step_reruns_data_feature_audit_after_family_correction_fails_to_diagnose(settings):
    grandparent_campaign_id = "campaign-grandparent-bounded-feature-audit"
    grandparent_dir = settings.paths().campaigns_dir / grandparent_campaign_id
    grandparent_report_path = grandparent_dir / "next_step_report.json"
    grandparent_recommendations_path = grandparent_dir / "next_recommendations.json"
    grandparent_spec = CampaignSpec(
        campaign_id=grandparent_campaign_id,
        family="impulse_transition_research",
        baseline_candidate_id="AF-CAND-0172",
        target_candidate_ids=["AF-CAND-0173", "AF-CAND-0172", "AF-CAND-0171", "AF-CAND-0170"],
    )
    grandparent_state = CampaignState(
        campaign_id=grandparent_campaign_id,
        family="impulse_transition_research",
        status="completed",
        baseline_candidate_id="AF-CAND-0172",
        active_candidate_ids=["AF-CAND-0172", "AF-CAND-0173", "AF-CAND-0171", "AF-CAND-0170"],
        stop_reason="data_feature_audit_completed_bounded_correction_supported",
        state_path=grandparent_dir / "state.json",
        last_report_path=grandparent_report_path,
        next_recommendations_path=grandparent_recommendations_path,
        updated_utc="2026-03-22T23:33:37Z",
    )
    grandparent_report = NextStepControllerReport(
        campaign_id=grandparent_campaign_id,
        parent_campaign_id="campaign-older-parent",
        selected_step_type="data_feature_audit",
        step_reason="Bounded family correction was still supported.",
        status="completed",
        stop_reason="data_feature_audit_completed_bounded_correction_supported",
        candidate_scope=["AF-CAND-0173", "AF-CAND-0172", "AF-CAND-0171", "AF-CAND-0170"],
        data_feature_audit_reports=[
            {
                "family": "impulse_transition_research",
                "audited_candidate_ids": ["AF-CAND-0173", "AF-CAND-0172", "AF-CAND-0171", "AF-CAND-0170"],
                "reference_candidate_id": "AF-CAND-0173",
                "family_decision": "bounded_correction_supported",
                "summary": "One bounded family correction might still be justified.",
                "suspected_root_causes": [
                    "provenance_contract_mixed",
                    "execution_cost_realism_consumes_edge",
                    "persistent_walk_forward_instability",
                ],
                "provenance_consistency": {},
                "recent_regime_signals": [],
                "recommended_actions": [],
                "candidate_summaries": [],
                "artifact_paths": {},
            }
        ],
        next_recommendations=[
            NextStepRecommendation(
                step_type="diagnose_existing_candidates",
                candidate_id="AF-CAND-0173",
                rationale="Run one bounded diagnosis pass on the reference branch.",
                binding=True,
                evidence_status="supported",
            )
        ],
        continuation_status="continue",
        stop_class="none",
        auto_continue_allowed=True,
        recommended_follow_on_step="diagnose_existing_candidates",
        report_path=grandparent_report_path,
    )
    write_json(grandparent_dir / "spec.json", grandparent_spec.model_dump(mode="json"))
    write_json(grandparent_state.state_path, grandparent_state.model_dump(mode="json"))
    write_json(grandparent_report_path, grandparent_report.model_dump(mode="json"))
    write_json(
        grandparent_recommendations_path,
        [item.model_dump(mode="json") for item in grandparent_report.next_recommendations],
    )

    parent_campaign_id = "campaign-parent-failed-family-correction-diagnosis"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_report_path = parent_dir / "next_step_report.json"
    parent_recommendations_path = parent_dir / "next_recommendations.json"
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="impulse_transition_research",
        baseline_candidate_id="AF-CAND-0173",
        target_candidate_ids=["AF-CAND-0173"],
        parent_campaign_id=grandparent_campaign_id,
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="impulse_transition_research",
        status="completed",
        baseline_candidate_id="AF-CAND-0173",
        active_candidate_ids=["AF-CAND-0173"],
        stop_reason="diagnosis_ambiguous_no_mutation_justified",
        state_path=parent_dir / "state.json",
        last_report_path=parent_report_path,
        next_recommendations_path=parent_recommendations_path,
        updated_utc="2026-03-22T23:33:39Z",
    )
    parent_report = NextStepControllerReport(
        campaign_id=parent_campaign_id,
        parent_campaign_id=grandparent_campaign_id,
        selected_step_type="diagnose_existing_candidates",
        step_reason="No bounded correction was diagnosable on the reference branch.",
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
        next_recommendations=[],
        continuation_status="stop",
        stop_class="ambiguity",
        auto_continue_allowed=False,
        report_path=parent_report_path,
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(parent_report_path, parent_report.model_dump(mode="json"))
    write_json(parent_recommendations_path, [])

    for candidate_id, trade_count, profit_factor, oos_pf, expectancy, cost_version in (
        ("AF-CAND-0170", 320, 0.71, 0.98, -0.75, "cost-itr-0"),
        ("AF-CAND-0171", 78, 0.88, 0.90, -0.39, "cost-itr-1"),
        ("AF-CAND-0172", 177, 0.67, 1.29, -0.95, "cost-itr-2"),
        ("AF-CAND-0173", 123, 0.50, 1.19, -1.55, "cost-itr-2"),
    ):
        _seed_data_feature_candidate(
            settings.paths().reports_dir / candidate_id,
            candidate_id,
            family="impulse_transition_research",
            trade_count=trade_count,
            profit_factor=profit_factor,
            out_of_sample_profit_factor=oos_pf,
            expectancy_pips=expectancy,
            stress_passed=False,
            walk_forward_ok=False,
            pbo=0.2 if candidate_id == "AF-CAND-0173" else None,
            white_reality_check_p_value=1.0 if candidate_id == "AF-CAND-0173" else None,
            entry_style="session_extreme_reversion"
            if candidate_id in {"AF-CAND-0172", "AF-CAND-0173"}
            else "trend_pullback_retest",
            dataset_snapshot_id="snap-itr-family",
            feature_version_id="feat-itr-family",
            label_version_id="label-itr-family",
            execution_cost_model_version=cost_version,
        )

    report = run_next_step(
        settings,
        family="impulse_transition_research",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-repeat-family-audit",
        allowed_step_types=["data_feature_audit"],
    )

    assert report.selected_step_type == "data_feature_audit"
    assert report.status == "completed"
    assert report.stop_class == "policy_decision"
    audit_report = report.data_feature_audit_reports[0]
    assert audit_report.family_decision == "retire_family"
    assert audit_report.reference_candidate_id == "AF-CAND-0173"


def test_apply_continuation_metadata_auto_continues_failed_family_correction_diagnosis(settings):
    parent_campaign_id = "campaign-parent-family-correction-follow-on"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_report_path = parent_dir / "next_step_report.json"
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="stationary_reclaim_research",
        baseline_candidate_id="AF-CAND-0200",
        target_candidate_ids=["AF-CAND-0200", "AF-CAND-0199", "AF-CAND-0198", "AF-CAND-0197"],
        parent_campaign_id="campaign-grandparent-feature",
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="stationary_reclaim_research",
        status="completed",
        baseline_candidate_id="AF-CAND-0200",
        active_candidate_ids=["AF-CAND-0200", "AF-CAND-0199", "AF-CAND-0198", "AF-CAND-0197"],
        stop_reason="data_feature_audit_completed_bounded_correction_supported",
        state_path=parent_dir / "state.json",
        last_report_path=parent_report_path,
        next_recommendations_path=parent_dir / "next_recommendations.json",
        updated_utc="2026-03-23T22:23:01Z",
    )
    parent_report = NextStepControllerReport(
        campaign_id=parent_campaign_id,
        parent_campaign_id="campaign-grandparent-feature",
        selected_step_type="data_feature_audit",
        step_reason="Family audit supported one bounded correction.",
        status="completed",
        stop_reason="data_feature_audit_completed_bounded_correction_supported",
        candidate_scope=["AF-CAND-0200", "AF-CAND-0199", "AF-CAND-0198", "AF-CAND-0197"],
        data_feature_audit_reports=[
            {
                "family": "stationary_reclaim_research",
                "audited_candidate_ids": ["AF-CAND-0200", "AF-CAND-0199", "AF-CAND-0198", "AF-CAND-0197"],
                "reference_candidate_id": "AF-CAND-0200",
                "family_decision": "bounded_correction_supported",
                "summary": "One bounded family correction is still supported.",
            }
        ],
        next_recommendations=[
            NextStepRecommendation(
                step_type="diagnose_existing_candidates",
                candidate_id="AF-CAND-0200",
                rationale="Run one bounded diagnosis pass on the reference branch.",
                binding=True,
                evidence_status="supported",
            )
        ],
        continuation_status="continue",
        stop_class="none",
        auto_continue_allowed=True,
        recommended_follow_on_step="diagnose_existing_candidates",
        report_path=parent_report_path,
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(parent_report_path, parent_report.model_dump(mode="json"))
    write_json(
        parent_dir / "next_recommendations.json",
        [item.model_dump(mode="json") for item in parent_report.next_recommendations],
    )

    diagnosis_report = NextStepControllerReport(
        campaign_id="campaign-child-diagnosis",
        parent_campaign_id=parent_campaign_id,
        selected_step_type="diagnose_existing_candidates",
        step_reason="No bounded correction was diagnosable on the reference branch.",
        status="completed",
        stop_reason="diagnosis_ambiguous_no_mutation_justified",
        candidate_scope=["AF-CAND-0200"],
        candidate_reports=[
            CandidateDiagnosticReport(
                candidate_id="AF-CAND-0200",
                readiness_status="robustness_provisional",
                walk_forward_failed_window=1,
                first_window_trade_count=47,
                later_window_trade_count=96,
                first_window_profit_factor=0.84,
                later_window_profit_factor=0.65,
                first_window_expectancy_pips=-0.45,
                later_window_expectancy_pips=-1.03,
                supported_slices=[],
                primary_issue=None,
                recommended_mutation=None,
            )
        ],
        next_recommendations=[],
        report_path=settings.paths().campaigns_dir / "campaign-child-diagnosis" / "next_step_report.json",
    )

    _apply_continuation_metadata(settings, diagnosis_report)

    assert diagnosis_report.continuation_status == "continue"
    assert diagnosis_report.stop_class == "none"
    assert diagnosis_report.auto_continue_allowed is True
    assert diagnosis_report.recommended_follow_on_step == "data_feature_audit"
    assert diagnosis_report.transition_status == "continue_lane"


def test_run_next_step_hypothesis_audit_keeps_reference_within_entry_style_lane(settings):
    parent_campaign_id = "campaign-parent-audit-lane-scope"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_report_path = parent_dir / "next_step_report.json"
    parent_recommendations_path = parent_dir / "next_recommendations.json"
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0015-FADE",
        target_candidate_ids=["AF-CAND-0035"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0015-FADE",
        active_candidate_ids=["AF-CAND-0015-FADE", "AF-CAND-0035"],
        stop_reason="re_evaluation_completed_with_supported_recommendation",
        state_path=parent_dir / "state.json",
        last_report_path=parent_report_path,
        next_recommendations_path=parent_recommendations_path,
        updated_utc="2026-03-22T02:15:00Z",
    )
    parent_report = NextStepControllerReport(
        campaign_id=parent_campaign_id,
        parent_campaign_id="campaign-grandparent",
        selected_step_type="re_evaluate_one_candidate",
        step_reason="The previous reevaluation produced a weak fade descendant.",
        status="completed",
        stop_reason="re_evaluation_completed_with_supported_recommendation",
        candidate_scope=["AF-CAND-0035"],
        next_recommendations=[
            NextStepRecommendation(
                step_type="diagnose_existing_candidates",
                candidate_id="AF-CAND-0035",
                rationale="Diagnose before any further mutation.",
                binding=True,
                evidence_status="supported",
            )
        ],
        continuation_status="stop",
        stop_class="lane_exhausted",
        auto_continue_allowed=False,
        recommended_follow_on_step="diagnose_existing_candidates",
        report_path=parent_report_path,
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(parent_report_path, parent_report.model_dump(mode="json"))
    write_json(
        parent_recommendations_path,
        [item.model_dump(mode="json") for item in parent_report.next_recommendations],
    )

    _seed_hypothesis_audit_candidate(
        settings.paths().reports_dir / "AF-CAND-0027",
        "AF-CAND-0027",
        trade_count=370,
        profit_factor=1.19,
        out_of_sample_profit_factor=1.65,
        expectancy_pips=0.36,
        stress_passed=True,
        walk_forward_ok=False,
        pbo=0.80,
        white_reality_check_p_value=0.31,
        entry_style="session_breakout",
    )
    _seed_hypothesis_audit_candidate(
        settings.paths().reports_dir / "AF-CAND-0034",
        "AF-CAND-0034",
        trade_count=118,
        profit_factor=0.94,
        out_of_sample_profit_factor=0.96,
        expectancy_pips=-0.08,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=0.42,
        white_reality_check_p_value=0.28,
        entry_style="failed_break_fade",
    )
    _seed_hypothesis_audit_candidate(
        settings.paths().reports_dir / "AF-CAND-0035",
        "AF-CAND-0035",
        trade_count=19,
        profit_factor=0.30,
        out_of_sample_profit_factor=0.0,
        expectancy_pips=-1.18,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=0.77,
        white_reality_check_p_value=0.45,
        entry_style="failed_break_fade",
    )

    append_failure_record(
        settings,
        candidate_id="AF-CAND-0027",
        stage="lane_stop_decision",
        failure_code="robustness_failure",
        details={"decision": "stop_lane_keep_reference_branch", "reference_branch": True},
    )

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-audit-lane-scope",
        allowed_step_types=["hypothesis_audit"],
    )

    assert report.selected_step_type == "hypothesis_audit"
    audit_report = report.hypothesis_audit_reports[0]
    assert audit_report.reference_candidate_id == "AF-CAND-0034"
    assert "AF-CAND-0027" not in set(audit_report.audited_candidate_ids)
    assert set(audit_report.audited_candidate_ids) == {"AF-CAND-0034", "AF-CAND-0035"}


def test_run_next_step_executes_data_regime_audit_after_hypothesis_audit_hold(settings):
    parent_campaign_id = "campaign-parent-regime-audit"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_report_path = parent_dir / "next_step_report.json"
    parent_recommendations_path = parent_dir / "next_recommendations.json"
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0001",
        target_candidate_ids=["AF-CAND-REF", "AF-CAND-ARCH1", "AF-CAND-ARCH2"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0001",
        active_candidate_ids=["AF-CAND-0001", "AF-CAND-REF", "AF-CAND-ARCH1", "AF-CAND-ARCH2"],
        stop_reason="hypothesis_audit_completed_hold_reference_blocked_by_robustness",
        state_path=parent_dir / "state.json",
        last_report_path=parent_report_path,
        next_recommendations_path=parent_recommendations_path,
        updated_utc="2026-03-22T01:18:58Z",
    )
    parent_report = NextStepControllerReport(
        campaign_id=parent_campaign_id,
        parent_campaign_id="campaign-grandparent",
        selected_step_type="hypothesis_audit",
        step_reason="Audit held the reference branch but blocked the lane.",
        status="completed",
        stop_reason="hypothesis_audit_completed_hold_reference_blocked_by_robustness",
        candidate_scope=["AF-CAND-REF", "AF-CAND-ARCH1", "AF-CAND-ARCH2"],
        hypothesis_audit_reports=[
            HypothesisAuditReport(
                family="scalping",
                audited_candidate_ids=["AF-CAND-REF", "AF-CAND-ARCH1", "AF-CAND-ARCH2"],
                reference_candidate_id="AF-CAND-REF",
                lane_decision="hold_reference_blocked_by_robustness",
                summary="Hold the reference branch and audit regimes next.",
            )
        ],
        continuation_status="stop",
        stop_class="policy_decision",
        auto_continue_allowed=False,
        report_path=parent_report_path,
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(parent_report_path, parent_report.model_dump(mode="json"))
    write_json(parent_recommendations_path, [])

    _seed_data_regime_candidate(
        settings.paths().reports_dir / "AF-CAND-REF",
        "AF-CAND-REF",
        first_window_pattern=[("europe", "mean_reversion_context", -0.8)] * 6
        + [("overlap", "trend_context", -0.8)] * 6,
        later_window_pattern=[("europe", "mean_reversion_context", 0.6)] * 12
        + [("overlap", "trend_context", 0.6)] * 12,
        trade_count=36,
        profit_factor=1.15,
        out_of_sample_profit_factor=1.30,
        expectancy_pips=0.22,
        stress_passed=True,
        walk_forward_ok=False,
        pbo=0.8,
        white_reality_check_p_value=0.31,
        entry_style="session_breakout",
    )
    _seed_data_regime_candidate(
        settings.paths().reports_dir / "AF-CAND-ARCH1",
        "AF-CAND-ARCH1",
        first_window_pattern=[("europe", "mean_reversion_context", -0.7)] * 6,
        later_window_pattern=[("europe", "mean_reversion_context", -0.2)] * 12,
        trade_count=18,
        profit_factor=0.75,
        out_of_sample_profit_factor=0.80,
        expectancy_pips=-0.42,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=None,
        white_reality_check_p_value=None,
        entry_style="mean_reversion_pullback",
    )
    _seed_data_regime_candidate(
        settings.paths().reports_dir / "AF-CAND-ARCH2",
        "AF-CAND-ARCH2",
        first_window_pattern=[("europe", "trend_context", -1.2)] * 4,
        later_window_pattern=[("europe", "trend_context", 0.3)] * 8,
        trade_count=12,
        profit_factor=0.70,
        out_of_sample_profit_factor=1.10,
        expectancy_pips=-0.35,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=None,
        white_reality_check_p_value=None,
        entry_style="pullback_continuation",
    )

    append_failure_record(
        settings,
        candidate_id="AF-CAND-ARCH1",
        stage="archive_decision",
        failure_code="empirical_failure",
        details={"decision": "archive_branch"},
    )
    append_failure_record(
        settings,
        candidate_id="AF-CAND-ARCH2",
        stage="archive_decision",
        failure_code="empirical_failure",
        details={"decision": "archive_branch"},
    )

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-regime-audit",
        allowed_step_types=["data_regime_audit"],
    )

    assert report.selected_step_type == "data_regime_audit"
    assert report.status == "completed"
    assert report.next_recommendations == []
    assert report.continuation_status == "stop"
    assert report.stop_class == "policy_decision"
    assert report.auto_continue_allowed is False
    assert len(report.data_regime_audit_reports) == 1
    audit_report = report.data_regime_audit_reports[0]
    assert audit_report.reference_candidate_id == "AF-CAND-REF"
    assert audit_report.focus_candidate_id == "AF-CAND-REF"
    assert audit_report.lane_decision == "retire_lane"
    assert "Do not run MT5 parity or forward" in audit_report.recommended_actions[1]


def test_run_next_step_executes_data_feature_audit_after_family_queue_exhaustion(settings):
    parent_campaign_id = "campaign-parent-feature-audit"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_report_path = parent_dir / "next_step_report.json"
    parent_recommendations_path = parent_dir / "next_recommendations.json"
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0014-PULL",
        target_candidate_ids=["AF-CAND-0042"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0014-PULL",
        active_candidate_ids=["AF-CAND-0014-PULL", "AF-CAND-0042"],
        stop_reason="data_regime_audit_completed_retire_lane",
        state_path=parent_dir / "state.json",
        last_report_path=parent_report_path,
        next_recommendations_path=parent_recommendations_path,
        updated_utc="2026-03-22T02:20:00Z",
    )
    parent_report = NextStepControllerReport(
        campaign_id=parent_campaign_id,
        parent_campaign_id="campaign-grandparent",
        selected_step_type="data_regime_audit",
        step_reason="Retire the final approved lane.",
        status="completed",
        stop_reason="data_regime_audit_completed_retire_lane",
        candidate_scope=["AF-CAND-0042", "AF-CAND-0037", "AF-CAND-0032"],
        data_regime_audit_reports=[
            {
                "family": "scalping",
                "audited_candidate_ids": ["AF-CAND-0042", "AF-CAND-0037", "AF-CAND-0032"],
                "reference_candidate_id": "AF-CAND-0042",
                "focus_candidate_id": "AF-CAND-0042",
                "failed_window_index": 1,
                "lane_decision": "retire_lane",
                "summary": "Final lane retired after broad instability.",
                "recommended_actions": [],
                "slice_summaries": [],
                "candidate_summaries": [],
                "artifact_paths": {},
            }
        ],
        continuation_status="stop",
        stop_class="policy_decision",
        auto_continue_allowed=False,
        transition_status="move_to_next_lane",
        report_path=parent_report_path,
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(parent_report_path, parent_report.model_dump(mode="json"))
    write_json(parent_recommendations_path, [])

    _seed_data_feature_candidate(
        settings.paths().reports_dir / "AF-CAND-0027",
        "AF-CAND-0027",
        trade_count=370,
        profit_factor=1.19,
        out_of_sample_profit_factor=1.65,
        expectancy_pips=0.36,
        stress_passed=True,
        walk_forward_ok=False,
        pbo=0.80,
        white_reality_check_p_value=0.31,
        entry_style="session_breakout",
        dataset_snapshot_id="snap-1",
        feature_version_id="feat-1",
        label_version_id="label-1",
        execution_cost_model_version="cost-1",
    )
    _seed_data_feature_candidate(
        settings.paths().reports_dir / "AF-CAND-0040",
        "AF-CAND-0040",
        trade_count=19,
        profit_factor=0.30,
        out_of_sample_profit_factor=0.0,
        expectancy_pips=-1.18,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=0.77,
        white_reality_check_p_value=0.45,
        entry_style="failed_break_fade",
        dataset_snapshot_id="snap-1",
        feature_version_id="feat-1",
        label_version_id="label-1",
        execution_cost_model_version="cost-1",
    )
    _seed_data_feature_candidate(
        settings.paths().reports_dir / "AF-CAND-0041",
        "AF-CAND-0041",
        trade_count=24,
        profit_factor=0.71,
        out_of_sample_profit_factor=6.31,
        expectancy_pips=-0.67,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=0.0,
        white_reality_check_p_value=1.0,
        entry_style="pullback_continuation",
        dataset_snapshot_id="snap-1",
        feature_version_id="feat-1",
        label_version_id="label-1",
        execution_cost_model_version="cost-1",
    )
    _seed_data_feature_candidate(
        settings.paths().reports_dir / "AF-CAND-0042",
        "AF-CAND-0042",
        trade_count=24,
        profit_factor=0.71,
        out_of_sample_profit_factor=6.31,
        expectancy_pips=-0.67,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=0.0,
        white_reality_check_p_value=1.0,
        entry_style="pullback_continuation",
        dataset_snapshot_id="snap-1",
        feature_version_id="feat-1",
        label_version_id="label-1",
        execution_cost_model_version="cost-1",
    )

    append_failure_record(
        settings,
        candidate_id="AF-CAND-0042",
        stage="data_regime_audit",
        failure_code="robustness_failure",
        details={
            "decision": "retire_lane",
            "reference_candidate_id": "AF-CAND-0042",
        },
        artifact_paths={
            "next_step_report_path": str(parent_report_path),
        },
    )

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-feature-audit",
        allowed_step_types=["data_feature_audit"],
    )

    assert report.selected_step_type == "data_feature_audit"
    assert report.status == "completed"
    assert report.next_recommendations == []
    assert report.continuation_status == "stop"
    assert report.stop_class == "policy_decision"
    assert report.transition_status == "hard_stop"
    assert len(report.data_feature_audit_reports) == 1
    audit_report = report.data_feature_audit_reports[0]
    assert audit_report.family_decision == "retire_family"
    assert audit_report.reference_candidate_id == "AF-CAND-0027"
    assert "provenance_contract_consistent" in audit_report.suspected_root_causes
    assert "execution_cost_realism_consumes_edge" in audit_report.suspected_root_causes
    assert "persistent_walk_forward_instability" in audit_report.suspected_root_causes
    assert "Retire the current family" in audit_report.recommended_actions[0]


def test_run_next_step_executes_data_feature_audit_after_structural_regime_instability(settings):
    parent_campaign_id = "campaign-parent-structural-regime"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_report_path = parent_dir / "next_step_report.json"
    parent_recommendations_path = parent_dir / "next_recommendations.json"
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="impulse_transition_research",
        baseline_candidate_id="AF-CAND-0172",
        target_candidate_ids=["AF-CAND-0173"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="impulse_transition_research",
        status="completed",
        baseline_candidate_id="AF-CAND-0172",
        active_candidate_ids=["AF-CAND-0172", "AF-CAND-0173"],
        stop_reason="data_regime_audit_completed_structural_regime_instability",
        state_path=parent_dir / "state.json",
        last_report_path=parent_report_path,
        next_recommendations_path=parent_recommendations_path,
        updated_utc="2026-03-22T23:27:47Z",
    )
    parent_report = NextStepControllerReport(
        campaign_id=parent_campaign_id,
        parent_campaign_id="campaign-grandparent",
        selected_step_type="data_regime_audit",
        step_reason="Regime audit found structural instability.",
        status="completed",
        stop_reason="data_regime_audit_completed_structural_regime_instability",
        candidate_scope=["AF-CAND-0173", "AF-CAND-0172"],
        data_regime_audit_reports=[
            {
                "family": "impulse_transition_research",
                "audited_candidate_ids": ["AF-CAND-0173", "AF-CAND-0172"],
                "reference_candidate_id": "AF-CAND-0173",
                "focus_candidate_id": "AF-CAND-0173",
                "failed_window_index": 1,
                "lane_decision": "structural_regime_instability",
                "summary": "The reference branch is structurally unstable.",
                "recommended_actions": [],
                "slice_summaries": [],
                "candidate_summaries": [],
                "artifact_paths": {},
            }
        ],
        continuation_status="stop",
        stop_class="policy_decision",
        auto_continue_allowed=False,
        transition_status="move_to_next_lane",
        report_path=parent_report_path,
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(parent_report_path, parent_report.model_dump(mode="json"))
    write_json(parent_recommendations_path, [])

    _seed_data_feature_candidate(
        settings.paths().reports_dir / "AF-CAND-0172",
        "AF-CAND-0172",
        trade_count=177,
        profit_factor=0.67,
        out_of_sample_profit_factor=1.29,
        expectancy_pips=-0.95,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=None,
        white_reality_check_p_value=None,
        family="impulse_transition_research",
        entry_style="session_extreme_reversion",
        dataset_snapshot_id="snap-itr-1",
        feature_version_id="feat-itr-1",
        label_version_id="label-itr-1",
        execution_cost_model_version="cost-itr-1",
    )
    _seed_data_feature_candidate(
        settings.paths().reports_dir / "AF-CAND-0173",
        "AF-CAND-0173",
        trade_count=123,
        profit_factor=0.50,
        out_of_sample_profit_factor=1.19,
        expectancy_pips=-1.55,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=0.2,
        white_reality_check_p_value=1.0,
        family="impulse_transition_research",
        entry_style="session_extreme_reversion",
        dataset_snapshot_id="snap-itr-1",
        feature_version_id="feat-itr-1",
        label_version_id="label-itr-1",
        execution_cost_model_version="cost-itr-1",
    )

    report = run_next_step(
        settings,
        family="impulse_transition_research",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-structural-feature-audit",
        allowed_step_types=["data_feature_audit"],
    )

    assert report.selected_step_type == "data_feature_audit"
    assert report.status == "completed"
    assert report.stop_class == "policy_decision"
    assert report.transition_status == "hard_stop"
    assert report.data_feature_audit_reports[0].family == "impulse_transition_research"


def test_run_next_step_data_feature_audit_scopes_to_latest_contract_cohort(settings):
    parent_campaign_id = "campaign-parent-feature-contract-cohort"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_report_path = parent_dir / "next_step_report.json"
    parent_recommendations_path = parent_dir / "next_recommendations.json"
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0056",
        target_candidate_ids=["AF-CAND-0058"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0056",
        active_candidate_ids=["AF-CAND-0056", "AF-CAND-0058"],
        stop_reason="data_regime_audit_completed_retire_lane",
        state_path=parent_dir / "state.json",
        last_report_path=parent_report_path,
        next_recommendations_path=parent_recommendations_path,
        updated_utc="2026-03-22T15:01:52Z",
    )
    parent_report = NextStepControllerReport(
        campaign_id=parent_campaign_id,
        parent_campaign_id="campaign-grandparent",
        selected_step_type="data_regime_audit",
        step_reason="The latest new-contract lane retired after regime review.",
        status="completed",
        stop_reason="data_regime_audit_completed_retire_lane",
        candidate_scope=["AF-CAND-0058", "AF-CAND-0031"],
        data_regime_audit_reports=[
            {
                "family": "scalping",
                "audited_candidate_ids": ["AF-CAND-0058", "AF-CAND-0031"],
                "reference_candidate_id": "AF-CAND-0058",
                "focus_candidate_id": "AF-CAND-0058",
                "failed_window_index": 1,
                "lane_decision": "retire_lane",
                "summary": "Latest lane retired after regime review.",
                "recommended_actions": [],
                "slice_summaries": [],
                "candidate_summaries": [],
                "artifact_paths": {},
            }
        ],
        continuation_status="stop",
        stop_class="policy_decision",
        auto_continue_allowed=False,
        transition_status="move_to_next_lane",
        report_path=parent_report_path,
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(parent_report_path, parent_report.model_dump(mode="json"))
    write_json(parent_recommendations_path, [])

    _seed_data_feature_candidate(
        settings.paths().reports_dir / "AF-CAND-0056",
        "AF-CAND-0056",
        trade_count=129,
        profit_factor=0.83,
        out_of_sample_profit_factor=0.73,
        expectancy_pips=-0.45,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=0.10,
        white_reality_check_p_value=0.20,
        entry_style="volatility_breakout",
        dataset_snapshot_id="snap-new",
        feature_version_id="feat-new",
        label_version_id="label-new",
        execution_cost_model_version="cost-new",
    )
    _seed_data_feature_candidate(
        settings.paths().reports_dir / "AF-CAND-0058",
        "AF-CAND-0058",
        trade_count=139,
        profit_factor=0.65,
        out_of_sample_profit_factor=0.84,
        expectancy_pips=-0.64,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=0.20,
        white_reality_check_p_value=0.30,
        entry_style="mean_reversion_pullback",
        dataset_snapshot_id="snap-new",
        feature_version_id="feat-new",
        label_version_id="label-new",
        execution_cost_model_version="cost-new",
    )
    _seed_data_feature_candidate(
        settings.paths().reports_dir / "AF-CAND-0031",
        "AF-CAND-0031",
        trade_count=139,
        profit_factor=0.65,
        out_of_sample_profit_factor=0.84,
        expectancy_pips=-0.64,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=0.60,
        white_reality_check_p_value=0.40,
        entry_style="mean_reversion_pullback",
        dataset_snapshot_id="snap-old",
        feature_version_id="feat-old",
        label_version_id="label-old",
        execution_cost_model_version="cost-old",
    )
    _seed_data_feature_candidate(
        settings.paths().reports_dir / "AF-CAND-0054",
        "AF-CAND-0054",
        trade_count=24,
        profit_factor=0.71,
        out_of_sample_profit_factor=6.31,
        expectancy_pips=-0.67,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=0.00,
        white_reality_check_p_value=1.00,
        entry_style="pullback_continuation",
        dataset_snapshot_id="snap-old",
        feature_version_id="feat-old",
        label_version_id="label-old",
        execution_cost_model_version="cost-old",
    )

    append_failure_record(
        settings,
        candidate_id="AF-CAND-0054",
        stage="data_regime_audit",
        failure_code="robustness_failure",
        details={
            "decision": "retire_lane",
            "reference_candidate_id": "AF-CAND-0054",
        },
        artifact_paths={
            "next_step_report_path": str(parent_report_path),
        },
    )

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-feature-contract-cohort",
        allowed_step_types=["data_feature_audit"],
    )

    audit_report = report.data_feature_audit_reports[0]
    assert set(audit_report.audited_candidate_ids) == {"AF-CAND-0056", "AF-CAND-0058"}
    assert audit_report.reference_candidate_id == "AF-CAND-0056"
    assert "provenance_contract_consistent" in audit_report.suspected_root_causes
    assert "provenance_contract_mixed" not in audit_report.suspected_root_causes
    assert audit_report.provenance_consistency["feature_version_ids"] == ["feat-new"]
    assert audit_report.provenance_consistency["label_version_ids"] == ["label-new"]


def test_run_next_step_data_feature_audit_keeps_best_reference_across_execution_cost_variants(settings):
    parent_campaign_id = "campaign-parent-feature-mixed-cost"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_report_path = parent_dir / "next_step_report.json"
    parent_recommendations_path = parent_dir / "next_recommendations.json"
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0163",
        target_candidate_ids=["AF-CAND-0165"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0163",
        active_candidate_ids=["AF-CAND-0165"],
        stop_reason="data_regime_audit_completed_retire_lane",
        state_path=parent_dir / "state.json",
        last_report_path=parent_report_path,
        next_recommendations_path=parent_recommendations_path,
        updated_utc="2026-03-22T22:48:08Z",
    )
    parent_report = NextStepControllerReport(
        campaign_id=parent_campaign_id,
        parent_campaign_id="campaign-grandparent",
        selected_step_type="data_regime_audit",
        step_reason="The last processed lane retired after regime review.",
        status="completed",
        stop_reason="data_regime_audit_completed_retire_lane",
        candidate_scope=["AF-CAND-0165"],
        data_regime_audit_reports=[
            {
                "family": "scalping",
                "audited_candidate_ids": ["AF-CAND-0165"],
                "reference_candidate_id": "AF-CAND-0165",
                "focus_candidate_id": "AF-CAND-0165",
                "failed_window_index": 1,
                "lane_decision": "retire_lane",
                "summary": "Last lane retired after regime review.",
                "recommended_actions": [],
                "slice_summaries": [],
                "candidate_summaries": [],
                "artifact_paths": {},
            }
        ],
        continuation_status="stop",
        stop_class="policy_decision",
        auto_continue_allowed=False,
        transition_status="move_to_next_lane",
        report_path=parent_report_path,
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(parent_report_path, parent_report.model_dump(mode="json"))
    write_json(parent_recommendations_path, [])

    _seed_data_feature_candidate(
        settings.paths().reports_dir / "AF-CAND-0163",
        "AF-CAND-0163",
        trade_count=378,
        profit_factor=1.18,
        out_of_sample_profit_factor=1.57,
        expectancy_pips=0.35,
        stress_passed=True,
        walk_forward_ok=False,
        pbo=0.80,
        white_reality_check_p_value=1.0,
        entry_style="session_breakout",
        dataset_snapshot_id="snap-directional",
        feature_version_id="feat-directional",
        label_version_id="label-directional",
        execution_cost_model_version="cost-london-open",
    )
    _seed_data_feature_candidate(
        settings.paths().reports_dir / "AF-CAND-0165",
        "AF-CAND-0165",
        trade_count=220,
        profit_factor=0.86,
        out_of_sample_profit_factor=0.84,
        expectancy_pips=-0.26,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=0.10,
        white_reality_check_p_value=0.40,
        entry_style="failed_break_fade",
        dataset_snapshot_id="snap-directional",
        feature_version_id="feat-directional",
        label_version_id="label-directional",
        execution_cost_model_version="cost-europe-open",
    )

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-feature-mixed-cost",
        allowed_step_types=["data_feature_audit"],
    )

    assert report.selected_step_type == "data_feature_audit"
    assert report.status == "completed"
    assert report.continuation_status == "continue"
    assert report.stop_class == "none"
    assert report.auto_continue_allowed is True
    assert report.transition_status == "continue_lane"
    assert report.recommended_follow_on_step == "diagnose_existing_candidates"
    audit_report = report.data_feature_audit_reports[0]
    assert set(audit_report.audited_candidate_ids) == {"AF-CAND-0163", "AF-CAND-0165"}
    assert audit_report.reference_candidate_id == "AF-CAND-0163"
    assert audit_report.family_decision == "bounded_correction_supported"
    assert "provenance_contract_mixed" in audit_report.suspected_root_causes
    assert report.next_recommendations[0].candidate_id == "AF-CAND-0163"
    assert report.next_recommendations[0].step_type == "diagnose_existing_candidates"


def test_run_next_step_data_feature_audit_ignores_session_filtered_snapshot_id_when_raw_dataset_matches(settings):
    parent_campaign_id = "campaign-parent-feature-raw-dataset"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_report_path = parent_dir / "next_step_report.json"
    parent_recommendations_path = parent_dir / "next_recommendations.json"
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0163",
        target_candidate_ids=["AF-CAND-0165"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0163",
        active_candidate_ids=["AF-CAND-0165"],
        stop_reason="data_regime_audit_completed_retire_lane",
        state_path=parent_dir / "state.json",
        last_report_path=parent_report_path,
        next_recommendations_path=parent_recommendations_path,
        updated_utc="2026-03-22T22:48:08Z",
    )
    parent_report = NextStepControllerReport(
        campaign_id=parent_campaign_id,
        parent_campaign_id="campaign-grandparent",
        selected_step_type="data_regime_audit",
        step_reason="The last processed lane retired after regime review.",
        status="completed",
        stop_reason="data_regime_audit_completed_retire_lane",
        candidate_scope=["AF-CAND-0165"],
        data_regime_audit_reports=[
            {
                "family": "scalping",
                "audited_candidate_ids": ["AF-CAND-0165"],
                "reference_candidate_id": "AF-CAND-0165",
                "focus_candidate_id": "AF-CAND-0165",
                "failed_window_index": 1,
                "lane_decision": "retire_lane",
                "summary": "Last lane retired after regime review.",
                "recommended_actions": [],
                "slice_summaries": [],
                "candidate_summaries": [],
                "artifact_paths": {},
            }
        ],
        continuation_status="stop",
        stop_class="policy_decision",
        auto_continue_allowed=False,
        transition_status="move_to_next_lane",
        report_path=parent_report_path,
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(parent_report_path, parent_report.model_dump(mode="json"))
    write_json(parent_recommendations_path, [])

    _seed_data_feature_candidate(
        settings.paths().reports_dir / "AF-CAND-0163",
        "AF-CAND-0163",
        trade_count=378,
        profit_factor=1.18,
        out_of_sample_profit_factor=1.57,
        expectancy_pips=0.35,
        stress_passed=True,
        walk_forward_ok=False,
        pbo=0.80,
        white_reality_check_p_value=1.0,
        entry_style="session_breakout",
        dataset_snapshot_id="snapshot-session-wide",
        feature_version_id="feat-directional",
        label_version_id="label-directional",
        execution_cost_model_version="cost-london-open",
    )
    _seed_data_feature_candidate(
        settings.paths().reports_dir / "AF-CAND-0165",
        "AF-CAND-0165",
        trade_count=220,
        profit_factor=0.86,
        out_of_sample_profit_factor=0.84,
        expectancy_pips=-0.26,
        stress_passed=False,
        walk_forward_ok=False,
        pbo=0.10,
        white_reality_check_p_value=0.40,
        entry_style="failed_break_fade",
        dataset_snapshot_id="snapshot-session-core",
        feature_version_id="feat-directional",
        label_version_id="label-directional",
        execution_cost_model_version="cost-europe-open",
    )
    for candidate_id in ("AF-CAND-0163", "AF-CAND-0165"):
        provenance_path = settings.paths().reports_dir / candidate_id / "data_provenance.json"
        provenance_payload = read_json(provenance_path)
        provenance_payload["dataset_snapshot"].update(
            {
                "source": "oanda",
                "instrument": "EUR_USD",
                "dataset_start_utc": "2026-02-01T22:04:00Z",
                "dataset_end_utc": "2026-03-20T20:59:00Z",
            }
        )
        write_json(provenance_path, provenance_payload)

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-feature-raw-dataset",
        allowed_step_types=["data_feature_audit"],
    )

    audit_report = report.data_feature_audit_reports[0]
    assert set(audit_report.audited_candidate_ids) == {"AF-CAND-0163", "AF-CAND-0165"}
    assert audit_report.reference_candidate_id == "AF-CAND-0163"


def test_run_next_step_data_feature_audit_retires_family_after_bounded_correction_attempt(settings):
    prior_audit_dir = settings.paths().campaigns_dir / "campaign-prior-feature-audit"
    prior_audit_report_path = prior_audit_dir / "next_step_report.json"
    prior_audit_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        prior_audit_report_path,
        NextStepControllerReport(
            campaign_id="campaign-prior-feature-audit",
            parent_campaign_id="campaign-prior-lane",
            selected_step_type="data_feature_audit",
            step_reason="Prior family audit supported one bounded correction.",
            status="completed",
            stop_reason="data_feature_audit_completed_bounded_correction_supported",
            candidate_scope=["AF-CAND-0163", "AF-CAND-0164", "AF-CAND-0165"],
            data_feature_audit_reports=[
                {
                    "family": "scalping",
                    "audited_candidate_ids": ["AF-CAND-0163", "AF-CAND-0164", "AF-CAND-0165"],
                    "reference_candidate_id": "AF-CAND-0163",
                    "family_decision": "bounded_correction_supported",
                    "summary": "One bounded correction is justified.",
                }
            ],
            continuation_status="continue",
            stop_class="none",
            auto_continue_allowed=True,
            report_path=prior_audit_report_path,
        ).model_dump(mode="json"),
    )

    parent_campaign_id = "campaign-parent-feature-post-correction"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_report_path = parent_dir / "next_step_report.json"
    parent_recommendations_path = parent_dir / "next_recommendations.json"
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0169",
        target_candidate_ids=["AF-CAND-0169"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0169",
        active_candidate_ids=["AF-CAND-0169"],
        stop_reason="data_regime_audit_completed_retire_lane",
        state_path=parent_dir / "state.json",
        last_report_path=parent_report_path,
        next_recommendations_path=parent_recommendations_path,
        updated_utc="2026-03-22T23:04:34Z",
    )
    parent_report = NextStepControllerReport(
        campaign_id=parent_campaign_id,
        parent_campaign_id="campaign-grandparent",
        selected_step_type="data_regime_audit",
        step_reason="Post-correction lane retired after regime review.",
        status="completed",
        stop_reason="data_regime_audit_completed_retire_lane",
        candidate_scope=["AF-CAND-0169"],
        data_regime_audit_reports=[
            {
                "family": "scalping",
                "audited_candidate_ids": ["AF-CAND-0169"],
                "reference_candidate_id": "AF-CAND-0169",
                "focus_candidate_id": "AF-CAND-0169",
                "failed_window_index": 1,
                "lane_decision": "retire_lane",
                "summary": "Post-correction lane retired after regime review.",
                "recommended_actions": [],
                "slice_summaries": [],
                "candidate_summaries": [],
                "artifact_paths": {},
            }
        ],
        continuation_status="stop",
        stop_class="policy_decision",
        auto_continue_allowed=False,
        transition_status="move_to_next_lane",
        report_path=parent_report_path,
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(parent_report_path, parent_report.model_dump(mode="json"))
    write_json(parent_recommendations_path, [])

    seed_payloads = [
        ("AF-CAND-0163", 378, 1.18, 1.57, 0.35, True, False, 0.80, 1.0, "session_breakout", "snapshot-a", "cost-a"),
        (
            "AF-CAND-0164",
            24,
            0.72,
            6.68,
            -0.64,
            False,
            False,
            0.10,
            0.50,
            "pullback_continuation",
            "snapshot-b",
            "cost-b",
        ),
        ("AF-CAND-0165", 220, 0.86, 0.84, -0.26, False, False, 0.10, 0.40, "failed_break_fade", "snapshot-b", "cost-c"),
        ("AF-CAND-0169", 257, 1.15, 1.27, 0.30, False, False, 0.77, 0.36, "session_breakout", "snapshot-c", "cost-a"),
    ]
    for (
        candidate_id,
        trade_count,
        profit_factor,
        oos_pf,
        expectancy,
        stress_passed,
        walk_forward_ok,
        pbo,
        wrc,
        entry_style,
        snapshot_id,
        cost_version,
    ) in seed_payloads:
        _seed_data_feature_candidate(
            settings.paths().reports_dir / candidate_id,
            candidate_id,
            trade_count=trade_count,
            profit_factor=profit_factor,
            out_of_sample_profit_factor=oos_pf,
            expectancy_pips=expectancy,
            stress_passed=stress_passed,
            walk_forward_ok=walk_forward_ok,
            pbo=pbo,
            white_reality_check_p_value=wrc,
            entry_style=entry_style,
            dataset_snapshot_id=snapshot_id,
            feature_version_id="feat-directional",
            label_version_id="label-directional",
            execution_cost_model_version=cost_version,
        )
        provenance_path = settings.paths().reports_dir / candidate_id / "data_provenance.json"
        provenance_payload = read_json(provenance_path)
        provenance_payload["dataset_snapshot"].update(
            {
                "source": "oanda",
                "instrument": "EUR_USD",
                "dataset_start_utc": "2026-02-01T22:04:00Z",
                "dataset_end_utc": "2026-03-20T20:59:00Z",
            }
        )
        write_json(provenance_path, provenance_payload)

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-feature-post-correction",
        allowed_step_types=["data_feature_audit"],
    )

    audit_report = report.data_feature_audit_reports[0]
    assert audit_report.family_decision == "retire_family"
    assert report.continuation_status == "stop"
    assert report.stop_class == "policy_decision"
    assert report.recommended_follow_on_step == "data_label_audit"


def test_run_next_step_executes_data_label_audit_after_family_retirement(settings):
    parent_campaign_id = "campaign-parent-label-audit"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_report_path = parent_dir / "next_step_report.json"
    parent_recommendations_path = parent_dir / "next_recommendations.json"
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0014-PULL",
        target_candidate_ids=["AF-CAND-0050"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0014-PULL",
        active_candidate_ids=["AF-CAND-0050"],
        stop_reason="data_feature_audit_completed_retire_family",
        state_path=parent_dir / "state.json",
        last_report_path=parent_report_path,
        next_recommendations_path=parent_recommendations_path,
        updated_utc="2026-03-22T09:05:19Z",
    )
    parent_report = NextStepControllerReport(
        campaign_id=parent_campaign_id,
        parent_campaign_id="campaign-grandparent",
        selected_step_type="data_feature_audit",
        step_reason="Retire the family and inspect the upstream contract next.",
        status="completed",
        stop_reason="data_feature_audit_completed_retire_family",
        candidate_scope=["AF-CAND-0050", "AF-CAND-0048", "AF-CAND-0047"],
        data_feature_audit_reports=[
            {
                "family": "scalping",
                "audited_candidate_ids": ["AF-CAND-0050", "AF-CAND-0048", "AF-CAND-0047"],
                "reference_candidate_id": "AF-CAND-0050",
                "family_decision": "retire_family",
                "summary": "Family retired after data/feature audit.",
                "suspected_root_causes": [
                    "provenance_contract_consistent",
                    "execution_cost_realism_consumes_edge",
                    "persistent_walk_forward_instability",
                ],
                "recommended_actions": ["Open a separate data/label audit before resuming autonomous search."],
            }
        ],
        continuation_status="stop",
        stop_class="policy_decision",
        auto_continue_allowed=False,
        report_path=parent_report_path,
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(parent_report_path, parent_report.model_dump(mode="json"))
    write_json(parent_recommendations_path, [])

    feature_path = settings.project_root / "src" / "agentic_forex" / "features" / "service.py"
    label_path = settings.project_root / "src" / "agentic_forex" / "labels" / "service.py"
    feature_path.parent.mkdir(parents=True, exist_ok=True)
    label_path.parent.mkdir(parents=True, exist_ok=True)
    feature_path.write_text("def build_features(frame):\n    return frame\n", encoding="utf-8")
    label_path.write_text(
        "def build_labels(frame, holding_bars):\n"
        "    future_price = frame['mid_c'].shift(-holding_bars)\n"
        "    frame['future_return_pips'] = future_price - frame['mid_c']\n"
        "    frame['label_up'] = (frame['future_return_pips'] > 0).astype(int)\n"
        "    return frame\n",
        encoding="utf-8",
    )

    for candidate_id, entry_style, trade_count, expectancy in (
        ("AF-CAND-0050", "pullback_continuation", 24, -0.67),
        ("AF-CAND-0048", "failed_break_fade", 19, -1.18),
        ("AF-CAND-0047", "failed_break_fade", 19, -1.18),
    ):
        _seed_data_feature_candidate(
            settings.paths().reports_dir / candidate_id,
            candidate_id,
            trade_count=trade_count,
            profit_factor=0.71 if candidate_id == "AF-CAND-0050" else 0.42,
            out_of_sample_profit_factor=6.31 if candidate_id == "AF-CAND-0050" else 0.0,
            expectancy_pips=expectancy,
            stress_passed=False,
            walk_forward_ok=False,
            pbo=0.0,
            white_reality_check_p_value=1.0,
            entry_style=entry_style,
            dataset_snapshot_id="61e89b30942a1ceb",
            feature_version_id="758a61d83428e532",
            label_version_id="104c608f5ff79a88",
            execution_cost_model_version="00ca1f0176143aaa",
            feature_paths=[str(feature_path)],
            label_paths=[str(label_path)],
        )

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-label-audit",
        allowed_step_types=["data_label_audit"],
    )

    assert report.selected_step_type == "data_label_audit"
    assert report.status == "completed"
    assert report.next_recommendations == []
    assert report.continuation_status == "stop"
    assert report.stop_class == "policy_decision"
    assert report.transition_status == "hard_stop"
    assert len(report.data_label_audit_reports) == 1
    audit_report = report.data_label_audit_reports[0]
    assert audit_report.contract_decision == "upstream_contract_change_required"
    assert audit_report.reference_candidate_id == "AF-CAND-0050"
    assert "label_contract_binary_direction_only" in audit_report.suspected_contract_gaps
    assert "label_contract_ignores_trade_path_geometry" in audit_report.suspected_contract_gaps
    assert "shared_label_contract_fails_across_styles" in audit_report.suspected_contract_gaps
    assert "Replace the binary future-return label" in audit_report.recommended_actions[1]


def test_run_next_step_treats_path_aware_label_contract_as_family_level_signal(settings):
    parent_campaign_id = "campaign-parent-label-audit-path-aware"
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_report_path = parent_dir / "next_step_report.json"
    parent_recommendations_path = parent_dir / "next_recommendations.json"
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family="scalping",
        baseline_candidate_id="AF-CAND-0054",
        target_candidate_ids=["AF-CAND-0055"],
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family="scalping",
        status="completed",
        baseline_candidate_id="AF-CAND-0054",
        active_candidate_ids=["AF-CAND-0055"],
        stop_reason="data_feature_audit_completed_retire_family",
        state_path=parent_dir / "state.json",
        last_report_path=parent_report_path,
        next_recommendations_path=parent_recommendations_path,
        updated_utc="2026-03-22T15:05:19Z",
    )
    parent_report = NextStepControllerReport(
        campaign_id=parent_campaign_id,
        parent_campaign_id="campaign-grandparent",
        selected_step_type="data_feature_audit",
        step_reason="Retire the family and inspect the upstream contract next.",
        status="completed",
        stop_reason="data_feature_audit_completed_retire_family",
        candidate_scope=["AF-CAND-0055", "AF-CAND-0056", "AF-CAND-0057"],
        data_feature_audit_reports=[
            {
                "family": "scalping",
                "audited_candidate_ids": ["AF-CAND-0055", "AF-CAND-0056", "AF-CAND-0057"],
                "reference_candidate_id": "AF-CAND-0055",
                "family_decision": "retire_family",
                "summary": "Family retired after data/feature audit.",
                "suspected_root_causes": [
                    "provenance_contract_consistent",
                    "execution_cost_realism_consumes_edge",
                    "persistent_walk_forward_instability",
                ],
                "recommended_actions": ["Open a separate data/label audit before resuming autonomous search."],
            }
        ],
        continuation_status="stop",
        stop_class="policy_decision",
        auto_continue_allowed=False,
        report_path=parent_report_path,
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(parent_report_path, parent_report.model_dump(mode="json"))
    write_json(parent_recommendations_path, [])

    feature_path = settings.project_root / "src" / "agentic_forex" / "features" / "service.py"
    label_path = settings.project_root / "src" / "agentic_forex" / "labels" / "service.py"
    feature_path.parent.mkdir(parents=True, exist_ok=True)
    label_path.parent.mkdir(parents=True, exist_ok=True)
    feature_path.write_text(
        "def build_features(frame):\n    frame['range_position_10'] = 0.5\n    return frame\n",
        encoding="utf-8",
    )
    label_path.write_text(
        "def build_labels(frame, holding_bars, stop_loss_pips, take_profit_pips):\n"
        "    frame['future_return_pips'] = 0.0\n"
        "    frame['timeout_return_pips'] = 0.0\n"
        "    frame['long_exit_reason'] = 'time_exit'\n"
        "    frame['short_exit_reason'] = 'time_exit'\n"
        "    frame['label_up'] = 0\n"
        "    frame['label_down'] = 0\n"
        "    frame['stop_loss_pips'] = stop_loss_pips\n"
        "    frame['take_profit_pips'] = take_profit_pips\n"
        "    return frame\n",
        encoding="utf-8",
    )

    for candidate_id, entry_style, trade_count, expectancy, holding_bars in (
        ("AF-CAND-0055", "volatility_breakout", 42, -0.25, 18),
        ("AF-CAND-0056", "mean_reversion_pullback", 38, -0.18, 24),
        ("AF-CAND-0057", "session_breakout", 36, -0.21, 30),
    ):
        _seed_data_feature_candidate(
            settings.paths().reports_dir / candidate_id,
            candidate_id,
            trade_count=trade_count,
            profit_factor=0.88,
            out_of_sample_profit_factor=0.94,
            expectancy_pips=expectancy,
            stress_passed=False,
            walk_forward_ok=False,
            pbo=0.0,
            white_reality_check_p_value=1.0,
            entry_style=entry_style,
            dataset_snapshot_id="61e89b30942a1ceb",
            feature_version_id="path-aware-feat-v1",
            label_version_id="path-aware-label-v1",
            execution_cost_model_version="00ca1f0176143aaa",
            holding_bars=holding_bars,
            feature_paths=[str(feature_path)],
            label_paths=[str(label_path)],
        )

    report = run_next_step(
        settings,
        family="scalping",
        parent_campaign_id=parent_campaign_id,
        campaign_id="campaign-child-label-audit-path-aware",
        allowed_step_types=["data_label_audit"],
    )

    assert report.selected_step_type == "data_label_audit"
    assert report.status == "completed"
    assert len(report.data_label_audit_reports) == 1
    audit_report = report.data_label_audit_reports[0]
    assert audit_report.contract_decision == "family_retire_confirmed"
    assert "label_contract_binary_direction_only" not in audit_report.suspected_contract_gaps
    assert "label_contract_ignores_trade_path_geometry" not in audit_report.suspected_contract_gaps
    assert "shared_label_contract_fails_across_styles" in audit_report.suspected_contract_gaps


def test_run_governed_loop_auto_continues_until_boundary(settings, monkeypatch):
    call_sequence: list[str | None] = []

    def _fake_run_next_step(
        settings,
        *,
        family="scalping",
        parent_campaign_id=None,
        campaign_id=None,
        allowed_step_types=None,
    ):
        call_sequence.append(parent_campaign_id)
        if len(call_sequence) == 1:
            return NextStepControllerReport(
                campaign_id="campaign-step-1",
                parent_campaign_id=parent_campaign_id,
                selected_step_type="mutate_one_candidate",
                step_reason="Execute the bound mutation.",
                status="completed",
                stop_reason="mutation_completed_with_supported_recommendation",
                candidate_scope=["AF-CAND-LOOP"],
                next_recommendations=[
                    NextStepRecommendation(
                        step_type="re_evaluate_one_candidate",
                        candidate_id="AF-CAND-LOOP-CHILD",
                        rationale="Reevaluate the mutated branch next.",
                    )
                ],
                continuation_status="continue",
                stop_class="none",
                auto_continue_allowed=True,
                recommended_follow_on_step="re_evaluate_one_candidate",
                max_safe_follow_on_steps=1,
                report_path=settings.paths().campaigns_dir / "campaign-step-1" / "next_step_report.json",
            )
        return NextStepControllerReport(
            campaign_id="campaign-step-2",
            parent_campaign_id=parent_campaign_id,
            selected_step_type="re_evaluate_one_candidate",
            step_reason="Reevaluate the weak branch.",
            status="completed",
            stop_reason="re_evaluation_completed_with_supported_recommendation",
            candidate_scope=["AF-CAND-LOOP-CHILD"],
            next_recommendations=[
                NextStepRecommendation(
                    step_type="diagnose_existing_candidates",
                    candidate_id="AF-CAND-LOOP-CHILD",
                    rationale="Diagnose before further mutation.",
                )
            ],
            continuation_status="stop",
            stop_class="lane_exhausted",
            auto_continue_allowed=False,
            recommended_follow_on_step="diagnose_existing_candidates",
            max_safe_follow_on_steps=0,
            report_path=settings.paths().campaigns_dir / "campaign-step-2" / "next_step_report.json",
        )

    monkeypatch.setattr("agentic_forex.campaigns.governed_loop.run_next_step", _fake_run_next_step)

    report = run_governed_loop(
        settings,
        family="scalping",
        parent_campaign_id="campaign-parent-loop",
        loop_id="loop-test",
        max_steps=4,
    )

    assert report.executed_steps == 2
    assert report.stop_class == "lane_exhausted"
    assert report.stop_reason == "re_evaluation_completed_with_supported_recommendation"
    assert report.executed_campaign_ids == ["campaign-step-1", "campaign-step-2"]
    assert report.final_parent_campaign_id == "campaign-step-2"
    assert report.report_path.exists()


def _seed_candidate_spec(settings, *, candidate_id: str, allowed_hours: list[int]) -> None:
    report_dir = settings.paths().reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    candidate = CandidateDraft(
        candidate_id=candidate_id,
        family="scalping",
        title=f"Candidate {candidate_id}",
        thesis="Bounded controller test candidate.",
        source_citations=["SRC-001"],
        strategy_hypothesis="Breakout continuation under Europe-session structure.",
        market_context=MarketContextSummary(
            session_focus="extended_session_quality_breakout",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=["Controller test seed."],
            allowed_hours_utc=allowed_hours,
        ),
        setup_summary="Test setup summary.",
        entry_summary="Test entry summary.",
        exit_summary="Test exit summary.",
        risk_summary="Test risk summary.",
        entry_style="session_breakout",
        holding_bars=26,
        signal_threshold=0.96,
        stop_loss_pips=4.2,
        take_profit_pips=7.4,
    )
    spec = StrategySpec(
        candidate_id=candidate_id,
        family="scalping",
        benchmark_group_id=candidate_id,
        variant_name="controller_seed",
        session_policy=SessionPolicy(
            name="candidate_defined_intraday",
            allowed_sessions=["europe_open_breakout"],
            allowed_hours_utc=allowed_hours,
            notes=["controller_seed"],
        ),
        side_policy="both",
        setup_logic=SetupLogic(
            style="session_breakout", summary="Test setup summary.", trigger_conditions=["Breakout confirmation"]
        ),
        filters=[
            {"name": "volatility_preference", "rule": "high"},
            {"name": "max_spread_pips", "rule": "1.9"},
            {"name": "min_volatility_20", "rule": "0.00012"},
            {"name": "require_ret_5_alignment", "rule": "true"},
            {"name": "require_mean_location_alignment", "rule": "true"},
            {"name": "breakout_zscore_floor", "rule": "0.32"},
            {"name": "ret_5_floor", "rule": "0.00005"},
        ],
        entry_logic=["Test entry summary.", "Signal threshold 0.96"],
        exit_logic=["Test exit summary.", "Time exit after 26 bars"],
        risk_policy=RiskPolicy(stop_loss_pips=4.2, take_profit_pips=7.4, notes=["Controller test risk policy."]),
        source_citations=["SRC-001"],
        notes=["Seeded for next-step controller tests."],
        entry_style="session_breakout",
        holding_bars=26,
        signal_threshold=0.96,
        stop_loss_pips=4.2,
        take_profit_pips=7.4,
    )
    write_json(report_dir / "candidate.json", candidate.model_dump(mode="json"))
    write_json(report_dir / "strategy_spec.json", spec.model_dump(mode="json"))


def _seed_candidate_reports(report_dir: Path, candidate_id: str) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    allowed_hours = [7, 8, 9, 10, 11, 12, 13, 14]
    write_json(
        report_dir / "strategy_spec.json",
        {
            "candidate_id": candidate_id,
            "session_policy": {"allowed_hours_utc": allowed_hours},
        },
    )
    start = datetime(2024, 1, 1, 7, 0, tzinfo=UTC)
    rows = []
    balance = 100000.0
    first_window_pattern = [("europe", "mean_reversion_context", -1.0)] * 2 + [("overlap", "trend_context", -2.1)] * 10
    second_window_pattern = [("europe", "trend_context", 1.2)] * 8 + [("overlap", "trend_context", 1.8)] * 4
    third_window_pattern = [("europe", "trend_context", 1.1)] * 8 + [("overlap", "trend_context", 1.7)] * 4
    for index, (session_bucket, context_bucket, pnl_pips) in enumerate(
        first_window_pattern + second_window_pattern + third_window_pattern
    ):
        if session_bucket == "europe":
            timestamp = start + timedelta(minutes=index * 10)
        else:
            timestamp = start.replace(hour=13, minute=0) + timedelta(minutes=index * 10)
        balance += pnl_pips * 50
        rows.append(
            {
                "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
                "exit_timestamp_utc": (timestamp + timedelta(minutes=26)).isoformat().replace("+00:00", "Z"),
                "split": "validation" if index < 24 else "out_of_sample",
                "side": "long",
                "entry_price": 1.1,
                "exit_price": 1.1005,
                "pnl_pips": pnl_pips,
                "pnl_dollars": pnl_pips * 50,
                "position_size_lots": 5.0,
                "balance_after": balance,
                "margin_utilization_pct": 20.0,
                "session_bucket": session_bucket,
                "volatility_bucket": "high",
                "context_bucket": context_bucket,
                "exit_reason": "time_exit" if pnl_pips > 0 else "stop_loss",
            }
        )
    pd.DataFrame.from_records(rows).to_csv(report_dir / "trade_ledger.csv", index=False)
    write_json(report_dir / "backtest_summary.json", {"candidate_id": candidate_id})
    write_json(
        report_dir / "robustness_report.json", {"candidate_id": candidate_id, "status": "robustness_provisional"}
    )
    write_json(
        report_dir / "review_packet.json",
        {
            "candidate_id": candidate_id,
            "readiness": "robustness_provisional",
            "metrics": {
                "grades": {"walk_forward_ok": False},
                "walk_forward_summary": [
                    {"window": 1, "trade_count": 12, "profit_factor": 0.7, "expectancy_pips": -1.825},
                    {"window": 2, "trade_count": 12, "profit_factor": 1.4, "expectancy_pips": 1.4},
                    {"window": 3, "trade_count": 12, "profit_factor": 1.5, "expectancy_pips": 1.3},
                ],
            },
        },
    )


def _seed_context_comparison_reports(report_dir: Path, candidate_id: str) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    allowed_hours = [7, 8, 9, 10, 11, 12]
    write_json(
        report_dir / "strategy_spec.json",
        {
            "candidate_id": candidate_id,
            "session_policy": {"allowed_hours_utc": allowed_hours},
        },
    )
    start = datetime(2024, 1, 1, 7, 0, tzinfo=UTC)
    rows = []
    balance = 100000.0
    first_window_pattern = [("europe", "trend_context", -1.8)] * 10 + [("europe", "mean_reversion_context", -0.2)] * 2
    second_window_pattern = [("europe", "trend_context", 1.4)] * 8 + [("europe", "mean_reversion_context", 0.2)] * 4
    third_window_pattern = [("europe", "trend_context", 1.3)] * 8 + [("europe", "mean_reversion_context", 0.1)] * 4
    for index, (session_bucket, context_bucket, pnl_pips) in enumerate(
        first_window_pattern + second_window_pattern + third_window_pattern
    ):
        timestamp = start + timedelta(minutes=index * 10)
        balance += pnl_pips * 50
        rows.append(
            {
                "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
                "exit_timestamp_utc": (timestamp + timedelta(minutes=26)).isoformat().replace("+00:00", "Z"),
                "split": "validation" if index < 24 else "out_of_sample",
                "side": "long",
                "entry_price": 1.1,
                "exit_price": 1.1005,
                "pnl_pips": pnl_pips,
                "pnl_dollars": pnl_pips * 50,
                "position_size_lots": 5.0,
                "balance_after": balance,
                "margin_utilization_pct": 20.0,
                "session_bucket": session_bucket,
                "volatility_bucket": "high",
                "context_bucket": context_bucket,
                "exit_reason": "time_exit" if pnl_pips > 0 else "stop_loss",
            }
        )
    pd.DataFrame.from_records(rows).to_csv(report_dir / "trade_ledger.csv", index=False)
    write_json(report_dir / "backtest_summary.json", {"candidate_id": candidate_id})
    write_json(
        report_dir / "robustness_report.json", {"candidate_id": candidate_id, "status": "robustness_provisional"}
    )
    write_json(
        report_dir / "review_packet.json",
        {
            "candidate_id": candidate_id,
            "readiness": "robustness_provisional",
            "metrics": {
                "grades": {"walk_forward_ok": False},
                "walk_forward_summary": [
                    {"window": 1, "trade_count": 12, "profit_factor": 0.65, "expectancy_pips": -1.533},
                    {"window": 2, "trade_count": 12, "profit_factor": 1.4, "expectancy_pips": 1.0},
                    {"window": 3, "trade_count": 12, "profit_factor": 1.3, "expectancy_pips": 0.9},
                ],
            },
        },
    )


def _seed_candidate_review_packet(
    report_dir: Path, candidate_id: str, *, walk_forward_ok: bool, stress_passed: bool
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(report_dir / "backtest_summary.json", {"candidate_id": candidate_id})
    write_json(
        report_dir / "robustness_report.json", {"candidate_id": candidate_id, "status": "robustness_provisional"}
    )
    write_json(
        report_dir / "review_packet.json",
        {
            "candidate_id": candidate_id,
            "readiness": "robustness_provisional",
            "metrics": {
                "trade_count": 140,
                "out_of_sample_profit_factor": 1.2,
                "expectancy_pips": 0.3,
                "stress_passed": stress_passed,
                "grades": {"walk_forward_ok": walk_forward_ok},
                "robustness_report": {
                    "deflated_sharpe_ratio": 0.5,
                    "cscv_pbo_available": True,
                    "pbo": 0.2,
                },
            },
        },
    )


def _seed_hypothesis_audit_candidate(
    report_dir: Path,
    candidate_id: str,
    *,
    trade_count: int,
    profit_factor: float,
    out_of_sample_profit_factor: float,
    expectancy_pips: float,
    stress_passed: bool,
    walk_forward_ok: bool,
    pbo: float,
    white_reality_check_p_value: float,
    family: str = "scalping",
    entry_style: str = "breakout",
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        report_dir / "strategy_spec.json",
        {
            "candidate_id": candidate_id,
            "family": family,
            "entry_style": entry_style,
        },
    )
    write_json(report_dir / "backtest_summary.json", {"candidate_id": candidate_id})
    write_json(
        report_dir / "review_packet.json",
        {
            "candidate_id": candidate_id,
            "readiness": "robustness_provisional",
            "metrics": {
                "trade_count": trade_count,
                "profit_factor": profit_factor,
                "out_of_sample_profit_factor": out_of_sample_profit_factor,
                "expectancy_pips": expectancy_pips,
                "stress_passed": stress_passed,
                "grades": {"walk_forward_ok": walk_forward_ok},
            },
        },
    )
    write_json(
        report_dir / "robustness_report.json",
        {
            "candidate_id": candidate_id,
            "status": "robustness_provisional",
            "pbo": pbo,
            "white_reality_check_p_value": white_reality_check_p_value,
        },
    )


def _seed_data_regime_candidate(
    report_dir: Path,
    candidate_id: str,
    *,
    first_window_pattern: list[tuple[str, str, float]],
    later_window_pattern: list[tuple[str, str, float]],
    trade_count: int,
    profit_factor: float,
    out_of_sample_profit_factor: float,
    expectancy_pips: float,
    stress_passed: bool,
    walk_forward_ok: bool,
    pbo: float | None,
    white_reality_check_p_value: float | None,
    entry_style: str,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        report_dir / "strategy_spec.json",
        {
            "candidate_id": candidate_id,
            "family": "scalping",
            "entry_style": entry_style,
        },
    )
    rows = []
    balance = 100000.0
    start = datetime(2024, 1, 1, 7, 0, tzinfo=UTC)
    all_rows = list(first_window_pattern) + list(later_window_pattern)
    for index, (session_bucket, context_bucket, pnl_pips) in enumerate(all_rows):
        timestamp = start + timedelta(minutes=index * 10)
        balance += pnl_pips * 50
        rows.append(
            {
                "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
                "exit_timestamp_utc": (timestamp + timedelta(minutes=25)).isoformat().replace("+00:00", "Z"),
                "split": "validation" if index < len(first_window_pattern) else "out_of_sample",
                "side": "long",
                "entry_price": 1.1,
                "exit_price": 1.1005,
                "pnl_pips": pnl_pips,
                "pnl_dollars": pnl_pips * 50,
                "position_size_lots": 5.0,
                "balance_after": balance,
                "margin_utilization_pct": 20.0,
                "session_bucket": session_bucket,
                "volatility_bucket": "high",
                "context_bucket": context_bucket,
                "exit_reason": "time_exit" if pnl_pips > 0 else "stop_loss",
            }
        )
    pd.DataFrame.from_records(rows).to_csv(report_dir / "trade_ledger.csv", index=False)
    write_json(report_dir / "backtest_summary.json", {"candidate_id": candidate_id})
    write_json(
        report_dir / "review_packet.json",
        {
            "candidate_id": candidate_id,
            "readiness": "robustness_provisional",
            "metrics": {
                "trade_count": trade_count,
                "profit_factor": profit_factor,
                "out_of_sample_profit_factor": out_of_sample_profit_factor,
                "expectancy_pips": expectancy_pips,
                "stress_passed": stress_passed,
                "walk_forward_summary": [
                    {
                        "window": 1,
                        "trade_count": len(first_window_pattern),
                        "profit_factor": 0.7,
                        "expectancy_pips": -0.8,
                    },
                    {
                        "window": 2,
                        "trade_count": len(later_window_pattern) // 2,
                        "profit_factor": 1.3,
                        "expectancy_pips": 0.6,
                    },
                    {
                        "window": 3,
                        "trade_count": len(later_window_pattern) - (len(later_window_pattern) // 2),
                        "profit_factor": 1.3,
                        "expectancy_pips": 0.6,
                    },
                ],
                "grades": {"walk_forward_ok": walk_forward_ok},
            },
        },
    )
    robustness_payload = {
        "candidate_id": candidate_id,
        "status": "robustness_provisional",
    }
    if pbo is not None:
        robustness_payload["pbo"] = pbo
    if white_reality_check_p_value is not None:
        robustness_payload["white_reality_check_p_value"] = white_reality_check_p_value
    write_json(report_dir / "robustness_report.json", robustness_payload)


def _seed_data_feature_candidate(
    report_dir: Path,
    candidate_id: str,
    *,
    family: str = "scalping",
    trade_count: int,
    profit_factor: float,
    out_of_sample_profit_factor: float,
    expectancy_pips: float,
    stress_passed: bool,
    walk_forward_ok: bool,
    pbo: float,
    white_reality_check_p_value: float,
    entry_style: str,
    dataset_snapshot_id: str,
    feature_version_id: str,
    label_version_id: str,
    execution_cost_model_version: str,
    holding_bars: int = 24,
    stop_loss_pips_value: float = 4.8,
    take_profit_pips_value: float = 7.2,
    feature_paths: list[str] | None = None,
    label_paths: list[str] | None = None,
) -> None:
    _seed_hypothesis_audit_candidate(
        report_dir,
        candidate_id,
        trade_count=trade_count,
        profit_factor=profit_factor,
        out_of_sample_profit_factor=out_of_sample_profit_factor,
        expectancy_pips=expectancy_pips,
        stress_passed=stress_passed,
        walk_forward_ok=walk_forward_ok,
        pbo=pbo,
        white_reality_check_p_value=white_reality_check_p_value,
        family=family,
        entry_style=entry_style,
    )
    write_json(
        report_dir / "strategy_spec.json",
        {
            "candidate_id": candidate_id,
            "family": family,
            "entry_style": entry_style,
            "holding_bars": holding_bars,
            "stop_loss_pips": stop_loss_pips_value,
            "take_profit_pips": take_profit_pips_value,
        },
    )
    write_json(
        report_dir / "data_provenance.json",
        {
            "candidate_id": candidate_id,
            "dataset_snapshot": {"snapshot_id": dataset_snapshot_id},
            "feature_build": {
                "feature_version_id": feature_version_id,
                "label_version_id": label_version_id,
                "feature_paths": feature_paths or [],
                "label_paths": label_paths or [],
            },
            "execution_cost_model_version": execution_cost_model_version,
        },
    )


def _seed_contract_context_candidate(settings, *, candidate_id: str, exclude_context_bucket: str) -> None:
    report_dir = settings.paths().reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    spec = StrategySpec(
        candidate_id=candidate_id,
        family="day_trading",
        benchmark_group_id=candidate_id,
        variant_name=f"context_guard_{exclude_context_bucket}",
        instrument="EUR_USD",
        execution_granularity="M1",
        context_granularities=["M5", "M15", "H1"],
        session_policy=SessionPolicy(
            name="candidate_defined_intraday",
            allowed_sessions=["intraday_active_windows"],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12],
            notes=["controller duplicate test"],
        ),
        side_policy="both",
        setup_logic=SetupLogic(
            style="compression_breakout",
            summary="Duplicate-mutation controller test.",
            trigger_conditions=["Compression breakout confirmation"],
        ),
        filters=[
            {"name": "volatility_preference", "rule": "low_to_moderate"},
            {"name": "quality_flags", "rule": "controller_test"},
            {"name": "max_spread_pips", "rule": "2.8"},
            {"name": "exclude_context_bucket", "rule": exclude_context_bucket},
        ],
        entry_logic=["Enter on compression break.", "Signal threshold 1.15"],
        exit_logic=["Exit via fixed stop, fixed target, or 90-bar timeout."],
        risk_policy=RiskPolicy(
            stop_loss_pips=7.5,
            take_profit_pips=12.5,
            max_open_positions=1,
            max_risk_per_trade_pct=0.25,
            notes=["Duplicate-mutation test risk policy."],
        ),
        source_citations=["SRC-001"],
        notes=["Seeded for duplicate-mutation controller tests."],
        entry_style="compression_breakout",
        holding_bars=90,
        signal_threshold=1.15,
        stop_loss_pips=7.5,
        take_profit_pips=12.5,
    )
    write_json(report_dir / "strategy_spec.json", spec.model_dump(mode="json"))
    write_json(
        report_dir / "review_packet.json",
        {
            "candidate_id": candidate_id,
            "readiness": "robustness_provisional",
            "metrics": {
                "trade_count": 140,
                "out_of_sample_profit_factor": 1.2,
                "expectancy_pips": 0.3,
                "stress_passed": False,
                "grades": {"walk_forward_ok": False},
            },
        },
    )
    write_json(
        report_dir / "data_provenance.json",
        {
            "candidate_id": candidate_id,
            "dataset_snapshot": {"snapshot_id": "snapshot-dup"},
            "feature_build": {
                "feature_version_id": "feature-dup",
                "label_version_id": "label-dup",
            },
            "execution_cost_model_version": "cost-dup",
        },
    )
