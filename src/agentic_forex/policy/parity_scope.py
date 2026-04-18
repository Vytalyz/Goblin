from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from agentic_forex.config import Settings
from agentic_forex.config.models import ParityClass, ProgramLanePolicy
from agentic_forex.governance.models import AutonomousManagerReport
from agentic_forex.utils.io import read_json, write_json

ScopeStatus = Literal[
    "in_scope_under_current_m1",
    "blocked_tick_required_pending_official_standard",
    "review_needed_before_official_parity",
    "archival_or_reference_only",
    "conflicting_parity_assignments",
]


class FrozenReferenceCandidate(BaseModel):
    candidate_id: str
    family: str | None = None
    hypothesis_class: str | None = None
    official_parity_class: ParityClass | None = None
    current_status: str
    source_path: Path


class ParityScopeLineage(BaseModel):
    family: str
    hypothesis_class: str
    seed_candidate_ids: list[str] = Field(default_factory=list)
    lane_ids: list[str] = Field(default_factory=list)
    queue_kinds: list[str] = Field(default_factory=list)
    parity_class: ParityClass | None = None
    official_parity_allowed: bool = False
    diagnostic_parity_allowed: bool = True
    current_scope_status: ScopeStatus
    latest_manager_stop_reason: str | None = None
    latest_manager_report_path: Path | None = None
    notes: list[str] = Field(default_factory=list)


class ParityScopeAuditReport(BaseModel):
    generated_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    total_lineages: int = 0
    explicit_parity_class_lineages: int = 0
    tick_required_lineages: int = 0
    unresolved_review_needed_lineages: int = 0
    archival_reference_only_lineages: int = 0
    unset_parity_class_lineages: int = 0
    conflicting_parity_class_lineages: int = 0
    lineages: list[ParityScopeLineage] = Field(default_factory=list)
    frozen_reference_candidates: list[FrozenReferenceCandidate] = Field(default_factory=list)
    report_path: Path


def build_parity_scope_audit(
    settings: Settings,
    *,
    write_docs: bool = True,
) -> ParityScopeAuditReport:
    grouped_lanes = _group_lineages(settings.program.approved_lanes)
    latest_manager_reports = _latest_manager_reports_by_family(settings)

    lineages: list[ParityScopeLineage] = []
    explicit_count = 0
    tick_required_count = 0
    review_needed_count = 0
    archival_count = 0
    unset_count = 0
    conflicting_count = 0

    for (family, hypothesis_class), lanes in sorted(grouped_lanes.items()):
        lineage = _build_lineage_record(
            settings,
            family=family,
            hypothesis_class=hypothesis_class,
            lanes=lanes,
            latest_manager_report=latest_manager_reports.get(family),
        )
        lineages.append(lineage)
        if lineage.current_scope_status == "conflicting_parity_assignments":
            conflicting_count += 1
        elif lineage.parity_class is not None:
            explicit_count += 1
            if lineage.parity_class == "tick_required":
                tick_required_count += 1
        else:
            unset_count += 1
            if lineage.current_scope_status == "review_needed_before_official_parity":
                review_needed_count += 1
            elif lineage.current_scope_status == "archival_or_reference_only":
                archival_count += 1

    report = ParityScopeAuditReport(
        total_lineages=len(lineages),
        explicit_parity_class_lineages=explicit_count,
        tick_required_lineages=tick_required_count,
        unresolved_review_needed_lineages=review_needed_count,
        archival_reference_only_lineages=archival_count,
        unset_parity_class_lineages=unset_count,
        conflicting_parity_class_lineages=conflicting_count,
        lineages=lineages,
        frozen_reference_candidates=_load_frozen_reference_candidates(settings),
        report_path=settings.paths().policy_reports_dir / "parity_scope_audit.json",
    )
    write_json(report.report_path, report.model_dump(mode="json"))
    if write_docs:
        _write_parity_lineage_audit_doc(settings, report)
        _write_parity_operator_matrix_doc(settings, report)
    return report


