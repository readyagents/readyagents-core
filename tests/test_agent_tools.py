from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.conftest import MockLLM
from typer.testing import CliRunner

from readyagents.cli import app
from readyagents.errors import BudgetExceeded, NodeError, StructuredOutputError
from readyagents.llm.base import CompletionResult, Message, ToolCall
from readyagents.llm.cache import LLMCache
from readyagents.llm.tool_calls import (
    tool_calls_from_anthropic_content,
    tool_calls_from_openai_message,
)
from readyagents.testing import ScriptedLLM, run_workflow_spec
from readyagents.tools import default_registry
from readyagents.workflow.engine import run_workflow
from readyagents.workflow.nodes import ExecutionContext
from readyagents.workflow.schema import WorkflowSpec
from readyagents.workflow.state import persist_run

runner = CliRunner()


def _registry(tmp_path: Path, *, allow_http: bool = False):
    return default_registry(allow_http=allow_http, workspace=tmp_path)


def _agent_spec(**extra: object) -> dict:
    node: dict = {
        "id": "worker",
        "type": "agent",
        "prompt": "What is 2+2?",
        "output_key": "answer",
    }
    node.update(extra)
    return {"name": "agent-tools", "nodes": [node]}


def test_compat_agent_without_tools_is_one_shot(tmp_path: Path) -> None:
    llm = ScriptedLLM()
    llm.enqueue("plain-text")
    state = run_workflow_spec(_agent_spec(), llm=llm, tools=_registry(tmp_path))
    assert state.status == "succeeded"
    assert state.output_keys["answer"] == "plain-text"
    assert len(llm.calls) == 1
    assert llm.calls[0]["tools"] is None


def test_happy_path_runs_real_calc(tmp_path: Path) -> None:
    llm = ScriptedLLM()
    llm.enqueue(
        "",
        tool_calls=[ToolCall(id="c1", name="calc", arguments={"expression": "2+2"})],
    )
    llm.enqueue("final-answer")
    state = run_workflow_spec(
        _agent_spec(tools=["calc"]),
        llm=llm,
        tools=_registry(tmp_path),
    )
    assert state.status == "succeeded"
    assert state.output_keys["answer"] == "final-answer"
    assert len(llm.calls) == 2
    assert llm.calls[0]["tools"]
    assert any(spec.get("name") == "calc" for spec in llm.calls[0]["tools"])
    tool_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert tool_msgs, "second complete must include a tool result"
    assert any("4" in (m.content or "") for m in tool_msgs)
    assert all("2+2" not in (m.content or "") for m in tool_msgs)


def test_tool_error_fed_back_then_real_calc(tmp_path: Path, tmp_settings) -> None:
    llm = ScriptedLLM()
    llm.enqueue(
        "",
        tool_calls=[ToolCall(id="bad", name="calc", arguments={"expression": "not-a-number"})],
    )
    llm.enqueue(
        "",
        tool_calls=[ToolCall(id="ok", name="calc", arguments={"expression": "2+2"})],
    )
    llm.enqueue("final-answer")
    spec = WorkflowSpec.model_validate(_agent_spec(tools=["calc"]))

    def save(state) -> None:
        persist_run(state, tmp_settings.runs_dir())

    ctx = ExecutionContext(
        spec,
        _registry(tmp_path),
        llm=llm,
        default_model="mock:test",
        on_persist=save,
    )
    state = run_workflow(spec, {}, ctx)
    assert state.status == "succeeded"
    assert state.output_keys["answer"] == "final-answer"
    assert len(llm.calls) == 3
    error_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    assert error_msgs
    assert any("error" in (m.content or "").lower() for m in error_msgs)
    good_msgs = [m for m in llm.calls[2]["messages"] if m.role == "tool"]
    assert any("4" in (m.content or "") for m in good_msgs)
    rounds = state.results[0].tool_rounds
    assert any(row.get("name") == "calc" and row.get("status") == "error" for row in rounds)
    assert any(row.get("name") == "calc" and row.get("status") == "ok" for row in rounds)
    dumped = persist_run(state, tmp_settings.runs_dir())
    text = dumped.read_text(encoding="utf-8")
    assert "calc" in text
    assert "tool_rounds" in text


