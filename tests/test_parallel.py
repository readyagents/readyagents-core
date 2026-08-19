from __future__ import annotations

from pathlib import Path

from readyagents.errors import ApprovalRequired, NodeError
from readyagents.tools import FunctionTool, ToolRegistry, default_registry
from readyagents.workflow.engine import run_workflow
from readyagents.workflow.nodes import ExecutionContext
from readyagents.workflow.schema import WorkflowSpec


def test_parallel_runs_independent_tools() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "fan",
            "nodes": [
                {
                    "id": "fan",
                    "type": "parallel",
                    "output_key": "parts",
                    "next": "join",
                    "branches": [
                        {"id": "a", "type": "tool", "tool": "calc", "arguments": {"expression": "2+2"}},
                        {"id": "b", "type": "tool", "tool": "calc", "arguments": {"expression": "5*5"}},
                    ],
                },
                {
                    "id": "join",
                    "type": "transform",
                    "template": "{{parts.a}}+{{parts.b}}",
                    "output_key": "out",
                },
            ],
        }
    )
    tools = default_registry(allow_http=False, workspace=Path("."))
    state = run_workflow(spec, {}, ExecutionContext(spec, tools))
    assert state.status == "succeeded"
    assert state.output_keys["parts"]["a"] == 4
    assert state.output_keys["parts"]["b"] == 25
    assert state.output_keys["out"] == "4+25"


def test_parallel_branch_failure() -> None:
    tools = ToolRegistry()

    def boom() -> str:
        raise RuntimeError("nope")

    tools.register(FunctionTool(name="ok", description="x", handler=lambda: "yes"))
    tools.register(FunctionTool(name="boom", description="x", handler=boom))
    spec = WorkflowSpec.model_validate(
        {
            "name": "pfail",
            "nodes": [
                {
                    "id": "fan",
                    "type": "parallel",
                    "branches": [
                        {"id": "a", "type": "tool", "tool": "ok"},
                        {"id": "b", "type": "tool", "tool": "boom"},
                    ],
                }
            ],
        }
    )
    try:
        run_workflow(spec, {}, ExecutionContext(spec, tools))
        raise AssertionError("expected failure")
    except NodeError as exc:
        assert "boom" in str(exc) or "nope" in str(exc)


def test_parallel_requires_branches() -> None:
    from pydantic import ValidationError

    try:
        WorkflowSpec.model_validate(
            {"name": "x", "nodes": [{"id": "p", "type": "parallel"}]}
        )
        raise AssertionError("expected validation error")
    except ValidationError:
        pass


def test_parallel_approval_in_branch_pauses() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "p-app",
            "nodes": [
                {
                    "id": "fan",
                    "type": "parallel",
                    "branches": [
                        {"id": "t", "type": "transform", "template": "x"},
                        {
                            "id": "g",
                            "type": "approval",
                            "prompt": "ok?",
                            "next": "t",
                        },
                    ],
                }
            ],
        }
    )
    try:
        run_workflow(spec, {}, ExecutionContext(spec, ToolRegistry()))
        raise AssertionError("expected pause")
    except ApprovalRequired as exc:
        assert exc.node_id == "g"
