"""Python-native tools that work with zero extra servers."""

from __future__ import annotations

import ast
import http.client
import ipaddress
import json
import operator
import os
import socket
import ssl
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import ParseResult, urljoin, urlparse
from uuid import uuid4

from readyagents import __version__
from readyagents.errors import ToolError
from readyagents.tools import FunctionTool, Tool

_BINOPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_HTTP_TIMEOUT = 20
_MAX_HTTP_BYTES = 1_000_000
_MAX_HTTP_REDIRECTS = 5
_MAX_POW_EXP = 32
_MAX_FILE_BYTES = 1_000_000
_MAX_JSON_BYTES = 1_000_000
_MAX_CALC_CHARS = 256
_BLOCKED_HOST_NAMES = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata.google.internal",
    }
)


def builtin_tools(*, allow_http: bool, workspace: Path) -> list[Tool]:
    workspace = Path(workspace).resolve()
    tools: list[Tool] = [
        FunctionTool(
            name="now",
            description="Current UTC time as ISO-8601.",
            schema={"type": "object", "properties": {}},
            handler=tool_now,
        ),
        FunctionTool(
            name="calc",
            description="Evaluate a safe arithmetic expression (e.g. '2 + 2 * 10').",
            schema={
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
            handler=tool_calc,
        ),
        FunctionTool(
            name="json_get",
            description="Extract a dotted path from JSON text or an object.",
            schema={
                "type": "object",
                "properties": {
                    "data": {},
                    "path": {"type": "string"},
                },
                "required": ["data", "path"],
            },
            handler=tool_json_get,
        ),
        FunctionTool(
            name="read_file",
            description="Read a UTF-8 text file sandboxed to the workflow workspace.",
            schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            handler=lambda path: tool_read_file(path, workspace=workspace),
        ),
        FunctionTool(
            name="write_file",
            description="Write a UTF-8 text file sandboxed to the workflow workspace.",
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            handler=lambda path, content: tool_write_file(path, content, workspace=workspace),
        ),
        FunctionTool(
            name="http_get",
            description="HTTP GET a URL. Disabled unless allow_http is enabled.",
            schema={
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
            handler=lambda url: tool_http_get(url, allow_http=allow_http),
        ),
    ]
    return tools


def tool_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def tool_calc(expression: str | int | float) -> int | float:
    if isinstance(expression, (int, float)):
        return expression
    text = str(expression).strip()
    if not text:
        raise ToolError("calc: empty expression")
    if len(text) > _MAX_CALC_CHARS:
        raise ToolError(f"calc: expression too long (max {_MAX_CALC_CHARS} characters)")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as exc:
        raise ToolError(f"calc: invalid expression: {exc}") from exc
    return _eval_ast(tree.body)


def _eval_ast(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        if isinstance(node.value, bool):
            raise ToolError("calc: only numbers and + - * / // % ** are allowed")
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval_ast(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left = _eval_ast(node.left)
        right = _eval_ast(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POW_EXP:
            raise ToolError("calc: exponent too large")
        try:
            return _BINOPS[type(node.op)](left, right)
        except ZeroDivisionError as exc:
            raise ToolError("calc: division by zero") from exc
    if isinstance(node, ast.Expr):
        return _eval_ast(node.value)
    raise ToolError("calc: only numbers and + - * / // % ** are allowed")


def tool_json_get(data: Any, path: str) -> Any:
    current: Any = data
    if isinstance(current, (bytes, bytearray)):
        if len(current) > _MAX_JSON_BYTES:
            raise ToolError(f"json_get: data too large (max {_MAX_JSON_BYTES} bytes)")
        current = current.decode("utf-8")
    if isinstance(current, str):
        if len(current.encode("utf-8")) > _MAX_JSON_BYTES:
            raise ToolError(f"json_get: data too large (max {_MAX_JSON_BYTES} bytes)")
        text = current.strip()
        if text:
            try:
                current = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ToolError(f"json_get: data is not valid JSON: {exc}") from exc
    for part in str(path).split("."):
        if part == "":
            continue
        if isinstance(current, dict):
            if part not in current:
                raise ToolError(f"json_get: path not found: {path}")
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError) as exc:
                raise ToolError(f"json_get: path not found: {path}") from exc
            continue
        raise ToolError(f"json_get: path not found: {path}")
    return current


def tool_http_get(url: str, *, allow_http: bool) -> str:
    if not allow_http:
        raise ToolError(
            "http_get is disabled. Set READYAGENTS_ALLOW_HTTP=1 or set allow_http: true "
            "on the workflow if you intend to fetch URLs."
        )
    current = url.strip() if isinstance(url, str) else ""
    for _ in range(_MAX_HTTP_REDIRECTS + 1):
        parsed = _assert_public_http_url(current)
        assert parsed.hostname is not None
        ips = _resolve_public_ips(parsed.hostname)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        last_err: Exception | None = None
        status = 0
        body = b""
        location: str | None = None
        for ip in ips:
            try:
                status, body, location = _http_exchange(
                    parsed.scheme, parsed.hostname, ip, port, path
                )
                last_err = None
                break
            except (TimeoutError, OSError) as exc:
                last_err = exc
        if last_err is not None:
            raise ToolError(f"http_get failed: {last_err}") from last_err
        if status in {301, 302, 303, 307, 308} and location:
            current = urljoin(current, location)
            continue
        if status >= 400:
            raise ToolError(f"http_get failed: HTTP Error {status}:")
        if len(body) > _MAX_HTTP_BYTES:
            raise ToolError("http_get: response too large")
        return body.decode("utf-8", errors="replace")
    raise ToolError("http_get: too many redirects")


def _http_exchange(
    scheme: str, hostname: str, ip: str, port: int, path: str
) -> tuple[int, bytes, str | None]:
    timeout = _HTTP_TIMEOUT
    headers = {"User-Agent": f"readyagents/{__version__}"}
    if scheme == "https":
        ctx = ssl.create_default_context()
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(
            hostname, port, timeout=timeout, context=ctx
        )

        def connect() -> None:
            sock = socket.create_connection((ip, port), timeout)
            conn.sock = ctx.wrap_socket(sock, server_hostname=hostname)

        conn.connect = connect  # type: ignore[method-assign]
    else:
        conn = http.client.HTTPConnection(hostname, port, timeout=timeout)

        def connect() -> None:
            conn.sock = socket.create_connection((ip, port), timeout)

        conn.connect = connect  # type: ignore[method-assign]
    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read(_MAX_HTTP_BYTES + 1)
        return resp.status, body, resp.getheader("Location")
    finally:
        conn.close()


def _assert_public_http_url(url: object) -> ParseResult:
    if not isinstance(url, str) or not url.strip():
        raise ToolError("http_get: url must start with http:// or https://")
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ToolError("http_get: url must start with http:// or https://")
    if parsed.username is not None or parsed.password is not None:
        raise ToolError("http_get: URLs with userinfo are not allowed")
    if not parsed.hostname:
        raise ToolError("http_get: URL must include a host")
    return parsed


def _resolve_public_ips(host: str) -> list[str]:
    name = host.strip().lower().rstrip(".")
    not_allowed = (
        f"http_get: host '{host}' is not allowed "
        "(loopback, private, link-local, or metadata addresses)"
    )
    if name in _BLOCKED_HOST_NAMES or name.endswith(".localhost") or name.endswith(".local"):
        raise ToolError(not_allowed)
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        ip = None
    if ip is not None:
        if _ip_is_blocked(ip):
            raise ToolError(not_allowed)
        return [str(ip)]
    try:
        infos = socket.getaddrinfo(name, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ToolError(f"http_get: could not resolve host '{host}'") from exc
    if not infos:
        raise ToolError(f"http_get: could not resolve host '{host}'")
    ips: list[str] = []
    seen: set[str] = set()
    for info in infos:
        addr = info[4][0]
        try:
            parsed_ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _ip_is_blocked(parsed_ip):
            raise ToolError(not_allowed)
        text = str(parsed_ip)
        if text not in seen:
            seen.add(text)
            ips.append(text)
    if not ips:
        raise ToolError(f"http_get: could not resolve host '{host}'")
    return ips


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def tool_read_file(path: str, *, workspace: Path) -> str:
    target = _sandbox_path(path, workspace)
    if not target.is_file():
        raise ToolError(f"read_file: not a file: {path}")
    try:
        size = target.stat().st_size
        if size > _MAX_FILE_BYTES:
            raise ToolError(
                f"read_file: file too large ({size} bytes, max {_MAX_FILE_BYTES})"
            )
        return target.read_text(encoding="utf-8")
    except ToolError:
        raise
    except (OSError, UnicodeError) as exc:
        raise ToolError(f"read_file: could not read {path}: {exc}") from exc


def tool_write_file(path: str, content: str, *, workspace: Path) -> str:
    target = _sandbox_path(path, workspace)
    if target.exists() and not target.is_file():
        raise ToolError(f"write_file: not a file: {path}")
    payload = str(content)
    size = len(payload.encode("utf-8"))
    if size > _MAX_FILE_BYTES:
        raise ToolError(
            f"write_file: content too large ({size} bytes, max {_MAX_FILE_BYTES})"
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / f".{target.name}.{uuid4().hex}.tmp"
        try:
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
    except OSError as exc:
        raise ToolError(f"write_file: could not write {path}: {exc}") from exc
    return str(target)


def _sandbox_path(path: str, workspace: Path) -> Path:
    workspace = Path(workspace).resolve()
    text = str(path).strip()
    if not text or text in {".", ".."}:
        raise ToolError("Path must be a file inside the workspace")
    if "\x00" in text:
        raise ToolError("Path contains invalid characters")
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(workspace) or resolved == workspace:
        raise ToolError(f"Path '{path}' is outside the workspace")
    return resolved
