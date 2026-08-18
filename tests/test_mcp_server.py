from __future__ import annotations

import pytest

from readyagents.mcp.server import _create_server, mcp_available

pytestmark = pytest.mark.skipif(not mcp_available(), reason="mcp extra not installed")


def test_mcp_server_constructs() -> None:
    server = _create_server("readyagents-test")
    assert server is not None
    assert hasattr(server, "tool")
    assert hasattr(server, "run")
