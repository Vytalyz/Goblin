from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import time
from ctypes import create_unicode_buffer
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
from pandas.errors import EmptyDataError

from agentic_forex.approval.service import require_stage_approval
from agentic_forex.backtesting.engine import _generate_signal
from agentic_forex.config import Settings
from agentic_forex.features.service import build_features
from agentic_forex.goblin.controls import enforce_candidate_strategy_governance, write_mt5_certification_report
from agentic_forex.goblin.models import MT5CertificationReport, ValidationCertification
from agentic_forex.governance.control_plane import policy_snapshot_hash
from agentic_forex.governance.provenance import build_environment_snapshot
from agentic_forex.governance.trial_ledger import append_failure_record, append_trial_entry
from agentic_forex.market_data.ingest import ingest_mt5_parity_csv
from agentic_forex.mt5.ea_generator import render_candidate_ea
from agentic_forex.mt5.models import (
    MT5IncidentReplayReport,
    MT5ManualRunReport,
    MT5Packet,
    MT5ParityReport,
    MT5RunResult,
    MT5RunSpec,
    MT5ValidationReport,
)
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows.contracts import StrategySpec

try:
    from ctypes import windll
except ImportError:  # pragma: no cover - non-Windows fallback
    windll = None


EXPECTED_SIGNAL_COLUMNS = [
    "timestamp_utc",
    "exit_timestamp_utc",
    "side",
    "entry_price",
    "exit_price",
    "pnl_pips",
    "candidate_id",
    "exit_reason",
    "stop_loss_price",
    "take_profit_price",
    "same_bar_collision",
    "collision_resolution",
]

BROKER_HISTORY_COLUMNS = [
    "timestamp_utc",
    "bid_o",
    "bid_h",
    "bid_l",
    "bid_c",
    "ask_o",
    "ask_h",
    "ask_l",
    "ask_c",
    "mid_o",
    "mid_h",
    "mid_l",
    "mid_c",
    "volume",
    "spread_pips",
]

AUDIT_COLUMNS = [
    "timestamp_utc",
    "exit_timestamp_utc",
    "side",
    "entry_price",
    "exit_price",
    "pnl_pips",
    "pnl_dollars",
    "candidate_id",
    "run_id",
    "magic_number",
    "ticket",
    "exit_reason",
    "stop_loss_price",
    "take_profit_price",
    "same_bar_collision",
]


class ParityPolicyError(PermissionError):
    """Raised when official parity is blocked by policy rather than implementation failure."""


def generate_mt5_packet(candidate_id: str, settings: Settings) -> MT5Packet:
    require_stage_approval(candidate_id, "mt5_packet", settings)
    enforce_candidate_strategy_governance(settings, candidate_id=candidate_id)
    report_dir = settings.paths().reports_dir / candidate_id
    packet_dir = settings.paths().approvals_dir / "mt5_packets" / candidate_id
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_run_id = f"mt5run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = settings.paths().mt5_runs_dir / candidate_id / packet_run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    spec = StrategySpec.model_validate(read_json(report_dir / "strategy_spec.json"))
    summary = read_json(report_dir / "backtest_summary.json") if (report_dir / "backtest_summary.json").exists() else {}
    review_packet = read_json(report_dir / "review_packet.json") if (report_dir / "review_packet.json").exists() else {}
    expected_signal_frame = _expected_signal_frame(settings, report_dir, candidate_id, spec)

    logic_manifest_path = packet_dir / "logic_manifest.json"
    expected_signal_path = packet_dir / "expected_signals.csv"
    notes_path = packet_dir / "notes.md"
    ea_source_path = packet_dir / "CandidateEA.mq5"
    packet_record_path = packet_dir / "packet.json"
    tester_config_path = run_dir / "tester_config.ini"
    compile_request_path = run_dir / "compile_request.json"
    launch_request_path = run_dir / "launch_request.json"
    report_path = run_dir / "tester_report.htm"

    install_id = settings.mt5_env.terminal_install_ids[0] if settings.mt5_env.terminal_install_ids else "mt5_practice_01"
    terminal_path = _resolve_terminal_path(settings)
    compile_target_path = _candidate_compile_target_relative_path(candidate_id, settings)
    base_terminal_data_path = _resolve_terminal_data_path(settings, terminal_path)
    base_metaeditor_path = _resolve_metaeditor_path(terminal_path)
    terminal_path, terminal_data_path, metaeditor_path = _prepare_automated_terminal_runtime(
        settings,
        terminal_path=terminal_path,
        terminal_data_path=base_terminal_data_path,
    )
    audit_relative_path = _audit_relative_path(candidate_id, packet_run_id, settings)
    audit_output_path = _resolve_audit_output_path(settings, terminal_data_path, audit_relative_path)
    broker_history_relative_path = _broker_history_relative_path(candidate_id, settings)
    broker_history_output_path = _resolve_broker_history_output_path(
        settings,
        terminal_data_path,
        broker_history_relative_path,
    )
    diagnostic_windows_relative_path = _diagnostic_windows_relative_path(candidate_id, settings)
    diagnostic_windows_output_path = _resolve_diagnostic_windows_output_path(
        settings,
        terminal_data_path,
        diagnostic_windows_relative_path,
    )
    diagnostic_ticks_relative_path = _diagnostic_ticks_relative_path(candidate_id, settings)
    diagnostic_ticks_output_path = _resolve_diagnostic_ticks_output_path(
        settings,
        terminal_data_path,
        diagnostic_ticks_relative_path,
    )

    rendered_source = render_candidate_ea(
        spec,
        audit_relative_path=audit_relative_path,
        broker_history_relative_path=broker_history_relative_path,
        diagnostic_windows_relative_path=diagnostic_windows_relative_path,
        diagnostic_ticks_relative_path=diagnostic_ticks_relative_path,
        packet_run_id=packet_run_id,
        broker_timezone=settings.policy.ftmo_timezone,
    )
    ea_source_path.write_text(rendered_source, encoding="utf-8")
    expected_signal_frame.to_csv(expected_signal_path, index=False)
    logic_manifest = build_logic_manifest_payload(
        spec=spec,
        rendered_source=rendered_source,
        expected_signal_frame=expected_signal_frame,
        settings=settings,
        source_artifact_paths={
            "strategy_spec_path": report_dir / "strategy_spec.json",
            "review_packet_path": report_dir / "review_packet.json",
            "expected_signal_path": expected_signal_path,
        },
    )
    logic_manifest_hash = str(logic_manifest["logic_manifest_hash"])

    run_spec = MT5RunSpec(
        candidate_id=candidate_id,
        run_id=packet_run_id,
        install_id=install_id,
        diagnostic_only=False,
        terminal_path=str(terminal_path) if terminal_path else None,
        portable_mode=bool(terminal_path and terminal_data_path and terminal_path.parent == terminal_data_path),
        tester_mode=settings.mt5_env.tester_mode,
        tick_mode=settings.mt5_env.tester_mode,
        spread_behavior="configured_by_strategy_tester",
        allow_live_trading=settings.mt5_env.allow_live_trading,
        shutdown_terminal=settings.mt5_env.shutdown_terminal,
        config_path=tester_config_path,
        report_path=report_path,
        compile_target_path=terminal_data_path / compile_target_path if terminal_data_path else compile_target_path,
        compile_request_path=compile_request_path,
        launch_request_path=launch_request_path,
        run_dir=run_dir,
        audit_relative_path=audit_relative_path,
        audit_output_path=audit_output_path,
        broker_history_relative_path=broker_history_relative_path,
        broker_history_output_path=broker_history_output_path,
        diagnostic_windows_relative_path=diagnostic_windows_relative_path,
        diagnostic_windows_output_path=diagnostic_windows_output_path,
        diagnostic_ticks_relative_path=diagnostic_ticks_relative_path,
        diagnostic_ticks_output_path=diagnostic_ticks_output_path,
        tester_timeout_seconds=settings.mt5_env.parity_launch_timeout_seconds,
        logic_manifest_hash=logic_manifest_hash,
    )
    write_json(
        logic_manifest_path,
        {
            **logic_manifest,
            "candidate_id": candidate_id,
            "entry_style": summary.get("entry_style", spec.entry_style),
            "practice_only": True,
            "parity_only": True,
            "research_truth_boundary": "reports_only_never_mt5_artifacts",
            "mt5_artifact_reuse_for_features_forbidden": True,
            "signal_audit_fields": AUDIT_COLUMNS,
            "approval_recommendation": review_packet.get("approval_recommendation", "needs_human_review"),
            "run_spec_path": str(run_dir / "run_spec.json"),
            "ea_source_path": str(ea_source_path),
            "expected_signal_path": str(expected_signal_path),
            "audit_relative_path": audit_relative_path,
            "audit_output_path": str(audit_output_path) if audit_output_path else None,
            "broker_history_relative_path": broker_history_relative_path,
            "broker_history_output_path": str(broker_history_output_path) if broker_history_output_path else None,
            "diagnostic_windows_relative_path": diagnostic_windows_relative_path,
            "diagnostic_windows_output_path": str(diagnostic_windows_output_path) if diagnostic_windows_output_path else None,
            "diagnostic_ticks_relative_path": diagnostic_ticks_relative_path,
            "diagnostic_ticks_output_path": str(diagnostic_ticks_output_path) if diagnostic_ticks_output_path else None,
            "news_blackout_mode": "manual_calendar_alignment_required",
            "expected_signal_mode": "mt5_executable_baseline",
            "terminal_data_path": str(terminal_data_path) if terminal_data_path else None,
            "stale_packet_policy": settings.mt5_env.stale_packet_policy,
        },
    )

    deployed_source_path: Path | None = None
    compiled_ex5_path: Path | None = None
    compile_log_path: Path | None = None
    if terminal_data_path and metaeditor_path:
        try:
            deployed_source_path, compiled_ex5_path, compile_log_path = _deploy_and_compile_ea(
                candidate_id=candidate_id,
                packet_source_path=ea_source_path,
                compile_target_relative_path=compile_target_path,
                terminal_data_path=terminal_data_path,
                metaeditor_path=metaeditor_path,
                packet_dir=packet_dir,
            )
        except RuntimeError:
            if (
                base_terminal_data_path is None
                or base_metaeditor_path is None
                or base_terminal_data_path == terminal_data_path
            ):
                raise
            base_source_path, base_ex5_path, compile_log_path = _deploy_and_compile_ea(
                candidate_id=candidate_id,
                packet_source_path=ea_source_path,
                compile_target_relative_path=compile_target_path,
                terminal_data_path=base_terminal_data_path,
                metaeditor_path=base_metaeditor_path,
                packet_dir=packet_dir,
            )
            deployed_source_path, compiled_ex5_path = _stage_existing_build_for_launch(
                source_path=base_source_path,
                compiled_ex5_path=base_ex5_path,
                compile_target_relative_path=compile_target_path,
                terminal_data_path=terminal_data_path,
            )

    tester_config_path.write_text(_tester_ini(candidate_id, run_spec, settings, spec, expected_signal_frame), encoding="utf-8")
    write_json(run_dir / "run_spec.json", run_spec.model_dump(mode="json"))
    write_json(
        compile_request_path,
        {
            "candidate_id": candidate_id,
            "run_id": packet_run_id,
            "install_id": install_id,
            "compile_target_path": str(run_spec.compile_target_path),
            "packet_source_path": str(ea_source_path),
            "deployed_source_path": str(deployed_source_path) if deployed_source_path else None,
            "compiled_ex5_path": str(compiled_ex5_path) if compiled_ex5_path else None,
            "compile_log_path": str(compile_log_path) if compile_log_path else None,
            "terminal_data_path": str(terminal_data_path) if terminal_data_path else None,
            "metaeditor_path": str(metaeditor_path) if metaeditor_path else None,
            "metaeditor_command": "metaeditor64.exe /compile:<full path>",
            "logic_manifest_hash": logic_manifest_hash,
            "audit_relative_path": audit_relative_path,
            "audit_output_path": str(audit_output_path) if audit_output_path else None,
            "broker_history_relative_path": broker_history_relative_path,
            "broker_history_output_path": str(broker_history_output_path) if broker_history_output_path else None,
            "diagnostic_windows_relative_path": diagnostic_windows_relative_path,
            "diagnostic_windows_output_path": str(diagnostic_windows_output_path) if diagnostic_windows_output_path else None,
            "diagnostic_ticks_relative_path": diagnostic_ticks_relative_path,
            "diagnostic_ticks_output_path": str(diagnostic_ticks_output_path) if diagnostic_ticks_output_path else None,
        },
    )
    write_json(
        launch_request_path,
        {
            "candidate_id": candidate_id,
            "run_id": packet_run_id,
            "terminal_path": str(terminal_path) if terminal_path else None,
            "install_id": install_id,
            "portable_mode": run_spec.portable_mode,
            "config_path": str(tester_config_path),
            "launch_mode": "/config",
            "audit_relative_path": audit_relative_path,
            "audit_output_path": str(audit_output_path) if audit_output_path else None,
            "broker_history_relative_path": broker_history_relative_path,
            "broker_history_output_path": str(broker_history_output_path) if broker_history_output_path else None,
            "diagnostic_windows_relative_path": diagnostic_windows_relative_path,
            "diagnostic_windows_output_path": str(diagnostic_windows_output_path) if diagnostic_windows_output_path else None,
            "diagnostic_ticks_relative_path": diagnostic_ticks_relative_path,
            "diagnostic_ticks_output_path": str(diagnostic_ticks_output_path) if diagnostic_ticks_output_path else None,
        },
    )
    notes_path.write_text(
        "\n".join(
            [
                f"# MT5 Packet: {candidate_id}",
                "",
                "- Practice only: true",
                "- Canonical research data source: OANDA",
                "- MT5 is parity validation only and must not feed training or research data stores.",
                "- MT5 packet artifacts must not be reused as features, labels, or ranking inputs.",
                "- Primary parity gate: rebuild the executable baseline from MT5-exported broker history captured during the tester run.",
                "- Packet expected signals remain a fallback artifact only when broker history export is unavailable.",
                f"- MT5 packet run id: {packet_run_id}",
                f"- Automated terminal path: {terminal_path}" if terminal_path else "- Automated terminal path: unavailable",
                f"- Automated terminal data path: {terminal_data_path}" if terminal_data_path else "- Automated terminal data path: unavailable",
                f"- Automated MetaEditor path: {metaeditor_path}" if metaeditor_path else "- Automated MetaEditor path: unavailable",
                f"- Audit output path: {audit_output_path}" if audit_output_path else "- Audit output path: unavailable",
                (
                    f"- Broker history output path: {broker_history_output_path}"
                    if broker_history_output_path
                    else "- Broker history output path: unavailable"
                ),
                f"- Deployed MQ5 path: {deployed_source_path}" if deployed_source_path else "- Deployed MQ5 path: unavailable",
                f"- Compiled EX5 path: {compiled_ex5_path}" if compiled_ex5_path else "- Compiled EX5 path: unavailable",
                f"- Compile log path: {compile_log_path}" if compile_log_path else "- Compile log path: unavailable",
            ]
        ),
        encoding="utf-8",
    )
    packet = MT5Packet(
        candidate_id=candidate_id,
        packet_dir=packet_dir,
        logic_manifest_path=logic_manifest_path,
        expected_signal_path=expected_signal_path,
        notes_path=notes_path,
        ea_source_path=ea_source_path,
        deployed_source_path=deployed_source_path,
        compiled_ex5_path=compiled_ex5_path,
        compile_log_path=compile_log_path,
        terminal_data_path=terminal_data_path,
        metaeditor_path=metaeditor_path,
        logic_manifest_hash=logic_manifest_hash,
        audit_relative_path=audit_relative_path,
        audit_output_path=audit_output_path,
        run_spec_path=run_dir / "run_spec.json",
        tester_config_path=tester_config_path,
        compile_request_path=compile_request_path,
        launch_request_path=launch_request_path,
    )
    write_json(packet_record_path, packet.model_dump(mode="json"))

    environment_snapshot = build_environment_snapshot(settings, candidate_id=candidate_id)
    append_trial_entry(
        settings,
        candidate_id=candidate_id,
        family=spec.family,
        stage="mt5_packet",
        artifact_paths={
            "packet_path": str(packet_record_path),
            "logic_manifest_path": str(logic_manifest_path),
            "expected_signal_path": str(expected_signal_path),
            "ea_source_path": str(ea_source_path),
            "deployed_source_path": str(deployed_source_path) if deployed_source_path else "",
            "compiled_ex5_path": str(compiled_ex5_path) if compiled_ex5_path else "",
            "compile_log_path": str(compile_log_path) if compile_log_path else "",
            "run_spec_path": str(run_dir / "run_spec.json"),
            "tester_config_path": str(tester_config_path),
            "compile_request_path": str(compile_request_path),
            "launch_request_path": str(launch_request_path),
            "environment_snapshot_path": str(environment_snapshot.report_path),
        },
        environment_snapshot_id=environment_snapshot.environment_id,
        gate_outcomes={
            "allow_live_trading": run_spec.allow_live_trading,
            "shutdown_terminal": run_spec.shutdown_terminal,
            "logic_manifest_hash": logic_manifest_hash,
        },
    )
    return packet


def run_mt5_parity(candidate_id: str, settings: Settings) -> MT5ParityReport:
    return _run_mt5_parity_mode(
        candidate_id,
        settings,
        diagnostic_only=False,
        tester_mode_override=settings.mt5_env.parity_tester_mode,
    )


def run_mt5_parity_diagnostic(candidate_id: str, settings: Settings) -> MT5ParityReport:
    return _run_mt5_parity_mode(
        candidate_id,
        settings,
        diagnostic_only=True,
        tester_mode_override=settings.mt5_env.parity_diagnostic_tester_mode or settings.mt5_env.tester_mode,
    )


