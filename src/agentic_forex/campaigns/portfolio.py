from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from agentic_forex.campaigns.autonomous_manager import run_autonomous_manager
from agentic_forex.config import Settings
from agentic_forex.config.models import PortfolioSlotPolicy
from agentic_forex.goblin.controls import finalize_goblin_run_record, start_goblin_run_record
from agentic_forex.goblin.models import PromotionDecisionPacket
from agentic_forex.governance.models import AutonomousManagerReport, PortfolioCycleReport, PortfolioSlotReport
from agentic_forex.utils.io import read_json, write_json


def run_portfolio_cycle(
    settings: Settings,
    *,
    slot_id: str | None = None,
    run_all_slots: bool = False,
    cycle_id: str | None = None,
) -> PortfolioCycleReport:
    selected_slots = _selected_slots(settings, slot_id=slot_id, run_all_slots=run_all_slots)
    report = PortfolioCycleReport(
        cycle_id=cycle_id or f"portfolio-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        slot_reports=[],
        report_path=settings.paths().portfolio_reports_dir / "placeholder.json",
    )
    report.report_path = settings.paths().portfolio_reports_dir / f"{report.cycle_id}.json"
    run_record = start_goblin_run_record(
        run_id=report.cycle_id,
        entrypoint="run_portfolio_cycle",
        slot_id=slot_id,
    )

    for slot in selected_slots:
        if slot.mode == "locked_benchmark":
            report.slot_reports.append(_summarize_locked_benchmark(settings, slot))
            continue
        report.slot_reports.append(_run_blank_slate_research_slot(settings, slot))

    write_json(report.report_path, report.model_dump(mode="json"))
    write_json(settings.paths().portfolio_reports_dir / "portfolio_cycle_latest.json", report.model_dump(mode="json"))
    finalize_goblin_run_record(settings, run_record)
    return report


def _selected_slots(settings: Settings, *, slot_id: str | None, run_all_slots: bool) -> list[PortfolioSlotPolicy]:
    if slot_id:
        return [settings.portfolio.slot_by_id(slot_id)]
    if run_all_slots or slot_id is None:
        return list(settings.portfolio.slots)
    return []


def _summarize_locked_benchmark(settings: Settings, slot: PortfolioSlotPolicy) -> PortfolioSlotReport:
    candidate_id = slot.active_candidate_id
    report_dir = settings.paths().reports_dir / str(candidate_id or "")
    operational_status_path = report_dir / "operational_status.md"
    review_packet_path = report_dir / "review_packet.json"
    forward_stage_path = report_dir / "forward_stage_report.json"
    notes: list[str] = []
    if operational_status_path.exists():
        notes.extend(_extract_status_lines(operational_status_path))
    else:
        notes.append("No operational_status.md found for the locked benchmark candidate.")

    artifact_paths = {
        "operational_status_path": str(operational_status_path),
    }
    if review_packet_path.exists():
        artifact_paths["review_packet_path"] = str(review_packet_path)
    if forward_stage_path.exists():
        artifact_paths["forward_stage_report_path"] = str(forward_stage_path)

    latest_manual_report = _latest_run_file(
        settings.paths().mt5_runs_dir / str(candidate_id or ""), "mt5_manual_run_report.json"
    )
    if latest_manual_report is not None:
        artifact_paths["latest_manual_run_report_path"] = str(latest_manual_report)

    return PortfolioSlotReport(
        slot_id=slot.slot_id,
        mode=slot.mode,
        purpose=slot.purpose,
        active_candidate_id=candidate_id,
        allowed_families=list(slot.allowed_families),
        codex_execution_mode=slot.codex_execution_mode,
        status="monitoring_summary_only",
        last_action="synthesized_locked_benchmark_status",
        mutation_occurred=False,
        artifact_paths=artifact_paths,
        notes=notes,
    )


