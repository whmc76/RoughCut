from __future__ import annotations

import pytest
from fastapi import HTTPException

from roughcut.api.config import (
    ConfigPatch,
    get_config,
    get_config_options,
    get_model_catalog,
    get_runtime_environment,
    get_service_status,
    patch_config,
)
from roughcut.config import Settings, get_settings


def test_get_config_options_exposes_workflow_templates_instead_of_channel_profiles():
    options = get_config_options()

    assert options.workflow_templates[0]["value"] == ""
    assert options.workflow_templates[0]["label"] == "自动选择模板"
    assert any(item["value"] == "unboxing_standard" for item in options.workflow_templates)
    assert any(item["value"] == "tutorial_standard" for item in options.workflow_templates)
    assert any(item["label"] == "潮玩EDC开箱" for item in options.workflow_templates)
    assert all(item["value"] != "unboxing_limited" for item in options.workflow_templates)
    assert all(item["value"] != "unboxing_upgrade" for item in options.workflow_templates)
    assert all(item["value"] != "edc_tactical" for item in options.workflow_templates)


def test_get_config_exposes_extended_provider_fields(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    settings = get_settings()
    object.__setattr__(settings, "llm_mode", "performance")
    object.__setattr__(settings, "transcription_dialect", "beijing")
    object.__setattr__(settings, "transcription_alignment_mode", "auto")
    object.__setattr__(settings, "transcription_alignment_min_word_coverage", 0.81)
    object.__setattr__(settings, "llm_backup_enabled", True)
    object.__setattr__(settings, "backup_reasoning_provider", "minimax")
    object.__setattr__(settings, "backup_reasoning_model", "MiniMax-M2.7-highspeed")
    object.__setattr__(settings, "backup_reasoning_effort", "medium")
    object.__setattr__(settings, "backup_vision_model", "MiniMax-VL-01")
    object.__setattr__(settings, "backup_search_provider", "auto")
    object.__setattr__(settings, "backup_search_fallback_provider", "minimax")
    object.__setattr__(settings, "backup_model_search_helper", "")
    object.__setattr__(settings, "openai_base_url", "https://api.openai.com/v1")
    object.__setattr__(settings, "qwen_asr_api_base_url", "http://127.0.0.1:18096")
    object.__setattr__(settings, "avatar_provider", "heygem")
    object.__setattr__(settings, "avatar_api_base_url", "https://api.heygem.com")
    object.__setattr__(settings, "avatar_training_api_base_url", "http://127.0.0.1:18180")
    object.__setattr__(settings, "avatar_presenter_id", "presenter_demo")
    object.__setattr__(settings, "avatar_layout_template", "picture_in_picture_right")
    object.__setattr__(settings, "avatar_safe_margin", 0.08)
    object.__setattr__(settings, "avatar_overlay_scale", 0.24)
    object.__setattr__(settings, "anthropic_base_url", "https://api.anthropic.com")
    object.__setattr__(settings, "minimax_base_url", "https://api.minimaxi.com/v1")
    object.__setattr__(settings, "minimax_api_host", "https://api.minimaxi.com")
    object.__setattr__(settings, "voice_provider", "indextts2")
    object.__setattr__(settings, "voice_clone_api_base_url", "http://127.0.0.1:49204")
    object.__setattr__(settings, "voice_clone_voice_id", "voice_demo")
    object.__setattr__(settings, "director_rewrite_strength", 0.55)
    object.__setattr__(settings, "local_reasoning_model", "qwen3.5:9b")
    object.__setattr__(settings, "multimodal_fallback_provider", "ollama")
    object.__setattr__(settings, "search_provider", "auto")
    object.__setattr__(settings, "search_fallback_provider", "searxng")
    object.__setattr__(settings, "output_dir", "output")
    object.__setattr__(settings, "preferred_ui_language", "en-US")
    object.__setattr__(settings, "telegram_agent_enabled", True)
    object.__setattr__(settings, "telegram_agent_claude_enabled", True)
    object.__setattr__(settings, "telegram_agent_claude_command", "claude")
    object.__setattr__(settings, "telegram_agent_claude_model", "opus")
    object.__setattr__(settings, "telegram_agent_codex_command", "codex")
    object.__setattr__(settings, "telegram_agent_codex_model", "gpt-5.4-mini")
    object.__setattr__(settings, "telegram_agent_acp_command", "python scripts/acp_bridge.py")
    object.__setattr__(settings, "telegram_agent_task_timeout_sec", 600)
    object.__setattr__(settings, "transcribe_runtime_timeout_sec", 1500)
    object.__setattr__(settings, "telegram_agent_result_max_chars", 2800)
    object.__setattr__(settings, "telegram_agent_state_dir", "data/telegram-agent")
    object.__setattr__(settings, "acp_bridge_backend", "codex")
    object.__setattr__(settings, "acp_bridge_fallback_backend", "claude")
    object.__setattr__(settings, "acp_bridge_claude_model", "opus")
    object.__setattr__(settings, "acp_bridge_codex_command", "codex")
    object.__setattr__(settings, "acp_bridge_codex_model", "gpt-5.4-mini")
    object.__setattr__(settings, "telegram_remote_review_enabled", True)
    object.__setattr__(settings, "telegram_bot_api_base_url", "https://api.telegram.org")
    object.__setattr__(settings, "telegram_bot_token", "bot-token")
    object.__setattr__(settings, "telegram_bot_chat_id", "123456789")
    object.__setattr__(settings, "default_job_workflow_mode", "standard_edit")
    object.__setattr__(settings, "default_job_enhancement_modes", ["ai_director"])
    object.__setattr__(settings, "auto_confirm_content_profile", True)
    object.__setattr__(settings, "content_profile_review_threshold", 0.72)
    object.__setattr__(settings, "auto_accept_glossary_corrections", True)
    object.__setattr__(settings, "glossary_correction_review_threshold", 0.9)
    object.__setattr__(settings, "auto_select_cover_variant", True)
    object.__setattr__(settings, "cover_selection_review_gap", 0.08)
    object.__setattr__(settings, "packaging_selection_review_gap", 0.08)
    object.__setattr__(settings, "packaging_selection_min_score", 0.6)
    object.__setattr__(settings, "subtitle_filler_cleanup_enabled", True)
    object.__setattr__(settings, "quality_auto_rerun_enabled", True)
    object.__setattr__(settings, "quality_auto_rerun_below_score", 75.0)
    object.__setattr__(settings, "quality_auto_rerun_max_attempts", 1)

    cfg = get_config()

    assert cfg.llm_mode == "performance"
    assert cfg.transcription_dialect == "beijing"
    assert cfg.transcription_alignment_mode == "auto"
    assert cfg.transcription_alignment_min_word_coverage == 0.81
    assert cfg.llm_backup_enabled is True
    assert cfg.backup_reasoning_provider == "minimax"
    assert cfg.backup_reasoning_model == "MiniMax-M2.7-highspeed"
    assert cfg.backup_vision_model == "MiniMax-VL-01"
    assert cfg.backup_search_provider == "auto"
    assert cfg.backup_search_fallback_provider == "minimax"
    assert cfg.qwen_asr_api_base_url == "http://127.0.0.1:18096"
    assert cfg.avatar_provider == "heygem"
    assert cfg.avatar_presenter_id == "presenter_demo"
    assert cfg.avatar_layout_template == "picture_in_picture_right"
    assert cfg.avatar_safe_margin == 0.08
    assert cfg.avatar_overlay_scale == 0.24
    assert cfg.voice_provider == "indextts2"
    assert cfg.voice_clone_voice_id == "voice_demo"
    assert cfg.director_rewrite_strength == 0.55
    assert cfg.local_reasoning_model == "qwen3.5:9b"
    assert cfg.multimodal_fallback_provider == "ollama"
    assert cfg.search_provider == "auto"
    assert cfg.search_fallback_provider == "searxng"
    assert cfg.preferred_ui_language == "en-US"
    assert cfg.telegram_agent_enabled is True
    assert cfg.telegram_agent_claude_enabled is True
    assert cfg.telegram_agent_claude_command == "claude"
    assert cfg.telegram_agent_claude_model == "opus"
    assert cfg.telegram_agent_codex_command == "codex"
    assert cfg.telegram_agent_codex_model == "gpt-5.4-mini"
    assert cfg.telegram_agent_acp_command == "python scripts/acp_bridge.py"
    assert cfg.telegram_agent_task_timeout_sec == 600
    assert cfg.transcribe_runtime_timeout_sec == 1500
    assert cfg.telegram_agent_result_max_chars == 2800
    assert cfg.telegram_agent_state_dir == "data/telegram-agent"
    assert cfg.acp_bridge_backend == "codex"
    assert cfg.acp_bridge_fallback_backend == "claude"
    assert cfg.acp_bridge_claude_model == "opus"
    assert cfg.acp_bridge_codex_command == "codex"
    assert cfg.acp_bridge_codex_model == "gpt-5.4-mini"
    assert cfg.telegram_remote_review_enabled is True
    assert cfg.telegram_bot_api_base_url == "https://api.telegram.org"
    assert cfg.telegram_bot_token_set is True
    assert cfg.telegram_bot_chat_id == "123456789"
    assert cfg.default_job_workflow_mode == "standard_edit"
    assert cfg.default_job_enhancement_modes == ["ai_director"]
    assert cfg.auto_confirm_content_profile is True
    assert cfg.content_profile_review_threshold == 0.72
    assert cfg.auto_accept_glossary_corrections is True
    assert cfg.glossary_correction_review_threshold == 0.9
    assert cfg.auto_select_cover_variant is True
    assert cfg.cover_selection_review_gap == 0.08
    assert cfg.packaging_selection_review_gap == 0.08
    assert cfg.packaging_selection_min_score == 0.6
    assert cfg.subtitle_filler_cleanup_enabled is True
    assert cfg.quality_auto_rerun_enabled is True
    assert cfg.quality_auto_rerun_below_score == 75.0
    assert cfg.quality_auto_rerun_max_attempts == 1
    assert cfg.persistence["settings_store"] == "database"
    assert cfg.persistence["profiles_store"] == "database"
    assert cfg.persistence["packaging_store"] == "database"
    assert "transcription_provider" in cfg.profile_bindable_keys
    assert "transcription_alignment_mode" in cfg.profile_bindable_keys
    assert "quality_auto_rerun_enabled" in cfg.profile_bindable_keys
    assert "openai_base_url" not in cfg.profile_bindable_keys
    assert "voice_clone_api_base_url" not in cfg.profile_bindable_keys
    assert "output_dir" not in cfg.profile_bindable_keys
    assert cfg.override_keys == []
    assert cfg.session_secret_keys == []
    assert cfg.overrides == {}


def test_get_runtime_environment_exposes_env_managed_fields(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    settings = get_settings()
    object.__setattr__(settings, "openai_base_url", "https://api.openai.com/v1")
    object.__setattr__(settings, "openai_auth_mode", "api_key")
    object.__setattr__(settings, "openai_api_key_helper", "")
    object.__setattr__(settings, "anthropic_base_url", "https://api.anthropic.com")
    object.__setattr__(settings, "anthropic_auth_mode", "api_key")
    object.__setattr__(settings, "anthropic_api_key_helper", "")
    object.__setattr__(settings, "minimax_base_url", "https://api.minimaxi.com/v1")
    object.__setattr__(settings, "minimax_api_host", "https://api.minimaxi.com")
    object.__setattr__(settings, "ollama_base_url", "http://127.0.0.1:11434")
    object.__setattr__(settings, "avatar_api_base_url", "https://api.heygem.com")
    object.__setattr__(settings, "avatar_training_api_base_url", "http://127.0.0.1:18180")
    object.__setattr__(settings, "voice_clone_api_base_url", "http://127.0.0.1:49204")
    object.__setattr__(settings, "output_dir", "output")

    runtime_environment = get_runtime_environment()

    assert runtime_environment.openai_base_url == "https://api.openai.com/v1"
    assert runtime_environment.openai_auth_mode == "api_key"
    assert runtime_environment.anthropic_base_url == "https://api.anthropic.com"
    assert runtime_environment.minimax_base_url == "https://api.minimaxi.com/v1"
    assert runtime_environment.minimax_api_host == "https://api.minimaxi.com"
    assert runtime_environment.ollama_base_url == "http://127.0.0.1:11434"
    assert runtime_environment.avatar_api_base_url == "https://api.heygem.com"
    assert runtime_environment.avatar_training_api_base_url == "http://127.0.0.1:18180"
    assert runtime_environment.voice_clone_api_base_url == "http://127.0.0.1:49204"
    assert runtime_environment.output_dir == "output"


def test_get_config_redacts_secret_overrides(tmp_path, monkeypatch):
    import json

    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    overrides_file = tmp_path / "roughcut_config.json"
    overrides_file.write_text(
        json.dumps(
            {
                "reasoning_provider": "minimax",
                "minimax_api_key": "super-secret",
                "telegram_bot_token": "bot-secret",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_api, "_CONFIG_FILE", overrides_file)
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", overrides_file)
    config_mod._settings = None

    cfg = get_config()

    assert cfg.override_keys == ["reasoning_provider"]
    assert cfg.session_secret_keys == ["minimax_api_key", "telegram_bot_token"]
    assert cfg.overrides["reasoning_provider"] == "minimax"
    assert "minimax_api_key" not in cfg.overrides
    assert "telegram_bot_token" not in cfg.overrides


def test_get_config_options_exposes_transcription_model_lists():
    options = get_config_options()

    assert options.job_languages[0]["value"] == "zh-CN"
    assert options.workflow_templates[0]["value"] == ""
    assert options.workflow_modes[0]["value"] == "standard_edit"
    assert any(item["value"] == "multilingual_translation" for item in options.enhancement_modes)
    assert any(item["value"] == "auto_review" for item in options.enhancement_modes)
    assert any(item["value"] == "avatar_commentary" for item in options.enhancement_modes)
    assert any(item["value"] == "mandarin" for item in options.transcription_dialects)
    assert any(item["value"] == "beijing" for item in options.transcription_dialects)
    assert any(item["value"] == "heygem" for item in options.avatar_providers)
    assert any(item["value"] == "indextts2" for item in options.voice_providers)
    assert any(item["key"] == "long_text_to_video" and item["status"] == "planned" for item in options.creative_mode_catalog["workflow_modes"])
    assert any(item["key"] == "ai_director" and item["status"] == "active" for item in options.creative_mode_catalog["enhancement_modes"])
    assert any(item["key"] == "multilingual_translation" and item["status"] == "active" for item in options.creative_mode_catalog["enhancement_modes"])
    assert any(item["key"] == "auto_review" and item["status"] == "active" for item in options.creative_mode_catalog["enhancement_modes"])
    assert "faster_whisper" in options.transcription_models
    assert options.transcription_models["faster_whisper"][0] == "large-v3"
    assert "large-v3-turbo" in options.transcription_models["faster_whisper"]
    assert "openai" in options.transcription_models
    assert options.transcription_models["openai"] == ["gpt-4o-transcribe", "gpt-4o-mini-transcribe"]
    assert options.transcription_models["qwen3_asr"][0] == "qwen3-asr-1.7b"
    assert "qwen3-asr-0.6b" in options.transcription_models["qwen3_asr"]
    assert "large-v3" in options.transcription_models["faster_whisper"]
    assert any(item["value"] == "unboxing_standard" for item in options.workflow_templates)
    assert all(item["value"] != "edc_tactical" for item in options.workflow_templates)
    assert any(item["value"] == "ollama" for item in options.multimodal_fallback_providers)
    assert any(item["value"] == "auto" for item in options.search_providers)
    assert all(item["value"] != "auto" for item in options.search_fallback_providers)


def test_get_service_status_reports_local_runtime_endpoints(monkeypatch):
    import roughcut.config as config_mod

    config_mod._settings = None
    settings = get_settings()
    object.__setattr__(settings, "ollama_base_url", "http://127.0.0.1:11434")
    object.__setattr__(settings, "qwen_asr_api_base_url", "http://127.0.0.1:18096")
    object.__setattr__(settings, "openai_api_key", "openai-test-key")

    class DummyResponse:
        def __init__(self, status_code: int, payload: dict | None = None):
            self.status_code = status_code
            self._payload = payload or {}

        def json(self):
            return self._payload

    def fake_get(url: str, *args, **kwargs):
        if url.endswith("/api/tags"):
            return DummyResponse(200, {"models": [{"name": "qwen3:8b"}]})
        if url.endswith("/health"):
            return DummyResponse(200, {"status": "ok"})
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr("roughcut.api.provider_catalog.httpx.get", fake_get)

    status = get_service_status()

    assert status.services["ollama"].status == "ok"
    assert status.services["ollama"].base_url == "http://127.0.0.1:11434"
    assert status.services["qwen3_asr"].status == "ok"
    assert status.services["openai"].status == "configured"


def test_get_model_catalog_returns_live_ollama_models(monkeypatch):
    import roughcut.config as config_mod

    config_mod._settings = None
    settings = get_settings()
    object.__setattr__(settings, "ollama_base_url", "http://127.0.0.1:11434")

    class DummyResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"models": [{"name": "qwen3:8b"}, {"name": "qwen2.5vl:7b"}]}

    monkeypatch.setattr("roughcut.api.provider_catalog.httpx.get", lambda *args, **kwargs: DummyResponse())

    catalog = get_model_catalog(provider="ollama", kind="reasoning", refresh=1)

    assert catalog.provider == "ollama"
    assert catalog.kind == "reasoning"
    assert catalog.source == "live"
    assert catalog.models == ["qwen2.5vl:7b", "qwen3:8b"]


def test_get_model_catalog_keeps_cached_models_when_refresh_fails(monkeypatch):
    import roughcut.api.provider_catalog as catalog_mod
    import roughcut.config as config_mod

    config_mod._settings = None
    settings = get_settings()
    object.__setattr__(settings, "openai_base_url", "https://api.openai.com/v1")
    object.__setattr__(settings, "openai_api_key", "openai-test-key")
    catalog_mod._MODEL_CATALOG_CACHE.clear()

    class LiveResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"data": [{"id": "gpt-4.1"}, {"id": "gpt-4.1-mini"}]}

    def first_get(*args, **kwargs):
        return LiveResponse()

    monkeypatch.setattr("roughcut.api.provider_catalog.httpx.get", first_get)
    fresh = get_model_catalog(provider="openai", kind="reasoning", refresh=1)

    def failing_get(*args, **kwargs):
        raise RuntimeError("upstream unavailable")

    monkeypatch.setattr("roughcut.api.provider_catalog.httpx.get", failing_get)
    cached = get_model_catalog(provider="openai", kind="reasoning", refresh=1)

    assert fresh.models == ["gpt-4.1", "gpt-4.1-mini"]
    assert cached.models == ["gpt-4.1", "gpt-4.1-mini"]
    assert cached.source == "cache"
    assert cached.status == "error"
    assert "upstream unavailable" in (cached.error or "")


@pytest.mark.asyncio
async def test_provider_check_reports_live_openai_models(client, monkeypatch):
    import roughcut.config as config_mod

    config_mod._settings = None
    settings = get_settings()
    object.__setattr__(settings, "openai_base_url", "https://api.openai.com/v1")
    object.__setattr__(settings, "openai_auth_mode", "api_key")
    object.__setattr__(settings, "openai_api_key_helper", "")
    object.__setattr__(settings, "openai_api_key", "openai-test-key")

    requests: list[tuple[str, dict[str, str]]] = []

    class DummyResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"data": [{"id": "gpt-4.1"}, {"id": "gpt-4.1-mini"}]}

    def fake_get(url: str, *args, **kwargs):
        requests.append((url, dict(kwargs.get("headers") or {})))
        return DummyResponse()

    monkeypatch.setattr("roughcut.api.provider_catalog.httpx.get", fake_get)

    response = await client.get("/api/v1/config/provider-check?provider=openai")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "openai"
    assert payload["base_url"] == "https://api.openai.com/v1"
    assert payload["status"] == "ok"
    assert payload["detail"] == "ok"
    assert payload["models"] == ["gpt-4.1", "gpt-4.1-mini"]
    assert payload["checked_at"]
    assert requests == [
        (
            "https://api.openai.com/v1/models",
            {"Authorization": "Bearer openai-test-key"},
        )
    ]


@pytest.mark.asyncio
async def test_provider_check_reports_live_ollama_models(client, monkeypatch):
    import roughcut.config as config_mod

    config_mod._settings = None
    settings = get_settings()
    object.__setattr__(settings, "ollama_base_url", "http://127.0.0.1:11434")

    requests: list[str] = []

    class DummyResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"models": [{"name": "qwen3:8b"}, {"name": "qwen2.5vl:7b"}]}

    def fake_get(url: str, *args, **kwargs):
        requests.append(url)
        return DummyResponse()

    monkeypatch.setattr("roughcut.api.provider_catalog.httpx.get", fake_get)

    response = await client.get("/api/v1/config/provider-check?provider=ollama")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "ollama"
    assert payload["base_url"] == "http://127.0.0.1:11434"
    assert payload["status"] == "ok"
    assert payload["detail"] == "ok"
    assert payload["models"] == ["qwen2.5vl:7b", "qwen3:8b"]
    assert payload["checked_at"]
    assert requests == ["http://127.0.0.1:11434/api/tags"]


