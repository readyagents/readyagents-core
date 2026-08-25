# ReadyAgents Core 0.4.0

**Docs honesty after 0.3.0. No new nodes. No always-on.**

0.4.0 labels the honesty PRs that landed on main after the 0.3.0 engine:

- CHANGELOG Unreleased no longer lists items already in 0.3.0 (#24)
- first-ten-minutes matches README: `readyagents new my-flow` (default is pipeline) (#25)
- NEXT leftover marks extras, size caps, DNS rebind, parallel timeout/retry, packs JSON, and Makefile/CONTRIBUTING smoke as shipped (#26)

The engine is still 0.3.0's. Install from a clone (`pip install -e .`). This package is not on PyPI.

---

# ReadyAgents Core 0.3.0

**Enterprise hooks that still fit a small, local, YAML-first core.**

ReadyAgents Core remains the free engine: YAML workflows, BYOK, builtin tools, MCP optional, packs for extensions. **0.2.0** made runs durable and inspectable. **0.3.0** adds the operator controls companies ask for — cost, approvals from outside the CLI, secrets/RBAC/audit hooks, structured output, a local cache — without an always-on control plane.

Apache-2.0. No vendor keys. No hosted runtime in core.

## Why this release matters

A careful team running agent graphs in production needs more than pause/resume:

1. **See cost per node** and stop when a budget is hit.
2. **Approve from a ticket or webhook pack**, not only `--approve` on a TTY.
3. **Ship the wheel** (PyPI-ready) and a one-service Dockerfile.
4. **Hook secrets, RBAC, and an append-only audit log** without vendoring Vault/AWS.
5. **Validate LLM JSON with Pydantic**, cache identical calls, and test workflows offline.

Core stays small. Packs still own connectors, inbound HTTP, and policy engines.

## What is new

### Observability and cost

JSON logs (`readyagents --log-format json …`) emit machine-parseable events with `run` and `node`. Agent nodes record `prompt_tokens` / `completion_tokens` / `cost_micros` on the node result; the run total is the sum. Dry-run still reports `estimated_tokens`.

```yaml
budget:
  max_tokens: 50000
  max_cost_usd: 1.0
fallback_models:
  - anthropic:claude-sonnet-4-5
circuit:
  failure_threshold: 3
  cooldown_seconds: 60
```

`BudgetExceeded` is typed. A failing primary model is retried on `fallback_models`. A process-local circuit breaker skips a recently failing model until cooldown.

### Approvals beyond the CLI

`--approve` / `--reject` and exit 2 still work. A paused run can also take a JSON payload:

```bash
readyagents run examples/approval_gate.yaml          # exit 2
readyagents decide <run_id> --file decision.json     # {"gate": "approve"}
# or
readyagents resume <run_id> --decision-file decision.json
readyagents run examples/multi_gate.yaml --approve first --approve second
```

Set `on_pause_url` (or `READYAGENTS_PAUSE_NOTIFY_URL`) for an **outbound** POST when a gate pauses. Core does not listen on a port.

### Security hooks

- Secrets backends via pack `register_secrets()`; env/`.env` remains the default BYOK path
- Append-only `$READYAGENTS_HOME/audit/<run_id>.jsonl` (resume snapshots still overwrite the run JSON)
- `--actor` plus pack `register_authorizers()` (`AuthorizationError` on deny)
- `READYAGENTS_REDACT=1` masks emails, `sk-…` keys, and `READYAGENTS_REDACT_LITERALS`

### Structured output, cache, packs

```yaml
- id: classify
  type: agent
  prompt: Return JSON.
  output_schema:
    type: object
    required: [priority]
    properties:
      priority: {type: string}
```

Invalid JSON raises `StructuredOutputError`. `READYAGENTS_LLM_CACHE=1` stores completions under `$READYAGENTS_HOME/cache/` (`--no-cache` skips). `examples/packs/connector_pack.py` is a local connector (no network) that registers `connector_ping`.

### Test helpers

```python
from readyagents.testing import EvalCase, RecordedLLM, ScriptedLLM, run_eval, run_workflow_spec
```

`RecordedLLM` replays a cassette with no network. `run_eval` scores pass/fail fixture workflows.

### Deploy

```bash
python -m build          # sdist + wheel (not published from this repo)
docker compose run --rm readyagents run examples/calc_pipeline.yaml
make smoke               # lint is separate: make ci
```

## Try it (no API keys)

```bash
pip install -e .
readyagents run examples/calc_pipeline.yaml
readyagents run examples/approval_gate.yaml
readyagents decide <run_id> --node gate --decision approve
readyagents run examples/multi_gate.yaml --approve first --approve second
readyagents run examples/support_triage.yaml --dry-run --input message=hello
```

## What we deliberately left out of core

- Always-on webhook listeners, workers, cron, queue consumers
- Hosted control plane, SSO, multi-tenant teams, billing
- OpenTelemetry stacks, extra databases, AWS/GCP/Vault SDKs
- New LLM vendors or live-network tests as a gate

## Compatibility

- Python 3.11+
- Existing 0.2.0 workflow YAML still runs. New fields (`budget`, `fallback_models`, `output_schema`, `cache`, `on_pause_url`) are additive.
- CLI exit code **2** is still “paused for approval”.

## Docs

- [README](README.md)
- [Changelog](CHANGELOG.md)
- [Getting started](docs/getting-started.md)
- [Workflows](docs/workflows.md)
- [CLI](docs/cli.md)
- [Configuration](docs/configuration.md)
- [Packs](docs/packs.md)

## Why this release matters

A careful engineer running agent graphs needs four things a playground does not:

1. **A human can stop a run.** Approval nodes pause (they do not hang a TTY).
2. **A failed step is not a lost run.** State is written after every node; `resume` continues from the last success.
3. **You can see what happened.** `runs list` / `show` / `inspect` / `replay`.
4. **Starting a project is boring in the good way.** `readyagents new` writes a workflow, README, and `.env.example`.

That is the difference between a demo engine and something you would actually use.

## What is new

### Human-in-the-loop

```yaml
- id: gate
  type: approval
  prompt: "Release payment of {{total}}?"
  then: receipt
  else: denied
```

Without a decision the CLI exits **2**, persists `paused`, and tells you how to continue:

```bash
readyagents run examples/approval_gate.yaml
readyagents resume <run_id> --approve gate
# or
readyagents run examples/approval_gate.yaml --approve gate
```

### Durable local runs

JSON under `.readyagents/runs/<run_id>.json`, written atomically after each node.

```bash
readyagents runs list
readyagents runs show <run_id>
readyagents runs show <run_id> --json
readyagents runs replay <run_id>
readyagents resume <run_id> --approve gate
```

Filters: `--status`, `--workflow`, `--limit`. Logs include `run=` and `node=`.

### Composition

- **`type: parallel`** — independent branches concurrently (`examples/fanout_gate.yaml`)
- **`type: include`** — run another workflow file (`examples/include_demo.yaml`)

### Scaffolding

```bash
readyagents new my-flow                     # approval template (default)
readyagents new my-flow --template basic
readyagents new my-flow --template research # parallel + approval
```

Each writes `workflow.yaml`, `README.md`, and `.env.example`.

### Dry-run

Agent nodes report `usage: estimated_tokens=…`. LLM examples that `parse_json` after an agent no longer crash on the dry-run stub.

## Try it (no API keys)

```bash
pip install -e .
readyagents run examples/calc_pipeline.yaml
readyagents runs list

readyagents run examples/approval_gate.yaml --approve gate
readyagents run examples/fanout_gate.yaml --approve gate
readyagents run examples/include_demo.yaml

readyagents new demo --template research
readyagents run demo/workflow.yaml --approve publish
```

With keys, the existing research / triage / review examples still work. `--dry-run` still walks them without calling a vendor.

## What we deliberately left out of core

These belong in **Premium Packs**, not this repository:

- Always-on / continuous workers and schedulers
- Hosted control plane, teams, SSO
- Distributed recovery and remote run stores
- Alerting, paging, billing

Core stays small so those can plug in via `readyagents.packs`.

## Compatibility

- Python 3.11+
- Existing 0.1.0 workflow YAML still runs. New node types (`approval`, `parallel`, `include`) are additive.
- CLI exit code **2** now means “paused for approval”, not a generic failure.

## Docs

- [README](README.md)
- [Changelog](CHANGELOG.md)
- [Getting started](docs/getting-started.md)
- [Workflows](docs/workflows.md)
- [CLI](docs/cli.md)
