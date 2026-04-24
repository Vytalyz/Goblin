"""Generate a Stage 1 strategy specification scaffold for a new candidate.

This is the **S1 (Strategy Design)** entry point of the Goblin Strategy
Development Loop. It produces three governed artifacts in one transaction:

1. ``reports/AF-CAND-NNNN/strategy_spec.json`` — minimal but complete
   numeric spec (instrument, session window, entry/exit rules, SL/TP,
   holding bars, allowed hours, volatility floor, spread ceiling).
2. ``Goblin/reports/strategy_rationale_cards/AF-CAND-NNNN.json`` — the
   five-field rationale card mandated by
   ``Goblin/contracts/strategy-rationale-card.md``.
3. ``Goblin/decisions/strategy_decisions.jsonl`` — appends a
   ``DEC-STRAT-AF-CAND-NNNN-S1-PASS`` entry that the validator
   (``tools/verify_strategy_decisions_schema.py``) accepts.

Governance constraints enforced here:

- The chosen ``--family`` must be in the slot's ``allowed_families`` list
  (per ``config/portfolio_policy.toml``).
- For ``slot_b`` (blank-slate research), the scaffolder refuses to copy
  numeric thresholds from any prior candidate: the user must supply
  ``--stop-loss-pips``, ``--take-profit-pips``, ``--holding-bars``, and
  ``--signal-threshold`` explicitly. This implements the
  ``strategy_inheritance == "none_from_prior_candidates"`` rule from
  ``AGENTS.md``.
- The hypothesis (rationale ``why_edge_should_exist``) must be at least
  30 characters so the resulting decision-log entry passes the schema's
  ``MIN_RATIONALE_CHARS`` check.

Usage::

    python tools/generate_strategy_spec.py \\
        --slot slot_b \\
        --family europe_open_impulse_retest_research \\
        --hypothesis "EUR/USD shows mean-reverting behavior after >20pip moves in the EU open." \\
        --stop-loss-pips 8 --take-profit-pips 24 \\
        --holding-bars 120 --signal-threshold 2.0 \\
        --what-invalidates "Trend regime overrides mean-reversion at session open." \\
        --hostile-regimes "trend_high_vol,news_event" \\
        --execution-assumptions "M1 fills, OANDA spread, no slippage adjustment" \\
        --non-deployable-when "Spread > 2.0 pips or news within 15 minutes."
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO_POLICY = REPO_ROOT / "config" / "portfolio_policy.toml"
DECISIONS_LOG = REPO_ROOT / "Goblin" / "decisions" / "strategy_decisions.jsonl"
RATIONALE_CARD_DIR = REPO_ROOT / "Goblin" / "reports" / "strategy_rationale_cards"
REPORTS_DIR = REPO_ROOT / "reports"

MIN_HYPOTHESIS_CHARS = 30
DEFAULT_INSTRUMENT = "EUR_USD"
DEFAULT_ALLOWED_HOURS_UTC = [8, 9, 10, 11, 12, 13]
DEFAULT_MIN_VOLATILITY_20 = 0.00010
DEFAULT_MAX_SPREAD_PIPS = 2.0


class StrategyScaffoldError(RuntimeError):
    """Raised when the scaffolder cannot produce governed artifacts."""


def _load_slot(slot_id: str) -> dict[str, Any]:
    if not PORTFOLIO_POLICY.exists():
        raise StrategyScaffoldError(f"portfolio policy not found: {PORTFOLIO_POLICY}")
    with PORTFOLIO_POLICY.open("rb") as fh:
        data = tomllib.load(fh)
    slots = data.get("portfolio", {}).get("slots", [])
    for slot in slots:
        if slot.get("slot_id") == slot_id:
            return slot
    raise StrategyScaffoldError(
        f"slot_id '{slot_id}' not found in {PORTFOLIO_POLICY.relative_to(REPO_ROOT)} "
        f"(available: {[s.get('slot_id') for s in slots]})"
    )


def _next_candidate_id(reports_dir: Path) -> str:
    """Allocate the next AF-CAND-NNNN by scanning ``reports_dir``.

    A standalone implementation (does not depend on
    ``agentic_forex.utils.ids.next_candidate_id``) so the scaffolder can
    run without the Python package being importable in unusual
    environments. Behaviour matches: take max existing 4-digit suffix
    under ``reports/AF-CAND-NNNN/`` and return ``+1`` zero-padded.
    """

    reports_dir.mkdir(parents=True, exist_ok=True)
    highest = 0
    for path in reports_dir.iterdir():
        if not path.is_dir():
            continue
        name = path.name
        if not name.startswith("AF-CAND-"):
            continue
        suffix = name[len("AF-CAND-") :]
        if len(suffix) == 4 and suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"AF-CAND-{highest + 1:04d}"


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_strategy_spec(
    *,
    candidate_id: str,
    family: str,
    instrument: str,
    allowed_hours_utc: list[int],
    hypothesis: str,
    stop_loss_pips: float,
    take_profit_pips: float,
    holding_bars: int,
    signal_threshold: float,
    min_volatility_20: float,
    max_spread_pips: float,
    slot_id: str,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "family": family,
        "slot_id": slot_id,
        "variant_name": "base",
        "instrument": instrument,
        "execution_granularity": "M1",
        "session_policy": {
            "name": "candidate_defined_intraday",
            "allowed_hours_utc": allowed_hours_utc,
        },
        "entry_logic": [
            f"Enter on signal threshold >= {signal_threshold}.",
            f"Hypothesis: {hypothesis}",
        ],
        "exit_logic": [
            f"Fixed stop {stop_loss_pips} pips.",
            f"Take profit {take_profit_pips} pips.",
            f"Time exit after {holding_bars} bars.",
        ],
        "risk_policy": {
            "stop_loss_pips": float(stop_loss_pips),
            "take_profit_pips": float(take_profit_pips),
            "max_open_positions": 1,
        },
        "filters": [
            {"name": "min_volatility_20", "rule": str(min_volatility_20)},
            {"name": "max_spread_pips", "rule": str(max_spread_pips)},
        ],
        "holding_bars": int(holding_bars),
        "signal_threshold": float(signal_threshold),
        "stop_loss_pips": float(stop_loss_pips),
        "take_profit_pips": float(take_profit_pips),
        "stage": "S1",
        "created_at": _utc_now_iso(),
        "source_hypothesis": hypothesis,
    }


def build_rationale_card(
    *,
    candidate_id: str,
    hypothesis: str,
    what_invalidates: str,
    hostile_regimes: list[str],
    execution_assumptions: str,
    non_deployable_when: str,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "created_at": _utc_now_iso(),
        "why_edge_should_exist": hypothesis,
        "what_invalidates_the_edge": what_invalidates,
        "regimes_that_should_hurt_it": hostile_regimes,
        "execution_assumptions_it_depends_on": execution_assumptions,
        "what_makes_it_non_deployable": non_deployable_when,
    }


def build_s1_decision_entry(
    *,
    candidate_id: str,
    slot_id: str,
    hypothesis: str,
    spec_path: Path,
    rationale_path: Path,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    root = repo_root if repo_root is not None else REPO_ROOT

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(root)).replace("\\", "/")
        except ValueError:
            return str(p).replace("\\", "/")

    rationale = f"S1 scaffold complete for {candidate_id}. Hypothesis: {hypothesis}"
    return {
        "decision_id": f"DEC-STRAT-{candidate_id}-S1-PASS",
        "candidate_id": candidate_id,
        "slot_id": slot_id,
        "stage": "S1",
        "outcome": "pass",
        "decided_by": "runner",
        "decided_at": _utc_now_iso(),
        "rationale": rationale,
        "gate_results": {
            "hypothesis_minimum_length": {
                "value": len(hypothesis),
                "threshold": MIN_HYPOTHESIS_CHARS,
                "passed": len(hypothesis) >= MIN_HYPOTHESIS_CHARS,
            },
            "rationale_card_present": {
                "value": 1,
                "threshold": 1,
                "passed": rationale_path.exists(),
            },
            "strategy_spec_present": {
                "value": 1,
                "threshold": 1,
                "passed": spec_path.exists(),
            },
        },
        "evidence_uris": [_rel(spec_path), _rel(rationale_path)],
        "next_action": "S2: run rule-only backtest via tools/run_strategy_s2_eval.py",
    }


def scaffold(
    *,
    slot_id: str,
    family: str,
    hypothesis: str,
    stop_loss_pips: float,
    take_profit_pips: float,
    holding_bars: int,
    signal_threshold: float,
    what_invalidates: str,
    hostile_regimes: list[str],
    execution_assumptions: str,
    non_deployable_when: str,
    instrument: str = DEFAULT_INSTRUMENT,
    allowed_hours_utc: list[int] | None = None,
    min_volatility_20: float = DEFAULT_MIN_VOLATILITY_20,
    max_spread_pips: float = DEFAULT_MAX_SPREAD_PIPS,
    repo_root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run the S1 scaffold transaction.

    Returns a result dict with the allocated ``candidate_id`` and the
    paths of the three artifacts (or planned paths if ``dry_run``).
    """

    root = repo_root if repo_root is not None else REPO_ROOT
    reports_dir = root / "reports"
    rationale_dir = root / "Goblin" / "reports" / "strategy_rationale_cards"
    decisions_log = root / "Goblin" / "decisions" / "strategy_decisions.jsonl"

    if len(hypothesis.strip()) < MIN_HYPOTHESIS_CHARS:
        raise StrategyScaffoldError(
            f"--hypothesis must be at least {MIN_HYPOTHESIS_CHARS} characters (got {len(hypothesis.strip())})"
        )

    # Slot validation lives off the canonical PORTFOLIO_POLICY constant so
    # tests can monkeypatch it; resolve via module-level lookup.
    slot = _load_slot(slot_id)
    allowed_families = slot.get("allowed_families", [])
    if family not in allowed_families:
        raise StrategyScaffoldError(f"family '{family}' is not in allowed_families for {slot_id}: {allowed_families}")

    candidate_id = _next_candidate_id(reports_dir)
    candidate_dir = reports_dir / candidate_id
    spec_path = candidate_dir / "strategy_spec.json"
    rationale_path = rationale_dir / f"{candidate_id}.json"

    spec = build_strategy_spec(
        candidate_id=candidate_id,
        family=family,
        instrument=instrument,
        allowed_hours_utc=allowed_hours_utc or list(DEFAULT_ALLOWED_HOURS_UTC),
        hypothesis=hypothesis.strip(),
        stop_loss_pips=stop_loss_pips,
        take_profit_pips=take_profit_pips,
        holding_bars=holding_bars,
        signal_threshold=signal_threshold,
        min_volatility_20=min_volatility_20,
        max_spread_pips=max_spread_pips,
        slot_id=slot_id,
    )
    card = build_rationale_card(
        candidate_id=candidate_id,
        hypothesis=hypothesis.strip(),
        what_invalidates=what_invalidates,
        hostile_regimes=hostile_regimes,
        execution_assumptions=execution_assumptions,
        non_deployable_when=non_deployable_when,
    )

    result: dict[str, Any] = {
        "candidate_id": candidate_id,
        "slot_id": slot_id,
        "family": family,
        "spec_path": str(spec_path),
        "rationale_card_path": str(rationale_path),
        "decisions_log_path": str(decisions_log),
        "dry_run": dry_run,
    }

    if dry_run:
        result["spec_preview"] = spec
        result["rationale_card_preview"] = card
        return result

    candidate_dir.mkdir(parents=True, exist_ok=True)
    rationale_dir.mkdir(parents=True, exist_ok=True)
    decisions_log.parent.mkdir(parents=True, exist_ok=True)

    spec_path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    rationale_path.write_text(json.dumps(card, indent=2) + "\n", encoding="utf-8")

    # Build the decision entry AFTER the artifacts exist so the
    # ``*_present`` gate values reflect reality.
    entry = build_s1_decision_entry(
        candidate_id=candidate_id,
        slot_id=slot_id,
        hypothesis=hypothesis.strip(),
        spec_path=spec_path,
        rationale_path=rationale_path,
        repo_root=root,
    )
    with decisions_log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")

    result["decision_entry"] = entry
    return result


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scaffold a Stage 1 strategy spec for a new Goblin candidate.",
    )
    parser.add_argument("--slot", required=True, choices=["slot_a", "slot_b"])
    parser.add_argument("--family", required=True)
    parser.add_argument("--hypothesis", required=True)
    parser.add_argument("--stop-loss-pips", type=float, required=True)
    parser.add_argument("--take-profit-pips", type=float, required=True)
    parser.add_argument("--holding-bars", type=int, required=True)
    parser.add_argument("--signal-threshold", type=float, required=True)
    parser.add_argument("--what-invalidates", required=True)
    parser.add_argument(
        "--hostile-regimes",
        required=True,
        help="Comma-separated list of regimes expected to hurt this strategy.",
    )
    parser.add_argument("--execution-assumptions", required=True)
    parser.add_argument("--non-deployable-when", required=True)
    parser.add_argument("--instrument", default=DEFAULT_INSTRUMENT)
    parser.add_argument(
        "--allowed-hours-utc",
        default=",".join(str(h) for h in DEFAULT_ALLOWED_HOURS_UTC),
        help="Comma-separated UTC hours (0-23). Default: 8,9,10,11,12,13.",
    )
    parser.add_argument("--min-volatility-20", type=float, default=DEFAULT_MIN_VOLATILITY_20)
    parser.add_argument("--max-spread-pips", type=float, default=DEFAULT_MAX_SPREAD_PIPS)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", help="Emit result as JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    hostile_regimes = [r.strip() for r in args.hostile_regimes.split(",") if r.strip()]
    allowed_hours = [int(h.strip()) for h in args.allowed_hours_utc.split(",") if h.strip()]

    try:
        result = scaffold(
            slot_id=args.slot,
            family=args.family,
            hypothesis=args.hypothesis,
            stop_loss_pips=args.stop_loss_pips,
            take_profit_pips=args.take_profit_pips,
            holding_bars=args.holding_bars,
            signal_threshold=args.signal_threshold,
            what_invalidates=args.what_invalidates,
            hostile_regimes=hostile_regimes,
            execution_assumptions=args.execution_assumptions,
            non_deployable_when=args.non_deployable_when,
            instrument=args.instrument,
            allowed_hours_utc=allowed_hours,
            min_volatility_20=args.min_volatility_20,
            max_spread_pips=args.max_spread_pips,
            dry_run=args.dry_run,
        )
    except StrategyScaffoldError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        prefix = "[dry-run] " if args.dry_run else ""
        print(
            f"{prefix}Allocated candidate: {result['candidate_id']} (slot={result['slot_id']}, family={result['family']})"
        )
        print(f"  spec:           {result['spec_path']}")
        print(f"  rationale card: {result['rationale_card_path']}")
        if not args.dry_run:
            print(f"  decision log:   {result['decisions_log_path']}")
            print(f"  decision_id:    {result['decision_entry']['decision_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
