from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from readyagents.audit import append_audit_event, read_audit_events
from readyagents.config import Settings, require_api_key
from readyagents.errors import ApprovalRequired, AuthorizationError, LLMError, NodeError
from readyagents.llm.registry import get_provider
from readyagents.logging import RedactLogFilter, _RunContextFilter
from readyagents.packs.protocol import BasePack
from readyagents.policy import CallbackAuthorizer, Redactor
from readyagents.secrets import MappingSecrets
from readyagents.tools import ToolRegistry
from readyagents.workflow.engine import run_workflow
from readyagents.workflow.nodes import ExecutionContext
from readyagents.workflow.runner import resume_run, run_workflow_file
from readyagents.workflow.schema import WorkflowSpec
from readyagents.workflow.state import persist_run


def test_secrets_hook_supplies_key_env_does_not() -> None:
    settings = Settings(  # type: ignore[call-arg]
        openai_api_key=None,
        anthropic_api_key=None,
        openai_compat_api_key=None,
        _env_file=(),
    )
    with pytest.raises(LLMError) as missing:
        require_api_key("openai", settings)
    assert "BYOK" in str(missing.value)

    vault = MappingSecrets({"OPENAI_API_KEY": "sk-from-vault-hook"})
    key = require_api_key("openai", settings, secrets=[vault])
    assert key == "sk-from-vault-hook"
    provider, model = get_provider(
        "openai:gpt-4o-mini",
        settings=settings,
        secrets=[vault],
    )
    assert provider.name == "openai"
    assert provider._api_key == "sk-from-vault-hook"
    assert model == "gpt-4o-mini"


def test_pack_secrets_reach_agent_provider(tmp_path: Path, tmp_settings, monkeypatch) -> None:
    class VaultPack(BasePack):
        name = "vault-test"
        version = "0.0.1"

        def register_secrets(self):
            return [MappingSecrets({"OPENAI_API_KEY": "sk-pack-secret"})]

    seen: dict[str, str | None] = {}

    def fake_get_provider(model_ref=None, *, settings=None, implicit=False, secrets=None):
        from readyagents.secrets import secret_for_provider

        seen["key"] = secret_for_provider("openai", settings=settings, secrets=secrets)
        raise LLMError("intercepted after secret resolve")

    monkeypatch.setattr("readyagents.workflow.nodes.get_provider", fake_get_provider)
    monkeypatch.setattr("readyagents.workflow.runner.discover_packs", lambda: [VaultPack()])
    path = tmp_path / "agent.yaml"
    path.write_text(
        """
name: needs-key
nodes:
  - id: a
    type: agent
    prompt: "hi"
    output_key: t
""",
        encoding="utf-8",
    )
    with pytest.raises(NodeError) as exc:
        run_workflow_file(path, settings=tmp_settings, persist=False)
    assert "intercepted" in str(exc.value)
    assert seen["key"] == "sk-pack-secret"

    seen.clear()
    monkeypatch.setattr("readyagents.workflow.runner.discover_packs", lambda: [])
    with pytest.raises(NodeError):
        run_workflow_file(path, settings=tmp_settings, persist=False)
    assert seen.get("key") in {None, ""}


def test_audit_trail_is_append_only(tmp_path: Path) -> None:
    audit = tmp_path / "audit"
    path = append_audit_event(audit, {"run_id": "r1", "event": "decision", "decision": "approve"})
    append_audit_event(audit, {"run_id": "r1", "event": "decision", "decision": "reject"})
    text = path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["decision"] == "approve"
    # A second persist must not erase the first line.
    events = read_audit_events(audit, "r1")
    assert events[0]["decision"] == "approve"
    assert events[1]["decision"] == "reject"
    assert events[0]["event"] == "decision"


def test_runner_audit_survives_second_persist(tmp_path: Path, tmp_settings) -> None:
    path = tmp_path / "wf.yaml"
    path.write_text(
        """
name: audit-me
start: a
nodes:
  - id: a
    type: transform
    template: "one"
    output_key: x
    next: b
  - id: b
    type: transform
    template: "two-{{x}}"
    output_key: y
""",
        encoding="utf-8",
    )
    state = run_workflow_file(path, settings=tmp_settings, persist=True)
    audit = tmp_settings.home_path() / "audit"
    first = read_audit_events(audit, state.run_id)
    assert any(e.get("event") == "run_started" for e in first)
    assert any(e.get("event") == "node_ok" and e.get("node_id") == "a" for e in first)
    persist_run(state, tmp_settings.runs_dir())
    again = read_audit_events(audit, state.run_id)
    assert again[0] == first[0]
    assert len(again) == len(first)


