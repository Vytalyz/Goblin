from __future__ import annotations

import json

from agentic_forex.goblin.controls import (
    detect_live_runtime_anomalies,
    run_broker_reconciliation,
    write_live_attach_manifest,
    write_runtime_heartbeat,
    write_runtime_summary,
)
from agentic_forex.goblin.models import (
    LiveAttachManifest,
    RuntimeHeartbeat,
    RuntimeSummary,
)
from agentic_forex.governance.trial_ledger import append_trial_entry


def _bootstrap_candidate_governance(settings, candidate_id: str, family: str = "overlap_benchmark") -> None:
    """Create the minimal governance fixtures that enforce_candidate_strategy_governance requires."""
    report_dir = settings.paths().reports_dir / candidate_id
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "strategy_spec.json").write_text(
        json.dumps({"candidate_id": candidate_id, "family": family, "entry_style": "session_breakout"}),
        encoding="utf-8",
    )
    append_trial_entry(settings, candidate_id=candidate_id, family=family, stage="backtested")


def test_write_live_attach_manifest(settings):
    _bootstrap_candidate_governance(settings, "AF-CAND-0263")
    manifest = write_live_attach_manifest(
        settings,
        manifest=LiveAttachManifest(
            candidate_id="AF-CAND-0263",
            run_id="live-run-20260412",
            account_id="12345678",
            chart_symbol="EURUSD",
            timeframe="M1",
            leverage=30.0,
            lot_mode="fixed",
            terminal_build="3820",
            attachment_confirmed=True,
            inputs_hash="abc123",
        ),
    )

    assert manifest.report_path is not None
    assert manifest.report_path.exists()
    payload = json.loads(manifest.report_path.read_text(encoding="utf-8"))
    assert payload["candidate_id"] == "AF-CAND-0263"
    assert payload["chart_symbol"] == "EURUSD"
    assert payload["attachment_confirmed"] is True


def test_write_runtime_summary(settings):
    summary = write_runtime_summary(
        settings,
        summary=RuntimeSummary(
            candidate_id="AF-CAND-0263",
            run_id="live-run-20260412",
            bars_processed=480,
            allowed_hour_bars=210,
            signals_generated=8,
            order_attempts=8,
            order_successes=7,
            order_failures=1,
            audit_write_failures=0,
        ),
    )

    assert summary.report_path is not None
    assert summary.report_path.exists()
    payload = json.loads(summary.report_path.read_text(encoding="utf-8"))
    assert payload["order_successes"] == 7
    assert payload["order_failures"] == 1


def test_write_runtime_heartbeat_uses_timestamped_filename(settings):
    heartbeat = write_runtime_heartbeat(
        settings,
        heartbeat=RuntimeHeartbeat(
            candidate_id="AF-CAND-0263",
            run_id="live-run-20260412",
            status="healthy",
            terminal_active=True,
            algo_trading_enabled=True,
        ),
    )

    assert heartbeat.report_path is not None
    assert heartbeat.report_path.exists()
    assert "heartbeat_" in heartbeat.report_path.name
    assert heartbeat.report_path.parent.name == "heartbeats"

    second = write_runtime_heartbeat(
        settings,
        heartbeat=RuntimeHeartbeat(
            candidate_id="AF-CAND-0263",
            run_id="live-run-20260412",
            status="warning",
            terminal_active=True,
            algo_trading_enabled=False,
        ),
    )
    assert second.report_path != heartbeat.report_path


def test_detect_live_runtime_anomalies_healthy():
    heartbeat = RuntimeHeartbeat(
        candidate_id="AF-CAND-0263",
        run_id="live-run-20260412",
        status="healthy",
        terminal_active=True,
        algo_trading_enabled=True,
        account_changed=False,
        stale_audit_detected=False,
    )
    assert detect_live_runtime_anomalies(heartbeat) == []


