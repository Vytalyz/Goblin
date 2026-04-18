from __future__ import annotations

import os
import re
import time
from contextlib import contextmanager
from datetime import UTC, datetime

from agentic_forex.config import Settings

_CANDIDATE_ID_PATTERN = re.compile(r"AF-CAND-(\d{4})$")
_COUNTER_LOCK_RETRY_SECONDS = 0.01
_COUNTER_LOCK_TIMEOUT_SECONDS = 5.0


def _highest_existing_candidate_sequence(settings: Settings) -> int:
    highest = 0
    for path in settings.paths().reports_dir.iterdir():
        if not path.is_dir():
            continue
        match = _CANDIDATE_ID_PATTERN.fullmatch(path.name)
        if match is None:
            continue
        highest = max(highest, int(match.group(1)))
    return highest


@contextmanager
def _candidate_counter_lock(settings: Settings):
    state_dir = settings.paths().state_dir
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "candidate_counter.lock"
    deadline = time.monotonic() + _COUNTER_LOCK_TIMEOUT_SECONDS
    lock_fd: int | None = None
    while True:
        try:
            lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out acquiring candidate counter lock: {lock_path}") from None
            time.sleep(_COUNTER_LOCK_RETRY_SECONDS)
        except PermissionError:
            # Windows can surface a transient PermissionError when another thread/process
            # wins the create race on the lock file. Treat it as a held lock instead of a
            # hard failure so concurrent candidate allocation stays deterministic.
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out acquiring candidate counter lock: {lock_path}") from None
            time.sleep(_COUNTER_LOCK_RETRY_SECONDS)
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


def next_candidate_id(settings: Settings) -> str:
    counter_path = settings.paths().state_dir / "candidate_counter.txt"
    with _candidate_counter_lock(settings):
        counter = 0
        if counter_path.exists():
            counter = int(counter_path.read_text(encoding="utf-8").strip() or "0")
        counter = max(counter, _highest_existing_candidate_sequence(settings))
        counter += 1
        counter_path.write_text(str(counter), encoding="utf-8")
        return f"AF-CAND-{counter:04d}"


def next_campaign_id(settings: Settings, *, suffix: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    base_identifier = f"campaign-{timestamp}"
    campaign_id = f"{base_identifier}{suffix}"
    counter = 0
    while (settings.paths().campaigns_dir / campaign_id).exists():
        counter += 1
        campaign_id = f"{base_identifier}-{counter:02d}{suffix}"
    return campaign_id
