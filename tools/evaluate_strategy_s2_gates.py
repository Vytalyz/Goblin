"""Evaluate the 12 Stage 2 (rule-only backtest) gates against existing artifacts.

This is the **decision layer** of S2 in the Goblin Strategy Development Loop.
It does NOT run a backtest. It reads already-produced artifacts:

- ``reports/AF-CAND-NNNN/backtest_summary.json`` (from
  ``agentic_forex.backtesting.engine.run_backtest``)
- ``reports/AF-CAND-NNNN/robustness_report.json`` (from
  ``agentic_forex.evals.robustness.build_robustness_report``)
- Optional cost-sensitivity sweep JSON: ``{"plus_1pip_pf": <float>, ...}``
- Optional stress override JSON (defaults to using
  ``backtest_summary``'s embedded stress, if present)

— and applies all 12 S2 gates from the strategy plan, then appends a
``DEC-STRAT-AF-CAND-NNNN-S2-PASS|FAIL`` entry to
``Goblin/decisions/strategy_decisions.jsonl``.

Thresholds come from ``config/eval_gates.toml [validation]`` so this
evaluator stays in lockstep with the rest of the kernel.

Gates evaluated (in order):

1.  ``oos_profit_factor`` ≥ ``out_of_sample_profit_factor_floor`` (1.05)
2.  ``oos_expectancy`` > ``expectancy_floor`` (0.0)
3.  ``oos_trade_count`` ≥ ``minimum_test_trade_count`` (100)
4.  ``walk_forward_pf_per_window`` ≥ ``walk_forward_profit_factor_floor`` (0.90)
5.  ``walk_forward_trades_per_window`` ≥ ``walk_forward_min_trades_per_window`` (10)
6.  ``drawdown_degradation_pct`` ≤ ``max_relative_drawdown_degradation_pct`` (15.0)
7.  ``stress_profit_factor`` ≥ ``stress_profit_factor_floor`` (1.0)
8.  ``regime_non_negativity`` — PF ≥ 1.0 in EVERY regime bucket
9.  ``cost_persistence_at_1pip`` — PF stays ≥ 1.0 at +1.0 pip cost shock
10. ``pbo`` ≤ ``pbo_threshold`` (0.35)
11. ``white_reality_check_p_value`` ≤ ``white_reality_check_pvalue_threshold`` (0.10)
12. ``deflated_sharpe_ratio`` ≥ ``deflated_sharpe_floor`` (0.0)

Gates 8/9/11/PBO can be marked ``available=False`` (e.g. fewer than 2
family candidates → CSCV/PBO unavailable). When ``available=False`` the
gate is recorded as ``passed=False`` with a clear reason, but the
``--allow-provisional`` flag downgrades it to ``passed=True`` with a
``provisional`` annotation. This matches the existing robustness suite's
``robustness_provisional`` mode.
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
EVAL_GATES_TOML = REPO_ROOT / "config" / "eval_gates.toml"
DECISIONS_LOG = REPO_ROOT / "Goblin" / "decisions" / "strategy_decisions.jsonl"

# Gate name keys (kept stable; downstream tooling may filter on these).
GATE_OOS_PF = "oos_profit_factor"
GATE_OOS_EXPECTANCY = "oos_expectancy"
GATE_OOS_TRADE_COUNT = "oos_trade_count"
GATE_WF_PF = "walk_forward_pf_per_window"
GATE_WF_TRADES = "walk_forward_trades_per_window"
GATE_DD_DEGRADATION = "drawdown_degradation_pct"
GATE_STRESS_PF = "stress_profit_factor"
GATE_REGIME_NON_NEG = "regime_non_negativity"
GATE_COST_PERSISTENCE = "cost_persistence_at_1pip"
GATE_PBO = "pbo"
GATE_WHITES_P = "white_reality_check_p_value"
GATE_DSR = "deflated_sharpe_ratio"

ALL_GATES = (
    GATE_OOS_PF,
    GATE_OOS_EXPECTANCY,
    GATE_OOS_TRADE_COUNT,
    GATE_WF_PF,
    GATE_WF_TRADES,
    GATE_DD_DEGRADATION,
    GATE_STRESS_PF,
    GATE_REGIME_NON_NEG,
    GATE_COST_PERSISTENCE,
    GATE_PBO,
    GATE_WHITES_P,
    GATE_DSR,
)


class S2GateEvaluationError(RuntimeError):
    """Raised when inputs are missing required fields."""


# ---------------------------------------------------------------------------
# Threshold loading
# ---------------------------------------------------------------------------


def load_thresholds(eval_gates_path: Path | None = None) -> dict[str, float]:
    """Load the [validation] block from eval_gates.toml.

    Returns a dict with the exact keys the engine uses; missing keys fall
    back to the documented defaults so the evaluator never crashes on a
    partial config (which would defeat its purpose as a deterministic
    decision layer).
    """

    path = eval_gates_path if eval_gates_path is not None else EVAL_GATES_TOML
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    v = data.get("validation", {})
    return {
        "out_of_sample_profit_factor_floor": float(v.get("out_of_sample_profit_factor_floor", 1.05)),
        "expectancy_floor": float(v.get("expectancy_floor", 0.0)),
        "minimum_test_trade_count": int(v.get("minimum_test_trade_count", 100)),
        "walk_forward_profit_factor_floor": float(v.get("walk_forward_profit_factor_floor", 0.90)),
        "walk_forward_min_trades_per_window": int(v.get("walk_forward_min_trades_per_window", 10)),
        "max_relative_drawdown_degradation_pct": float(v.get("max_relative_drawdown_degradation_pct", 15.0)),
        "stress_profit_factor_floor": float(v.get("stress_profit_factor_floor", 1.0)),
        "pbo_threshold": float(v.get("pbo_threshold", 0.35)),
        "white_reality_check_pvalue_threshold": float(v.get("white_reality_check_pvalue_threshold", 0.10)),
        "deflated_sharpe_floor": float(v.get("deflated_sharpe_floor", 0.0)),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise S2GateEvaluationError(f"required artifact not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _gate(
    name: str,
    *,
    value: Any,
    threshold: Any,
    passed: bool,
    notes: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {"value": value, "threshold": threshold, "passed": bool(passed)}
    if notes is not None:
        entry["notes"] = notes
    return entry


# ---------------------------------------------------------------------------
# Per-gate evaluators (pure functions over input dicts)
# ---------------------------------------------------------------------------


def evaluate_walk_forward(
    walk_forward_summary: list[dict[str, Any]],
    *,
    pf_floor: float,
    min_trades: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Returns (pf_gate, trades_gate)."""
    if not walk_forward_summary:
        return (
            _gate(
                GATE_WF_PF,
                value=None,
                threshold=pf_floor,
                passed=False,
                notes="no walk_forward windows recorded",
            ),
            _gate(
                GATE_WF_TRADES,
                value=None,
                threshold=min_trades,
                passed=False,
                notes="no walk_forward windows recorded",
            ),
        )
    min_pf = min(float(w.get("profit_factor", 0.0)) for w in walk_forward_summary)
    min_window_trades = min(int(w.get("trade_count", 0)) for w in walk_forward_summary)
    return (
        _gate(GATE_WF_PF, value=min_pf, threshold=pf_floor, passed=min_pf >= pf_floor),
        _gate(
            GATE_WF_TRADES,
            value=min_window_trades,
            threshold=min_trades,
            passed=min_window_trades >= min_trades,
        ),
    )


