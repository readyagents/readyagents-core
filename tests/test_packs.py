from __future__ import annotations

from typing import Any

from readyagents.packs.loader import collect_pack_nodes, collect_pack_tools, discover_packs
from readyagents.packs.protocol import BasePack
from readyagents.tools import FunctionTool
from readyagents.workflow.engine import run_workflow
from readyagents.workflow.nodes import ExecutionContext
from readyagents.workflow.runner import run_workflow_file
from readyagents.workflow.schema import WorkflowSpec


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
