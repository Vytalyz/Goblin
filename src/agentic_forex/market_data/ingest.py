from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
import requests

from agentic_forex.config import Settings
from agentic_forex.goblin.evidence import build_default_research_data_contract, build_default_time_session_contract
from agentic_forex.market_data.models import MarketIngestResult
from agentic_forex.market_data.qa import assess_market_data_quality
from agentic_forex.utils.io import read_json, write_json

REQUIRED_COLUMNS = [
    "timestamp_utc",
    "bid_o",
    "bid_h",
    "bid_l",
    "bid_c",
    "ask_o",
    "ask_h",
    "ask_l",
    "ask_c",
    "volume",
]


def ingest_market_csv(input_csv: Path, settings: Settings) -> MarketIngestResult:
    frame = pd.read_csv(input_csv)
    normalized = _normalize_csv_frame(frame)
    raw_copy = settings.paths().raw_csv_dir / input_csv.name
    raw_copy.write_text(input_csv.read_text(encoding="utf-8"), encoding="utf-8")
    return _persist_market_frame(
        frame=normalized,
        settings=settings,
        source="csv_adapter",
        raw_path=raw_copy,
        input_path=input_csv,
        namespace="research",
        granularity=settings.data.base_granularity,
        provenance={
            "adapter": "csv",
            "canonical_source": settings.data.canonical_source,
            **_time_basis_metadata(settings),
        },
    )


def ingest_oanda_json(input_json: Path, settings: Settings) -> MarketIngestResult:
    payload = read_json(input_json)
    frame, instrument, granularity = _normalize_oanda_payload(payload, settings)
    raw_path = settings.paths().raw_oanda_dir / input_json.name
    raw_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return _persist_market_frame(
        frame=frame,
        settings=settings,
        source="oanda",
        raw_path=raw_path,
        input_path=input_json,
        namespace="research",
        granularity=granularity,
        instrument=instrument,
        provenance={
            "adapter": "oanda_json",
            **_time_basis_metadata(settings),
            **_research_contract_metadata(settings, instrument=instrument, granularity=granularity),
        },
    )


def fetch_oanda_candles(
    *,
    settings: Settings,
    instrument: str | None = None,
    granularity: str | None = None,
    count: int | None = None,
) -> MarketIngestResult:
    token = settings.oanda.api_token()
    if not token:
        raise ValueError(
            "Missing OANDA token. Set "
            f"{settings.oanda.token_env} or store a Windows Credential Manager secret under "
            f"{', '.join(settings.oanda.credential_targets)}."
        )
    resolved_instrument = instrument or settings.oanda.default_instrument
    resolved_granularity = granularity or settings.oanda.default_granularity
    resolved_count = count or settings.oanda.default_count
    url = f"{settings.oanda.host}/v3/instruments/{resolved_instrument}/candles"
    payload = _fetch_oanda_payload(
        settings=settings,
        token=token,
        url=url,
        params={
            "price": settings.oanda.price_component,
            "granularity": resolved_granularity,
            "count": resolved_count,
        },
    )
    raw_path = (
        settings.paths().raw_oanda_dir
        / f"{resolved_instrument.lower()}_{resolved_granularity.lower()}_{_timestamp_slug()}.json"
    )
    raw_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    frame, _, _ = _normalize_oanda_payload(payload, settings)
    return _persist_market_frame(
        frame=frame,
        settings=settings,
        source="oanda",
        raw_path=raw_path,
        input_path=None,
        namespace="research",
        granularity=resolved_granularity,
        instrument=resolved_instrument,
        provenance={
            "adapter": "oanda_api",
            "url": url,
            **_time_basis_metadata(settings),
            **_research_contract_metadata(
                settings,
                instrument=resolved_instrument,
                granularity=resolved_granularity,
            ),
        },
        merge_existing=True,
    )


