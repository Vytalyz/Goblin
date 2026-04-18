from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentic_forex.config import Settings
from agentic_forex.goblin.models import (
    AgentAction,
    ApprovalBoundary,
    BoundedAgentRole,
    BrokerReconciliationReport,
    CandidateScorecard,
    DeploymentBundle,
    DeploymentLadderState,
    DeploymentProfile,
    EvaluationSuite,
    ExperimentAccountingLedger,
    ExperimentBudgetCaps,
    GoblinRunRecord,
    IncidentClosurePacket,
    IncidentRecord,
    IncidentSeverity,
    IncidentSlaClass,
    InvestigationPack,
    InvestigationScenario,
    InvestigationTrace,
    KnowledgeEventRecord,
    KnowledgeLineageRecord,
    LiveAttachManifest,
    ModelRegistryEntry,
    MT5CertificationReport,
    OfflineTrainingCycle,
    PromotionDecisionPacket,
    RetrievalCitation,
    RetrievalDocument,
    RetrievalIndex,
    RetrievalIndexEntry,
    RetrievalResponse,
    RiskOverlay,
    RuntimeHeartbeat,
    RuntimeSummary,
    StrategyMethodologyAudit,
    StrategyRationaleCard,
    TrustedLabelPolicy,
)
from agentic_forex.governance.models import ProductionIncidentReport
from agentic_forex.utils.io import read_json, write_json

_P10_REQUIRED_STATISTICAL_POLICY_KEYS = {
    "validation.parity_timestamp_tolerance_seconds",
    "validation.parity_price_tolerance_pips",
    "validation.parity_min_match_rate",
    "validation.minimum_test_trade_count",
}
_P10_PROMOTION_APPROVAL_STATUSES = {
    "promote",
    "promoted",
    "approved",
    "eligible_for_replacement",
}
_P10_LADDER_STATE_RANK = {
    "shadow_only": 0,
    "limited_demo": 1,
    "observed_demo": 2,
    "challenger_demo": 3,
    "eligible_for_replacement": 4,
}
_P10_DEPLOYMENT_FIT_DELTA_BUNDLE_THRESHOLD = 0.05
_P12_FORBIDDEN_AUTONOMY_ACTIONS: set[AgentAction] = {
    "approve",
    "promote",
    "deploy",
    "bypass_governance",
}