def test_approval_decision_stays_in_append_only_audit(tmp_path: Path, tmp_settings) -> None:
    path = tmp_path / "gate.yaml"
    path.write_text(
        """
name: audit-gate
nodes:
  - id: gate
    type: approval
    prompt: "go?"
    then: ok
    else: denied
  - id: ok
    type: transform
    template: "paid"
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
    state = resume_run(run_id, settings=tmp_settings, decisions={"gate": "approve"})
    assert state.status == "succeeded"
    audit = tmp_settings.home_path() / "audit"
    events = read_audit_events(audit, run_id)
    assert events, "audit log missing"
    first = events[0]
    assert any(e.get("event") == "decision" and e.get("decision") == "approve" for e in events)
    persist_run(state, tmp_settings.runs_dir())
    again = read_audit_events(audit, run_id)
    assert again[0] == first
    assert len(again) >= len(events)


def test_rbac_denies_resume_run_stays_paused(tmp_path: Path, tmp_settings) -> None:
    path = tmp_path / "gated.yaml"
    path.write_text(
        """
name: rbac-gate
nodes:
  - id: gate
    type: approval
    prompt: "ok?"
    then: ok
    else: denied
  - id: ok
    type: transform
    template: "should-not"
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
    deny = CallbackAuthorizer(lambda actor, action, resource: False)
    with pytest.raises(AuthorizationError) as denied:
        resume_run(
            run_id,
            settings=tmp_settings,
            decisions={"gate": "approve"},
            authorizer=deny,
            actor="intern",
        )
    assert denied.value.action in {"resume", "approve"}
    from readyagents.workflow.state import load_run

    loaded = load_run(tmp_settings.runs_dir(), run_id)
    assert loaded.status == "paused"
    assert loaded.pending_node == "gate"


def test_pii_redaction_logs_and_persisted_record(tmp_path: Path, tmp_settings) -> None:
    secret = "SECRETVALUE-abc"
    redactor = Redactor(literals=[secret])
    spec = WorkflowSpec.model_validate(
        {
            "name": "pii",
            "nodes": [
                {
                    "id": "t",
                    "type": "transform",
                    "template": f"token={secret}",
                    "output_key": "leak",
                }
            ],
        }
    )
    saved: list = []

    def on_persist(state) -> None:
        persist_run(state, tmp_settings.runs_dir(), redactor=redactor)
        saved.append(state.run_id)

    state = run_workflow(spec, {}, ExecutionContext(spec, ToolRegistry(), on_persist=on_persist))
    record_path = tmp_settings.runs_dir() / f"{state.run_id}.json"
    text = record_path.read_text(encoding="utf-8")
    assert secret not in text
    assert "[redacted]" in text

    buf = []

    class _H(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            buf.append(self.format(record))

    handler = _H()
    handler.addFilter(_RunContextFilter())
    handler.addFilter(RedactLogFilter(redactor))
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("readyagents.pii-test")
    logger.handlers[:] = []
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info("leaked %s", secret)
    assert buf
    assert secret not in buf[-1]
    assert "[redacted]" in buf[-1]


def test_runner_redacts_persisted_record(tmp_path: Path, monkeypatch) -> None:
    from readyagents.config import Settings, clear_settings_cache

    secret = "SECRETVALUE-runner"
    monkeypatch.chdir(tmp_path)
    settings = Settings(  # type: ignore[call-arg]
        home=tmp_path / ".readyagents",
        workspace=tmp_path,
        allow_http=False,
        default_model="openai:gpt-4o-mini",
        openai_api_key=None,
        anthropic_api_key=None,
        redact=True,
        redact_literals=secret,
        _env_file=(),
    )
    clear_settings_cache()
    path = tmp_path / "pii.yaml"
    path.write_text(
        f"""
name: pii-runner
nodes:
  - id: t
    type: transform
    template: "token={secret}"
    output_key: leak
""",
        encoding="utf-8",
    )
    state = run_workflow_file(path, settings=settings, persist=True)
    record = (settings.runs_dir() / f"{state.run_id}.json").read_text(encoding="utf-8")
    assert secret not in record
    assert "[redacted]" in record
    clear_settings_cache()