def backfill_oanda_history(
    *,
    settings: Settings,
    start: str | datetime,
    end: str | datetime | None = None,
    instrument: str | None = None,
    granularity: str | None = None,
    chunk_size: int = 5000,
) -> MarketIngestResult:
    token = settings.oanda.api_token()
    if not token:
        raise ValueError(
            "Missing OANDA token. Set "
            f"{settings.oanda.token_env} or store a Windows Credential Manager secret under "
            f"{', '.join(settings.oanda.credential_targets)}."
        )
    resolved_instrument = instrument or settings.oanda.default_instrument
    resolved_granularity = granularity or settings.oanda.default_granularity
    resolved_start = _parse_utc_timestamp(start)
    resolved_end = _parse_utc_timestamp(end) if end else datetime.now(UTC)
    if resolved_end <= resolved_start:
        raise ValueError("Backfill end time must be after the start time.")
    page_size = min(max(int(chunk_size), 1), 5000)
    url = f"{settings.oanda.host}/v3/instruments/{resolved_instrument}/candles"

    frames: list[pd.DataFrame] = []
    chunk_records: list[dict] = []
    current_to = resolved_end
    page_index = 0

    while current_to > resolved_start:
        payload = _fetch_oanda_payload(
            settings=settings,
            token=token,
            url=url,
            params={
                "price": settings.oanda.price_component,
                "granularity": resolved_granularity,
                "count": page_size,
                "to": _to_oanda_timestamp(current_to),
            },
        )
        frame, _, _ = _normalize_oanda_payload(payload, settings)
        if frame.empty:
            break
        oldest_timestamp = frame["timestamp_utc"].min().to_pydatetime()
        newest_timestamp = frame["timestamp_utc"].max().to_pydatetime()
        chunk_path = (
            settings.paths().raw_oanda_backfill_dir
            / f"{resolved_instrument.lower()}_{resolved_granularity.lower()}_{page_index:04d}_{_timestamp_slug()}.json"
        )
        chunk_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        chunk_records.append(
            {
                "page_index": page_index,
                "raw_path": str(chunk_path),
                "row_count": int(len(frame)),
                "start_time_utc": oldest_timestamp.isoformat().replace("+00:00", "Z"),
                "end_time_utc": newest_timestamp.isoformat().replace("+00:00", "Z"),
            }
        )
        frames.append(frame)
        if oldest_timestamp <= resolved_start:
            break
        if oldest_timestamp >= current_to:
            raise ValueError("OANDA backfill pagination did not move backwards in time.")
        current_to = oldest_timestamp
        page_index += 1

    if not frames:
        raise ValueError("No candles returned for the requested OANDA backfill window.")

    combined = pd.concat(frames, ignore_index=True)
    combined["timestamp_utc"] = pd.to_datetime(combined["timestamp_utc"], utc=True)
    filtered = combined.loc[
        (combined["timestamp_utc"] >= pd.Timestamp(resolved_start))
        & (combined["timestamp_utc"] <= pd.Timestamp(resolved_end))
    ]
    filtered = (
        filtered.sort_values("timestamp_utc")
        .drop_duplicates(subset=["timestamp_utc"], keep="last")
        .reset_index(drop=True)
    )
    manifest_path = (
        settings.paths().raw_oanda_backfill_dir
        / f"{resolved_instrument.lower()}_{resolved_granularity.lower()}_{_timestamp_slug()}_manifest.json"
    )
    write_json(
        manifest_path,
        {
            "instrument": resolved_instrument,
            "granularity": resolved_granularity,
            "requested_start_utc": resolved_start.isoformat().replace("+00:00", "Z"),
            "requested_end_utc": resolved_end.isoformat().replace("+00:00", "Z"),
            "chunk_size": page_size,
            "chunk_count": len(chunk_records),
            "chunks": chunk_records,
        },
    )
    return _persist_market_frame(
        frame=filtered,
        settings=settings,
        source="oanda",
        raw_path=manifest_path,
        input_path=None,
        namespace="research",
        granularity=resolved_granularity,
        instrument=resolved_instrument,
        provenance={
            "adapter": "oanda_backfill",
            "url": url,
            "requested_start_utc": resolved_start.isoformat().replace("+00:00", "Z"),
            "requested_end_utc": resolved_end.isoformat().replace("+00:00", "Z"),
            "chunk_size": page_size,
            "chunk_count": len(chunk_records),
            **_time_basis_metadata(settings),
            **_research_contract_metadata(
                settings,
                instrument=resolved_instrument,
                granularity=resolved_granularity,
            ),
        },
        merge_existing=True,
    )


