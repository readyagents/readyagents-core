# ReadyAgents Core — high-ROI brainstorm

Date: 2026-08-19  
Scope: `readyagents-core` only (not the staging site, not Premium Packs).  
Method: read the engine, CLI, tests, examples, docs, and the three commits on `main`.

## 1. What is already strong

The core is small and opinionated in the right places.

- **Clone-and-run path.** `examples/calc_pipeline.yaml` needs no API keys, no Node.js, no extra servers. That is the right first impression for an open-core toolkit.
- **BYOK is real.** Empty `.env.example`, `require_api_key` / `get_provider` fail with an operator-facing message, no vendor keys in `src/` or examples.
- **Graph engine is the product.** Typed YAML/JSON schema, tool / transform / condition / agent nodes, retries, timeouts, cycle detection, pack-registered node types. The engine accepts a tool registry and an LLM stand-in, so tests do not need the network.
- **Local-first tools.** `now`, `calc`, `json_get`, sandboxed `read_file` / `write_file`, opt-in `http_get`. MCP is an extra, not a requirement.
- **Pack seam is clean.** Empty `readyagents.packs` entry point, `discover_packs()` is `[]` in core, `BasePack` is a protocol. Premium can plug in without forking the engine.
- **Operator CLI is honest.** Typer + Rich, `--dry-run`, `--no-persist`, `validate`, `mcp serve`. Errors are typed (`NodeError`, `LLMError`, `ApprovalRequired`) rather than stack dumps.

Uncommitted work on this branch (this session) already adds the reliability primitives the product was missing: **approval nodes**, **persist-after-each-node + resume**, **`runs list/show/inspect/replay`**, and **`readyagents new`**. Those match the highest-ROI list below.

## 2. Biggest gaps that still hurt real usability

Even with the reliability primitives in place, a careful engineer still hits friction:

| Gap | Why it hurts |
| --- | --- |
| HITL without a TTY | Approval must pause and persist, not block. (Addressed: `--approve` / `--reject` / `resume`.) |
| Crash / failed mid-graph | Without per-node persist + resume, a 6-node workflow is all-or-nothing. (Addressed.) |
| “Did it run? What did node 3 return?” | Need `runs list` + timeline. (Addressed.) |
| Empty-directory onboarding | `init` only writes `.env`. Need `new` → workflow + README + `.env.example`. (Addressed.) |
| `--dry-run` after `parse_json` | `support_triage` dry-run still dies because the agent stub is not JSON. LLM examples feel broken without keys. |
| Machine-readable inspect | `runs show` is a Rich table. Scripts and CI cannot consume it. |
| Makefile / CONTRIBUTING lag | Docs and `make run-example` still look like a 3-command toy. |
| Pre-alpha packaging | No PyPI release (out of scope this session), 0 stars, three commits. Trust comes from the runnable path, not marketing. |

## 3. Highest-ROI improvements for this session

Priority matches “reliability, DX, ready-to-use” and stays inside core.

| # | Item | ROI | Status this session |
| --- | --- | --- | --- |
| 1 | Human-in-the-loop `approval` node | High — production workflows need a gate | Implement |
| 2 | Persist after each node + resume from last success | High — the difference between a demo and a tool | Implement |
| 3 | `readyagents runs list` / `show` / `inspect` / `replay` + `run=`/`node=` logs | High — observability without a control plane | Implement |
| 4 | `readyagents new` scaffolding | High — first-run DX | Implement |
| 5 | New keyless HITL example + polish existing examples | Medium-high — proves 1–4 | Implement |
| 6 | Tests on the shipped path (CLI, engine, resume, scaffold) | Required | Implement |
| 7 | README + `docs/*.md` match the new CLI | Required | Implement |
| 8 | Dry-run `parse_json` fallback so LLM examples walk without keys | Medium — leftover DX hole | Implement |
| 9 | `runs show --json` / `runs list --json` | Medium — inspect for scripts | Implement |

Items 1–7 are the user-stated preference order. 8–9 are small, same-architecture follow-through so examples and inspection feel finished.

## 4. Risks of each idea

- **Approval node.** Interactive `input()` would hang CI and this environment. Mitigation: never block; raise `ApprovalRequired`, persist `paused` + `pending_node`, continue only with `--approve` / `--reject`.
- **Per-node persist.** Extra disk I/O; crash between persist and next node. Mitigation: overwrite one JSON file per `run_id`; resume skips `status=ok` nodes and retries the pending/failed node. No database.
- **Resume of a succeeded run.** Easy to confuse with replay. Mitigation: refuse resume of `succeeded`; `runs replay` starts a new run from stored inputs.
- **Scaffolding.** Overwriting user files. Mitigation: refuse if `workflow.yaml` / `README.md` / `.env.example` already exist.
- **Dry-run JSON stub.** A fake object could hide template bugs. Mitigation: only when the value already starts with `[dry-run]`; real runs still parse strictly.
- **`--json`.** Two output shapes. Mitigation: flag-gated; default remains the table.

## 5. What must stay out of core (Premium Packs / later)

Do **not** add any of this here:

- Always-on / continuous workers, schedulers, cron loops, queue consumers
- Hosted control plane, multi-tenant teams, RBAC, SSO
- Distributed recovery, replicas, consensus, remote run stores
- Alerting, paging, SLO dashboards, billing (Polar)
- New LLM vendors or live-network tests as a gate
- Heavy deps (databases, OpenTelemetry stacks, web UIs)

Those compose via `readyagents.packs` when they exist.

## 6. Architecture choices (this session)

Keep extending existing seams:

- New node type `approval` next to `condition` (same `then` / `else` routing).
- `ExecutionContext.decisions` + `on_persist` callback so tests inject decisions and a runs dir with no TTY.
- JSON files under `$READYAGENTS_HOME/runs/<run_id>.json` (stdlib only).
- CLI sub-app `runs` and top-level `resume` / `new`.
- Structured logs via the existing logger: `run=%(run_id)s node=%(node_id)s`.

## 7. Definition of done

- This file is in the repo.
- Items 1–7 shipped, tested, documented; 8–9 if time.
- `python -m pytest` green; `calc_pipeline` CLI succeeds twice; `approval_gate` pauses and resumes; `readyagents new` writes three files; `runs list` / `show` print a run id and a node timeline.
- `src/` still has no always-on scheduler or distributed recovery.
