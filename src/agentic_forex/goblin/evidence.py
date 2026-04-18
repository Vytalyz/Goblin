from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from shutil import copy2
from typing import Any

from agentic_forex.config import Settings
from agentic_forex.goblin.models import (
    ArtifactIndex,
    ArtifactProvenance,
    ArtifactRecord,
    ArtifactValidationResult,
    ResearchDataContract,
    TimeSessionContract,
    TruthAlignmentReport,
    TruthChannel,
)
from agentic_forex.goblin.service import TRUTH_CONTRACTS
from agentic_forex.utils.io import read_json, write_json

CHANNEL_DIR_MAP: dict[TruthChannel, str] = {
    "research_backtest": "research_backtest",
    "mt5_replay": "mt5_replay",
    "live_demo": "live_demo",
    "broker_account_history": "broker_account_history",
}


def ensure_goblin_evidence_roots(settings: Settings) -> None:
    paths = settings.paths()
    paths.ensure_directories()
    for channel in CHANNEL_DIR_MAP:
        channel_root(settings, channel).mkdir(parents=True, exist_ok=True)
        artifact_index_path(settings, channel).parent.mkdir(parents=True, exist_ok=True)


def channel_root(settings: Settings, channel: TruthChannel) -> Path:
    paths = settings.paths()
    mapping: dict[TruthChannel, Path] = {
        "research_backtest": paths.goblin_research_reports_dir,
        "mt5_replay": paths.goblin_mt5_replay_reports_dir,
        "live_demo": paths.goblin_live_demo_reports_dir,
        "broker_account_history": paths.goblin_broker_history_reports_dir,
    }
    return mapping[channel]


def artifact_index_path(settings: Settings, channel: TruthChannel) -> Path:
    return settings.paths().goblin_artifact_indexes_dir / f"{CHANNEL_DIR_MAP[channel]}.json"


def load_artifact_index(settings: Settings, channel: TruthChannel) -> ArtifactIndex:
    ensure_goblin_evidence_roots(settings)
    index_path = artifact_index_path(settings, channel)
    if not index_path.exists():
        index = ArtifactIndex(evidence_channel=channel, artifacts=[], index_path=index_path)
        write_json(index_path, index.model_dump(mode="json"))
        return index
    return ArtifactIndex.model_validate(read_json(index_path))


def validate_artifact_provenance(
    settings: Settings,
    *,
    provenance: ArtifactProvenance,
    artifact_path: Path,
) -> ArtifactValidationResult:
    ensure_goblin_evidence_roots(settings)
    resolved_path = artifact_path.resolve()
    expected_root = channel_root(settings, provenance.evidence_channel).resolve()
    conflicting_channel = None
    reasons: list[str] = []
    if not resolved_path.exists():
        reasons.append("artifact_missing")
    if not provenance.artifact_hash:
        reasons.append("artifact_hash_missing")
    if not provenance.candidate_id:
        reasons.append("candidate_id_missing")
    if not provenance.run_id:
        reasons.append("run_id_missing")
    if not provenance.symbol:
        reasons.append("symbol_missing")
    if not provenance.timezone_basis:
        reasons.append("timezone_basis_missing")
    for channel in CHANNEL_DIR_MAP:
        candidate_root = channel_root(settings, channel).resolve()
        if _is_relative_to(resolved_path, candidate_root) and channel != provenance.evidence_channel:
            conflicting_channel = channel
            reasons.append("cross_channel_artifact_path")
            break
    valid = not reasons or reasons == ["artifact_hash_missing"]
    return ArtifactValidationResult(
        evidence_channel=provenance.evidence_channel,
        artifact_path=resolved_path,
        valid=valid,
        reasons=reasons,
        channel_root=expected_root,
        conflicting_channel=conflicting_channel,
    )


def register_artifact(
    settings: Settings,
    *,
    provenance: ArtifactProvenance,
    artifact_path: Path,
    metadata: dict[str, Any] | None = None,
    authoritative: bool = False,
    snapshot: bool = True,
) -> ArtifactRecord:
    ensure_goblin_evidence_roots(settings)
    resolved_original = artifact_path.resolve()
    resolved_hash = provenance.artifact_hash or _sha256_file(resolved_original)
    resolved_provenance = provenance.model_copy(update={"artifact_hash": resolved_hash})
    validation = validate_artifact_provenance(settings, provenance=resolved_provenance, artifact_path=resolved_original)
    if not validation.valid:
        raise ValueError(f"artifact_validation_failed:{'|'.join(validation.reasons)}")

    managed_root = (
        channel_root(settings, resolved_provenance.evidence_channel)
        / resolved_provenance.candidate_id
        / resolved_provenance.run_id
    )
    managed_root.mkdir(parents=True, exist_ok=True)
    managed_path = managed_root / resolved_original.name
    if snapshot:
        copy2(resolved_original, managed_path)
    else:
        managed_path = resolved_original

    artifact_id = _artifact_id(
        resolved_provenance.evidence_channel,
        resolved_provenance.candidate_id,
        resolved_provenance.run_id,
        resolved_original.name,
        resolved_hash,
    )
    record = ArtifactRecord(
        artifact_id=artifact_id,
        provenance=resolved_provenance,
        original_path=resolved_original,
        managed_path=managed_path.resolve(),
        authoritative=authoritative,
        metadata=dict(metadata or {}),
    )
    index = load_artifact_index(settings, resolved_provenance.evidence_channel)
    index.artifacts = [item for item in index.artifacts if item.artifact_id != artifact_id]
    index.artifacts.append(record)
    index.generated_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    write_json(index.index_path, index.model_dump(mode="json"))
    return record