def ingest_mt5_parity_csv(input_csv: Path, settings: Settings) -> MarketIngestResult:
    frame = pd.read_csv(input_csv)
    if "timestamp_utc" not in frame.columns:
        raise ValueError("MT5 parity audit must include timestamp_utc.")
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    parquet_path = settings.paths().normalized_mt5_dir / f"{settings.data.instrument.lower()}_mt5_parity.parquet"
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(parquet_path, index=False)
    raw_copy = settings.paths().raw_mt5_dir / input_csv.name
    raw_copy.write_text(input_csv.read_text(encoding="utf-8"), encoding="utf-8")
    con = duckdb.connect(str(settings.mt5_parity_db_path))
    try:
        con.execute("CREATE OR REPLACE TABLE mt5_parity_audit AS SELECT * FROM read_parquet(?)", [str(parquet_path)])
    finally:
        con.close()
    result = MarketIngestResult(
        instrument=settings.data.instrument,
        source="mt5_parity",
        namespace="mt5_parity",
        granularity=settings.data.base_granularity,
        input_path=input_csv,
        raw_path=raw_copy,
        parquet_path=parquet_path,
        row_count=int(len(frame)),
        duckdb_path=settings.mt5_parity_db_path,
        provenance={"adapter": "mt5_audit_csv", **_time_basis_metadata(settings)},
    )
    write_json(settings.paths().reports_dir / "mt5_parity_ingest.json", result.model_dump(mode="json"))
    return result


def _normalize_csv_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    normalized = frame.copy()
    normalized["timestamp_utc"] = pd.to_datetime(normalized["timestamp_utc"], utc=True)
    return _augment_common_columns(normalized)


def _normalize_oanda_payload(payload: dict, settings: Settings) -> tuple[pd.DataFrame, str, str]:
    candles = payload.get("candles") or []
    instrument = str(payload.get("instrument") or settings.data.instrument)
    granularity = str(payload.get("granularity") or settings.data.base_granularity)
    records: list[dict] = []
    for candle in candles:
        if not candle.get("complete", True):
            continue
        bid = candle.get("bid") or {}
        ask = candle.get("ask") or {}
        if not bid or not ask:
            continue
        records.append(
            {
                "timestamp_utc": candle["time"],
                "bid_o": float(bid["o"]),
                "bid_h": float(bid["h"]),
                "bid_l": float(bid["l"]),
                "bid_c": float(bid["c"]),
                "ask_o": float(ask["o"]),
                "ask_h": float(ask["h"]),
                "ask_l": float(ask["l"]),
                "ask_c": float(ask["c"]),
                "volume": int(candle.get("volume", 0)),
            }
        )
    frame = pd.DataFrame.from_records(records)
    if frame.empty:
        raise ValueError("No complete bid/ask candles found in OANDA payload.")
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    return _augment_common_columns(frame), instrument, granularity


