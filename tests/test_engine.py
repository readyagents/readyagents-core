from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import MockLLM

from readyagents.errors import NodeError, TemplateError
from readyagents.tools import FunctionTool, ToolRegistry
from readyagents.workflow.engine import run_workflow
from readyagents.workflow.nodes import ExecutionContext
from readyagents.workflow.schema import WorkflowSpec
from readyagents.workflow.state import RunState


def _ctx(
    spec: WorkflowSpec,
    tools: ToolRegistry | None = None,
    llm: MockLLM | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        spec,
        tools or ToolRegistry(),
        dry_run=False,
        llm=llm or MockLLM("ok"),
        default_model="mock:test",
    )


def test_sequential_transforms() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "seq",
            "inputs": {"name": "Ada"},
            "nodes": [
                {"id": "a", "type": "transform", "template": "hello {{name}}", "output_key": "greet"},
                {"id": "b", "type": "transform", "template": "{{greet}}!", "output_key": "out"},
            ],
        }
    )
    state = run_workflow(spec, spec.input_defaults(), _ctx(spec))
    assert state.status == "succeeded"
    assert state.output_keys["out"] == "hello Ada!"


def test_condition_branches() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "br",
            "inputs": {"priority": "urgent"},
            "start": "c",
            "nodes": [
                {
                    "id": "c",
                    "type": "condition",
                    "when": 'priority == "urgent"',
                    "then": "hot",
                    "else": "cold",
                },
                {"id": "hot", "type": "transform", "template": "P1", "output_key": "label"},
                {"id": "cold", "type": "transform", "template": "P3", "output_key": "label"},
            ],
        }
    )
    state = run_workflow(spec, spec.input_defaults(), _ctx(spec))
    assert state.output_keys["label"] == "P1"

    spec.inputs["priority"] = "low"
    state = run_workflow(spec, {"priority": "low"}, _ctx(spec))
    assert state.output_keys["label"] == "P3"


def test_missing_template_var() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "miss",
            "nodes": [{"id": "t", "type": "transform", "template": "x={{nope}}"}],
        }
    )
    with pytest.raises(NodeError) as exc:
        run_workflow(spec, {}, _ctx(spec))
    msg = str(exc.value)
    assert isinstance(exc.value.__cause__, TemplateError) or "Missing template variable" in msg


def test_retry_then_succeed() -> None:
    hits = {"n": 0}

    def flaky() -> str:
        hits["n"] += 1
        if hits["n"] < 3:
            raise RuntimeError("not yet")
        return "ok"

    tools = ToolRegistry()
    tools.register(FunctionTool(name="flaky", description="x", handler=flaky))
    spec = WorkflowSpec.model_validate(
        {
            "name": "retry",
            "nodes": [
                {
                    "id": "f",
                    "type": "tool",
                    "tool": "flaky",
                    "retry": {"max_attempts": 3, "backoff_seconds": 0},
                    "output_key": "v",
                }
            ],
        }
    )
    state = run_workflow(spec, {}, _ctx(spec, tools=tools))
    assert state.output_keys["v"] == "ok"
    assert hits["n"] == 3


def test_retry_exhausted() -> None:
    def boom() -> str:
        raise RuntimeError("nope")

    tools = ToolRegistry()
    tools.register(FunctionTool(name="boom", description="x", handler=boom))
    spec = WorkflowSpec.model_validate(
        {
            "name": "fail",
            "nodes": [
                {
                    "id": "f",
                    "type": "tool",
                    "tool": "boom",
                    "retry": {"max_attempts": 2, "backoff_seconds": 0},
                }
            ],
        }
    )
    with pytest.raises(NodeError):
        run_workflow(spec, {}, _ctx(spec, tools=tools))


def test_agent_uses_llm() -> None:
    llm = MockLLM("brief-text")
    spec = WorkflowSpec.model_validate(
        {
            "name": "ag",
            "inputs": {"topic": "tea"},
            "nodes": [
                {
                    "id": "a",
                    "type": "agent",
                    "prompt": "Write about {{topic}}",
                    "output_key": "text",
                }
            ],
        }
    )
    state = run_workflow(spec, spec.input_defaults(), _ctx(spec, llm=llm))
    assert state.output_keys["text"] == "brief-text"
    assert "tea" in llm.calls[0][-1].content


def test_dry_run_skips_llm() -> None:
    llm = MockLLM("should-not-run")
    spec = WorkflowSpec.model_validate(
        {
            "name": "dry",
            "inputs": {"topic": "x"},
            "nodes": [{"id": "a", "type": "agent", "prompt": "go {{topic}}", "output_key": "out"}],
        }
    )
    ctx = ExecutionContext(spec, ToolRegistry(), dry_run=True, llm=llm)
    state = run_workflow(spec, spec.input_defaults(), ctx)
    assert llm.calls == []
    assert "[dry-run]" in state.output_keys["out"]
    assert "go x" in state.output_keys["out"]


def test_cycle_detected() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "loop",
            "nodes": [
                {"id": "a", "type": "transform", "template": "1", "next": "b"},
                {"id": "b", "type": "transform", "template": "2", "next": "a"},
            ],
        }
    )
    with pytest.raises(Exception, match="Cycle"):
        run_workflow(spec, {}, _ctx(spec))


def test_edges_with_when() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "e",
            "inputs": {"ok": True},
            "nodes": [
                {"id": "start", "type": "transform", "template": "go"},
                {"id": "yes", "type": "transform", "template": "Y", "output_key": "v"},
                {"id": "no", "type": "transform", "template": "N", "output_key": "v"},
            ],
            "edges": [
                {"from": "start", "to": "yes", "when": "ok == true"},
                {"from": "start", "to": "no"},
            ],
        }
    )
    state = run_workflow(spec, spec.input_defaults(), _ctx(spec))
    assert state.output_keys["v"] == "Y"


def test_run_state_record_roundtrip(tmp_path: Path) -> None:
    from readyagents.workflow.state import persist_run

    state = RunState.start("w", {"a": 1})
    state.record("n", "out", node_type="transform", output_key="k")
    state.finish("succeeded")
    path = persist_run(state, tmp_path)
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "succeeded" in text
    assert '"k"' in text or "out" in text
