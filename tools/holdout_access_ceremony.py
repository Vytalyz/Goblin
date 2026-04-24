"""
EX-4 — Sealed holdout decryption ceremony (R4 §C5, L3, G3/G7/G8/G9/G12).

Hard caps and invariants:
  - Maximum 2 successful decryption events for the entire P2 program
    (counted from prior DEC-ML-HOLDOUT-ACCESS-N-COMPLETED entries in
    Goblin/decisions/ml_decisions.jsonl).
  - Decryption requires a key path OUTSIDE the repo (refused if path
    resolves anywhere under REPO_ROOT).
  - Plaintext is written to a tmpfile (caller's tempdir) and shredded in
    a finally-block regardless of whether the eval succeeds.
  - Three decision-log entries bracket every ceremony:
      INITIATED -> COMPLETED (success path)
      INITIATED -> ABORTED   (any exception path)
  - On crash, ABORTED still counts toward the cap (G7: aborts are visible).
  - Ceremony refuses to start if a prior INITIATED entry has no matching
    COMPLETED or ABORTED entry (idempotency guard against partial runs).

Inputs:
  --key-path  : absolute path to Fernet key file (must be outside repo)
  --eval-cmd  : command to invoke the eval pipeline; receives the plaintext
                parquet path as its single positional argument
  --note      : human-readable rationale (>=50 chars), written to log entries

This module is unit-testable: count_completed_accesses,
ml_decisions_log_path, append_decision, ceremony_should_refuse, and
shred_plaintext are all isolated functions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ML_DECISIONS_LOG = REPO_ROOT / "Goblin" / "decisions" / "ml_decisions.jsonl"
SEALED_HOLDOUT_PATH = REPO_ROOT / "Goblin" / "holdout" / "ml_p2_holdout.parquet.enc"
HARD_CAP = 2
ACCESS_ID_PATTERN = re.compile(r"^DEC-ML-HOLDOUT-ACCESS-(\d+)-(INITIATED|COMPLETED|ABORTED)$")


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        out.append(json.loads(s))
    return out


def count_completed_accesses(entries: list[dict]) -> int:
    """Count DEC-ML-HOLDOUT-ACCESS-N-COMPLETED entries (each = 1 used decryption)."""
    return sum(
        1
        for e in entries
        if isinstance(e.get("decision_id"), str)
        and e["decision_id"].endswith("-COMPLETED")
        and ACCESS_ID_PATTERN.match(e["decision_id"])
    )


def count_aborted_accesses(entries: list[dict]) -> int:
    return sum(
        1
        for e in entries
        if isinstance(e.get("decision_id"), str)
        and e["decision_id"].endswith("-ABORTED")
        and ACCESS_ID_PATTERN.match(e["decision_id"])
    )


def has_dangling_initiated(entries: list[dict]) -> str | None:
    """Return the dangling INITIATED decision_id (no matching terminal), or None."""
    initiated_ns: dict[int, str] = {}
    terminal_ns: set[int] = set()
    for e in entries:
        did = e.get("decision_id")
        if not isinstance(did, str):
            continue
        m = ACCESS_ID_PATTERN.match(did)
        if not m:
            continue
        n = int(m.group(1))
        kind = m.group(2)
        if kind == "INITIATED":
            initiated_ns[n] = did
        else:
            terminal_ns.add(n)
    for n, did in initiated_ns.items():
        if n not in terminal_ns:
            return did
    return None


def next_access_n(entries: list[dict]) -> int:
    used = set()
    for e in entries:
        did = e.get("decision_id")
        if isinstance(did, str):
            m = ACCESS_ID_PATTERN.match(did)
            if m:
                used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return n


def ceremony_should_refuse(entries: list[dict]) -> str | None:
    """Return refusal reason string, or None if ceremony may proceed."""
    completed = count_completed_accesses(entries)
    aborted = count_aborted_accesses(entries)
    used = completed + aborted
    if used >= HARD_CAP:
        return (
            f"REFUSED: {used} prior holdout-access events "
            f"(completed={completed}, aborted={aborted}) >= hard cap {HARD_CAP}"
        )
    dangling = has_dangling_initiated(entries)
    if dangling is not None:
        return f"REFUSED: dangling INITIATED entry without terminal: {dangling}. Resolve manually before re-running."
    return None


def append_decision(path: Path, entry: dict) -> None:
    """Append a JSON object as one line to the decision log (atomic open-append)."""
    line = json.dumps(entry, separators=(",", ":"), sort_keys=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def shred_plaintext(path: Path, *, passes: int = 3) -> None:
    """Best-effort shred: overwrite file with random bytes N times then unlink.

    NOTE: On modern filesystems with copy-on-write, journaling, or SSD wear
    levelling, overwriting cannot guarantee physical erasure. The primary
    safeguard is that the plaintext is only written to the OS tempdir and
    that this function runs in a finally-block. Defense-in-depth only.
    """
    if not path.exists():
        return
    size = path.stat().st_size
    try:
        with path.open("r+b") as f:
            for _ in range(max(1, passes)):
                f.seek(0)
                f.write(secrets.token_bytes(size))
                f.flush()
                os.fsync(f.fileno())
    except OSError:
        pass
    try:
        path.unlink()
    except OSError:
        pass


def _validate_key_outside_repo(key_path: Path) -> None:
    resolved = key_path.resolve()
    try:
        resolved.relative_to(REPO_ROOT)
    except ValueError:
        return  # OK: not under REPO_ROOT
    raise RuntimeError(
        f"FATAL: key path {resolved} is inside the repository tree. Holdout keys must live outside the repo."
    )


def _decrypt(key_bytes: bytes, ciphertext: bytes) -> bytes:
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        raise RuntimeError("cryptography package required for decryption: pip install cryptography") from e
    return Fernet(key_bytes).decrypt(ciphertext)


def run_ceremony(
    *,
    key_path: Path,
    eval_cmd: list[str],
    note: str,
    decisions_log: Path = ML_DECISIONS_LOG,
    sealed_path: Path = SEALED_HOLDOUT_PATH,
    actor: str = "owner",
) -> int:
    """Run the full ceremony. Returns exit code (0 = success)."""
    if len(note) < 50:
        print("FAIL: --note must be >= 50 chars (audit-trail requirement)", file=sys.stderr)
        return 2
    _validate_key_outside_repo(key_path)
    if not key_path.exists():
        print(f"FAIL: key not found at {key_path}", file=sys.stderr)
        return 3
    if not sealed_path.exists():
        print(f"FAIL: sealed holdout not found at {sealed_path}", file=sys.stderr)
        return 4

    entries = _read_log(decisions_log)
    refusal = ceremony_should_refuse(entries)
    if refusal:
        print(refusal, file=sys.stderr)
        return 5

    n = next_access_n(entries)
    initiated_id = f"DEC-ML-HOLDOUT-ACCESS-{n}-INITIATED"
    completed_id = f"DEC-ML-HOLDOUT-ACCESS-{n}-COMPLETED"
    aborted_id = f"DEC-ML-HOLDOUT-ACCESS-{n}-ABORTED"
    ciphertext_sha = hashlib.sha256(sealed_path.read_bytes()).hexdigest()

    append_decision(
        decisions_log,
        {
            "decision_id": initiated_id,
            "phase": "ML-2.0",
            "decision_type": "holdout_access_initiated",
            "verdict": "in_progress",
            "decided_by": actor,
            "decided_at": _utc_now_iso(),
            "rationale": note,
            "evidence_uris": [
                f"Goblin/holdout/{sealed_path.name}",
                ".github/workflows/holdout-ceremony.yml",
            ],
            "sealed_holdout_sha256": ciphertext_sha,
            "access_index": n,
            "hard_cap": HARD_CAP,
        },
    )

    plaintext_path: Path | None = None
    try:
        key_bytes = key_path.read_bytes().strip()
        plaintext = _decrypt(key_bytes, sealed_path.read_bytes())

        tmpdir = Path(tempfile.mkdtemp(prefix="holdout_ceremony_"))
        plaintext_path = tmpdir / "ml_p2_holdout.parquet"
        plaintext_path.write_bytes(plaintext)
        plaintext_sha = hashlib.sha256(plaintext).hexdigest()

        cmd = list(eval_cmd) + [str(plaintext_path)]
        print(f"Invoking eval: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        eval_exit = result.returncode
        print("--- eval stdout ---")
        print(result.stdout)
        print("--- eval stderr ---")
        print(result.stderr)
        if eval_exit != 0:
            raise RuntimeError(f"eval pipeline exited {eval_exit}")

        append_decision(
            decisions_log,
            {
                "decision_id": completed_id,
                "phase": "ML-2.0",
                "decision_type": "holdout_access_completed",
                "verdict": "completed",
                "decided_by": actor,
                "decided_at": _utc_now_iso(),
                "rationale": f"Holdout access #{n} completed successfully. Eval exit=0.",
                "evidence_uris": [f"Goblin/holdout/{sealed_path.name}"],
                "sealed_holdout_sha256": ciphertext_sha,
                "plaintext_sha256_at_decryption": plaintext_sha,
                "access_index": n,
                "linked_initiated_decision_id": initiated_id,
            },
        )
        print(f"OK: holdout access #{n} completed.")
        return 0
    except Exception as exc:  # noqa: BLE001
        append_decision(
            decisions_log,
            {
                "decision_id": aborted_id,
                "phase": "ML-2.0",
                "decision_type": "holdout_access_aborted",
                "verdict": "aborted",
                "decided_by": actor,
                "decided_at": _utc_now_iso(),
                "rationale": f"Holdout access #{n} aborted: {type(exc).__name__}: {exc}",
                "evidence_uris": [f"Goblin/holdout/{sealed_path.name}"],
                "sealed_holdout_sha256": ciphertext_sha,
                "access_index": n,
                "linked_initiated_decision_id": initiated_id,
                "abort_reason": str(exc),
            },
        )
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 6
    finally:
        if plaintext_path is not None:
            shred_plaintext(plaintext_path)
            try:
                plaintext_path.parent.rmdir()
            except OSError:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EX-4 sealed holdout ceremony")
    parser.add_argument("--key-path", type=Path, required=True)
    parser.add_argument("--note", type=str, required=True)
    parser.add_argument("--actor", type=str, default="owner")
    parser.add_argument(
        "--eval-cmd",
        nargs=argparse.REMAINDER,
        required=True,
        help="Eval command; receives plaintext-parquet path as last argument.",
    )
    args = parser.parse_args(argv)
    return run_ceremony(
        key_path=args.key_path,
        eval_cmd=args.eval_cmd,
        note=args.note,
        actor=args.actor,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
