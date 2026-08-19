from __future__ import annotations

from pathlib import Path

import pytest

from readyagents.errors import NodeError, WorkflowError
from readyagents.tools import default_registry
from readyagents.workflow.engine import run_workflow
from readyagents.workflow.nodes import ExecutionContext
from readyagents.workflow.runner import run_workflow_file
from readyagents.workflow.schema import WorkflowSpec


def test_include_runs_child(tmp_path: Path, tmp_settings, examples_dir: Path) -> None:
    state = run_workflow_file(
        examples_dir / "include_demo.yaml",
        inputs={"n": 5},
        settings=tmp_settings,
        persist=False,
    )
    assert state.status == "succeeded"
    assert state.output_keys["summary"] == "include_demo ok: 15"


def test_include_missing_file(tmp_path: Path) -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "miss",
            "nodes": [{"id": "c", "type": "include", "path": "nope.yaml"}],
        }
    )
    ctx = ExecutionContext(spec, default_registry(allow_http=False, workspace=tmp_path), workflow_dir=tmp_path)
    with pytest.raises(NodeError, match="not found"):
        run_workflow(spec, {}, ctx)


def test_include_requires_path() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        WorkflowSpec.model_validate({"name": "x", "nodes": [{"id": "c", "type": "include"}]})


def test_include_depth_guard(tmp_path: Path) -> None:
    child = tmp_path / "loop.yaml"
    child.write_text(
        """
name: loop
nodes:
  - id: again
    type: include
    path: loop.yaml
""",
        encoding="utf-8",
    )
    spec = WorkflowSpec.model_validate(
        {"name": "root", "nodes": [{"id": "c", "type": "include", "path": "loop.yaml"}]}
    )
    ctx = ExecutionContext(
        spec,
        default_registry(allow_http=False, workspace=tmp_path),
        workflow_dir=tmp_path,
    )
    with pytest.raises((WorkflowError, NodeError), match="include depth"):
        run_workflow(spec, {}, ctx)
