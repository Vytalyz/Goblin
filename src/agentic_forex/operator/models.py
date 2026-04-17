from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


CapabilitySourceKind = Literal["official_doc", "local_dir", "local_file"]
CapabilitySurfaceType = Literal[
    "docs",
    "agent",
    "subagent",
    "automation",
    "hook",
    "workflow",
    "skill",
    "rules",
    "config",
    "control_plane",
    "knowledge",
]
CapabilityStability = Literal["stable", "experimental", "repo_defined", "legacy_optional"]
WindowsSupport = Literal["supported", "limited", "disabled"]
CriticalPathEligibility = Literal["allowed", "guarded", "forbidden"]
SandboxPosture = Literal["read_only", "workspace_write", "dangerous", "not_applicable"]
ApprovalPosture = Literal["none", "rules_prompt", "human_gate", "machine_gate", "not_applicable"]
ActionStatus = Literal["completed", "failed"]


class CapabilityManifestEntry(BaseModel):
    source_id: str
    capability_name: str
    source_kind: CapabilitySourceKind
    source_ref: str
    surface_type: CapabilitySurfaceType
    stability: CapabilityStability
    windows_support: WindowsSupport
    critical_path_eligibility: CriticalPathEligibility
    repo_applicability: str
    sandbox_posture: SandboxPosture
    approval_posture: ApprovalPosture
    recursive: bool = False
    notes: list[str] = Field(default_factory=list)


class CapabilityManifest(BaseModel):
    sources: list[CapabilityManifestEntry] = Field(default_factory=list)


class CapabilityCatalogEntry(BaseModel):
    source_id: str
    capability_name: str
    source_ref: str
    source_kind: CapabilitySourceKind
    surface_type: CapabilitySurfaceType
    stability: CapabilityStability
    windows_support: WindowsSupport
    critical_path_eligibility: CriticalPathEligibility
    repo_applicability: str
    sandbox_posture: SandboxPosture
    approval_posture: ApprovalPosture
    fetched_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    sync_status: Literal["synced", "failed"] = "synced"
    summary: str = ""
    artifact_path: Path | None = None
    content_sha256: str | None = None
    inventory: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class CapabilitySyncReport(BaseModel):
    run_id: str
    manifest_path: Path
    catalog_path: Path
    index_path: Path
    synced_entries: int
    failed_entries: int
    entries: list[CapabilityCatalogEntry] = Field(default_factory=list)
    report_path: Path


class QueueLaneSnapshot(BaseModel):
    lane_id: str
    family: str
    hypothesis_class: str
    queue_kind: str
    seed_candidate_id: str
    seed_exists: bool


class QueueCampaignSnapshot(BaseModel):
    campaign_id: str
    family: str
    status: str
    stop_reason: str | None = None
    updated_utc: str


class QueueSnapshotReport(BaseModel):
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    family_filter: str | None = None
    pending_lanes: list[QueueLaneSnapshot] = Field(default_factory=list)
    recent_campaigns: list[QueueCampaignSnapshot] = Field(default_factory=list)
    recent_program_reports: list[str] = Field(default_factory=list)
    recent_manager_reports: list[str] = Field(default_factory=list)
    report_path: Path


class OperatorStateExport(BaseModel):
    run_id: str
    policy_snapshot_hash: str
    llm_provider: str
    planning_mode: str
    queue_snapshot_path: Path
    queue_snapshot: dict[str, Any]
    capability_catalog_path: Path | None = None
    codex_assets: dict[str, Any] = Field(default_factory=dict)
    automation_specs: list[dict[str, Any]] = Field(default_factory=list)
    portfolio_slots: list[dict[str, Any]] = Field(default_factory=list)
    report_path: Path


class OperatorContractFinding(BaseModel):
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    path: Path | None = None


class OperatorContractReport(BaseModel):
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    passed: bool
    findings: list[OperatorContractFinding] = Field(default_factory=list)
    report_path: Path


class GovernedActionManifest(BaseModel):
    run_id: str
    action: str
    requested_utc: str
    completed_utc: str | None = None
    status: ActionStatus = "completed"
    policy_snapshot_hash: str
    request: dict[str, Any] = Field(default_factory=dict)
    delegated_agent_summaries: list[dict[str, Any]] = Field(default_factory=list)
    output_report_path: Path | None = None
    output_report_type: str | None = None
    output_payload: dict[str, Any] = Field(default_factory=dict)
    trace_dir: Path
    manifest_path: Path


