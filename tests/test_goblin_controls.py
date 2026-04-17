from __future__ import annotations

import json

import pytest

from agentic_forex.approval.models import ApprovalRecord
from agentic_forex.approval.service import record_approval
from agentic_forex.goblin.controls import (
    build_deployment_bundle,
    close_incident_record,
    default_approval_boundaries,
    enforce_candidate_strategy_governance,
    enforce_strategy_governance,
    open_incident_record,
    write_candidate_scorecard,
    write_experiment_accounting_ledger,
    write_mt5_certification_report,
    write_promotion_decision_packet,
    write_strategy_methodology_audit,
    write_strategy_rationale_card,
)
from agentic_forex.goblin.models import MT5CertificationReport, ValidationCertification
from agentic_forex.governance.trial_ledger import append_trial_entry


def test_default_approval_boundaries_follow_settings(settings):
    boundaries = default_approval_boundaries(settings)

    stages = {item.stage: item.mode for item in boundaries}
    assert stages["mt5_packet"] == "machine_allowed"
    assert stages["human_review"] == "human_required"


def test_open_and_close_incident_record(settings):
    record = open_incident_record(
        settings,
        candidate_id="AF-CAND-0263",
        title="Validation mismatch",
        blockers=["parity_gap"],
    )

    assert record.report_path is not None
    assert record.report_path.exists()

    closure = close_incident_record(
        settings,
        candidate_id="AF-CAND-0263",
        incident_id=record.incident_id,
        resolution_summary="Resolved after replay verification.",
        approved_by="tester",
        root_cause_note="Parity gap attributed to tick filter; resolved.",
    )

    assert closure.report_path is not None
    assert closure.report_path.exists()


def test_build_deployment_bundle_hashes_available_artifacts(settings):
    report_dir = settings.paths().reports_dir / "AF-CAND-0263"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "review_packet.json").write_text('{"candidate_id":"AF-CAND-0263"}', encoding="utf-8")
    record_approval(
        ApprovalRecord(
            candidate_id="AF-CAND-0263",
            stage="human_review",
            decision="approve",
            approver="qa",
            rationale="ready",
            source="human",
        ),
        settings,
    )

    bundle = build_deployment_bundle(settings, candidate_id="AF-CAND-0263")

    assert bundle.validation_packet_hash is not None
    assert bundle.approval_refs
    output_path = settings.paths().goblin_deployment_bundles_dir / "AF-CAND-0263" / f"{bundle.bundle_id}.json"
    assert output_path.exists()


def test_build_deployment_bundle_uses_packet_and_certified_run_hashes(settings):
    candidate_id = "AF-CAND-0263"
    packet_dir = settings.paths().approvals_dir / "mt5_packets" / candidate_id
    packet_dir.mkdir(parents=True, exist_ok=True)
    run_id = "mt5run-20260414T002341Z"
    run_dir = settings.paths().mt5_runs_dir / candidate_id / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ex5_path = settings.paths().root / "data" / "state" / "mt5_automation_runtime" / "MQL5" / "Experts" / "AgenticForex" / f"{candidate_id}.ex5"
    ex5_path.parent.mkdir(parents=True, exist_ok=True)
    ex5_path.write_bytes(b"compiled-ex5")
    set_path = run_dir / f"{candidate_id}-{run_id}.set"
    set_path.write_text("input=true\n", encoding="utf-8")
    (packet_dir / "packet.json").write_text(
        json.dumps(
            {
                "candidate_id": candidate_id,
                "compiled_ex5_path": str(ex5_path),
                "run_spec_path": str(run_dir / "run_spec.json"),
            }
        ),
        encoding="utf-8",
    )
    cert_dir = settings.paths().goblin_mt5_certification_reports_dir / candidate_id / run_id
    cert_dir.mkdir(parents=True, exist_ok=True)
    (cert_dir / "mt5_certification_report.json").write_text(
        json.dumps(
            {
                "candidate_id": candidate_id,
                "run_id": run_id,
                "validation_status": "passed",
                "certification": {"status": "deployment_grade"},
            }
        ),
        encoding="utf-8",
    )
    record_approval(
        ApprovalRecord(
            candidate_id=candidate_id,
            stage="human_review",
            decision="approve",
            approver="qa",
            rationale="ready",
            source="human",
        ),
        settings,
    )

    bundle = build_deployment_bundle(settings, candidate_id=candidate_id)

    assert bundle.ea_build_hash is not None
    assert bundle.inputs_hash is not None


