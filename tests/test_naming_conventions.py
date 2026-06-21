from roughcut.api.avatar_materials import _derive_runtime_preview_capability
from roughcut.config import (
    DEFAULT_TRANSCRIPTION_MODELS,
    DEFAULT_TRANSCRIPTION_PROVIDER,
    Settings,
    _normalize_settings,
    _normalize_runtime_override_values,
    canonicalize_transcription_provider_name,
    normalize_transcription_provider_name,
    resolve_llm_task_route,
    resolve_transcription_provider_plan,
    uses_codex_auth_helper,
)
from roughcut.naming import (
    AVATAR_CAPABILITY_GENERATION,
    AVATAR_CAPABILITY_PORTRAIT,
    AVATAR_CAPABILITY_PREVIEW,
    AVATAR_CAPABILITY_VOICE,
    normalize_auth_mode,
    normalize_avatar_capability_status,
)


def test_auth_mode_uses_generic_helper_name() -> None:
    assert normalize_auth_mode("helper") == "helper"
    assert normalize_auth_mode("codex_compat") == "helper"
    assert normalize_auth_mode("codex") == "api_key"
    assert normalize_auth_mode("claude") == "api_key"

    settings = Settings(_env_file=None, openai_auth_mode="codex_compat", anthropic_auth_mode="helper")
    _normalize_settings(settings)

    assert settings.openai_auth_mode == "helper"
    assert settings.anthropic_auth_mode == "helper"


def test_codex_token_helper_uses_cli_bridge_for_responses() -> None:
    token_helper_settings = Settings(
        _env_file=None,
        openai_auth_mode="helper",
        openai_api_key_helper="python scripts/print_codex_access_token.py",
    )
    _normalize_settings(token_helper_settings)

    cli_bridge_settings = Settings(
        _env_file=None,
        openai_auth_mode="helper",
        openai_api_key_helper="codex",
    )
    _normalize_settings(cli_bridge_settings)

    assert uses_codex_auth_helper(token_helper_settings) is True
    assert uses_codex_auth_helper(cli_bridge_settings) is True


def test_content_profile_route_defaults_to_glm_for_analysis() -> None:
    settings = Settings(
        _env_file=None,
        llm_mode="performance",
        llm_routing_mode="hybrid_performance",
        zhipu_api_key="<configured>",
    )
    _normalize_settings(settings)

    route = resolve_llm_task_route("content_profile", settings=settings)

    assert route["reasoning_provider"] == "zhipu"
    assert route["reasoning_model"] == "glm-5.2"
    assert route["reasoning_effort"] == "low"


def test_glm_is_default_main_reasoning_visual_and_searxng_search_route() -> None:
    settings = Settings(_env_file=None)
    _normalize_settings(settings)

    assert settings.reasoning_provider == "zhipu"
    assert settings.reasoning_model == "glm-5.2"
    assert settings.active_vision_model == "glm-4.6v-flash"
    assert settings.multimodal_fallback_provider == "zhipu"
    assert settings.multimodal_fallback_model == "glm-4.6v-flash"
    assert settings.search_provider == "searxng"
    assert settings.search_fallback_provider == "searxng"


def test_searxng_is_default_search_provider_override_shape() -> None:
    normalized = _normalize_runtime_override_values(
        {
            "search_provider": "searxng",
            "search_fallback_provider": "searxng",
            "model_search_helper": "python scripts/codex_model_search_helper.py",
        }
    )

    assert normalized["search_provider"] == "searxng"
    assert normalized["search_fallback_provider"] == "searxng"


def test_search_minimax_route_downgrades_to_searxng_without_minimax_key() -> None:
    settings = Settings(
        _env_file=None,
        minimax_api_key="",
        search_provider="minimax",
        search_fallback_provider="minimax",
        backup_search_provider="minimax",
        backup_search_fallback_provider="minimax",
        searxng_url="http://localhost:8080",
    )
    _normalize_settings(settings)

    assert settings.search_provider == "searxng"
    assert settings.search_fallback_provider == "searxng"
    assert settings.backup_search_provider == "searxng"
    assert settings.backup_search_fallback_provider == "searxng"


def test_cover_image_backend_accepts_minimax_aliases() -> None:
    normalized = _normalize_runtime_override_values(
        {
            "intelligent_copy_cover_image_backend": "minimax_api",
        }
    )

    assert normalized["intelligent_copy_cover_image_backend"] == "minimax_images_api"


def test_copy_route_defaults_to_glm_for_final_copywriting_production() -> None:
    settings = Settings(
        _env_file=None,
        llm_mode="performance",
        llm_routing_mode="hybrid_performance",
    )
    _normalize_settings(settings)

    route = resolve_llm_task_route("copy", settings=settings)

    assert route["reasoning_provider"] == "zhipu"
    assert route["reasoning_model"] == "glm-5.2"