def _tokenize_for_retrieval(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    # Preserve deterministic order while removing duplicates.
    return list(dict.fromkeys(tokens))


def default_approval_boundaries(settings: Settings) -> list[ApprovalBoundary]:
    machine_allowed = sorted(set(settings.autonomy.machine_approvable_stages))
    human_only = sorted(set(settings.autonomy.human_only_stages))
    boundaries: list[ApprovalBoundary] = []
    for stage in machine_allowed:
        boundaries.append(
            ApprovalBoundary(
                stage=stage,
                mode="machine_allowed",
                rationale="Configured machine-approvable stage under autonomy policy.",
                allowed_sources=["policy_engine", "human"],
            )
        )
    for stage in human_only:
        boundaries.append(
            ApprovalBoundary(
                stage=stage,
                mode="human_required",
                rationale="Configured human-only stage under autonomy policy.",
                allowed_sources=["human"],
            )
        )
    return boundaries


def open_incident_record(
    settings: Settings,
    *,
    candidate_id: str,
    title: str,
    incident_id: str | None = None,
    severity: IncidentSeverity = "S3",
    sla_class: IncidentSlaClass = "before_next_promotion_gate",
    incident_type: str | None = None,
    ladder_state_at_incident: DeploymentLadderState | None = None,
    deployed_bundle_id: str | None = None,
    affected_candidate_ids: list[str] | None = None,
    blockers: list[str] | None = None,
    evidence_paths: dict[str, str] | None = None,
    notes: list[str] | None = None,
) -> IncidentRecord:
    record_id = incident_id or f"goblin-incident-{candidate_id}-{_utc_stamp()}"
    report_dir = settings.paths().goblin_incident_reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    record = IncidentRecord(
        incident_id=record_id,
        candidate_id=candidate_id,
        severity=severity,
        sla_class=sla_class,
        incident_type=incident_type,
        title=title,
        affected_candidate_ids=list(affected_candidate_ids or [candidate_id]),
        blockers=list(blockers or []),
        evidence_paths=dict(evidence_paths or {}),
        notes=list(notes or []),
        ladder_state_at_incident=ladder_state_at_incident,
        deployed_bundle_id=deployed_bundle_id,
        report_path=report_dir / f"{record_id}.json",
    )
    write_json(record.report_path, record.model_dump(mode="json"))
    _update_latest_incident_pointer(settings, candidate_id, record.report_path)
    return record


def validate_incident_closure(severity: IncidentSeverity, packet: IncidentClosurePacket) -> list[str]:
    """Return a list of missing required field names for the given severity.

    An empty list means the closure packet satisfies the severity requirements.
    See ``incident-sla.md`` for the authoritative requirements.
    """
    missing: list[str] = []
    if severity == "S1":
        for field in (
            "root_cause_classification",
            "root_cause_description",
            "corrective_action",
            "verification_evidence_path",
            "deployed_bundle_id",
            "approved_by",
        ):
            if not getattr(packet, field, None):
                missing.append(field)
    elif severity == "S2":
        for field in ("root_cause_classification", "root_cause_description", "deployed_bundle_id", "approved_by"):
            if not getattr(packet, field, None):
                missing.append(field)
        if not packet.corrective_action and not packet.monitoring_plan:
            missing.append("corrective_action_or_monitoring_plan")
    elif severity == "S3":
        if not packet.root_cause_note:
            missing.append("root_cause_note")
    # S4 requires no formal closure evidence
    return missing


def close_incident_record(
    settings: Settings,
    *,
    candidate_id: str,
    incident_id: str,
    resolution_summary: str,
    approved_by: str | None = None,
    evidence_paths: dict[str, str] | None = None,
    root_cause_classification: str | None = None,
    root_cause_description: str | None = None,
    root_cause_note: str | None = None,
    corrective_action: str | None = None,
    monitoring_plan: str | None = None,
    verification_evidence_path: str | None = None,
    deployed_bundle_id: str | None = None,
    ladder_state_at_incident: DeploymentLadderState | None = None,
) -> IncidentClosurePacket:
    report_dir = settings.paths().goblin_incident_reports_dir / candidate_id
    record_path = report_dir / f"{incident_id}.json"
    if not record_path.exists():
        raise FileNotFoundError(f"Incident record not found: {incident_id}")
    record = IncidentRecord.model_validate(read_json(record_path))

    closure = IncidentClosurePacket(
        incident_id=incident_id,
        resolution_summary=resolution_summary,
        root_cause_classification=root_cause_classification,
        root_cause_description=root_cause_description,
        root_cause_note=root_cause_note,
        corrective_action=corrective_action,
        monitoring_plan=monitoring_plan,
        verification_evidence_path=verification_evidence_path,
        deployed_bundle_id=deployed_bundle_id or record.deployed_bundle_id,
        ladder_state_at_incident=ladder_state_at_incident or record.ladder_state_at_incident,
        evidence_paths=dict(evidence_paths or record.evidence_paths),
        approved_by=approved_by,
        report_path=report_dir / f"{incident_id}.closure.json",
    )

    missing = validate_incident_closure(record.severity, closure)
    if missing:
        raise ValueError(
            f"Closure packet for {record.severity} incident {incident_id} is missing required fields: {missing}"
        )

    record.lifecycle_status = "closed"
    if resolution_summary not in record.notes:
        record.notes.append(resolution_summary)
    write_json(record_path, record.model_dump(mode="json"))
    write_json(closure.report_path, closure.model_dump(mode="json"))
    _update_latest_incident_pointer(settings, candidate_id, record_path)
    return closure


def list_open_blocking_incidents(settings: Settings, *, candidate_id: str) -> list[IncidentRecord]:
    """Return all open or monitoring S1/S2 incidents for ``candidate_id``.

    These incidents block new live attaches and ladder advancement per the
    incident-severity-matrix and deployment-ladder contracts.
    """
    report_dir = settings.paths().goblin_incident_reports_dir / candidate_id
    if not report_dir.exists():
        return []
    blocking: list[IncidentRecord] = []
    for path in report_dir.glob("*.json"):
        if path.stem.endswith(".closure"):
            continue
        try:
            record = IncidentRecord.model_validate(read_json(path))
        except Exception:
            continue
        if record.lifecycle_status in ("open", "monitoring") and record.severity in ("S1", "S2"):
            blocking.append(record)
    return blocking


def build_deployment_bundle(
    settings: Settings,
    *,
    candidate_id: str,
    bundle_id: str | None = None,
    rollback_criteria: list[str] | None = None,
) -> DeploymentBundle:
    resolved_bundle_id = bundle_id or f"{candidate_id}-{_utc_stamp()}"
    report_dir = settings.paths().reports_dir / candidate_id
    goblin_dir = settings.paths().goblin_deployment_bundles_dir / candidate_id
    goblin_dir.mkdir(parents=True, exist_ok=True)

    packet = _load_mt5_packet_payload(settings, candidate_id)
    certified_run_id = _latest_certified_mt5_run_id(settings, candidate_id)

    ea_build_hash = _first_existing_hash(
        report_dir / "candidate.ex5",
        report_dir / "CandidateEA.ex5",
        _payload_path(packet, "compiled_ex5_path"),
    )
    inputs_hash = _first_existing_hash(
        report_dir / "tester_inputs.set",
        report_dir / "packet_inputs.set",
        _certified_run_set_path(settings, candidate_id, certified_run_id),
        _packet_run_set_path(candidate_id, packet),
    )
    validation_packet_hash = _first_existing_hash(
        settings.paths().goblin_truth_alignment_reports_dir / candidate_id / "truth_alignment_report.json",
        report_dir / "review_packet.json",
        settings.paths().approvals_dir / "mt5_packets" / candidate_id / "packet.json",
    )
    approval_refs = _candidate_approval_refs(settings, candidate_id)

    bundle = DeploymentBundle(
        candidate_id=candidate_id,
        bundle_id=resolved_bundle_id,
        ea_build_hash=ea_build_hash,
        inputs_hash=inputs_hash,
        symbol_assumptions={
            "instrument": settings.data.instrument,
            "execution_granularity": settings.data.execution_granularity,
        },
        account_assumptions={
            "currency": settings.policy.default_account_currency,
            "initial_balance": settings.policy.default_initial_balance,
            "leverage": settings.policy.default_leverage,
            "max_total_exposure_lots": settings.policy.default_max_total_exposure_lots,
        },
        validation_packet_hash=validation_packet_hash,
        approval_refs=approval_refs,
        rollback_criteria=list(
            rollback_criteria
            or [
                "material_runtime_error",
                "parity_regression",
                "unresolved_operational_incident",
            ]
        ),
    )
    output_path = goblin_dir / f"{resolved_bundle_id}.json"
    write_json(output_path, bundle.model_dump(mode="json"))
    return bundle


def write_mt5_certification_report(
    settings: Settings,
    *,
    report: MT5CertificationReport,
) -> MT5CertificationReport:
    report_dir = settings.paths().goblin_mt5_certification_reports_dir / report.candidate_id / report.run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    resolved = report.model_copy(update={"report_path": report_dir / "mt5_certification_report.json"})
    write_json(resolved.report_path, resolved.model_dump(mode="json"))
    return resolved


def write_investigation_scenario(
    settings: Settings,
    *,
    scenario: InvestigationScenario,
) -> InvestigationScenario:
    if not scenario.candidate_id:
        raise ValueError("InvestigationScenario.candidate_id is required.")
    report_dir = _investigation_pack_root(
        settings, candidate_id=scenario.candidate_id, incident_id=scenario.incident_id
    )
    scenarios_dir = report_dir / "scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)
    resolved = scenario.model_copy(
        update={"report_path": scenarios_dir / _stable_json_filename(scenario.scenario_id, prefix="scenario")}
    )
    write_json(resolved.report_path, resolved.model_dump(mode="json"))
    return resolved


def write_investigation_trace(
    settings: Settings,
    *,
    trace: InvestigationTrace,
) -> InvestigationTrace:
    if not trace.candidate_id:
        raise ValueError("InvestigationTrace.candidate_id is required.")
    report_dir = _investigation_pack_root(settings, candidate_id=trace.candidate_id, incident_id=trace.incident_id)
    traces_dir = report_dir / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    resolved = trace.model_copy(
        update={"report_path": traces_dir / _stable_json_filename(trace.trace_id, prefix="trace")}
    )
    write_json(resolved.report_path, resolved.model_dump(mode="json"))
    return resolved


def write_evaluation_suite(
    settings: Settings,
    *,
    suite: EvaluationSuite,
) -> EvaluationSuite:
    if not suite.candidate_id:
        raise ValueError("EvaluationSuite.candidate_id is required.")
    incident_id = suite.incident_id or suite.suite_id
    report_dir = settings.paths().goblin_evaluation_reports_dir / suite.candidate_id / incident_id
    report_dir.mkdir(parents=True, exist_ok=True)
    resolved = suite.model_copy(
        update={"report_path": report_dir / _stable_json_filename(suite.suite_id, prefix="suite")}
    )
    write_json(resolved.report_path, resolved.model_dump(mode="json"))
    return resolved


def build_incident_investigation_pack(
    settings: Settings,
    *,
    incident_report_path: Path,
    pack_id: str | None = None,
) -> InvestigationPack:
    incident = ProductionIncidentReport.model_validate(read_json(incident_report_path))
    resolved_pack_id = pack_id or f"investigation-pack-{incident.incident_id}"
    benchmark_history_path = _write_benchmark_history(
        settings, incident=incident, incident_report_path=incident_report_path
    )

    scenario_paths: list[Path] = []
    scenarios = _build_investigation_scenarios(incident, incident_report_path=incident_report_path)
    for scenario in scenarios:
        resolved_scenario = write_investigation_scenario(settings, scenario=scenario)
        assert resolved_scenario.report_path is not None
        scenario_paths.append(resolved_scenario.report_path)

    trace = write_investigation_trace(
        settings,
        trace=InvestigationTrace(
            trace_id=f"trace-{incident.incident_id}",
            scenario_id=scenarios[0].scenario_id,
            incident_id=incident.incident_id,
            candidate_id=incident.candidate_id,
            evidence_refs=_investigation_evidence_refs(
                incident, incident_report_path=incident_report_path, benchmark_history_path=benchmark_history_path
            ),
            tool_calls=_investigation_tool_calls(incident),
            intermediate_classifications=_intermediate_classifications(incident),
            findings=_investigation_findings(incident),
            follow_up_actions=_follow_up_actions(incident),
            final_classification=incident.attribution_bucket,
            confidence=_investigation_confidence(incident),
        ),
    )
    suite = write_evaluation_suite(
        settings,
        suite=EvaluationSuite(
            suite_id=f"suite-{incident.incident_id}",
            title=f"Incident evaluation suite for {incident.incident_id}",
            incident_id=incident.incident_id,
            candidate_id=incident.candidate_id,
            scenario_ids=[scenario.scenario_id for scenario in scenarios],
            benchmark_history_path=benchmark_history_path,
            notes=[
                "Deterministic regression and replay-backed scenarios remain advisory.",
                "Benchmark history is frozen from the incident report used to build the pack.",
            ],
        ),
    )

    pack_root = _investigation_pack_root(settings, candidate_id=incident.candidate_id, incident_id=incident.incident_id)
    pack = InvestigationPack(
        pack_id=resolved_pack_id,
        incident_id=incident.incident_id,
        candidate_id=incident.candidate_id,
        scenario_paths=scenario_paths,
        trace_path=trace.report_path,
        evaluation_suite_path=suite.report_path,
        benchmark_history_path=benchmark_history_path,
        report_path=pack_root / "investigation_pack.json",
    )
    write_json(pack.report_path, pack.model_dump(mode="json"))
    return pack


def write_strategy_rationale_card(
    settings: Settings,
    *,
    family: str,
    thesis: str,
    candidate_id: str | None = None,
    invalidation_conditions: list[str] | None = None,
    hostile_regimes: list[str] | None = None,
    execution_assumptions: list[str] | None = None,
    non_deployable_conditions: list[str] | None = None,
) -> StrategyRationaleCard:
    target_id = candidate_id or family
    report_dir = settings.paths().goblin_rationale_cards_dir / target_id
    report_dir.mkdir(parents=True, exist_ok=True)
    card = StrategyRationaleCard(
        family=family,
        candidate_id=candidate_id,
        thesis=thesis,
        invalidation_conditions=list(invalidation_conditions or []),
        hostile_regimes=list(hostile_regimes or []),
        execution_assumptions=list(execution_assumptions or []),
        non_deployable_conditions=list(non_deployable_conditions or []),
        report_path=report_dir / "strategy_rationale_card.json",
    )
    write_json(card.report_path, card.model_dump(mode="json"))
    return card


def write_experiment_accounting_ledger(
    settings: Settings,
    *,
    family: str,
    budget_caps: ExperimentBudgetCaps | dict[str, int] | None = None,
) -> ExperimentAccountingLedger:
    if isinstance(budget_caps, dict):
        resolved_caps = ExperimentBudgetCaps(**budget_caps)
    else:
        resolved_caps = budget_caps or ExperimentBudgetCaps()
    entries = _load_family_trial_entries(settings, family=family)
    trial_count_family = len(entries)
    failed_refinement_count = sum(1 for entry in entries if _is_failed_refinement_entry(entry))
    max_observed_mutation_depth = _max_observed_mutation_depth(entries)

    suspension_reasons: list[str] = []
    if trial_count_family >= resolved_caps.max_trials_per_family:
        suspension_reasons.append(
            f"family trial cap reached ({trial_count_family}/{resolved_caps.max_trials_per_family})"
        )
    if failed_refinement_count >= resolved_caps.max_failed_refinements:
        suspension_reasons.append(
            f"failed refinement cap reached ({failed_refinement_count}/{resolved_caps.max_failed_refinements})"
        )
    if max_observed_mutation_depth > resolved_caps.max_mutation_depth:
        suspension_reasons.append(
            f"mutation depth cap exceeded ({max_observed_mutation_depth}>{resolved_caps.max_mutation_depth})"
        )

    rationale_card_path = _find_family_rationale_card(settings, family=family)
    report_dir = settings.paths().goblin_experiment_accounting_dir / family
    report_dir.mkdir(parents=True, exist_ok=True)
    ledger = ExperimentAccountingLedger(
        family=family,
        trial_count_family=trial_count_family,
        failed_refinement_count=failed_refinement_count,
        max_observed_mutation_depth=max_observed_mutation_depth,
        suspended=bool(suspension_reasons),
        suspension_reasons=suspension_reasons,
        invalid_comparison_rules=[
            "in_sample_vs_out_of_sample_is_invalid",
            "cross_window_comparison_requires_regime_accounting",
            "research_backtest_and_mt5_replay_are_non_substitutable",
        ],
        budget_caps=resolved_caps,
        strategy_rationale_card_path=rationale_card_path,
        trial_ledger_path=settings.paths().experiments_dir / "trial_ledger.jsonl",
        notes=[
            "Statistical decision policy is the minimum research floor before any promotion discussion.",
            "Budget caps are intentionally permissive and should tighten only with evidence.",
        ],
        report_path=report_dir / "experiment_accounting_ledger.json",
    )
    write_json(ledger.report_path, ledger.model_dump(mode="json"))
    return ledger


def enforce_strategy_governance(
    settings: Settings,
    *,
    family: str,
    budget_caps: ExperimentBudgetCaps | dict[str, int] | None = None,
    minimum_methodology_score: float = 0.55,
) -> ExperimentAccountingLedger:
    ledger = write_experiment_accounting_ledger(settings, family=family, budget_caps=budget_caps)
    if ledger.strategy_rationale_card_path is None:
        raise ValueError(f"strategy_governance_blocked:{family}:missing_strategy_rationale_card")
    audit = write_strategy_methodology_audit(
        settings,
        family=family,
        ledger=ledger,
        minimum_required_score=minimum_methodology_score,
    )
    ledger = ledger.model_copy(update={"strategy_methodology_audit_path": audit.report_path})
    if ledger.report_path is not None:
        write_json(ledger.report_path, ledger.model_dump(mode="json"))
    if not audit.passed:
        raise ValueError(
            f"strategy_governance_blocked:{family}:methodology_rubric_below_floor:{audit.weighted_score:.3f}<{audit.minimum_required_score:.3f}"
        )
    if ledger.suspended:
        reasons = "; ".join(ledger.suspension_reasons)
        raise ValueError(f"strategy_governance_blocked:{family}:suspended:{reasons}")
    return ledger


def enforce_candidate_strategy_governance(
    settings: Settings,
    *,
    candidate_id: str,
    minimum_methodology_score: float = 0.55,
) -> ExperimentAccountingLedger:
    family = _resolve_candidate_family(settings, candidate_id=candidate_id)
    if _find_family_rationale_card(settings, family=family) is None:
        _bootstrap_family_rationale_card_from_candidate(settings, candidate_id=candidate_id, family=family)
    ledger = enforce_strategy_governance(
        settings,
        family=family,
        minimum_methodology_score=minimum_methodology_score,
    )
    candidate_entries = _load_candidate_trial_entries(settings, candidate_id=candidate_id)
    if not candidate_entries:
        raise ValueError(f"strategy_governance_blocked:{candidate_id}:missing_experiment_lineage")
    if ledger.report_path is not None:
        notes = list(ledger.notes)
        notes.append(f"lineage_verified_for_candidate:{candidate_id}:{len(candidate_entries)} entries")
        deduped_notes = list(dict.fromkeys(notes))
        ledger = ledger.model_copy(update={"notes": deduped_notes})
        write_json(ledger.report_path, ledger.model_dump(mode="json"))
    return ledger


def write_strategy_methodology_audit(
    settings: Settings,
    *,
    family: str,
    ledger: ExperimentAccountingLedger | None = None,
    minimum_required_score: float = 0.55,
) -> StrategyMethodologyAudit:
    resolved_ledger = ledger or write_experiment_accounting_ledger(settings, family=family)
    rationale_path = resolved_ledger.strategy_rationale_card_path
    rationale_card = (
        StrategyRationaleCard.model_validate(read_json(rationale_path))
        if rationale_path and rationale_path.exists()
        else None
    )

    has_thesis = bool((rationale_card.thesis or "").strip()) if rationale_card else False
    thesis_length = len((rationale_card.thesis or "").strip()) if rationale_card else 0
    has_invalidation = bool(rationale_card and rationale_card.invalidation_conditions)
    has_hostile = bool(rationale_card and rationale_card.hostile_regimes)
    has_execution = bool(rationale_card and rationale_card.execution_assumptions)
    has_non_deployable = bool(rationale_card and rationale_card.non_deployable_conditions)

    missing_requirements: list[str] = []
    if not has_thesis:
        missing_requirements.append("missing_thesis")
    if not has_invalidation:
        missing_requirements.append("missing_invalidation_conditions")
    if not has_hostile:
        missing_requirements.append("missing_hostile_regimes")
    if not has_execution:
        missing_requirements.append("missing_execution_assumptions")

    thesis_score = 1.0 if thesis_length >= 48 else 0.6 if has_thesis else 0.0
    falsifiability_score = 0.0
    if has_invalidation:
        falsifiability_score += 0.6
    if has_non_deployable:
        falsifiability_score += 0.4
    regime_specificity_score = 0.0
    if has_hostile:
        regime_specificity_score += 0.5
    if has_execution:
        regime_specificity_score += 0.5
    search_discipline_score = 1.0 if not resolved_ledger.suspended else 0.25
    has_comparison_guards = {
        "in_sample_vs_out_of_sample_is_invalid",
        "cross_window_comparison_requires_regime_accounting",
    }.issubset(set(resolved_ledger.invalid_comparison_rules))
    comparison_integrity_score = 1.0 if has_comparison_guards else 0.0

    dimension_scores = {
        "thesis_quality": round(thesis_score, 6),
        "falsifiability": round(min(falsifiability_score, 1.0), 6),
        "regime_specificity": round(min(regime_specificity_score, 1.0), 6),
        "search_discipline": round(search_discipline_score, 6),
        "comparison_integrity": round(comparison_integrity_score, 6),
    }
    weighted_score = (
        dimension_scores["thesis_quality"] * 0.30
        + dimension_scores["falsifiability"] * 0.20
        + dimension_scores["regime_specificity"] * 0.20
        + dimension_scores["search_discipline"] * 0.20
        + dimension_scores["comparison_integrity"] * 0.10
    )
    notes = [
        "Methodology audit is family-level governance evidence and does not replace candidate-level validation gates.",
        "Weighted rubric score combines rationale quality, falsifiability, regime specificity, search discipline, and comparison integrity.",
    ]
    if resolved_ledger.suspended:
        notes.append("Family is currently suspended by experiment-accounting budget controls.")
    report_dir = settings.paths().goblin_methodology_audits_dir / family
    report_dir.mkdir(parents=True, exist_ok=True)
    audit = StrategyMethodologyAudit(
        family=family,
        dimension_scores=dimension_scores,
        weighted_score=round(weighted_score, 6),
        minimum_required_score=float(minimum_required_score),
        passed=weighted_score >= float(minimum_required_score),
        missing_requirements=missing_requirements,
        notes=notes,
        report_path=report_dir / "strategy_methodology_audit.json",
    )
    write_json(audit.report_path, audit.model_dump(mode="json"))
    return audit


def write_candidate_scorecard(
    settings: Settings,
    *,
    candidate_id: str,
    alpha_quality: float,
    robustness: float,
    executable_parity: float,
    operational_reliability: float,
    deployment_fit: float,
    notes: list[str] | None = None,
) -> CandidateScorecard:
    report_dir = settings.paths().goblin_scorecards_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    scorecard = CandidateScorecard(
        candidate_id=candidate_id,
        alpha_quality=alpha_quality,
        robustness=robustness,
        executable_parity=executable_parity,
        operational_reliability=operational_reliability,
        deployment_fit=deployment_fit,
        notes=list(notes or []),
        report_path=report_dir / "candidate_scorecard.json",
    )
    write_json(scorecard.report_path, scorecard.model_dump(mode="json"))
    return scorecard


def write_promotion_decision_packet(
    settings: Settings,
    *,
    candidate_id: str,
    decision_status: str,
    scorecard_path: Path | None = None,
    truth_alignment_report_path: Path | None = None,
    strategy_rationale_card_path: Path | None = None,
    experiment_accounting_ledger_path: Path | None = None,
    strategy_methodology_audit_path: Path | None = None,
    approval_refs: list[str] | None = None,
    deployment_profile: dict | None = None,
    risk_overlay: dict | None = None,
    search_bias_summary: list[str] | None = None,
    statistical_policy_keys: list[str] | None = None,
    deployment_ladder_state: DeploymentLadderState | None = None,
    deployment_fit_delta: float | None = None,
    deployment_fit_change_requires_new_bundle: bool = False,
    deployment_bundle_id: str | None = None,
    notes: list[str] | None = None,
) -> PromotionDecisionPacket:
    report_dir = settings.paths().goblin_deployment_bundles_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    family = _resolve_candidate_family(settings, candidate_id=candidate_id)
    ledger = write_experiment_accounting_ledger(settings, family=family)
    methodology_audit = write_strategy_methodology_audit(settings, family=family, ledger=ledger)

    resolved_rationale_path = strategy_rationale_card_path or ledger.strategy_rationale_card_path
    resolved_ledger_path = experiment_accounting_ledger_path or ledger.report_path
    resolved_methodology_path = strategy_methodology_audit_path or methodology_audit.report_path
    resolved_search_bias_summary = list(search_bias_summary or [])
    resolved_statistical_policy_keys = list(
        dict.fromkeys(statistical_policy_keys or sorted(_P10_REQUIRED_STATISTICAL_POLICY_KEYS))
    )
    resolved_ladder_state = deployment_ladder_state or _resolve_latest_candidate_ladder_state(
        settings,
        candidate_id=candidate_id,
    )
    if ledger.report_path is not None:
        resolved_search_bias_summary.append(
            f"family={ledger.family}; trial_count={ledger.trial_count_family}; failed_refinements={ledger.failed_refinement_count}; max_mutation_depth={ledger.max_observed_mutation_depth}; suspended={ledger.suspended}"
        )
    if methodology_audit.report_path is not None:
        resolved_search_bias_summary.append(
            f"methodology_audit_score={methodology_audit.weighted_score:.3f}; minimum_required={methodology_audit.minimum_required_score:.3f}; passed={methodology_audit.passed}"
        )
    if methodology_audit.missing_requirements:
        resolved_search_bias_summary.append(
            f"methodology_missing_requirements={','.join(methodology_audit.missing_requirements)}"
        )
    resolved_search_bias_summary = list(dict.fromkeys(resolved_search_bias_summary))

    missing_policy_keys = sorted(
        _P10_REQUIRED_STATISTICAL_POLICY_KEYS.difference(set(resolved_statistical_policy_keys))
    )
    if missing_policy_keys:
        raise ValueError("promotion_packet_missing_statistical_policy_keys: " + ", ".join(missing_policy_keys))
    if resolved_ladder_state is None:
        raise ValueError(
            "promotion_packet_missing_ladder_state: deployment_ladder_state is required by deployment-ladder contract"
        )
    is_promotion_approval = decision_status.strip().lower() in _P10_PROMOTION_APPROVAL_STATUSES
    if (
        is_promotion_approval
        and _P10_LADDER_STATE_RANK[resolved_ladder_state] < _P10_LADDER_STATE_RANK["observed_demo"]
    ):
        raise ValueError(
            "promotion_blocked_below_observed_demo: candidate ladder state must be observed_demo or higher"
        )

    requires_new_bundle = bool(deployment_fit_change_requires_new_bundle)
    if deployment_fit_delta is not None and abs(deployment_fit_delta) >= _P10_DEPLOYMENT_FIT_DELTA_BUNDLE_THRESHOLD:
        requires_new_bundle = True
    if requires_new_bundle and not deployment_bundle_id:
        raise ValueError(
            "deployment_fit_delta_requires_new_bundle: provide deployment_bundle_id when deployment fit changes materially"
        )

    packet = PromotionDecisionPacket(
        candidate_id=candidate_id,
        decision_status=decision_status,
        statistical_policy_keys=resolved_statistical_policy_keys,
        deployment_ladder_state=resolved_ladder_state,
        scorecard_path=scorecard_path,
        truth_alignment_report_path=truth_alignment_report_path,
        strategy_rationale_card_path=resolved_rationale_path,
        experiment_accounting_ledger_path=resolved_ledger_path,
        strategy_methodology_audit_path=resolved_methodology_path,
        search_bias_summary=resolved_search_bias_summary,
        deployment_fit_delta=deployment_fit_delta,
        deployment_fit_change_requires_new_bundle=requires_new_bundle,
        deployment_bundle_id=deployment_bundle_id,
        approval_refs=list(approval_refs or _candidate_approval_refs(settings, candidate_id)),
        deployment_profile=DeploymentProfile(**deployment_profile) if deployment_profile else None,
        risk_overlay=RiskOverlay(**risk_overlay) if risk_overlay else None,
        notes=list(notes or []),
        report_path=report_dir / "promotion_decision_packet.json",
    )
    write_json(packet.report_path, packet.model_dump(mode="json"))
    return packet


def write_model_registry_entry(settings: Settings, *, entry: ModelRegistryEntry) -> ModelRegistryEntry:
    report_dir = settings.paths().goblin_model_registry_dir / entry.model_id
    report_dir.mkdir(parents=True, exist_ok=True)
    updates: dict[str, Any] = {"report_path": report_dir / "model_registry_entry.json"}
    if entry.label_policy_path is None and entry.label_policy:
        updates["label_policy_path"] = (
            settings.paths().goblin_label_policies_dir / entry.label_policy / "trusted_label_policy.json"
        )
    if entry.training_cycle_path is None:
        cycle_root = settings.paths().goblin_training_cycles_dir / entry.model_id
        latest_cycle_path: Path | None = None
        if cycle_root.exists():
            cycle_files = sorted(cycle_root.glob("*/offline_training_cycle.json"))
            if cycle_files:
                latest_cycle_path = cycle_files[-1]
        updates["training_cycle_path"] = latest_cycle_path
    resolved = entry.model_copy(update=updates)
    write_json(resolved.report_path, resolved.model_dump(mode="json"))
    return resolved


def write_trusted_label_policy(
    settings: Settings,
    *,
    policy: TrustedLabelPolicy,
) -> TrustedLabelPolicy:
    """Persist a TrustedLabelPolicy artifact.

    Raises ``ValueError`` if ``ambiguity_rejection_criteria`` is empty — at least one
    criterion is required so label quality is explicitly governed.
    """
    if not policy.ambiguity_rejection_criteria:
        raise ValueError("trusted_label_policy_requires_ambiguity_rejection_criteria")
    report_dir = settings.paths().goblin_label_policies_dir / policy.policy_id
    report_dir.mkdir(parents=True, exist_ok=True)
    resolved = policy.model_copy(update={"report_path": report_dir / "trusted_label_policy.json"})
    write_json(resolved.report_path, resolved.model_dump(mode="json"))
    return resolved


def write_offline_training_cycle(
    settings: Settings,
    *,
    cycle: OfflineTrainingCycle,
) -> OfflineTrainingCycle:
    """Persist an OfflineTrainingCycle artifact.

    Raises ``ValueError`` if:
    - ``holdout_window_ids`` is empty (holdout evaluation is mandatory).
    - ``touches_live_execution`` is True but ``mt5_certification_path`` is None
      (live-touching models require MT5 certification evidence).
    """
    if not cycle.holdout_window_ids:
        raise ValueError("offline_training_requires_holdout_windows")
    if cycle.touches_live_execution and cycle.mt5_certification_path is None:
        raise ValueError("live_execution_model_requires_mt5_certification")
    report_dir = settings.paths().goblin_training_cycles_dir / cycle.model_id / cycle.cycle_id
    report_dir.mkdir(parents=True, exist_ok=True)
    resolved = cycle.model_copy(update={"report_path": report_dir / "offline_training_cycle.json"})
    write_json(resolved.report_path, resolved.model_dump(mode="json"))
    return resolved


def enforce_ml_governance(
    settings: Settings,
    *,
    model_id: str,
    touches_live_execution: bool = False,
) -> ModelRegistryEntry:
    """Load a model registry entry and assert ML governance constraints.

    Raises ``ValueError`` if:
    - ``online_self_tuning_enabled`` is True (forbidden by P11 exit criterion).
    - ``touches_live_execution`` is True and the registry entry is not approved.
    """
    entry_path = settings.paths().goblin_model_registry_dir / model_id / "model_registry_entry.json"
    if not entry_path.exists():
        raise FileNotFoundError(f"model_registry_entry not found for model_id={model_id!r}")
    data = read_json(entry_path)
    entry = ModelRegistryEntry.model_validate(data)
    if entry.online_self_tuning_enabled:
        raise ValueError("ml_governance_blocked_online_self_tuning")
    if touches_live_execution and entry.approval_state != "approved":
        raise ValueError("ml_governance_blocked_unapproved_model")
    return entry


def write_knowledge_lineage(settings: Settings, *, record: KnowledgeLineageRecord) -> KnowledgeLineageRecord:
    report_dir = settings.paths().goblin_knowledge_reports_dir / record.subject_type
    report_dir.mkdir(parents=True, exist_ok=True)
    resolved = record.model_copy(update={"report_path": report_dir / f"{record.subject_id}.json"})
    write_json(resolved.report_path, resolved.model_dump(mode="json"))
    return resolved


def append_knowledge_event(settings: Settings, *, event: KnowledgeEventRecord) -> Path:
    """Append a structured knowledge event into the Goblin event store."""
    events_path = settings.paths().goblin_knowledge_events_dir / "knowledge_events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event.model_dump(mode="json"), default=str) + "\n")
    return events_path


def write_retrieval_document(
    settings: Settings,
    *,
    document: RetrievalDocument,
    content: str | None = None,
) -> RetrievalDocument:
    """Persist retrieval metadata and optional content for vector indexing."""
    report_dir = settings.paths().goblin_retrieval_documents_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    content_path = document.content_path
    if content is not None:
        content_path = report_dir / f"{document.document_id}.txt"
        content_path.write_text(content, encoding="utf-8")
    resolved = document.model_copy(update={"content_path": content_path})
    write_json(report_dir / f"{document.document_id}.json", resolved.model_dump(mode="json"))
    return resolved


def build_retrieval_index(settings: Settings) -> RetrievalIndex:
    """Build a deterministic token index from structured retrieval documents."""
    docs_dir = settings.paths().goblin_retrieval_documents_dir
    entries: list[RetrievalIndexEntry] = []
    if docs_dir.exists():
        for document_path in sorted(docs_dir.glob("*.json")):
            document = RetrievalDocument.model_validate(read_json(document_path))
            tokens: list[str] = []
            if document.content_path is not None and document.content_path.exists():
                tokens = _tokenize_for_retrieval(document.content_path.read_text(encoding="utf-8"))
            entries.append(
                RetrievalIndexEntry(
                    document_id=document.document_id,
                    source_hash=document.source_hash,
                    content_path=document.content_path,
                    candidate_id=document.candidate_id,
                    family=document.family,
                    slot=document.slot,
                    evidence_channel=document.evidence_channel,
                    tokens=tokens,
                )
            )

    index_path = settings.paths().goblin_vector_memory_dir / "retrieval_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index = RetrievalIndex(document_count=len(entries), entries=entries, index_path=index_path)
    write_json(index_path, index.model_dump(mode="json"))
    return index


def retrieve_with_provenance(
    settings: Settings,
    *,
    query_text: str,
    top_k: int = 5,
) -> RetrievalResponse:
    """Return advisory retrieval hits that always cite provenance-bearing source artifacts."""
    if top_k <= 0:
        raise ValueError("retrieval_top_k_must_be_positive")

    index_path = settings.paths().goblin_vector_memory_dir / "retrieval_index.json"
    if not index_path.exists():
        build_retrieval_index(settings)
    index = RetrievalIndex.model_validate(read_json(index_path))

    query_tokens = set(_tokenize_for_retrieval(query_text))
    scored: list[tuple[float, RetrievalIndexEntry]] = []
    for entry in index.entries:
        entry_tokens = set(entry.tokens)
        if not query_tokens or not entry_tokens:
            score = 0.0
        else:
            score = len(query_tokens & entry_tokens) / len(query_tokens)
        if score > 0.0:
            scored.append((score, entry))
    scored.sort(key=lambda item: item[0], reverse=True)

    citations = [
        RetrievalCitation(
            document_id=entry.document_id,
            source_hash=entry.source_hash,
            content_path=entry.content_path,
            score=score,
        )
        for score, entry in scored[:top_k]
    ]
    query_id = f"rq-{hashlib.sha256(query_text.encode('utf-8')).hexdigest()[:12]}"
    report_path = settings.paths().goblin_retrieval_queries_dir / f"{query_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    response = RetrievalResponse(
        query_id=query_id,
        query_text=query_text,
        citations=citations,
        report_path=report_path,
    )
    write_json(report_path, response.model_dump(mode="json"))
    return response


