from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class MT5RunSpec(BaseModel):
    candidate_id: str
    run_id: str
    install_id: str
    diagnostic_only: bool = False
    lineage_root_candidate_id: str | None = None
    parity_class: Literal["m1_official", "tick_required"] | None = None
    parity_policy_lane_ids: list[str] = Field(default_factory=list)
    parity_policy_snapshot_hash: str | None = None
    terminal_path: str | None = None
    portable_mode: bool = False
    tester_mode: str
    tick_mode: str
    spread_behavior: str
    allow_live_trading: bool
    shutdown_terminal: bool
    config_path: Path
    report_path: Path
    compile_target_path: Path
    compile_request_path: Path
    launch_request_path: Path
    run_dir: Path
    audit_relative_path: str | None = None
    audit_output_path: Path | None = None
    broker_history_relative_path: str | None = None
    broker_history_output_path: Path | None = None
    diagnostic_windows_relative_path: str | None = None
    diagnostic_windows_output_path: Path | None = None
    diagnostic_ticks_relative_path: str | None = None
    diagnostic_ticks_output_path: Path | None = None
    runtime_summary_relative_path: str | None = None
    runtime_summary_output_path: Path | None = None
    signal_trace_relative_path: str | None = None
    signal_trace_output_path: Path | None = None
    tester_inputs_profile_path: Path | None = None
    tester_from_date: str | None = None
    tester_to_date: str | None = None
    tester_timeout_seconds: int = 900
    logic_manifest_hash: str | None = None


class MT5Packet(BaseModel):
    candidate_id: str
    packet_dir: Path
    logic_manifest_path: Path
    expected_signal_path: Path
    notes_path: Path
    ea_source_path: Path
    deployed_source_path: Path | None = None
    compiled_ex5_path: Path | None = None
    compile_log_path: Path | None = None
    terminal_data_path: Path | None = None
    metaeditor_path: Path | None = None
    logic_manifest_hash: str | None = None
    audit_relative_path: str | None = None
    audit_output_path: Path | None = None
    run_spec_path: Path
    tester_config_path: Path
    compile_request_path: Path
    launch_request_path: Path


class MT5RunResult(BaseModel):
    candidate_id: str
    run_id: str
    launch_status: Literal["completed", "timed_out", "launch_failed"]
    terminal_return_code: int | None = None
    timed_out: bool = False
    terminal_path: str | None = None
    terminal_data_path: Path | None = None
    tester_report_path: Path | None = None
    audit_csv_path: Path | None = None
    broker_history_csv_path: Path | None = None
    diagnostic_ticks_csv_path: Path | None = None
    runtime_summary_json_path: Path | None = None
    signal_trace_csv_path: Path | None = None
    tester_inputs_profile_path: Path | None = None
    launch_status_path: Path


class MT5ManualRunReport(BaseModel):
    candidate_id: str
    run_id: str
    packet_reused: bool = False
    tester_mode: str | None = None
    launch_status: Literal["completed", "timed_out", "launch_failed"]
    manual_overrides: dict[str, float | str | bool | None] = Field(default_factory=dict)
    tester_config_path: Path
    launch_request_path: Path
    tester_report_path: Path | None = None
    audit_csv_path: Path | None = None
    broker_history_csv_path: Path | None = None
    diagnostic_ticks_csv_path: Path | None = None
    runtime_summary_json_path: Path | None = None
    signal_trace_csv_path: Path | None = None
    tester_inputs_profile_path: Path | None = None
    launch_status_path: Path | None = None
    report_path: Path


class MT5IncidentReplayReport(BaseModel):
    candidate_id: str
    run_id: str
    incident_id: str | None = None
    window_start: str
    window_end: str
    launch_status: Literal["completed", "timed_out", "launch_failed"]
    harness_status: Literal["replay_ready", "harness_untrusted"]
    certification_status: Literal["deployment_grade", "research_only", "untrusted"] | None = None
    certification_report_path: Path | None = None
    tick_provenance: Literal["real_ticks", "generated_ticks", "mixed", "unknown"] | None = None
    baseline_reproduction_passed: bool | None = None
    report_trade_count: int | None = None
    manual_overrides: dict[str, float | str | bool | None] = Field(default_factory=dict)
    tester_config_path: Path
    launch_request_path: Path
    tester_inputs_profile_path: Path | None = None
    tester_report_path: Path | None = None
    audit_csv_path: Path | None = None
    broker_history_csv_path: Path | None = None
    diagnostic_ticks_csv_path: Path | None = None
    runtime_summary_json_path: Path | None = None
    signal_trace_csv_path: Path | None = None
    launch_status_path: Path | None = None
    notes: list[str] = Field(default_factory=list)
    report_path: Path


class MT5ValidationReport(BaseModel):
    candidate_id: str
    run_id: str | None = None
    lineage_root_candidate_id: str | None = None
    parity_class: Literal["m1_official", "tick_required"] | None = None
    parity_policy_lane_ids: list[str] = Field(default_factory=list)
    parity_policy_snapshot_hash: str | None = None
    validation_status: Literal["pending_audit", "insufficient_evidence", "passed", "failed"]
    failure_classification: Literal["parity_failure", "execution_cost_failure"] | None = None
    parity_rate: float
    audit_rows: int
    expected_signal_source: str = "packet_expected_signals"
    expected_trade_count: int = 0
    actual_trade_count: int = 0
    matched_trade_count: int = 0
    unmatched_expected_count: int = 0
    unmatched_actual_count: int = 0
    expected_signal_path: Path | None = None
    broker_history_csv_path: Path | None = None
    matched_trade_diagnostics_path: Path | None = None
    diagnostics_report_path: Path | None = None
    tolerances_used: dict[str, float | int] = Field(default_factory=dict)
    report_path: Path


class MT5ParityReport(BaseModel):
    candidate_id: str
    run_id: str
    diagnostic_only: bool = False
    lineage_root_candidate_id: str | None = None
    parity_class: Literal["m1_official", "tick_required"] | None = None
    parity_policy_lane_ids: list[str] = Field(default_factory=list)
    parity_policy_snapshot_hash: str | None = None
    tester_mode: str | None = None
    packet_reused: bool = False
    logic_manifest_hash: str | None = None
    validation_status: Literal["pending_audit", "insufficient_evidence", "passed", "failed"]
    failure_classification: Literal["parity_failure", "execution_cost_failure"] | None = None
    parity_rate: float = 0.0
    audit_rows: int = 0
    certification_status: Literal["deployment_grade", "research_only", "untrusted"] | None = None
    certification_report_path: Path | None = None
    tick_provenance: Literal["real_ticks", "generated_ticks", "mixed", "unknown"] | None = None
    baseline_reproduction_passed: bool | None = None
    tester_report_path: Path | None = None
    audit_csv_path: Path | None = None
    broker_history_csv_path: Path | None = None
    diagnostic_ticks_csv_path: Path | None = None
    diagnostic_tick_analysis_path: Path | None = None
    runtime_summary_json_path: Path | None = None
    signal_trace_csv_path: Path | None = None
    tester_inputs_profile_path: Path | None = None
    launch_status_path: Path | None = None
    validation_report_path: Path | None = None
    diagnostics_report_path: Path | None = None
    report_path: Path
