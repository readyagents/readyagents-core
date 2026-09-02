from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from readyagents.errors import ConfigError
from readyagents.packs.loader import (
    collect_pack_nodes,
    collect_pack_specs,
    collect_pack_tools,
    confine_pack_path,
    discover_packs,
    load_pack_file,
)
from readyagents.packs.protocol import BasePack
from readyagents.tools import FunctionTool
from readyagents.workflow.engine import run_workflow
from readyagents.workflow.nodes import ExecutionContext
from readyagents.workflow.runner import run_workflow_file
from readyagents.workflow.schema import WorkflowSpec

_REPO = Path(__file__).resolve().parents[1]
_CONNECTOR = _REPO / "examples" / "packs" / "connector_pack.py"


class FakePack(BasePack):
    name = "fake"
    version = "9.9.9"

    def register_tools(self):
        return [FunctionTool(name="ping", description="pack tool", handler=lambda: "pong")]

    def register_nodes(self):
        return {"echo": _EchoHandler()}

    def register_workflows(self):
        return [{"name": "bundled"}]


class _EchoHandler:
    type_name = "echo"

    def execute(self, node: Any, state: Any, context: Any) -> Any:
        return f"echo:{node.id}"


def test_core_has_no_builtin_packs() -> None:
    assert discover_packs() == []


def test_collect_tools_from_fake_pack() -> None:
    registry = collect_pack_tools([FakePack()])
    assert registry.get("ping").run() == "pong"


def test_run_workflow_file_merges_pack_tools_and_nodes(tmp_path, tmp_settings, monkeypatch) -> None:
    path = tmp_path / "packwf.yaml"
    path.write_text(
        """
name: pack-merge
start: ping
nodes:
  - id: ping
    type: tool
    tool: ping
    output_key: pong
    next: echo
  - id: echo
    type: echo
    output_key: echoed
""",
        encoding="utf-8",
    )
    monkeypatch.setattr("readyagents.workflow.runner.discover_packs", lambda: [FakePack()])
    state = run_workflow_file(path, settings=tmp_settings, persist=False)
    assert state.status == "succeeded"
    assert state.output_keys["pong"] == "pong"
    assert state.output_keys["echoed"] == "echo:echo"


def test_pack_node_handler() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "pack-node",
            "nodes": [{"id": "e", "type": "echo", "output_key": "v"}],
        }
    )
    handlers = collect_pack_nodes([FakePack()])
    assert "echo" in handlers
    ctx = ExecutionContext(spec, collect_pack_tools([FakePack()]), extra_handlers=handlers)
    state = run_workflow(spec, {}, ctx)
    assert state.status == "succeeded"
    assert state.output_keys["v"] == "echo:e"


def test_discover_via_entry_points(monkeypatch) -> None:
    class EP:
        name = "fake"

        def load(self):
            return FakePack

    class EPs:
        def select(self, group):
            assert group == "readyagents.packs"
            return [EP()]

    monkeypatch.setattr("readyagents.packs.loader.entry_points", lambda: EPs())
    packs = discover_packs()
    assert len(packs) == 1
    assert packs[0].name == "fake"
    assert packs[0].version == "9.9.9"


def test_load_pack_file_connector_ping() -> None:
    pack = load_pack_file(_CONNECTOR, root=_REPO)
    assert pack.name == "example-connector"
    registry = collect_pack_tools([pack])
    result = registry.get("connector_ping").run(message="hello")
    assert result["ok"] is True
    assert result["message"] == "hello"
    assert result["connector"] == "example-connector"


def test_run_workflow_file_extra_packs(tmp_settings) -> None:
    pack = load_pack_file(_CONNECTOR, root=_REPO)
    state = run_workflow_file(
        _REPO / "examples" / "connector_demo.yaml",
        settings=tmp_settings,
        persist=False,
        extra_packs=[pack],
    )
    assert state.status == "succeeded"
    assert "hello" in str(state.output_keys["summary"])


def test_confine_pack_path_refuses_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "ok.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="outside the workspace"):
        confine_pack_path("/etc/passwd", workspace)
    with pytest.raises(ConfigError, match="outside the workspace"):
        confine_pack_path("../secret.py", workspace)
    outside = tmp_path / "secret.py"
    outside.write_text("def get_pack():\n    return None\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="outside the workspace"):
        load_pack_file(outside, root=workspace)


def test_collect_pack_specs_env_and_flags(monkeypatch) -> None:
    monkeypatch.setenv("READYAGENTS_PACK", "a.py,b.py")
    specs = collect_pack_specs(["c.py"])
    assert specs == ["a.py", "b.py", "c.py"]
