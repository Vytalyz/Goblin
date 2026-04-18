from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from agentic_forex.config import Settings
from agentic_forex.governance.models import (
    CandidateCompileReport,
    CandidateTriageReport,
    EASpecGenerationReport,
    MT5SmokeBacktestReport,
    RuleFormalizationReport,
)
from agentic_forex.market_data.qa import assess_market_data_quality
from agentic_forex.mt5.ea_generator import render_candidate_ea
from agentic_forex.mt5.models import MT5RunResult, MT5RunSpec
from agentic_forex.mt5.service import (
    _audit_relative_path,
    _candidate_compile_target_relative_path,
    _deploy_and_compile_ea,
    _launch_mt5_tester,
    _load_audit_frame,
    _prepare_automated_terminal_runtime,
    _resolve_audit_output_path,
    _resolve_metaeditor_path,
    _resolve_terminal_data_path,
    _resolve_terminal_path,
    _stage_existing_build_for_launch,
    _tester_ini,
    build_logic_manifest_payload,
)
from agentic_forex.nodes.toolkit import compile_strategy_spec_tool
from agentic_forex.runtime import ReadPolicy
from agentic_forex.utils.io import read_json, write_json
from agentic_forex.workflows.contracts import CandidateDraft, EASpec, RuleSpec, StrategySpec


def ensure_strategy_spec(settings: Settings, *, candidate_id: str) -> StrategySpec:
    report_dir = settings.paths().reports_dir / candidate_id
    spec_path = report_dir / "strategy_spec.json"
    if spec_path.exists():
        return StrategySpec.model_validate(read_json(spec_path))
    candidate = _load_candidate_or_recover(settings, candidate_id=candidate_id)
    payload = compile_strategy_spec_tool(
        payload=candidate.model_dump(mode="json"),
        settings=settings,
        config={},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )
    return StrategySpec.model_validate(payload)