def run_mt5_manual_test(
    candidate_id: str,
    settings: Settings,
    *,
    deposit: float | None = None,
    leverage: float | None = None,
    fixed_lots: float | None = None,
    auto_scale_lots: bool = False,
    min_lot: float = 0.01,
    lot_step: float = 0.01,
    tester_mode: str | None = None,
) -> MT5ManualRunReport:
    require_stage_approval(candidate_id, "mt5_packet", settings)
    packet = load_mt5_packet(candidate_id, settings)
    packet_reused = packet is not None and not _is_packet_stale(candidate_id, settings, packet)
    if not packet_reused:
        packet = generate_mt5_packet(candidate_id, settings)
    assert packet is not None
    canonical_spec = _load_spec(settings, candidate_id)
    manual_spec, manual_overrides = _manual_run_strategy_spec(
        canonical_spec,
        deposit=deposit,
        leverage=leverage,
        fixed_lots=fixed_lots,
        auto_scale_lots=auto_scale_lots or (deposit is not None and fixed_lots is None),
        min_lot=min_lot,
        lot_step=lot_step,
    )

    manual_run_id = f"mt5manual-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = settings.paths().mt5_runs_dir / candidate_id / manual_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_spec = _manual_run_spec_from_packet(
        packet,
        settings,
        run_dir,
        manual_run_id,
        spec=manual_spec,
        tester_mode_override=tester_mode,
    )
    tester_inputs_profile_path = _write_tester_inputs_profile(run_spec, manual_spec)
    write_json(run_dir / "run_spec.json", run_spec.model_dump(mode="json"))
    write_json(
        run_spec.launch_request_path,
        {
            "candidate_id": candidate_id,
            "run_id": manual_run_id,
            "terminal_path": run_spec.terminal_path,
            "portable_mode": run_spec.portable_mode,
            "config_path": str(run_spec.config_path),
            "launch_mode": "/config",
            "logic_manifest_hash": run_spec.logic_manifest_hash,
            "packet_reused": packet_reused,
            "manual_run": True,
            "tester_mode": run_spec.tester_mode,
            "tester_inputs_profile_path": str(tester_inputs_profile_path) if tester_inputs_profile_path else None,
            "manual_overrides": manual_overrides,
            "broker_history_relative_path": run_spec.broker_history_relative_path,
            "broker_history_output_path": (
                str(run_spec.broker_history_output_path) if run_spec.broker_history_output_path else None
            ),
            "diagnostic_windows_relative_path": run_spec.diagnostic_windows_relative_path,
            "diagnostic_windows_output_path": (
                str(run_spec.diagnostic_windows_output_path) if run_spec.diagnostic_windows_output_path else None
            ),
            "diagnostic_ticks_relative_path": run_spec.diagnostic_ticks_relative_path,
            "diagnostic_ticks_output_path": (
                str(run_spec.diagnostic_ticks_output_path) if run_spec.diagnostic_ticks_output_path else None
            ),
        },
    )
    run_spec.config_path.write_text(
        _tester_ini(
            candidate_id,
            run_spec,
            settings,
            manual_spec,
            _load_expected_signal_frame(packet.expected_signal_path),
        ),
        encoding="utf-8",
    )
    _clear_previous_parity_outputs(run_spec)
    run_result = _launch_mt5_tester(run_spec, settings)
    report = MT5ManualRunReport(
        candidate_id=candidate_id,
        run_id=manual_run_id,
        packet_reused=packet_reused,
        tester_mode=run_spec.tester_mode,
        launch_status=run_result.launch_status,
        manual_overrides=manual_overrides,
        tester_config_path=run_spec.config_path,
        launch_request_path=run_spec.launch_request_path,
        tester_report_path=run_result.tester_report_path,
        audit_csv_path=run_result.audit_csv_path,
        broker_history_csv_path=run_result.broker_history_csv_path,
        diagnostic_ticks_csv_path=run_result.diagnostic_ticks_csv_path,
        runtime_summary_json_path=run_result.runtime_summary_json_path,
        signal_trace_csv_path=run_result.signal_trace_csv_path,
        tester_inputs_profile_path=tester_inputs_profile_path,
        launch_status_path=run_result.launch_status_path,
        report_path=run_dir / "mt5_manual_run_report.json",
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    return report


def run_mt5_incident_replay(
    candidate_id: str,
    settings: Settings,
    *,
    window_start: str,
    window_end: str,
    incident_id: str | None = None,
    deposit: float | None = None,
    leverage: float | None = None,
    fixed_lots: float | None = None,
    tester_mode: str | None = None,
) -> MT5IncidentReplayReport:
    require_stage_approval(candidate_id, "mt5_packet", settings)
    packet = load_mt5_packet(candidate_id, settings)
    packet_reused = packet is not None and not _is_packet_stale(candidate_id, settings, packet)
    if not packet_reused:
        packet = generate_mt5_packet(candidate_id, settings)
    assert packet is not None

    canonical_spec = _load_spec(settings, candidate_id)
    replay_spec, manual_overrides = _manual_run_strategy_spec(
        canonical_spec,
        deposit=deposit,
        leverage=leverage,
        fixed_lots=fixed_lots,
        auto_scale_lots=False,
        min_lot=0.01,
        lot_step=0.01,
    )
    replay_run_id = f"mt5incident-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = settings.paths().mt5_runs_dir / candidate_id / replay_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_spec = _manual_run_spec_from_packet(
        packet,
        settings,
        run_dir,
        replay_run_id,
        spec=replay_spec,
        tester_mode_override=tester_mode,
    )
    run_spec.tester_from_date = _format_tester_date(window_start)
    run_spec.tester_to_date = _format_tester_date(window_end)
    tester_inputs_profile_path = _write_tester_inputs_profile(run_spec, replay_spec)
    write_json(run_dir / "run_spec.json", run_spec.model_dump(mode="json"))
    write_json(
        run_spec.launch_request_path,
        {
            "candidate_id": candidate_id,
            "run_id": replay_run_id,
            "incident_id": incident_id,
            "terminal_path": run_spec.terminal_path,
            "portable_mode": run_spec.portable_mode,
            "config_path": str(run_spec.config_path),
            "launch_mode": "/config",
            "logic_manifest_hash": run_spec.logic_manifest_hash,
            "packet_reused": packet_reused,
            "incident_replay": True,
            "tester_mode": run_spec.tester_mode,
            "tester_from_date": run_spec.tester_from_date,
            "tester_to_date": run_spec.tester_to_date,
            "tester_inputs_profile_path": str(tester_inputs_profile_path) if tester_inputs_profile_path else None,
            "manual_overrides": manual_overrides,
        },
    )
    run_spec.config_path.write_text(
        _tester_ini(
            candidate_id,
            run_spec,
            settings,
            replay_spec,
            pd.DataFrame(columns=EXPECTED_SIGNAL_COLUMNS),
        ),
        encoding="utf-8",
    )
    _clear_previous_parity_outputs(run_spec)
    run_result = _launch_mt5_tester(run_spec, settings)
    report_trade_count = _tester_report_trade_count(run_result.tester_report_path)
    baseline_harness_passed = _latest_incident_baseline_harness_passed(candidate_id, settings)
    harness_status = (
        "replay_ready"
        if baseline_harness_passed
        and run_result.launch_status == "completed"
        and report_trade_count is not None
        and report_trade_count > 0
        else "harness_untrusted"
    )
    notes = []
    if not baseline_harness_passed:
        notes.append(
            "Old known-good baseline harness has not passed in the latest incident report; "
            "same-window replay remains non-authoritative."
        )
    if run_result.launch_status != "completed":
        notes.append("Replay did not complete cleanly; treat the MT5 harness as untrusted for incident attribution.")
    if harness_status == "harness_untrusted":
        notes.append("Replay completed without a positive parsed Total Trades count; do not use this as strategy evidence.")
    certification_report = _build_mt5_certification_report(
        settings,
        strategy_spec=replay_spec,
        run_spec=run_spec,
        run_result=run_result,
        validation_report=None,
        baseline_reproduction_passed=baseline_harness_passed,
        deployment_target=False,
        basis="incident_replay_same_window",
        notes=notes,
    )
    report = MT5IncidentReplayReport(
        candidate_id=candidate_id,
        run_id=replay_run_id,
        incident_id=incident_id,
        window_start=window_start,
        window_end=window_end,
        launch_status=run_result.launch_status,
        harness_status=harness_status,  # type: ignore[arg-type]
        certification_status=certification_report.certification.status,
        certification_report_path=certification_report.report_path,
        tick_provenance=certification_report.tick_provenance,
        baseline_reproduction_passed=certification_report.baseline_reproduction_passed,
        report_trade_count=report_trade_count,
        manual_overrides=manual_overrides,
        tester_config_path=run_spec.config_path,
        launch_request_path=run_spec.launch_request_path,
        tester_inputs_profile_path=tester_inputs_profile_path,
        tester_report_path=run_result.tester_report_path,
        audit_csv_path=run_result.audit_csv_path,
        broker_history_csv_path=run_result.broker_history_csv_path,
        diagnostic_ticks_csv_path=run_result.diagnostic_ticks_csv_path,
        runtime_summary_json_path=run_result.runtime_summary_json_path,
        signal_trace_csv_path=run_result.signal_trace_csv_path,
        launch_status_path=run_result.launch_status_path,
        notes=notes,
        report_path=run_dir / "mt5_incident_replay_report.json",
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    return report


def _latest_incident_baseline_harness_passed(candidate_id: str, settings: Settings) -> bool:
    latest_path = settings.paths().incidents_dir / candidate_id / "latest_incident_report.json"
    if not latest_path.exists():
        return False
    try:
        payload = read_json(latest_path)
    except Exception:
        return False
    harness_check = payload.get("harness_check") or {}
    return harness_check.get("status") == "passed"


def _manual_run_strategy_spec(
    spec: StrategySpec,
    *,
    deposit: float | None,
    leverage: float | None,
    fixed_lots: float | None,
    auto_scale_lots: bool,
    min_lot: float,
    lot_step: float,
) -> tuple[StrategySpec, dict[str, float | str | bool | None]]:
    manual_spec = spec.model_copy(deep=True)
    canonical_deposit = float(spec.account_model.initial_balance)
    canonical_leverage = float(spec.account_model.leverage)
    canonical_fixed_lots = min(float(spec.account_model.max_total_exposure_lots), 5.0)
    manual_overrides: dict[str, float | str | bool | None] = {
        "deposit": deposit,
        "leverage": leverage,
        "fixed_lots": fixed_lots,
        "auto_scale_lots": auto_scale_lots,
        "canonical_deposit": round(canonical_deposit, 6),
        "canonical_leverage": round(canonical_leverage, 6),
        "canonical_fixed_lots": round(canonical_fixed_lots, 6),
        "min_lot": round(float(min_lot), 6),
        "lot_step": round(float(lot_step), 6),
        "sizing_mode": "canonical_packet",
    }
    if deposit is not None:
        manual_spec.account_model.initial_balance = float(deposit)
    if leverage is not None:
        manual_spec.account_model.leverage = float(leverage)
        manual_spec.risk_envelope.leverage = float(leverage)

    effective_fixed_lots = canonical_fixed_lots
    if fixed_lots is not None:
        effective_fixed_lots = _quantize_lot_size(float(fixed_lots), min_lot=min_lot, lot_step=lot_step)
        manual_overrides["sizing_mode"] = "explicit_fixed_lots"
    elif auto_scale_lots and deposit is not None and canonical_deposit > 0:
        scaled_fixed_lots = canonical_fixed_lots * (float(deposit) / canonical_deposit)
        effective_fixed_lots = _quantize_lot_size(scaled_fixed_lots, min_lot=min_lot, lot_step=lot_step)
        manual_overrides["scaled_fixed_lots_raw"] = round(scaled_fixed_lots, 6)
        manual_overrides["sizing_mode"] = "scaled_from_canonical"

    manual_spec.account_model.max_total_exposure_lots = effective_fixed_lots
    manual_overrides["effective_fixed_lots"] = round(effective_fixed_lots, 6)
    return manual_spec, manual_overrides


def _quantize_lot_size(raw_lots: float, *, min_lot: float, lot_step: float) -> float:
    resolved_step = max(float(lot_step), 0.0001)
    resolved_min = max(float(min_lot), resolved_step)
    safe_raw = max(float(raw_lots), 0.0)
    if safe_raw <= 0.0:
        safe_raw = resolved_min
    stepped = math.floor((safe_raw + 1e-12) / resolved_step) * resolved_step
    if stepped < resolved_min:
        stepped = resolved_min
    return round(stepped, _lot_precision(resolved_step))


def _lot_precision(lot_step: float) -> int:
    normalized = f"{lot_step:.8f}".rstrip("0").rstrip(".")
    if "." not in normalized:
        return 0
    return len(normalized.split(".", 1)[1])


def _run_mt5_parity_mode(
    candidate_id: str,
    settings: Settings,
    *,
    diagnostic_only: bool,
    tester_mode_override: str | None,
) -> MT5ParityReport:
    require_stage_approval(candidate_id, "mt5_packet", settings)
    require_stage_approval(candidate_id, "mt5_parity_run", settings)
    require_stage_approval(candidate_id, "mt5_validation", settings)
    parity_policy = _resolve_effective_parity_policy(
        candidate_id,
        settings,
        enforce_official=not diagnostic_only,
    )
    packet = load_mt5_packet(candidate_id, settings)
    packet_reused = packet is not None and not _is_packet_stale(candidate_id, settings, packet)
    if not packet_reused:
        packet = generate_mt5_packet(candidate_id, settings)
    assert packet is not None

    run_prefix = "mt5diag" if diagnostic_only else "mt5run"
    parity_run_id = f"{run_prefix}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = settings.paths().mt5_runs_dir / candidate_id / parity_run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_spec = _parity_run_spec_from_packet(
        packet,
        settings,
        run_dir,
        parity_run_id,
        tester_mode_override=tester_mode_override,
        diagnostic_only=diagnostic_only,
    )
    run_spec.lineage_root_candidate_id = parity_policy["lineage_root_candidate_id"]
    run_spec.parity_class = parity_policy["parity_class"]
    run_spec.parity_policy_lane_ids = list(parity_policy["lane_ids"])
    run_spec.parity_policy_snapshot_hash = parity_policy["policy_snapshot_hash"]
    diagnostic_window_count = _stage_diagnostic_tick_windows(candidate_id, settings, run_spec=run_spec)
    parity_spec = _load_spec(settings, candidate_id)
    tester_inputs_profile_path = _write_tester_inputs_profile(run_spec, parity_spec)
    write_json(run_dir / "run_spec.json", run_spec.model_dump(mode="json"))
    write_json(
        run_spec.launch_request_path,
        {
            "candidate_id": candidate_id,
            "run_id": parity_run_id,
            "terminal_path": run_spec.terminal_path,
            "portable_mode": run_spec.portable_mode,
            "config_path": str(run_spec.config_path),
            "launch_mode": "/config",
            "logic_manifest_hash": run_spec.logic_manifest_hash,
            "packet_reused": packet_reused,
            "diagnostic_only": diagnostic_only,
            "tester_mode": run_spec.tester_mode,
            "tester_inputs_profile_path": str(tester_inputs_profile_path) if tester_inputs_profile_path else None,
            "lineage_root_candidate_id": run_spec.lineage_root_candidate_id,
            "parity_class": run_spec.parity_class,
            "parity_policy_lane_ids": run_spec.parity_policy_lane_ids,
            "parity_policy_snapshot_hash": run_spec.parity_policy_snapshot_hash,
            "broker_history_relative_path": run_spec.broker_history_relative_path,
            "broker_history_output_path": (
                str(run_spec.broker_history_output_path) if run_spec.broker_history_output_path else None
            ),
            "diagnostic_windows_relative_path": run_spec.diagnostic_windows_relative_path,
            "diagnostic_windows_output_path": (
                str(run_spec.diagnostic_windows_output_path) if run_spec.diagnostic_windows_output_path else None
            ),
            "diagnostic_ticks_relative_path": run_spec.diagnostic_ticks_relative_path,
            "diagnostic_ticks_output_path": (
                str(run_spec.diagnostic_ticks_output_path) if run_spec.diagnostic_ticks_output_path else None
            ),
            "diagnostic_window_count": diagnostic_window_count,
        },
    )
    run_spec.config_path.write_text(
        _tester_ini(candidate_id, run_spec, settings, parity_spec, _load_expected_signal_frame(packet.expected_signal_path)),
        encoding="utf-8",
    )
    _clear_previous_parity_outputs(run_spec)
    run_result = _launch_mt5_tester(run_spec, settings)
    validation_report = validate_mt5_practice(
        candidate_id,
        settings,
        run_result.audit_csv_path,
        broker_history_csv=run_result.broker_history_csv_path,
        signal_trace_csv=run_result.signal_trace_csv_path,
        run_id=parity_run_id,
        report_dir=run_dir,
        strict_missing=True,
        lineage_root_candidate_id=run_spec.lineage_root_candidate_id,
        parity_class=run_spec.parity_class,
        parity_policy_lane_ids=run_spec.parity_policy_lane_ids,
        parity_policy_snapshot_hash=run_spec.parity_policy_snapshot_hash,
    )
    diagnostic_tick_analysis_path = _write_diagnostic_tick_analysis(
        candidate_id=candidate_id,
        run_id=parity_run_id,
        diagnostics_report_path=validation_report.diagnostics_report_path,
        diagnostic_windows_path=run_dir / "diagnostic_tick_windows.csv",
        diagnostic_ticks_csv_path=run_result.diagnostic_ticks_csv_path,
        destination_dir=run_dir,
    )
    certification_notes: list[str] = []
    if diagnostic_only:
        certification_notes.append("Diagnostic MT5 parity is non-authoritative even when validation passes.")
    certification_report = _build_mt5_certification_report(
        settings,
        strategy_spec=parity_spec,
        run_spec=run_spec,
        run_result=run_result,
        validation_report=validation_report,
        baseline_reproduction_passed=validation_report.validation_status == "passed",
        deployment_target=not diagnostic_only and run_spec.parity_class == "m1_official",
        basis="mt5_parity_validation",
        notes=certification_notes,
    )
    parity_report = MT5ParityReport(
        candidate_id=candidate_id,
        run_id=parity_run_id,
        diagnostic_only=diagnostic_only,
        lineage_root_candidate_id=run_spec.lineage_root_candidate_id,
        parity_class=run_spec.parity_class,
        parity_policy_lane_ids=run_spec.parity_policy_lane_ids,
        parity_policy_snapshot_hash=run_spec.parity_policy_snapshot_hash,
        tester_mode=run_spec.tester_mode,
        packet_reused=packet_reused,
        logic_manifest_hash=run_spec.logic_manifest_hash,
        validation_status=validation_report.validation_status,
        failure_classification=validation_report.failure_classification,
        parity_rate=validation_report.parity_rate,
        audit_rows=validation_report.audit_rows,
        certification_status=certification_report.certification.status,
        certification_report_path=certification_report.report_path,
        tick_provenance=certification_report.tick_provenance,
        baseline_reproduction_passed=certification_report.baseline_reproduction_passed,
        tester_report_path=run_result.tester_report_path,
        audit_csv_path=run_result.audit_csv_path,
        broker_history_csv_path=run_result.broker_history_csv_path,
        diagnostic_ticks_csv_path=run_result.diagnostic_ticks_csv_path,
        diagnostic_tick_analysis_path=diagnostic_tick_analysis_path,
        runtime_summary_json_path=run_result.runtime_summary_json_path,
        signal_trace_csv_path=run_result.signal_trace_csv_path,
        tester_inputs_profile_path=tester_inputs_profile_path,
        launch_status_path=run_result.launch_status_path,
        validation_report_path=validation_report.report_path,
        diagnostics_report_path=validation_report.diagnostics_report_path,
        report_path=run_dir / ("mt5_parity_diagnostic_report.json" if diagnostic_only else "mt5_parity_report.json"),
    )
    write_json(parity_report.report_path, parity_report.model_dump(mode="json"))

    environment_snapshot = build_environment_snapshot(settings, candidate_id=candidate_id)
    append_trial_entry(
        settings,
        candidate_id=candidate_id,
        family=_load_spec(settings, candidate_id).family,
        stage="mt5_parity_diagnostic" if diagnostic_only else "mt5_parity_run",
        artifact_paths={
            "packet_path": str(packet.packet_dir / "packet.json"),
            "run_spec_path": str(run_dir / "run_spec.json"),
            "tester_config_path": str(run_spec.config_path),
            "launch_request_path": str(run_spec.launch_request_path),
            "launch_status_path": str(run_result.launch_status_path),
            "tester_report_path": str(run_result.tester_report_path) if run_result.tester_report_path else "",
            "audit_csv_path": str(run_result.audit_csv_path) if run_result.audit_csv_path else "",
            "broker_history_csv_path": str(run_result.broker_history_csv_path) if run_result.broker_history_csv_path else "",
            "diagnostic_tick_windows_path": str(run_spec.run_dir / "diagnostic_tick_windows.csv")
            if (run_spec.run_dir / "diagnostic_tick_windows.csv").exists()
            else "",
            "diagnostic_ticks_csv_path": str(run_result.diagnostic_ticks_csv_path) if run_result.diagnostic_ticks_csv_path else "",
            "diagnostic_tick_analysis_path": str(diagnostic_tick_analysis_path) if diagnostic_tick_analysis_path else "",
            "validation_report_path": str(validation_report.report_path),
            "diagnostics_report_path": str(validation_report.diagnostics_report_path) if validation_report.diagnostics_report_path else "",
            "mt5_certification_report_path": str(certification_report.report_path) if certification_report.report_path else "",
            "mt5_parity_report_path": str(parity_report.report_path),
            "environment_snapshot_path": str(environment_snapshot.report_path),
        },
        environment_snapshot_id=environment_snapshot.environment_id,
        gate_outcomes={
            "packet_reused": packet_reused,
            "diagnostic_only": diagnostic_only,
            "lineage_root_candidate_id": run_spec.lineage_root_candidate_id,
            "parity_class": run_spec.parity_class,
            "parity_policy_lane_ids": run_spec.parity_policy_lane_ids,
            "parity_policy_snapshot_hash": run_spec.parity_policy_snapshot_hash,
            "tester_mode": run_spec.tester_mode,
            "launch_status": run_result.launch_status,
            "validation_status": validation_report.validation_status,
            "failure_classification": validation_report.failure_classification,
            "parity_rate": validation_report.parity_rate,
            "tick_provenance": certification_report.tick_provenance,
            "baseline_reproduction_passed": certification_report.baseline_reproduction_passed,
            "certification_status": certification_report.certification.status,
        },
        failure_code=None if diagnostic_only else _failure_code_from_classification(validation_report.failure_classification),
    )
    if validation_report.failure_classification and not diagnostic_only:
        append_failure_record(
            settings,
            candidate_id=candidate_id,
            stage="mt5_parity_run",
            failure_code=_failure_code_from_classification(validation_report.failure_classification),
            details={
                "validation_status": validation_report.validation_status,
                "parity_rate": validation_report.parity_rate,
                "launch_status": run_result.launch_status,
                "lineage_root_candidate_id": run_spec.lineage_root_candidate_id,
                "parity_class": run_spec.parity_class,
                "certification_status": certification_report.certification.status,
            },
            artifact_paths={
                "mt5_parity_report_path": str(parity_report.report_path),
                "validation_report_path": str(validation_report.report_path),
                "diagnostics_report_path": str(validation_report.diagnostics_report_path) if validation_report.diagnostics_report_path else "",
                "diagnostic_ticks_csv_path": str(run_result.diagnostic_ticks_csv_path) if run_result.diagnostic_ticks_csv_path else "",
                "mt5_certification_report_path": str(certification_report.report_path) if certification_report.report_path else "",
            },
        )
    return parity_report


def validate_mt5_practice(
    candidate_id: str,
    settings: Settings,
    audit_csv: Path | None,
    *,
    broker_history_csv: Path | None = None,
    signal_trace_csv: Path | None = None,
    run_id: str | None = None,
    report_dir: Path | None = None,
    strict_missing: bool = False,
    lineage_root_candidate_id: str | None = None,
    parity_class: str | None = None,
    parity_policy_lane_ids: list[str] | None = None,
    parity_policy_snapshot_hash: str | None = None,
) -> MT5ValidationReport:
    require_stage_approval(candidate_id, "mt5_validation", settings)
    packet_dir = settings.paths().approvals_dir / "mt5_packets" / candidate_id
    expected_signal_path = packet_dir / "expected_signals.csv"
    packet_expected = _load_expected_signal_frame(expected_signal_path)
    expected = packet_expected
    expected_signal_source = "packet_expected_signals"
    spec = _load_spec(settings, candidate_id)
    broker_history_frame = pd.DataFrame(columns=BROKER_HISTORY_COLUMNS)
    if broker_history_csv and broker_history_csv.exists():
        broker_history_frame = _load_broker_history_frame(broker_history_csv)
        broker_expected = (
            _signal_trace_expected_signal_frame(
                settings=settings,
                spec=spec,
                candidate_id=candidate_id,
                broker_history_csv=broker_history_csv,
                signal_trace_csv=signal_trace_csv,
            )
            if signal_trace_csv and signal_trace_csv.exists()
            else _broker_history_expected_signal_frame(settings, spec, candidate_id, broker_history_csv)
        )
        broker_expected = _constrain_expected_frame_to_packet_range(broker_expected, packet_expected)
        if not broker_expected.empty:
            expected = broker_expected
            expected_signal_source = (
                "broker_history_signal_trace_baseline"
                if signal_trace_csv and signal_trace_csv.exists()
                else "broker_history_executable_baseline"
            )
    actual = _load_audit_frame(audit_csv)

    resolved_run_id = run_id
    resolved_run_dir = report_dir
    if resolved_run_id is None or resolved_run_dir is None:
        latest_run_id, latest_run_dir = _latest_run(candidate_id, settings)
        resolved_run_id = resolved_run_id or latest_run_id
        resolved_run_dir = resolved_run_dir or latest_run_dir
    destination_dir = resolved_run_dir or packet_dir

    if audit_csv and audit_csv.exists():
        ingest_mt5_parity_csv(audit_csv, settings)

    validation_status = "pending_audit"
    failure_classification = None
    matched_trade_count = 0
    unmatched_expected_count = int(len(expected))
    unmatched_actual_count = int(len(actual))
    parity_rate = 0.0
    matches: list[dict[str, Any]] = []

    if strict_missing and (audit_csv is None or not audit_csv.exists()):
        validation_status = "failed"
        failure_classification = "parity_failure"
    elif audit_csv is None or not audit_csv.exists():
        validation_status = "pending_audit"
    elif bool(actual.attrs.get("malformed")):
        validation_status = "failed"
        failure_classification = "parity_failure"
    elif actual.empty or expected.empty:
        validation_status = "insufficient_evidence"
    elif len(actual) < settings.validation.parity_min_closed_trades or len(expected) < settings.validation.parity_min_closed_trades:
        validation_status = "insufficient_evidence"
    else:
        uses_broker_history_baseline = expected_signal_source in {
            "broker_history_executable_baseline",
            "broker_history_signal_trace_baseline",
        }
        matches = _match_expected_to_actual(
            expected,
            actual,
            settings,
            spec=spec if uses_broker_history_baseline else None,
            broker_history_frame=broker_history_frame if uses_broker_history_baseline else None,
        )
        matched_trade_count = len(matches)
        unmatched_expected_count = max(len(expected) - matched_trade_count, 0)
        unmatched_actual_count = max(len(actual) - matched_trade_count, 0)
        parity_rate = float(matched_trade_count / max(len(expected), len(actual), 1))
        unmatched_expected_rate = unmatched_expected_count / max(len(expected), 1)
        unmatched_actual_rate = unmatched_actual_count / max(len(actual), 1)
        if (
            parity_rate < settings.validation.parity_min_match_rate
            or unmatched_expected_rate > settings.validation.parity_max_unmatched_expected_rate
            or unmatched_actual_rate > settings.validation.parity_max_unmatched_actual_rate
        ):
            validation_status = "failed"
            failure_classification = "parity_failure"
        elif any(
            match["entry_price_delta_pips"] > settings.validation.parity_price_tolerance_pips
            or (
                match["exit_price_delta_pips"] > settings.validation.parity_price_tolerance_pips
                and not bool(match.get("boundary_ambiguous_exit_semantics", False))
            )
            or (
                match["fill_delta_pips"] > settings.validation.parity_fill_tolerance_pips
                and not bool(match.get("boundary_ambiguous_exit_semantics", False))
            )
            or (
                match["close_timing_delta_seconds"] > settings.validation.parity_close_timing_tolerance_seconds
                and not (
                    bool(match.get("exit_reason_match", True))
                    and match["exit_price_delta_pips"] <= settings.validation.parity_price_tolerance_pips
                    and match["fill_delta_pips"] <= settings.validation.parity_fill_tolerance_pips
                )
                and not bool(match.get("boundary_ambiguous_close_timing", False))
                and not bool(match.get("boundary_ambiguous_exit_semantics", False))
            )
            or (
                not bool(match.get("exit_reason_match", True))
                and not bool(match.get("boundary_ambiguous_exit_semantics", False))
            )
            or not bool(match.get("same_bar_collision_match", True))
            for match in matches
        ):
            validation_status = "failed"
            failure_classification = "execution_cost_failure"
        else:
            validation_status = "passed"

    diagnostics_report_path, matched_trade_diagnostics_path = _write_parity_diagnostics(
        candidate_id=candidate_id,
        run_id=resolved_run_id,
        destination_dir=destination_dir,
        expected=expected,
        actual=actual,
        matches=matches,
        settings=settings,
        expected_signal_source=expected_signal_source,
        validation_status=validation_status,
        failure_classification=failure_classification,
        expected_signal_path=expected_signal_path if expected_signal_path.exists() else None,
        broker_history_csv_path=broker_history_csv if broker_history_csv and broker_history_csv.exists() else None,
    )

    report_path = destination_dir / "validation_report.json"
    report = MT5ValidationReport(
        candidate_id=candidate_id,
        run_id=resolved_run_id,
        lineage_root_candidate_id=lineage_root_candidate_id,
        parity_class=parity_class,
        parity_policy_lane_ids=list(parity_policy_lane_ids or []),
        parity_policy_snapshot_hash=parity_policy_snapshot_hash,
        validation_status=validation_status,  # type: ignore[arg-type]
        failure_classification=failure_classification,  # type: ignore[arg-type]
        parity_rate=round(parity_rate, 6),
        audit_rows=int(len(actual)),
        expected_signal_source=expected_signal_source,
        expected_trade_count=int(len(expected)),
        actual_trade_count=int(len(actual)),
        matched_trade_count=matched_trade_count,
        unmatched_expected_count=unmatched_expected_count,
        unmatched_actual_count=unmatched_actual_count,
        expected_signal_path=expected_signal_path if expected_signal_path.exists() else None,
        broker_history_csv_path=broker_history_csv if broker_history_csv and broker_history_csv.exists() else None,
        matched_trade_diagnostics_path=matched_trade_diagnostics_path,
        diagnostics_report_path=diagnostics_report_path,
        tolerances_used=_parity_tolerances(settings),
        report_path=report_path,
    )
    write_json(report_path, report.model_dump(mode="json"))

    environment_snapshot = build_environment_snapshot(settings, candidate_id=candidate_id)
    append_trial_entry(
        settings,
        candidate_id=candidate_id,
        family=_load_spec(settings, candidate_id).family,
        stage="mt5_validation",
        artifact_paths={
            "validation_report_path": str(report_path),
            "audit_csv_path": str(audit_csv) if audit_csv else "",
            "expected_signal_path": str(expected_signal_path),
            "broker_history_csv_path": str(broker_history_csv) if broker_history_csv and broker_history_csv.exists() else "",
            "matched_trade_diagnostics_path": str(matched_trade_diagnostics_path) if matched_trade_diagnostics_path else "",
            "diagnostics_report_path": str(diagnostics_report_path) if diagnostics_report_path else "",
            "environment_snapshot_path": str(environment_snapshot.report_path),
        },
        environment_snapshot_id=environment_snapshot.environment_id,
        gate_outcomes={
            "validation_status": report.validation_status,
            "failure_classification": report.failure_classification,
            "parity_rate": report.parity_rate,
            "lineage_root_candidate_id": report.lineage_root_candidate_id,
            "parity_class": report.parity_class,
            "parity_policy_lane_ids": report.parity_policy_lane_ids,
            "parity_policy_snapshot_hash": report.parity_policy_snapshot_hash,
            "expected_signal_source": report.expected_signal_source,
            "matched_trade_count": report.matched_trade_count,
            "expected_trade_count": report.expected_trade_count,
            "actual_trade_count": report.actual_trade_count,
        },
        failure_code=_failure_code_from_classification(report.failure_classification),
    )
    if report.failure_classification:
        append_failure_record(
            settings,
            candidate_id=candidate_id,
            stage="mt5_validation",
            failure_code=_failure_code_from_classification(report.failure_classification),
            details={
                "validation_status": report.validation_status,
                "parity_rate": report.parity_rate,
                "matched_trade_count": report.matched_trade_count,
                "lineage_root_candidate_id": report.lineage_root_candidate_id,
                "parity_class": report.parity_class,
            },
            artifact_paths={
                "validation_report_path": str(report_path),
                "diagnostics_report_path": str(diagnostics_report_path) if diagnostics_report_path else "",
                "matched_trade_diagnostics_path": str(matched_trade_diagnostics_path) if matched_trade_diagnostics_path else "",
            },
        )
    return report


