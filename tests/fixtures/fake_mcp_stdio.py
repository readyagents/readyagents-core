"""Tiny MCP stdio server for tests. Logs one spawn line, then serves `add`."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def _log_spawn() -> None:
    path = os.environ.get("FAKE_MCP_SPAWN_LOG")
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(f"{os.getpid()}\n")
        fh.flush()


def _run_sdk() -> None:
    try:
        from mcp.server import MCPServer as Server
    except ImportError:
        from mcp.server.fastmcp import FastMCP as Server  # type: ignore[no-redef]

    server = Server("fake")

    @server.tool(name="add", description="Return n plus one.")
    def add(n: int) -> str:
        return str(int(n) + 1)

    server.run(transport="stdio")


def _run_jsonrpc() -> None:
    """Speak enough JSON-RPC for initialize / tools/list / tools/call."""
    import json

    schema = {
        "type": "object",
        "properties": {"n": {"type": "integer"}},
        "required": ["n"],
    }

    def reply(msg_id: object, result: object) -> None:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}) + "\n")
        sys.stdout.flush()

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        method = message.get("method")
        msg_id = message.get("id")
        if method == "initialize":
            version = "2025-11-25"
            params = message.get("params") or {}
            if isinstance(params, dict) and params.get("protocolVersion"):
                version = str(params["protocolVersion"])
            reply(
                msg_id,
                {
                    "protocolVersion": version,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake", "version": "0.0.1"},
                },
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            reply(
                msg_id,
                {
                    "tools": [
                        {
                            "name": "add",
                            "description": "Return n plus one.",
                            "inputSchema": schema,
                        }
                    ]
                },
            )
        elif method == "tools/call":
            params = message.get("params") or {}
            args = params.get("arguments") if isinstance(params, dict) else {}
            if not isinstance(args, dict):
                args = {}
            n = int(args.get("n", 0))
            reply(
                msg_id,
                {"content": [{"type": "text", "text": str(n + 1)}], "isError": False},
            )
        elif msg_id is not None:
            reply(msg_id, {})


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.ERROR)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    _log_spawn()
    try:
        _run_sdk()
    except ImportError:
        _run_jsonrpc()


if __name__ == "__main__":
    main()
