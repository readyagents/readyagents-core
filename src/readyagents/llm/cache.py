"""Local, opt-in LLM response cache. File-backed, skippable, no network."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from readyagents.llm.base import CompletionResult, Message


class LLMCache:
    """Content-addressed completions under ``$READYAGENTS_HOME/cache/``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.hits = 0
        self.misses = 0

    def key(self, model: str, messages: list[Message]) -> str:
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def get(self, key: str) -> CompletionResult | None:
        path = self.root / f"{key}.json"
        if not path.is_file():
            self.misses += 1
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.misses += 1
            return None
        if not isinstance(data, dict) or "text" not in data:
            self.misses += 1
            return None
        self.hits += 1
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return CompletionResult(
            text=str(data.get("text") or ""),
            model=str(data.get("model") or ""),
            usage=dict(usage),
        )

    def put(self, key: str, result: CompletionResult) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{key}.json"
        tmp = self.root / f".{key}.{uuid4().hex}.tmp"
        payload: dict[str, Any] = {
            "text": result.text,
            "model": result.model,
            "usage": dict(result.usage or {}),
        }
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
