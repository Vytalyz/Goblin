from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class ExperimentComparisonRecord(BaseModel):
    candidate_id: str
    family: str
    instrument: str
    entry_style: str
    benchmark_group_id: str | None = None
    variant_name: str | None = None
    dataset_start_utc: str | None = None
    dataset_end_utc: str | None = None
    trading_days_observed: int = 0
    trade_count: int = 0
    profit_factor: float = 0.0
    out_of_sample_profit_factor: float = 0.0
    expectancy_pips: float = 0.0
    max_drawdown_pct: float = 0.0
    stressed_profit_factor: float = 0.0
    stress_passed: bool = False
    ftmo_fit_score: float | None = None
    ftmo_fit_band: str | None = None
    readiness: str = "unreviewed"
    approval_recommendation: str = "not_reviewed"
    ready_for_publish: bool = False
    walk_forward_ok: bool | None = None
    benchmark_ranking_score: float | None = None
    comparison_score: float = 0.0
    spec_path: Path
    backtest_summary_path: Path
    stress_report_path: Path | None = None
    review_packet_path: Path | None = None
    benchmark_report_path: Path | None = None


class ExperimentComparisonReport(BaseModel):
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    family_filter: str | None = None
    candidate_filters: list[str] = Field(default_factory=list)
    total_records: int
    registry_path: Path
    report_path: Path
    latest_report_path: Path
    recommended_candidate_id: str | None = None
    excluded_candidates: dict[str, list[str]] = Field(default_factory=dict)
    records: list[ExperimentComparisonRecord] = Field(default_factory=list)


class ScalpingExplorationCandidate(BaseModel):
    candidate_id: str
    title: str
    entry_style: str
    thesis: str
    candidate_path: Path
    spec_path: Path
    backtest_summary_path: Path
    stress_report_path: Path
    review_packet_path: Path


class ScalpingExplorationReport(BaseModel):
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    family: str = "scalping"
    digest_source_count: int = 0
    approved_source_ids: list[str] = Field(default_factory=list)
    comparison_report_path: Path
    recommended_candidate_id: str | None = None
    report_path: Path
    candidates: list[ScalpingExplorationCandidate] = Field(default_factory=list)


class DayTradingExplorationCandidate(BaseModel):
    candidate_id: str
    title: str
    entry_style: str
    thesis: str
    candidate_path: Path
    spec_path: Path
    backtest_summary_path: Path
    stress_report_path: Path
    review_packet_path: Path


class DayTradingExplorationReport(BaseModel):
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    family: str = "day_trading"
    digest_source_count: int = 0
    approved_source_ids: list[str] = Field(default_factory=list)
    scan_report_path: Path | None = None
    comparison_report_path: Path
    recommended_candidate_id: str | None = None
    reference_candidate_id: str | None = None
    continuation_gate: DayTradingContinuationGate | None = None
    report_path: Path
    candidates: list[DayTradingExplorationCandidate] = Field(default_factory=list)


class DayTradingBehaviorScanRecord(BaseModel):
    candidate_id: str
    family: str
    entry_style: str
    title: str
    trade_count: int
    min_walk_forward_trade_count: int = 0
    walk_forward_ok: bool = False
    out_of_sample_profit_factor: float = 0.0
    expectancy_pips: float = 0.0
    stressed_profit_factor: float = 0.0
    stress_passed: bool = False
    max_drawdown_pct: float = 0.0
    supported_slice_count: int = 0
    comparison_eligible: bool = True
    comparison_eligibility_reason: str | None = None
    book_alignment_score: float = 0.0
    book_veto_reasons: list[str] = Field(default_factory=list)
    open_anchor_hour_utc: int | None = None
    max_hold_bars: int | None = None
    overnight_allowed: bool = False
    risk_filter_profile: str | None = None
    scan_score: float = 0.0
    candidate_path: Path
    spec_path: Path
    backtest_summary_path: Path
    stress_report_path: Path
    review_packet_path: Path


class DayTradingHypothesisScreenRecord(BaseModel):
    family: str
    entry_style: str
    title: str
    pretest_score: float = 0.0
    pretest_eligible: bool = False
    pretest_reason: str | None = None
    estimated_trade_days: int = 0
    estimated_signal_count: int = 0
    anchor_alignment_score: float = 0.0
    daytype_alignment_score: float = 0.0
    book_alignment_score: float = 0.0
    book_veto_reasons: list[str] = Field(default_factory=list)
    open_anchor_hour_utc: int | None = None
    max_hold_bars: int | None = None
    overnight_allowed: bool = False
    risk_filter_profile: str | None = None


class DayTradingBehaviorScanReport(BaseModel):
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    family: str = "day_trading"
    digest_source_count: int = 0
    approved_source_ids: list[str] = Field(default_factory=list)
    family_filter: str | None = None
    comparison_report_path: Path
    screened_template_count: int = 0
    materialized_candidate_count: int = 0
    recommended_candidate_id: str | None = None
    reference_candidate_id: str | None = None
    continuation_gate: DayTradingContinuationGate | None = None
    report_path: Path
    screen_records: list[DayTradingHypothesisScreenRecord] = Field(default_factory=list)
    records: list[DayTradingBehaviorScanRecord] = Field(default_factory=list)


class DayTradingContinuationGate(BaseModel):
    reference_candidate_id: str
    reference_trade_count: int
    reference_min_walk_forward_trade_count: int
    reference_out_of_sample_profit_factor: float
    reference_expectancy_pips: float
    reference_stressed_profit_factor: float
    required_trade_count: int
    required_min_walk_forward_trade_count: int
    minimum_out_of_sample_profit_factor: float
    minimum_expectancy_pips: float
    minimum_stressed_profit_factor: float
    decision: str
    selected_candidate_id: str | None = None
    reason: str


class DayTradingRefinementVariant(BaseModel):
    candidate_id: str
    variant_label: str
    title: str
    family: str
    trade_count: int
    out_of_sample_profit_factor: float
    stressed_profit_factor: float
    stress_passed: bool
    expectancy_pips: float
    max_drawdown_pct: float
    meets_requirement_subset: bool
    refinement_score: float
    candidate_path: Path
    spec_path: Path
    review_packet_path: Path


class DayTradingRefinementReport(BaseModel):
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    target_candidate_id: str
    target_family: str
    challenger_family: str | None = None
    objective: str
    comparison_report_path: Path
    report_path: Path
    recommended_candidate_id: str | None = None
    variants: list[DayTradingRefinementVariant] = Field(default_factory=list)


class ScalpingIterationVariant(BaseModel):
    candidate_id: str
    variant_label: str
    title: str
    trade_count: int
    out_of_sample_profit_factor: float
    stressed_profit_factor: float
    stress_passed: bool
    expectancy_pips: float
    max_drawdown_pct: float
    kept_oos_guardrail: bool
    meets_iteration_objective: bool
    iteration_score: float
    spec_path: Path
    review_packet_path: Path


class ScalpingIterationReport(BaseModel):
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    baseline_candidate_id: str
    target_candidate_id: str
    objective: str
    oos_guardrail_profit_factor: float
    comparison_report_path: Path
    report_path: Path
    recommended_candidate_id: str | None = None
    variants: list[ScalpingIterationVariant] = Field(default_factory=list)
