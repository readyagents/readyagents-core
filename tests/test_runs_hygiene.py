from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from readyagents.cli import app
from readyagents.config import clear_settings_cache
from readyagents.errors import ApprovalRequired, ConfigError
from readyagents.tools import FunctionTool, ToolRegistry
from readyagents.workflow.engine import run_workflow
from readyagents.workflow.nodes import ExecutionContext
from readyagents.workflow.runner import resume_run, run_workflow_file
from readyagents.workflow.schema import WorkflowSpec
from readyagents.workflow.state import delete_run, gc_runs, list_runs, load_run, persist_run

runner = CliRunner()


def test_pause_record_includes_prompt(tmp_settings) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples" / "approval_gate.yaml"
    with pytest.raises(ApprovalRequired):
        run_workflow_file(examples, settings=tmp_settings, persist=True)
    paused = list_runs(tmp_settings.runs_dir(), status="paused")
    assert paused
    state = paused[0]
    assert state.pending is not None
    assert state.pending.get("prompt")
    assert "approve" in (state.pending.get("resume") or "")
    assert "42" in str(state.pending.get("prompt"))


def test_cli_pause_show_json_has_prompt(tmp_settings, monkeypatch) -> None:
    clear_settings_cache()
    monkeypatch.setenv("READYAGENTS_HOME", str(tmp_settings.home))
    examples = Path(__file__).resolve().parents[1] / "examples" / "approval_gate.yaml"
    paused = runner.invoke(app, ["run", str(examples)])
    assert paused.exit_code == 2, paused.stdout + paused.stderr
    import json
    import re

    text = paused.stdout + paused.stderr
    match = re.search(r"run_id:\s*([0-9a-f]{16,})", text)
    if not match:
        match = re.search(r"([0-9a-f]{32})", text)
    assert match, text
    rid = match.group(1)
    shown = runner.invoke(app, ["runs", "show", rid, "--json"])
    assert shown.exit_code == 0
    record = json.loads(shown.stdout[shown.stdout.find("{") :])
    assert record.get("pending")
    assert record["pending"].get("prompt")
    assert record["status"] == "paused"


def test_delete_run_and_gc_spares_paused(tmp_settings) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples"
    calc = run_workflow_file(examples / "calc_pipeline.yaml", settings=tmp_settings, persist=True)
    assert calc.status == "succeeded"
    with pytest.raises(ApprovalRequired):
        run_workflow_file(examples / "approval_gate.yaml", settings=tmp_settings, persist=True)
    paused = [s for s in list_runs(tmp_settings.runs_dir()) if s.status == "paused"]
    succeeded = [s for s in list_runs(tmp_settings.runs_dir()) if s.status == "succeeded"]
    assert paused and succeeded
    deleted = gc_runs(tmp_settings.runs_dir(), statuses=["succeeded", "failed", "cancelled"])
    assert calc.run_id in deleted
    still = list_runs(tmp_settings.runs_dir())
    assert any(s.status == "paused" for s in still)
    assert not any(s.run_id == calc.run_id for s in still)
    rid = paused[0].run_id
    path = delete_run(tmp_settings.runs_dir(), rid)
    assert not path.exists()
    with pytest.raises(ConfigError):
        load_run(tmp_settings.runs_dir(), rid)


def test_cli_delete(tmp_settings, monkeypatch) -> None:
    monkeypatch.setenv("READYAGENTS_HOME", str(tmp_settings.home))
    examples = Path(__file__).resolve().parents[1] / "examples" / "calc_pipeline.yaml"
    ran = runner.invoke(app, ["run", str(examples)])
    assert ran.exit_code == 0, ran.stdout + ran.stderr
    import re

    match = re.search(r"run_id:\s*([0-9a-f]{16,})", ran.stdout)
    assert match
    rid = match.group(1)
    denied = runner.invoke(app, ["runs", "delete", rid])
    assert denied.exit_code == 1
    ok = runner.invoke(app, ["runs", "delete", rid, "--yes"])
    assert ok.exit_code == 0, ok.stdout + ok.stderr
    assert "Deleted" in ok.stdout


def test_keyboard_interrupt_persists_cancelled(tmp_path, tmp_settings) -> None:
    tools = ToolRegistry()

    def boom() -> str:
        raise KeyboardInterrupt()

    tools.register(FunctionTool(name="boom", description="x", handler=boom, schema={}))
    spec = WorkflowSpec.model_validate(
        {
            "name": "cancel-me",
            "nodes": [{"id": "x", "type": "tool", "tool": "boom"}],
        }
    )

    def on_persist(state) -> None:
        persist_run(state, tmp_settings.runs_dir())

    ctx = ExecutionContext(spec, tools, on_persist=on_persist, default_model="mock:test")
    with pytest.raises(KeyboardInterrupt):
        run_workflow(spec, {}, ctx)
    found = list_runs(tmp_settings.runs_dir(), status="cancelled")
    assert found
    assert found[0].status == "cancelled"
    assert found[0].pending_node == "x"


def test_gc_include_paused_deletes_paused_with_default_statuses(tmp_settings) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples"
    with pytest.raises(ApprovalRequired):
        run_workflow_file(examples / "approval_gate.yaml", settings=tmp_settings, persist=True)
    paused = list_runs(tmp_settings.runs_dir(), status="paused")
    assert paused
    rid = paused[0].run_id
    kept = gc_runs(tmp_settings.runs_dir(), include_paused=False)
    assert rid not in kept
    assert load_run(tmp_settings.runs_dir(), rid).status == "paused"
    deleted = gc_runs(tmp_settings.runs_dir(), include_paused=True)
    assert rid in deleted
    with pytest.raises(ConfigError):
        load_run(tmp_settings.runs_dir(), rid)


def test_resume_clears_pending_prompt(tmp_settings) -> None:
    examples = Path(__file__).resolve().parents[1] / "examples" / "approval_gate.yaml"
    with pytest.raises(ApprovalRequired) as paused:
        run_workflow_file(examples, settings=tmp_settings, persist=True)
    run_id = paused.value.run_id
    loaded = load_run(tmp_settings.runs_dir(), run_id)
    assert loaded.pending is not None
    assert "42" in str(loaded.pending.get("prompt"))
    state = resume_run(run_id, settings=tmp_settings, persist=True, decisions={"gate": "approve"})
    assert state.status == "succeeded"
    assert state.pending is None
    reloaded = load_run(tmp_settings.runs_dir(), run_id)
    assert reloaded.status == "succeeded"
    assert reloaded.pending is None
    assert reloaded.pending_node is None
