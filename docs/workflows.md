# Workflows

Workflows are YAML or JSON documents validated with Pydantic.

## Minimal example

```yaml
name: hello
inputs:
  name: world
nodes:
  - id: greet
    type: transform
    template: "hello {{name}}"
    output_key: message
```

Run:

```bash
readyagents run hello.yaml --input name=Ada
```

## Fields

| Field | Meaning |
| --- | --- |
| `name` | Workflow name (stored on the run record) |
| `version` | Free-form string |
| `inputs` | Default inputs. A value may be a scalar or `{default, description}` |
| `required_inputs` | Keys that must be present after defaults + CLI |
| `start` | First node id (defaults to the first node) |
| `nodes` | List of node objects |
| `edges` | Optional `{from, to, when}` routing |
| `mcp_servers` | Map of name → `{command, args, env, cwd}` |
| `allow_http` | Enable builtin `http_get` |
| `workspace` | Override sandbox directory |
| `default_model` | Override `READYAGENTS_DEFAULT_MODEL` for agent nodes |

## Node fields (all types)

| Field | Meaning |
| --- | --- |
| `id` | Unique id |
| `type` | `agent` \| `tool` \| `condition` \| `transform` |
| `next` | Default successor if no edges |
| `output_key` | Alias for templates (`{{brief}}` instead of `{{write}}`) |
| `timeout_seconds` | Soft timeout |
| `retry` | `{max_attempts, backoff_seconds, backoff_multiplier}` |

If `next` and `edges` are omitted, the engine uses **list order** (the following node).

## Agent

```yaml
- id: draft
  type: agent
  model: openai:gpt-4o-mini   # optional
  system: You are concise.
  prompt: |
    Write a haiku about {{topic}}.
  output_key: haiku
```

Missing `{{variables}}` fail with `TemplateError`.

## Tool

```yaml
- id: math
  type: tool
  tool: calc
  arguments:
    expression: "1 + {{n}}"
  output_key: total
```

Builtin tools: `now`, `calc`, `json_get`, `read_file`, `write_file`, `http_get` (opt-in).

MCP tools are named `server.tool` (and also the bare tool name if unique).

## Condition

```yaml
- id: branch
  type: condition
  when: classified.priority == "urgent"
  then: urgent_reply
  else: normal_reply
```

Supported expressions (no Python `eval`):

- dotted path truthiness: `allow_http`
- comparisons: `== != > < >= <= contains startswith endswith`
- quoted strings, numbers, `true` / `false`
- `{{templates}}` on either side

## Transform

```yaml
- id: parse
  type: transform
  source: classification_raw
  parse_json: true
  output_key: classified

- id: pick
  type: transform
  source: classified
  json_path: priority
  output_key: priority

- id: line
  type: transform
  template: "status={{priority}}"
```

## Edges

```yaml
edges:
  - from: classify
    to: parse
  - from: parse
    to: urgent
    when: classified.priority == "urgent"
  - from: parse
    to: normal
```

An edge without `when` is the default if no conditioned edge matches.

## Run records

Successful and failed runs persist to `.readyagents/runs/<run_id>.json` unless you pass `--no-persist`.

## Examples in this repo

| File | Needs LLM | Notes |
| --- | --- | --- |
| `examples/calc_pipeline.yaml` | No | Clone-and-run smoke test |
| `examples/research_brief.yaml` | Yes | Optional HTTP fetch |
| `examples/support_triage.yaml` | Yes | JSON classify then branch |
| `examples/code_review.yaml` | Yes | Builtin `read_file` + review |