def write_bounded_agent_role(settings: Settings, *, role: BoundedAgentRole) -> BoundedAgentRole:
    """Persist a bounded Goblin agent role that cannot hold governance powers."""
    forbidden_in_allowed = sorted(set(role.allowed_actions) & _P12_FORBIDDEN_AUTONOMY_ACTIONS)
    if forbidden_in_allowed:
        raise ValueError("bounded_agent_role_includes_forbidden_actions")
    report_dir = settings.paths().goblin_agent_roles_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    resolved = role.model_copy(update={"report_path": report_dir / f"{role.role_id}.json"})
    write_json(resolved.report_path, resolved.model_dump(mode="json"))
    return resolved


def assert_agent_action_allowed(
    settings: Settings,
    *,
    role_id: str,
    action: AgentAction,
) -> BoundedAgentRole:
    role_path = settings.paths().goblin_agent_roles_dir / f"{role_id}.json"
    if not role_path.exists():
        raise FileNotFoundError(f"bounded_agent_role not found for role_id={role_id!r}")
    role = BoundedAgentRole.model_validate(read_json(role_path))
    if action in _P12_FORBIDDEN_AUTONOMY_ACTIONS:
        raise ValueError("agent_role_action_not_allowed")
    if action in role.denied_actions or action not in role.allowed_actions:
        raise ValueError("agent_role_action_not_allowed")
    return role