def load_mt5_packet(candidate_id: str, settings: Settings) -> MT5Packet | None:
    path = settings.paths().approvals_dir / "mt5_packets" / candidate_id / "packet.json"
    if not path.exists():
        return None
    return MT5Packet.model_validate(read_json(path))


def load_latest_mt5_validation(candidate_id: str, settings: Settings) -> MT5ValidationReport | None:
    root = settings.paths().mt5_runs_dir / candidate_id
    if root.exists():
        for run_dir in sorted((path for path in root.iterdir() if path.is_dir()), reverse=True):
            report_path = run_dir / "validation_report.json"
            if report_path.exists():
                return MT5ValidationReport.model_validate(read_json(report_path))
    packet_path = settings.paths().approvals_dir / "mt5_packets" / candidate_id / "validation_report.json"
    if packet_path.exists():
        return MT5ValidationReport.model_validate(read_json(packet_path))
    return None


def load_latest_mt5_parity_report(candidate_id: str, settings: Settings) -> MT5ParityReport | None:
    root = settings.paths().mt5_runs_dir / candidate_id
    if not root.exists():
        return None
    for run_dir in sorted((path for path in root.iterdir() if path.is_dir()), reverse=True):
        report_path = run_dir / "mt5_parity_report.json"
        if report_path.exists():
            return MT5ParityReport.model_validate(read_json(report_path))
    return None


def _resolve_effective_parity_policy(
    candidate_id: str,
    settings: Settings,
    *,
    enforce_official: bool,
) -> dict[str, Any]:
    spec = _load_spec(settings, candidate_id)
    parent_map, child_map = _trial_lineage_maps(settings)
    ancestor_depths = _candidate_ancestor_depths(candidate_id, parent_map)
    matching_lanes = [
        lane
        for lane in settings.program.approved_lanes
        if lane.family == spec.family and lane.hypothesis_class == spec.entry_style
    ]
    seeded_matches = [
        (lane, ancestor_depths[lane.seed_candidate_id])
        for lane in matching_lanes
        if lane.seed_candidate_id in ancestor_depths
    ]
    if not seeded_matches:
        if enforce_official:
            raise ParityPolicyError(
                f"parity_policy_unset:no_matching_root_seed:family={spec.family}:hypothesis_class={spec.entry_style}"
            )
        return {
            "lineage_root_candidate_id": None,
            "parity_class": None,
            "lane_ids": [],
            "policy_snapshot_hash": policy_snapshot_hash(settings),
        }

    furthest_depth = max(depth for _, depth in seeded_matches)
    root_seed_candidates = sorted(
        {
            lane.seed_candidate_id
            for lane, depth in seeded_matches
            if depth == furthest_depth
        }
    )
    if len(root_seed_candidates) != 1:
        raise ParityPolicyError(
            f"parity_policy_ambiguous_root:family={spec.family}:hypothesis_class={spec.entry_style}:candidate={candidate_id}"
        )
    lineage_root_candidate_id = root_seed_candidates[0]
    root_lanes = [lane for lane in matching_lanes if lane.seed_candidate_id == lineage_root_candidate_id]
    lane_ids = sorted(lane.lane_id for lane in root_lanes)
    configured_classes = sorted({lane.parity_class for lane in root_lanes if lane.parity_class})
    if len(configured_classes) > 1:
        raise ParityPolicyError(
            f"parity_policy_conflict:lineage_root={lineage_root_candidate_id}:classes={','.join(configured_classes)}"
        )
    configured_class = configured_classes[0] if configured_classes else None

    lineage_candidates = _candidate_descendants(lineage_root_candidate_id, child_map)
    lineage_candidates.add(lineage_root_candidate_id)
    evidence_classes = sorted(
        {
            report_class
            for lineage_candidate_id in lineage_candidates
            if (report := load_latest_mt5_parity_report(lineage_candidate_id, settings)) is not None
            and not report.diagnostic_only
            and (report_class := _parity_class_from_report(report, settings)) is not None
        }
    )
    if len(evidence_classes) > 1:
        raise ParityPolicyError(
            f"parity_policy_evidence_conflict:lineage_root={lineage_root_candidate_id}:classes={','.join(evidence_classes)}"
        )
    locked_class = evidence_classes[0] if evidence_classes else None
    effective_class = configured_class or locked_class

    if enforce_official:
        if effective_class is None:
            raise ParityPolicyError(f"parity_policy_unset:lineage_root={lineage_root_candidate_id}")
        if locked_class is not None and effective_class != locked_class:
            raise ParityPolicyError(
                "parity_policy_switch_blocked:"
                f"lineage_root={lineage_root_candidate_id}:locked_class={locked_class}:requested_class={effective_class}"
            )
        if effective_class != "m1_official":
            raise ParityPolicyError(
                f"parity_policy_blocked:lineage_root={lineage_root_candidate_id}:parity_class={effective_class}"
            )

    return {
        "lineage_root_candidate_id": lineage_root_candidate_id,
        "parity_class": effective_class,
        "lane_ids": lane_ids,
        "policy_snapshot_hash": policy_snapshot_hash(settings),
    }


def _trial_lineage_maps(settings: Settings) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    parent_map: dict[str, set[str]] = {}
    child_map: dict[str, set[str]] = {}
    ledger_path = settings.paths().experiments_dir / "trial_ledger.jsonl"
    if not ledger_path.exists():
        return parent_map, child_map
    for payload in _read_jsonl(ledger_path):
        candidate_id = str(payload.get("candidate_id") or "").strip()
        if not candidate_id:
            continue
        parents = {
            str(parent_id).strip()
            for parent_id in (payload.get("parent_candidate_ids") or [])
            if str(parent_id).strip()
        }
        parents.discard(candidate_id)
        if not parents:
            continue
        parent_map.setdefault(candidate_id, set()).update(parents)
        for parent_id in parents:
            child_map.setdefault(parent_id, set()).add(candidate_id)
    return parent_map, child_map


def _candidate_ancestor_depths(candidate_id: str, parent_map: dict[str, set[str]]) -> dict[str, int]:
    depths: dict[str, int] = {candidate_id: 0}
    stack: list[tuple[str, int, frozenset[str]]] = [(candidate_id, 0, frozenset({candidate_id}))]
    while stack:
        current_candidate_id, depth, path = stack.pop()
        for parent_candidate_id in parent_map.get(current_candidate_id, set()):
            if parent_candidate_id in path:
                continue
            next_depth = depth + 1
            if next_depth <= depths.get(parent_candidate_id, -1):
                continue
            depths[parent_candidate_id] = next_depth
            stack.append((parent_candidate_id, next_depth, path | {parent_candidate_id}))
    return depths


def _candidate_descendants(candidate_id: str, child_map: dict[str, set[str]]) -> set[str]:
    descendants: set[str] = set()
    stack = list(child_map.get(candidate_id, set()))
    while stack:
        current_candidate_id = stack.pop()
        if current_candidate_id == candidate_id or current_candidate_id in descendants:
            continue
        descendants.add(current_candidate_id)
        stack.extend(child_map.get(current_candidate_id, set()))
    return descendants


def _parity_class_from_report(report: MT5ParityReport, settings: Settings) -> str | None:
    if report.diagnostic_only:
        return None
    if report.certification_status != "deployment_grade":
        return None
    if report.parity_class:
        return report.parity_class
    official_tester_mode = settings.mt5_env.parity_tester_mode or "1 minute OHLC"
    if report.tester_mode == official_tester_mode:
        return "m1_official"
    return None


def _build_mt5_certification_report(
    settings: Settings,
    *,
    strategy_spec: StrategySpec,
    run_spec: MT5RunSpec,
    run_result: MT5RunResult,
    validation_report: MT5ValidationReport | None,
    baseline_reproduction_passed: bool,
    deployment_target: bool,
    basis: str,
    notes: list[str] | None = None,
) -> MT5CertificationReport:
    tick_provenance = _tick_provenance_from_tester_mode(run_spec.tester_mode)
    login, broker_server = _configured_mt5_account(_run_spec_terminal_data_path(run_spec, settings))
    certification_notes = list(notes or [])
    if deployment_target:
        certification_notes.append("Official parity authority is granted only through deployment-grade MT5 certification.")
    if tick_provenance == "unknown":
        certification_notes.append("Tick provenance could not be derived from the configured tester mode.")
    certification_status = _resolve_mt5_certification_status(
        diagnostic_only=run_spec.diagnostic_only,
        deployment_target=deployment_target,
        launch_status=run_result.launch_status,
        validation_status=validation_report.validation_status if validation_report else None,
        baseline_reproduction_passed=baseline_reproduction_passed,
    )
    certification = ValidationCertification(
        artifact_id=f"goblin-mt5-certification-{run_spec.candidate_id}-{run_spec.run_id}",
        status=certification_status,
        basis=basis,
        notes=certification_notes,
    )
    report = MT5CertificationReport(
        candidate_id=run_spec.candidate_id,
        run_id=run_spec.run_id,
        diagnostic_only=run_spec.diagnostic_only,
        tester_mode=run_spec.tester_mode,
        delay_model=f"configured_fill_delay_ms:{int(strategy_spec.execution_cost_model.fill_delay_ms)}",
        tick_provenance=tick_provenance,  # type: ignore[arg-type]
        symbol_snapshot={
            "instrument": strategy_spec.instrument,
            "execution_granularity": strategy_spec.execution_granularity,
            "tick_mode": run_spec.tick_mode,
            "spread_behavior": run_spec.spread_behavior,
            "tester_from_date": run_spec.tester_from_date,
            "tester_to_date": run_spec.tester_to_date,
        },
        account_snapshot={
            "install_id": run_spec.install_id,
            "login": login,
            "broker_server": broker_server,
            "allow_live_trading": run_spec.allow_live_trading,
        },
        terminal_build=None,
        broker_server_class=_broker_server_class(broker_server),
        baseline_reproduction_passed=baseline_reproduction_passed,
        launch_status=run_result.launch_status,
        validation_status=validation_report.validation_status if validation_report else None,
        parity_rate=validation_report.parity_rate if validation_report else None,
        audit_rows=validation_report.audit_rows if validation_report else None,
        certification=certification,
        notes=certification_notes,
    )
    return write_mt5_certification_report(settings, report=report)


def _resolve_mt5_certification_status(
    *,
    diagnostic_only: bool,
    deployment_target: bool,
    launch_status: str,
    validation_status: str | None,
    baseline_reproduction_passed: bool,
) -> str:
    if launch_status != "completed":
        return "untrusted"
    if validation_status is not None and validation_status != "passed":
        return "untrusted"
    if not baseline_reproduction_passed:
        return "untrusted"
    if diagnostic_only or not deployment_target:
        return "research_only"
    return "deployment_grade"


def _tick_provenance_from_tester_mode(tester_mode: str | None) -> str:
    normalized = (tester_mode or "").strip().lower()
    if not normalized:
        return "unknown"
    if "real ticks" in normalized:
        return "real_ticks"
    if "1 minute ohlc" in normalized or "open prices" in normalized or normalized == "every tick":
        return "generated_ticks"
    return "unknown"


def _broker_server_class(broker_server: str | None) -> str | None:
    if broker_server is None:
        return None
    normalized = broker_server.strip().lower()
    if "practice" in normalized or "demo" in normalized:
        return "practice"
    if "live" in normalized or "real" in normalized:
        return "live"
    if "oanda" in normalized:
        return "oanda"
    return broker_server.strip()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _stage_diagnostic_tick_windows(
    candidate_id: str,
    settings: Settings,
    *,
    run_spec: MT5RunSpec,
) -> int:
    if run_spec.diagnostic_windows_output_path is None:
        return 0
    if run_spec.diagnostic_windows_output_path.exists():
        run_spec.diagnostic_windows_output_path.unlink()
    payload = _latest_parity_diagnostics_payload(candidate_id, settings)
    if not payload:
        return 0
    top_breaches = payload.get("top_breaches") or []
    if not top_breaches:
        return 0
    try:
        broker_timezone = ZoneInfo(settings.policy.ftmo_timezone)
    except ZoneInfoNotFoundError:
        broker_timezone = ZoneInfo("UTC")
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, breach in enumerate(top_breaches[:8], start=1):
        expected_exit = _parse_optional_utc(breach.get("expected_exit_timestamp_utc"))
        actual_exit = _parse_optional_utc(breach.get("actual_exit_timestamp_utc"))
        timestamps = [value for value in (expected_exit, actual_exit) if value is not None]
        if not timestamps:
            continue
        window_start_utc = min(timestamps) - timedelta(minutes=2)
        window_end_utc = max(timestamps) + timedelta(minutes=2)
        key = (
            window_start_utc.isoformat(),
            window_end_utc.isoformat(),
            str(breach.get("likely_cause", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "window_id": f"breach-{index:02d}",
                "start_broker": window_start_utc.astimezone(broker_timezone).strftime("%Y.%m.%d %H:%M:%S"),
                "end_broker": window_end_utc.astimezone(broker_timezone).strftime("%Y.%m.%d %H:%M:%S"),
                "side": str(breach.get("side", "")),
                "expected_exit_reason": str(breach.get("expected_exit_reason", "")),
                "actual_exit_reason": str(breach.get("actual_exit_reason", "")),
                "expected_exit_utc": breach.get("expected_exit_timestamp_utc") or "",
                "actual_exit_utc": breach.get("actual_exit_timestamp_utc") or "",
                "likely_cause": str(breach.get("likely_cause", "")),
                "expected_stop_loss_price": str(breach.get("expected_stop_loss_price", "")),
                "actual_stop_loss_price": str(breach.get("actual_stop_loss_price", "")),
                "expected_take_profit_price": str(breach.get("expected_take_profit_price", "")),
                "actual_take_profit_price": str(breach.get("actual_take_profit_price", "")),
            }
        )
    if not rows:
        return 0
    frame = pd.DataFrame.from_records(rows)
    frame.to_csv(run_spec.run_dir / "diagnostic_tick_windows.csv", index=False)
    run_spec.diagnostic_windows_output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(run_spec.diagnostic_windows_output_path, index=False)
    return int(len(rows))


def _latest_parity_diagnostics_payload(candidate_id: str, settings: Settings) -> dict[str, Any] | None:
    root = settings.paths().mt5_runs_dir / candidate_id
    if not root.exists():
        return None
    for run_dir in sorted((path for path in root.iterdir() if path.is_dir()), reverse=True):
        diagnostics_path = run_dir / "parity_diagnostics.json"
        if diagnostics_path.exists():
            return read_json(diagnostics_path)
    return None


def _parse_optional_utc(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _write_diagnostic_tick_analysis(
    *,
    candidate_id: str,
    run_id: str,
    diagnostics_report_path: Path | None,
    diagnostic_windows_path: Path | None,
    diagnostic_ticks_csv_path: Path | None,
    destination_dir: Path,
) -> Path | None:
    if diagnostic_windows_path is None or diagnostic_ticks_csv_path is None:
        return None
    if not diagnostic_windows_path.exists() or not diagnostic_ticks_csv_path.exists():
        return None
    window_frame = _load_diagnostic_windows_frame(diagnostic_windows_path)
    if window_frame.empty:
        return None
    tick_frame = _load_diagnostic_ticks_frame(diagnostic_ticks_csv_path)
    if tick_frame.empty:
        return None

    analyses: list[dict[str, Any]] = []
    for window_row in window_frame.to_dict(orient="records"):
        window_id = str(window_row.get("window_id", "")).strip()
        if not window_id:
            continue
        window_ticks = tick_frame.loc[tick_frame["window_id"] == window_id].copy()
        analyses.append(_analyze_diagnostic_tick_window(window_id, window_row, window_ticks))

    analysis_payload = {
        "candidate_id": candidate_id,
        "run_id": run_id,
        "diagnostic_ticks_csv_path": str(diagnostic_ticks_csv_path),
        "diagnostics_report_path": str(diagnostics_report_path) if diagnostics_report_path else None,
        "diagnostic_windows_path": str(diagnostic_windows_path),
        "window_analyses": analyses,
    }
    analysis_path = destination_dir / "diagnostic_tick_analysis.json"
    write_json(analysis_path, analysis_payload)
    return analysis_path


def _load_diagnostic_windows_frame(path: Path) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path, low_memory=False)
    except EmptyDataError:
        return pd.DataFrame()
    if frame.empty:
        return pd.DataFrame()
    required = {"window_id", "side", "expected_exit_reason", "actual_exit_reason", "expected_exit_utc", "actual_exit_utc"}
    if not required.issubset(set(frame.columns)):
        return pd.DataFrame()
    normalized = frame.copy()
    for column in (
        "window_id",
        "side",
        "expected_exit_reason",
        "actual_exit_reason",
        "expected_exit_utc",
        "actual_exit_utc",
        "likely_cause",
    ):
        if column not in normalized.columns:
            normalized[column] = ""
        normalized[column] = normalized[column].astype(str)
    for column in (
        "expected_stop_loss_price",
        "actual_stop_loss_price",
        "expected_take_profit_price",
        "actual_take_profit_price",
    ):
        if column not in normalized.columns:
            normalized[column] = ""
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    return normalized


def _load_diagnostic_ticks_frame(path: Path) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path, low_memory=False)
    except EmptyDataError:
        return pd.DataFrame()
    if frame.empty:
        return pd.DataFrame()
    required = {"window_id", "timestamp_utc", "bid", "ask"}
    if not required.issubset(set(frame.columns)):
        return pd.DataFrame()
    normalized = frame.copy()
    normalized["timestamp_utc"] = pd.to_datetime(normalized["timestamp_utc"], utc=True, errors="coerce")
    for column in ("bid", "ask", "last", "volume", "flags"):
        if column not in normalized.columns:
            normalized[column] = 0.0
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce").fillna(0.0)
    for column in ("expected_exit_utc", "actual_exit_utc"):
        if column not in normalized.columns:
            normalized[column] = ""
        normalized[column] = normalized[column].astype(str)
    if "likely_cause" not in normalized.columns:
        normalized["likely_cause"] = ""
    normalized["likely_cause"] = normalized["likely_cause"].astype(str)
    return normalized.dropna(subset=["timestamp_utc"]).reset_index(drop=True)


def _analyze_diagnostic_tick_window(window_id: str, breach: dict[str, Any], window_ticks: pd.DataFrame) -> dict[str, Any]:
    expected_exit_utc = _parse_optional_utc(breach.get("expected_exit_utc"))
    actual_exit_utc = _parse_optional_utc(breach.get("actual_exit_utc"))
    expected_stop = _optional_float(breach.get("expected_stop_loss_price"))
    expected_target = _optional_float(breach.get("expected_take_profit_price"))
    actual_stop = _optional_float(breach.get("actual_stop_loss_price"))
    actual_target = _optional_float(breach.get("actual_take_profit_price"))
    side = str(breach.get("side", "")).strip().lower()

    expected_stop_hit = _first_level_hit(window_ticks, side=side, level=expected_stop, event="stop_loss")
    expected_target_hit = _first_level_hit(window_ticks, side=side, level=expected_target, event="take_profit")
    actual_stop_hit = _first_level_hit(window_ticks, side=side, level=actual_stop, event="stop_loss")
    actual_target_hit = _first_level_hit(window_ticks, side=side, level=actual_target, event="take_profit")

    return {
        "window_id": window_id,
        "likely_cause": str(breach.get("likely_cause", "")),
        "side": side,
        "tick_count": int(len(window_ticks)),
        "window_start_utc": _format_optional_timestamp(window_ticks["timestamp_utc"].min()) if not window_ticks.empty else None,
        "window_end_utc": _format_optional_timestamp(window_ticks["timestamp_utc"].max()) if not window_ticks.empty else None,
        "expected_exit_reason": str(breach.get("expected_exit_reason", "")),
        "actual_exit_reason": str(breach.get("actual_exit_reason", "")),
        "expected_exit_timestamp_utc": _format_optional_timestamp(expected_exit_utc),
        "actual_exit_timestamp_utc": _format_optional_timestamp(actual_exit_utc),
        "expected_stop_hit_utc": _format_optional_timestamp(expected_stop_hit),
        "expected_target_hit_utc": _format_optional_timestamp(expected_target_hit),
        "actual_stop_hit_utc": _format_optional_timestamp(actual_stop_hit),
        "actual_target_hit_utc": _format_optional_timestamp(actual_target_hit),
        "supports_expected_exit_reason": _supports_exit_reason(
            str(breach.get("expected_exit_reason", "")),
            expected_exit_utc,
            stop_hit=expected_stop_hit,
            target_hit=expected_target_hit,
        ),
        "supports_actual_exit_reason": _supports_exit_reason(
            str(breach.get("actual_exit_reason", "")),
            actual_exit_utc,
            stop_hit=actual_stop_hit,
            target_hit=actual_target_hit,
        ),
    }