def _group_lineages(approved_lanes: list[ProgramLanePolicy]) -> dict[tuple[str, str], list[ProgramLanePolicy]]:
    grouped: dict[tuple[str, str], list[ProgramLanePolicy]] = {}
    for lane in approved_lanes:
        grouped.setdefault((lane.family, lane.hypothesis_class), []).append(lane)
    return grouped


def _build_lineage_record(
    settings: Settings,
    *,
    family: str,
    hypothesis_class: str,
    lanes: list[ProgramLanePolicy],
    latest_manager_report: AutonomousManagerReport | None,
) -> ParityScopeLineage:
    explicit_classes = {lane.parity_class for lane in lanes if lane.parity_class is not None}
    has_unset_lanes = any(lane.parity_class is None for lane in lanes)
    notes: list[str] = []
    parity_class: ParityClass | None = None

    if len(explicit_classes) > 1:
        scope_status: ScopeStatus = "conflicting_parity_assignments"
        notes.append("Lineage has multiple explicit parity_class values across approved lanes.")
    elif explicit_classes and has_unset_lanes:
        scope_status = "conflicting_parity_assignments"
        notes.append("Lineage mixes explicit and unset parity_class values across approved lanes.")
    elif explicit_classes:
        parity_class = next(iter(explicit_classes))
        if parity_class == "m1_official":
            scope_status = "in_scope_under_current_m1"
        else:
            scope_status = "blocked_tick_required_pending_official_standard"
            notes.append(
                "Lineage is explicitly classified as tick_required and remains blocked until a class-wide official standard exists."
            )
    else:
        scope_status = _infer_unresolved_scope_status(latest_manager_report)
        if scope_status == "review_needed_before_official_parity":
            notes.append("Lineage is unresolved and must be classified prospectively before any official parity run.")
        elif scope_status == "archival_or_reference_only":
            notes.append("Lineage is currently archival or reference-only unless explicitly reopened.")

    return ParityScopeLineage(
        family=family,
        hypothesis_class=hypothesis_class,
        seed_candidate_ids=sorted({lane.seed_candidate_id for lane in lanes}),
        lane_ids=sorted({lane.lane_id for lane in lanes}),
        queue_kinds=sorted({lane.queue_kind for lane in lanes}),
        parity_class=parity_class,
        official_parity_allowed=scope_status == "in_scope_under_current_m1",
        diagnostic_parity_allowed=True,
        current_scope_status=scope_status,
        latest_manager_stop_reason=latest_manager_report.stop_reason if latest_manager_report else None,
        latest_manager_report_path=latest_manager_report.report_path if latest_manager_report else None,
        notes=notes,
    )


def _latest_manager_reports_by_family(settings: Settings) -> dict[str, AutonomousManagerReport]:
    latest: dict[str, tuple[float, AutonomousManagerReport]] = {}
    for report_path in settings.paths().autonomous_manager_dir.glob("*.json"):
        try:
            report = AutonomousManagerReport.model_validate(read_json(report_path))
        except Exception:  # noqa: BLE001
            continue
        last_modified = report_path.stat().st_mtime
        current = latest.get(report.family)
        if current is None or last_modified > current[0]:
            latest[report.family] = (last_modified, report)
    return {family: payload for family, (_, payload) in latest.items()}


def _infer_unresolved_scope_status(latest_manager_report: AutonomousManagerReport | None) -> ScopeStatus:
    if latest_manager_report is None:
        return "review_needed_before_official_parity"

    reason = str(latest_manager_report.stop_reason or "")
    archival_markers = (
        "family_retire_confirmed",
        "retire_family",
        "retire_lane",
        "structural_regime_instability",
        "program_loop_no_pending_approved_lanes",
        "program_loop_archetype_retired",
        "program_loop_low_novelty_seed",
    )
    if any(marker in reason for marker in archival_markers):
        return "archival_or_reference_only"

    review_markers = (
        "watchdog_",
        "max_cycles_reached",
        "program_loop_max_lanes_reached",
        "program_loop_parent_lane_hard_stop",
        "blocked_no_authorized_path",
    )
    if any(marker in reason for marker in review_markers):
        return "review_needed_before_official_parity"

    if latest_manager_report.stop_class in {"blocked_budget", "blocked_policy", "policy_decision"}:
        return "review_needed_before_official_parity"
    return "archival_or_reference_only"


