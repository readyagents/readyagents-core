"""Resolve an LLM provider from settings / model ref."""

from __future__ import annotations

from readyagents.config import Settings, get_settings, require_api_key
from readyagents.errors import LLMError
from readyagents.llm.anthropic_provider import AnthropicProvider
from readyagents.llm.base import LLMProvider, parse_model_ref
from readyagents.llm.openai_compat import OpenAICompatProvider
from readyagents.llm.openai_provider import OpenAIProvider
from readyagents.logging import get_logger

log = get_logger("llm")

_COMPAT_NAMES = {"openai-compat", "openai_compat", "compat", "groq", "ollama"}

# Documented defaults from .env.example / docs/configuration.md
_FALLBACK_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-5",
    "openai-compat": "llama-3.1-8b-instant",
    "groq": "llama-3.1-8b-instant",
    "ollama": "llama3",
}


def _has_key(settings: Settings, provider_name: str) -> bool:
    if provider_name == "openai":
        return bool(settings.api_key_for("openai"))
    if provider_name == "anthropic":
        return bool(settings.api_key_for("anthropic"))
    if provider_name in _COMPAT_NAMES:
        return bool(settings.api_key_for("openai-compat"))
    return False


def _implicit_fallback_ref(settings: Settings) -> str | None:
    """First provider that actually has a key. None if BYOK is empty."""
    if settings.api_key_for("openai"):
        return f"openai:{_FALLBACK_MODELS['openai']}"
    if settings.api_key_for("anthropic"):
        return f"anthropic:{_FALLBACK_MODELS['anthropic']}"
    if settings.api_key_for("openai-compat"):
        if settings.openai_compat_base_url:
            return f"openai-compat:{_FALLBACK_MODELS['openai-compat']}"
        return f"groq:{_FALLBACK_MODELS['groq']}"
    return None


def get_provider(
    model_ref: str | None = None,
    *,
    settings: Settings | None = None,
    implicit: bool = False,
) -> tuple[LLMProvider, str]:
    """Return `(provider, model_id)` for a `provider:model` string.

    When ``implicit`` is true (agent node has no ``model:``), a missing key
    for the default provider falls back to whichever BYOK key is set.
    An explicit model ref never falls back.
    """
    settings = settings or get_settings()
    ref = model_ref or settings.default_model
    provider_name, model_id = parse_model_ref(ref)

    if implicit and not _has_key(settings, provider_name):
        fallback = _implicit_fallback_ref(settings)
        if fallback:
            new_provider, new_model = parse_model_ref(fallback)
            log.info(
                "No API key for default provider '%s'; using %s:%s",
                provider_name,
                new_provider,
                new_model,
            )
            provider_name, model_id = new_provider, new_model

    if provider_name == "openai":
        key = require_api_key("openai", settings)
        return OpenAIProvider(key), model_id

    if provider_name == "anthropic":
        key = require_api_key("anthropic", settings)
        return AnthropicProvider(key), model_id

    if provider_name in _COMPAT_NAMES:
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
