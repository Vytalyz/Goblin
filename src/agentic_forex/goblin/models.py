from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

TruthChannel = Literal["research_backtest", "mt5_replay", "live_demo", "broker_account_history"]
ComparisonEnforcement = Literal["structural_consistency", "strict_executable_parity", "strict_reconciliation"]
PhaseStatus = Literal[
    "not_started",
    "ready",
    "in_progress",
    "blocked",
    "verification_pending",
    "completed",
    "superseded",
    "incident_open",
]
RerunMode = Literal["resume_from_last_checkpoint", "restart_phase", "rebuild_regenerable_outputs"]
CertificationStatus = Literal["deployment_grade", "research_only", "untrusted"]
TickProvenance = Literal["real_ticks", "generated_ticks", "mixed", "unknown"]
ApprovalMode = Literal["human_required", "machine_allowed", "machine_only"]
HeartbeatStatus = Literal["healthy", "warning", "stale", "offline"]
IncidentLifecycleStatus = Literal["open", "monitoring", "mitigated", "closed"]
IncidentSeverity = Literal["S1", "S2", "S3", "S4"]
IncidentSlaClass = Literal["before_next_attach", "before_next_promotion_gate", "observation_window"]
DeploymentLadderState = Literal[
    "shadow_only",
    "limited_demo",
    "observed_demo",
    "challenger_demo",
    "eligible_for_replacement",
]


class ComparisonContract(BaseModel):
    left_channel: TruthChannel
    right_channel: TruthChannel
    enforcement: ComparisonEnforcement
    decision_scope: str
    notes: list[str] = Field(default_factory=list)


class ArtifactProvenance(BaseModel):
    candidate_id: str
    run_id: str
    artifact_origin: str
    evidence_channel: TruthChannel
    terminal_id: str | None = None
    terminal_build: str | None = None
    broker_server: str | None = None
    symbol: str
    timezone_basis: str
    created_at_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    artifact_hash: str | None = None


class ArtifactRecord(BaseModel):
    artifact_id: str
    provenance: ArtifactProvenance
    original_path: Path
    managed_path: Path
    registered_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    authoritative: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ArtifactIndex(BaseModel):
    evidence_channel: TruthChannel
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    index_path: Path


class ArtifactValidationResult(BaseModel):
    evidence_channel: TruthChannel
    artifact_path: Path
    valid: bool
    reasons: list[str] = Field(default_factory=list)
    channel_root: Path | None = None
    conflicting_channel: TruthChannel | None = None


class ResearchDataContract(BaseModel):
    instrument: str
    price_component: Literal["M", "B", "A", "BA"] = "BA"
    granularity: str = "M1"
    smooth: bool = False
    include_first: bool = True
    daily_alignment: int = 17
    alignment_timezone: str = "America/New_York"
    weekly_alignment: str = "Friday"
    utc_normalization_policy: str = "store_utc_emit_utc"


class TimeSessionContract(BaseModel):
    broker_timezone: str
    broker_offset_policy: str
    comparison_timezone_basis: str = "UTC"
    london_timezone: str = "Europe/London"
    new_york_timezone: str = "America/New_York"
    overlap_definition: str = "london_new_york_overlap"
    dst_policy: str = "timezone_database_with_transition_boundaries"
    holiday_policy: str = "broker_calendar_plus_major_market_holidays"


class ValidationCertification(BaseModel):
    artifact_id: str
    status: CertificationStatus
    basis: str
    notes: list[str] = Field(default_factory=list)


class MT5CertificationReport(BaseModel):
    candidate_id: str
    run_id: str
    diagnostic_only: bool = False
    tester_mode: str
    delay_model: str
    tick_provenance: TickProvenance = "unknown"
    symbol_snapshot: dict[str, Any] = Field(default_factory=dict)
    account_snapshot: dict[str, Any] = Field(default_factory=dict)
    terminal_build: str | None = None
    broker_server_class: str | None = None
    baseline_reproduction_passed: bool = False
    launch_status: Literal["completed", "timed_out", "launch_failed"] | None = None
    validation_status: Literal["pending_audit", "insufficient_evidence", "passed", "failed"] | None = None
    parity_rate: float | None = None
    audit_rows: int | None = None
    certification: ValidationCertification
    notes: list[str] = Field(default_factory=list)
    report_path: Path | None = None


