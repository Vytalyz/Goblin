from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from pydantic import ValidationError

from agentic_forex.approval.service import is_stage_approved
from agentic_forex.campaigns.controller import load_or_create_campaign_state
from agentic_forex.campaigns.throughput import (
    compile_ea_candidate as build_compile_report,
    formalize_rule_candidate,
    generate_ea_spec as build_ea_spec_report,
    run_mt5_backtest_smoke as build_mt5_smoke_report,
    triage_candidate,
)
from agentic_forex.config import Settings
from agentic_forex.governance.control_plane import policy_snapshot_hash
from agentic_forex.forward.service import load_forward_stage_report, run_shadow_forward
from agentic_forex.governance.models import (
    CampaignSpec,
    CampaignState,
    CandidateCompileReport,
    CandidateDiagnosticReport,
    CandidateMutationReport,
    CandidateReevaluationReport,
    CandidateTriageReport,
    DataFeatureAuditReport,
    DataLabelAuditReport,
    DataRegimeAuditReport,
    DataRegimeSliceSummary,
    DiagnosticSliceReport,
    EASpecGenerationReport,
    HypothesisAuditCandidateSummary,
    HypothesisAuditReport,
    MT5SmokeBacktestReport,
    NextStepControllerReport,
    NextStepRecommendation,
    NextStepType,
    RuleFormalizationReport,
)
from agentic_forex.governance.provenance import (
    build_data_provenance,
    build_environment_snapshot,
    load_data_provenance,
    load_environment_snapshot,
)
from agentic_forex.governance.readiness import resolve_readiness_status
from agentic_forex.governance.trial_ledger import append_failure_record, append_trial_entry
from agentic_forex.goblin.controls import enforce_strategy_governance
from agentic_forex.llm import MockLLMClient
from agentic_forex.mt5.service import ParityPolicyError, load_latest_mt5_validation, run_mt5_parity
from agentic_forex.nodes import build_tool_registry
from agentic_forex.nodes.toolkit import default_execution_cost_fields
from agentic_forex.runtime import ReadPolicy, WorkflowEngine
from agentic_forex.utils.ids import next_candidate_id, next_campaign_id
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows import WorkflowRepository
from agentic_forex.workflows.contracts import CandidateDraft, FilterRule, ReviewPacket, StrategySpec


DEFAULT_ALLOWED_STEP_TYPES: list[NextStepType] = ["diagnose_existing_candidates"]
SUPPORTED_STEP_TYPES: set[NextStepType] = {
    "diagnose_existing_candidates",
    "mutate_one_candidate",
    "re_evaluate_one_candidate",
    "formalize_rule_candidate",
    "generate_ea_spec",
    "compile_ea_candidate",
    "run_mt5_backtest_smoke",
    "triage_reviewable_candidate",
    "hypothesis_audit",
    "data_regime_audit",
    "data_feature_audit",
    "data_label_audit",
    "run_parity",
    "run_forward",
}
SESSION_BUCKET_HOURS = {
    "asia": list(range(0, 7)),
    "europe": list(range(7, 13)),
    "overlap": list(range(13, 17)),
    "us_late": list(range(17, 24)),
}


@dataclass(slots=True)
class _NextStepDecision:
    step_type: NextStepType | None
    candidate_scope: list[str]
    rationale: str
    stop_reason: str | None = None
    recommendation: NextStepRecommendation | None = None


@dataclass(slots=True)
class _ContinuationDecision:
    continuation_status: str
    stop_class: str
    auto_continue_allowed: bool
    recommended_follow_on_step: NextStepType | None = None
    max_safe_follow_on_steps: int = 0


def run_next_step(
    settings: Settings,
    *,
    family: str = "scalping",
    parent_campaign_id: str | None = None,
    campaign_id: str | None = None,
    allowed_step_types: list[NextStepType] | None = None,
) -> NextStepControllerReport:
    enforce_strategy_governance(settings, family=family)
    parent_state = _load_latest_completed_campaign_state(settings, family=family, campaign_id=parent_campaign_id)
    parent_spec = _load_campaign_spec(parent_state.state_path.parent)
    allowed = list(dict.fromkeys(allowed_step_types or DEFAULT_ALLOWED_STEP_TYPES))
    binding_recommendations = _load_next_recommendations(parent_state.state_path.parent)
    decision = _select_next_step(
        settings,
        parent_spec=parent_spec,
        parent_state=parent_state,
        binding_recommendations=binding_recommendations,
        allowed_step_types=allowed,
    )
    child_spec = _build_child_campaign_spec(
        settings,
        parent_spec=parent_spec,
        parent_state=parent_state,
        campaign_id=campaign_id,
        allowed_step_types=allowed,
        decision=decision,
    )
    state = load_or_create_campaign_state(child_spec, settings)
    _inherit_child_state_counters(state, parent_state)
    state.parent_campaign_id = child_spec.parent_campaign_id
    state.current_step_type = child_spec.step_type
    state.status = "running"
    state.state_version += 1
    state.updated_utc = _utc_now()
    write_json(state.state_path, state.model_dump(mode="json"))

    report_path = state.state_path.parent / "next_step_report.json"
    recommendations_path = state.state_path.parent / "next_recommendations.json"
    try:
        if decision.step_type not in SUPPORTED_STEP_TYPES:
            report = NextStepControllerReport(
                campaign_id=child_spec.campaign_id,
                parent_campaign_id=child_spec.parent_campaign_id,
                selected_step_type=decision.step_type,
                step_reason=decision.rationale,
                status="stopped",
                stop_reason=decision.stop_reason or "no_supported_next_step",
                candidate_scope=decision.candidate_scope,
                report_path=report_path,
            )
            _apply_continuation_metadata(settings, report)
            write_json(report.report_path, report.model_dump(mode="json"))
            write_json(recommendations_path, [])
            state.status = "stopped"
            state.stop_reason = report.stop_reason
            state.last_report_path = report.report_path
            state.next_recommendations_path = recommendations_path
            return report

        if decision.step_type == "diagnose_existing_candidates":
            report = _run_diagnose_existing_candidates(
                settings,
                child_spec=child_spec,
                state=state,
                parent_spec=parent_spec,
                candidate_ids=decision.candidate_scope,
                step_reason=decision.rationale,
                report_path=report_path,
                recommendations_path=recommendations_path,
            )
            state.active_candidate_ids = list(decision.candidate_scope)
            state.iterations_run += len(decision.candidate_scope)
            state.trials_consumed += len(decision.candidate_scope)
        elif decision.step_type == "mutate_one_candidate":
            report = _run_mutate_one_candidate(
                settings,
                child_spec=child_spec,
                state=state,
                candidate_ids=decision.candidate_scope,
                recommendation=decision.recommendation,
                step_reason=decision.rationale,
                report_path=report_path,
                recommendations_path=recommendations_path,
            )
            state.active_candidate_ids = [item.mutated_candidate_id for item in report.mutation_reports]
            state.iterations_run += len(report.mutation_reports)
            state.trials_consumed += len(report.mutation_reports)
        elif decision.step_type == "formalize_rule_candidate":
            report = _run_formalize_rule_candidate(
                settings,
                child_spec=child_spec,
                state=state,
                candidate_ids=decision.candidate_scope,
                step_reason=decision.rationale,
                report_path=report_path,
                recommendations_path=recommendations_path,
            )
            state.active_candidate_ids = [item.candidate_id for item in report.rule_formalization_reports]
            state.iterations_run += len(report.rule_formalization_reports)
            state.trials_consumed += len(report.rule_formalization_reports)
        elif decision.step_type == "generate_ea_spec":
            report = _run_generate_ea_spec(
                settings,
                child_spec=child_spec,
                state=state,
                candidate_ids=decision.candidate_scope,
                step_reason=decision.rationale,
                report_path=report_path,
                recommendations_path=recommendations_path,
            )
            state.active_candidate_ids = [item.candidate_id for item in report.ea_spec_generation_reports]
            state.iterations_run += len(report.ea_spec_generation_reports)
            state.trials_consumed += len(report.ea_spec_generation_reports)
        elif decision.step_type == "compile_ea_candidate":
            report = _run_compile_ea_candidate(
                settings,
                child_spec=child_spec,
                state=state,
                candidate_ids=decision.candidate_scope,
                step_reason=decision.rationale,
                report_path=report_path,
                recommendations_path=recommendations_path,
            )
            state.active_candidate_ids = [item.candidate_id for item in report.compile_reports]
            state.iterations_run += len(report.compile_reports)
            state.trials_consumed += len(report.compile_reports)
        elif decision.step_type == "run_mt5_backtest_smoke":
            report = _run_mt5_backtest_smoke(
                settings,
                child_spec=child_spec,
                state=state,
                candidate_ids=decision.candidate_scope,
                step_reason=decision.rationale,
                report_path=report_path,
                recommendations_path=recommendations_path,
            )
            state.active_candidate_ids = [item.candidate_id for item in report.mt5_smoke_reports]
            state.iterations_run += len(report.mt5_smoke_reports)
            state.trials_consumed += len(report.mt5_smoke_reports)
        elif decision.step_type == "triage_reviewable_candidate":
            report = _run_triage_reviewable_candidate(
                settings,
                child_spec=child_spec,
                state=state,
                candidate_ids=decision.candidate_scope,
                step_reason=decision.rationale,
                report_path=report_path,
                recommendations_path=recommendations_path,
            )
            state.active_candidate_ids = [item.candidate_id for item in report.triage_reports]
            state.iterations_run += len(report.triage_reports)
            state.trials_consumed += len(report.triage_reports)
        elif decision.step_type == "re_evaluate_one_candidate":
            report = _run_re_evaluate_one_candidate(
                settings,
                child_spec=child_spec,
                state=state,
                candidate_ids=decision.candidate_scope,
                recommendation=decision.recommendation,
                step_reason=decision.rationale,
                report_path=report_path,
                recommendations_path=recommendations_path,
            )
            state.active_candidate_ids = [item.candidate_id for item in report.reevaluation_reports]
            state.iterations_run += len(report.reevaluation_reports)
            state.trials_consumed += len(report.reevaluation_reports)
            for recommendation in report.next_recommendations:
                if recommendation.binding and recommendation.step_type == "run_parity" and recommendation.candidate_id:
                    if recommendation.candidate_id not in state.promoted_candidate_ids:
                        state.promoted_candidate_ids.append(recommendation.candidate_id)
        elif decision.step_type == "hypothesis_audit":
            report = _run_hypothesis_audit(
                settings,
                child_spec=child_spec,
                state=state,
                parent_spec=parent_spec,
                candidate_ids=decision.candidate_scope,
                step_reason=decision.rationale,
                report_path=report_path,
                recommendations_path=recommendations_path,
            )
        elif decision.step_type == "data_regime_audit":
            report = _run_data_regime_audit(
                settings,
                child_spec=child_spec,
                state=state,
                parent_spec=parent_spec,
                candidate_ids=decision.candidate_scope,
                step_reason=decision.rationale,
                report_path=report_path,
                recommendations_path=recommendations_path,
            )
        elif decision.step_type == "data_feature_audit":
            report = _run_data_feature_audit(
                settings,
                child_spec=child_spec,
                state=state,
                parent_spec=parent_spec,
                candidate_ids=decision.candidate_scope,
                step_reason=decision.rationale,
                report_path=report_path,
                recommendations_path=recommendations_path,
            )
        elif decision.step_type == "data_label_audit":
            report = _run_data_label_audit(
                settings,
                child_spec=child_spec,
                state=state,
                parent_spec=parent_spec,
                candidate_ids=decision.candidate_scope,
                step_reason=decision.rationale,
                report_path=report_path,
                recommendations_path=recommendations_path,
            )
        elif decision.step_type == "run_parity":
            report = _run_parity_step(
                settings,
                child_spec=child_spec,
                state=state,
                candidate_ids=decision.candidate_scope,
                recommendation=decision.recommendation,
                step_reason=decision.rationale,
                report_path=report_path,
                recommendations_path=recommendations_path,
            )
        else:
            report = _run_forward_step(
                settings,
                child_spec=child_spec,
                state=state,
                candidate_ids=decision.candidate_scope,
                recommendation=decision.recommendation,
                step_reason=decision.rationale,
                report_path=report_path,
                recommendations_path=recommendations_path,
            )

        _apply_continuation_metadata(settings, report)
        write_json(report.report_path, report.model_dump(mode="json"))
        write_json(recommendations_path, [item.model_dump(mode="json") for item in report.next_recommendations])
        state.status = report.status
        state.stop_reason = report.stop_reason
        state.last_report_path = report.report_path
        state.next_recommendations_path = recommendations_path
        return report
    finally:
        state.state_version += 1
        state.updated_utc = _utc_now()
        write_json(state.state_path, state.model_dump(mode="json"))


