# Next core improvements

Ordered list for the remaining open-core work. Cap is 3–6 executable items.
Already on `main` (0.2.0 and Agent G. commits `efdad65`…`ef404a9`) is out of
scope, as is Premium Pack territory (schedulers, hosted control plane,
multi-tenant, extra databases, billing).

Produced 2026-08-20 by merging five independent reviews (tests, reliability,
CLI/DX, examples/docs, tools/security/CI). Execute **one item per commit**.

## To do (execute in order)

### 1. `--dry-run` must not write files — shipped

`--dry-run` already skips the LLM and stubs `http_get`. `write_file` still
runs and mutates the workspace. Stub side-effecting tools (`write_file` at
minimum) with `[dry-run] <tool> …` so a dry-run cannot create or overwrite
files. Keep read-only builtins (`now`, `calc`, `json_get`, `read_file`) so
keyless examples still walk.

**Done when:** `readyagents run` of a `write_file` workflow with `--dry-run`
exits 0 and the target file is absent. A real (non-dry) run still writes.

### 2. Node timeout actually expires — shipped

`_call_with_timeout` waits for the worker on `ThreadPoolExecutor` shutdown, so
a timed-out node still blocks until the handler finishes. Retries can stack
overlapping sleeps. Return when the budget expires (`shutdown(wait=False)` /
cancel futures). Keep a single `NodeError` (`timed out after Ns`).

**Done when:** a tool that sleeps 2s with `timeout_seconds: 0.05` fails in well
under 1s; the error is one `NodeError` and names the node.

### 3. Missing workflow path is exit 1, not approval's exit 2 — shipped

`run` / `validate` use Typer `exists=True`, so a missing file is a usage
error (exit 2) — the same code as an approval pause. Scripts cannot tell a
typo from HITL. Resolve the path in our code and raise `ConfigError`
("Workflow file not found") with **exit 1**. Reserve exit 2 for
`ApprovalRequired`.

**Done when:** `readyagents run missing.yaml` exits 1 and prints `ConfigError`;
`readyagents run examples/approval_gate.yaml` still exits 2.

### 4. Successful runs print `run_id:`

Success currently puts the id only in the Rich table title. Failed and paused
runs print `run_id:`. The 60-second README path (`runs list` / `runs report`)
needs a copy-pasteable id on the happy path too.

**Done when:** `readyagents run examples/calc_pipeline.yaml` stdout contains
`run_id:` followed by the hex id, and still contains `succeeded` and
`calc_pipeline ok`.

### 5. `validate` rejects cyclic graphs

Runtime already raises `WorkflowError` on cycles (`seen` + 500-step cap).
`readyagents validate` only checks dangling refs, so `a.next: b` / `b.next: a`
prints OK. Detect cycles at schema time over `next` / `then` / `else` / `edges`
(including self-loops).

**Done when:** `readyagents validate cycle.yaml --json` has `ok: false` and the
message mentions `Cycle`. Sequential and branching acyclic graphs still
validate.

### 6. Confine YAML `workspace:` (and MCP `run_workflow` paths)

File tools are sandboxed *to* `workspace`, but a workflow may set
`workspace: /` (or `../…`) and relocate that sandbox. MCP `run_workflow`
accepts any filesystem path. Resolve `workspace:` under
`settings.workspace_path()` (same idea as include confinement). MCP
`run_workflow` may only load a workflow file under that root.

**Done when:** a workflow with `workspace: /tmp` (or an escape) fails with a
typed error and does not write outside the settings workspace; MCP
`run_workflow("/etc/passwd")` fails the same way. `examples/calc_pipeline.yaml`
is unchanged.

## Leftover (not in this pass)

- Include-child approval pause/resume (`pending_node` is the include node)
- `runs list` prints each run twice (line + table)
- `--log-level` on `run` as docs claim (today it is root-only)
- MCP client must not shadow sandbox builtins or inherit API keys
- Size caps for `read_file` / `write_file` / `json_get` / `calc`
- Pin `http_get` to IPs already classified public (DNS rebinding)
- Docs extras still look like PyPI (`pip install "readyagents[openai]"`)
- Makefile / CONTRIBUTING / CI: `composed_gate`, `ruff format --check`
- `readyagents new` overwrite-refusal test
- `packs --json`; `runs show --json` envelope for missing ids
- Parallel branches honoring `timeout_seconds` / `retry`

## Merge note

| Review | Who | What they ranked first |
| --- | --- | --- |
| Tests | specialist | `resume`/`replay --json` coverage; include HITL; timeout+retry; dry-run `http_get`; `new` overwrite |
| Reliability | specialist | timeout cancel; dry-run `write_file`; workspace relocate; schema cycles; parallel policy |
| CLI/DX | specialist | missing-file exit 1 vs pause 2; success `run_id:`; `runs list` dup; `--log-level` on `run` |
| Examples/docs | specialist | extras install path; `new` default docs; Makefile smoke; `write_file` example |
| Tools/security/CI | specialist | MCP `run_workflow` confinement; MCP shadow/env; DNS rebind; payload caps; `make lint` |

Merged list prefers operator-visible reliability and honesty over extra tests
of already-shipped flags, and over docs-only drift (those sit in Leftover).
