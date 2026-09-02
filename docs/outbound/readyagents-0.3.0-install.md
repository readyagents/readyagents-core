# ReadyAgents Core 0.3.0 — install

ReadyAgents Core **0.3.0** is a local YAML agent-workflow engine (BYOK). This package is not on PyPI. Install from a clone.

```bash
git clone https://github.com/readyagents/readyagents-core.git
cd readyagents-core
pip install -e .
readyagents version
readyagents run examples/calc_pipeline.yaml
```

No API keys for the keyless examples. Copy `.env.example` to `.env` only when you add an agent node.

Core stays Apache-2.0 and local. Paid inbound approval (ReadyAgents Gate) is a pack, not this engine.
