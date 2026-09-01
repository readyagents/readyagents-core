from __future__ import annotations

import re
import shutil
from pathlib import Path

from typer.testing import CliRunner

from readyagents.cli import app
from readyagents.config import clear_settings_cache

runner = CliRunner()


def _plain(text: str) -> str:
    """Strip ANSI and whitespace so Rich wrapping cannot hide tokens."""
    return re.sub(r"\s+", "", re.sub(r"\x1b\[[0-9;]*m", "", text))


def _run_id(text: str) -> str:
    blob = _plain(text)
    match = re.search(r"run_id:([0-9a-f]{16,})", blob)
    if match:
        return match.group(1)
    match = re.search(r"Run([0-9a-f]{16,})—", blob)
    if match:
        return match.group(1)
    raise AssertionError(f"no run id in:\n{text}")


def _copy_example(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parents[1] / "examples" / "gated_write.yaml"
    dest = tmp_path / "gated_write.yaml"
    shutil.copy(src, dest)
    return dest


def _stamp(tmp_path: Path) -> Path:
    return tmp_path / "gated.txt"


def test_pause_does_not_write_then_approve_writes(tmp_path: Path, monkeypatch) -> None:
    """Pause is exit 2 and gated.txt is absent; --approve gate writes once."""
    clear_settings_cache()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("READYAGENTS_HOME", str(tmp_path / ".readyagents"))
    wf = _copy_example(tmp_path)
    target = _stamp(tmp_path)

    paused = runner.invoke(app, ["run", str(wf)])
    assert paused.exit_code == 2, paused.stdout + paused.stderr
    text = paused.stdout + paused.stderr
    assert "ApprovalRequired" in text or "Approval required" in text
    assert not target.exists()

    run_id = _run_id(text)
    resumed = runner.invoke(app, ["resume", run_id, "--approve", "gate"])
    assert resumed.exit_code == 0, resumed.stdout + resumed.stderr
    assert "succeeded" in resumed.stdout
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "gated_write ok: 42\n"
    clear_settings_cache()


def test_reject_resume_never_writes(tmp_path: Path, monkeypatch) -> None:
    clear_settings_cache()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("READYAGENTS_HOME", str(tmp_path / ".readyagents"))
    wf = _copy_example(tmp_path)
    target = _stamp(tmp_path)

    paused = runner.invoke(app, ["run", str(wf)])
    assert paused.exit_code == 2, paused.stdout + paused.stderr
    assert not target.exists()
    run_id = _run_id(paused.stdout + paused.stderr)

    rejected = runner.invoke(app, ["resume", run_id, "--reject", "gate"])
    assert rejected.exit_code == 0, rejected.stdout + rejected.stderr
    assert "succeeded" in rejected.stdout
    assert "gated_write denied" in rejected.stdout
    assert not target.exists()
    clear_settings_cache()


def test_oneshot_reject_never_writes(tmp_path: Path, monkeypatch) -> None:
    clear_settings_cache()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("READYAGENTS_HOME", str(tmp_path / ".readyagents"))
    wf = _copy_example(tmp_path)
    target = _stamp(tmp_path)

    result = runner.invoke(app, ["run", str(wf), "--reject", "gate"])
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "gated_write denied" in result.stdout
    assert not target.exists()
    clear_settings_cache()
