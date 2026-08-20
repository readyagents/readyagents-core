"""Typer CLI for ReadyAgents Core."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from readyagents import __version__
from readyagents.errors import ApprovalRequired, ReadyAgentsError
from readyagents.logging import configure_logging
from readyagents.packs.loader import discover_packs
from readyagents.scaffold import TEMPLATES, create_project
from readyagents.workflow.runner import (
    load_workflow,
    replay_run,
    resume_run,
    run_workflow_file,
)
from readyagents.workflow.state import (
    RunState,
    build_decisions,
    list_runs,
    load_run,
    parse_input_pairs,
)

app = typer.Typer(
    name="readyagents",
    help="ReadyAgents Core — Agent Workflow engine + MCP Toolkit (BYOK).",
    no_args_is_help=True,
    add_completion=False,
)
mcp_app = typer.Typer(help="Run ReadyAgents as an MCP server.", no_args_is_help=True)
runs_app = typer.Typer(help="Inspect persisted workflow runs.", no_args_is_help=True)
app.add_typer(mcp_app, name="mcp")
app.add_typer(runs_app, name="runs")

console = Console()
err_console = Console(stderr=True)

_WORKFLOW_ARG = typer.Argument(
    ...,
    help="Workflow YAML or JSON file.",
)


def _version_flag(value: bool) -> None:
    if value:
        console.print(__version__)
        raise typer.Exit()


@app.callback()
def _root(
    version: bool | None = typer.Option(
        None,
        "--version",
        callback=_version_flag,
        is_eager=True,
        help="Print version and exit.",
    ),
    log_level: str = typer.Option(
        "INFO",
        "--log-level",
        help="DEBUG, INFO, WARNING, or ERROR.",
        envvar="READYAGENTS_LOG_LEVEL",
    ),
) -> None:
    configure_logging(log_level)


@app.command()
def version() -> None:
    """Print the ReadyAgents version."""
    console.print(__version__)


@app.command("init")
def init_cmd(
    dest: Path = typer.Option(Path(".env"), "--dest", help="Path to write the env file."),
) -> None:
    """Create a local `.env` from `.env.example` if it does not exist."""
    example = Path(".env.example")
    if dest.exists():
        console.print(f"[yellow]{dest} already exists[/yellow] — left unchanged.")
        _print_next_steps()
        return
    if example.is_file():
        dest.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        dest.write_text(_ENV_TEMPLATE, encoding="utf-8")
    console.print(f"[green]Wrote {dest}[/green] — add your BYOK API keys, then run:")
    _print_next_steps()


def _print_next_steps() -> None:
    console.print(
        Panel(
            "[bold]Next steps[/bold]\n"
            "1. Edit `.env` and set OPENAI_API_KEY and/or ANTHROPIC_API_KEY\n"
            "2. Scaffold:  [cyan]readyagents new my-flow[/cyan]\n"
            "3. Smoke test (no keys):  "
            "[cyan]readyagents run examples/calc_pipeline.yaml[/cyan]\n"
            "4. With keys:  [cyan]readyagents run examples/research_brief.yaml "
            "--input topic=your-topic[/cyan]\n"
            "See docs/getting-started.md",
            title="ReadyAgents",
        )
    )


@app.command("new")
def new_cmd(
    name: str = typer.Argument("starter", help="Project / workflow name."),
    dest: Path | None = typer.Option(
        None,
        "--dest",
        help="Directory to write (defaults to ./<name>).",
    ),
    template: str = typer.Option(
        "pipeline",
        "--template",
        "-t",
        help=f"Starter kind: {', '.join(TEMPLATES)}.",
    ),
) -> None:
    """Write a starter workflow, README, and `.env.example`."""
    target = dest if dest is not None else Path(name)
    try:
        written = create_project(target, name=name, template=template)
    except ReadyAgentsError as exc:
        _fail(exc)
        return
    console.print(f"[green]Created {target.resolve()}[/green]  template={template}")
    for path in written:
        console.print(f"  {path.name}")
    wf = target / "workflow.yaml"
    if template == "basic" or template == "pipeline":
        console.print(f"Run: [cyan]readyagents run {wf}[/cyan]")
    elif template == "research":
        console.print(f"Run: [cyan]readyagents run {wf} --approve publish[/cyan]")
    else:
        console.print(f"Run: [cyan]readyagents run {wf} --approve gate[/cyan]")


@app.command()
def validate(
    path: Path = _WORKFLOW_ARG,
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Print the workflow summary as JSON on stdout (no tables).",
    ),
) -> None:
    """Schema-validate a workflow file without executing it."""
    try:
        workflow = load_workflow(path)
    except ReadyAgentsError as exc:
        if as_json:
            _print_json(
                {
                    "ok": False,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
            )
            raise typer.Exit(code=1) from exc
        _fail(exc)
    nodes = [
        {
            "id": node.id,
            "type": str(node.type),
            "next": node.next,
            "then": node.then,
            "else": node.else_,
        }
        for node in workflow.nodes
    ]
    if as_json:
        _print_json(
            {
                "ok": True,
                "name": workflow.name,
                "start": workflow.start,
                "node_count": len(workflow.nodes),
                "nodes": nodes,
            }
        )
        return
    table = Table(title=f"Valid: {workflow.name}")
    table.add_column("Node")
    table.add_column("Type")
    table.add_column("Next")
    for node in workflow.nodes:
        table.add_row(node.id, str(node.type), _node_routing(node))
    console.print(table)
    console.print(f"[green]OK[/green] — {len(workflow.nodes)} node(s), start={workflow.start}")


@app.command()
def run(
    path: Path = _WORKFLOW_ARG,
    inputs: list[str] = typer.Option(
        [],
        "--input",
        "-i",
        help="Input as KEY=VALUE (repeatable).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Walk the graph without calling an LLM, http_get, or write_file.",
    ),
    no_persist: bool = typer.Option(
        False, "--no-persist", help="Do not write a run record."
    ),
    approve: list[str] = typer.Option(
        [],
        "--approve",
        help="Approve an approval node by id (repeatable).",
    ),
    reject: list[str] = typer.Option(
        [],
        "--reject",
        help="Reject an approval node by id (repeatable).",
    ),
    resume: str | None = typer.Option(
        None,
        "--resume",
        help="Resume this run id instead of starting a new run.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Print the run record as JSON on stdout (no tables).",
    ),
) -> None:
    """Execute a workflow."""
    persist = not no_persist
    try:
        parsed = parse_input_pairs(inputs)
        decisions = build_decisions(approve, reject)
        if resume:
            state = resume_run(
                resume,
                path=path,
                inputs=parsed or None,
                dry_run=dry_run,
                persist=persist,
                decisions=decisions,
            )
        else:
            state = run_workflow_file(
                path,
                inputs=parsed,
                dry_run=dry_run,
                persist=persist,
                decisions=decisions,
            )
    except ReadyAgentsError as exc:
        _emit_run_exception(exc, as_json=as_json, persist=persist)
    _emit_run(state, as_json=as_json)


@app.command("resume")
def resume_cmd(
    run_id: str = typer.Argument(..., help="Run id (or unique prefix)."),
    workflow: Path | None = typer.Option(
        None,
        "--workflow",
        help="Workflow file (defaults to the path stored on the run).",
    ),
    inputs: list[str] = typer.Option(
        [],
        "--input",
        "-i",
        help="Override stored inputs as KEY=VALUE (repeatable).",
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
    no_persist: bool = typer.Option(False, "--no-persist"),
    approve: list[str] = typer.Option([], "--approve"),
    reject: list[str] = typer.Option([], "--reject"),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Print the run record as JSON on stdout (no tables).",
    ),
) -> None:
    """Resume a paused or failed run from the last successful node."""
    persist = not no_persist
    try:
        parsed = parse_input_pairs(inputs)
        state = resume_run(
            run_id,
            path=workflow,
            inputs=parsed or None,
            dry_run=dry_run,
            persist=persist,
            decisions=build_decisions(approve, reject),
        )
    except ReadyAgentsError as exc:
        _emit_run_exception(exc, as_json=as_json, persist=persist)
    _emit_run(state, as_json=as_json)


@app.command("packs")
def packs_cmd() -> None:
    """List installed ReadyAgents packs (entry point group readyagents.packs)."""
    found = discover_packs()
    if not found:
        console.print("No packs installed. Core runs without any packs.")
        console.print(
            "See docs/packs.md for how a future readyagents-pack-continuous would plug in."
        )
        return
    table = Table(title="Installed packs")
    table.add_column("Name")
    table.add_column("Version")
    for pack in found:
        table.add_row(pack.name, pack.version)
    console.print(table)


@runs_app.command("list")
def runs_list(
    as_json: bool = typer.Option(False, "--json", help="Print JSON instead of a table."),
    status: str | None = typer.Option(
        None, "--status", help="Filter: running, paused, failed, succeeded."
    ),
    workflow: str | None = typer.Option(None, "--workflow", help="Filter by workflow name."),
    limit: int = typer.Option(0, "--limit", help="Max rows (0 = all)."),
) -> None:
    """List persisted runs (newest first)."""
    from readyagents.config import get_settings

    settings = get_settings()
    found = list_runs(
        settings.runs_dir(),
        status=status,
        workflow=workflow,
        limit=limit,
    )
    if as_json:
        payload = [
            {
                "run_id": s.run_id,
                "workflow": s.workflow_name,
                "status": s.status,
                "started_at": s.started_at,
                "pending_node": s.pending_node,
                "nodes": [r.node_id for r in s.results],
            }
            for s in found
        ]
        _print_json(payload)
        return
    if not found:
        console.print(f"No runs in {settings.runs_dir()}")
        return
    table = Table(title=f"Runs in {settings.runs_dir()}", expand=True)
    table.add_column("run_id", no_wrap=True, overflow="fold")
    table.add_column("workflow")
    table.add_column("status")
    table.add_column("started_at")
    table.add_column("nodes")
    for state in found:
        nodes = ",".join(r.node_id for r in state.results) or "-"
        table.add_row(state.run_id, state.workflow_name, state.status, state.started_at, nodes)
        console.print(
            f"run_id: {state.run_id}  workflow: {state.workflow_name}  status: {state.status}"
        )
    console.print(table)


@runs_app.command("show")
def runs_show(
    run_id: str = typer.Argument(..., help="Run id (or unique prefix)."),
    as_json: bool = typer.Option(False, "--json", help="Print the stored run record as JSON."),
) -> None:
    """Show a run record and its node timeline."""
    _show_run(run_id, as_json=as_json)


@runs_app.command("inspect")
def runs_inspect(
    run_id: str = typer.Argument(..., help="Run id (or unique prefix)."),
    as_json: bool = typer.Option(False, "--json", help="Print the stored run record as JSON."),
) -> None:
    """Alias for `runs show` — inspect stored state and the node timeline."""
    _show_run(run_id, as_json=as_json)


@runs_app.command("report")
def runs_report(
    run_id: str = typer.Argument(..., help="Run id (or unique prefix)."),
    dest: Path | None = typer.Option(
        None,
        "--out",
        "-o",
        help="HTML file to write (default: <run_id>.html in cwd).",
    ),
) -> None:
    """Write a local HTML summary of a persisted run."""
    from readyagents.config import get_settings
    from readyagents.report import write_html_report

    try:
        state = load_run(get_settings().runs_dir(), run_id)
        path = dest or Path(f"{state.run_id}.html")
        written = write_html_report(state, path)
    except ReadyAgentsError as exc:
        _fail(exc)
        return
    console.print(f"[green]Wrote {written}[/green]  open it in a browser.")


@runs_app.command("replay")
def runs_replay(
    run_id: str = typer.Argument(..., help="Run id (or unique prefix)."),
    dry_run: bool = typer.Option(False, "--dry-run"),
    no_persist: bool = typer.Option(False, "--no-persist"),
    approve: list[str] = typer.Option([], "--approve"),
    reject: list[str] = typer.Option([], "--reject"),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Print the run record as JSON on stdout (no tables).",
    ),
) -> None:
    """Start a new run using the stored workflow path and inputs."""
    persist = not no_persist
    try:
        state = replay_run(
            run_id,
            dry_run=dry_run,
            persist=persist,
            decisions=build_decisions(approve, reject),
        )
    except ReadyAgentsError as exc:
        _emit_run_exception(exc, as_json=as_json, persist=persist)
    _emit_run(state, as_json=as_json)


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Expose builtin tools (and run_workflow) over MCP stdio."""
    try:
        from readyagents.mcp.server import serve_stdio

        serve_stdio()
    except ReadyAgentsError as exc:
        _fail(exc)


