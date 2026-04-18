from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

FailureCode = Literal[
    "empirical_failure",
    "robustness_failure",
    "provenance_failure",
    "data_integrity_failure",
    "execution_cost_failure",
    "compile_failure",
    "mt5_smoke_failure",
    "throughput_failure",
    "parity_failure",
    "forward_failure",
    "risk_envelope_violation",
    "campaign_budget_exhausted",
    "manual_review_rejected",
]

NextStepType = Literal[
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
    "human_review",
]

ContinuationStatus = Literal["continue", "stop"]
ProgramTransitionStatus = Literal["continue_lane", "move_to_next_lane", "hard_stop"]
TransitionIntent = Literal["resume_same_candidate", "advance_same_lane", "advance_next_lane", "stop_terminal"]
NotificationReason = Literal["ea_test_ready", "blocked_no_authorized_path", "integrity_exception"]
PortfolioSlotExecutionStatus = Literal[
    "monitoring_summary_only", "research_manager_executed", "research_manager_blocked"
]
ProductionIncidentStatus = Literal[
    "validation_suspended",
    "harness_untrusted",
    "replay_ready",
    "diff_complete",
    "attribution_complete",
    "decision_ready",
]
ProductionIncidentAttributionBucket = Literal[
    "market_or_regime",
    "execution_delta",
    "implementation_delta",
    "ops_delta",
    "harness_failure",
    "unclassified",
]
TradeDiffClassification = Literal[
    "matched_trade",
    "missing_live_trade",
    "extra_live_trade",
    "entry_time_delta",
    "entry_price_delta",
    "exit_time_delta",
    "exit_price_delta",
    "spread_slippage_delta",
    "size_delta",
    "stop_target_timeout_path_delta",
]

StopClass = Literal[
    "none",
    "approval_required",
    "budget_exhausted",
    "lane_exhausted",
    "integrity_issue",
    "policy_decision",
    "ambiguity",
    "ea_test_ready",
    "blocked_no_authorized_path",
    "blocked_policy",
    "blocked_integrity",
    "blocked_budget",
    "blocked_human_required",
    "blocked_upstream_contract",
    "blocked_evidence_stale",
    "blocked_no_candidates",
    "integrity_exception",
]

ReadinessStatus = Literal[
    "discovered",
    "rule_spec_complete",
    "ea_spec_complete",
    "ea_compiled",
    "mt5_backtest_executed",
    "reviewable_candidate",
    "specified",
    "backtested",
    "robustness_provisional",
    "parity_passed",
    "forward_passed",
    "review_eligible_provisional",
    "robustness_passed",
    "review_eligible",
    "human_review_passed",
    "human_review_rejected",
    "published_research_snapshot",
    "ea_test_ready",
]

CompileFailureClassification = Literal[
    "spec_incompleteness",
    "codegen_defect",
    "unsupported_mt5_primitive",
    "indicator_dependency_failure",
    "parameter_schema_failure",
    "state_machine_defect",
]

SmokeFailureClassification = Literal[
    "tester_configuration_failure",
    "no_trades_generated",
    "invalid_order_construction",
    "invalid_stop_target_geometry",
    "runtime_ea_error",
    "artifact_write_failure",
]

TriageClassification = Literal["discard", "refine", "send_to_research_lane"]


class DatasetSnapshot(BaseModel):
    snapshot_id: str
    source: str
    extraction_utc: str
    instrument: str
    symbol_mapping: dict[str, str] = Field(default_factory=dict)
    dataset_start_utc: str | None = None
    dataset_end_utc: str | None = None
    session_filters: list[int] = Field(default_factory=list)
    qa_report_path: Path | None = None
    parquet_path: Path


class FeatureBuildVersion(BaseModel):
    feature_version_id: str
    label_version_id: str
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    feature_paths: list[Path] = Field(default_factory=list)
    label_paths: list[Path] = Field(default_factory=list)


class ExperimentDataProvenance(BaseModel):
    provenance_id: str
    candidate_id: str
    stage: str
    dataset_snapshot: DatasetSnapshot
    feature_build: FeatureBuildVersion
    calendar_version_id: str | None = None
    execution_cost_model_version: str
    risk_envelope_version: str
    strategy_spec_version: str
    report_path: Path


