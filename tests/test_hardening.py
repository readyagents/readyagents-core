from __future__ import annotations

from pathlib import Path

import pytest

from readyagents.errors import ApprovalRequired, ConfigError, NodeError
from readyagents.tools import FunctionTool, ToolRegistry
from readyagents.workflow.engine import run_workflow
from readyagents.workflow.nodes import ExecutionContext
from readyagents.workflow.schema import WorkflowSpec
from readyagents.workflow.state import list_runs, load_run, persist_run


def _two_gates() -> WorkflowSpec:
    return WorkflowSpec.model_validate(
        {
            "name": "two-gates",
            "start": "a",
            "nodes": [
                {"id": "a", "type": "transform", "template": "1", "output_key": "v", "next": "g1"},
                {
                    "id": "g1",
                    "type": "approval",
                    "prompt": "first {{v}}?",
                    "then": "g2",
                    "else": "no",
                },
                {
                    "id": "g2",
                    "type": "approval",
                    "prompt": "second?",
                    "then": "yes",
                    "else": "no",
                },
                {"id": "yes", "type": "transform", "template": "all-yes", "output_key": "summary"},
                {"id": "no", "type": "transform", "template": "stopped", "output_key": "summary"},
            ],
        }
    )


def test_two_approval_gates_need_both_decisions() -> None:
    spec = _two_gates()
    with pytest.raises(ApprovalRequired) as first:
        run_workflow(spec, {}, ExecutionContext(spec, ToolRegistry(), decisions={}))
    assert first.value.node_id == "g1"
    with pytest.raises(ApprovalRequired) as second:
        run_workflow(spec, {}, ExecutionContext(spec, ToolRegistry(), decisions={"g1": "approve"}))
    assert second.value.node_id == "g2"
    state = run_workflow(
        spec, {}, ExecutionContext(spec, ToolRegistry(), decisions={"g1": "approve", "g2": "approve"})
    )
    assert state.status == "succeeded"
    assert state.output_keys["summary"] == "all-yes"


def test_reject_then_resume_with_approve(tmp_path: Path) -> None:
    spec = _two_gates()
    runs = tmp_path / "runs"

    def save(state) -> None:
        persist_run(state, runs)

    with pytest.raises(ApprovalRequired):
        run_workflow(spec, {}, ExecutionContext(spec, ToolRegistry(), on_persist=save))
    loaded = load_run(runs, list(runs.glob("*.json"))[0].stem)
    ctx = ExecutionContext(spec, ToolRegistry(), decisions={"g1": "reject"}, on_persist=save)
    state = run_workflow(spec, loaded.inputs, ctx, state=loaded)
    assert state.status == "succeeded"
    assert state.output_keys["summary"] == "stopped"


def test_resume_after_reject_path_already_done(tmp_path: Path) -> None:
    spec = _two_gates()
    state = run_workflow(
        spec, {}, ExecutionContext(spec, ToolRegistry(), decisions={"g1": "reject"})
    )
    persist_run(state, tmp_path)
    with pytest.raises(Exception, match="already succeeded"):
        from readyagents.workflow.engine import run_workflow as rw

        loaded = load_run(tmp_path, state.run_id)
        rw(spec, loaded.inputs, ExecutionContext(spec, ToolRegistry()), state=loaded)


def test_unknown_approval_decision() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "bad",
            "nodes": [
                {"id": "g", "type": "approval", "prompt": "?", "then": "g", "else": "g"},
            ],
        }
    )
    with pytest.raises(NodeError, match="unknown decision"):
        run_workflow(spec, {}, ExecutionContext(spec, ToolRegistry(), decisions={"g": "maybe"}))


def test_corrupt_run_record_typed_error(tmp_path: Path) -> None:
    path = tmp_path / "deadbeefdeadbeef.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="Corrupt"):
        load_run(tmp_path, "deadbeefdeadbeef")


def test_empty_run_record_invalid(tmp_path: Path) -> None:
    path = tmp_path / "aaaaaaaaaaaaaaaa.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid"):
        load_run(tmp_path, "aaaaaaaaaaaaaaaa")


