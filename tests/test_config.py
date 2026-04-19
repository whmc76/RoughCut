from __future__ import annotations

import json

import pytest

import roughcut.config as config_mod
from roughcut.config import (
    DEFAULT_OUTPUT_ROOT,
    Settings,
    get_settings,
    infer_coding_backends,
    llm_backup_route,
    normalize_transcription_settings,
    resolve_backup_llm_route,
    resolve_coding_backend_model,
)
import roughcut.providers.factory as factory_mod
from roughcut.providers.reasoning.base import Message, ReasoningResponse


def test_default_settings():
    s = Settings(_env_file=None)
    assert s.transcription_provider == "openai"
    assert s.transcription_model == "gpt-4o-transcribe"
    assert s.transcription_dialect == "mandarin"
    assert s.transcription_alignment_mode == "auto"
    assert s.transcription_alignment_min_word_coverage == 0.72
    assert s.llm_mode == "performance"
    assert s.reasoning_provider == "minimax"
    assert s.reasoning_model == "MiniMax-M2.7-highspeed"
    assert s.llm_backup_enabled is True
    assert s.backup_reasoning_provider == "minimax"
    assert s.backup_reasoning_model == "MiniMax-M2.7-highspeed"
    assert s.backup_vision_model == "MiniMax-VL-01"
    assert s.backup_search_provider == "auto"
    assert s.backup_search_fallback_provider == "minimax"
    assert s.local_reasoning_model == "qwen3.5:9b"
    assert s.multimodal_fallback_provider == "ollama"
    assert s.search_provider == "auto"
    assert s.search_fallback_provider == "searxng"
    assert s.openai_auth_mode == "api_key"
    assert s.anthropic_auth_mode == "api_key"
    assert s.minimax_base_url == "https://api.minimaxi.com/v1"
    assert ".mp4" in s.allowed_extensions
    assert s.job_storage_dir == str((DEFAULT_OUTPUT_ROOT / "jobs").as_posix())
    assert s.output_dir == str((DEFAULT_OUTPUT_ROOT / "output").as_posix())
    assert s.preferred_ui_language == "zh-CN"
    assert s.render_debug_dir == str((DEFAULT_OUTPUT_ROOT / "render-debug").as_posix())
    assert s.telegram_agent_enabled is False
    assert s.telegram_agent_claude_enabled is False
    assert s.telegram_agent_claude_command == "claude"
    assert s.telegram_agent_claude_model == ""
    assert s.telegram_agent_codex_command == "codex"
    assert s.telegram_agent_codex_model == ""
    assert s.acp_bridge_backend == ""
    assert s.acp_bridge_fallback_backend == ""
    assert s.acp_bridge_claude_model == ""
    assert s.acp_bridge_codex_command == "codex"
    assert s.acp_bridge_codex_model == ""
    assert s.telegram_agent_acp_command == ""
    assert s.telegram_agent_task_timeout_sec == 900
    assert s.transcribe_runtime_timeout_sec == 900
    assert s.telegram_agent_result_max_chars == 3500
    assert s.telegram_agent_state_dir == str((DEFAULT_OUTPUT_ROOT / "telegram-agent").as_posix())
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


def test_llm_backup_route_switches_reasoning_search_and_vision():
    s = Settings(
        _env_file=None,
        reasoning_provider="openai",
        reasoning_model="gpt-5.4",
        llm_backup_enabled=True,
        backup_reasoning_provider="minimax",
        backup_reasoning_model="MiniMax-M2.7-highspeed",
        backup_vision_model="MiniMax-VL-01",
        backup_search_provider="auto",
        backup_search_fallback_provider="minimax",
    )

    route = resolve_backup_llm_route(settings=s)
    assert route["reasoning_provider"] == "minimax"
    assert route["reasoning_model"] == "MiniMax-M2.7-highspeed"
    assert route["vision_model"] == "MiniMax-VL-01"
    assert route["search_provider"] == "auto"
    assert route["search_fallback_provider"] == "minimax"

    with llm_backup_route(settings=s):
        assert s.active_reasoning_provider == "minimax"
        assert s.active_reasoning_model == "MiniMax-M2.7-highspeed"
        assert s.active_vision_model == "MiniMax-VL-01"
        assert s.active_search_provider == "auto"
        assert s.active_search_fallback_provider == "minimax"


def test_infer_coding_backends_prefers_hybrid_routes():
    s = Settings(
        _env_file=None,
        llm_routing_mode="hybrid_performance",
        hybrid_analysis_provider="openai",
        hybrid_analysis_model="gpt-5.4",
        hybrid_copy_provider="anthropic",
        hybrid_copy_model="claude-sonnet-4-20250514",
        telegram_agent_claude_enabled=True,
    )

    assert infer_coding_backends(s) == ["codex", "claude"]
    assert resolve_coding_backend_model("codex", settings=s) == "gpt-5.4"
    assert resolve_coding_backend_model("claude", settings=s) == "claude-sonnet-4-20250514"


def test_resolve_coding_backend_model_uses_explicit_value_before_auto():
    s = Settings(
        _env_file=None,
        llm_routing_mode="hybrid_performance",
        hybrid_analysis_provider="openai",
        hybrid_analysis_model="gpt-5.4",
    )

    assert resolve_coding_backend_model("codex", settings=s, explicit_model="gpt-5.4-mini") == "gpt-5.4-mini"