def formalize_rule_candidate(settings: Settings, *, candidate_id: str) -> RuleFormalizationReport:
    report_dir = settings.paths().reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    candidate = _load_candidate_or_recover(settings, candidate_id=candidate_id)
    spec = ensure_strategy_spec(settings, candidate_id=candidate_id)
    rule_spec_path = report_dir / "rule_spec.json"
    rule_spec = RuleSpec(
        candidate_id=candidate_id,
        family=spec.family,
        market_hypothesis=candidate.strategy_hypothesis,
        instrument=spec.instrument,
        timeframe=spec.execution_granularity,
        session_hours_utc=list(spec.session_policy.allowed_hours_utc),
        no_trade_hours_utc=_no_trade_hours(spec.session_policy.allowed_hours_utc),
        side_policy=spec.side_policy,
        entry_trigger_formula=[*spec.setup_logic.trigger_conditions, *spec.entry_logic],
        order_type=_infer_order_type(spec),
        stop_logic=f"fixed_stop_{spec.stop_loss_pips:.2f}_pips",
        target_logic=f"fixed_target_{spec.take_profit_pips:.2f}_pips",
        timeout_logic=f"time_exit_after_{spec.holding_bars}_bars",
        spread_filter=f"max_spread_{spec.risk_envelope.max_spread_allowed_pips:.2f}_pips",
        news_event_policy=(
            f"{spec.news_policy.minimum_impact}_{spec.news_policy.blackout_minutes_before}_"
            f"{spec.news_policy.blackout_minutes_after}"
            if spec.news_policy.enabled
            else "disabled"
        ),
        max_trades=spec.risk_envelope.max_simultaneous_positions,
        cooldown_bars=max(int(spec.holding_bars // 4), 1),
        sizing_rule=spec.risk_envelope.sizing_rule,
        invalidation_rules=[
            *spec.setup_logic.trigger_conditions,
            *spec.risk_envelope.kill_switch_conditions,
        ],
        holding_bars=spec.holding_bars,
        stop_loss_pips=spec.stop_loss_pips,
        take_profit_pips=spec.take_profit_pips,
        notes=[
            f"Derived from {spec.candidate_id} strategy_spec.json.",
            *spec.notes[:5],
        ],
    )
    write_json(rule_spec_path, rule_spec.model_dump(mode="json"))
    report = RuleFormalizationReport(
        candidate_id=candidate_id,
        readiness_status="rule_spec_complete",
        economic_plausibility_passed=False,
        completeness_checks=[
            "instrument",
            "timeframe",
            "session_hours_utc",
            "entry_trigger_formula",
            "order_type",
            "stop_logic",
            "target_logic",
            "timeout_logic",
            "spread_filter",
            "news_event_policy",
            "sizing_rule",
            "invalidation_rules",
        ],
        artifact_paths={
            "candidate_path": str(report_dir / "candidate.json"),
            "strategy_spec_path": str(report_dir / "strategy_spec.json"),
            "rule_spec_path": str(rule_spec_path),
        },
    )
    write_json(report_dir / "rule_formalization_report.json", report.model_dump(mode="json"))
    return report


def generate_ea_spec(settings: Settings, *, candidate_id: str) -> EASpecGenerationReport:
    report_dir = settings.paths().reports_dir / candidate_id
    rule_spec = RuleSpec.model_validate(read_json(report_dir / "rule_spec.json"))
    spec = ensure_strategy_spec(settings, candidate_id=candidate_id)
    ea_spec_path = report_dir / "ea_spec.json"
    ea_spec = EASpec(
        candidate_id=candidate_id,
        family=spec.family,
        instrument=spec.instrument,
        timeframe=spec.execution_granularity,
        signal_inputs=[
            *rule_spec.entry_trigger_formula,
            *(filter_rule.name for filter_rule in spec.filters),
        ],
        parameter_values={
            "signal_threshold": spec.signal_threshold,
            "holding_bars": spec.holding_bars,
            "stop_loss_pips": spec.stop_loss_pips,
            "take_profit_pips": spec.take_profit_pips,
            "max_spread_allowed_pips": spec.risk_envelope.max_spread_allowed_pips,
            "max_daily_loss_pct": spec.risk_envelope.max_daily_loss_pct,
            "max_simultaneous_positions": spec.risk_envelope.max_simultaneous_positions,
        },
        order_construction={
            "order_type": rule_spec.order_type,
            "side_policy": spec.side_policy,
            "max_open_positions": spec.risk_policy.max_open_positions,
            "risk_per_trade_pct": spec.risk_policy.max_risk_per_trade_pct,
        },
        stop_target_timeout={
            "stop_logic": rule_spec.stop_logic,
            "target_logic": rule_spec.target_logic,
            "timeout_logic": rule_spec.timeout_logic,
            "stop_loss_pips": spec.stop_loss_pips,
            "take_profit_pips": spec.take_profit_pips,
            "holding_bars": spec.holding_bars,
        },
        session_filters={
            "allowed_hours_utc": rule_spec.session_hours_utc,
            "no_trade_hours_utc": rule_spec.no_trade_hours_utc,
            "spread_filter": rule_spec.spread_filter,
            "news_event_policy": rule_spec.news_event_policy,
        },
        risk_controls={
            "max_daily_loss_pct": spec.risk_envelope.max_daily_loss_pct,
            "max_spread_allowed_pips": spec.risk_envelope.max_spread_allowed_pips,
            "sizing_rule": spec.risk_envelope.sizing_rule,
            "kill_switch_conditions": spec.risk_envelope.kill_switch_conditions,
            "margin_buffer_pct": spec.risk_envelope.margin_buffer_pct,
        },
        state_machine={
            "states": ["WAIT_SIGNAL", "SUBMIT_ORDER", "MANAGE_POSITION", "COOLDOWN"],
            "cooldown_bars": rule_spec.cooldown_bars,
            "invalidation_rules": rule_spec.invalidation_rules,
        },
        source_rule_spec_path=report_dir / "rule_spec.json",
        notes=[f"Deterministic MT5 rendering contract for {candidate_id}."],
    )
    write_json(ea_spec_path, ea_spec.model_dump(mode="json"))
    plausibility_findings = minimum_economic_plausibility(
        settings, candidate_id=candidate_id, rule_spec=rule_spec, spec=spec
    )
    report = EASpecGenerationReport(
        candidate_id=candidate_id,
        readiness_status="ea_spec_complete",
        economic_plausibility_passed=not plausibility_findings,
        plausibility_findings=plausibility_findings,
        artifact_paths={
            "rule_spec_path": str(report_dir / "rule_spec.json"),
            "strategy_spec_path": str(report_dir / "strategy_spec.json"),
            "ea_spec_path": str(ea_spec_path),
        },
    )
    write_json(report_dir / "ea_spec_generation_report.json", report.model_dump(mode="json"))
    return report


def compile_ea_candidate(settings: Settings, *, candidate_id: str) -> CandidateCompileReport:
    report_dir = settings.paths().reports_dir / candidate_id
    spec = ensure_strategy_spec(settings, candidate_id=candidate_id)
    generation_report = EASpecGenerationReport.model_validate(read_json(report_dir / "ea_spec_generation_report.json"))
    throughput_dir = report_dir / "throughput"
    throughput_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"throughput-compile-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    source_path = throughput_dir / "CandidateEA.mq5"
    logic_manifest_path = throughput_dir / "logic_manifest.json"
    report_path = report_dir / "compile_report.json"
    compile_target_relative_path = _candidate_compile_target_relative_path(candidate_id, settings)

    if not generation_report.economic_plausibility_passed:
        report = CandidateCompileReport(
            candidate_id=candidate_id,
            readiness_status="ea_spec_complete",
            compile_status="failed",
            failure_classification="spec_incompleteness",
            artifact_paths={
                "ea_spec_generation_report_path": str(report_dir / "ea_spec_generation_report.json"),
                "ea_spec_path": str(report_dir / "ea_spec.json"),
                "compile_report_path": str(report_path),
            },
        )
        write_json(report_path, report.model_dump(mode="json"))
        return report

    audit_relative_path = _audit_relative_path(candidate_id, run_id, settings)
    rendered_source = render_candidate_ea(
        spec,
        audit_relative_path=audit_relative_path,
        packet_run_id=run_id,
        broker_timezone=settings.policy.ftmo_timezone,
    )
    smoke_expected_signals = _smoke_expected_signal_frame(settings, spec)
    logic_manifest = build_logic_manifest_payload(
        spec=spec,
        rendered_source=rendered_source,
        expected_signal_frame=smoke_expected_signals,
        settings=settings,
        source_artifact_paths={
            "candidate_path": report_dir / "candidate.json",
            "strategy_spec_path": report_dir / "strategy_spec.json",
            "rule_spec_path": report_dir / "rule_spec.json",
            "ea_spec_path": report_dir / "ea_spec.json",
        },
    )
    logic_manifest_hash = str(logic_manifest["logic_manifest_hash"])
    source_path.write_text(rendered_source, encoding="utf-8")
    write_json(
        logic_manifest_path,
        {
            **logic_manifest,
            "candidate_id": candidate_id,
            "stage": "throughput_compile",
            "run_id": run_id,
            "ea_source_path": str(source_path),
        },
    )
    terminal_path = _resolve_terminal_path(settings)
    base_terminal_data_path = _resolve_terminal_data_path(settings, terminal_path)
    base_metaeditor_path = _resolve_metaeditor_path(terminal_path)
    terminal_path, terminal_data_path, metaeditor_path = _prepare_automated_terminal_runtime(
        settings,
        terminal_path=terminal_path,
        terminal_data_path=base_terminal_data_path,
    )

    try:
        if terminal_data_path is None or metaeditor_path is None:
            raise RuntimeError("metaeditor_or_terminal_data_unavailable")
        try:
            deployed_source_path, compiled_ex5_path, compile_log_path = _deploy_and_compile_ea(
                candidate_id=candidate_id,
                packet_source_path=source_path,
                compile_target_relative_path=compile_target_relative_path,
                terminal_data_path=terminal_data_path,
                metaeditor_path=metaeditor_path,
                packet_dir=throughput_dir,
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
                packet_source_path=source_path,
                compile_target_relative_path=compile_target_relative_path,
                terminal_data_path=base_terminal_data_path,
                metaeditor_path=base_metaeditor_path,
                packet_dir=throughput_dir,
            )
            deployed_source_path, compiled_ex5_path = _stage_existing_build_for_launch(
                source_path=base_source_path,
                compiled_ex5_path=base_ex5_path,
                compile_target_relative_path=compile_target_relative_path,
                terminal_data_path=terminal_data_path,
            )
    except Exception as exc:  # noqa: BLE001
        classification = _classify_compile_failure(str(exc))
        report = CandidateCompileReport(
            candidate_id=candidate_id,
            readiness_status="ea_spec_complete",
            compile_status="failed",
            failure_classification=classification,
            logic_manifest_hash=logic_manifest_hash,
            artifact_paths={
                "ea_spec_path": str(report_dir / "ea_spec.json"),
                "strategy_spec_path": str(report_dir / "strategy_spec.json"),
                "ea_source_path": str(source_path),
                "logic_manifest_path": str(logic_manifest_path),
                "compile_report_path": str(report_path),
            },
        )
        write_json(report_path, report.model_dump(mode="json"))
        return report

    report = CandidateCompileReport(
        candidate_id=candidate_id,
        readiness_status="ea_compiled",
        compile_status="passed",
        logic_manifest_hash=logic_manifest_hash,
        artifact_paths={
            "ea_spec_path": str(report_dir / "ea_spec.json"),
            "strategy_spec_path": str(report_dir / "strategy_spec.json"),
            "ea_source_path": str(source_path),
            "deployed_source_path": str(deployed_source_path),
            "compiled_ex5_path": str(compiled_ex5_path),
            "compile_log_path": str(compile_log_path) if compile_log_path else "",
            "logic_manifest_path": str(logic_manifest_path),
            "compile_report_path": str(report_path),
        },
    )
    write_json(report_path, report.model_dump(mode="json"))
    return report


def run_mt5_backtest_smoke(settings: Settings, *, candidate_id: str) -> MT5SmokeBacktestReport:
    report_dir = settings.paths().reports_dir / candidate_id
    spec = ensure_strategy_spec(settings, candidate_id=candidate_id)
    compile_report = CandidateCompileReport.model_validate(read_json(report_dir / "compile_report.json"))
    report_path = report_dir / "mt5_smoke_report.json"
    if compile_report.compile_status != "passed":
        report = MT5SmokeBacktestReport(
            candidate_id=candidate_id,
            readiness_status="ea_compiled",
            smoke_status="failed",
            failure_classification="tester_configuration_failure",
            trade_count=0,
            artifact_paths={
                "compile_report_path": str(report_dir / "compile_report.json"),
                "mt5_smoke_report_path": str(report_path),
            },
        )
        write_json(report_path, report.model_dump(mode="json"))
        return report

    throughput_dir = report_dir / "throughput"
    throughput_dir.mkdir(parents=True, exist_ok=True)
    terminal_path = _resolve_terminal_path(settings)
    base_terminal_data_path = _resolve_terminal_data_path(settings, terminal_path)
    base_metaeditor_path = _resolve_metaeditor_path(terminal_path)
    terminal_path, terminal_data_path, _ = _prepare_automated_terminal_runtime(
        settings,
        terminal_path=terminal_path,
        terminal_data_path=base_terminal_data_path,
    )
    run_id = f"throughput-smoke-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    run_dir = report_dir / "mt5_smoke" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logic_manifest_path = run_dir / "logic_manifest.json"
    audit_relative_path = _audit_relative_path(candidate_id, run_id, settings)
    audit_output_path = _resolve_audit_output_path(settings, terminal_data_path, audit_relative_path)
    source_path = run_dir / "CandidateEA.mq5"
    compile_target_relative_path = _candidate_compile_target_relative_path(candidate_id, settings)
    rendered_source = render_candidate_ea(
        spec,
        audit_relative_path=audit_relative_path,
        packet_run_id=run_id,
        broker_timezone=settings.policy.ftmo_timezone,
    )
    smoke_expected_signals = _smoke_expected_signal_frame(settings, spec)
    logic_manifest = build_logic_manifest_payload(
        spec=spec,
        rendered_source=rendered_source,
        expected_signal_frame=smoke_expected_signals,
        settings=settings,
        source_artifact_paths={
            "candidate_path": report_dir / "candidate.json",
            "strategy_spec_path": report_dir / "strategy_spec.json",
            "rule_spec_path": report_dir / "rule_spec.json",
            "ea_spec_path": report_dir / "ea_spec.json",
            "compile_manifest_path": Path(compile_report.artifact_paths.get("logic_manifest_path", ""))
            if compile_report.artifact_paths.get("logic_manifest_path")
            else None,
        },
    )
    logic_manifest_hash = str(logic_manifest["logic_manifest_hash"])
    source_path.write_text(rendered_source, encoding="utf-8")
    write_json(
        logic_manifest_path,
        {
            **logic_manifest,
            "candidate_id": candidate_id,
            "stage": "throughput_smoke",
            "run_id": run_id,
            "ea_source_path": str(source_path),
            "compile_logic_manifest_hash": compile_report.logic_manifest_hash,
        },
    )
    try:
        if terminal_data_path is None:
            raise RuntimeError("terminal_data_path_unavailable")
        runtime_metaeditor_path = _resolve_metaeditor_path(terminal_path)
        if runtime_metaeditor_path is None:
            raise RuntimeError("metaeditor_path_unavailable")
        try:
            staged_source_path, staged_ex5_path, compile_log_path = _deploy_and_compile_ea(
                candidate_id=candidate_id,
                packet_source_path=source_path,
                compile_target_relative_path=compile_target_relative_path,
                terminal_data_path=terminal_data_path,
                metaeditor_path=runtime_metaeditor_path,
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
                candidate_id=candidate_id,
                packet_source_path=source_path,
                compile_target_relative_path=compile_target_relative_path,
                terminal_data_path=base_terminal_data_path,
                metaeditor_path=base_metaeditor_path,
                packet_dir=run_dir,
            )
            staged_source_path, staged_ex5_path = _stage_existing_build_for_launch(
                source_path=base_source_path,
                compiled_ex5_path=base_ex5_path,
                compile_target_relative_path=compile_target_relative_path,
                terminal_data_path=terminal_data_path,
            )
    except Exception:
        report = MT5SmokeBacktestReport(
            candidate_id=candidate_id,
            readiness_status="ea_compiled",
            smoke_status="failed",
            failure_classification="tester_configuration_failure",
            trade_count=0,
            logic_manifest_hash=logic_manifest_hash,
            artifact_paths={
                "compile_report_path": str(report_dir / "compile_report.json"),
                "ea_source_path": str(source_path),
                "logic_manifest_path": str(logic_manifest_path),
                "mt5_smoke_report_path": str(report_path),
            },
        )
        write_json(report_path, report.model_dump(mode="json"))
        return report
    run_spec = MT5RunSpec(
        candidate_id=candidate_id,
        run_id=run_id,
        install_id=settings.mt5_env.terminal_install_ids[0]
        if settings.mt5_env.terminal_install_ids
        else "mt5_practice_01",
        terminal_path=str(terminal_path) if terminal_path else None,
        portable_mode=bool(terminal_path and terminal_data_path and terminal_path.parent == terminal_data_path),
        tester_mode=settings.mt5_env.tester_mode,
        tick_mode=settings.mt5_env.tester_mode,
        spread_behavior="configured_by_strategy_tester",
        allow_live_trading=False,
        shutdown_terminal=settings.mt5_env.shutdown_terminal,
        config_path=run_dir / "tester_config.ini",
        report_path=run_dir / "tester_report.htm",
        compile_target_path=staged_source_path,
        compile_request_path=run_dir / "compile_request.json",
        launch_request_path=run_dir / "launch_request.json",
        run_dir=run_dir,
        audit_relative_path=audit_relative_path,
        audit_output_path=audit_output_path,
        tester_timeout_seconds=settings.mt5_env.parity_launch_timeout_seconds,
    )
    run_spec.config_path.write_text(
        _tester_ini(candidate_id, run_spec, settings, spec, _smoke_expected_signal_frame(settings, spec)),
        encoding="utf-8",
    )
    write_json(
        run_spec.launch_request_path,
        {
            "candidate_id": candidate_id,
            "run_id": run_id,
            "ea_source_path": str(source_path),
            "compile_log_path": str(compile_log_path) if compile_log_path else "",
            "audit_relative_path": audit_relative_path,
            "audit_output_path": str(audit_output_path) if audit_output_path else "",
            "logic_manifest_hash": logic_manifest_hash,
            "compile_logic_manifest_hash": compile_report.logic_manifest_hash,
        },
    )

    run_result = _launch_mt5_tester(run_spec, settings)
    smoke_report = _build_smoke_report(
        settings,
        candidate_id=candidate_id,
        run_result=run_result,
        report_path=report_path,
        logic_manifest_hash=logic_manifest_hash,
        logic_manifest_path=logic_manifest_path,
    )
    return smoke_report


def triage_candidate(
    settings: Settings,
    *,
    candidate_id: str,
    compile_retries_used: int,
    compile_retry_cap: int,
    smoke_retries_used: int,
    smoke_retry_cap: int,
    ea_spec_rewrites_used: int,
    ea_spec_rewrite_cap: int,
) -> CandidateTriageReport:
    report_dir = settings.paths().reports_dir / candidate_id
    generation_report = (
        EASpecGenerationReport.model_validate(read_json(report_dir / "ea_spec_generation_report.json"))
        if (report_dir / "ea_spec_generation_report.json").exists()
        else None
    )
    compile_report = (
        CandidateCompileReport.model_validate(read_json(report_dir / "compile_report.json"))
        if (report_dir / "compile_report.json").exists()
        else None
    )
    smoke_report = (
        MT5SmokeBacktestReport.model_validate(read_json(report_dir / "mt5_smoke_report.json"))
        if (report_dir / "mt5_smoke_report.json").exists()
        else None
    )

    if (
        compile_report
        and compile_report.compile_status == "passed"
        and smoke_report
        and smoke_report.smoke_status == "passed"
    ):
        classification = "send_to_research_lane"
        readiness_status = "reviewable_candidate"
        rationale = (
            f"{candidate_id} completed rule formalization, EA specification, MT5 compile, and smoke backtest "
            "successfully. It is reviewable and may be admitted into a research promotion lane."
        )
    elif generation_report and not generation_report.economic_plausibility_passed:
        classification = "discard"
        readiness_status = "ea_spec_complete"
        rationale = (
            f"{candidate_id} failed the minimum economic plausibility gate, so it should be discarded before compile."
        )
    elif compile_report and compile_report.compile_status == "failed":
        classification = "discard" if compile_retries_used >= compile_retry_cap else "refine"
        readiness_status = "ea_spec_complete"
        rationale = (
            f"{candidate_id} failed MT5 compile with {compile_report.failure_classification or 'unknown_compile_failure'}. "
            f"{'Retry budget is exhausted.' if classification == 'discard' else 'A bounded rewrite remains allowed.'}"
        )
    elif smoke_report and smoke_report.smoke_status == "failed":
        classification = "discard" if smoke_retries_used >= smoke_retry_cap else "refine"
        readiness_status = "ea_compiled"
        rationale = (
            f"{candidate_id} compiled but failed MT5 smoke with "
            f"{smoke_report.failure_classification or 'unknown_smoke_failure'}. "
            f"{'Retry budget is exhausted.' if classification == 'discard' else 'A bounded smoke retry remains allowed.'}"
        )
    else:
        classification = "discard" if ea_spec_rewrites_used >= ea_spec_rewrite_cap else "refine"
        readiness_status = "rule_spec_complete"
        rationale = (
            f"{candidate_id} has incomplete throughput evidence. "
            f"{'Rewrite budget is exhausted.' if classification == 'discard' else 'A bounded reformulation remains allowed.'}"
        )

    triage_report = CandidateTriageReport(
        candidate_id=candidate_id,
        readiness_status=readiness_status,
        classification=classification,
        rationale=rationale,
        compile_status=compile_report.compile_status if compile_report else None,
        smoke_status=smoke_report.smoke_status if smoke_report else None,
        artifact_paths={
            "rule_spec_path": str(report_dir / "rule_spec.json") if (report_dir / "rule_spec.json").exists() else "",
            "ea_spec_path": str(report_dir / "ea_spec.json") if (report_dir / "ea_spec.json").exists() else "",
            "compile_report_path": str(report_dir / "compile_report.json")
            if (report_dir / "compile_report.json").exists()
            else "",
            "mt5_smoke_report_path": str(report_dir / "mt5_smoke_report.json")
            if (report_dir / "mt5_smoke_report.json").exists()
            else "",
            "triage_report_path": str(report_dir / "triage_report.json"),
        },
    )
    write_json(report_dir / "triage_report.json", triage_report.model_dump(mode="json"))
    return triage_report


def minimum_economic_plausibility(
    settings: Settings,
    *,
    candidate_id: str,
    rule_spec: RuleSpec,
    spec: StrategySpec,
) -> list[str]:
    findings: list[str] = []
    market_quality = _load_market_quality(settings, instrument=spec.instrument, granularity=spec.execution_granularity)
    spread_reference = market_quality.get("spread_p95_pips") or market_quality.get("spread_median_pips") or 1.2
    if spec.take_profit_pips <= float(spread_reference) * 1.5:
        findings.append("modeled edge horizon is too small relative to recent spread conditions")
    if spec.stop_loss_pips <= float(spread_reference):
        findings.append("stop geometry is tighter than the recent spread envelope")
    if not rule_spec.session_hours_utc:
        findings.append("session choice is missing for an intraday strategy")
    if rule_spec.max_trades <= 0 or not rule_spec.sizing_rule.strip():
        findings.append("sizing or max trade controls are missing")
    if spec.holding_bars <= 0 or spec.holding_bars > 720:
        findings.append("holding period is structurally unrealistic for the declared style")
    if spec.risk_envelope.max_spread_allowed_pips <= 0 or spec.risk_envelope.max_daily_loss_pct <= 0:
        findings.append("risk envelope is incomplete")
    if spec.family == "scalping" and len(rule_spec.session_hours_utc) > 10:
        findings.append("session exposure is too broad for a scalping-style candidate")
    return findings


def _smoke_report_trade_count(tester_report_path: Path | None) -> int:
    if tester_report_path is None or not tester_report_path.exists():
        return -1
    try:
        raw = tester_report_path.read_bytes()
    except OSError:
        return -1
    payload = ""
    for encoding in ("utf-16", "utf-8", "cp1252", "latin-1"):
        try:
            payload = raw.decode(encoding)
            if "Total Trades" in payload:
                break
        except UnicodeDecodeError:
            continue
    if not payload:
        return -1
    match = re.search(r"Total Trades:</td>\s*<td[^>]*><b>(\d+)</b>", payload, flags=re.IGNORECASE)
    if not match:
        return -1
    try:
        return int(match.group(1))
    except ValueError:
        return -1


def _load_candidate_or_recover(settings: Settings, *, candidate_id: str) -> CandidateDraft:
    report_dir = settings.paths().reports_dir / candidate_id
    candidate_path = report_dir / "candidate.json"
    if candidate_path.exists():
        return CandidateDraft.model_validate(read_json(candidate_path))
    spec = StrategySpec.model_validate(read_json(report_dir / "strategy_spec.json"))
    candidate = CandidateDraft(
        candidate_id=spec.candidate_id,
        family=spec.family,
        title=f"{spec.family.replace('_', ' ').title()} Candidate {spec.candidate_id}",
        thesis="Recovered candidate context from strategy specification.",
        source_citations=spec.source_citations,
        strategy_hypothesis="Recovered deterministic MT5 throughput candidate.",
        market_context={
            "session_focus": spec.session_policy.name,
            "volatility_preference": "moderate",
            "directional_bias": spec.side_policy,
            "execution_notes": spec.session_policy.notes,
            "allowed_hours_utc": spec.session_policy.allowed_hours_utc,
        },
        setup_summary=spec.setup_logic.summary,
        entry_summary=" ".join(spec.entry_logic),
        exit_summary=" ".join(spec.exit_logic),
        risk_summary="Recovered from strategy specification.",
        notes=spec.notes,
        quality_flags=["recovered_candidate_context"],
        entry_style=spec.entry_style,
        holding_bars=spec.holding_bars,
        signal_threshold=spec.signal_threshold,
        stop_loss_pips=spec.stop_loss_pips,
        take_profit_pips=spec.take_profit_pips,
    )
    write_json(candidate_path, candidate.model_dump(mode="json"))
    return candidate


def _build_smoke_report(
    settings: Settings,
    *,
    candidate_id: str,
    run_result: MT5RunResult,
    report_path: Path,
    logic_manifest_hash: str | None = None,
    logic_manifest_path: Path | None = None,
) -> MT5SmokeBacktestReport:
    if run_result.launch_status != "completed":
        report = MT5SmokeBacktestReport(
            candidate_id=candidate_id,
            readiness_status="ea_compiled",
            smoke_status="failed",
            failure_classification="tester_configuration_failure",
            trade_count=0,
            logic_manifest_hash=logic_manifest_hash,
            artifact_paths={
                "launch_status_path": str(run_result.launch_status_path),
                "logic_manifest_path": str(logic_manifest_path) if logic_manifest_path else "",
                "mt5_smoke_report_path": str(report_path),
            },
        )
        write_json(report_path, report.model_dump(mode="json"))
        return report

    if run_result.audit_csv_path is None or not run_result.audit_csv_path.exists():
        report_trade_count = _smoke_report_trade_count(run_result.tester_report_path)
        if report_trade_count == 0:
            failure_classification = "no_trades_generated"
        else:
            failure_classification = (
                "tester_configuration_failure" if run_result.tester_report_path is None else "artifact_write_failure"
            )
        report = MT5SmokeBacktestReport(
            candidate_id=candidate_id,
            readiness_status="ea_compiled",
            smoke_status="failed",
            failure_classification=failure_classification,
            trade_count=max(report_trade_count, 0),
            logic_manifest_hash=logic_manifest_hash,
            artifact_paths={
                "launch_status_path": str(run_result.launch_status_path),
                "tester_report_path": str(run_result.tester_report_path) if run_result.tester_report_path else "",
                "logic_manifest_path": str(logic_manifest_path) if logic_manifest_path else "",
                "mt5_smoke_report_path": str(report_path),
            },
        )
        write_json(report_path, report.model_dump(mode="json"))
        return report

    audit_frame = _load_audit_frame(run_result.audit_csv_path)
    if bool(audit_frame.attrs.get("malformed")):
        report = MT5SmokeBacktestReport(
            candidate_id=candidate_id,
            readiness_status="ea_compiled",
            smoke_status="failed",
            failure_classification="runtime_ea_error",
            trade_count=0,
            logic_manifest_hash=logic_manifest_hash,
            artifact_paths={
                "launch_status_path": str(run_result.launch_status_path),
                "audit_csv_path": str(run_result.audit_csv_path),
                "logic_manifest_path": str(logic_manifest_path) if logic_manifest_path else "",
                "mt5_smoke_report_path": str(report_path),
            },
        )
        write_json(report_path, report.model_dump(mode="json"))
        return report

    if audit_frame.empty:
        report = MT5SmokeBacktestReport(
            candidate_id=candidate_id,
            readiness_status="ea_compiled",
            smoke_status="failed",
            failure_classification="no_trades_generated",
            trade_count=0,
            logic_manifest_hash=logic_manifest_hash,
            artifact_paths={
                "launch_status_path": str(run_result.launch_status_path),
                "audit_csv_path": str(run_result.audit_csv_path),
                "logic_manifest_path": str(logic_manifest_path) if logic_manifest_path else "",
                "mt5_smoke_report_path": str(report_path),
            },
        )
        write_json(report_path, report.model_dump(mode="json"))
        return report

    if ((audit_frame["entry_price"] <= 0).any()) or ((audit_frame["exit_price"] <= 0).any()):
        report = MT5SmokeBacktestReport(
            candidate_id=candidate_id,
            readiness_status="ea_compiled",
            smoke_status="failed",
            failure_classification="invalid_order_construction",
            trade_count=int(len(audit_frame)),
            logic_manifest_hash=logic_manifest_hash,
            artifact_paths={
                "launch_status_path": str(run_result.launch_status_path),
                "audit_csv_path": str(run_result.audit_csv_path),
                "logic_manifest_path": str(logic_manifest_path) if logic_manifest_path else "",
                "mt5_smoke_report_path": str(report_path),
            },
        )
        write_json(report_path, report.model_dump(mode="json"))
        return report

    report = MT5SmokeBacktestReport(
        candidate_id=candidate_id,
        readiness_status="mt5_backtest_executed",
        smoke_status="passed",
        trade_count=int(len(audit_frame)),
        logic_manifest_hash=logic_manifest_hash,
        artifact_paths={
            "launch_status_path": str(run_result.launch_status_path),
            "tester_report_path": str(run_result.tester_report_path) if run_result.tester_report_path else "",
            "audit_csv_path": str(run_result.audit_csv_path),
            "logic_manifest_path": str(logic_manifest_path) if logic_manifest_path else "",
            "mt5_smoke_report_path": str(report_path),
        },
    )
    write_json(report_path, report.model_dump(mode="json"))
    return report


def _classify_compile_failure(message: str) -> str:
    normalized = message.lower()
    if "metaeditor_or_terminal_data_unavailable" in normalized:
        return "indicator_dependency_failure"
    if "undeclared" in normalized or "syntax" in normalized or "compile failed" in normalized:
        return "codegen_defect"
    if "cannot open file" in normalized or "indicator" in normalized:
        return "indicator_dependency_failure"
    if "parameter" in normalized or "schema" in normalized:
        return "parameter_schema_failure"
    if "state" in normalized:
        return "state_machine_defect"
    if "unsupported" in normalized:
        return "unsupported_mt5_primitive"
    return "codegen_defect"


def _load_market_quality(settings: Settings, *, instrument: str, granularity: str) -> dict[str, float]:
    report_path = settings.paths().market_quality_reports_dir / f"{instrument.lower()}_{granularity.lower()}.json"
    if report_path.exists():
        payload = read_json(report_path)
        return {
            "spread_median_pips": float(payload.get("spread_median_pips") or 0.0),
            "spread_p95_pips": float(payload.get("spread_p95_pips") or 0.0),
        }
    try:
        payload = assess_market_data_quality(settings, instrument=instrument, granularity=granularity).model_dump(
            mode="json"
        )
    except Exception:  # noqa: BLE001
        return {"spread_median_pips": 0.8, "spread_p95_pips": 1.2}
    return {
        "spread_median_pips": float(payload.get("spread_median_pips") or 0.0),
        "spread_p95_pips": float(payload.get("spread_p95_pips") or 0.0),
    }


def _infer_order_type(spec: StrategySpec) -> str:
    entry_style = spec.entry_style.lower()
    if "breakout" in entry_style:
        return "stop"
    if "pullback" in entry_style or "reversion" in entry_style or "fade" in entry_style:
        return "market"
    if "reclaim" in entry_style or "retest" in entry_style:
        return "limit"
    return "market"


def _no_trade_hours(allowed_hours: list[int]) -> list[int]:
    if not allowed_hours:
        return []
    return [hour for hour in range(24) if hour not in set(allowed_hours)]


def _smoke_expected_signal_frame(settings: Settings, spec: StrategySpec) -> pd.DataFrame:
    parquet_path = (
        settings.paths().normalized_research_dir
        / f"{spec.instrument.lower()}_{spec.execution_granularity.lower()}.parquet"
    )
    if parquet_path.exists():
        try:
            frame = pd.read_parquet(parquet_path, columns=["timestamp_utc"])
            if not frame.empty:
                timestamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
                start = timestamps.min().to_pydatetime().astimezone(UTC)
                end = timestamps.max().to_pydatetime().astimezone(UTC)
                return pd.DataFrame.from_records(
                    [
                        {
                            "timestamp_utc": start,
                            "exit_timestamp_utc": end,
                            "side": "long",
                            "entry_price": 1.0,
                            "exit_price": 1.0,
                            "pnl_pips": 0.0,
                            "candidate_id": spec.candidate_id,
                        }
                    ]
                )
        except Exception:  # noqa: BLE001
            pass
    now = datetime.now(UTC)
    return pd.DataFrame.from_records(
        [
            {
                "timestamp_utc": now,
                "exit_timestamp_utc": now,
                "side": "long",
                "entry_price": 1.0,
                "exit_price": 1.0,
                "pnl_pips": 0.0,
                "candidate_id": spec.candidate_id,
            }
        ]
    )
