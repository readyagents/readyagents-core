"""OpenAI Chat Completions provider."""

from __future__ import annotations

from typing import Any

from readyagents.errors import LLMError
from readyagents.llm.base import CompletionResult, Message


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, *, base_url: str | None = None) -> None:
        self._api_key = api_key
        self._base_url = base_url

    def complete(
        self,
        messages: list[Message],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> CompletionResult:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMError(
                "The OpenAI extra is not installed. Run: pip install 'readyagents[openai]'"
            ) from exc
        try:
            client_kwargs: dict[str, Any] = {"api_key": self._api_key}
            if self._base_url:
                client_kwargs["base_url"] = self._base_url
            client = OpenAI(**client_kwargs)
            payload: dict[str, Any] = {
                "model": model,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
            }
            if tools:
                payload["tools"] = tools
            payload.update({k: v for k, v in kwargs.items() if v is not None})
            response = client.chat.completions.create(**payload)
            choice = response.choices[0]
            text = (choice.message.content or "").strip()
            usage: dict[str, Any] = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }
            return CompletionResult(text=text, model=model, raw=response, usage=usage)
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"OpenAI request failed: {exc}") from exc