def _run_blank_slate_research_slot(settings: Settings, slot: PortfolioSlotPolicy) -> PortfolioSlotReport:
    if not slot.allowed_families:
        return PortfolioSlotReport(
            slot_id=slot.slot_id,
            mode=slot.mode,
            purpose=slot.purpose,
            active_candidate_id=slot.active_candidate_id,
            allowed_families=list(slot.allowed_families),
            codex_execution_mode=slot.codex_execution_mode,
            status="research_manager_blocked",
            last_action="no_allowed_family_configured",
            mutation_occurred=False,
            artifact_paths={},
            notes=["Blank-slate research slot has no allowed_families configured."],
        )

    selected_family: str | None = None
    selected_report = None
    last_fallback_family: str | None = None
    last_fallback_report = None
    attempted_notes: list[str] = []
    artifact_paths: dict[str, str] = {}

    for family in slot.allowed_families:
        manager_report = run_autonomous_manager(
            settings,
            family=family,
            manager_run_id=_portfolio_manager_run_id(slot.slot_id, family),
        )
        artifact_paths[f"autonomous_manager_report_path_{family}"] = str(manager_report.report_path)
        if _manager_report_is_slot_fallback_boundary(manager_report):
            attempted_notes.append(
                f"{family}: slot fallback triggered ({manager_report.stop_reason}), trying next allowed family."
            )
            last_fallback_family = family
            last_fallback_report = manager_report
            continue
        selected_family = family
        selected_report = manager_report
        break

    if selected_family is None or selected_report is None:
        if last_fallback_family is not None and last_fallback_report is not None:
            artifact_paths["autonomous_manager_report_path"] = str(last_fallback_report.report_path)
            return PortfolioSlotReport(
                slot_id=slot.slot_id,
                mode=slot.mode,
                purpose=slot.purpose,
                active_candidate_id=slot.active_candidate_id,
                allowed_families=list(slot.allowed_families),
                codex_execution_mode=slot.codex_execution_mode,
                status="research_manager_blocked",
                last_action="ran_autonomous_manager_fallbacks",
                mutation_occurred=False,
                artifact_paths=artifact_paths,
                notes=[
                    *attempted_notes,
                    "No family advanced past the slot fallback boundary.",
                    f"Final fallback family: {last_fallback_family}",
                    f"Terminal boundary: {last_fallback_report.terminal_boundary}",
                    f"Stop reason: {last_fallback_report.stop_reason}",
                ],
            )
        return PortfolioSlotReport(
            slot_id=slot.slot_id,
            mode=slot.mode,
            purpose=slot.purpose,
            active_candidate_id=slot.active_candidate_id,
            allowed_families=list(slot.allowed_families),
            codex_execution_mode=slot.codex_execution_mode,
            status="research_manager_blocked",
            last_action="no_allowed_family_configured",
            mutation_occurred=False,
            artifact_paths=artifact_paths,
            notes=["Blank-slate research slot did not resolve any allowed family."],
        )

    mutation_occurred = _manager_mutation_occurred(selected_report)
    artifact_paths["autonomous_manager_report_path"] = str(selected_report.report_path)

    benchmark_candidate_id = _resolve_locked_benchmark_candidate(settings)
    notes = [
        *attempted_notes,
        f"Selected family: {selected_family}",
        f"Terminal boundary: {selected_report.terminal_boundary}",
        f"Stop reason: {selected_report.stop_reason}",
    ]
    if benchmark_candidate_id:
        notes.append(f"Locked benchmark candidate: {benchmark_candidate_id}")

    challenger_candidate_id = selected_report.handoff_candidate_id
    if challenger_candidate_id:
        artifact_paths["challenger_candidate_id"] = challenger_candidate_id
        if benchmark_candidate_id and challenger_candidate_id == benchmark_candidate_id:
            return PortfolioSlotReport(
                slot_id=slot.slot_id,
                mode=slot.mode,
                purpose=slot.purpose,
                active_candidate_id=slot.active_candidate_id,
                allowed_families=list(slot.allowed_families),
                codex_execution_mode=slot.codex_execution_mode,
                status="research_manager_blocked",
                last_action=f"ran_autonomous_manager:{selected_family}",
                mutation_occurred=False,
                artifact_paths=artifact_paths,
                notes=[
                    *notes,
                    "challenger_conflict_with_locked_benchmark: challenger cannot reuse benchmark candidate identity.",
                ],
            )
        promotion_packet = _load_promotion_packet(settings, candidate_id=challenger_candidate_id)
        if promotion_packet is None:
            return PortfolioSlotReport(
                slot_id=slot.slot_id,
                mode=slot.mode,
                purpose=slot.purpose,
                active_candidate_id=slot.active_candidate_id,
                allowed_families=list(slot.allowed_families),
                codex_execution_mode=slot.codex_execution_mode,
                status="research_manager_blocked",
                last_action=f"ran_autonomous_manager:{selected_family}",
                mutation_occurred=False,
                artifact_paths=artifact_paths,
                notes=[
                    *notes,
                    "challenger_missing_promotion_packet: candidate cannot enter challenger lane without promotion_decision_packet.",
                ],
            )
        artifact_paths["challenger_promotion_packet_path"] = str(promotion_packet.report_path)
        notes.append(
            f"challenger packet ladder state: {promotion_packet.deployment_ladder_state}; decision_status={promotion_packet.decision_status}"
        )

    return PortfolioSlotReport(
        slot_id=slot.slot_id,
        mode=slot.mode,
        purpose=slot.purpose,
        active_candidate_id=slot.active_candidate_id,
        allowed_families=list(slot.allowed_families),
        codex_execution_mode=slot.codex_execution_mode,
        status="research_manager_executed" if mutation_occurred else "research_manager_blocked",
        last_action=f"ran_autonomous_manager:{selected_family}",
        mutation_occurred=mutation_occurred,
        artifact_paths=artifact_paths,
        notes=notes,
    )


