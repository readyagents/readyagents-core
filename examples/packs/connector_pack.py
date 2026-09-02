"""Example pack: a local connector tool (no network, no vendor SDK).

Load locally with ``readyagents run ... --pack examples/packs/connector_pack.py``.
A published pack uses the ``readyagents.packs`` entry point. Core ships zero packs.
"""

from __future__ import annotations

from typing import Any

from readyagents.packs import BasePack
from readyagents.tools import FunctionTool


class ConnectorPack(BasePack):
    name = "example-connector"
    version = "0.3.0"

    def register_tools(self):
        def ping(message: str = "pong") -> dict[str, Any]:
            return {"ok": True, "message": message, "connector": self.name}

        return [
            FunctionTool(
                name="connector_ping",
                description="Example pack connector — echoes a payload (local, no network).",
                handler=ping,
                schema={
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                },
            )
        ]


def get_pack() -> ConnectorPack:
    return ConnectorPack()
