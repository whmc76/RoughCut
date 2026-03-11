from __future__ import annotations

import roughcut.config as config_mod
from roughcut.providers.factory import get_search_provider


def test_get_search_provider_auto_falls_back_to_searxng_for_local_without_ollama_key():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "llm_mode", "local")
    object.__setattr__(settings, "search_provider", "auto")
    object.__setattr__(settings, "search_fallback_provider", "searxng")
    object.__setattr__(settings, "model_search_helper", "")
    object.__setattr__(settings, "ollama_api_key", "")

    provider = get_search_provider()
    assert provider.__class__.__name__ == "SearXNGProvider"


def test_get_search_provider_model_uses_helper():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "search_provider", "model")
    object.__setattr__(settings, "model_search_helper", "python -c \"print('[]')\"")

    provider = get_search_provider()
    assert provider.__class__.__name__ == "ModelSearchProvider"


def test_get_search_provider_auto_prefers_minimax_when_reasoning_uses_minimax():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "llm_mode", "performance")
    object.__setattr__(settings, "reasoning_provider", "minimax")
    object.__setattr__(settings, "search_provider", "auto")
    object.__setattr__(settings, "minimax_api_key", "test-key")
    object.__setattr__(settings, "minimax_base_url", "https://api.minimaxi.com/v1")

    provider = get_search_provider()
    assert provider.__class__.__name__ == "MiniMaxSearchProvider"


def test_get_search_provider_auto_prefers_openai_when_reasoning_uses_openai():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "llm_mode", "performance")
    object.__setattr__(settings, "reasoning_provider", "openai")
    object.__setattr__(settings, "search_provider", "auto")
    object.__setattr__(settings, "openai_api_key", "test-key")

    provider = get_search_provider()
    assert provider.__class__.__name__ == "OpenAISearchProvider"


def test_get_search_provider_auto_prefers_anthropic_when_reasoning_uses_anthropic():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "llm_mode", "performance")
    object.__setattr__(settings, "reasoning_provider", "anthropic")
    object.__setattr__(settings, "search_provider", "auto")
    object.__setattr__(settings, "anthropic_api_key", "test-key")

    provider = get_search_provider()
    assert provider.__class__.__name__ == "AnthropicSearchProvider"


def test_get_search_provider_auto_prefers_ollama_when_local_has_api_key():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "llm_mode", "local")
    object.__setattr__(settings, "search_provider", "auto")
    object.__setattr__(settings, "ollama_api_key", "test-key")

    provider = get_search_provider()
    assert provider.__class__.__name__ == "OllamaSearchProvider"


def test_get_search_provider_minimax_explicit():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "search_provider", "minimax")
    object.__setattr__(settings, "minimax_api_key", "test-key")
    object.__setattr__(settings, "minimax_base_url", "https://api.minimaxi.com/v1")

    provider = get_search_provider()
    assert provider.__class__.__name__ == "MiniMaxSearchProvider"


def test_get_search_provider_ollama_explicit():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "search_provider", "ollama")
    object.__setattr__(settings, "ollama_api_key", "test-key")

    provider = get_search_provider()
    assert provider.__class__.__name__ == "OllamaSearchProvider"
