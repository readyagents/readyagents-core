"""Typed errors for ReadyAgents Core."""

from __future__ import annotations


class ReadyAgentsError(Exception):
    """Base error for all ReadyAgents failures."""


class ConfigError(ReadyAgentsError):
    """Invalid configuration, missing settings, or unreadable files."""


class WorkflowError(ReadyAgentsError):
    """Invalid workflow definition or graph execution problem."""


class NodeError(ReadyAgentsError):
    """A single node failed after retries / timeout."""

    def __init__(self, node_id: str, message: str, *, cause: BaseException | None = None) -> None:
        self.node_id = node_id
        self.cause = cause
        super().__init__(f"Node '{node_id}': {message}")


class LLMError(ReadyAgentsError):
    """LLM provider, model, or API-key failure."""


class MCPError(ReadyAgentsError):
    """MCP client or server failure."""


class TemplateError(ReadyAgentsError):
    """Template interpolation failed (missing variable or bad path)."""


class ToolError(ReadyAgentsError):
    """Builtin or MCP tool invocation failed."""


class ApprovalRequired(ReadyAgentsError):
    """An approval node is waiting for an explicit operator decision."""

    def __init__(
        self,
        node_id: str,
        run_id: str,
        prompt: str,
        *,
        state: object | None = None,
    ) -> None:
        self.node_id = node_id
        self.run_id = run_id
        self.prompt = prompt
        self.state = state
        super().__init__(
            f"Approval required at node '{node_id}' (run {run_id}). "
            f"{prompt} Resume with: readyagents resume {run_id} --approve {node_id}"
        )
