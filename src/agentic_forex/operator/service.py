from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections import Counter, defaultdict
from csv import DictReader
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from agentic_forex.campaigns import (
    run_autonomous_manager,
    run_governed_loop,
    run_next_step,
    run_portfolio_cycle,
    run_program_loop,
)
from agentic_forex.config import Settings
from agentic_forex.experiments.service import compare_experiments
from agentic_forex.goblin.controls import enforce_strategy_governance, write_strategy_methodology_audit
from agentic_forex.governance.control_plane import policy_snapshot_hash
from agentic_forex.operator.models import (
    CandidateBranchAuditRecord,
    CandidateBranchAuditReport,
    CandidateWindowDensityAuditRecord,
    CandidateWindowDensityAuditReport,
    CandidateWindowDensityHourRecord,
    CandidateWindowDensityPhaseRecord,
    CandidateWindowDensityWalkForwardRecord,
    CapabilityCatalogEntry,
    CapabilityManifest,
    CapabilityManifestEntry,
    CapabilitySyncReport,
    GovernedActionInspection,
    GovernedActionManifest,
    OperatorContractFinding,
    OperatorContractReport,
    OperatorStateExport,
    QueueCampaignSnapshot,
    QueueLaneSnapshot,
    QueueSnapshotReport,
)
from agentic_forex.utils.io import read_json, write_json


