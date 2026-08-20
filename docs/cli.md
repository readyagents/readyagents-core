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

## `readyagents new [name]`

Write a starter project: `workflow.yaml`, `README.md`, and `.env.example`.

```bash
readyagents new my-flow
readyagents run my-flow/workflow.yaml
readyagents new gated --template approval
readyagents run gated/workflow.yaml --approve gate
```

Templates: `basic`, `approval`, `research` (parallel + approval), `pipeline` (default; calc/json/condition), `review` (read_file + approval).

## `readyagents validate PATH`

Loads YAML/JSON and validates the Pydantic schema (unique node ids, dangling `next` / edges, required fields per type, unique parallel branch ids). Does not call tools or LLMs. `--json` prints `{ok, name, start, nodes}` (or `{ok: false, error, message}` on failure). The table shows `then:` / `else:` routing, not only `next`.

## `readyagents run PATH`

```bash
readyagents run examples/calc_pipeline.yaml
readyagents run examples/approval_gate.yaml --approve gate
readyagents run examples/research_brief.yaml --input topic="mcp servers"
readyagents run examples/support_triage.yaml -i message="billing question"
readyagents run examples/code_review.yaml --dry-run
readyagents run examples/research_brief.yaml --no-persist
```

| Flag | Meaning |
| --- | --- |
| `--input KEY=VALUE` / `-i` | Repeatable. `true`/`false`/`null` and integers are coerced |
| `--dry-run` | No LLM, no `http_get` or `write_file`; templates still interpolate. Read-only tools (`now`, `calc`, `json_get`, `read_file`) still run. |
| `--no-persist` | Skip writing `.readyagents/runs/<id>.json` |
| `--approve NODE` | Supply an approval-node decision (repeatable) |
| `--reject NODE` | Reject an approval node (repeatable) |
| `--resume RUN_ID` | Continue a paused/failed run instead of starting fresh |
| `--json` | Print the run record as JSON on stdout (no tables; scripts/CI) |
| `--log-level` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

Exit code `1` on validation or execution errors. Exit code `2` when an **approval** node pauses for a decision. The CLI prints `ErrorClass: message` rather than a full traceback. Logs include `run=<id>` and `node=<id>`.

Failed runs print the **node timeline**, `run_id`, and a `readyagents resume RUN_ID` hint (same idea as approval pauses). `--json` on pause/failure is an error envelope (`error`, `message`, `run_id`, `run`) so scripts can still recover the record. `resume` and `runs replay` accept `--json` too. JSON is written without Rich markup, so values like `[dry-run]` stay intact.

State is persisted after **each** successful node (unless `--no-persist`).

## `readyagents resume RUN_ID`

Resume a paused or failed run from the last successful node. Uses the workflow path stored on the run record.

```bash
readyagents resume abcdef --approve gate
readyagents resume abcdef --workflow examples/approval_gate.yaml --reject gate
readyagents resume abcdef --json
```

## `readyagents runs list`

List persisted runs (newest first). Each line includes `run_id`. `--json` prints a JSON array. Filters: `--status`, `--workflow`, `--limit`.

## `readyagents runs show RUN_ID`

Show status, pending node (if paused), **node timeline**, inputs, and outputs. `readyagents runs inspect RUN_ID` is an alias. `--json` prints the stored run record.

## `readyagents runs replay RUN_ID`

Start a **new** run with the stored workflow path and inputs (not a resume).

## `readyagents runs report RUN_ID`

Write a local HTML summary (timeline, usage, outputs). Open the file in a browser.

```bash
readyagents runs report <run_id>
readyagents runs report <run_id> --out /tmp/run.html
```

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
