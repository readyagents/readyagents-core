from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from readyagents.errors import StructuredOutputError
from readyagents.llm.cache import LLMCache
from readyagents.testing import ScriptedLLM, run_workflow_spec
from readyagents.tools import ToolRegistry
from readyagents.workflow.engine import run_workflow
from readyagents.workflow.nodes import ExecutionContext
from readyagents.workflow.runner import run_workflow_file
from readyagents.workflow.schema import WorkflowSpec


def _load_connector_pack():
    root = Path(__file__).resolve().parents[1] / "examples" / "packs" / "connector_pack.py"
    spec = importlib.util.spec_from_file_location("connector_pack", root)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ConnectorPack()


def test_structured_output_valid_is_typed() -> None:
    llm = ScriptedLLM()
    llm.enqueue('{"label": "urgent", "score": 3}', model="x")
    state = run_workflow_spec(
        {
            "name": "struct-ok",
            "nodes": [
                {
                    "id": "a",
                    "type": "agent",
                    "prompt": "classify",
                    "model": "mock:x",
                    "output_key": "parsed",
                    "output_schema": {
                        "type": "object",
                        "required": ["label", "score"],
                        "properties": {
                            "label": {"type": "string"},
                            "score": {"type": "integer"},
                        },
                    },
                }
            ],
        },
        llm=llm,
    )
    assert state.status == "succeeded"
    parsed = state.output_keys["parsed"]
    assert parsed == {"label": "urgent", "score": 3}
    assert isinstance(parsed["label"], str)
    assert isinstance(parsed["score"], int)


def test_structured_output_invalid_fails_typed() -> None:
    llm = ScriptedLLM()
    llm.enqueue('{"label": 9}', model="x")
    with pytest.raises(StructuredOutputError) as exc:
        run_workflow_spec(
            {
                "name": "struct-bad",
                "nodes": [
                    {
                        "id": "a",
                        "type": "agent",
                        "prompt": "classify",
                        "model": "mock:x",
                        "output_schema": {
                            "type": "object",
                            "required": ["label"],
                            "properties": {"label": {"type": "string"}},
                            "additionalProperties": False,
                        },
                    }
                ],
            },
            llm=llm,
        )
    assert exc.value.node_id == "a"
    assert "schema" in str(exc.value).lower() or "validation" in str(exc.value).lower()


def test_llm_cache_hit_does_not_call_again(tmp_path: Path) -> None:
    llm = ScriptedLLM()
    llm.enqueue("cached-text", model="m", usage={"prompt_tokens": 4, "completion_tokens": 1})
    cache = LLMCache(tmp_path / "cache")
    spec = WorkflowSpec.model_validate(
        {
            "name": "cache-me",
            "nodes": [
                {
                    "id": "a",
                    "type": "agent",
                    "prompt": "same prompt",
                    "model": "mock:m",
                    "output_key": "text",
                }
            ],
        }
    )
    ctx1 = ExecutionContext(spec, ToolRegistry(), llm=llm, llm_cache=cache, cache_llm=True)
    first = run_workflow(spec, {}, ctx1)
    assert first.output_keys["text"] == "cached-text"
    assert len(llm.calls) == 1
    ctx2 = ExecutionContext(spec, ToolRegistry(), llm=llm, llm_cache=cache, cache_llm=True)
    second = run_workflow(spec, {}, ctx2)
    assert second.output_keys["text"] == "cached-text"
    assert len(llm.calls) == 1
    assert cache.hits >= 1


def test_pack_registered_connector_runs_in_workflow(
    tmp_path: Path, tmp_settings, monkeypatch, examples_dir: Path
) -> None:
    pack = _load_connector_pack()
    monkeypatch.setattr("readyagents.workflow.runner.discover_packs", lambda: [pack])
    state = run_workflow_file(
        examples_dir / "connector_demo.yaml",
        settings=tmp_settings,
        persist=False,
    )
    assert state.status == "succeeded"
    assert state.output_keys["summary"] == "connector_demo ok: hello"
    assert state.output_keys["hit"]["ok"] is True
    assert state.output_keys["hit"]["connector"] == "example-connector"
