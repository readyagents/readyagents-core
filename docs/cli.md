# CLI

The `readyagents` command is a [Typer](https://typer.tiangolo.com/) app.

```bash
readyagents --help
readyagents --version
```

## `readyagents init`

Writes `.env` from `.env.example` when `.env` is missing. Prints next steps. Does not overwrite an existing `.env`.

```bash
readyagents init
readyagents init --dest .env
```

## `readyagents validate PATH`

Loads YAML/JSON and validates the Pydantic schema (unique node ids, dangling `next` / edges, required fields per type). Does not call tools or LLMs.

## `readyagents run PATH`

```bash
readyagents run examples/calc_pipeline.yaml
readyagents run examples/research_brief.yaml --input topic="mcp servers"
readyagents run examples/support_triage.yaml -i message="billing question"
readyagents run examples/code_review.yaml --dry-run
readyagents run examples/research_brief.yaml --no-persist
```

| Flag | Meaning |
| --- | --- |
| `--input KEY=VALUE` / `-i` | Repeatable. `true`/`false`/`null` and integers are coerced |
| `--dry-run` | No LLM, no `http_get`; templates still interpolate |
| `--no-persist` | Skip writing `.readyagents/runs/<id>.json` |
| `--log-level` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

Exit code `1` on validation or execution errors. The CLI prints `ErrorClass: message` rather than a full traceback.

## `readyagents mcp serve`

Stdio MCP server. Requires `pip install 'readyagents[mcp]'`. See [mcp.md](mcp.md).

## `readyagents packs`

Lists packs discovered via entry points. Empty when only core is installed.

## `readyagents version`

Prints the package version.

## Python API

```python
from pathlib import Path
from readyagents.workflow.runner import run_workflow_file

state = run_workflow_file(Path("examples/calc_pipeline.yaml"), persist=False)
print(state.status, state.output_keys)
```