def test_write_mt5_certification_report(settings):
    report = write_mt5_certification_report(
        settings,
        report=MT5CertificationReport(
            candidate_id="AF-CAND-0263",
            run_id="mt5run-test",
            tester_mode="1 minute OHLC",
            delay_model="configured_fill_delay_ms:250",
            tick_provenance="generated_ticks",
            baseline_reproduction_passed=True,
            certification=ValidationCertification(
                artifact_id="cert-1",
                status="deployment_grade",
                basis="mt5_parity_validation",
            ),
        ),
    )

    assert report.report_path is not None
    assert report.report_path.exists()
    payload = json.loads(report.report_path.read_text(encoding="utf-8"))
    assert payload["candidate_id"] == "AF-CAND-0263"
    assert payload["certification"]["status"] == "deployment_grade"


def test_write_rationale_card_and_scorecard(settings):
    card = write_strategy_rationale_card(
        settings,
        family="overlap_resolution_bridge_research",
        candidate_id="AF-CAND-0263",
        thesis="Overlap dislocations mean revert after failed continuation.",
        invalidation_conditions=["sustained trend day continuation"],
        hostile_regimes=["macro release shock"],
        execution_assumptions=["bounded spread during entry"],
    )
    scorecard = write_candidate_scorecard(
        settings,
        candidate_id="AF-CAND-0263",
        alpha_quality=0.62,
        robustness=0.58,
        executable_parity=0.71,
        operational_reliability=0.65,
        deployment_fit=0.54,
        notes=["requires further replay verification"],
    )

    assert card.report_path is not None
    assert card.report_path.exists()
    assert scorecard.report_path is not None
    assert scorecard.report_path.exists()
    payload = json.loads(scorecard.report_path.read_text(encoding="utf-8"))
    assert payload["candidate_id"] == "AF-CAND-0263"


def test_write_experiment_accounting_ledger_tracks_caps_and_suspension(settings):
    write_strategy_rationale_card(
        settings,
        family="europe_open_impulse_retest_research",
        thesis="Opening impulse retrace has bounded continuation probability.",
    )
    append_trial_entry(
        settings,
        candidate_id="AF-CAND-9001",
        family="europe_open_impulse_retest_research",
        stage="mutate_one_candidate",
        parent_candidate_ids=["AF-CAND-9000"],
        failure_code="throughput_failure",
    )
    append_trial_entry(
        settings,
        candidate_id="AF-CAND-9002",
        family="europe_open_impulse_retest_research",
        stage="mutate_one_candidate",
        parent_candidate_ids=["AF-CAND-9001"],
        failure_code="compile_failure",
    )

    ledger = write_experiment_accounting_ledger(
        settings,
        family="europe_open_impulse_retest_research",
        budget_caps={
            "max_trials_per_family": 10,
            "max_mutation_depth": 1,
            "max_failed_refinements": 1,
        },
    )

    assert ledger.report_path is not None
    assert ledger.report_path.exists()
    assert ledger.suspended is True
    assert ledger.failed_refinement_count == 2
    assert ledger.max_observed_mutation_depth >= 2
    assert ledger.strategy_rationale_card_path is not None


def test_write_strategy_methodology_audit_scores_family_rationale(settings):
    write_strategy_rationale_card(
        settings,
        family="europe_open_continuation_research",
        thesis="Europe open continuation has a bounded extension profile that is only tradable under controlled spread and volatility regimes.",
        invalidation_conditions=["first-hour impulse fails and reverses through opening range mean"],
        hostile_regimes=["macro release shock with spread expansion"],
        execution_assumptions=["entry spread remains below 2.0 pips"],
        non_deployable_conditions=["broker spread exceeds deterministic envelope"],
    )
    ledger = write_experiment_accounting_ledger(settings, family="europe_open_continuation_research")

    audit = write_strategy_methodology_audit(settings, family="europe_open_continuation_research", ledger=ledger)

    assert audit.report_path is not None
    assert audit.report_path.exists()
    assert audit.passed is True
    assert audit.weighted_score >= audit.minimum_required_score
    assert not audit.missing_requirements


