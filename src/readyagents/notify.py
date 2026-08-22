"""Outbound pause notify. Core never listens; packs may receive the webhook."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

from readyagents import __version__


def post_json(url: str, payload: dict[str, Any], *, timeout: float = 5.0) -> None:
    data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"readyagents/{__version__}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read(256)