def test_detect_live_runtime_anomalies_all_chaos():
    heartbeat = RuntimeHeartbeat(
        candidate_id="AF-CAND-0263",
        run_id="live-run-20260412",
        status="offline",
        terminal_active=False,
        algo_trading_enabled=False,
        account_changed=True,
        stale_audit_detected=True,
    )
    anomalies = detect_live_runtime_anomalies(heartbeat)
    assert "terminal_close" in anomalies
    assert "algo_trading_disabled" in anomalies
    assert "account_change" in anomalies
    assert "stale_audit_gap" in anomalies
    assert "heartbeat_gap" in anomalies


def test_detect_live_runtime_anomalies_partial():
    heartbeat = RuntimeHeartbeat(
        candidate_id="AF-CAND-0263",
        run_id="live-run-20260412",
        status="stale",
        terminal_active=True,
        algo_trading_enabled=True,
        account_changed=False,
        stale_audit_detected=True,
    )
    anomalies = detect_live_runtime_anomalies(heartbeat)
    assert "stale_audit_gap" in anomalies
    assert "heartbeat_gap" in anomalies
    assert "terminal_close" not in anomalies


def test_run_broker_reconciliation_no_ea_audit(settings, tmp_path):
    broker_csv = tmp_path / "broker_history.csv"
    broker_csv.write_text(
        "Ticket,Symbol,Type,Volume,Open Time,Close Time,Open Price,Close Price,Profit\n"
        "11111,EURUSD,buy,0.01,2026-01-15T09:30:00Z,2026-01-15T11:00:00Z,1.10500,1.10700,2.00\n"
        "22222,EURUSD,sell,0.01,2026-01-15T13:00:00Z,2026-01-15T14:30:00Z,1.10700,1.10500,2.00\n",
        encoding="utf-8",
    )

    report = run_broker_reconciliation(
        settings,
        candidate_id="AF-CAND-0263",
        run_id="live-run-20260412",
        broker_csv_path=broker_csv,
        account_id="12345678",
    )

    assert report.report_path is not None
    assert report.report_path.exists()
    assert report.reconciliation_status == "not_run"
    assert "EA audit not available" in report.notes[0]


