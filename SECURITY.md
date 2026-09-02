# Security

## Reporting

If you find a vulnerability in ReadyAgents Core, please **do not** open a public issue.

The GitHub account [readyagents](https://github.com/readyagents) is a **User**, not an Organization.

Use [private vulnerability reporting](https://github.com/readyagents/readyagents-core/security/advisories/new) on this repository. That form is the working contact.

Include:

- A description of the issue
- Steps to reproduce
- Impact (file sandbox escape, prompt/tool injection, secret leakage, etc.)

We will acknowledge the report and work on a fix before any disclosure.

## Scope notes

- `read_file` / `write_file` / `list_dir` are intentionally sandboxed to a workspace directory (symlinks and `..` cannot escape; writes are atomic)
- `type: include` paths must stay under the parent workflow directory
- `http_get` is disabled unless explicitly opted in, and even then refuses loopback, private, link-local, and metadata hosts (including after redirects)
- `calc` is a restricted arithmetic evaluator, not Python `eval`
- API keys live in the environment / local env files and must never be committed

## Secrets in issues and PRs

Do not paste API keys, `.env`, or `.env-ai` contents into GitHub.
