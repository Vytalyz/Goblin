from __future__ import annotations

from conftest import create_corpus_mirror

from agentic_forex.corpus.catalog import catalog_corpus
from agentic_forex.llm import MockLLMClient
from agentic_forex.nodes import build_tool_registry
from agentic_forex.runtime import ReadPolicy, WorkflowEngine
from agentic_forex.workflows import WorkflowRepository
from agentic_forex.workflows.contracts import CandidateDraft, DiscoveryRequest


def test_discovery_workflow_routes_scalping_and_writes_trace(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    policy = ReadPolicy(project_root=settings.project_root, allowed_external_roots=[mirror])
    catalog_corpus(mirror, settings, policy)
    engine = WorkflowEngine(
        settings=settings,
        llm_client=MockLLMClient(),
        tool_registry=build_tool_registry(),
        read_policy=policy,
    )
    workflow = WorkflowRepository(settings.paths()).load(settings.workflows.discovery_workflow_id)

    trace = engine.run(
        workflow,
        DiscoveryRequest(
            question="Build a scalping strategy for EUR/USD",
            family_hint="scalping",
            mirror_path=mirror,
            max_sources=2,
        ).model_dump(mode="json"),
    )

    candidate = CandidateDraft.model_validate(trace.output_payload)
    route_targets = [item.route_target for item in trace.node_traces if item.node_kind.value == "router"]

    assert candidate.family == "scalping"
    assert route_targets == ["scalping_analyst"]
    assert "quant_reviewed" in candidate.quality_flags
    assert "risk_reviewed" in candidate.quality_flags
    assert "execution_reviewed" in candidate.quality_flags
    assert candidate.market_context.session_focus == "europe_open_breakout"
    assert candidate.market_context.allowed_hours_utc == [7, 8, 9, 10, 11, 12]
    assert candidate.entry_style == "session_breakout"
    assert (settings.paths().reports_dir / candidate.candidate_id / "candidate.json").exists()
    assert (settings.paths().traces_dir / trace.trace_id / "trace.json").exists()
    assert (settings.paths().traces_dir / trace.trace_id / "trace.md").exists()


def test_discovery_workflow_routes_day_trading(settings, tmp_path):
    mirror = create_corpus_mirror(tmp_path)
    policy = ReadPolicy(project_root=settings.project_root, allowed_external_roots=[mirror])
    catalog_corpus(mirror, settings, policy)
    engine = WorkflowEngine(
        settings=settings,
        llm_client=MockLLMClient(),
        tool_registry=build_tool_registry(),
        read_policy=policy,
    )
    workflow = WorkflowRepository(settings.paths()).load(settings.workflows.discovery_workflow_id)

    trace = engine.run(
        workflow,
        DiscoveryRequest(
            question="Build a day trading strategy for EUR/USD",
            family_hint="day_trading",
            mirror_path=mirror,
            max_sources=2,
        ).model_dump(mode="json"),
    )

    candidate = CandidateDraft.model_validate(trace.output_payload)
    route_targets = [item.route_target for item in trace.node_traces if item.node_kind.value == "router"]

    assert candidate.family == "day_trading"
    assert route_targets == ["day_trading_analyst"]
    assert candidate.strategy_hypothesis
    assert candidate.contradiction_summary
