from __future__ import annotations

from pathlib import Path

import pytest

from readyagents.config import Settings, clear_settings_cache, load_settings, require_api_key
from readyagents.errors import LLMError
from readyagents.llm.registry import get_provider


def test_env_then_dotenv_then_env_ai(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_cache()
    monkeypatch.chdir(tmp_path)
    env_ai = tmp_path / ".env-ai"
    env_ai.write_text(
        "OPENAI_API_KEY=from-ai\nREADYAGENTS_DEFAULT_MODEL=from-ai\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("OPENAI_API_KEY=from-env-file\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("READYAGENTS_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("READYAGENTS_DEFAULT_MODEL", raising=False)
    settings = load_settings()
    assert settings.openai_api_key == "from-env-file"
    assert settings.default_model == "from-ai"

    monkeypatch.setenv("OPENAI_API_KEY", "from-process")
    settings = load_settings()
    assert settings.openai_api_key == "from-process"
    clear_settings_cache()


def test_empty_key_is_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_cache()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "   ")
    monkeypatch.delenv("READYAGENTS_OPENAI_API_KEY", raising=False)
    settings = load_settings(env_file=())
    assert settings.openai_api_key is None
    clear_settings_cache()


def test_require_api_key_message() -> None:
    settings = Settings(openai_api_key=None, anthropic_api_key=None, _env_file=())  # type: ignore[call-arg]
    with pytest.raises(LLMError) as exc:
        require_api_key("openai", settings)
    msg = str(exc.value)
    assert "OPENAI_API_KEY" in msg
    assert "BYOK" in msg


def test_get_provider_missing_key_tells_user_to_set_key() -> None:
    settings = Settings(  # type: ignore[call-arg]
        openai_api_key=None,
        anthropic_api_key=None,
        openai_compat_api_key=None,
        _env_file=(),
    )
    with pytest.raises(LLMError) as exc:
        get_provider("openai:gpt-4o-mini", settings=settings)
    msg = str(exc.value)
    assert "BYOK" in msg
    assert "OPENAI_API_KEY" in msg
    assert "Set" in msg or "set" in msg


def test_readyagents_prefixed_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_cache()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("READYAGENTS_OPENAI_API_KEY", "prefixed")
    settings = load_settings(env_file=())
    assert settings.openai_api_key == "prefixed"
    clear_settings_cache()
