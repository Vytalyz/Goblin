"""P07 targeted tests — deployment ladder, bundle validation, and attach enforcement."""

from __future__ import annotations

import json

from agentic_forex.goblin.controls import (
    list_open_blocking_incidents,
    validate_attach_against_bundle,
    write_live_attach_manifest,
)
from agentic_forex.goblin.models import (
    DeploymentBundle,
    IncidentClosurePacket,
    LiveAttachManifest,
)

# ---------------------------------------------------------------------------
# Model field presence
# ---------------------------------------------------------------------------


def test_live_attach_manifest_carries_ladder_state():
    """LiveAttachManifest accepts ladder_state, broker_server, and bundle_id fields."""
    manifest = LiveAttachManifest(
        candidate_id="AF-CAND-0263",
        run_id="live-run-001",
        chart_symbol="EURUSD",
        timeframe="M1",
        ladder_state="observed_demo",
        broker_server="demo.broker.com",
        bundle_id="bundle-001",
    )
    assert manifest.ladder_state == "observed_demo"
    assert manifest.broker_server == "demo.broker.com"
    assert manifest.bundle_id == "bundle-001"


def test_incident_closure_packet_carries_bundle_and_ladder_fields():
    """IncidentClosurePacket carries deployed_bundle_id and ladder_state_at_incident."""
    packet = IncidentClosurePacket(
        incident_id="test-001",
        resolution_summary="resolved",
        deployed_bundle_id="bundle-042",
        ladder_state_at_incident="limited_demo",
    )
    assert packet.deployed_bundle_id == "bundle-042"
    assert packet.ladder_state_at_incident == "limited_demo"


def test_live_attach_manifest_ladder_state_persisted(settings):
    """ladder_state is written to disk in the live attach manifest JSON."""
    report_dir = settings.paths().reports_dir / "AF-CAND-0263"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "strategy_spec.json").write_text(
        json.dumps({"candidate_id": "AF-CAND-0263", "family": "overlap_resolution_bridge_research"}),
        encoding="utf-8",
    )
    from agentic_forex.governance.trial_ledger import append_trial_entry

    append_trial_entry(
        settings, candidate_id="AF-CAND-0263", family="overlap_resolution_bridge_research", stage="backtested"
    )
    manifest = write_live_attach_manifest(
        settings,
        manifest=LiveAttachManifest(
            candidate_id="AF-CAND-0263",
            run_id="live-run-ladder-001",
            chart_symbol="EURUSD",
            timeframe="M1",
            ladder_state="limited_demo",
            bundle_id="bundle-001",
        ),
    )
    on_disk = json.loads(manifest.report_path.read_text(encoding="utf-8"))
    assert on_disk["ladder_state"] == "limited_demo"
    assert on_disk["bundle_id"] == "bundle-001"


# ---------------------------------------------------------------------------
# validate_attach_against_bundle — hash checks
# ---------------------------------------------------------------------------


def test_validate_attach_against_bundle_passes_when_hashes_match(settings):
    """No violations when inputs_hash matches between manifest and bundle."""
    bundle = DeploymentBundle(
        candidate_id="AF-CAND-0263",
        bundle_id="bundle-001",
        inputs_hash="hash-abc",
    )
    manifest = LiveAttachManifest(
        candidate_id="AF-CAND-0263",
        run_id="live-run-001",
        chart_symbol="EURUSD",
        timeframe="M1",
        inputs_hash="hash-abc",
        bundle_id="bundle-001",
        ladder_state="limited_demo",
    )
    violations = validate_attach_against_bundle(settings, manifest=manifest, bundle=bundle)
    assert violations == []


def test_validate_attach_against_bundle_no_hash_in_bundle_passes(settings):
    """When the bundle carries no hashes, no violation is raised."""
    bundle = DeploymentBundle(
        candidate_id="AF-CAND-0263",
        bundle_id="bundle-no-hashes",
    )
    manifest = LiveAttachManifest(
        candidate_id="AF-CAND-0263",
        run_id="live-run-001",
        chart_symbol="EURUSD",
        timeframe="M1",
        inputs_hash="hash-abc",
        bundle_id="bundle-no-hashes",
        ladder_state="shadow_only",
    )
    violations = validate_attach_against_bundle(settings, manifest=manifest, bundle=bundle)
    assert violations == []


def test_validate_attach_against_bundle_opens_s1_on_inputs_hash_mismatch(settings):
    """inputs_hash mismatch returns a violation and opens a release_integrity_failure S1 incident."""
    bundle = DeploymentBundle(
        candidate_id="AF-CAND-0263",
        bundle_id="bundle-001",
        ea_build_hash="ea-hash-xyz",
        inputs_hash="inputs-hash-ORIGINAL",
    )
    manifest = LiveAttachManifest(
        candidate_id="AF-CAND-0263",
        run_id="live-run-mismatch",
        chart_symbol="EURUSD",
        timeframe="M1",
        inputs_hash="inputs-hash-DIFFERENT",
        bundle_id="bundle-001",
        ladder_state="limited_demo",
    )
    violations = validate_attach_against_bundle(settings, manifest=manifest, bundle=bundle)
    assert len(violations) == 1
    assert "inputs_hash mismatch" in violations[0]

    # S1 release_integrity_failure incident must have been opened
    blocking = list_open_blocking_incidents(settings, candidate_id="AF-CAND-0263")
    rif_incidents = [r for r in blocking if r.incident_type == "release_integrity_failure"]
    assert len(rif_incidents) == 1
    assert rif_incidents[0].severity == "S1"
    assert rif_incidents[0].deployed_bundle_id == "bundle-001"
    assert rif_incidents[0].ladder_state_at_incident == "limited_demo"


def test_validate_attach_against_bundle_matching_hashes_no_incident(settings):
    """Matching hashes produce no incident."""
    bundle = DeploymentBundle(
        candidate_id="AF-CAND-0264",
        bundle_id="bundle-002",
        ea_build_hash="ea-hash",
        inputs_hash="inputs-hash-SAME",
    )
    manifest = LiveAttachManifest(
        candidate_id="AF-CAND-0264",
        run_id="live-run-clean",
        chart_symbol="GBPUSD",
        timeframe="M5",
        inputs_hash="inputs-hash-SAME",
        bundle_id="bundle-002",
        ladder_state="observed_demo",
    )
    violations = validate_attach_against_bundle(settings, manifest=manifest, bundle=bundle)
    assert violations == []
    blocking = list_open_blocking_incidents(settings, candidate_id="AF-CAND-0264")
    assert blocking == []