class GovernedActionInspection(BaseModel):
    run_id: str
    action: str
    status: ActionStatus
    output_report_path: Path | None = None
    output_report_type: str | None = None
    manifest_path: Path
    trace_dir: Path
    output_payload: dict[str, Any] = Field(default_factory=dict)


class CandidateBranchAuditRecord(BaseModel):
    candidate_id: str
    family: str
    entry_style: str
    trade_count: int = 0
    profit_factor: float = 0.0
    out_of_sample_profit_factor: float = 0.0
    expectancy_pips: float = 0.0
    max_drawdown_pct: float = 0.0
    stressed_profit_factor: float = 0.0
    stress_passed: bool = False
    walk_forward_ok: bool = False
    readiness: str = "unreviewed"
    approval_recommendation: str = "not_reviewed"
    trial_count_family: int = 0
    trial_count_candidate: int = 0
    diagnostic_stop_reason: str | None = None
    transition_status: str | None = None
    auto_continue_allowed: bool = False
    supported_slice_count: int = 0
    recommended_mutation: str | None = None
    diagnostic_confidence: float | None = None
    branch_score: float = 0.0
    blocked_reasons: list[str] = Field(default_factory=list)
    candidate_paths: dict[str, str] = Field(default_factory=dict)


class CandidateBranchAuditReport(BaseModel):
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    candidate_ids: list[str] = Field(default_factory=list)
    comparison_report_path: Path | None = None
    decision: Literal["recommit_branch", "open_new_family"]
    recommended_candidate_id: str | None = None
    recommended_family: str | None = None
    next_family_hint: str | None = None
    rationale: list[str] = Field(default_factory=list)
    records: list[CandidateBranchAuditRecord] = Field(default_factory=list)
    report_path: Path


class CandidateWindowDensityHourRecord(BaseModel):
    hour_utc: int
    trade_count: int = 0
    mean_pnl_pips: float = 0.0
    profit_factor: float = 0.0
    candidate_support: int = 0


class CandidateWindowDensityPhaseRecord(BaseModel):
    phase_name: Literal["open_impulse", "early_follow_through", "late_morning_decay", "outside_anchor"]
    trade_count: int = 0
    mean_pnl_pips: float = 0.0
    profit_factor: float = 0.0
    candidate_support: int = 0


class CandidateWindowDensityWalkForwardRecord(BaseModel):
    window: int
    trade_count: int = 0
    profit_factor: float = 0.0
    expectancy_pips: float = 0.0
    passed: bool = False


class CandidateWindowDensityAuditRecord(BaseModel):
    candidate_id: str
    family: str
    entry_style: str
    allowed_hours_utc: list[int] = Field(default_factory=list)
    open_anchor_hour_utc: int | None = None
    trade_count: int = 0
    out_of_sample_profit_factor: float = 0.0
    expectancy_pips: float = 0.0
    stressed_profit_factor: float = 0.0
    stress_passed: bool = False
    weakest_window: int = 0
    weakest_window_trade_count: int = 0
    weakest_window_hours: list[CandidateWindowDensityHourRecord] = Field(default_factory=list)
    weakest_window_phases: list[CandidateWindowDensityPhaseRecord] = Field(default_factory=list)
    walk_forward_windows: list[CandidateWindowDensityWalkForwardRecord] = Field(default_factory=list)
    hour_records: list[CandidateWindowDensityHourRecord] = Field(default_factory=list)
    phase_records: list[CandidateWindowDensityPhaseRecord] = Field(default_factory=list)
    candidate_paths: dict[str, str] = Field(default_factory=dict)


class CandidateWindowDensityAuditReport(BaseModel):
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    candidate_ids: list[str] = Field(default_factory=list)
    reference_candidate_id: str | None = None
    weakest_window: int | None = None
    decision: Literal["revive_family", "refine_family_once", "adjust_discovery_model"]
    recommended_hours_utc: list[int] = Field(default_factory=list)
    recommended_phases: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)
    aggregate_hour_records: list[CandidateWindowDensityHourRecord] = Field(default_factory=list)
    weakest_window_hour_records: list[CandidateWindowDensityHourRecord] = Field(default_factory=list)
    aggregate_phase_records: list[CandidateWindowDensityPhaseRecord] = Field(default_factory=list)
    weakest_window_phase_records: list[CandidateWindowDensityPhaseRecord] = Field(default_factory=list)
    records: list[CandidateWindowDensityAuditRecord] = Field(default_factory=list)
    report_path: Path
