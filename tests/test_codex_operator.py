from __future__ import annotations

from pathlib import Path

from agentic_forex.experiments.models import ExperimentComparisonRecord, ExperimentComparisonReport
from agentic_forex.goblin.controls import write_strategy_rationale_card
from agentic_forex.operator import (
    audit_candidate_branches,
    audit_candidate_window_density,
    export_operator_state,
    inspect_governed_action,
    run_governed_action,
    sync_codex_capabilities,
    validate_operator_contract,
)
from agentic_forex.utils.io import write_json


class _FakeResponse:
    def __init__(self, url: str) -> None:
        self.text = f"<html><title>{url}</title><h1>{url}</h1><p>Codex capability body.</p></html>"

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def get(self, url: str, timeout: int, headers: dict[str, str]):  # noqa: ARG002
        return _FakeResponse(url)


class _FakeProgramLoopResult:
    def __init__(self, report_path: Path) -> None:
        self.report_path = report_path

    def model_dump(self, mode: str = "json") -> dict:  # noqa: ARG002
        return {
            "program_id": "program-001",
            "family": "scalping",
            "status": "completed",
            "stop_reason": "ok",
            "report_path": str(self.report_path),
        }


def test_sync_codex_capabilities_writes_catalog_and_index(settings):
    report = sync_codex_capabilities(settings, run_id="cap-sync-test", session=_FakeSession())

    assert report.failed_entries == 0
    assert report.catalog_path.exists()
    assert report.index_path.exists()

    hooks_entry = next(entry for entry in report.entries if entry.source_id == "official.codex_hooks")
    assert hooks_entry.windows_support == "disabled"
    assert hooks_entry.critical_path_eligibility == "forbidden"


def test_export_operator_state_includes_codex_assets(settings):
    sync_codex_capabilities(settings, run_id="cap-sync-state", session=_FakeSession())
    report = export_operator_state(settings, run_id="operator-state-test")

    assert report.report_path.exists()
    assert "portfolio_orchestrator.toml" in report.codex_assets["codex_agent_files"]
    assert any(item["name"] == "Capability Refresh" for item in report.automation_specs)
    assert report.capability_catalog_path == settings.paths().capability_catalog_path


def test_validate_operator_contract_passes_for_scaffolded_project(settings):
    report = validate_operator_contract(settings)

    assert report.report_path.exists()
    assert report.passed is True
    assert not [item for item in report.findings if item.severity == "error"]


def test_run_and_inspect_governed_action_write_operator_manifest(settings, monkeypatch, tmp_path):
    fake_report_path = tmp_path / "program-loop.json"
    fake_report_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "agentic_forex.operator.service.run_program_loop",
        lambda *args, **kwargs: _FakeProgramLoopResult(fake_report_path),
    )

    write_strategy_rationale_card(
        settings,
        family="scalping",
        thesis="Scalping family remains bounded to deterministic throughput controls.",
    )

    manifest = run_governed_action(settings, action="program_loop", run_id="governed-action-test")

    assert manifest.manifest_path.exists()
    assert manifest.output_report_path == fake_report_path
    strategy_gate = next(
        item
        for item in manifest.delegated_agent_summaries
        if item.get("gate") == "strategy_governance"
    )
    assert strategy_gate["methodology_audit_path"] is not None
    assert strategy_gate["methodology_audit_passed"] is True
    assert float(strategy_gate["methodology_audit_score"]) >= 0.55

    inspection = inspect_governed_action(settings, run_id="governed-action-test")
    assert inspection.manifest_path == manifest.manifest_path
    assert inspection.output_report_path == fake_report_path