def test_allowlist_rejects_write_file(tmp_path: Path) -> None:
    target = tmp_path / "secret.txt"
    llm = ScriptedLLM()
    llm.enqueue(
        "",
        tool_calls=[
            ToolCall(
                id="w1",
                name="write_file",
                arguments={"path": "secret.txt", "content": "leaked"},
            )
        ],
    )
    with pytest.raises(NodeError, match="allowlist") as exc:
        run_workflow_spec(
            _agent_spec(tools=["calc"]),
            llm=llm,
            tools=_registry(tmp_path),
        )
    assert exc.value.node_id == "worker"
    assert not target.exists()
    assert len(llm.calls) == 1


def test_unknown_yaml_tool_fails_before_llm(tmp_path: Path) -> None:
    llm = ScriptedLLM()
    llm.enqueue("should-not-run")
    with pytest.raises(NodeError, match="unknown tool"):
        run_workflow_spec(
            _agent_spec(tools=["not_a_real_tool"]),
            llm=llm,
            tools=_registry(tmp_path),
        )
    assert llm.calls == []


def test_max_tool_rounds_cap(tmp_path: Path) -> None:
    class AlwaysCalc:
        name = "always"

        def __init__(self) -> None:
            self.calls: list[dict] = []

        def complete(self, messages, *, model: str, tools=None, **kwargs):
            self.calls.append({"model": model, "messages": messages, "tools": tools})
            return CompletionResult(
                text="",
                model=model,
                tool_calls=[
                    ToolCall(
                        id=f"c{len(self.calls)}",
                        name="calc",
                        arguments={"expression": "1+1"},
                    )
                ],
            )

    llm = AlwaysCalc()
    started = time.perf_counter()
    with pytest.raises(NodeError, match="max_tool_rounds=1") as exc:
        run_workflow_spec(
            _agent_spec(tools=["calc"], max_tool_rounds=1),
            llm=llm,
            tools=_registry(tmp_path),
        )
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0
    assert exc.value.node_id == "worker"
    assert "max_tool_rounds=1" in str(exc.value)


def test_dry_run_write_file_does_not_touch_disk_or_llm(tmp_path: Path) -> None:
    llm = MockLLM("should-not-run")
    spec = WorkflowSpec.model_validate(
        _agent_spec(tools=["write_file"], prompt="write hello to out.txt")
    )
    ctx = ExecutionContext(
        spec,
        _registry(tmp_path),
        dry_run=True,
        llm=llm,
        default_model="mock:test",
    )
    state = run_workflow(spec, {}, ctx)
    assert state.status == "succeeded"
    assert llm.calls == []
    assert "[dry-run]" in str(state.output_keys["answer"])
    assert "write_file" in str(state.output_keys["answer"])
    assert not (tmp_path / "out.txt").exists()


def test_agent_http_get_loopback_refused(tmp_path: Path) -> None:
    llm = ScriptedLLM()
    llm.enqueue(
        "",
        tool_calls=[
            ToolCall(
                id="h1",
                name="http_get",
                arguments={"url": "http://127.0.0.1/"},
            )
        ],
    )
    llm.enqueue("blocked")
    state = run_workflow_spec(
        _agent_spec(tools=["http_get"]),
        llm=llm,
        tools=_registry(tmp_path, allow_http=True),
    )
    assert state.status == "succeeded"
    assert state.output_keys["answer"] == "blocked"
    error_msgs = [m for m in llm.calls[1]["messages"] if m.role == "tool"]
    blob = " ".join(m.content or "" for m in error_msgs).lower()
    assert "loopback" in blob or "blocked" in blob or "private" in blob
    assert "127.0.0.1" in " ".join(m.content or "" for m in error_msgs) or "loopback" in blob
    rounds = state.results[0].tool_rounds
    assert any(row.get("name") == "http_get" and row.get("status") == "error" for row in rounds)


