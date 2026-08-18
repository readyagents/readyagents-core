"""Resolve an LLM provider from settings / model ref."""

from __future__ import annotations

from readyagents.config import Settings, get_settings, require_api_key
from readyagents.errors import LLMError
from readyagents.llm.anthropic_provider import AnthropicProvider
from readyagents.llm.base import LLMProvider, parse_model_ref
from readyagents.llm.openai_compat import OpenAICompatProvider
from readyagents.llm.openai_provider import OpenAIProvider


def get_provider(
    model_ref: str | None = None,
    *,
    settings: Settings | None = None,
) -> tuple[LLMProvider, str]:
    """Return `(provider, model_id)` for a `provider:model` string."""
    settings = settings or get_settings()
    ref = model_ref or settings.default_model
    provider_name, model_id = parse_model_ref(ref)

    if provider_name == "openai":
        key = require_api_key("openai", settings)
        return OpenAIProvider(key), model_id

    if provider_name == "anthropic":
        key = require_api_key("anthropic", settings)
        return AnthropicProvider(key), model_id

    if provider_name in {"openai-compat", "openai_compat", "compat", "groq", "ollama"}:
        key = require_api_key("openai-compat", settings)
        base = settings.openai_compat_base_url
        if not base:
            if provider_name == "groq":
                base = "https://api.groq.com/openai/v1"
            elif provider_name == "ollama":
                base = "http://127.0.0.1:11434/v1"
            else:
                raise LLMError(
                    "OpenAI-compatible provider requires OPENAI_COMPAT_BASE_URL "
                    "(for example https://api.groq.com/openai/v1 or http://127.0.0.1:11434/v1)."
                )
        api_key = key or "not-needed"
        return OpenAICompatProvider(api_key, base_url=base), model_id

    raise LLMError(
        f"Unknown LLM provider '{provider_name}'. "
        "Use openai, anthropic, or openai-compat (Groq/Ollama)."
    )
