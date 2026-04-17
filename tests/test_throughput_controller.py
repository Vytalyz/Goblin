from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agentic_forex.campaigns import run_next_step, run_program_loop
from agentic_forex.campaigns.throughput import _build_smoke_report, _smoke_expected_signal_frame, run_mt5_backtest_smoke
from agentic_forex.config.models import OrthogonalityMetadata, ProgramLanePolicy
from agentic_forex.governance import CampaignSpec, CampaignState
from agentic_forex.governance.models import (
    CandidateCompileReport,
    CandidateTriageReport,
    EASpecGenerationReport,
    MT5SmokeBacktestReport,
    RuleFormalizationReport,
)
from agentic_forex.mt5.ea_generator import render_candidate_ea
from agentic_forex.mt5.service import build_logic_manifest_payload
from agentic_forex.mt5.models import MT5RunResult
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.runtime import ReadPolicy
from agentic_forex.utils.io import read_json, write_json


def test_run_next_step_formalizes_rule_candidate_and_recommends_ea_spec(settings, monkeypatch):
    candidate_id = "AF-CAND-THRU-0001"
    _seed_throughput_candidate(settings, candidate_id=candidate_id)
    _seed_parent_campaign(
        settings,
        family="throughput_research",
        parent_campaign_id="campaign-throughput-formalize-parent",
        candidate_id=candidate_id,
        step_type="formalize_rule_candidate",
    )

    def _fake_formalize_rule_candidate(settings, *, candidate_id):
        report_dir = settings.paths().reports_dir / candidate_id
        return RuleFormalizationReport(
            candidate_id=candidate_id,
            readiness_status="rule_spec_complete",
            completeness_checks=["instrument", "entry_trigger_formula"],
            artifact_paths={
                "candidate_path": str(report_dir / "candidate.json"),
                "strategy_spec_path": str(report_dir / "strategy_spec.json"),
                "rule_spec_path": str(report_dir / "rule_spec.json"),
            },
        )

    monkeypatch.setattr("agentic_forex.campaigns.next_step.formalize_rule_candidate", _fake_formalize_rule_candidate)

    report = run_next_step(
        settings,
        family="throughput_research",
        parent_campaign_id="campaign-throughput-formalize-parent",
        campaign_id="campaign-throughput-formalize-child",
        allowed_step_types=["formalize_rule_candidate"],
    )

    assert report.selected_step_type == "formalize_rule_candidate"
    assert report.status == "completed"
    assert report.rule_formalization_reports[0].readiness_status == "rule_spec_complete"
    assert report.next_recommendations[0].step_type == "generate_ea_spec"
    assert report.auto_continue_allowed is True


def test_run_next_step_generate_ea_spec_redirects_failed_plausibility_to_triage(settings, monkeypatch):
    candidate_id = "AF-CAND-THRU-0002"
    _seed_throughput_candidate(settings, candidate_id=candidate_id)
    write_json(
        settings.paths().reports_dir / candidate_id / "rule_spec.json",
        {"candidate_id": candidate_id, "family": "throughput_research"},
    )
    _seed_parent_campaign(
        settings,
        family="throughput_research",
        parent_campaign_id="campaign-throughput-easpec-parent",
        candidate_id=candidate_id,
        step_type="generate_ea_spec",
    )

    def _fake_generate_ea_spec(settings, *, candidate_id):
        report_dir = settings.paths().reports_dir / candidate_id
        return EASpecGenerationReport(
            candidate_id=candidate_id,
            readiness_status="ea_spec_complete",
            economic_plausibility_passed=False,
            plausibility_findings=["modeled edge horizon is too small relative to recent spread conditions"],
            artifact_paths={
                "rule_spec_path": str(report_dir / "rule_spec.json"),
                "ea_spec_path": str(report_dir / "ea_spec.json"),
            },
        )

    monkeypatch.setattr("agentic_forex.campaigns.next_step.build_ea_spec_report", _fake_generate_ea_spec)

    report = run_next_step(
        settings,
        family="throughput_research",
        parent_campaign_id="campaign-throughput-easpec-parent",
        campaign_id="campaign-throughput-easpec-child",
        allowed_step_types=["generate_ea_spec"],
    )

    assert report.selected_step_type == "generate_ea_spec"
    assert report.stop_reason == "minimum_economic_plausibility_rejected"
    assert report.ea_spec_generation_reports[0].economic_plausibility_passed is False
    assert report.next_recommendations[0].step_type == "triage_reviewable_candidate"
    assert report.auto_continue_allowed is True


