# Concepts

ReadyAgents Core is a small engine that runs a **graph of nodes**. Each node is typed. State is a JSON-like document that grows as nodes finish.

## Workflow

A workflow is a YAML (or JSON) file with:

- `name` and optional `description`
- `inputs` — default values for `{{variables}}`
- `nodes` — the work
- optional `edges` — explicit routing (otherwise `next` or list order)
- optional `mcp_servers` — extra tools started as MCP subprocesses
- `allow_http` — opt-in for the builtin `http_get` tool

## Node types

| Type | Role |
| --- | --- |
| `agent` | LLM call with a prompt template |
| `tool` | Call a named builtin, pack, or MCP tool |
| `condition` | Branch on a small expression |
| `transform` | Template, JSON parse, or dotted-path extract |

Packs may register additional node types.

## State

For a run, the engine keeps:

- `inputs` — merged defaults + `--input`
- `node_outputs` — raw output keyed by node id
- `output_keys` — optional aliases (`output_key: brief`)
- `metadata` — source path, dry-run flag, workspace, `allow_http`
- `errors` — if the run failed

Templates see a merged namespace: inputs, metadata, node ids, and output keys. `{{topic}}` and `{{plan}}` both work if those names exist.

## Reliability

Each node may set:

```yaml
timeout_seconds: 60
retry:
  max_attempts: 3
  backoff_seconds: 1
  backoff_multiplier: 2
```

Failures raise typed errors (`NodeError`, `LLMError`, `MCPError`, …) instead of a bare stack dump in the CLI.

## Extension: packs

Core is complete on its own. A pack is an installed Python package that exposes an entry point in group `readyagents.packs`. It can register tools, node types, and bundled workflows. See [packs.md](packs.md).

## MCP

MCP is optional. Builtin tools are Python. You do not need Node.js unless you attach an MCP server that requires it.
