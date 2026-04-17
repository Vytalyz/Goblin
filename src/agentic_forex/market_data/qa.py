from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from agentic_forex.config import Settings
from agentic_forex.market_data.models import (
    MarketDataQualityReport,
    MissingBarGap,
    SessionCoverageBucket,
    SpreadAnomalySample,
    WeekdayCoverageBucket,
)
from agentic_forex.utils.io import write_json


GRANULARITY_DELTAS = {
    "S5": timedelta(seconds=5),
    "S10": timedelta(seconds=10),
    "S15": timedelta(seconds=15),
    "S30": timedelta(seconds=30),
    "M1": timedelta(minutes=1),
    "M2": timedelta(minutes=2),
    "M4": timedelta(minutes=4),
    "M5": timedelta(minutes=5),
    "M10": timedelta(minutes=10),
    "M15": timedelta(minutes=15),
    "M30": timedelta(minutes=30),
    "H1": timedelta(hours=1),
    "H2": timedelta(hours=2),
    "H3": timedelta(hours=3),
    "H4": timedelta(hours=4),
    "H6": timedelta(hours=6),
    "H8": timedelta(hours=8),
    "H12": timedelta(hours=12),
    "D": timedelta(days=1),
    "W": timedelta(days=7),
}

MARKET_CLOSURE_THRESHOLD = timedelta(hours=8)
MAX_SAMPLE_COUNT = 12


def assess_market_data_quality(
    settings: Settings,
    *,
    instrument: str | None = None,
    granularity: str | None = None,
    parquet_path: Path | None = None,
) -> MarketDataQualityReport:
    resolved_instrument = instrument or settings.data.instrument
    resolved_granularity = granularity or settings.data.base_granularity
    resolved_path = parquet_path or (
        settings.paths().normalized_research_dir / f"{resolved_instrument.lower()}_{resolved_granularity.lower()}.parquet"
    )
    if not resolved_path.exists():
        raise FileNotFoundError(f"Market parquet not found: {resolved_path}")
    frame = pd.read_parquet(resolved_path)
    return build_market_data_quality_report(
        frame,
        instrument=resolved_instrument,
        granularity=resolved_granularity,
        parquet_path=resolved_path,
        report_path=_report_path(settings, resolved_instrument, resolved_granularity),
    )


