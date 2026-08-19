"""Create a starter ReadyAgents project (workflow + README + .env pattern)."""

from __future__ import annotations

from pathlib import Path

from readyagents.errors import ConfigError

TEMPLATES = ("basic", "approval", "research", "pipeline", "review")

_ENV = """# ReadyAgents BYOK — fill in your keys. Never commit real keys.

READYAGENTS_DEFAULT_MODEL=openai:gpt-4o-mini
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
# READYAGENTS_ALLOW_HTTP=0
"""

_WORKFLOWS: dict[str, str] = {
    "basic": """name: {name}
version: "1"
description: >
  Basic starter from `readyagents new --template basic`. No API keys.
  Run: readyagents run workflow.yaml

start: stamp
nodes:
  - id: stamp
    type: tool
    tool: now
    output_key: timestamp
    next: greet

  - id: greet
    type: transform
    template: "{name} ok at {{{{timestamp}}}}"
    output_key: summary
""",
    "approval": """name: {name}
version: "1"
description: >
  Approval starter from `readyagents new --template approval`. No API keys.
  Run: readyagents run workflow.yaml --approve gate

start: stamp
nodes:
  - id: stamp
    type: tool
    tool: now
    output_key: timestamp
    next: greet

  - id: greet
    type: transform
    template: "{name} ok at {{{{timestamp}}}}"
    output_key: summary
    next: gate

  - id: gate
    type: approval
    prompt: "Accept starter summary? {{{{summary}}}}"
    then: done
    else: stopped

  - id: done
    type: transform
    template: "approved: {{{{summary}}}}"
    output_key: result

  - id: stopped
    type: transform
    template: "rejected: {{{{summary}}}}"
    output_key: result
""",
    "pipeline": """name: {name}
version: "1"
description: >
  Keyless pipeline starter (`--template pipeline`): calc, json_get, condition.
  Run: readyagents run workflow.yaml

start: add
nodes:
  - id: add
    type: tool
    tool: calc
    arguments:
      expression: "6 * 7"
    output_key: n
    next: pack

  - id: pack
    type: transform
    template: '{{"n": {{{{n}}}}}}'
    output_key: blob
    next: pick

  - id: pick
    type: tool
    tool: json_get
    arguments:
      data: "{{{{blob}}}}"
      path: n
    output_key: extracted
    next: check

  - id: check
    type: condition
    when: extracted == 42
    then: ok
    else: bad

  - id: ok
    type: transform
    template: "{name} pipeline ok: {{{{extracted}}}}"
    output_key: summary

  - id: bad
    type: transform
    template: "{name} pipeline unexpected: {{{{extracted}}}}"
    output_key: summary
""",
    "review": """name: {name}
version: "1"
description: >
  File-review starter (`--template review`). Reads a workspace file, then a
  transform you can later swap for an agent node. No API keys.
  Run: readyagents run workflow.yaml --input path=README.md

inputs:
  path: README.md

start: read
nodes:
  - id: read
    type: tool
    tool: read_file
    arguments:
      path: "{{{{path}}}}"
    output_key: source
    next: note

  - id: note
    type: transform
    template: "review {{{{path}}}} ({name}): {{{{source}}}}"
    output_key: summary
    next: gate

  - id: gate
    type: approval
    prompt: "Accept review of {{{{path}}}}?"
    then: done
    else: hold

  - id: done
    type: transform
    template: "accepted: {{{{path}}}}"
    output_key: result

  - id: hold
    type: transform
    template: "held: {{{{path}}}}"
    output_key: result
""",
    "research": """name: {name}
version: "1"
description: >
  Research-style starter. Fan-out two builtin tools, then an approval gate.
  No API keys. Run: readyagents run workflow.yaml --approve publish

start: fan
nodes:
  - id: fan
    type: parallel
    output_key: parts
    next: combine
    branches:
      - id: math
        type: tool
        tool: calc
        arguments:
          expression: "21 * 2"
      - id: when
        type: tool
        tool: now

  - id: combine
    type: transform
    template: "value={{{{parts.math}}}} at {{{{parts.when}}}}"
    output_key: brief
    next: publish

  - id: publish
    type: approval
    prompt: "Publish brief? {{{{brief}}}}"
    then: ok
    else: hold

  - id: ok
    type: transform
    template: "{name} published: {{{{brief}}}}"
    output_key: result

  - id: hold
    type: transform
    template: "{name} held: {{{{brief}}}}"
    output_key: result
""",
}

_READMES: dict[str, str] = {
    "basic": """# {name}

Basic ReadyAgents starter (`--template basic`). BYOK. No approval gate.

```bash
readyagents run workflow.yaml
readyagents runs list
readyagents runs show <run_id>
```

Copy `.env.example` to `.env` if you add agent nodes.
""",
    "approval": """# {name}

Approval starter (`--template approval`). BYOK.

```bash
readyagents run workflow.yaml --approve gate
# or pause, then:
readyagents run workflow.yaml
readyagents resume <run_id> --approve gate
```

Copy `.env.example` to `.env` if you add agent nodes.
""",
    "pipeline": """# {name}

Pipeline starter (`--template pipeline`). Builtin tools only.

```bash
readyagents run workflow.yaml
readyagents runs show <run_id>
readyagents runs report <run_id>
```
""",
    "review": """# {name}

File-review starter (`--template review`). Keyless transform; swap `note` for
an `agent` node when you add API keys.

```bash
readyagents run workflow.yaml --input path=README.md --approve gate
readyagents resume <run_id> --approve gate
```
""",
    "research": """# {name}

Research-style starter (`--template research`): parallel fan-out + approval.

```bash
readyagents run workflow.yaml --approve publish
readyagents run workflow.yaml --dry-run --approve publish
```

No API keys required. Add `type: agent` nodes and keys later.
""",
}


def create_project(dest: Path, *, name: str, template: str = "pipeline") -> list[Path]:
    dest = dest.expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    kind = (template or "pipeline").strip().lower()
    if kind not in _WORKFLOWS:
        raise ConfigError(
            f"Unknown template '{template}'. Choose one of: {', '.join(TEMPLATES)}"
        )
    workflow = dest / "workflow.yaml"
    readme = dest / "README.md"
    env_example = dest / ".env.example"
    for path in (workflow, readme, env_example):
        if path.exists():
            raise ConfigError(f"Refusing to overwrite existing file: {path}")
    slug = _slug(name)
    workflow.write_text(_WORKFLOWS[kind].format(name=slug), encoding="utf-8")
    readme.write_text(_READMES[kind].format(name=slug), encoding="utf-8")
    env_example.write_text(_ENV, encoding="utf-8")
    return [workflow, readme, env_example]


def _slug(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name.strip())
    cleaned = cleaned.strip("-_") or "starter"
    return cleaned
