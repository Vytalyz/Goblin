"""P06 targeted tests — incident severity, SLA validation, and blocking logic."""

from __future__ import annotations

import json

import pytest

from agentic_forex.goblin.controls import (
    close_incident_record,
    list_open_blocking_incidents,
    open_incident_record,
    validate_incident_closure,
)
from agentic_forex.goblin.models import (
    IncidentClosurePacket,
    IncidentRecord,
)

# ---------------------------------------------------------------------------
# Model field presence
# ---------------------------------------------------------------------------


def test_incident_record_has_severity_and_sla_class():
    """IncidentRecord carries severity and sla_class with correct defaults."""
    record = IncidentRecord(
        incident_id="test-001",
        candidate_id="AF-CAND-0001",
        title="test incident",
    )
    assert record.severity == "S3"
    assert record.sla_class == "before_next_promotion_gate"
    assert record.incident_type is None
    assert record.ladder_state_at_incident is None
    assert record.deployed_bundle_id is None


def test_incident_record_accepts_all_severity_levels():
    """All four severity levels are valid on IncidentRecord."""
    for sev in ("S1", "S2", "S3", "S4"):
        r = IncidentRecord(incident_id="x", candidate_id="c", title="t", severity=sev)
        assert r.severity == sev


# ---------------------------------------------------------------------------
# open_incident_record — severity stored and persisted
# ---------------------------------------------------------------------------


def test_open_incident_stores_severity(settings):
    """open_incident_record persists severity and incident_type to disk."""
    record = open_incident_record(
        settings,
        candidate_id="AF-CAND-0263",
        title="broker_pnl_mismatch detected",
        severity="S2",
        sla_class="before_next_attach",
        incident_type="broker_pnl_mismatch",
        deployed_bundle_id="bundle-001",
    )
    assert record.severity == "S2"
    assert record.sla_class == "before_next_attach"
    assert record.incident_type == "broker_pnl_mismatch"
    assert record.deployed_bundle_id == "bundle-001"

    on_disk = json.loads(record.report_path.read_text(encoding="utf-8"))
    assert on_disk["severity"] == "S2"
    assert on_disk["incident_type"] == "broker_pnl_mismatch"


def test_open_incident_defaults_to_s3(settings):
    """open_incident_record defaults to S3 when severity is not supplied."""
    record = open_incident_record(
        settings,
        candidate_id="AF-CAND-0263",
        title="stale heartbeat observed",
    )
    assert record.severity == "S3"
    assert record.sla_class == "before_next_promotion_gate"


def test_open_incident_stores_ladder_state(settings):
    """ladder_state_at_incident is stored on the record when provided."""
    record = open_incident_record(
        settings,
        candidate_id="AF-CAND-0263",
        title="release_integrity_failure",
        severity="S1",
        sla_class="before_next_attach",
        incident_type="release_integrity_failure",
        ladder_state_at_incident="limited_demo",
    )
    assert record.ladder_state_at_incident == "limited_demo"
    on_disk = json.loads(record.report_path.read_text(encoding="utf-8"))
    assert on_disk["ladder_state_at_incident"] == "limited_demo"


# ---------------------------------------------------------------------------
# validate_incident_closure — per-severity field requirements
# ---------------------------------------------------------------------------


def test_validate_closure_s1_requires_all_fields():
    """validate_incident_closure returns missing fields for an empty S1 packet."""
    packet = IncidentClosurePacket(incident_id="x", resolution_summary="resolved")
    missing = validate_incident_closure("S1", packet)
    assert "root_cause_classification" in missing
    assert "root_cause_description" in missing
    assert "corrective_action" in missing
    assert "verification_evidence_path" in missing
    assert "deployed_bundle_id" in missing
    assert "approved_by" in missing


def test_validate_closure_s1_passes_with_all_fields():
    """validate_incident_closure returns empty list when all S1 fields are present."""
    packet = IncidentClosurePacket(
        incident_id="x",
        resolution_summary="resolved",
        root_cause_classification="broker_pnl_mismatch",
        root_cause_description="Cash delta exceeded 5x average trade profit.",
        corrective_action="Corrected lot sizing and reconciled broker CSV.",
        verification_evidence_path="Goblin/reports/broker_account_history/AF-CAND-0263/reconciliation.json",
        deployed_bundle_id="bundle-001",
        approved_by="operator",
    )
    missing = validate_incident_closure("S1", packet)
    assert missing == []


def test_validate_closure_s2_requires_corrective_or_monitoring():
    """validate_incident_closure flags when neither corrective_action nor monitoring_plan is set."""
    packet = IncidentClosurePacket(
        incident_id="x",
        resolution_summary="r",
        root_cause_classification="stale_heartbeat",
        root_cause_description="Heartbeat gap detected.",
        deployed_bundle_id="bundle-002",
        approved_by="operator",
        # corrective_action and monitoring_plan both absent
    )
    missing = validate_incident_closure("S2", packet)
    assert "corrective_action_or_monitoring_plan" in missing


