from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field


class MarketIngestResult(BaseModel):
    instrument: str
    source: str
    namespace: str = "research"
    granularity: str
    input_path: Path | None = None
    raw_path: Path | None = None
    parquet_path: Path
    row_count: int
    duckdb_path: Path
    start_time_utc: datetime | None = None
    end_time_utc: datetime | None = None
    quality_report_path: Path | None = None
    provenance: dict = Field(default_factory=dict)


class MissingBarGap(BaseModel):
    gap_start_utc: datetime
    gap_end_utc: datetime
    missing_bars: int
    gap_minutes: float


class SpreadAnomalySample(BaseModel):
    timestamp_utc: datetime
    spread_pips: float


class SessionCoverageBucket(BaseModel):
    hour_utc: int
    row_count: int
    row_share: float


class WeekdayCoverageBucket(BaseModel):
    weekday_utc: int
    row_count: int
    row_share: float


class MarketDataQualityReport(BaseModel):
    instrument: str
    granularity: str
    parquet_path: Path
    generated_at: datetime
    row_count: int
    unique_timestamp_count: int
    start_time_utc: datetime | None = None
    end_time_utc: datetime | None = None
    expected_interval_label: str
    expected_interval_seconds: int
    duplicate_row_count: int
    duplicate_unique_timestamp_count: int
    duplicate_timestamp_samples: list[datetime] = Field(default_factory=list)
    missing_bar_count: int
    missing_gap_samples: list[MissingBarGap] = Field(default_factory=list)
    market_closure_gap_count: int = 0
    market_closure_gap_samples: list[MissingBarGap] = Field(default_factory=list)
    spread_min_pips: float
    spread_mean_pips: float
    spread_median_pips: float
    spread_p95_pips: float
    spread_p99_pips: float
    spread_max_pips: float
    spread_anomaly_threshold_pips: float
    spread_anomaly_count: int
    spread_anomaly_samples: list[SpreadAnomalySample] = Field(default_factory=list)
    session_coverage: list[SessionCoverageBucket] = Field(default_factory=list)
    weekday_coverage: list[WeekdayCoverageBucket] = Field(default_factory=list)
    report_path: Path | None = None
