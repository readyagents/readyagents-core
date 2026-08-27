from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from readyagents.errors import WorkflowError
from readyagents.workflow.runner import load_workflow, merge_inputs
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
        WorkflowSpec.model_validate({"name": "x", "nodes": [{"id": "a", "type": "agent"}]})


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
        "agent_tools.yaml",
        "foreach_calc.yaml",
        "json_mutate.yaml",
    ):
        spec = load_workflow(examples_dir / name)
        assert spec.nodes


def test_agent_tools_allowlist_and_cap() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "worker",
            "nodes": [
                {
                    "id": "worker",
                    "type": "agent",
                    "prompt": "Use calc if needed. What is 2+2?",
                    "tools": ["calc"],
                    "max_tool_rounds": 4,
                }
            ],
        }
    )
    assert spec.nodes[0].tools == ["calc"]
    assert spec.nodes[0].max_tool_rounds == 4


def test_agent_without_tools_is_one_shot_schema() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "plain",
            "nodes": [{"id": "a", "type": "agent", "prompt": "hello"}],
        }
    )
    assert spec.nodes[0].tools == []
    assert spec.nodes[0].max_tool_rounds is None


def test_non_agent_tools_rejected() -> None:
    with pytest.raises(ValidationError, match="tools"):
        WorkflowSpec.model_validate(
            {
                "name": "bad",
                "nodes": [
                    {
                        "id": "t",
                        "type": "transform",
                        "template": "x",
                        "tools": ["calc"],
                    }
                ],
            }
        )


def test_duplicate_agent_tools_rejected() -> None:
    with pytest.raises(ValidationError, match="Duplicate"):
        WorkflowSpec.model_validate(
            {
                "name": "dup",
                "nodes": [
                    {
                        "id": "a",
                        "type": "agent",
                        "prompt": "hi",
                        "tools": ["calc", "calc"],
                    }
                ],
            }
        )


def test_mcp_style_tool_name_allowed() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "mcp",
            "nodes": [
                {
                    "id": "a",
                    "type": "agent",
                    "prompt": "list",
                    "tools": ["filesystem.list_directory"],
                }
            ],
        }
    )
    assert spec.nodes[0].tools == ["filesystem.list_directory"]


def test_cycle_rejected() -> None:
    with pytest.raises(ValidationError, match="Cycle"):
        WorkflowSpec.model_validate(
            {
                "name": "loop",
                "nodes": [
                    {"id": "a", "type": "transform", "template": "1", "next": "b"},
                    {"id": "b", "type": "transform", "template": "2", "next": "a"},
                ],
            }
        )


def test_self_loop_rejected() -> None:
    with pytest.raises(ValidationError, match="Cycle"):
        WorkflowSpec.model_validate(
            {
                "name": "self",
                "nodes": [
                    {"id": "a", "type": "transform", "template": "1", "next": "a"},
                ],
            }
        )


def test_branching_dag_is_not_a_cycle() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "dag",
            "start": "gate",
            "nodes": [
                {
                    "id": "gate",
                    "type": "condition",
                    "when": "ok == true",
                    "then": "yes",
                    "else": "no",
                },
                {"id": "yes", "type": "transform", "template": "Y", "next": "end"},
                {"id": "no", "type": "transform", "template": "N", "next": "end"},
                {"id": "end", "type": "transform", "template": "done"},
            ],
        }
    )
    assert spec.start == "gate"


def test_duplicate_parallel_branch_ids_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate parallel branch"):
        WorkflowSpec.model_validate(
            {
                "name": "dup-branch",
                "nodes": [
                    {
                        "id": "fan",
                        "type": "parallel",
                        "branches": [
                            {"id": "a", "type": "transform", "template": "1"},
                            {"id": "a", "type": "transform", "template": "2"},
                        ],
                    }
                ],
            }
        )


def test_required_inputs_missing_and_satisfied() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "need",
            "required_inputs": ["topic", "n"],
            "nodes": [
                {"id": "t", "type": "transform", "template": "{{topic}}-{{n}}", "output_key": "v"}
            ],
        }
    )
    with pytest.raises(WorkflowError, match=r"Missing required inputs: topic, n") as exc:
        merge_inputs(spec, {})
    assert "--input topic=..." in str(exc.value)
    assert "--input n=..." in str(exc.value)
    with pytest.raises(WorkflowError, match="n"):
        merge_inputs(spec, {"topic": "alpha"})
    merged = merge_inputs(spec, {"topic": "alpha", "n": 2})
    assert merged["topic"] == "alpha"
    assert merged["n"] == 2


def test_required_inputs_satisfied_by_default() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "need-def",
            "inputs": {"topic": {"default": "alpha"}},
            "required_inputs": ["topic"],
            "nodes": [{"id": "t", "type": "transform", "template": "{{topic}}"}],
        }
    )
    assert merge_inputs(spec, {})["topic"] == "alpha"


def test_parse_input_pairs() -> None:
    parsed = parse_input_pairs(["n=3", "flag=true", "name=Ada Lovelace"])
    assert parsed["n"] == 3
    assert parsed["flag"] is True
    assert parsed["name"] == "Ada Lovelace"
    with pytest.raises(WorkflowError):
        parse_input_pairs(["nope"])
