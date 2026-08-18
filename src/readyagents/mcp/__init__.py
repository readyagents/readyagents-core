from readyagents.mcp.builtin import builtin_tools

__all__ = ["builtin_tools", "MCPClient"]


def __getattr__(name: str):
    if name == "MCPClient":
        from readyagents.mcp.client import MCPClient

        return MCPClient
    raise AttributeError(name)