def test_run_next_step_compile_and_smoke_write_classified_failures(settings, monkeypatch):
    candidate_id = "AF-CAND-THRU-0003"
    _seed_throughput_candidate(settings, candidate_id=candidate_id)
    report_dir = settings.paths().reports_dir / candidate_id
    write_json(report_dir / "strategy_spec.json", {"candidate_id": candidate_id, "family": "throughput_research"})
    write_json(report_dir / "ea_spec.json", {"candidate_id": candidate_id, "family": "throughput_research"})
    _seed_parent_campaign(
        settings,
        family="throughput_research",
        parent_campaign_id="campaign-throughput-compile-parent",
        candidate_id=candidate_id,
        step_type="compile_ea_candidate",
    )

    def _fake_compile(settings, *, candidate_id):
        report_dir = settings.paths().reports_dir / candidate_id
        return CandidateCompileReport(
            candidate_id=candidate_id,
            readiness_status="ea_spec_complete",
            compile_status="failed",
            failure_classification="parameter_schema_failure",
            artifact_paths={"compile_report_path": str(report_dir / "compile_report.json")},
        )

    monkeypatch.setattr("agentic_forex.campaigns.next_step.build_compile_report", _fake_compile)

    compile_report = run_next_step(
        settings,
        family="throughput_research",
        parent_campaign_id="campaign-throughput-compile-parent",
        campaign_id="campaign-throughput-compile-child",
        allowed_step_types=["compile_ea_candidate"],
    )

    assert compile_report.compile_reports[0].failure_classification == "parameter_schema_failure"
    assert compile_report.next_recommendations[0].step_type == "triage_reviewable_candidate"

    write_json(report_dir / "compile_report.json", {"candidate_id": candidate_id, "compile_status": "passed"})
    _seed_parent_campaign(
        settings,
        family="throughput_research",
        parent_campaign_id="campaign-throughput-smoke-parent",
        candidate_id=candidate_id,
        step_type="run_mt5_backtest_smoke",
    )

    def _fake_smoke(settings, *, candidate_id):
        report_dir = settings.paths().reports_dir / candidate_id
        return MT5SmokeBacktestReport(
            candidate_id=candidate_id,
            readiness_status="ea_compiled",
            smoke_status="failed",
            failure_classification="no_trades_generated",
            trade_count=0,
            artifact_paths={"mt5_smoke_report_path": str(report_dir / "mt5_smoke_report.json")},
        )

    monkeypatch.setattr("agentic_forex.campaigns.next_step.build_mt5_smoke_report", _fake_smoke)

    smoke_report = run_next_step(
        settings,
        family="throughput_research",
        parent_campaign_id="campaign-throughput-smoke-parent",
        campaign_id="campaign-throughput-smoke-child",
        allowed_step_types=["run_mt5_backtest_smoke"],
    )

    assert smoke_report.mt5_smoke_reports[0].failure_classification == "no_trades_generated"
    assert smoke_report.next_recommendations[0].step_type == "triage_reviewable_candidate"


