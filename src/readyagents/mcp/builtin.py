"""Python-native tools that work with zero extra servers."""

from __future__ import annotations

import ast
import json
import operator
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

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
_MAX_POW_EXP = 32


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
        current = current.decode("utf-8")
    if isinstance(current, str):
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
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise ToolError("http_get: url must start with http:// or https://")
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "readyagents/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT) as response:  # noqa: S310
            body = response.read(_MAX_HTTP_BYTES + 1)
    except urllib.error.URLError as exc:
        raise ToolError(f"http_get failed: {exc}") from exc
    if len(body) > _MAX_HTTP_BYTES:
        raise ToolError("http_get: response too large")
    return body.decode("utf-8", errors="replace")


def tool_read_file(path: str, *, workspace: Path) -> str:
    target = _sandbox_path(path, workspace)
    if not target.is_file():
        raise ToolError(f"read_file: not a file: {path}")
    try:
        return target.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ToolError(f"read_file: could not read {path}: {exc}") from exc


def tool_write_file(path: str, content: str, *, workspace: Path) -> str:
    target = _sandbox_path(path, workspace)
    if target.exists() and not target.is_file():
        raise ToolError(f"write_file: not a file: {path}")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / f".{target.name}.{uuid4().hex}.tmp"
        try:
            tmp.write_text(str(content), encoding="utf-8")
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
