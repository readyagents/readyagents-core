from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from readyagents.cli import app
from readyagents.errors import ApprovalRequired
from readyagents.testing import run_workflow_file_test
from readyagents.tools import ToolRegistry
from readyagents.workflow.engine import run_workflow
from readyagents.workflow.nodes import ExecutionContext
from readyagents.workflow.runner import resume_run, run_workflow_file
from readyagents.workflow.schema import WorkflowSpec
from readyagents.workflow.state import load_decision_file, parse_decision_payload

runner = CliRunner()

_MULTI = {
    "name": "multi-gate",
    "start": "prep",
    "nodes": [
        {
            "id": "prep",
            "type": "transform",
            "template": "payload",
            "output_key": "body",
            "next": "first",
        },
        {
            "id": "first",
            "type": "approval",
            "prompt": "First {{body}}?",
            "then": "second",
            "else": "denied",
        },
        {
            "id": "second",
            "type": "approval",
            "prompt": "Second {{body}}?",
            "then": "ok",
            "else": "denied",
        },
        {
            "id": "ok",
            "type": "transform",
            "template": "multi_gate ok: {{body}}",
            "output_key": "summary",
        },
        {"id": "denied", "type": "transform", "template": "denied", "output_key": "summary"},
    ],
}


def test_parse_decision_payload_shapes() -> None:
    assert parse_decision_payload({"gate": "approve"}) == {"gate": "approve"}
    assert parse_decision_payload({"node_id": "gate", "decision": "Approve"}) == {"gate": "approve"}
    assert parse_decision_payload({"node": "g", "decision": "reject"}) == {"g": "reject"}
    assert parse_decision_payload({"decisions": {"a": "approve", "b": "reject"}}) == {
        "a": "approve",
        "b": "reject",
    }
    assert parse_decision_payload([{"node_id": "a", "decision": "approve"}]) == {"a": "approve"}


def test_load_decision_file(tmp_path: Path) -> None:
    path = tmp_path / "d.json"
    path.write_text(json.dumps({"first": "approve"}), encoding="utf-8")
    assert load_decision_file(path) == {"first": "approve"}


def test_multi_gate_pause_inject_pause(tmp_path: Path, tmp_settings) -> None:
    spec = WorkflowSpec.model_validate(_MULTI)
    pauses: list[str] = []

    def on_pause(exc, state) -> None:
        pauses.append(exc.node_id)

    with pytest.raises(ApprovalRequired) as first:
        run_workflow(
            spec,
            {},
            ExecutionContext(spec, ToolRegistry(), on_pause=on_pause),
        )
    assert first.value.node_id == "first"
    assert first.value.state.status == "paused"
    assert pauses == ["first"]

    ctx = ExecutionContext(
        spec,
        ToolRegistry(),
        decisions={"first": "approve"},
        on_pause=on_pause,
    )
    with pytest.raises(ApprovalRequired) as second:
        run_workflow(spec, {}, ctx, state=first.value.state)
    assert second.value.node_id == "second"
    assert pauses == ["first", "second"]

    payload = tmp_path / "second.json"
    payload.write_text(json.dumps({"node_id": "second", "decision": "approve"}), encoding="utf-8")
    injected = load_decision_file(payload)
    state = run_workflow(
        spec,
        {},
        ExecutionContext(spec, ToolRegistry(), decisions=injected),
        state=second.value.state,
    )
    assert state.status == "succeeded"
    assert state.output_keys["summary"] == "multi_gate ok: payload"


def test_decision_file_on_runner(tmp_path: Path, tmp_settings) -> None:
    path = tmp_path / "wf.yaml"
    path.write_text(
        """
name: file-gate
start: gate
nodes:
  - id: gate
    type: approval
    prompt: "go?"
    then: ok
    else: denied
  - id: ok
    type: transform
    template: "file-gate ok"
    output_key: summary
  - id: denied
    type: transform
    template: "no"
    output_key: summary
""",
        encoding="utf-8",
    )
    with pytest.raises(ApprovalRequired) as exc:
        run_workflow_file(path, settings=tmp_settings, persist=True)
    run_id = exc.value.run_id
    decision = tmp_path / "dec.json"
    decision.write_text(json.dumps({"gate": "approve"}), encoding="utf-8")
    state = resume_run(run_id, settings=tmp_settings, decision_file=decision)
    assert state.status == "succeeded"
    assert state.output_keys["summary"] == "file-gate ok"


def test_cli_decide_file(tmp_path: Path, tmp_settings, monkeypatch) -> None:
    monkeypatch.setenv("READYAGENTS_HOME", str(tmp_settings.home))
    from readyagents.config import clear_settings_cache

    clear_settings_cache()
    wf = tmp_path / "g.yaml"
    wf.write_text(
        """
name: cli-gate
nodes:
  - id: gate
    type: approval
    prompt: "x"
    then: ok
    else: denied
  - id: ok
    type: transform
    template: "cli ok"
    output_key: summary
  - id: denied
    type: transform
    template: "no"
    output_key: summary
""",
        encoding="utf-8",
    )
    paused = runner.invoke(app, ["run", str(wf)])
    assert paused.exit_code == 2, paused.stdout + paused.stderr
    text = paused.stdout + paused.stderr
    match = re.search(r"resume ([0-9a-f]{16,})", text, re.I)
    assert match, text
    run_id = match.group(1)
    decision = tmp_path / "d.json"
    decision.write_text(json.dumps({"node": "gate", "decision": "approve"}), encoding="utf-8")
    decided = runner.invoke(app, ["decide", run_id, "--file", str(decision)])
    assert decided.exit_code == 0, decided.stdout + decided.stderr
    assert "cli ok" in decided.stdout
    clear_settings_cache()


def test_on_pause_url_posts_outbound_payload(tmp_path: Path, tmp_settings, monkeypatch) -> None:
    posted: list[tuple[str, dict]] = []

    def fake_post(url: str, payload: dict, *, timeout: float = 5.0) -> None:
        posted.append((url, payload))

    monkeypatch.setattr("readyagents.workflow.runner.post_json", fake_post)
    path = tmp_path / "notify.yaml"
    path.write_text(
        """
name: notify-gate
on_pause_url: https://hooks.example.invalid/pause
nodes:
  - id: gate
    type: approval
    prompt: "ship?"
    then: ok
    else: denied
  - id: ok
    type: transform
    template: "ok"
    output_key: summary
  - id: denied
    type: transform
    template: "no"
    output_key: summary
""",
        encoding="utf-8",
    )
    with pytest.raises(ApprovalRequired) as exc:
        run_workflow_file(path, settings=tmp_settings, persist=True)
    assert posted, "outbound pause notify was not called"
    url, payload = posted[0]
    assert url == "https://hooks.example.invalid/pause"
    assert payload["event"] == "approval_required"
    assert payload["run_id"] == exc.value.run_id
    assert payload["node_id"] == "gate"
    assert "resume" in payload


def test_example_multi_gate_one_shot(examples_dir: Path, tmp_settings) -> None:
    state = run_workflow_file_test(
        examples_dir / "multi_gate.yaml",
        settings=tmp_settings,
        decisions={"first": "approve", "second": "approve"},
    )
    assert state.status == "succeeded"
    assert "multi_gate ok" in str(state.output_keys["summary"])
