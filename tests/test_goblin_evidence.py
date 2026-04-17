from __future__ import annotations

from pathlib import Path

from agentic_forex.goblin import ArtifactProvenance
from agentic_forex.goblin.evidence import (
    build_default_research_data_contract,
    build_default_time_session_contract,
    build_truth_alignment_report,
    latest_registered_artifact,
    load_artifact_index,
    register_artifact,
    validate_artifact_provenance,
)


def test_register_artifact_snapshots_into_channel_root(settings):
    source = settings.project_root / "reports" / "AF-CAND-0263" / "sample_backtest.json"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('{"status": "ok"}', encoding="utf-8")

    provenance = ArtifactProvenance(
        candidate_id="AF-CAND-0263",
        run_id="run-001",
        artifact_origin="backtest_summary",
        evidence_channel="research_backtest",
        symbol="EUR_USD",
        timezone_basis="UTC",
    )
    record = register_artifact(
        settings,
        provenance=provenance,
        artifact_path=source,
        authoritative=True,
    )

    assert record.managed_path.exists()
    assert settings.paths().goblin_research_reports_dir in record.managed_path.parents
    index = load_artifact_index(settings, "research_backtest")
    assert any(item.artifact_id == record.artifact_id for item in index.artifacts)
    latest = latest_registered_artifact(settings, channel="research_backtest", candidate_id="AF-CAND-0263")
    assert latest is not None
    assert latest.artifact_id == record.artifact_id


def test_validate_artifact_provenance_rejects_cross_channel_path(settings):
    cross_channel_path = settings.paths().goblin_mt5_replay_reports_dir / "AF-CAND-0263" / "run-002" / "replay.csv"
    cross_channel_path.parent.mkdir(parents=True, exist_ok=True)
    cross_channel_path.write_text("timestamp_utc\n2026-01-01T00:00:00Z\n", encoding="utf-8")

    provenance = ArtifactProvenance(
        candidate_id="AF-CAND-0263",
        run_id="run-002",
        artifact_origin="live_runtime_audit",
        evidence_channel="live_demo",
        symbol="EUR_USD",
        timezone_basis="Europe/Prague",
        artifact_hash="abc123",
    )
    result = validate_artifact_provenance(settings, provenance=provenance, artifact_path=cross_channel_path)

    assert result.valid is False
    assert "cross_channel_artifact_path" in result.reasons
    assert result.conflicting_channel == "mt5_replay"


def test_build_default_contracts_follow_settings(settings):
    research_contract = build_default_research_data_contract(settings)
    time_contract = build_default_time_session_contract(settings)

    assert research_contract.instrument == settings.oanda.default_instrument
    assert research_contract.price_component == settings.oanda.price_component
    assert research_contract.granularity == settings.data.base_granularity
    assert time_contract.broker_timezone == settings.policy.ftmo_timezone
    assert time_contract.comparison_timezone_basis == "UTC"
    assert time_contract.overlap_definition == "london_new_york_overlap"


def test_build_truth_alignment_report_uses_registered_artifacts(settings):
    created: dict[str, object] = {}
    for channel, origin in (
        ("research_backtest", "research_summary"),
        ("mt5_replay", "mt5_report"),
        ("live_demo", "runtime_summary"),
        ("broker_account_history", "account_history"),
    ):
        source = settings.project_root / f"{channel}.json"
        source.write_text(f'{{"channel": "{channel}"}}', encoding="utf-8")
        provenance = ArtifactProvenance(
            candidate_id="AF-CAND-0263",
            run_id=f"{channel}-run",
            artifact_origin=origin,
            evidence_channel=channel,  # type: ignore[arg-type]
            symbol="EUR_USD",
            timezone_basis="UTC",
        )
        created[channel] = register_artifact(settings, provenance=provenance, artifact_path=source, authoritative=True)

    report = build_truth_alignment_report(
        settings,
        candidate_id="AF-CAND-0263",
        artifact_records=created,  # type: ignore[arg-type]
        governance_effect="validation_required",
    )

    assert report.report_path is not None
    assert Path(report.report_path).exists()
    assert len(report.required_contracts) == 3
    assert report.governance_effect == "validation_required"
    assert "research_backtest" in report.evidence_summaries
    assert "broker_account_history" in report.evidence_summaries
    assert report.comparison_time_basis == "UTC"
    assert report.time_basis_consistent is True
    assert report.time_session_contract is not None
    assert report.channel_timezones["mt5_replay"] == "UTC"


def test_build_truth_alignment_report_flags_time_basis_mismatch(settings):
    created: dict[str, object] = {}
    for channel, timezone_basis in (
        ("research_backtest", "UTC"),
        ("mt5_replay", "Europe/Prague"),
    ):
        source = settings.project_root / f"{channel}.json"
        source.write_text(f'{{"channel": "{channel}"}}', encoding="utf-8")
        provenance = ArtifactProvenance(
            candidate_id="AF-CAND-0263",
            run_id=f"{channel}-run",
            artifact_origin=f"{channel}_artifact",
            evidence_channel=channel,  # type: ignore[arg-type]
            symbol="EUR_USD",
            timezone_basis=timezone_basis,
        )
        created[channel] = register_artifact(settings, provenance=provenance, artifact_path=source, authoritative=True)

    report = build_truth_alignment_report(
        settings,
        candidate_id="AF-CAND-0263",
        artifact_records=created,  # type: ignore[arg-type]
        governance_effect="hold_for_time_basis_mismatch",
    )

    assert report.time_basis_consistent is False
    assert report.time_basis_mismatches == ["mt5_replay:Europe/Prague"]