def sync_codex_capabilities(
    settings: Settings,
    *,
    run_id: str | None = None,
    session: requests.Session | None = None,
) -> CapabilitySyncReport:
    manifest_path = settings.paths().config_dir / settings.codex_operator.capability_manifest_filename
    manifest = _load_capability_manifest(manifest_path)
    resolved_run_id = run_id or f"capability-sync-{_timestamp_token()}"
    trace_dir = settings.paths().codex_operator_traces_dir / resolved_run_id
    trace_dir.mkdir(parents=True, exist_ok=True)
    session = session or requests.Session()

    entries: list[CapabilityCatalogEntry] = []
    for source in manifest.sources:
        if source.source_kind == "official_doc":
            entry = _sync_official_doc_entry(settings, source=source, trace_dir=trace_dir, session=session)
        else:
            entry = _sync_local_surface_entry(settings, source=source, trace_dir=trace_dir)
        entries.append(entry)

    catalog_payload = {
        "generated_utc": _utc_now(),
        "run_id": resolved_run_id,
        "sources": [entry.model_dump(mode="json") for entry in entries],
    }
    write_json(settings.paths().capability_catalog_path, catalog_payload)
    settings.paths().capability_index_path.write_text(_render_capability_index(entries), encoding="utf-8")

    report = CapabilitySyncReport(
        run_id=resolved_run_id,
        manifest_path=manifest_path,
        catalog_path=settings.paths().capability_catalog_path,
        index_path=settings.paths().capability_index_path,
        synced_entries=sum(1 for entry in entries if entry.sync_status == "synced"),
        failed_entries=sum(1 for entry in entries if entry.sync_status == "failed"),
        entries=entries,
        report_path=trace_dir / "capability_sync_report.json",
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    (trace_dir / "capability_sync_report.md").write_text(_render_capability_report(report), encoding="utf-8")
    return report


def build_queue_snapshot(
    settings: Settings,
    *,
    family: str | None = None,
    report_name: str | None = None,
) -> QueueSnapshotReport:
    pending_lanes: list[QueueLaneSnapshot] = []
    for lane in settings.program.approved_lanes:
        if family and lane.family != family:
            continue
        report_dir = settings.paths().reports_dir / lane.seed_candidate_id
        seed_exists = (report_dir / "candidate.json").exists() or (report_dir / "strategy_spec.json").exists()
        pending_lanes.append(
            QueueLaneSnapshot(
                lane_id=lane.lane_id,
                family=lane.family,
                hypothesis_class=lane.hypothesis_class,
                queue_kind=lane.queue_kind,
                seed_candidate_id=lane.seed_candidate_id,
                seed_exists=seed_exists,
            )
        )

    campaign_rows: list[QueueCampaignSnapshot] = []
    for state_path in sorted(settings.paths().campaigns_dir.glob("*/state.json")):
        payload = read_json(state_path)
        if family and str(payload.get("family") or "") != family:
            continue
        campaign_rows.append(
            QueueCampaignSnapshot(
                campaign_id=str(payload.get("campaign_id") or state_path.parent.name),
                family=str(payload.get("family") or ""),
                status=str(payload.get("status") or "unknown"),
                stop_reason=payload.get("stop_reason"),
                updated_utc=str(payload.get("updated_utc") or ""),
            )
        )
    campaign_rows.sort(key=lambda item: item.updated_utc, reverse=True)

    report_path = settings.paths().operator_reports_dir / (report_name or f"queue_snapshot-{_timestamp_token()}.json")
    report = QueueSnapshotReport(
        family_filter=family,
        pending_lanes=pending_lanes,
        recent_campaigns=campaign_rows[:10],
        recent_program_reports=_recent_report_paths(settings.paths().program_loops_dir),
        recent_manager_reports=_recent_report_paths(settings.paths().autonomous_manager_dir),
        report_path=report_path,
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    return report


def export_operator_state(
    settings: Settings,
    *,
    run_id: str | None = None,
    family: str | None = None,
) -> OperatorStateExport:
    queue_report = build_queue_snapshot(
        settings,
        family=family,
        report_name=f"queue_snapshot-{(run_id or _timestamp_token())}.json",
    )
    resolved_run_id = run_id or f"operator-state-{_timestamp_token()}"
    automation_specs = _load_automation_specs(settings)
    capability_catalog_path = (
        settings.paths().capability_catalog_path if settings.paths().capability_catalog_path.exists() else None
    )

    report = OperatorStateExport(
        run_id=resolved_run_id,
        policy_snapshot_hash=policy_snapshot_hash(settings),
        llm_provider=settings.llm.provider,
        planning_mode=settings.llm.planning_mode,
        queue_snapshot_path=queue_report.report_path,
        queue_snapshot=queue_report.model_dump(mode="json"),
        capability_catalog_path=capability_catalog_path,
        codex_assets={
            "codex_config_path": str(settings.paths().codex_dir / "config.toml"),
            "codex_agent_files": sorted(path.name for path in settings.paths().codex_agents_dir.glob("*.toml")),
            "repo_skill_dirs": sorted(
                path.name for path in settings.paths().repo_agent_skills_dir.glob("*") if path.is_dir()
            ),
            "rules_file": str(Path(settings.codex_operator.repo_rules_file)),
        },
        automation_specs=automation_specs,
        portfolio_slots=[slot.model_dump(mode="json") for slot in settings.portfolio.slots],
        report_path=settings.paths().operator_reports_dir / f"{resolved_run_id}.json",
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    return report


def audit_candidate_branches(
    settings: Settings,
    *,
    candidate_ids: list[str],
    next_family_hint: str | None = None,
) -> CandidateBranchAuditReport:
    if not candidate_ids:
        raise ValueError("At least one candidate id is required for a branch audit.")

    comparison = compare_experiments(settings, candidate_ids=candidate_ids)
    comparison_records = {record.candidate_id: record for record in comparison.records}
    records: list[CandidateBranchAuditRecord] = []
    for candidate_id in candidate_ids:
        review_packet_path = settings.paths().reports_dir / candidate_id / "review_packet.json"
        robustness_report_path = settings.paths().reports_dir / candidate_id / "robustness_report.json"
        review_payload = read_json(review_packet_path)
        robustness_payload = read_json(robustness_report_path)
        diagnostic_payload, diagnostic_path = _latest_next_step_report_for_candidate(settings, candidate_id)
        comparison_record = comparison_records.get(candidate_id)
        metrics = dict(review_payload.get("metrics") or {})
        blocked_reasons = list(robustness_payload.get("warnings") or [])
        if diagnostic_payload:
            blocked_reasons.extend(list((diagnostic_payload.get("candidate_reports") or [{}])[0].get("notes") or []))
        branch_score = _branch_audit_score(
            trade_count=int(metrics.get("trade_count") or 0),
            oos_profit_factor=float(metrics.get("out_of_sample_profit_factor") or 0.0),
            expectancy_pips=float(metrics.get("expectancy_pips") or 0.0),
            stressed_profit_factor=float((metrics.get("stress_scenarios") or [{}])[-1].get("profit_factor") or 0.0),
            stress_passed=bool(metrics.get("stress_passed")),
            walk_forward_ok=bool(robustness_payload.get("walk_forward_ok")),
            auto_continue_allowed=bool(diagnostic_payload.get("auto_continue_allowed"))
            if diagnostic_payload
            else False,
            supported_slice_count=len(
                (diagnostic_payload.get("candidate_reports") or [{}])[0].get("supported_slices") or []
            )
            if diagnostic_payload
            else 0,
            trial_count_family=int(robustness_payload.get("trial_count_family") or 0),
        )
        candidate_paths = {
            "review_packet_path": str(review_packet_path),
            "robustness_report_path": str(robustness_report_path),
        }
        if diagnostic_path:
            candidate_paths["next_step_report_path"] = str(diagnostic_path)
        record = CandidateBranchAuditRecord(
            candidate_id=candidate_id,
            family=str(metrics.get("family") or (comparison_record.family if comparison_record else "")),
            entry_style=str(comparison_record.entry_style if comparison_record else ""),
            trade_count=int(metrics.get("trade_count") or 0),
            profit_factor=float(metrics.get("profit_factor") or 0.0),
            out_of_sample_profit_factor=float(metrics.get("out_of_sample_profit_factor") or 0.0),
            expectancy_pips=float(metrics.get("expectancy_pips") or 0.0),
            max_drawdown_pct=float(metrics.get("max_drawdown_pct") or 0.0),
            stressed_profit_factor=float((metrics.get("stress_scenarios") or [{}])[-1].get("profit_factor") or 0.0),
            stress_passed=bool(metrics.get("stress_passed")),
            walk_forward_ok=bool(robustness_payload.get("walk_forward_ok")),
            readiness=str(review_payload.get("readiness") or "unreviewed"),
            approval_recommendation=str(review_payload.get("approval_recommendation") or "not_reviewed"),
            trial_count_family=int(robustness_payload.get("trial_count_family") or 0),
            trial_count_candidate=int(robustness_payload.get("trial_count_candidate") or 0),
            diagnostic_stop_reason=str(diagnostic_payload.get("stop_reason")) if diagnostic_payload else None,
            transition_status=str(diagnostic_payload.get("transition_status")) if diagnostic_payload else None,
            auto_continue_allowed=bool(diagnostic_payload.get("auto_continue_allowed"))
            if diagnostic_payload
            else False,
            supported_slice_count=len(
                (diagnostic_payload.get("candidate_reports") or [{}])[0].get("supported_slices") or []
            )
            if diagnostic_payload
            else 0,
            recommended_mutation=((diagnostic_payload.get("candidate_reports") or [{}])[0].get("recommended_mutation"))
            if diagnostic_payload
            else None,
            diagnostic_confidence=(
                (diagnostic_payload.get("candidate_reports") or [{}])[0].get("diagnostic_confidence")
            )
            if diagnostic_payload
            else None,
            branch_score=round(branch_score, 6),
            blocked_reasons=list(dict.fromkeys(item for item in blocked_reasons if item)),
            candidate_paths=candidate_paths,
        )
        records.append(record)

    actionable = [
        record
        for record in records
        if record.auto_continue_allowed or record.supported_slice_count > 0 or record.recommended_mutation
    ]
    ranked = sorted(records, key=lambda item: item.branch_score, reverse=True)
    decision = "recommit_branch" if actionable else "open_new_family"
    recommended_candidate_id = (
        sorted(actionable, key=lambda item: item.branch_score, reverse=True)[0].candidate_id if actionable else None
    )
    recommended_family = next(
        (record.family for record in records if record.candidate_id == recommended_candidate_id), None
    )
    rationale = _branch_audit_rationale(records, next_family_hint=next_family_hint, decision=decision)
    report = CandidateBranchAuditReport(
        candidate_ids=list(candidate_ids),
        comparison_report_path=comparison.report_path,
        decision=decision,
        recommended_candidate_id=recommended_candidate_id,
        recommended_family=recommended_family,
        next_family_hint=next_family_hint if decision == "open_new_family" else None,
        rationale=rationale,
        records=ranked,
        report_path=settings.paths().operator_reports_dir / f"candidate_branch_audit-{_timestamp_token()}.json",
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    return report


def audit_candidate_window_density(
    settings: Settings,
    *,
    candidate_ids: list[str],
    reference_candidate_id: str | None = None,
) -> CandidateWindowDensityAuditReport:
    if not candidate_ids:
        raise ValueError("At least one candidate id is required for a window-density audit.")

    records: list[CandidateWindowDensityAuditRecord] = []
    aggregate_hour_pnl: dict[int, list[float]] = defaultdict(list)
    aggregate_weak_window_pnl: dict[int, list[float]] = defaultdict(list)
    aggregate_phase_pnl: dict[str, list[float]] = defaultdict(list)
    aggregate_weak_window_phase_pnl: dict[str, list[float]] = defaultdict(list)
    weak_window_counter: Counter[int] = Counter()

    for candidate_id in candidate_ids:
        report_dir = settings.paths().reports_dir / candidate_id
        candidate_payload = read_json(report_dir / "candidate.json")
        spec_payload = read_json(report_dir / "strategy_spec.json")
        backtest_payload = read_json(report_dir / "backtest_summary.json")
        stress_payload = read_json(report_dir / "stress_test.json")
        ledger_rows = list(_read_trade_ledger_rows(report_dir / "trade_ledger.csv"))
        open_anchor_hour_utc = int(
            candidate_payload.get("open_anchor_hour_utc")
            or spec_payload.get("open_anchor_hour_utc")
            or min(list(spec_payload.get("session_policy", {}).get("allowed_hours_utc") or [7]))
        )

        walk_forward_windows = [
            CandidateWindowDensityWalkForwardRecord(
                window=int(window.get("window", 0)),
                trade_count=int(window.get("trade_count", 0)),
                profit_factor=float(window.get("profit_factor", 0.0)),
                expectancy_pips=float(window.get("expectancy_pips", 0.0)),
                passed=bool(window.get("passed", False)),
            )
            for window in list(backtest_payload.get("walk_forward_summary") or [])
        ]
        weakest_window_record = min(
            walk_forward_windows,
            key=lambda item: (item.trade_count, item.profit_factor, item.expectancy_pips),
        )
        weak_window_counter[weakest_window_record.window] += 1

        hour_groups = _group_trades_by_hour(ledger_rows)
        for hour, pnl_values in hour_groups.items():
            aggregate_hour_pnl[hour].extend(pnl_values)
        phase_groups = _group_trades_by_phase(ledger_rows, open_anchor_hour_utc=open_anchor_hour_utc)
        for phase_name, pnl_values in phase_groups.items():
            aggregate_phase_pnl[phase_name].extend(pnl_values)
        weakest_window_groups = _group_trades_by_hour(
            _rows_for_walk_forward_window(ledger_rows, backtest_payload, weakest_window_record.window)
        )
        for hour, pnl_values in weakest_window_groups.items():
            aggregate_weak_window_pnl[hour].extend(pnl_values)
        weakest_window_phase_groups = _group_trades_by_phase(
            _rows_for_walk_forward_window(ledger_rows, backtest_payload, weakest_window_record.window),
            open_anchor_hour_utc=open_anchor_hour_utc,
        )
        for phase_name, pnl_values in weakest_window_phase_groups.items():
            aggregate_weak_window_phase_pnl[phase_name].extend(pnl_values)

        records.append(
            CandidateWindowDensityAuditRecord(
                candidate_id=candidate_id,
                family=str(candidate_payload.get("family") or spec_payload.get("family") or ""),
                entry_style=str(candidate_payload.get("entry_style") or spec_payload.get("entry_style") or ""),
                allowed_hours_utc=list(spec_payload.get("session_policy", {}).get("allowed_hours_utc") or []),
                open_anchor_hour_utc=open_anchor_hour_utc,
                trade_count=int(backtest_payload.get("trade_count", 0)),
                out_of_sample_profit_factor=float(backtest_payload.get("out_of_sample_profit_factor", 0.0)),
                expectancy_pips=float(backtest_payload.get("expectancy_pips", 0.0)),
                stressed_profit_factor=float(stress_payload.get("stressed_profit_factor", 0.0)),
                stress_passed=bool(stress_payload.get("passed", False)),
                weakest_window=weakest_window_record.window,
                weakest_window_trade_count=weakest_window_record.trade_count,
                weakest_window_hours=_hour_records_from_groups(weakest_window_groups, support_counter=None),
                weakest_window_phases=_phase_records_from_groups(weakest_window_phase_groups, support_counter=None),
                walk_forward_windows=walk_forward_windows,
                hour_records=_hour_records_from_groups(hour_groups, support_counter=None),
                phase_records=_phase_records_from_groups(phase_groups, support_counter=None),
                candidate_paths={
                    "candidate_path": str(report_dir / "candidate.json"),
                    "spec_path": str(report_dir / "strategy_spec.json"),
                    "backtest_summary_path": str(report_dir / "backtest_summary.json"),
                    "stress_test_path": str(report_dir / "stress_test.json"),
                    "trade_ledger_path": str(report_dir / "trade_ledger.csv"),
                },
            )
        )

    weakest_window = weak_window_counter.most_common(1)[0][0] if weak_window_counter else None
    aggregate_hour_records = _hour_records_from_groups(
        aggregate_hour_pnl,
        support_counter=_hour_support_counter(records, attribute="hour_records"),
    )
    weakest_window_hour_records = _hour_records_from_groups(
        aggregate_weak_window_pnl,
        support_counter=_hour_support_counter(
            [record for record in records if record.weakest_window == weakest_window],
            attribute="weakest_window_hours",
        ),
    )
    aggregate_phase_records = _phase_records_from_groups(
        aggregate_phase_pnl,
        support_counter=_phase_support_counter(records, attribute="phase_records"),
    )
    weakest_window_phase_records = _phase_records_from_groups(
        aggregate_weak_window_phase_pnl,
        support_counter=_phase_support_counter(
            [record for record in records if record.weakest_window == weakest_window],
            attribute="weakest_window_phases",
        ),
    )
    recommended_hours = _contiguous_supported_hours(
        weakest_window_hour_records,
        candidate_count=len([record for record in records if record.weakest_window == weakest_window]),
    )
    recommended_phases = _supported_phase_names(
        weakest_window_phase_records,
        aggregate_phase_records=aggregate_phase_records,
        candidate_count=len([record for record in records if record.weakest_window == weakest_window]),
    )
    if recommended_phases and recommended_hours:
        decision = "revive_family"
        rationale = [
            f"Weakest walk-forward window {weakest_window} still shows repeatable anchored phase support in {recommended_phases}.",
            f"The same clue family also retains a contiguous hour block {recommended_hours}, so the family can be revived without inventing a new geometry branch.",
        ]
    elif recommended_phases:
        decision = "refine_family_once"
        rationale = [
            f"Weakest walk-forward window {weakest_window} still shows repeatable anchored phase support in {recommended_phases}.",
            "One bounded family refinement is justified because the weakness is phase-conditioned rather than a fully broken chronology model.",
        ]
    else:
        decision = "adjust_discovery_model"
        rationale = [
            f"Weakest walk-forward window {weakest_window} is underdense across the whole clue family rather than missing one repeatable anchored phase edge.",
            "The trade ledgers show the same middle window failing across open-anchor phases, so another hour micro-family would just relabel the same chronology hole.",
        ]
    report = CandidateWindowDensityAuditReport(
        candidate_ids=list(candidate_ids),
        reference_candidate_id=reference_candidate_id,
        weakest_window=weakest_window,
        decision=decision,
        recommended_hours_utc=recommended_hours,
        recommended_phases=recommended_phases,
        rationale=rationale,
        aggregate_hour_records=aggregate_hour_records,
        weakest_window_hour_records=weakest_window_hour_records,
        aggregate_phase_records=aggregate_phase_records,
        weakest_window_phase_records=weakest_window_phase_records,
        records=sorted(records, key=lambda item: (item.weakest_window_trade_count, item.trade_count)),
        report_path=settings.paths().operator_reports_dir / f"candidate_window_density_audit-{_timestamp_token()}.json",
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    return report


def validate_operator_contract(settings: Settings) -> OperatorContractReport:
    findings: list[OperatorContractFinding] = []
    codex_config_path = settings.paths().codex_dir / "config.toml"
    rules_path = settings.project_root / settings.codex_operator.repo_rules_file
    capability_manifest_path = settings.paths().config_dir / settings.codex_operator.capability_manifest_filename

    if settings.data.canonical_source.lower() != "oanda":
        findings.append(
            OperatorContractFinding(
                severity="error",
                code="canonical_source_not_oanda",
                message="OANDA must remain the canonical research data source.",
                path=settings.paths().config_dir / "default.toml",
            )
        )
    if settings.mt5_env.allow_live_trading:
        findings.append(
            OperatorContractFinding(
                severity="error",
                code="mt5_live_trading_enabled",
                message="MT5 live trading must remain disabled.",
                path=settings.paths().config_dir / "mt5_env.toml",
            )
        )

    try:
        overlap_slot = settings.portfolio.slot_by_id("overlap_benchmark")
        if overlap_slot.active_candidate_id != "AF-CAND-0263" or overlap_slot.mutation_allowed:
            findings.append(
                OperatorContractFinding(
                    severity="error",
                    code="overlap_slot_mutable",
                    message="The overlap benchmark slot must stay pinned to AF-CAND-0263 and remain immutable.",
                    path=settings.paths().config_dir / "portfolio_policy.toml",
                )
            )
    except KeyError:
        findings.append(
            OperatorContractFinding(
                severity="error",
                code="missing_overlap_slot",
                message="Portfolio policy is missing the overlap_benchmark slot.",
                path=settings.paths().config_dir / "portfolio_policy.toml",
            )
        )

    try:
        gap_slot = settings.portfolio.slot_by_id("gap_blank_slate")
        if gap_slot.strategy_inheritance != "none_from_AF-CAND-0263_logic":
            findings.append(
                OperatorContractFinding(
                    severity="error",
                    code="gap_slot_inheritance_invalid",
                    message="The gap blank-slate slot must explicitly reject AF-CAND-0263 strategy inheritance.",
                    path=settings.paths().config_dir / "portfolio_policy.toml",
                )
            )
    except KeyError:
        findings.append(
            OperatorContractFinding(
                severity="error",
                code="missing_gap_slot",
                message="Portfolio policy is missing the gap_blank_slate slot.",
                path=settings.paths().config_dir / "portfolio_policy.toml",
            )
        )

    if settings.codex_operator.allow_hooks_in_critical_path:
        findings.append(
            OperatorContractFinding(
                severity="error",
                code="hooks_allowed_on_critical_path",
                message="Hooks must remain out of the critical path for this repo.",
                path=settings.paths().config_dir / "codex_operator_policy.toml",
            )
        )

    if not codex_config_path.exists():
        findings.append(
            OperatorContractFinding(
                severity="error",
                code="missing_codex_config",
                message="Repo-local Codex config is missing.",
                path=codex_config_path,
            )
        )
    else:
        config_payload = tomllib.loads(codex_config_path.read_text(encoding="utf-8"))
        if config_payload.get("sandbox_mode") != "workspace-write":
            findings.append(
                OperatorContractFinding(
                    severity="error",
                    code="codex_sandbox_not_workspace_write",
                    message="Repo-local Codex config must default to workspace-write.",
                    path=codex_config_path,
                )
            )
        features = config_payload.get("features") or {}
        if features.get("codex_hooks") not in {False, None}:
            findings.append(
                OperatorContractFinding(
                    severity="error",
                    code="codex_hooks_enabled",
                    message="Codex hooks must remain disabled for this Windows-first repo.",
                    path=codex_config_path,
                )
            )

    if not rules_path.exists():
        findings.append(
            OperatorContractFinding(
                severity="error",
                code="missing_rules_file",
                message="Repo-local Codex rules file is missing.",
                path=rules_path,
            )
        )

    if not capability_manifest_path.exists():
        findings.append(
            OperatorContractFinding(
                severity="error",
                code="missing_capability_manifest",
                message="Capability sync manifest is missing.",
                path=capability_manifest_path,
            )
        )

    findings.extend(_validate_skill_mirrors(settings))
    findings.extend(_validate_automation_specs(settings))

    if not settings.paths().capability_catalog_path.exists():
        findings.append(
            OperatorContractFinding(
                severity="warning",
                code="missing_capability_catalog",
                message="Capability catalog has not been synced yet.",
                path=settings.paths().capability_catalog_path,
            )
        )

    report = OperatorContractReport(
        passed=not any(item.severity == "error" for item in findings),
        findings=findings,
        report_path=settings.paths().operator_reports_dir / f"operator_contract-{_timestamp_token()}.json",
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    return report


def _read_trade_ledger_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(DictReader(handle))


def _rows_for_walk_forward_window(
    ledger_rows: list[dict[str, str]],
    backtest_payload: dict[str, Any],
    window_number: int,
) -> list[dict[str, str]]:
    window = next(
        (
            item
            for item in list(backtest_payload.get("walk_forward_summary") or [])
            if int(item.get("window", 0)) == window_number
        ),
        None,
    )
    if window is None:
        return []
    start = _parse_utc(window["start_utc"])
    end = _parse_utc(window["end_utc"])
    return [row for row in ledger_rows if start <= _parse_utc(row["timestamp_utc"]) < end]


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _group_trades_by_hour(ledger_rows: list[dict[str, str]]) -> dict[int, list[float]]:
    grouped: dict[int, list[float]] = defaultdict(list)
    for row in ledger_rows:
        timestamp = row.get("timestamp_utc")
        pnl_value = row.get("pnl_pips")
        if not timestamp or pnl_value in (None, ""):
            continue
        grouped[_parse_utc(timestamp).hour].append(float(pnl_value))
    return dict(grouped)


def _group_trades_by_phase(
    ledger_rows: list[dict[str, str]],
    *,
    open_anchor_hour_utc: int,
) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in ledger_rows:
        timestamp = row.get("timestamp_utc")
        pnl_value = row.get("pnl_pips")
        if not timestamp or pnl_value in (None, ""):
            continue
        hour_utc = _parse_utc(timestamp).hour
        grouped[_phase_name_for_hour(hour_utc, open_anchor_hour_utc=open_anchor_hour_utc)].append(float(pnl_value))
    return dict(grouped)


def _hour_support_counter(
    records: list[CandidateWindowDensityAuditRecord],
    *,
    attribute: str,
) -> Counter[int]:
    counter: Counter[int] = Counter()
    for record in records:
        hours = {item.hour_utc for item in getattr(record, attribute)}
        for hour in hours:
            counter[hour] += 1
    return counter


def _phase_support_counter(
    records: list[CandidateWindowDensityAuditRecord],
    *,
    attribute: str,
) -> Counter[str]:
    counter: Counter[str] = Counter()
    for record in records:
        phase_names = {item.phase_name for item in getattr(record, attribute)}
        for phase_name in phase_names:
            counter[phase_name] += 1
    return counter


def _hour_records_from_groups(
    hour_groups: dict[int, list[float]],
    *,
    support_counter: Counter[int] | None,
) -> list[CandidateWindowDensityHourRecord]:
    records: list[CandidateWindowDensityHourRecord] = []
    for hour in sorted(hour_groups):
        pnl_values = hour_groups[hour]
        gross_profit = sum(value for value in pnl_values if value > 0)
        gross_loss = abs(sum(value for value in pnl_values if value < 0))
        if gross_loss == 0:
            profit_factor = gross_profit if gross_profit > 0 else 0.0
        else:
            profit_factor = gross_profit / gross_loss
        records.append(
            CandidateWindowDensityHourRecord(
                hour_utc=hour,
                trade_count=len(pnl_values),
                mean_pnl_pips=sum(pnl_values) / len(pnl_values),
                profit_factor=profit_factor,
                candidate_support=int((support_counter or Counter()).get(hour, 0)),
            )
        )
    return records


def _phase_records_from_groups(
    phase_groups: dict[str, list[float]],
    *,
    support_counter: Counter[str] | None,
) -> list[CandidateWindowDensityPhaseRecord]:
    records: list[CandidateWindowDensityPhaseRecord] = []
    phase_order = {
        "open_impulse": 0,
        "early_follow_through": 1,
        "late_morning_decay": 2,
        "outside_anchor": 3,
    }
    for phase_name in sorted(phase_groups, key=lambda item: phase_order.get(item, 99)):
        pnl_values = phase_groups[phase_name]
        gross_profit = sum(value for value in pnl_values if value > 0)
        gross_loss = abs(sum(value for value in pnl_values if value < 0))
        if gross_loss == 0:
            profit_factor = gross_profit if gross_profit > 0 else 0.0
        else:
            profit_factor = gross_profit / gross_loss
        records.append(
            CandidateWindowDensityPhaseRecord(
                phase_name=phase_name,  # type: ignore[arg-type]
                trade_count=len(pnl_values),
                mean_pnl_pips=sum(pnl_values) / len(pnl_values),
                profit_factor=profit_factor,
                candidate_support=int((support_counter or Counter()).get(phase_name, 0)),
            )
        )
    return records


def _contiguous_supported_hours(
    hour_records: list[CandidateWindowDensityHourRecord],
    *,
    candidate_count: int,
) -> list[int]:
    if candidate_count <= 0:
        return []
    support_floor = max(2, int(candidate_count * 0.6 + 0.999999))
    viable_hours = sorted(
        record.hour_utc
        for record in hour_records
        if record.candidate_support >= support_floor and record.trade_count >= support_floor
    )
    best_block: list[int] = []
    current_block: list[int] = []
    previous_hour: int | None = None
    for hour in viable_hours:
        if previous_hour is None or hour == previous_hour + 1:
            current_block.append(hour)
        else:
            if len(current_block) > len(best_block):
                best_block = current_block
            current_block = [hour]
        previous_hour = hour
    if len(current_block) > len(best_block):
        best_block = current_block
    return best_block if len(best_block) >= 2 else []


def _supported_phase_names(
    phase_records: list[CandidateWindowDensityPhaseRecord],
    *,
    aggregate_phase_records: list[CandidateWindowDensityPhaseRecord],
    candidate_count: int,
) -> list[str]:
    if candidate_count <= 0:
        return []
    support_floor = max(2, int(candidate_count * 0.6 + 0.999999))
    aggregate_lookup = {record.phase_name: record for record in aggregate_phase_records}
    supported: list[str] = []
    for record in phase_records:
        aggregate_record = aggregate_lookup.get(record.phase_name)
        if aggregate_record is None:
            continue
        if record.candidate_support < support_floor or record.trade_count < support_floor:
            continue
        if record.mean_pnl_pips <= 0.0 or record.profit_factor < 1.0:
            continue
        if aggregate_record.mean_pnl_pips <= 0.0 or aggregate_record.profit_factor < 1.0:
            continue
        supported.append(record.phase_name)
    return supported


def _phase_name_for_hour(hour_utc: int, *, open_anchor_hour_utc: int) -> str:
    if hour_utc <= open_anchor_hour_utc:
        return "open_impulse"
    if hour_utc == open_anchor_hour_utc + 1:
        return "early_follow_through"
    if hour_utc <= open_anchor_hour_utc + 4:
        return "late_morning_decay"
    return "outside_anchor"


def run_governed_action(
    settings: Settings,
    *,
    action: str,
    family: str = "scalping",
    parent_campaign_id: str | None = None,
    campaign_id: str | None = None,
    allowed_step_types: list[str] | None = None,
    loop_id: str | None = None,
    max_steps: int = 8,
    program_id: str | None = None,
    max_lanes: int | None = None,
    manager_run_id: str | None = None,
    max_cycles: int | None = None,
    cycle_id: str | None = None,
    slot_id: str | None = None,
    all_slots: bool = False,
    run_id: str | None = None,
) -> GovernedActionManifest:
    resolved_run_id = run_id or f"{action}-{_timestamp_token()}"
    trace_dir = settings.paths().codex_operator_traces_dir / resolved_run_id
    trace_dir.mkdir(parents=True, exist_ok=True)
    manifest = GovernedActionManifest(
        run_id=resolved_run_id,
        action=action,
        requested_utc=_utc_now(),
        policy_snapshot_hash=policy_snapshot_hash(settings),
        request={
            "family": family,
            "parent_campaign_id": parent_campaign_id,
            "campaign_id": campaign_id,
            "allowed_step_types": allowed_step_types or [],
            "loop_id": loop_id,
            "max_steps": max_steps,
            "program_id": program_id,
            "max_lanes": max_lanes,
            "manager_run_id": manager_run_id,
            "max_cycles": max_cycles,
            "cycle_id": cycle_id,
            "slot_id": slot_id,
            "all_slots": all_slots,
        },
        trace_dir=trace_dir,
        manifest_path=trace_dir / "operator_manifest.json",
    )
    try:
        if action in {"next_step", "governed_loop", "program_loop", "autonomous_manager"}:
            ledger = enforce_strategy_governance(settings, family=family)
            methodology_audit = write_strategy_methodology_audit(settings, family=family, ledger=ledger)
            manifest.delegated_agent_summaries.append(
                {
                    "gate": "strategy_governance",
                    "family": family,
                    "ledger_path": str(ledger.report_path) if ledger.report_path else None,
                    "methodology_audit_path": str(methodology_audit.report_path)
                    if methodology_audit.report_path
                    else None,
                    "methodology_audit_score": methodology_audit.weighted_score,
                    "methodology_audit_passed": methodology_audit.passed,
                    "trial_count_family": ledger.trial_count_family,
                    "failed_refinement_count": ledger.failed_refinement_count,
                    "max_observed_mutation_depth": ledger.max_observed_mutation_depth,
                    "suspended": ledger.suspended,
                }
            )
        result = _dispatch_governed_action(
            settings,
            action=action,
            family=family,
            parent_campaign_id=parent_campaign_id,
            campaign_id=campaign_id,
            allowed_step_types=allowed_step_types,
            loop_id=loop_id,
            max_steps=max_steps,
            program_id=program_id,
            max_lanes=max_lanes,
            manager_run_id=manager_run_id,
            max_cycles=max_cycles,
            cycle_id=cycle_id,
            slot_id=slot_id,
            all_slots=all_slots,
        )
        manifest.output_report_path = getattr(result, "report_path", None)
        manifest.output_report_type = type(result).__name__
        manifest.output_payload = _serialize_result(result)
        manifest.status = "completed"
    except Exception as exc:  # noqa: BLE001
        manifest.output_report_type = "exception"
        manifest.output_payload = {"error": str(exc)}
        manifest.status = "failed"
        raise
    finally:
        manifest.completed_utc = _utc_now()
        write_json(manifest.manifest_path, manifest.model_dump(mode="json"))
        (trace_dir / "operator_manifest.md").write_text(_render_governed_manifest(manifest), encoding="utf-8")
    return manifest


def inspect_governed_action(
    settings: Settings,
    *,
    run_id: str | None = None,
    manifest_path: Path | None = None,
) -> GovernedActionInspection:
    resolved_manifest_path = manifest_path
    if resolved_manifest_path is None:
        if run_id is not None:
            resolved_manifest_path = settings.paths().codex_operator_traces_dir / run_id / "operator_manifest.json"
        else:
            manifests = sorted(settings.paths().codex_operator_traces_dir.glob("*/operator_manifest.json"))
            if not manifests:
                raise FileNotFoundError("No governed action manifests were found.")
            resolved_manifest_path = manifests[-1]

    payload = read_json(resolved_manifest_path)
    return GovernedActionInspection(
        run_id=str(payload.get("run_id") or resolved_manifest_path.parent.name),
        action=str(payload.get("action") or "unknown"),
        status=str(payload.get("status") or "failed"),
        output_report_path=Path(payload["output_report_path"]) if payload.get("output_report_path") else None,
        output_report_type=payload.get("output_report_type"),
        manifest_path=resolved_manifest_path,
        trace_dir=resolved_manifest_path.parent,
        output_payload=dict(payload.get("output_payload") or {}),
    )


def _latest_next_step_report_for_candidate(
    settings: Settings, candidate_id: str
) -> tuple[dict[str, Any] | None, Path | None]:
    matches: list[tuple[float, Path, dict[str, Any]]] = []
    for path in settings.paths().campaigns_dir.glob("*/next_step_report.json"):
        payload = read_json(path)
        candidate_scope = set(payload.get("candidate_scope") or [])
        if candidate_id not in candidate_scope:
            continue
        matches.append((path.stat().st_mtime, path, payload))
    if not matches:
        return None, None
    _, report_path, payload = max(matches, key=lambda item: item[0])
    return payload, report_path


def _load_capability_manifest(manifest_path: Path) -> CapabilityManifest:
    payload = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    return CapabilityManifest.model_validate(payload)


def _sync_official_doc_entry(
    settings: Settings,
    *,
    source: CapabilityManifestEntry,
    trace_dir: Path,
    session: requests.Session,
) -> CapabilityCatalogEntry:
    snapshot_path = trace_dir / f"{source.source_id}.html"
    try:
        response = session.get(
            source.source_ref,
            timeout=settings.codex_operator.capability_sync_timeout_seconds,
            headers={"User-Agent": "agentic-forex-capability-sync/1.0"},
        )
        response.raise_for_status()
        html = response.text
        snapshot_path.write_text(html, encoding="utf-8")
        summary = _summarize_html(html)
        return CapabilityCatalogEntry(
            source_id=source.source_id,
            capability_name=source.capability_name,
            source_ref=source.source_ref,
            source_kind=source.source_kind,
            surface_type=source.surface_type,
            stability=source.stability,
            windows_support=source.windows_support,
            critical_path_eligibility=source.critical_path_eligibility,
            repo_applicability=source.repo_applicability,
            sandbox_posture=source.sandbox_posture,
            approval_posture=source.approval_posture,
            summary=summary,
            artifact_path=snapshot_path,
            content_sha256=_sha256_text(html),
            inventory={"bytes": len(html.encode("utf-8"))},
            notes=source.notes,
        )
    except Exception as exc:  # noqa: BLE001
        return CapabilityCatalogEntry(
            source_id=source.source_id,
            capability_name=source.capability_name,
            source_ref=source.source_ref,
            source_kind=source.source_kind,
            surface_type=source.surface_type,
            stability=source.stability,
            windows_support=source.windows_support,
            critical_path_eligibility=source.critical_path_eligibility,
            repo_applicability=source.repo_applicability,
            sandbox_posture=source.sandbox_posture,
            approval_posture=source.approval_posture,
            sync_status="failed",
            summary=f"Failed to sync official documentation: {exc}",
            artifact_path=snapshot_path,
            notes=source.notes,
        )


def _sync_local_surface_entry(
    settings: Settings,
    *,
    source: CapabilityManifestEntry,
    trace_dir: Path,
) -> CapabilityCatalogEntry:
    target_path = (settings.project_root / source.source_ref).resolve()
    snapshot_path = trace_dir / f"{source.source_id}.json"
    if not target_path.exists():
        return CapabilityCatalogEntry(
            source_id=source.source_id,
            capability_name=source.capability_name,
            source_ref=source.source_ref,
            source_kind=source.source_kind,
            surface_type=source.surface_type,
            stability=source.stability,
            windows_support=source.windows_support,
            critical_path_eligibility=source.critical_path_eligibility,
            repo_applicability=source.repo_applicability,
            sandbox_posture=source.sandbox_posture,
            approval_posture=source.approval_posture,
            sync_status="failed",
            summary="Local capability surface is missing from the repository.",
            artifact_path=snapshot_path,
            notes=source.notes,
        )

    inventory = _inventory_local_surface(
        target_path,
        recursive=source.recursive,
        limit=settings.codex_operator.capability_inventory_limit,
        sample_bytes=settings.codex_operator.capability_sample_bytes,
        project_root=settings.project_root,
    )
    write_json(snapshot_path, inventory)
    return CapabilityCatalogEntry(
        source_id=source.source_id,
        capability_name=source.capability_name,
        source_ref=source.source_ref,
        source_kind=source.source_kind,
        surface_type=source.surface_type,
        stability=source.stability,
        windows_support=source.windows_support,
        critical_path_eligibility=source.critical_path_eligibility,
        repo_applicability=source.repo_applicability,
        sandbox_posture=source.sandbox_posture,
        approval_posture=source.approval_posture,
        summary=str(inventory.get("summary") or ""),
        artifact_path=snapshot_path,
        content_sha256=_sha256_text(json.dumps(inventory, sort_keys=True)),
        inventory=inventory,
        notes=source.notes,
    )


def _inventory_local_surface(
    target_path: Path,
    *,
    recursive: bool,
    limit: int,
    sample_bytes: int,
    project_root: Path,
) -> dict[str, Any]:
    if target_path.is_file():
        text_sample = ""
        try:
            text_sample = target_path.read_text(encoding="utf-8", errors="ignore")[:sample_bytes]
        except OSError:
            text_sample = ""
        return {
            "summary": f"Single file surface at {target_path.relative_to(project_root)}.",
            "path": str(target_path.relative_to(project_root)),
            "bytes": target_path.stat().st_size,
            "sha256": _sha256_bytes(target_path.read_bytes()),
            "sample": text_sample,
        }

    pattern = "**/*" if recursive else "*"
    files = [path for path in target_path.glob(pattern) if path.is_file()]
    files.sort()
    suffix_counts = Counter(path.suffix or "<no_ext>" for path in files)
    sample_paths = [str(path.relative_to(project_root)) for path in files[:limit]]
    content_fingerprint = _sha256_text(
        json.dumps(
            {
                "files": sample_paths,
                "suffix_counts": dict(sorted(suffix_counts.items())),
            },
            sort_keys=True,
        )
    )
    return {
        "summary": f"Directory surface with {len(files)} files under {target_path.relative_to(project_root)}.",
        "path": str(target_path.relative_to(project_root)),
        "file_count": len(files),
        "sample_paths": sample_paths,
        "suffix_counts": dict(sorted(suffix_counts.items())),
        "content_fingerprint": content_fingerprint,
    }


def _render_capability_index(entries: list[CapabilityCatalogEntry]) -> str:
    lines = [
        "# Codex Capability Index",
        "",
        "This catalog is the repo's source of truth for what the Codex-native operator may rely on.",
        "",
        "| Capability | Source | Type | Stability | Windows | Critical Path | Sandbox | Approval | Status |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entry in sorted(entries, key=lambda item: item.source_id):
        lines.append(
            f"| {entry.capability_name} | `{entry.source_ref}` | `{entry.surface_type}` | `{entry.stability}` | `{entry.windows_support}` | `{entry.critical_path_eligibility}` | `{entry.sandbox_posture}` | `{entry.approval_posture}` | `{entry.sync_status}` |"
        )
    lines.extend(["", "## Notes", ""])
    for entry in sorted(entries, key=lambda item: item.source_id):
        lines.append(f"### {entry.capability_name}")
        lines.append(f"- Source: `{entry.source_ref}`")
        lines.append(f"- Repo applicability: {entry.repo_applicability}")
        lines.append(f"- Summary: {entry.summary or 'No summary captured.'}")
        if entry.notes:
            lines.append(f"- Notes: {'; '.join(entry.notes)}")
        lines.append("")
    return "\n".join(lines)


def _render_capability_report(report: CapabilitySyncReport) -> str:
    lines = [
        "# Capability Sync Report",
        "",
        f"- Run ID: `{report.run_id}`",
        f"- Synced entries: {report.synced_entries}",
        f"- Failed entries: {report.failed_entries}",
        "",
    ]
    for entry in report.entries:
        lines.append(f"## {entry.capability_name}")
        lines.append(f"- Status: `{entry.sync_status}`")
        lines.append(f"- Source: `{entry.source_ref}`")
        lines.append(f"- Summary: {entry.summary}")
        lines.append("")
    return "\n".join(lines)


def _validate_skill_mirrors(settings: Settings) -> list[OperatorContractFinding]:
    findings: list[OperatorContractFinding] = []
    source_root = settings.paths().codex_skills_src_dir
    runtime_root = settings.paths().repo_agent_skills_dir
    for source_skill in sorted(path for path in source_root.glob("*") if path.is_dir()):
        source_skill_md = source_skill / "SKILL.md"
        runtime_skill_md = runtime_root / source_skill.name / "SKILL.md"
        if not source_skill_md.exists():
            findings.append(
                OperatorContractFinding(
                    severity="error",
                    code="source_skill_missing",
                    message=f"Source skill {source_skill.name} is missing SKILL.md.",
                    path=source_skill_md,
                )
            )
            continue
        if not runtime_skill_md.exists():
            findings.append(
                OperatorContractFinding(
                    severity="error",
                    code="runtime_skill_missing",
                    message=f"Runtime skill mirror {source_skill.name} is missing.",
                    path=runtime_skill_md,
                )
            )
            continue
        if source_skill_md.read_text(encoding="utf-8") != runtime_skill_md.read_text(encoding="utf-8"):
            findings.append(
                OperatorContractFinding(
                    severity="error",
                    code="skill_mirror_mismatch",
                    message=f"Runtime skill mirror for {source_skill.name} is out of sync with .codex/skills-src.",
                    path=runtime_skill_md,
                )
            )
    return findings


def _validate_automation_specs(settings: Settings) -> list[OperatorContractFinding]:
    findings: list[OperatorContractFinding] = []
    for spec_path in sorted(settings.paths().automation_specs_dir.glob("*.toml")):
        payload = tomllib.loads(spec_path.read_text(encoding="utf-8"))
        status = str(payload.get("status") or "").lower()
        execution_mode = str(payload.get("execution_mode") or "").lower()
        if status != settings.codex_operator.automation_default_status:
            findings.append(
                OperatorContractFinding(
                    severity="error",
                    code="automation_not_paused",
                    message=f"Automation spec {spec_path.name} must default to paused.",
                    path=spec_path,
                )
            )
        if execution_mode != settings.codex_operator.automation_default_execution:
            findings.append(
                OperatorContractFinding(
                    severity="error",
                    code="automation_execution_mode_invalid",
                    message=f"Automation spec {spec_path.name} must default to worktree execution.",
                    path=spec_path,
                )
            )
    return findings


def _load_automation_specs(settings: Settings) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for spec_path in sorted(settings.paths().automation_specs_dir.glob("*.toml")):
        payload = tomllib.loads(spec_path.read_text(encoding="utf-8"))
        specs.append(
            {
                "name": payload.get("name"),
                "status": payload.get("status"),
                "execution_mode": payload.get("execution_mode"),
                "prompt_file": payload.get("prompt_file"),
                "path": str(spec_path.relative_to(settings.project_root)),
            }
        )
    return specs


def _dispatch_governed_action(
    settings: Settings,
    *,
    action: str,
    family: str,
    parent_campaign_id: str | None,
    campaign_id: str | None,
    allowed_step_types: list[str] | None,
    loop_id: str | None,
    max_steps: int,
    program_id: str | None,
    max_lanes: int | None,
    manager_run_id: str | None,
    max_cycles: int | None,
    cycle_id: str | None,
    slot_id: str | None,
    all_slots: bool,
):
    if action == "next_step":
        return run_next_step(
            settings,
            family=family,
            parent_campaign_id=parent_campaign_id,
            campaign_id=campaign_id,
            allowed_step_types=allowed_step_types,
        )
    if action == "governed_loop":
        return run_governed_loop(
            settings,
            family=family,
            parent_campaign_id=parent_campaign_id,
            loop_id=loop_id,
            max_steps=max_steps,
            allowed_step_types=allowed_step_types,
        )
    if action == "program_loop":
        return run_program_loop(
            settings,
            family=family,
            parent_campaign_id=parent_campaign_id,
            program_id=program_id,
            max_lanes=max_lanes,
        )
    if action == "autonomous_manager":
        return run_autonomous_manager(
            settings,
            family=family,
            parent_campaign_id=parent_campaign_id,
            program_id=program_id,
            manager_run_id=manager_run_id,
            max_cycles=max_cycles,
        )
    if action == "portfolio_cycle":
        return run_portfolio_cycle(
            settings,
            slot_id=slot_id,
            run_all_slots=all_slots,
            cycle_id=cycle_id,
        )
    raise ValueError(f"Unsupported governed action: {action}")


def _render_governed_manifest(manifest: GovernedActionManifest) -> str:
    return "\n".join(
        [
            "# Governed Action Manifest",
            "",
            f"- Run ID: `{manifest.run_id}`",
            f"- Action: `{manifest.action}`",
            f"- Status: `{manifest.status}`",
            f"- Policy snapshot: `{manifest.policy_snapshot_hash}`",
            f"- Output report type: `{manifest.output_report_type or 'none'}`",
            f"- Output report path: `{manifest.output_report_path or ''}`",
            "",
            "```json",
            json.dumps(manifest.output_payload, indent=2, default=str),
            "```",
        ]
    )


def _summarize_html(html: str) -> str:
    title_match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    h1_match = re.search(r"<h1[^>]*>(.*?)</h1>", html, flags=re.IGNORECASE | re.DOTALL)
    text = _strip_html(html)
    fragments = [
        _collapse_ws(title_match.group(1)) if title_match else "",
        _collapse_ws(h1_match.group(1)) if h1_match else "",
        _collapse_ws(text)[:240],
    ]
    fragments = [fragment for fragment in fragments if fragment]
    return " | ".join(dict.fromkeys(fragments))


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip()


def _collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _recent_report_paths(directory: Path, *, limit: int = 5) -> list[str]:
    files = sorted(
        (path for path in directory.glob("*.json") if path.is_file()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    return [str(path) for path in files[:limit]]


def _serialize_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    if isinstance(result, dict):
        return result
    if isinstance(result, Path):
        return {"path": str(result)}
    return {"value": str(result)}


def _branch_audit_score(
    *,
    trade_count: int,
    oos_profit_factor: float,
    expectancy_pips: float,
    stressed_profit_factor: float,
    stress_passed: bool,
    walk_forward_ok: bool,
    auto_continue_allowed: bool,
    supported_slice_count: int,
    trial_count_family: int,
) -> float:
    score = 0.0
    score += min(trade_count, 250) * 0.04
    score += oos_profit_factor * 12.0
    score += expectancy_pips * 18.0
    score += stressed_profit_factor * 15.0
    if stress_passed:
        score += 18.0
    else:
        score -= 14.0
    if walk_forward_ok:
        score += 18.0
    else:
        score -= 12.0
    if auto_continue_allowed:
        score += 24.0
    if supported_slice_count > 0:
        score += supported_slice_count * 6.0
    if trial_count_family >= 50:
        score -= 10.0
    return score


def _branch_audit_rationale(
    records: list[CandidateBranchAuditRecord],
    *,
    next_family_hint: str | None,
    decision: str,
) -> list[str]:
    if not records:
        return ["No candidate records were available for audit."]
    rationale: list[str] = []
    for record in sorted(records, key=lambda item: item.branch_score, reverse=True):
        rationale.append(
            f"{record.candidate_id} ({record.family}) scored {record.branch_score:.2f}: "
            f"OOS PF {record.out_of_sample_profit_factor:.3f}, expectancy {record.expectancy_pips:.3f}, "
            f"stressed PF {record.stressed_profit_factor:.3f}, walk_forward_ok={record.walk_forward_ok}, "
            f"supported_slices={record.supported_slice_count}."
        )
    if decision == "open_new_family":
        rationale.append(
            "Every audited branch is at a governed hard stop with no supported slice and no justified mutation, so the next rational move is an orthogonal family rather than more reclaim/breakout search."
        )
        if next_family_hint:
            rationale.append(f"Recommended next family: {next_family_hint}.")
    else:
        rationale.append(
            "At least one audited branch still has a supported bounded continuation and should remain active."
        )
    return rationale


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _timestamp_token() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
