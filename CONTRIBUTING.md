# Contributing

Thanks for improving ReadyAgents Core.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Checks

```bash
make test
make lint
make run-example
```

`make lint` is `ruff check` plus `ruff format --check`. `make run-example` smokes `calc_pipeline`, `approval_gate`, and `composed_gate` (keyless).

Or:

```bash
python -m pytest
ruff check src tests
ruff format --check src tests
readyagents run examples/calc_pipeline.yaml
readyagents run examples/approval_gate.yaml --approve gate
readyagents run examples/composed_gate.yaml --approve gate
```

Tests must not use the network or real API keys. Mock LLM providers.
Approval nodes must be driven with `--approve` / `--reject` (or `ExecutionContext.decisions`) — never a blocking prompt.

## Guidelines

- Keep the core small. Always-on / continuous systems belong in a **pack**, not this repo.
- Typed errors over generic exceptions.
- BYOK only — never commit secrets. `.env`, `.env-ai`, and `.keys/` are gitignored.
- Apache-2.0 for original contributions unless you say otherwise in the PR.

## Pull requests

1. One focused change per PR
2. Tests for engine/schema/tool behavior you touch
3. No generated secrets, no run artifacts under `.readyagents/`
