# ReadyAgents Core — 0.8 brainstorm

Date: 2026-09-02
Scope: `readyagents-core` only (not the staging site, not Premium Packs).
Now: package **0.8.0** (eval CLI, `--pack`, `list_dir`, new templates, JSON envelope). PyPI publish slipped — install docs stay clone-only.
Method: engine/CLI/examples/docs as they sit today, 0.7 leftovers, and what a YAML+BYOK+MCP buyer actually needs.
Hard rules: **Python only — no Node.js.** No always-on listener, scheduler, hosted control plane, extra database, or billing.

## Headline

**Operator-complete local core: one-line install, `eval` as a command, load a pack from a path, list a workspace without MCP. Still one-shot. Still no Node.**

0.6 was list-shaped YAML and inspectable tool-use. 0.7 was honest composition resume and a real MCP client. 0.8 should not add a new node type. It should make the engine **installable, scoreable, and extensible from a file** so a careful engineer can try it without a clone ritual and without `npx`.

## 1. What is already strong (do not redo)

- **Clone-and-run, keyless.** `calc_pipeline`, `foreach_calc`, `gated_write`, approval family. No API keys, no Node, no extra servers.
- **Graph is the product.** `agent` / `tool` / `condition` / `transform` / `approval` / `parallel` / `include` / `foreach`. Bounded agent `tools:` loop. YAML glue (`default` / `len` / `join`, `and` / `or` / `not`).
- **HITL is a primitive.** Pause is exit 2, persist, `resume` / `decide`. Gate-before-`write_file` is documented and tested.
- **Resume does not re-bill** include / parallel / foreach snapshots.
- **BYOK + budgets + fallback + audit hooks.** Local JSON run store, HTML `runs report`, `--json` on the hot path.
- **MCP extra is Python.** Client sessions + `readyagents mcp serve`. Optional `[mcp]`.
- **Pack protocol exists.** Empty core entry-point group; example packs live under `examples/packs/` and are test-injected only.
- **Eval library exists.** `readyagents.testing.run_eval` / `EvalCase` — no CLI yet.
- **Packaging is ready.** hatchling sdist/wheel; README still says not on PyPI.

Site copy (“always-on packs”, waitlist) is **ahead of core**. 0.8 marketing must match the repo, not the waitlist.

## 2. Gaps that still hurt (0.8 material)

| Gap | Why it hurts |
| --- | --- |
| Not on PyPI | Clone + venv is a conversion killer. `uvx` / `pipx` is how Python CLIs are tried in 2026. |
| Eval is a library only | Market proof is “evals that gate a release.” CI cannot run `readyagents eval suite.yaml`. |
| Packs are install-or-nothing | `examples/packs/connector_pack.py` cannot be loaded by an operator without an entry point. The open-core story is invisible. |
| No `list_dir` | Agents and foreach workflows cannot see the workspace without an MCP filesystem server. Docs currently demo that server with **`npx`**, which we must not require. |
| `readyagents new` is 0.4-shaped | Engine has foreach, agent tools, gated write. Scaffold templates do not. |
| `--json` shapes differ by subcommand | Scripts special-case `validate` vs `run` vs `packs` vs missing `runs show`. |
| MCP docs lead with `npx` | Contradicts “No Node.js.” Calling a third-party Node MCP server is the *user’s* choice; it must not be our first example. |
| Fallback is per call | A flaky primary can flip-flop across nodes. Sticky fallback (process-local, already have a circuit breaker) is the small reliability win. |

## 3. Highest-ROI 0.8 cut (execute in order)

Cap is **six** engine/CLI items. One focused change per commit (CONTRIBUTING). Docs-only ride-alongs are not a version.

| # | Item | Why 0.8 | Done when |
| --- | --- | --- | --- |
| 1 | **PyPI 0.8.0** + install docs (`pip install readyagents`, `uvx readyagents run …`) | Distribution. Wheel already builds. Keep the clone path. | `pip index` / a test venv installs `readyagents==0.8.0`; README 60-second start is the one-liner; extras `[openai]`, `[anthropic]`, `[mcp]`, `[all]` work from PyPI. |
| 2 | **`readyagents eval PATH`** | Wrap the existing harness. Offline evals are the production gate buyers ask for. No hosted eval SaaS. | `readyagents eval tests/fixtures/…` (or `examples/eval/`) exits 0/1; `--json` prints `{ok, passed, failed, results}`; uses `ScriptedLLM` / recorded fixtures; **no network**. |
| 3 | **`--pack PATH` / `READYAGENTS_PACK`** | Load a local `BasePack` module without publishing an entry point. Proves packs without Premium. | `readyagents run examples/connector_demo.yaml --pack examples/packs/connector_pack.py` registers `connector_ping`; `readyagents packs --pack …` lists it; path must stay under workspace / cwd (no `/etc` escape). Repeatable flag. |
| 4 | **Sandboxed `list_dir` builtin** | Sibling of `read_file`. Size-capped, workspace-bound, no hidden files unless opted in. Replaces the npx filesystem demo for first-run. | Keyless example lists `examples/` (or a tmp workspace); `..` / symlink escape fails; `--dry-run` still lists (read-only); MCP `run_workflow` cannot list outside the workspace. |
| 5 | **`readyagents new` templates** `foreach`, `agent-tools`, `gated` | Engine + examples already exist (`foreach_calc`, `agent_tools`, `gated_write`). | `readyagents new demo --template foreach` (and the other two) writes three files and refuses overwrite; `pipeline` stays default; docs table lists them. |
| 6 | **Unified `--json` envelope** | `{ok, command, …}` on validate / run / resume / packs / eval / runs show-missing. | Every `--json` path is JSON on stdout, no Rich markup; success `ok: true`; pause is `ok: false` plus `run_id` and exit 2; missing run id is `ok: false` not a crash. One test module covers the envelope. |

