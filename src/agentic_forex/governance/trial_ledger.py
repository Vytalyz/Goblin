from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agentic_forex.config import Settings
from agentic_forex.governance.models import FailureCode, FailureRecord, TrialLedgerEntry

_JSONL_LOCK_RETRY_SECONDS = 0.01
_JSONL_LOCK_TIMEOUT_SECONDS = 5.0


def append_trial_entry(
    settings: Settings,
    *,
    candidate_id: str,
    family: str,
    stage: str,
    artifact_paths: dict[str, str] | None = None,
    gate_outcomes: dict[str, Any] | None = None,
    parent_candidate_ids: list[str] | None = None,
    mutation_policy: str | None = None,
    campaign_id: str | None = None,
    provenance_id: str | None = None,
    environment_snapshot_id: str | None = None,
    failure_code: FailureCode | None = None,
) -> TrialLedgerEntry:
    entry = TrialLedgerEntry(
        trial_id=f"trial-{uuid.uuid4().hex[:12]}",
        candidate_id=candidate_id,
        family=family,
        stage=stage,
        parent_candidate_ids=parent_candidate_ids or [],
        mutation_policy=mutation_policy,
        campaign_id=campaign_id,
        provenance_id=provenance_id,
        environment_snapshot_id=environment_snapshot_id,
        artifact_paths=artifact_paths or {},
        gate_outcomes=gate_outcomes or {},
        failure_code=failure_code,
    )
    _append_jsonl(settings.paths().experiments_dir / "trial_ledger.jsonl", entry.model_dump(mode="json"))
    return entry


def append_failure_record(
    settings: Settings,
    *,
    candidate_id: str,
    stage: str,
    failure_code: FailureCode,
    details: dict[str, Any] | None = None,
    artifact_paths: dict[str, str] | None = None,
    campaign_id: str | None = None,
) -> FailureRecord:
    record = FailureRecord(
        failure_id=f"failure-{uuid.uuid4().hex[:12]}",
        candidate_id=candidate_id,
        stage=stage,
        failure_code=failure_code,
        campaign_id=campaign_id,
        details=details or {},
        artifact_paths=artifact_paths or {},
    )
    _append_jsonl(
        settings.paths().observational_knowledge_dir / "failure_records.jsonl", record.model_dump(mode="json")
    )
    return record


def count_trials(settings: Settings, *, family: str | None = None, candidate_id: str | None = None) -> int:
    path = settings.paths().experiments_dir / "trial_ledger.jsonl"
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                # Interrupted parallel writes should not break downstream robustness accounting.
                continue
            if family and payload.get("family") != family:
                continue
            if candidate_id and payload.get("candidate_id") != candidate_id:
                continue
            count += 1
    return count


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, default=str) + "\n"
    with _jsonl_append_lock(path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(serialized)


@contextmanager
def _jsonl_append_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    deadline = time.monotonic() + _JSONL_LOCK_TIMEOUT_SECONDS
    lock_fd: int | None = None
    while True:
        try:
            lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out acquiring JSONL append lock: {lock_path}") from None
            time.sleep(_JSONL_LOCK_RETRY_SECONDS)
    try:
        if lock_fd is not None:
            os.write(lock_fd, str(os.getpid()).encode("utf-8"))
        yield
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