def _show_run(run_id: str, *, as_json: bool = False) -> None:
    from readyagents.config import get_settings

    try:
        state = load_run(get_settings().runs_dir(), run_id)
    except ReadyAgentsError as exc:
        _fail(exc)
        return
    if as_json:
        _print_json(state.to_record())
        return
    console.print(f"run_id: {state.run_id}")
    console.print(f"workflow: {state.workflow_name}")
    console.print(f"status: {state.status}")
    if state.pending_node:
        console.print(f"pending_node: {state.pending_node}")
    _print_usage(state)
    _print_run(state)
    if state.output_keys:
        console.print(Panel(escape(_preview(state.output_keys, limit=2000)), title="Outputs"))
    if state.inputs:
        console.print(Panel(escape(_preview(state.inputs, limit=2000)), title="Inputs"))


def _print_json(payload: object) -> None:
    """Write JSON to stdout without Rich markup (values may contain `[...]`)."""
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


def _node_routing(node: Any) -> str:
    """Compact then/else/next for the validate table (else was previously dropped)."""
    bits: list[str] = []
    if node.then:
        bits.append(f"then:{node.then}")
    if node.else_:
        bits.append(f"else:{node.else_}")
    if node.next:
        bits.append(node.next if not bits else f"next:{node.next}")
    return " ".join(bits)


