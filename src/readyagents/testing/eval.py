"""Tiny eval harness: score fixture workflows (pass and fail cases)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from readyagents.testing.helpers import run_workflow_file_test, run_workflow_spec
from readyagents.tools import ToolRegistry
from readyagents.workflow.schema import WorkflowSpec
from readyagents.workflow.state import RunState


@dataclass
class EvalCase:
    name: str
    workflow: Mapping[str, Any] | WorkflowSpec | Path | str
    inputs: dict[str, Any] = field(default_factory=dict)
    decisions: dict[str, str] = field(default_factory=dict)
    expect_status: str = "succeeded"
    expect_outputs: dict[str, Any] | None = None
    expect_contains: dict[str, str] | None = None


@dataclass
class EvalResult:
    name: str
    passed: bool
    reason: str = ""
    state: RunState | None = None


@dataclass
class EvalReport:
    results: list[EvalResult]

    @property
    def passed(self) -> int:
        return sum(1 for row in self.results if row.passed)

    @property
    def failed(self) -> int:
        return sum(1 for row in self.results if not row.passed)

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def assert_passing(self) -> None:
        if self.ok:
            return
        lines = [f"{row.name}: {row.reason}" for row in self.results if not row.passed]
        raise AssertionError("eval failures:\n" + "\n".join(lines))


def _score(state: RunState, case: EvalCase) -> tuple[bool, str]:
    if state.status != case.expect_status:
        return False, f"status {state.status!r} != {case.expect_status!r}"
    outputs = state.output_keys or state.node_outputs
    if case.expect_outputs:
        for key, expected in case.expect_outputs.items():
            actual = outputs.get(key)
            if actual != expected:
                return False, f"output {key!r}={actual!r} != {expected!r}"
    if case.expect_contains:
        for key, needle in case.expect_contains.items():
            hay = outputs.get(key)
            if needle not in str(hay):
                return False, f"output {key!r}={hay!r} does not contain {needle!r}"
    return True, "ok"


def run_eval(
    cases: Sequence[EvalCase],
    *,
    llm: Any = None,
    tools: ToolRegistry | None = None,
    settings: Any | None = None,
) -> EvalReport:
    results: list[EvalResult] = []
    for case in cases:
        try:
            if isinstance(case.workflow, (Path, str)):
                state = run_workflow_file_test(
                    case.workflow,
                    inputs=case.inputs,
                    llm=llm,
                    settings=settings,
                    persist=False,
                    decisions=case.decisions,
                    extra_tools=tools,
                )
            else:
                state = run_workflow_spec(
                    case.workflow,
                    inputs=case.inputs,
                    llm=llm,
                    tools=tools,
                    decisions=case.decisions,
                )
        except Exception as exc:  # noqa: BLE001
            results.append(EvalResult(name=case.name, passed=False, reason=str(exc)))
            continue
        ok, reason = _score(state, case)
        results.append(EvalResult(name=case.name, passed=ok, reason=reason, state=state))
    return EvalReport(results)