def evaluate_drawdown_degradation(
    *,
    in_sample_dd_pct: float | None,
    overall_dd_pct: float | None,
    threshold_pct: float,
) -> dict[str, Any]:
    """How much worse is overall DD vs in-sample DD, as a pct of in-sample.

    Degradation = (overall - in_sample) / in_sample * 100. If in-sample is
    zero or both are missing, the gate is marked unavailable (passed=False
    with a note) so the caller can decide whether to allow provisional.
    """
    if in_sample_dd_pct is None or overall_dd_pct is None:
        return _gate(
            GATE_DD_DEGRADATION,
            value=None,
            threshold=threshold_pct,
            passed=False,
            notes="in-sample or overall drawdown missing from backtest summary",
        )
    if in_sample_dd_pct <= 0:
        # No in-sample DD to degrade from — treat overall DD vs threshold directly.
        return _gate(
            GATE_DD_DEGRADATION,
            value=float(overall_dd_pct),
            threshold=threshold_pct,
            passed=overall_dd_pct <= threshold_pct,
            notes="in-sample drawdown was 0; gate evaluated against absolute overall DD",
        )
    degradation = (float(overall_dd_pct) - float(in_sample_dd_pct)) / float(in_sample_dd_pct) * 100.0
    return _gate(
        GATE_DD_DEGRADATION,
        value=round(degradation, 4),
        threshold=threshold_pct,
        passed=degradation <= threshold_pct,
    )


