"""Typer CLI for ReadyAgents Core."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from readyagents import __version__
from readyagents.errors import ReadyAgentsError
from readyagents.logging import configure_logging
from readyagents.packs.loader import discover_packs
from readyagents.workflow.runner import load_workflow, run_workflow_file
from readyagents.workflow.state import parse_input_pairs

app = typer.Typer(
    name="readyagents",
    help="ReadyAgents Core — Agent Workflow engine + MCP Toolkit (BYOK).",
    no_args_is_help=True,
    add_completion=False,
)
mcp_app = typer.Typer(help="Run ReadyAgents as an MCP server.", no_args_is_help=True)
app.add_typer(mcp_app, name="mcp")

console = Console()
err_console = Console(stderr=True)

_WORKFLOW_ARG = typer.Argument(
    ...,
    exists=True,
    readable=True,
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
            "2. Smoke test (no keys):  "
            "[cyan]readyagents run examples/calc_pipeline.yaml[/cyan]\n"
            "3. With keys:  [cyan]readyagents run examples/research_brief.yaml "
            "--input topic=your-topic[/cyan]\n"
            "See docs/getting-started.md",
            title="ReadyAgents",
        )
    )


@app.command()
def validate(path: Path = _WORKFLOW_ARG) -> None:
    """Schema-validate a workflow file without executing it."""
    try:
        workflow = load_workflow(path)
    except ReadyAgentsError as exc:
        _fail(exc)
        return
    table = Table(title=f"Valid: {workflow.name}")
    table.add_column("Node")
    table.add_column("Type")
    table.add_column("Next")
    for node in workflow.nodes:
        nxt = node.next or node.then or ""
        table.add_row(node.id, str(node.type), nxt)
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
        help="Interpolate and walk the graph without calling an LLM (or http_get).",
    ),
    no_persist: bool = typer.Option(
        False, "--no-persist", help="Do not write a run record."
    ),
) -> None:
    """Execute a workflow."""
    try:
        parsed = parse_input_pairs(inputs)
        state = run_workflow_file(
            path,
            inputs=parsed,
            dry_run=dry_run,
            persist=not no_persist,
        )
    except ReadyAgentsError as exc:
        _fail(exc)
        return

    table = Table(title=f"Run {state.run_id} — {state.status}")
    table.add_column("Node")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Output", overflow="fold")
    for result in state.results:
        preview = result.error or _preview(result.output)
        table.add_row(result.node_id, result.type, result.status, escape(preview))
    console.print(table)
    if state.status != "succeeded":
        raise typer.Exit(code=1)
    console.print("[green]succeeded[/green]")
    if state.output_keys:
        console.print(Panel(escape(_preview(state.output_keys, limit=2000)), title="Outputs"))


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


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Expose builtin tools (and run_workflow) over MCP stdio."""
    try:
        from readyagents.mcp.server import serve_stdio

        serve_stdio()
    except ReadyAgentsError as exc:
        _fail(exc)


def _preview(value: object, limit: int = 160) -> str:
    text = value if isinstance(value, str) else repr(value)
    text = text.replace("\n", " ")
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _fail(exc: BaseException) -> None:
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