def _optional_float(raw: Any) -> float | None:
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _first_level_hit(
    window_ticks: pd.DataFrame,
    *,
    side: str,
    level: float | None,
    event: str,
) -> datetime | None:
    if level is None or window_ticks.empty:
        return None
    if side == "long":
        if event == "stop_loss":
            hits = window_ticks.loc[window_ticks["bid"] <= level]
        else:
            hits = window_ticks.loc[window_ticks["bid"] >= level]
    elif side == "short":
        if event == "stop_loss":
            hits = window_ticks.loc[window_ticks["ask"] >= level]
        else:
            hits = window_ticks.loc[window_ticks["ask"] <= level]
    else:
        return None
    if hits.empty:
        return None
    return pd.Timestamp(hits.iloc[0]["timestamp_utc"]).to_pydatetime().astimezone(UTC)


def _supports_exit_reason(
    exit_reason: str,
    exit_timestamp_utc: datetime | None,
    *,
    stop_hit: datetime | None,
    target_hit: datetime | None,
) -> bool | None:
    normalized = exit_reason.strip().lower()
    if normalized == "stop_loss":
        return stop_hit is not None and (target_hit is None or stop_hit <= target_hit)
    if normalized == "take_profit":
        return target_hit is not None and (stop_hit is None or target_hit <= stop_hit)
    if normalized == "timeout":
        if exit_timestamp_utc is None:
            return None
        earliest_hit = min((value for value in (stop_hit, target_hit) if value is not None), default=None)
        return earliest_hit is None or earliest_hit > exit_timestamp_utc
    return None


def _parity_run_spec_from_packet(
    packet: MT5Packet,
    settings: Settings,
    run_dir: Path,
    run_id: str,
    *,
    tester_mode_override: str | None = None,
    diagnostic_only: bool = False,
) -> MT5RunSpec:
    packet_spec = MT5RunSpec.model_validate(read_json(packet.run_spec_path))
    resolved_terminal_path = Path(packet_spec.terminal_path) if packet_spec.terminal_path else _resolve_terminal_path(settings)
    resolved_terminal_data_path = packet.terminal_data_path or _resolve_terminal_data_path(settings, resolved_terminal_path)
    terminal_path, terminal_data_path, _ = _prepare_automated_terminal_runtime(
        settings,
        terminal_path=resolved_terminal_path,
        terminal_data_path=resolved_terminal_data_path,
    )
    staged_source_path, _ = _stage_existing_build_for_launch(
        source_path=packet.deployed_source_path or packet.ea_source_path,
        compiled_ex5_path=packet.compiled_ex5_path,
        compile_target_relative_path=_candidate_compile_target_relative_path(packet.candidate_id, settings),
        terminal_data_path=terminal_data_path,
    )
    diagnostic_windows_relative_path = _diagnostic_windows_relative_path(packet.candidate_id, settings)
    diagnostic_ticks_relative_path = _diagnostic_ticks_relative_path(packet.candidate_id, settings)
    runtime_summary_relative_path = _run_scoped_runtime_summary_relative_path(packet.candidate_id, run_id, settings)
    signal_trace_relative_path = _run_scoped_signal_trace_relative_path(packet.candidate_id, run_id, settings)
    return MT5RunSpec(
        candidate_id=packet.candidate_id,
        run_id=run_id,
        install_id=packet_spec.install_id,
        diagnostic_only=diagnostic_only,
        terminal_path=str(terminal_path) if terminal_path else packet_spec.terminal_path,
        portable_mode=bool(terminal_path and terminal_data_path and terminal_path.parent == terminal_data_path),
        tester_mode=tester_mode_override or settings.mt5_env.parity_tester_mode or packet_spec.tester_mode,
        tick_mode=tester_mode_override or settings.mt5_env.parity_tester_mode or packet_spec.tick_mode,
        spread_behavior=packet_spec.spread_behavior,
        allow_live_trading=packet_spec.allow_live_trading,
        shutdown_terminal=packet_spec.shutdown_terminal,
        config_path=run_dir / "tester_config.ini",
        report_path=run_dir / "tester_report.htm",
        compile_target_path=staged_source_path,
        compile_request_path=packet_spec.compile_request_path,
        launch_request_path=run_dir / "launch_request.json",
        run_dir=run_dir,
        audit_relative_path=packet.audit_relative_path,
        audit_output_path=(
            _resolve_audit_output_path(settings, terminal_data_path, packet.audit_relative_path)
            if packet.audit_relative_path
            else packet.audit_output_path
        ),
        broker_history_relative_path=_broker_history_relative_path(packet.candidate_id, settings),
        broker_history_output_path=_resolve_broker_history_output_path(
            settings,
            terminal_data_path,
            _broker_history_relative_path(packet.candidate_id, settings),
        ),
        diagnostic_windows_relative_path=diagnostic_windows_relative_path,
        diagnostic_windows_output_path=_resolve_diagnostic_windows_output_path(
            settings,
            terminal_data_path,
            diagnostic_windows_relative_path,
        ),
        diagnostic_ticks_relative_path=diagnostic_ticks_relative_path,
        diagnostic_ticks_output_path=_resolve_diagnostic_ticks_output_path(
            settings,
            terminal_data_path,
            diagnostic_ticks_relative_path,
        ),
        runtime_summary_relative_path=runtime_summary_relative_path,
        runtime_summary_output_path=_resolve_runtime_summary_output_path(
            settings,
            terminal_data_path,
            runtime_summary_relative_path,
        ),
        signal_trace_relative_path=signal_trace_relative_path,
        signal_trace_output_path=_resolve_signal_trace_output_path(
            settings,
            terminal_data_path,
            signal_trace_relative_path,
        ),
        tester_inputs_profile_path=_tester_inputs_profile_path(terminal_data_path, packet.candidate_id, run_id),
        tester_timeout_seconds=settings.mt5_env.parity_launch_timeout_seconds,
        logic_manifest_hash=packet.logic_manifest_hash,
    )


def _manual_run_spec_from_packet(
    packet: MT5Packet,
    settings: Settings,
    run_dir: Path,
    run_id: str,
    *,
    spec: StrategySpec,
    tester_mode_override: str | None = None,
) -> MT5RunSpec:
    packet_spec = MT5RunSpec.model_validate(read_json(packet.run_spec_path))
    base_terminal_path = _resolve_terminal_path(settings)
    base_terminal_data_path = _resolve_terminal_data_path(settings, base_terminal_path)
    base_metaeditor_path = _resolve_metaeditor_path(base_terminal_path)
    resolved_terminal_path = Path(packet_spec.terminal_path) if packet_spec.terminal_path else _resolve_terminal_path(settings)
    resolved_terminal_data_path = packet.terminal_data_path or _resolve_terminal_data_path(settings, resolved_terminal_path)
    terminal_path, terminal_data_path, metaeditor_path = _prepare_automated_terminal_runtime(
        settings,
        terminal_path=resolved_terminal_path,
        terminal_data_path=resolved_terminal_data_path,
    )
    audit_relative_path = _audit_relative_path(packet.candidate_id, run_id, settings)
    broker_history_relative_path = _run_scoped_broker_history_relative_path(packet.candidate_id, run_id, settings)
    diagnostic_windows_relative_path = _run_scoped_diagnostic_windows_relative_path(packet.candidate_id, run_id, settings)
    diagnostic_ticks_relative_path = _run_scoped_diagnostic_ticks_relative_path(packet.candidate_id, run_id, settings)
    runtime_summary_relative_path = _run_scoped_runtime_summary_relative_path(packet.candidate_id, run_id, settings)
    signal_trace_relative_path = _run_scoped_signal_trace_relative_path(packet.candidate_id, run_id, settings)
    rendered_source = render_candidate_ea(
        spec,
        audit_relative_path=audit_relative_path,
        broker_history_relative_path=broker_history_relative_path,
        diagnostic_windows_relative_path=diagnostic_windows_relative_path,
        diagnostic_ticks_relative_path=diagnostic_ticks_relative_path,
        runtime_summary_relative_path=runtime_summary_relative_path,
        signal_trace_relative_path=signal_trace_relative_path,
        packet_run_id=run_id,
        broker_timezone=settings.policy.ftmo_timezone,
    )
    manual_source_path = run_dir / "CandidateEA.mq5"
    manual_source_path.write_text(rendered_source, encoding="utf-8")
    compile_target_relative_path = _manual_compile_target_relative_path(packet.candidate_id, run_id, settings)
    if terminal_data_path is None or metaeditor_path is None:
        raise RuntimeError("Manual MT5 run requires an available MT5 automation runtime with MetaEditor.")
    try:
        deployed_source_path, compiled_ex5_path, compile_log_path = _deploy_and_compile_ea(
            candidate_id=packet.candidate_id,
            packet_source_path=manual_source_path,
            compile_target_relative_path=compile_target_relative_path,
            terminal_data_path=terminal_data_path,
            metaeditor_path=metaeditor_path,
            packet_dir=run_dir,
        )
    except RuntimeError:
        if (
            base_terminal_data_path is None
            or base_metaeditor_path is None
            or base_terminal_data_path == terminal_data_path
        ):
            raise
        base_source_path, base_ex5_path, compile_log_path = _deploy_and_compile_ea(
            candidate_id=packet.candidate_id,
            packet_source_path=manual_source_path,
            compile_target_relative_path=compile_target_relative_path,
            terminal_data_path=base_terminal_data_path,
            metaeditor_path=base_metaeditor_path,
            packet_dir=run_dir,
        )
        deployed_source_path, compiled_ex5_path = _stage_existing_build_for_launch(
            source_path=base_source_path,
            compiled_ex5_path=base_ex5_path,
            compile_target_relative_path=compile_target_relative_path,
            terminal_data_path=terminal_data_path,
        )
    write_json(
        run_dir / "compile_request.json",
        {
            "candidate_id": packet.candidate_id,
            "run_id": run_id,
            "manual_run": True,
            "compile_target_path": str(deployed_source_path),
            "packet_source_path": str(manual_source_path),
            "compiled_ex5_path": str(compiled_ex5_path) if compiled_ex5_path else None,
            "compile_log_path": str(compile_log_path) if compile_log_path else None,
            "terminal_data_path": str(terminal_data_path),
            "metaeditor_path": str(metaeditor_path),
        },
    )
    resolved_tester_mode = tester_mode_override or packet_spec.tester_mode or settings.mt5_env.tester_mode
    return MT5RunSpec(
        candidate_id=packet.candidate_id,
        run_id=run_id,
        install_id=packet_spec.install_id,
        diagnostic_only=False,
        terminal_path=str(terminal_path) if terminal_path else packet_spec.terminal_path,
        portable_mode=bool(terminal_path and terminal_data_path and terminal_path.parent == terminal_data_path),
        tester_mode=resolved_tester_mode,
        tick_mode=resolved_tester_mode,
        spread_behavior=packet_spec.spread_behavior,
        allow_live_trading=packet_spec.allow_live_trading,
        shutdown_terminal=packet_spec.shutdown_terminal,
        config_path=run_dir / "tester_config.ini",
        report_path=run_dir / "tester_report.htm",
        compile_target_path=deployed_source_path,
        compile_request_path=run_dir / "compile_request.json",
        launch_request_path=run_dir / "launch_request.json",
        run_dir=run_dir,
        audit_relative_path=audit_relative_path,
        audit_output_path=_resolve_audit_output_path(settings, terminal_data_path, audit_relative_path),
        broker_history_relative_path=broker_history_relative_path,
        broker_history_output_path=_resolve_broker_history_output_path(
            settings,
            terminal_data_path,
            broker_history_relative_path,
        ),
        diagnostic_windows_relative_path=diagnostic_windows_relative_path,
        diagnostic_windows_output_path=_resolve_diagnostic_windows_output_path(
            settings,
            terminal_data_path,
            diagnostic_windows_relative_path,
        ),
        diagnostic_ticks_relative_path=diagnostic_ticks_relative_path,
        diagnostic_ticks_output_path=_resolve_diagnostic_ticks_output_path(
            settings,
            terminal_data_path,
            diagnostic_ticks_relative_path,
        ),
        runtime_summary_relative_path=runtime_summary_relative_path,
        runtime_summary_output_path=_resolve_runtime_summary_output_path(
            settings,
            terminal_data_path,
            runtime_summary_relative_path,
        ),
        signal_trace_relative_path=signal_trace_relative_path,
        signal_trace_output_path=_resolve_signal_trace_output_path(
            settings,
            terminal_data_path,
            signal_trace_relative_path,
        ),
        tester_inputs_profile_path=_tester_inputs_profile_path(terminal_data_path, packet.candidate_id, run_id),
        tester_timeout_seconds=settings.mt5_env.parity_launch_timeout_seconds,
        logic_manifest_hash=packet.logic_manifest_hash,
    )


def _load_expected_signal_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=EXPECTED_SIGNAL_COLUMNS)
    try:
        frame = pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame(columns=EXPECTED_SIGNAL_COLUMNS)
    return _normalize_expected_frame(frame)


def _expected_signal_frame(settings: Settings, report_dir: Path, candidate_id: str, spec: StrategySpec) -> pd.DataFrame:
    executable = _executable_expected_signal_frame(settings, spec, candidate_id)
    if not executable.empty:
        return executable
    return _trade_ledger_expected_signal_frame(report_dir, candidate_id)


def _broker_history_expected_signal_frame(
    settings: Settings,
    spec: StrategySpec,
    candidate_id: str,
    broker_history_csv: Path,
) -> pd.DataFrame:
    broker_history = _load_broker_history_frame(broker_history_csv)
    if broker_history.empty:
        return pd.DataFrame(columns=EXPECTED_SIGNAL_COLUMNS)
    return _executable_expected_signal_frame_from_market_frame(broker_history, spec, candidate_id)


def _signal_trace_expected_signal_frame(
    *,
    settings: Settings,
    spec: StrategySpec,
    candidate_id: str,
    broker_history_csv: Path,
    signal_trace_csv: Path,
) -> pd.DataFrame:
    broker_history = _load_broker_history_frame(broker_history_csv)
    signal_trace = _load_signal_trace_frame(signal_trace_csv)
    if broker_history.empty or signal_trace.empty:
        return pd.DataFrame(columns=EXPECTED_SIGNAL_COLUMNS)
    timestamp_to_index = {
        pd.Timestamp(timestamp): int(index)
        for index, timestamp in broker_history["timestamp_utc"].items()
    }
    pip_scale = _pip_scale(spec.instrument)
    rows: list[dict[str, Any]] = []
    for signal_row in signal_trace.to_dict(orient="records"):
        timestamp = pd.Timestamp(signal_row["timestamp_utc"])
        entry_index = timestamp_to_index.get(timestamp)
        if entry_index is None:
            continue
        signal_value = int(signal_row["signal"])
        if signal_value == 0:
            continue
        history_row = broker_history.iloc[entry_index]
        entry_price = float(history_row["ask_o"] if signal_value > 0 else history_row["bid_o"])
        exit_result = _resolve_executable_exit(broker_history, entry_index, signal_value, entry_price, spec, pip_scale)
        if exit_result is None:
            continue
        exit_timestamp = broker_history.iloc[int(exit_result["exit_index"])] ["timestamp_utc"]
        exit_price = float(exit_result["exit_price"])
        pnl_pips = (
            (exit_price - entry_price) * pip_scale
            if signal_value > 0
            else (entry_price - exit_price) * pip_scale
        )
        rows.append(
            {
                "timestamp_utc": timestamp,
                "exit_timestamp_utc": exit_timestamp,
                "side": "long" if signal_value > 0 else "short",
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl_pips": pnl_pips,
                "candidate_id": candidate_id,
                "exit_reason": str(exit_result["exit_reason"]),
                "stop_loss_price": float(exit_result["stop_loss_price"]),
                "take_profit_price": float(exit_result["take_profit_price"]),
                "same_bar_collision": bool(exit_result["same_bar_collision"]),
                "collision_resolution": str(exit_result["collision_resolution"]),
            }
        )
    if not rows:
        return pd.DataFrame(columns=EXPECTED_SIGNAL_COLUMNS)
    return _normalize_expected_frame(pd.DataFrame.from_records(rows, columns=EXPECTED_SIGNAL_COLUMNS))


def _trade_ledger_expected_signal_frame(report_dir: Path, candidate_id: str) -> pd.DataFrame:
    trade_ledger_path = report_dir / "trade_ledger.csv"
    if not trade_ledger_path.exists():
        return pd.DataFrame(columns=EXPECTED_SIGNAL_COLUMNS)
    try:
        trade_ledger = pd.read_csv(trade_ledger_path)
    except EmptyDataError:
        return pd.DataFrame(columns=EXPECTED_SIGNAL_COLUMNS)
    if trade_ledger.empty:
        return pd.DataFrame(columns=EXPECTED_SIGNAL_COLUMNS)
    expected = trade_ledger.copy()
    expected["candidate_id"] = candidate_id
    for column in EXPECTED_SIGNAL_COLUMNS:
        if column not in expected.columns:
            if column in {"timestamp_utc", "exit_timestamp_utc", "side", "candidate_id", "exit_reason", "collision_resolution"}:
                expected[column] = ""
            elif column == "same_bar_collision":
                expected[column] = False
            else:
                expected[column] = 0.0
    return _normalize_expected_frame(expected[EXPECTED_SIGNAL_COLUMNS])


def _executable_expected_signal_frame(settings: Settings, spec: StrategySpec, candidate_id: str) -> pd.DataFrame:
    parquet_path = settings.paths().normalized_research_dir / f"{spec.instrument.lower()}_{spec.execution_granularity.lower()}.parquet"
    if not parquet_path.exists():
        return pd.DataFrame(columns=EXPECTED_SIGNAL_COLUMNS)
    raw = pd.read_parquet(parquet_path)
    return _executable_expected_signal_frame_from_market_frame(raw, spec, candidate_id)


def _executable_expected_signal_frame_from_market_frame(
    raw: pd.DataFrame,
    spec: StrategySpec,
    candidate_id: str,
) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame(columns=EXPECTED_SIGNAL_COLUMNS)
    required_columns = {
        "timestamp_utc",
        "bid_o",
        "bid_h",
        "bid_l",
        "ask_o",
        "ask_h",
        "ask_l",
        "spread_pips",
    }
    if not required_columns.issubset(set(raw.columns)):
        return pd.DataFrame(columns=EXPECTED_SIGNAL_COLUMNS)
    market_frame = _build_executable_market_frame(raw, spec)
    features = build_features(market_frame).reset_index(drop=True)
    if features.empty or len(features) <= spec.holding_bars + 21:
        return pd.DataFrame(columns=EXPECTED_SIGNAL_COLUMNS)

    pip_scale = _pip_scale(spec.instrument)
    next_available_index = 21
    expected_rows: list[dict[str, Any]] = []

    for index in range(21, len(features) - spec.holding_bars - 1):
        if index < next_available_index:
            continue

        entry_row = features.iloc[index]
        signal_row = features.iloc[index - 1]

        if spec.session_policy.allowed_hours_utc and int(entry_row["hour"]) not in spec.session_policy.allowed_hours_utc:
            continue
        if float(entry_row["spread_pips"]) > spec.risk_envelope.max_spread_allowed_pips:
            continue

        signal = _generate_signal(signal_row, spec)
        if signal == 0:
            continue

        entry_price = float(entry_row["ask_o"] if signal > 0 else entry_row["bid_o"])
        exit_result = _resolve_executable_exit(features, index, signal, entry_price, spec, pip_scale)
        if exit_result is None:
            continue

        expected_rows.append(
            {
                "timestamp_utc": entry_row["timestamp_utc"],
                "exit_timestamp_utc": features.iloc[int(exit_result["exit_index"])]["timestamp_utc"],
                "side": "long" if signal > 0 else "short",
                "entry_price": entry_price,
                "exit_price": float(exit_result["exit_price"]),
                "pnl_pips": (
                    (float(exit_result["exit_price"]) - entry_price) * pip_scale
                    if signal > 0
                    else (entry_price - float(exit_result["exit_price"])) * pip_scale
                ),
                "candidate_id": candidate_id,
                "exit_reason": str(exit_result["exit_reason"]),
                "stop_loss_price": float(exit_result["stop_loss_price"]),
                "take_profit_price": float(exit_result["take_profit_price"]),
                "same_bar_collision": bool(exit_result["same_bar_collision"]),
                "collision_resolution": str(exit_result["collision_resolution"]),
            }
        )
        if spec.risk_policy.max_open_positions <= 1:
            next_available_index = int(exit_result["exit_index"]) + 1

    if not expected_rows:
        return pd.DataFrame(columns=EXPECTED_SIGNAL_COLUMNS)
    return _normalize_expected_frame(pd.DataFrame.from_records(expected_rows, columns=EXPECTED_SIGNAL_COLUMNS))


def _load_broker_history_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=BROKER_HISTORY_COLUMNS)
    try:
        frame = pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame(columns=BROKER_HISTORY_COLUMNS)
    return _normalize_broker_history_frame(frame)


def _normalize_broker_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "timestamp_utc",
        "bid_o",
        "bid_h",
        "bid_l",
        "bid_c",
        "ask_o",
        "ask_h",
        "ask_l",
        "ask_c",
        "spread_pips",
    }
    if not required.issubset(set(frame.columns)):
        return pd.DataFrame(columns=BROKER_HISTORY_COLUMNS)
    normalized = frame.copy()
    normalized["timestamp_utc"] = pd.to_datetime(normalized["timestamp_utc"], utc=True, errors="coerce")
    for column in (
        "bid_o",
        "bid_h",
        "bid_l",
        "bid_c",
        "ask_o",
        "ask_h",
        "ask_l",
        "ask_c",
        "spread_pips",
        "volume",
    ):
        if column not in normalized.columns:
            normalized[column] = 0.0
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce").fillna(0.0)
    normalized = _ensure_market_mid_columns(normalized)
    normalized = normalized.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc").drop_duplicates(
        subset=["timestamp_utc"],
        keep="last",
    )
    return normalized.reset_index(drop=True)


def _load_signal_trace_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["timestamp_utc", "signal", "spread_pips", "bars_processed"])
    try:
        frame = pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame(columns=["timestamp_utc", "signal", "spread_pips", "bars_processed"])
    if frame.empty or not {"timestamp_utc", "signal"}.issubset(set(frame.columns)):
        return pd.DataFrame(columns=["timestamp_utc", "signal", "spread_pips", "bars_processed"])
    normalized = frame.copy()
    normalized["timestamp_utc"] = pd.to_datetime(normalized["timestamp_utc"], utc=True, errors="coerce")
    normalized["signal"] = pd.to_numeric(normalized["signal"], errors="coerce").fillna(0).astype(int)
    for column in ("spread_pips", "bars_processed"):
        if column not in normalized.columns:
            normalized[column] = 0.0
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce").fillna(0.0)
    normalized = normalized.dropna(subset=["timestamp_utc"]).sort_values("timestamp_utc").drop_duplicates(
        subset=["timestamp_utc"],
        keep="last",
    )
    return normalized.reset_index(drop=True)