def test_patch_config_rejects_unknown_transcription_provider(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    with pytest.raises(HTTPException, match="Unsupported transcription_provider"):
        patch_config(ConfigPatch(transcription_provider="unknown_provider"))


def test_patch_config_normalizes_transcription_alignment_fields(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    cfg = patch_config(
        ConfigPatch(
            transcription_alignment_mode="SYNTHETIC",
            transcription_alignment_min_word_coverage=1.5,
        )
    )

    assert cfg.transcription_alignment_mode == "synthetic"
    assert cfg.transcription_alignment_min_word_coverage == 1.0


def test_patch_config_rejects_unknown_transcription_dialect(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    with pytest.raises(HTTPException, match="Unsupported transcription_dialect"):
        patch_config(ConfigPatch(transcription_dialect="unknown_dialect"))


def test_patch_config_normalizes_invalid_transcription_model_for_provider(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    cfg = patch_config(
        ConfigPatch(
            transcription_provider="openai",
            transcription_model="base",
        )
    )

    assert cfg.transcription_provider == "openai"
    assert cfg.transcription_model == "gpt-4o-transcribe"


def test_patch_config_accepts_qwen_asr_provider(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    cfg = patch_config(
        ConfigPatch(
            transcription_provider="qwen3_asr",
            transcription_model="qwen3-asr-1.7b",
            transcription_dialect="beijing",
            qwen_asr_api_base_url="http://127.0.0.1:18096",
        )
    )

    assert cfg.transcription_provider == "qwen3_asr"
    assert cfg.transcription_model == "qwen3-asr-1.7b"
    assert cfg.transcription_dialect == "beijing"


def test_patch_config_rejects_env_managed_connection_fields(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    with pytest.raises(HTTPException, match="startup env only"):
        patch_config(
            ConfigPatch(
                openai_base_url="https://override.invalid/v1",
                voice_clone_api_base_url="https://voice.example.com",
                output_dir=str(tmp_path / "exports"),
            )
        )


def test_patch_config_clamps_quality_auto_rerun_settings(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    cfg = patch_config(
        ConfigPatch(
            quality_auto_rerun_enabled=True,
            quality_auto_rerun_below_score=120.0,
            quality_auto_rerun_max_attempts=8,
        )
    )

    assert cfg.quality_auto_rerun_enabled is True
    assert cfg.quality_auto_rerun_below_score == 100.0
    assert cfg.quality_auto_rerun_max_attempts == 5
    assert isinstance(cfg.qwen_asr_api_base_url, str)
    assert cfg.qwen_asr_api_base_url


def test_patch_config_forces_search_provider_to_auto_bundle(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    cfg = patch_config(
        ConfigPatch(
            reasoning_provider="openai",
            search_provider="openai",
            search_fallback_provider="model",
            model_search_helper="  helper-model  ",
        )
    )

    persisted = config_mod.load_runtime_overrides()

    assert cfg.reasoning_provider == "openai"
    assert cfg.search_provider == "auto"
    assert cfg.search_fallback_provider == "model"
    assert cfg.model_search_helper == "helper-model"
    assert persisted["search_provider"] == "auto"
    assert persisted["search_fallback_provider"] == "model"


def test_patch_config_accepts_backup_llm_bundle_fields(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    cfg = patch_config(
        ConfigPatch(
            llm_backup_enabled=True,
            backup_reasoning_provider="minimax",
            backup_reasoning_model="MiniMax-M2.7-highspeed",
            backup_reasoning_effort="medium",
            backup_vision_model="MiniMax-VL-01",
            backup_search_provider="auto",
            backup_search_fallback_provider="minimax",
        )
    )

    persisted = config_mod.load_runtime_overrides()

    assert cfg.llm_backup_enabled is True
    assert cfg.backup_reasoning_provider == "minimax"
    assert cfg.backup_reasoning_model == "MiniMax-M2.7-highspeed"
    assert cfg.backup_vision_model == "MiniMax-VL-01"
    assert cfg.backup_search_provider == "auto"
    assert cfg.backup_search_fallback_provider == "minimax"
    assert persisted["backup_reasoning_provider"] == "minimax"
    assert persisted["backup_reasoning_model"] == "MiniMax-M2.7-highspeed"


def test_patch_config_accepts_creative_provider_fields(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    cfg = patch_config(
        ConfigPatch(
            avatar_provider="heygem",
            avatar_safe_margin=0.22,
            voice_provider="runninghub",
            director_rewrite_strength=0.88,
            default_job_workflow_mode="standard_edit",
            default_job_enhancement_modes=["avatar_commentary", "ai_director"],
        )
    )

    assert cfg.avatar_provider == "heygem"
    assert cfg.avatar_safe_margin == 0.22
    assert cfg.voice_provider == "runninghub"
    assert cfg.director_rewrite_strength == 0.88
    assert cfg.default_job_workflow_mode == "standard_edit"
    assert cfg.default_job_enhancement_modes == ["avatar_commentary", "ai_director"]


def test_patch_config_accepts_preferred_ui_language(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    cfg = patch_config(
        ConfigPatch(
            preferred_ui_language="en-US",
        )
    )

    assert cfg.preferred_ui_language == "en-US"


def test_patch_config_accepts_telegram_remote_review_fields(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    cfg = patch_config(
        ConfigPatch(
            telegram_agent_enabled=True,
            telegram_agent_claude_enabled=True,
            telegram_agent_claude_command="claude",
            telegram_agent_claude_model="opus",
            telegram_agent_codex_command="codex-nightly",
            telegram_agent_codex_model="gpt-5.4-mini",
            telegram_agent_acp_command="python scripts/acp_bridge.py",
            telegram_agent_task_timeout_sec=1200,
            transcribe_runtime_timeout_sec=1800,
            telegram_agent_result_max_chars=5000,
            telegram_agent_state_dir=str(tmp_path / "agent-state"),
            acp_bridge_backend="codex",
            acp_bridge_fallback_backend="claude",
            acp_bridge_claude_model="opus",
            acp_bridge_codex_command="codex-nightly",
            acp_bridge_codex_model="gpt-5.4-mini",
            telegram_remote_review_enabled=True,
            telegram_bot_api_base_url="https://api.telegram.org/",
            telegram_bot_token="bot-token",
            telegram_bot_chat_id="123456789",
        )
    )

    assert cfg.telegram_agent_enabled is True
    assert cfg.telegram_agent_claude_enabled is True
    assert cfg.telegram_agent_claude_command == "claude"
    assert cfg.telegram_agent_claude_model == "opus"
    assert cfg.telegram_agent_codex_command == "codex-nightly"
    assert cfg.telegram_agent_codex_model == "gpt-5.4-mini"
    assert cfg.telegram_agent_acp_command == "python scripts/acp_bridge.py"
    assert cfg.telegram_agent_task_timeout_sec == 1200
    assert cfg.transcribe_runtime_timeout_sec == 1800
    assert cfg.telegram_agent_result_max_chars == 5000
    assert cfg.telegram_agent_state_dir == str(tmp_path / "agent-state")
    assert cfg.acp_bridge_backend == "codex"
    assert cfg.acp_bridge_fallback_backend == "claude"
    assert cfg.acp_bridge_claude_model == "opus"
    assert cfg.acp_bridge_codex_command == "codex-nightly"
    assert cfg.acp_bridge_codex_model == "gpt-5.4-mini"
    assert cfg.telegram_remote_review_enabled is True
    assert cfg.telegram_bot_api_base_url == "https://api.telegram.org"
    assert cfg.telegram_bot_token_set is True
    assert cfg.telegram_bot_chat_id == "123456789"
    assert "telegram_bot_token" not in cfg.override_keys
    assert "telegram_bot_token" in cfg.session_secret_keys


def test_patch_config_rejects_unknown_acp_bridge_backend(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    with pytest.raises(HTTPException, match="acp_bridge_backend must be auto, claude or codex"):
        patch_config(ConfigPatch(acp_bridge_backend="unsupported"))


def test_patch_config_accepts_blank_acp_backend_and_model_overrides(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    cfg = patch_config(
        ConfigPatch(
            telegram_agent_codex_model="",
            telegram_agent_claude_model="",
            acp_bridge_backend="",
            acp_bridge_fallback_backend="",
            acp_bridge_claude_model="",
            acp_bridge_codex_model="",
        )
    )

    assert cfg.telegram_agent_codex_model == ""
    assert cfg.telegram_agent_claude_model == ""
    assert cfg.acp_bridge_backend == ""
    assert cfg.acp_bridge_fallback_backend == ""
    assert cfg.acp_bridge_claude_model == ""
    assert cfg.acp_bridge_codex_model == ""


def test_patch_config_clamps_transcribe_runtime_timeout(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = Settings(_env_file=None)

    cfg = patch_config(ConfigPatch(transcribe_runtime_timeout_sec=30))

    assert cfg.transcribe_runtime_timeout_sec == 60


def test_patch_config_accepts_subtitle_filler_cleanup_toggle(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    cfg = patch_config(
        ConfigPatch(
            subtitle_filler_cleanup_enabled=False,
        )
    )

    assert cfg.subtitle_filler_cleanup_enabled is False


def test_patch_config_accepts_indextts2_voice_provider(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    config_mod._settings = None

    cfg = patch_config(
        ConfigPatch(
            voice_provider="indextts2",
        )
    )

    assert cfg.voice_provider == "indextts2"
    assert get_runtime_environment().voice_clone_api_base_url == "http://127.0.0.1:49204"


def test_patch_config_persists_to_database_without_override_file(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    override_file = tmp_path / "roughcut_config.json"
    monkeypatch.setattr(config_api, "_CONFIG_FILE", override_file)
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", override_file)
    config_mod._settings = None

    patch_config(
        ConfigPatch(
            transcription_provider="qwen_asr",
            transcription_model="qwen3-asr-1.7b",
            transcription_dialect="beijing",
            quality_auto_rerun_enabled=False,
            quality_auto_rerun_below_score=66.0,
        )
    )

    assert override_file.exists() is False

    config_mod._settings = None
    settings = get_settings()

    assert settings.transcription_provider == "qwen3_asr"
    assert settings.transcription_model == "qwen3-asr-1.7b"
    assert settings.transcription_dialect == "beijing"
    assert settings.quality_auto_rerun_enabled is False
    assert settings.quality_auto_rerun_below_score == 66.0


def test_patch_config_keeps_secret_keys_out_of_persisted_overrides(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod

    override_file = tmp_path / "roughcut_config.json"
    monkeypatch.setattr(config_api, "_CONFIG_FILE", override_file)
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", override_file)
    config_mod._settings = None
    config_mod._session_secret_overrides.clear()

    cfg = patch_config(
        ConfigPatch(
            minimax_api_key="secret-token",
            reasoning_provider="minimax",
        )
    )

    persisted = config_mod.load_runtime_overrides()

    assert cfg.minimax_api_key_set is True
    assert "minimax_api_key" in cfg.session_secret_keys
    assert "minimax_api_key" not in cfg.override_keys
    assert persisted["reasoning_provider"] == "minimax"
    assert persisted["transcription_provider"] == "openai"
    assert persisted["transcription_model"] == "gpt-4o-transcribe"
    assert "minimax_api_key" not in persisted