def write_live_attach_manifest(
    settings: Settings,
    *,
    manifest: LiveAttachManifest,
) -> LiveAttachManifest:
    enforce_candidate_strategy_governance(settings, candidate_id=manifest.candidate_id)
    report_dir = settings.paths().goblin_live_demo_reports_dir / manifest.candidate_id / manifest.run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    resolved = manifest.model_copy(update={"report_path": report_dir / "live_attach_manifest.json"})
    write_json(resolved.report_path, resolved.model_dump(mode="json"))
    return resolved


def write_runtime_summary(
    settings: Settings,
    *,
    summary: RuntimeSummary,
) -> RuntimeSummary:
    report_dir = settings.paths().goblin_live_demo_reports_dir / summary.candidate_id / summary.run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    resolved = summary.model_copy(update={"report_path": report_dir / "runtime_summary.json"})
    write_json(resolved.report_path, resolved.model_dump(mode="json"))
    return resolved


def write_runtime_heartbeat(
    settings: Settings,
    *,
    heartbeat: RuntimeHeartbeat,
) -> RuntimeHeartbeat:
    heartbeats_dir = (
        settings.paths().goblin_live_demo_reports_dir / heartbeat.candidate_id / heartbeat.run_id / "heartbeats"
    )
    heartbeats_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    resolved = heartbeat.model_copy(update={"report_path": heartbeats_dir / f"heartbeat_{stamp}.json"})
    write_json(resolved.report_path, resolved.model_dump(mode="json"))
    return resolved