class EnvironmentSnapshot(BaseModel):
    environment_id: str
    captured_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    python_version: str
    dependency_snapshot_hash: str
    os_platform: str
    machine_id: str
    git_revision: str | None = None
    mt5_build: str | None = None
    metaeditor_version: str | None = None
    report_path: Path | None = None


class RobustnessReport(BaseModel):
    candidate_id: str
    evaluation_revision: int = 1
    supersedes_evaluation_revision: int | None = None
    mode: Literal["staged_proxy_only", "full_search_adjusted_robustness"] = "staged_proxy_only"
    cscv_pbo_available: bool = False
    cscv_partition_count: int = 0
    cscv_candidate_count: int = 0
    white_reality_check_available: bool = False
    white_reality_check_candidate_count: int = 0
    white_reality_check_bootstrap_samples: int = 0
    white_reality_check_best_candidate_id: str | None = None
    white_reality_check_p_value: float | None = None
    white_reality_check_pvalue_threshold: float | None = None
    candidate_universe: list[str] = Field(default_factory=list)
    comparable_universe_contract: dict[str, Any] = Field(default_factory=dict)
    pbo: float | None = None
    pbo_threshold: float | None = None
    observed_sharpe: float = 0.0
    deflated_sharpe_ratio: float = 0.0
    deflated_sharpe_floor: float | None = None
    trial_count_family: int = 0
    trial_count_candidate: int = 0
    walk_forward_ok: bool = False
    stress_ok: bool = False
    warnings: list[str] = Field(default_factory=list)
    status: Literal["robustness_provisional", "robustness_passed"] = "robustness_provisional"
    artifact_references: dict[str, Any] = Field(default_factory=dict)
    report_path: Path


class ForwardStageReport(BaseModel):
    candidate_id: str
    evaluation_revision: int = 1
    supersedes_evaluation_revision: int | None = None
    mode: Literal["oanda_shadow"] = "oanda_shadow"
    forward_policy_version: str | None = None
    forward_policy_envelope: dict[str, Any] = Field(default_factory=dict)
    forward_dataset_snapshot_id: str | None = None
    trading_days_observed: int = 0
    trade_count: int = 0
    profit_factor: float = 0.0
    expectancy_pips: float = 0.0
    oos_expectancy_pips: float = 0.0
    expectancy_degradation_pct: float = 100.0
    risk_violations: list[str] = Field(default_factory=list)
    passed: bool = False
    artifact_references: dict[str, Any] = Field(default_factory=dict)
    report_path: Path


class FailureRecord(BaseModel):
    failure_id: str
    candidate_id: str
    stage: str
    failure_code: FailureCode
    campaign_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    recorded_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))


class LeaseRecord(BaseModel):
    lease_key: str
    owner_id: str
    manager_run_id: str
    acquired_utc: str
    heartbeat_utc: str
    expires_utc: str
    fencing_token: int
    state_version_at_acquire: int = 0
    policy_snapshot_hash: str
    active: bool = True
    report_path: Path


class IdempotencyRecord(BaseModel):
    idempotency_key: str
    payload_fingerprint: str
    manager_run_id: str
    recorded_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    outcome_path: Path | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    report_path: Path


class ProgramEvent(BaseModel):
    event_type: str
    severity: Literal["info", "warning", "error"] = "info"
    family: str
    candidate_id: str | None = None
    campaign_id: str | None = None
    report_path: Path | None = None
    notification_eligible: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    recorded_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))


class IntegrityIncident(BaseModel):
    incident_id: str
    exception_class: str
    attempted_action: str
    family: str
    program_id: str
    lease_key: str | None = None
    lease_state: dict[str, Any] = Field(default_factory=dict)
    fencing_token: int | None = None
    expected_base_state_version: int | None = None
    actual_base_state_version: int | None = None
    related_ids: dict[str, str] = Field(default_factory=dict)
    evidence_references: dict[str, str] = Field(default_factory=dict)
    triggering_policy_snapshot_hash: str | None = None
    authoritative_state_snapshot_hash: str | None = None
    halt_scope: Literal["lane", "family", "program"] = "program"
    recorded_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    report_path: Path


