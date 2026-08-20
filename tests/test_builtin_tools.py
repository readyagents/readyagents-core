from __future__ import annotations

import urllib.request
from pathlib import Path

import pytest

from readyagents.errors import ToolError
from readyagents.mcp.builtin import (
    tool_calc,
    tool_json_get,
    tool_now,
    tool_read_file,
    tool_write_file,
)
from readyagents.tools import default_registry
from readyagents.workflow.runner import run_workflow_file


def test_now_iso() -> None:
    value = tool_now()
    assert "T" in value
    assert value.endswith("Z") or "+" in value


def test_calc_arithmetic() -> None:
    assert tool_calc("2 + 2 * 10") == 22
    assert tool_calc("10 // 3") == 3
    assert tool_calc("-4 + 1") == -3


def test_calc_rejects_names() -> None:
    with pytest.raises(ToolError):
        tool_calc("__import__('os').system('pwd')")
    with pytest.raises(ToolError):
        tool_calc("2 ** 99")


def test_json_get_dotted() -> None:
    data = '{"a": {"b": [0, {"c": 7}]}}'
    assert tool_json_get(data, "a.b.1.c") == 7
    assert tool_json_get({"x": 1}, "x") == 1
    with pytest.raises(ToolError):
        tool_json_get({"x": 1}, "nope")


def test_file_sandbox(tmp_path: Path) -> None:
    inside = tmp_path / "note.txt"
    tool_write_file("note.txt", "hello", workspace=tmp_path)
    assert inside.read_text(encoding="utf-8") == "hello"
    assert tool_read_file("note.txt", workspace=tmp_path) == "hello"
    with pytest.raises(ToolError):
        tool_read_file("../outside.txt", workspace=tmp_path)


def test_file_sandbox_rejects_absolute_and_write_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("nope", encoding="utf-8")
    with pytest.raises(ToolError, match="outside"):
        tool_read_file(str(secret), workspace=workspace)
    with pytest.raises(ToolError, match="outside"):
        tool_write_file(str(secret), "overwrite", workspace=workspace)
    with pytest.raises(ToolError, match="outside"):
        tool_write_file("../escaped.txt", "x", workspace=workspace)
    assert secret.read_text(encoding="utf-8") == "nope"
    assert not (tmp_path / "escaped.txt").exists()


def test_file_sandbox_rejects_empty_and_workspace_root(tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="workspace"):
        tool_read_file("", workspace=tmp_path)
    with pytest.raises(ToolError, match="workspace"):
        tool_read_file(".", workspace=tmp_path)
    with pytest.raises(ToolError, match="workspace"):
        tool_write_file("..", "x", workspace=tmp_path)
    (tmp_path / "sub").mkdir()
    with pytest.raises(ToolError, match="not a file"):
        tool_read_file("sub", workspace=tmp_path)
    with pytest.raises(ToolError, match="not a file"):
        tool_write_file("sub", "x", workspace=tmp_path)


def test_write_file_is_atomic_and_nested(tmp_path: Path) -> None:
    written = tool_write_file("a/b/out.txt", "hello", workspace=tmp_path)
    target = tmp_path / "a" / "b" / "out.txt"
    assert Path(written) == target
    assert target.read_text(encoding="utf-8") == "hello"
    assert list(tmp_path.rglob(".*.tmp")) == []
    tool_write_file("a/b/out.txt", "replaced", workspace=tmp_path)
    assert target.read_text(encoding="utf-8") == "replaced"
    assert list(tmp_path.rglob(".*.tmp")) == []


def test_file_sandbox_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("secret", encoding="utf-8")
    link = workspace / "link.txt"
    try:
        link.symlink_to(victim)
    except OSError:
        pytest.skip("symlinks not supported")
    with pytest.raises(ToolError, match="outside"):
        tool_read_file("link.txt", workspace=workspace)
    with pytest.raises(ToolError, match="outside"):
        tool_write_file("link.txt", "changed", workspace=workspace)
    assert victim.read_text(encoding="utf-8") == "secret"


def test_http_disabled_by_default(tmp_path: Path) -> None:
    registry = default_registry(allow_http=False, workspace=tmp_path)
    with pytest.raises(ToolError, match="disabled"):
        registry.get("http_get").run(url="https://example.com")


def test_http_get_rejects_non_http_schemes() -> None:
    from readyagents.mcp.builtin import tool_http_get

    for url in ("file:///etc/passwd", "ftp://example.com/x", "not-a-url", ""):
        with pytest.raises(ToolError, match="http://"):
            tool_http_get(url, allow_http=True)


def test_http_get_rejects_userinfo_and_empty_host() -> None:
    from readyagents.mcp.builtin import tool_http_get

    with pytest.raises(ToolError, match="userinfo"):
        tool_http_get("https://user:pass@example.com/", allow_http=True)
    with pytest.raises(ToolError, match="host"):
        tool_http_get("https:///no-host", allow_http=True)