def validate_attach_against_bundle(
    settings: Settings,
    *,
    manifest: LiveAttachManifest,
    bundle: DeploymentBundle,
) -> list[str]:
    """Check that the live attach manifest is consistent with the approved deployment bundle.

    Returns a list of violation strings.  If the list is non-empty a
    ``release_integrity_failure`` S1 incident is automatically opened for the
    candidate.  See ``environment-reproducibility.md`` and ``deployment-ladder.md``.
    """
    violations: list[str] = []

    if bundle.ea_build_hash and manifest.inputs_hash:
        # ea_build_hash is the EA binary; inputs_hash is the .set file.
        # Both are captured on the manifest at attach time and on the bundle at issue time.
        if bundle.inputs_hash and manifest.inputs_hash != bundle.inputs_hash:
            violations.append(f"inputs_hash mismatch: bundle={bundle.inputs_hash!r} manifest={manifest.inputs_hash!r}")

    # Check EA hash via bundle_id linkage (advisory: manifest may not carry ea hash directly)
    # The authoritative check is inputs_hash — if the bundle has no hashes, no violation.

    if violations:
        open_incident_record(
            settings,
            candidate_id=manifest.candidate_id,
            title="release_integrity_failure: config hash mismatch at attach",
            severity="S1",
            sla_class="before_next_attach",
            incident_type="release_integrity_failure",
            ladder_state_at_incident=manifest.ladder_state,
            deployed_bundle_id=bundle.bundle_id,
            notes=[f"Bundle {bundle.bundle_id!r} vs attach manifest {manifest.run_id!r}: {v}" for v in violations],
        )

    return violations


