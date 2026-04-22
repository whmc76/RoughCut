from roughcut.api.avatar_materials import _derive_runtime_preview_capability
from roughcut.config import Settings, _normalize_settings, canonicalize_transcription_provider_name
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
    assert normalize_auth_mode("codex") == "api_key"
    assert normalize_auth_mode("claude") == "api_key"

    settings = Settings(_env_file=None, openai_auth_mode="helper", anthropic_auth_mode="helper")
    _normalize_settings(settings)

    assert settings.openai_auth_mode == "helper"
    assert settings.anthropic_auth_mode == "helper"


def test_transcription_aliases_only_keep_canonical_provider_shapes() -> None:
    assert canonicalize_transcription_provider_name("local-asr") == "local_http_asr"
    assert canonicalize_transcription_provider_name("faster-whisper") == "faster_whisper"
    assert canonicalize_transcription_provider_name("fast") == "fast"


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
