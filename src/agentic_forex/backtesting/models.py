from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class TradeRecord(BaseModel):
    timestamp_utc: str
    exit_timestamp_utc: str
    split: str
    side: str
    entry_price: float
    exit_price: float
    pnl_pips: float
    pnl_dollars: float
    position_size_lots: float
    balance_after: float
    margin_utilization_pct: float
    session_bucket: str
    volatility_bucket: str
    context_bucket: str
    exit_reason: str


class RegimeBreakdown(BaseModel):
    label: str
    trade_count: int
    mean_pnl_pips: float
    profit_factor: float


class BacktestArtifact(BaseModel):
    candidate_id: str
    spec_path: Path
    trade_ledger_path: Path
    summary_path: Path
    trade_count: int
    win_rate: float
    profit_factor: float
    expectancy_pips: float
    max_drawdown_pct: float
    out_of_sample_profit_factor: float
    split_breakdown: dict = Field(default_factory=dict)
    regime_breakdown: dict = Field(default_factory=dict)
    walk_forward_summary: list[dict] = Field(default_factory=list)
    failure_attribution: dict = Field(default_factory=dict)
    account_metrics: dict = Field(default_factory=dict)
    artifact_references: dict = Field(default_factory=dict)


class StressScenarioResult(BaseModel):
    name: str
    spread_multiplier: float
    slippage_pips: float
    fill_delay_ms: int = 0
    commission_per_standard_lot_usd: float = 0.0
    profit_factor: float
    expectancy_pips: float


class StressTestReport(BaseModel):
    candidate_id: str
    base_profit_factor: float
    stressed_profit_factor: float
    spread_multiplier: float
    slippage_pips: float
    fill_delay_ms: int = 0
    commission_per_standard_lot_usd: float = 0.0
    passed: bool
    scenarios: list[StressScenarioResult] = Field(default_factory=list)
    artifact_references: dict = Field(default_factory=dict)
    report_path: Path


class BenchmarkVariantResult(BaseModel):
    candidate_id: str
    benchmark_group_id: str
    variant_name: str
    entry_style: str
    spec_path: Path
    backtest_summary_path: Path
    stress_report_path: Path
    trade_count: int
    profit_factor: float
    out_of_sample_profit_factor: float
    expectancy_pips: float
    max_drawdown_pct: float
    stressed_profit_factor: float
    grades: dict = Field(default_factory=dict)
    ranking_score: float


class ScalpingBenchmarkReport(BaseModel):
    benchmark_group_id: str
    base_candidate_id: str
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    report_path: Path
    variants: list[BenchmarkVariantResult] = Field(default_factory=list)
    recommended_candidate_id: str