def _load_frozen_reference_candidates(settings: Settings) -> list[FrozenReferenceCandidate]:
    frozen: list[FrozenReferenceCandidate] = []
    for status_path in sorted(settings.paths().reports_dir.glob("AF-CAND-*/operational_status.md")):
        parsed = _parse_frozen_status(status_path)
        if parsed is not None:
            frozen.append(parsed)
    return frozen


def _parse_frozen_status(status_path: Path) -> FrozenReferenceCandidate | None:
    text = status_path.read_text(encoding="utf-8")
    parsed_lines = _parse_status_bullets(text)
    candidate_id = parsed_lines.get("Candidate")
    current_status = parsed_lines.get("Frozen status")
    if not candidate_id or not current_status:
        return None
    family = parsed_lines.get("Family")
    hypothesis_class = parsed_lines.get("Hypothesis class")
    parity_class_raw = parsed_lines.get("Official parity class")
    parity_class: ParityClass | None = None
    if parity_class_raw in {"m1_official", "tick_required"}:
        parity_class = parity_class_raw
    return FrozenReferenceCandidate(
        candidate_id=candidate_id,
        family=family,
        hypothesis_class=hypothesis_class,
        official_parity_class=parity_class,
        current_status=current_status,
        source_path=status_path,
    )


def _parse_status_bullets(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    current_nested_label: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        nested_match = re.match(r"^\s+-\s+`([^`]+)`\s*$", line)
        if nested_match and current_nested_label is not None:
            parsed[current_nested_label] = nested_match.group(1).strip()
            current_nested_label = None
            continue

        inline_match = re.match(r"^- ([^:]+):\s*`([^`]+)`\s*$", line)
        if inline_match:
            parsed[inline_match.group(1).strip()] = inline_match.group(2).strip()
            current_nested_label = None
            continue

        block_match = re.match(r"^- ([^:]+):\s*$", line)
        if block_match:
            current_nested_label = block_match.group(1).strip()
            continue

        current_nested_label = None
    return parsed


def _write_parity_lineage_audit_doc(settings: Settings, report: ParityScopeAuditReport) -> None:
    lines: list[str] = [
        "# Parity Lineage Audit",
        "",
        f"- Audit date: `{report.generated_utc[:10]}`",
        "- Scope: active throughput and promotion lanes in `config/program_policy.toml`",
        "- Goal: confirm explicit parity-class coverage after parity-class enforcement was added",
        "",
        "## Summary",
        "",
        f"- Total active family or hypothesis-class lineages: `{report.total_lineages}`",
        f"- Explicit parity-class lineages: `{report.explicit_parity_class_lineages}`",
        f"- Current unresolved review-needed lineages: `{report.unresolved_review_needed_lineages}`",
        f"- Archival or reference-only unresolved lineages: `{report.archival_reference_only_lineages}`",
        f"- Unset parity-class lineages: `{report.unset_parity_class_lineages}`",
        f"- Conflicting parity-class lineages: `{report.conflicting_parity_class_lineages}`",
        "",
        "## Conservative Scope Decision",
        "",
        "- Current official scope remains conservative.",
        '- Only lineages with an explicit `parity_class = "m1_official"` are currently in scope for official parity.',
        "- Lineages with `parity_class = <unset>` are blocked for official parity until they are classified prospectively in policy.",
        "- Diagnostic parity remains allowed as a non-authoritative investigation tool.",
        "",
        "## Current Live Scope",
        "",
        "### In Scope Now",
        "",
    ]

    in_scope = [lineage for lineage in report.lineages if lineage.current_scope_status == "in_scope_under_current_m1"]
    if in_scope:
        for lineage in in_scope:
            lines.extend(
                [
                    f"- `{lineage.family} / {lineage.hypothesis_class}`",
                    f"  - roots: `{', '.join(lineage.seed_candidate_ids)}`",
                    f"  - parity class: `{lineage.parity_class}`",
                    "  - current status:",
                    "    - live under the current official standard",
                ]
            )
            if any(candidate.candidate_id == "AF-CAND-0239" for candidate in report.frozen_reference_candidates):
                if (
                    lineage.family == "session_momentum_band_research"
                    and lineage.hypothesis_class == "session_momentum_band"
                ):
                    lines.append(
                        "    - `AF-CAND-0239` remains frozen as `research-valid, parity-blocked, operationally unproven under current official M1 parity standard`"
                    )
    else:
        lines.extend(["- None.", ""])

    lines.extend(["", "### Explicit Tick-Required Lineages", ""])
    tick_required = [
        lineage
        for lineage in report.lineages
        if lineage.current_scope_status == "blocked_tick_required_pending_official_standard"
    ]
    if tick_required:
        for lineage in tick_required:
            lines.extend(
                [
                    f"- `{lineage.family} / {lineage.hypothesis_class}`",
                    f"  - roots: `{', '.join(lineage.seed_candidate_ids)}`",
                    "  - status: blocked until a class-wide official `tick_required` standard exists",
                ]
            )
    else:
        lines.append("- None.")

    lines.extend(["", "### Review Needed Before Any Future Official Parity", ""])
    review_needed = [
        lineage for lineage in report.lineages if lineage.current_scope_status == "review_needed_before_official_parity"
    ]
    if review_needed:
        lines.extend(
            [
                "",
                "These lineages are not retired cleanly enough to be treated as archival only, but they are still unresolved and must not enter official parity until they are classified prospectively:",
                "",
            ]
        )
        for lineage in review_needed:
            lines.extend(
                [
                    f"- `{lineage.family} / {lineage.hypothesis_class}`",
                    f"  - roots: `{', '.join(lineage.seed_candidate_ids)}`",
                    f"  - latest manager outcome: `{lineage.latest_manager_stop_reason or 'no_manager_evidence'}`",
                ]
            )
        lines.extend(
            [
                "",
                "Conservative interpretation:",
                "",
                "- these remain `parity_class = <unset>`",
                "- they are blocked for official parity",
                "- they are the first unresolved lineages to classify if this family is reopened",
            ]
        )
    else:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "## Archival Or Reference-Only Unresolved Scope",
            "",
            "All other unresolved lineages are currently treated as archival or reference-only because their latest governed outcomes already closed them materially, for example:",
            "",
            "- family retirement confirmed",
            "- retire-family or retire-lane audit",
            "- no pending approved lanes",
            "- archetype retired",
            "- low-novelty seed block",
            "",
            "## Explicitly Classified Lineages",
            "",
        ]
    )
    explicit_lineages = [lineage for lineage in report.lineages if lineage.parity_class is not None]
    if explicit_lineages:
        for lineage in explicit_lineages:
            lines.extend(
                [
                    f"- `{lineage.family} / {lineage.hypothesis_class}`",
                    f"  - roots: `{', '.join(lineage.seed_candidate_ids)}`",
                    f"  - queue kinds: `{', '.join(lineage.queue_kinds)}`",
                    f"  - parity class: `{lineage.parity_class}`",
                ]
            )
    else:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "## Main Audit Finding",
            "",
            "- The repo now enforces parity class correctly, but the policy file is still mostly legacy-shaped.",
            "- Only explicitly classified lineages are eligible for official parity.",
            "- Review-needed unresolved lineages should be classified prospectively if their families are reopened.",
            "- All other unresolved lineages are better treated as archival or reference-only until explicitly reopened.",
            "- This is not an integrity bug anymore, because official parity will now block if unresolved lineages try to advance.",
            "",
            "## Operational Rule After This Audit",
            "",
            "- Do not treat `<unset>` as implicitly `m1_official`.",
            "- Do not backfill parity class from candidate outcomes.",
            "- Do not use diagnostic parity as promotion truth.",
            "- If a lineage needs official parity, classify it first in `program_policy.toml`.",
        ]
    )

    if report.frozen_reference_candidates:
        lines.extend(["", "## Reference Candidates", ""])
        for candidate in report.frozen_reference_candidates:
            lines.extend(
                [
                    f"- `{candidate.candidate_id}`",
                    f"  - status: `{candidate.current_status}`",
                    f"  - source: `{candidate.source_path}`",
                ]
            )

    path = settings.paths().knowledge_dir / "parity-lineage-audit.md"
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_parity_operator_matrix_doc(settings: Settings, report: ParityScopeAuditReport) -> None:
    lines: list[str] = [
        "# Parity Operator Matrix",
        "",
        "This file is the operator-facing control surface for current parity scope. It is intentionally shorter than the raw policy file and should be read alongside `knowledge/parity-lineage-audit.md`.",
        "",
        "## Frozen Reference Candidates",
        "",
    ]

    if report.frozen_reference_candidates:
        lines.extend(
            [
                "| Candidate | Family | Official Parity Class | Official Parity Allowed | Diagnostic Allowed | Current Status |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for candidate in report.frozen_reference_candidates:
            official_allowed = "yes" if candidate.official_parity_class == "m1_official" else "no"
            lines.append(
                f"| `{candidate.candidate_id}` | `{candidate.family or ''}` | `{candidate.official_parity_class or '<unset>'}` | {official_allowed} | yes | `{candidate.current_status}` |"
            )
    else:
        lines.append("- None.")

    def _append_lineage_table(title: str, wanted_status: ScopeStatus) -> None:
        matching = [lineage for lineage in report.lineages if lineage.current_scope_status == wanted_status]
        lines.extend(["", f"## {title}", ""])
        if not matching:
            lines.append("- None.")
            return
        lines.extend(
            [
                "| Family | Hypothesis Class | Seed Roots | Official Parity Class | Official Parity Allowed | Diagnostic Allowed | Current Scope Status |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for lineage in matching:
            lines.append(
                f"| `{lineage.family}` | `{lineage.hypothesis_class}` | `{', '.join(lineage.seed_candidate_ids)}` | `{lineage.parity_class or '<unset>'}` | {'yes' if lineage.official_parity_allowed else 'no'} | {'yes' if lineage.diagnostic_parity_allowed else 'no'} | `{lineage.current_scope_status}` |"
            )

    _append_lineage_table("Current In-Scope Lineages", "in_scope_under_current_m1")
    _append_lineage_table(
        "Explicit Tick-Required Lineages",
        "blocked_tick_required_pending_official_standard",
    )
    _append_lineage_table(
        "Current Review-Needed Lineages",
        "review_needed_before_official_parity",
    )
    _append_lineage_table(
        "Conflicting Parity Assignments",
        "conflicting_parity_assignments",
    )

    archival_families = sorted(
        {lineage.family for lineage in report.lineages if lineage.current_scope_status == "archival_or_reference_only"}
    )
    lines.extend(["", "## Archival Or Reference-Only Families", ""])
    if archival_families:
        lines.extend(
            [
                "These families remain in the repo for evidence lineage, but their latest governed outcomes already closed them materially. Treat them as archival unless explicitly reopened through policy.",
                "",
            ]
        )
        for family in archival_families:
            lines.append(f"- `{family}`")
    else:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "## Working Rule",
            "",
            "- Only explicit `m1_official` lineages are currently eligible for official parity.",
            "- `<unset>` never means implicit `m1_official`.",
            "- Diagnostic parity may be used to explain failures, but it cannot establish promotion truth.",
            "- If a review-needed lineage is reopened, classify it prospectively before any official parity run.",
        ]
    )

    path = settings.paths().knowledge_dir / "parity-operator-matrix.md"
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