def test_list_runs_skips_corrupt_and_filters(tmp_path: Path) -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "okwf",
            "nodes": [{"id": "t", "type": "transform", "template": "x", "output_key": "v"}],
        }
    )
    state = run_workflow(spec, {}, ExecutionContext(spec, ToolRegistry()))
    persist_run(state, tmp_path)
    (tmp_path / "junk.json").write_text("not-json", encoding="utf-8")
    found = list_runs(tmp_path)
    assert len(found) == 1
    assert found[0].run_id == state.run_id
    assert list_runs(tmp_path, status="succeeded")
    assert list_runs(tmp_path, status="paused") == []
    assert list_runs(tmp_path, workflow="okwf")
    assert list_runs(tmp_path, workflow="nope") == []
    assert len(list_runs(tmp_path, limit=1)) == 1


def test_ambiguous_run_prefix(tmp_path: Path) -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "p",
            "nodes": [{"id": "t", "type": "transform", "template": "x"}],
        }
    )
    a = run_workflow(spec, {}, ExecutionContext(spec, ToolRegistry()))
    b = run_workflow(spec, {}, ExecutionContext(spec, ToolRegistry()))
    persist_run(a, tmp_path)
    persist_run(b, tmp_path)
    with pytest.raises(ConfigError, match="ambiguous"):
        load_run(tmp_path, "")  # matches all via glob prefix? empty prefix
    # unique prefixes still work
    loaded = load_run(tmp_path, a.run_id[:10])
    assert loaded.run_id == a.run_id


def test_atomic_persist_readable(tmp_path: Path) -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "atom",
            "nodes": [{"id": "t", "type": "transform", "template": "ok", "output_key": "v"}],
        }
    )
    saved = []

    def on_persist(state) -> None:
        p = persist_run(state, tmp_path)
        saved.append(p)
        loaded = load_run(tmp_path, state.run_id)
        assert loaded.output_keys.get("v") == "ok" or loaded.status in {"running", "succeeded"}

    state = run_workflow(spec, {}, ExecutionContext(spec, ToolRegistry(), on_persist=on_persist))
    assert state.status == "succeeded"
    assert saved
    assert not list(tmp_path.glob(".*.tmp"))


def test_timeout_on_slow_tool() -> None:
    import time

    tools = ToolRegistry()
    tools.register(FunctionTool(name="slow", description="x", handler=lambda: time.sleep(0.4) or "x"))
    spec = WorkflowSpec.model_validate(
        {
            "name": "to",
            "nodes": [{"id": "s", "type": "tool", "tool": "slow", "timeout_seconds": 0.05}],
        }
    )
    with pytest.raises(NodeError, match="timed out") as exc:
        run_workflow(spec, {}, ExecutionContext(spec, tools))
    msg = str(exc.value)
    assert msg.count("Node 's':") == 1
    assert exc.value.run_id
    assert exc.value.state is not None
    assert getattr(exc.value.state, "status", None) == "failed"
    assert getattr(exc.value.state, "pending_node", None) == "s"


def test_failed_run_exception_carries_state() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "boom",
            "nodes": [{"id": "t", "type": "tool", "tool": "missing"}],
        }
    )
    with pytest.raises(NodeError) as exc:
        run_workflow(spec, {}, ExecutionContext(spec, ToolRegistry()))
    assert "Unknown tool" in str(exc.value)
    assert exc.value.run_id
    assert exc.value.state is not None
    loaded = exc.value.state
    assert getattr(loaded, "status", None) == "failed"
    assert getattr(loaded, "run_id", None) == exc.value.run_id


def test_dry_run_records_token_estimate() -> None:
    spec = WorkflowSpec.model_validate(
        {
            "name": "est",
            "nodes": [{"id": "a", "type": "agent", "prompt": "hello " * 20, "output_key": "t"}],
        }
    )
    from tests.conftest import MockLLM

    ctx = ExecutionContext(spec, ToolRegistry(), dry_run=True, llm=MockLLM("no"))
    state = run_workflow(spec, {}, ctx)
    assert state.status == "succeeded"
    assert state.usage.get("estimated_tokens", 0) >= 1
    assert "estimated_tokens=" in str(state.output_keys["t"])
