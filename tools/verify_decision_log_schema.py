"""Decision log schema validator (ML-1.7).

Validates ``Goblin/decisions/ml_decisions.jsonl`` is a JSON-Lines file in which
every entry includes the required governance fields and a complete 8-field bias
self-audit.

Used by the ``decision-log-schema-check`` CI job. Returns exit code 0 on
success, non-zero on the first malformed entry.

Usage:
    python tools/verify_decision_log_schema.py [--path PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = REPO_ROOT / "Goblin" / "decisions" / "ml_decisions.jsonl"

REQUIRED_TOP_LEVEL: tuple[str, ...] = (
    "decision_id",
    "phase",
    "decision_type",
    "verdict",
    "decided_by",
    "decided_at",
    "rationale",
    "bias_self_audit",
)

BIAS_KEYS: tuple[str, ...] = (
    "confirmation_bias",
    "cherry_picking",
    "anchoring",
    "complexity_creep",
    "sunk_cost",
    "recency",
    "narrative",
    "survivorship",
)


class DecisionLogSchemaError(ValueError):
    """Raised when an entry in the ML decision log is malformed."""


# Explicit grandfather set: entries written BEFORE the 8-field bias self-audit
# format was standardized in DEC-ML-1.6.0-COMPLETE. The append-only invariant
# forbids mutating these in place; they are accepted on the historical record
# but no new entry may rely on this exemption.
#
# EX-7: hardened from `len(...) == 1` to identity comparison so silent
# additions to the set surface in code review. Modifications require
# CODEOWNERS review on tools/verify_decision_log_schema.py per
# .github/CODEOWNERS, plus a new EX-7.x decision log entry.
GRANDFATHERED_NO_BIAS_AUDIT: frozenset[str] = frozenset(
    {
        "DEC-ML-1.6.0-CANDIDATES",
    }
)
# Hard assertion: the grandfather set must be exactly this value.
# If a maintainer adds an entry, this assertion forces them to update
# both the literal AND this guard in the SAME commit (visibility).
assert GRANDFATHERED_NO_BIAS_AUDIT == frozenset({"DEC-ML-1.6.0-CANDIDATES"}), (
    "GRANDFATHERED_NO_BIAS_AUDIT mutated without updating the EX-7 guard. "
    "See docs and CODEOWNERS before changing."
)

# Operational ceremony decision_types are auto-generated bracketing events
# (e.g. holdout-access INITIATED/ABORTED/COMPLETED). They record an
# operational fact, not an analytical choice, so a bias self-audit is not
# meaningful. The originating analytical decision (the prediction file or
# evaluation entry) carries the bias self-audit instead.
OPERATIONAL_CEREMONY_DECISION_TYPES: frozenset[str] = frozenset(
    {
        "holdout_access_initiated",
        "holdout_access_completed",
        "holdout_access_aborted",
    }
)


def _check_entry(idx: int, entry: dict) -> None:
    decision_id = entry.get("decision_id", "")
    decision_type = entry.get("decision_type", "")
    is_grandfathered = (
        decision_id in GRANDFATHERED_NO_BIAS_AUDIT
        or decision_type in OPERATIONAL_CEREMONY_DECISION_TYPES
    )
    required = (
        REQUIRED_TOP_LEVEL if not is_grandfathered else tuple(f for f in REQUIRED_TOP_LEVEL if f != "bias_self_audit")
    )
    for key in required:
        if key not in entry:
            raise DecisionLogSchemaError(f"entry {idx}: missing required field '{key}'")
        value = entry[key]
        if value is None or (isinstance(value, str) and not value.strip()):
            raise DecisionLogSchemaError(f"entry {idx}: field '{key}' is empty")
    if is_grandfathered:
        return
    audit = entry["bias_self_audit"]
    if not isinstance(audit, dict):
        raise DecisionLogSchemaError(f"entry {idx}: bias_self_audit must be an object")
    for bias in BIAS_KEYS:
        considered = f"{bias}_considered"
        note = f"{bias}_note"
        if considered not in audit:
            raise DecisionLogSchemaError(f"entry {idx}: bias_self_audit missing '{considered}'")
        if audit[considered] is not True:
            raise DecisionLogSchemaError(f"entry {idx}: bias_self_audit '{considered}' must be true")
        if note not in audit or not isinstance(audit[note], str) or not audit[note].strip():
            raise DecisionLogSchemaError(f"entry {idx}: bias_self_audit '{note}' must be a non-empty string")


def validate_lines(lines: Iterable[str]) -> int:
    count = 0
    for idx, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DecisionLogSchemaError(f"entry {idx}: invalid JSON ({exc})") from exc
        _check_entry(idx, entry)
        count += 1
    return count


def validate_file(path: Path) -> int:
    if not path.exists():
        raise DecisionLogSchemaError(f"decision log not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return validate_lines(fh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_LOG)
    args = parser.parse_args(argv)
    try:
        n = validate_file(args.path)
    except DecisionLogSchemaError as exc:
        print(f"[verify_decision_log_schema] FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"[verify_decision_log_schema] OK: {n} entries validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
