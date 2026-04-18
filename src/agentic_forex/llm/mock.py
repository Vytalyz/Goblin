from __future__ import annotations

from pydantic import BaseModel

from agentic_forex.llm.base import BaseLLMClient
from agentic_forex.workflows.contracts import (
    CandidateDraft,
    MarketContextSummary,
    MarketRationale,
    ReframedQuestion,
    ReviewPacket,
)


class MockLLMClient(BaseLLMClient):
    def generate_structured(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_prompt: str,
        schema_model: type[BaseModel],
        payload: dict | None = None,
    ) -> BaseModel:
        context = payload or {}
        if schema_model is ReframedQuestion:
            question = str(context.get("question", ""))
            family = str(context.get("family_hint") or "").strip().lower()
            if not family:
                family = "scalping" if "scalp" in question.lower() else "day_trading"
            return ReframedQuestion(
                original_question=question,
                normalized_question=question.strip() or "Discover a fresh forex strategy.",
                candidate_family=family,
                reasoning="Mock reframe selected a family from the request language.",
                search_terms=[family.replace("_", " "), "eur usd", "entry exit", "session structure"],
            )
        if schema_model is CandidateDraft:
            family = str(context.get("candidate_family") or context.get("family") or "scalping")
            candidate = _base_candidate(family, context)
            return _apply_task_overlay(candidate, task_name)
        if schema_model is ReviewPacket:
            approval_recommendation = str(
                context.get("approval_recommendation")
                or (context.get("metrics") or {}).get("approval_recommendation")
                or "needs_human_review"
            )
            readiness_status = str(context.get("readiness_status") or "robustness_provisional")
            required_evidence = list(context.get("required_evidence") or [])
            robustness_mode = str(context.get("robustness_mode") or "staged_proxy_only")
            search_adjusted_weakness = (
                "Search-adjusted robustness gates are active; promotion still requires clean CSCV/PBO and White's Reality Check."
                if robustness_mode == "full_search_adjusted_robustness"
                else "Search-adjusted robustness evidence is still incomplete, so this review remains provisional."
            )
            return ReviewPacket(
                candidate_id=str(context.get("candidate_id", "AF-CAND-0001")),
                readiness=readiness_status,
                required_evidence=required_evidence,
                robustness_mode=robustness_mode,
                strengths=[
                    "Deterministic strategy spec with traceable rules.",
                    "Corpus quality gating and contradiction capture are present.",
                    "Backtest, stress, and shadow ML artifacts are available.",
                    "FTMO fit scoring is attached as a non-blocking policy layer.",
                ],
                weaknesses=[
                    "Discovery synthesis is still mock-driven in tests.",
                    "Needs explicit human approval before MT5 packet generation.",
                    search_adjusted_weakness,
                ],
                failure_modes=[
                    "Performance decays outside the intended intraday context.",
                    "Spread and slippage expansion can compress expectancy.",
                ],
                contradiction_summary=list(
                    context.get("contradiction_summary")
                    or ["Momentum and fade sources disagree on optimal entry timing."]
                ),
                next_actions=[
                    "Inspect walk-forward windows and worst stress scenario.",
                    "Approve only if the deterministic baseline remains stable against costs.",
                ],
                approval_recommendation=approval_recommendation,
                citations=list(context.get("citations") or ["SRC-001"]),
                metrics=dict(context.get("metrics") or {}),
                ftmo_fit=dict((context.get("metrics") or {}).get("ftmo_fit") or {}),
            )
        return schema_model.model_validate(context)


