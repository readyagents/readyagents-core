from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from readyagents.errors import ConfigError, MCPError
from readyagents.llm.base import ToolCall
from readyagents.llm.tool_calls import spec_from_tool
from readyagents.mcp.client import MCPClient, mcp_available
from readyagents.testing import ScriptedLLM
from readyagents.tools import FunctionTool
from readyagents.workflow.runner import run_workflow_file
from readyagents.workflow.schema import MCPServerSpec

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "fake_mcp_stdio.py"
needs_mcp = pytest.mark.skipif(not mcp_available(), reason="mcp extra not installed")


def _server_spec(spawn_log: Path, *, cwd: str | None = None) -> dict:
    spec: dict = {
        "command": sys.executable,
        "args": [str(FIXTURE)],
        "env": {
            "FAKE_MCP_SPAWN_LOG": str(spawn_log),
            "PYTHONUNBUFFERED": "1",
        },
    }
    if cwd is not None:
        spec["cwd"] = cwd
    return spec


def _write_workflow(
    path: Path, spawn_log: Path, *, cwd: str | None = None, agent: bool = True
) -> Path:
    if agent:
        nodes = [
            {
                "id": "worker",
                "type": "agent",
                "prompt": "use add twice",
                "tools": ["fake.add"],
                "output_key": "answer",
            }
        ]
    else:
        nodes = [
            {
                "id": "a",
                "type": "tool",
                "tool": "fake.add",
                "arguments": {"n": 1},
                "output_key": "one",
                "next": "b",
            },
            {
                "id": "b",
                "type": "tool",
                "tool": "fake.add",
                "arguments": {"n": 2},
                "output_key": "two",
            },
        ]
    doc = {
        "name": "mcp-client",
        "mcp_servers": {"fake": _server_spec(spawn_log, cwd=cwd)},
        "nodes": nodes,
    }
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


def test_spec_from_tool_empty_schema_is_object() -> None:
    tool = FunctionTool(name="x", description="", handler=lambda: None, schema={})
    spec = spec_from_tool(tool)
    assert spec["schema"] == {"type": "object", "properties": {}}
    bare = spec_from_tool(SimpleNamespace(name="y", description="", schema=None))
    assert bare["schema"] == {"type": "object", "properties": {}}


@needs_mcp
def test_mcp_session_reused_and_schema_passed_to_llm(tmp_path: Path, tmp_settings) -> None:
    spawn_log = tmp_path / "spawn.log"
    wf = _write_workflow(tmp_path / "wf.yaml", spawn_log, agent=True)
    llm = ScriptedLLM()
    llm.enqueue(
        "",
        tool_calls=[ToolCall(id="c1", name="fake.add", arguments={"n": 1})],
    )
    llm.enqueue(
        "",
        tool_calls=[ToolCall(id="c2", name="fake.add", arguments={"n": 2})],
    )
    llm.enqueue("done")
    state = run_workflow_file(wf, settings=tmp_settings, persist=False, llm=llm)
    assert state.status == "succeeded"
    assert state.output_keys["answer"] == "done"
    lines = spawn_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, lines
    assert llm.calls
    payload = json.dumps(llm.calls[0]["tools"])
    assert '"n"' in payload
    specs = llm.calls[0]["tools"] or []
    add = next(row for row in specs if row.get("name") == "fake.add")
    properties = (add.get("schema") or {}).get("properties") or {}
    assert "n" in properties
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert any("2" in (m.content or "") for m in tool_msgs)
    tool_msgs2 = [m for m in llm.calls[2]["messages"] if m.role == "tool"]
    assert any("3" in (m.content or "") for m in tool_msgs2)


@needs_mcp
def test_mcp_two_tool_nodes_reuse_one_child(tmp_path: Path, tmp_settings) -> None:
    spawn_log = tmp_path / "spawn.log"
    wf = _write_workflow(tmp_path / "wf.yaml", spawn_log, agent=False)
    state = run_workflow_file(wf, settings=tmp_settings, persist=False)
    assert state.status == "succeeded"
    assert str(state.output_keys["one"]).strip() == "2"
    assert str(state.output_keys["two"]).strip() == "3"
    lines = spawn_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, lines


@needs_mcp
@pytest.mark.parametrize("cwd", ["/", "../escape"])
def test_mcp_cwd_escape_fails_before_spawn(tmp_path: Path, tmp_settings, cwd: str) -> None:
    spawn_log = tmp_path / "spawn.log"
    spec = MCPServerSpec.model_validate(_server_spec(spawn_log, cwd=cwd))
    with pytest.raises((ConfigError, MCPError), match="outside"):
        MCPClient({"fake": spec}, tmp_path)
    assert not spawn_log.exists()

    wf = _write_workflow(tmp_path / "bad.yaml", spawn_log, cwd=cwd, agent=False)
    with pytest.raises((ConfigError, MCPError), match="outside"):
        run_workflow_file(wf, settings=tmp_settings, persist=False)
    assert not spawn_log.exists()