def _state_from_exc(exc: BaseException) -> RunState | None:
    state = getattr(exc, "state", None)
    return state if isinstance(state, RunState) else None


def _emit_run(state: RunState, *, as_json: bool) -> None:
    if as_json:
        _print_json(state.to_record())
    else:
        _print_run(state)
        if state.status == "succeeded":
            console.print("[green]succeeded[/green]")
            console.print(f"run_id: {state.run_id}")
            _print_usage(state)
            if state.output_keys:
                console.print(
                    Panel(escape(_preview(state.output_keys, limit=2000)), title="Outputs")
                )
        else:
            console.print(f"[red]{state.status}[/red]")
            console.print(f"run_id: {state.run_id}")
    if state.status != "succeeded":
        raise typer.Exit(code=1)


def _emit_run_exception(exc: ReadyAgentsError, *, as_json: bool, persist: bool) -> NoReturn:
    """Print a paused or failed run (JSON or tables) and exit. Never returns."""
    if isinstance(exc, ApprovalRequired):
        state = _state_from_exc(exc)
        if as_json:
            payload: dict[str, Any] = {
                "error": type(exc).__name__,
                "message": str(exc),
                "run_id": exc.run_id,
                "node_id": exc.node_id,
                "prompt": exc.prompt,
                "status": "paused",
            }
            if state is not None:
                payload["run"] = state.to_record()
            _print_json(payload)
        else:
            _print_paused(exc)
        raise typer.Exit(code=2) from exc

    state = _state_from_exc(exc)
    run_id = getattr(exc, "run_id", None) or (state.run_id if state is not None else None)
    if as_json:
        payload = {
            "error": type(exc).__name__,
            "message": str(exc),
            "run_id": run_id,
            "status": state.status if state is not None else "failed",
        }
        if state is not None:
            payload["run"] = state.to_record()
        _print_json(payload)
        raise typer.Exit(code=1) from exc

    if state is not None:
        _print_run(state)
        err_console.print(f"[red]{type(exc).__name__}:[/red] {exc}")
        console.print(f"run_id: {state.run_id}  status: {state.status}")
        if persist:
            cmd = f"readyagents resume {state.run_id}"
            pending = state.pending_node
            if pending:
                console.print(
                    f"Resume: [cyan]{cmd}[/cyan]  (retry node [bold]{escape(pending)}[/bold])"
                )
            else:
                console.print(f"Resume: [cyan]{cmd}[/cyan]")
        raise typer.Exit(code=1) from exc

    _fail(exc)