def evaluate_regime_non_negativity(
    regime_breakdown: dict[str, Any] | list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Every regime bucket must have PF >= 1.0 (non-negative edge)."""
    if not regime_breakdown:
        return _gate(
            GATE_REGIME_NON_NEG,
            value=None,
            threshold=1.0,
            passed=False,
            notes="regime_breakdown missing or empty",
        )
    # The engine emits regime_breakdown either as {regime: {...}} or as a list.
    if isinstance(regime_breakdown, dict):
        items = list(regime_breakdown.items())
    else:
        items = [(r.get("regime", f"r{i}"), r) for i, r in enumerate(regime_breakdown)]

    failing: list[str] = []
    pf_by_regime: dict[str, float] = {}
    for regime_name, payload in items:
        if not isinstance(payload, dict):
            failing.append(f"{regime_name}=non-dict")
            continue
        pf = float(payload.get("profit_factor", 0.0))
        pf_by_regime[regime_name] = pf
        if pf < 1.0:
            failing.append(f"{regime_name}={pf:.3f}")
    return _gate(
        GATE_REGIME_NON_NEG,
        value=pf_by_regime,
        threshold=1.0,
        passed=len(failing) == 0,
        notes=("regimes below floor: " + ", ".join(failing)) if failing else None,
    )


def evaluate_cost_persistence(
    cost_sweep: dict[str, Any] | None,
    *,
    pf_floor: float = 1.0,
) -> dict[str, Any]:
    """PF must remain >= pf_floor at +1.0 pip cost shock."""
    if not cost_sweep:
        return _gate(
            GATE_COST_PERSISTENCE,
            value=None,
            threshold=pf_floor,
            passed=False,
            notes="cost-sensitivity sweep not provided (run a +1pip backtest and pass --cost-sweep)",
        )
    plus_1pip = cost_sweep.get("plus_1pip_pf")
    if plus_1pip is None:
        return _gate(
            GATE_COST_PERSISTENCE,
            value=None,
            threshold=pf_floor,
            passed=False,
            notes="cost-sweep missing plus_1pip_pf key",
        )
    plus_1pip = float(plus_1pip)
    return _gate(
        GATE_COST_PERSISTENCE,
        value=plus_1pip,
        threshold=pf_floor,
        passed=plus_1pip >= pf_floor,
    )


def evaluate_robustness_gates(
    robustness: dict[str, Any],
    thresholds: dict[str, float],
    *,
    allow_provisional: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Returns (pbo_gate, whites_gate, dsr_gate)."""

    pbo_available = bool(robustness.get("cscv_pbo_available", False))
    pbo_value = robustness.get("pbo")
    pbo_threshold = thresholds["pbo_threshold"]
    if pbo_available and pbo_value is not None:
        pbo_gate = _gate(
            GATE_PBO,
            value=float(pbo_value),
            threshold=pbo_threshold,
            passed=float(pbo_value) <= pbo_threshold,
        )
    else:
        pbo_gate = _gate(
            GATE_PBO,
            value=pbo_value,
            threshold=pbo_threshold,
            passed=allow_provisional,
            notes="PBO unavailable (insufficient family candidates); provisional"
            if allow_provisional
            else "PBO unavailable (insufficient family candidates)",
        )

    wrc_available = bool(robustness.get("white_reality_check_available", False))
    wrc_p = robustness.get("white_reality_check_p_value")
    wrc_threshold = thresholds["white_reality_check_pvalue_threshold"]
    if wrc_available and wrc_p is not None:
        whites_gate = _gate(
            GATE_WHITES_P,
            value=float(wrc_p),
            threshold=wrc_threshold,
            passed=float(wrc_p) <= wrc_threshold,
        )
    else:
        whites_gate = _gate(
            GATE_WHITES_P,
            value=wrc_p,
            threshold=wrc_threshold,
            passed=allow_provisional,
            notes="White's RC unavailable (insufficient family candidates); provisional"
            if allow_provisional
            else "White's RC unavailable (insufficient family candidates)",
        )

    dsr = robustness.get("deflated_sharpe_ratio")
    dsr_floor = thresholds["deflated_sharpe_floor"]
    if dsr is None:
        dsr_gate = _gate(
            GATE_DSR,
            value=None,
            threshold=dsr_floor,
            passed=False,
            notes="DSR missing from robustness report",
        )
    else:
        dsr_gate = _gate(
            GATE_DSR,
            value=float(dsr),
            threshold=dsr_floor,
            passed=float(dsr) >= dsr_floor,
        )
    return pbo_gate, whites_gate, dsr_gate


# ---------------------------------------------------------------------------
# Top-level evaluation
# ---------------------------------------------------------------------------


def evaluate_s2(
    *,
    candidate_id: str,
    slot_id: str | None,
    backtest_summary: dict[str, Any],
    robustness_report: dict[str, Any],
    cost_sweep: dict[str, Any] | None = None,
    stress_override: dict[str, Any] | None = None,
    thresholds: dict[str, float] | None = None,
    allow_provisional: bool = False,
    decided_by: str = "runner",
    repo_root: Path | None = None,
    spec_path: Path | None = None,
) -> dict[str, Any]:
    """Run all 12 S2 gates and return a decision-log entry (not yet appended).

    The returned dict matches the strategy_decisions.jsonl schema and is
    accepted by tools/verify_strategy_decisions_schema.py.
    """

    th = thresholds if thresholds is not None else load_thresholds()
    root = repo_root if repo_root is not None else REPO_ROOT

    # --- Gates 1-3: OOS basics ---
    oos_pf = float(backtest_summary.get("out_of_sample_profit_factor", 0.0))
    expectancy = float(backtest_summary.get("expectancy_pips", 0.0))
    trade_count = int(backtest_summary.get("trade_count", 0))

    g1 = _gate(
        GATE_OOS_PF,
        value=oos_pf,
        threshold=th["out_of_sample_profit_factor_floor"],
        passed=oos_pf >= th["out_of_sample_profit_factor_floor"],
    )
    g2 = _gate(
        GATE_OOS_EXPECTANCY,
        value=expectancy,
        threshold=th["expectancy_floor"],
        passed=expectancy > th["expectancy_floor"],
    )
    g3 = _gate(
        GATE_OOS_TRADE_COUNT,
        value=trade_count,
        threshold=th["minimum_test_trade_count"],
        passed=trade_count >= th["minimum_test_trade_count"],
    )

    # --- Gates 4-5: Walk-forward stability ---
    g4, g5 = evaluate_walk_forward(
        backtest_summary.get("walk_forward_summary", []),
        pf_floor=th["walk_forward_profit_factor_floor"],
        min_trades=th["walk_forward_min_trades_per_window"],
    )

    # --- Gate 6: drawdown degradation ---
    in_sample_dd = backtest_summary.get("in_sample_drawdown_pct")
    overall_dd = backtest_summary.get("max_drawdown_pct")
    g6 = evaluate_drawdown_degradation(
        in_sample_dd_pct=in_sample_dd,
        overall_dd_pct=overall_dd,
        threshold_pct=th["max_relative_drawdown_degradation_pct"],
    )

    # --- Gate 7: stress PF ---
    if stress_override is not None:
        stress_pf = float(stress_override.get("profit_factor", 0.0))
    else:
        stress_pf = float(backtest_summary.get("stress_profit_factor", 0.0))
    g7 = _gate(
        GATE_STRESS_PF,
        value=stress_pf,
        threshold=th["stress_profit_factor_floor"],
        passed=stress_pf >= th["stress_profit_factor_floor"],
    )

    # --- Gate 8: regime non-negativity ---
    g8 = evaluate_regime_non_negativity(backtest_summary.get("regime_breakdown"))

    # --- Gate 9: cost persistence ---
    g9 = evaluate_cost_persistence(cost_sweep)

    # --- Gates 10-12: robustness ---
    g10, g11, g12 = evaluate_robustness_gates(robustness_report, th, allow_provisional=allow_provisional)

    gate_results: dict[str, dict[str, Any]] = {
        GATE_OOS_PF: g1,
        GATE_OOS_EXPECTANCY: g2,
        GATE_OOS_TRADE_COUNT: g3,
        GATE_WF_PF: g4,
        GATE_WF_TRADES: g5,
        GATE_DD_DEGRADATION: g6,
        GATE_STRESS_PF: g7,
        GATE_REGIME_NON_NEG: g8,
        GATE_COST_PERSISTENCE: g9,
        GATE_PBO: g10,
        GATE_WHITES_P: g11,
        GATE_DSR: g12,
    }

    failing = [name for name, g in gate_results.items() if not g["passed"]]
    outcome = "pass" if not failing else "fail"
    decision_suffix = "PASS" if outcome == "pass" else "FAIL"
    rationale = (
        f"S2 gate evaluation for {candidate_id}: {len(gate_results) - len(failing)}/{len(gate_results)} gates passed."
    )
    if failing:
        rationale += f" Failing gates: {', '.join(failing)}."
    if allow_provisional:
        rationale += " (allow_provisional=True applied to robustness gates without family universe)."

    def _rel(p: Path | None) -> str | None:
        if p is None:
            return None
        try:
            return str(p.relative_to(root)).replace("\\", "/")
        except ValueError:
            return str(p).replace("\\", "/")

    evidence_uris: list[str] = []
    if spec_path is not None:
        rel = _rel(spec_path)
        if rel:
            evidence_uris.append(rel)
    evidence_uris.append(f"reports/{candidate_id}/backtest_summary.json")
    evidence_uris.append(f"reports/{candidate_id}/robustness_report.json")

    entry: dict[str, Any] = {
        "decision_id": f"DEC-STRAT-{candidate_id}-S2-{decision_suffix}",
        "candidate_id": candidate_id,
        "stage": "S2",
        "outcome": outcome,
        "decided_by": decided_by,
        "decided_at": _utc_now_iso(),
        "rationale": rationale,
        "gate_results": gate_results,
        "evidence_uris": evidence_uris,
        "next_action": (
            "S3: per-candidate ML evaluation (run tools/run_strategy_s3_eval.py)"
            if outcome == "pass"
            else "RETIRE: write post-mortem and return to S1 with a fresh hypothesis"
        ),
    }
    if slot_id is not None:
        entry["slot_id"] = slot_id
    if failing:
        entry["failure_mode"] = ", ".join(failing)
    return entry


def append_decision(entry: dict[str, Any], decisions_log: Path | None = None) -> Path:
    log = decisions_log if decisions_log is not None else DECISIONS_LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return log


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the 12 S2 gates against existing backtest + robustness artifacts.",
    )
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--slot-id", default=None)
    parser.add_argument(
        "--backtest-summary",
        type=Path,
        help="Path to backtest_summary.json. Defaults to reports/<candidate_id>/backtest_summary.json.",
    )
    parser.add_argument(
        "--robustness-report",
        type=Path,
        help="Path to robustness_report.json. Defaults to reports/<candidate_id>/robustness_report.json.",
    )
    parser.add_argument(
        "--cost-sweep",
        type=Path,
        default=None,
        help='Optional path to a cost-sweep JSON like {"plus_1pip_pf": 1.07}.',
    )
    parser.add_argument(
        "--allow-provisional",
        action="store_true",
        help="Mark PBO/White's gates as passed when the family universe is too small.",
    )
    parser.add_argument(
        "--decided-by",
        default="runner",
        choices=["owner", "runner"],
    )
    parser.add_argument("--no-append", action="store_true", help="Print entry only; do not append.")
    parser.add_argument("--json", action="store_true", help="Emit entry as JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    candidate_dir = REPO_ROOT / "reports" / args.candidate_id
    backtest_path = args.backtest_summary or (candidate_dir / "backtest_summary.json")
    robustness_path = args.robustness_report or (candidate_dir / "robustness_report.json")

    try:
        backtest = _load_json(backtest_path)
        robustness = _load_json(robustness_path)
        cost_sweep = _load_json(args.cost_sweep) if args.cost_sweep else None
        entry = evaluate_s2(
            candidate_id=args.candidate_id,
            slot_id=args.slot_id,
            backtest_summary=backtest,
            robustness_report=robustness,
            cost_sweep=cost_sweep,
            allow_provisional=args.allow_provisional,
            decided_by=args.decided_by,
            spec_path=candidate_dir / "strategy_spec.json",
        )
    except S2GateEvaluationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if not args.no_append:
        append_decision(entry)

    if args.json:
        print(json.dumps(entry, indent=2))
    else:
        outcome_marker = "PASS" if entry["outcome"] == "pass" else "FAIL"
        print(f"S2 evaluation for {args.candidate_id}: {outcome_marker}")
        print(f"  decision_id: {entry['decision_id']}")
        print(f"  {entry['rationale']}")
        for gate_name, gate in entry["gate_results"].items():
            mark = "[PASS]" if gate["passed"] else "[FAIL]"
            note = f"  ({gate['notes']})" if gate.get("notes") else ""
            print(f"  {mark} {gate_name}: value={gate['value']} threshold={gate['threshold']}{note}")
    return 0 if entry["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