class TruthAlignmentReport(BaseModel):
    candidate_id: str
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    required_contracts: list[ComparisonContract] = Field(default_factory=list)
    evidence_summaries: dict[str, Any] = Field(default_factory=dict)
    time_session_contract: TimeSessionContract | None = None
    comparison_time_basis: str | None = None
    channel_timezones: dict[str, str] = Field(default_factory=dict)
    time_basis_consistent: bool = True
    time_basis_mismatches: list[str] = Field(default_factory=list)
    deltas: dict[str, Any] = Field(default_factory=dict)
    governance_effect: str = ""
    report_path: Path | None = None


class BrokerReconciliationReport(BaseModel):
    candidate_id: str
    broker_source_path: Path | None = None
    account_id: str | None = None
    matched_trade_count: int = 0
    missing_broker_trade_count: int = 0
    extra_broker_trade_count: int = 0
    cash_pnl_delta: float = 0.0
    reconciliation_status: Literal["not_run", "matched", "mismatch"] = "not_run"
    notes: list[str] = Field(default_factory=list)
    report_path: Path | None = None


class LiveAttachManifest(BaseModel):
    candidate_id: str
    run_id: str
    account_id: str | None = None
    chart_symbol: str
    timeframe: str
    leverage: float | None = None
    lot_mode: str | None = None
    terminal_build: str | None = None
    broker_server: str | None = None
    attached_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    attachment_confirmed: bool = False
    inputs_hash: str | None = None
    bundle_id: str | None = None
    ladder_state: DeploymentLadderState | None = None
    report_path: Path | None = None


class RuntimeSummary(BaseModel):
    candidate_id: str
    run_id: str
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    bars_processed: int = 0
    allowed_hour_bars: int = 0
    filter_blocks: int = 0
    spread_blocks: int = 0
    signals_generated: int = 0
    order_attempts: int = 0
    order_successes: int = 0
    order_failures: int = 0
    audit_write_failures: int = 0
    notes: list[str] = Field(default_factory=list)
    report_path: Path | None = None


class RuntimeHeartbeat(BaseModel):
    candidate_id: str
    run_id: str
    timestamp_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    status: HeartbeatStatus = "healthy"
    terminal_active: bool = True
    algo_trading_enabled: bool = True
    account_changed: bool = False
    stale_audit_detected: bool = False
    notes: list[str] = Field(default_factory=list)
    report_path: Path | None = None


class DeploymentBundle(BaseModel):
    candidate_id: str
    bundle_id: str
    ea_build_hash: str | None = None
    inputs_hash: str | None = None
    symbol_assumptions: dict[str, Any] = Field(default_factory=dict)
    account_assumptions: dict[str, Any] = Field(default_factory=dict)
    validation_packet_hash: str | None = None
    approval_refs: list[str] = Field(default_factory=list)
    rollback_criteria: list[str] = Field(default_factory=list)


class ApprovalBoundary(BaseModel):
    stage: str
    mode: ApprovalMode
    rationale: str
    allowed_sources: list[str] = Field(default_factory=list)


class IncidentRecord(BaseModel):
    incident_id: str
    candidate_id: str
    lifecycle_status: IncidentLifecycleStatus = "open"
    severity: IncidentSeverity = "S3"
    sla_class: IncidentSlaClass = "before_next_promotion_gate"
    incident_type: str | None = None
    title: str
    opened_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    affected_candidate_ids: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    evidence_paths: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    ladder_state_at_incident: DeploymentLadderState | None = None
    deployed_bundle_id: str | None = None
    report_path: Path | None = None


