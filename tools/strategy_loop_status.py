"""Strategy loop status reader.

Renders the current state of the Goblin Strategy Development Loop:
  - Active candidate per portfolio slot (slot_a, slot_b)
  - Most recent decision per candidate from
    ``Goblin/decisions/strategy_decisions.jsonl``
  - Current stage and last gate outcome

Read-only. Never mutates any file. Emits human-readable text by default;
``--json`` switches to a machine-readable dump for tooling integration.

Usage:
    python tools/strategy_loop_status.py
    python tools/strategy_loop_status.py --json
    python tools/strategy_loop_status.py --candidate AF-CAND-0733
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections import OrderedDict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DECISIONS_LOG = REPO_ROOT / "Goblin" / "decisions" / "strategy_decisions.jsonl"
PORTFOLIO_POLICY = REPO_ROOT / "config" / "portfolio_policy.toml"


def _load_portfolio_slots() -> list[dict[str, Any]]:
    if not PORTFOLIO_POLICY.exists():
        return []
    with PORTFOLIO_POLICY.open("rb") as fh:
        data = tomllib.load(fh)
    return list(data.get("portfolio", {}).get("slots", []))


def _load_decisions() -> list[dict[str, Any]]:
    if not DECISIONS_LOG.exists():
        return []
    entries: list[dict[str, Any]] = []
    for raw in DECISIONS_LOG.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            entries.append(json.loads(raw))
        except json.JSONDecodeError:
            # The validator covers this; the status reader should not crash.
            continue
    return entries


def _latest_per_candidate(entries: list[dict[str, Any]]) -> "OrderedDict[str, dict[str, Any]]":
    """Return the latest decision per candidate, preserving insertion order."""
    latest: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for entry in entries:
        cid = entry.get("candidate_id")
        if not isinstance(cid, str):
            continue
        latest[cid] = entry  # last occurrence wins; order preserved by OrderedDict
    return latest


def build_status(
    *,
    candidate_filter: str | None = None,
) -> dict[str, Any]:
    slots = _load_portfolio_slots()
    decisions = _load_decisions()
    latest = _latest_per_candidate(decisions)

    def _slot_record(slot: dict[str, Any]) -> dict[str, Any]:
        cid = slot.get("active_candidate_id")
        last = latest.get(cid) if cid else None
        return {
            "slot_id": slot.get("slot_id"),
            "mode": slot.get("mode"),
            "purpose": slot.get("purpose"),
            "active_candidate_id": cid,
            "allowed_families": slot.get("allowed_families", []),
            "last_decision": last,
        }

    try:
        log_path_display = str(DECISIONS_LOG.relative_to(REPO_ROOT))
    except ValueError:
        log_path_display = str(DECISIONS_LOG)

    status: dict[str, Any] = {
        "decisions_log_path": log_path_display,
        "decisions_total": len(decisions),
        "candidates_tracked": len(latest),
        "slots": [_slot_record(s) for s in slots],
    }

    if candidate_filter:
        history = [e for e in decisions if e.get("candidate_id") == candidate_filter]
        status["candidate_filter"] = candidate_filter
        status["candidate_history"] = history
        status["candidate_history_count"] = len(history)

    return status


def _format_text(status: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append("Goblin Strategy Loop — Status")
    lines.append("=" * 72)
    lines.append(f"Decisions log: {status['decisions_log_path']}")
    lines.append(
        f"Total decisions: {status['decisions_total']}  |  "
        f"Candidates tracked: {status['candidates_tracked']}"
    )
    lines.append("")
    lines.append("Portfolio slots")
    lines.append("-" * 72)
    if not status["slots"]:
        lines.append("  (no slots loaded — check config/portfolio_policy.toml)")
    for slot in status["slots"]:
        lines.append(
            f"  [{slot['slot_id']}] mode={slot['mode']}  "
            f"active_candidate={slot['active_candidate_id'] or '(none)'}"
        )
        lines.append(f"      purpose: {slot['purpose']}")
        if slot["allowed_families"]:
            lines.append(
                f"      allowed_families: {', '.join(slot['allowed_families'])}"
            )
        last = slot["last_decision"]
        if last:
            lines.append(
                f"      last_decision: {last.get('decision_id')}  "
                f"stage={last.get('stage')}  outcome={last.get('outcome')}  "
                f"at={last.get('decided_at')}"
            )
            lines.append(f"      next_action: {last.get('next_action')}")
        else:
            lines.append("      last_decision: (none recorded)")
        lines.append("")

    if "candidate_filter" in status:
        lines.append(
            f"History for {status['candidate_filter']} "
            f"({status['candidate_history_count']} entries)"
        )
        lines.append("-" * 72)
        if not status["candidate_history"]:
            lines.append("  (no decisions recorded for this candidate)")
        for entry in status["candidate_history"]:
            lines.append(
                f"  {entry.get('decided_at')}  "
                f"{entry.get('stage')}  {entry.get('outcome')}  "
                f"-> {entry.get('next_action')}"
            )
            lines.append(f"      {entry.get('decision_id')}")
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of text.",
    )
    parser.add_argument(
        "--candidate",
        type=str,
        default=None,
        help="Show full decision history for a specific candidate id.",
    )
    args = parser.parse_args(argv)

    status = build_status(candidate_filter=args.candidate)

    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(_format_text(status))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
