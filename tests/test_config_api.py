from __future__ import annotations

from roughcut.api.config import get_config, get_config_options
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
    object.__setattr__(settings, "output_dir", "data/output")
    object.__setattr__(settings, "auto_confirm_content_profile", True)
    object.__setattr__(settings, "content_profile_review_threshold", 0.72)
    object.__setattr__(settings, "auto_accept_glossary_corrections", True)
    object.__setattr__(settings, "glossary_correction_review_threshold", 0.9)
    object.__setattr__(settings, "auto_select_cover_variant", True)
    object.__setattr__(settings, "cover_selection_review_gap", 0.08)
    object.__setattr__(settings, "packaging_selection_review_gap", 0.08)
    object.__setattr__(settings, "packaging_selection_min_score", 0.6)

    cfg = get_config()

    assert cfg.llm_mode == "performance"
    assert cfg.openai_base_url == "https://api.openai.com/v1"
    assert cfg.anthropic_base_url == "https://api.anthropic.com"
    assert cfg.minimax_base_url == "https://api.minimaxi.com/v1"
    assert cfg.local_reasoning_model == "qwen3.5:9b"
    assert cfg.multimodal_fallback_provider == "ollama"
    assert cfg.search_provider == "auto"
    assert cfg.search_fallback_provider == "searxng"
    assert cfg.output_dir == "data/output"
    assert cfg.auto_confirm_content_profile is True
    assert cfg.content_profile_review_threshold == 0.72
    assert cfg.auto_accept_glossary_corrections is True
    assert cfg.glossary_correction_review_threshold == 0.9
    assert cfg.auto_select_cover_variant is True
    assert cfg.cover_selection_review_gap == 0.08
    assert cfg.packaging_selection_review_gap == 0.08
    assert cfg.packaging_selection_min_score == 0.6
    assert cfg.openai_auth_mode == "api_key"
    assert cfg.anthropic_auth_mode == "api_key"


def test_get_config_options_exposes_transcription_model_lists():
    options = get_config_options()

    assert options.job_languages[0]["value"] == "zh-CN"
    assert options.channel_profiles[0]["value"] == ""
    assert "local_whisper" in options.transcription_models
    assert options.transcription_models["local_whisper"][0] == "base"
    assert "openai" in options.transcription_models
    assert options.transcription_models["openai"] == ["gpt-4o-transcribe"]
    assert "base" in options.transcription_models["local_whisper"]
    assert any(item["value"] == "edc_tactical" for item in options.channel_profiles)
    assert any(item["value"] == "ollama" for item in options.multimodal_fallback_providers)
    assert any(item["value"] == "auto" for item in options.search_providers)
    assert all(item["value"] != "auto" for item in options.search_fallback_providers)
