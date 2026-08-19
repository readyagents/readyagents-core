from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from readyagents.cli import app
from readyagents.config import clear_settings_cache

runner = CliRunner()


def _run_id(text: str) -> str:
    match = re.search(r"run_id:\s*([0-9a-f]{16,})", text)
    if match:
        return match.group(1)
    match = re.search(r"Run ([0-9a-f]{16,}) —", text)
    if match:
        return match.group(1)
    raise AssertionError(f"no run id in:\n{text}")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_validate_ok_fixture() -> None:
    fixture = Path(__file__).resolve().parent / "fixtures" / "ok.yaml"
    result = runner.invoke(app, ["validate", str(fixture)])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
    assert "fixture_ok" in result.stdout
    assert "1 node(s)" in result.stdout
    assert "start=t" in result.stdout


def test_validate_calc_pipeline() -> None:
    result = runner.invoke(app, ["validate", "examples/calc_pipeline.yaml"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
    assert "calc_pipeline" in result.stdout
    assert "add" in result.stdout
    assert "stamp" in result.stdout


def test_validate_invalid_workflow(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        "name: bad\nnodes:\n  - id: a\n    type: transform\n    template: x\n    next: missing\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["validate", str(path)])
    assert result.exit_code == 1
    text = result.stdout + result.stderr
    assert "WorkflowError" in text
    assert "Invalid workflow" in text


def test_validate_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", str(tmp_path / "nope.yaml")])
    assert result.exit_code != 0


def test_init_writes_template_when_no_example(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    dest = tmp_path / ".env"
    result = runner.invoke(app, ["init", "--dest", str(dest)])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert dest.is_file()
    text = dest.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=" in text
    assert "ANTHROPIC_API_KEY=" in text
    assert "READYAGENTS_DEFAULT_MODEL=" in text
    assert "sk-" not in text
    assert "Wrote" in result.stdout
    assert "readyagents new" in result.stdout


def test_init_copies_env_example(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    example = tmp_path / ".env.example"
    example.write_text("# copied-from-example\nOPENAI_API_KEY=\n", encoding="utf-8")
    dest = tmp_path / ".env"
    result = runner.invoke(app, ["init", "--dest", str(dest)])
    assert result.exit_code == 0, result.stdout + result.stderr
    copied = dest.read_text(encoding="utf-8")
    assert copied == example.read_text(encoding="utf-8")
    assert "copied-from-example" in copied
    assert "sk-" not in copied
    assert "Wrote" in result.stdout


def test_init_does_not_overwrite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    dest = tmp_path / ".env"
    dest.write_text("KEEP=1\n", encoding="utf-8")
    result = runner.invoke(app, ["init", "--dest", str(dest)])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert dest.read_text(encoding="utf-8") == "KEEP=1\n"
    assert "already exists" in result.stdout
    assert "left unchanged" in result.stdout


def test_init_default_dest(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.stdout + result.stderr
    dest = tmp_path / ".env"
    assert dest.is_file()
    assert "OPENAI_API_KEY=" in dest.read_text(encoding="utf-8")
    assert "sk-" not in dest.read_text(encoding="utf-8")


def test_reject_oneshot_cli() -> None:
    result = runner.invoke(
        app, ["run", "examples/approval_gate.yaml", "--reject", "gate", "--no-persist"]
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "succeeded" in result.stdout
    assert "approval_gate denied" in result.stdout
    assert "approval_gate ok" not in result.stdout


def test_reject_resume_cli(tmp_path: Path, monkeypatch) -> None:
    clear_settings_cache()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("READYAGENTS_HOME", str(tmp_path / ".readyagents"))
    example = _repo_root() / "examples" / "approval_gate.yaml"
    paused = runner.invoke(app, ["run", str(example)])
    assert paused.exit_code == 2, paused.stdout + paused.stderr
    text = paused.stdout + paused.stderr
    assert "ApprovalRequired" in text or "Approval required" in text
    listed = runner.invoke(app, ["runs", "list"])
    assert listed.exit_code == 0, listed.stdout + listed.stderr
    run_id = _run_id(listed.stdout + paused.stdout)
    rejected = runner.invoke(app, ["resume", run_id, "--reject", "gate"])
    assert rejected.exit_code == 0, rejected.stdout + rejected.stderr
    assert "succeeded" in rejected.stdout
    assert "approval_gate denied" in rejected.stdout
    clear_settings_cache()


def test_mcp_help_lists_serve() -> None:
    result = runner.invoke(app, ["mcp", "--help"])
    assert result.exit_code == 0
    assert "serve" in result.stdout


def test_mcp_serve_invokes_stdio(monkeypatch) -> None:
    # Live `mcp serve` blocks on stdio (server.run(transport="stdio")). Patch the
    # transport so the CLI wiring is covered without hanging the suite.
    called = {"n": 0}

    def fake_serve() -> None:
        called["n"] += 1

    monkeypatch.setattr("readyagents.mcp.server.serve_stdio", fake_serve)
    result = runner.invoke(app, ["mcp", "serve"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert called["n"] == 1
