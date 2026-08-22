"""Offline / recorded LLM: replay a cassette file, no network."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from readyagents.errors import LLMError
from readyagents.llm.base import CompletionResult, Message


class RecordedLLM:
    """Replay stored completions. Optional ``inner`` records new calls to disk."""

    name = "recorded"

    def __init__(self, cassette: Path | str, *, inner: Any | None = None) -> None:
        self.cassette = Path(cassette)
        self.inner = inner
        self.calls: list[list[Message]] = []
        self.models: list[str] = []
        self._tape: list[dict[str, Any]] = []
        if self.cassette.is_file():
            loaded = json.loads(self.cassette.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                self._tape = [row for row in loaded if isinstance(row, dict)]
        self._index = 0

    def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: Any = None,
        **kwargs: Any,
    ) -> CompletionResult:
        self.calls.append(messages)
        self.models.append(model)
        if self._index < len(self._tape):
            row = self._tape[self._index]
            self._index += 1
            usage = row.get("usage") if isinstance(row.get("usage"), dict) else {}
            return CompletionResult(
                text=str(row.get("text") or ""),
                model=str(row.get("model") or model),
                usage=dict(usage),
            )
        if self.inner is None:
            raise LLMError(
                f"No recorded completion at index {self._index} in {self.cassette} "
                "(offline replay — no network)"
            )
        result = self.inner.complete(messages, model=model, tools=tools, **kwargs)
        self._tape.append(
            {"text": result.text, "model": result.model or model, "usage": dict(result.usage or {})}
        )
        self._index += 1
        self.cassette.parent.mkdir(parents=True, exist_ok=True)
        self.cassette.write_text(json.dumps(self._tape, indent=2, ensure_ascii=False) + "\n")
        return result