class IncidentClosurePacket(BaseModel):
    incident_id: str
    closure_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    resolution_summary: str
    # severity-driven required fields (see incident-sla.md)
    root_cause_classification: str | None = None
    root_cause_description: str | None = None
    root_cause_note: str | None = None
    corrective_action: str | None = None
    monitoring_plan: str | None = None
    verification_evidence_path: str | None = None
    deployed_bundle_id: str | None = None
    ladder_state_at_incident: DeploymentLadderState | None = None
    evidence_paths: dict[str, str] = Field(default_factory=dict)
    approved_by: str | None = None
    report_path: Path | None = None


class InvestigationScenario(BaseModel):
    scenario_id: str
    incident_id: str | None = None
    candidate_id: str | None = None
    scenario_type: str = "incident_reproduction"
    title: str
    description: str
    evidence_requirements: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    report_path: Path | None = None


class InvestigationTrace(BaseModel):
    trace_id: str
    scenario_id: str
    incident_id: str | None = None
    candidate_id: str | None = None
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    evidence_refs: list[str] = Field(default_factory=list)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    intermediate_classifications: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    follow_up_actions: list[str] = Field(default_factory=list)
    final_classification: str | None = None
    confidence: float | None = None
    report_path: Path | None = None


class EvaluationSuite(BaseModel):
    suite_id: str
    title: str
    incident_id: str | None = None
    candidate_id: str | None = None
    suite_type: str = "incident_investigation"
    scenario_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    benchmark_history_path: Path | None = None
    report_path: Path | None = None


class InvestigationPack(BaseModel):
    pack_id: str
    incident_id: str
    candidate_id: str
    scenario_paths: list[Path] = Field(default_factory=list)
    trace_path: Path | None = None
    evaluation_suite_path: Path | None = None
    benchmark_history_path: Path | None = None
    report_path: Path | None = None


class StrategyRationaleCard(BaseModel):
    family: str
    candidate_id: str | None = None
    thesis: str
    invalidation_conditions: list[str] = Field(default_factory=list)
    hostile_regimes: list[str] = Field(default_factory=list)
    execution_assumptions: list[str] = Field(default_factory=list)
    non_deployable_conditions: list[str] = Field(default_factory=list)
    report_path: Path | None = None


class ExperimentBudgetCaps(BaseModel):
    max_trials_per_family: int = 160
    max_mutation_depth: int = 8
    max_failed_refinements: int = 48


class StrategyMethodologyAudit(BaseModel):
    family: str
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    rubric_version: str = "goblin_p09_methodology_v1"
    rubric_ref: str = "Goblin/contracts/strategy-methodology-rubric.md"
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    weighted_score: float = 0.0
    minimum_required_score: float = 0.55
    passed: bool = False
    missing_requirements: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    report_path: Path | None = None


class ExperimentAccountingLedger(BaseModel):
    family: str
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    trial_count_family: int = 0
    failed_refinement_count: int = 0
    max_observed_mutation_depth: int = 0
    suspended: bool = False
    suspension_reasons: list[str] = Field(default_factory=list)
    invalid_comparison_rules: list[str] = Field(default_factory=list)
    statistical_policy_ref: str = "Goblin/contracts/statistical-decision-policy.md"
    budget_caps: ExperimentBudgetCaps = Field(default_factory=ExperimentBudgetCaps)
    strategy_rationale_card_path: Path | None = None
    strategy_methodology_audit_path: Path | None = None
    trial_ledger_path: Path | None = None
    notes: list[str] = Field(default_factory=list)
    report_path: Path | None = None


class DeploymentProfile(BaseModel):
    profile_id: str
    account_currency: str = "USD"
    initial_balance: float = 0.0
    leverage: float = 0.0
    max_total_exposure_lots: float = 0.0
    lot_sizing_mode: str = "fixed"
    notes: list[str] = Field(default_factory=list)


class RiskOverlay(BaseModel):
    overlay_id: str
    max_daily_loss_pct: float | None = None
    max_trade_risk_pct: float | None = None
    max_concurrent_exposure_lots: float | None = None
    notes: list[str] = Field(default_factory=list)


