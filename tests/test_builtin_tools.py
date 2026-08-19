from __future__ import annotations

from pathlib import Path

import pytest

from readyagents.errors import ToolError
from readyagents.mcp.builtin import (
    tool_calc,
    tool_json_get,
    tool_now,
    tool_read_file,
    tool_write_file,
)
from readyagents.tools import default_registry
from readyagents.workflow.runner import run_workflow_file


def test_now_iso() -> None:
    value = tool_now()
    assert "T" in value
    assert value.endswith("Z") or "+" in value


def test_calc_arithmetic() -> None:
    assert tool_calc("2 + 2 * 10") == 22
    assert tool_calc("10 // 3") == 3
    assert tool_calc("-4 + 1") == -3


def test_calc_rejects_names() -> None:
    with pytest.raises(ToolError):
        tool_calc("__import__('os').system('pwd')")
    with pytest.raises(ToolError):
        tool_calc("2 ** 99")


def test_json_get_dotted() -> None:
    data = '{"a": {"b": [0, {"c": 7}]}}'
    assert tool_json_get(data, "a.b.1.c") == 7
    assert tool_json_get({"x": 1}, "x") == 1
    with pytest.raises(ToolError):
        tool_json_get({"x": 1}, "nope")


def test_file_sandbox(tmp_path: Path) -> None:
    inside = tmp_path / "note.txt"
    tool_write_file("note.txt", "hello", workspace=tmp_path)
    assert inside.read_text(encoding="utf-8") == "hello"
    assert tool_read_file("note.txt", workspace=tmp_path) == "hello"
    with pytest.raises(ToolError):
        tool_read_file("../outside.txt", workspace=tmp_path)


def test_http_disabled_by_default(tmp_path: Path) -> None:
    registry = default_registry(allow_http=False, workspace=tmp_path)
    with pytest.raises(ToolError, match="disabled"):
        registry.get("http_get").run(url="https://example.com")


def test_default_registry_includes_builtins(tmp_path: Path) -> None:
    registry = default_registry(allow_http=False, workspace=tmp_path)
    for name in ("now", "calc", "json_get", "read_file", "write_file", "http_get"):
        assert name in registry.names()
    assert registry.get("calc").run(expression="1 + 2 * 3") == 7


def test_calc_pipeline_example(examples_dir: Path, tmp_settings) -> None:
    path = examples_dir / "calc_pipeline.yaml"
    state = run_workflow_file(path, settings=tmp_settings, persist=True)
    assert state.status == "succeeded"
    assert state.output_keys["extracted"] == 22
    assert "ok" in str(state.output_keys["summary"])
    assert all(r.node_id != "bad" for r in state.results)
    runs = list(tmp_settings.runs_dir().glob("*.json"))
    assert len(runs) == 1


def test_research_brief_dry_run_no_keys(examples_dir: Path, tmp_settings) -> None:
    state = run_workflow_file(
        examples_dir / "research_brief.yaml",
        inputs={"topic": "test"},
        dry_run=True,
        settings=tmp_settings,
        persist=False,
    )
    assert state.status == "succeeded"
    assert any("[dry-run]" in str(v) for v in state.node_outputs.values())
