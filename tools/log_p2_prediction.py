"""
ML-P2.0 — Prediction logger (R4-11 pre-commitment protocol).

Appends a midpoint or trigger prediction entry to
Goblin/decisions/predictions.jsonl, validates all required fields, and
enforces the trigger-phase cross-reference to a midpoint commit SHA.

Usage (midpoint — file before first non-error PF on non-holdout data):
  python tools/log_p2_prediction.py \\
      --phase midpoint \\
      --verdict CONDITIONAL \\
      --point-estimate 0.067 \\
      --ci-low 0.020 \\
      --ci-high 0.120 \\
      --rationale "XGB in-sample CV shows mean 0.067 PF lift across 6 survivors ..." \\
      --attestation "I have not viewed holdout data at the time of filing this prediction."

Usage (trigger — file immediately before ceremony):
  python tools/log_p2_prediction.py \\
      --phase trigger \\
      --verdict CONDITIONAL \\
      --point-estimate 0.072 \\
      --ci-low 0.025 \\
      --ci-high 0.125 \\
      --rationale "..." \\
      --attestation "..." \\
      --midpoint-sha <40-char-sha-from-midpoint-prediction-commit>

Exit codes:
  0 = prediction written
  1 = validation error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS_LOG = REPO_ROOT / "Goblin" / "decisions" / "predictions.jsonl"

VALID_VERDICTS = frozenset({"GO", "CONDITIONAL", "CONDITIONAL_RESTRICTED", "NO_GO"})
VALID_PHASES = frozenset({"midpoint", "trigger"})
RATIONALE_MIN_LEN = 50
ATTESTATION_MIN_LEN = 30
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s:
            entries.append(json.loads(s))
    return entries


def _next_prediction_id(entries: list[dict], phase: str) -> str:
    """Generate the next sequential prediction_id for this phase."""
    label = "MIDPOINT" if phase == "midpoint" else "TRIGGER"
    existing = [
        e.get("prediction_id", "")
        for e in entries
        if isinstance(e.get("prediction_id"), str)
        and f"PRED-ML-2.0-{label}-" in e["prediction_id"]
    ]
    n = len(existing) + 1
    return f"PRED-ML-2.0-{label}-{n}"


def validate_prediction_entry(entry: dict) -> list[str]:
    """Return list of validation error strings; empty = valid."""
    errors: list[str] = []

    phase = entry.get("phase")
    if phase not in VALID_PHASES:
        errors.append(f"phase must be one of {sorted(VALID_PHASES)}, got {phase!r}")

    verdict = entry.get("predicted_verdict")
    if verdict not in VALID_VERDICTS:
        errors.append(f"predicted_verdict must be one of {sorted(VALID_VERDICTS)}, got {verdict!r}")

    point = entry.get("predicted_point_estimate_pf")
    ci_low = entry.get("predicted_ci_low")
    ci_high = entry.get("predicted_ci_high")

    for name, val in [("predicted_point_estimate_pf", point), ("predicted_ci_low", ci_low), ("predicted_ci_high", ci_high)]:
        if not isinstance(val, (int, float)):
            errors.append(f"{name} must be a number, got {val!r}")

    if isinstance(ci_low, (int, float)) and isinstance(point, (int, float)) and isinstance(ci_high, (int, float)):
        if not (ci_low <= point <= ci_high):
            errors.append(
                f"ci_low <= point_estimate <= ci_high violated: "
                f"{ci_low} <= {point} <= {ci_high}"
            )

    sha = entry.get("commit_sha_at_prediction", "")
    if not COMMIT_SHA_RE.match(str(sha)):
        errors.append(f"commit_sha_at_prediction must be a 40-char hex SHA, got {sha!r}")

    rationale = entry.get("rationale_note", "")
    if len(str(rationale)) < RATIONALE_MIN_LEN:
        errors.append(
            f"rationale_note must be >= {RATIONALE_MIN_LEN} chars "
            f"(got {len(str(rationale))})"
        )

    attestation = entry.get("predictor_attestation", "")
    if len(str(attestation)) < ATTESTATION_MIN_LEN:
        errors.append(
            f"predictor_attestation must be >= {ATTESTATION_MIN_LEN} chars "
            f"(got {len(str(attestation))})"
        )

    if phase == "trigger":
        mp_sha = entry.get("commit_sha_of_midpoint_prediction", "")
        if not COMMIT_SHA_RE.match(str(mp_sha)):
            errors.append(
                "trigger phase requires commit_sha_of_midpoint_prediction "
                f"(40-char hex), got {mp_sha!r}"
            )

    return errors


def append_prediction(path: Path, entry: dict) -> None:
    """Append one JSON object as a single line (atomic open-append)."""
    line = json.dumps(entry, separators=(",", ":"), sort_keys=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _get_current_commit_sha() -> str:
    """Return the current HEAD SHA (40 chars), or 40 zeros on failure."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        sha = result.stdout.strip()
        if COMMIT_SHA_RE.match(sha):
            return sha
    except Exception:  # noqa: BLE001
        pass
    return "0" * 40


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ML-P2.0 prediction logger (R4-11)")
    ap.add_argument("--phase", required=True, choices=sorted(VALID_PHASES))
    ap.add_argument("--verdict", required=True, choices=sorted(VALID_VERDICTS))
    ap.add_argument("--point-estimate", type=float, required=True,
                    dest="point_estimate",
                    help="Predicted aggregate PF lift on 6 survivors")
    ap.add_argument("--ci-low", type=float, required=True, dest="ci_low")
    ap.add_argument("--ci-high", type=float, required=True, dest="ci_high")
    ap.add_argument("--rationale", type=str, required=True,
                    help=f">= {RATIONALE_MIN_LEN} characters")
    ap.add_argument("--attestation", type=str, required=True,
                    help=f">= {ATTESTATION_MIN_LEN} chars; non-peek attestation for solo owner")
    ap.add_argument("--midpoint-sha", type=str, default=None, dest="midpoint_sha",
                    help="Required for trigger phase: commit SHA of midpoint prediction")
    ap.add_argument("--commit-sha", type=str, default=None, dest="commit_sha",
                    help="Override HEAD commit SHA (default: auto-detect)")
    ap.add_argument("--log", type=Path, default=PREDICTIONS_LOG,
                    help="Predictions log path")
    ap.add_argument("--dry-run", action="store_true",
                    help="Validate and print the entry without writing")
    args = ap.parse_args(argv)

    commit_sha = args.commit_sha or _get_current_commit_sha()

    entries = _read_log(args.log)
    prediction_id = _next_prediction_id(entries, args.phase)

    entry: dict = {
        "prediction_id": prediction_id,
        "phase": args.phase,
        "predicted_verdict": args.verdict,
        "predicted_point_estimate_pf": args.point_estimate,
        "predicted_ci_low": args.ci_low,
        "predicted_ci_high": args.ci_high,
        "commit_sha_at_prediction": commit_sha,
        "wallclock_utc": _utc_iso(),
        "rationale_note": args.rationale,
        "predictor_attestation": args.attestation,
    }

    if args.phase == "trigger":
        if not args.midpoint_sha:
            print("ERROR: --midpoint-sha is required for trigger phase", file=sys.stderr)
            return 1
        entry["commit_sha_of_midpoint_prediction"] = args.midpoint_sha
        # Verify midpoint entry exists
        midpoint_entries = [
            e for e in entries
            if e.get("phase") == "midpoint"
            and e.get("commit_sha_at_prediction") == args.midpoint_sha
        ]
        if not midpoint_entries:
            print(
                f"WARNING: no midpoint prediction found with "
                f"commit_sha_at_prediction={args.midpoint_sha!r}. "
                "Double-check the SHA before proceeding.",
                file=sys.stderr,
            )

        # Compute delta from midpoint
        if midpoint_entries:
            mp_point = float(midpoint_entries[-1].get("predicted_point_estimate_pf", 0.0))
            entry["predicted_delta_from_midpoint_pf"] = round(
                args.point_estimate - mp_point, 6
            )

    errors = validate_prediction_entry(entry)
    if errors:
        print("VALIDATION ERRORS:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("[dry-run] Prediction entry (NOT written):")
        print(json.dumps(entry, indent=2))
        return 0

    append_prediction(args.log, entry)
    print(f"[log-prediction] Written: {entry['prediction_id']} -> {args.log}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
