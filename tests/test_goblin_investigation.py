from __future__ import annotations

import json
from pathlib import Path

from agentic_forex.goblin.controls import build_incident_investigation_pack
from agentic_forex.governance.models import (
    FrozenArtifactSnapshot,
    LedgerPerformanceSummary,
    ProductionIncidentReport,
    TesterHarnessCheck,
    TradeDiffSummary,
)


def test_build_incident_investigation_pack_writes_reproducible_artifacts(settings, tmp_path: Path):
    incident_report_path = tmp_path / "incident_report.json"
    report = ProductionIncidentReport(
        incident_id="production-incident-AF-CAND-0263-test",
        candidate_id="AF-CAND-0263",
        workflow_status="attribution_complete",
        attribution_bucket="implementation_delta",
        freeze=FrozenArtifactSnapshot(
            candidate_id="AF-CAND-0263",
            artifact_paths={"strategy_spec.json": "C:\\repo\\reports\\AF-CAND-0263\\strategy_spec.json"},
            artifact_hashes={"strategy_spec.json": "abc123"},
        ),
        harness_check=TesterHarnessCheck(
            status="passed",
            baseline_window_start="2025-10-01",
            baseline_window_end="2026-03-20",
            expected_min_trade_count=100,
            observed_trade_count=130,
            tester_report_path=tmp_path / "baseline_report.htm",
        ),
        ledger_summaries=[
            LedgerPerformanceSummary(
                source_name="live_audit",
                trade_count=12,
                net_pips=-50.3,
                csv_path=tmp_path / "live_audit.csv",
            ),
            LedgerPerformanceSummary(
                source_name="mt5_replay_audit",
                trade_count=13,
                net_pips=-30.8,
                csv_path=tmp_path / "mt5_replay.csv",
            ),
        ],
        trade_diff_summaries=[
            TradeDiffSummary(
                reference_name="mt5_replay_audit",
                observed_name="live_audit",
                matched_count=12,
                missing_observed_count=1,
                extra_observed_count=0,
                material_mismatch_count=4,
                pnl_delta_pips=-19.5,
                classifications={"missing_live_trade": 1, "spread_slippage_delta": 3},
                diff_csv_path=tmp_path / "mt5_vs_live_diff.csv",
            )
        ],
        artifact_paths={
            "incident_dir": str(tmp_path),
            "same_window_tester_report_path": str(tmp_path / "same_window_report.htm"),
        },
        notes=["Validation remains suspended until closure evidence is accepted."],
        report_path=incident_report_path,
    )
    incident_report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    pack = build_incident_investigation_pack(settings, incident_report_path=incident_report_path)

    assert pack.report_path is not None
    assert pack.report_path.exists()
    assert len(pack.scenario_paths) == 3
    for scenario_path in pack.scenario_paths:
        assert scenario_path.exists()
        assert len(scenario_path.name) <= 64
    assert pack.trace_path is not None and pack.trace_path.exists()
    assert len(pack.trace_path.name) <= 64
    assert pack.evaluation_suite_path is not None and pack.evaluation_suite_path.exists()
    assert len(pack.evaluation_suite_path.name) <= 64
    assert pack.benchmark_history_path is not None and pack.benchmark_history_path.exists()

    trace_payload = json.loads(pack.trace_path.read_text(encoding="utf-8"))
    assert trace_payload["final_classification"] == "implementation_delta"
    assert "harness_status=passed" in trace_payload["intermediate_classifications"]
    assert trace_payload["follow_up_actions"]

    suite_payload = json.loads(pack.evaluation_suite_path.read_text(encoding="utf-8"))
    assert suite_payload["suite_type"] == "incident_investigation"
    assert len(suite_payload["scenario_ids"]) == 3

    benchmark_payload = json.loads(pack.benchmark_history_path.read_text(encoding="utf-8"))
    assert benchmark_payload["incident_id"] == "production-incident-AF-CAND-0263-test"
    assert benchmark_payload["incident_report_hash"]
