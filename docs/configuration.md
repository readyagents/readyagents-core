# Configuration (BYOK)

ReadyAgents is bring-your-own-key. Nothing in this repository contains LLM credentials.

## Load order

For each setting, the first non-empty value wins:

1. Process environment variables
2. `.env` in the current working directory
3. `.env-ai` in the current working directory (local operator file; gitignored)

Copy `.env.example` to `.env` and fill in keys.

## LLM keys and default model

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` or `READYAGENTS_OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` or `READYAGENTS_ANTHROPIC_API_KEY` | Anthropic |
| `OPENAI_COMPAT_API_KEY` or `READYAGENTS_OPENAI_COMPAT_API_KEY` | Groq / Ollama / compatible |
| `OPENAI_COMPAT_BASE_URL` | Base URL for compatible APIs |
| `READYAGENTS_DEFAULT_MODEL` | `provider:model`, e.g. `openai:gpt-4o-mini` |

Model references:

- `openai:gpt-4o-mini`
- `anthropic:claude-sonnet-4-5`
- `openai-compat:llama-3.1-8b-instant` (requires `OPENAI_COMPAT_BASE_URL`)
- `groq:llama-3.1-8b-instant` (defaults Groq base URL)
- `ollama:llama3` (defaults `http://127.0.0.1:11434/v1`)

Install extras to talk to a provider:

```bash
pip install "readyagents[openai]"
pip install "readyagents[anthropic]"
pip install "readyagents[all]"
```

If an agent node runs with no key, the CLI exits with a short `LLMError` telling you which variable to set — not a traceback dump.

If the node has no explicit `model:` and the default provider has no key, the engine uses the provider that *does* have a key (Anthropic, then OpenAI-compatible). An explicit `model: openai:...` still requires that key.

## Other settings

| Variable | Purpose |
| --- | --- |
| `READYAGENTS_ALLOW_HTTP` | `1` / `true` enables builtin `http_get` |
| `READYAGENTS_WORKSPACE` | Sandbox root for `read_file` / `write_file` (default: cwd) |
| `READYAGENTS_HOME` | Artifact directory (default: `.readyagents`). Run JSON lives in `$READYAGENTS_HOME/runs/` |
| `READYAGENTS_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. Log lines include `run=` and `node=` |

Inspect and resume those records with `readyagents runs list`, `readyagents runs show`, and `readyagents resume`.

Workflow YAML may also set `allow_http: true` and `workspace:`. Either the env flag or the workflow flag enables HTTP.

## Files you should never commit

- `.env`, `.env.local`, `.env-ai`
- `.keys/`
- `.readyagents/` (run records)

`.env.example` contains placeholders only and is safe to commit.
