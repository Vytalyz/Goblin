from __future__ import annotations

from agentic_forex.approval.service import latest_stage_decision
from agentic_forex.backtesting.models import BacktestArtifact, StressTestReport
from agentic_forex.config import Settings
from agentic_forex.governance.models import ForwardStageReport, ReadinessStatus, RobustnessReport


def resolve_readiness_status(
    *,
    candidate_id: str,
    spec_exists: bool,
    backtest: BacktestArtifact | None,
    stress: StressTestReport | None,
    robustness: RobustnessReport | None,
    parity_passed: bool,
    forward_report: ForwardStageReport | None,
    settings: Settings,
) -> ReadinessStatus:
    human_decision = latest_stage_decision(candidate_id, "human_review", settings)
    if human_decision == "reject":
        return "human_review_rejected"
    if human_decision == "approve":
        return "human_review_passed"
    if robustness and robustness.cscv_pbo_available and robustness.status == "robustness_passed":
        if parity_passed and forward_report and forward_report.passed:
            return "review_eligible"
        return "robustness_passed"
    if forward_report and forward_report.passed and parity_passed:
        return "review_eligible_provisional"
    if forward_report and forward_report.passed:
        return "forward_passed"
    if parity_passed:
        return "parity_passed"
    if robustness:
        return "robustness_provisional"
    if backtest:
        return "backtested"
    if spec_exists:
        return "ea_spec_complete"
    return "discovered"


def required_evidence(status: ReadinessStatus) -> list[str]:
    mapping: dict[ReadinessStatus, list[str]] = {
        "discovered": ["candidate draft", "corpus citations"],
        "rule_spec_complete": [
            "rule spec",
            "deterministic entry/exit contract",
            "risk envelope",
            "session/news filters",
        ],
        "ea_spec_complete": ["ea spec", "parameter schema", "order-construction contract", "state-machine behavior"],
        "ea_compiled": ["ea source", "compile report", "deterministic code-generation manifest"],
        "mt5_backtest_executed": ["mt5 smoke report", "tester config", "smoke artifacts"],
        "reviewable_candidate": ["rule spec", "ea spec", "compile report", "mt5 smoke report", "triage report"],
        "specified": ["strategy spec", "execution cost model", "risk envelope", "initial provenance skeleton"],
        "backtested": ["backtest summary", "trade ledger", "data provenance", "environment snapshot"],
        "robustness_provisional": ["DSR", "walk-forward summary", "stress report", "trial warnings"],
        "parity_passed": [
            "MT5 tester config",
            "compile request",
            "parsed parity report",
            "live-trading disabled proof",
        ],
        "forward_passed": ["OANDA shadow-forward report", "forward gate metrics", "no hard risk-envelope violations"],
        "review_eligible_provisional": [
            "backtest summary",
            "trade ledger",
            "data provenance",
            "environment snapshot",
            "DSR",
            "walk-forward summary",
            "stress report",
            "trial warnings",
            "MT5 config",
            "compile request",
            "parsed parity report",
            "live-trading disabled proof",
            "OANDA shadow-forward report",
        ],
        "robustness_passed": ["CSCV/PBO report", "White's Reality Check", "full robustness report"],
        "review_eligible": ["full robustness report", "MT5 parity report", "OANDA shadow-forward report"],
        "human_review_passed": ["human review approval record"],
        "human_review_rejected": ["human review rejection record"],
        "published_research_snapshot": ["publish manifest", "immutable artifact bundle"],
        "ea_test_ready": [
            "fresh MT5 approvals",
            "passed MT5 parity report",
            "passed forward-stage report",
            "operator safety envelope",
            "reproducibility manifest",
        ],
    }
    return mapping[status]
