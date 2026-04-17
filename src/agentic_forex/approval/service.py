from __future__ import annotations

import json
from pathlib import Path
from shutil import copy2
from typing import Any

from agentic_forex.approval.models import ApprovalRecord, PublishManifest
from agentic_forex.config import Settings
from agentic_forex.goblin.controls import enforce_candidate_strategy_governance
from agentic_forex.governance.control_plane import fingerprint_evidence_paths, latest_evaluation_revision, policy_snapshot_hash
from agentic_forex.governance.incident import candidate_validation_suspended
from agentic_forex.governance.trial_ledger import append_trial_entry
from agentic_forex.utils.io import read_json, write_json


def publish_candidate(candidate_id: str, settings: Settings) -> PublishManifest:
    if candidate_validation_suspended(candidate_id, settings):
        raise PermissionError(f"{candidate_id} is validation-suspended by an active production incident.")
    enforce_candidate_strategy_governance(settings, candidate_id=candidate_id)
    source_dir = settings.paths().reports_dir / candidate_id
    review_packet = source_dir / "review_packet.json"
    if not review_packet.exists():
        raise FileNotFoundError(f"Review packet missing for {candidate_id}; run review-candidate before publish.")
    if latest_stage_decision(candidate_id, "human_review", settings) != "approve":
        raise PermissionError(f"{candidate_id} requires an approved 'human_review' record before publish.")
    published_root = settings.paths().published_dir / candidate_id
    existing = sorted(path for path in published_root.glob("v*") if path.is_dir())
    version = f"v{len(existing) + 1:04d}"
    snapshot_dir = published_root / version
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[str] = []
    if source_dir.exists():
        for item in source_dir.iterdir():
            if item.is_file():
                copy2(item, snapshot_dir / item.name)
                artifacts.append(item.name)
    manifest = PublishManifest(
        candidate_id=candidate_id,
        version=version,
        manifest_path=snapshot_dir / "manifest.json",
        snapshot_dir=snapshot_dir,
        artifacts=artifacts,
        notes=[
            "This snapshot is a research archive only.",
            "published_research_snapshot is not equivalent to deployment readiness.",
            "Promotion beyond research archiving still requires parity, forward-stage evidence, and human review gates.",
        ],
    )
    write_json(manifest.manifest_path, manifest.model_dump(mode="json"))
    review_payload = read_json(review_packet)
    append_trial_entry(
        settings,
        candidate_id=candidate_id,
        family=str(review_payload.get("family") or "scalping"),
        stage="published_research_snapshot",
        artifact_paths={
            "manifest_path": str(manifest.manifest_path),
            "snapshot_dir": str(snapshot_dir),
        },
        gate_outcomes={
            "version": version,
            "artifact_count": len(artifacts),
            "publication_type": manifest.publication_type,
            "deployment_ready": manifest.deployment_ready,
            "readiness_status": review_payload.get("readiness"),
        },
    )
    return manifest


def record_approval(record: ApprovalRecord, settings: Settings) -> Path:
    log_path = settings.paths().approvals_dir / "approval_log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if record.approval_idempotency_key:
        existing = _approval_by_idempotency_key(record.approval_idempotency_key, settings)
        if existing is not None:
            if _approval_payload_fingerprint(existing) == _approval_payload_fingerprint(record):
                return log_path
            raise ValueError(f"approval_idempotency_conflict:{record.approval_idempotency_key}")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.model_dump(mode="json"), default=str) + "\n")
    return log_path


def latest_manifest(candidate_id: str, settings: Settings) -> PublishManifest:
    published_root = settings.paths().published_dir / candidate_id
    versions = sorted(path for path in published_root.glob("v*") if path.is_dir())
    if not versions:
        raise FileNotFoundError(f"No published snapshot found for {candidate_id}")
    return PublishManifest.model_validate(read_json(versions[-1] / "manifest.json"))


def is_stage_approved(
    candidate_id: str,
    stage: str,
    settings: Settings,
    *,
    require_fresh: bool = False,
    current_policy_snapshot_hash: str | None = None,
) -> bool:
    status = approval_status(
        candidate_id,
        stage,
        settings,
        current_policy_snapshot_hash=current_policy_snapshot_hash,
    )
    if not status["approved"]:
        return False
    if require_fresh and (not status["fresh"] or status["superseded"]):
        return False
    return True


