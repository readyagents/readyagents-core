"""Execute individual node types."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from readyagents.errors import ApprovalRequired, NodeError, TemplateError, ToolError, WorkflowError
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


_APPROVE_VALUES = {"approve", "approved", "yes", "true", "accept", "ok"}
_REJECT_VALUES = {"reject", "rejected", "deny", "denied", "no", "false"}
_MAX_INCLUDE_DEPTH = 8
_MAX_PARALLEL = 8
# Dry-run still walks the graph; these tools must not hit the network or disk.
_DRY_RUN_STUB_TOOLS = frozenset({"http_get", "write_file"})


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
        decisions: Mapping[str, str] | None = None,
        on_persist: Callable[[RunState], None] | None = None,
        workflow_dir: Path | None = None,
        include_depth: int = 0,
    ) -> None:
        self.workflow = workflow
        self.tools = tools
        self.dry_run = dry_run
        self.llm = llm
        self.default_model = default_model or workflow.default_model
        self.extra_handlers = dict(extra_handlers or {})
        self.decisions = {str(k): str(v).strip().lower() for k, v in dict(decisions or {}).items()}
        self.on_persist = on_persist
        self.workflow_dir = Path(workflow_dir) if workflow_dir else Path.cwd()
        self.include_depth = include_depth

    def decision_for(self, node_id: str) -> str | None:
        value = self.decisions.get(node_id)
        return value if value else None


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
    if kind == NodeType.approval.value:
        return _run_approval(node, state, ctx)
    if kind == NodeType.parallel.value:
        return _run_parallel(node, state, ctx)
    if kind == NodeType.include.value:
        return _run_include(node, state, ctx)
    known = ", ".join(t.value for t in NodeType)
    raise WorkflowError(
        f"Unsupported node type '{node.type}' on node '{node.id}'. "
        f"Known types: {known}. Packs may register extra types via readyagents.packs."
    )


def _run_agent(node: NodeSpec, state: RunState, ctx: ExecutionContext) -> str:
    ns = state.mapping()
    prompt = interpolate(node.prompt or "", ns)
    system = interpolate(node.system, ns) if node.system else None
    if ctx.dry_run:
        preview = prompt if not system else f"[system]\n{system}\n[user]\n{prompt}"
        estimated = _estimate_tokens(prompt, system or "")
        state.add_usage(estimated_tokens=estimated)
        return f"[dry-run]\n{preview}\n[estimated_tokens={estimated}]"
    explicit = bool(node.model)
    model_ref = node.model or ctx.default_model
    if ctx.llm is not None:
        provider = ctx.llm
        model_id = (model_ref or "mock").split(":", 1)[-1]
        if model_ref and ":" in model_ref:
            model_id = model_ref.split(":", 1)[1]
    else:
        provider, model_id = get_provider(model_ref, implicit=not explicit)
    messages: list[Message] = []
    if system:
        messages.append(Message(role="system", content=system))
    messages.append(Message(role="user", content=prompt))
    result = provider.complete(messages, model=model_id)
    if result.usage:
        state.add_usage(**result.usage)
    return result.text


def _run_tool(node: NodeSpec, state: RunState, ctx: ExecutionContext) -> Any:
    name = node.tool or ""
    args = interpolate_value(node.arguments, state.mapping())
    if not isinstance(args, dict):
        raise NodeError(node.id, "tool arguments must be a mapping")
    if ctx.dry_run and name in _DRY_RUN_STUB_TOOLS:
        return f"[dry-run] {name} {args}"
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
            if ctx.dry_run and value.lstrip().startswith("[dry-run]"):
                value = {"dry_run": True}
            else:
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


def _run_approval(node: NodeSpec, state: RunState, ctx: ExecutionContext) -> dict[str, Any]:
    ns = state.mapping()
    prompt = interpolate(node.prompt or f"Approve node '{node.id}'?", ns)
    raw = ctx.decision_for(node.id)
    if raw is None:
        raise ApprovalRequired(node.id, state.run_id, prompt, state=state)
    if raw in _APPROVE_VALUES:
        approved = True
    elif raw in _REJECT_VALUES:
        approved = False
    else:
        raise NodeError(
            node.id,
            f"unknown decision '{raw}' (use approve or reject)",
        )
    if approved:
        nxt = node.then or node.next
    else:
        nxt = node.else_
    return {
        "approved": approved,
        "decision": "approve" if approved else "reject",
        "prompt": prompt,
        "next": nxt,
    }


def _estimate_tokens(*texts: str) -> int:
    total = sum(len(t or "") for t in texts)
    return max(1, total // 4)


def _run_parallel(node: NodeSpec, state: RunState, ctx: ExecutionContext) -> dict[str, Any]:
    branches = list(node.branches or [])
    if not branches:
        raise NodeError(node.id, "parallel nodes require 'branches'")
    collected: dict[str, Any] = {}

    def _one(branch: NodeSpec) -> tuple[str, Any]:
        try:
            return branch.id, execute_node(branch, state, ctx)
        except ApprovalRequired:
            raise
        except Exception as exc:  # noqa: BLE001
            raise NodeError(
                branch.id,
                f"parallel branch '{branch.id}' failed: {exc}",
                cause=exc if isinstance(exc, BaseException) else None,
            ) from exc

    workers = max(1, min(_MAX_PARALLEL, len(branches)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, branch) for branch in branches]
        for fut in as_completed(futures):
            branch_id, output = fut.result()
            collected[branch_id] = output
    ordered = {branch.id: collected[branch.id] for branch in branches}
    return ordered


def _run_include(node: NodeSpec, state: RunState, ctx: ExecutionContext) -> Any:
    if ctx.include_depth >= _MAX_INCLUDE_DEPTH:
        raise WorkflowError(
            f"include depth exceeded ({_MAX_INCLUDE_DEPTH}). Check for cycles in sub-workflows."
        )
    raw_path = interpolate(node.path or "", state.mapping())
    if not raw_path:
        raise NodeError(node.id, "include nodes require 'path'")
    candidate = _confine_include_path(raw_path, ctx.workflow_dir, node.id)
    if not candidate.is_file():
        raise NodeError(
            node.id,
            f"included workflow not found: {candidate} "
            f"(resolved from path '{raw_path}' relative to {ctx.workflow_dir})",
        )

    from readyagents.workflow.engine import run_workflow
    from readyagents.workflow.runner import load_workflow, merge_inputs

    spec = load_workflow(candidate)
    nested_in = interpolate_value(node.call_inputs, state.mapping())
    if nested_in is None:
        nested_in = {}
    if not isinstance(nested_in, dict):
        raise NodeError(node.id, "include inputs must be a mapping")
    merged = merge_inputs(spec, nested_in)
    nested_ctx = ExecutionContext(
        spec,
        ctx.tools,
        dry_run=ctx.dry_run,
        llm=ctx.llm,
        default_model=ctx.default_model,
        extra_handlers=ctx.extra_handlers,
        decisions=ctx.decisions,
        on_persist=None,
        workflow_dir=candidate.parent,
        include_depth=ctx.include_depth + 1,
    )
    nested = run_workflow(
        spec,
        merged,
        nested_ctx,
        metadata={"source": str(candidate), "included_by": node.id},
    )
    if nested.status == "paused":
        raise ApprovalRequired(
            nested.pending_node or node.id,
            state.run_id,
            f"Nested workflow '{spec.name}' is waiting for approval.",
            state=state,
        )
    if nested.status != "succeeded":
        raise NodeError(node.id, f"included workflow '{spec.name}' {nested.status}")
    state.add_usage(**nested.usage)
    return nested.output_keys or nested.node_outputs


def _confine_include_path(raw_path: str, workflow_dir: Path, node_id: str) -> Path:
    """Resolve an include path and refuse anything outside the parent workflow dir."""
    root = Path(workflow_dir).resolve()
    text = str(raw_path).strip()
    if not text or "\x00" in text:
        raise NodeError(node_id, "include nodes require a path under the parent workflow directory")
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise NodeError(
            node_id,
            f"included workflow is outside the parent workflow directory: {raw_path} "
            f"(resolved to {resolved}, must stay under {root})",
        )
    return resolved


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
