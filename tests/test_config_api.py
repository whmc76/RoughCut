from __future__ import annotations

from roughcut.api.config import get_config
from roughcut.config import get_settings


def test_get_config_exposes_extended_provider_fields(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    settings = get_settings()
    object.__setattr__(settings, "llm_mode", "performance")
    object.__setattr__(settings, "openai_base_url", "https://api.openai.com/v1")
    object.__setattr__(settings, "anthropic_base_url", "https://api.anthropic.com")
    object.__setattr__(settings, "minimax_base_url", "https://api.minimaxi.com/v1")
    object.__setattr__(settings, "local_reasoning_model", "qwen3.5:9b")
    object.__setattr__(settings, "multimodal_fallback_provider", "ollama")
    object.__setattr__(settings, "search_provider", "auto")
    object.__setattr__(settings, "search_fallback_provider", "searxng")

    cfg = get_config()

    assert cfg.llm_mode == "performance"
    assert cfg.openai_base_url == "https://api.openai.com/v1"
    assert cfg.anthropic_base_url == "https://api.anthropic.com"
    assert cfg.minimax_base_url == "https://api.minimaxi.com/v1"
    assert cfg.local_reasoning_model == "qwen3.5:9b"
    assert cfg.multimodal_fallback_provider == "ollama"
    assert cfg.search_provider == "auto"
    assert cfg.search_fallback_provider == "searxng"
    assert cfg.openai_auth_mode == "api_key"
    assert cfg.anthropic_auth_mode == "api_key"
