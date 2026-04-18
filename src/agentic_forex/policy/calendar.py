from __future__ import annotations

from pathlib import Path

import pandas as pd

from agentic_forex.config import Settings
from agentic_forex.utils.io import write_json

REQUIRED_COLUMNS = ["timestamp_utc", "currency", "impact", "title"]
IMPACT_RANK = {"low": 1, "medium": 2, "high": 3}


def ingest_economic_calendar(input_csv: Path, settings: Settings) -> dict:
    frame = pd.read_csv(input_csv)
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Economic calendar CSV is missing required columns: {', '.join(missing)}")
    normalized = frame.copy()
    normalized["timestamp_utc"] = pd.to_datetime(normalized["timestamp_utc"], utc=True)
    normalized["currency"] = normalized["currency"].astype(str).str.upper().str.strip()
    normalized["impact"] = normalized["impact"].astype(str).str.lower().str.strip()
    raw_copy = settings.paths().raw_calendar_dir / input_csv.name
    raw_copy.write_text(input_csv.read_text(encoding="utf-8"), encoding="utf-8")
    normalized.to_parquet(settings.economic_calendar_path, index=False)
    result = {
        "raw_path": str(raw_copy),
        "calendar_path": str(settings.economic_calendar_path),
        "row_count": int(len(normalized)),
        "currencies": sorted({item for item in normalized["currency"].unique() if item}),
        "impacts": sorted({item for item in normalized["impact"].unique() if item}),
    }
    write_json(settings.paths().policy_reports_dir / "economic_calendar_ingest.json", result)
    return result


def load_relevant_calendar_events(settings: Settings, *, currencies: list[str], minimum_impact: str) -> pd.DataFrame:
    if not settings.economic_calendar_path.exists():
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    frame = pd.read_parquet(settings.economic_calendar_path)
    if frame.empty:
        return frame
    normalized = frame.copy()
    normalized["timestamp_utc"] = pd.to_datetime(normalized["timestamp_utc"], utc=True)
    normalized["currency"] = normalized["currency"].astype(str).str.upper().str.strip()
    normalized["impact"] = normalized["impact"].astype(str).str.lower().str.strip()
    minimum_rank = IMPACT_RANK.get(minimum_impact.lower(), 3)
    allowed = {item.upper() for item in currencies}
    filtered = normalized.loc[
        normalized["currency"].isin(allowed)
        & normalized["impact"].map(lambda item: IMPACT_RANK.get(item, 0) >= minimum_rank)
    ]
    return filtered.sort_values("timestamp_utc").reset_index(drop=True)


def build_blackout_windows(events: pd.DataFrame, *, minutes_before: int, minutes_after: int) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=["start_utc", "end_utc", "currency", "impact", "title"])
    windows = events.copy()
    windows["start_utc"] = windows["timestamp_utc"] - pd.to_timedelta(minutes_before, unit="m")
    windows["end_utc"] = windows["timestamp_utc"] + pd.to_timedelta(minutes_after, unit="m")
    return windows[["start_utc", "end_utc", "currency", "impact", "title"]]


def is_in_blackout(timestamp, windows: pd.DataFrame) -> bool:
    if windows.empty:
        return False
    ts = pd.Timestamp(timestamp)
    overlap = windows.loc[(windows["start_utc"] <= ts) & (windows["end_utc"] >= ts)]
    return not overlap.empty
