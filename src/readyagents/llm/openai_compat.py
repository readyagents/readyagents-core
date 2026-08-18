"""OpenAI-compatible endpoints (Groq, Ollama, Together, vLLM, …)."""

from __future__ import annotations

from readyagents.llm.openai_provider import OpenAIProvider


class OpenAICompatProvider(OpenAIProvider):
    name = "openai-compat"

    def __init__(self, api_key: str, *, base_url: str) -> None:
        super().__init__(api_key, base_url=base_url)
