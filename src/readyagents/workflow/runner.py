"""Load a workflow file, execute it, persist the run record."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from readyagents.config import Settings, get_settings
from readyagents.errors import ConfigError, WorkflowError
from readyagents.llm.base import LLMProvider
from readyagents.packs.loader import collect_pack_nodes, collect_pack_tools, discover_packs
from readyagents.tools import ToolRegistry, default_registry
from readyagents.workflow.engine import run_workflow
from readyagents.workflow.nodes import ExecutionContext
from readyagents.workflow.schema import WorkflowSpec, validate_required_inputs
from readyagents.workflow.state import RunState, persist_run


def load_workflow(path: Path | str) -> WorkflowSpec:
    file = Path(path)
    if not file.is_file():
        raise ConfigError(f"Workflow file not found: {file}")
    text = file.read_text(encoding="utf-8")
    try:
        if file.suffix.lower() in {".json"}:
            data = json.loads(text)
        else:
            data = yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise WorkflowError(f"Could not parse {file}: {exc}") from exc
    if not isinstance(data, dict):
        raise WorkflowError(f"Workflow {file} must be a mapping")
    try:
        return WorkflowSpec.model_validate(data)
    except ValidationError as exc:
        raise WorkflowError(_format_validation(file, exc)) from exc


def _format_validation(path: Path, exc: ValidationError) -> str:
    lines = [f"Invalid workflow {path}:"]
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        lines.append(f"  - {loc}: {err.get('msg')}")
    return "\n".join(lines)


def merge_inputs(workflow: WorkflowSpec, overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    merged = dict(workflow.input_defaults())
    if overrides:
        merged.update(overrides)
    validate_required_inputs(workflow, merged)
    return merged


def run_workflow_file(
    path: Path | str,
    *,
    inputs: Mapping[str, Any] | None = None,
    dry_run: bool = False,
    settings: Settings | None = None,
    llm: LLMProvider | None = None,
    persist: bool = True,
    extra_tools: ToolRegistry | None = None,
) -> RunState:
    settings = settings or get_settings()
    workflow = load_workflow(path)
    merged = merge_inputs(workflow, inputs)

    workspace = Path(workflow.workspace) if workflow.workspace else settings.workspace_path()
    if not workspace.is_absolute():
        workspace = (Path.cwd() / workspace).resolve()
    allow_http = bool(workflow.allow_http or settings.allow_http)

    tools = default_registry(allow_http=allow_http, workspace=workspace)
    packs = discover_packs()
    tools.merge(collect_pack_tools(packs))
    if extra_tools:
        tools.merge(extra_tools)

    mcp = None
    if workflow.mcp_servers and not dry_run:
        from readyagents.mcp.client import MCPClient

        mcp = MCPClient(workflow.mcp_servers)
        tools.merge(mcp.tools())

    ctx = ExecutionContext(
        workflow,
        tools,
        dry_run=dry_run,
        llm=llm,
        default_model=workflow.default_model or settings.default_model,
        extra_handlers=collect_pack_nodes(packs),
    )
    metadata = {
        "source": str(Path(path)),
        "allow_http": allow_http,
        "dry_run": dry_run,
        "workspace": str(workspace),
    }
    try:
        state = run_workflow(workflow, merged, ctx, metadata=metadata)
    finally:
        if mcp is not None:
            mcp.close()

    if persist:
        persist_run(state, settings.runs_dir())
    return state
