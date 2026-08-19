from __future__ import annotations

from pathlib import Path

import pytest

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
    for expected in ("now", "calc", "json_get", "read_file", "write_file", "http_get", "run_workflow"):
        assert expected in by_name
    assert by_name["calc"].fn(expression="2 + 2 * 10") == "22"
    stamp = by_name["now"].fn()
    assert "T" in stamp
    assert by_name["json_get"].fn(data='{"value": 9}', path="value") == "9"
    written = by_name["write_file"].fn(path="note.txt", content="hello")
    assert Path(written).read_text(encoding="utf-8") == "hello"
    assert by_name["read_file"].fn(path="note.txt") == "hello"
