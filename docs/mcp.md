# MCP toolkit

ReadyAgents includes an MCP **client** (call other servers from a workflow) and an MCP **server** (expose this toolkit to other agents).

MCP is an **optional extra**. Builtin tools are Python and need no Node.js.

```bash
pip install -e ".[mcp]"
```

## Builtin tools (always available)

| Tool | Arguments | Notes |
| --- | --- | --- |
| `now` | — | UTC ISO-8601 |
| `calc` | `expression` | Arithmetic only (`+ - * / // % **`) |
| `json_get` | `data`, `path` | Dotted path into JSON/dict |
| `json_set` | `data`, `path`, `value` | Set a dotted path; returns the full document |
| `json_merge` | `data`, `path`, `value` | Merge an object at a dotted path (`""` / `"."` merges at the root) |
| `list_dir` | `path` (default `.`) | Sandboxed directory listing; skips dotfiles unless `include_hidden` |
| `read_file` | `path` | Sandboxed to workspace |
| `write_file` | `path`, `content` | Sandboxed to workspace |
| `http_get` | `url` | Off until `READYAGENTS_ALLOW_HTTP=1` or `allow_http: true`; private/loopback/metadata URLs stay blocked |

## List a workspace without MCP

Builtin `list_dir` is Python and needs no Node.js and no MCP filesystem server:

```bash
readyagents run examples/list_dir.yaml
readyagents run examples/list_dir.yaml --dry-run
```

## Client: MCP servers in a workflow

Optional. A workflow may call a third-party MCP server (that server may be written in any language). ReadyAgents itself does not require Node.js. Prefer builtin `list_dir` / `read_file` / `write_file` unless you need a remote server.

```yaml
mcp_servers:
  other:
    command: readyagents
    args: ["mcp", "serve"]
```

Each named server keeps **one stdio session** for the run (`list_tools` and `call_tool` reuse it). Tool JSON Schema from the server is passed through to agent `tools:`. `cwd` defaults to the workflow workspace and cannot escape it.

If the workflow declares `mcp_servers` but `mcp` is not installed, you get a clear `MCPError` with the pip extra to install.

Core examples do **not** require MCP servers.

## Server: expose ReadyAgents

```bash
readyagents mcp serve
```

Speaks MCP over **stdio**. Other agents can call `now`, `calc`, `json_get`, `json_set`, `json_merge`, `list_dir`, `read_file`, `write_file`, `http_get` (if enabled), and `run_workflow`.

`run_workflow` takes `path` (workflow file) and `inputs_json` (JSON object). `path` must stay under the server workspace (the same sandbox as `read_file` / `write_file`).

Point your MCP host at the `readyagents` CLI command. Example Claude Desktop / host config sketch:

```json
{
  "mcpServers": {
    "readyagents": {
      "command": "readyagents",
      "args": ["mcp", "serve"]
    }
  }
}
```

## Security notes

- `list_dir` / `read_file` / `write_file` cannot escape the workspace directory
- YAML `workspace:` cannot relocate the sandbox outside `READYAGENTS_WORKSPACE`
- MCP `run_workflow` only loads a workflow file under that same root
- MCP client tools are registered as `server.tool` and cannot replace sandbox builtins (`read_file`)
- MCP stdio children do not inherit `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` unless set in `mcp_servers.*.env`
- `http_get` is opt-in
- `calc` does not evaluate arbitrary Python
