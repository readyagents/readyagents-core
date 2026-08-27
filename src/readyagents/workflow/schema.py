"""Pydantic models for YAML/JSON workflow definitions."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from readyagents.errors import WorkflowError


class NodeType(StrEnum):
    agent = "agent"
    tool = "tool"
    condition = "condition"
    transform = "transform"
    approval = "approval"
    parallel = "parallel"
    include = "include"


class RetrySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=1, ge=1, le=20)
    backoff_seconds: float = Field(default=1.0, ge=0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0)


class BudgetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_tokens: int | None = Field(default=None, ge=0)
    max_cost_usd: float | None = Field(default=None, ge=0)


class CircuitSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure_threshold: int = Field(default=3, ge=1)
    cooldown_seconds: float = Field(default=60.0, ge=0)


class MCPServerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None


class NodeSpec(BaseModel):
    """One node in the workflow graph."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(min_length=1)
    type: str
    timeout_seconds: float | None = Field(default=None, gt=0)
    retry: RetrySpec | None = None
    next: str | None = None
    output_key: str | None = None
    description: str | None = None

    # agent
    prompt: str | None = None
    system: str | None = None
    model: str | None = None

    # tool
    tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)

    # condition
    when: str | None = None
    then: str | None = None
    else_: str | None = Field(default=None, alias="else")

    # transform
    template: str | None = None
    source: str | None = None
    json_path: str | None = None
    parse_json: bool = False

    # parallel
    branches: list[NodeSpec] = Field(default_factory=list)

    # include (sub-workflow)
    path: str | None = None
    call_inputs: dict[str, Any] = Field(default_factory=dict, alias="inputs")

    # agent extras
    fallback_models: list[str] = Field(default_factory=list)
    output_schema: dict[str, Any] | None = None
    cache: bool | None = None
    tools: list[str] = Field(default_factory=list)
    max_tool_rounds: int | None = Field(default=None, ge=1, le=20)

    @field_validator("id")
    @classmethod
    def _id_token(cls, value: str) -> str:
        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"Invalid node id '{value}' (use letters, numbers, _ or -)")
        return value

    @field_validator("type")
    @classmethod
    def _type_token(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not cleaned.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"Invalid node type '{value}'")
        return cleaned

    @field_validator("tools")
    @classmethod
    def _tools_tokens(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in value:
            name = str(raw).strip()
            if not name:
                raise ValueError("tool names must be non-empty")
            token = name.replace("_", "").replace("-", "").replace(".", "")
            if not token.isalnum():
                raise ValueError(f"Invalid tool name '{name}' (use letters, numbers, _, -, .)")
            if name in seen:
                raise ValueError(f"Duplicate tool name '{name}'")
            seen.add(name)
            cleaned.append(name)
        return cleaned

    @model_validator(mode="after")
    def _type_fields(self) -> NodeSpec:
        t = self.type
        if t != NodeType.agent.value and self.tools:
            raise ValueError(f"Node '{self.id}': 'tools' is only valid on agent nodes")
        if t == NodeType.agent.value and not self.prompt:
            raise ValueError(f"Node '{self.id}': agent nodes require 'prompt'")
        if t == NodeType.tool.value and not self.tool:
            raise ValueError(f"Node '{self.id}': tool nodes require 'tool'")
        if t == NodeType.condition.value:
            if not self.when:
                raise ValueError(f"Node '{self.id}': condition nodes require 'when'")
            if not self.then and not self.else_:
                raise ValueError(f"Node '{self.id}': condition nodes require 'then' and/or 'else'")
        if t == NodeType.transform.value:
            if self.template is None and not self.json_path and not self.parse_json:
                raise ValueError(
                    f"Node '{self.id}': transform nodes require "
                    "'template', 'json_path', or parse_json"
                )
        if t == NodeType.approval.value:
            if not self.prompt:
                raise ValueError(f"Node '{self.id}': approval nodes require 'prompt'")
            if not self.then and not self.else_ and not self.next:
                raise ValueError(
                    f"Node '{self.id}': approval nodes require 'then', 'else', or 'next'"
                )
        if t == NodeType.parallel.value and not self.branches:
            raise ValueError(f"Node '{self.id}': parallel nodes require 'branches'")
        if t == NodeType.include.value and not self.path:
            raise ValueError(f"Node '{self.id}': include nodes require 'path'")
        return self


class EdgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    when: str | None = None


class WorkflowSpec(BaseModel):
    """A validated workflow document."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str
    version: str = "1"
    description: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    required_inputs: list[str] = Field(default_factory=list)
    start: str | None = None
    nodes: list[NodeSpec]
    edges: list[EdgeSpec] = Field(default_factory=list)
    mcp_servers: dict[str, MCPServerSpec] = Field(default_factory=dict)
    allow_http: bool = False
    workspace: str | None = None
    default_model: str | None = None
    budget: BudgetSpec | None = None
    fallback_models: list[str] = Field(default_factory=list)
    circuit: CircuitSpec | None = None
    on_pause_url: str | None = None
    cache_llm: bool | None = None
    redact: bool | None = None

    @model_validator(mode="after")
    def _graph(self) -> WorkflowSpec:
        if not self.nodes:
            raise ValueError("Workflow must declare at least one node")
        ids = [n.id for n in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate node ids")
        known = set(ids)
        start = self.start or self.nodes[0].id
        if start not in known:
            raise ValueError(f"start node '{start}' does not exist")
        self.start = start
        for node in self.nodes:
            for ref in (node.next, node.then, node.else_):
                if ref is not None and ref not in known:
                    raise ValueError(f"Node '{node.id}' references unknown node '{ref}'")
            if node.branches:
                branch_ids = [b.id for b in node.branches]
                if len(branch_ids) != len(set(branch_ids)):
                    raise ValueError(f"Node '{node.id}': duplicate parallel branch ids")
        for edge in self.edges:
            if edge.from_ not in known:
                raise ValueError(f"Edge from unknown node '{edge.from_}'")
            if edge.to not in known:
                raise ValueError(f"Edge to unknown node '{edge.to}'")
        self._assert_acyclic()
        return self

    def _assert_acyclic(self) -> None:
        graph: dict[str, list[str]] = {node.id: [] for node in self.nodes}
        for node in self.nodes:
            for ref in (node.next, node.then, node.else_):
                if ref is not None:
                    graph[node.id].append(ref)
        for edge in self.edges:
            graph[edge.from_].append(edge.to)

        visiting: set[str] = set()
        done: set[str] = set()

        def dfs(nid: str) -> None:
            visiting.add(nid)
            for nxt in graph[nid]:
                if nxt in visiting:
                    raise ValueError(f"Cycle detected at node '{nxt}'")
                if nxt not in done and nxt in graph:
                    dfs(nxt)
            visiting.remove(nid)
            done.add(nid)

        for nid in graph:
            if nid not in done:
                dfs(nid)

    def node_map(self) -> dict[str, NodeSpec]:
        return {n.id: n for n in self.nodes}

    def input_defaults(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {}
        for key, raw in self.inputs.items():
            if isinstance(raw, dict) and "default" in raw:
                defaults[key] = raw["default"]
            else:
                defaults[key] = raw
        return defaults


def validate_required_inputs(workflow: WorkflowSpec, provided: dict[str, Any]) -> None:
    missing = [name for name in workflow.required_inputs if name not in provided]
    if missing:
        example = " ".join(f"--input {name}=..." for name in missing)
        raise WorkflowError(f"Missing required inputs: {', '.join(missing)}. Pass {example}.")


NodeSpec.model_rebuild()
