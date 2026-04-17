from __future__ import annotations

import json

import pytest

from agentic_forex.goblin.controls import (
    append_knowledge_event,
    assert_agent_action_allowed,
    build_retrieval_index,
    retrieve_with_provenance,
    write_bounded_agent_role,
    write_retrieval_document,
)
from agentic_forex.goblin.models import BoundedAgentRole, KnowledgeEventRecord, RetrievalDocument


def test_append_knowledge_event_writes_jsonl(settings):
    event_path = append_knowledge_event(
        settings,
        event=KnowledgeEventRecord(
            event_id="evt-1",
            event_type="lineage_link",
            subject_type="candidate",
            subject_id="AF-CAND-0263",
            artifact_refs=["artifact-1"],
            metadata={"reason": "phase12"},
        ),
    )

    assert event_path.exists()
    rows = event_path.read_text(encoding="utf-8").strip().splitlines()
    assert rows
    payload = json.loads(rows[-1])
    assert payload["event_id"] == "evt-1"
    assert payload["subject_id"] == "AF-CAND-0263"


def test_retrieve_with_provenance_cites_sources(settings):
    write_retrieval_document(
        settings,
        document=RetrievalDocument(
            document_id="doc-1",
            source_type="runtime_summary",
            source_hash="hash-1",
            candidate_id="AF-CAND-0263",
        ),
        content="runtime summary anomaly spread spike governance incident",
    )
    build_retrieval_index(settings)

    response = retrieve_with_provenance(settings, query_text="spread anomaly governance", top_k=3)

    assert response.report_path is not None
    assert response.report_path.exists()
    assert response.citations
    assert response.citations[0].document_id == "doc-1"
    assert response.citations[0].source_hash == "hash-1"


def test_write_bounded_agent_role_blocks_forbidden_governance_actions(settings):
    with pytest.raises(ValueError, match="bounded_agent_role_includes_forbidden_actions"):
        write_bounded_agent_role(
            settings,
            role=BoundedAgentRole(
                role_id="reviewer",
                description="review role",
                allowed_actions=["retrieve", "approve"],
            ),
        )


def test_assert_agent_action_allowed_enforces_role_boundaries(settings):
    write_bounded_agent_role(
        settings,
        role=BoundedAgentRole(
            role_id="reviewer",
            description="review role",
            allowed_actions=["retrieve", "summarize", "write_note"],
        ),
    )

    role = assert_agent_action_allowed(settings, role_id="reviewer", action="retrieve")
    assert role.role_id == "reviewer"

    with pytest.raises(ValueError, match="agent_role_action_not_allowed"):
        assert_agent_action_allowed(settings, role_id="reviewer", action="deploy")
