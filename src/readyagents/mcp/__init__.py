from readyagents.mcp.builtin import builtin_tools

__all__ = ["builtin_tools", "MCPClient", "construct_server", "mcp_available"]


def __getattr__(name: str):
    if name == "MCPClient":
        from readyagents.mcp.client import MCPClient

        return MCPClient
    if name in {"construct_server", "mcp_available"}:
        from readyagents.mcp.server import construct_server, mcp_available

        return construct_server if name == "construct_server" else mcp_available
    raise AttributeError(name)