class FrozenArtifactSnapshot(BaseModel):
    candidate_id: str
    frozen_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    live_audit_csv_path: Path | None = None
    terminal_context: dict[str, Any] = Field(default_factory=dict)
    strategy_context: dict[str, Any] = Field(default_factory=dict)
    known_uptime_gaps: list[str] = Field(default_factory=list)


class TesterHarnessCheck(BaseModel):
    status: Literal["not_checked", "passed", "failed"] = "not_checked"
    baseline_window_start: str | None = None
    baseline_window_end: str | None = None
    expected_min_trade_count: int = 1
    observed_trade_count: int | None = None
    tester_report_path: Path | None = None
    notes: list[str] = Field(default_factory=list)


class TradeDiffSummary(BaseModel):
    reference_name: str
    observed_name: str
    matched_count: int = 0
    missing_observed_count: int = 0
    extra_observed_count: int = 0
    material_mismatch_count: int = 0
    pnl_delta_pips: float = 0.0
    classifications: dict[str, int] = Field(default_factory=dict)
    diff_csv_path: Path | None = None


class LedgerPerformanceSummary(BaseModel):
    source_name: str
    trade_count: int = 0
    net_pips: float = 0.0
    gross_profit_pips: float = 0.0
    gross_loss_pips: float = 0.0
    profit_factor: float | None = None
    win_rate: float | None = None
    csv_path: Path | None = None


class ProductionIncidentReport(BaseModel):
    incident_id: str
    candidate_id: str
    workflow_status: ProductionIncidentStatus
    validation_suspended: bool = True
    attribution_bucket: ProductionIncidentAttributionBucket = "unclassified"
    freeze: FrozenArtifactSnapshot
    harness_check: TesterHarnessCheck = Field(default_factory=TesterHarnessCheck)
    ledger_summaries: list[LedgerPerformanceSummary] = Field(default_factory=list)
    trade_diff_summaries: list[TradeDiffSummary] = Field(default_factory=list)
    blocked_candidate_ids: list[str] = Field(default_factory=list)
    decision: str = "freeze_replay_diff_attribute_before_strategy_judgment"
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    report_path: Path


class OperatorSafetyEnvelope(BaseModel):
    max_spread_guard_pips: float
    max_slippage_pips: float
    max_concurrent_positions: int
    max_daily_loss_pct: float
    session_no_trade_windows_utc: list[int] = Field(default_factory=list)
    kill_switch_conditions: list[str] = Field(default_factory=list)
    broker_session_assumptions: list[str] = Field(default_factory=list)
    symbol_spec_assumptions: list[str] = Field(default_factory=list)
    position_sizing_rule: str
    fail_safe_behaviors: list[str] = Field(default_factory=list)


class ReproducibilityManifest(BaseModel):
    candidate_id: str
    evaluation_revision: int = 1
    research_contract_version: str
    label_contract_version: str
    dataset_snapshot_id: str | None = None
    feature_version_id: str | None = None
    execution_cost_model_version: str | None = None
    policy_snapshot_hash: str
    terminal_build: str | None = None
    ea_source_hash: str | None = None
    ex5_hash: str | None = None
    tester_config_hash: str | None = None
    forward_harness_version: str | None = None
    report_hashes: dict[str, str] = Field(default_factory=dict)
    report_path: Path


class TrialLedgerEntry(BaseModel):
    trial_id: str
    candidate_id: str
    family: str
    stage: str
    parent_candidate_ids: list[str] = Field(default_factory=list)
    mutation_policy: str | None = None
    campaign_id: str | None = None
    provenance_id: str | None = None
    environment_snapshot_id: str | None = None
    gate_outcomes: dict[str, Any] = Field(default_factory=dict)
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    failure_code: FailureCode | None = None
    recorded_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))