def _base_candidate(family: str, context: dict) -> CandidateDraft:
    is_scalping = family == "scalping"
    return CandidateDraft(
        candidate_id=str(context.get("candidate_id", "")) or "AF-CAND-0001",
        family=family,
        title="Europe Session Breakout Scalp Prototype" if is_scalping else "Day Session Breakout Prototype",
        thesis=(
            "Exploit Europe-session directional expansion in EUR/USD with deterministic breakout rules and execution filters."
            if is_scalping
            else "Trade session-defined directional expansion in EUR/USD with disciplined time exits."
        ),
        source_citations=list(context.get("source_citations") or ["SRC-001"]),
        strategy_hypothesis=(
            "High-quality scalping sources and the current empirical slice both favor Europe-session momentum expansion over blind exhaustion fades."
            if is_scalping
            else "High-quality intraday sources suggest day-trading edge appears when a defined session range transitions into controlled directional expansion."
        ),
        market_context=MarketContextSummary(
            session_focus="europe_open_breakout",
            volatility_preference="high",
            directional_bias="both",
            execution_notes=[
                "Use canonical OANDA bid/ask data for research.",
                "Do not allow MT5 parity data into research or training.",
                "Constrain scalping execution to Europe-session hours with explicit spread and volatility filters.",
            ],
            allowed_hours_utc=[7, 8, 9, 10, 11, 12] if is_scalping else [],
        ),
        market_rationale=MarketRationale(
            market_behavior=(
                "Europe-session directional expansion and retest behavior persist long enough to be expressed with deterministic rules."
                if is_scalping
                else "Session-defined range transitions can create a slower intraday continuation edge."
            ),
            edge_mechanism=(
                "Enter only when momentum, price location, and volatility filters all align in the same direction."
                if is_scalping
                else "Enter only after the range-to-expansion transition is explicit and machine-checkable."
            ),
            persistence_reason=(
                "The strategy assumes repeatable session microstructure rather than one-off chart patterns."
            ),
            failure_regimes=[
                "session structure changes or liquidity quality degrades",
                "spread, slippage, or delay consume the modeled edge",
                "the setup only works in one narrow historical window",
            ],
            validation_focus=[
                "test the idea on unseen time slices",
                "verify the edge survives stress assumptions",
                "retire the setup if returns do not concentrate in the claimed session context",
            ],
        ),
        setup_summary=(
            "Monitor Europe-session directional expansion and only participate when momentum, volatility, and price-location filters all align."
            if is_scalping
            else "Monitor session structure for controlled directional expansion after an identifiable range state."
        ),
        entry_summary=(
            "Enter on deterministic Europe-session breakout confirmation when 12-bar momentum, 5-bar return, and price location all agree."
            if is_scalping
            else "Enter on deterministic momentum confirmation after session structure alignment."
        ),
        exit_summary=(
            "Exit through fixed stop, fixed target, or 45-bar timeout."
            if is_scalping
            else "Exit through fixed stop, fixed target, or end-of-holding-window timeout."
        ),
        risk_summary="Single-position, low-risk deterministic rule set with explicit spread, volatility, and session filters.",
        notes=[
            "Mock discovery candidate for end-to-end validation using the empirically reworked breakout baseline.",
            "Shadow ML remains non-primary and cannot emit live signals.",
        ],
        quality_flags=list(context.get("quality_flags") or []),
        contradiction_summary=list(context.get("contradictions") or context.get("contradiction_summary") or []),
        critic_notes=list(context.get("critic_notes") or []),
        entry_style="session_breakout",
        holding_bars=45 if is_scalping else 96,
        signal_threshold=1.2 if is_scalping else 0.8,
        stop_loss_pips=5.0 if is_scalping else 12.0,
        take_profit_pips=8.0 if is_scalping else 18.0,
    )


def _apply_task_overlay(candidate: CandidateDraft, task_name: str) -> CandidateDraft:
    notes = list(candidate.notes)
    quality_flags = list(candidate.quality_flags)
    critic_notes = list(candidate.critic_notes)
    if task_name == "quant_critic":
        quality_flags.append("quant_reviewed")
        critic_notes.append("QuantCritic: expectancy and OOS stability must dominate narrative appeal.")
    elif task_name == "risk_critic":
        quality_flags.append("risk_reviewed")
        critic_notes.append("RiskCritic: reject if drawdown and cost stress overwhelm the base edge.")
    elif task_name == "execution_realist":
        quality_flags.append("execution_reviewed")
        critic_notes.append("ExecutionRealist: MT5 parity is downstream only; keep research data canonical to OANDA.")
    elif task_name in {"scalping_analyst", "day_trading_analyst"}:
        notes.append("Strategy persona produced the initial deterministic candidate draft.")
    return candidate.model_copy(update={"notes": notes, "quality_flags": quality_flags, "critic_notes": critic_notes})