def test_enforce_strategy_governance_blocks_on_methodology_floor(settings):
    write_strategy_rationale_card(
        settings,
        family="weak_methodology_family",
        thesis="too short",
    )

    with pytest.raises(ValueError, match="methodology_rubric_below_floor"):
        enforce_strategy_governance(
            settings,
            family="weak_methodology_family",
            minimum_methodology_score=0.85,
        )


def test_enforce_candidate_strategy_governance_requires_lineage(settings):
    candidate_id = "AF-CAND-NO-LINEAGE"
    report_dir = settings.paths().reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "strategy_spec.json").write_text(
        json.dumps({"candidate_id": candidate_id, "family": "scalping", "entry_style": "session_breakout"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing_experiment_lineage"):
        enforce_candidate_strategy_governance(settings, candidate_id=candidate_id)


def test_write_promotion_packet_attaches_search_bias_governance_evidence(settings):
    candidate_id = "AF-CAND-PROMO-0001"
    report_dir = settings.paths().reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "strategy_spec.json").write_text(
        json.dumps(
            {
                "candidate_id": candidate_id,
                "family": "scalping",
                "entry_style": "session_breakout",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    append_trial_entry(
        settings,
        candidate_id=candidate_id,
        family="scalping",
        stage="backtested",
    )

    packet = write_promotion_decision_packet(
        settings,
        candidate_id=candidate_id,
        decision_status="pending",
        deployment_ladder_state="observed_demo",
    )

    assert packet.report_path is not None
    assert packet.report_path.exists()
    assert packet.experiment_accounting_ledger_path is not None
    assert packet.strategy_methodology_audit_path is not None
    assert packet.search_bias_summary
    assert packet.statistical_policy_keys
    assert packet.deployment_ladder_state == "observed_demo"


def test_write_promotion_packet_requires_statistical_policy_key_citations(settings):
    candidate_id = "AF-CAND-PROMO-0002"
    report_dir = settings.paths().reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "strategy_spec.json").write_text(
        json.dumps({"candidate_id": candidate_id, "family": "scalping"}, indent=2),
        encoding="utf-8",
    )
    append_trial_entry(settings, candidate_id=candidate_id, family="scalping", stage="backtested")

    with pytest.raises(ValueError, match="promotion_packet_missing_statistical_policy_keys"):
        write_promotion_decision_packet(
            settings,
            candidate_id=candidate_id,
            decision_status="pending",
            deployment_ladder_state="observed_demo",
            statistical_policy_keys=["validation.parity_min_match_rate"],
        )


def test_write_promotion_packet_blocks_approval_below_observed_demo(settings):
    candidate_id = "AF-CAND-PROMO-0003"
    report_dir = settings.paths().reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "strategy_spec.json").write_text(
        json.dumps({"candidate_id": candidate_id, "family": "scalping"}, indent=2),
        encoding="utf-8",
    )
    append_trial_entry(settings, candidate_id=candidate_id, family="scalping", stage="backtested")

    with pytest.raises(ValueError, match="promotion_blocked_below_observed_demo"):
        write_promotion_decision_packet(
            settings,
            candidate_id=candidate_id,
            decision_status="approved",
            deployment_ladder_state="limited_demo",
        )


def test_write_promotion_packet_requires_bundle_for_material_deployment_fit_delta(settings):
    candidate_id = "AF-CAND-PROMO-0004"
    report_dir = settings.paths().reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "strategy_spec.json").write_text(
        json.dumps({"candidate_id": candidate_id, "family": "scalping"}, indent=2),
        encoding="utf-8",
    )
    append_trial_entry(settings, candidate_id=candidate_id, family="scalping", stage="backtested")

    with pytest.raises(ValueError, match="deployment_fit_delta_requires_new_bundle"):
        write_promotion_decision_packet(
            settings,
            candidate_id=candidate_id,
            decision_status="pending",
            deployment_ladder_state="observed_demo",
            deployment_fit_delta=0.08,
        )

    packet = write_promotion_decision_packet(
        settings,
        candidate_id=candidate_id,
        decision_status="pending",
        deployment_ladder_state="observed_demo",
        deployment_fit_delta=0.08,
        deployment_bundle_id="AF-CAND-PROMO-0004-bundle-1",
    )
    assert packet.deployment_fit_change_requires_new_bundle is True
    assert packet.deployment_bundle_id == "AF-CAND-PROMO-0004-bundle-1"
