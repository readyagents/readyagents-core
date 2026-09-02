"""Expose ReadyAgents builtin tools (and run-workflow) as an MCP server."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from readyagents.config import get_settings
from readyagents.errors import MCPError
from readyagents.mcp.builtin import builtin_tools


def mcp_available() -> bool:
    try:
        import mcp  # noqa: F401

        return True
    except ImportError:
        return False


def _create_server(name: str) -> Any:
    try:
        from mcp.server import MCPServer

        return MCPServer(name)
    except ImportError:
        pass
    try:
        from mcp.server.fastmcp import FastMCP

        return FastMCP(name)
    except ImportError as exc:
        raise MCPError(
            "This version of the mcp package does not provide MCPServer or FastMCP."
        ) from exc


def construct_server(*, allow_http: bool | None = None, workspace: Path | None = None) -> Any:
    """Build an MCP server that exposes builtin tools. Does not start a transport."""
    if not mcp_available():
        raise MCPError("MCP extra is not installed. Run: pip install 'readyagents[mcp]'")

    settings = get_settings()
    allow = settings.allow_http if allow_http is None else allow_http
    root = workspace or settings.workspace_path()
    tools = {t.name: t for t in builtin_tools(allow_http=allow, workspace=root)}
    server = _create_server("readyagents")
    _register_server_tools(server, tools, workspace=Path(root))
    return server


def serve_stdio(*, allow_http: bool | None = None, workspace: Path | None = None) -> None:
    """Run a stdio MCP server exposing builtin tools."""
    construct_server(allow_http=allow_http, workspace=workspace).run(transport="stdio")


def _register_server_tools(server: Any, tools: dict[str, Any], *, workspace: Path) -> None:
    root = Path(workspace).resolve()

    @server.tool(name="now", description=tools["now"].description)
    def now() -> str:
        return str(tools["now"].run())

    @server.tool(name="calc", description=tools["calc"].description)
    def calc(expression: str) -> str:
        return str(tools["calc"].run(expression=expression))

    @server.tool(name="json_get", description=tools["json_get"].description)
    def json_get(data: str, path: str) -> str:
        import json

        result = tools["json_get"].run(data=data, path=path)
        if isinstance(result, (dict, list)):
            return json.dumps(result)
        return str(result)

    @server.tool(name="json_set", description=tools["json_set"].description)
    def json_set(data: str, path: str, value: str) -> str:
        import json

        result = tools["json_set"].run(data=data, path=path, value=value)
        if isinstance(result, (dict, list)):
            return json.dumps(result)
        return str(result)

    @server.tool(name="json_merge", description=tools["json_merge"].description)
    def json_merge(data: str, path: str, value: str) -> str:
        import json

        result = tools["json_merge"].run(data=data, path=path, value=value)
        if isinstance(result, (dict, list)):
            return json.dumps(result)
        return str(result)

    @server.tool(name="http_get", description=tools["http_get"].description)
    def http_get(url: str) -> str:
        return str(tools["http_get"].run(url=url))

    @server.tool(name="list_dir", description=tools["list_dir"].description)
    def list_dir(path: str = ".", include_hidden: bool = False, max_entries: int = 200) -> str:
        import json

        result = tools["list_dir"].run(
            path=path, include_hidden=include_hidden, max_entries=max_entries
        )
        if isinstance(result, (dict, list)):
            return json.dumps(result)
        return str(result)

    @server.tool(name="read_file", description=tools["read_file"].description)
    def read_file(path: str) -> str:
        return str(tools["read_file"].run(path=path))

    @server.tool(name="write_file", description=tools["write_file"].description)
    def write_file(path: str, content: str) -> str:
        return str(tools["write_file"].run(path=path, content=content))

    @server.tool()
    def run_workflow(path: str, inputs_json: str = "{}") -> str:
        """Run a ReadyAgents workflow file under the server workspace."""
        import json

        from readyagents.config import get_settings
        from readyagents.errors import ConfigError
        from readyagents.workflow.runner import confine_under, run_workflow_file

        data = json.loads(inputs_json) if inputs_json else {}
        if not isinstance(data, dict):
            raise ValueError("inputs_json must be a JSON object")
        try:
            wf_path = confine_under(path, root, what="workflow")
        except ConfigError as exc:
            raise MCPError(str(exc)) from exc
        bound = get_settings().model_copy(update={"workspace": Path(root)})
        state = run_workflow_file(wf_path, inputs=data, settings=bound)
        return json.dumps(state.to_record(), ensure_ascii=False)
