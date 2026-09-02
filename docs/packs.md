# Packs

ReadyAgents is **open-core**. This repository is the free engine. Commercial or extra capability layers are **packs**: installed Python packages that register extra tools, node types, and workflows.

Core runs with **zero packs**.

## Protocol

A pack implements:

```python
from readyagents.packs import BasePack
from readyagents.tools import FunctionTool

class ContinuousPack(BasePack):
    name = "continuous"
    version = "1.0.0"

    def register_tools(self):
        return [
            FunctionTool(
                name="watch_queue",
                description="example always-on helper (not published)",
                handler=lambda: "not in core",
            )
        ]

    def register_nodes(self):
        return {}  # optional NodeHandler keyed by type name

    def register_workflows(self):
        return []  # optional bundled workflow paths or dicts

    def register_secrets(self):
        return []  # optional SecretsBackend objects (Vault/AWS belong here, not in core)

    def register_authorizers(self):
        return []  # optional RBAC hooks; core default is allow-all
```

`register_nodes()` values should expose `type_name` and `execute(node, state, context)`.

## Discovery

Packs are loaded from the `readyagents.packs` [entry point](https://packaging.python.org/en/latest/specifications/entry-points/) group.

In a future `readyagents-pack-continuous` project:

```toml
[project]
name = "readyagents-pack-continuous"

[project.entry-points."readyagents.packs"]
continuous = "readyagents_pack_continuous:get_pack"
```

```python
# readyagents_pack_continuous/__init__.py
def get_pack():
    return ContinuousPack()
```

This pack is not published.

The engine calls `discover_packs()` at run start and merges tools/node handlers. No change to core YAML is required except using the new tool or node type names.

## Design rule

Packs **compose on top** of core. They must not fork the engine. Always-on / continuous execution, hosted control planes, inbound webhook listeners, and premium connectors belong in packs — not in `readyagents-core`.

An in-tree example connector (local, no network) lives at `examples/packs/connector_pack.py` and registers the `connector_ping` tool. Core’s `readyagents.packs` entry-point group stays empty.

Load a pack from a Python file without installing an entry point. The path is confined to the workspace (`READYAGENTS_WORKSPACE` or the current directory). `..`, symlink escapes, and paths such as `/etc/passwd` are refused.

```bash
readyagents run examples/connector_demo.yaml --pack examples/packs/connector_pack.py
readyagents packs --pack examples/packs/connector_pack.py
```

`--pack` is repeatable. `READYAGENTS_PACK` may hold one path, or several separated by `os.pathsep` or commas.

List what is installed (plus any `--pack` / `READYAGENTS_PACK` modules):

```bash
readyagents packs
```
