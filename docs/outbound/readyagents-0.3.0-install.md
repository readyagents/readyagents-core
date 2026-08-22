# ReadyAgents Core 0.3.0 — install

ReadyAgents Core **0.3.0** is a local YAML agent-workflow engine (BYOK). The sdist and wheel are built; packaging is PyPI-ready.

```bash
pip install readyagents==0.3.0
# until the public index lists it, install the wheel from this repo:
# pip install dist/readyagents-0.3.0-py3-none-any.whl
readyagents version   # 0.3.0
readyagents run examples/calc_pipeline.yaml
```

No API keys for the keyless examples. Copy `.env.example` to `.env` only when you add an agent node.

Core stays Apache-2.0 and local. Paid inbound approval (ReadyAgents Gate) is a pack, not this engine.
