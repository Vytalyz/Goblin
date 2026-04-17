from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class NodeKind(str, Enum):
    AGENT = "agent"
    TOOL = "tool"
    ROUTER = "router"
    FINALIZE = "finalize"


class NodeSpec(BaseModel):
    id: str
    kind: NodeKind
    name: str
    input_schema: str
    output_schema: str
    config: dict[str, Any] = Field(default_factory=dict)


class EdgeSpec(BaseModel):
    source: str
    target: str
    contract: str


class WorkflowDefinition(BaseModel):
    workflow_id: str
    version: str
    start_node: str
    input_schema: str
    output_schema: str
    nodes: list[NodeSpec]
    edges: list[EdgeSpec]


class NodeTrace(BaseModel):
    node_id: str
    node_name: str
    node_kind: NodeKind
    started_utc: str
    ended_utc: str
    duration_ms: float
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] | None = None
    route_target: str | None = None
    citations: list[str] = Field(default_factory=list)
    error: str | None = None


class WorkflowTrace(BaseModel):
    workflow_id: str
    workflow_version: str
    trace_id: str
    started_utc: str = Field(default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    ended_utc: str | None = None
    node_traces: list[NodeTrace] = Field(default_factory=list)
    output_payload: dict[str, Any] | None = None