class CandidateScorecard(BaseModel):
    candidate_id: str
    alpha_quality: float = 0.0
    robustness: float = 0.0
    executable_parity: float = 0.0
    operational_reliability: float = 0.0
    deployment_fit: float = 0.0
    notes: list[str] = Field(default_factory=list)
    report_path: Path | None = None


class PromotionDecisionPacket(BaseModel):
    candidate_id: str
    decision_status: str = "pending"
    statistical_policy_keys: list[str] = Field(default_factory=list)
    deployment_ladder_state: DeploymentLadderState | None = None
    scorecard_path: Path | None = None
    truth_alignment_report_path: Path | None = None
    strategy_rationale_card_path: Path | None = None
    experiment_accounting_ledger_path: Path | None = None
    strategy_methodology_audit_path: Path | None = None
    search_bias_summary: list[str] = Field(default_factory=list)
    deployment_fit_delta: float | None = None
    deployment_fit_change_requires_new_bundle: bool = False
    deployment_bundle_id: str | None = None
    approval_refs: list[str] = Field(default_factory=list)
    deployment_profile: DeploymentProfile | None = None
    risk_overlay: RiskOverlay | None = None
    notes: list[str] = Field(default_factory=list)
    report_path: Path | None = None


class ModelRegistryEntry(BaseModel):
    model_id: str
    purpose: str
    training_dataset_snapshot: str
    label_policy: str
    feature_schema: dict[str, Any] = Field(default_factory=dict)
    evaluation_windows: list[str] = Field(default_factory=list)
    calibration_results: dict[str, Any] = Field(default_factory=dict)
    drift_thresholds: dict[str, Any] = Field(default_factory=dict)
    approval_state: str = "pending"
    report_path: Path | None = None
    label_policy_path: Path | None = None
    training_cycle_path: Path | None = None
    online_self_tuning_enabled: bool = False


class TrustedLabelPolicy(BaseModel):
    policy_id: str
    model_purpose: str
    provenance_requirements: list[str] = Field(default_factory=list)
    snapshot_freeze_rules: list[str] = Field(default_factory=list)
    ambiguity_rejection_criteria: list[str] = Field(default_factory=list)
    allowed_truth_channels: list[TruthChannel] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    report_path: Path | None = None


OfflineTrainingStatus = Literal["pending_validation", "validation_passed", "validation_failed", "approved"]


class OfflineTrainingCycle(BaseModel):
    cycle_id: str
    model_id: str
    label_policy_id: str
    dataset_snapshot_id: str
    holdout_window_ids: list[str] = Field(default_factory=list)
    feature_version_id: str | None = None
    training_completed_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    validation_status: OfflineTrainingStatus = "pending_validation"
    validation_passed: bool = False
    holdout_evaluation: dict[str, Any] = Field(default_factory=dict)
    touches_live_execution: bool = False
    mt5_replay_required: bool = False
    mt5_certification_path: Path | None = None
    approval_state: str = "pending"
    approved_by: str | None = None
    notes: list[str] = Field(default_factory=list)
    report_path: Path | None = None


class RetrievalDocument(BaseModel):
    document_id: str
    source_type: str
    source_hash: str
    candidate_id: str | None = None
    family: str | None = None
    slot: str | None = None
    evidence_channel: TruthChannel | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    content_path: Path | None = None


AgentAction = Literal[
    "retrieve",
    "summarize",
    "draft_recommendation",
    "write_note",
    "open_incident",
    "approve",
    "promote",
    "deploy",
    "bypass_governance",
]


class KnowledgeEventRecord(BaseModel):
    event_id: str
    event_type: str
    subject_type: str
    subject_id: str
    artifact_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    recorded_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))


class RetrievalIndexEntry(BaseModel):
    document_id: str
    source_hash: str
    content_path: Path | None = None
    candidate_id: str | None = None
    family: str | None = None
    slot: str | None = None
    evidence_channel: TruthChannel | None = None
    tokens: list[str] = Field(default_factory=list)


