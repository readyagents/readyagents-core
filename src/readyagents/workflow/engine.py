"""Execute a workflow graph with retries, timeouts, and branching."""

from __future__ import annotations

import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from readyagents.errors import NodeError, ReadyAgentsError, WorkflowError
from readyagents.logging import get_logger
from readyagents.workflow.nodes import ExecutionContext, evaluate_condition, execute_node
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
) -> RunState:
    state = RunState.start(workflow.name, inputs, metadata=metadata)
    nodes = workflow.node_map()
    current = workflow.start or workflow.nodes[0].id
    seen: set[str] = set()
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
            _execute_with_policy(node, state, ctx)
            current = _next_node(workflow, node, state)
        state.finish("succeeded")
    except ReadyAgentsError as exc:
        state.record_error(
            current or "?",
            str(nodes[current].type) if current in nodes else "?",
            str(exc),
        )
        state.finish("failed")
        raise
    return state


def _execute_with_policy(node: NodeSpec, state: RunState, ctx: ExecutionContext) -> None:
    retry = node.retry
    attempts = retry.max_attempts if retry else 1
    backoff = retry.backoff_seconds if retry else 1.0
    multiplier = retry.backoff_multiplier if retry else 2.0
    last_error: BaseException | None = None
    started = utc_now()

    for attempt in range(1, attempts + 1):
        try:
            output = _call_with_timeout(node, state, ctx)
            state.record(
                node.id,
                output,
                node_type=str(node.type),
                output_key=node.output_key,
                attempts=attempt,
                started_at=started,
                finished_at=utc_now(),
            )
            return
        except ReadyAgentsError as exc:
            last_error = exc
            log.warning("Node %s attempt %s/%s failed: %s", node.id, attempt, attempts, exc)
            if attempt >= attempts:
                break
            time.sleep(backoff * (multiplier ** (attempt - 1)))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            log.warning("Node %s attempt %s/%s failed: %s", node.id, attempt, attempts, exc)
            if attempt >= attempts:
                break
            time.sleep(backoff * (multiplier ** (attempt - 1)))

    message = str(last_error) if last_error else "unknown error"
    raise NodeError(node.id, message, cause=last_error) from last_error


def _call_with_timeout(node: NodeSpec, state: RunState, ctx: ExecutionContext) -> Any:
    if not node.timeout_seconds:
        return execute_node(node, state, ctx)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(execute_node, node, state, ctx)
        try:
            return future.result(timeout=node.timeout_seconds)
        except FutureTimeout as exc:
            raise NodeError(
                node.id,
                f"timed out after {node.timeout_seconds}s",
                cause=exc,
            ) from exc


def _uses_explicit_routing(workflow: WorkflowSpec) -> bool:
    if workflow.edges:
        return True
    return any(n.next or n.then or n.else_ for n in workflow.nodes)


def _next_node(workflow: WorkflowSpec, node: NodeSpec, state: RunState) -> str | None:
    if str(node.type) == NodeType.condition.value:
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
