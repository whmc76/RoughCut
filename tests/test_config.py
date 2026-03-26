from __future__ import annotations

import roughcut.config as config_mod
from roughcut.config import Settings, get_settings


def test_default_settings():
    s = Settings(_env_file=None)
    assert s.transcription_provider == "openai"
    assert s.transcription_model == "gpt-4o-transcribe"
    assert s.transcription_dialect == "mandarin"
    assert s.llm_mode == "performance"
    assert s.reasoning_provider == "minimax"
    assert s.reasoning_model == "MiniMax-M2.7-highspeed"
    assert s.local_reasoning_model == "qwen3.5:9b"
    assert s.multimodal_fallback_provider == "ollama"
    assert s.search_provider == "auto"
    assert s.search_fallback_provider == "searxng"
    assert s.openai_auth_mode == "api_key"
    assert s.anthropic_auth_mode == "api_key"
    assert s.minimax_base_url == "https://api.minimaxi.com/v1"
    assert ".mp4" in s.allowed_extensions
    assert s.output_dir == "output"
    assert s.preferred_ui_language == "zh-CN"
    assert s.render_debug_dir == "output/test/render-debug"
    assert s.telegram_agent_enabled is False
    assert s.telegram_agent_claude_enabled is False
    assert s.telegram_agent_claude_command == "claude"
    assert s.telegram_agent_claude_model == "opus"
    assert s.telegram_agent_codex_command == "codex"
    assert s.telegram_agent_codex_model == "gpt-5.4-mini"
    assert s.acp_bridge_backend == "codex"
    assert s.acp_bridge_fallback_backend == "claude"
    assert s.acp_bridge_claude_model == "opus"
    assert s.acp_bridge_codex_command == "codex"
    assert s.acp_bridge_codex_model == "gpt-5.4-mini"
    assert s.telegram_agent_acp_command == ""
    assert s.telegram_agent_task_timeout_sec == 900
    assert s.telegram_agent_result_max_chars == 3500
    assert s.telegram_agent_state_dir == "data/telegram-agent"
    assert s.telegram_remote_review_enabled is False
    assert s.telegram_bot_api_base_url == "https://api.telegram.org"
    assert s.telegram_bot_token == ""
    assert s.telegram_bot_chat_id == ""
    assert s.default_job_workflow_mode == "standard_edit"
    assert s.default_job_enhancement_modes == []
    assert s.cover_output_variants == 5
    assert s.auto_confirm_content_profile is False
    assert s.content_profile_review_threshold == 0.9
    assert s.auto_accept_glossary_corrections is True
    assert s.glossary_correction_review_threshold == 0.9
    assert s.auto_select_cover_variant is True
    assert s.cover_selection_review_gap == 0.08
    assert s.packaging_selection_review_gap == 0.08
    assert s.packaging_selection_min_score == 0.6
    assert s.subtitle_filler_cleanup_enabled is True
    assert s.quality_auto_rerun_enabled is True
    assert s.quality_auto_rerun_below_score == 75.0
    assert s.quality_auto_rerun_max_attempts == 1
    assert s.avatar_overlay_scale == 0.18
    assert s.active_reasoning_provider == "minimax"

def test_local_mode_switches_active_provider():
    s = Settings(_env_file=None, llm_mode="local", local_reasoning_model="qwen3.5:9b")
    assert s.active_reasoning_provider == "ollama"
    assert s.active_reasoning_model == "qwen3.5:9b"
    assert s.active_search_provider == "auto"


def test_parse_extensions_from_string():
    s = Settings(_env_file=None, allowed_extensions=".mp4,.mov,.mkv")
    assert s.allowed_extensions == [".mp4", ".mov", ".mkv"]


def test_max_upload_size_bytes():
    s = Settings(_env_file=None, max_upload_size_mb=100)
    assert s.max_upload_size_bytes == 100 * 1024 * 1024


def test_get_settings_sanitizes_invalid_transcription_override(tmp_path, monkeypatch):
    overrides_file = tmp_path / "roughcut_config.json"
    overrides_file.write_text(
        '{"transcription_provider":"qwen_asr","transcription_model":"Qwen/Qwen3-ASR-1.7B","transcription_dialect":"martian"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", overrides_file)
    config_mod._settings = None

    settings = get_settings()

    assert settings.transcription_provider == "qwen_asr"
    assert settings.transcription_model == "qwen3-asr-1.7b"
    assert settings.transcription_dialect == "mandarin"
    assert settings.default_job_workflow_mode == "standard_edit"
    assert settings.default_job_enhancement_modes == []


def test_get_settings_accepts_qwen_asr_override(tmp_path, monkeypatch):
    overrides_file = tmp_path / "roughcut_config.json"
    overrides_file.write_text(
        '{"transcription_provider":"qwen_asr","transcription_model":"qwen3-asr-1.7b","transcription_dialect":"beijing"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", overrides_file)
    config_mod._settings = None

    settings = get_settings()

    assert settings.transcription_provider == "qwen_asr"
    assert settings.transcription_model == "qwen3-asr-1.7b"
    assert settings.transcription_dialect == "beijing"
    assert settings.qwen_asr_api_base_url == "http://127.0.0.1:18096"


def test_load_runtime_overrides_strips_secret_keys_from_legacy_file(tmp_path, monkeypatch):
    overrides_file = tmp_path / "roughcut_config.json"
    overrides_file.write_text(
        '{"reasoning_provider":"minimax","minimax_api_key":"secret-token","openai_base_url":"https://override.invalid/v1","output_dir":"custom-output"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", overrides_file)
    config_mod._settings = None
    config_mod._session_secret_overrides.clear()

    persisted = config_mod.load_runtime_overrides()

    assert persisted == {"reasoning_provider": "minimax"}
    assert config_mod.get_session_secret_override_keys() == ["minimax_api_key"]
    if overrides_file.exists():
        assert overrides_file.read_text(encoding="utf-8") == '{\n  "reasoning_provider": "minimax"\n}'
