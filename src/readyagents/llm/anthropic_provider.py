"""Anthropic Messages provider."""

from __future__ import annotations

from typing import Any

from readyagents.errors import LLMError
from readyagents.llm.base import CompletionResult, Message


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> CompletionResult:
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise LLMError(
                "The Anthropic extra is not installed. Run: pip install 'readyagents[anthropic]'"
            ) from exc
        system = ""
        chat: list[dict[str, str]] = []
        for message in messages:
            if message.role == "system":
                system = f"{system}\n{message.content}".strip() if system else message.content
            else:
                role = "assistant" if message.role == "assistant" else "user"
                chat.append({"role": role, "content": message.content})
        if not chat:
            raise LLMError("Anthropic requires at least one non-system message")
        try:
            client = Anthropic(api_key=self._api_key)
            payload: dict[str, Any] = {"model": model, "messages": chat, "max_tokens": 4096}
            if system:
                payload["system"] = system
            if tools:
                payload["tools"] = tools
            payload.update({k: v for k, v in kwargs.items() if v is not None and k != "max_tokens"})
            if kwargs.get("max_tokens") is not None:
                payload["max_tokens"] = kwargs["max_tokens"]
            response = client.messages.create(**payload)
            parts = []
            for block in response.content:
                text = getattr(block, "text", None)
                if text:
                    parts.append(text)
            usage: dict[str, Any] = {}
            if getattr(response, "usage", None):
                usage = {
                    "input_tokens": getattr(response.usage, "input_tokens", None),
                    "output_tokens": getattr(response.usage, "output_tokens", None),
                }
            return CompletionResult(
                text="".join(parts).strip(),
                model=model,
                raw=response,
                usage=usage,
            )
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Anthropic request failed: {exc}") from exc