class DiagnosticSliceReport(BaseModel):
    slice_type: Literal["session_bucket", "context_bucket", "spread_anomaly"]
    slice_label: str
    first_window_trade_count: int = 0
    later_window_trade_count: int = 0
    first_window_profit_factor: float = 0.0
    later_window_profit_factor: float = 0.0
    first_window_expectancy_pips: float = 0.0
    later_window_expectancy_pips: float = 0.0
    expectancy_improvement_pips: float = 0.0
    first_window_loss_share: float = 0.0
    evidence_score: float = 0.0
    supported: bool = False


class CandidateDiagnosticReport(BaseModel):
    candidate_id: str
    readiness_status: ReadinessStatus
    walk_forward_failed_window: int = 1
    first_window_start_utc: str | None = None
    first_window_end_utc: str | None = None
    first_window_trade_count: int = 0
    first_window_profit_factor: float = 0.0
    first_window_expectancy_pips: float = 0.0
    later_window_trade_count: int = 0
    later_window_profit_factor: float = 0.0
    later_window_expectancy_pips: float = 0.0
    spread_anomaly_rate_first_window: float = 0.0
    spread_anomaly_rate_later_windows: float = 0.0
    supported_slices: list[DiagnosticSliceReport] = Field(default_factory=list)
    primary_issue: str | None = None
    recommended_mutation: str | None = None
    diagnostic_confidence: float = 0.0
    notes: list[str] = Field(default_factory=list)
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class CandidateMutationReport(BaseModel):
    source_candidate_id: str
    mutated_candidate_id: str
    mutation_type: str
    rationale: str
    readiness_status: ReadinessStatus = "ea_spec_complete"
    changed_fields: list[str] = Field(default_factory=list)
    artifact_references: dict[str, Any] = Field(default_factory=dict)
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class RuleFormalizationReport(BaseModel):
    candidate_id: str
    readiness_status: ReadinessStatus = "rule_spec_complete"
    economic_plausibility_passed: bool = False
    completeness_checks: list[str] = Field(default_factory=list)
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class EASpecGenerationReport(BaseModel):
    candidate_id: str
    readiness_status: ReadinessStatus = "ea_spec_complete"
    economic_plausibility_passed: bool = False
    plausibility_findings: list[str] = Field(default_factory=list)
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class CandidateCompileReport(BaseModel):
    candidate_id: str
    readiness_status: ReadinessStatus | str = "ea_spec_complete"
    compile_status: Literal["passed", "failed"] = "failed"
    failure_classification: CompileFailureClassification | None = None
    logic_manifest_hash: str | None = None
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class MT5SmokeBacktestReport(BaseModel):
    candidate_id: str
    readiness_status: ReadinessStatus | str = "ea_compiled"
    smoke_status: Literal["passed", "failed"] = "failed"
    failure_classification: SmokeFailureClassification | None = None
    trade_count: int = 0
    logic_manifest_hash: str | None = None
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class CandidateTriageReport(BaseModel):
    candidate_id: str
    readiness_status: ReadinessStatus | str = "ea_spec_complete"
    classification: TriageClassification
    rationale: str
    compile_status: str | None = None
    smoke_status: str | None = None
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class CandidateReevaluationReport(BaseModel):
    candidate_id: str
    source_candidate_id: str | None = None
    evaluation_revision: int = 1
    supersedes_evaluation_revision: int | None = None
    readiness_status: ReadinessStatus
    robustness_mode: str = "staged_proxy_only"
    approval_recommendation: str = "needs_human_review"
    trade_count: int = 0
    out_of_sample_profit_factor: float = 0.0
    expectancy_pips: float = 0.0
    stressed_profit_factor: float = 0.0
    walk_forward_ok: bool = False
    stress_passed: bool = False
    artifact_references: dict[str, Any] = Field(default_factory=dict)
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class HypothesisAuditCandidateSummary(BaseModel):
    candidate_id: str
    family: str
    entry_style: str | None = None
    readiness_status: ReadinessStatus | str = "ea_spec_complete"
    trade_count: int = 0
    profit_factor: float = 0.0
    out_of_sample_profit_factor: float = 0.0
    expectancy_pips: float = 0.0
    stress_passed: bool = False
    walk_forward_ok: bool = False
    pbo: float | None = None
    white_reality_check_p_value: float | None = None
    archived: bool = False
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class HypothesisAuditReport(BaseModel):
    family: str
    audited_candidate_ids: list[str] = Field(default_factory=list)
    reference_candidate_id: str | None = None
    lane_decision: Literal[
        "retire_lane",
        "hold_reference_blocked_by_robustness",
        "narrow_correction_supported",
        "insufficient_evidence",
    ] = "insufficient_evidence"
    summary: str
    common_failure_modes: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    candidate_summaries: list[HypothesisAuditCandidateSummary] = Field(default_factory=list)
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class DataRegimeSliceSummary(BaseModel):
    slice_type: Literal["session_bucket", "context_bucket", "volatility_bucket"]
    slice_label: str
    first_window_trade_count: int = 0
    later_window_trade_count: int = 0
    first_window_expectancy_pips: float = 0.0
    later_window_expectancy_pips: float = 0.0
    expectancy_delta_pips: float = 0.0
    first_window_loss_share: float = 0.0
    first_window_trade_share: float = 0.0
    supported_narrow_correction: bool = False