def build_market_data_quality_report(
    frame: pd.DataFrame,
    *,
    instrument: str,
    granularity: str,
    parquet_path: Path,
    report_path: Path | None = None,
) -> MarketDataQualityReport:
    if "timestamp_utc" not in frame.columns:
        raise ValueError("Market frame must include timestamp_utc for QA.")
    normalized = frame.copy()
    normalized["timestamp_utc"] = pd.to_datetime(normalized["timestamp_utc"], utc=True)
    normalized = normalized.sort_values("timestamp_utc").reset_index(drop=True)
    unique_frame = normalized.drop_duplicates(subset=["timestamp_utc"], keep="last").reset_index(drop=True)

    expected_delta = _expected_delta(granularity)
    duplicate_mask = normalized.duplicated(subset=["timestamp_utc"], keep=False)
    duplicate_rows = normalized.loc[duplicate_mask, "timestamp_utc"]

    missing_gaps: list[MissingBarGap] = []
    closure_gaps: list[MissingBarGap] = []
    missing_bar_count = 0
    if len(unique_frame) > 1:
        timestamps = unique_frame["timestamp_utc"]
        diffs = timestamps.diff()
        for index, diff in enumerate(diffs.iloc[1:], start=1):
            if pd.isna(diff) or diff <= expected_delta:
                continue
            previous_timestamp = timestamps.iloc[index - 1].to_pydatetime()
            current_timestamp = timestamps.iloc[index].to_pydatetime()
            missing_bars = max(int(round(diff.total_seconds() / expected_delta.total_seconds())) - 1, 1)
            gap = MissingBarGap(
                gap_start_utc=previous_timestamp,
                gap_end_utc=current_timestamp,
                missing_bars=missing_bars,
                gap_minutes=round(diff.total_seconds() / 60, 3),
            )
            if diff >= MARKET_CLOSURE_THRESHOLD:
                closure_gaps.append(gap)
            else:
                missing_gaps.append(gap)
                missing_bar_count += missing_bars

    spread_series = normalized.get("spread_pips")
    if spread_series is None:
        raise ValueError("Market frame must include spread_pips for QA.")
    spread_series = spread_series.astype(float)
    spread_min = float(spread_series.min())
    spread_mean = float(spread_series.mean())
    spread_median = float(spread_series.median())
    spread_p95 = float(spread_series.quantile(0.95))
    spread_p99 = float(spread_series.quantile(0.99))
    spread_max = float(spread_series.max())
    spread_std = float(spread_series.std(ddof=0) if len(spread_series) > 1 else 0.0)
    spread_threshold = max(spread_p99 * 1.5, spread_median * 2.5, spread_mean + (3 * spread_std), 1.5)
    anomalies = normalized.loc[spread_series >= spread_threshold, ["timestamp_utc", "spread_pips"]]

    session_counts = unique_frame["timestamp_utc"].dt.hour.value_counts().sort_index()
    weekday_counts = unique_frame["timestamp_utc"].dt.weekday.value_counts().sort_index()
    unique_count = int(len(unique_frame))

    report = MarketDataQualityReport(
        instrument=instrument,
        granularity=granularity,
        parquet_path=parquet_path,
        generated_at=datetime.now(UTC),
        row_count=int(len(normalized)),
        unique_timestamp_count=unique_count,
        start_time_utc=_frame_boundary(unique_frame, "min"),
        end_time_utc=_frame_boundary(unique_frame, "max"),
        expected_interval_label=granularity,
        expected_interval_seconds=int(expected_delta.total_seconds()),
        duplicate_row_count=int(duplicate_mask.sum()),
        duplicate_unique_timestamp_count=int(duplicate_rows.nunique()),
        duplicate_timestamp_samples=[item.to_pydatetime() for item in duplicate_rows.drop_duplicates().head(MAX_SAMPLE_COUNT)],
        missing_bar_count=missing_bar_count,
        missing_gap_samples=missing_gaps[:MAX_SAMPLE_COUNT],
        market_closure_gap_count=len(closure_gaps),
        market_closure_gap_samples=closure_gaps[:MAX_SAMPLE_COUNT],
        spread_min_pips=round(spread_min, 6),
        spread_mean_pips=round(spread_mean, 6),
        spread_median_pips=round(spread_median, 6),
        spread_p95_pips=round(spread_p95, 6),
        spread_p99_pips=round(spread_p99, 6),
        spread_max_pips=round(spread_max, 6),
        spread_anomaly_threshold_pips=round(float(spread_threshold), 6),
        spread_anomaly_count=int(len(anomalies)),
        spread_anomaly_samples=[
            SpreadAnomalySample(timestamp_utc=row.timestamp_utc.to_pydatetime(), spread_pips=round(float(row.spread_pips), 6))
            for row in anomalies.head(MAX_SAMPLE_COUNT).itertuples(index=False)
        ],
        session_coverage=[
            SessionCoverageBucket(
                hour_utc=int(hour),
                row_count=int(count),
                row_share=round(count / unique_count, 6) if unique_count else 0.0,
            )
            for hour, count in session_counts.items()
        ],
        weekday_coverage=[
            WeekdayCoverageBucket(
                weekday_utc=int(day),
                row_count=int(count),
                row_share=round(count / unique_count, 6) if unique_count else 0.0,
            )
            for day, count in weekday_counts.items()
        ],
        report_path=report_path,
    )
    if report_path:
        write_json(report_path, report.model_dump(mode="json"))
    return report


def _frame_boundary(frame: pd.DataFrame, op: str) -> datetime | None:
    if frame.empty:
        return None
    series = frame["timestamp_utc"]
    value = getattr(series, op)()
    return value.to_pydatetime() if hasattr(value, "to_pydatetime") else None


def _expected_delta(granularity: str) -> timedelta:
    if granularity not in GRANULARITY_DELTAS:
        raise ValueError(f"Unsupported granularity for QA: {granularity}")
    return GRANULARITY_DELTAS[granularity]


def _report_path(settings: Settings, instrument: str, granularity: str) -> Path:
    return settings.paths().market_quality_reports_dir / f"{instrument.lower()}_{granularity.lower()}.json"