def latest_stage_decision(candidate_id: str, stage: str, settings: Settings) -> str | None:
    record = latest_stage_record(candidate_id, stage, settings)
    return record.decision if record else None


def latest_stage_record(candidate_id: str, stage: str, settings: Settings) -> ApprovalRecord | None:
    log_path = settings.paths().approvals_dir / "approval_log.jsonl"
    if not log_path.exists():
        return None
    latest: ApprovalRecord | None = None
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if payload.get("candidate_id") == candidate_id and payload.get("stage") == stage:
                latest = ApprovalRecord.model_validate(payload)
    return latest


def require_stage_approval(candidate_id: str, stage: str, settings: Settings) -> None:
    if not is_stage_approved(candidate_id, stage, settings):
        raise PermissionError(f"{candidate_id} requires an approved '{stage}' record before continuing.")


def approval_status(
    candidate_id: str,
    stage: str,
    settings: Settings,
    *,
    current_policy_snapshot_hash: str | None = None,
) -> dict[str, Any]:
    record = latest_stage_record(candidate_id, stage, settings)
    if record is None:
        return {
            "approved": False,
            "fresh": False,
            "superseded": False,
            "stale_reasons": ["missing_approval"],
            "record": None,
        }
    if record.decision != "approve":
        return {
            "approved": False,
            "fresh": False,
            "superseded": False,
            "stale_reasons": ["latest_decision_not_approve"],
            "record": record,
        }
    policy_hash = current_policy_snapshot_hash or policy_snapshot_hash(settings)
    stale_reasons: list[str] = []
    if record.stage == "human_review" and record.source == "policy_engine":
        stale_reasons.append("human_review_requires_human_source")
    if record.policy_snapshot_hash and record.policy_snapshot_hash != policy_hash:
        stale_reasons.append("policy_snapshot_mismatch")
    if record.evidence_fingerprint and record.evidence_paths:
        current_fingerprint = fingerprint_evidence_paths(record.evidence_paths, policy_hash=policy_hash)
        if current_fingerprint != record.evidence_fingerprint:
            stale_reasons.append("evidence_fingerprint_changed")
    elif record.evidence_paths:
        for value in record.evidence_paths.values():
            if not Path(value).exists():
                stale_reasons.append("evidence_missing")
                break
    latest_revision = latest_evaluation_revision(candidate_id, stage, settings)
    superseded = latest_revision > int(record.evaluation_revision or 0)
    return {
        "approved": True,
        "fresh": not stale_reasons,
        "superseded": superseded,
        "stale_reasons": stale_reasons,
        "record": record,
        "latest_evaluation_revision": latest_revision,
    }


def issue_machine_approval(
    candidate_id: str,
    stage: str,
    settings: Settings,
    *,
    evidence_paths: dict[str, str],
    rationale: str,
    approver: str = "policy_engine",
    idempotency_key: str | None = None,
) -> ApprovalRecord:
    if stage == "human_review":
        raise PermissionError("human_review requires an explicit human approval record.")
    snapshot_hash = policy_snapshot_hash(settings)
    record = ApprovalRecord(
        candidate_id=candidate_id,
        stage=stage,
        decision="approve",
        approver=approver,
        rationale=rationale,
        source="policy_engine",
        evidence_paths=evidence_paths,
        policy_snapshot_hash=snapshot_hash,
        evidence_fingerprint=fingerprint_evidence_paths(evidence_paths, policy_hash=snapshot_hash),
        approval_idempotency_key=idempotency_key,
        evaluation_revision=max(latest_evaluation_revision(candidate_id, stage, settings), 1),
        attestation={
            "prerequisites_verified": True,
            "freshness_verified": True,
            "policy_snapshot_hash_verified": True,
            "legal_transition_verified": True,
            "ranking_inputs_unchanged": True,
            "queue_scope_unchanged": True,
            "strategy_logic_unchanged": True,
        },
    )
    record_approval(record, settings)
    return record


def _approval_by_idempotency_key(key: str, settings: Settings) -> ApprovalRecord | None:
    log_path = settings.paths().approvals_dir / "approval_log.jsonl"
    if not log_path.exists():
        return None
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if payload.get("approval_idempotency_key") == key:
                return ApprovalRecord.model_validate(payload)
    return None


def _approval_payload_fingerprint(record: ApprovalRecord) -> str:
    payload = record.model_dump(mode="json", exclude={"recorded_utc"})
    return json.dumps(payload, sort_keys=True, default=str)