class DataRegimeAuditReport(BaseModel):
    family: str
    audited_candidate_ids: list[str] = Field(default_factory=list)
    reference_candidate_id: str | None = None
    focus_candidate_id: str | None = None
    failed_window_index: int = 1
    lane_decision: Literal[
        "retire_lane",
        "narrow_correction_supported",
        "structural_regime_instability",
        "insufficient_evidence",
    ] = "insufficient_evidence"
    summary: str
    dominant_first_window_loss_modes: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    slice_summaries: list[DataRegimeSliceSummary] = Field(default_factory=list)
    candidate_summaries: list[HypothesisAuditCandidateSummary] = Field(default_factory=list)
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class DataFeatureAuditReport(BaseModel):
    family: str
    audited_candidate_ids: list[str] = Field(default_factory=list)
    reference_candidate_id: str | None = None
    family_decision: Literal[
        "retire_family",
        "bounded_correction_supported",
        "insufficient_evidence",
    ] = "insufficient_evidence"
    summary: str
    suspected_root_causes: list[str] = Field(default_factory=list)
    provenance_consistency: dict[str, Any] = Field(default_factory=dict)
    recent_regime_signals: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    candidate_summaries: list[HypothesisAuditCandidateSummary] = Field(default_factory=list)
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class DataLabelAuditReport(BaseModel):
    family: str
    audited_candidate_ids: list[str] = Field(default_factory=list)
    reference_candidate_id: str | None = None
    contract_decision: Literal[
        "upstream_contract_change_required",
        "family_retire_confirmed",
        "insufficient_evidence",
    ] = "insufficient_evidence"
    summary: str
    suspected_contract_gaps: list[str] = Field(default_factory=list)
    label_contract_snapshot: dict[str, Any] = Field(default_factory=dict)
    recommended_actions: list[str] = Field(default_factory=list)
    candidate_summaries: list[HypothesisAuditCandidateSummary] = Field(default_factory=list)
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class NextStepRecommendation(BaseModel):
    step_type: NextStepType
    candidate_id: str | None = None
    rationale: str
    binding: bool = True
    evidence_status: Literal["supported", "ambiguous", "blocked"] = "supported"
    source_campaign_id: str | None = None
    step_payload: dict[str, Any] = Field(default_factory=dict)


