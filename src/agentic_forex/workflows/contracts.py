from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

_EVIDENCE_TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "mean_reversion_stationarity": (
        "stationarity",
        "stationary",
        "adf",
        "augmented dickey-fuller",
        "hurst",
        "variance ratio",
        "cointegration",
        "cointegrated",
    ),
    "mean_reversion_half_life": (
        "half-life",
        "half life",
        "ornstein-uhlenbeck",
    ),
    "momentum_horizon_correlation": (
        "time series momentum",
        "lagged return correlation",
        "lag correlation",
        "look-back",
        "lookback",
        "holding horizon",
        "past and future returns",
        "return correlation",
    ),
    "fx_common_quote_realism": (
        "common quote currency",
        "common quote",
        "quote currency",
        "cross-rate",
        "cross rate",
        "same dollar value",
        "common base currency",
    ),
    "fx_rollover_realism": (
        "rollover",
        "carry",
        "overnight interest",
        "interest differential",
        "swap rate",
        "triple rollover",
    ),
}


def infer_market_evidence_tags(*values: object) -> list[str]:
    fragments: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            fragments.append(value)
            continue
        if isinstance(value, dict):
            fragments.extend(str(item) for item in value.values() if item is not None)
            continue
        if isinstance(value, (list, tuple, set)):
            fragments.extend(str(item) for item in value if item is not None)
            continue
        fragments.append(str(value))
    haystack = " ".join(fragment for fragment in fragments if fragment).lower()
    inferred: set[str] = set()
    for tag, keywords in _EVIDENCE_TAG_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            inferred.add(tag)
    return sorted(inferred)


class DiscoveryRequest(BaseModel):
    question: str
    family_hint: str | None = None
    mirror_path: Path
    max_sources: int = 5


class ReframedQuestion(BaseModel):
    original_question: str
    normalized_question: str
    candidate_family: str
    reasoning: str
    search_terms: list[str]


class RouteDecision(BaseModel):
    next_node: str
    payload: dict[str, Any]
    rationale: str


class MarketContextSummary(BaseModel):
    session_focus: str
    volatility_preference: str
    directional_bias: str
    execution_notes: list[str] = Field(default_factory=list)
    allowed_hours_utc: list[int] = Field(default_factory=list)


class MarketRationale(BaseModel):
    market_behavior: str = ""
    edge_mechanism: str = ""
    persistence_reason: str = ""
    failure_regimes: list[str] = Field(default_factory=list)
    validation_focus: list[str] = Field(default_factory=list)
    evidence_tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _populate_evidence_tags(self) -> MarketRationale:
        inferred_tags = infer_market_evidence_tags(
            self.market_behavior,
            self.edge_mechanism,
            self.persistence_reason,
            self.failure_regimes,
            self.validation_focus,
        )
        combined = {str(tag).strip() for tag in self.evidence_tags if str(tag).strip()}
        combined.update(inferred_tags)
        self.evidence_tags = sorted(combined)
        return self

    def is_meaningful(self) -> bool:
        return any(
            [
                self.market_behavior.strip(),
                self.edge_mechanism.strip(),
                self.persistence_reason.strip(),
                bool(self.failure_regimes),
                bool(self.validation_focus),
                bool(self.evidence_tags),
            ]
        )


class CandidateDraft(BaseModel):
    candidate_id: str
    family: str
    title: str
    thesis: str
    source_citations: list[str]
    strategy_hypothesis: str
    market_context: MarketContextSummary
    market_rationale: MarketRationale = Field(default_factory=MarketRationale)
    setup_summary: str
    entry_summary: str
    exit_summary: str
    risk_summary: str
    notes: list[str] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)
    contradiction_summary: list[str] = Field(default_factory=list)
    critic_notes: list[str] = Field(default_factory=list)
    custom_filters: list[dict[str, str]] = Field(default_factory=list)
    enable_news_blackout: bool = False
    book_alignment_score: float = 0.0
    book_veto_reasons: list[str] = Field(default_factory=list)
    open_anchor_hour_utc: int | None = None
    max_hold_bars: int | None = None
    overnight_allowed: bool = False
    risk_filter_profile: str | None = None
    entry_style: str
    holding_bars: int
    signal_threshold: float
    stop_loss_pips: float
    take_profit_pips: float
    trailing_stop_enabled: bool = False
    trailing_stop_pips: float | None = None

    @model_validator(mode="after")
    def _populate_market_rationale(self) -> CandidateDraft:
        if self.market_rationale.is_meaningful():
            return self
        session_focus = self.market_context.session_focus.replace("_", " ").strip()
        volatility = self.market_context.volatility_preference.replace("_", " ").strip()
        self.market_rationale = MarketRationale(
            market_behavior=(self.strategy_hypothesis.strip() or self.setup_summary.strip() or self.thesis.strip()),
            edge_mechanism=(self.entry_summary.strip() or self.setup_summary.strip() or self.exit_summary.strip()),
            persistence_reason=(
                self.thesis.strip()
                or self.risk_summary.strip()
                or "The candidate requires fresh empirical confirmation under canonical OANDA research data."
            ),
            failure_regimes=[
                f"{session_focus or 'session'} conditions degrade materially",
                f"{volatility or 'volatility'} profile no longer matches the thesis",
                "spread, slippage, or fill delay consume the expected edge",
            ],
            validation_focus=[
                "verify the thesis on unseen time windows",
                "confirm the edge survives execution-cost stress",
                "retire the candidate if the claimed session context is not where the returns concentrate",
            ],
        )
        return self


