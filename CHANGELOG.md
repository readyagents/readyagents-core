# Changelog

All notable changes to ReadyAgents Core.

## Unreleased

- Implicit default model uses the BYOK provider that has a key (explicit `model:` is unchanged)
- `readyagents new` defaults to the keyless `pipeline` template (`--template approval` still works)
- HTML run reports: `readyagents runs report RUN_ID`
- Extra `readyagents new` templates: `pipeline`, `review`
- Example `examples/composed_gate.yaml` (include + parallel + approval)
- Clearer errors for unknown node types, missing includes, and parallel branch failures

## 0.2.0 — 2026-08-19

### Added

- **Approval node** (`type: approval`) — human-in-the-loop gate. Pauses the run (exit 2) until `--approve` / `--reject` or `readyagents resume`.
- **Per-node persistence** and **resume** from the last successful node (`readyagents resume RUN_ID`). Records are JSON under `.readyagents/runs/`, written atomically.
- **Run inspection:** `readyagents runs list|show|inspect|replay`, with `--json`, `--status`, `--workflow`, and `--limit`.
- **Scaffolding:** `readyagents new` with templates `basic`, `approval`, and `research`.
- **Parallel fan-out:** `type: parallel` with concurrent `branches`.
- **Sub-workflows:** `type: include` to compose another YAML workflow (depth-limited).
- **Dry-run token estimate** on agent nodes (`usage.estimated_tokens`).
- Examples: `approval_gate.yaml`, `fanout_gate.yaml`, `include_demo.yaml`.

### Changed

- Structured logs include `run=<id>` and `node=<id>`.
- `--dry-run` `parse_json` after an agent stub no longer crashes LLM examples.

### Safety

- Core still has no always-on scheduler, control plane, distributed recovery, alerting, or billing. Those remain pack material.
