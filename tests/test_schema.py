from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from readyagents.errors import WorkflowError
from readyagents.workflow.runner import load_workflow
from readyagents.workflow.schema import WorkflowSpec
from readyagents.workflow.state import parse_input_pairs


def test_minimal_transform_workflow() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "hello",
            "nodes": [
                {
                    "id": "greet",
                    "type": "transform",
                    "template": "hi {{name}}",
                    "output_key": "message",
                }
            ],
        }
    )
    assert spec.start == "greet"
    assert spec.nodes[0].type == "transform"


def test_duplicate_ids_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkflowSpec.model_validate(
            {
                "name": "dup",
                "nodes": [
                    {"id": "a", "type": "transform", "template": "1"},
                    {"id": "a", "type": "transform", "template": "2"},
                ],
            }
        )


def test_agent_requires_prompt() -> None:
    with pytest.raises(ValidationError):
        WorkflowSpec.model_validate(
            {"name": "x", "nodes": [{"id": "a", "type": "agent"}]}
        )


def test_unknown_next_rejected() -> None:
    with pytest.raises(ValidationError):
        WorkflowSpec.model_validate(
            {
                "name": "x",
                "nodes": [{"id": "a", "type": "transform", "template": "1", "next": "missing"}],
            }
        )


def test_approval_requires_prompt() -> None:
    with pytest.raises(ValidationError):
        WorkflowSpec.model_validate(
            {"name": "x", "nodes": [{"id": "g", "type": "approval", "then": "g"}]}
        )


def test_condition_requires_when() -> None:
    with pytest.raises(ValidationError):
        WorkflowSpec.model_validate(
            {"name": "x", "nodes": [{"id": "c", "type": "condition", "then": "c"}]}
        )


def test_load_yaml_fixture(tmp_path: Path) -> None:
    path = tmp_path / "wf.yaml"
    path.write_text(
        """
name: file_wf
nodes:
  - id: n
    type: transform
    template: ok
""",
        encoding="utf-8",
    )
    spec = load_workflow(path)
    assert spec.name == "file_wf"


def test_load_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("name: x\nnodes: not-a-list\n", encoding="utf-8")
    with pytest.raises(WorkflowError):
        load_workflow(path)


def test_input_defaults_nested() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "x",
            "inputs": {"topic": {"default": "alpha", "description": "t"}},
            "nodes": [{"id": "n", "type": "transform", "template": "{{topic}}"}],
        }
    )
    assert spec.input_defaults()["topic"] == "alpha"


def test_example_workflows_validate(examples_dir: Path) -> None:
    for name in (
        "calc_pipeline.yaml",
        "research_brief.yaml",
        "support_triage.yaml",
        "code_review.yaml",
        "approval_gate.yaml",
        "fanout_gate.yaml",
        "include_demo.yaml",
        "included_min.yaml",
        "composed_gate.yaml",
    ):
        spec = load_workflow(examples_dir / name)
        assert spec.nodes


def test_parse_input_pairs() -> None:
    parsed = parse_input_pairs(["n=3", "flag=true", "name=Ada Lovelace"])
    assert parsed["n"] == 3
    assert parsed["flag"] is True
    assert parsed["name"] == "Ada Lovelace"
    with pytest.raises(WorkflowError):
        parse_input_pairs(["nope"])
