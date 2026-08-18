from __future__ import annotations

from typer.testing import CliRunner

from readyagents.cli import app

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


def test_run_calc_pipeline() -> None:
    result = runner.invoke(app, ["run", "examples/calc_pipeline.yaml", "--no-persist"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "succeeded" in result.stdout
    assert "calc_pipeline ok" in result.stdout


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
