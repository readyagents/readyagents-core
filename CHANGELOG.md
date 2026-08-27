# Changelog

All notable changes to ReadyAgents Core.

## Unreleased

### Added

- **Bounded agent tool-use loop.** Agent nodes may set `tools: [calc, …]` (an allowlist of registry/MCP names) and optional `max_tool_rounds` (default 8, hard max 20). The engine passes tool specs into `complete(..., tools=)`, runs **real** registry tools, and uses the **final** model text as the node output. Omit `tools` for a one-shot complete (0.4.0). Unknown YAML names fail before any LLM call; a model request off the allowlist is not executed. `--dry-run` still skips the LLM and does not run `write_file` / `http_get`. Example: `examples/agent_tools.yaml`.

### Safety

- Core still has no always-on listener, scheduler, hosted control plane, extra database, or billing.

## 0.4.0 — 2026-08-26

### Docs

- Empty Unreleased of items already shipped in 0.3.0 (#24)
- `docs/first-ten-minutes.md` uses `readyagents new my-flow` (default pipeline), not `--template pipeline` (#25)
- `NEXT.md` leftover marks extras, size caps, DNS rebind, parallel timeout/retry, packs JSON, and Makefile/CONTRIBUTING smoke as shipped (#26)

## 0.3.0 — 2026-08-22

### Added

- **Structured JSON logs** (`--log-format json` / `READYAGENTS_LOG_FORMAT=json`) with `run` and `node` on every event
- **Per-node token/cost tracking** rolled up on the run (`usage.prompt_tokens`, `completion_tokens`, `cost_micros`). Include nodes count nested agent usage once; parallel branches merge onto the fan-out node.
- **Budget limits** (`budget.max_tokens` / `budget.max_cost_usd` or env) stop further LLM work with `BudgetExceeded`
- **Model fallback** (`fallback_models` on the node or workflow) and a process-local **circuit breaker**
- **External decision injection:** `readyagents decide RUN_ID --file decisions.json` and `--decision-file` on `run`/`resume` (no always-on HTTP listener). Outbound `on_pause_url` notify only
- **Multi-gate example** `examples/multi_gate.yaml` (two sequential approvals)
- **Secrets-manager hooks** (env/`.env` remains default BYOK; packs may register backends)
- **Append-only audit trail** under `$READYAGENTS_HOME/audit/<run_id>.jsonl`
- **RBAC hooks** (`--actor`, pack `register_authorizers`) and optional **PII redaction**
- **Pydantic `output_schema`** on agent nodes (`StructuredOutputError` on mismatch)
- **Opt-in local LLM cache** (`READYAGENTS_LLM_CACHE=1`, `--no-cache` to skip)
- **Example connector pack** (`examples/packs/connector_pack.py`) proving the pack seam
- **`readyagents.testing`**: `run_workflow_spec`, `ScriptedLLM`, `RecordedLLM`, `run_eval`
- Official **Dockerfile** + **docker-compose.yml**; `make smoke` / `make ci` cover lint, tests, and keyless examples (dry-run, resume, approval, parallel, include)

### Reliability (folded from post-0.2.0)

- `readyagents new` overwrite refusal; `--log-level` on `run`; MCP tools cannot shadow sandbox `read_file`
- Nested `include` approval pauses the parent; `validate` rejects cycles; success prints `run_id:`
- Missing workflow path is `ConfigError` (exit 1); `--dry-run` stubs `write_file`; node timeouts return when the budget expires
- `http_get` refuses private/loopback/metadata hosts; file tools and `include` stay sandboxed

### Safety

- Core still has no always-on listener, scheduler, hosted control plane, extra database, or vendor secrets SDK. Those remain pack material.

## 0.2.0 — 2026-08-19

### Added

- **Approval node** (`type: approval`) — human-in-the-loop gate. Pauses the run (exit 2) until `--approve` / `--reject` or `readyagents resume`.
- **Per-node persistence** and **resume** from the last successful node (`readyagents resume RUN_ID`). Records are JSON under `.readyagents/runs/`, written atomically.
- **Run inspection:** `readyagents runs list|show|inspect|replay`, with `--json`, `--status`, `--workflow`, and `--limit`.
- **Scaffolding:** `readyagents new` with templates `basic`, `approval`, and `research`.
- **Parallel fan-out:** `type: parallel` with concurrent `branches`.
- **Sub-workflows:** `type: include` to compose another YAML workflow (depth-limited).
- **Dry-run token estimate** on agent nodes (`usage.estimated_tokens`).
- Examples: `approval_gate.yaml`, `fanout_gate.yaml`, `include_demo.yaml`.

### Changed

- Structured logs include `run=<id>` and `node=<id>`.
- `--dry-run` `parse_json` after an agent stub no longer crashes LLM examples.

### Safety

- Core still has no always-on scheduler, control plane, distributed recovery, alerting, or billing. Those remain pack material.
