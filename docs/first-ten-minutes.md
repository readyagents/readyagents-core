# First ten minutes

No API keys. The package is **not on PyPI** — install from a clone (`pip install -e .`) as in the [README](../README.md).

## 1. Prove the engine works

```bash
readyagents run examples/calc_pipeline.yaml
readyagents runs list
readyagents runs report <run_id>
```

`calc_pipeline` is builtin tools only (`calc`, `now`, `json_get`). The HTML report is local. Nothing is uploaded.

## 2. Pause is not a crash

```bash
readyagents run examples/approval_gate.yaml
```

The CLI exits **2** and the run status is `paused`. That means a human gate is waiting, not that the install failed.

```bash
readyagents resume <run_id> --approve gate
# or
readyagents resume <run_id> --reject gate
```

Same-shot: `readyagents run examples/approval_gate.yaml --approve gate`.

Or inject a JSON decision without `--approve` flags:

```bash
readyagents decide <run_id> --node gate --decision approve
```

## 3. Start your own file

```bash
readyagents new my-flow
readyagents run my-flow/workflow.yaml
```

`pipeline` is keyless. Add an `agent` node only after you install an extra from this checkout (`pip install -e ".[openai]"` or `".[anthropic]"`) and put your own key in `.env`.

## Next

- [Getting started](getting-started.md) — more examples, including LLM ones
- [Workflows](workflows.md) — YAML syntax
- [CLI](cli.md) — every command