def test_run_next_step_triage_reviewable_candidate_moves_lane_and_stays_silent(settings, monkeypatch):
    candidate_id = "AF-CAND-THRU-0004"
    _seed_throughput_candidate(settings, candidate_id=candidate_id)
    report_dir = settings.paths().reports_dir / candidate_id
    write_json(report_dir / "compile_report.json", {"candidate_id": candidate_id, "compile_status": "passed"})
    _seed_parent_campaign(
        settings,
        family="throughput_research",
        parent_campaign_id="campaign-throughput-triage-parent",
        candidate_id=candidate_id,
        step_type="triage_reviewable_candidate",
    )

    def _fake_triage_candidate(
        settings,
        *,
        candidate_id,
        compile_retries_used,
        compile_retry_cap,
        smoke_retries_used,
        smoke_retry_cap,
        ea_spec_rewrites_used,
        ea_spec_rewrite_cap,
    ):
        report_dir = settings.paths().reports_dir / candidate_id
        return CandidateTriageReport(
            candidate_id=candidate_id,
            readiness_status="reviewable_candidate",
            classification="send_to_research_lane",
            rationale="Smoke artifacts are complete and the candidate is ready for research-lane admission.",
            compile_status="passed",
            smoke_status="passed",
            artifact_paths={"triage_report_path": str(report_dir / "triage_report.json")},
        )

    monkeypatch.setattr("agentic_forex.campaigns.next_step.triage_candidate", _fake_triage_candidate)

    report = run_next_step(
        settings,
        family="throughput_research",
        parent_campaign_id="campaign-throughput-triage-parent",
        campaign_id="campaign-throughput-triage-child",
        allowed_step_types=["triage_reviewable_candidate"],
    )

    assert report.selected_step_type == "triage_reviewable_candidate"
    assert report.triage_reports[0].classification == "send_to_research_lane"
    assert report.auto_continue_allowed is False
    assert report.transition_status == "move_to_next_lane"
    assert report.notification_required is False


def test_build_smoke_report_classifies_zero_trade_html_as_no_trades_generated(settings, tmp_path):
    candidate_id = "AF-CAND-THRU-REPORT"
    report_dir = settings.paths().reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    tester_report = tmp_path / "tester_report.htm"
    tester_report.write_text(
        "<html><td colspan=\"3\">Total Trades:</td><td nowrap><b>0</b></td></html>",
        encoding="utf-16",
    )
    launch_status_path = tmp_path / "launch_status.json"
    write_json(launch_status_path, {"candidate_id": candidate_id})

    report = _build_smoke_report(
        settings,
        candidate_id=candidate_id,
        run_result=MT5RunResult(
            candidate_id=candidate_id,
            run_id="throughput-smoke-test",
            launch_status="completed",
            terminal_return_code=0,
            timed_out=False,
            terminal_path=None,
            terminal_data_path=None,
            tester_report_path=tester_report,
            audit_csv_path=None,
            launch_status_path=launch_status_path,
        ),
        report_path=report_dir / "mt5_smoke_report.json",
    )

    assert report.failure_classification == "no_trades_generated"
    assert report.trade_count == 0


