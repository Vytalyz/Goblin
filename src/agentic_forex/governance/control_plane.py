from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agentic_forex.config import Settings
from agentic_forex.governance.models import IdempotencyRecord, IntegrityIncident, LeaseRecord, ProgramEvent
from agentic_forex.utils.io import read_json, write_json


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def policy_snapshot_hash(settings: Settings) -> str:
    payload = {
        "data": settings.data.model_dump(mode="json"),
        "validation": settings.validation.model_dump(mode="json"),
        "campaign": settings.campaign.model_dump(mode="json"),
        "program": settings.program.model_dump(mode="json"),
        "autonomy": settings.autonomy.model_dump(mode="json"),
        "mt5_env": settings.mt5_env.model_dump(mode="json"),
        "policy": settings.policy.model_dump(mode="json"),
    }
    return stable_hash(payload)


def fingerprint_evidence_paths(
    evidence_paths: dict[str, str | Path],
    *,
    policy_hash: str | None = None,
) -> str:
    payload: dict[str, Any] = {"policy_snapshot_hash": policy_hash}
    for key, value in sorted(evidence_paths.items()):
        path = Path(value)
        if path.exists() and path.is_file():
            payload[key] = {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        else:
            payload[key] = {"path": str(path), "missing": True}
    return stable_hash(payload)


def authoritative_state_snapshot_hash(settings: Settings, *, campaign_id: str | None) -> str:
    paths: list[Path] = []
    if campaign_id:
        campaign_dir = settings.paths().campaigns_dir / campaign_id
        paths.extend(
            [
                campaign_dir / "state.json",
                campaign_dir / "next_step_report.json",
                campaign_dir / "next_recommendations.json",
            ]
        )
    paths.extend(
        [
            settings.paths().approvals_dir / "approval_log.jsonl",
            settings.paths().observational_knowledge_dir / "failure_records.jsonl",
            settings.paths().experiments_dir / "trial_ledger.jsonl",
        ]
    )
    payload: dict[str, Any] = {}
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        payload[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return stable_hash(payload)


def campaign_state_version(settings: Settings, campaign_id: str | None) -> int:
    if not campaign_id:
        return 0
    state_path = settings.paths().campaigns_dir / campaign_id / "state.json"
    if not state_path.exists():
        return 0
    payload = read_json(state_path)
    return int(payload.get("state_version") or 0)


def latest_evaluation_revision(candidate_id: str, stage: str, settings: Settings) -> int:
    report_dir = settings.paths().reports_dir / candidate_id
    stage_path = _evaluation_report_path(report_dir, stage)
    if stage_path is None or not stage_path.exists():
        return 0
    payload = read_json(stage_path)
    return int(payload.get("evaluation_revision") or 1)


def append_event(settings: Settings, event: ProgramEvent) -> Path:
    path = settings.paths().events_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event.model_dump(mode="json"), default=str) + "\n")
    return path


def write_incident(settings: Settings, incident: IntegrityIncident) -> Path:
    write_json(incident.report_path, incident.model_dump(mode="json"))
    return incident.report_path


def load_lease(settings: Settings, lease_key: str) -> LeaseRecord | None:
    path = _lease_path(settings, lease_key)
    if not path.exists():
        return None
    return LeaseRecord.model_validate(read_json(path))


def acquire_lease(
    settings: Settings,
    *,
    lease_key: str,
    owner_id: str,
    manager_run_id: str,
    policy_hash: str,
    state_version_at_acquire: int,
    ttl_seconds: int,
) -> LeaseRecord:
    now = datetime.now(UTC)
    path = _lease_path(settings, lease_key)
    existing = load_lease(settings, lease_key)
    if existing and existing.active and _parse_utc(existing.expires_utc) > now and existing.owner_id != owner_id:
        raise PermissionError(f"lease_conflict:{lease_key}")
    fencing_token = (existing.fencing_token + 1) if existing else 1
    lease = LeaseRecord(
        lease_key=lease_key,
        owner_id=owner_id,
        manager_run_id=manager_run_id,
        acquired_utc=_format_utc(now),
        heartbeat_utc=_format_utc(now),
        expires_utc=_format_utc(now + timedelta(seconds=ttl_seconds)),
        fencing_token=fencing_token,
        state_version_at_acquire=state_version_at_acquire,
        policy_snapshot_hash=policy_hash,
        active=True,
        report_path=path,
    )
    write_json(path, lease.model_dump(mode="json"))
    return lease


def heartbeat_lease(
    settings: Settings, *, lease_key: str, owner_id: str, fencing_token: int, ttl_seconds: int
) -> LeaseRecord:
    lease = load_lease(settings, lease_key)
    if lease is None or not lease.active:
        raise PermissionError(f"lease_missing:{lease_key}")
    if lease.owner_id != owner_id or lease.fencing_token != fencing_token:
        raise PermissionError(f"lease_fencing_mismatch:{lease_key}")
    now = datetime.now(UTC)
    lease.heartbeat_utc = _format_utc(now)
    lease.expires_utc = _format_utc(now + timedelta(seconds=ttl_seconds))
    write_json(lease.report_path, lease.model_dump(mode="json"))
    return lease


def release_lease(settings: Settings, *, lease_key: str, owner_id: str, fencing_token: int) -> LeaseRecord | None:
    lease = load_lease(settings, lease_key)
    if lease is None:
        return None
    if lease.owner_id != owner_id or lease.fencing_token != fencing_token:
        raise PermissionError(f"lease_fencing_mismatch:{lease_key}")
    lease.active = False
    lease.heartbeat_utc = _format_utc(datetime.now(UTC))
    write_json(lease.report_path, lease.model_dump(mode="json"))
    return lease


def load_idempotency_record(settings: Settings, idempotency_key: str) -> IdempotencyRecord | None:
    path = _idempotency_path(settings, idempotency_key)
    if not path.exists():
        return None
    return IdempotencyRecord.model_validate(read_json(path))


def record_idempotency_result(
    settings: Settings,
    *,
    idempotency_key: str,
    payload_fingerprint: str,
    manager_run_id: str,
    outcome_path: Path | None,
    metadata: dict[str, Any] | None = None,
) -> IdempotencyRecord:
    record = IdempotencyRecord(
        idempotency_key=idempotency_key,
        payload_fingerprint=payload_fingerprint,
        manager_run_id=manager_run_id,
        outcome_path=outcome_path,
        metadata=metadata or {},
        report_path=_idempotency_path(settings, idempotency_key),
    )
    write_json(record.report_path, record.model_dump(mode="json"))
    return record


def _evaluation_report_path(report_dir: Path, stage: str) -> Path | None:
    if stage in {"robustness", "mt5_packet", "mt5_parity_run", "mt5_validation"}:
        return report_dir / "robustness_report.json"
    if stage in {"forward", "forward_stage", "human_review"}:
        return report_dir / "forward_stage_report.json"
    return None


def _lease_path(settings: Settings, lease_key: str) -> Path:
    token = hashlib.sha256(lease_key.encode("utf-8")).hexdigest()[:24]
    return settings.paths().leases_dir / f"{token}.json"


def _idempotency_path(settings: Settings, idempotency_key: str) -> Path:
    token = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]
    return settings.paths().idempotency_dir / f"{token}.json"


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