def _manager_report_is_slot_fallback_boundary(manager_report: AutonomousManagerReport) -> bool:
    if manager_report.terminal_boundary != "blocked_no_authorized_path":
        return False
    if _manager_mutation_occurred(manager_report):
        return False
    stop_reason = manager_report.stop_reason
    fallback_prefixes = (
        "program_loop_no_pending_approved_lanes",
        "program_loop_low_novelty_seed:",
        "program_loop_archetype_retired:",
        "program_loop_missing_family_evidence:",
    )
    return any(stop_reason.startswith(prefix) for prefix in fallback_prefixes)


def _manager_mutation_occurred(manager_report: AutonomousManagerReport) -> bool:
    if manager_report.handoff_candidate_id:
        return True
    if any(summary.material_transition or summary.approvals_issued for summary in manager_report.cycle_summaries):
        return True
    return manager_report.stop_reason == "ea_test_ready"


def _portfolio_manager_run_id(slot_id: str, family: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"portfolio-{slot_id}-{family}-{timestamp}"


def _resolve_locked_benchmark_candidate(settings: Settings) -> str | None:
    for slot in settings.portfolio.slots:
        if slot.mode == "locked_benchmark" and slot.active_candidate_id:
            return slot.active_candidate_id
    return None


def _load_promotion_packet(settings: Settings, *, candidate_id: str) -> PromotionDecisionPacket | None:
    packet_path = settings.paths().goblin_deployment_bundles_dir / candidate_id / "promotion_decision_packet.json"
    if not packet_path.exists():
        return None
    packet = PromotionDecisionPacket.model_validate(read_json(packet_path))
    return packet.model_copy(update={"report_path": packet_path})


def _latest_run_file(run_root: Path, file_name: str) -> Path | None:
    if not run_root.exists():
        return None
    matches = sorted(run_root.glob(f"*/{file_name}"))
    if not matches:
        return None
    return matches[-1]


def _extract_status_lines(status_path: Path) -> list[str]:
    lines: list[str] = []
    for raw_line in status_path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text.startswith("-"):
            continue
        text = re.sub(r"^-\s*", "", text)
        text = text.replace("`", "").strip()
        if text:
            lines.append(text)
    return lines[:6]