def test_run_mt5_backtest_smoke_renders_run_specific_audit_path(settings, monkeypatch):
    candidate_id = "AF-CAND-THRU-SMOKE-RUN"
    report_dir = settings.paths().reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        report_dir / "compile_report.json",
        {
            "candidate_id": candidate_id,
            "readiness_status": "ea_compiled",
            "compile_status": "passed",
            "failure_classification": None,
            "artifact_paths": {
                "compiled_ex5_path": str(report_dir / "throughput" / "CandidateEA.ex5"),
                "deployed_source_path": str(report_dir / "throughput" / "CandidateEA.mq5"),
            },
        },
    )

    terminal_path = settings.project_root / "terminal64.exe"
    terminal_path.write_text("", encoding="utf-8")
    terminal_data_path = settings.paths().state_dir / "mt5_automation_runtime_test"
    terminal_data_path.mkdir(parents=True, exist_ok=True)

    captured: dict[str, str] = {}

    monkeypatch.setattr(
        "agentic_forex.campaigns.throughput.ensure_strategy_spec",
        lambda settings, *, candidate_id: SimpleNamespace(
            candidate_id=candidate_id,
            execution_granularity="M1",
            instrument="EUR_USD",
            model_dump_json=lambda: "{}",
        ),
    )
    monkeypatch.setattr(
        "agentic_forex.campaigns.throughput.render_candidate_ea",
        lambda spec, *, audit_relative_path, packet_run_id, broker_timezone="UTC": captured.update(
            {
                "audit_relative_path": audit_relative_path,
                "packet_run_id": packet_run_id,
                "broker_timezone": broker_timezone,
            }
        )
        or "// source",
    )
    monkeypatch.setattr("agentic_forex.campaigns.throughput._resolve_terminal_path", lambda settings: terminal_path)
    monkeypatch.setattr(
        "agentic_forex.campaigns.throughput._resolve_terminal_data_path",
        lambda settings, terminal_path: terminal_data_path,
    )
    monkeypatch.setattr(
        "agentic_forex.campaigns.throughput._prepare_automated_terminal_runtime",
        lambda settings, terminal_path, terminal_data_path: (terminal_path, terminal_data_path, None),
    )
    monkeypatch.setattr(
        "agentic_forex.campaigns.throughput._resolve_metaeditor_path",
        lambda terminal_path: terminal_path.parent / "MetaEditor64.exe",
    )

    def _fake_deploy_and_compile_ea(*, candidate_id, packet_source_path, compile_target_relative_path, terminal_data_path, metaeditor_path, packet_dir):
        staged_source_path = terminal_data_path / compile_target_relative_path
        staged_source_path.parent.mkdir(parents=True, exist_ok=True)
        staged_source_path.write_text(packet_source_path.read_text(encoding="utf-8"), encoding="utf-8")
        staged_ex5_path = staged_source_path.with_suffix(".ex5")
        staged_ex5_path.write_text("binary", encoding="utf-8")
        compile_log_path = packet_dir / "compile.log"
        compile_log_path.write_text("ok", encoding="utf-8")
        return staged_source_path, staged_ex5_path, compile_log_path

    monkeypatch.setattr("agentic_forex.campaigns.throughput._deploy_and_compile_ea", _fake_deploy_and_compile_ea)
    monkeypatch.setattr(
        "agentic_forex.campaigns.throughput._tester_ini",
        lambda candidate_id, run_spec, settings, spec, expected_signal_frame: "[Tester]",
    )
    monkeypatch.setattr(
        "agentic_forex.campaigns.throughput._smoke_expected_signal_frame",
        lambda settings, spec: None,
    )
    monkeypatch.setattr(
        "agentic_forex.campaigns.throughput._resolve_audit_output_path",
        lambda settings, terminal_data_path, audit_relative_path: terminal_data_path / audit_relative_path.replace("\\", "/"),
    )
    monkeypatch.setattr(
        "agentic_forex.campaigns.throughput._launch_mt5_tester",
        lambda run_spec, settings: MT5RunResult(
            candidate_id=run_spec.candidate_id,
            run_id=run_spec.run_id,
            launch_status="completed",
            terminal_return_code=0,
            timed_out=False,
            terminal_path=run_spec.terminal_path,
            terminal_data_path=terminal_data_path,
            tester_report_path=None,
            audit_csv_path=None,
            launch_status_path=run_spec.run_dir / "launch_status.json",
        ),
    )

    run_mt5_backtest_smoke(settings, candidate_id=candidate_id)

    assert captured["packet_run_id"].startswith("throughput-smoke-")
    assert captured["packet_run_id"] in captured["audit_relative_path"]


