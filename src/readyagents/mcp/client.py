"""Connect to MCP servers declared in a workflow (optional extra)."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from readyagents.errors import MCPError
from readyagents.tools import FunctionTool, Tool
from readyagents.workflow.schema import MCPServerSpec

# Stdio children get a narrow env. API keys are not inherited unless the
# workflow sets them under mcp_servers.<name>.env.
_PASSTHROUGH_ENV = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LC_MESSAGES",
        "TERM",
        "TMPDIR",
        "TEMP",
        "TMP",
        "USER",
        "LOGNAME",
        "SHELL",
    }
)


def mcp_child_env(spec: MCPServerSpec) -> dict[str, str]:
    """Env mapping passed to an MCP stdio subprocess."""
    env = {key: value for key, value in os.environ.items() if key in _PASSTHROUGH_ENV}
    if spec.env:
        env.update(spec.env)
    return env


def mcp_available() -> bool:
    try:
        import mcp  # noqa: F401

        return True
    except ImportError:
        return False


class MCPClient:
    """Lazy stdio MCP client. Safe to construct when the extra is missing."""

    def __init__(self, servers: dict[str, MCPServerSpec]) -> None:
        self._servers = servers
        self._tools: dict[str, Tool] | None = None

    def tools(self) -> dict[str, Tool]:
        if not self._servers:
            return {}
        if self._tools is None:
            self._tools = _load_tools_sync(self._servers)
        return self._tools

    def close(self) -> None:
        self._tools = None


def _load_tools_sync(servers: dict[str, MCPServerSpec]) -> dict[str, Tool]:
    if not mcp_available():
        names = ", ".join(servers)
        raise MCPError(
            f"Workflow declares MCP servers ({names}) but the mcp extra is not installed. "
            "Run: pip install 'readyagents[mcp]'"
        )
    return asyncio.run(_load_tools(servers))


async def _load_tools(servers: dict[str, MCPServerSpec]) -> dict[str, Tool]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    tools: dict[str, Tool] = {}
    for name, spec in servers.items():
        params = StdioServerParameters(
            command=spec.command,
            args=spec.args,
            env=mcp_child_env(spec),
            cwd=spec.cwd,
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    for item in listed.tools:
                        qualified = f"{name}.{item.name}"
                        desc = item.description or ""
                        tools[qualified] = _remote_tool(name, spec, item.name, desc)
        except MCPError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MCPError(f"Failed to connect to MCP server '{name}': {exc}") from exc
    return tools


def _remote_tool(server: str, spec: MCPServerSpec, tool_name: str, description: str) -> Tool:
    def handler(**kwargs: Any) -> Any:
        return asyncio.run(_call_tool(spec, tool_name, kwargs))

    return FunctionTool(
        name=f"{server}.{tool_name}",
        description=description or f"MCP tool {tool_name} from {server}",
        handler=handler,
    )


async def _call_tool(spec: MCPServerSpec, tool_name: str, arguments: dict[str, Any]) -> Any:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=spec.command,
        args=spec.args,
        env=mcp_child_env(spec),
        cwd=spec.cwd,
    )
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                if getattr(result, "isError", False):
                    raise MCPError(f"MCP tool '{tool_name}' returned an error: {result}")
                content = getattr(result, "content", None)
                if not content:
                    return str(result)
                texts = []
                for block in content:
                    text = getattr(block, "text", None)
                    if text is not None:
                        texts.append(text)
                return "\n".join(texts) if texts else str(result)
    except MCPError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MCPError(f"MCP tool '{tool_name}' failed: {exc}") from exc