def detect_live_runtime_anomalies(heartbeat: RuntimeHeartbeat) -> list[str]:
    """Return anomaly strings for any chaos conditions found in the heartbeat."""
    anomalies: list[str] = []
    if not heartbeat.terminal_active:
        anomalies.append("terminal_close")
    if not heartbeat.algo_trading_enabled:
        anomalies.append("algo_trading_disabled")
    if heartbeat.account_changed:
        anomalies.append("account_change")
    if heartbeat.stale_audit_detected:
        anomalies.append("stale_audit_gap")
    if heartbeat.status in ("stale", "offline"):
        anomalies.append("heartbeat_gap")
    return anomalies


def run_broker_reconciliation(
    settings: Settings,
    *,
    candidate_id: str,
    run_id: str,
    broker_csv_path: Path,
    account_id: str | None = None,
    ea_audit_path: Path | None = None,
) -> BrokerReconciliationReport:
    """
    Parse a broker account-history CSV, optionally compare against an EA audit JSON,
    and write a BrokerReconciliationReport to the broker_account_history channel.

    If ``ea_audit_path`` is not supplied the function looks for
    ``Goblin/reports/live_demo/<candidate_id>/<run_id>/ea_audit.json``.
    If no EA audit is found the report is written with status ``not_run``.
    """
    broker_trades = _parse_broker_csv(broker_csv_path)
    resolved_ea_path = ea_audit_path or (
        settings.paths().goblin_live_demo_reports_dir / candidate_id / run_id / "ea_audit.json"
    )
    ea_trades = _load_ea_audit_trades(resolved_ea_path)

    matched, missing_broker, extra_broker, pnl_delta = _reconcile_trades(ea_trades, broker_trades)

    if ea_trades is None:
        status = "not_run"
        notes = ["EA audit not available; broker data stored but not compared."]
    elif missing_broker or extra_broker:
        status = "mismatch"
        notes = _reconciliation_notes(missing_broker, extra_broker, pnl_delta)
    else:
        status = "matched"
        notes = _reconciliation_notes(missing_broker, extra_broker, pnl_delta)

    report_dir = settings.paths().goblin_broker_history_reports_dir / candidate_id / run_id
    report_dir.mkdir(parents=True, exist_ok=True)
    report = BrokerReconciliationReport(
        candidate_id=candidate_id,
        broker_source_path=broker_csv_path,
        account_id=account_id,
        matched_trade_count=len(matched),
        missing_broker_trade_count=len(missing_broker),
        extra_broker_trade_count=len(extra_broker),
        cash_pnl_delta=round(pnl_delta, 6),
        reconciliation_status=status,  # type: ignore[arg-type]
        notes=notes,
        report_path=report_dir / "broker_reconciliation_report.json",
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    return report


def _parse_broker_csv(broker_csv_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with broker_csv_path.open("r", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append({k.strip().lower().replace(" ", "_"): v.strip() for k, v in row.items()})
    return rows


def _load_ea_audit_trades(ea_audit_path: Path) -> list[dict[str, Any]] | None:
    if not ea_audit_path.exists():
        return None
    data = read_json(ea_audit_path)
    return list(data.get("trades", []))


def _reconcile_trades(
    ea_trades: list[dict[str, Any]] | None,
    broker_trades: list[dict[str, Any]],
) -> tuple[list[str], list[str], list[str], float]:
    if ea_trades is None:
        return [], [], [str(t.get("ticket", "")) for t in broker_trades], 0.0

    broker_by_ticket = {str(t.get("ticket", "")): t for t in broker_trades}
    ea_by_ticket = {str(t.get("ticket", "")): t for t in ea_trades}
    all_tickets = set(broker_by_ticket) | set(ea_by_ticket)

    matched: list[str] = []
    missing_broker: list[str] = []
    extra_broker: list[str] = []
    pnl_delta = 0.0

    for ticket in sorted(all_tickets):
        in_ea = ticket in ea_by_ticket
        in_broker = ticket in broker_by_ticket
        if in_ea and in_broker:
            ea_profit = float(ea_by_ticket[ticket].get("profit", 0.0))
            broker_profit = float(broker_by_ticket[ticket].get("profit", 0.0))
            pnl_delta += abs(ea_profit - broker_profit)
            matched.append(ticket)
        elif in_ea:
            missing_broker.append(ticket)
        else:
            extra_broker.append(ticket)

    return matched, missing_broker, extra_broker, pnl_delta


def _reconciliation_notes(
    missing_broker: list[str],
    extra_broker: list[str],
    pnl_delta: float,
) -> list[str]:
    notes: list[str] = []
    if missing_broker:
        notes.append(f"missing_broker_trades:{len(missing_broker)} tickets={missing_broker[:10]}")
    if extra_broker:
        notes.append(f"extra_broker_trades:{len(extra_broker)} tickets={extra_broker[:10]}")
    if pnl_delta > 0.0:
        notes.append(f"cash_pnl_delta:{pnl_delta:.6f}")
    return notes


def _load_family_trial_entries(settings: Settings, *, family: str) -> list[dict[str, Any]]:
    path = settings.paths().experiments_dir / "trial_ledger.jsonl"
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(payload.get("family") or "") != family:
                continue
            entries.append(payload)
    return entries


def _load_candidate_trial_entries(settings: Settings, *, candidate_id: str) -> list[dict[str, Any]]:
    path = settings.paths().experiments_dir / "trial_ledger.jsonl"
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(payload.get("candidate_id") or "") != candidate_id:
                continue
            entries.append(payload)
    return entries


def _is_failed_refinement_entry(entry: dict[str, Any]) -> bool:
    failure_code = str(entry.get("failure_code") or "")
    if failure_code in {
        "throughput_failure",
        "compile_failure",
        "mt5_smoke_failure",
        "robustness_failure",
        "empirical_failure",
    }:
        return True
    stage = str(entry.get("stage") or "").lower()
    return "mutat" in stage and bool(failure_code)


def _max_observed_mutation_depth(entries: list[dict[str, Any]]) -> int:
    parent_map: dict[str, list[str]] = {}
    for entry in entries:
        candidate_id = str(entry.get("candidate_id") or "")
        if not candidate_id:
            continue
        parent_ids = [str(parent) for parent in (entry.get("parent_candidate_ids") or []) if str(parent)]
        parent_map[candidate_id] = parent_ids

    memo: dict[str, int] = {}

    def depth(candidate_id: str, seen: set[str]) -> int:
        if candidate_id in memo:
            return memo[candidate_id]
        if candidate_id in seen:
            return 0
        seen.add(candidate_id)
        parents = parent_map.get(candidate_id, [])
        if not parents:
            memo[candidate_id] = 0
            return 0
        resolved = 1 + max(depth(parent_id, set(seen)) for parent_id in parents)
        memo[candidate_id] = resolved
        return resolved

    return max((depth(candidate_id, set()) for candidate_id in parent_map), default=0)


def _find_family_rationale_card(settings: Settings, *, family: str) -> Path | None:
    family_path = settings.paths().goblin_rationale_cards_dir / family / "strategy_rationale_card.json"
    if family_path.exists():
        return family_path
    for path in sorted(settings.paths().goblin_rationale_cards_dir.glob("*/strategy_rationale_card.json")):
        try:
            payload = read_json(path)
        except Exception:  # noqa: BLE001
            continue
        if str(payload.get("family") or "") == family:
            return path
    return None


def _resolve_candidate_family(settings: Settings, *, candidate_id: str) -> str:
    report_dir = settings.paths().reports_dir / candidate_id
    review_path = report_dir / "review_packet.json"
    if review_path.exists():
        review_payload = read_json(review_path)
        review_family = str(review_payload.get("family") or "")
        if review_family:
            return review_family
    spec_path = report_dir / "strategy_spec.json"
    if spec_path.exists():
        spec_payload = read_json(spec_path)
        spec_family = str(spec_payload.get("family") or "")
        if spec_family:
            return spec_family
    raise ValueError(f"strategy_governance_blocked:{candidate_id}:family_unresolved")


def _bootstrap_family_rationale_card_from_candidate(
    settings: Settings,
    *,
    candidate_id: str,
    family: str,
) -> StrategyRationaleCard:
    report_dir = settings.paths().reports_dir / candidate_id
    spec_path = report_dir / "strategy_spec.json"
    entry_style = "unknown"
    setup_summary = ""
    if spec_path.exists():
        spec_payload = read_json(spec_path)
        entry_style = str(spec_payload.get("entry_style") or "unknown")
        setup_logic = spec_payload.get("setup_logic") or {}
        setup_summary = str(setup_logic.get("summary") or "")
    thesis = f"Family {family} candidate {candidate_id} uses {entry_style} execution and requires explicit invalidation, regime-specific risk controls, and bounded search discipline before any live/demo progression."
    invalidation_conditions = [
        "out_of_sample_profit_factor falls below policy floor",
        "stress validation fails under declared execution-cost assumptions",
    ]
    hostile_regimes = [
        "spread-shock and slippage-expansion windows",
        "session-structure breaks where the expected edge concentration disappears",
    ]
    execution_assumptions = [
        setup_summary or "entry logic remains consistent with declared setup summary",
        "execution conditions remain within bounded spread and fill-delay assumptions",
    ]
    non_deployable_conditions = [
        "candidate lacks stable walk-forward behavior",
        "candidate violates governed comparison integrity constraints",
    ]
    return write_strategy_rationale_card(
        settings,
        family=family,
        thesis=thesis,
        invalidation_conditions=invalidation_conditions,
        hostile_regimes=hostile_regimes,
        execution_assumptions=execution_assumptions,
        non_deployable_conditions=non_deployable_conditions,
    )


def _candidate_approval_refs(settings: Settings, candidate_id: str) -> list[str]:
    log_path = settings.paths().approvals_dir / "approval_log.jsonl"
    if not log_path.exists():
        return []
    refs: list[str] = []
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if payload.get("candidate_id") != candidate_id:
                continue
            refs.append(
                f"{payload.get('stage')}:{payload.get('decision')}:{payload.get('recorded_utc')}:{payload.get('source')}"
            )
    return refs


def _resolve_latest_candidate_ladder_state(
    settings: Settings,
    *,
    candidate_id: str,
) -> DeploymentLadderState | None:
    manifests_dir = settings.paths().goblin_live_demo_reports_dir / candidate_id
    if not manifests_dir.exists():
        return None
    latest_manifest: LiveAttachManifest | None = None
    for manifest_path in manifests_dir.glob("*/live_attach_manifest.json"):
        try:
            manifest = LiveAttachManifest.model_validate(read_json(manifest_path))
        except Exception:
            continue
        if latest_manifest is None or manifest.attached_utc > latest_manifest.attached_utc:
            latest_manifest = manifest
    return latest_manifest.ladder_state if latest_manifest is not None else None


def _first_existing_hash(*paths: Path) -> str | None:
    for path in paths:
        if path is not None and path.exists():
            return _sha256_file(path)
    return None


def _load_mt5_packet_payload(settings: Settings, candidate_id: str) -> dict[str, Any] | None:
    packet_path = settings.paths().approvals_dir / "mt5_packets" / candidate_id / "packet.json"
    if not packet_path.exists():
        return None
    payload = read_json(packet_path)
    return payload if isinstance(payload, dict) else None


def _payload_path(payload: dict[str, Any] | None, key: str) -> Path | None:
    if payload is None:
        return None
    value = payload.get(key)
    if not value:
        return None
    return Path(str(value))


def _packet_run_set_path(candidate_id: str, payload: dict[str, Any] | None) -> Path | None:
    run_spec_path = _payload_path(payload, "run_spec_path")
    if run_spec_path is None:
        return None
    run_id = run_spec_path.parent.name
    return run_spec_path.parent / f"{candidate_id}-{run_id}.set"


def _latest_certified_mt5_run_id(settings: Settings, candidate_id: str) -> str | None:
    candidate_dir = settings.paths().goblin_mt5_certification_reports_dir / candidate_id
    if not candidate_dir.exists():
        return None

    latest_run_id: str | None = None
    for report_path in candidate_dir.glob("*/mt5_certification_report.json"):
        try:
            payload = read_json(report_path)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        certification = payload.get("certification")
        if not isinstance(certification, dict):
            continue
        if payload.get("validation_status") != "passed":
            continue
        if certification.get("status") != "deployment_grade":
            continue
        run_id = str(payload.get("run_id") or report_path.parent.name)
        if latest_run_id is None or run_id > latest_run_id:
            latest_run_id = run_id
    return latest_run_id


def _certified_run_set_path(settings: Settings, candidate_id: str, run_id: str | None) -> Path | None:
    if not run_id:
        return None
    run_dir = settings.paths().mt5_runs_dir / candidate_id / run_id
    return run_dir / f"{candidate_id}-{run_id}.set"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _update_latest_incident_pointer(settings: Settings, candidate_id: str, record_path: Path) -> None:
    latest_path = settings.paths().goblin_incident_reports_dir / candidate_id / "latest_incident.json"
    payload = {"candidate_id": candidate_id, "record_path": str(record_path)}
    write_json(latest_path, payload)


def _investigation_pack_root(settings: Settings, *, candidate_id: str, incident_id: str | None) -> Path:
    root = settings.paths().goblin_investigation_reports_dir / candidate_id
    if incident_id:
        root = root / incident_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def _stable_json_filename(identifier: str, *, prefix: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", identifier.lower()).strip("-") or "artifact"
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:10]
    stem_budget = max(16, 48 - len(prefix) - len(digest) - 2)
    stem = normalized[:stem_budget].rstrip("-") or "artifact"
    return f"{prefix}-{stem}-{digest}.json"


def _write_benchmark_history(
    settings: Settings,
    *,
    incident: ProductionIncidentReport,
    incident_report_path: Path,
) -> Path:
    report_dir = settings.paths().goblin_benchmark_history_reports_dir / incident.candidate_id / incident.incident_id
    report_dir.mkdir(parents=True, exist_ok=True)
    benchmark_history_path = report_dir / "benchmark_history.json"
    payload = {
        "incident_id": incident.incident_id,
        "candidate_id": incident.candidate_id,
        "workflow_status": incident.workflow_status,
        "attribution_bucket": incident.attribution_bucket,
        "validation_suspended": incident.validation_suspended,
        "incident_report_path": str(incident_report_path),
        "incident_report_hash": _sha256_file(incident_report_path),
        "generated_utc": incident.generated_utc,
        "harness_check": incident.harness_check.model_dump(mode="json"),
        "ledger_summaries": [summary.model_dump(mode="json") for summary in incident.ledger_summaries],
        "trade_diff_summaries": [summary.model_dump(mode="json") for summary in incident.trade_diff_summaries],
        "artifact_paths": dict(incident.artifact_paths),
        "frozen_artifact_paths": dict(incident.freeze.artifact_paths),
        "frozen_artifact_hashes": dict(incident.freeze.artifact_hashes),
    }
    write_json(benchmark_history_path, payload)
    return benchmark_history_path


def _build_investigation_scenarios(
    incident: ProductionIncidentReport,
    *,
    incident_report_path: Path,
) -> list[InvestigationScenario]:
    scenarios: list[InvestigationScenario] = [
        InvestigationScenario(
            scenario_id=f"{incident.incident_id}-attribution",
            incident_id=incident.incident_id,
            candidate_id=incident.candidate_id,
            scenario_type="incident_attribution",
            title=f"Reproduce incident attribution for {incident.incident_id}",
            description=(
                f"Use the frozen incident report at {incident_report_path} to reproduce workflow status "
                f"{incident.workflow_status} and final classification {incident.attribution_bucket}."
            ),
            evidence_requirements=[str(incident_report_path)],
            success_criteria=[
                f"workflow_status == {incident.workflow_status}",
                f"attribution_bucket == {incident.attribution_bucket}",
            ],
        )
    ]

    if incident.harness_check.status != "not_checked" or incident.harness_check.tester_report_path:
        harness_evidence = []
        if incident.harness_check.tester_report_path is not None:
            harness_evidence.append(str(incident.harness_check.tester_report_path))
        scenarios.append(
            InvestigationScenario(
                scenario_id=f"{incident.incident_id}-baseline-harness",
                incident_id=incident.incident_id,
                candidate_id=incident.candidate_id,
                scenario_type="baseline_harness",
                title=f"Reproduce baseline harness check for {incident.incident_id}",
                description=(
                    "Recompute the baseline known-good replay check and confirm the expected minimum trade count "
                    "and resulting harness trust status."
                ),
                evidence_requirements=harness_evidence,
                success_criteria=[
                    f"harness_check.status == {incident.harness_check.status}",
                    f"expected_min_trade_count == {incident.harness_check.expected_min_trade_count}",
                ],
            )
        )

    ledger_by_name = {summary.source_name: summary for summary in incident.ledger_summaries}
    for diff_summary in incident.trade_diff_summaries:
        evidence_requirements: list[str] = []
        reference_summary = ledger_by_name.get(diff_summary.reference_name)
        observed_summary = ledger_by_name.get(diff_summary.observed_name)
        if reference_summary and reference_summary.csv_path is not None:
            evidence_requirements.append(str(reference_summary.csv_path))
        if observed_summary and observed_summary.csv_path is not None:
            evidence_requirements.append(str(observed_summary.csv_path))
        if diff_summary.diff_csv_path is not None:
            evidence_requirements.append(str(diff_summary.diff_csv_path))
        scenarios.append(
            InvestigationScenario(
                scenario_id=f"{incident.incident_id}-{diff_summary.reference_name}-vs-{diff_summary.observed_name}",
                incident_id=incident.incident_id,
                candidate_id=incident.candidate_id,
                scenario_type="trade_diff_reconciliation",
                title=f"Reproduce {diff_summary.reference_name} vs {diff_summary.observed_name}",
                description=(
                    "Re-run the frozen trade diff comparison and confirm matched, missing, extra, and material "
                    "mismatch counts before changing the incident classification."
                ),
                evidence_requirements=evidence_requirements,
                success_criteria=[
                    f"matched_count == {diff_summary.matched_count}",
                    f"missing_observed_count == {diff_summary.missing_observed_count}",
                    f"extra_observed_count == {diff_summary.extra_observed_count}",
                    f"material_mismatch_count == {diff_summary.material_mismatch_count}",
                ],
            )
        )
    return scenarios


# ---------------------------------------------------------------------------
# P14 — Session-Aware Run Logging
# ---------------------------------------------------------------------------

_SESSION_BOUNDARIES_UTC = [
    ("tokyo", 0, 9),
    ("london", 7, 16),
    ("new_york", 12, 21),
]


def classify_session_window(timestamp_utc: datetime | str) -> str:
    """Derive the forex session window from a UTC timestamp.

    Returns one of: ``"tokyo"``, ``"london"``, ``"london_new_york_overlap"``,
    ``"new_york"``, or ``"off_hours"``.  The classification is deterministic
    and based solely on the hour of the UTC timestamp.
    """
    if isinstance(timestamp_utc, str):
        timestamp_utc = datetime.fromisoformat(timestamp_utc)
    hour = timestamp_utc.hour
    in_london = 7 <= hour < 16
    in_new_york = 12 <= hour < 21
    if in_london and in_new_york:
        return "london_new_york_overlap"
    if in_london:
        return "london"
    if in_new_york:
        return "new_york"
    if 0 <= hour < 9:
        return "tokyo"
    return "off_hours"


def start_goblin_run_record(
    *,
    run_id: str,
    entrypoint: str,
    family: str | None = None,
    candidate_id: str | None = None,
    campaign_id: str | None = None,
    slot_id: str | None = None,
) -> GoblinRunRecord:
    """Create a ``GoblinRunRecord`` at the start of a campaign entrypoint."""
    now = datetime.now(UTC)
    return GoblinRunRecord(
        run_id=run_id,
        session_window=classify_session_window(now),
        family=family,
        candidate_id=candidate_id,
        campaign_id=campaign_id,
        slot_id=slot_id,
        started_utc=now.isoformat(),
        entrypoint=entrypoint,
    )


def finalize_goblin_run_record(
    settings: Settings,
    record: GoblinRunRecord,
    *,
    trace_id: str | None = None,
    trial_id: str | None = None,
    notes: list[str] | None = None,
) -> Path:
    """Finalize and persist a ``GoblinRunRecord`` to append-only JSONL."""
    record.ended_utc = datetime.now(UTC).isoformat()
    if trace_id is not None:
        record.trace_id = trace_id
    if trial_id is not None:
        record.trial_id = trial_id
    if notes:
        record.notes.extend(notes)
    records_dir = settings.paths().goblin_run_records_dir
    records_dir.mkdir(parents=True, exist_ok=True)
    record_path = records_dir / "run_records.jsonl"
    with record_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record.model_dump(mode="json"), default=str) + "\n")
    return record_path


def _investigation_evidence_refs(
    incident: ProductionIncidentReport,
    *,
    incident_report_path: Path,
    benchmark_history_path: Path,
) -> list[str]:
    refs = {str(incident_report_path), str(benchmark_history_path)}
    if incident.harness_check.tester_report_path is not None:
        refs.add(str(incident.harness_check.tester_report_path))
    for summary in incident.ledger_summaries:
        if summary.csv_path is not None:
            refs.add(str(summary.csv_path))
    for summary in incident.trade_diff_summaries:
        if summary.diff_csv_path is not None:
            refs.add(str(summary.diff_csv_path))
    refs.update(value for value in incident.artifact_paths.values() if value)
    return sorted(refs)


def _investigation_tool_calls(incident: ProductionIncidentReport) -> list[dict[str, Any]]:
    tool_calls: list[dict[str, Any]] = [
        {
            "tool": "freeze_artifacts",
            "candidate_id": incident.candidate_id,
            "artifact_count": len(incident.freeze.artifact_paths),
        },
        {
            "tool": "build_harness_check",
            "status": incident.harness_check.status,
            "expected_min_trade_count": incident.harness_check.expected_min_trade_count,
            "observed_trade_count": incident.harness_check.observed_trade_count,
        },
    ]
    for summary in incident.trade_diff_summaries:
        tool_calls.append(
            {
                "tool": "compare_trade_ledgers",
                "reference_name": summary.reference_name,
                "observed_name": summary.observed_name,
                "matched_count": summary.matched_count,
                "material_mismatch_count": summary.material_mismatch_count,
            }
        )
    tool_calls.append(
        {
            "tool": "attribute_incident",
            "workflow_status": incident.workflow_status,
            "attribution_bucket": incident.attribution_bucket,
        }
    )
    return tool_calls


def _intermediate_classifications(incident: ProductionIncidentReport) -> list[str]:
    classifications = [
        f"harness_status={incident.harness_check.status}",
        f"workflow_status={incident.workflow_status}",
        f"validation_suspended={incident.validation_suspended}",
    ]
    for summary in incident.trade_diff_summaries:
        classifications.append(
            f"diff:{summary.reference_name}->{summary.observed_name}:"
            f"missing={summary.missing_observed_count}:extra={summary.extra_observed_count}:"
            f"mismatches={summary.material_mismatch_count}"
        )
    return classifications


def _investigation_findings(incident: ProductionIncidentReport) -> list[str]:
    findings = [
        f"Final incident classification recorded as {incident.attribution_bucket}.",
        f"Workflow status recorded as {incident.workflow_status}.",
    ]
    if incident.harness_check.status == "passed":
        findings.append("Baseline harness reproduction passed before attribution.")
    elif incident.harness_check.status == "failed":
        findings.append("Baseline harness reproduction failed; replay evidence remains constrained.")
    for summary in incident.trade_diff_summaries:
        findings.append(
            f"{summary.reference_name} vs {summary.observed_name}: matched={summary.matched_count}, "
            f"missing={summary.missing_observed_count}, extra={summary.extra_observed_count}, "
            f"material_mismatch={summary.material_mismatch_count}."
        )
    return findings


def _follow_up_actions(incident: ProductionIncidentReport) -> list[str]:
    actions: list[str] = []
    if incident.validation_suspended:
        actions.append("Keep validation suspended until closure evidence is accepted.")
    if incident.workflow_status != "attribution_complete":
        actions.append("Rebuild the investigation pack after additional replay or reconciliation evidence is captured.")
        return actions
    if incident.attribution_bucket == "implementation_delta":
        actions.append(
            "Verify the implementation fix against the same frozen incident window before citing new live evidence."
        )
    elif incident.attribution_bucket == "execution_delta":
        actions.append("Review execution-cost assumptions and broker reconciliation before changing strategy judgment.")
    elif incident.attribution_bucket == "market_or_regime":
        actions.append("Treat execution as clean and continue with regime investigation before replacement decisions.")
    else:
        actions.append("Continue monitoring until the incident classification is no longer unclassified.")
    return actions


def _investigation_confidence(incident: ProductionIncidentReport) -> float:
    if incident.workflow_status == "attribution_complete" and incident.harness_check.status == "passed":
        return 0.95
    if incident.workflow_status == "diff_complete":
        return 0.8
    if incident.workflow_status == "replay_ready":
        return 0.7
    if incident.workflow_status == "validation_suspended":
        return 0.5
    return 0.35


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
