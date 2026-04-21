"""Strategy decisions log schema validator.

Validates ``Goblin/decisions/strategy_decisions.jsonl`` is an append-only
JSON-Lines file in which every entry conforms to the schema documented at
``Goblin/decisions/STRATEGY_DECISIONS_SCHEMA.md``.

Returns exit code 0 on success, non-zero on the first malformed entry.

Usage:
    python tools/verify_strategy_decisions_schema.py [--path PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = REPO_ROOT / "Goblin" / "decisions" / "strategy_decisions.jsonl"

REQUIRED_TOP_LEVEL: tuple[str, ...] = (
    "decision_id",
    "candidate_id",
    "stage",
    "outcome",
    "decided_by",
    "decided_at",
    "rationale",
    "gate_results",
    "evidence_uris",
    "next_action",
)

VALID_STAGES: frozenset[str] = frozenset(
    {"S1", "S2", "S3", "S4", "S5", "S6", "S7", "RETIREMENT"}
)

VALID_OUTCOMES: frozenset[str] = frozenset(
    {"pass", "fail", "pending", "retired", "promoted"}
)

VALID_DECIDED_BY: frozenset[str] = frozenset({"owner", "runner"})

DECISION_ID_RE = re.compile(
    r"^DEC-STRAT-AF-CAND-[A-Z0-9-]+-(?:S[1-7]|RETIREMENT)-[A-Z]+(?:-\d+)?$"
)
CANDIDATE_ID_RE = re.compile(r"^AF-CAND-[A-Z0-9-]+$")
ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")

MIN_RATIONALE_CHARS = 30


class StrategyDecisionLogError(ValueError):
    """Raised when an entry in the strategy decisions log is malformed."""


def _check_entry(idx: int, entry: dict, *, seen_ids: set[str]) -> None:
    for key in REQUIRED_TOP_LEVEL:
        if key not in entry:
            raise StrategyDecisionLogError(
                f"entry {idx}: missing required field '{key}'"
            )

    decision_id = entry["decision_id"]
    if not isinstance(decision_id, str) or not DECISION_ID_RE.match(decision_id):
        raise StrategyDecisionLogError(
            f"entry {idx}: decision_id '{decision_id}' does not match required format"
        )
    if decision_id in seen_ids:
        raise StrategyDecisionLogError(
            f"entry {idx}: duplicate decision_id '{decision_id}'"
        )
    seen_ids.add(decision_id)

    candidate_id = entry["candidate_id"]
    if not isinstance(candidate_id, str) or not CANDIDATE_ID_RE.match(candidate_id):
        raise StrategyDecisionLogError(
            f"entry {idx}: candidate_id '{candidate_id}' does not match AF-CAND-* format"
        )

    stage = entry["stage"]
    if stage not in VALID_STAGES:
        raise StrategyDecisionLogError(
            f"entry {idx}: stage '{stage}' not in {sorted(VALID_STAGES)}"
        )

    outcome = entry["outcome"]
    if outcome not in VALID_OUTCOMES:
        raise StrategyDecisionLogError(
            f"entry {idx}: outcome '{outcome}' not in {sorted(VALID_OUTCOMES)}"
        )

    decided_by = entry["decided_by"]
    if decided_by not in VALID_DECIDED_BY:
        raise StrategyDecisionLogError(
            f"entry {idx}: decided_by '{decided_by}' not in {sorted(VALID_DECIDED_BY)}"
        )

    decided_at = entry["decided_at"]
    if not isinstance(decided_at, str) or not ISO_UTC_RE.match(decided_at):
        raise StrategyDecisionLogError(
            f"entry {idx}: decided_at '{decided_at}' is not ISO-8601 UTC (must end with Z)"
        )

    rationale = entry["rationale"]
    if not isinstance(rationale, str) or len(rationale.strip()) < MIN_RATIONALE_CHARS:
        raise StrategyDecisionLogError(
            f"entry {idx}: rationale must be a string of at least "
            f"{MIN_RATIONALE_CHARS} non-whitespace characters"
        )

    gate_results = entry["gate_results"]
    if not isinstance(gate_results, dict):
        raise StrategyDecisionLogError(
            f"entry {idx}: gate_results must be an object"
        )
    for gate_name, gate in gate_results.items():
        if not isinstance(gate, dict):
            raise StrategyDecisionLogError(
                f"entry {idx}: gate_results['{gate_name}'] must be an object"
            )
        for required_gate_key in ("value", "threshold", "passed"):
            if required_gate_key not in gate:
                raise StrategyDecisionLogError(
                    f"entry {idx}: gate_results['{gate_name}'] missing '{required_gate_key}'"
                )
        if not isinstance(gate["passed"], bool):
            raise StrategyDecisionLogError(
                f"entry {idx}: gate_results['{gate_name}'].passed must be a boolean"
            )

    evidence_uris = entry["evidence_uris"]
    if not isinstance(evidence_uris, list) or not all(
        isinstance(u, str) for u in evidence_uris
    ):
        raise StrategyDecisionLogError(
            f"entry {idx}: evidence_uris must be a list of strings"
        )

    next_action = entry["next_action"]
    if not isinstance(next_action, str) or not next_action.strip():
        raise StrategyDecisionLogError(
            f"entry {idx}: next_action must be a non-empty string"
        )


def validate_lines(lines: Iterable[str]) -> int:
    count = 0
    seen_ids: set[str] = set()
    for idx, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StrategyDecisionLogError(
                f"entry {idx}: invalid JSON ({exc})"
            ) from exc
        _check_entry(idx, entry, seen_ids=seen_ids)
        count += 1
    return count


def validate_file(path: Path) -> int:
    if not path.exists():
        raise StrategyDecisionLogError(f"strategy decisions log not found: {path}")
    with path.open(encoding="utf-8") as fh:
        return validate_lines(fh)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_LOG)
    args = parser.parse_args(argv)
    try:
        n = validate_file(args.path)
    except StrategyDecisionLogError as exc:
        print(f"[verify_strategy_decisions_schema] FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"[verify_strategy_decisions_schema] OK: {n} entries validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