def test_audit_candidate_branches_opens_new_family_when_both_branches_are_terminal(settings, monkeypatch):
    reports_root = settings.paths().reports_dir
    for candidate_id, family, entry_style, oos_pf, expectancy, stressed_pf in (
        ("AF-CAND-0291", "europe_open_reclaim_research", "range_reclaim", 0.93, 0.14, 0.81),
        ("AF-CAND-0328", "europe_open_balance_breakout_research", "balance_area_breakout", 1.25, -0.24, 0.65),
    ):
        report_dir = reports_root / candidate_id
        report_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            report_dir / "review_packet.json",
            {
                "candidate_id": candidate_id,
                "readiness": "robustness_provisional",
                "approval_recommendation": "needs_human_review",
                "metrics": {
                    "family": family,
                    "trade_count": 150,
                    "profit_factor": 1.0,
                    "out_of_sample_profit_factor": oos_pf,
                    "expectancy_pips": expectancy,
                    "max_drawdown_pct": 3.0,
                    "stress_scenarios": [{"profit_factor": stressed_pf}],
                    "stress_passed": False,
                },
            },
        )
        write_json(
            report_dir / "robustness_report.json",
            {
                "candidate_id": candidate_id,
                "trial_count_family": 52,
                "trial_count_candidate": 12,
                "walk_forward_ok": False,
                "stress_ok": False,
                "warnings": ["Walk-forward windows are not uniformly stable."],
            },
        )
        campaign_dir = settings.paths().campaigns_dir / f"{candidate_id.lower()}-next-step"
        campaign_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            campaign_dir / "next_step_report.json",
            {
                "candidate_scope": [candidate_id],
                "stop_reason": "diagnosis_ambiguous_no_mutation_justified",
                "transition_status": "hard_stop",
                "auto_continue_allowed": False,
                "candidate_reports": [
                    {
                        "candidate_id": candidate_id,
                        "supported_slices": [],
                        "recommended_mutation": None,
                        "diagnostic_confidence": 0.0,
                        "notes": ["No single supported session, context, or spread slice was strong enough to justify mutation."],
                    }
                ],
            },
        )

    comparison_report = ExperimentComparisonReport(
        total_records=2,
        registry_path=settings.paths().experiments_dir / "registry.csv",
        report_path=settings.paths().experiments_dir / "comparison_pytest.json",
        latest_report_path=settings.paths().experiments_dir / "comparison_latest.json",
        recommended_candidate_id=None,
        records=[
            ExperimentComparisonRecord(
                candidate_id="AF-CAND-0291",
                family="europe_open_reclaim_research",
                instrument="EUR_USD",
                entry_style="range_reclaim",
                trade_count=150,
                out_of_sample_profit_factor=0.93,
                expectancy_pips=0.14,
                max_drawdown_pct=3.0,
                stressed_profit_factor=0.81,
                stress_passed=False,
                comparison_score=-30.0,
                spec_path=reports_root / "AF-CAND-0291" / "strategy_spec.json",
                backtest_summary_path=reports_root / "AF-CAND-0291" / "backtest_summary.json",
            ),
            ExperimentComparisonRecord(
                candidate_id="AF-CAND-0328",
                family="europe_open_balance_breakout_research",
                instrument="EUR_USD",
                entry_style="balance_area_breakout",
                trade_count=156,
                out_of_sample_profit_factor=1.25,
                expectancy_pips=-0.24,
                max_drawdown_pct=3.6,
                stressed_profit_factor=0.65,
                stress_passed=False,
                comparison_score=-20.0,
                spec_path=reports_root / "AF-CAND-0328" / "strategy_spec.json",
                backtest_summary_path=reports_root / "AF-CAND-0328" / "backtest_summary.json",
            ),
        ],
    )
    monkeypatch.setattr("agentic_forex.operator.service.compare_experiments", lambda *args, **kwargs: comparison_report)

    report = audit_candidate_branches(
        settings,
        candidate_ids=["AF-CAND-0291", "AF-CAND-0328"],
        next_family_hint="europe_open_compression_reversion_research",
    )

    assert report.report_path.exists()
    assert report.decision == "open_new_family"
    assert report.recommended_candidate_id is None
    assert report.next_family_hint == "europe_open_compression_reversion_research"


