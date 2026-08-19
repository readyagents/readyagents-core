# ReadyAgents Core 0.2.0

**The first release that feels like a toolkit you can trust for one-shot work.**

ReadyAgents Core is still the free, open-source engine: YAML workflows, BYOK, builtin tools, MCP optional, packs later. 0.1.0 proved clone-and-run. **0.2.0** is the reliability and operator-experience layer.

Apache-2.0. No vendor keys. No always-on runtime in core.

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

JSON under `.readyagents/runs/<id>.json`, written atomically after each node.

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