def _print_usage(state: RunState) -> None:
    if not state.usage:
        return
    parts = [f"{k}={v}" for k, v in state.usage.items()]
    console.print("usage: " + " ".join(parts))


def _print_run(state: RunState) -> None:
    table = Table(title=f"Run {state.run_id} — {state.status}")
    table.add_column("Node")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Output", overflow="fold")
    for result in state.results:
        preview = result.error or _preview(result.output)
        table.add_row(result.node_id, result.type, result.status, escape(preview))
    console.print(table)


def _print_paused(exc: ApprovalRequired) -> None:
    if exc.state is not None and isinstance(exc.state, RunState):
        _print_run(exc.state)
    err_console.print(f"[yellow]{type(exc).__name__}:[/yellow] {exc}")
    if exc.prompt:
        console.print(Panel(escape(exc.prompt), title=f"Approval: {exc.node_id}"))
    console.print(
        f"Resume: [cyan]readyagents resume {exc.run_id} --approve {exc.node_id}[/cyan]"
    )


def _preview(value: object, limit: int = 160) -> str:
    text = value if isinstance(value, str) else repr(value)
    text = text.replace("\n", " ")
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _fail(exc: BaseException) -> NoReturn:
    err_console.print(f"[red]{type(exc).__name__}:[/red] {exc}")
    raise typer.Exit(code=1) from exc


_ENV_TEMPLATE = """# ReadyAgents BYOK — fill in your keys. Never commit real keys.

READYAGENTS_DEFAULT_MODEL=openai:gpt-4o-mini
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
# READYAGENTS_ALLOW_HTTP=0
"""


def main() -> None:
    app()


if __name__ == "__main__":
    main()