class SessionPolicy(BaseModel):
    name: str
    allowed_sessions: list[str] = Field(default_factory=list)
    allowed_hours_utc: list[int] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SetupLogic(BaseModel):
    style: str
    summary: str
    trigger_conditions: list[str] = Field(default_factory=list)


class FilterRule(BaseModel):
    name: str
    rule: str


class RiskPolicy(BaseModel):
    stop_loss_pips: float
    take_profit_pips: float
    trailing_stop_enabled: bool = False
    trailing_stop_pips: float | None = None
    max_open_positions: int = 1
    max_risk_per_trade_pct: float = 0.25
    notes: list[str] = Field(default_factory=list)


class AccountModel(BaseModel):
    initial_balance: float = 100000.0
    account_currency: str = "USD"
    risk_per_trade_pct: float = 0.25
    leverage: float = 30.0
    contract_size: float = 100000.0
    pip_value_per_standard_lot: float = 10.0
    margin_buffer_pct: float = 10.0
    max_total_exposure_lots: float = 5.0
    notes: list[str] = Field(default_factory=list)


class NewsPolicy(BaseModel):
    enabled: bool = False
    event_source: str = "economic_calendar"
    minimum_impact: str = "high"
    blackout_minutes_before: int = 15
    blackout_minutes_after: int = 15
    currencies: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ExecutionCostModel(BaseModel):
    canonical_source: str = "oanda"  # Configurable; OANDA is the default per AGENTS.md policy.
    spread_mode: str = "bid_ask"
    broker_fee_model: str = "oanda_spread_only"
    spread_multiplier: float = 1.0
    slippage_pips: float = 0.0
    commission_per_standard_lot_usd: float = 0.0
    fill_delay_ms: int = 0
    liquidity_session_assumption: str = "intraday_liquidity"
    tick_model_assumption: str = "oanda_bid_ask_m1"
    notes: list[str] = Field(default_factory=list)


class CostModel(ExecutionCostModel):
    pass


class RiskEnvelope(BaseModel):
    max_daily_loss_pct: float = 5.0
    max_simultaneous_positions: int = 1
    max_spread_allowed_pips: float = 2.0
    session_boundaries_utc: list[int] = Field(default_factory=list)
    news_event_policy: str = "calendar_blackout"
    kill_switch_conditions: list[str] = Field(default_factory=list)
    leverage: float = 30.0
    sizing_rule: str = "fixed_fractional"
    margin_buffer_pct: float = 10.0
    notes: list[str] = Field(default_factory=list)


class ValidationProfile(BaseModel):
    time_split: tuple[float, float, float] = (0.6, 0.2, 0.2)
    minimum_test_trade_count: int = 100
    out_of_sample_profit_factor_floor: float = 1.05
    expectancy_floor: float = 0.0
    stress_profit_factor_floor: float = 1.0
    drawdown_review_trigger_pct: float = 12.0
    stress_spread_multiplier: float = 1.25
    stress_slippage_pips: float = 0.25
    stress_fill_delay_ms: int = 500
    walk_forward_windows: int = 3
    walk_forward_mode: Literal["equal_trade_windows", "anchored_time_windows"] = "anchored_time_windows"
    walk_forward_profit_factor_floor: float = 0.9
    walk_forward_min_trades_per_window: int = 10
    walk_forward_min_window_days: int = 7
    incident_baseline_window_start: str | None = None
    incident_baseline_window_end: str | None = None
    incident_baseline_expected_min_trade_count: int | None = None


class ShadowMLPolicy(BaseModel):
    enabled: bool = True
    primary_signal_allowed: bool = False
    modes: list[str] = Field(default_factory=lambda: ["scoring", "filtering", "critique", "ranking"])
    promotion_gate_notes: list[str] = Field(
        default_factory=lambda: [
            "Must beat rule baseline on out-of-sample profit factor.",
            "Must improve expectancy.",
            "Must not materially worsen drawdown.",
            "Must survive spread and slippage stress.",
        ]
    )