class NextStepControllerReport(BaseModel):
    campaign_id: str
    parent_campaign_id: str | None = None
    selected_step_type: NextStepType | None = None
    step_reason: str
    status: Literal["completed", "stopped"] = "completed"
    stop_reason: str
    candidate_scope: list[str] = Field(default_factory=list)
    candidate_reports: list[CandidateDiagnosticReport] = Field(default_factory=list)
    mutation_reports: list[CandidateMutationReport] = Field(default_factory=list)
    rule_formalization_reports: list[RuleFormalizationReport] = Field(default_factory=list)
    ea_spec_generation_reports: list[EASpecGenerationReport] = Field(default_factory=list)
    compile_reports: list[CandidateCompileReport] = Field(default_factory=list)
    mt5_smoke_reports: list[MT5SmokeBacktestReport] = Field(default_factory=list)
    triage_reports: list[CandidateTriageReport] = Field(default_factory=list)
    reevaluation_reports: list[CandidateReevaluationReport] = Field(default_factory=list)
    hypothesis_audit_reports: list[HypothesisAuditReport] = Field(default_factory=list)
    data_regime_audit_reports: list[DataRegimeAuditReport] = Field(default_factory=list)
    data_feature_audit_reports: list[DataFeatureAuditReport] = Field(default_factory=list)
    data_label_audit_reports: list[DataLabelAuditReport] = Field(default_factory=list)
    mt5_parity_reports: list[dict[str, Any]] = Field(default_factory=list)
    forward_reports: list[ForwardStageReport] = Field(default_factory=list)
    next_recommendations: list[NextStepRecommendation] = Field(default_factory=list)
    continuation_status: ContinuationStatus = "stop"
    stop_class: StopClass = "ambiguity"
    auto_continue_allowed: bool = False
    recommended_follow_on_step: NextStepType | None = None
    max_safe_follow_on_steps: int = 0
    transition_status: ProgramTransitionStatus = "hard_stop"
    transition_intent: TransitionIntent = "stop_terminal"
    policy_snapshot_hash: str | None = None
    notification_required: bool = False
    notification_reason: NotificationReason | None = None
    handoff_candidate_id: str | None = None
    handoff_artifact_paths: dict[str, str] = Field(default_factory=dict)
    report_path: Path


class GovernedLoopStepSummary(BaseModel):
    step_index: int
    campaign_id: str
    selected_step_type: NextStepType | None = None
    status: Literal["completed", "stopped"] = "completed"
    stop_reason: str
    continuation_status: ContinuationStatus = "stop"
    stop_class: StopClass = "ambiguity"
    auto_continue_allowed: bool = False
    recommended_follow_on_step: NextStepType | None = None
    transition_status: ProgramTransitionStatus = "hard_stop"
    transition_intent: TransitionIntent = "stop_terminal"
    report_path: Path


class GovernedLoopReport(BaseModel):
    loop_id: str
    family: str
    initial_parent_campaign_id: str | None = None
    final_parent_campaign_id: str | None = None
    executed_steps: int = 0
    max_steps: int = 0
    status: Literal["completed", "stopped"] = "stopped"
    stop_reason: str
    stop_class: StopClass = "ambiguity"
    transition_intent: TransitionIntent = "stop_terminal"
    final_report_path: Path | None = None
    final_recommendations: list[NextStepRecommendation] = Field(default_factory=list)
    executed_campaign_ids: list[str] = Field(default_factory=list)
    step_summaries: list[GovernedLoopStepSummary] = Field(default_factory=list)
    policy_snapshot_hash: str | None = None
    report_path: Path


class ProgramLoopLaneSummary(BaseModel):
    lane_index: int
    lane_id: str
    family: str
    hypothesis_class: str
    seed_candidate_id: str
    queue_kind: Literal["throughput", "promotion"] = "promotion"
    seed_campaign_id: str | None = None
    initial_parent_campaign_id: str | None = None
    final_parent_campaign_id: str | None = None
    governed_loop_report_path: Path | None = None
    status: Literal["completed", "stopped"] = "stopped"
    stop_reason: str
    stop_class: StopClass = "ambiguity"
    transition_status: ProgramTransitionStatus = "hard_stop"
    transition_intent: TransitionIntent = "stop_terminal"


class ProgramLoopReport(BaseModel):
    program_id: str
    family: str
    initial_parent_campaign_id: str | None = None
    final_parent_campaign_id: str | None = None
    executed_lanes: int = 0
    max_lanes: int = 0
    status: Literal["completed", "stopped"] = "stopped"
    stop_reason: str
    stop_class: StopClass = "ambiguity"
    transition_intent: TransitionIntent = "stop_terminal"
    lane_summaries: list[ProgramLoopLaneSummary] = Field(default_factory=list)
    final_audit_report_path: Path | None = None
    policy_snapshot_hash: str | None = None
    notification_required: bool = False
    notification_reason: NotificationReason | None = None
    handoff_candidate_id: str | None = None
    handoff_artifact_paths: dict[str, str] = Field(default_factory=dict)
    report_path: Path