def _ensure_market_mid_columns(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    if "mid_o" not in normalized.columns:
        normalized["mid_o"] = (normalized["bid_o"] + normalized["ask_o"]) / 2.0
    if "mid_h" not in normalized.columns:
        normalized["mid_h"] = (normalized["bid_h"] + normalized["ask_h"]) / 2.0
    if "mid_l" not in normalized.columns:
        normalized["mid_l"] = (normalized["bid_l"] + normalized["ask_l"]) / 2.0
    if "mid_c" not in normalized.columns:
        normalized["mid_c"] = (normalized["bid_c"] + normalized["ask_c"]) / 2.0
    return normalized


def _build_executable_market_frame(frame: pd.DataFrame, spec: StrategySpec) -> pd.DataFrame:
    normalized = frame.copy()
    if {"bid_o", "bid_h", "bid_l", "bid_c", "spread_pips"}.issubset(set(normalized.columns)):
        pip_scale = _pip_scale(spec.instrument)
        spread_price = pd.to_numeric(normalized["spread_pips"], errors="coerce").fillna(0.0) / pip_scale
        half_spread = spread_price / 2.0
        normalized["mid_o"] = pd.to_numeric(normalized["bid_o"], errors="coerce").fillna(0.0) + half_spread
        normalized["mid_h"] = pd.to_numeric(normalized["bid_h"], errors="coerce").fillna(0.0) + half_spread
        normalized["mid_l"] = pd.to_numeric(normalized["bid_l"], errors="coerce").fillna(0.0) + half_spread
        normalized["mid_c"] = pd.to_numeric(normalized["bid_c"], errors="coerce").fillna(0.0) + half_spread
        return normalized
    return _ensure_market_mid_columns(normalized)


def _constrain_expected_frame_to_packet_range(expected: pd.DataFrame, packet_expected: pd.DataFrame) -> pd.DataFrame:
    if expected.empty or packet_expected.empty:
        return expected
    normalized_expected = _normalize_expected_frame(expected)
    normalized_packet = _normalize_expected_frame(packet_expected)
    start = pd.to_datetime(normalized_packet["timestamp_utc"], utc=True, errors="coerce").min()
    exit_series = normalized_packet["exit_timestamp_utc"] if "exit_timestamp_utc" in normalized_packet.columns else None
    if exit_series is not None and exit_series.notna().any():
        stop = pd.to_datetime(exit_series, utc=True, errors="coerce").max()
    else:
        stop = pd.to_datetime(normalized_packet["timestamp_utc"], utc=True, errors="coerce").max()
    constrained = normalized_expected.loc[
        (normalized_expected["timestamp_utc"] >= start)
        & (normalized_expected["timestamp_utc"] <= stop)
    ]
    if "exit_timestamp_utc" in constrained.columns:
        constrained = constrained.loc[
            constrained["exit_timestamp_utc"].isna() | (constrained["exit_timestamp_utc"] <= stop)
        ]
    return constrained.reset_index(drop=True)


def _resolve_executable_exit(
    features: pd.DataFrame,
    entry_index: int,
    signal: int,
    entry_price: float,
    spec: StrategySpec,
    pip_scale: float,
) -> dict[str, Any] | None:
    price_digits = _instrument_digits(spec.instrument)
    stop_distance = spec.stop_loss_pips / pip_scale
    target_distance = spec.take_profit_pips / pip_scale
    normalized_entry_price = round(float(entry_price), price_digits)
    stop_price = round(
        normalized_entry_price - stop_distance if signal > 0 else normalized_entry_price + stop_distance,
        price_digits,
    )
    target_price = round(
        normalized_entry_price + target_distance if signal > 0 else normalized_entry_price - target_distance,
        price_digits,
    )
    final_index = entry_index + spec.holding_bars
    if final_index >= len(features):
        return None

    # Match the EA timeout behavior: once the holding window expires, the position
    # is closed at the opening of the expiry bar before that bar's later path can
    # turn the trade into a stop or target exit.
    for index in range(entry_index, final_index):
        row = features.iloc[index]
        if signal > 0:
            bid_l = round(float(row["bid_l"]), price_digits)
            bid_h = round(float(row["bid_h"]), price_digits)
            bid_o = round(float(row["bid_o"]), price_digits)
            exact_stop = bid_l <= stop_price
            exact_target = bid_h >= target_price
            hit_stop = exact_stop
            hit_target = exact_target
            collision_stop = exact_stop
            collision_target = exact_target
            if hit_stop and hit_target:
                open_price = bid_o
                if abs(open_price - stop_price) <= abs(target_price - open_price):
                    collision_resolution = "stop_loss_nearest_open"
                    hit_target = False
                else:
                    collision_resolution = "take_profit_nearest_open"
                    hit_stop = False
            else:
                collision_resolution = ""
            if hit_stop:
                result = {
                    "exit_index": index,
                    "exit_price": stop_price,
                    "exit_reason": "stop_loss",
                    "stop_loss_price": stop_price,
                    "take_profit_price": target_price,
                    "same_bar_collision": bool(collision_stop and collision_target),
                    "collision_resolution": collision_resolution,
                }
                return result
            if hit_target:
                result = {
                    "exit_index": index,
                    "exit_price": target_price,
                    "exit_reason": "take_profit",
                    "stop_loss_price": stop_price,
                    "take_profit_price": target_price,
                    "same_bar_collision": bool(collision_stop and collision_target),
                    "collision_resolution": collision_resolution,
                }
                return result
        else:
            ask_h = round(float(row["ask_h"]), price_digits)
            ask_l = round(float(row["ask_l"]), price_digits)
            ask_o = round(float(row["ask_o"]), price_digits)
            exact_stop = ask_h >= stop_price
            exact_target = ask_l <= target_price
            hit_stop = exact_stop
            hit_target = exact_target
            collision_stop = exact_stop
            collision_target = exact_target
            if hit_stop and hit_target:
                open_price = ask_o
                if abs(open_price - stop_price) <= abs(target_price - open_price):
                    collision_resolution = "stop_loss_nearest_open"
                    hit_target = False
                else:
                    collision_resolution = "take_profit_nearest_open"
                    hit_stop = False
            else:
                collision_resolution = ""
            if hit_stop:
                result = {
                    "exit_index": index,
                    "exit_price": stop_price,
                    "exit_reason": "stop_loss",
                    "stop_loss_price": stop_price,
                    "take_profit_price": target_price,
                    "same_bar_collision": bool(collision_stop and collision_target),
                    "collision_resolution": collision_resolution,
                }
                return result
            if hit_target:
                result = {
                    "exit_index": index,
                    "exit_price": target_price,
                    "exit_reason": "take_profit",
                    "stop_loss_price": stop_price,
                    "take_profit_price": target_price,
                    "same_bar_collision": bool(collision_stop and collision_target),
                    "collision_resolution": collision_resolution,
                }
                return result

    final_row = features.iloc[final_index]
    exit_price = round(float(final_row["bid_o"] if signal > 0 else final_row["ask_o"]), price_digits)
    return {
        "exit_index": final_index,
        "exit_price": exit_price,
        "exit_reason": "timeout",
        "stop_loss_price": stop_price,
        "take_profit_price": target_price,
        "same_bar_collision": False,
        "collision_resolution": "",
    }


def _normalize_expected_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    normalized["timestamp_utc"] = pd.to_datetime(normalized["timestamp_utc"], utc=True, errors="coerce")
    exit_series = normalized["exit_timestamp_utc"] if "exit_timestamp_utc" in normalized.columns else pd.Series(pd.NaT, index=normalized.index)
    normalized["exit_timestamp_utc"] = pd.to_datetime(exit_series, utc=True, errors="coerce")
    normalized["side"] = normalized["side"].astype(str).str.lower().str.strip()
    for column in ("entry_price", "exit_price", "pnl_pips"):
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce").fillna(0.0)
    normalized["candidate_id"] = normalized["candidate_id"].astype(str)
    if "exit_reason" not in normalized.columns:
        normalized["exit_reason"] = ""
    normalized["exit_reason"] = normalized["exit_reason"].astype(str).str.lower().str.strip()
    for column in ("stop_loss_price", "take_profit_price"):
        if column not in normalized.columns:
            normalized[column] = 0.0
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce").fillna(0.0)
    if "same_bar_collision" not in normalized.columns:
        normalized["same_bar_collision"] = False
    normalized["same_bar_collision"] = normalized["same_bar_collision"].astype(bool)
    if "collision_resolution" not in normalized.columns:
        normalized["collision_resolution"] = ""
    normalized["collision_resolution"] = normalized["collision_resolution"].astype(str).str.lower().str.strip()
    normalized = normalized.dropna(subset=["timestamp_utc"]).reset_index(drop=True)
    return normalized


def _load_audit_frame(path: Path | None) -> pd.DataFrame:
    if path is None or not path.exists():
        return pd.DataFrame(columns=AUDIT_COLUMNS)
    try:
        frame = pd.read_csv(path)
    except EmptyDataError:
        return pd.DataFrame(columns=AUDIT_COLUMNS)
    required_columns = {"timestamp_utc", "side", "entry_price", "exit_price", "pnl_pips"}
    if not required_columns.issubset(set(frame.columns)):
        malformed = pd.DataFrame(columns=AUDIT_COLUMNS)
        malformed.attrs["malformed"] = True
        return malformed
    normalized = frame.copy()
    if "exit_timestamp_utc" not in normalized.columns:
        normalized["exit_timestamp_utc"] = pd.NaT
    normalized["timestamp_utc"] = pd.to_datetime(normalized["timestamp_utc"], utc=True, errors="coerce")
    normalized["exit_timestamp_utc"] = pd.to_datetime(normalized["exit_timestamp_utc"], utc=True, errors="coerce")
    normalized["side"] = normalized["side"].astype(str).str.lower().str.strip()
    for column in ("entry_price", "exit_price", "pnl_pips", "pnl_dollars"):
        if column not in normalized.columns:
            normalized[column] = 0.0
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce").fillna(0.0)
    if "exit_reason" not in normalized.columns:
        normalized["exit_reason"] = ""
    normalized["exit_reason"] = normalized["exit_reason"].astype(str).str.lower().str.strip()
    for column in ("stop_loss_price", "take_profit_price"):
        if column not in normalized.columns:
            normalized[column] = 0.0
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce").fillna(0.0)
    if "same_bar_collision" not in normalized.columns:
        normalized["same_bar_collision"] = False
    normalized["same_bar_collision"] = normalized["same_bar_collision"].astype(bool)
    for column in ("candidate_id", "run_id", "magic_number", "ticket"):
        if column not in normalized.columns:
            normalized[column] = ""
        normalized[column] = normalized[column].astype(str)
    normalized = normalized.dropna(subset=["timestamp_utc"]).reset_index(drop=True)
    return normalized[AUDIT_COLUMNS]


def _match_expected_to_actual(
    expected: pd.DataFrame,
    actual: pd.DataFrame,
    settings: Settings,
    *,
    spec: StrategySpec | None = None,
    broker_history_frame: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    entry_tolerance = settings.validation.parity_timestamp_tolerance_seconds
    matched: list[dict[str, float | int]] = []
    used_actual: set[int] = set()
    executable_features: pd.DataFrame | None = None
    feature_index_by_timestamp: dict[pd.Timestamp, int] = {}
    pip_scale = 10000.0
    if spec is not None and broker_history_frame is not None and not broker_history_frame.empty:
        executable_features = build_features(_ensure_market_mid_columns(broker_history_frame)).reset_index(drop=True)
        feature_index_by_timestamp = {
            pd.Timestamp(timestamp): int(index)
            for index, timestamp in executable_features["timestamp_utc"].items()
        }
        pip_scale = _pip_scale(spec.instrument)
    for expected_index, expected_row in expected.iterrows():
        best_actual_index: int | None = None
        best_score: float | None = None
        best_exit_delta = 0.0
        for actual_index, actual_row in actual.iterrows():
            if actual_index in used_actual:
                continue
            if actual_row["side"] != expected_row["side"]:
                continue
            entry_delta = abs((actual_row["timestamp_utc"] - expected_row["timestamp_utc"]).total_seconds())
            if entry_delta > entry_tolerance:
                continue
            exit_delta = _exit_timing_delta_seconds(expected_row, actual_row)
            score = entry_delta + min(exit_delta, settings.validation.parity_close_timing_tolerance_seconds)
            if best_score is None or score < best_score:
                best_actual_index = actual_index
                best_score = score
                best_exit_delta = exit_delta
        if best_actual_index is None:
            continue
        used_actual.add(best_actual_index)
        actual_row = actual.iloc[best_actual_index]
        expected_exit_timestamp = _format_optional_timestamp(expected_row.get("exit_timestamp_utc"))
        expected_exit_price = round(float(expected_row["exit_price"]), 6)
        expected_pnl_pips = round(float(expected_row["pnl_pips"]), 6)
        expected_exit_reason = str(expected_row.get("exit_reason", ""))
        expected_stop_loss_price = round(float(expected_row.get("stop_loss_price", 0.0)), 6)
        expected_take_profit_price = round(float(expected_row.get("take_profit_price", 0.0)), 6)
        expected_same_bar_collision = bool(expected_row.get("same_bar_collision", False))
        expected_collision_resolution = str(expected_row.get("collision_resolution", ""))
        comparison_basis = "baseline_executable"
        boundary_ambiguous_close_timing = False
        if (
            executable_features is not None
            and spec is not None
            and _price_delta_pips(expected_row["entry_price"], actual_row["entry_price"]) <= settings.validation.parity_price_tolerance_pips
        ):
            adjusted_exit = _matched_actual_fill_exit_baseline(
                executable_features=executable_features,
                feature_index_by_timestamp=feature_index_by_timestamp,
                expected_entry_timestamp=expected_row["timestamp_utc"],
                actual_entry_timestamp=actual_row["timestamp_utc"],
                side=str(expected_row["side"]),
                actual_entry_price=float(actual_row["entry_price"]),
                spec=spec,
                pip_scale=pip_scale,
                entry_tolerance_seconds=entry_tolerance,
            )
            if adjusted_exit is not None:
                expected_exit_timestamp = adjusted_exit["exit_timestamp_utc"]
                expected_exit_price = round(float(adjusted_exit["exit_price"]), 6)
                expected_pnl_pips = round(float(adjusted_exit["pnl_pips"]), 6)
                expected_exit_reason = str(adjusted_exit["exit_reason"])
                expected_stop_loss_price = round(float(adjusted_exit["stop_loss_price"]), 6)
                expected_take_profit_price = round(float(adjusted_exit["take_profit_price"]), 6)
                expected_same_bar_collision = bool(adjusted_exit["same_bar_collision"])
                expected_collision_resolution = str(adjusted_exit["collision_resolution"])
                comparison_basis = "actual_fill_adjusted_executable"
                boundary_ambiguous_close_timing = _is_boundary_ambiguous_close_timing(
                    executable_features=executable_features,
                    feature_index_by_timestamp=feature_index_by_timestamp,
                    expected_entry_timestamp=expected_row["timestamp_utc"],
                    actual_entry_timestamp=actual_row["timestamp_utc"],
                    side=str(expected_row["side"]),
                    actual_entry_price=float(actual_row["entry_price"]),
                    actual_exit_timestamp=actual_row.get("exit_timestamp_utc"),
                    actual_exit_reason=str(actual_row.get("exit_reason", "")),
                    spec=spec,
                    pip_scale=pip_scale,
                    entry_tolerance_seconds=entry_tolerance,
                )
        boundary_ambiguous_exit_semantics = False
        if executable_features is not None and spec is not None:
            boundary_ambiguous_exit_semantics = _is_boundary_ambiguous_exit_semantics(
                executable_features=executable_features,
                feature_index_by_timestamp=feature_index_by_timestamp,
                expected_entry_timestamp=expected_row["timestamp_utc"],
                actual_entry_timestamp=actual_row["timestamp_utc"],
                side=str(expected_row["side"]),
                actual_entry_price=float(actual_row["entry_price"]),
                actual_exit_timestamp=actual_row.get("exit_timestamp_utc"),
                actual_exit_reason=str(actual_row.get("exit_reason", "")),
                spec=spec,
                pip_scale=pip_scale,
                entry_tolerance_seconds=entry_tolerance,
            )
            if not boundary_ambiguous_exit_semantics:
                boundary_ambiguous_exit_semantics = _is_expected_boundary_ambiguous_timeout(
                    executable_features=executable_features,
                    feature_index_by_timestamp=feature_index_by_timestamp,
                    expected_entry_timestamp=expected_row["timestamp_utc"],
                    actual_entry_timestamp=actual_row["timestamp_utc"],
                    side=str(expected_row["side"]),
                    actual_entry_price=float(actual_row["entry_price"]),
                    expected_exit_timestamp=expected_exit_timestamp,
                    expected_exit_reason=expected_exit_reason,
                    actual_exit_timestamp=actual_row.get("exit_timestamp_utc"),
                    actual_exit_reason=str(actual_row.get("exit_reason", "")),
                    spec=spec,
                    pip_scale=pip_scale,
                    entry_tolerance_seconds=entry_tolerance,
                )
        matched.append(
            {
                "expected_index": int(expected_index),
                "actual_index": int(best_actual_index),
                "side": str(expected_row["side"]),
                "expected_timestamp_utc": expected_row["timestamp_utc"].isoformat().replace("+00:00", "Z"),
                "actual_timestamp_utc": actual_row["timestamp_utc"].isoformat().replace("+00:00", "Z"),
                "expected_exit_timestamp_utc": expected_exit_timestamp,
                "actual_exit_timestamp_utc": _format_optional_timestamp(actual_row.get("exit_timestamp_utc")),
                "expected_entry_price": round(float(expected_row["entry_price"]), 6),
                "actual_entry_price": round(float(actual_row["entry_price"]), 6),
                "expected_exit_price": expected_exit_price,
                "actual_exit_price": round(float(actual_row["exit_price"]), 6),
                "expected_pnl_pips": expected_pnl_pips,
                "actual_pnl_pips": round(float(actual_row["pnl_pips"]), 6),
                "expected_exit_reason": expected_exit_reason,
                "actual_exit_reason": str(actual_row.get("exit_reason", "")),
                "exit_reason_match": expected_exit_reason == str(actual_row.get("exit_reason", "")),
                "expected_stop_loss_price": expected_stop_loss_price,
                "actual_stop_loss_price": round(float(actual_row.get("stop_loss_price", 0.0)), 6),
                "expected_take_profit_price": expected_take_profit_price,
                "actual_take_profit_price": round(float(actual_row.get("take_profit_price", 0.0)), 6),
                "expected_same_bar_collision": expected_same_bar_collision,
                "actual_same_bar_collision": bool(actual_row.get("same_bar_collision", False)),
                "same_bar_collision_match": expected_same_bar_collision == bool(actual_row.get("same_bar_collision", False)),
                "expected_collision_resolution": expected_collision_resolution,
                "baseline_expected_exit_timestamp_utc": _format_optional_timestamp(expected_row.get("exit_timestamp_utc")),
                "baseline_expected_exit_price": round(float(expected_row["exit_price"]), 6),
                "baseline_expected_pnl_pips": round(float(expected_row["pnl_pips"]), 6),
                "baseline_expected_exit_reason": str(expected_row.get("exit_reason", "")),
                "baseline_expected_stop_loss_price": round(float(expected_row.get("stop_loss_price", 0.0)), 6),
                "baseline_expected_take_profit_price": round(float(expected_row.get("take_profit_price", 0.0)), 6),
                "comparison_basis": comparison_basis,
                "boundary_ambiguous_close_timing": bool(boundary_ambiguous_close_timing),
                "boundary_ambiguous_exit_semantics": bool(boundary_ambiguous_exit_semantics),
                "entry_price_delta_pips": round(_price_delta_pips(expected_row["entry_price"], actual_row["entry_price"]), 6),
                "exit_price_delta_pips": round(_price_delta_pips(expected_exit_price, actual_row["exit_price"]), 6),
                "fill_delta_pips": round(abs(float(expected_pnl_pips) - float(actual_row["pnl_pips"])), 6),
                "close_timing_delta_seconds": round(
                    _optional_timestamp_delta_seconds(expected_exit_timestamp, actual_row.get("exit_timestamp_utc")),
                    6,
                ),
            }
        )
    return matched


def _matched_actual_fill_exit_baseline(
    *,
    executable_features: pd.DataFrame,
    feature_index_by_timestamp: dict[pd.Timestamp, int],
    expected_entry_timestamp: Any,
    actual_entry_timestamp: Any,
    side: str,
    actual_entry_price: float,
    spec: StrategySpec,
    pip_scale: float,
    entry_tolerance_seconds: int,
) -> dict[str, Any] | None:
    entry_index = _resolve_feature_entry_index(
        feature_index_by_timestamp,
        expected_entry_timestamp,
        actual_entry_timestamp,
        tolerance_seconds=entry_tolerance_seconds,
    )
    if entry_index is None:
        return None
    signal = 1 if side == "long" else -1
    exit_result = _resolve_executable_exit(executable_features, entry_index, signal, actual_entry_price, spec, pip_scale)
    if exit_result is None:
        return None
    exit_timestamp = executable_features.iloc[int(exit_result["exit_index"])]["timestamp_utc"]
    exit_price = float(exit_result["exit_price"])
    pnl_pips = (
        (exit_price - actual_entry_price) * pip_scale
        if signal > 0
        else (actual_entry_price - exit_price) * pip_scale
    )
    return {
        "exit_timestamp_utc": _format_optional_timestamp(exit_timestamp),
        "exit_price": exit_price,
        "pnl_pips": pnl_pips,
        "exit_reason": str(exit_result["exit_reason"]),
        "stop_loss_price": float(exit_result["stop_loss_price"]),
        "take_profit_price": float(exit_result["take_profit_price"]),
        "same_bar_collision": bool(exit_result["same_bar_collision"]),
        "collision_resolution": str(exit_result["collision_resolution"]),
    }


def _is_boundary_ambiguous_close_timing(
    *,
    executable_features: pd.DataFrame,
    feature_index_by_timestamp: dict[pd.Timestamp, int],
    expected_entry_timestamp: Any,
    actual_entry_timestamp: Any,
    side: str,
    actual_entry_price: float,
    actual_exit_timestamp: Any,
    actual_exit_reason: str,
    spec: StrategySpec,
    pip_scale: float,
    entry_tolerance_seconds: int,
) -> bool:
    if actual_exit_reason not in {"stop_loss", "take_profit"}:
        return False
    if actual_exit_timestamp is None or pd.isna(actual_exit_timestamp):
        return False
    entry_index = _resolve_feature_entry_index(
        feature_index_by_timestamp,
        expected_entry_timestamp,
        actual_entry_timestamp,
        tolerance_seconds=entry_tolerance_seconds,
    )
    if entry_index is None:
        return False
    near_timestamp, exact_timestamp = _boundary_hit_window(
        executable_features=executable_features,
        entry_index=entry_index,
        side=side,
        actual_entry_price=actual_entry_price,
        actual_exit_reason=actual_exit_reason,
        spec=spec,
        pip_scale=pip_scale,
    )
    if near_timestamp is None or exact_timestamp is None or near_timestamp >= exact_timestamp:
        return False
    actual_exit_ts = pd.Timestamp(actual_exit_timestamp)
    if actual_exit_ts.tzinfo is None:
        actual_exit_ts = actual_exit_ts.tz_localize(UTC)
    else:
        actual_exit_ts = actual_exit_ts.tz_convert(UTC)
    return near_timestamp <= actual_exit_ts <= (exact_timestamp + pd.Timedelta(seconds=entry_tolerance_seconds))


def _is_boundary_ambiguous_exit_semantics(
    *,
    executable_features: pd.DataFrame,
    feature_index_by_timestamp: dict[pd.Timestamp, int],
    expected_entry_timestamp: Any,
    actual_entry_timestamp: Any,
    side: str,
    actual_entry_price: float,
    actual_exit_timestamp: Any,
    actual_exit_reason: str,
    spec: StrategySpec,
    pip_scale: float,
    entry_tolerance_seconds: int,
) -> bool:
    if actual_exit_reason not in {"stop_loss", "take_profit"}:
        return False
    if actual_exit_timestamp is None or pd.isna(actual_exit_timestamp):
        return False
    entry_index = _resolve_feature_entry_index(
        feature_index_by_timestamp,
        expected_entry_timestamp,
        actual_entry_timestamp,
        tolerance_seconds=entry_tolerance_seconds,
    )
    if entry_index is None:
        return False
    near_timestamp, exact_timestamp = _boundary_hit_window(
        executable_features=executable_features,
        entry_index=entry_index,
        side=side,
        actual_entry_price=actual_entry_price,
        actual_exit_reason=actual_exit_reason,
        spec=spec,
        pip_scale=pip_scale,
    )
    if near_timestamp is None:
        return False
    actual_exit_ts = pd.Timestamp(actual_exit_timestamp)
    if actual_exit_ts.tzinfo is None:
        actual_exit_ts = actual_exit_ts.tz_localize(UTC)
    else:
        actual_exit_ts = actual_exit_ts.tz_convert(UTC)
    upper_bound = (
        exact_timestamp + pd.Timedelta(seconds=entry_tolerance_seconds)
        if exact_timestamp is not None
        else near_timestamp + pd.Timedelta(seconds=entry_tolerance_seconds)
    )
    return near_timestamp <= actual_exit_ts <= upper_bound


def _is_expected_boundary_ambiguous_timeout(
    *,
    executable_features: pd.DataFrame,
    feature_index_by_timestamp: dict[pd.Timestamp, int],
    expected_entry_timestamp: Any,
    actual_entry_timestamp: Any,
    side: str,
    actual_entry_price: float,
    expected_exit_timestamp: Any,
    expected_exit_reason: str,
    actual_exit_timestamp: Any,
    actual_exit_reason: str,
    spec: StrategySpec,
    pip_scale: float,
    entry_tolerance_seconds: int,
) -> bool:
    if actual_exit_reason != "timeout" or expected_exit_reason not in {"stop_loss", "take_profit"}:
        return False
    if expected_exit_timestamp is None or pd.isna(expected_exit_timestamp) or actual_exit_timestamp is None or pd.isna(actual_exit_timestamp):
        return False
    entry_index = _resolve_feature_entry_index(
        feature_index_by_timestamp,
        expected_entry_timestamp,
        actual_entry_timestamp,
        tolerance_seconds=entry_tolerance_seconds,
    )
    if entry_index is None:
        return False
    near_timestamp, exact_timestamp = _boundary_hit_window(
        executable_features=executable_features,
        entry_index=entry_index,
        side=side,
        actual_entry_price=actual_entry_price,
        actual_exit_reason=expected_exit_reason,
        spec=spec,
        pip_scale=pip_scale,
    )
    boundary_timestamp = exact_timestamp or near_timestamp
    if boundary_timestamp is None:
        return False
    expected_exit_ts = pd.Timestamp(expected_exit_timestamp)
    if expected_exit_ts.tzinfo is None:
        expected_exit_ts = expected_exit_ts.tz_localize(UTC)
    else:
        expected_exit_ts = expected_exit_ts.tz_convert(UTC)
    actual_exit_ts = pd.Timestamp(actual_exit_timestamp)
    if actual_exit_ts.tzinfo is None:
        actual_exit_ts = actual_exit_ts.tz_localize(UTC)
    else:
        actual_exit_ts = actual_exit_ts.tz_convert(UTC)
    return (
        abs((boundary_timestamp - expected_exit_ts).total_seconds()) <= entry_tolerance_seconds
        and actual_exit_ts >= boundary_timestamp
    )


def _resolve_feature_entry_index(
    feature_index_by_timestamp: dict[pd.Timestamp, int],
    expected_entry_timestamp: Any,
    actual_entry_timestamp: Any,
    *,
    tolerance_seconds: int,
) -> int | None:
    candidates: list[pd.Timestamp] = []
    for raw in (actual_entry_timestamp, expected_entry_timestamp):
        if raw is None or pd.isna(raw):
            continue
        timestamp = pd.Timestamp(raw)
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(UTC)
        else:
            timestamp = timestamp.tz_convert(UTC)
        candidates.append(timestamp)
        if timestamp in feature_index_by_timestamp:
            return feature_index_by_timestamp[timestamp]
    if not candidates:
        return None
    best_timestamp: pd.Timestamp | None = None
    best_delta: float | None = None
    for timestamp in feature_index_by_timestamp:
        for candidate in candidates:
            delta = abs((timestamp - candidate).total_seconds())
            if delta > tolerance_seconds:
                continue
            if best_delta is None or delta < best_delta:
                best_timestamp = timestamp
                best_delta = delta
    if best_timestamp is None:
        return None
    return feature_index_by_timestamp[best_timestamp]


def _boundary_hit_window(
    *,
    executable_features: pd.DataFrame,
    entry_index: int,
    side: str,
    actual_entry_price: float,
    actual_exit_reason: str,
    spec: StrategySpec,
    pip_scale: float,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    price_digits = _instrument_digits(spec.instrument)
    point_tolerance = 10 ** (-price_digits)
    stop_distance = spec.stop_loss_pips / pip_scale
    target_distance = spec.take_profit_pips / pip_scale
    normalized_entry_price = round(float(actual_entry_price), price_digits)
    signal = 1 if side == "long" else -1
    stop_price = round(
        normalized_entry_price - stop_distance if signal > 0 else normalized_entry_price + stop_distance,
        price_digits,
    )
    target_price = round(
        normalized_entry_price + target_distance if signal > 0 else normalized_entry_price - target_distance,
        price_digits,
    )
    final_index = entry_index + spec.holding_bars
    if final_index >= len(executable_features):
        return (None, None)

    near_timestamp: pd.Timestamp | None = None
    exact_timestamp: pd.Timestamp | None = None
    for index in range(entry_index, final_index):
        row = executable_features.iloc[index]
        timestamp = pd.Timestamp(row["timestamp_utc"])
        if actual_exit_reason == "stop_loss":
            if signal > 0:
                exact_hit = round(float(row["bid_l"]), price_digits) <= stop_price
                near_hit = round(float(row["bid_l"]), price_digits) <= (stop_price + point_tolerance)
            else:
                exact_hit = round(float(row["ask_h"]), price_digits) >= stop_price
                near_hit = round(float(row["ask_h"]), price_digits) >= (stop_price - point_tolerance)
        else:
            if signal > 0:
                exact_hit = round(float(row["bid_h"]), price_digits) >= target_price
                near_hit = round(float(row["bid_h"]), price_digits) >= (target_price - point_tolerance)
            else:
                exact_hit = round(float(row["ask_l"]), price_digits) <= target_price
                near_hit = round(float(row["ask_l"]), price_digits) <= (target_price + point_tolerance)
        if near_hit and near_timestamp is None:
            near_timestamp = timestamp
        if exact_hit:
            exact_timestamp = timestamp
            break
    return (near_timestamp, exact_timestamp)


def _optional_timestamp_delta_seconds(expected_timestamp: Any, actual_timestamp: Any) -> float:
    if expected_timestamp is None or pd.isna(expected_timestamp) or actual_timestamp is None or pd.isna(actual_timestamp):
        return 0.0
    expected_ts = pd.Timestamp(expected_timestamp)
    if expected_ts.tzinfo is None:
        expected_ts = expected_ts.tz_localize(UTC)
    else:
        expected_ts = expected_ts.tz_convert(UTC)
    actual_ts = pd.Timestamp(actual_timestamp)
    if actual_ts.tzinfo is None:
        actual_ts = actual_ts.tz_localize(UTC)
    else:
        actual_ts = actual_ts.tz_convert(UTC)
    return abs((actual_ts - expected_ts).total_seconds())


def _format_optional_timestamp(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(UTC)
    else:
        timestamp = timestamp.tz_convert(UTC)
    return timestamp.isoformat().replace("+00:00", "Z")


def _exit_timing_delta_seconds(expected_row: pd.Series, actual_row: pd.Series) -> float:
    expected_exit = expected_row.get("exit_timestamp_utc")
    actual_exit = actual_row.get("exit_timestamp_utc")
    if pd.isna(expected_exit) or pd.isna(actual_exit):
        return 0.0
    return abs((actual_exit - expected_exit).total_seconds())


def _price_delta_pips(expected_price: float, actual_price: float) -> float:
    return abs(float(actual_price) - float(expected_price)) * 10000.0


def _write_parity_diagnostics(
    *,
    candidate_id: str,
    run_id: str | None,
    destination_dir: Path,
    expected: pd.DataFrame,
    actual: pd.DataFrame,
    matches: list[dict[str, Any]],
    settings: Settings,
    expected_signal_source: str,
    validation_status: str,
    failure_classification: str | None,
    expected_signal_path: Path | None,
    broker_history_csv_path: Path | None,
) -> tuple[Path, Path]:
    diagnostics_report_path = destination_dir / "parity_diagnostics.json"
    matched_trade_diagnostics_path = destination_dir / "matched_trade_diagnostics.csv"

    diagnostics_frame = pd.DataFrame.from_records(matches)
    if diagnostics_frame.empty:
        diagnostics_frame = pd.DataFrame(
            columns=[
                "expected_index",
                "actual_index",
                "side",
                "expected_timestamp_utc",
                "actual_timestamp_utc",
                "expected_exit_timestamp_utc",
                "actual_exit_timestamp_utc",
                "expected_entry_price",
                "actual_entry_price",
                "expected_exit_price",
                "actual_exit_price",
                "expected_pnl_pips",
                "actual_pnl_pips",
                "entry_price_delta_pips",
                "exit_price_delta_pips",
                "fill_delta_pips",
                "close_timing_delta_seconds",
                "expected_exit_reason",
                "actual_exit_reason",
                "exit_reason_match",
                "expected_same_bar_collision",
                "actual_same_bar_collision",
                "same_bar_collision_match",
                "expected_collision_resolution",
                "boundary_ambiguous_exit_semantics",
                "breach_entry_price",
                "breach_exit_price",
                "breach_fill_delta",
                "breach_close_timing",
                "breach_exit_reason",
                "breach_same_bar_collision",
                "breach_any",
                "likely_cause",
            ]
        )
    else:
        diagnostics_frame["breach_entry_price"] = (
            diagnostics_frame["entry_price_delta_pips"] > settings.validation.parity_price_tolerance_pips
        )
        diagnostics_frame["breach_exit_price"] = (
            diagnostics_frame["exit_price_delta_pips"] > settings.validation.parity_price_tolerance_pips
        )
        diagnostics_frame["breach_fill_delta"] = (
            diagnostics_frame["fill_delta_pips"] > settings.validation.parity_fill_tolerance_pips
        )
        diagnostics_frame["breach_close_timing"] = (
            diagnostics_frame["close_timing_delta_seconds"] > settings.validation.parity_close_timing_tolerance_seconds
        )
        pure_timing_match = (
            diagnostics_frame.get("exit_reason_match", pd.Series(False, index=diagnostics_frame.index, dtype=bool)).fillna(False).astype(bool)
            & (diagnostics_frame["exit_price_delta_pips"] <= settings.validation.parity_price_tolerance_pips)
            & (diagnostics_frame["fill_delta_pips"] <= settings.validation.parity_fill_tolerance_pips)
        )
        diagnostics_frame["breach_close_timing"] = diagnostics_frame["breach_close_timing"] & ~pure_timing_match
        if "boundary_ambiguous_close_timing" in diagnostics_frame:
            diagnostics_frame["breach_close_timing"] = diagnostics_frame["breach_close_timing"] & ~diagnostics_frame[
                "boundary_ambiguous_close_timing"
            ].fillna(False).astype(bool)
        diagnostics_frame["breach_exit_reason"] = ~diagnostics_frame.get(
            "exit_reason_match",
            pd.Series(True, index=diagnostics_frame.index, dtype=bool),
        )
        if "boundary_ambiguous_exit_semantics" in diagnostics_frame:
            ambiguous_exit = diagnostics_frame["boundary_ambiguous_exit_semantics"].fillna(False).astype(bool)
            diagnostics_frame["breach_exit_price"] = diagnostics_frame["breach_exit_price"] & ~ambiguous_exit
            diagnostics_frame["breach_fill_delta"] = diagnostics_frame["breach_fill_delta"] & ~ambiguous_exit
            diagnostics_frame["breach_close_timing"] = diagnostics_frame["breach_close_timing"] & ~ambiguous_exit
            diagnostics_frame["breach_exit_reason"] = diagnostics_frame["breach_exit_reason"] & ~ambiguous_exit
        diagnostics_frame["breach_same_bar_collision"] = ~diagnostics_frame.get(
            "same_bar_collision_match",
            pd.Series(True, index=diagnostics_frame.index, dtype=bool),
        )
        diagnostics_frame["breach_any"] = diagnostics_frame[
            [
                "breach_entry_price",
                "breach_exit_price",
                "breach_fill_delta",
                "breach_close_timing",
                "breach_exit_reason",
                "breach_same_bar_collision",
            ]
        ].any(axis=1)
        diagnostics_frame["likely_cause"] = diagnostics_frame.apply(_classify_parity_breach_row, axis=1)

    diagnostics_frame.to_csv(matched_trade_diagnostics_path, index=False)

    summary = _parity_diagnostics_summary(diagnostics_frame)
    breach_counts = {
        "entry_price": int(diagnostics_frame["breach_entry_price"].sum()) if "breach_entry_price" in diagnostics_frame else 0,
        "exit_price": int(diagnostics_frame["breach_exit_price"].sum()) if "breach_exit_price" in diagnostics_frame else 0,
        "fill_delta": int(diagnostics_frame["breach_fill_delta"].sum()) if "breach_fill_delta" in diagnostics_frame else 0,
        "close_timing": int(diagnostics_frame["breach_close_timing"].sum()) if "breach_close_timing" in diagnostics_frame else 0,
        "exit_reason_mismatch": int(diagnostics_frame["breach_exit_reason"].sum()) if "breach_exit_reason" in diagnostics_frame else 0,
        "same_bar_collision_mismatch": int(diagnostics_frame["breach_same_bar_collision"].sum()) if "breach_same_bar_collision" in diagnostics_frame else 0,
        "any_breach": int(diagnostics_frame["breach_any"].sum()) if "breach_any" in diagnostics_frame else 0,
    }
    likely_causes = (
        diagnostics_frame.loc[diagnostics_frame.get("breach_any", pd.Series(dtype=bool))]
        ["likely_cause"]
        .value_counts()
        .to_dict()
        if "likely_cause" in diagnostics_frame
        else {}
    )
    likely_cause_severity: dict[str, float] = {}
    top_breaches: list[dict[str, Any]]
    if diagnostics_frame.empty or "breach_any" not in diagnostics_frame:
        top_breaches = []
    else:
        ranked = diagnostics_frame.copy()
        ranked["severity_score"] = (
            ranked["entry_price_delta_pips"]
            + ranked["exit_price_delta_pips"]
            + ranked["fill_delta_pips"]
            + (ranked["close_timing_delta_seconds"] / max(settings.validation.parity_close_timing_tolerance_seconds, 1))
            + ranked["breach_exit_reason"].astype(int) * 5.0
            + ranked["breach_same_bar_collision"].astype(int) * 3.0
        )
        likely_cause_severity = {
            key: round(float(value), 6)
            for key, value in ranked.loc[ranked["breach_any"]]
            .groupby("likely_cause")["severity_score"]
            .sum()
            .sort_values(ascending=False)
            .items()
        }
        top_breaches = (
            ranked.loc[ranked["breach_any"]]
            .sort_values("severity_score", ascending=False)
            .head(10)
            .drop(columns=["severity_score"])
            .to_dict(orient="records")
        )

    diagnostics_payload = {
        "candidate_id": candidate_id,
        "run_id": run_id,
        "validation_status": validation_status,
        "failure_classification": failure_classification,
        "expected_signal_source": expected_signal_source,
        "expected_trade_count": int(len(expected)),
        "actual_trade_count": int(len(actual)),
        "matched_trade_count": int(len(matches)),
        "unmatched_expected_count": max(int(len(expected) - len(matches)), 0),
        "unmatched_actual_count": max(int(len(actual) - len(matches)), 0),
        "tolerances_used": _parity_tolerances(settings),
        "breach_counts": breach_counts,
        "likely_cause_counts": likely_causes,
        "likely_cause_severity": likely_cause_severity,
        "primary_failure_mode": _primary_failure_mode(breach_counts, likely_causes, likely_cause_severity),
        "metric_summary": summary,
        "exit_reason_counts": (
            {
                "expected": diagnostics_frame["expected_exit_reason"].value_counts().to_dict(),
                "actual": diagnostics_frame["actual_exit_reason"].value_counts().to_dict(),
            }
            if "expected_exit_reason" in diagnostics_frame and "actual_exit_reason" in diagnostics_frame
            else {}
        ),
        "same_bar_collision_counts": (
            {
                "expected_true": int(diagnostics_frame["expected_same_bar_collision"].sum()),
                "actual_true": int(diagnostics_frame["actual_same_bar_collision"].sum()),
            }
            if "expected_same_bar_collision" in diagnostics_frame and "actual_same_bar_collision" in diagnostics_frame
            else {}
        ),
        "expected_signal_path": str(expected_signal_path) if expected_signal_path else None,
        "broker_history_csv_path": str(broker_history_csv_path) if broker_history_csv_path else None,
        "matched_trade_diagnostics_path": str(matched_trade_diagnostics_path),
        "top_breaches": top_breaches,
    }
    write_json(diagnostics_report_path, diagnostics_payload)
    return diagnostics_report_path, matched_trade_diagnostics_path


def _parity_diagnostics_summary(diagnostics_frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    if diagnostics_frame.empty:
        return {}
    summary: dict[str, dict[str, float]] = {}
    for metric in (
        "entry_price_delta_pips",
        "exit_price_delta_pips",
        "fill_delta_pips",
        "close_timing_delta_seconds",
    ):
        summary[metric] = {
            "median": round(float(diagnostics_frame[metric].median()), 6),
            "p95": round(float(diagnostics_frame[metric].quantile(0.95)), 6),
            "max": round(float(diagnostics_frame[metric].max()), 6),
        }
    return summary


def _classify_parity_breach_row(row: pd.Series) -> str:
    if bool(row.get("breach_exit_reason")):
        expected_reason = str(row.get("expected_exit_reason", "")).strip().lower()
        actual_reason = str(row.get("actual_exit_reason", "")).strip().lower()
        if "timeout" in {expected_reason, actual_reason}:
            return "timeout_rule_mismatch"
        if bool(row.get("breach_same_bar_collision")) or bool(row.get("expected_same_bar_collision")) or bool(
            row.get("actual_same_bar_collision")
        ):
            return "intrabar_collision_mismatch"
        return "exit_reason_mismatch"
    if bool(row.get("breach_same_bar_collision")):
        return "intrabar_collision_mismatch"
    if bool(row.get("breach_close_timing")) and bool(row.get("breach_exit_price")):
        return "exit_timing_and_price_drift"
    if bool(row.get("breach_exit_price")) and not bool(row.get("breach_entry_price")):
        return "exit_semantics_drift"
    if bool(row.get("breach_close_timing")):
        return "timeout_or_bar_close_drift"
    if bool(row.get("breach_fill_delta")):
        return "pnl_fill_drift"
    if bool(row.get("breach_entry_price")):
        return "entry_price_drift"
    return "within_tolerance"


def _primary_failure_mode(
    breach_counts: dict[str, int],
    likely_causes: dict[str, int],
    likely_cause_severity: dict[str, float],
) -> str:
    if breach_counts["any_breach"] <= 0:
        return "within_tolerance"
    if likely_cause_severity:
        return max(likely_cause_severity.items(), key=lambda item: item[1])[0]
    if likely_causes:
        return max(likely_causes.items(), key=lambda item: item[1])[0]
    if breach_counts["exit_price"] >= max(breach_counts["entry_price"], breach_counts["fill_delta"], breach_counts["close_timing"]):
        return "exit_semantics_drift"
    if breach_counts["close_timing"] > 0:
        return "timeout_or_bar_close_drift"
    if breach_counts["entry_price"] > 0:
        return "entry_price_drift"
    if breach_counts["fill_delta"] > 0:
        return "pnl_fill_drift"
    return "within_tolerance"


def _parity_tolerances(settings: Settings) -> dict[str, float | int]:
    return {
        "parity_timestamp_tolerance_seconds": settings.validation.parity_timestamp_tolerance_seconds,
        "parity_close_timing_tolerance_seconds": settings.validation.parity_close_timing_tolerance_seconds,
        "parity_price_tolerance_pips": settings.validation.parity_price_tolerance_pips,
        "parity_fill_tolerance_pips": settings.validation.parity_fill_tolerance_pips,
        "parity_min_match_rate": settings.validation.parity_min_match_rate,
        "parity_max_unmatched_expected_rate": settings.validation.parity_max_unmatched_expected_rate,
        "parity_max_unmatched_actual_rate": settings.validation.parity_max_unmatched_actual_rate,
        "parity_min_closed_trades": settings.validation.parity_min_closed_trades,
    }


def _failure_code_from_classification(classification: str | None) -> str | None:
    if classification == "execution_cost_failure":
        return "execution_cost_failure"
    if classification == "parity_failure":
        return "parity_failure"
    return None


def _audit_relative_path(candidate_id: str, packet_run_id: str, settings: Settings) -> str:
    return f"{settings.mt5_env.audit_subdirectory}\\{candidate_id}__{packet_run_id}__audit.csv"


def _broker_history_relative_path(candidate_id: str, settings: Settings) -> str:
    return f"{settings.mt5_env.audit_subdirectory}\\{candidate_id}__broker_history.csv"


def _run_scoped_broker_history_relative_path(candidate_id: str, run_id: str, settings: Settings) -> str:
    return f"{settings.mt5_env.audit_subdirectory}\\{candidate_id}__{run_id}__broker_history.csv"


def _diagnostic_windows_relative_path(candidate_id: str, settings: Settings) -> str:
    return f"{settings.mt5_env.audit_subdirectory}\\{candidate_id}__diagnostic_tick_windows.csv"


def _run_scoped_diagnostic_windows_relative_path(candidate_id: str, run_id: str, settings: Settings) -> str:
    return f"{settings.mt5_env.audit_subdirectory}\\{candidate_id}__{run_id}__diagnostic_tick_windows.csv"


def _diagnostic_ticks_relative_path(candidate_id: str, settings: Settings) -> str:
    return f"{settings.mt5_env.audit_subdirectory}\\{candidate_id}__diagnostic_ticks.csv"


def _run_scoped_diagnostic_ticks_relative_path(candidate_id: str, run_id: str, settings: Settings) -> str:
    return f"{settings.mt5_env.audit_subdirectory}\\{candidate_id}__{run_id}__diagnostic_ticks.csv"


def _run_scoped_runtime_summary_relative_path(candidate_id: str, run_id: str, settings: Settings) -> str:
    return f"{settings.mt5_env.audit_subdirectory}\\{candidate_id}__{run_id}__runtime_summary.json"


def _run_scoped_signal_trace_relative_path(candidate_id: str, run_id: str, settings: Settings) -> str:
    return f"{settings.mt5_env.audit_subdirectory}\\{candidate_id}__{run_id}__signal_trace.csv"


def _resolve_audit_output_path(settings: Settings, terminal_data_path: Path | None, audit_relative_path: str) -> Path | None:
    if settings.mt5_env.audit_file_mode != "common_files":
        if terminal_data_path is None:
            return None
        return terminal_data_path / "MQL5" / "Files" / Path(audit_relative_path)
    common_root = Path.home() / "AppData" / "Roaming" / "MetaQuotes" / "Terminal" / "Common" / "Files"
    return common_root / Path(audit_relative_path)


def _resolve_broker_history_output_path(
    settings: Settings,
    terminal_data_path: Path | None,
    broker_history_relative_path: str,
) -> Path | None:
    if settings.mt5_env.audit_file_mode != "common_files":
        if terminal_data_path is None:
            return None
        return terminal_data_path / "MQL5" / "Files" / Path(broker_history_relative_path)
    common_root = Path.home() / "AppData" / "Roaming" / "MetaQuotes" / "Terminal" / "Common" / "Files"
    return common_root / Path(broker_history_relative_path)


def _resolve_diagnostic_windows_output_path(
    settings: Settings,
    terminal_data_path: Path | None,
    diagnostic_windows_relative_path: str,
) -> Path | None:
    return _resolve_broker_history_output_path(settings, terminal_data_path, diagnostic_windows_relative_path)


def _resolve_diagnostic_ticks_output_path(
    settings: Settings,
    terminal_data_path: Path | None,
    diagnostic_ticks_relative_path: str,
) -> Path | None:
    return _resolve_broker_history_output_path(settings, terminal_data_path, diagnostic_ticks_relative_path)


def _resolve_runtime_summary_output_path(
    settings: Settings,
    terminal_data_path: Path | None,
    runtime_summary_relative_path: str,
) -> Path | None:
    return _resolve_broker_history_output_path(settings, terminal_data_path, runtime_summary_relative_path)


def _resolve_signal_trace_output_path(
    settings: Settings,
    terminal_data_path: Path | None,
    signal_trace_relative_path: str,
) -> Path | None:
    return _resolve_broker_history_output_path(settings, terminal_data_path, signal_trace_relative_path)


def _prepare_automated_terminal_runtime(
    settings: Settings,
    *,
    terminal_path: Path | None,
    terminal_data_path: Path | None,
) -> tuple[Path | None, Path | None, Path | None]:
    if terminal_path is None or not terminal_path.exists():
        return terminal_path, terminal_data_path, _resolve_metaeditor_path(terminal_path)

    runtime_root = settings.paths().state_dir / "mt5_automation_runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    runtime_terminal_path = runtime_root / terminal_path.name

    for binary_name in ("terminal64.exe", "MetaEditor64.exe", "metatester64.exe", "Terminal.ico"):
        source_path = terminal_path.parent / binary_name
        if source_path.exists():
            _copy_if_stale(source_path, runtime_root / binary_name)

    if runtime_terminal_path.exists():
        _stop_mt5_processes_for_path(runtime_terminal_path)

    install_config_dir = terminal_path.parent / "Config"
    runtime_config_dir = runtime_root / "Config"
    runtime_config_dir.mkdir(parents=True, exist_ok=True)
    for source_dir in (
        terminal_data_path / "config" if terminal_data_path else None,
        terminal_data_path / "Config" if terminal_data_path else None,
        install_config_dir if install_config_dir.exists() else None,
    ):
        if source_dir is not None and source_dir.exists():
            _sync_directory_contents(source_dir, runtime_config_dir)
    preferred_config_dir = None
    for source_dir in (
        terminal_data_path / "config" if terminal_data_path else None,
        terminal_data_path / "Config" if terminal_data_path else None,
    ):
        if source_dir is not None and source_dir.exists():
            preferred_config_dir = source_dir
            break
    if preferred_config_dir is not None:
        for config_name in ("common.ini", "accounts.dat", "servers.dat", "settings.ini", "terminal.ini"):
            source_path = preferred_config_dir / config_name
            if source_path.exists():
                target_path = runtime_config_dir / config_name
                try:
                    shutil.copy2(source_path, target_path)
                except PermissionError:
                    if not target_path.exists():
                        raise

    runtime_mql5_dir = runtime_root / "MQL5"
    if terminal_data_path and (terminal_data_path / "MQL5").exists():
        _sync_directory_contents(terminal_data_path / "MQL5", runtime_mql5_dir)
    for relative_dir in (
        Path("Experts") / "AgenticForex",
        Path("Files"),
    ):
        (runtime_mql5_dir / relative_dir).mkdir(parents=True, exist_ok=True)

    event_calendar_path = (
        terminal_data_path / "MQL5" / "Files" / "mt5_event_calendar.csv" if terminal_data_path else None
    )
    if event_calendar_path and event_calendar_path.exists():
        _copy_if_stale(event_calendar_path, runtime_mql5_dir / "Files" / event_calendar_path.name)

    tester_dir = terminal_path.parent / "Tester"
    if tester_dir.exists():
        _sync_directory_contents(tester_dir, runtime_root / "Tester")

    return runtime_terminal_path, runtime_root, _resolve_metaeditor_path(runtime_terminal_path)


def _stage_existing_build_for_launch(
    *,
    source_path: Path | None,
    compiled_ex5_path: Path | None,
    compile_target_relative_path: Path,
    terminal_data_path: Path | None,
) -> tuple[Path, Path | None]:
    if terminal_data_path is None:
        resolved_source_path = source_path or compile_target_relative_path
        return resolved_source_path, compiled_ex5_path

    staged_source_path = terminal_data_path / compile_target_relative_path
    staged_ex5_path = staged_source_path.with_suffix(".ex5")
    staged_source_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path is not None and source_path.exists():
        if source_path.resolve() != staged_source_path.resolve():
            shutil.copy2(source_path, staged_source_path)
    if compiled_ex5_path is not None and compiled_ex5_path.exists():
        if compiled_ex5_path.resolve() != staged_ex5_path.resolve():
            shutil.copy2(compiled_ex5_path, staged_ex5_path)
    return staged_source_path, staged_ex5_path if staged_ex5_path.exists() else compiled_ex5_path


def _copy_if_stale(source_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        if (
            target_path.stat().st_size == source_path.stat().st_size
            and target_path.stat().st_mtime >= source_path.stat().st_mtime
        ):
            return
    shutil.copy2(source_path, target_path)


def _sync_directory_contents(source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for source_path in source_dir.rglob("*"):
        if source_path.is_dir():
            continue
        relative_path = source_path.relative_to(source_dir)
        _copy_if_stale(source_path, target_dir / relative_path)


def build_logic_manifest_payload(
    *,
    spec: StrategySpec,
    rendered_source: str,
    expected_signal_frame: pd.DataFrame | None,
    settings: Settings,
    source_artifact_paths: dict[str, Path | str | None] | None = None,
) -> dict[str, Any]:
    expected_signal_csv = expected_signal_frame.to_csv(index=False) if expected_signal_frame is not None else ""
    component_hashes = {
        "strategy_spec_sha256": _hash_text(spec.model_dump_json()),
        "rendered_ea_sha256": _hash_text(_normalized_rendered_source(rendered_source)),
        "expected_signals_sha256": _hash_text(expected_signal_csv),
        "compile_target_sha256": _hash_text(settings.mt5_env.compile_target_relative_path),
        "expert_path_sha256": _hash_text(settings.mt5_env.expert_relative_path),
    }
    artifact_hashes: dict[str, str] = {}
    for label, raw_path in (source_artifact_paths or {}).items():
        if raw_path is None:
            continue
        candidate = Path(raw_path)
        if candidate.exists():
            artifact_hashes[label] = _hash_path(candidate)
    manifest_payload = "\n".join(
        [f"{key}={value}" for key, value in sorted(component_hashes.items())]
        + [f"{key}={value}" for key, value in sorted(artifact_hashes.items())]
    )
    return {
        "logic_manifest_hash": hashlib.sha256(manifest_payload.encode("utf-8")).hexdigest(),
        "component_hashes": component_hashes,
        "source_artifact_hashes": artifact_hashes,
    }


def _logic_manifest_hash(
    *,
    spec: StrategySpec,
    rendered_source: str,
    expected_signal_frame: pd.DataFrame | None,
    settings: Settings,
    source_artifact_paths: dict[str, Path | str | None] | None = None,
) -> str:
    payload = build_logic_manifest_payload(
        spec=spec,
        rendered_source=rendered_source,
        expected_signal_frame=expected_signal_frame,
        settings=settings,
        source_artifact_paths=source_artifact_paths,
    )
    return str(payload["logic_manifest_hash"])


def _normalized_rendered_source(rendered_source: str) -> str:
    normalized = re.sub(
        r'input string InpPacketRunId = .*?;',
        'input string InpPacketRunId = "__RUN_ID__";',
        rendered_source,
    )
    normalized = re.sub(
        r'input string InpAuditRelativePath = .*?;',
        'input string InpAuditRelativePath = "__AUDIT_PATH__";',
        normalized,
    )
    normalized = re.sub(
        r'input string InpBrokerHistoryRelativePath = .*?;',
        'input string InpBrokerHistoryRelativePath = "__BROKER_HISTORY_PATH__";',
        normalized,
    )
    normalized = re.sub(
        r'input string InpDiagnosticWindowsRelativePath = .*?;',
        'input string InpDiagnosticWindowsRelativePath = "__DIAGNOSTIC_WINDOWS_PATH__";',
        normalized,
    )
    normalized = re.sub(
        r'input string InpDiagnosticTicksRelativePath = .*?;',
        'input string InpDiagnosticTicksRelativePath = "__DIAGNOSTIC_TICKS_PATH__";',
        normalized,
    )
    return normalized


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_packet_stale(candidate_id: str, settings: Settings, packet: MT5Packet) -> bool:
    if settings.mt5_env.stale_packet_policy != "logic_manifest_hash_or_missing_ex5":
        return not (packet.compiled_ex5_path and packet.compiled_ex5_path.exists())
    if not packet.compiled_ex5_path or not packet.compiled_ex5_path.exists():
        return True
    report_dir = settings.paths().reports_dir / candidate_id
    spec = StrategySpec.model_validate(read_json(report_dir / "strategy_spec.json"))
    rendered_source = render_candidate_ea(
        spec,
        audit_relative_path=packet.audit_relative_path or _audit_relative_path(candidate_id, "packet", settings),
        broker_history_relative_path=_broker_history_relative_path(candidate_id, settings),
        diagnostic_windows_relative_path=_diagnostic_windows_relative_path(candidate_id, settings),
        diagnostic_ticks_relative_path=_diagnostic_ticks_relative_path(candidate_id, settings),
        packet_run_id=_packet_run_id(packet),
        broker_timezone=settings.policy.ftmo_timezone,
    )
    expected_signal_frame = _expected_signal_frame(settings, report_dir, candidate_id, spec)
    current_hash = _logic_manifest_hash(
        spec=spec,
        rendered_source=rendered_source,
        expected_signal_frame=expected_signal_frame,
        settings=settings,
        source_artifact_paths={
            "strategy_spec_path": report_dir / "strategy_spec.json",
            "review_packet_path": report_dir / "review_packet.json",
            "expected_signal_path": packet.expected_signal_path,
        },
    )
    return current_hash != packet.logic_manifest_hash


def _packet_run_id(packet: MT5Packet) -> str:
    try:
        run_spec = MT5RunSpec.model_validate(read_json(packet.run_spec_path))
        return run_spec.run_id
    except Exception:
        return "packet"


def _clear_previous_parity_outputs(run_spec: MT5RunSpec) -> None:
    if run_spec.report_path.exists():
        run_spec.report_path.unlink()
    if run_spec.audit_output_path and run_spec.audit_output_path.exists():
        run_spec.audit_output_path.unlink()
    if run_spec.broker_history_output_path and run_spec.broker_history_output_path.exists():
        run_spec.broker_history_output_path.unlink()
    if run_spec.diagnostic_ticks_output_path and run_spec.diagnostic_ticks_output_path.exists():
        run_spec.diagnostic_ticks_output_path.unlink()
    if run_spec.runtime_summary_output_path and run_spec.runtime_summary_output_path.exists():
        run_spec.runtime_summary_output_path.unlink()
    if run_spec.signal_trace_output_path and run_spec.signal_trace_output_path.exists():
        run_spec.signal_trace_output_path.unlink()


def _launch_mt5_tester(run_spec: MT5RunSpec, settings: Settings) -> MT5RunResult:
    launch_status_path = run_spec.run_dir / "launch_status.json"
    started_utc = datetime.now(UTC)
    command: list[str] = []
    if run_spec.portable_mode and run_spec.terminal_path:
        _stop_mt5_processes_for_path(Path(run_spec.terminal_path))
        _clear_tester_cache(
            _run_spec_terminal_data_path(run_spec, settings),
            preserve_paths=[run_spec.tester_inputs_profile_path] if run_spec.tester_inputs_profile_path else None,
        )
    if run_spec.terminal_path:
        command = [run_spec.terminal_path, f"/config:{_windows_cli_path(run_spec.config_path)}"]
        if run_spec.portable_mode:
            command.append("/portable")

    terminal_return_code: int | None = None
    launch_status = "completed"
    timed_out = False
    stdout = ""
    stderr = ""
    compiled_ex5_path = run_spec.compile_target_path.with_suffix(".ex5")
    if not run_spec.terminal_path or not Path(run_spec.terminal_path).exists():
        launch_status = "launch_failed"
        stderr = "terminal_path_missing"
    elif not compiled_ex5_path.exists():
        launch_status = "launch_failed"
        stderr = "compiled_ex5_missing"
    else:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=run_spec.tester_timeout_seconds,
            )
            terminal_return_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            launch_status = "timed_out"
            timed_out = True
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
        except OSError as exc:
            launch_status = "launch_failed"
            stderr = str(exc)

    if run_spec.shutdown_terminal and run_spec.portable_mode and run_spec.terminal_path:
        _stop_mt5_processes_for_path(Path(run_spec.terminal_path))

    tester_report_path = _wait_for_tester_report(run_spec, settings)
    archived_tester_report_path: Path | None = None
    if tester_report_path and tester_report_path.exists():
        archived_tester_report_path = _archive_tester_report_bundle(tester_report_path, run_spec.run_dir)
    archived_audit_path: Path | None = None
    _wait_for_audit_output(run_spec)
    if run_spec.audit_output_path and run_spec.audit_output_path.exists():
        archived_audit_path = run_spec.run_dir / run_spec.audit_output_path.name
        archived_audit_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(run_spec.audit_output_path, archived_audit_path)
    archived_broker_history_path: Path | None = None
    _wait_for_broker_history_output(run_spec)
    if run_spec.broker_history_output_path and run_spec.broker_history_output_path.exists():
        archived_broker_history_path = run_spec.run_dir / run_spec.broker_history_output_path.name
        archived_broker_history_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(run_spec.broker_history_output_path, archived_broker_history_path)
    archived_diagnostic_ticks_path: Path | None = None
    _wait_for_diagnostic_ticks_output(run_spec)
    if run_spec.diagnostic_ticks_output_path and run_spec.diagnostic_ticks_output_path.exists():
        archived_diagnostic_ticks_path = run_spec.run_dir / run_spec.diagnostic_ticks_output_path.name
        archived_diagnostic_ticks_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(run_spec.diagnostic_ticks_output_path, archived_diagnostic_ticks_path)
    archived_runtime_summary_path: Path | None = None
    _wait_for_runtime_summary_output(run_spec)
    if run_spec.runtime_summary_output_path and run_spec.runtime_summary_output_path.exists():
        archived_runtime_summary_path = run_spec.run_dir / run_spec.runtime_summary_output_path.name
        archived_runtime_summary_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(run_spec.runtime_summary_output_path, archived_runtime_summary_path)
    archived_signal_trace_path: Path | None = None
    _wait_for_signal_trace_output(run_spec)
    if run_spec.signal_trace_output_path and run_spec.signal_trace_output_path.exists():
        archived_signal_trace_path = run_spec.run_dir / run_spec.signal_trace_output_path.name
        archived_signal_trace_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(run_spec.signal_trace_output_path, archived_signal_trace_path)
    write_json(
        launch_status_path,
        {
            "candidate_id": run_spec.candidate_id,
            "run_id": run_spec.run_id,
            "command": command,
            "launch_status": launch_status,
            "timed_out": timed_out,
            "terminal_return_code": terminal_return_code,
            "tester_report_path": str(archived_tester_report_path) if archived_tester_report_path else None,
            "audit_csv_path": str(archived_audit_path) if archived_audit_path else None,
            "broker_history_csv_path": str(archived_broker_history_path) if archived_broker_history_path else None,
            "diagnostic_ticks_csv_path": str(archived_diagnostic_ticks_path) if archived_diagnostic_ticks_path else None,
            "runtime_summary_json_path": str(archived_runtime_summary_path) if archived_runtime_summary_path else None,
            "signal_trace_csv_path": str(archived_signal_trace_path) if archived_signal_trace_path else None,
            "tester_inputs_profile_path": str(run_spec.tester_inputs_profile_path) if run_spec.tester_inputs_profile_path else None,
            "started_utc": started_utc.isoformat().replace("+00:00", "Z"),
            "finished_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "stdout": stdout[-4000:],
            "stderr": stderr[-4000:],
        },
    )
    return MT5RunResult(
        candidate_id=run_spec.candidate_id,
        run_id=run_spec.run_id,
        launch_status=launch_status,  # type: ignore[arg-type]
        terminal_return_code=terminal_return_code,
        timed_out=timed_out,
        terminal_path=run_spec.terminal_path,
        terminal_data_path=_run_spec_terminal_data_path(run_spec, settings),
        tester_report_path=archived_tester_report_path,
        audit_csv_path=archived_audit_path,
        broker_history_csv_path=archived_broker_history_path,
        diagnostic_ticks_csv_path=archived_diagnostic_ticks_path,
        runtime_summary_json_path=archived_runtime_summary_path,
        signal_trace_csv_path=archived_signal_trace_path,
        tester_inputs_profile_path=run_spec.tester_inputs_profile_path,
        launch_status_path=launch_status_path,
    )


def _archive_tester_report_bundle(tester_report_path: Path, destination_dir: Path) -> Path:
    destination_dir.mkdir(parents=True, exist_ok=True)
    archived_tester_report_path = destination_dir / tester_report_path.name
    if tester_report_path.resolve() != archived_tester_report_path.resolve():
        shutil.copy2(tester_report_path, archived_tester_report_path)
    else:
        archived_tester_report_path = tester_report_path

    # MT5 HTML reports reference companion PNG charts by the same stem.
    for companion_path in tester_report_path.parent.glob(f"{tester_report_path.stem}*.png"):
        archived_companion_path = destination_dir / companion_path.name
        if companion_path.resolve() == archived_companion_path.resolve():
            continue
        shutil.copy2(companion_path, archived_companion_path)

    return archived_tester_report_path


def _latest_run(candidate_id: str, settings: Settings) -> tuple[str | None, Path | None]:
    root = settings.paths().mt5_runs_dir / candidate_id
    if not root.exists():
        return None, None
    runs = sorted(path for path in root.iterdir() if path.is_dir())
    if not runs:
        return None, None
    latest = runs[-1]
    return latest.name, latest


def _tester_ini(
    candidate_id: str,
    run_spec: MT5RunSpec,
    settings: Settings,
    spec: StrategySpec,
    expected_signal_frame: pd.DataFrame,
) -> str:
    report_name = _tester_runtime_report_stem(run_spec)
    from_date, to_date = _tester_date_range(expected_signal_frame)
    if run_spec.tester_from_date:
        from_date = run_spec.tester_from_date
    if run_spec.tester_to_date:
        to_date = run_spec.tester_to_date
    lines = ["[Common]"]
    login, server = _configured_mt5_account(_run_spec_terminal_data_path(run_spec, settings))
    if login:
        lines.append(f"Login={login}")
    if server:
        lines.append(f"Server={server}")
    lines.extend(
        [
            "",
            "[Experts]",
            f"AllowLiveTrading={1 if run_spec.allow_live_trading else 0}",
            "",
            "[Tester]",
            f"Expert={_expert_path_for_run_spec(run_spec, settings)}",
            *(
                [f"ExpertParameters={run_spec.tester_inputs_profile_path.name}"]
                if run_spec.tester_inputs_profile_path is not None
                else []
            ),
            f"Symbol={_mt5_symbol(spec.instrument)}",
            f"Period={spec.execution_granularity}",
            f"Model={_tester_model_value(run_spec.tester_mode)}",
            f"FromDate={from_date}",
            f"ToDate={to_date}",
            f"Deposit={int(spec.account_model.initial_balance)}",
            f"Currency={spec.account_model.account_currency}",
            f"Leverage={int(spec.account_model.leverage)}",
            f"Report={report_name}",
            "ReplaceReport=1",
            "Visual=0",
            f"ShutdownTerminal={1 if run_spec.shutdown_terminal else 0}",
        ]
    )
    return "\n".join(lines)


def _tester_date_range(expected_signal_frame: pd.DataFrame) -> tuple[str, str]:
    if expected_signal_frame.empty:
        now = datetime.now(UTC)
        return now.strftime("%Y.%m.%d"), now.strftime("%Y.%m.%d")
    start_series = pd.to_datetime(expected_signal_frame["timestamp_utc"], utc=True, errors="coerce")
    start = start_series.min().to_pydatetime().astimezone(UTC)
    if "exit_timestamp_utc" in expected_signal_frame.columns and expected_signal_frame["exit_timestamp_utc"].notna().any():
        stop_series = pd.to_datetime(expected_signal_frame["exit_timestamp_utc"], utc=True, errors="coerce")
        stop = stop_series.max().to_pydatetime().astimezone(UTC)
    else:
        stop = start_series.max().to_pydatetime().astimezone(UTC)
    return start.strftime("%Y.%m.%d"), stop.strftime("%Y.%m.%d")


def _format_tester_date(value: str) -> str:
    normalized = value.strip()
    if re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", normalized):
        return normalized
    timestamp = pd.to_datetime(normalized, utc=True, errors="raise")
    return timestamp.to_pydatetime().astimezone(UTC).strftime("%Y.%m.%d")


def _tester_report_trade_count(tester_report_path: Path | None) -> int | None:
    if tester_report_path is None or not tester_report_path.exists():
        return None
    try:
        raw = tester_report_path.read_bytes()
    except OSError:
        return None
    payload = ""
    for encoding in ("utf-16", "utf-8", "cp1252", "latin-1"):
        try:
            payload = raw.decode(encoding)
            if "Total Trades" in payload:
                break
        except UnicodeDecodeError:
            continue
    if not payload:
        return None
    patterns = (
        r"Total Trades:</td>\s*<td[^>]*><b>(\d+)</b>",
        r"Total Trades\s*</[^>]+>\s*<[^>]+>\s*(?:<b>)?(\d+)",
        r"Total Trades\s+(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, payload, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    text = re.sub(r"<[^>]+>", " ", payload)
    match = re.search(r"Total Trades\s+(\d+)", re.sub(r"\s+", " ", text), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _tester_model_value(raw_mode: str) -> str:
    normalized = raw_mode.strip().lower()
    mapping = {
        "every tick": "0",
        "1 minute ohlc": "1",
        "open prices only": "2",
        "every tick based on real ticks": "4",
        "real ticks": "4",
    }
    return mapping.get(normalized, "4")


def _pip_scale(instrument: str) -> float:
    normalized = instrument.replace("/", "_").upper()
    if normalized.endswith("_JPY"):
        return 100.0
    return 10000.0


def _instrument_digits(instrument: str) -> int:
    normalized = instrument.replace("/", "_").upper()
    if normalized.endswith("_JPY"):
        return 3
    return 5


def _mt5_symbol(instrument: str) -> str:
    return instrument.replace("_", "").replace("/", "").strip().upper()


def _tester_expert_path(expert_relative_path: str) -> str:
    normalized = expert_relative_path.replace("/", "\\")
    if normalized.lower().startswith("experts\\"):
        return normalized[len("Experts\\") :]
    return normalized


def _expert_path_for_run_spec(run_spec: MT5RunSpec, settings: Settings) -> str:
    compile_target_path = Path(run_spec.compile_target_path)
    if compile_target_path.is_absolute():
        normalized_parts = [part.lower() for part in compile_target_path.parts]
        try:
            experts_index = normalized_parts.index("experts")
        except ValueError:
            return _tester_expert_path(settings.mt5_env.expert_relative_path)
        expert_relative = Path(*compile_target_path.parts[experts_index + 1 :]).with_suffix(".ex5")
        return str(expert_relative).replace("/", "\\")
    return _tester_expert_path(settings.mt5_env.expert_relative_path)


def _candidate_compile_target_relative_path(candidate_id: str, settings: Settings) -> Path:
    compile_target_path = Path(settings.mt5_env.compile_target_relative_path)
    return compile_target_path.with_name(f"{candidate_id}.mq5")


def _manual_compile_target_relative_path(candidate_id: str, run_id: str, settings: Settings) -> Path:
    compile_target_path = Path(settings.mt5_env.compile_target_relative_path)
    return compile_target_path.with_name(f"{candidate_id}-manual.mq5")


def _run_spec_terminal_data_path(run_spec: MT5RunSpec, settings: Settings) -> Path | None:
    if not run_spec.terminal_path:
        return None
    terminal_path = Path(run_spec.terminal_path)
    if run_spec.portable_mode:
        return terminal_path.parent
    return _resolve_terminal_data_path(settings, terminal_path)


def _configured_mt5_account(terminal_data_path: Path | None) -> tuple[str | None, str | None]:
    if terminal_data_path is None:
        return None, None
    for candidate in (
        terminal_data_path / "Config" / "common.ini",
        terminal_data_path / "config" / "common.ini",
    ):
        if not candidate.exists():
            continue
        payload = _read_mt5_ini(candidate)
        login_match = re.search(r"^\s*Login\s*=\s*(\d+)\s*$", payload, flags=re.MULTILINE)
        server_match = re.search(r"^\s*Server\s*=\s*(.+?)\s*$", payload, flags=re.MULTILINE)
        login = login_match.group(1) if login_match else None
        server = server_match.group(1).strip() if server_match else None
        if login or server:
            return login, server
    return None, None


def _wait_for_tester_report(run_spec: MT5RunSpec, settings: Settings) -> Path | None:
    deadline = time.time() + 5.0
    while time.time() < deadline:
        report_path = _discover_tester_report(run_spec, settings)
        if report_path is not None:
            return report_path
        time.sleep(0.25)
    return _discover_tester_report(run_spec, settings)


def _wait_for_audit_output(run_spec: MT5RunSpec) -> None:
    if run_spec.audit_output_path is None:
        return
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if run_spec.audit_output_path.exists():
            return
        time.sleep(0.25)


def _wait_for_broker_history_output(run_spec: MT5RunSpec) -> None:
    if run_spec.broker_history_output_path is None:
        return
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if run_spec.broker_history_output_path.exists():
            return
        time.sleep(0.25)


def _wait_for_diagnostic_ticks_output(run_spec: MT5RunSpec) -> None:
    if run_spec.diagnostic_ticks_output_path is None:
        return
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if run_spec.diagnostic_ticks_output_path.exists():
            return
        time.sleep(0.25)


def _wait_for_runtime_summary_output(run_spec: MT5RunSpec) -> None:
    if run_spec.runtime_summary_output_path is None:
        return
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if run_spec.runtime_summary_output_path.exists():
            return
        time.sleep(0.25)


def _wait_for_signal_trace_output(run_spec: MT5RunSpec) -> None:
    if run_spec.signal_trace_output_path is None:
        return
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if run_spec.signal_trace_output_path.exists():
            return
        time.sleep(0.25)


def _discover_tester_report(run_spec: MT5RunSpec, settings: Settings) -> Path | None:
    candidates = [
        run_spec.report_path,
        run_spec.report_path.with_suffix(".htm"),
        run_spec.report_path.with_suffix(".html"),
        run_spec.report_path.with_suffix(".xml"),
        run_spec.report_path.with_suffix(".xlsx"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    for candidate in run_spec.run_dir.glob(f"{run_spec.report_path.stem}*"):
        if candidate.is_file():
            return candidate
    terminal_data_path = _run_spec_terminal_data_path(run_spec, settings)
    if terminal_data_path is not None:
        report_stem = _tester_runtime_report_stem(run_spec)
        for suffix in (".htm", ".html", ".xml", ".xlsx"):
            candidate = terminal_data_path / f"{report_stem}{suffix}"
            if candidate.exists():
                return candidate
        for candidate in sorted(terminal_data_path.glob(f"{report_stem}*"), reverse=True):
            if candidate.is_file():
                return candidate
        for pattern in ("ReportTester*.htm", "ReportTester*.html", "ReportTester*.xml", "ReportTester*.xlsx"):
            matches = sorted(terminal_data_path.glob(pattern), reverse=True)
            if matches:
                return matches[0]
    profiles_dir = _tester_profiles_dir(_run_spec_terminal_data_path(run_spec, settings))
    if profiles_dir is not None and profiles_dir.exists():
        report_stem = _tester_runtime_report_stem(run_spec)
        for suffix in (".htm", ".html", ".xml", ".xlsx"):
            candidate = profiles_dir / f"{report_stem}{suffix}"
            if candidate.exists():
                return candidate
        for candidate in sorted(profiles_dir.glob(f"{report_stem}*"), reverse=True):
            if candidate.is_file():
                return candidate
        for pattern in ("ReportTester*.htm", "ReportTester*.html", "ReportTester*.xml", "ReportTester*.xlsx"):
            matches = sorted(profiles_dir.glob(pattern), reverse=True)
            if matches:
                return matches[0]
    return None


def _windows_cli_path(path: Path | str) -> str:
    candidate = Path(path)
    raw_path = str(candidate)
    if windll is None or not candidate.exists():
        return raw_path
    try:
        buffer = create_unicode_buffer(32768)
        result = windll.kernel32.GetShortPathNameW(raw_path, buffer, len(buffer))
        if result > 0:
            return buffer.value
    except Exception:
        pass
    return raw_path


def _stop_mt5_processes_for_path(terminal_path: Path) -> None:
    target_path = str(terminal_path)
    escaped_path = target_path.replace("'", "''")
    script = "\n".join(
        [
            f"$target = '{escaped_path}'",
            "$names = @('terminal64.exe','metatester64.exe')",
            "Get-CimInstance Win32_Process |",
            "  Where-Object { $names -contains $_.Name -and $_.ExecutablePath -eq $target } |",
            "  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
        ]
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return
    time.sleep(1.0)


def _clear_tester_cache(terminal_data_path: Path | None, *, preserve_paths: list[Path | None] | None = None) -> None:
    if terminal_data_path is None:
        return
    preserved = {path.resolve() for path in (preserve_paths or []) if path is not None and path.exists()}
    cache_root = terminal_data_path / "Tester" / "cache"
    if cache_root.exists():
        for cache_path in cache_root.glob("*"):
            if cache_path.is_dir():
                shutil.rmtree(cache_path, ignore_errors=True)
            else:
                _safe_unlink(cache_path)

    profiles_dir = _tester_profiles_dir(terminal_data_path)
    if profiles_dir is None or not profiles_dir.exists():
        profiles_dir = None
    if profiles_dir is not None:
        for pattern in (
            "*.set",
            "ReportTester*.htm",
            "ReportTester*.html",
            "ReportTester*.xml",
            "ReportTester*.xlsx",
            "ReportTester*.png",
        ):
            for stale_path in profiles_dir.glob(pattern):
                if stale_path.resolve() in preserved:
                    continue
                _safe_unlink(stale_path)

    for pattern in ("*-report.htm", "*-report.html", "*-report.xml", "*-report.xlsx"):
        for stale_path in terminal_data_path.glob(pattern):
            _safe_unlink(stale_path)
    for pattern in ("ReportTester*.htm", "ReportTester*.html", "ReportTester*.xml", "ReportTester*.xlsx"):
        for stale_path in terminal_data_path.glob(pattern):
            _safe_unlink(stale_path)


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        return


def _tester_profiles_dir(terminal_data_path: Path | None) -> Path | None:
    if terminal_data_path is None:
        return None
    return terminal_data_path / "MQL5" / "Profiles" / "Tester"


def _tester_inputs_profile_path(terminal_data_path: Path | None, candidate_id: str, run_id: str) -> Path | None:
    profiles_dir = _tester_profiles_dir(terminal_data_path)
    if profiles_dir is None:
        return None
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", f"{candidate_id}-{run_id}.set")
    return profiles_dir / safe_name


def _write_tester_inputs_profile(run_spec: MT5RunSpec, spec: StrategySpec) -> Path | None:
    if run_spec.tester_inputs_profile_path is None:
        return None
    run_spec.tester_inputs_profile_path.parent.mkdir(parents=True, exist_ok=True)
    content = _tester_inputs_profile_content(run_spec, spec)
    run_spec.tester_inputs_profile_path.write_text(content, encoding="utf-16")
    archived_path = run_spec.run_dir / run_spec.tester_inputs_profile_path.name
    archived_path.write_text(content, encoding="utf-16")
    return run_spec.tester_inputs_profile_path


def _tester_inputs_profile_content(run_spec: MT5RunSpec, spec: StrategySpec) -> str:
    filters = {item.name: item.rule for item in spec.filters}
    rows: list[tuple[str, str, bool]] = [
        ("InpCandidateId", spec.candidate_id, False),
        ("InpPacketRunId", run_spec.run_id, False),
        ("InpMagicNumber", str(_profile_magic_number(spec.candidate_id)), True),
        ("InpFixedLots", f"{min(spec.account_model.max_total_exposure_lots, 5.0):.2f}", True),
        ("InpSignalThreshold", f"{spec.signal_threshold:.5f}", True),
        ("InpStopLossPips", f"{spec.stop_loss_pips:.5f}", True),
        ("InpTakeProfitPips", f"{spec.take_profit_pips:.5f}", True),
        ("InpMaxSpreadPips", f"{_profile_float_or_default(filters.get('max_spread_pips'), spec.risk_envelope.max_spread_allowed_pips):.5f}", True),
        ("InpMinVolatility20", f"{_profile_float_or_default(filters.get('min_volatility_20'), 0.0):.8f}", True),
        ("InpBreakoutZscoreFloor", f"{_profile_float_or_default(filters.get('breakout_zscore_floor'), 0.0):.5f}", True),
        ("InpMaxRangeWidth10Pips", f"{_profile_float_or_default(filters.get('max_range_width_10_pips'), 0.0):.5f}", True),
        ("InpCompressionRangePositionFloor", f"{_profile_float_or_default(filters.get('compression_range_position_floor'), 0.65):.5f}", True),
        ("InpExtensionZscoreFloor", f"{_profile_float_or_default(filters.get('extension_zscore_floor'), 0.0):.5f}", True),
        ("InpReclaimRangePositionFloor", f"{_profile_float_or_default(filters.get('reclaim_range_position_floor'), 0.12):.5f}", True),
        ("InpReclaimRangePositionCeiling", f"{_profile_float_or_default(filters.get('reclaim_range_position_ceiling'), 0.42):.5f}", True),
        ("InpReclaimMomentumCeiling", f"{_profile_float_or_default(filters.get('reclaim_momentum_ceiling'), 4.0):.5f}", True),
        ("InpRet5Floor", f"{_profile_float_or_default(filters.get('ret_5_floor'), 0.0):.8f}", True),
        ("InpTrendRet5Min", f"{_profile_float_or_default(filters.get('trend_ret_5_min'), 0.0):.8f}", True),
        ("InpPullbackZscoreLimit", f"{_profile_float_or_default(filters.get('pullback_zscore_limit'), 0.45):.5f}", True),
        ("InpRetestZscoreLimit", f"{_profile_float_or_default(filters.get('retest_zscore_limit'), 0.35):.5f}", True),
        ("InpRetestRangePositionFloor", f"{_profile_float_or_default(filters.get('retest_range_position_floor'), 0.52):.5f}", True),
        ("InpContinuationZscoreFloor", f"{_profile_float_or_default(filters.get('continuation_zscore_floor'), 0.08):.5f}", True),
        ("InpContinuationZscoreCeiling", f"{_profile_float_or_default(filters.get('continuation_zscore_ceiling'), 0.72):.5f}", True),
        ("InpContinuationRangePositionFloor", f"{_profile_float_or_default(filters.get('continuation_range_position_floor'), 0.60):.5f}", True),
        ("InpFadeRet5Floor", f"{_profile_float_or_default(filters.get('fade_ret_5_floor'), 0.0):.8f}", True),
        ("InpFadeMomentumCeiling", f"{_profile_float_or_default(filters.get('fade_momentum_ceiling'), 3.2):.5f}", True),
        ("InpRequireRet5Alignment", _bool_profile_value(filters.get("require_ret_5_alignment")), False),
        ("InpRequireMeanLocationAlignment", _bool_profile_value(filters.get("require_mean_location_alignment")), False),
        ("InpRequireRet1Confirmation", _bool_profile_value(filters.get("require_ret_1_confirmation")), False),
        ("InpRequireReclaimRet1", _bool_profile_value(filters.get("require_reclaim_ret_1")), False),
        ("InpRequireRecoveryRet1", _bool_profile_value(filters.get("require_recovery_ret_1")), False),
        ("InpRequireReversalRet1", _bool_profile_value(filters.get("require_reversal_ret_1")), False),
        ("InpRequireReversalMomentum", _bool_profile_value(filters.get("require_reversal_momentum")), False),
        ("InpFillDelayMs", str(int(spec.execution_cost_model.fill_delay_ms)), True),
        ("InpHoldingBars", str(int(spec.holding_bars)), True),
        ("InpAllowedHoursCsv", ",".join(str(hour) for hour in spec.session_policy.allowed_hours_utc), False),
        ("InpExcludedContextBucket", str(filters.get("exclude_context_bucket", "")), False),
        ("InpRequiredVolatilityBucket", str(filters.get("required_volatility_bucket", "")), False),
        ("InpEntryStyle", spec.entry_style, False),
        ("InpAuditRelativePath", run_spec.audit_relative_path or "", False),
        ("InpBrokerHistoryRelativePath", run_spec.broker_history_relative_path or "", False),
        ("InpDiagnosticWindowsRelativePath", run_spec.diagnostic_windows_relative_path or "", False),
        ("InpDiagnosticTicksRelativePath", run_spec.diagnostic_ticks_relative_path or "", False),
        ("InpRuntimeSummaryRelativePath", run_spec.runtime_summary_relative_path or "", False),
        ("InpSignalTraceRelativePath", run_spec.signal_trace_relative_path or "", False),
        ("InpBrokerTimezone", "Europe/Prague", False),
    ]
    lines = [
        f"; generated by Agentic Forex for {run_spec.candidate_id} {run_spec.run_id}",
        "; authoritative tester input profile; optimization disabled for every input",
    ]
    for name, value, numeric in rows:
        if numeric:
            lines.append(f"{name}={value}||{value}||0||{value}||N")
        else:
            lines.append(f"{name}={value}")
    return "\n".join(lines) + "\n"


def _bool_profile_value(value: str | None) -> str:
    return "true" if _profile_bool_literal(value) == "true" else "false"


def _profile_float_or_default(value: str | None, default: float) -> float:
    if value is None:
        return float(default)
    try:
        return float(value)
    except ValueError:
        return float(default)


def _profile_bool_literal(value: str | None) -> str:
    truthy = {"1", "true", "yes", "on", "required"}
    return "true" if (value or "").strip().lower() in truthy else "false"


def _profile_magic_number(candidate_id: str) -> int:
    digits = "".join(character for character in candidate_id if character.isdigit())
    if not digits:
        return 240321
    return 200000 + int(digits[-5:])


def _tester_runtime_report_stem(run_spec: MT5RunSpec) -> str:
    raw_stem = f"{run_spec.candidate_id}-{run_spec.run_id}-report"
    return re.sub(r"[^A-Za-z0-9_.-]", "_", raw_stem)


def _load_spec(settings: Settings, candidate_id: str) -> StrategySpec:
    return StrategySpec.model_validate(read_json(settings.paths().reports_dir / candidate_id / "strategy_spec.json"))


def _resolve_terminal_path(settings: Settings) -> Path | None:
    for raw_path in settings.mt5_env.terminal_paths:
        candidate = Path(raw_path)
        if candidate.exists():
            return candidate
    for raw_path in settings.mt5_env.default_discovery_paths:
        candidate = Path(raw_path)
        if candidate.exists():
            return candidate
    return None


def _resolve_metaeditor_path(terminal_path: Path | None) -> Path | None:
    if terminal_path is None:
        return None
    for candidate in (terminal_path.parent / "MetaEditor64.exe", terminal_path.parent / "metaeditor64.exe"):
        if candidate.exists():
            return candidate
    return None


def _resolve_terminal_data_path(settings: Settings, terminal_path: Path | None) -> Path | None:
    if terminal_path is None:
        return None
    if settings.mt5_env.portable_mode:
        return terminal_path.parent
    terminal_root = Path.home() / "AppData" / "Roaming" / "MetaQuotes" / "Terminal"
    if not terminal_root.exists():
        return None
    broker_hint = "OANDA" if "OANDA" in terminal_path.parent.name.upper() else None
    for candidate in terminal_root.iterdir():
        if not candidate.is_dir() or candidate.name in {"Common", "Community", "Help"}:
            continue
        common_ini = candidate / "config" / "common.ini"
        if not common_ini.exists():
            continue
        payload = _read_mt5_ini(common_ini)
        if broker_hint and broker_hint in payload.upper():
            return candidate
    for candidate in terminal_root.iterdir():
        if (candidate / "MQL5").exists():
            return candidate
    return None


def _deploy_and_compile_ea(
    *,
    candidate_id: str,
    packet_source_path: Path,
    compile_target_relative_path: Path,
    terminal_data_path: Path,
    metaeditor_path: Path,
    packet_dir: Path,
) -> tuple[Path, Path, Path | None]:
    deployed_source_path = terminal_data_path / compile_target_relative_path
    compiled_ex5_path = deployed_source_path.with_suffix(".ex5")
    deployed_source_path.parent.mkdir(parents=True, exist_ok=True)
    deployed_source_path.write_text(packet_source_path.read_text(encoding="utf-8"), encoding="utf-8")
    if compiled_ex5_path.exists():
        compiled_ex5_path.unlink()
    compile_log_path = packet_dir / "compile.log"
    command = [
        str(metaeditor_path),
        f"/compile:{deployed_source_path}",
        f"/log:{compile_log_path}",
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=120)
    for _ in range(20):
        if compiled_ex5_path.exists():
            break
        time.sleep(0.25)
    resolved_log_path = compile_log_path if compile_log_path.exists() else None
    if not compiled_ex5_path.exists():
        log_excerpt = ""
        if resolved_log_path is not None:
            log_excerpt = resolved_log_path.read_text(encoding="utf-8", errors="ignore")
        stderr = completed.stderr.strip()
        stdout = completed.stdout.strip()
        details = "\n".join(part for part in [stdout, stderr, log_excerpt] if part).strip()
        raise RuntimeError(
            f"MT5 compile failed for {candidate_id} using {metaeditor_path}. "
            f"Log: {compile_log_path}. Details: {details[:2000]}"
        )
    return deployed_source_path, compiled_ex5_path, resolved_log_path


def _read_mt5_ini(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-16", "utf-16-le", "utf-16-be", "latin-1"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" in text:
            text = text.replace("\x00", "")
        return text
    return raw.decode("utf-8", errors="ignore").replace("\x00", "")


# ---------------------------------------------------------------------------
# Standalone deploy / compile / cleanup helpers
# ---------------------------------------------------------------------------


@dataclass
class DeployResult:
    candidate_id: str
    source_path: str
    deployed_mq5_path: str
    compiled_ex5_path: str
    compile_log_path: str | None
    source_hash: str
    build_hash: str


def deploy_and_compile_candidate_ea(
    settings: Settings,
    *,
    candidate_id: str,
    target_filename: str = "CandidateEA.mq5",
) -> DeployResult:
    packet_dir = settings.paths().approvals_dir / "mt5_packets" / candidate_id
    source_path = packet_dir / "CandidateEA.mq5"
    if not source_path.exists():
        raise FileNotFoundError(
            f"Packet source not found: {source_path}. "
            f"Run 'generate-mt5-packet --candidate-id {candidate_id}' first."
        )
    terminal_path = _resolve_terminal_path(settings)
    terminal_data_path = _resolve_terminal_data_path(settings, terminal_path)
    metaeditor_path = _resolve_metaeditor_path(terminal_path)
    if terminal_data_path is None:
        raise RuntimeError("Cannot resolve MT5 terminal data path. Check mt5_env config.")
    if metaeditor_path is None:
        raise RuntimeError("Cannot resolve MetaEditor path. Check MT5 installation.")

    compile_target_relative = Path(settings.mt5_env.compile_target_relative_path)
    target_relative = compile_target_relative.with_name(target_filename)

    deployed_source, compiled_ex5, compile_log = _deploy_and_compile_ea(
        candidate_id=candidate_id,
        packet_source_path=source_path,
        compile_target_relative_path=target_relative,
        terminal_data_path=terminal_data_path,
        metaeditor_path=metaeditor_path,
        packet_dir=packet_dir,
    )

    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest().upper()
    build_hash = hashlib.sha256(compiled_ex5.read_bytes()).hexdigest().upper()

    return DeployResult(
        candidate_id=candidate_id,
        source_path=str(source_path),
        deployed_mq5_path=str(deployed_source),
        compiled_ex5_path=str(compiled_ex5),
        compile_log_path=str(compile_log) if compile_log else None,
        source_hash=source_hash,
        build_hash=build_hash,
    )


@dataclass
class CleanupResult:
    kept: list[str]
    removed: list[str]
    experts_dir: str


def cleanup_mt5_experts(
    settings: Settings,
    *,
    keep_ids: list[str],
    dry_run: bool = False,
) -> CleanupResult:
    terminal_path = _resolve_terminal_path(settings)
    terminal_data_path = _resolve_terminal_data_path(settings, terminal_path)
    if terminal_data_path is None:
        raise RuntimeError("Cannot resolve MT5 terminal data path.")

    compile_target_relative = Path(settings.mt5_env.compile_target_relative_path)
    experts_dir = terminal_data_path / compile_target_relative.parent

    if not experts_dir.exists():
        raise FileNotFoundError(f"Experts directory not found: {experts_dir}")

    keep_stems = set()
    for cid in keep_ids:
        keep_stems.add(cid)
    keep_stems.add("CandidateEA")

    kept: list[str] = []
    removed: list[str] = []

    for f in sorted(experts_dir.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in (".mq5", ".ex5"):
            continue
        if f.stem in keep_stems:
            kept.append(f.name)
            continue
        if dry_run:
            removed.append(f.name)
        else:
            f.unlink()
            removed.append(f.name)

    return CleanupResult(
        kept=kept,
        removed=removed,
        experts_dir=str(experts_dir),
    )
