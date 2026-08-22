from __future__ import annotations

from pathlib import Path

import pytest

from readyagents.testing import EvalCase, RecordedLLM, ScriptedLLM, run_eval, run_workflow_spec


def test_recorded_llm_replays_without_network(tmp_path: Path) -> None:
    cassette = tmp_path / "tape.json"
    inner = ScriptedLLM()
    inner.enqueue("hello-offline", model="m", usage={"prompt_tokens": 2, "completion_tokens": 2})
    recorder = RecordedLLM(cassette, inner=inner)
    first = run_workflow_spec(
        {
            "name": "rec",
            "nodes": [
                {"id": "a", "type": "agent", "prompt": "hi", "model": "mock:m", "output_key": "t"}
            ],
        },
        llm=recorder,
    )
    assert first.output_keys["t"] == "hello-offline"
    assert cassette.is_file()
    replay = RecordedLLM(cassette)
    second = run_workflow_spec(
        {
            "name": "rec",
            "nodes": [
                {"id": "a", "type": "agent", "prompt": "hi", "model": "mock:m", "output_key": "t"}
            ],
        },
        llm=replay,
    )
    assert second.output_keys["t"] == "hello-offline"
    assert replay.calls  # drove complete()
    assert inner.calls  # only the recording pass hit the inner stand-in
    # replay must not call inner (no network / no second inner complete)
    assert len(inner.calls) == 1


def test_eval_harness_pass_and_fail() -> None:
    passing = EvalCase(
        name="pass-calc",
        workflow={
            "name": "eval-pass",
            "nodes": [
                {"id": "t", "type": "transform", "template": "ok-42", "output_key": "summary"}
            ],
        },
        expect_status="succeeded",
        expect_outputs={"summary": "ok-42"},
        expect_contains={"summary": "ok-"},
    )
    failing = EvalCase(
        name="fail-mismatch",
        workflow={
            "name": "eval-fail",
            "nodes": [
                {"id": "t", "type": "transform", "template": "wrong", "output_key": "summary"}
            ],
        },
        expect_status="succeeded",
        expect_outputs={"summary": "expected"},
    )
    report = run_eval([passing, failing])
    assert report.passed == 1
    assert report.failed == 1
    assert not report.ok
    by_name = {row.name: row for row in report.results}
    assert by_name["pass-calc"].passed
    assert not by_name["fail-mismatch"].passed
    with pytest.raises(AssertionError, match="eval failures"):
        report.assert_passing()


def test_eval_harness_file_fixture(tmp_path: Path, tmp_settings) -> None:
    wf = tmp_path / "tiny.yaml"
    wf.write_text(
        """
name: eval-file
nodes:
  - id: t
    type: transform
    template: "file-ok"
    output_key: summary
""",
        encoding="utf-8",
    )
    report = run_eval(
        [
            EvalCase(
                name="file",
                workflow=wf,
                expect_status="succeeded",
                expect_contains={"summary": "file-ok"},
            )
        ],
        settings=tmp_settings,
    )
    assert report.ok
    report.assert_passing()