def _run_diagnose_existing_candidates(
    settings: Settings,
    *,
    child_spec: CampaignSpec,
    state: CampaignState,
    parent_spec: CampaignSpec,
    candidate_ids: list[str],
    step_reason: str,
    report_path: Path,
    recommendations_path: Path,
) -> NextStepControllerReport:
    qa_report = read_json(
        settings.paths().market_quality_reports_dir
        / f"{settings.data.instrument.lower()}_{settings.data.base_granularity.lower()}.json"
    )
    market_path = Path(qa_report["parquet_path"])
    market_frame = pd.read_parquet(market_path)[["timestamp_utc", "spread_pips"]]
    market_frame["timestamp_utc"] = pd.to_datetime(market_frame["timestamp_utc"], utc=True)
    anomaly_threshold = float(qa_report.get("spread_anomaly_threshold_pips", 0.0))
    market_frame["is_spread_anomaly"] = market_frame["spread_pips"] >= anomaly_threshold

    candidate_reports = [
        _diagnose_candidate(
            settings,
            candidate_id=candidate_id,
            market_frame=market_frame,
            anomaly_threshold=anomaly_threshold,
        )
        for candidate_id in candidate_ids
    ]
    next_recommendations = _build_next_recommendations(
        settings,
        candidate_reports=candidate_reports,
        candidate_scope=candidate_ids,
    )
    stop_reason = (
        "diagnosis_completed_with_supported_recommendation"
        if next_recommendations
        else "diagnosis_ambiguous_no_mutation_justified"
    )
    report = NextStepControllerReport(
        campaign_id=child_spec.campaign_id,
        parent_campaign_id=child_spec.parent_campaign_id,
        selected_step_type="diagnose_existing_candidates",
        step_reason=step_reason,
        status="completed",
        stop_reason=stop_reason,
        candidate_scope=candidate_ids,
        candidate_reports=candidate_reports,
        next_recommendations=next_recommendations,
        report_path=report_path,
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    write_json(recommendations_path, [item.model_dump(mode="json") for item in next_recommendations])

    for candidate_report in candidate_reports:
        append_trial_entry(
            settings,
            candidate_id=candidate_report.candidate_id,
            family=child_spec.family,
            stage="diagnose_existing_candidates",
            campaign_id=child_spec.campaign_id,
            parent_candidate_ids=[parent_spec.baseline_candidate_id, candidate_report.candidate_id],
            mutation_policy="diagnosis_only",
            artifact_paths={
                "campaign_state_path": str(state.state_path),
                "next_step_report_path": str(report.report_path),
                "next_recommendations_path": str(recommendations_path),
            },
            gate_outcomes={
                "primary_issue": candidate_report.primary_issue,
                "diagnostic_confidence": candidate_report.diagnostic_confidence,
                "mutation_supported": bool(candidate_report.recommended_mutation),
            },
        )
    return report


def _run_mutate_one_candidate(
    settings: Settings,
    *,
    child_spec: CampaignSpec,
    state: CampaignState,
    candidate_ids: list[str],
    recommendation: NextStepRecommendation | None,
    step_reason: str,
    report_path: Path,
    recommendations_path: Path,
) -> NextStepControllerReport:
    source_candidate_id = candidate_ids[0]
    source_spec = _load_spec(settings, source_candidate_id)
    source_candidate = _load_candidate(settings, source_candidate_id, source_spec)
    mutation_payload = _resolve_mutation_payload(recommendation, source_spec)
    if mutation_payload is None:
        report = NextStepControllerReport(
            campaign_id=child_spec.campaign_id,
            parent_campaign_id=child_spec.parent_campaign_id,
            selected_step_type="mutate_one_candidate",
            step_reason=step_reason,
            status="stopped",
            stop_reason="unsupported_mutation_instruction",
            candidate_scope=candidate_ids,
            report_path=report_path,
        )
        write_json(report.report_path, report.model_dump(mode="json"))
        write_json(recommendations_path, [])
        return report

    preview_blueprint = _build_mutation_blueprint(
        settings,
        source_candidate_id=source_candidate_id,
        mutated_candidate_id="AF-CAND-PREVIEW",
        source_candidate=source_candidate,
        source_spec=source_spec,
        mutation_payload=mutation_payload,
    )
    if preview_blueprint is None:
        report = NextStepControllerReport(
            campaign_id=child_spec.campaign_id,
            parent_campaign_id=child_spec.parent_campaign_id,
            selected_step_type="mutate_one_candidate",
            step_reason=step_reason,
            status="stopped",
            stop_reason="mutation_instruction_had_no_effect",
            candidate_scope=candidate_ids,
            report_path=report_path,
        )
        write_json(report.report_path, report.model_dump(mode="json"))
        write_json(recommendations_path, [])
        return report

    equivalent_candidate_id = _find_equivalent_candidate_for_spec(
        settings,
        source_candidate_id=source_candidate_id,
        target_spec=preview_blueprint["spec"],
    )
    if equivalent_candidate_id:
        next_recommendations = [
            NextStepRecommendation(
                step_type="hypothesis_audit",
                candidate_id=source_candidate_id,
                rationale=(
                    f"The bounded mutation for {source_candidate_id} already exists as {equivalent_candidate_id} under "
                    "the same governed research contract. The lane should stop direct mutation and escalate to a "
                    "hypothesis audit instead of minting a duplicate variant."
                ),
                binding=True,
                evidence_status="supported",
                step_payload={
                    "source_candidate_id": source_candidate_id,
                    "equivalent_candidate_id": equivalent_candidate_id,
                    "mutation_type": mutation_payload["mutation_type"],
                },
            )
        ]
        report = NextStepControllerReport(
            campaign_id=child_spec.campaign_id,
            parent_campaign_id=child_spec.parent_campaign_id,
            selected_step_type="mutate_one_candidate",
            step_reason=step_reason,
            status="completed",
            stop_reason="mutation_duplicate_variant_redirected_to_hypothesis_audit",
            candidate_scope=candidate_ids,
            next_recommendations=next_recommendations,
            report_path=report_path,
        )
        write_json(report.report_path, report.model_dump(mode="json"))
        write_json(recommendations_path, [item.model_dump(mode="json") for item in next_recommendations])
        append_trial_entry(
            settings,
            candidate_id=source_candidate_id,
            family=child_spec.family,
            stage="mutate_one_candidate",
            campaign_id=child_spec.campaign_id,
            parent_candidate_ids=[source_candidate_id],
            mutation_policy=str(mutation_payload["mutation_type"]),
            artifact_paths={
                "campaign_state_path": str(state.state_path),
                "next_step_report_path": str(report.report_path),
                "next_recommendations_path": str(recommendations_path),
            },
            gate_outcomes={
                "duplicate_variant_detected": True,
                "equivalent_candidate_id": equivalent_candidate_id,
                "mutation_type": str(mutation_payload["mutation_type"]),
            },
        )
        return report

    mutated_candidate_id = next_candidate_id(settings)
    report_dir = settings.paths().reports_dir / mutated_candidate_id
    if report_dir.exists():
        report = NextStepControllerReport(
            campaign_id=child_spec.campaign_id,
            parent_campaign_id=child_spec.parent_campaign_id,
            selected_step_type="mutate_one_candidate",
            step_reason=step_reason,
            status="stopped",
            stop_reason="candidate_id_collision_detected",
            candidate_scope=candidate_ids,
            report_path=report_path,
            stop_class="integrity_issue",
        )
        write_json(report.report_path, report.model_dump(mode="json"))
        write_json(recommendations_path, [])
        return report
    report_dir.mkdir(parents=True, exist_ok=False)
    mutation_blueprint = _build_mutation_blueprint(
        settings,
        source_candidate_id=source_candidate_id,
        mutated_candidate_id=mutated_candidate_id,
        source_candidate=source_candidate,
        source_spec=source_spec,
        mutation_payload=mutation_payload,
    )
    if mutation_blueprint is None:
        report = NextStepControllerReport(
            campaign_id=child_spec.campaign_id,
            parent_campaign_id=child_spec.parent_campaign_id,
            selected_step_type="mutate_one_candidate",
            step_reason=step_reason,
            status="stopped",
            stop_reason="mutation_instruction_had_no_effect",
            candidate_scope=candidate_ids,
            report_path=report_path,
        )
        write_json(report.report_path, report.model_dump(mode="json"))
        write_json(recommendations_path, [])
        return report

    mutated_candidate = mutation_blueprint["candidate"]
    mutated_spec = mutation_blueprint["spec"]
    candidate_path = report_dir / "candidate.json"
    spec_path = report_dir / "strategy_spec.json"
    write_json(candidate_path, mutated_candidate.model_dump(mode="json"))
    write_json(spec_path, mutated_spec.model_dump(mode="json"))

    data_provenance = build_data_provenance(mutated_spec, settings, stage="ea_spec_complete")
    environment_snapshot = build_environment_snapshot(settings, candidate_id=mutated_candidate_id)
    mutation_report_path = report_dir / "mutation_report.json"
    mutation_report = CandidateMutationReport(
        source_candidate_id=source_candidate_id,
        mutated_candidate_id=mutated_candidate_id,
        mutation_type=str(mutation_payload["mutation_type"]),
        rationale=recommendation.rationale if recommendation else step_reason,
        readiness_status=resolve_readiness_status(
            candidate_id=mutated_candidate_id,
            spec_exists=True,
            backtest=None,
            stress=None,
            robustness=None,
            parity_passed=False,
            forward_report=None,
            settings=settings,
        ),
        changed_fields=list(mutation_blueprint["changed_fields"]),
        artifact_references={
            "dataset_snapshot": data_provenance.dataset_snapshot.model_dump(mode="json"),
            "feature_build": data_provenance.feature_build.model_dump(mode="json"),
            "data_provenance": data_provenance.model_dump(mode="json"),
            "environment_snapshot": environment_snapshot.model_dump(mode="json"),
            "execution_cost_model": mutated_spec.execution_cost_model.model_dump(mode="json"),
            "risk_envelope": mutated_spec.risk_envelope.model_dump(mode="json"),
        },
        artifact_paths={
            "source_candidate_path": str(settings.paths().reports_dir / source_candidate_id / "candidate.json"),
            "source_spec_path": str(settings.paths().reports_dir / source_candidate_id / "strategy_spec.json"),
            "candidate_path": str(candidate_path),
            "spec_path": str(spec_path),
            "data_provenance_path": str(data_provenance.report_path),
            "environment_snapshot_path": str(environment_snapshot.report_path),
            "mutation_report_path": str(mutation_report_path),
        },
    )
    write_json(mutation_report_path, mutation_report.model_dump(mode="json"))

    next_recommendations = [
        NextStepRecommendation(
            step_type="re_evaluate_one_candidate",
            candidate_id=mutated_candidate_id,
            rationale=(
                f"Mutation completed for {mutated_candidate_id}. Re-evaluate the mutated breakout candidate under the "
                f"current canonical OANDA dataset and execution-cost assumptions before any further search."
            ),
            binding=True,
            evidence_status="supported",
            step_payload={
                "source_candidate_id": source_candidate_id,
            "mutation_type": mutation_payload["mutation_type"],
            **mutation_blueprint["step_payload"],
        },
    )
    ]
    report = NextStepControllerReport(
        campaign_id=child_spec.campaign_id,
        parent_campaign_id=child_spec.parent_campaign_id,
        selected_step_type="mutate_one_candidate",
        step_reason=step_reason,
        status="completed",
        stop_reason="mutation_completed_with_supported_recommendation",
        candidate_scope=candidate_ids,
        mutation_reports=[mutation_report],
        next_recommendations=next_recommendations,
        report_path=report_path,
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    write_json(recommendations_path, [item.model_dump(mode="json") for item in next_recommendations])
    append_trial_entry(
        settings,
        candidate_id=mutated_candidate_id,
        family=child_spec.family,
        stage="mutate_one_candidate",
        campaign_id=child_spec.campaign_id,
        parent_candidate_ids=[source_candidate_id],
        mutation_policy=str(mutation_payload["mutation_type"]),
        provenance_id=data_provenance.provenance_id,
        environment_snapshot_id=environment_snapshot.environment_id,
        artifact_paths={
            "campaign_state_path": str(state.state_path),
            "next_step_report_path": str(report.report_path),
            "next_recommendations_path": str(recommendations_path),
            "candidate_path": str(candidate_path),
            "spec_path": str(spec_path),
            "mutation_report_path": str(mutation_report_path),
            "data_provenance_path": str(data_provenance.report_path),
            "environment_snapshot_path": str(environment_snapshot.report_path),
        },
        gate_outcomes={
            "source_candidate_id": source_candidate_id,
            "readiness_status": mutation_report.readiness_status,
            **mutation_blueprint["gate_outcomes"],
        },
    )
    return report


def _run_formalize_rule_candidate(
    settings: Settings,
    *,
    child_spec: CampaignSpec,
    state: CampaignState,
    candidate_ids: list[str],
    step_reason: str,
    report_path: Path,
    recommendations_path: Path,
) -> NextStepControllerReport:
    candidate_id = candidate_ids[0]
    state.rule_spec_reformulations_by_candidate[candidate_id] = (
        state.rule_spec_reformulations_by_candidate.get(candidate_id, 0) + 1
    )
    try:
        formalization_report = formalize_rule_candidate(settings, candidate_id=candidate_id)
    except Exception as exc:  # noqa: BLE001
        report = NextStepControllerReport(
            campaign_id=child_spec.campaign_id,
            parent_campaign_id=child_spec.parent_campaign_id,
            selected_step_type="formalize_rule_candidate",
            step_reason=step_reason,
            status="stopped",
            stop_reason=f"rule_spec_generation_failed:{exc}",
            candidate_scope=candidate_ids,
            report_path=report_path,
        )
        write_json(report.report_path, report.model_dump(mode="json"))
        write_json(recommendations_path, [])
        return report

    next_recommendations = [
        NextStepRecommendation(
            step_type="generate_ea_spec",
            candidate_id=candidate_id,
            rationale=(
                f"{candidate_id} now has a deterministic rule spec. The next bounded throughput step is EA-spec "
                "generation under the same control-plane state."
            ),
            binding=True,
            evidence_status="supported",
            step_payload={"source_candidate_id": candidate_id},
        )
    ]
    report = NextStepControllerReport(
        campaign_id=child_spec.campaign_id,
        parent_campaign_id=child_spec.parent_campaign_id,
        selected_step_type="formalize_rule_candidate",
        step_reason=step_reason,
        status="completed",
        stop_reason="rule_formalization_completed_with_supported_recommendation",
        candidate_scope=candidate_ids,
        rule_formalization_reports=[formalization_report],
        next_recommendations=next_recommendations,
        report_path=report_path,
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    write_json(recommendations_path, [item.model_dump(mode="json") for item in next_recommendations])
    append_trial_entry(
        settings,
        candidate_id=candidate_id,
        family=child_spec.family,
        stage="formalize_rule_candidate",
        campaign_id=child_spec.campaign_id,
        parent_candidate_ids=[candidate_id],
        mutation_policy="throughput_rule_formalization",
        artifact_paths=formalization_report.artifact_paths,
        gate_outcomes={
            "rule_spec_reformulations_used": state.rule_spec_reformulations_by_candidate[candidate_id],
            "rule_spec_reformulation_cap": child_spec.max_rule_spec_reformulations_per_hypothesis,
        },
    )
    return report


def _run_generate_ea_spec(
    settings: Settings,
    *,
    child_spec: CampaignSpec,
    state: CampaignState,
    candidate_ids: list[str],
    step_reason: str,
    report_path: Path,
    recommendations_path: Path,
) -> NextStepControllerReport:
    candidate_id = candidate_ids[0]
    state.ea_spec_rewrites_by_candidate[candidate_id] = state.ea_spec_rewrites_by_candidate.get(candidate_id, 0) + 1
    try:
        ea_spec_report = build_ea_spec_report(settings, candidate_id=candidate_id)
    except Exception as exc:  # noqa: BLE001
        report = NextStepControllerReport(
            campaign_id=child_spec.campaign_id,
            parent_campaign_id=child_spec.parent_campaign_id,
            selected_step_type="generate_ea_spec",
            step_reason=step_reason,
            status="stopped",
            stop_reason=f"ea_spec_generation_failed:{exc}",
            candidate_scope=candidate_ids,
            report_path=report_path,
        )
        write_json(report.report_path, report.model_dump(mode="json"))
        write_json(recommendations_path, [])
        return report

    follow_on_step: NextStepType = "compile_ea_candidate" if ea_spec_report.economic_plausibility_passed else "triage_reviewable_candidate"
    next_recommendations = [
        NextStepRecommendation(
            step_type=follow_on_step,
            candidate_id=candidate_id,
            rationale=(
                f"{candidate_id} now has an EA spec and "
                f"{'passed' if ea_spec_report.economic_plausibility_passed else 'failed'} the minimum economic "
                "plausibility gate."
            ),
            binding=True,
            evidence_status="supported",
            step_payload={"source_candidate_id": candidate_id},
        )
    ]
    stop_reason = (
        "ea_spec_generation_completed_with_supported_compile"
        if ea_spec_report.economic_plausibility_passed
        else "minimum_economic_plausibility_rejected"
    )
    report = NextStepControllerReport(
        campaign_id=child_spec.campaign_id,
        parent_campaign_id=child_spec.parent_campaign_id,
        selected_step_type="generate_ea_spec",
        step_reason=step_reason,
        status="completed",
        stop_reason=stop_reason,
        candidate_scope=candidate_ids,
        ea_spec_generation_reports=[ea_spec_report],
        next_recommendations=next_recommendations,
        report_path=report_path,
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    write_json(recommendations_path, [item.model_dump(mode="json") for item in next_recommendations])
    append_trial_entry(
        settings,
        candidate_id=candidate_id,
        family=child_spec.family,
        stage="generate_ea_spec",
        campaign_id=child_spec.campaign_id,
        parent_candidate_ids=[candidate_id],
        mutation_policy="throughput_ea_spec_generation",
        artifact_paths=ea_spec_report.artifact_paths,
        gate_outcomes={
            "economic_plausibility_passed": ea_spec_report.economic_plausibility_passed,
            "plausibility_findings": ea_spec_report.plausibility_findings,
            "ea_spec_rewrites_used": state.ea_spec_rewrites_by_candidate[candidate_id],
            "ea_spec_rewrite_cap": child_spec.max_ea_spec_rewrites_per_candidate,
        },
        failure_code="throughput_failure" if not ea_spec_report.economic_plausibility_passed else None,
    )
    return report


def _run_compile_ea_candidate(
    settings: Settings,
    *,
    child_spec: CampaignSpec,
    state: CampaignState,
    candidate_ids: list[str],
    step_reason: str,
    report_path: Path,
    recommendations_path: Path,
) -> NextStepControllerReport:
    candidate_id = candidate_ids[0]
    state.compile_retries_by_candidate[candidate_id] = state.compile_retries_by_candidate.get(candidate_id, 0) + 1
    compile_report = build_compile_report(settings, candidate_id=candidate_id)
    next_recommendations = [
        NextStepRecommendation(
            step_type="run_mt5_backtest_smoke" if compile_report.compile_status == "passed" else "triage_reviewable_candidate",
            candidate_id=candidate_id,
            rationale=(
                f"{candidate_id} "
                f"{'compiled successfully and is ready for an MT5 smoke backtest.' if compile_report.compile_status == 'passed' else 'failed compile and should be triaged before any further rewrite.'}"
            ),
            binding=True,
            evidence_status="supported",
            step_payload={"source_candidate_id": candidate_id},
        )
    ]
    stop_reason = (
        "compile_ea_candidate_completed_with_supported_smoke"
        if compile_report.compile_status == "passed"
        else "compile_ea_candidate_failed"
    )
    report = NextStepControllerReport(
        campaign_id=child_spec.campaign_id,
        parent_campaign_id=child_spec.parent_campaign_id,
        selected_step_type="compile_ea_candidate",
        step_reason=step_reason,
        status="completed",
        stop_reason=stop_reason,
        candidate_scope=candidate_ids,
        compile_reports=[compile_report],
        next_recommendations=next_recommendations,
        report_path=report_path,
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    write_json(recommendations_path, [item.model_dump(mode="json") for item in next_recommendations])
    append_trial_entry(
        settings,
        candidate_id=candidate_id,
        family=child_spec.family,
        stage="compile_ea_candidate",
        campaign_id=child_spec.campaign_id,
        parent_candidate_ids=[candidate_id],
        mutation_policy="throughput_compile",
        artifact_paths=compile_report.artifact_paths,
        gate_outcomes={
            "compile_status": compile_report.compile_status,
            "failure_classification": compile_report.failure_classification,
            "compile_retries_used": state.compile_retries_by_candidate[candidate_id],
            "compile_retry_cap": child_spec.max_compile_retries_per_candidate,
        },
        failure_code="compile_failure" if compile_report.compile_status == "failed" else None,
    )
    if compile_report.compile_status == "failed":
        append_failure_record(
            settings,
            candidate_id=candidate_id,
            stage="compile_ea_candidate",
            failure_code="compile_failure",
            campaign_id=child_spec.campaign_id,
            details={
                "failure_classification": compile_report.failure_classification,
                "compile_retries_used": state.compile_retries_by_candidate[candidate_id],
                "compile_retry_cap": child_spec.max_compile_retries_per_candidate,
            },
            artifact_paths=compile_report.artifact_paths,
        )
    return report


def _run_mt5_backtest_smoke(
    settings: Settings,
    *,
    child_spec: CampaignSpec,
    state: CampaignState,
    candidate_ids: list[str],
    step_reason: str,
    report_path: Path,
    recommendations_path: Path,
) -> NextStepControllerReport:
    candidate_id = candidate_ids[0]
    state.smoke_retries_by_candidate[candidate_id] = state.smoke_retries_by_candidate.get(candidate_id, 0) + 1
    smoke_report = build_mt5_smoke_report(settings, candidate_id=candidate_id)
    next_recommendations = [
        NextStepRecommendation(
            step_type="triage_reviewable_candidate",
            candidate_id=candidate_id,
            rationale=(
                f"{candidate_id} completed the bounded MT5 smoke stage with status {smoke_report.smoke_status}. "
                "The next throughput step is triage."
            ),
            binding=True,
            evidence_status="supported",
            step_payload={"source_candidate_id": candidate_id},
        )
    ]
    report = NextStepControllerReport(
        campaign_id=child_spec.campaign_id,
        parent_campaign_id=child_spec.parent_campaign_id,
        selected_step_type="run_mt5_backtest_smoke",
        step_reason=step_reason,
        status="completed",
        stop_reason=(
            "mt5_smoke_completed_with_supported_triage"
            if smoke_report.smoke_status == "passed"
            else "mt5_smoke_failed_requires_triage"
        ),
        candidate_scope=candidate_ids,
        mt5_smoke_reports=[smoke_report],
        next_recommendations=next_recommendations,
        report_path=report_path,
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    write_json(recommendations_path, [item.model_dump(mode="json") for item in next_recommendations])
    append_trial_entry(
        settings,
        candidate_id=candidate_id,
        family=child_spec.family,
        stage="run_mt5_backtest_smoke",
        campaign_id=child_spec.campaign_id,
        parent_candidate_ids=[candidate_id],
        mutation_policy="throughput_mt5_smoke",
        artifact_paths=smoke_report.artifact_paths,
        gate_outcomes={
            "smoke_status": smoke_report.smoke_status,
            "failure_classification": smoke_report.failure_classification,
            "trade_count": smoke_report.trade_count,
            "smoke_retries_used": state.smoke_retries_by_candidate[candidate_id],
            "smoke_retry_cap": child_spec.max_smoke_retries_per_candidate,
        },
        failure_code="mt5_smoke_failure" if smoke_report.smoke_status == "failed" else None,
    )
    if smoke_report.smoke_status == "failed":
        append_failure_record(
            settings,
            candidate_id=candidate_id,
            stage="run_mt5_backtest_smoke",
            failure_code="mt5_smoke_failure",
            campaign_id=child_spec.campaign_id,
            details={
                "failure_classification": smoke_report.failure_classification,
                "smoke_retries_used": state.smoke_retries_by_candidate[candidate_id],
                "smoke_retry_cap": child_spec.max_smoke_retries_per_candidate,
            },
            artifact_paths=smoke_report.artifact_paths,
        )
    return report


def _run_triage_reviewable_candidate(
    settings: Settings,
    *,
    child_spec: CampaignSpec,
    state: CampaignState,
    candidate_ids: list[str],
    step_reason: str,
    report_path: Path,
    recommendations_path: Path,
) -> NextStepControllerReport:
    candidate_id = candidate_ids[0]
    triage_report = triage_candidate(
        settings,
        candidate_id=candidate_id,
        compile_retries_used=state.compile_retries_by_candidate.get(candidate_id, 0),
        compile_retry_cap=child_spec.max_compile_retries_per_candidate,
        smoke_retries_used=state.smoke_retries_by_candidate.get(candidate_id, 0),
        smoke_retry_cap=child_spec.max_smoke_retries_per_candidate,
        ea_spec_rewrites_used=state.ea_spec_rewrites_by_candidate.get(candidate_id, 0),
        ea_spec_rewrite_cap=child_spec.max_ea_spec_rewrites_per_candidate,
    )
    stop_reason = {
        "discard": "triage_completed_discard_candidate",
        "refine": "triage_completed_refine_candidate",
        "send_to_research_lane": "triage_completed_send_to_research_lane",
    }[triage_report.classification]
    report = NextStepControllerReport(
        campaign_id=child_spec.campaign_id,
        parent_campaign_id=child_spec.parent_campaign_id,
        selected_step_type="triage_reviewable_candidate",
        step_reason=step_reason,
        status="completed",
        stop_reason=stop_reason,
        candidate_scope=candidate_ids,
        triage_reports=[triage_report],
        next_recommendations=[],
        report_path=report_path,
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    write_json(recommendations_path, [])
    append_trial_entry(
        settings,
        candidate_id=candidate_id,
        family=child_spec.family,
        stage="triage_reviewable_candidate",
        campaign_id=child_spec.campaign_id,
        parent_candidate_ids=[candidate_id],
        mutation_policy="throughput_triage",
        artifact_paths=triage_report.artifact_paths,
        gate_outcomes={
            "triage_classification": triage_report.classification,
            "compile_status": triage_report.compile_status,
            "smoke_status": triage_report.smoke_status,
            "reviewable_candidate": triage_report.readiness_status == "reviewable_candidate",
        },
        failure_code="throughput_failure" if triage_report.classification != "send_to_research_lane" else None,
    )
    return report


def _run_re_evaluate_one_candidate(
    settings: Settings,
    *,
    child_spec: CampaignSpec,
    state: CampaignState,
    candidate_ids: list[str],
    recommendation: NextStepRecommendation | None,
    step_reason: str,
    report_path: Path,
    recommendations_path: Path,
) -> NextStepControllerReport:
    candidate_id = candidate_ids[0]
    source_candidate_id = str((recommendation.step_payload or {}).get("source_candidate_id") or "")
    spec = _load_spec(settings, candidate_id)
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

    review_packet = ReviewPacket.model_validate(review_trace.output_payload)
    reevaluation_report_path = settings.paths().reports_dir / candidate_id / "reevaluation_report.json"
    reevaluation_report = _build_reevaluation_report(
        settings,
        candidate_id=candidate_id,
        source_candidate_id=source_candidate_id or None,
        review_packet=review_packet,
        report_path=reevaluation_report_path,
    )
    next_recommendations = _build_post_reevaluation_recommendations(
        settings,
        candidate_id=candidate_id,
        source_candidate_id=source_candidate_id or None,
        review_packet=review_packet,
    )
    stop_reason = (
        "re_evaluation_completed_with_supported_recommendation"
        if next_recommendations
        else "re_evaluation_completed_no_supported_next_step"
    )
    report = NextStepControllerReport(
        campaign_id=child_spec.campaign_id,
        parent_campaign_id=child_spec.parent_campaign_id,
        selected_step_type="re_evaluate_one_candidate",
        step_reason=step_reason,
        status="completed",
        stop_reason=stop_reason,
        candidate_scope=candidate_ids,
        reevaluation_reports=[reevaluation_report],
        next_recommendations=next_recommendations,
        report_path=report_path,
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    write_json(recommendations_path, [item.model_dump(mode="json") for item in next_recommendations])

    data_provenance = load_data_provenance(candidate_id, settings)
    environment_snapshot = load_environment_snapshot(candidate_id, settings)
    append_trial_entry(
        settings,
        candidate_id=candidate_id,
        family=child_spec.family,
        stage="re_evaluate_one_candidate",
        campaign_id=child_spec.campaign_id,
        parent_candidate_ids=[source_candidate_id] if source_candidate_id else [candidate_id],
        mutation_policy="reevaluation_only",
        provenance_id=data_provenance.provenance_id if data_provenance else None,
        environment_snapshot_id=environment_snapshot.environment_id if environment_snapshot else None,
        artifact_paths={
            "campaign_state_path": str(state.state_path),
            "next_step_report_path": str(report.report_path),
            "next_recommendations_path": str(recommendations_path),
            **reevaluation_report.artifact_paths,
        },
        gate_outcomes={
            "readiness_status": reevaluation_report.readiness_status,
            "approval_recommendation": reevaluation_report.approval_recommendation,
            "trade_count": reevaluation_report.trade_count,
            "out_of_sample_profit_factor": reevaluation_report.out_of_sample_profit_factor,
            "stressed_profit_factor": reevaluation_report.stressed_profit_factor,
            "walk_forward_ok": reevaluation_report.walk_forward_ok,
            "stress_passed": reevaluation_report.stress_passed,
        },
    )
    return report


def _run_hypothesis_audit(
    settings: Settings,
    *,
    child_spec: CampaignSpec,
    state: CampaignState,
    parent_spec: CampaignSpec,
    candidate_ids: list[str],
    step_reason: str,
    report_path: Path,
    recommendations_path: Path,
) -> NextStepControllerReport:
    candidate_summaries = [
        _build_hypothesis_audit_candidate_summary(settings, candidate_id)
        for candidate_id in candidate_ids
        if _hypothesis_audit_artifacts_exist(settings, candidate_id)
    ]
    parent_report = _load_controller_report_for_campaign(settings, child_spec.parent_campaign_id)
    reference_summary = _select_hypothesis_reference_summary(candidate_summaries)
    lane_decision = _resolve_hypothesis_lane_decision(candidate_summaries, reference_summary, settings)
    if lane_decision == "narrow_correction_supported" and _hypothesis_audit_should_hold_reference(
        parent_report,
        reference_summary,
    ):
        lane_decision = "hold_reference_blocked_by_robustness"
    common_failure_modes = _collect_hypothesis_failure_modes(candidate_summaries, settings)
    summary = _build_hypothesis_audit_summary(
        candidate_summaries=candidate_summaries,
        reference_summary=reference_summary,
        lane_decision=lane_decision,
    )
    recommended_actions = _build_hypothesis_audit_actions(
        lane_decision=lane_decision,
        reference_summary=reference_summary,
    )
    next_recommendations = _build_hypothesis_audit_recommendations(
        lane_decision=lane_decision,
        reference_summary=reference_summary,
    )
    audit_report = HypothesisAuditReport(
        family=parent_spec.family,
        audited_candidate_ids=[item.candidate_id for item in candidate_summaries],
        reference_candidate_id=reference_summary.candidate_id if reference_summary else None,
        lane_decision=lane_decision,
        summary=summary,
        common_failure_modes=common_failure_modes,
        recommended_actions=recommended_actions,
        candidate_summaries=candidate_summaries,
        artifact_paths={
            "campaign_state_path": str(state.state_path),
            "next_step_report_path": str(report_path),
            "next_recommendations_path": str(recommendations_path),
        },
    )
    stop_reason = f"hypothesis_audit_completed_{lane_decision}"
    report = NextStepControllerReport(
        campaign_id=child_spec.campaign_id,
        parent_campaign_id=child_spec.parent_campaign_id,
        selected_step_type="hypothesis_audit",
        step_reason=step_reason,
        status="completed",
        stop_reason=stop_reason,
        candidate_scope=candidate_ids,
        hypothesis_audit_reports=[audit_report],
        next_recommendations=next_recommendations,
        report_path=report_path,
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    write_json(recommendations_path, [item.model_dump(mode="json") for item in next_recommendations])

    for summary_item in candidate_summaries:
        append_trial_entry(
            settings,
            candidate_id=summary_item.candidate_id,
            family=child_spec.family,
            stage="hypothesis_audit",
            campaign_id=child_spec.campaign_id,
            parent_candidate_ids=[candidate_id for candidate_id in candidate_ids if candidate_id != summary_item.candidate_id],
            mutation_policy="audit_only",
            artifact_paths={
                "campaign_state_path": str(state.state_path),
                "next_step_report_path": str(report.report_path),
                "next_recommendations_path": str(recommendations_path),
                **summary_item.artifact_paths,
            },
            gate_outcomes={
                "lane_decision": lane_decision,
                "reference_candidate_id": reference_summary.candidate_id if reference_summary else None,
                "walk_forward_ok": summary_item.walk_forward_ok,
                "stress_passed": summary_item.stress_passed,
                "pbo": summary_item.pbo,
                "white_reality_check_p_value": summary_item.white_reality_check_p_value,
                "archived": summary_item.archived,
            },
        )

    if lane_decision in {"retire_lane", "hold_reference_blocked_by_robustness"}:
        target_candidate = reference_summary.candidate_id if reference_summary else candidate_ids[0]
        append_failure_record(
            settings,
            candidate_id=target_candidate,
            stage="hypothesis_audit",
            failure_code="robustness_failure",
            campaign_id=child_spec.campaign_id,
            details={
                "decision": lane_decision,
                "audited_candidate_ids": [item.candidate_id for item in candidate_summaries],
                "reference_candidate_id": reference_summary.candidate_id if reference_summary else None,
                "summary": summary,
            },
            artifact_paths={
                "next_step_report_path": str(report.report_path),
            },
        )
    return report


def _run_data_regime_audit(
    settings: Settings,
    *,
    child_spec: CampaignSpec,
    state: CampaignState,
    parent_spec: CampaignSpec,
    candidate_ids: list[str],
    step_reason: str,
    report_path: Path,
    recommendations_path: Path,
) -> NextStepControllerReport:
    candidate_summaries = [
        _build_hypothesis_audit_candidate_summary(settings, candidate_id)
        for candidate_id in candidate_ids
        if _hypothesis_audit_artifacts_exist(settings, candidate_id)
    ]
    reference_summary = _select_hypothesis_reference_summary(candidate_summaries)
    slice_summaries: list[DataRegimeSliceSummary] = []
    focus_candidate_id = reference_summary.candidate_id if reference_summary else None
    if focus_candidate_id:
        slice_summaries = _build_data_regime_slice_summaries(settings, focus_candidate_id)
    lane_decision = _resolve_data_regime_lane_decision(slice_summaries, reference_summary, settings)
    summary = _build_data_regime_summary(
        candidate_summaries=candidate_summaries,
        reference_summary=reference_summary,
        slice_summaries=slice_summaries,
        lane_decision=lane_decision,
    )
    recommended_actions = _build_data_regime_actions(
        lane_decision=lane_decision,
        reference_summary=reference_summary,
        supported_slice=_select_supported_data_regime_slice(slice_summaries),
    )
    next_recommendations = _build_data_regime_recommendations(
        reference_summary=reference_summary,
        supported_slice=_select_supported_data_regime_slice(slice_summaries),
        lane_decision=lane_decision,
    )
    audit_report = DataRegimeAuditReport(
        family=parent_spec.family,
        audited_candidate_ids=[item.candidate_id for item in candidate_summaries],
        reference_candidate_id=reference_summary.candidate_id if reference_summary else None,
        focus_candidate_id=focus_candidate_id,
        failed_window_index=1,
        lane_decision=lane_decision,
        summary=summary,
        dominant_first_window_loss_modes=[item.slice_label for item in slice_summaries[:3]],
        recommended_actions=recommended_actions,
        slice_summaries=slice_summaries,
        candidate_summaries=candidate_summaries,
        artifact_paths={
            "campaign_state_path": str(state.state_path),
            "next_step_report_path": str(report_path),
            "next_recommendations_path": str(recommendations_path),
        },
    )
    stop_reason = f"data_regime_audit_completed_{lane_decision}"
    report = NextStepControllerReport(
        campaign_id=child_spec.campaign_id,
        parent_campaign_id=child_spec.parent_campaign_id,
        selected_step_type="data_regime_audit",
        step_reason=step_reason,
        status="completed",
        stop_reason=stop_reason,
        candidate_scope=candidate_ids,
        data_regime_audit_reports=[audit_report],
        next_recommendations=next_recommendations,
        report_path=report_path,
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    write_json(recommendations_path, [item.model_dump(mode="json") for item in next_recommendations])

    for summary_item in candidate_summaries:
        append_trial_entry(
            settings,
            candidate_id=summary_item.candidate_id,
            family=child_spec.family,
            stage="data_regime_audit",
            campaign_id=child_spec.campaign_id,
            parent_candidate_ids=[candidate_id for candidate_id in candidate_ids if candidate_id != summary_item.candidate_id],
            mutation_policy="audit_only",
            artifact_paths={
                "campaign_state_path": str(state.state_path),
                "next_step_report_path": str(report.report_path),
                "next_recommendations_path": str(recommendations_path),
                **summary_item.artifact_paths,
            },
            gate_outcomes={
                "lane_decision": lane_decision,
                "reference_candidate_id": reference_summary.candidate_id if reference_summary else None,
                "focus_candidate_id": focus_candidate_id,
                "archived": summary_item.archived,
            },
        )

    if lane_decision in {"retire_lane", "structural_regime_instability"}:
        target_candidate = reference_summary.candidate_id if reference_summary else candidate_ids[0]
        append_failure_record(
            settings,
            candidate_id=target_candidate,
            stage="data_regime_audit",
            failure_code="robustness_failure",
            campaign_id=child_spec.campaign_id,
            details={
                "decision": lane_decision,
                "audited_candidate_ids": [item.candidate_id for item in candidate_summaries],
                "focus_candidate_id": focus_candidate_id,
                "reference_candidate_id": reference_summary.candidate_id if reference_summary else None,
                "summary": summary,
            },
            artifact_paths={
                "next_step_report_path": str(report.report_path),
            },
        )
    return report


def _run_data_feature_audit(
    settings: Settings,
    *,
    child_spec: CampaignSpec,
    state: CampaignState,
    parent_spec: CampaignSpec,
    candidate_ids: list[str],
    step_reason: str,
    report_path: Path,
    recommendations_path: Path,
) -> NextStepControllerReport:
    candidate_summaries = [
        _build_hypothesis_audit_candidate_summary(settings, candidate_id)
        for candidate_id in candidate_ids
        if _hypothesis_audit_artifacts_exist(settings, candidate_id)
    ]
    reference_summary = _select_hypothesis_reference_summary(candidate_summaries)
    provenance_consistency = _build_data_feature_provenance_consistency(settings, candidate_summaries)
    recent_regime_signals = _collect_recent_regime_signals(settings, candidate_summaries)
    suspected_root_causes = _build_data_feature_root_causes(
        settings,
        candidate_summaries=candidate_summaries,
        provenance_consistency=provenance_consistency,
        recent_regime_signals=recent_regime_signals,
    )
    family_decision = _resolve_data_feature_family_decision(
        candidate_summaries=candidate_summaries,
        provenance_consistency=provenance_consistency,
        suspected_root_causes=suspected_root_causes,
        settings=settings,
    )
    summary = _build_data_feature_summary(
        candidate_summaries=candidate_summaries,
        reference_summary=reference_summary,
        family_decision=family_decision,
        suspected_root_causes=suspected_root_causes,
        provenance_consistency=provenance_consistency,
    )
    recommended_actions = _build_data_feature_actions(
        family_decision=family_decision,
        reference_summary=reference_summary,
    )
    next_recommendations = _build_data_feature_recommendations(
        family_decision=family_decision,
        reference_summary=reference_summary,
    )
    audit_report = DataFeatureAuditReport(
        family=parent_spec.family,
        audited_candidate_ids=[item.candidate_id for item in candidate_summaries],
        reference_candidate_id=reference_summary.candidate_id if reference_summary else None,
        family_decision=family_decision,
        summary=summary,
        suspected_root_causes=suspected_root_causes,
        provenance_consistency=provenance_consistency,
        recent_regime_signals=recent_regime_signals,
        recommended_actions=recommended_actions,
        candidate_summaries=candidate_summaries,
        artifact_paths={
            "campaign_state_path": str(state.state_path),
            "next_step_report_path": str(report_path),
            "next_recommendations_path": str(recommendations_path),
        },
    )
    stop_reason = f"data_feature_audit_completed_{family_decision}"
    report = NextStepControllerReport(
        campaign_id=child_spec.campaign_id,
        parent_campaign_id=child_spec.parent_campaign_id,
        selected_step_type="data_feature_audit",
        step_reason=step_reason,
        status="completed",
        stop_reason=stop_reason,
        candidate_scope=candidate_ids,
        data_feature_audit_reports=[audit_report],
        next_recommendations=next_recommendations,
        report_path=report_path,
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    write_json(recommendations_path, [item.model_dump(mode="json") for item in next_recommendations])

    for summary_item in candidate_summaries:
        append_trial_entry(
            settings,
            candidate_id=summary_item.candidate_id,
            family=child_spec.family,
            stage="data_feature_audit",
            campaign_id=child_spec.campaign_id,
            parent_candidate_ids=[candidate_id for candidate_id in candidate_ids if candidate_id != summary_item.candidate_id],
            mutation_policy="audit_only",
            artifact_paths={
                "campaign_state_path": str(state.state_path),
                "next_step_report_path": str(report.report_path),
                "next_recommendations_path": str(recommendations_path),
                **summary_item.artifact_paths,
            },
            gate_outcomes={
                "family_decision": family_decision,
                "reference_candidate_id": reference_summary.candidate_id if reference_summary else None,
                "archived": summary_item.archived,
                "root_causes": suspected_root_causes,
            },
        )

    if family_decision == "retire_family":
        target_candidate = reference_summary.candidate_id if reference_summary else candidate_ids[0]
        append_failure_record(
            settings,
            candidate_id=target_candidate,
            stage="data_feature_audit",
            failure_code="robustness_failure",
            campaign_id=child_spec.campaign_id,
            details={
                "decision": family_decision,
                "audited_candidate_ids": [item.candidate_id for item in candidate_summaries],
                "reference_candidate_id": reference_summary.candidate_id if reference_summary else None,
                "root_causes": suspected_root_causes,
                "summary": summary,
            },
            artifact_paths={
                "next_step_report_path": str(report.report_path),
            },
        )
    return report


def _run_parity_step(
    settings: Settings,
    *,
    child_spec: CampaignSpec,
    state: CampaignState,
    candidate_ids: list[str],
    recommendation: NextStepRecommendation | None,
    step_reason: str,
    report_path: Path,
    recommendations_path: Path,
) -> NextStepControllerReport:
    candidate_id = candidate_ids[0]
    if _operational_budget_exhausted(state, settings):
        report = NextStepControllerReport(
            campaign_id=child_spec.campaign_id,
            parent_campaign_id=child_spec.parent_campaign_id,
            selected_step_type="run_parity",
            step_reason=step_reason,
            status="stopped",
            stop_reason="operational_retry_budget_exhausted",
            candidate_scope=candidate_ids,
            report_path=report_path,
        )
        write_json(report.report_path, report.model_dump(mode="json"))
        write_json(recommendations_path, [])
        return report

    try:
        parity_report = run_mt5_parity(candidate_id, settings)
    except ParityPolicyError as exc:
        report = NextStepControllerReport(
            campaign_id=child_spec.campaign_id,
            parent_campaign_id=child_spec.parent_campaign_id,
            selected_step_type="run_parity",
            step_reason=step_reason,
            status="stopped",
            stop_reason=str(exc),
            candidate_scope=candidate_ids,
            report_path=report_path,
        )
        write_json(report.report_path, report.model_dump(mode="json"))
        write_json(recommendations_path, [])
        return report
    state.operational_runs_consumed += 1
    state.mt5_parity_retries_by_candidate[candidate_id] = state.mt5_parity_retries_by_candidate.get(candidate_id, 0) + 1

    next_recommendations: list[NextStepRecommendation] = []
    if parity_report.validation_status == "passed":
        next_recommendations.append(
            NextStepRecommendation(
                step_type="run_forward",
                candidate_id=candidate_id,
                rationale=(
                    f"{candidate_id} passed practice parity with the configured MT5 tolerances. "
                    "The next governed step is OANDA shadow-forward."
                ),
                binding=True,
                evidence_status="supported",
                source_campaign_id=child_spec.campaign_id,
                step_payload={"source_candidate_id": candidate_id},
            )
        )
    elif parity_report.validation_status == "failed":
        next_recommendations.append(
            NextStepRecommendation(
                step_type="diagnose_existing_candidates",
                candidate_id=candidate_id,
                rationale=(
                    f"{candidate_id} failed MT5 practice parity with classification "
                    f"{parity_report.failure_classification or 'parity_failure'}. "
                    "The next legal step is diagnosis only; parity evidence must not mutate policy directly."
                ),
                binding=True,
                evidence_status="supported",
                source_campaign_id=child_spec.campaign_id,
                step_payload={"source_candidate_id": candidate_id},
            )
        )

    stop_reason = {
        "passed": "parity_completed_with_supported_recommendation",
        "failed": "parity_failed_requires_diagnosis",
        "insufficient_evidence": "parity_insufficient_evidence",
        "pending_audit": "parity_pending_audit",
    }.get(parity_report.validation_status, "parity_completed")
    report = NextStepControllerReport(
        campaign_id=child_spec.campaign_id,
        parent_campaign_id=child_spec.parent_campaign_id,
        selected_step_type="run_parity",
        step_reason=step_reason,
        status="completed" if parity_report.validation_status in {"passed", "failed", "insufficient_evidence"} else "stopped",
        stop_reason=stop_reason,
        candidate_scope=candidate_ids,
        mt5_parity_reports=[parity_report.model_dump(mode="json")],
        next_recommendations=next_recommendations,
        report_path=report_path,
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    write_json(recommendations_path, [item.model_dump(mode="json") for item in next_recommendations])
    return report


def _run_forward_step(
    settings: Settings,
    *,
    child_spec: CampaignSpec,
    state: CampaignState,
    candidate_ids: list[str],
    recommendation: NextStepRecommendation | None,
    step_reason: str,
    report_path: Path,
    recommendations_path: Path,
) -> NextStepControllerReport:
    candidate_id = candidate_ids[0]
    if _operational_budget_exhausted(state, settings):
        report = NextStepControllerReport(
            campaign_id=child_spec.campaign_id,
            parent_campaign_id=child_spec.parent_campaign_id,
            selected_step_type="run_forward",
            step_reason=step_reason,
            status="stopped",
            stop_reason="operational_retry_budget_exhausted",
            candidate_scope=candidate_ids,
            report_path=report_path,
        )
        write_json(report.report_path, report.model_dump(mode="json"))
        write_json(recommendations_path, [])
        return report

    spec = _load_spec(settings, candidate_id)
    forward_report = run_shadow_forward(spec, settings)
    state.operational_runs_consumed += 1
    state.shadow_forward_retries_by_candidate[candidate_id] = state.shadow_forward_retries_by_candidate.get(candidate_id, 0) + 1

    parity_validation = load_latest_mt5_validation(candidate_id, settings)
    readiness_status = resolve_readiness_status(
        candidate_id=candidate_id,
        spec_exists=True,
        backtest=None,
        stress=None,
        robustness=None,
        parity_passed=bool(parity_validation and parity_validation.validation_status == "passed"),
        forward_report=forward_report,
        settings=settings,
    )
    next_recommendations: list[NextStepRecommendation] = []
    if forward_report.passed and readiness_status in {"review_eligible_provisional", "review_eligible"}:
        next_recommendations.append(
            NextStepRecommendation(
                step_type="human_review",
                candidate_id=candidate_id,
                rationale=(
                    f"{candidate_id} passed OANDA shadow-forward after parity and is now {readiness_status}. "
                    "The next required action is explicit human review."
                ),
                binding=True,
                evidence_status="supported",
                source_campaign_id=child_spec.campaign_id,
                step_payload={"source_candidate_id": candidate_id},
            )
        )
    elif not forward_report.passed:
        next_recommendations.append(
            NextStepRecommendation(
                step_type="diagnose_existing_candidates",
                candidate_id=candidate_id,
                rationale=(
                    f"{candidate_id} failed OANDA shadow-forward after parity. "
                    "The next legal step is diagnosis rather than direct mutation or policy change."
                ),
                binding=True,
                evidence_status="supported",
                source_campaign_id=child_spec.campaign_id,
                step_payload={"source_candidate_id": candidate_id},
            )
        )

    report = NextStepControllerReport(
        campaign_id=child_spec.campaign_id,
        parent_campaign_id=child_spec.parent_campaign_id,
        selected_step_type="run_forward",
        step_reason=step_reason,
        status="completed",
        stop_reason="forward_completed_with_supported_recommendation" if next_recommendations else "forward_completed_no_supported_next_step",
        candidate_scope=candidate_ids,
        forward_reports=[forward_report],
        next_recommendations=next_recommendations,
        report_path=report_path,
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    write_json(recommendations_path, [item.model_dump(mode="json") for item in next_recommendations])
    return report


def _inherit_child_state_counters(state: CampaignState, parent_state: CampaignState) -> None:
    if state.iterations_run or state.trials_consumed or state.operational_runs_consumed:
        return
    state.iterations_run = parent_state.iterations_run
    state.trials_consumed = parent_state.trials_consumed
    state.operational_runs_consumed = parent_state.operational_runs_consumed
    state.promoted_candidate_ids = list(parent_state.promoted_candidate_ids)
    state.rule_spec_reformulations_by_candidate = dict(parent_state.rule_spec_reformulations_by_candidate)
    state.ea_spec_rewrites_by_candidate = dict(parent_state.ea_spec_rewrites_by_candidate)
    state.compile_retries_by_candidate = dict(parent_state.compile_retries_by_candidate)
    state.smoke_retries_by_candidate = dict(parent_state.smoke_retries_by_candidate)
    state.mt5_parity_retries_by_candidate = dict(parent_state.mt5_parity_retries_by_candidate)
    state.shadow_forward_retries_by_candidate = dict(parent_state.shadow_forward_retries_by_candidate)


def _operational_budget_exhausted(state: CampaignState, settings: Settings) -> bool:
    return state.operational_runs_consumed >= settings.campaign.max_total_operational_runs_per_campaign


def _diagnose_candidate(
    settings: Settings,
    *,
    candidate_id: str,
    market_frame: pd.DataFrame,
    anomaly_threshold: float,
) -> CandidateDiagnosticReport:
    report_dir = settings.paths().reports_dir / candidate_id
    review_packet = read_json(report_dir / "review_packet.json")
    trade_ledger = pd.read_csv(report_dir / "trade_ledger.csv")
    trade_ledger["timestamp_utc"] = pd.to_datetime(trade_ledger["timestamp_utc"], utc=True)
    windows = max(len((review_packet.get("metrics") or {}).get("walk_forward_summary") or []), 1)
    trade_ledger["walk_forward_window"] = _assign_walk_forward_windows(len(trade_ledger), windows)
    merged = trade_ledger.merge(market_frame, on="timestamp_utc", how="left")
    merged["is_spread_anomaly"] = merged["is_spread_anomaly"].fillna(False)

    first_window = merged[merged["walk_forward_window"] == 1].reset_index(drop=True)
    later_windows = merged[merged["walk_forward_window"] > 1].reset_index(drop=True)
    first_loss_total = abs(first_window.loc[first_window["pnl_pips"] < 0, "pnl_pips"].sum()) or 1e-9
    supported_slices = _collect_supported_slices(first_window, later_windows, first_loss_total)
    primary_issue = supported_slices[0].slice_type + ":" + supported_slices[0].slice_label if supported_slices else None
    recommended_mutation = _recommend_mutation(
        candidate_id,
        supported_slices[0],
        report_dir / "strategy_spec.json",
    ) if supported_slices else None
    diagnostic_confidence = round(min(0.95, supported_slices[0].evidence_score / 5.0), 3) if supported_slices else 0.0

    return CandidateDiagnosticReport(
        candidate_id=candidate_id,
        readiness_status=str(review_packet.get("readiness") or "robustness_provisional"),
        walk_forward_failed_window=1,
        first_window_start_utc=_timestamp(first_window["timestamp_utc"].min() if not first_window.empty else None),
        first_window_end_utc=_timestamp(first_window["timestamp_utc"].max() if not first_window.empty else None),
        first_window_trade_count=int(len(first_window)),
        first_window_profit_factor=_profit_factor(first_window["pnl_pips"]) if not first_window.empty else 0.0,
        first_window_expectancy_pips=float(first_window["pnl_pips"].mean()) if not first_window.empty else 0.0,
        later_window_trade_count=int(len(later_windows)),
        later_window_profit_factor=_profit_factor(later_windows["pnl_pips"]) if not later_windows.empty else 0.0,
        later_window_expectancy_pips=float(later_windows["pnl_pips"].mean()) if not later_windows.empty else 0.0,
        spread_anomaly_rate_first_window=float(first_window["is_spread_anomaly"].mean()) if not first_window.empty else 0.0,
        spread_anomaly_rate_later_windows=float(later_windows["is_spread_anomaly"].mean()) if not later_windows.empty else 0.0,
        supported_slices=supported_slices[:4],
        primary_issue=primary_issue,
        recommended_mutation=recommended_mutation,
        diagnostic_confidence=diagnostic_confidence,
        notes=_candidate_notes(first_window, later_windows, anomaly_threshold, supported_slices),
        artifact_paths={
            "review_packet_path": str(report_dir / "review_packet.json"),
            "trade_ledger_path": str(report_dir / "trade_ledger.csv"),
            "backtest_summary_path": str(report_dir / "backtest_summary.json"),
            "robustness_report_path": str(report_dir / "robustness_report.json"),
        },
    )


def _build_reevaluation_report(
    settings: Settings,
    *,
    candidate_id: str,
    source_candidate_id: str | None,
    review_packet: ReviewPacket,
    report_path: Path,
) -> CandidateReevaluationReport:
    metrics = review_packet.metrics or {}
    grades = metrics.get("grades") or {}
    stress_scenarios = metrics.get("stress_scenarios") or []
    stressed_profit_factor = float(stress_scenarios[-1]["profit_factor"]) if stress_scenarios else 0.0
    report = CandidateReevaluationReport(
        candidate_id=candidate_id,
        source_candidate_id=source_candidate_id,
        readiness_status=str(review_packet.readiness),
        robustness_mode=str(review_packet.robustness_mode),
        approval_recommendation=str(review_packet.approval_recommendation),
        trade_count=int(metrics.get("trade_count") or 0),
        out_of_sample_profit_factor=float(metrics.get("out_of_sample_profit_factor") or 0.0),
        expectancy_pips=float(metrics.get("expectancy_pips") or 0.0),
        stressed_profit_factor=stressed_profit_factor,
        walk_forward_ok=bool(grades.get("walk_forward_ok")),
        stress_passed=bool(metrics.get("stress_passed")),
        artifact_references={
            "dataset_snapshot": metrics.get("dataset_snapshot", {}),
            "feature_build": metrics.get("feature_build", {}),
            "data_provenance": metrics.get("data_provenance", {}),
            "environment_snapshot": metrics.get("environment_snapshot", {}),
            "execution_cost_model": metrics.get("execution_cost_model", {}),
            "risk_envelope": metrics.get("risk_envelope", {}),
        },
        artifact_paths={
            "spec_path": str(settings.paths().reports_dir / candidate_id / "strategy_spec.json"),
            "backtest_summary_path": str(settings.paths().reports_dir / candidate_id / "backtest_summary.json"),
            "trade_ledger_path": str(settings.paths().reports_dir / candidate_id / "trade_ledger.csv"),
            "stress_report_path": str(settings.paths().reports_dir / candidate_id / "stress_test.json"),
            "review_packet_path": str(settings.paths().reports_dir / candidate_id / "review_packet.json"),
            "robustness_report_path": str(settings.paths().reports_dir / candidate_id / "robustness_report.json"),
            "data_provenance_path": str(settings.paths().reports_dir / candidate_id / "data_provenance.json"),
            "environment_snapshot_path": str(settings.paths().reports_dir / candidate_id / "environment_snapshot.json"),
            "reevaluation_report_path": str(report_path),
        },
    )
    write_json(report_path, report.model_dump(mode="json"))
    return report


def _build_post_reevaluation_recommendations(
    settings: Settings,
    *,
    candidate_id: str,
    source_candidate_id: str | None,
    review_packet: ReviewPacket,
) -> list[NextStepRecommendation]:
    metrics = review_packet.metrics or {}
    grades = metrics.get("grades") or {}
    robustness = metrics.get("robustness_report") or {}
    trade_count = int(metrics.get("trade_count") or 0)
    walk_forward_ok = bool(grades.get("walk_forward_ok"))
    stress_passed = bool(metrics.get("stress_passed"))
    oos_profit_factor = float(metrics.get("out_of_sample_profit_factor") or 0.0)
    expectancy = float(metrics.get("expectancy_pips") or 0.0)
    dsr = float(robustness.get("deflated_sharpe_ratio") or 0.0)
    pbo = robustness.get("pbo")
    cscv_available = bool(robustness.get("cscv_pbo_available"))
    white_reality_check_available = bool(robustness.get("white_reality_check_available"))
    white_reality_check_p_value = robustness.get("white_reality_check_p_value")

    if (
        trade_count >= settings.validation.minimum_test_trade_count
        and walk_forward_ok
        and stress_passed
        and oos_profit_factor >= settings.validation.out_of_sample_profit_factor_floor
        and expectancy > settings.validation.expectancy_floor
        and dsr >= settings.validation.deflated_sharpe_floor
        and (not cscv_available or pbo is None or float(pbo) <= settings.validation.pbo_threshold)
        and (
            not white_reality_check_available
            or white_reality_check_p_value is None
            or float(white_reality_check_p_value) <= settings.validation.white_reality_check_pvalue_threshold
        )
    ):
        return [
            NextStepRecommendation(
                step_type="run_parity",
                candidate_id=candidate_id,
                rationale=(
                    f"{candidate_id} now meets the bounded empirical and provisional robustness gates for parity entry. "
                    "The next governed step should be MT5 parity, still in practice-only mode."
                ),
                binding=True,
                evidence_status="supported",
                step_payload={"source_candidate_id": source_candidate_id or candidate_id},
            )
        ]

    if not walk_forward_ok or not stress_passed:
        return [
            NextStepRecommendation(
                step_type="diagnose_existing_candidates",
                candidate_id=candidate_id,
                rationale=(
                    f"{candidate_id} remains provisionally governed but still fails "
                    f"{'walk-forward stability' if not walk_forward_ok else 'stress'} after the bounded mutation. "
                    "The next step should be a fresh diagnosis before any additional mutation."
                ),
                binding=True,
                evidence_status="supported",
                step_payload={"source_candidate_id": source_candidate_id or candidate_id},
            )
        ]
    return []


def _collect_supported_slices(
    first_window: pd.DataFrame,
    later_windows: pd.DataFrame,
    first_loss_total: float,
) -> list[DiagnosticSliceReport]:
    slices: list[DiagnosticSliceReport] = []
    for column, slice_type in (("session_bucket", "session_bucket"), ("context_bucket", "context_bucket")):
        for label, group in first_window.groupby(column):
            later_group = later_windows[later_windows[column] == label]
            slice_report = _build_slice_report(
                slice_type=slice_type,
                slice_label=str(label),
                first_group=group,
                later_group=later_group,
                first_loss_total=first_loss_total,
            )
            if slice_report.supported:
                slices.append(slice_report)
    spread_slice = _build_spread_slice(first_window, later_windows)
    if spread_slice and spread_slice.supported:
        slices.append(spread_slice)
    return sorted(slices, key=lambda item: item.evidence_score, reverse=True)


def _build_slice_report(
    *,
    slice_type: str,
    slice_label: str,
    first_group: pd.DataFrame,
    later_group: pd.DataFrame,
    first_loss_total: float,
) -> DiagnosticSliceReport:
    first_expectancy = float(first_group["pnl_pips"].mean()) if not first_group.empty else 0.0
    later_expectancy = float(later_group["pnl_pips"].mean()) if not later_group.empty else 0.0
    loss_share = (
        float(abs(first_group.loc[first_group["pnl_pips"] < 0, "pnl_pips"].sum()) / first_loss_total)
        if not first_group.empty
        else 0.0
    )
    first_pf = _profit_factor(first_group["pnl_pips"]) if not first_group.empty else 0.0
    later_pf = _profit_factor(later_group["pnl_pips"]) if not later_group.empty else 0.0
    expectancy_improvement = later_expectancy - first_expectancy
    evidence_score = ((loss_share * 3) + max(expectancy_improvement, 0.0) + max(0.9 - first_pf, 0.0))
    supported = (
        len(first_group) >= 10
        and first_expectancy < -0.2
        and expectancy_improvement >= 0.75
        and loss_share >= 0.25
    )
    return DiagnosticSliceReport(
        slice_type=slice_type,  # type: ignore[arg-type]
        slice_label=slice_label,
        first_window_trade_count=int(len(first_group)),
        later_window_trade_count=int(len(later_group)),
        first_window_profit_factor=first_pf,
        later_window_profit_factor=later_pf,
        first_window_expectancy_pips=first_expectancy,
        later_window_expectancy_pips=later_expectancy,
        expectancy_improvement_pips=expectancy_improvement,
        first_window_loss_share=loss_share,
        evidence_score=round(float(evidence_score), 6),
        supported=supported,
    )


def _build_spread_slice(first_window: pd.DataFrame, later_windows: pd.DataFrame) -> DiagnosticSliceReport | None:
    if "is_spread_anomaly" not in first_window.columns:
        return None
    first_rate = float(first_window["is_spread_anomaly"].mean()) if not first_window.empty else 0.0
    later_rate = float(later_windows["is_spread_anomaly"].mean()) if not later_windows.empty else 0.0
    supported = first_rate >= 0.1 and first_rate >= max(later_rate * 1.5, 0.1)
    return DiagnosticSliceReport(
        slice_type="spread_anomaly",
        slice_label="spread_anomaly",
        first_window_trade_count=int(first_window["is_spread_anomaly"].sum()),
        later_window_trade_count=int(later_windows["is_spread_anomaly"].sum()),
        first_window_profit_factor=first_rate,
        later_window_profit_factor=later_rate,
        first_window_expectancy_pips=first_rate,
        later_window_expectancy_pips=later_rate,
        expectancy_improvement_pips=first_rate - later_rate,
        first_window_loss_share=first_rate,
        evidence_score=round(first_rate * 5, 6),
        supported=supported,
    )


def _build_next_recommendations(
    settings: Settings,
    *,
    candidate_reports: list[CandidateDiagnosticReport],
    candidate_scope: list[str],
) -> list[NextStepRecommendation]:
    if not candidate_reports:
        return []
    primary = next((report for report in candidate_reports if report.candidate_id == candidate_scope[0]), candidate_reports[0])
    if len(candidate_reports) == 1:
        session_slice = next(
            (
                item
                for item in primary.supported_slices
                if item.slice_type == "session_bucket" and item.slice_label in SESSION_BUCKET_HOURS
            ),
            None,
        )
        if session_slice:
            hours = _recommended_session_hours(primary, session_slice.slice_label)
            session_trim_policy = _session_trim_policy(primary)
            mutation_payload = {
                "mutation_type": "trim_allowed_hours",
                "session_bucket": session_slice.slice_label,
                "removed_hours_utc": hours,
            }
            if session_trim_policy["enable_news_blackout"]:
                mutation_payload["enable_news_blackout"] = True
            if (
                0 < len(hours) <= session_trim_policy["max_removed_hours"]
                and not _session_trim_would_clear_schedule(primary, hours)
                and not _mutation_already_explored(
                    settings,
                    source_candidate_id=primary.candidate_id,
                    mutation_payload=mutation_payload,
                )
            ):
                blackout_rationale = (
                    " and enable the governed calendar blackout"
                    if session_trim_policy["enable_news_blackout"]
                    else ""
                )
                return [
                    NextStepRecommendation(
                        step_type="mutate_one_candidate",
                        candidate_id=primary.candidate_id,
                        rationale=(
                            f"The failed first walk-forward window is weakest in the {session_slice.slice_label} "
                            f"session slice for {primary.candidate_id}. The next bounded campaign should remove "
                            f"hours {hours} from allowed_hours_utc{blackout_rationale}, then re-evaluate without "
                            "broadening scope."
                        ),
                        binding=True,
                        evidence_status="supported",
                        step_payload=mutation_payload,
                    )
                ]
        for context_slice in (item for item in primary.supported_slices if item.slice_type == "context_bucket"):
            mutation_payload = {
                "mutation_type": "suppress_context_bucket",
                "context_bucket": context_slice.slice_label,
            }
            if _mutation_already_explored(
                settings,
                source_candidate_id=primary.candidate_id,
                mutation_payload=mutation_payload,
            ):
                continue
            return [
                NextStepRecommendation(
                    step_type="mutate_one_candidate",
                    candidate_id=primary.candidate_id,
                    rationale=(
                        f"The failed first walk-forward window is weakest in {context_slice.slice_label} trades "
                        f"for {primary.candidate_id}. The next bounded campaign should test one family-consistent "
                        f"filter adjustment that suppresses that context bucket."
                    ),
                    binding=True,
                    evidence_status="supported",
                    step_payload=mutation_payload,
                )
            ]
        if primary.supported_slices:
            return [
                NextStepRecommendation(
                    step_type="hypothesis_audit",
                    candidate_id=primary.candidate_id,
                    rationale=(
                        f"{primary.candidate_id} still shows a supported structural weakness, but no single bounded "
                        "mutation remains narrow enough to justify another direct change. The next governed step "
                        "should be a hypothesis audit before further search."
                    ),
                    binding=True,
                    evidence_status="supported",
                    step_payload={"source_candidate_id": primary.candidate_id},
                )
            ]
        return []
    secondary = next((report for report in candidate_reports if report.candidate_id == candidate_scope[-1]), candidate_reports[-1])
    common_session = _shared_supported_slice(candidate_reports, "session_bucket")
    if common_session and common_session.slice_label in SESSION_BUCKET_HOURS:
        hours = _recommended_session_hours(primary, common_session.slice_label)
        session_trim_policy = _session_trim_policy(primary)
        mutation_payload = {
            "mutation_type": "trim_allowed_hours",
            "session_bucket": common_session.slice_label,
            "removed_hours_utc": hours,
        }
        if session_trim_policy["enable_news_blackout"]:
            mutation_payload["enable_news_blackout"] = True
        if (
            0 < len(hours) <= session_trim_policy["max_removed_hours"]
            and not _session_trim_would_clear_schedule(primary, hours)
            and not _mutation_already_explored(
                settings,
                source_candidate_id=primary.candidate_id,
                mutation_payload=mutation_payload,
            )
        ):
            blackout_rationale = (
                " and enable the governed calendar blackout"
                if session_trim_policy["enable_news_blackout"]
                else ""
            )
            return [
                NextStepRecommendation(
                    step_type="mutate_one_candidate",
                    candidate_id=primary.candidate_id,
                    rationale=(
                        f"The failed first walk-forward window is consistently weakest in the {common_session.slice_label} "
                        f"session slice for {primary.candidate_id} and {secondary.candidate_id}. The next bounded campaign "
                        f"should apply one narrow session adjustment to {primary.candidate_id} by removing overlap hours "
                        f"{hours} from allowed_hours_utc{blackout_rationale}, then re-evaluate without broadening scope."
                    ),
                    binding=True,
                    evidence_status="supported",
                    step_payload=mutation_payload,
                )
            ]
    common_context = _shared_supported_slice(candidate_reports, "context_bucket")
    if common_context and not _mutation_already_explored(
        settings,
        source_candidate_id=primary.candidate_id,
        mutation_payload={
            "mutation_type": "suppress_context_bucket",
            "context_bucket": common_context.slice_label,
        },
    ):
        return [
            NextStepRecommendation(
                step_type="mutate_one_candidate",
                candidate_id=primary.candidate_id,
                rationale=(
                    f"The failed first walk-forward window is consistently weakest in {common_context.slice_label} trades "
                    f"for {primary.candidate_id} and {secondary.candidate_id}. The next bounded campaign should test one "
                    f"family-consistent filter adjustment on {primary.candidate_id} that suppresses that context bucket."
                ),
                binding=True,
                evidence_status="supported",
                step_payload={
                    "mutation_type": "suppress_context_bucket",
                    "context_bucket": common_context.slice_label,
                },
            )
        ]
    if primary.supported_slices or secondary.supported_slices:
        return [
            NextStepRecommendation(
                step_type="hypothesis_audit",
                candidate_id=primary.candidate_id,
                rationale=(
                    f"{primary.candidate_id} and {secondary.candidate_id} still show supported structural weakness, "
                    "but no single bounded mutation remains narrow enough to justify another direct change. The "
                    "next governed step should be a hypothesis audit before further search."
                ),
                binding=True,
                evidence_status="supported",
                step_payload={"source_candidate_id": primary.candidate_id},
            )
        ]
    return []


def _shared_supported_slice(
    candidate_reports: list[CandidateDiagnosticReport],
    slice_type: str,
) -> DiagnosticSliceReport | None:
    common_labels: set[str] | None = None
    by_candidate: dict[str, dict[str, DiagnosticSliceReport]] = {}
    for report in candidate_reports:
        supported = {item.slice_label: item for item in report.supported_slices if item.slice_type == slice_type}
        by_candidate[report.candidate_id] = supported
        labels = set(supported)
        common_labels = labels if common_labels is None else common_labels & labels
    if not common_labels:
        return None
    return max(
        (by_candidate[candidate_reports[0].candidate_id][label] for label in common_labels),
        key=lambda item: item.evidence_score,
    )


def _recommended_session_hours(report: CandidateDiagnosticReport, bucket: str) -> list[int]:
    allowed_hours = _allowed_session_hours(report)
    return [hour for hour in allowed_hours if hour in SESSION_BUCKET_HOURS.get(bucket, [])]


def _allowed_session_hours(report: CandidateDiagnosticReport) -> list[int]:
    spec_path = Path(report.artifact_paths["review_packet_path"]).parent / "strategy_spec.json"
    spec_payload = read_json(spec_path)
    return list(
        (
            ((spec_payload.get("session_policy") or {}).get("allowed_hours_utc"))
            or spec_payload.get("session_policy", {}).get("allowed_hours_utc", [])
        )
    )


def _session_trim_would_clear_schedule(report: CandidateDiagnosticReport, removed_hours: list[int]) -> bool:
    allowed_hours = _allowed_session_hours(report)
    kept_hours = [hour for hour in allowed_hours if hour not in set(removed_hours)]
    return not kept_hours


def _session_trim_policy(report: CandidateDiagnosticReport) -> dict[str, object]:
    spec_path = Path(report.artifact_paths["review_packet_path"]).parent / "strategy_spec.json"
    spec_payload = read_json(spec_path)
    family = str(spec_payload.get("family") or "")
    news_enabled = bool((spec_payload.get("news_policy") or {}).get("enabled"))
    is_research_family = family.endswith("_research")
    return {
        "max_removed_hours": 4 if is_research_family else 2,
        "enable_news_blackout": is_research_family and not news_enabled,
    }


def _recommend_mutation(candidate_id: str, slice_report: DiagnosticSliceReport, spec_path: Path) -> str | None:
    if slice_report.slice_type == "session_bucket" and slice_report.slice_label in SESSION_BUCKET_HOURS:
        spec_payload = read_json(spec_path)
        allowed_hours = ((spec_payload.get("session_policy") or {}).get("allowed_hours_utc")) or []
        affected_hours = [hour for hour in allowed_hours if hour in SESSION_BUCKET_HOURS[slice_report.slice_label]]
        if affected_hours:
            return (
                f"Trim {slice_report.slice_label} exposure by removing allowed_hours_utc {affected_hours} "
                f"inside the current breakout family."
            )
    if slice_report.slice_type == "context_bucket" and slice_report.slice_label == "mean_reversion_context":
        return (
            f"Add one narrow filter that suppresses {slice_report.slice_label} entries "
            f"inside the current breakout family."
        )
    return None


def _candidate_notes(
    first_window: pd.DataFrame,
    later_windows: pd.DataFrame,
    anomaly_threshold: float,
    supported_slices: list[DiagnosticSliceReport],
) -> list[str]:
    notes = [
        f"First walk-forward window spans {len(first_window)} trades; later windows span {len(later_windows)} trades.",
        f"Spread anomaly threshold from QA is {round(anomaly_threshold, 6)} pips.",
    ]
    if first_window.empty:
        notes.append("No trades were present in the first walk-forward window.")
        return notes
    first_anomaly_rate = float(first_window["is_spread_anomaly"].mean()) if "is_spread_anomaly" in first_window.columns else 0.0
    if first_anomaly_rate == 0.0:
        notes.append("Spread anomalies do not explain the failed first walk-forward window in this candidate.")
    if not supported_slices:
        notes.append("No single supported session, context, or spread slice was strong enough to justify mutation.")
    return notes


def _assign_walk_forward_windows(row_count: int, windows: int) -> list[int]:
    if row_count <= 0:
        return []
    window_size = max(math.floor(row_count / max(windows, 1)), 1)
    return [1 + min(index // window_size, windows - 1) for index in range(row_count)]


def _load_parent_controller_report(settings: Settings, parent_state: CampaignState) -> NextStepControllerReport | None:
    if parent_state.last_report_path is None:
        return None
    report_path = Path(parent_state.last_report_path)
    return _load_controller_report_from_path(settings, report_path)


def _load_controller_report_for_campaign(settings: Settings, campaign_id: str | None) -> NextStepControllerReport | None:
    if not campaign_id:
        return None
    report_path = settings.paths().campaigns_dir / campaign_id / "next_step_report.json"
    return _load_controller_report_from_path(settings, report_path)


def _load_controller_report_from_path(settings: Settings, report_path: Path) -> NextStepControllerReport | None:
    if not report_path.exists():
        return None
    payload = read_json(report_path)
    if payload.get("continuation_status") is None:
        payload["continuation_status"] = "stop"
    if payload.get("stop_class") is None:
        payload["stop_class"] = "ambiguity"
    if payload.get("auto_continue_allowed") is None:
        payload["auto_continue_allowed"] = False
    if payload.get("max_safe_follow_on_steps") is None:
        payload["max_safe_follow_on_steps"] = 0
    if payload.get("transition_status") is None:
        payload["transition_status"] = "hard_stop"
    report = NextStepControllerReport.model_validate(payload)
    if (
        payload.get("continuation_status") == "stop"
        and payload.get("stop_class") == "ambiguity"
        and report.selected_step_type is not None
    ):
        _apply_continuation_metadata(settings, report)
    return report


def _derive_hypothesis_audit_scope(
    settings: Settings,
    *,
    parent_spec: CampaignSpec,
    parent_state: CampaignState,
    parent_report: NextStepControllerReport,
) -> list[str]:
    scoped_candidate_ids = list(parent_report.candidate_scope or _candidate_scope(parent_spec, parent_state))
    lane_entry_style = _resolve_lane_entry_style(
        settings,
        candidate_ids=scoped_candidate_ids,
        fallback_candidate_id=parent_spec.baseline_candidate_id,
    )
    reference_candidate_id = _select_reference_candidate_id(
        settings,
        family=parent_spec.family,
        entry_style=lane_entry_style,
        exclude_candidate_ids=scoped_candidate_ids,
    )
    if reference_candidate_id:
        scoped_candidate_ids.append(reference_candidate_id)
    archived_candidate_id = _select_recent_archived_candidate_id(
        settings,
        family=parent_spec.family,
        entry_style=lane_entry_style,
        exclude_candidate_ids=scoped_candidate_ids,
    )
    if archived_candidate_id:
        scoped_candidate_ids.append(archived_candidate_id)
    return list(dict.fromkeys(scoped_candidate_ids))[:3]


def _resolve_lane_entry_style(
    settings: Settings,
    *,
    candidate_ids: list[str],
    fallback_candidate_id: str | None,
) -> str | None:
    for candidate_id in [*candidate_ids, fallback_candidate_id]:
        if not candidate_id:
            continue
        spec_path = settings.paths().reports_dir / candidate_id / "strategy_spec.json"
        if not spec_path.exists():
            continue
        payload = read_json(spec_path)
        entry_style = str(payload.get("entry_style") or "").strip()
        if entry_style:
            return entry_style
    return None


def _select_reference_candidate_id(
    settings: Settings,
    *,
    family: str,
    entry_style: str | None,
    exclude_candidate_ids: list[str],
) -> str | None:
    for record in reversed(_load_failure_records(settings)):
        if not bool((record.get("details") or {}).get("reference_branch")):
            continue
        candidate_id = str(record.get("candidate_id") or "")
        if not candidate_id or candidate_id in exclude_candidate_ids:
            continue
        if not _candidate_matches_lane(settings, candidate_id, family=family, entry_style=entry_style):
            continue
        if _hypothesis_audit_artifacts_exist(settings, candidate_id):
            return candidate_id

    summaries: list[HypothesisAuditCandidateSummary] = []
    for report_dir in settings.paths().reports_dir.glob("AF-CAND-*"):
        candidate_id = report_dir.name
        if candidate_id in exclude_candidate_ids:
            continue
        if not _candidate_matches_lane(settings, candidate_id, family=family, entry_style=entry_style):
            continue
        if not _hypothesis_audit_artifacts_exist(settings, candidate_id):
            continue
        summaries.append(_build_hypothesis_audit_candidate_summary(settings, candidate_id))
    reference_summary = _select_hypothesis_reference_summary(summaries)
    return reference_summary.candidate_id if reference_summary else None


def _select_recent_archived_candidate_id(
    settings: Settings,
    *,
    family: str,
    entry_style: str | None,
    exclude_candidate_ids: list[str],
) -> str | None:
    for record in reversed(_load_failure_records(settings)):
        details = record.get("details") or {}
        decision = str(details.get("decision") or "")
        if not decision.startswith("archive_"):
            continue
        candidate_id = str(record.get("candidate_id") or "")
        if not candidate_id or candidate_id in exclude_candidate_ids:
            continue
        if not _candidate_matches_lane(settings, candidate_id, family=family, entry_style=entry_style):
            continue
        if _hypothesis_audit_artifacts_exist(settings, candidate_id):
            return candidate_id
    return None


def _candidate_matches_lane(
    settings: Settings,
    candidate_id: str,
    *,
    family: str,
    entry_style: str | None,
) -> bool:
    spec_path = settings.paths().reports_dir / candidate_id / "strategy_spec.json"
    if not spec_path.exists():
        return False
    payload = read_json(spec_path)
    if str(payload.get("family") or "") != family:
        return False
    if entry_style is None:
        return True
    return str(payload.get("entry_style") or "") == entry_style


def _hypothesis_audit_artifacts_exist(settings: Settings, candidate_id: str) -> bool:
    report_dir = settings.paths().reports_dir / candidate_id
    return (
        (report_dir / "strategy_spec.json").exists()
        and (report_dir / "review_packet.json").exists()
        and (report_dir / "robustness_report.json").exists()
    )


def _load_failure_records(settings: Settings) -> list[dict[str, object]]:
    path = settings.paths().observational_knowledge_dir / "failure_records.jsonl"
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def _candidate_is_archived(settings: Settings, candidate_id: str) -> bool:
    for record in reversed(_load_failure_records(settings)):
        if str(record.get("candidate_id") or "") != candidate_id:
            continue
        decision = str((record.get("details") or {}).get("decision") or "")
        if decision.startswith("archive_"):
            return True
        if decision:
            return False
    return False


def _build_hypothesis_audit_candidate_summary(
    settings: Settings,
    candidate_id: str,
) -> HypothesisAuditCandidateSummary:
    report_dir = settings.paths().reports_dir / candidate_id
    spec_payload = read_json(report_dir / "strategy_spec.json")
    review_payload = read_json(report_dir / "review_packet.json")
    robustness_payload = read_json(report_dir / "robustness_report.json")
    metrics = review_payload.get("metrics") or {}
    grades = metrics.get("grades") or {}
    review_robustness = metrics.get("robustness_report") or {}
    return HypothesisAuditCandidateSummary(
        candidate_id=candidate_id,
        family=str(spec_payload.get("family") or review_payload.get("family") or "unknown"),
        entry_style=spec_payload.get("entry_style"),
        readiness_status=str(
            review_payload.get("readiness")
            or metrics.get("readiness_status")
            or robustness_payload.get("status")
            or "ea_spec_complete"
        ),
        trade_count=int(metrics.get("trade_count") or 0),
        profit_factor=float(metrics.get("profit_factor") or 0.0),
        out_of_sample_profit_factor=float(metrics.get("out_of_sample_profit_factor") or 0.0),
        expectancy_pips=float(metrics.get("expectancy_pips") or 0.0),
        stress_passed=bool(metrics.get("stress_passed") or grades.get("stress_ok")),
        walk_forward_ok=bool(grades.get("walk_forward_ok")),
        pbo=_as_optional_float(robustness_payload.get("pbo", review_robustness.get("pbo"))),
        white_reality_check_p_value=_as_optional_float(
            robustness_payload.get(
                "white_reality_check_p_value",
                review_robustness.get("white_reality_check_p_value"),
            )
        ),
        archived=_candidate_is_archived(settings, candidate_id),
        artifact_paths={
            "strategy_spec_path": str(report_dir / "strategy_spec.json"),
            "review_packet_path": str(report_dir / "review_packet.json"),
            "robustness_report_path": str(report_dir / "robustness_report.json"),
        },
    )


def _select_hypothesis_reference_summary(
    candidate_summaries: list[HypothesisAuditCandidateSummary],
) -> HypothesisAuditCandidateSummary | None:
    if not candidate_summaries:
        return None
    return max(
        candidate_summaries,
        key=lambda item: (
            0 if item.archived else 1,
            1 if item.stress_passed else 0,
            1 if item.walk_forward_ok else 0,
            -(item.pbo if item.pbo is not None else 1.0),
            -(item.white_reality_check_p_value if item.white_reality_check_p_value is not None else 1.0),
            item.expectancy_pips,
            item.out_of_sample_profit_factor,
            item.trade_count,
        ),
    )


def _resolve_hypothesis_lane_decision(
    candidate_summaries: list[HypothesisAuditCandidateSummary],
    reference_summary: HypothesisAuditCandidateSummary | None,
    settings: Settings,
) -> str:
    if not candidate_summaries:
        return "insufficient_evidence"
    if reference_summary and not reference_summary.archived:
        if _summary_clears_research_gates(reference_summary, settings):
            return "narrow_correction_supported"
        return "hold_reference_blocked_by_robustness"
    return "retire_lane"


def _hypothesis_audit_should_hold_reference(
    parent_report: NextStepControllerReport | None,
    reference_summary: HypothesisAuditCandidateSummary | None,
) -> bool:
    if parent_report is None or reference_summary is None:
        return False
    if parent_report.selected_step_type != "diagnose_existing_candidates":
        return False
    binding_follow_on = next(
        (
            item
            for item in parent_report.next_recommendations
            if item.binding and item.evidence_status == "supported"
        ),
        None,
    )
    if binding_follow_on is not None:
        return (
            binding_follow_on.step_type == "hypothesis_audit"
            and binding_follow_on.candidate_id == reference_summary.candidate_id
        )
    return (
        parent_report.stop_reason == "diagnosis_ambiguous_no_mutation_justified"
        and not parent_report.next_recommendations
    )


def _summary_clears_research_gates(summary: HypothesisAuditCandidateSummary, settings: Settings) -> bool:
    validation = settings.validation
    if summary.trade_count < validation.minimum_test_trade_count:
        return False
    if summary.expectancy_pips <= validation.expectancy_floor:
        return False
    if summary.out_of_sample_profit_factor < validation.out_of_sample_profit_factor_floor:
        return False
    if not summary.stress_passed or not summary.walk_forward_ok:
        return False
    if summary.pbo is not None and summary.pbo > validation.pbo_threshold:
        return False
    if (
        summary.white_reality_check_p_value is not None
        and summary.white_reality_check_p_value > validation.white_reality_check_pvalue_threshold
    ):
        return False
    return True


def _collect_hypothesis_failure_modes(
    candidate_summaries: list[HypothesisAuditCandidateSummary],
    settings: Settings,
) -> list[str]:
    validation = settings.validation
    failure_modes: list[str] = []
    if any(not item.walk_forward_ok for item in candidate_summaries):
        failure_modes.append("walk_forward_instability")
    if any(not item.stress_passed for item in candidate_summaries):
        failure_modes.append("execution_cost_stress_failure")
    if any(item.expectancy_pips <= validation.expectancy_floor for item in candidate_summaries):
        failure_modes.append("negative_or_flat_expectancy")
    if any(item.trade_count < validation.minimum_test_trade_count for item in candidate_summaries):
        failure_modes.append("insufficient_trade_count")
    if any(item.pbo is not None and item.pbo > validation.pbo_threshold for item in candidate_summaries):
        failure_modes.append("search_adjusted_robustness_failure")
    if any(
        item.white_reality_check_p_value is not None
        and item.white_reality_check_p_value > validation.white_reality_check_pvalue_threshold
        for item in candidate_summaries
    ):
        failure_modes.append("white_reality_check_failure")
    return failure_modes


def _build_hypothesis_audit_summary(
    *,
    candidate_summaries: list[HypothesisAuditCandidateSummary],
    reference_summary: HypothesisAuditCandidateSummary | None,
    lane_decision: str,
) -> str:
    audited_ids = ", ".join(item.candidate_id for item in candidate_summaries) or "no candidates"
    if lane_decision == "hold_reference_blocked_by_robustness" and reference_summary:
        archived_ids = ", ".join(
            item.candidate_id for item in candidate_summaries if item.archived and item.candidate_id != reference_summary.candidate_id
        ) or "no archived comparators"
        return (
            f"Hypothesis audit compared {audited_ids}. {reference_summary.candidate_id} remains the strongest empirical "
            f"reference branch, but it is still blocked by walk-forward or search-adjusted robustness gates. Archived "
            f"comparators {archived_ids} do not justify continuing mutation in the current lane."
        )
    if lane_decision == "retire_lane":
        return (
            f"Hypothesis audit compared {audited_ids}. No non-archived candidate in the current lane remains strong enough "
            "to justify another bounded mutation under the current governance model."
        )
    if lane_decision == "narrow_correction_supported" and reference_summary:
        return (
            f"Hypothesis audit compared {audited_ids}. {reference_summary.candidate_id} clears the current research gates "
            "well enough to justify one additional bounded correction from the audited reference branch."
        )
    return f"Hypothesis audit compared {audited_ids}, but the available evidence is not strong enough to justify a lane decision."


def _build_hypothesis_audit_actions(
    *,
    lane_decision: str,
    reference_summary: HypothesisAuditCandidateSummary | None,
) -> list[str]:
    if lane_decision == "hold_reference_blocked_by_robustness" and reference_summary:
        return [
            f"Keep {reference_summary.candidate_id} as the empirical reference branch at robustness_provisional.",
            "Do not run MT5 parity or forward on this lane.",
            "Stop further mutation in this lane until a separate hypothesis, data, or regime audit justifies one bounded correction.",
        ]
    if lane_decision == "retire_lane":
        return [
            "Retire the current strategy lane from further mutation.",
            "Open a new hypothesis-family campaign instead of continuing search inside this exhausted lane.",
        ]
    if lane_decision == "narrow_correction_supported" and reference_summary:
        return [
            f"Use {reference_summary.candidate_id} as the only approved source branch for one additional bounded correction.",
            "Stop again after that correction and reevaluation.",
        ]
    return [
        "Stop and gather more evidence before opening another campaign in this lane.",
    ]


def _build_hypothesis_audit_recommendations(
    *,
    lane_decision: str,
    reference_summary: HypothesisAuditCandidateSummary | None,
) -> list[NextStepRecommendation]:
    if lane_decision != "narrow_correction_supported" or reference_summary is None:
        return []
    return [
        NextStepRecommendation(
            step_type="diagnose_existing_candidates",
            candidate_id=reference_summary.candidate_id,
            rationale=(
                f"{reference_summary.candidate_id} remains the strongest audited reference branch and still clears the "
                "research promotion gates. Run one fresh bounded diagnosis on that branch to justify exactly one more "
                "correction before any further lane expansion or retirement."
            ),
            binding=True,
            evidence_status="supported",
            step_payload={
                "source_candidate_id": reference_summary.candidate_id,
                "audit_origin": "hypothesis_audit",
            },
        )
    ]


def _as_optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_data_regime_slice_summaries(settings: Settings, candidate_id: str) -> list[DataRegimeSliceSummary]:
    ledger_path = settings.paths().reports_dir / candidate_id / "trade_ledger.csv"
    review_path = settings.paths().reports_dir / candidate_id / "review_packet.json"
    if not ledger_path.exists() or not review_path.exists():
        return []
    trade_frame = pd.read_csv(ledger_path)
    if trade_frame.empty or "pnl_pips" not in trade_frame.columns:
        return []
    review_payload = read_json(review_path)
    walk_forward_summary = (review_payload.get("metrics") or {}).get("walk_forward_summary") or []
    windows = max(len(walk_forward_summary), 1)
    trade_frame["wf_window"] = _assign_walk_forward_windows(len(trade_frame), windows)
    first_window = trade_frame[trade_frame["wf_window"] == 1].copy()
    later_windows = trade_frame[trade_frame["wf_window"] > 1].copy()
    if first_window.empty:
        return []

    total_first_window_losses = abs(first_window["pnl_pips"].clip(upper=0).sum()) or 1e-9
    summaries: list[DataRegimeSliceSummary] = []
    for slice_type in ("session_bucket", "context_bucket", "volatility_bucket"):
        if slice_type not in trade_frame.columns:
            continue
        first_groups = first_window.groupby(slice_type)["pnl_pips"].agg(["count", "mean", "sum"])
        later_groups = later_windows.groupby(slice_type)["pnl_pips"].agg(["count", "mean", "sum"]) if not later_windows.empty else pd.DataFrame()
        slice_labels = list(dict.fromkeys(list(first_groups.index) + list(later_groups.index)))
        for slice_label in slice_labels:
            first_count = int(first_groups.loc[slice_label, "count"]) if slice_label in first_groups.index else 0
            later_count = int(later_groups.loc[slice_label, "count"]) if slice_label in later_groups.index else 0
            first_mean = float(first_groups.loc[slice_label, "mean"]) if slice_label in first_groups.index else 0.0
            later_mean = float(later_groups.loc[slice_label, "mean"]) if slice_label in later_groups.index else 0.0
            first_sum = float(first_groups.loc[slice_label, "sum"]) if slice_label in first_groups.index else 0.0
            first_loss_share = abs(min(first_sum, 0.0)) / total_first_window_losses
            first_trade_share = first_count / max(len(first_window), 1)
            delta_mean = later_mean - first_mean
            supported = _supports_narrow_regime_correction(
                slice_type=slice_type,
                first_count=first_count,
                first_trade_share=first_trade_share,
                first_loss_share=first_loss_share,
                delta_mean=delta_mean,
            )
            summaries.append(
                DataRegimeSliceSummary(
                    slice_type=slice_type,
                    slice_label=str(slice_label),
                    first_window_trade_count=first_count,
                    later_window_trade_count=later_count,
                    first_window_expectancy_pips=first_mean,
                    later_window_expectancy_pips=later_mean,
                    expectancy_delta_pips=delta_mean,
                    first_window_loss_share=first_loss_share,
                    first_window_trade_share=first_trade_share,
                    supported_narrow_correction=supported,
                )
            )
    return sorted(
        summaries,
        key=lambda item: (
            1 if item.supported_narrow_correction else 0,
            item.first_window_loss_share,
            item.expectancy_delta_pips,
            item.first_window_trade_count,
        ),
        reverse=True,
    )


def _supports_narrow_regime_correction(
    *,
    slice_type: str,
    first_count: int,
    first_trade_share: float,
    first_loss_share: float,
    delta_mean: float,
) -> bool:
    if slice_type == "volatility_bucket":
        return False
    if first_count < 12:
        return False
    if first_trade_share > 0.40:
        return False
    if first_loss_share < 0.30:
        return False
    if delta_mean < 1.0:
        return False
    return True


def _select_supported_data_regime_slice(
    slice_summaries: list[DataRegimeSliceSummary],
) -> DataRegimeSliceSummary | None:
    return next((item for item in slice_summaries if item.supported_narrow_correction), None)


def _resolve_data_regime_lane_decision(
    slice_summaries: list[DataRegimeSliceSummary],
    reference_summary: HypothesisAuditCandidateSummary | None,
    settings: Settings,
) -> str:
    supported_slice = _select_supported_data_regime_slice(slice_summaries)
    if supported_slice is not None and reference_summary is not None:
        return "narrow_correction_supported"
    if reference_summary is None:
        return "insufficient_evidence"
    if not reference_summary.walk_forward_ok and (reference_summary.pbo or 1.0) > settings.validation.pbo_threshold:
        return "retire_lane"
    return "structural_regime_instability"


def _build_data_regime_summary(
    *,
    candidate_summaries: list[HypothesisAuditCandidateSummary],
    reference_summary: HypothesisAuditCandidateSummary | None,
    slice_summaries: list[DataRegimeSliceSummary],
    lane_decision: str,
) -> str:
    audited_ids = ", ".join(item.candidate_id for item in candidate_summaries) or "no candidates"
    top_modes = ", ".join(item.slice_label for item in slice_summaries[:3]) or "no concentrated regime slices"
    if lane_decision == "narrow_correction_supported" and reference_summary is not None:
        supported_slice = _select_supported_data_regime_slice(slice_summaries)
        return (
            f"Data/regime audit compared {audited_ids}. {reference_summary.candidate_id} remains the reference branch and "
            f"the failed first walk-forward window is concentrated enough in {supported_slice.slice_type}={supported_slice.slice_label} "
            "to justify one additional bounded correction."
        )
    if lane_decision == "retire_lane" and reference_summary is not None:
        return (
            f"Data/regime audit compared {audited_ids}. {reference_summary.candidate_id} remains the strongest empirical branch, "
            f"but the failed first walk-forward window is broadly weak across {top_modes}, so no narrow correction is justified."
        )
    if lane_decision == "structural_regime_instability" and reference_summary is not None:
        return (
            f"Data/regime audit compared {audited_ids}. {reference_summary.candidate_id} shows persistent first-window instability "
            f"across {top_modes}, which points to structural regime dependence rather than one repairable slice."
        )
    return f"Data/regime audit compared {audited_ids}, but the evidence was insufficient to support a bounded correction."


def _build_data_regime_actions(
    *,
    lane_decision: str,
    reference_summary: HypothesisAuditCandidateSummary | None,
    supported_slice: DataRegimeSliceSummary | None,
) -> list[str]:
    if lane_decision == "narrow_correction_supported" and reference_summary is not None and supported_slice is not None:
        return [
            f"Use {reference_summary.candidate_id} as the only source branch for one additional bounded correction.",
            f"Constrain the correction to {supported_slice.slice_type}={supported_slice.slice_label}.",
            "Stop again immediately after that correction and reevaluation.",
        ]
    if lane_decision in {"retire_lane", "structural_regime_instability"}:
        return [
            "Retire the current strategy lane from further mutation.",
            "Do not run MT5 parity or forward on this lane.",
            "Open a different hypothesis class or perform a separate data/feature audit before resuming search.",
        ]
    return [
        "Stop and collect more evidence before changing the current lane.",
    ]


def _build_data_regime_recommendations(
    *,
    reference_summary: HypothesisAuditCandidateSummary | None,
    supported_slice: DataRegimeSliceSummary | None,
    lane_decision: str,
) -> list[NextStepRecommendation]:
    if lane_decision != "narrow_correction_supported" or reference_summary is None or supported_slice is None:
        return []
    step_payload = _data_regime_mutation_payload(supported_slice)
    if not step_payload:
        return []
    return [
        NextStepRecommendation(
            step_type="mutate_one_candidate",
            candidate_id=reference_summary.candidate_id,
            rationale=(
                f"Reference branch {reference_summary.candidate_id} shows a concentrated failed first-window slice at "
                f"{supported_slice.slice_type}={supported_slice.slice_label}; apply one bounded correction and reevaluate."
            ),
            binding=True,
            evidence_status="supported",
            step_payload=step_payload,
        )
    ]


def _data_regime_mutation_payload(slice_summary: DataRegimeSliceSummary) -> dict[str, object]:
    if slice_summary.slice_type == "context_bucket":
        return {
            "mutation_type": "suppress_context_bucket",
            "context_bucket": slice_summary.slice_label,
        }
    if slice_summary.slice_type == "session_bucket":
        removed_hours = SESSION_BUCKET_HOURS.get(slice_summary.slice_label)
        if removed_hours:
            return {
                "mutation_type": "trim_allowed_hours",
                "removed_hours_utc": removed_hours,
            }
    return {}


def _derive_data_feature_audit_scope(
    settings: Settings,
    *,
    family: str,
    parent_report: NextStepControllerReport | None,
) -> list[str]:
    seed_candidate_ids: list[str] = []
    if parent_report is not None:
        if parent_report.data_regime_audit_reports:
            seed_candidate_ids.extend(parent_report.data_regime_audit_reports[0].audited_candidate_ids)
        elif parent_report.candidate_scope:
            seed_candidate_ids.extend(parent_report.candidate_scope)

    contract_fingerprint = _select_data_feature_contract_anchor(
        settings,
        family=family,
        candidate_ids=seed_candidate_ids,
    )
    scoped_candidate_ids: list[str] = []

    def _try_add(candidate_id: str) -> None:
        if not candidate_id or candidate_id in scoped_candidate_ids:
            return
        if not _candidate_matches_lane(settings, candidate_id, family=family, entry_style=None):
            return
        if not _hypothesis_audit_artifacts_exist(settings, candidate_id):
            return
        if contract_fingerprint is not None:
            candidate_contract = _load_candidate_family_audit_fingerprint(settings, candidate_id)
            if candidate_contract != contract_fingerprint:
                return
        scoped_candidate_ids.append(candidate_id)

    for candidate_id in seed_candidate_ids:
        _try_add(candidate_id)

    for record in reversed(_load_failure_records(settings)):
        candidate_id = str(record.get("candidate_id") or "")
        details = record.get("details") or {}
        reference_candidate_id = str(details.get("reference_candidate_id") or "")
        for item in (reference_candidate_id, candidate_id):
            _try_add(item)
        if len(scoped_candidate_ids) >= 6:
            break

    recent_candidates: list[tuple[float, str]] = []
    for report_dir in settings.paths().reports_dir.glob("AF-CAND-*"):
        candidate_id = report_dir.name
        if candidate_id in scoped_candidate_ids:
            continue
        if contract_fingerprint is not None:
            candidate_contract = _load_candidate_family_audit_fingerprint(settings, candidate_id)
            if candidate_contract != contract_fingerprint:
                continue
        recency = _candidate_audit_recency(settings, candidate_id)
        if recency <= 0.0:
            continue
        recent_candidates.append((recency, candidate_id))
    for _, candidate_id in sorted(recent_candidates, reverse=True):
        _try_add(candidate_id)
        if len(scoped_candidate_ids) >= 6:
            break
    return list(dict.fromkeys(scoped_candidate_ids))[:6]


def _select_data_feature_contract_anchor(
    settings: Settings,
    *,
    family: str,
    candidate_ids: list[str],
) -> tuple[str, str, str] | None:
    scoped_summaries = [
        _build_hypothesis_audit_candidate_summary(settings, candidate_id)
        for candidate_id in candidate_ids
        if _candidate_matches_lane(settings, candidate_id, family=family, entry_style=None)
        and _hypothesis_audit_artifacts_exist(settings, candidate_id)
    ]
    reference_summary = _select_hypothesis_reference_summary(scoped_summaries)
    if reference_summary is not None:
        contract_fingerprint = _load_candidate_family_audit_fingerprint(settings, reference_summary.candidate_id)
        if contract_fingerprint is not None:
            return contract_fingerprint

    fallback_summaries: list[HypothesisAuditCandidateSummary] = []
    for report_dir in settings.paths().reports_dir.glob("AF-CAND-*"):
        candidate_id = report_dir.name
        if not _candidate_matches_lane(settings, candidate_id, family=family, entry_style=None):
            continue
        if not _hypothesis_audit_artifacts_exist(settings, candidate_id):
            continue
        if _load_candidate_family_audit_fingerprint(settings, candidate_id) is None:
            continue
        fallback_summaries.append(_build_hypothesis_audit_candidate_summary(settings, candidate_id))
    reference_summary = _select_hypothesis_reference_summary(fallback_summaries)
    if reference_summary is not None:
        contract_fingerprint = _load_candidate_family_audit_fingerprint(settings, reference_summary.candidate_id)
        if contract_fingerprint is not None:
            return contract_fingerprint
    return None


def _candidate_audit_recency(settings: Settings, candidate_id: str) -> float:
    report_dir = settings.paths().reports_dir / candidate_id
    timestamps = [
        path.stat().st_mtime
        for path in (
            report_dir / "reevaluation_report.json",
            report_dir / "review_packet.json",
            report_dir / "robustness_report.json",
        )
        if path.exists()
    ]
    return max(timestamps, default=0.0)


def _load_candidate_contract_fingerprint(
    settings: Settings,
    candidate_id: str,
) -> tuple[str, str, str, str] | None:
    provenance_path = settings.paths().reports_dir / candidate_id / "data_provenance.json"
    if not provenance_path.exists():
        return None
    payload = read_json(provenance_path)
    dataset_snapshot = payload.get("dataset_snapshot") or {}
    feature_build = payload.get("feature_build") or {}
    fingerprint = (
        str(dataset_snapshot.get("snapshot_id") or ""),
        str(feature_build.get("feature_version_id") or ""),
        str(feature_build.get("label_version_id") or ""),
        str(payload.get("execution_cost_model_version") or ""),
    )
    if not any(fingerprint):
        return None
    return fingerprint


def _load_candidate_family_audit_fingerprint(
    settings: Settings,
    candidate_id: str,
) -> tuple[str, str, str] | None:
    provenance_path = settings.paths().reports_dir / candidate_id / "data_provenance.json"
    if not provenance_path.exists():
        return None
    payload = read_json(provenance_path)
    dataset_snapshot = payload.get("dataset_snapshot") or {}
    feature_build = payload.get("feature_build") or {}
    raw_dataset_identity = "|".join(
        str(item or "")
        for item in (
            dataset_snapshot.get("source"),
            dataset_snapshot.get("instrument"),
            dataset_snapshot.get("dataset_start_utc"),
            dataset_snapshot.get("dataset_end_utc"),
        )
    ).strip("|")
    fingerprint = (
        raw_dataset_identity or str(dataset_snapshot.get("snapshot_id") or ""),
        str(feature_build.get("feature_version_id") or ""),
        str(feature_build.get("label_version_id") or ""),
    )
    if not any(fingerprint):
        return None
    return fingerprint


def _strategy_identity_fingerprint(spec: StrategySpec) -> str:
    normalized = _strip_non_identity_fields(spec.model_dump(mode="json"))
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _strip_non_identity_fields(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _strip_non_identity_fields(item)
            for key, item in value.items()
            if key not in {"candidate_id", "benchmark_group_id", "variant_name", "notes"}
        }
    if isinstance(value, list):
        return [_strip_non_identity_fields(item) for item in value]
    return value


def _find_equivalent_candidate_for_spec(
    settings: Settings,
    *,
    source_candidate_id: str,
    target_spec: StrategySpec,
) -> str | None:
    target_fingerprint = _strategy_identity_fingerprint(target_spec)
    source_contract_fingerprint = _load_candidate_contract_fingerprint(settings, source_candidate_id)
    for report_dir in settings.paths().reports_dir.glob("AF-CAND-*"):
        if not report_dir.is_dir():
            continue
        existing_candidate_id = report_dir.name
        if existing_candidate_id == source_candidate_id:
            continue
        if source_contract_fingerprint is not None:
            existing_contract_fingerprint = _load_candidate_contract_fingerprint(settings, existing_candidate_id)
            if existing_contract_fingerprint != source_contract_fingerprint:
                continue
        spec_path = report_dir / "strategy_spec.json"
        if not spec_path.exists():
            continue
        try:
            existing_spec = StrategySpec.model_validate(read_json(spec_path))
        except ValidationError:
            continue
        if _strategy_identity_fingerprint(existing_spec) == target_fingerprint:
            return existing_candidate_id
    return None


def _mutation_already_explored(
    settings: Settings,
    *,
    source_candidate_id: str,
    mutation_payload: dict[str, object],
) -> bool:
    try:
        source_spec = _load_spec(settings, source_candidate_id)
        source_candidate = _load_candidate(settings, source_candidate_id, source_spec)
        preview_blueprint = _build_mutation_blueprint(
            settings,
            source_candidate_id=source_candidate_id,
            mutated_candidate_id="AF-CAND-PREVIEW",
            source_candidate=source_candidate,
            source_spec=source_spec,
            mutation_payload=mutation_payload,
        )
    except (FileNotFoundError, ValidationError):
        return False
    if preview_blueprint is None:
        return False
    equivalent_candidate_id = _find_equivalent_candidate_for_spec(
        settings,
        source_candidate_id=source_candidate_id,
        target_spec=preview_blueprint["spec"],
    )
    return equivalent_candidate_id is not None


def _build_data_feature_provenance_consistency(
    settings: Settings,
    candidate_summaries: list[HypothesisAuditCandidateSummary],
) -> dict[str, object]:
    dataset_snapshot_ids: set[str] = set()
    feature_version_ids: set[str] = set()
    label_version_ids: set[str] = set()
    execution_cost_model_versions: set[str] = set()
    candidates_with_provenance: list[str] = []
    archived_candidates_excluded: list[str] = []

    for summary in candidate_summaries:
        if summary.archived:
            archived_candidates_excluded.append(summary.candidate_id)
            continue
        provenance_path = settings.paths().reports_dir / summary.candidate_id / "data_provenance.json"
        if not provenance_path.exists():
            continue
        payload = read_json(provenance_path)
        dataset_snapshot = payload.get("dataset_snapshot") or {}
        feature_build = payload.get("feature_build") or {}
        dataset_snapshot_id = str(dataset_snapshot.get("snapshot_id") or "")
        feature_version_id = str(feature_build.get("feature_version_id") or "")
        label_version_id = str(feature_build.get("label_version_id") or "")
        execution_cost_model_version = str(payload.get("execution_cost_model_version") or "")
        if dataset_snapshot_id:
            dataset_snapshot_ids.add(dataset_snapshot_id)
        if feature_version_id:
            feature_version_ids.add(feature_version_id)
        if label_version_id:
            label_version_ids.add(label_version_id)
        if execution_cost_model_version:
            execution_cost_model_versions.add(execution_cost_model_version)
        candidates_with_provenance.append(summary.candidate_id)

    return {
        "candidate_count_with_provenance": len(candidates_with_provenance),
        "archived_candidates_excluded": archived_candidates_excluded,
        "dataset_snapshot_ids": sorted(dataset_snapshot_ids),
        "feature_version_ids": sorted(feature_version_ids),
        "label_version_ids": sorted(label_version_ids),
        "execution_cost_model_versions": sorted(execution_cost_model_versions),
        "dataset_snapshot_consistent": len(dataset_snapshot_ids) <= 1,
        "feature_version_consistent": len(feature_version_ids) <= 1,
        "label_version_consistent": len(label_version_ids) <= 1,
        "execution_cost_model_consistent": len(execution_cost_model_versions) <= 1,
    }


def _collect_recent_regime_signals(
    settings: Settings,
    candidate_summaries: list[HypothesisAuditCandidateSummary],
) -> list[str]:
    signals: list[str] = []
    candidate_ids = {item.candidate_id for item in candidate_summaries}
    for record in reversed(_load_failure_records(settings)):
        if str(record.get("stage") or "") != "data_regime_audit":
            continue
        candidate_id = str(record.get("candidate_id") or "")
        if candidate_id and candidate_id not in candidate_ids:
            continue
        report_path = Path(str((record.get("artifact_paths") or {}).get("next_step_report_path") or ""))
        if not report_path.exists():
            continue
        payload = read_json(report_path)
        audit_payloads = payload.get("data_regime_audit_reports") or []
        if not audit_payloads:
            continue
        dominant_modes = list(audit_payloads[0].get("dominant_first_window_loss_modes") or [])
        if dominant_modes:
            signals.append(", ".join(str(item) for item in dominant_modes))
        if len(signals) >= 3:
            break
    return list(dict.fromkeys(signals))


def _build_data_feature_root_causes(
    settings: Settings,
    *,
    candidate_summaries: list[HypothesisAuditCandidateSummary],
    provenance_consistency: dict[str, object],
    recent_regime_signals: list[str],
) -> list[str]:
    if not candidate_summaries:
        return ["insufficient_evidence"]
    validation = settings.validation
    root_causes: list[str] = []
    if all(
        bool(provenance_consistency.get(key))
        for key in (
            "dataset_snapshot_consistent",
            "feature_version_consistent",
            "label_version_consistent",
            "execution_cost_model_consistent",
        )
    ):
        root_causes.append("provenance_contract_consistent")
    else:
        root_causes.append("provenance_contract_mixed")

    if sum(item.trade_count < validation.minimum_test_trade_count for item in candidate_summaries) >= max(2, len(candidate_summaries) // 2):
        root_causes.append("insufficient_trade_density")
    if any(
        item.trade_count < validation.minimum_test_trade_count
        and item.out_of_sample_profit_factor >= validation.out_of_sample_profit_factor_floor
        and item.expectancy_pips <= validation.expectancy_floor
        for item in candidate_summaries
    ):
        root_causes.append("low_sample_oos_spike")
    if sum((not item.stress_passed) and item.expectancy_pips <= validation.expectancy_floor for item in candidate_summaries) >= max(
        2, len(candidate_summaries) // 2
    ):
        root_causes.append("execution_cost_realism_consumes_edge")
    if sum(not item.walk_forward_ok for item in candidate_summaries) >= max(2, len(candidate_summaries) // 2):
        root_causes.append("persistent_walk_forward_instability")
    if recent_regime_signals:
        root_causes.append("broad_regime_dependence")
    return root_causes


def _resolve_data_feature_family_decision(
    *,
    candidate_summaries: list[HypothesisAuditCandidateSummary],
    provenance_consistency: dict[str, object],
    suspected_root_causes: list[str],
    settings: Settings,
) -> str:
    if not candidate_summaries:
        return "insufficient_evidence"
    reference_summary = _select_hypothesis_reference_summary(candidate_summaries)
    if reference_summary is None:
        return "insufficient_evidence"
    if _bounded_data_feature_correction_already_attempted(settings, candidate_summaries):
        if not _summary_clears_research_gates(reference_summary, settings):
            return "retire_family"
    if "provenance_contract_mixed" in suspected_root_causes:
        return "bounded_correction_supported"
    if (
        "persistent_walk_forward_instability" in suspected_root_causes
        and "execution_cost_realism_consumes_edge" in suspected_root_causes
        and not _summary_clears_research_gates(reference_summary, settings)
    ):
        return "retire_family"
    if (
        "low_sample_oos_spike" in suspected_root_causes
        and "provenance_contract_consistent" not in suspected_root_causes
    ):
        return "bounded_correction_supported"
    return "retire_family"


def _bounded_data_feature_correction_already_attempted(
    settings: Settings,
    candidate_summaries: list[HypothesisAuditCandidateSummary],
) -> bool:
    if not candidate_summaries:
        return False
    family = candidate_summaries[0].family
    current_candidate_ids = {item.candidate_id for item in candidate_summaries}
    if not current_candidate_ids:
        return False
    for report_path in settings.paths().campaigns_dir.glob("*/next_step_report.json"):
        payload = read_json(report_path)
        if str(payload.get("selected_step_type") or "") != "data_feature_audit":
            continue
        audit_payloads = payload.get("data_feature_audit_reports") or []
        if not audit_payloads:
            continue
        audit_payload = audit_payloads[0]
        if str(audit_payload.get("family") or "") != family:
            continue
        if str(audit_payload.get("family_decision") or "") != "bounded_correction_supported":
            continue
        prior_audited_ids = {str(item) for item in audit_payload.get("audited_candidate_ids") or [] if str(item)}
        if not prior_audited_ids:
            continue
        if current_candidate_ids & prior_audited_ids and current_candidate_ids - prior_audited_ids:
            return True
        prior_campaign_id = str(payload.get("campaign_id") or report_path.parent.name)
        if not prior_campaign_id:
            continue
        for follow_on_path in settings.paths().campaigns_dir.glob("*/next_step_report.json"):
            follow_on_payload = read_json(follow_on_path)
            if str(follow_on_payload.get("selected_step_type") or "") != "diagnose_existing_candidates":
                continue
            if str(follow_on_payload.get("parent_campaign_id") or "") != prior_campaign_id:
                continue
            if str(follow_on_payload.get("stop_reason") or "") != "diagnosis_ambiguous_no_mutation_justified":
                continue
            diagnostic_candidate_ids = {
                str(item)
                for item in follow_on_payload.get("candidate_scope") or []
                if str(item)
            }
            if diagnostic_candidate_ids & current_candidate_ids:
                return True
    return False


def _build_data_feature_summary(
    *,
    candidate_summaries: list[HypothesisAuditCandidateSummary],
    reference_summary: HypothesisAuditCandidateSummary | None,
    family_decision: str,
    suspected_root_causes: list[str],
    provenance_consistency: dict[str, object],
) -> str:
    audited_ids = ", ".join(item.candidate_id for item in candidate_summaries) or "no candidates"
    root_cause_text = ", ".join(suspected_root_causes) or "no clear root causes"
    if family_decision == "retire_family" and reference_summary is not None:
        return (
            f"Data/feature audit compared {audited_ids}. {reference_summary.candidate_id} remains the best empirical "
            f"reference branch, but the audited candidates share {root_cause_text} under a "
            f"{'consistent' if provenance_consistency.get('dataset_snapshot_consistent') and provenance_consistency.get('feature_version_consistent') else 'mixed'} research contract. "
            "That points to structural family weakness rather than one more safe bounded mutation."
        )
    if family_decision == "bounded_correction_supported" and reference_summary is not None:
        return (
            f"Data/feature audit compared {audited_ids}. {reference_summary.candidate_id} remains the reference branch, "
            f"and the audited family shows {root_cause_text}, which supports one bounded upstream correction before any new lane search."
        )
    return f"Data/feature audit compared {audited_ids}, but the evidence is insufficient to support a family-level decision."


def _build_data_feature_actions(
    *,
    family_decision: str,
    reference_summary: HypothesisAuditCandidateSummary | None,
) -> list[str]:
    if family_decision == "retire_family":
        return [
            "Retire the current family from further mutation and parity work.",
            "Do not extend the approved program queue with nearby variants of this family.",
            "Open a different hypothesis class or a separate data/label audit before resuming autonomous search.",
        ]
    if family_decision == "bounded_correction_supported" and reference_summary is not None:
        return [
            f"Use {reference_summary.candidate_id} as the only reference branch for one bounded upstream correction.",
            "Stop again immediately after that correction and rerun the program queue only if the correction changes the research contract.",
        ]
    return [
        "Stop and gather more evidence before expanding the autonomous queue.",
    ]


def _build_data_feature_recommendations(
    *,
    family_decision: str,
    reference_summary: HypothesisAuditCandidateSummary | None,
) -> list[NextStepRecommendation]:
    if family_decision != "bounded_correction_supported" or reference_summary is None:
        return []
    return [
        NextStepRecommendation(
            step_type="diagnose_existing_candidates",
            candidate_id=reference_summary.candidate_id,
            rationale=(
                f"{reference_summary.candidate_id} remains the strongest family reference after the data/feature audit. "
                "Run one bounded diagnosis pass on that branch before any further correction or retirement decision."
            ),
            binding=True,
            evidence_status="supported",
            step_payload={
                "source_candidate_id": reference_summary.candidate_id,
                "audit_origin": "data_feature_audit",
            },
        )
    ]


def _run_data_label_audit(
    settings: Settings,
    *,
    child_spec: CampaignSpec,
    state: CampaignState,
    parent_spec: CampaignSpec,
    candidate_ids: list[str],
    step_reason: str,
    report_path: Path,
    recommendations_path: Path,
) -> NextStepControllerReport:
    candidate_summaries = [
        _build_hypothesis_audit_candidate_summary(settings, candidate_id)
        for candidate_id in candidate_ids
        if _hypothesis_audit_artifacts_exist(settings, candidate_id)
    ]
    reference_summary = _select_hypothesis_reference_summary(candidate_summaries)
    label_contract_snapshot = _build_data_label_contract_snapshot(settings, candidate_summaries)
    suspected_contract_gaps = _build_data_label_contract_gaps(
        candidate_summaries=candidate_summaries,
        label_contract_snapshot=label_contract_snapshot,
        settings=settings,
    )
    contract_decision = _resolve_data_label_contract_decision(
        candidate_summaries=candidate_summaries,
        suspected_contract_gaps=suspected_contract_gaps,
    )
    summary = _build_data_label_summary(
        candidate_summaries=candidate_summaries,
        reference_summary=reference_summary,
        contract_decision=contract_decision,
        suspected_contract_gaps=suspected_contract_gaps,
    )
    recommended_actions = _build_data_label_actions(
        contract_decision=contract_decision,
        reference_summary=reference_summary,
    )
    audit_report = DataLabelAuditReport(
        family=parent_spec.family,
        audited_candidate_ids=[item.candidate_id for item in candidate_summaries],
        reference_candidate_id=reference_summary.candidate_id if reference_summary else None,
        contract_decision=contract_decision,
        summary=summary,
        suspected_contract_gaps=suspected_contract_gaps,
        label_contract_snapshot=label_contract_snapshot,
        recommended_actions=recommended_actions,
        candidate_summaries=candidate_summaries,
        artifact_paths={
            "campaign_state_path": str(state.state_path),
            "next_step_report_path": str(report_path),
            "next_recommendations_path": str(recommendations_path),
        },
    )
    stop_reason = f"data_label_audit_completed_{contract_decision}"
    report = NextStepControllerReport(
        campaign_id=child_spec.campaign_id,
        parent_campaign_id=child_spec.parent_campaign_id,
        selected_step_type="data_label_audit",
        step_reason=step_reason,
        status="completed",
        stop_reason=stop_reason,
        candidate_scope=candidate_ids,
        data_label_audit_reports=[audit_report],
        next_recommendations=[],
        report_path=report_path,
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    write_json(recommendations_path, [])

    for summary_item in candidate_summaries:
        append_trial_entry(
            settings,
            candidate_id=summary_item.candidate_id,
            family=child_spec.family,
            stage="data_label_audit",
            campaign_id=child_spec.campaign_id,
            parent_candidate_ids=[candidate_id for candidate_id in candidate_ids if candidate_id != summary_item.candidate_id],
            mutation_policy="audit_only",
            artifact_paths={
                "campaign_state_path": str(state.state_path),
                "next_step_report_path": str(report.report_path),
                "next_recommendations_path": str(recommendations_path),
                **summary_item.artifact_paths,
            },
            gate_outcomes={
                "contract_decision": contract_decision,
                "reference_candidate_id": reference_summary.candidate_id if reference_summary else None,
                "suspected_contract_gaps": suspected_contract_gaps,
            },
        )

    if contract_decision != "insufficient_evidence":
        target_candidate = reference_summary.candidate_id if reference_summary else candidate_ids[0]
        append_failure_record(
            settings,
            candidate_id=target_candidate,
            stage="data_label_audit",
            failure_code="provenance_failure" if contract_decision == "upstream_contract_change_required" else "robustness_failure",
            campaign_id=child_spec.campaign_id,
            details={
                "decision": contract_decision,
                "audited_candidate_ids": [item.candidate_id for item in candidate_summaries],
                "reference_candidate_id": reference_summary.candidate_id if reference_summary else None,
                "suspected_contract_gaps": suspected_contract_gaps,
                "summary": summary,
            },
            artifact_paths={
                "next_step_report_path": str(report.report_path),
            },
        )
    return report


def _build_data_label_contract_snapshot(
    settings: Settings,
    candidate_summaries: list[HypothesisAuditCandidateSummary],
) -> dict[str, object]:
    dataset_snapshot_ids: set[str] = set()
    feature_version_ids: set[str] = set()
    label_version_ids: set[str] = set()
    feature_paths: set[str] = set()
    label_paths: set[str] = set()
    holding_bars: set[int] = set()
    stop_loss_pips: set[float] = set()
    take_profit_pips: set[float] = set()
    risk_reward_ratios: set[float] = set()
    entry_styles: set[str] = set()

    for summary in candidate_summaries:
        report_dir = settings.paths().reports_dir / summary.candidate_id
        provenance_path = report_dir / "data_provenance.json"
        spec_path = report_dir / "strategy_spec.json"
        if provenance_path.exists():
            payload = read_json(provenance_path)
            dataset_snapshot = payload.get("dataset_snapshot") or {}
            feature_build = payload.get("feature_build") or {}
            dataset_snapshot_id = str(dataset_snapshot.get("snapshot_id") or "")
            feature_version_id = str(feature_build.get("feature_version_id") or "")
            label_version_id = str(feature_build.get("label_version_id") or "")
            if dataset_snapshot_id:
                dataset_snapshot_ids.add(dataset_snapshot_id)
            if feature_version_id:
                feature_version_ids.add(feature_version_id)
            if label_version_id:
                label_version_ids.add(label_version_id)
            for path_item in feature_build.get("feature_paths") or []:
                if path_item:
                    feature_paths.add(str(path_item))
            for path_item in feature_build.get("label_paths") or []:
                if path_item:
                    label_paths.add(str(path_item))
        if spec_path.exists():
            spec_payload = read_json(spec_path)
            entry_style = str(spec_payload.get("entry_style") or "")
            if entry_style:
                entry_styles.add(entry_style)
            holding_bar_value = spec_payload.get("holding_bars")
            if isinstance(holding_bar_value, int | float):
                holding_bars.add(int(holding_bar_value))
            stop_loss = _extract_float(spec_payload, "stop_loss_pips")
            take_profit = _extract_float(spec_payload, "take_profit_pips")
            if stop_loss is not None:
                stop_loss_pips.add(stop_loss)
            if take_profit is not None:
                take_profit_pips.add(take_profit)
            if stop_loss and take_profit:
                risk_reward_ratios.add(round(take_profit / stop_loss, 6))

    label_source_text = "\n".join(_read_existing_text(Path(path_item)) for path_item in sorted(label_paths))
    return {
        "dataset_snapshot_ids": sorted(dataset_snapshot_ids),
        "feature_version_ids": sorted(feature_version_ids),
        "label_version_ids": sorted(label_version_ids),
        "feature_paths": sorted(feature_paths),
        "label_paths": sorted(label_paths),
        "entry_styles": sorted(entry_styles),
        "holding_bars": sorted(holding_bars),
        "stop_loss_pips": sorted(stop_loss_pips),
        "take_profit_pips": sorted(take_profit_pips),
        "risk_reward_ratios": sorted(risk_reward_ratios),
        "uses_future_return_pips_label": "future_return_pips" in label_source_text,
        "uses_binary_direction_label": "label_up" in label_source_text,
        "uses_path_aware_exit_labels": any(
            token in label_source_text
            for token in (
                "stop_loss_pips",
                "take_profit_pips",
                "long_exit_reason",
                "short_exit_reason",
                "time_exit",
                "_path_outcomes",
            )
        ),
        "mentions_exit_geometry": any(
            token in label_source_text
            for token in (
                "stop_loss",
                "take_profit",
                "time_exit",
                "barrier",
                "triple_barrier",
                "long_exit_reason",
                "short_exit_reason",
                "timeout_return_pips",
                "_path_outcomes",
            )
        ),
    }


def _build_data_label_contract_gaps(
    *,
    candidate_summaries: list[HypothesisAuditCandidateSummary],
    label_contract_snapshot: dict[str, object],
    settings: Settings,
) -> list[str]:
    if not candidate_summaries:
        return ["insufficient_evidence"]
    validation = settings.validation
    gaps: list[str] = []
    if len(label_contract_snapshot.get("label_version_ids") or []) <= 1:
        gaps.append("shared_label_contract_consistent")
    else:
        gaps.append("label_contract_mixed")
    if bool(label_contract_snapshot.get("uses_future_return_pips_label")) and bool(
        label_contract_snapshot.get("uses_binary_direction_label")
    ) and not bool(label_contract_snapshot.get("uses_path_aware_exit_labels")):
        gaps.append("label_contract_binary_direction_only")
    if len(label_contract_snapshot.get("holding_bars") or []) <= 1 and sum(
        not item.walk_forward_ok for item in candidate_summaries
    ) >= max(2, len(candidate_summaries) // 2):
        gaps.append("single_horizon_contract_undervalidated")
    if (
        len(label_contract_snapshot.get("risk_reward_ratios") or []) >= 1
        and not bool(label_contract_snapshot.get("uses_path_aware_exit_labels"))
    ):
        gaps.append("label_contract_ignores_trade_path_geometry")
    if len(label_contract_snapshot.get("entry_styles") or []) >= 2 and sum(
        (item.expectancy_pips <= validation.expectancy_floor) or (not item.stress_passed)
        for item in candidate_summaries
    ) >= max(2, len(candidate_summaries) // 2):
        gaps.append("shared_label_contract_fails_across_styles")
    return gaps


def _resolve_data_label_contract_decision(
    *,
    candidate_summaries: list[HypothesisAuditCandidateSummary],
    suspected_contract_gaps: list[str],
) -> str:
    if not candidate_summaries:
        return "insufficient_evidence"
    if "label_contract_mixed" in suspected_contract_gaps:
        return "insufficient_evidence"
    critical_gaps = {
        "label_contract_binary_direction_only",
        "single_horizon_contract_undervalidated",
        "label_contract_ignores_trade_path_geometry",
        "shared_label_contract_fails_across_styles",
    }
    if len(critical_gaps.intersection(suspected_contract_gaps)) >= 2:
        return "upstream_contract_change_required"
    if {
        "label_contract_binary_direction_only",
        "shared_label_contract_fails_across_styles",
    }.issubset(set(suspected_contract_gaps)):
        return "upstream_contract_change_required"
    return "family_retire_confirmed"


def _build_data_label_summary(
    *,
    candidate_summaries: list[HypothesisAuditCandidateSummary],
    reference_summary: HypothesisAuditCandidateSummary | None,
    contract_decision: str,
    suspected_contract_gaps: list[str],
) -> str:
    audited_ids = ", ".join(item.candidate_id for item in candidate_summaries) or "no candidates"
    gap_text = ", ".join(suspected_contract_gaps) or "no clear contract gaps"
    if contract_decision == "upstream_contract_change_required" and reference_summary is not None:
        return (
            f"Data/label audit compared {audited_ids}. {reference_summary.candidate_id} remains the empirical reference, "
            f"but the shared research contract shows {gap_text}. That points to an upstream label-contract problem "
            "before any new family queue should be approved."
        )
    if contract_decision == "family_retire_confirmed" and reference_summary is not None:
        return (
            f"Data/label audit compared {audited_ids}. {reference_summary.candidate_id} remains the empirical reference, "
            f"but the family still fails under {gap_text}. A label-only explanation is not enough to reopen this family."
        )
    return f"Data/label audit compared {audited_ids}, but the evidence is insufficient to support a contract-level decision."


def _build_data_label_actions(
    *,
    contract_decision: str,
    reference_summary: HypothesisAuditCandidateSummary | None,
) -> list[str]:
    if contract_decision == "upstream_contract_change_required":
        reference_candidate = reference_summary.candidate_id if reference_summary else "the current reference branch"
        return [
            f"Freeze the current family and use {reference_candidate} only as the reference branch for contract redesign.",
            "Replace the binary future-return label with a path-aware label aligned to stop, target, and timeout geometry.",
            "Regenerate fresh roots under the new label contract before approving another autonomous queue.",
        ]
    if contract_decision == "family_retire_confirmed":
        return [
            "Keep the current family retired under the existing research contract.",
            "Do not assume a label-only change will rescue this family without a broader hypothesis redesign.",
            "Approve the next autonomous queue only for a genuinely orthogonal hypothesis class.",
        ]
    return [
        "Stop and gather more research-contract evidence before approving the next queue.",
    ]


def _read_existing_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _extract_float(payload: dict[str, object], field_name: str) -> float | None:
    direct_value = payload.get(field_name)
    if isinstance(direct_value, (int, float)):
        return float(direct_value)
    nested = payload.get("risk_policy")
    if isinstance(nested, dict):
        nested_value = nested.get(field_name)
        if isinstance(nested_value, (int, float)):
            return float(nested_value)
    return None


def _select_next_step(
    settings: Settings,
    *,
    parent_spec: CampaignSpec,
    parent_state: CampaignState,
    binding_recommendations: list[NextStepRecommendation],
    allowed_step_types: list[NextStepType],
) -> _NextStepDecision:
    candidate_scope = _candidate_scope(parent_spec, parent_state)
    parent_report = _load_parent_controller_report(settings, parent_state)
    grandparent_report = (
        _load_controller_report_for_campaign(settings, parent_report.parent_campaign_id)
        if parent_report is not None
        else None
    )
    if (
        parent_report is not None
        and parent_report.selected_step_type == "hypothesis_audit"
        and parent_report.hypothesis_audit_reports
        and parent_report.hypothesis_audit_reports[0].lane_decision == "hold_reference_blocked_by_robustness"
        and "data_regime_audit" in allowed_step_types
    ):
        return _NextStepDecision(
            step_type="data_regime_audit",
            candidate_scope=list(parent_report.hypothesis_audit_reports[0].audited_candidate_ids or candidate_scope),
            rationale=(
                "The parent hypothesis audit held the reference branch but blocked the lane on robustness, so the next "
                "governed step is a bounded data/regime audit on the audited candidates."
            ),
        )
    if (
        parent_report is not None
        and parent_report.selected_step_type == "data_regime_audit"
        and parent_report.data_regime_audit_reports
        and parent_report.data_regime_audit_reports[0].lane_decision in {"retire_lane", "structural_regime_instability"}
        and "data_feature_audit" in allowed_step_types
    ):
        return _NextStepDecision(
            step_type="data_feature_audit",
            candidate_scope=_derive_data_feature_audit_scope(
                settings,
                family=parent_spec.family,
                parent_report=parent_report,
            ),
            rationale=(
                "The approved lane queue is exhausted after a retirement-level data/regime audit, so the next governed "
                "step is a bounded data/feature audit across the strongest recent family references."
            ),
        )
    if (
        parent_report is not None
        and parent_report.selected_step_type == "data_feature_audit"
        and parent_report.data_feature_audit_reports
        and parent_report.data_feature_audit_reports[0].family_decision == "retire_family"
        and "data_label_audit" in allowed_step_types
    ):
        return _NextStepDecision(
            step_type="data_label_audit",
            candidate_scope=list(parent_report.data_feature_audit_reports[0].audited_candidate_ids or candidate_scope),
            rationale=(
                "The family-level data/feature audit retired the current family, so the next governed step is a bounded "
                "data/label contract audit before any new autonomous queue can be approved."
            ),
        )
    if (
        parent_report is not None
        and parent_report.selected_step_type == "diagnose_existing_candidates"
        and parent_report.stop_reason == "diagnosis_ambiguous_no_mutation_justified"
        and not parent_report.next_recommendations
        and parent_report.candidate_reports
        and all(
            not candidate_report.supported_slices and not candidate_report.recommended_mutation
            for candidate_report in parent_report.candidate_reports
        )
        and grandparent_report is not None
        and grandparent_report.selected_step_type == "data_feature_audit"
        and grandparent_report.data_feature_audit_reports
        and grandparent_report.data_feature_audit_reports[0].family_decision == "bounded_correction_supported"
        and "data_feature_audit" in allowed_step_types
    ):
        return _NextStepDecision(
            step_type="data_feature_audit",
            candidate_scope=list(grandparent_report.data_feature_audit_reports[0].audited_candidate_ids or candidate_scope),
            rationale=(
                "The bounded family correction proposed by the parent data/feature audit could not justify even one "
                "supported mutation on the reference branch, so the next governed step is to rerun the family audit "
                "and close the family if no new correction path exists."
            ),
        )
    if (
        parent_report is not None
        and parent_report.selected_step_type == "diagnose_existing_candidates"
        and parent_report.stop_reason == "diagnosis_ambiguous_no_mutation_justified"
        and not parent_report.next_recommendations
        and parent_report.candidate_reports
        and all(
            not candidate_report.supported_slices and not candidate_report.recommended_mutation
            for candidate_report in parent_report.candidate_reports
        )
        and "hypothesis_audit" in allowed_step_types
    ):
        return _NextStepDecision(
            step_type="hypothesis_audit",
            candidate_scope=_derive_hypothesis_audit_scope(
                settings,
                parent_spec=parent_spec,
                parent_state=parent_state,
                parent_report=parent_report,
            ),
            rationale=(
                "The parent diagnosis exhausted the bounded mutation path without a supported next mutation, so the "
                "next governed step is a bounded hypothesis audit rather than another search step."
            ),
        )
    if (
        parent_report is not None
        and parent_report.stop_class == "lane_exhausted"
        and "hypothesis_audit" in allowed_step_types
    ):
        return _NextStepDecision(
            step_type="hypothesis_audit",
            candidate_scope=_derive_hypothesis_audit_scope(
                settings,
                parent_spec=parent_spec,
                parent_state=parent_state,
                parent_report=parent_report,
            ),
            rationale=(
                "The parent lane is already marked lane_exhausted, so the next governed step is a bounded "
                "hypothesis audit rather than another mutation or diagnosis pass."
            ),
        )
    if binding_recommendations:
        recommendation = next((item for item in binding_recommendations if _is_binding_recommendation(settings, parent_state, item)), None)
        if recommendation:
            if recommendation.step_type not in allowed_step_types:
                return _NextStepDecision(
                    step_type=None,
                    candidate_scope=candidate_scope,
                    rationale=f"Binding recommendation {recommendation.step_type} is outside the allowed step set.",
                    stop_reason="binding_recommendation_outside_allowed_step_types",
                    recommendation=recommendation,
                )
            if recommendation.step_type not in SUPPORTED_STEP_TYPES:
                return _NextStepDecision(
                    step_type=None,
                    candidate_scope=candidate_scope,
                    rationale=f"Binding recommendation {recommendation.step_type} is not yet implemented by the controller.",
                    stop_reason="unsupported_binding_recommended_step",
                    recommendation=recommendation,
                )
            if not _binding_recommendation_artifacts_exist(settings, recommendation):
                return _NextStepDecision(
                    step_type=None,
                    candidate_scope=candidate_scope,
                    rationale="Binding recommendation prerequisites are missing from the repo state.",
                    stop_reason="binding_recommendation_missing_artifacts",
                    recommendation=recommendation,
                )
            if not _binding_recommendation_approvals_present(settings, recommendation):
                return _NextStepDecision(
                    step_type=None,
                    candidate_scope=candidate_scope,
                    rationale=f"Binding recommendation {recommendation.step_type} is missing required approvals.",
                    stop_reason="binding_recommendation_missing_required_approval",
                    recommendation=recommendation,
                )
            scoped_candidate_ids = [recommendation.candidate_id] if recommendation.candidate_id else candidate_scope
            return _NextStepDecision(
                step_type=recommendation.step_type,
                candidate_scope=scoped_candidate_ids,
                rationale=f"Following binding recommendation from the latest completed campaign: {recommendation.rationale}",
                recommendation=recommendation,
            )
    if parent_spec.queue_kind == "throughput" and candidate_scope:
        candidate_id = candidate_scope[0]
        report_dir = settings.paths().reports_dir / candidate_id
        if "formalize_rule_candidate" in allowed_step_types and not (report_dir / "rule_spec.json").exists():
            return _NextStepDecision(
                step_type="formalize_rule_candidate",
                candidate_scope=[candidate_id],
                rationale="Throughput lane defaulted to rule formalization because no rule_spec artifact exists yet.",
            )
        if "generate_ea_spec" in allowed_step_types and (report_dir / "rule_spec.json").exists() and not (report_dir / "ea_spec.json").exists():
            return _NextStepDecision(
                step_type="generate_ea_spec",
                candidate_scope=[candidate_id],
                rationale="Throughput lane defaulted to EA-spec generation because rule_spec exists but ea_spec is missing.",
            )
        if "compile_ea_candidate" in allowed_step_types and (report_dir / "ea_spec.json").exists() and not (report_dir / "compile_report.json").exists():
            return _NextStepDecision(
                step_type="compile_ea_candidate",
                candidate_scope=[candidate_id],
                rationale="Throughput lane defaulted to compile because the EA spec exists but no compile report was found.",
            )
        if "run_mt5_backtest_smoke" in allowed_step_types and (report_dir / "compile_report.json").exists() and not (report_dir / "mt5_smoke_report.json").exists():
            return _NextStepDecision(
                step_type="run_mt5_backtest_smoke",
                candidate_scope=[candidate_id],
                rationale="Throughput lane defaulted to MT5 smoke because the candidate compiled but no smoke artifact exists yet.",
            )
        if "triage_reviewable_candidate" in allowed_step_types and (
            (report_dir / "ea_spec_generation_report.json").exists()
            or (report_dir / "compile_report.json").exists()
            or (report_dir / "mt5_smoke_report.json").exists()
        ):
            return _NextStepDecision(
                step_type="triage_reviewable_candidate",
                candidate_scope=[candidate_id],
                rationale="Throughput lane defaulted to triage because compile/smoke evidence exists and no later throughput step is pending.",
            )
    if "diagnose_existing_candidates" in allowed_step_types:
        diagnostic_scope = [candidate_id for candidate_id in candidate_scope if _candidate_needs_diagnosis(settings, candidate_id)]
        if diagnostic_scope:
            return _NextStepDecision(
                step_type="diagnose_existing_candidates",
                candidate_scope=diagnostic_scope,
                rationale=(
                    "The latest completed campaign left the active hold candidates in robustness_provisional with failed "
                    "walk-forward stability, so a diagnosis-only step is the highest-priority legal next action."
                ),
            )
    return _NextStepDecision(
        step_type=None,
        candidate_scope=candidate_scope,
        rationale="No supported next step could be selected without violating the current gates or step restrictions.",
        stop_reason="no_supported_next_step",
    )


def _is_binding_recommendation(settings: Settings, parent_state: CampaignState, recommendation: NextStepRecommendation) -> bool:
    if not recommendation.binding or recommendation.evidence_status != "supported":
        return False
    if _has_newer_completed_child_campaign(settings, parent_state, recommendation):
        return False
    return True


def _has_newer_completed_child_campaign(
    settings: Settings,
    parent_state: CampaignState,
    recommendation: NextStepRecommendation | None = None,
) -> bool:
    target_candidate_id = recommendation.candidate_id if recommendation is not None else None
    for state_path in settings.paths().campaigns_dir.glob("*/state.json"):
        state = CampaignState.model_validate(read_json(state_path))
        if state.parent_campaign_id != parent_state.campaign_id or state.status != "completed":
            continue
        if target_candidate_id:
            child_scope = set(state.active_candidate_ids) | set(state.promoted_candidate_ids)
            if target_candidate_id not in child_scope:
                continue
        if state.updated_utc > parent_state.updated_utc:
            return True
    return False


def _binding_recommendation_artifacts_exist(settings: Settings, recommendation: NextStepRecommendation) -> bool:
    if not recommendation.candidate_id:
        return True
    report_dir = settings.paths().reports_dir / recommendation.candidate_id
    if recommendation.step_type == "formalize_rule_candidate":
        return (report_dir / "candidate.json").exists() or (report_dir / "strategy_spec.json").exists()
    if recommendation.step_type == "generate_ea_spec":
        return (report_dir / "rule_spec.json").exists()
    if recommendation.step_type == "compile_ea_candidate":
        return (report_dir / "ea_spec.json").exists() and (report_dir / "strategy_spec.json").exists()
    if recommendation.step_type == "run_mt5_backtest_smoke":
        return (report_dir / "compile_report.json").exists()
    if recommendation.step_type == "triage_reviewable_candidate":
        return (
            (report_dir / "ea_spec_generation_report.json").exists()
            or (report_dir / "compile_report.json").exists()
            or (report_dir / "mt5_smoke_report.json").exists()
        )
    if recommendation.step_type == "run_parity":
        return (report_dir / "review_packet.json").exists() and (report_dir / "strategy_spec.json").exists()
    if recommendation.step_type == "run_forward":
        return (report_dir / "review_packet.json").exists() and (report_dir / "strategy_spec.json").exists()
    return (report_dir / "strategy_spec.json").exists() or (report_dir / "candidate.json").exists()


def _binding_recommendation_approvals_present(settings: Settings, recommendation: NextStepRecommendation) -> bool:
    if not recommendation.candidate_id:
        return True
    required_stages = _required_approval_stages_for_step(recommendation.step_type)
    current_policy_hash = policy_snapshot_hash(settings)
    return all(
        is_stage_approved(
            recommendation.candidate_id,
            stage,
            settings,
            require_fresh=True,
            current_policy_snapshot_hash=current_policy_hash,
        )
        for stage in required_stages
    )


def _required_approval_stages_for_step(step_type: NextStepType | None) -> list[str]:
    if step_type == "run_parity":
        return ["mt5_packet", "mt5_parity_run", "mt5_validation"]
    return []


def _candidate_needs_diagnosis(settings: Settings, candidate_id: str) -> bool:
    review_path = settings.paths().reports_dir / candidate_id / "review_packet.json"
    if not review_path.exists():
        return False
    review_payload = read_json(review_path)
    grades = (review_payload.get("metrics") or {}).get("grades") or {}
    readiness = str(review_payload.get("readiness") or "")
    return readiness == "robustness_provisional" and not bool(grades.get("walk_forward_ok"))


def _candidate_scope(parent_spec: CampaignSpec, parent_state: CampaignState) -> list[str]:
    scoped = list(parent_spec.target_candidate_ids)
    if not scoped:
        scoped = [candidate_id for candidate_id in parent_state.active_candidate_ids if candidate_id != parent_state.baseline_candidate_id]
    if not scoped:
        scoped = list(parent_state.active_candidate_ids)
    return list(dict.fromkeys(scoped))


def _build_child_campaign_spec(
    settings: Settings,
    *,
    parent_spec: CampaignSpec,
    parent_state: CampaignState,
    campaign_id: str | None,
    allowed_step_types: list[NextStepType],
    decision: _NextStepDecision,
) -> CampaignSpec:
    child_campaign_id = campaign_id or next_campaign_id(settings, suffix="-next-step")
    return CampaignSpec(
        campaign_id=child_campaign_id,
        family=parent_spec.family,
        baseline_candidate_id=parent_spec.baseline_candidate_id,
        target_candidate_ids=decision.candidate_scope,
        parent_campaign_id=parent_state.campaign_id,
        queue_kind=parent_spec.queue_kind,
        throughput_target_count=parent_spec.throughput_target_count,
        orthogonality_metadata=dict(parent_spec.orthogonality_metadata),
        compile_budget=parent_spec.compile_budget,
        smoke_budget=parent_spec.smoke_budget,
        max_rule_spec_reformulations_per_hypothesis=parent_spec.max_rule_spec_reformulations_per_hypothesis,
        max_ea_spec_rewrites_per_candidate=parent_spec.max_ea_spec_rewrites_per_candidate,
        max_compile_retries_per_candidate=parent_spec.max_compile_retries_per_candidate,
        max_smoke_retries_per_candidate=parent_spec.max_smoke_retries_per_candidate,
        step_type=decision.step_type,
        allowed_step_types=allowed_step_types,
        max_iterations=1,
        max_new_candidates=0,
        trial_cap_per_family=max(len(decision.candidate_scope), 1),
        stop_on_review_eligible_provisional=False,
        notes=[
            f"Single-step child campaign opened from {parent_state.campaign_id}.",
            f"Selected step: {decision.step_type or 'none'}.",
            "This controller run must stop after exactly one legal step.",
        ],
    )


def _load_latest_completed_campaign_state(
    settings: Settings,
    *,
    family: str,
    campaign_id: str | None = None,
) -> CampaignState:
    if campaign_id:
        state_path = settings.paths().campaigns_dir / campaign_id / "state.json"
        if not state_path.exists():
            raise FileNotFoundError(f"Campaign state not found: {state_path}")
        return CampaignState.model_validate(read_json(state_path))
    states: list[CampaignState] = []
    for state_path in settings.paths().campaigns_dir.glob("*/state.json"):
        state = CampaignState.model_validate(read_json(state_path))
        if state.family == family and state.status == "completed":
            states.append(state)
    if not states:
        raise FileNotFoundError(f"No completed {family} campaign state was found.")
    return max(states, key=lambda item: item.updated_utc)


def _load_campaign_spec(campaign_dir: Path) -> CampaignSpec:
    spec_path = campaign_dir / "spec.json"
    if not spec_path.exists():
        raise FileNotFoundError(f"Campaign spec not found: {spec_path}")
    return CampaignSpec.model_validate(read_json(spec_path))


def _load_next_recommendations(campaign_dir: Path) -> list[NextStepRecommendation]:
    path = campaign_dir / "next_recommendations.json"
    if not path.exists():
        return []
    payload = read_json(path)
    return [NextStepRecommendation.model_validate(item) for item in payload]


def _load_candidate(settings: Settings, candidate_id: str, spec: StrategySpec) -> CandidateDraft:
    path = settings.paths().reports_dir / candidate_id / "candidate.json"
    if path.exists():
        return CandidateDraft.model_validate(read_json(path))
    return CandidateDraft(
        candidate_id=spec.candidate_id,
        family=spec.family,
        title=f"{spec.family.replace('_', ' ').title()} Candidate {spec.candidate_id}",
        thesis="Recovered candidate context from compiled strategy specification.",
        source_citations=spec.source_citations,
        strategy_hypothesis="Recovered from deterministic strategy specification.",
        market_context={
            "session_focus": spec.session_policy.name,
            "volatility_preference": "unspecified",
            "directional_bias": spec.side_policy,
            "execution_notes": spec.session_policy.notes,
            "allowed_hours_utc": spec.session_policy.allowed_hours_utc,
        },
        setup_summary=spec.setup_logic.summary,
        entry_summary=" ".join(spec.entry_logic),
        exit_summary=" ".join(spec.exit_logic),
        risk_summary="Recovered from strategy spec risk policy.",
        notes=spec.notes,
        quality_flags=["recovered_candidate_context"],
        contradiction_summary=[],
        critic_notes=[],
        entry_style=spec.entry_style,
        holding_bars=spec.holding_bars,
        signal_threshold=spec.signal_threshold,
        stop_loss_pips=spec.stop_loss_pips,
        take_profit_pips=spec.take_profit_pips,
    )


def _load_spec(settings: Settings, candidate_id: str) -> StrategySpec:
    path = settings.paths().reports_dir / candidate_id / "strategy_spec.json"
    if not path.exists():
        raise FileNotFoundError(f"Strategy spec not found: {path}")
    return StrategySpec.model_validate(read_json(path))


def _resolve_mutation_payload(
    recommendation: NextStepRecommendation | None,
    source_spec: StrategySpec,
) -> dict[str, object] | None:
    if recommendation is None:
        return None
    payload = dict(recommendation.step_payload or {})
    mutation_type = str(payload.get("mutation_type") or "").strip()
    if not mutation_type:
        removed_hours = _extract_removed_hours_from_rationale(recommendation.rationale)
        if removed_hours:
            mutation_type = "trim_allowed_hours"
            payload["removed_hours_utc"] = removed_hours
    if mutation_type == "trim_allowed_hours":
        removed_hours = [int(hour) for hour in payload.get("removed_hours_utc", [])]
        current_hours = set(source_spec.session_policy.allowed_hours_utc)
        removed_hours = [hour for hour in removed_hours if hour in current_hours]
        if removed_hours:
            normalized_payload: dict[str, object] = {
                "mutation_type": mutation_type,
                "removed_hours_utc": removed_hours,
            }
            if bool(payload.get("enable_news_blackout")):
                normalized_payload["enable_news_blackout"] = True
            return normalized_payload
    if mutation_type == "refresh_execution_cost_defaults":
        return {
            "mutation_type": mutation_type,
            "refresh_reason": str(payload.get("refresh_reason") or "apply current governed scalping execution-cost defaults"),
        }
    if mutation_type == "suppress_context_bucket":
        context_bucket = str(payload.get("context_bucket") or "").strip()
        if context_bucket:
            return {
                "mutation_type": mutation_type,
                "context_bucket": context_bucket,
            }
    return None


def _extract_removed_hours_from_rationale(rationale: str) -> list[int]:
    match = re.search(r"hours\s*\[([0-9,\s]+)\]\s*from allowed_hours_utc", rationale)
    if not match:
        return []
    return [int(item.strip()) for item in match.group(1).split(",") if item.strip()]


def _build_mutation_blueprint(
    settings: Settings,
    *,
    source_candidate_id: str,
    mutated_candidate_id: str,
    source_candidate: CandidateDraft,
    source_spec: StrategySpec,
    mutation_payload: dict[str, object],
) -> dict[str, object] | None:
    mutation_type = str(mutation_payload["mutation_type"])
    if mutation_type == "trim_allowed_hours":
        removed_hours = list(mutation_payload["removed_hours_utc"])
        enable_news_blackout = bool(mutation_payload.get("enable_news_blackout"))
        updated_hours = [hour for hour in source_spec.session_policy.allowed_hours_utc if hour not in set(removed_hours)]
        if not updated_hours or updated_hours == list(source_spec.session_policy.allowed_hours_utc):
            return None
        updated_notes = list(source_spec.notes) + [
            f"Mutation source candidate: {source_candidate_id}.",
            f"Removed overlap hours {removed_hours} under bounded single-step controller.",
        ]
        changed_fields = [
            "candidate_id",
            "title",
            "thesis",
            "market_context.allowed_hours_utc",
            "session_policy.allowed_hours_utc",
            "risk_envelope.session_boundaries_utc",
            "variant_name",
        ]
        step_payload: dict[str, object] = {"removed_hours_utc": removed_hours}
        gate_outcomes: dict[str, object] = {"removed_hours_utc": removed_hours}
        spec_update: dict[str, object] = {
            "candidate_id": mutated_candidate_id,
            "benchmark_group_id": mutated_candidate_id,
            "variant_name": f"overlap_trim_{'_'.join(str(hour) for hour in removed_hours)}",
            "session_policy": source_spec.session_policy.model_copy(
                update={
                    "allowed_hours_utc": updated_hours,
                    "notes": list(source_spec.session_policy.notes)
                    + [f"Single-step controller removed overlap hours {removed_hours} from {source_candidate_id}."],
                }
            ),
            "risk_envelope": source_spec.risk_envelope.model_copy(update={"session_boundaries_utc": updated_hours}),
            "notes": updated_notes,
        }
        candidate_execution_notes = list(source_candidate.market_context.execution_notes) + [
            f"Single-step controller mutation removed overlap hours {removed_hours} from {source_candidate_id}.",
        ]
        candidate_notes = list(source_candidate.notes) + [
            f"Mutated from {source_candidate_id} via single-step controller.",
            f"Removed allowed_hours_utc {removed_hours} to reduce weak overlap exposure.",
        ]
        if enable_news_blackout:
            spec_update["news_policy"] = source_spec.news_policy.model_copy(
                update={
                    "enabled": True,
                    "notes": list(source_spec.news_policy.notes)
                    + [f"Single-step controller enabled the governed news blackout for {source_candidate_id}."],
                }
            )
            spec_update["risk_envelope"] = source_spec.risk_envelope.model_copy(
                update={
                    "session_boundaries_utc": updated_hours,
                    "news_event_policy": "calendar_blackout",
                }
            )
            updated_notes.append("Enabled calendar blackout windows under the bounded correction lane.")
            candidate_execution_notes.append(
                f"Single-step controller enabled the governed news blackout for {source_candidate_id}."
            )
            candidate_notes.append("Enabled the governed calendar blackout under the bounded correction lane.")
            changed_fields.extend(["news_policy.enabled", "risk_envelope.news_event_policy"])
            step_payload["enable_news_blackout"] = True
            gate_outcomes["enable_news_blackout"] = True
        return {
            "candidate": source_candidate.model_copy(
                update={
                    "candidate_id": mutated_candidate_id,
                    "title": f"{source_candidate.title} Overlap Trim",
                    "thesis": (
                        f"{source_candidate.thesis} Narrow session mutation derived from {source_candidate_id} "
                        f"by removing overlap hours {removed_hours}."
                    ),
                    "market_context": source_candidate.market_context.model_copy(
                        update={
                            "allowed_hours_utc": updated_hours,
                            "execution_notes": candidate_execution_notes,
                        }
                    ),
                    "notes": candidate_notes,
                }
            ),
            "spec": source_spec.model_copy(update=spec_update),
            "changed_fields": changed_fields,
            "step_payload": step_payload,
            "gate_outcomes": gate_outcomes,
        }
    if mutation_type == "refresh_execution_cost_defaults":
        cost_defaults = default_execution_cost_fields(
            settings,
            family=source_spec.family,
            session_focus=source_candidate.market_context.session_focus,
        )
        current_cost_payload = source_spec.cost_model.model_dump(mode="json")
        current_execution_payload = source_spec.execution_cost_model.model_dump(mode="json")
        if all(current_cost_payload.get(key) == value for key, value in cost_defaults.items()) and all(
            current_execution_payload.get(key) == value for key, value in cost_defaults.items()
        ):
            return None
        refresh_reason = str(mutation_payload.get("refresh_reason") or "apply current governed scalping execution-cost defaults")
        return {
            "candidate": source_candidate.model_copy(
                update={
                    "candidate_id": mutated_candidate_id,
                    "title": f"{source_candidate.title} Execution Refresh",
                    "thesis": (
                        f"{source_candidate.thesis} Execution-cost refresh derived from {source_candidate_id} "
                        f"to align the candidate with the current governed scalping cost model."
                    ),
                    "market_context": source_candidate.market_context.model_copy(
                        update={
                            "execution_notes": list(source_candidate.market_context.execution_notes)
                            + [f"Single-step controller refreshed execution-cost defaults from {source_candidate_id}."],
                        }
                    ),
                    "notes": list(source_candidate.notes)
                    + [
                        f"Mutated from {source_candidate_id} via single-step controller.",
                        f"Execution-cost defaults refreshed to current governed scalping assumptions: {refresh_reason}.",
                    ],
                }
            ),
            "spec": source_spec.model_copy(
                update={
                    "candidate_id": mutated_candidate_id,
                    "benchmark_group_id": mutated_candidate_id,
                    "variant_name": "execution_refresh",
                    "cost_model": source_spec.cost_model.model_copy(update=cost_defaults),
                    "execution_cost_model": source_spec.execution_cost_model.model_copy(update=cost_defaults),
                    "notes": list(source_spec.notes)
                    + [
                        f"Mutation source candidate: {source_candidate_id}.",
                        "Refreshed execution-cost defaults under bounded single-step controller.",
                    ],
                }
            ),
            "changed_fields": [
                "candidate_id",
                "title",
                "thesis",
                "variant_name",
                "market_context.execution_notes",
                "cost_model.broker_fee_model",
                "cost_model.slippage_pips",
                "cost_model.commission_per_standard_lot_usd",
                "cost_model.fill_delay_ms",
                "execution_cost_model.broker_fee_model",
                "execution_cost_model.slippage_pips",
                "execution_cost_model.commission_per_standard_lot_usd",
                "execution_cost_model.fill_delay_ms",
            ],
            "step_payload": {
                "refresh_reason": refresh_reason,
                "fill_delay_ms": int(cost_defaults["fill_delay_ms"]),
                "slippage_pips": float(cost_defaults["slippage_pips"]),
                "broker_fee_model": str(cost_defaults["broker_fee_model"]),
                "commission_per_standard_lot_usd": float(cost_defaults["commission_per_standard_lot_usd"]),
            },
            "gate_outcomes": {
                "fill_delay_ms": int(cost_defaults["fill_delay_ms"]),
                "slippage_pips": float(cost_defaults["slippage_pips"]),
                "broker_fee_model": str(cost_defaults["broker_fee_model"]),
                "commission_per_standard_lot_usd": float(cost_defaults["commission_per_standard_lot_usd"]),
            },
        }
    if mutation_type == "suppress_context_bucket":
        context_bucket = str(mutation_payload["context_bucket"])
        existing_filters = list(source_spec.filters)
        existing_context_rule = next(
            (item.rule for item in existing_filters if item.name == "exclude_context_bucket"),
            None,
        )
        if existing_context_rule == context_bucket:
            return None
        updated_filters = [item for item in existing_filters if item.name != "exclude_context_bucket"]
        updated_filters.append(FilterRule(name="exclude_context_bucket", rule=context_bucket))
        return {
            "candidate": source_candidate.model_copy(
                update={
                    "candidate_id": mutated_candidate_id,
                    "title": f"{source_candidate.title} Context Guard",
                    "thesis": (
                        f"{source_candidate.thesis} Context-guard mutation derived from {source_candidate_id} "
                        f"to suppress {context_bucket} entries inside the current breakout family."
                    ),
                    "market_context": source_candidate.market_context.model_copy(
                        update={
                            "execution_notes": list(source_candidate.market_context.execution_notes)
                            + [f"Single-step controller suppresses {context_bucket} entries from {source_candidate_id}."],
                        }
                    ),
                    "notes": list(source_candidate.notes)
                    + [
                        f"Mutated from {source_candidate_id} via single-step controller.",
                        f"Added exclude_context_bucket={context_bucket} to suppress the weakest shared walk-forward context.",
                    ],
                }
            ),
            "spec": source_spec.model_copy(
                update={
                    "candidate_id": mutated_candidate_id,
                    "benchmark_group_id": mutated_candidate_id,
                    "variant_name": f"context_guard_{context_bucket}",
                    "filters": updated_filters,
                    "notes": list(source_spec.notes)
                    + [
                        f"Mutation source candidate: {source_candidate_id}.",
                        f"Added exclude_context_bucket={context_bucket} under bounded single-step controller.",
                    ],
                }
            ),
            "changed_fields": [
                "candidate_id",
                "title",
                "thesis",
                "variant_name",
                "market_context.execution_notes",
                "filters.exclude_context_bucket",
            ],
            "step_payload": {
                "context_bucket": context_bucket,
            },
            "gate_outcomes": {
                "context_bucket": context_bucket,
            },
        }
    return None


def _profit_factor(pnl: pd.Series) -> float:
    if pnl.empty:
        return 0.0
    gross_profit = pnl[pnl > 0].sum()
    gross_loss = abs(pnl[pnl < 0].sum()) or 1e-9
    return float(gross_profit / gross_loss)


def _timestamp(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    if hasattr(value, "to_pydatetime"):
        return value.to_pydatetime().astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _apply_continuation_metadata(settings: Settings, report: NextStepControllerReport) -> None:
    decision = _determine_continuation_decision(settings, report)
    report.continuation_status = decision.continuation_status
    report.stop_class = decision.stop_class
    report.auto_continue_allowed = decision.auto_continue_allowed
    report.recommended_follow_on_step = decision.recommended_follow_on_step
    report.max_safe_follow_on_steps = decision.max_safe_follow_on_steps
    report.transition_status = _determine_transition_status(report)
    report.transition_intent = _determine_transition_intent(report)
    report.policy_snapshot_hash = policy_snapshot_hash(settings)


def _determine_continuation_decision(settings: Settings, report: NextStepControllerReport) -> _ContinuationDecision:
    follow_on = next((item for item in report.next_recommendations if item.binding and item.evidence_status == "supported"), None)
    recommended_follow_on_step = follow_on.step_type if follow_on else None
    diagnosis_family_follow_on = _diagnosis_follow_on_after_family_correction(settings, report)

    if report.status != "completed":
        stop_class = _classify_stop_reason(report.stop_reason)
        return _ContinuationDecision(
            continuation_status="stop",
            stop_class=stop_class,
            auto_continue_allowed=False,
            recommended_follow_on_step=recommended_follow_on_step,
            max_safe_follow_on_steps=0,
        )

    if report.selected_step_type == "hypothesis_audit":
        lane_decision = (
            report.hypothesis_audit_reports[0].lane_decision
            if report.hypothesis_audit_reports
            else None
        )
        if lane_decision == "narrow_correction_supported" and follow_on is not None:
            return _ContinuationDecision(
                continuation_status="continue",
                stop_class="none",
                auto_continue_allowed=True,
                recommended_follow_on_step=recommended_follow_on_step,
                max_safe_follow_on_steps=1,
            )
        return _ContinuationDecision(
            continuation_status="stop",
            stop_class="policy_decision",
            auto_continue_allowed=False,
            recommended_follow_on_step=recommended_follow_on_step,
            max_safe_follow_on_steps=0,
        )

    if report.selected_step_type == "data_feature_audit":
        if (
            report.data_feature_audit_reports
            and report.data_feature_audit_reports[0].family_decision == "bounded_correction_supported"
            and follow_on is not None
        ):
            return _ContinuationDecision(
                continuation_status="continue",
                stop_class="none",
                auto_continue_allowed=True,
                recommended_follow_on_step=follow_on.step_type,
                max_safe_follow_on_steps=1,
            )
        return _ContinuationDecision(
            continuation_status="stop",
            stop_class="policy_decision",
            auto_continue_allowed=False,
            recommended_follow_on_step="data_label_audit"
            if report.data_feature_audit_reports
            and report.data_feature_audit_reports[0].family_decision == "retire_family"
            else None,
            max_safe_follow_on_steps=0,
        )

    if report.selected_step_type == "data_label_audit":
        return _ContinuationDecision(
            continuation_status="stop",
            stop_class="policy_decision",
            auto_continue_allowed=False,
            recommended_follow_on_step=None,
            max_safe_follow_on_steps=0,
        )

    if report.selected_step_type == "triage_reviewable_candidate":
        return _ContinuationDecision(
            continuation_status="stop",
            stop_class="policy_decision",
            auto_continue_allowed=False,
            recommended_follow_on_step=None,
            max_safe_follow_on_steps=0,
        )

    if report.selected_step_type == "data_regime_audit" and follow_on is None:
        return _ContinuationDecision(
            continuation_status="stop",
            stop_class="policy_decision",
            auto_continue_allowed=False,
            recommended_follow_on_step=None,
            max_safe_follow_on_steps=0,
        )

    if diagnosis_family_follow_on is not None:
        return _ContinuationDecision(
            continuation_status="continue",
            stop_class="none",
            auto_continue_allowed=True,
            recommended_follow_on_step=diagnosis_family_follow_on,
            max_safe_follow_on_steps=1,
        )

    if follow_on is None:
        stop_class = "ambiguity"
        if _lane_exhausted_from_report(report, settings):
            stop_class = "lane_exhausted"
        return _ContinuationDecision(
            continuation_status="stop",
            stop_class=stop_class,
            auto_continue_allowed=False,
            recommended_follow_on_step=None,
            max_safe_follow_on_steps=0,
        )

    if follow_on.step_type == "human_review":
        return _ContinuationDecision(
            continuation_status="stop",
            stop_class="approval_required",
            auto_continue_allowed=False,
            recommended_follow_on_step=follow_on.step_type,
            max_safe_follow_on_steps=0,
        )

    if _lane_exhausted_from_report(report, settings):
        return _ContinuationDecision(
            continuation_status="stop",
            stop_class="lane_exhausted",
            auto_continue_allowed=False,
            recommended_follow_on_step=follow_on.step_type,
            max_safe_follow_on_steps=0,
        )

    if follow_on.step_type == "run_parity" and not _binding_recommendation_approvals_present(settings, follow_on):
        return _ContinuationDecision(
            continuation_status="stop",
            stop_class="approval_required",
            auto_continue_allowed=False,
            recommended_follow_on_step=follow_on.step_type,
            max_safe_follow_on_steps=0,
        )

    return _ContinuationDecision(
        continuation_status="continue",
        stop_class="none",
        auto_continue_allowed=True,
        recommended_follow_on_step=follow_on.step_type,
        max_safe_follow_on_steps=1,
    )


def _classify_stop_reason(stop_reason: str | None) -> str:
    reason = str(stop_reason or "")
    if "upstream_contract" in reason:
        return "blocked_upstream_contract"
    if "stale" in reason and "approval" in reason:
        return "blocked_evidence_stale"
    if "no_pending" in reason:
        return "blocked_no_candidates"
    if "approval" in reason:
        return "approval_required"
    if "budget" in reason:
        return "budget_exhausted"
    if "artifact" in reason or "integrity" in reason or "collision" in reason:
        return "integrity_issue"
    if (
        "outside_allowed_step_types" in reason
        or "unsupported" in reason
        or "parity_policy" in reason
        or "parity_class" in reason
        or "hypothesis_audit" in reason
        or "data_regime_audit" in reason
        or "data_feature_audit" in reason
        or "data_label_audit" in reason
    ):
        return "policy_decision"
    if "lane_exhausted" in reason:
        return "lane_exhausted"
    return "ambiguity"


def _determine_transition_status(report: NextStepControllerReport) -> str:
    if report.auto_continue_allowed:
        return "continue_lane"
    if report.stop_class in {
        "approval_required",
        "integrity_issue",
        "budget_exhausted",
        "blocked_upstream_contract",
        "blocked_evidence_stale",
        "blocked_no_candidates",
        "blocked_no_authorized_path",
        "integrity_exception",
    }:
        return "hard_stop"
    if report.selected_step_type == "hypothesis_audit":
        if report.hypothesis_audit_reports:
            lane_decision = report.hypothesis_audit_reports[0].lane_decision
            if lane_decision == "narrow_correction_supported":
                return "continue_lane"
            if lane_decision == "hold_reference_blocked_by_robustness":
                return "continue_lane"
            if lane_decision == "retire_lane":
                return "move_to_next_lane"
        return "hard_stop"
    if report.selected_step_type == "data_regime_audit":
        if report.data_regime_audit_reports:
            lane_decision = report.data_regime_audit_reports[0].lane_decision
            if lane_decision == "narrow_correction_supported":
                return "continue_lane"
            if lane_decision in {"retire_lane", "structural_regime_instability"}:
                return "move_to_next_lane"
        return "hard_stop"
    if report.selected_step_type == "data_feature_audit":
        return "hard_stop"
    if report.selected_step_type == "data_label_audit":
        return "hard_stop"
    if report.selected_step_type == "triage_reviewable_candidate":
        return "move_to_next_lane"
    if report.stop_class == "lane_exhausted":
        return "continue_lane"
    return "hard_stop"


def _determine_transition_intent(report: NextStepControllerReport) -> str:
    if report.transition_status == "continue_lane":
        if report.recommended_follow_on_step == report.selected_step_type:
            return "resume_same_candidate"
        return "advance_same_lane"
    if report.transition_status == "move_to_next_lane":
        return "advance_next_lane"
    return "stop_terminal"


def _lane_exhausted_from_report(report: NextStepControllerReport, settings: Settings) -> bool:
    if report.selected_step_type == "diagnose_existing_candidates":
        return _diagnosis_indicates_lane_exhaustion(report, settings)
    if not report.reevaluation_reports:
        return False
    validation = settings.validation
    for reevaluation in report.reevaluation_reports:
        if reevaluation.walk_forward_ok:
            return False
        if reevaluation.stress_passed:
            return False
        if reevaluation.trade_count >= validation.minimum_test_trade_count and reevaluation.expectancy_pips > validation.expectancy_floor:
            return False
        if (
            reevaluation.trade_count >= validation.minimum_test_trade_count
            and reevaluation.out_of_sample_profit_factor >= validation.out_of_sample_profit_factor_floor
        ):
            return False
    return True


def _diagnosis_indicates_lane_exhaustion(report: NextStepControllerReport, settings: Settings) -> bool:
    if report.next_recommendations or not report.candidate_reports:
        return False
    minimum_trade_count = settings.validation.minimum_test_trade_count
    for candidate_report in report.candidate_reports:
        total_trade_count = candidate_report.first_window_trade_count + candidate_report.later_window_trade_count
        if candidate_report.supported_slices:
            return False
        if total_trade_count >= minimum_trade_count:
            return False
        if candidate_report.walk_forward_failed_window <= 0:
            return False
    return True


def _diagnosis_follow_on_after_family_correction(
    settings: Settings,
    report: NextStepControllerReport,
) -> str | None:
    if report.selected_step_type != "diagnose_existing_candidates":
        return None
    if report.stop_reason != "diagnosis_ambiguous_no_mutation_justified":
        return None
    if report.next_recommendations or not report.candidate_reports:
        return None
    if any(candidate_report.supported_slices or candidate_report.recommended_mutation for candidate_report in report.candidate_reports):
        return None
    parent_report = _load_controller_report_for_campaign(settings, report.parent_campaign_id)
    if parent_report is None or parent_report.selected_step_type != "data_feature_audit":
        return None
    if not parent_report.data_feature_audit_reports:
        return None
    if parent_report.data_feature_audit_reports[0].family_decision != "bounded_correction_supported":
        return None
    return "data_feature_audit"
