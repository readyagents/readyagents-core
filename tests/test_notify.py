from __future__ import annotations

from pathlib import Path

import pytest

from readyagents import __version__
from readyagents.errors import ApprovalRequired, ToolError
from readyagents.notify import post_json
from readyagents.workflow.runner import run_workflow_file


def _gate_workflow(on_pause_url: str) -> str:
    return f"""
name: notify-ssrf
on_pause_url: {on_pause_url}
nodes:
  - id: gate
    type: approval
    prompt: "ship?"
    then: ok
    else: denied
  - id: ok
    type: transform
    template: "ok"
    output_key: summary
  - id: denied
    type: transform
    template: "no"
    output_key: summary
"""


def test_post_json_blocks_private_and_loopback_hosts() -> None:
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
        "http://metadata.google.internal/",
    )
    for url in blocked:
        with pytest.raises(ToolError, match="not allowed"):
            post_json(url, {"event": "approval_required"})


def test_post_json_blocks_metadata_hostname() -> None:
    with pytest.raises(ToolError, match="not allowed"):
        post_json("http://metadata.google.internal/computeMetadata/v1/", {"event": "x"})


def test_post_json_raises_before_loopback_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    connected: list[str] = []

    def fake_create(
        address: tuple, timeout: object = None, source_address: object = None
    ) -> object:
        connected.append(address[0])
        raise OSError("should not connect")

    monkeypatch.setattr("socket.create_connection", fake_create)
    with pytest.raises(ToolError, match="not allowed"):
        post_json("http://127.0.0.1/", {"event": "x"})
    assert connected == []
    assert "127.0.0.1" not in connected


def test_pause_notify_loopback_still_pauses(
    tmp_path: Path, tmp_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    connected: list[str] = []

    def fake_create(
        address: tuple, timeout: object = None, source_address: object = None
    ) -> object:
        connected.append(address[0])
        raise OSError("should not connect")

    monkeypatch.setattr("socket.create_connection", fake_create)
    path = tmp_path / "notify.yaml"
    path.write_text(_gate_workflow("http://127.0.0.1/"), encoding="utf-8")
    with pytest.raises(ApprovalRequired):
        run_workflow_file(path, settings=tmp_settings, persist=True)
    assert "127.0.0.1" not in connected
    assert connected == []


def test_post_json_posts_json_to_pinned_public_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "readyagents.mcp.builtin.socket.getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("8.8.8.8", 0))],
    )
    seen: dict[str, object] = {}

    def fake_exchange(
        scheme: str,
        hostname: str,
        ip: str,
        port: int,
        path: str,
        **kwargs: object,
    ) -> tuple[int, bytes, str | None]:
        seen["scheme"] = scheme
        seen["ip"] = ip
        seen["host"] = hostname
        seen["path"] = path
        seen["method"] = kwargs.get("method", "GET")
        seen["body"] = kwargs.get("body")
        seen["headers"] = kwargs.get("headers")
        seen["timeout"] = kwargs.get("timeout")
        return 204, b"", None

    monkeypatch.setattr("readyagents.notify._http_exchange", fake_exchange)
    post_json("https://hooks.example/pause?x=1", {"event": "approval_required"})
    assert seen["scheme"] == "https"
    assert seen["ip"] == "8.8.8.8"
    assert seen["host"] == "hooks.example"
    assert seen["path"] == "/pause?x=1"
    assert seen["method"] == "POST"
    assert seen["timeout"] == 5.0
    body = seen["body"]
    assert isinstance(body, bytes) and b"approval_required" in body
    headers = seen["headers"]
    assert isinstance(headers, dict)
    assert headers["Content-Type"] == "application/json"
    assert headers["User-Agent"] == f"readyagents/{__version__}"


def test_post_json_pins_resolved_ip_against_rebind(monkeypatch: pytest.MonkeyPatch) -> None:
    resolves = {"n": 0}

    def fake_gai(*args: object, **kwargs: object) -> list:
        resolves["n"] += 1
        if resolves["n"] == 1:
            return [(0, 0, 0, "", ("8.8.8.8", 0))]
        return [(0, 0, 0, "", ("127.0.0.1", 0))]

    connected: list[str] = []

    def fake_create(
        address: tuple, timeout: object = None, source_address: object = None
    ) -> object:
        connected.append(address[0])
        raise OSError("pinned")

    monkeypatch.setattr("readyagents.mcp.builtin.socket.getaddrinfo", fake_gai)
    monkeypatch.setattr("readyagents.mcp.builtin.socket.create_connection", fake_create)
    with pytest.raises(OSError, match="pinned"):
        post_json("https://rebind.example/", {"event": "x"})
    assert connected == ["8.8.8.8"]
    assert resolves["n"] == 1


def test_post_json_refuses_redirect_to_private(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "readyagents.mcp.builtin.socket.getaddrinfo",
        lambda *a, **k: [(0, 0, 0, "", ("8.8.8.8", 0))],
    )

    def fake_exchange(
        scheme: str, hostname: str, ip: str, port: int, path: str, **kwargs: object
    ) -> tuple[int, bytes, str | None]:
        return 302, b"", "http://169.254.169.254/latest/meta-data/"

    monkeypatch.setattr("readyagents.notify._http_exchange", fake_exchange)
    with pytest.raises(ToolError, match="not allowed"):
        post_json("https://example.com/start", {"event": "x"})