def test_get_settings_normalizes_legacy_search_provider_override_to_auto(tmp_path, monkeypatch):
    overrides_file = tmp_path / "roughcut_config.json"
    overrides_file.write_text(
        '{"reasoning_provider":"openai","search_provider":"openai","search_fallback_provider":"model","model_search_helper":"  helper  "}',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", overrides_file)
    config_mod._settings = None

    settings = get_settings()
    persisted = config_mod.load_runtime_overrides()

    assert settings.search_provider == "auto"
    assert settings.search_fallback_provider == "model"
    assert settings.model_search_helper == "helper"
    assert persisted["search_provider"] == "auto"
    assert persisted["search_fallback_provider"] == "model"


def test_parse_extensions_from_string():
    s = Settings(_env_file=None, allowed_extensions=".mp4,.mov,.mkv")
    assert s.allowed_extensions == [".mp4", ".mov", ".mkv"]


def test_max_upload_size_bytes():
    s = Settings(_env_file=None, max_upload_size_mb=100)
    assert s.max_upload_size_bytes == 100 * 1024 * 1024


def test_max_upload_size_bytes_zero_disables_limit():
    s = Settings(_env_file=None, max_upload_size_mb=0)
    assert s.max_upload_size_bytes == 0


def test_get_settings_sanitizes_invalid_transcription_override(tmp_path, monkeypatch):
    overrides_file = tmp_path / "roughcut_config.json"
    overrides_file.write_text(
        '{"transcription_provider":"qwen_asr","transcription_model":"Qwen/Qwen3-ASR-1.7B","transcription_dialect":"martian"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", overrides_file)
    config_mod._settings = None

    settings = get_settings()

    assert settings.transcription_provider == "qwen3_asr"
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

    assert settings.transcription_provider == "qwen3_asr"
    assert settings.transcription_model == "qwen3-asr-1.7b"
    assert settings.transcription_dialect == "beijing"
    assert isinstance(settings.qwen_asr_api_base_url, str)
    assert settings.qwen_asr_api_base_url


def test_normalize_transcription_settings_maps_legacy_provider_aliases():
    assert normalize_transcription_settings("local_whisper", "base") == ("faster_whisper", "base")
    assert normalize_transcription_settings("fast", "large-v3") == ("faster_whisper", "large-v3")
    assert normalize_transcription_settings("qwen_asr", "qwen3-asr-1.7b") == ("qwen3_asr", "qwen3-asr-1.7b")
    assert normalize_transcription_settings("qwen3asr", "qwen3-asr-1.7b") == ("qwen3_asr", "qwen3-asr-1.7b")


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


def test_get_settings_prefers_explicit_telegram_env_over_runtime_override(tmp_path, monkeypatch):
    overrides_file = tmp_path / "roughcut_config.json"
    overrides_file.write_text(
        json.dumps(
            {
                "telegram_agent_state_dir": "F:/persisted/state",
                "telegram_bot_api_base_url": "https://persisted.example",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", overrides_file)
    monkeypatch.setenv("TELEGRAM_AGENT_STATE_DIR", "F:/env/state")
    monkeypatch.setenv("TELEGRAM_BOT_API_BASE_URL", "https://127.0.0.1:1")
    config_mod._settings = None
    config_mod._session_secret_overrides.clear()

    settings = get_settings()

    assert settings.telegram_agent_state_dir == "F:/env/state"
    assert settings.telegram_bot_api_base_url == "https://127.0.0.1:1"
    config_mod._settings = None


def test_get_settings_prefers_explicit_telegram_token_env_over_session_secret_override(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env-token")
    config_mod._settings = None
    config_mod._session_secret_overrides.clear()
    config_mod._session_secret_overrides["telegram_bot_token"] = "persisted-token"

    settings = get_settings()

    assert settings.telegram_bot_token == "env-token"
    config_mod._settings = None
    config_mod._session_secret_overrides.clear()


@pytest.mark.asyncio
async def test_reasoning_provider_falls_back_to_backup_bundle():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "llm_mode", "performance")
    object.__setattr__(settings, "reasoning_provider", "openai")
    object.__setattr__(settings, "reasoning_model", "gpt-5.4")
    object.__setattr__(settings, "llm_backup_enabled", True)
    object.__setattr__(settings, "backup_reasoning_provider", "minimax")
    object.__setattr__(settings, "backup_reasoning_model", "MiniMax-M2.7-highspeed")

    calls: list[str] = []

    class _PrimaryProvider:
        async def complete(self, messages, *, temperature=0.3, max_tokens=4096, json_mode=False):
            del messages, temperature, max_tokens, json_mode
            calls.append("openai")
            raise RuntimeError("primary failed")

    class _BackupProvider:
        async def complete(self, messages, *, temperature=0.3, max_tokens=4096, json_mode=False):
            del temperature, max_tokens, json_mode
            calls.append("minimax")
            return ReasoningResponse(
                content=f"backup:{messages[0].content}",
                raw_content=None,
                usage={},
                model="MiniMax-M2.7-highspeed",
            )

    original = factory_mod._build_reasoning_provider
    factory_mod._build_reasoning_provider = lambda provider: _PrimaryProvider() if provider == "openai" else _BackupProvider()
    try:
        provider = factory_mod.get_reasoning_provider()
        response = await provider.complete([Message(role="user", content="hello")])
    finally:
        factory_mod._build_reasoning_provider = original

    assert response.content == "backup:hello"
    assert response.model == "MiniMax-M2.7-highspeed"
    assert calls == ["openai", "minimax"]
