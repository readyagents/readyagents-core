from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from readyagents.errors import ApprovalRequired, NodeError, ToolError
from readyagents.mcp.builtin import tool_calc
from readyagents.tools import FunctionTool, default_registry
from readyagents.workflow.engine import run_workflow
from readyagents.workflow.nodes import ExecutionContext
from readyagents.workflow.runner import resume_run, run_workflow_file
from readyagents.workflow.schema import WorkflowSpec
from readyagents.workflow.state import load_run, persist_run

_CALC_SCHEMA = {
    "type": "object",
    "properties": {"expression": {"type": "string"}},
    "required": ["expression"],
}


def _wrap_calc(tools, hits: dict[str, int], key: str = "n") -> None:
    def counted(expression: str | int | float):
        hits[key] += 1
        return tool_calc(expression)

    tools._tools["calc"] = FunctionTool(
        name="calc",
        description="counted calc",
        schema=_CALC_SCHEMA,
        handler=counted,
    )


def test_include_resume_skips_completed_child_calc(
    tmp_path: Path, tmp_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    hits = {"n": 0}
    real_default = default_registry

    def wrapped_registry(*, allow_http, workspace):
        tools = real_default(allow_http=allow_http, workspace=workspace)
        _wrap_calc(tools, hits)
        return tools

    monkeypatch.setattr("readyagents.workflow.runner.default_registry", wrapped_registry)

    (tmp_path / "child.yaml").write_text(
        """
name: nested_calc_gate
inputs:
  n: 0
start: math
nodes:
  - id: math
    type: tool
    tool: calc
    arguments:
      expression: "1+{{n}}"
    output_key: total
    next: gate
  - id: gate
    type: approval
    prompt: "Allow nested?"
    then: ok
    else: hold
  - id: ok
    type: transform
    template: "{{total}}"
    output_key: verdict
  - id: hold
    type: transform
    template: "no"
    output_key: verdict
""",
        encoding="utf-8",
    )
    parent = tmp_path / "parent.yaml"
    parent.write_text(
        """
name: parent_include_resume
inputs:
  n: 4
start: nested
nodes:
  - id: nested
    type: include
    path: child.yaml
    inputs:
      n: "{{n}}"
    output_key: child
    next: wrap
  - id: wrap
    type: transform
    template: "parent ok: {{child.total}}"
    output_key: summary
""",
        encoding="utf-8",
    )

    with pytest.raises(ApprovalRequired) as paused:
        run_workflow_file(parent, settings=tmp_settings, persist=True)
    assert paused.value.node_id == "gate"
    assert hits["n"] == 1
    run_id = paused.value.run_id
    loaded = load_run(tmp_settings.runs_dir(), run_id)
    assert loaded.status == "paused"
    assert loaded.pending_node == "nested"
    child_run = (loaded.metadata.get("_include") or {}).get("nested") or {}
    record = child_run.get("run") or {}
    math_ok = [
        row
        for row in record.get("node_results") or []
        if row.get("node_id") == "math" and row.get("status") == "ok"
    ]
    assert math_ok
    assert math_ok[0].get("output") == 5

    state = resume_run(run_id, settings=tmp_settings, decisions={"gate": "approve"})
    assert state.status == "succeeded"
    assert state.run_id == run_id
    assert hits["n"] == 1
    assert state.output_keys["child"]["total"] == 5
    assert state.output_keys["summary"] == "parent ok: 5"


def test_parallel_resume_skips_completed_calc_branch(tmp_path: Path, tmp_settings) -> None:
    hits = {"calc": 0, "flaky": 0}

    def flaky() -> str:
        hits["flaky"] += 1
        if hits["flaky"] == 1:
            raise ToolError("boom")
        return "ok"

    tools = default_registry(allow_http=False, workspace=tmp_path)
    _wrap_calc(tools, hits, key="calc")
    tools.register(FunctionTool(name="flaky", description="fails once", handler=flaky))
    spec = WorkflowSpec.model_validate(
        {
            "name": "parallel-resume",
            "start": "fan",
            "nodes": [
                {
                    "id": "fan",
                    "type": "parallel",
                    "output_key": "parts",
                    "branches": [
                        {
                            "id": "a",
                            "type": "tool",
                            "tool": "calc",
                            "arguments": {"expression": "2+2"},
                        },
                        {"id": "b", "type": "tool", "tool": "flaky"},
                    ],
                }
            ],
        }
    )

    def on_persist(state) -> None:
        persist_run(state, tmp_settings.runs_dir())

    ctx = ExecutionContext(spec, tools, on_persist=on_persist, default_model="mock:test")
    with pytest.raises(NodeError, match="boom"):
        run_workflow(spec, {}, ctx)
    assert hits["calc"] == 1
    assert hits["flaky"] == 1

    found = list(tmp_settings.runs_dir().glob("*.json"))
    assert len(found) == 1
    loaded = load_run(tmp_settings.runs_dir(), found[0].stem)
    assert loaded.status == "failed"
    prior = (loaded.metadata.get("_parallel") or {}).get("fan") or {}
    assert prior.get("a") == 4
    assert "b" not in prior

    ctx2 = ExecutionContext(spec, tools, on_persist=on_persist, default_model="mock:test")
    state = run_workflow(spec, {}, ctx2, state=loaded)
    assert state.status == "succeeded"
    assert hits["calc"] == 1
    assert hits["flaky"] == 2
    assert state.output_keys["parts"]["a"] == 4
    assert state.output_keys["parts"]["b"] == "ok"


def test_nested_foreach_still_schema_invalid() -> None:
    with pytest.raises(ValidationError, match="nested foreach"):
        WorkflowSpec.model_validate(
            {
                "name": "x",
                "nodes": [
                    {
                        "id": "f",
                        "type": "foreach",
                        "items": "xs",
                        "body": {
                            "id": "inner",
                            "type": "foreach",
                            "items": "xs",
                            "body": {"id": "t", "type": "transform", "template": "a"},
                        },
                    }
                ],
            }
        )