def test_copy_route_keeps_configured_glm_when_gpt_is_not_the_active_codex_bridge() -> None:
    settings = Settings(
        _env_file=None,
        llm_mode="performance",
        llm_routing_mode="hybrid_performance",
        hybrid_copy_provider="zhipu",
        hybrid_copy_model="glm-5.2",
    )
    _normalize_settings(settings)

    route = resolve_llm_task_route("copy", settings=settings)

    assert route["reasoning_provider"] == "zhipu"
    assert route["reasoning_model"] == "glm-5.2"


def test_copy_route_keeps_codex_openai_priority_chain() -> None:
    settings = Settings(
        _env_file=None,
        llm_mode="performance",
        llm_routing_mode="hybrid_performance",
        reasoning_provider="openai",
        reasoning_model="gpt-5.5",
        openai_auth_mode="helper",
        openai_api_key="",
        openai_api_key_helper="python scripts/print_codex_access_token.py",
    )
    _normalize_settings(settings)

    route = resolve_llm_task_route("copy", settings=settings)

    assert route == {}


def test_transcription_aliases_only_keep_canonical_provider_shapes() -> None:
    assert canonicalize_transcription_provider_name("local-asr") == "local_http_asr"
    assert canonicalize_transcription_provider_name("faster-whisper") == "faster_whisper"
    assert canonicalize_transcription_provider_name("fast") == "fast"


def test_transcription_runtime_keeps_explicit_supported_provider_routes() -> None:
    assert DEFAULT_TRANSCRIPTION_PROVIDER == "local_http_asr"
    assert normalize_transcription_provider_name("local-asr") == "local_http_asr"
    assert normalize_transcription_provider_name("faster-whisper") == "faster_whisper"
    assert normalize_transcription_provider_name("openai") == "openai"
    assert normalize_transcription_provider_name("unknown") == DEFAULT_TRANSCRIPTION_PROVIDER
    assert resolve_transcription_provider_plan("openai", "gpt-4o-transcribe") == [
        ("openai", DEFAULT_TRANSCRIPTION_MODELS["openai"])
    ]


def test_legacy_local_http_asr_snapshot_is_normalized_to_current_http_asr_service() -> None:
    normalized = _normalize_runtime_override_values(
        {
            "transcription_provider": "local_http_asr",
            "transcription_model": "moss-audio-8b-instruct",
            "local_asr_api_base_url": "http://127.0.0.1:30080",
            "local_asr_model_name": "moss-audio-8b-instruct",
            "local_asr_display_name": "MOSS-Audio 8B Instruct",
        }
    )

    assert normalized["transcription_model"] == "qwen3-asr-1.7b-forced-aligner"
    assert normalized["local_asr_api_base_url"] == "http://127.0.0.1:30230"
    assert normalized["local_asr_model_name"] == "qwen3-asr-1.7b-forced-aligner"
    assert normalized["local_asr_display_name"] == "Qwen3-ASR 1.7B + ForcedAligner"


def test_avatar_capability_status_uses_business_capability_keys() -> None:
    normalized = normalize_avatar_capability_status(
        {
            "avatar_generation": "ready",
            "voice_clone": "ready",
            "portrait_reference": "ready",
        }
    )

    assert normalized[AVATAR_CAPABILITY_GENERATION] == "ready"
    assert normalized[AVATAR_CAPABILITY_VOICE] == "ready"
    assert normalized[AVATAR_CAPABILITY_PORTRAIT] == "ready"
    assert set(normalized) == {
        AVATAR_CAPABILITY_GENERATION,
        AVATAR_CAPABILITY_VOICE,
        AVATAR_CAPABILITY_PORTRAIT,
        AVATAR_CAPABILITY_PREVIEW,
    }


def test_runtime_avatar_capabilities_do_not_emit_provider_specific_keys() -> None:
    capability, _next_action = _derive_runtime_preview_capability(
        {"avatar_generation": "ready", "voice_clone": "ready"},
        [
            {"role": "speaking_video", "checks": []},
            {"role": "voice_sample", "checks": []},
        ],
        preview_service_available=True,
    )

    assert set(capability) == {
        AVATAR_CAPABILITY_GENERATION,
        AVATAR_CAPABILITY_VOICE,
        AVATAR_CAPABILITY_PORTRAIT,
        AVATAR_CAPABILITY_PREVIEW,
    }
    assert capability[AVATAR_CAPABILITY_GENERATION] == "ready"
    assert capability[AVATAR_CAPABILITY_PREVIEW] == "ready"
