from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

ApprovalStage = Literal[
    "human_review",
    "mt5_packet",
    "mt5_parity_run",
    "mt5_validation",
]
ApprovalSource = Literal["human", "policy_engine"]


class PublishManifest(BaseModel):
    candidate_id: str
    version: str
    published_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    manifest_path: Path
    snapshot_dir: Path
    artifacts: list[str]
    publication_type: Literal["research_archive"] = "research_archive"
    deployment_ready: bool = False
    notes: list[str] = Field(default_factory=list)


class ApprovalRecord(BaseModel):
    candidate_id: str
    stage: ApprovalStage
    decision: str
    approver: str
    rationale: str
    source: ApprovalSource = "human"
    evidence_paths: dict[str, str] = Field(default_factory=dict)
    policy_snapshot_hash: str | None = None
    evidence_fingerprint: str | None = None
    approval_idempotency_key: str | None = None
    evaluation_revision: int = 1
    attestation: dict[str, bool] = Field(default_factory=dict)
    recorded_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