class StrategySpec(BaseModel):
    candidate_id: str
    family: str
    benchmark_group_id: str | None = None
    variant_name: str = "base"
    instrument: str = "EUR_USD"
    execution_granularity: str = "M1"
    context_granularities: list[str] = Field(default_factory=lambda: ["M5", "M15"])
    session_policy: SessionPolicy
    side_policy: str = "both"
    setup_logic: SetupLogic
    market_rationale: MarketRationale = Field(default_factory=MarketRationale)
    filters: list[FilterRule] = Field(default_factory=list)
    entry_logic: list[str] = Field(default_factory=list)
    exit_logic: list[str] = Field(default_factory=list)
    risk_policy: RiskPolicy
    account_model: AccountModel = Field(default_factory=AccountModel)
    news_policy: NewsPolicy = Field(default_factory=NewsPolicy)
    cost_model: CostModel = Field(default_factory=CostModel)
    execution_cost_model: ExecutionCostModel = Field(default_factory=ExecutionCostModel)
    risk_envelope: RiskEnvelope = Field(default_factory=RiskEnvelope)
    validation_profile: ValidationProfile = Field(default_factory=ValidationProfile)
    shadow_ml_policy: ShadowMLPolicy = Field(default_factory=ShadowMLPolicy)
    source_citations: list[str]
    notes: list[str] = Field(default_factory=list)
    open_anchor_hour_utc: int | None = None
    base_granularity: str = "M1"
    entry_style: str
    holding_bars: int
    signal_threshold: float
    stop_loss_pips: float
    take_profit_pips: float
    trailing_stop_enabled: bool = False
    trailing_stop_pips: float | None = None
    spread_multiplier: float = 1.0
    time_split: tuple[float, float, float] = (0.6, 0.2, 0.2)


class RuleSpec(BaseModel):
    candidate_id: str
    family: str
    market_hypothesis: str
    instrument: str = "EUR_USD"
    timeframe: str = "M1"
    session_hours_utc: list[int] = Field(default_factory=list)
    no_trade_hours_utc: list[int] = Field(default_factory=list)
    side_policy: str = "both"
    entry_trigger_formula: list[str] = Field(default_factory=list)
    order_type: str = "market"
    stop_logic: str
    target_logic: str
    timeout_logic: str
    spread_filter: str
    news_event_policy: str
    max_trades: int = 1
    cooldown_bars: int = 0
    sizing_rule: str
    invalidation_rules: list[str] = Field(default_factory=list)
    holding_bars: int
    stop_loss_pips: float
    take_profit_pips: float
    trailing_stop_enabled: bool = False
    trailing_stop_pips: float | None = None
    notes: list[str] = Field(default_factory=list)


class EASpec(BaseModel):
    candidate_id: str
    family: str
    instrument: str = "EUR_USD"
    timeframe: str = "M1"
    signal_inputs: list[str] = Field(default_factory=list)
    parameter_values: dict[str, float | int | str | bool] = Field(default_factory=dict)
    order_construction: dict[str, Any] = Field(default_factory=dict)
    stop_target_timeout: dict[str, Any] = Field(default_factory=dict)
    session_filters: dict[str, Any] = Field(default_factory=dict)
    risk_controls: dict[str, Any] = Field(default_factory=dict)
    state_machine: dict[str, Any] = Field(default_factory=dict)
    source_rule_spec_path: Path | None = None
    notes: list[str] = Field(default_factory=list)


class CriticNote(BaseModel):
    critic_name: str
    severity: str
    finding: str
    recommendation: str


class ReviewContext(BaseModel):
    candidate_id: str
    family: str
    title: str
    thesis: str
    citations: list[str]
    contradiction_summary: list[str] = Field(default_factory=list)
    critic_notes: list[CriticNote] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)
    readiness_status: str = "backtested"
    required_evidence: list[str] = Field(default_factory=list)
    robustness_mode: str = "staged_proxy_only"
    metrics: dict[str, Any]


class ReviewPacket(BaseModel):
    candidate_id: str
    readiness: str
    required_evidence: list[str] = Field(default_factory=list)
    robustness_mode: str = "staged_proxy_only"
    strengths: list[str]
    weaknesses: list[str]
    failure_modes: list[str] = Field(default_factory=list)
    contradiction_summary: list[str] = Field(default_factory=list)
    next_actions: list[str]
    approval_recommendation: str
    citations: list[str]
    metrics: dict[str, Any]
    ftmo_fit: dict[str, Any] = Field(default_factory=dict)


class FTMORuleset(BaseModel):
    ruleset_id: str
    evaluation_label: str
    profit_target_pct: float
    maximum_daily_loss_pct: float
    maximum_loss_pct: float
    best_day_profit_target_share_limit: float
    minimum_trading_days: int
    timezone: str
    notes: list[str] = Field(default_factory=list)


class FTMOFitReport(BaseModel):
    ruleset_id: str
    evaluation_label: str
    fit_score_0_100: float
    fit_band: str
    measured_with: str
    profit_target_progress_pct: float
    daily_loss_observed_pct: float
    overall_drawdown_observed_pct: float
    best_day_profit_share_of_target_pct: float
    trading_days_observed: int
    leverage_observed: float
    news_blackout_enabled: bool
    daily_loss_fit: float
    overall_drawdown_fit: float
    profit_target_fit: float
    best_day_concentration_fit: float
    minimum_trading_days_fit: float
    execution_discipline_fit: float
    real_market_behavior_fit: float
    blockers: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class CandidatePublication(BaseModel):
    candidate_id: str
    version: str
    published_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    manifest_path: Path
    snapshot_dir: Path


class MT5ValidationRequest(BaseModel):
    candidate_id: str
    audit_csv: Path | None = None