def test_audit_candidate_window_density_adjusts_discovery_when_weak_window_has_no_contiguous_hour_block(settings):
    reports_root = settings.paths().reports_dir
    specs = {
        "AF-CAND-0414": [8, 9, 10, 11, 12],
        "AF-CAND-0416": [7, 8, 9, 10, 11, 12],
        "AF-CAND-0418": [8, 9, 10, 11, 12],
    }
    ledgers = {
        "AF-CAND-0414": [
            ("2025-10-10T08:10:00Z", 1.0),
            ("2025-10-11T09:15:00Z", 0.8),
            ("2025-12-10T09:20:00Z", -0.6),
            ("2025-12-11T11:00:00Z", -0.4),
            ("2026-02-10T08:05:00Z", 1.4),
            ("2026-02-11T12:15:00Z", 1.1),
        ],
        "AF-CAND-0416": [
            ("2025-10-10T07:10:00Z", 0.9),
            ("2025-10-11T08:15:00Z", 0.7),
            ("2025-12-10T09:20:00Z", -1.0),
            ("2025-12-11T11:00:00Z", -0.8),
            ("2025-12-12T09:30:00Z", 0.2),
            ("2026-02-10T08:05:00Z", 1.0),
            ("2026-02-11T12:15:00Z", 0.8),
        ],
        "AF-CAND-0418": [
            ("2025-10-10T08:10:00Z", 1.1),
            ("2025-10-11T10:15:00Z", 0.5),
            ("2025-12-10T09:20:00Z", -0.7),
            ("2025-12-11T11:00:00Z", -0.6),
            ("2025-12-12T09:30:00Z", -0.3),
            ("2026-02-10T08:05:00Z", 1.2),
            ("2026-02-11T12:15:00Z", 0.9),
        ],
    }
    for candidate_id, allowed_hours in specs.items():
        report_dir = reports_root / candidate_id
        report_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            report_dir / "candidate.json",
            {
                "candidate_id": candidate_id,
                "family": "europe_open_high_vol_pullback_persistence_research",
                "entry_style": "pullback_continuation",
            },
        )
        write_json(
            report_dir / "strategy_spec.json",
            {
                "candidate_id": candidate_id,
                "family": "europe_open_high_vol_pullback_persistence_research",
                "entry_style": "pullback_continuation",
                "session_policy": {"allowed_hours_utc": allowed_hours},
            },
        )
        write_json(
            report_dir / "backtest_summary.json",
            {
                "trade_count": len(ledgers[candidate_id]),
                "out_of_sample_profit_factor": 1.4,
                "expectancy_pips": 0.4,
                "walk_forward_summary": [
                    {
                        "window": 1,
                        "start_utc": "2025-10-01T00:00:00Z",
                        "end_utc": "2025-11-30T00:00:00Z",
                        "trade_count": 4,
                        "profit_factor": 1.3,
                        "expectancy_pips": 0.5,
                        "passed": True,
                    },
                    {
                        "window": 2,
                        "start_utc": "2025-11-30T00:00:00Z",
                        "end_utc": "2026-01-31T00:00:00Z",
                        "trade_count": 2 if candidate_id == "AF-CAND-0414" else 3,
                        "profit_factor": 0.7,
                        "expectancy_pips": -0.5,
                        "passed": False,
                    },
                    {
                        "window": 3,
                        "start_utc": "2026-01-31T00:00:00Z",
                        "end_utc": "2026-03-31T00:00:00Z",
                        "trade_count": 3,
                        "profit_factor": 1.5,
                        "expectancy_pips": 0.7,
                        "passed": True,
                    },
                ],
            },
        )
        write_json(
            report_dir / "stress_test.json",
            {
                "stressed_profit_factor": 1.05,
                "passed": True,
            },
        )
        with (report_dir / "trade_ledger.csv").open("w", encoding="utf-8", newline="") as handle:
            handle.write("timestamp_utc,pnl_pips\n")
            for timestamp_utc, pnl_pips in ledgers[candidate_id]:
                handle.write(f"{timestamp_utc},{pnl_pips}\n")

    report = audit_candidate_window_density(
        settings,
        candidate_ids=["AF-CAND-0414", "AF-CAND-0416", "AF-CAND-0418"],
        reference_candidate_id="AF-CAND-0414",
    )

    assert report.report_path.exists()
    assert report.reference_candidate_id == "AF-CAND-0414"
    assert report.weakest_window == 2
    assert report.decision == "adjust_discovery_model"
    assert report.recommended_hours_utc == []
    assert report.recommended_phases == []
    assert report.aggregate_phase_records
    assert report.weakest_window_phase_records
