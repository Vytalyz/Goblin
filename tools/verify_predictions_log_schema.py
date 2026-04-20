"""
EX-3 — Schema validator for Goblin/decisions/predictions.jsonl (R4-11 + L2).

Enforces the schema documented in Goblin/decisions/PREDICTIONS_SCHEMA.md.

Exits 0 if all entries valid, 1 otherwise. Used by CI job
`predictions-log-schema-check`.

Empty file is valid (initial state before any prediction is logged).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = REPO_ROOT / "Goblin" / "decisions" / "predictions.jsonl"

REQUIRED_TOP_LEVEL = (
    "prediction_id",
    "phase",
    "predicted_verdict",
    "predicted_point_estimate_pf",
    "predicted_ci_low",
    "predicted_ci_high",
    "commit_sha_at_prediction",
    "wallclock_utc",
    "rationale_note",
    "predictor_attestation",
)
ALLOWED_PHASES = frozenset({"midpoint", "trigger"})
ALLOWED_VERDICTS = frozenset({"GO", "CONDITIONAL", "CONDITIONAL_RESTRICTED", "NO_GO"})
RATIONALE_MIN_CHARS = 50
ATTESTATION_MIN_CHARS = 30
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ISO8601_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def validate_entry(entry: dict, midpoint_shas: set[str]) -> list[str]:
    """Return a list of error messages for *entry*; empty list = valid."""
    errors: list[str] = []
    for field in REQUIRED_TOP_LEVEL:
        if field not in entry:
            errors.append(f"missing required field: {field}")
    if errors:
        return errors

    if entry["phase"] not in ALLOWED_PHASES:
        errors.append(f"phase must be one of {sorted(ALLOWED_PHASES)}")
    if entry["predicted_verdict"] not in ALLOWED_VERDICTS:
        errors.append(f"predicted_verdict must be one of {sorted(ALLOWED_VERDICTS)}")

    for f in ("predicted_point_estimate_pf", "predicted_ci_low", "predicted_ci_high"):
        if not isinstance(entry[f], (int, float)) or isinstance(entry[f], bool):
            errors.append(f"{f} must be a number")

    if not errors:
        lo = entry["predicted_ci_low"]
        pt = entry["predicted_point_estimate_pf"]
        hi = entry["predicted_ci_high"]
        if not (lo <= pt <= hi):
            errors.append(
                f"predicted_ci_low ({lo}) <= point_estimate ({pt}) "
                f"<= predicted_ci_high ({hi}) violated"
            )

    sha = entry["commit_sha_at_prediction"]
    if not isinstance(sha, str) or not SHA_PATTERN.match(sha):
        errors.append("commit_sha_at_prediction must be a 40-char lowercase hex string")

    ts = entry["wallclock_utc"]
    if not isinstance(ts, str) or not ISO8601_PATTERN.match(ts):
        errors.append("wallclock_utc must match YYYY-MM-DDTHH:MM:SSZ")

    note = entry["rationale_note"]
    if not isinstance(note, str) or len(note) < RATIONALE_MIN_CHARS:
        errors.append(f"rationale_note must be a string >= {RATIONALE_MIN_CHARS} chars")

    att = entry["predictor_attestation"]
    if not isinstance(att, str) or len(att) < ATTESTATION_MIN_CHARS:
        errors.append(
            f"predictor_attestation must be a string >= {ATTESTATION_MIN_CHARS} chars"
        )

    if entry.get("phase") == "trigger":
        ref = entry.get("commit_sha_of_midpoint_prediction")
        if not isinstance(ref, str) or not SHA_PATTERN.match(ref):
            errors.append(
                "trigger entry requires commit_sha_of_midpoint_prediction "
                "(40-char hex)"
            )
        elif ref not in midpoint_shas:
            errors.append(
                f"trigger references midpoint SHA {ref} that does not appear in any "
                "prior phase=midpoint entry"
            )

    return errors


def validate_file(path: Path) -> tuple[bool, list[str]]:
    """Validate every line in *path*. Returns (is_valid, error_messages)."""
    if not path.exists():
        return False, [f"file not found: {path}"]

    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return True, []  # empty log is valid

    errors: list[str] = []
    seen_ids: set[str] = set()
    midpoint_shas: set[str] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"line {lineno}: invalid JSON: {e}")
            continue

        line_errors = validate_entry(entry, midpoint_shas)
        for e in line_errors:
            errors.append(f"line {lineno} ({entry.get('prediction_id', '?')}): {e}")

        pid = entry.get("prediction_id")
        if pid in seen_ids:
            errors.append(f"line {lineno}: duplicate prediction_id: {pid}")
        elif pid:
            seen_ids.add(pid)

        if entry.get("phase") == "midpoint":
            sha = entry.get("commit_sha_at_prediction")
            if isinstance(sha, str) and SHA_PATTERN.match(sha):
                midpoint_shas.add(sha)

    return (len(errors) == 0), errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EX-3 predictions log validator")
    parser.add_argument(
        "log_path",
        nargs="?",
        type=Path,
        default=DEFAULT_LOG,
        help="Path to predictions.jsonl (default: Goblin/decisions/predictions.jsonl)",
    )
    args = parser.parse_args(argv)

    valid, errors = validate_file(args.log_path)
    if valid:
        print(f"OK: {args.log_path} valid (entries checked).")
        return 0
    print(f"FAIL: {args.log_path} has {len(errors)} error(s):")
    for e in errors:
        print(f"  - {e}")
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
