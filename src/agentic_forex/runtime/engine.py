from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime

from agentic_forex.config import Settings
from agentic_forex.llm.base import BaseLLMClient
from agentic_forex.runtime.models import EdgeSpec, NodeKind, NodeTrace, WorkflowDefinition, WorkflowTrace
from agentic_forex.runtime.schemas import schema_model, validate_named
from agentic_forex.runtime.security import ReadPolicy


class WorkflowEngine:
    def __init__(
        self,
        *,
        settings: Settings,
        llm_client: BaseLLMClient,
        tool_registry: dict[str, object],
        read_policy: ReadPolicy,
    ) -> None:
        self.settings = settings
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.read_policy = read_policy

    def run(self, workflow: WorkflowDefinition, payload: dict) -> WorkflowTrace:
        current_payload = validate_named(workflow.input_schema, payload).model_dump(mode="json")
        node_map = {node.id: node for node in workflow.nodes}
        trace = WorkflowTrace(
            workflow_id=workflow.workflow_id,
            workflow_version=workflow.version,
            trace_id=f"trace-{uuid.uuid4().hex[:12]}",
        )
        current_node_id = workflow.start_node
        while True:
            node = node_map[current_node_id]
            input_snapshot = dict(current_payload)
            started_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            started = time.perf_counter()
            output_payload: dict | None = None
            route_target: str | None = None
            error: str | None = None
            try:
                validated_input = validate_named(node.input_schema, current_payload).model_dump(mode="json")
                input_snapshot = dict(validated_input)
                if node.kind == NodeKind.AGENT:
                    output_payload = self._run_agent(node.config, validated_input, node.output_schema)
                elif node.kind == NodeKind.TOOL:
                    output_payload = self._run_tool(node.config, validated_input, node.output_schema)
                elif node.kind == NodeKind.ROUTER:
                    route = self._run_router(node.config, validated_input)
                    route_target = route["next_node"]
                    output_payload = route["payload"]
                elif node.kind == NodeKind.FINALIZE:
                    output_payload = self._run_finalize(node.config, validated_input, node.output_schema)
                else:  # pragma: no cover
                    raise ValueError(f"Unsupported node kind: {node.kind}")
                output_payload = validate_named(node.output_schema, output_payload).model_dump(mode="json")
                next_node = self._resolve_next_node(workflow.edges, node.id, route_target, output_payload)
                current_payload = output_payload
            except Exception as exc:  # noqa: BLE001
                error = str(exc)
                next_node = None
            trace.node_traces.append(
                NodeTrace(
                    node_id=node.id,
                    node_name=node.name,
                    node_kind=node.kind,
                    started_utc=started_utc,
                    ended_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    duration_ms=round((time.perf_counter() - started) * 1000, 3),
                    input_payload=input_snapshot,
                    output_payload=output_payload,
                    route_target=route_target,
                    citations=list(output_payload.get("source_citations") or output_payload.get("citations") or [])
                    if output_payload
                    else [],
                    error=error,
                )
            )
            if error:
                break
            if next_node is None:
                trace.output_payload = validate_named(workflow.output_schema, current_payload).model_dump(mode="json")
                break
            current_node_id = next_node
        trace.ended_utc = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        self._write_trace(trace)
        return trace

    def _run_agent(self, config: dict, payload: dict, output_schema: str) -> dict:
        prompt_root = self.settings.paths().prompts_dir
        system_prompt = self.read_policy.read_text(prompt_root / config["system_prompt"])
        role_prompt = ""
        if config.get("role_brief"):
            role_prompt = self.read_policy.read_text(self.settings.paths().roles_dir / config["role_brief"]).strip()
        skill_prompt = ""
        if config.get("skill_guide"):
            skill_prompt = self.read_policy.read_text(self.settings.paths().skills_dir / config["skill_guide"]).strip()
        user_prompt_template = self.read_policy.read_text(prompt_root / config["user_prompt"])
        user_prompt = user_prompt_template.replace("{{payload}}", json.dumps(payload, indent=2, default=str))
        result = self.llm_client.generate_structured(
            task_name=config["task_name"],
            system_prompt="\n\n".join(chunk for chunk in (role_prompt, skill_prompt, system_prompt) if chunk),
            user_prompt=user_prompt,
            schema_model=schema_model(output_schema),
            payload=payload,
        )
        return result.model_dump(mode="json")

    def _run_tool(self, config: dict, payload: dict, output_schema: str) -> dict:
        tool = self.tool_registry[config["tool_name"]]
        result = tool(payload=payload, settings=self.settings, config=config, read_policy=self.read_policy)
        return validate_named(output_schema, result).model_dump(mode="json")

    def _run_router(self, config: dict, payload: dict) -> dict:
        tool = self.tool_registry[config["tool_name"]]
        result = tool(payload=payload, settings=self.settings, config=config, read_policy=self.read_policy)
        return validate_named("RouteDecision", result).model_dump(mode="json")

    def _run_finalize(self, config: dict, payload: dict, output_schema: str) -> dict:
        tool = self.tool_registry[config["tool_name"]]
        result = tool(payload=payload, settings=self.settings, config=config, read_policy=self.read_policy)
        return validate_named(output_schema, result).model_dump(mode="json")

    def _resolve_next_node(self, edges: list[EdgeSpec], source: str, route_target: str | None, payload: dict) -> str | None:
        outgoing = [edge for edge in edges if edge.source == source]
        if not outgoing:
            return None
        if route_target:
            edge = next(edge for edge in outgoing if edge.target == route_target)
            validate_named(edge.contract, payload)
            return edge.target
        if len(outgoing) != 1:
            raise ValueError(f"Node {source} requires an explicit route.")
        validate_named(outgoing[0].contract, payload)
        return outgoing[0].target

    def _write_trace(self, trace: WorkflowTrace) -> None:
        trace_dir = self.settings.paths().traces_dir / trace.trace_id
        trace_dir.mkdir(parents=True, exist_ok=True)
        (trace_dir / "trace.json").write_text(trace.model_dump_json(indent=2), encoding="utf-8")
        markdown = [f"# Workflow Trace: {trace.workflow_id}", ""]
        for item in trace.node_traces:
            markdown.extend(
                [
                    f"## {item.node_name} ({item.node_kind.value})",
                    f"- Node ID: {item.node_id}",
                    f"- Duration ms: {item.duration_ms}",
                    f"- Route target: {item.route_target or 'n/a'}",
                    f"- Error: {item.error or 'none'}",
                    "",
                    "```json",
                    json.dumps(item.output_payload or {}, indent=2, default=str),
                    "```",
                    "",
                ]
            )
        (trace_dir / "trace.md").write_text("\n".join(markdown), encoding="utf-8")
