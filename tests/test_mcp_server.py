from __future__ import annotations

import json
from pathlib import Path

import pytest

from readyagents.errors import MCPError
from readyagents.mcp.server import _create_server, construct_server, mcp_available

pytestmark = pytest.mark.skipif(not mcp_available(), reason="mcp extra not installed")


def test_mcp_server_constructs() -> None:
    server = _create_server("readyagents-test")
    assert server is not None
    assert hasattr(server, "tool")
    assert hasattr(server, "run")


def test_construct_server_exposes_builtin_tools(tmp_path: Path) -> None:
    server = construct_server(allow_http=False, workspace=tmp_path)
    assert server is not None
    assert hasattr(server, "tool")
    assert hasattr(server, "run")
    by_name = {t.name: t for t in server._tool_manager.list_tools()}
    for expected in (
        "now",
        "calc",
        "json_get",
        "json_set",
        "json_merge",
        "read_file",
        "write_file",
        "http_get",
        "run_workflow",
    ):
        assert expected in by_name
    assert by_name["calc"].fn(expression="2 + 2 * 10") == "22"
    stamp = by_name["now"].fn()
    assert "T" in stamp
    assert by_name["json_get"].fn(data='{"value": 9}', path="value") == "9"
    set_doc = by_name["json_set"].fn(
        data='{"user": {"name": "anon"}}', path="user.name", value="Ada"
    )
    assert json.loads(set_doc) == {"user": {"name": "Ada"}}
    merged = by_name["json_merge"].fn(data=set_doc, path="user", value='{"ok": true}')
    assert json.loads(merged) == {"user": {"name": "Ada", "ok": True}}
    written = by_name["write_file"].fn(path="note.txt", content="hello")
    assert Path(written).read_text(encoding="utf-8") == "hello"
    assert by_name["read_file"].fn(path="note.txt") == "hello"


def test_mcp_run_workflow_stays_in_workspace(tmp_path: Path, monkeypatch) -> None:
    from readyagents.config import clear_settings_cache

    clear_settings_cache()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("READYAGENTS_HOME", str(tmp_path / ".readyagents"))
    monkeypatch.setenv("READYAGENTS_WORKSPACE", str(tmp_path))
    example = Path(__file__).resolve().parents[1] / "examples" / "calc_pipeline.yaml"
    dest = tmp_path / "calc_pipeline.yaml"
    dest.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    server = construct_server(allow_http=False, workspace=tmp_path)
    by_name = {t.name: t for t in server._tool_manager.list_tools()}
    run_wf = by_name["run_workflow"].fn

    payload = json.loads(run_wf(path="calc_pipeline.yaml", inputs_json="{}"))
    assert payload["status"] == "succeeded"
    assert "calc_pipeline ok" in json.dumps(payload)

    with pytest.raises(MCPError, match="outside the workspace"):
        run_wf(path="/etc/passwd", inputs_json="{}")
    with pytest.raises(MCPError, match="outside the workspace"):
        run_wf(path="../escape.yaml", inputs_json="{}")
    clear_settings_cache()
