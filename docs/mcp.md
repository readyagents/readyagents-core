# MCP toolkit

ReadyAgents includes an MCP **client** (call other servers from a workflow) and an MCP **server** (expose this toolkit to other agents).

MCP is an **optional extra**. Builtin tools are Python and need no Node.js.

```bash
pip install "readyagents[mcp]"
```

## Builtin tools (always available)

| Tool | Arguments | Notes |
| --- | --- | --- |
| `now` | — | UTC ISO-8601 |
| `calc` | `expression` | Arithmetic only (`+ - * / // % **`) |
| `json_get` | `data`, `path` | Dotted path into JSON/dict |
| `read_file` | `path` | Sandboxed to workspace |
| `write_file` | `path`, `content` | Sandboxed to workspace |
| `http_get` | `url` | Off until `READYAGENTS_ALLOW_HTTP=1` or `allow_http: true`; private/loopback/metadata URLs stay blocked |

## Client: MCP servers in a workflow

```yaml
mcp_servers:
  filesystem:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]

nodes:
  - id: list
    type: tool
    tool: filesystem.list_directory
    arguments:
      path: "."
```

If the workflow declares `mcp_servers` but `mcp` is not installed, you get a clear `MCPError` with the pip extra to install.

Core examples do **not** require MCP servers.

## Server: expose ReadyAgents

```bash
readyagents mcp serve
```

Speaks MCP over **stdio**. Other agents can call `now`, `calc`, `json_get`, `read_file`, `write_file`, `http_get` (if enabled), and `run_workflow`.

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

- `read_file` / `write_file` cannot escape the workspace directory
- YAML `workspace:` cannot relocate the sandbox outside `READYAGENTS_WORKSPACE`
- MCP `run_workflow` only loads a workflow file under that same root
- MCP client tools are registered as `server.tool` and cannot replace sandbox builtins (`read_file`)
- MCP stdio children do not inherit `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` unless set in `mcp_servers.*.env`
- `http_get` is opt-in
- `calc` does not evaluate arbitrary Python