### Ride-along (same release, not a seventh engine cut)

- MCP docs: first client example is **Python stdio** or builtin `list_dir`, not `npx @modelcontextprotocol/server-filesystem`.
- README: one comparison table (YAML-in-git, BYOK, HITL pause/resume, MCP client+server, local-only, Apache-2.0) vs LangGraph / n8n / CrewAI — honest cells, no fake checkmarks.
- Pin the `i-ran-this` issue template.
- Optional: `server.json` + Cursor/Claude `mcpServers.readyagents` snippet in `docs/mcp.md` (metadata only).

## 4. Risks of each idea

- **PyPI.** Publishing 0.8.0 while README still says “not on PyPI” on old clones. Mitigation: version bump + README/docs/outbound install notes in the same release; yank is worse than a late publish. Do not publish 0.7.0 after the fact unless we must.
- **Eval CLI.** Becoming a prompt-eval product. Mitigation: fixture workflows + expected status/outputs only (what `run_eval` already does). No LLM-as-judge, no live vendors in CI.
- **`--pack PATH`.** Arbitrary code exec (it is Python). Mitigation: same trust model as “you ran this clone”; confine the *path* to workspace; do not download packs; document it as local-only. Entry points stay the install path.
- **`list_dir`.** Leaking `.env` / `.git`. Mitigation: skip dotfiles by default; cap entries; no recursive dump without an explicit bounded `max_depth` (default 1).
- **New templates.** Drift from examples. Mitigation: templates stay short; examples remain the canonical demos; tests assert `new` output runs keyless.
- **JSON envelope.** Breaking scripts that parse today’s shapes. Mitigation: additive `ok` / `command` fields; keep existing keys (`run_id`, `error`, `message`) inside the envelope. Document as 0.8 CLI.

## 5. Explicitly not 0.8 (Premium / 0.9+ / never-core)

Do **not** add any of this in 0.8:

| Item | Why not now |
| --- | --- |
| Node.js, npm, npx, a JS frontend | Product rule. MCP extra is Python. Users may *call* a Node MCP server; we do not ship or require one. |
| Always-on workers, cron, queues, inbound HTTP | Premium Pack. Core is one-shot + resume. |
| Hosted control plane, SSO, multi-tenant, extra DBs, billing | Pack / site, not this repo. |
| Visual editor / drag-and-drop | Lies about the product (YAML in git). |
| Nested foreach, unbounded map | Complexity; 0.6 cap stands. |
| `http_request` POST | Real demand, real SSRF/body risk. Design in 0.9 with the same public-IP pin, method allowlist, size caps. Keep `http_get`. |
| Streaming tokens | Changes persist/resume and CLI. Not needed for YAML one-shot. |
| `runs cancel` as a daemon | Ctrl-C already persists `cancelled`. Cancelling *another* process is always-on-shaped. Optional tiny 0.9: mark a JSON record cancelled so `resume` refuses. |
| Sticky LLM fallback | Small and good; do it if 1–6 finish early, not instead of them. |
| Mocked live-vendor CI | Tests stay scripted. Do not add network as a gate. |
| Discord, waitlist features, site redesign | Other repo. |

## 6. Architecture choices (0.8)

Stay on existing seams. No new runtime process.

- **Eval CLI** → `readyagents.testing.run_eval` + a YAML list of `EvalCase` fields. Reuse `ScriptedLLM` / `RecordedLLM`. Exit 1 on failed cases, 0 on all pass.
- **Local pack** → import a module from a confined path; require a `get_pack()` or a `Pack` instance; merge through `collect_pack_*` already used by the engine.
- **`list_dir`** → next to `read_file` in builtin tools; same workspace sandbox (absolute / `..` / symlink rules); return a JSON list `{name, type, size}` capped.
- **Templates** → strings in `scaffold.py` only; no new engine types.
- **JSON envelope** → one helper in `cli.py` (`emit_json(ok=..., command=..., **fields)`); Rich stays default.
- **PyPI** → existing hatchling config; GitHub release tag `v0.8.0`; CI already has `ruff format --check`.

## 7. Suggested 0.8 messaging (repo, not ads)

Primary: **Local YAML agent workflow engine** (git-native, BYOK, pause/resume HITL).
Secondary: **MCP toolkit** (Python client + `mcp serve`) with no control plane.

Can claim: clone or `pip install`, run without keys, pause before writes, resume without re-running paid nodes, BYOK, Apache-2.0, optional MCP, load a local pack, eval fixtures in CI.

Cannot claim: hosted runs, visual builder, always-on, 500 connectors, Slack inbound as a product, nested map/reduce, Node-free *ecosystem* (third-party MCP servers may still be Node; **our** code is not).

Avoid: “autonomous employees”, “USB-C for AI”, “the n8n of X”, “production-ready” with no eval command.

## 8. Definition of done

- This file describes 0.8 (0.2–0.7 brainstorms are history in git).
- Items 1–6 shipped, tested, documented; ride-alongs in the same tag if cheap.
- `python -m pytest` green; keyless `calc_pipeline`, `foreach_calc`, `gated_write`, `approval_gate` still behave.
- `readyagents eval` runs without keys; `--pack` loads the in-tree connector example; `list_dir` example is keyless; `new --template foreach` runs.
- `src/` still has no scheduler, inbound listener, Node toolchain, or extra database.
- README install line matches PyPI reality (or still says clone-only if publish is blocked — then item 1 is explicitly slipped, not faked).
