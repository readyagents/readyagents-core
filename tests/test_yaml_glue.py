from __future__ import annotations

from pathlib import Path

import pytest

from readyagents.errors import TemplateError, WorkflowError
from readyagents.testing import run_workflow_spec
from readyagents.tools import default_registry
from readyagents.workflow.conditions import evaluate_condition
from readyagents.workflow.templates import interpolate


def test_default_filter_fills_missing() -> None:
    assert interpolate("{{missing | default ok}}", {}) == "ok"
    assert interpolate('{{missing | default "ok"}}', {}) == "ok"
    with pytest.raises(TemplateError):
        interpolate("{{missing}}", {})


def test_len_and_join_filters() -> None:
    ns = {"results": [2, 4], "name": "Ada"}
    assert interpolate("{{results | len}}", ns) == "2"
    assert interpolate('{{results | join ","}}', ns) == "2,4"
    assert interpolate("{{name | default x}}", ns) == "Ada"


def test_and_or_not_conditions() -> None:
    ns = {"a": 1, "b": 2, "flag": True}
    assert evaluate_condition("a == 1 and b == 2", ns) is True
    assert evaluate_condition("a == 1 and b == 9", ns) is False
    assert evaluate_condition("a == 9 or b == 2", ns) is True
    assert evaluate_condition("not flag", ns) is False
    assert evaluate_condition("(a == 1 and b == 9) or b == 2", ns) is True


def test_leftover_boolean_text_rejected() -> None:
    with pytest.raises(WorkflowError, match="parse"):
        evaluate_condition('a == "x" leftover', {"a": "x"})


def test_foreach_len_uses_real_calc(tmp_path: Path) -> None:
    spec = {
        "name": "glue",
        "inputs": {"expressions": ["1+1", "2+2"]},
        "nodes": [
            {
                "id": "each",
                "type": "foreach",
                "items": "expressions",
                "output_key": "results",
                "next": "count",
                "body": {
                    "id": "math",
                    "type": "tool",
                    "tool": "calc",
                    "arguments": {"expression": "{{item}}"},
                },
            },
            {
                "id": "count",
                "type": "transform",
                "template": "{{results | len}}",
                "output_key": "n",
            },
        ],
    }
    state = run_workflow_spec(spec, tools=default_registry(allow_http=False, workspace=tmp_path))
    assert state.status == "succeeded"
    assert state.output_keys["results"] == [2, 4]
    assert state.output_keys["n"] == "2"


def test_and_condition_routes_then(tmp_path: Path) -> None:
    spec = {
        "name": "and-gate",
        "inputs": {"a": 1, "b": 2},
        "nodes": [
            {
                "id": "c",
                "type": "condition",
                "when": "a == 1 and b == 2",
                "then": "yes",
                "else": "no",
            },
            {"id": "yes", "type": "transform", "template": "hit-then", "output_key": "out"},
            {"id": "no", "type": "transform", "template": "hit-else", "output_key": "out"},
        ],
    }
    state = run_workflow_spec(spec, tools=default_registry(allow_http=False, workspace=tmp_path))
    assert state.status == "succeeded"
    assert state.output_keys["out"] == "hit-then"