def test_validate_closure_s2_passes_with_monitoring_plan():
    """monitoring_plan alone satisfies the S2 corrective/monitoring requirement."""
    packet = IncidentClosurePacket(
        incident_id="x",
        resolution_summary="r",
        root_cause_classification="stale_heartbeat",
        root_cause_description="Heartbeat gap detected.",
        monitoring_plan="Watch for recurrence over next 5 sessions.",
        deployed_bundle_id="bundle-002",
        approved_by="operator",
    )
    missing = validate_incident_closure("S2", packet)
    assert missing == []


def test_validate_closure_s3_requires_root_cause_note():
    """validate_incident_closure returns root_cause_note for a bare S3 packet."""
    packet = IncidentClosurePacket(incident_id="x", resolution_summary="r")
    missing = validate_incident_closure("S3", packet)
    assert "root_cause_note" in missing


def test_validate_closure_s3_passes_with_note():
    packet = IncidentClosurePacket(
        incident_id="x",
        resolution_summary="r",
        root_cause_note="Swap detected on intraday position held past cut-off.",
    )
    assert validate_incident_closure("S3", packet) == []


def test_validate_closure_s4_requires_nothing():
    """S4 incidents need no formal closure evidence."""
    packet = IncidentClosurePacket(incident_id="x", resolution_summary="r")
    assert validate_incident_closure("S4", packet) == []


# ---------------------------------------------------------------------------
# close_incident_record — enforcement in context
# ---------------------------------------------------------------------------


def test_close_incident_enforces_s1_fields(settings):
    """close_incident_record raises ValueError when S1 closure packet is incomplete."""
    record = open_incident_record(
        settings,
        candidate_id="AF-CAND-0263",
        title="account_identity_change",
        severity="S1",
        incident_type="account_identity_change",
    )
    with pytest.raises(ValueError, match="missing required fields"):
        close_incident_record(
            settings,
            candidate_id="AF-CAND-0263",
            incident_id=record.incident_id,
            resolution_summary="resolved",
            # No root_cause_classification etc. — should fail
        )


def test_close_incident_s3_succeeds_with_minimal_packet(settings):
    """close_incident_record for an S3 incident accepts a root_cause_note."""
    record = open_incident_record(
        settings,
        candidate_id="AF-CAND-0263",
        title="unexpected_swap_in_audit",
        severity="S3",
        incident_type="unexpected_swap_in_audit",
    )
    closure = close_incident_record(
        settings,
        candidate_id="AF-CAND-0263",
        incident_id=record.incident_id,
        resolution_summary="Swap was expected; position held intentionally.",
        root_cause_note="Position held past cut-off by design for this session.",
    )
    assert closure.incident_id == record.incident_id
    assert closure.root_cause_note == "Position held past cut-off by design for this session."


# ---------------------------------------------------------------------------
# list_open_blocking_incidents — S1/S2 blocking, S3/closed excluded
# ---------------------------------------------------------------------------


def test_list_open_blocking_incidents_returns_s1_and_s2(settings):
    """S1 and S2 open incidents are returned; S3 and closed are not."""
    open_incident_record(
        settings,
        candidate_id="AF-CAND-0263",
        title="release_integrity_failure",
        severity="S1",
        incident_type="release_integrity_failure",
    )
    open_incident_record(
        settings,
        candidate_id="AF-CAND-0263",
        title="broker_pnl_mismatch",
        severity="S2",
        incident_type="broker_pnl_mismatch",
    )
    open_incident_record(
        settings,
        candidate_id="AF-CAND-0263",
        title="stale_heartbeat",
        severity="S3",
        incident_type="stale_heartbeat",
    )
    blocking = list_open_blocking_incidents(settings, candidate_id="AF-CAND-0263")
    severities = {r.severity for r in blocking}
    assert "S1" in severities
    assert "S2" in severities
    assert "S3" not in severities


def test_list_open_blocking_incidents_excludes_closed(settings):
    """A closed S2 incident is not returned as blocking."""
    record = open_incident_record(
        settings,
        candidate_id="AF-CAND-0263",
        title="ea_audit_write_failure",
        severity="S2",
        incident_type="ea_audit_write_failure",
        deployed_bundle_id="bundle-003",
    )
    close_incident_record(
        settings,
        candidate_id="AF-CAND-0263",
        incident_id=record.incident_id,
        resolution_summary="Evidence file repaired.",
        root_cause_classification="ea_audit_write_failure",
        root_cause_description="EA failed to write audit on session start.",
        corrective_action="Repaired EA audit write path.",
        deployed_bundle_id="bundle-003",
        approved_by="operator",
    )
    blocking = list_open_blocking_incidents(settings, candidate_id="AF-CAND-0263")
    assert all(b.incident_id != record.incident_id for b in blocking)


def test_list_open_blocking_incidents_empty_when_no_incidents(settings):
    """Returns empty list for a candidate with no incident files."""
    blocking = list_open_blocking_incidents(settings, candidate_id="AF-CAND-UNKNOWN")
    assert blocking == []