def test_budget_stops_later_complete_round(tmp_path: Path) -> None:
    llm = ScriptedLLM()
    llm.enqueue(
        "",
        tool_calls=[ToolCall(id="c1", name="calc", arguments={"expression": "2+2"})],
        usage={"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10},
    )
    llm.enqueue("should-not-run", usage={"prompt_tokens": 1, "completion_tokens": 1})
    spec = WorkflowSpec.model_validate(_agent_spec(tools=["calc"]))
    ctx = ExecutionContext(
        spec,
        _registry(tmp_path),
        llm=llm,
        default_model="mock:test",
        budget_tokens=10,
    )
    with pytest.raises(BudgetExceeded) as exc:
        run_workflow(spec, {}, ctx)
    assert exc.value.kind == "tokens"
    assert len(llm.calls) == 1


def test_output_schema_validates_final_text_only(tmp_path: Path) -> None:
    llm = ScriptedLLM()
    llm.enqueue(
        "not-json",
        tool_calls=[ToolCall(id="c1", name="calc", arguments={"expression": "2+2"})],
    )
    llm.enqueue('{"priority": "high"}')
    state = run_workflow_spec(
        _agent_spec(
            tools=["calc"],
            output_schema={
                "type": "object",
                "required": ["priority"],
                "properties": {"priority": {"type": "string"}},
            },
        ),
        llm=llm,
        tools=_registry(tmp_path),
    )
    assert state.status == "succeeded"
    assert state.output_keys["answer"]["priority"] == "high"

    llm_bad = ScriptedLLM()
    llm_bad.enqueue(
        "",
        tool_calls=[ToolCall(id="c1", name="calc", arguments={"expression": "2+2"})],
    )
    llm_bad.enqueue("not-json-final")
    with pytest.raises(StructuredOutputError):
        run_workflow_spec(
            _agent_spec(
                tools=["calc"],
                output_schema={
                    "type": "object",
                    "required": ["priority"],
                    "properties": {"priority": {"type": "string"}},
                },
            ),
            llm=llm_bad,
            tools=_registry(tmp_path),
        )


def test_scripted_llm_enqueues_tool_calls() -> None:
    llm = ScriptedLLM()
    llm.enqueue(
        "",
        tool_calls=[ToolCall(id="1", name="calc", arguments={"expression": "2+2"})],
    )
    result = llm.complete([Message(role="user", content="hi")], model="m", tools=[{"name": "calc"}])
    assert result.tool_calls[0].name == "calc"
    assert result.tool_calls[0].arguments["expression"] == "2+2"
    assert llm.calls[0]["tools"] == [{"name": "calc"}]


def test_openai_and_anthropic_tool_call_mapping() -> None:
    fn = SimpleNamespace(name="calc", arguments='{"expression": "2+2"}')
    call = SimpleNamespace(id="1", function=fn)
    message = SimpleNamespace(tool_calls=[call], content=None)
    mapped = tool_calls_from_openai_message(message)
    assert mapped == [ToolCall(id="1", name="calc", arguments={"expression": "2+2"})]

    dict_mapped = tool_calls_from_openai_message(
        {
            "tool_calls": [
                {
                    "id": "2",
                    "function": {"name": "calc", "arguments": '{"expression": "1+1"}'},
                }
            ]
        }
    )
    assert dict_mapped[0].arguments["expression"] == "1+1"

    blocks = [
        SimpleNamespace(type="text", text="hi", name=None, id=None, input=None),
        SimpleNamespace(type="tool_use", id="t1", name="calc", input={"expression": "2+2"}),
    ]
    anth = tool_calls_from_anthropic_content(blocks)
    assert anth == [ToolCall(id="t1", name="calc", arguments={"expression": "2+2"})]


def test_cache_key_distinguishes_tools(tmp_path: Path) -> None:
    cache = LLMCache(tmp_path / "cache")
    messages = [Message(role="user", content="hi")]
    bare = cache.key("m", messages, tools=None)
    with_tools = cache.key(
        "m",
        messages,
        tools=[{"name": "calc", "description": "", "schema": {}}],
    )
    assert bare != with_tools


def test_cli_validate_and_dry_run_agent_tools() -> None:
    example = "examples/agent_tools.yaml"
    validated = runner.invoke(app, ["validate", example])
    assert validated.exit_code == 0, validated.stdout + validated.stderr
    first = runner.invoke(app, ["run", example, "--dry-run", "--no-persist"])
    assert first.exit_code == 0, first.stdout + first.stderr
    assert "run_id:" in first.stdout
    assert "[dry-run]" in first.stdout
    second = runner.invoke(app, ["run", example, "--dry-run", "--no-persist"])
    assert second.exit_code == 0, second.stdout + second.stderr
    assert "run_id:" in second.stdout
    assert "[dry-run]" in second.stdout
