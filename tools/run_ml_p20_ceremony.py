"""ML-P2.0 ceremony wrapper.

Validates that BOTH a midpoint AND a trigger prediction exist in
Goblin/decisions/predictions.jsonl BEFORE invoking the holdout
decryption ceremony.  This prevents burning a HARD_CAP decryption
event when the owner forgot to file required predictions.

Usage:
    python tools/run_ml_p20_ceremony.py --key-path <path_outside_repo> [--note <note>]

Pre-conditions (checked before ceremony INITIATED is logged):
  1. Goblin/decisions/predictions.jsonl has >= 1 phase=midpoint entry
  2. Goblin/decisions/predictions.jsonl has >= 1 phase=trigger  entry

The ceremony invokes:
    python tools/run_ml_p20_holdout_eval.py <plaintext_parquet_path>
and shreds the plaintext after the eval script exits.

Owner workflow:
  1. python tools/run_ml_p20_insample.py          # generates midpoint evidence
  2. Edit Goblin/decisions/predictions.jsonl      # file MIDPOINT prediction
  3. git commit + push
  4. Edit Goblin/decisions/predictions.jsonl      # file TRIGGER prediction
  5. git commit + push
  6. python tools/run_ml_p20_ceremony.py --key-path ~/.goblin/holdout_keys/HOLDOUT-ML-P2-20260420.key
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import holdout_access_ceremony as _cer  # noqa: E402

PREDICTIONS_LOG = REPO_ROOT / "Goblin" / "decisions" / "predictions.jsonl"
EVAL_SCRIPT = REPO_ROOT / "tools" / "run_ml_p20_holdout_eval.py"

DEFAULT_NOTE = (
    "ML-P2.0 holdout access: evaluating XGB-on-survivors primary endpoint "
    "against sealed holdout HOLDOUT-ML-P2-20260420 (DEC-ML-2.0-TARGET). "
    "MIDPOINT and TRIGGER predictions confirmed present."
)


def _load_predictions() -> list[dict]:
    if not PREDICTIONS_LOG.exists():
        return []
    out: list[dict] = []
    for line in PREDICTIONS_LOG.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s:
            out.append(json.loads(s))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ML-P2.0 sealed holdout ceremony wrapper.")
    ap.add_argument(
        "--key-path",
        type=Path,
        required=True,
        help="Path to Fernet key file (must be outside the repo).",
    )
    ap.add_argument("--note", type=str, default=DEFAULT_NOTE)
    ap.add_argument("--actor", type=str, default="owner")
    args = ap.parse_args(argv)

    # ------------------------------------------------------------------
    # Pre-condition: both predictions must be filed
    # ------------------------------------------------------------------
    preds = _load_predictions()
    midpoint_entries = [e for e in preds if e.get("phase") == "midpoint"]
    trigger_entries = [e for e in preds if e.get("phase") == "trigger"]

    if not midpoint_entries:
        print(
            "[p20-ceremony] ABORTED: no midpoint prediction found in predictions.jsonl.\n"
            "  Run tools/run_ml_p20_insample.py, then file the MIDPOINT prediction.",
            file=sys.stderr,
        )
        return 1

    if not trigger_entries:
        print(
            "[p20-ceremony] ABORTED: no trigger prediction found in predictions.jsonl.\n"
            "  File the TRIGGER prediction immediately before running this script.",
            file=sys.stderr,
        )
        return 1

    mid_id = midpoint_entries[-1].get("prediction_id", "?")
    trig_id = trigger_entries[-1].get("prediction_id", "?")
    print(f"[p20-ceremony] midpoint prediction : {mid_id}")
    print(f"[p20-ceremony] trigger  prediction : {trig_id}")
    print("[p20-ceremony] pre-conditions satisfied -- invoking holdout ceremony ...")

    python = sys.executable
    eval_cmd = [python, str(EVAL_SCRIPT)]

    return _cer.run_ceremony(
        key_path=args.key_path,
        eval_cmd=eval_cmd,
        note=args.note,
        actor=args.actor,
    )


if __name__ == "__main__":
    sys.exit(main())
