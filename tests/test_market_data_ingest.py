from __future__ import annotations

import json

import pandas as pd

from agentic_forex.market_data.ingest import backfill_oanda_history, ingest_market_csv, ingest_mt5_parity_csv, ingest_oanda_json
from agentic_forex.market_data.qa import build_market_data_quality_report

from conftest import create_market_csv, create_oanda_candles_json


def test_oanda_and_mt5_ingest_are_isolated(settings, tmp_path):
    oanda_json = create_oanda_candles_json(tmp_path)
    mt5_csv = create_market_csv(tmp_path, rows=120)

    oanda_result = ingest_oanda_json(oanda_json, settings)
    mt5_result = ingest_mt5_parity_csv(mt5_csv, settings)

    assert oanda_result.source == "oanda"
    assert oanda_result.namespace == "research"
    assert "research" in str(oanda_result.parquet_path)
    assert oanda_result.duckdb_path == settings.market_db_path
    assert oanda_result.provenance["comparison_time_basis"] == "UTC"
    assert oanda_result.provenance["research_data_contract"]["instrument"] == "EUR_USD"

    assert mt5_result.source == "mt5_parity"
    assert mt5_result.namespace == "mt5_parity"
    assert "mt5_parity" in str(mt5_result.parquet_path)
    assert mt5_result.duckdb_path == settings.mt5_parity_db_path
    assert mt5_result.provenance["comparison_time_basis"] == "UTC"


def test_oanda_backfill_paginates_and_writes_quality_report(settings, tmp_path, monkeypatch):
    source_json = create_oanda_candles_json(tmp_path, rows=6)
    payload = json.loads(source_json.read_text(encoding="utf-8"))
    candles = payload["candles"]
    newest_time = candles[-1]["time"]
    middle_time = candles[3]["time"]

    class DummyResponse:
        def __init__(self, response_payload):
            self._payload = response_payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    calls: list[dict] = []

    def fake_get(url, *, params, headers, timeout):
        calls.append({"url": url, "params": dict(params), "headers": dict(headers), "timeout": timeout})
        if params["to"] == newest_time:
            response_candles = candles[3:]
        elif params["to"] == middle_time:
            response_candles = candles[:4]
        else:
            raise AssertionError(f"Unexpected OANDA pagination boundary: {params['to']}")
        return DummyResponse(
            {
                "instrument": "EUR_USD",
                "granularity": "M1",
                "candles": response_candles,
            }
        )

    monkeypatch.setenv("OANDA_API_TOKEN", "test-token")
    monkeypatch.setattr("agentic_forex.market_data.ingest.requests.get", fake_get)

    result = backfill_oanda_history(
        settings=settings,
        instrument="EUR_USD",
        granularity="M1",
        start=candles[0]["time"],
        end=newest_time,
        chunk_size=3,
    )

    assert len(calls) == 2
    assert result.row_count == 6
    assert result.provenance["adapter"] == "oanda_backfill"
    assert result.provenance["chunk_count"] == 2
    assert result.provenance["comparison_time_basis"] == "UTC"
    assert result.provenance["research_data_contract"]["price_component"] == settings.oanda.price_component
    assert result.provenance["time_session_contract"]["broker_timezone"] == settings.policy.ftmo_timezone
    assert result.quality_report_path is not None
    assert result.quality_report_path.exists()
    manifest = json.loads(result.raw_path.read_text(encoding="utf-8"))
    assert manifest["chunk_count"] == 2
    qa_report = json.loads(result.quality_report_path.read_text(encoding="utf-8"))
    assert qa_report["missing_bar_count"] == 0
    assert qa_report["duplicate_row_count"] == 0


def test_market_quality_report_flags_duplicates_gaps_and_spread_spikes(settings, tmp_path):
    csv_path = create_market_csv(tmp_path, rows=120)
    ingest_result = ingest_market_csv(csv_path, settings)
    frame = pd.read_parquet(ingest_result.parquet_path)
    manipulated = pd.concat([frame.iloc[:60], frame.iloc[[10]], frame.iloc[61:]], ignore_index=True)
    manipulated.loc[60, "spread_pips"] = 4.2

    report = build_market_data_quality_report(
        manipulated,
        instrument="EUR_USD",
        granularity="M1",
        parquet_path=ingest_result.parquet_path,
        report_path=tmp_path / "qa-report.json",
    )

    assert report.duplicate_row_count >= 2
    assert report.duplicate_unique_timestamp_count == 1
    assert report.missing_bar_count == 1
    assert report.spread_anomaly_count >= 1
    assert report.report_path == tmp_path / "qa-report.json"