def test_logic_manifest_payload_normalizes_run_specific_mt5_instrumentation(settings):
    candidate_id = "AF-CAND-THRU-LOGIC"
    _seed_throughput_candidate(settings, candidate_id=candidate_id)
    spec_payload = compile_strategy_spec_tool(
        payload=read_json(settings.paths().reports_dir / candidate_id / "candidate.json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    report_dir = settings.paths().reports_dir / candidate_id
    write_json(report_dir / "strategy_spec.json", spec_payload)

    from agentic_forex.workflows.contracts import StrategySpec

    spec = StrategySpec.model_validate(spec_payload)
    expected_signal_frame = _smoke_expected_signal_frame(settings, spec)
    first_payload = build_logic_manifest_payload(
        spec=spec,
        rendered_source=render_candidate_ea(
            spec,
            audit_relative_path="AgenticForex\\Audit\\first.csv",
            packet_run_id="first-run",
        ),
        expected_signal_frame=expected_signal_frame,
        settings=settings,
        source_artifact_paths={"strategy_spec_path": report_dir / "strategy_spec.json"},
    )
    second_payload = build_logic_manifest_payload(
        spec=spec,
        rendered_source=render_candidate_ea(
            spec,
            audit_relative_path="AgenticForex\\Audit\\second.csv",
            packet_run_id="second-run",
        ),
        expected_signal_frame=expected_signal_frame,
        settings=settings,
        source_artifact_paths={"strategy_spec_path": report_dir / "strategy_spec.json"},
    )

    assert first_payload["logic_manifest_hash"] == second_payload["logic_manifest_hash"]


def test_run_program_loop_rejects_nonorthogonal_throughput_lanes(settings):
    settings.program.approved_lanes = [
        ProgramLanePolicy(
            lane_id="throughput-lane-a",
            family="throughput_research",
            hypothesis_class="session_breakout",
            seed_candidate_id="AF-CAND-THRU-A",
            queue_kind="throughput",
            throughput_target_count=10,
            compile_budget=6,
            smoke_budget=5,
            orthogonality_metadata=OrthogonalityMetadata(
                market_hypothesis="intraday_breakout",
                trigger_family="range_expansion",
                holding_profile="intraday",
                session_profile="europe",
                regime_dependency="high_vol_trend",
            ),
        ),
        ProgramLanePolicy(
            lane_id="throughput-lane-b",
            family="throughput_research",
            hypothesis_class="session_breakout_adjacent",
            seed_candidate_id="AF-CAND-THRU-B",
            queue_kind="throughput",
            throughput_target_count=10,
            compile_budget=6,
            smoke_budget=5,
            orthogonality_metadata=OrthogonalityMetadata(
                market_hypothesis="intraday_breakout",
                trigger_family="range_expansion",
                holding_profile="intraday",
                session_profile="overlap",
                regime_dependency="high_vol_trend",
            ),
        ),
    ]

    report = run_program_loop(
        settings,
        family="throughput_research",
        program_id="program-throughput-orthogonality",
        max_lanes=2,
    )

    assert report.executed_lanes == 0
    assert report.stop_class == "policy_decision"
    assert "invalid_throughput_orthogonality" in report.stop_reason


def _seed_throughput_candidate(settings, *, candidate_id: str) -> None:
    report_dir = settings.paths().reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        report_dir / "candidate.json",
        {
            "candidate_id": candidate_id,
            "family": "throughput_research",
            "title": f"Throughput Candidate {candidate_id}",
            "thesis": "Bounded throughput candidate.",
            "source_citations": ["SRC-001"],
            "strategy_hypothesis": "Test deterministic candidate.",
            "market_context": {
                "session_focus": "europe_open",
                "volatility_preference": "moderate",
                "directional_bias": "both",
                "execution_notes": ["throughput test"],
                "allowed_hours_utc": [7, 8, 9, 10],
            },
            "setup_summary": "Test setup.",
            "entry_summary": "Enter on deterministic trigger.",
            "exit_summary": "Exit by target, stop, or timeout.",
            "risk_summary": "Fixed stop and target.",
            "entry_style": "trend_pullback",
            "holding_bars": 18,
            "signal_threshold": 0.8,
            "stop_loss_pips": 6.0,
            "take_profit_pips": 10.0,
            "notes": [],
            "quality_flags": [],
            "contradiction_summary": [],
            "critic_notes": [],
        },
    )


def _seed_parent_campaign(
    settings,
    *,
    family: str,
    parent_campaign_id: str,
    candidate_id: str,
    step_type: str,
) -> None:
    parent_dir = settings.paths().campaigns_dir / parent_campaign_id
    parent_dir.mkdir(parents=True, exist_ok=True)
    parent_spec = CampaignSpec(
        campaign_id=parent_campaign_id,
        family=family,
        baseline_candidate_id=candidate_id,
        target_candidate_ids=[candidate_id],
        queue_kind="throughput",
        step_type=step_type,
        allowed_step_types=[step_type],
        throughput_target_count=10,
        compile_budget=6,
        smoke_budget=5,
    )
    parent_state = CampaignState(
        campaign_id=parent_campaign_id,
        family=family,
        status="completed",
        baseline_candidate_id=candidate_id,
        parent_campaign_id=None,
        current_step_type=step_type,
        active_candidate_ids=[candidate_id],
        state_path=parent_dir / "state.json",
        updated_utc="2026-03-22T18:00:00Z",
    )
    write_json(parent_dir / "spec.json", parent_spec.model_dump(mode="json"))
    write_json(parent_state.state_path, parent_state.model_dump(mode="json"))
    write_json(
        parent_dir / "next_recommendations.json",
        [
            {
                "step_type": step_type,
                "candidate_id": candidate_id,
                "rationale": f"Continue throughput with {step_type}.",
                "binding": True,
                "evidence_status": "supported",
            }
        ],
    )