class RetrievalIndex(BaseModel):
    index_id: str = "goblin-retrieval-index"
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    document_count: int = 0
    entries: list[RetrievalIndexEntry] = Field(default_factory=list)
    index_path: Path | None = None


class RetrievalCitation(BaseModel):
    document_id: str
    source_hash: str
    content_path: Path | None = None
    score: float


class RetrievalResponse(BaseModel):
    query_id: str
    query_text: str
    citations: list[RetrievalCitation] = Field(default_factory=list)
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    report_path: Path | None = None


class BoundedAgentRole(BaseModel):
    role_id: str
    description: str
    allowed_actions: list[AgentAction] = Field(default_factory=list)
    denied_actions: list[AgentAction] = Field(
        default_factory=lambda: ["approve", "promote", "deploy", "bypass_governance"]
    )
    report_path: Path | None = None


class KnowledgeLineageRecord(BaseModel):
    lineage_id: str
    subject_type: str
    subject_id: str
    parent_ids: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    report_path: Path | None = None


class GoblinRunRecord(BaseModel):
    run_id: str
    session_window: str
    strategy_archetype: str | None = None
    family: str | None = None
    candidate_id: str | None = None
    campaign_id: str | None = None
    trace_id: str | None = None
    trial_id: str | None = None
    slot_id: str | None = None
    started_utc: str
    ended_utc: str | None = None
    entrypoint: str
    notes: list[str] = Field(default_factory=list)


class PhaseBlueprint(BaseModel):
    phase_id: str
    title: str
    objective: str
    dependencies: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    build_items: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    expected_artifacts: list[str] = Field(default_factory=list)
    checkpoint_targets: list[str] = Field(default_factory=list)
    authoritative_artifacts: list[str] = Field(default_factory=list)
    regenerable_artifacts: list[str] = Field(default_factory=list)
    exit_criteria: list[str] = Field(default_factory=list)
    owner: str = "GoblinOrchestrator"
    rerun_mode: RerunMode = "resume_from_last_checkpoint"


class CheckpointRecord(BaseModel):
    checkpoint_id: str
    phase_id: str
    created_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    summary: str
    authoritative_artifacts: list[str] = Field(default_factory=list)
    regenerable_artifacts: list[str] = Field(default_factory=list)
    status_at_checkpoint: PhaseStatus
    checkpoint_path: Path


class PhaseRecord(BaseModel):
    phase_id: str
    title: str
    objective: str
    status: PhaseStatus = "not_started"
    dependencies: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    build_items: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    expected_artifacts: list[str] = Field(default_factory=list)
    checkpoint_targets: list[str] = Field(default_factory=list)
    authoritative_artifacts: list[str] = Field(default_factory=list)
    regenerable_artifacts: list[str] = Field(default_factory=list)
    last_checkpoint: str | None = None
    idempotency_key: str
    rerun_mode: RerunMode = "resume_from_last_checkpoint"
    resume_command: str
    verify_command: str
    blockers: list[str] = Field(default_factory=list)
    owner: str = "GoblinOrchestrator"
    started_at: str | None = None
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    completed_at: str | None = None
    exit_criteria: list[str] = Field(default_factory=list)
    acceptance_result: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    record_path: Path

    @model_validator(mode="before")
    @classmethod
    def _normalize_nullable_fields(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("acceptance_result") is None:
            data = dict(data)
            data["acceptance_result"] = {}
        return data


class GoblinProgramStatus(BaseModel):
    program_id: str = "goblin-v3"
    program_name: str = "Goblin"
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    total_phases: int = 0
    phase_counts: dict[str, int] = Field(default_factory=dict)
    ready_phase_ids: list[str] = Field(default_factory=list)
    blocked_phase_ids: list[str] = Field(default_factory=list)
    current_phase_id: str | None = None
    phase_records: list[PhaseRecord] = Field(default_factory=list)
    program_status_path: Path
    status_markdown_path: Path
    roadmap_markdown_path: Path
    program_markdown_path: Path
