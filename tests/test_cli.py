from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from readyagents.cli import app
from readyagents.config import clear_settings_cache

runner = CliRunner()


def test_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.stdout
    assert "validate" in result.stdout


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_packs_none_installed() -> None:
    result = runner.invoke(app, ["packs"])
    assert result.exit_code == 0
    assert "No packs installed" in result.stdout


def test_run_calc_pipeline() -> None:
    result = runner.invoke(app, ["run", "examples/calc_pipeline.yaml", "--no-persist"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "succeeded" in result.stdout
    assert "calc_pipeline ok" in result.stdout


def test_run_agent_workflow_without_keys_fails_byok(tmp_path, monkeypatch) -> None:
    clear_settings_cache()
    monkeypatch.chdir(tmp_path)
    for key in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "READYAGENTS_OPENAI_API_KEY",
        "READYAGENTS_ANTHROPIC_API_KEY",
        "OPENAI_COMPAT_API_KEY",
        "READYAGENTS_OPENAI_COMPAT_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    example = Path(__file__).resolve().parents[1] / "examples" / "research_brief.yaml"
    result = runner.invoke(
        app,
        ["run", str(example), "--no-persist", "--input", "topic=x"],
    )
    assert result.exit_code == 1
    text = result.stdout + result.stderr
    assert "BYOK" in text
    assert "OPENAI_API_KEY" in text
    clear_settings_cache()


def test_dry_run_research_brief() -> None:
    result = runner.invoke(
        app,
        [
            "run",
            "examples/research_brief.yaml",
            "--dry-run",
            "--no-persist",
            "--input",
            "topic=test",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "[dry-run]" in result.stdout