def latest_registered_artifact(
    settings: Settings,
    *,
    channel: TruthChannel,
    candidate_id: str,
    artifact_origin: str | None = None,
) -> ArtifactRecord | None:
    index = load_artifact_index(settings, channel)
    matches = [
        item
        for item in index.artifacts
        if item.provenance.candidate_id == candidate_id
        and (artifact_origin is None or item.provenance.artifact_origin == artifact_origin)
    ]
    if not matches:
        return None
    matches.sort(key=lambda item: item.registered_utc, reverse=True)
    return matches[0]


def artifact_by_id(settings: Settings, *, channel: TruthChannel, artifact_id: str) -> ArtifactRecord | None:
    index = load_artifact_index(settings, channel)
    for artifact in index.artifacts:
        if artifact.artifact_id == artifact_id:
            return artifact
    return None


def build_default_research_data_contract(
    settings: Settings,
    *,
    instrument: str | None = None,
    granularity: str | None = None,
) -> ResearchDataContract:
    return ResearchDataContract(
        instrument=instrument or settings.oanda.default_instrument or settings.data.instrument,
        price_component=str(settings.oanda.price_component or "BA"),  # type: ignore[arg-type]
        granularity=granularity or settings.data.base_granularity or settings.oanda.default_granularity,
        smooth=False,
        include_first=True,
        daily_alignment=17,
        alignment_timezone="America/New_York",
        weekly_alignment="Friday",
        utc_normalization_policy="store_utc_emit_utc",
    )


def build_default_time_session_contract(settings: Settings) -> TimeSessionContract:
    return TimeSessionContract(
        broker_timezone=settings.policy.ftmo_timezone,
        broker_offset_policy="named_timezone_database_with_dst",
        comparison_timezone_basis="UTC",
        london_timezone="Europe/London",
        new_york_timezone="America/New_York",
        overlap_definition="london_new_york_overlap",
        dst_policy="timezone_database_with_transition_boundaries",
        holiday_policy="broker_calendar_plus_major_market_holidays",
    )


def build_truth_alignment_report(
    settings: Settings,
    *,
    candidate_id: str,
    artifact_records: dict[TruthChannel, ArtifactRecord | None],
    governance_effect: str = "",
    deltas: dict[str, Any] | None = None,
) -> TruthAlignmentReport:
    ensure_goblin_evidence_roots(settings)
    present_channels = {channel for channel, record in artifact_records.items() if record is not None}
    time_session_contract = build_default_time_session_contract(settings)
    comparison_time_basis = time_session_contract.comparison_timezone_basis
    required_contracts = [
        contract
        for contract in TRUTH_CONTRACTS
        if contract.left_channel in present_channels and contract.right_channel in present_channels
    ]
    evidence_summaries = {
        channel: {
            "artifact_id": record.artifact_id,
            "artifact_origin": record.provenance.artifact_origin,
            "managed_path": str(record.managed_path),
            "registered_utc": record.registered_utc,
            "authoritative": record.authoritative,
            "artifact_hash": record.provenance.artifact_hash,
        }
        for channel, record in artifact_records.items()
        if record is not None
    }
    channel_timezones = {
        channel: str(record.provenance.timezone_basis)
        for channel, record in artifact_records.items()
        if record is not None
    }
    time_basis_mismatches = [
        f"{channel}:{timezone_basis}"
        for channel, timezone_basis in channel_timezones.items()
        if timezone_basis != comparison_time_basis
    ]
    report_dir = settings.paths().goblin_truth_alignment_reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "truth_alignment_report.json"
    report = TruthAlignmentReport(
        candidate_id=candidate_id,
        required_contracts=required_contracts,
        evidence_summaries=evidence_summaries,
        time_session_contract=time_session_contract,
        comparison_time_basis=comparison_time_basis,
        channel_timezones=channel_timezones,
        time_basis_consistent=not time_basis_mismatches,
        time_basis_mismatches=time_basis_mismatches,
        deltas=dict(deltas or {}),
        governance_effect=governance_effect,
        report_path=report_path,
    )
    write_json(report_path, report.model_dump(mode="json"))
    return report


def _artifact_id(
    channel: TruthChannel, candidate_id: str, run_id: str, filename: str, artifact_hash: str | None
) -> str:
    payload = f"{channel}|{candidate_id}|{run_id}|{filename}|{artifact_hash or 'none'}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_relative_to(path: Path, other: Path) -> bool:
    try:
        path.relative_to(other)
    except ValueError:
        return False
    return True
