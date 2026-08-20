"""Execute a workflow graph with retries, timeouts, and branching."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from readyagents.errors import ApprovalRequired, ReadyAgentsError, WorkflowError
from readyagents.logging import get_logger
from readyagents.workflow.nodes import (
    ExecutionContext,
    evaluate_condition,
    execute_node_with_policy,
)
from readyagents.workflow.schema import NodeSpec, NodeType, WorkflowSpec
from readyagents.workflow.state import RunState, utc_now

log = get_logger("engine")

_MAX_STEPS = 500


def run_workflow(
    workflow: WorkflowSpec,
    inputs: Mapping[str, Any],
    ctx: ExecutionContext,
    *,
    metadata: Mapping[str, Any] | None = None,
    state: RunState | None = None,
) -> RunState:
    nodes = workflow.node_map()
    if state is None:
        state = RunState.start(workflow.name, inputs, metadata=metadata)
        current = workflow.start or workflow.nodes[0].id
        seen: set[str] = set()
    else:
        current, seen = _resume_cursor(workflow, state)
        if inputs:
            state.inputs.update(dict(inputs))
        if metadata:
            state.metadata.update(dict(metadata))

    extra = {"run_id": state.run_id, "node_id": "-"}
    log.info("run %s status=%s", state.run_id, state.status, extra=extra)

    steps = 0
    try:
        while current:
            steps += 1
            if steps > _MAX_STEPS:
                raise WorkflowError(f"Workflow exceeded {_MAX_STEPS} steps (possible cycle)")
            if current in seen:
                raise WorkflowError(f"Cycle detected at node '{current}'")
            if current not in nodes:
                raise WorkflowError(f"Unknown node '{current}'")
            node = nodes[current]
            seen.add(current)
            log.info(
                "node %s (%s)",
                node.id,
                node.type,
                extra={"run_id": state.run_id, "node_id": node.id},
            )
            _execute_with_policy(node, state, ctx)
            state.pending_node = None
            _persist(ctx, state)
            current = _next_node(workflow, node, state)
        state.pending_node = None
        state.finish("succeeded")
        _persist(ctx, state)
    except ApprovalRequired as exc:
        state.pending_node = current
        state.finish("paused")
        _persist(ctx, state)
        exc.state = state
        raise
    except ReadyAgentsError as exc:
        state.pending_node = current
        state.record_error(
            current or "?",
            str(nodes[current].type) if current in nodes else "?",
            str(exc),
        )
        state.finish("failed")
        _persist(ctx, state)
        exc.state = state
        if not exc.run_id:
            exc.run_id = state.run_id
        raise
    return state


def _resume_cursor(workflow: WorkflowSpec, state: RunState) -> tuple[str | None, set[str]]:
    if state.status == "succeeded":
        raise WorkflowError(
            f"Run {state.run_id} already succeeded. "
            f"Use 'readyagents runs replay {state.run_id}' to start a new run."
        )
    completed = {r.node_id for r in state.results if r.status == "ok"}
    current = state.pending_node
    if not current:
        for result in reversed(state.results):
            if result.status == "error":
                current = result.node_id
                break
        if not current and state.results:
            last_ok = next((r for r in reversed(state.results) if r.status == "ok"), None)
            if last_ok and last_ok.node_id in workflow.node_map():
                current = _next_node(workflow, workflow.node_map()[last_ok.node_id], state)
    if current:
        state.results = [
            r for r in state.results if not (r.node_id == current and r.status == "error")
        ]
        if current not in completed:
            state.node_outputs.pop(current, None)
    state.pending_node = None
    state.status = "running"
    state.finished_at = None
    return current, completed


def _persist(ctx: ExecutionContext, state: RunState) -> None:
    if ctx.on_persist is None:
        return
    ctx.on_persist(state)


def _execute_with_policy(node: NodeSpec, state: RunState, ctx: ExecutionContext) -> None:
    started = utc_now()
    output, attempt = execute_node_with_policy(node, state, ctx)
    state.record(
        node.id,
        output,
        node_type=str(node.type),
        output_key=node.output_key,
        attempts=attempt,
        started_at=started,
        finished_at=utc_now(),
    )


def _uses_explicit_routing(workflow: WorkflowSpec) -> bool:
    if workflow.edges:
        return True
    return any(n.next or n.then or n.else_ for n in workflow.nodes)


def _next_node(workflow: WorkflowSpec, node: NodeSpec, state: RunState) -> str | None:
    if str(node.type) in {NodeType.condition.value, NodeType.approval.value}:
        output = state.node_outputs.get(node.id) or {}
        nxt = output.get("next") if isinstance(output, dict) else None
        return nxt

    edges = [e for e in workflow.edges if e.from_ == node.id]
    if edges:
        default = None
        ns = state.mapping()
        for edge in edges:
            if edge.when is None:
                default = edge.to
                continue
            if evaluate_condition(edge.when, ns):
                return edge.to
        return default

    if node.next:
        return node.next

    # List order only for purely sequential workflows (no next/edges/branches).
    if _uses_explicit_routing(workflow):
        return None

    ids = [n.id for n in workflow.nodes]
    idx = ids.index(node.id)
    if idx + 1 < len(ids):
        return ids[idx + 1]
    return None
