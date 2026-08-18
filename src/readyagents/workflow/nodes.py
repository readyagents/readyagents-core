"""Execute individual node types."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from readyagents.errors import NodeError, TemplateError, ToolError, WorkflowError
from readyagents.llm.base import LLMProvider, Message
from readyagents.llm.registry import get_provider
from readyagents.tools import ToolRegistry
from readyagents.workflow.schema import NodeSpec, NodeType, WorkflowSpec
from readyagents.workflow.state import RunState
from readyagents.workflow.templates import interpolate, interpolate_value, lookup, resolve_path

_COMPARE = re.compile(
    r"^\s*(.+?)\s*(==|!=|>=|<=|>|<|contains|startswith|endswith)\s*(.+?)\s*$",
    re.DOTALL,
)


class ExecutionContext:
    def __init__(
        self,
        workflow: WorkflowSpec,
        tools: ToolRegistry,
        *,
        dry_run: bool = False,
        llm: LLMProvider | None = None,
        default_model: str | None = None,
        extra_handlers: Mapping[str, Any] | None = None,
    ) -> None:
        self.workflow = workflow
        self.tools = tools
        self.dry_run = dry_run
        self.llm = llm
        self.default_model = default_model or workflow.default_model
        self.extra_handlers = dict(extra_handlers or {})


def execute_node(node: NodeSpec, state: RunState, ctx: ExecutionContext) -> Any:
    kind = node.type if isinstance(node.type, str) else str(node.type)
    handler = ctx.extra_handlers.get(kind)
    if handler is not None:
        return handler.execute(node, state, ctx)

    if kind == NodeType.agent.value:
        return _run_agent(node, state, ctx)
    if kind == NodeType.tool.value:
        return _run_tool(node, state, ctx)
    if kind == NodeType.transform.value:
        return _run_transform(node, state, ctx)
    if kind == NodeType.condition.value:
        return _run_condition(node, state, ctx)
    raise WorkflowError(f"Unsupported node type: {node.type}")


def _run_agent(node: NodeSpec, state: RunState, ctx: ExecutionContext) -> str:
    ns = state.mapping()
    prompt = interpolate(node.prompt or "", ns)
    system = interpolate(node.system, ns) if node.system else None
    if ctx.dry_run:
        preview = prompt if not system else f"[system]\n{system}\n[user]\n{prompt}"
        return f"[dry-run]\n{preview}"
    model_ref = node.model or ctx.default_model
    if ctx.llm is not None:
        provider = ctx.llm
        model_id = (model_ref or "mock").split(":", 1)[-1]
        if model_ref and ":" in model_ref:
            model_id = model_ref.split(":", 1)[1]
    else:
        provider, model_id = get_provider(model_ref)
    messages: list[Message] = []
    if system:
        messages.append(Message(role="system", content=system))
    messages.append(Message(role="user", content=prompt))
    result = provider.complete(messages, model=model_id)
    return result.text


def _run_tool(node: NodeSpec, state: RunState, ctx: ExecutionContext) -> Any:
    name = node.tool or ""
    args = interpolate_value(node.arguments, state.mapping())
    if not isinstance(args, dict):
        raise NodeError(node.id, "tool arguments must be a mapping")
    if ctx.dry_run and name == "http_get":
        return f"[dry-run] http_get {args}"
    tool = ctx.tools.get(name)
    return tool.run(**args)


def _run_transform(node: NodeSpec, state: RunState, ctx: ExecutionContext) -> Any:
    ns = state.mapping()
    value: Any
    if node.template is not None:
        value = interpolate(node.template, ns)
    elif node.source:
        value = lookup(ns, node.source)
    else:
        if not state.results:
            raise TemplateError("transform has no source and no prior node output")
        value = state.node_outputs[state.results[-1].node_id]

    if node.parse_json:
        if isinstance(value, str):
            value = _parse_json_lenient(value)
    if node.json_path:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ToolError(f"transform json_path: value is not JSON: {exc}") from exc
        value = resolve_path(value, node.json_path)
    return value


def _parse_json_lenient(text: str) -> Any:
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                pass
        start = stripped.find("[")
        end = stripped.rfind("]")
        if start != -1 and end != -1 and end > start:
            return json.loads(stripped[start : end + 1])
        raise ToolError("transform parse_json: could not parse JSON from text") from None


def _run_condition(node: NodeSpec, state: RunState, ctx: ExecutionContext) -> dict[str, Any]:
    matched = evaluate_condition(node.when or "", state.mapping())
    nxt = node.then if matched else node.else_
    return {"matched": matched, "next": nxt}


def evaluate_condition(expr: str, mapping: Mapping[str, Any]) -> bool:
    """Evaluate a small comparison or a truthy interpolated value. No `eval()`."""
    expr = expr.strip()
    if not expr:
        return False
    match = _COMPARE.match(expr)
    if match:
        left_raw, op, right_raw = match.group(1), match.group(2), match.group(3)
        left = _atom(left_raw, mapping)
        right = _atom(right_raw, mapping)
        return _compare(left, op, right)
    interpolated = interpolate(expr, mapping) if "{{" in expr else expr
    try:
        value = (
            lookup(mapping, interpolated)
            if interpolated.isidentifier() or "." in interpolated
            else interpolated
        )
    except TemplateError:
        value = interpolated
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0", ""}:
            return False
    return bool(value)


def _atom(raw: str, mapping: Mapping[str, Any]) -> Any:
    text = raw.strip()
    quoted = (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    )
    if quoted:
        return interpolate(text[1:-1], mapping)
    if "{{" in text:
        return interpolate(text, mapping)
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    try:
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text)
        return float(text)
    except ValueError:
        pass
    try:
        return lookup(mapping, text)
    except TemplateError:
        return interpolate(text, mapping) if "{{" in text else text


def _compare(left: Any, op: str, right: Any) -> bool:
    if op == "==":
        return _norm(left) == _norm(right)
    if op == "!=":
        return _norm(left) != _norm(right)
    if op in {">", "<", ">=", "<="}:
        try:
            lf, rf = float(left), float(right)
        except (TypeError, ValueError):
            lf, rf = str(left), str(right)
        if op == ">":
            return lf > rf
        if op == "<":
            return lf < rf
        if op == ">=":
            return lf >= rf
        return lf <= rf
    left_s, right_s = str(left), str(right)
    if op == "contains":
        return right_s in left_s
    if op == "startswith":
        return left_s.startswith(right_s)
    if op == "endswith":
        return left_s.endswith(right_s)
    return False


def _norm(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip()
    return value
