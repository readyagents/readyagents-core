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
from readyagents.workflow.state import RunState, load_run, persist_run


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


def confine_under(raw: str | Path, root: Path, *, what: str) -> Path:
    """Resolve `raw` and refuse anything outside `root` (symlink-aware)."""
    root = Path(root).resolve()
    text = str(raw).strip()
    if not text or "\x00" in text:
        raise ConfigError(f"{what} must be a path under {root}")
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ConfigError(
            f"{what} is outside the workspace: {raw} "
            f"(resolved to {resolved}, must stay under {root})"
        )
    return resolved


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
    decisions: Mapping[str, str] | None = None,
    resume_state: RunState | None = None,
) -> RunState:
    settings = settings or get_settings()
    workflow = load_workflow(path)
    if resume_state is not None:
        merged = dict(resume_state.inputs)
        if inputs:
            merged.update(inputs)
        validate_required_inputs(workflow, merged)
    else:
        merged = merge_inputs(workflow, inputs)

    source_path = Path(path).resolve()
    workflow_dir = source_path.parent
    if settings.workspace is not None:
        root = settings.workspace_path()
    else:
        root = workflow_dir
    declared = (workflow.workspace or "").strip()
    workspace = confine_under(declared, root, what="workspace") if declared else root
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

    runs_dir = settings.runs_dir()

    def _save(state: RunState) -> None:
        persist_run(state, runs_dir)

    ctx = ExecutionContext(
        workflow,
        tools,
        dry_run=dry_run,
        llm=llm,
        default_model=workflow.default_model or settings.default_model,
        extra_handlers=collect_pack_nodes(packs),
        decisions=decisions,
        on_persist=_save if persist else None,
        workflow_dir=source_path.parent,
    )
    metadata = {
        "source": str(source_path),
        "allow_http": allow_http,
        "dry_run": dry_run,
        "workspace": str(workspace),
    }
    try:
        state = run_workflow(
            workflow,
            merged,
            ctx,
            metadata=metadata,
            state=resume_state,
        )
    finally:
        if mcp is not None:
            mcp.close()
    return state


def resume_run(
    run_id: str,
    *,
    settings: Settings | None = None,
    path: Path | str | None = None,
    inputs: Mapping[str, Any] | None = None,
    dry_run: bool = False,
    persist: bool = True,
    extra_tools: ToolRegistry | None = None,
    decisions: Mapping[str, str] | None = None,
    llm: LLMProvider | None = None,
) -> RunState:
    settings = settings or get_settings()
    state = load_run(settings.runs_dir(), run_id)
    source = path or state.metadata.get("source")
    if not source:
        raise ConfigError(
            f"Run {state.run_id} has no stored workflow path. Pass --workflow PATH."
        )
    return run_workflow_file(
        source,
        inputs=inputs,
        dry_run=dry_run,
        settings=settings,
        llm=llm,
        persist=persist,
        extra_tools=extra_tools,
        decisions=decisions,
        resume_state=state,
    )


def replay_run(
    run_id: str,
    *,
    settings: Settings | None = None,
    persist: bool = True,
    dry_run: bool = False,
    extra_tools: ToolRegistry | None = None,
    decisions: Mapping[str, str] | None = None,
    llm: LLMProvider | None = None,
) -> RunState:
    """Start a new run with the stored workflow path and inputs."""
    settings = settings or get_settings()
    previous = load_run(settings.runs_dir(), run_id)
    source = previous.metadata.get("source")
    if not source:
        raise ConfigError(
            f"Run {previous.run_id} has no stored workflow path. Cannot replay."
        )
    return run_workflow_file(
        source,
        inputs=previous.inputs,
        dry_run=dry_run,
        settings=settings,
        llm=llm,
        persist=persist,
        extra_tools=extra_tools,
        decisions=decisions,
    )