class AutonomousManagerCycleSummary(BaseModel):
    cycle_index: int
    lane_id: str
    program_report_path: Path | None = None
    stop_reason: str
    stop_class: StopClass
    material_transition: bool = False
    approvals_issued: list[str] = Field(default_factory=list)


class AutonomousManagerReport(BaseModel):
    manager_run_id: str
    program_id: str
    family: str
    initial_parent_campaign_id: str | None = None
    final_parent_campaign_id: str | None = None
    executed_cycles: int = 0
    max_cycles: int = 0
    status: Literal["completed", "stopped"] = "stopped"
    stop_reason: str
    stop_class: StopClass
    terminal_boundary: NotificationReason
    policy_snapshot_hash: str
    cycle_summaries: list[AutonomousManagerCycleSummary] = Field(default_factory=list)
    notification_required: bool = True
    notification_reason: NotificationReason
    handoff_candidate_id: str | None = None
    handoff_artifact_paths: dict[str, str] = Field(default_factory=dict)
    incident_report_path: Path | None = None
    report_path: Path


class PortfolioSlotReport(BaseModel):
    slot_id: str
    mode: str
    purpose: str
    active_candidate_id: str | None = None
    allowed_families: list[str] = Field(default_factory=list)
    codex_execution_mode: str = "disabled"
    status: PortfolioSlotExecutionStatus
    last_action: str
    mutation_occurred: bool = False
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class PortfolioCycleReport(BaseModel):
    cycle_id: str
    slot_reports: list[PortfolioSlotReport] = Field(default_factory=list)
    report_path: Path
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))


class CampaignSpec(BaseModel):
    campaign_id: str
    family: str
    baseline_candidate_id: str
    target_candidate_ids: list[str] = Field(default_factory=list)
    parent_campaign_id: str | None = None
    queue_kind: Literal["throughput", "promotion"] = "promotion"
    throughput_target_count: int = 0
    orthogonality_metadata: dict[str, str] = Field(default_factory=dict)
    compile_budget: int = 0
    smoke_budget: int = 0
    max_rule_spec_reformulations_per_hypothesis: int = 2
    max_ea_spec_rewrites_per_candidate: int = 2
    max_compile_retries_per_candidate: int = 2
    max_smoke_retries_per_candidate: int = 1
    step_type: NextStepType | None = None
    allowed_step_types: list[NextStepType] = Field(default_factory=list)
    max_iterations: int = 1
    max_new_candidates: int = 4
    trial_cap_per_family: int = 50
    stop_on_review_eligible_provisional: bool = True
    notes: list[str] = Field(default_factory=list)


class CampaignState(BaseModel):
    campaign_id: str
    family: str
    status: Literal["planned", "running", "stopped", "completed"] = "planned"
    baseline_candidate_id: str
    parent_campaign_id: str | None = None
    current_step_type: NextStepType | None = None
    active_candidate_ids: list[str] = Field(default_factory=list)
    promoted_candidate_ids: list[str] = Field(default_factory=list)
    iterations_run: int = 0
    trials_consumed: int = 0
    operational_runs_consumed: int = 0
    rule_spec_reformulations_by_candidate: dict[str, int] = Field(default_factory=dict)
    ea_spec_rewrites_by_candidate: dict[str, int] = Field(default_factory=dict)
    compile_retries_by_candidate: dict[str, int] = Field(default_factory=dict)
    smoke_retries_by_candidate: dict[str, int] = Field(default_factory=dict)
    mt5_parity_retries_by_candidate: dict[str, int] = Field(default_factory=dict)
    shadow_forward_retries_by_candidate: dict[str, int] = Field(default_factory=dict)
    state_version: int = 1
    stop_reason: str | None = None
    state_path: Path
    last_report_path: Path | None = None
    next_recommendations_path: Path | None = None
    updated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
