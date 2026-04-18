from __future__ import annotations

from agentic_forex.llm import MockLLMClient
from agentic_forex.runtime import ReadPolicy, WorkflowEngine
from agentic_forex.runtime.models import NodeKind, NodeSpec, WorkflowDefinition


def passthrough_tool(*, payload, settings, config, read_policy):
    return payload


def test_node_schema_validation_writes_trace_error(settings):
    workflow = WorkflowDefinition(
        workflow_id="schema_validation_test",
        version="1.0.0",
        start_node="needs_candidate",
        input_schema="DiscoveryRequest",
        output_schema="CandidateDraft",
        nodes=[
            NodeSpec(
                id="needs_candidate",
                kind=NodeKind.TOOL,
                name="Needs Candidate",
                input_schema="CandidateDraft",
                output_schema="CandidateDraft",
                config={"tool_name": "passthrough"},
            )
        ],
        edges=[],
    )
    engine = WorkflowEngine(
        settings=settings,
        llm_client=MockLLMClient(),
        tool_registry={"passthrough": passthrough_tool},
        read_policy=ReadPolicy(project_root=settings.project_root),
    )

    trace = engine.run(
        workflow,
        {
            "question": "Test request",
            "family_hint": "scalping",
            "mirror_path": str(settings.project_root),
            "max_sources": 2,
        },
    )

    assert trace.output_payload is None
    assert len(trace.node_traces) == 1
    assert trace.node_traces[0].error is not None
    assert "candidate_id" in trace.node_traces[0].error
    assert (settings.paths().traces_dir / trace.trace_id / "trace.json").exists()
    assert (settings.paths().traces_dir / trace.trace_id / "trace.md").exists()