def _augment_common_columns(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    normalized["mid_o"] = (normalized["bid_o"] + normalized["ask_o"]) / 2
    normalized["mid_h"] = (normalized["bid_h"] + normalized["ask_h"]) / 2
    normalized["mid_l"] = (normalized["bid_l"] + normalized["ask_l"]) / 2
    normalized["mid_c"] = (normalized["bid_c"] + normalized["ask_c"]) / 2
    normalized["spread_pips"] = (normalized["ask_c"] - normalized["bid_c"]) * 10000
    return normalized


def _persist_market_frame(
    *,
    frame: pd.DataFrame,
    settings: Settings,
    source: str,
    raw_path: Path | None,
    input_path: Path | None,
    namespace: str,
    granularity: str,
    instrument: str | None = None,
    provenance: dict | None = None,
    merge_existing: bool = False,
) -> MarketIngestResult:
    resolved_instrument = instrument or settings.data.instrument
    existed_before = False
    if namespace == "research":
        parquet_dir = settings.paths().normalized_research_dir
        parquet_path = parquet_dir / f"{resolved_instrument.lower()}_{granularity.lower()}.parquet"
        duckdb_path = settings.market_db_path
        table_name = "market_bars"
    else:
        parquet_dir = settings.paths().normalized_mt5_dir
        parquet_path = parquet_dir / f"{resolved_instrument.lower()}_{granularity.lower()}_{namespace}.parquet"
        duckdb_path = settings.mt5_parity_db_path
        table_name = "mt5_parity_audit"
    parquet_dir.mkdir(parents=True, exist_ok=True)
    existed_before = parquet_path.exists()
    persisted_frame = frame.copy()
    if merge_existing and parquet_path.exists():
        existing = pd.read_parquet(parquet_path)
        persisted_frame = pd.concat([existing, persisted_frame], ignore_index=True)
    if "timestamp_utc" in persisted_frame.columns:
        persisted_frame["timestamp_utc"] = pd.to_datetime(persisted_frame["timestamp_utc"], utc=True)
        persisted_frame = persisted_frame.sort_values("timestamp_utc")
        persisted_frame = persisted_frame.drop_duplicates(subset=["timestamp_utc"], keep="last").reset_index(drop=True)
    persisted_frame.to_parquet(parquet_path, index=False)
    con = duckdb.connect(str(duckdb_path))
    try:
        con.execute(f"CREATE OR REPLACE TABLE {table_name} AS SELECT * FROM read_parquet(?)", [str(parquet_path)])
    finally:
        con.close()
    quality_report_path = None
    if namespace == "research":
        quality_report = assess_market_data_quality(
            settings,
            instrument=resolved_instrument,
            granularity=granularity,
            parquet_path=parquet_path,
        )
        quality_report_path = quality_report.report_path
    result = MarketIngestResult(
        instrument=resolved_instrument,
        source=source,
        namespace=namespace,
        granularity=granularity,
        input_path=input_path,
        raw_path=raw_path,
        parquet_path=parquet_path,
        row_count=int(len(persisted_frame)),
        duckdb_path=duckdb_path,
        start_time_utc=_frame_boundary(persisted_frame, "min"),
        end_time_utc=_frame_boundary(persisted_frame, "max"),
        quality_report_path=quality_report_path,
        provenance={**(provenance or {}), "merged_existing": bool(merge_existing and existed_before)},
    )
    report_name = "market_ingest.json" if namespace == "research" else "mt5_parity_ingest.json"
    write_json(settings.paths().reports_dir / report_name, result.model_dump(mode="json"))
    return result


def _fetch_oanda_payload(*, settings: Settings, token: str, url: str, params: dict) -> dict:
    response = requests.get(
        url,
        params=params,
        headers={"Authorization": f"Bearer {token}"},
        timeout=settings.oanda.timeout_seconds,
    )
    response.raise_for_status()
    return response.json()


def _parse_utc_timestamp(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _to_oanda_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _frame_boundary(frame: pd.DataFrame, op: str) -> datetime | None:
    if frame.empty or "timestamp_utc" not in frame.columns:
        return None
    series = frame["timestamp_utc"]
    value = getattr(series, op)()
    return value.to_pydatetime() if hasattr(value, "to_pydatetime") else None


def _timestamp_slug() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _time_basis_metadata(settings: Settings) -> dict[str, object]:
    time_session_contract = build_default_time_session_contract(settings)
    return {
        "comparison_time_basis": time_session_contract.comparison_timezone_basis,
        "time_session_contract": time_session_contract.model_dump(mode="json"),
    }


def _research_contract_metadata(
    settings: Settings,
    *,
    instrument: str,
    granularity: str,
) -> dict[str, object]:
    research_data_contract = build_default_research_data_contract(
        settings,
        instrument=instrument,
        granularity=granularity,
    )
    return {
        "research_data_contract": research_data_contract.model_dump(mode="json"),
    }