def test_http_get_blocks_private_and_loopback_hosts() -> None:
    from readyagents.mcp.builtin import tool_http_get

    blocked = (
        "http://127.0.0.1/",
        "http://localhost/secret",
        "http://[::1]/",
        "https://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/admin",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://[::ffff:127.0.0.1]/",
        "http://2130706433/",
        "http://foo.localhost/",
    )
    for url in blocked:
        with pytest.raises(ToolError, match="not allowed"):
            tool_http_get(url, allow_http=True)


def test_http_get_fetches_public_url(monkeypatch: pytest.MonkeyPatch) -> None:
    from readyagents.mcp.builtin import tool_http_get

    monkeypatch.setattr(
        "readyagents.mcp.builtin.socket.getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("8.8.8.8", 0))],
    )

    class _Resp:
        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, n: int) -> bytes:
            return b"hello-public"

    class _Opener:
        def open(self, request: object, timeout: object = None) -> _Resp:
            headers = getattr(request, "headers", {})
            ua = headers.get("User-agent") or headers.get("User-Agent")
            assert ua == "readyagents/0.2.0"
            return _Resp()

    monkeypatch.setattr("urllib.request.build_opener", lambda *a, **k: _Opener())
    assert tool_http_get("https://example.com/page", allow_http=True) == "hello-public"


def test_http_get_refuses_redirect_to_private(monkeypatch: pytest.MonkeyPatch) -> None:
    from readyagents.mcp.builtin import _SafeRedirectHandler

    monkeypatch.setattr(
        "readyagents.mcp.builtin.socket.getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("8.8.8.8", 0))],
    )
    handler = _SafeRedirectHandler()
    req = urllib.request.Request("https://example.com/start")
    with pytest.raises(ToolError, match="not allowed"):
        handler.redirect_request(
            req, None, 302, "Found", {}, "http://169.254.169.254/latest/meta-data/"
        )
    # Public hosts still pass the redirect check (no network).
    forwarded = handler.redirect_request(req, None, 302, "Found", {}, "https://example.com/next")
    assert forwarded is not None
    assert forwarded.full_url.startswith("https://example.com/next")


def test_default_registry_includes_builtins(tmp_path: Path) -> None:
    registry = default_registry(allow_http=False, workspace=tmp_path)
    for name in ("now", "calc", "json_get", "read_file", "write_file", "http_get"):
        assert name in registry.names()
    assert registry.get("calc").run(expression="1 + 2 * 3") == 7


def test_calc_pipeline_example(examples_dir: Path, tmp_settings) -> None:
    path = examples_dir / "calc_pipeline.yaml"
    state = run_workflow_file(path, settings=tmp_settings, persist=True)
    assert state.status == "succeeded"
    assert state.output_keys["extracted"] == 22
    assert "ok" in str(state.output_keys["summary"])
    assert all(r.node_id != "bad" for r in state.results)
    runs = list(tmp_settings.runs_dir().glob("*.json"))
    assert len(runs) == 1


def test_research_brief_dry_run_no_keys(examples_dir: Path, tmp_settings) -> None:
    state = run_workflow_file(
        examples_dir / "research_brief.yaml",
        inputs={"topic": "test"},
        dry_run=True,
        settings=tmp_settings,
        persist=False,
    )
    assert state.status == "succeeded"
    assert any("[dry-run]" in str(v) for v in state.node_outputs.values())


def test_calc_rejects_long_expression(monkeypatch: pytest.MonkeyPatch) -> None:
    from readyagents.mcp import builtin as builtin_mod

    monkeypatch.setattr(builtin_mod, "_MAX_CALC_CHARS", 8)
    with pytest.raises(ToolError, match="too long"):
        tool_calc("1 + 1 + 1")


def test_json_get_rejects_large_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    from readyagents.mcp import builtin as builtin_mod

    monkeypatch.setattr(builtin_mod, "_MAX_JSON_BYTES", 8)
    with pytest.raises(ToolError, match="too large"):
        tool_json_get("{\"a\": 12345}", "a")
    with pytest.raises(ToolError, match="too large"):
        tool_json_get(b"{\"a\": 12345}", "a")


def test_read_file_rejects_large_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from readyagents.mcp import builtin as builtin_mod

    monkeypatch.setattr(builtin_mod, "_MAX_FILE_BYTES", 8)
    (tmp_path / "big.txt").write_text("0123456789", encoding="utf-8")
    with pytest.raises(ToolError, match="too large"):
        tool_read_file("big.txt", workspace=tmp_path)


def test_write_file_rejects_large_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from readyagents.mcp import builtin as builtin_mod

    monkeypatch.setattr(builtin_mod, "_MAX_FILE_BYTES", 8)
    with pytest.raises(ToolError, match="too large"):
        tool_write_file("out.txt", "0123456789", workspace=tmp_path)
    assert not (tmp_path / "out.txt").exists()

