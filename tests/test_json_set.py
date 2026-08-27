from __future__ import annotations

from pathlib import Path

import pytest

from readyagents.errors import ToolError
from readyagents.mcp.builtin import _MAX_JSON_BYTES, tool_json_merge, tool_json_set
from readyagents.workflow.runner import run_workflow_file


def test_json_set_nested_does_not_mutate() -> None:
    original = {"user": {"name": "anon", "tags": ["x"]}}
    result = tool_json_set(original, "user.name", "Ada")
    assert result == {"user": {"name": "Ada", "tags": ["x"]}}
    assert original == {"user": {"name": "anon", "tags": ["x"]}}
    assert result is not original
    assert result["user"] is not original["user"]


def test_json_set_creates_missing_dict_parents() -> None:
    result = tool_json_set("{}", "user.profile.name", "Ada")
    assert result == {"user": {"profile": {"name": "Ada"}}}


def test_json_set_list_index() -> None:
    data = {"a": {"b": [{"c": 1}, {"c": 2}]}}
    result = tool_json_set(data, "a.b.0.c", 7)
    assert result == {"a": {"b": [{"c": 7}, {"c": 2}]}}
    assert data["a"]["b"][0]["c"] == 1


def test_json_merge_objects() -> None:
    original = {"user": {"name": "Ada"}}
    result = tool_json_merge(original, "user", {"ok": True})
    assert result == {"user": {"name": "Ada", "ok": True}}
    assert original == {"user": {"name": "Ada"}}
    root = tool_json_merge({"a": 1}, "", {"b": 2})
    assert root == {"a": 1, "b": 2}
    dotted = tool_json_merge({"a": 1}, ".", '{"b": 3}')
    assert dotted == {"a": 1, "b": 3}


def test_json_merge_creates_missing_object() -> None:
    result = tool_json_merge({}, "user", {"ok": True})
    assert result == {"user": {"ok": True}}


def test_json_set_refuses_dunder_path() -> None:
    with pytest.raises(ToolError, match="refused"):
        tool_json_set({"a": 1}, "__proto__", "x")
    with pytest.raises(ToolError, match="refused"):
        tool_json_set({"a": 1}, "a.__hidden", "x")
    with pytest.raises(ToolError, match="refused"):
        tool_json_merge({}, "__proto__", {"x": 1})
    with pytest.raises(ToolError, match="refused"):
        tool_json_set({}, "constructor", 1)
    with pytest.raises(ToolError, match="refused"):
        tool_json_set({}, "a.prototype.b", 1)


def test_json_set_refuses_empty_path_segments() -> None:
    with pytest.raises(ToolError, match="empty path"):
        tool_json_set({}, "", "x")
    with pytest.raises(ToolError, match="empty path"):
        tool_json_set({}, "a..b", "x")
    with pytest.raises(ToolError, match="empty path"):
        tool_json_merge({}, "user.", {"ok": True})


def test_json_merge_requires_object_value_and_target() -> None:
    with pytest.raises(ToolError, match="object"):
        tool_json_merge({"a": 1}, "", "not-an-object")
    with pytest.raises(ToolError, match="object"):
        tool_json_merge({"user": []}, "user", {"ok": True})


def test_json_set_size_cap() -> None:
    huge = "x" * (_MAX_JSON_BYTES + 1)
    with pytest.raises(ToolError, match="too large"):
        tool_json_set({}, "a", huge)
    with pytest.raises(ToolError, match="too large"):
        tool_json_merge({}, "a", '{"k": "' + huge + '"}')


def test_json_mutate_example(examples_dir: Path, tmp_settings) -> None:
    state = run_workflow_file(
        examples_dir / "json_mutate.yaml",
        settings=tmp_settings,
        persist=False,
    )
    assert state.status == "succeeded"
    doc = state.output_keys["doc"]
    assert doc == {"user": {"name": "Ada", "ok": True}}
    assert state.node_outputs["set_name"]["user"]["name"] == "Ada"
    assert state.node_outputs["merge_flag"]["user"]["ok"] is True