def test_run_broker_reconciliation_matched(settings, tmp_path):
    broker_csv = tmp_path / "broker_history.csv"
    broker_csv.write_text(
        "Ticket,Symbol,Type,Volume,Open Time,Close Time,Open Price,Close Price,Profit\n"
        "11111,EURUSD,buy,0.01,2026-01-15T09:30:00Z,2026-01-15T11:00:00Z,1.10500,1.10700,2.00\n"
        "22222,EURUSD,sell,0.01,2026-01-15T13:00:00Z,2026-01-15T14:30:00Z,1.10700,1.10500,2.00\n",
        encoding="utf-8",
    )
    ea_audit = tmp_path / "ea_audit.json"
    ea_audit.write_text(
        json.dumps(
            {
                "candidate_id": "AF-CAND-0263",
                "run_id": "live-run-20260412",
                "trades": [
                    {
                        "ticket": "11111",
                        "symbol": "EURUSD",
                        "trade_type": "buy",
                        "volume": 0.01,
                        "open_time": "2026-01-15T09:30:00Z",
                        "close_time": "2026-01-15T11:00:00Z",
                        "open_price": 1.10500,
                        "close_price": 1.10700,
                        "profit": 2.00,
                    },
                    {
                        "ticket": "22222",
                        "symbol": "EURUSD",
                        "trade_type": "sell",
                        "volume": 0.01,
                        "open_time": "2026-01-15T13:00:00Z",
                        "close_time": "2026-01-15T14:30:00Z",
                        "open_price": 1.10700,
                        "close_price": 1.10500,
                        "profit": 2.00,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_broker_reconciliation(
        settings,
        candidate_id="AF-CAND-0263",
        run_id="live-run-20260412",
        broker_csv_path=broker_csv,
        ea_audit_path=ea_audit,
    )

    assert report.reconciliation_status == "matched"
    assert report.matched_trade_count == 2
    assert report.missing_broker_trade_count == 0
    assert report.extra_broker_trade_count == 0
    assert report.cash_pnl_delta == 0.0


def test_run_broker_reconciliation_mismatch(settings, tmp_path):
    broker_csv = tmp_path / "broker_history.csv"
    broker_csv.write_text(
        "Ticket,Symbol,Type,Volume,Open Time,Close Time,Open Price,Close Price,Profit\n"
        "11111,EURUSD,buy,0.01,2026-01-15T09:30:00Z,2026-01-15T11:00:00Z,1.10500,1.10700,2.00\n"
        "33333,EURUSD,buy,0.01,2026-01-15T15:00:00Z,2026-01-15T16:00:00Z,1.10600,1.10400,-2.00\n",
        encoding="utf-8",
    )
    ea_audit = tmp_path / "ea_audit.json"
    ea_audit.write_text(
        json.dumps(
            {
                "candidate_id": "AF-CAND-0263",
                "run_id": "live-run-20260412",
                "trades": [
                    {
                        "ticket": "11111",
                        "symbol": "EURUSD",
                        "trade_type": "buy",
                        "volume": 0.01,
                        "open_time": "2026-01-15T09:30:00Z",
                        "close_time": "2026-01-15T11:00:00Z",
                        "open_price": 1.10500,
                        "close_price": 1.10700,
                        "profit": 2.00,
                    },
                    {
                        "ticket": "22222",
                        "symbol": "EURUSD",
                        "trade_type": "sell",
                        "volume": 0.01,
                        "open_time": "2026-01-15T13:00:00Z",
                        "close_time": "2026-01-15T14:30:00Z",
                        "open_price": 1.10700,
                        "close_price": 1.10500,
                        "profit": 2.00,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_broker_reconciliation(
        settings,
        candidate_id="AF-CAND-0263",
        run_id="live-run-20260412",
        broker_csv_path=broker_csv,
        ea_audit_path=ea_audit,
    )

    assert report.reconciliation_status == "mismatch"
    assert report.matched_trade_count == 1
    assert report.missing_broker_trade_count == 1  # ticket 22222 in EA but not broker
    assert report.extra_broker_trade_count == 1   # ticket 33333 in broker but not EA
    assert report.report_path is not None
    assert report.report_path.exists()
    payload = json.loads(report.report_path.read_text(encoding="utf-8"))
    assert payload["reconciliation_status"] == "mismatch"


def test_run_broker_reconciliation_pnl_delta(settings, tmp_path):
    broker_csv = tmp_path / "broker_history.csv"
    broker_csv.write_text(
        "Ticket,Symbol,Type,Volume,Open Time,Close Time,Open Price,Close Price,Profit\n"
        "11111,EURUSD,buy,0.01,2026-01-15T09:30:00Z,2026-01-15T11:00:00Z,1.10500,1.10700,1.95\n",
        encoding="utf-8",
    )
    ea_audit = tmp_path / "ea_audit.json"
    ea_audit.write_text(
        json.dumps(
            {
                "candidate_id": "AF-CAND-0263",
                "run_id": "live-run-20260412",
                "trades": [
                    {
                        "ticket": "11111",
                        "symbol": "EURUSD",
                        "trade_type": "buy",
                        "volume": 0.01,
                        "open_time": "2026-01-15T09:30:00Z",
                        "close_time": "2026-01-15T11:00:00Z",
                        "open_price": 1.10500,
                        "close_price": 1.10700,
                        "profit": 2.00,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = run_broker_reconciliation(
        settings,
        candidate_id="AF-CAND-0263",
        run_id="live-run-20260412",
        broker_csv_path=broker_csv,
        ea_audit_path=ea_audit,
    )

    assert report.reconciliation_status == "matched"
    assert report.matched_trade_count == 1
    assert abs(report.cash_pnl_delta - 0.05) < 1e-9
