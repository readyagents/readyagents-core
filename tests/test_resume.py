from __future__ import annotations

from pathlib import Path

import pytest

from readyagents.errors import ApprovalRequired, NodeError, WorkflowError
from readyagents.tools import FunctionTool, ToolRegistry
from readyagents.workflow.engine import run_workflow
from readyagents.workflow.nodes import ExecutionContext
from readyagents.workflow.runner import resume_run, run_workflow_file
from readyagents.workflow.schema import WorkflowSpec
from readyagents.workflow.state import load_run, persist_run


def test_persist_after_each_node_then_resume_skips_success(tmp_path: Path, tmp_settings) -> None:
    counts = {"a": 0, "b": 0}

    def tool_a() -> str:
        counts["a"] += 1
        return "A"

    def tool_b() -> str:
        counts["b"] += 1
        if counts["b"] < 2:
            raise RuntimeError("transient")
        return "B"

    tools = ToolRegistry()
    tools.register(FunctionTool(name="a", description="a", handler=tool_a))
    tools.register(FunctionTool(name="b", description="b", handler=tool_b))

    spec = WorkflowSpec.model_validate(
        {
            "name": "resume-me",
            "start": "a",
            "nodes": [
                {"id": "a", "type": "tool", "tool": "a", "output_key": "first", "next": "b"},
                {
                    "id": "b",
                    "type": "tool",
                    "tool": "b",
                    "output_key": "second",
                    "retry": {"max_attempts": 1, "backoff_seconds": 0},
                    "next": "c",
                },
                {"id": "c", "type": "transform", "template": "{{first}}-{{second}}", "output_key": "out"},
            ],
        }
    )

    saved: list[str] = []

    def on_persist(state) -> None:
        saved.append(state.status)
        persist_run(state, tmp_settings.runs_dir())

    ctx = ExecutionContext(spec, tools, on_persist=on_persist)
    with pytest.raises(NodeError):
        run_workflow(spec, {}, ctx)
    assert counts["a"] == 1
    assert counts["b"] == 1
    assert "failed" in saved

    files = list(tmp_settings.runs_dir().glob("*.json"))
    assert len(files) == 1
    loaded = load_run(tmp_settings.runs_dir(), files[0].stem)
    assert loaded.status == "failed"
    assert loaded.pending_node == "b"
    assert loaded.output_keys["first"] == "A"

    ctx2 = ExecutionContext(spec, tools, on_persist=on_persist)
    state = run_workflow(spec, loaded.inputs, ctx2, state=loaded)
    assert state.status == "succeeded"
    assert counts["a"] == 1
    assert counts["b"] == 2
    assert state.output_keys["out"] == "A-B"


def test_resume_approval_after_pause(tmp_path: Path, tmp_settings) -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "gate-resume",
            "nodes": [
                {"id": "prep", "type": "transform", "template": "hi", "output_key": "msg", "next": "gate"},
                {
                    "id": "gate",
                    "type": "approval",
                    "prompt": "ok {{msg}}?",
                    "then": "done",
                    "else": "no",
                },
                {"id": "done", "type": "transform", "template": "go {{msg}}", "output_key": "summary"},
                {"id": "no", "type": "transform", "template": "stop", "output_key": "summary"},
            ],
        }
    )

    def on_persist(state) -> None:
        persist_run(state, tmp_settings.runs_dir())

    with pytest.raises(ApprovalRequired) as exc:
        run_workflow(spec, {}, ExecutionContext(spec, ToolRegistry(), on_persist=on_persist))
    run_id = exc.value.run_id
    loaded = load_run(tmp_settings.runs_dir(), run_id)
    assert loaded.status == "paused"
    assert loaded.pending_node == "gate"

    ctx = ExecutionContext(spec, ToolRegistry(), decisions={"gate": "approve"}, on_persist=on_persist)
    state = run_workflow(spec, loaded.inputs, ctx, state=loaded)
    assert state.status == "succeeded"
    assert state.output_keys["summary"] == "go hi"


def test_resume_run_file_roundtrip(tmp_path: Path, tmp_settings) -> None:
    path = tmp_path / "wf.yaml"
    path.write_text(
        """
name: file-resume
start: boom
nodes:
  - id: boom
    type: tool
    tool: once
    output_key: v
    retry:
      max_attempts: 1
      backoff_seconds: 0
    next: done
  - id: done
    type: transform
    template: "got {{v}}"
    output_key: summary
""",
        encoding="utf-8",
    )
    hits = {"n": 0}

    def once() -> str:
        hits["n"] += 1
        if hits["n"] < 2:
            raise RuntimeError("not yet")
        return "ok"

    extra = ToolRegistry()
    extra.register(FunctionTool(name="once", description="x", handler=once))

    with pytest.raises(NodeError):
        run_workflow_file(path, settings=tmp_settings, persist=True, extra_tools=extra)
    files = list(tmp_settings.runs_dir().glob("*.json"))
    assert len(files) == 1
    run_id = files[0].stem
    state = resume_run(run_id, settings=tmp_settings, extra_tools=extra)
    assert state.status == "succeeded"
    assert state.output_keys["summary"] == "got ok"
    assert hits["n"] == 2


def test_resume_applies_input_overrides(tmp_path: Path, tmp_settings) -> None:
    path = tmp_path / "expr.yaml"
    path.write_text(
        """
name: expr-resume
inputs:
  expr: "1 / 0"
start: prep
nodes:
  - id: prep
    type: transform
    template: "go"
    output_key: tag
    next: calc
  - id: calc
    type: tool
    tool: calc
    arguments:
      expression: "{{expr}}"
    output_key: n
""",
        encoding="utf-8",
    )
    with pytest.raises(NodeError):
        run_workflow_file(path, settings=tmp_settings, persist=True)
    files = list(tmp_settings.runs_dir().glob("*.json"))
    assert len(files) == 1
    state = resume_run(files[0].stem, settings=tmp_settings, inputs={"expr": "3 + 4"})
    assert state.status == "succeeded"
    assert state.output_keys["n"] == 7
    assert state.inputs["expr"] == "3 + 4"


def test_resume_succeeded_run_rejected(tmp_path: Path, tmp_settings) -> None:
    path = tmp_path / "ok.yaml"
    path.write_text(
        """
name: already
nodes:
  - id: t
    type: transform
    template: ok
    output_key: summary
""",
        encoding="utf-8",
    )
    first = run_workflow_file(path, settings=tmp_settings, persist=True)
    assert first.status == "succeeded"
    with pytest.raises(WorkflowError, match="already succeeded"):
        resume_run(first.run_id, settings=tmp_settings)
