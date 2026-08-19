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


def test_readme_keyless_smoke(tmp_path: Path, monkeypatch) -> None:
    """README 60-second path, persist on, no API keys."""
    clear_settings_cache()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("READYAGENTS_HOME", str(tmp_path / ".readyagents"))
    root = Path(__file__).resolve().parents[1]

    calc = runner.invoke(app, ["run", str(root / "examples" / "calc_pipeline.yaml")])
    assert calc.exit_code == 0, calc.stdout + calc.stderr
    assert "succeeded" in calc.stdout
    assert "calc_pipeline ok" in calc.stdout

    listed = runner.invoke(app, ["runs", "list"])
    assert listed.exit_code == 0, listed.stdout + listed.stderr
    assert "calc_pipeline" in listed.stdout
    run_id = _run_id(listed.stdout + calc.stdout)

    report = runner.invoke(app, ["runs", "report", run_id])
    assert report.exit_code == 0, report.stdout + report.stderr
    html = tmp_path / f"{run_id}.html"
    assert html.is_file()
    assert run_id in html.read_text(encoding="utf-8")

    dest = tmp_path / "my-flow"
    created = runner.invoke(
        app, ["new", "my-flow", "--dest", str(dest), "--template", "pipeline"]
    )
    assert created.exit_code == 0, created.stdout + created.stderr
    assert (dest / "workflow.yaml").is_file()
    assert (dest / "README.md").is_file()
    assert (dest / ".env.example").is_file()

    gate = runner.invoke(
        app, ["run", str(root / "examples" / "approval_gate.yaml"), "--approve", "gate"]
    )
    assert gate.exit_code == 0, gate.stdout + gate.stderr
    assert "approval_gate ok" in gate.stdout

    composed = runner.invoke(
        app, ["run", str(root / "examples" / "composed_gate.yaml"), "--approve", "gate"]
    )
    assert composed.exit_code == 0, composed.stdout + composed.stderr
    assert "composed_gate ok" in composed.stdout
    clear_settings_cache()
