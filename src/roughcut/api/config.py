"""Runtime config API — read/write roughcut_config.json to override env vars."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from roughcut.api.options import (
    JOB_LANGUAGE_OPTIONS,
    MULTIMODAL_FALLBACK_PROVIDER_OPTIONS,
    SEARCH_FALLBACK_PROVIDER_OPTIONS,
    SEARCH_PROVIDER_OPTIONS,
    build_avatar_provider_options,
    build_channel_profile_options,
    build_enhancement_mode_options,
    build_transcription_dialect_options,
    build_voice_provider_options,
    build_workflow_mode_options,
    normalize_job_language,
)
from roughcut.config import (
    AVATAR_PROVIDER_OPTIONS,
    DEFAULT_TRANSCRIPTION_PROVIDER,
    PROFILE_BINDABLE_SETTINGS,
    TRANSCRIPTION_MODEL_OPTIONS,
    VOICE_PROVIDER_OPTIONS,
    apply_runtime_overrides,
    clear_runtime_overrides,
    get_settings,
    get_session_secret_override_keys,
    load_runtime_overrides,
    normalize_transcription_settings,
)
from roughcut.config_profiles import (
    CONFIG_PROFILES_FILE,
    activate_config_profile,
    build_config_profiles_payload,
    create_config_profile,
    delete_config_profile,
    update_config_profile,
)
from roughcut.creative.modes import normalize_enhancement_modes, normalize_workflow_mode
from roughcut.creative.modes import build_mode_catalog
from roughcut.packaging.library import MANIFEST_PATH
from roughcut.speech.dialects import DEFAULT_TRANSCRIPTION_DIALECT, normalize_transcription_dialect

router = APIRouter(prefix="/config", tags=["config"])

_CONFIG_FILE = Path("roughcut_config.json")
_SECRET_OVERRIDE_KEYS = {
    "openai_api_key",
    "anthropic_api_key",
    "minimax_api_key",
    "minimax_coding_plan_api_key",
    "ollama_api_key",
    "avatar_api_key",
    "voice_clone_api_key",
    "telegram_bot_token",
}


class ConfigOut(BaseModel):
    persistence: dict[str, Any]
    # Transcription
    transcription_provider: str
    transcription_model: str
    transcription_dialect: str
    # Reasoning
    llm_mode: str
    reasoning_provider: str
    reasoning_model: str
    local_reasoning_model: str
    local_vision_model: str
    multimodal_fallback_provider: str
    multimodal_fallback_model: str
    search_provider: str
    search_fallback_provider: str
    model_search_helper: str
    openai_base_url: str
    openai_auth_mode: str
    openai_api_key_helper: str
    qwen_asr_api_base_url: str
    avatar_provider: str
    avatar_api_base_url: str
    avatar_training_api_base_url: str
    avatar_api_key_set: bool
    avatar_presenter_id: str
    avatar_layout_template: str
    avatar_safe_margin: float
    avatar_overlay_scale: float
    anthropic_base_url: str
    anthropic_auth_mode: str
    anthropic_api_key_helper: str
    minimax_base_url: str
    minimax_api_host: str
    voice_provider: str
    voice_clone_api_base_url: str
    voice_clone_api_key_set: bool
    voice_clone_voice_id: str
    director_rewrite_strength: float
    ollama_api_key_set: bool
    # Keys (masked)
    openai_api_key_set: bool
    anthropic_api_key_set: bool
    minimax_api_key_set: bool
    minimax_coding_plan_api_key_set: bool
    ollama_base_url: str
    # Security
    max_upload_size_mb: int
    max_video_duration_sec: int
    ffmpeg_timeout_sec: int
    allowed_extensions: list[str]
    output_dir: str
    preferred_ui_language: str
    telegram_agent_enabled: bool
    telegram_agent_claude_enabled: bool
    telegram_agent_claude_command: str
    telegram_agent_claude_model: str
    telegram_agent_codex_command: str
    telegram_agent_codex_model: str
    telegram_agent_acp_command: str
    telegram_agent_task_timeout_sec: int
    telegram_agent_result_max_chars: int
    telegram_agent_state_dir: str
    acp_bridge_backend: str
    acp_bridge_fallback_backend: str
    acp_bridge_claude_model: str
    acp_bridge_codex_command: str
    acp_bridge_codex_model: str
    telegram_remote_review_enabled: bool
    telegram_bot_api_base_url: str
    telegram_bot_token_set: bool
    telegram_bot_chat_id: str
    default_job_workflow_mode: str
    default_job_enhancement_modes: list[str]
    # Feature flags
    fact_check_enabled: bool
    auto_confirm_content_profile: bool
    content_profile_review_threshold: float
    content_profile_auto_review_min_accuracy: float
    content_profile_auto_review_min_samples: int
    auto_accept_glossary_corrections: bool
    glossary_correction_review_threshold: float
    auto_select_cover_variant: bool
    cover_selection_review_gap: float
    packaging_selection_review_gap: float
    packaging_selection_min_score: float
    subtitle_filler_cleanup_enabled: bool
    quality_auto_rerun_enabled: bool
    quality_auto_rerun_below_score: float
    quality_auto_rerun_max_attempts: int
    # Overrides currently stored
    override_keys: list[str]
    session_secret_keys: list[str]
    profile_bindable_keys: list[str]
    overrides: dict


def _sanitize_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in overrides.items():
        if key in _SECRET_OVERRIDE_KEYS:
            sanitized[key] = "[secure]" if str(value or "").strip() else ""
        else:
            sanitized[key] = value
    return sanitized


class ConfigOptionsOut(BaseModel):
    job_languages: list[dict[str, str]]
    channel_profiles: list[dict[str, str]]
    workflow_modes: list[dict[str, str]]
    enhancement_modes: list[dict[str, str]]
    transcription_dialects: list[dict[str, str]]
    avatar_providers: list[dict[str, str]]
    voice_providers: list[dict[str, str]]
    creative_mode_catalog: dict[str, list[dict[str, Any]]]
    transcription_models: dict[str, list[str]]
    multimodal_fallback_providers: list[dict[str, str]]
    search_providers: list[dict[str, str]]
    search_fallback_providers: list[dict[str, str]]


class ConfigProfileOut(BaseModel):
    id: str
    name: str
    description: str
    created_at: str
    updated_at: str
    is_active: bool
    is_dirty: bool
    dirty_keys: list[str]
    dirty_details: list[dict[str, Any]]
    llm_mode: str
    transcription_provider: str
    transcription_model: str
    transcription_dialect: str
    reasoning_provider: str
    reasoning_model: str
    workflow_mode: str
    enhancement_modes: list[str]
    auto_confirm_content_profile: bool
    content_profile_review_threshold: float
    packaging_selection_min_score: float
    quality_auto_rerun_enabled: bool
    quality_auto_rerun_below_score: float
    copy_style: str
    cover_style: str
    title_style: str
    subtitle_style: str
    smart_effect_style: str
    avatar_presenter_id: str
    packaging_enabled: bool
    insert_pool_size: int
    music_pool_size: int


class ConfigProfilesOut(BaseModel):
    active_profile_id: str | None = None
    active_profile_dirty: bool = False
    active_profile_dirty_keys: list[str] = []
    active_profile_dirty_details: list[dict[str, Any]] = []
    profiles: list[ConfigProfileOut]


class ConfigProfileCreate(BaseModel):
    name: str
    description: str | None = None


class ConfigProfileUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    capture_current: bool = False


class ConfigPatch(BaseModel):
    transcription_provider: str | None = None
    transcription_model: str | None = None
    transcription_dialect: str | None = None
    llm_mode: str | None = None
    reasoning_provider: str | None = None
    reasoning_model: str | None = None
    local_reasoning_model: str | None = None
    local_vision_model: str | None = None
    multimodal_fallback_provider: str | None = None
    multimodal_fallback_model: str | None = None
    search_provider: str | None = None
    search_fallback_provider: str | None = None
    model_search_helper: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_auth_mode: str | None = None
    openai_api_key_helper: str | None = None
    qwen_asr_api_base_url: str | None = None
    avatar_provider: str | None = None
    avatar_api_base_url: str | None = None
    avatar_training_api_base_url: str | None = None
    avatar_api_key: str | None = None
    avatar_presenter_id: str | None = None
    avatar_layout_template: str | None = None
    avatar_safe_margin: float | None = None
    avatar_overlay_scale: float | None = None
    anthropic_api_key: str | None = None
    anthropic_base_url: str | None = None
    anthropic_auth_mode: str | None = None
    anthropic_api_key_helper: str | None = None
    minimax_api_key: str | None = None
    minimax_base_url: str | None = None
    minimax_api_host: str | None = None
    minimax_coding_plan_api_key: str | None = None
    voice_provider: str | None = None
    voice_clone_api_base_url: str | None = None
    voice_clone_api_key: str | None = None
    voice_clone_voice_id: str | None = None
    director_rewrite_strength: float | None = None
    ollama_api_key: str | None = None
    ollama_base_url: str | None = None
    max_upload_size_mb: int | None = None
    max_video_duration_sec: int | None = None
    ffmpeg_timeout_sec: int | None = None
    allowed_extensions: list[str] | None = None
    output_dir: str | None = None
    preferred_ui_language: str | None = None
    telegram_agent_enabled: bool | None = None
    telegram_agent_claude_enabled: bool | None = None
    telegram_agent_claude_command: str | None = None
    telegram_agent_claude_model: str | None = None
    telegram_agent_codex_command: str | None = None
    telegram_agent_codex_model: str | None = None
    telegram_agent_acp_command: str | None = None
    telegram_agent_task_timeout_sec: int | None = None
    telegram_agent_result_max_chars: int | None = None
    telegram_agent_state_dir: str | None = None
    acp_bridge_backend: str | None = None
    acp_bridge_fallback_backend: str | None = None
    acp_bridge_claude_model: str | None = None
    acp_bridge_codex_command: str | None = None
    acp_bridge_codex_model: str | None = None
    telegram_remote_review_enabled: bool | None = None
    telegram_bot_api_base_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_bot_chat_id: str | None = None
    default_job_workflow_mode: str | None = None
    default_job_enhancement_modes: list[str] | None = None
    fact_check_enabled: bool | None = None
    auto_confirm_content_profile: bool | None = None
    content_profile_review_threshold: float | None = None
    content_profile_auto_review_min_accuracy: float | None = None
    content_profile_auto_review_min_samples: int | None = None
    auto_accept_glossary_corrections: bool | None = None
    glossary_correction_review_threshold: float | None = None
    auto_select_cover_variant: bool | None = None
    cover_selection_review_gap: float | None = None
    packaging_selection_review_gap: float | None = None
    packaging_selection_min_score: float | None = None
    subtitle_filler_cleanup_enabled: bool | None = None
    quality_auto_rerun_enabled: bool | None = None
    quality_auto_rerun_below_score: float | None = None
    quality_auto_rerun_max_attempts: int | None = None


@router.get("", response_model=ConfigOut)
def get_config():
    s = get_settings()
    overrides = load_runtime_overrides()
    sanitized_overrides = _sanitize_overrides(overrides)
    session_secret_keys = get_session_secret_override_keys()
    return ConfigOut(
        persistence={
            "settings_store": "database",
            "profiles_store": "database",
            "packaging_store": "database",
            "legacy_override_file_present": _CONFIG_FILE.exists(),
            "legacy_profiles_file_present": CONFIG_PROFILES_FILE.exists(),
            "legacy_packaging_manifest_present": MANIFEST_PATH.exists(),
        },
        transcription_provider=s.transcription_provider,
        transcription_model=s.transcription_model,
        transcription_dialect=s.transcription_dialect,
        llm_mode=s.llm_mode,
        reasoning_provider=s.reasoning_provider,
        reasoning_model=s.reasoning_model,
        local_reasoning_model=s.local_reasoning_model,
        local_vision_model=s.local_vision_model,
        multimodal_fallback_provider=s.multimodal_fallback_provider,
        multimodal_fallback_model=s.multimodal_fallback_model,
        search_provider=s.search_provider,
        search_fallback_provider=s.search_fallback_provider,
        model_search_helper=s.model_search_helper,
        openai_base_url=s.openai_base_url,
        openai_auth_mode=s.openai_auth_mode,
        openai_api_key_helper=s.openai_api_key_helper,
        qwen_asr_api_base_url=s.qwen_asr_api_base_url,
        avatar_provider=s.avatar_provider,
        avatar_api_base_url=s.avatar_api_base_url,
        avatar_training_api_base_url=s.avatar_training_api_base_url,
        avatar_api_key_set=bool(s.avatar_api_key),
        avatar_presenter_id=s.avatar_presenter_id,
        avatar_layout_template=s.avatar_layout_template,
        avatar_safe_margin=s.avatar_safe_margin,
        avatar_overlay_scale=s.avatar_overlay_scale,
        anthropic_base_url=s.anthropic_base_url,
        anthropic_auth_mode=s.anthropic_auth_mode,
        anthropic_api_key_helper=s.anthropic_api_key_helper,
        minimax_base_url=s.minimax_base_url,
        minimax_api_host=s.minimax_api_host,
        voice_provider=s.voice_provider,
        voice_clone_api_base_url=s.voice_clone_api_base_url,
        voice_clone_api_key_set=bool(s.voice_clone_api_key),
        voice_clone_voice_id=s.voice_clone_voice_id,
        director_rewrite_strength=s.director_rewrite_strength,
        ollama_api_key_set=bool(s.ollama_api_key),
        openai_api_key_set=bool(s.openai_api_key),
        anthropic_api_key_set=bool(s.anthropic_api_key),
        minimax_api_key_set=bool(s.minimax_api_key),
        minimax_coding_plan_api_key_set=bool(s.minimax_coding_plan_api_key),
        ollama_base_url=s.ollama_base_url,
        max_upload_size_mb=s.max_upload_size_mb,
        max_video_duration_sec=s.max_video_duration_sec,
        ffmpeg_timeout_sec=s.ffmpeg_timeout_sec,
        allowed_extensions=s.allowed_extensions,
        output_dir=s.output_dir,
        preferred_ui_language=s.preferred_ui_language,
        telegram_agent_enabled=s.telegram_agent_enabled,
        telegram_agent_claude_enabled=s.telegram_agent_claude_enabled,
        telegram_agent_claude_command=s.telegram_agent_claude_command,
        telegram_agent_claude_model=s.telegram_agent_claude_model,
        telegram_agent_codex_command=s.telegram_agent_codex_command,
        telegram_agent_codex_model=s.telegram_agent_codex_model,
        telegram_agent_acp_command=s.telegram_agent_acp_command,
        telegram_agent_task_timeout_sec=s.telegram_agent_task_timeout_sec,
        telegram_agent_result_max_chars=s.telegram_agent_result_max_chars,
        telegram_agent_state_dir=s.telegram_agent_state_dir,
        acp_bridge_backend=s.acp_bridge_backend,
        acp_bridge_fallback_backend=s.acp_bridge_fallback_backend,
        acp_bridge_claude_model=s.acp_bridge_claude_model,
        acp_bridge_codex_command=s.acp_bridge_codex_command,
        acp_bridge_codex_model=s.acp_bridge_codex_model,
        telegram_remote_review_enabled=s.telegram_remote_review_enabled,
        telegram_bot_api_base_url=s.telegram_bot_api_base_url,
        telegram_bot_token_set=bool(s.telegram_bot_token),
        telegram_bot_chat_id=s.telegram_bot_chat_id,
        default_job_workflow_mode=s.default_job_workflow_mode,
        default_job_enhancement_modes=s.default_job_enhancement_modes,
        fact_check_enabled=s.fact_check_enabled,
        auto_confirm_content_profile=s.auto_confirm_content_profile,
        content_profile_review_threshold=s.content_profile_review_threshold,
        content_profile_auto_review_min_accuracy=s.content_profile_auto_review_min_accuracy,
        content_profile_auto_review_min_samples=s.content_profile_auto_review_min_samples,
        auto_accept_glossary_corrections=s.auto_accept_glossary_corrections,
        glossary_correction_review_threshold=s.glossary_correction_review_threshold,
        auto_select_cover_variant=s.auto_select_cover_variant,
        cover_selection_review_gap=s.cover_selection_review_gap,
        packaging_selection_review_gap=s.packaging_selection_review_gap,
        packaging_selection_min_score=s.packaging_selection_min_score,
        subtitle_filler_cleanup_enabled=s.subtitle_filler_cleanup_enabled,
        quality_auto_rerun_enabled=s.quality_auto_rerun_enabled,
        quality_auto_rerun_below_score=s.quality_auto_rerun_below_score,
        quality_auto_rerun_max_attempts=s.quality_auto_rerun_max_attempts,
        override_keys=sorted(overrides.keys()),
        session_secret_keys=session_secret_keys,
        profile_bindable_keys=sorted(PROFILE_BINDABLE_SETTINGS),
        overrides=sanitized_overrides,
    )


@router.get("/options", response_model=ConfigOptionsOut)
def get_config_options():
    return ConfigOptionsOut(
        job_languages=JOB_LANGUAGE_OPTIONS,
        channel_profiles=build_channel_profile_options(),
        workflow_modes=build_workflow_mode_options(),
        enhancement_modes=build_enhancement_mode_options(),
        transcription_dialects=build_transcription_dialect_options(),
        avatar_providers=build_avatar_provider_options(),
        voice_providers=build_voice_provider_options(),
        creative_mode_catalog=build_mode_catalog(),
        transcription_models=TRANSCRIPTION_MODEL_OPTIONS,
        multimodal_fallback_providers=MULTIMODAL_FALLBACK_PROVIDER_OPTIONS,
        search_providers=SEARCH_PROVIDER_OPTIONS,
        search_fallback_providers=SEARCH_FALLBACK_PROVIDER_OPTIONS,
    )


@router.get("/profiles", response_model=ConfigProfilesOut)
def get_config_profiles():
    return ConfigProfilesOut(**build_config_profiles_payload())


@router.post("/profiles", response_model=ConfigProfilesOut, status_code=201)
def create_profile(body: ConfigProfileCreate):
    try:
        payload = create_config_profile(body.name, description=body.description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ConfigProfilesOut(**payload)


@router.patch("/profiles/{profile_id}", response_model=ConfigProfilesOut)
def patch_profile(profile_id: str, body: ConfigProfileUpdate):
    try:
        payload = update_config_profile(
            profile_id,
            name=body.name,
            description=body.description,
            capture_current=body.capture_current,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="剪辑配置不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ConfigProfilesOut(**payload)


@router.post("/profiles/{profile_id}/activate", response_model=ConfigProfilesOut)
def activate_profile(profile_id: str):
    try:
        payload = activate_config_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="剪辑配置不存在") from exc
    return ConfigProfilesOut(**payload)


@router.delete("/profiles/{profile_id}", response_model=ConfigProfilesOut)
def remove_profile(profile_id: str):
    try:
        payload = delete_config_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="剪辑配置不存在") from exc
    return ConfigProfilesOut(**payload)


@router.patch("", response_model=ConfigOut)
def patch_config(body: ConfigPatch):
    overrides = load_runtime_overrides()

    updates = body.model_dump(exclude_none=True)
    if "transcription_provider" in updates:
        provider = str(updates["transcription_provider"]).strip().lower()
        if provider not in TRANSCRIPTION_MODEL_OPTIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Unsupported transcription_provider. "
                    f"Use one of: {', '.join(sorted(TRANSCRIPTION_MODEL_OPTIONS))}"
                ),
            )
        updates["transcription_provider"] = provider
    if "transcription_dialect" in updates:
        dialect = str(updates["transcription_dialect"]).strip().lower()
        normalized_dialect = normalize_transcription_dialect(dialect)
        if dialect != normalized_dialect and dialect:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported transcription_dialect. Use one of: {', '.join(item['value'] for item in build_transcription_dialect_options())}",
            )
        updates["transcription_dialect"] = normalized_dialect or DEFAULT_TRANSCRIPTION_DIALECT
    if "avatar_provider" in updates:
        avatar_provider = str(updates["avatar_provider"]).strip().lower()
        if avatar_provider not in AVATAR_PROVIDER_OPTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported avatar_provider. Use one of: {', '.join(AVATAR_PROVIDER_OPTIONS)}",
            )
        updates["avatar_provider"] = avatar_provider
    if "voice_provider" in updates:
        voice_provider = str(updates["voice_provider"]).strip().lower()
        if voice_provider not in VOICE_PROVIDER_OPTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported voice_provider. Use one of: {', '.join(VOICE_PROVIDER_OPTIONS)}",
            )
        updates["voice_provider"] = voice_provider
    if "output_dir" in updates:
        output_dir = str(updates["output_dir"]).strip()
        if not output_dir:
            raise HTTPException(status_code=400, detail="output_dir cannot be empty")
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        updates["output_dir"] = output_dir
    if "preferred_ui_language" in updates:
        try:
            updates["preferred_ui_language"] = normalize_job_language(str(updates["preferred_ui_language"] or ""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "telegram_bot_api_base_url" in updates:
        api_base_url = str(updates["telegram_bot_api_base_url"]).strip().rstrip("/")
        if not api_base_url:
            raise HTTPException(status_code=400, detail="telegram_bot_api_base_url cannot be empty")
        updates["telegram_bot_api_base_url"] = api_base_url
    if "telegram_agent_claude_command" in updates:
        updates["telegram_agent_claude_command"] = str(updates["telegram_agent_claude_command"] or "").strip() or "claude"
    if "telegram_agent_claude_model" in updates:
        updates["telegram_agent_claude_model"] = str(updates["telegram_agent_claude_model"] or "").strip() or "opus"
    if "telegram_agent_codex_command" in updates:
        updates["telegram_agent_codex_command"] = str(updates["telegram_agent_codex_command"] or "").strip() or "codex"
    if "telegram_agent_codex_model" in updates:
        updates["telegram_agent_codex_model"] = str(updates["telegram_agent_codex_model"] or "").strip() or "gpt-5.4-mini"
    if "telegram_agent_acp_command" in updates:
        updates["telegram_agent_acp_command"] = str(updates["telegram_agent_acp_command"] or "").strip()
    if "telegram_agent_state_dir" in updates:
        state_dir = str(updates["telegram_agent_state_dir"] or "").strip()
        if not state_dir:
            raise HTTPException(status_code=400, detail="telegram_agent_state_dir cannot be empty")
        Path(state_dir).mkdir(parents=True, exist_ok=True)
        updates["telegram_agent_state_dir"] = state_dir
    if "acp_bridge_backend" in updates:
        backend = str(updates["acp_bridge_backend"] or "").strip().lower()
        if backend not in {"claude", "codex"}:
            raise HTTPException(status_code=400, detail="acp_bridge_backend must be claude or codex")
        updates["acp_bridge_backend"] = backend
    if "acp_bridge_fallback_backend" in updates:
        fallback_backend = str(updates["acp_bridge_fallback_backend"] or "").strip().lower()
        if fallback_backend not in {"claude", "codex"}:
            raise HTTPException(status_code=400, detail="acp_bridge_fallback_backend must be claude or codex")
        updates["acp_bridge_fallback_backend"] = fallback_backend
    if "acp_bridge_claude_model" in updates:
        updates["acp_bridge_claude_model"] = str(updates["acp_bridge_claude_model"] or "").strip() or "opus"
    if "acp_bridge_codex_command" in updates:
        updates["acp_bridge_codex_command"] = str(updates["acp_bridge_codex_command"] or "").strip() or "codex"
    if "acp_bridge_codex_model" in updates:
        updates["acp_bridge_codex_model"] = str(updates["acp_bridge_codex_model"] or "").strip() or "gpt-5.4-mini"
    if "telegram_bot_chat_id" in updates:
        updates["telegram_bot_chat_id"] = str(updates["telegram_bot_chat_id"] or "").strip()
    if "default_job_workflow_mode" in updates:
        try:
            updates["default_job_workflow_mode"] = normalize_workflow_mode(str(updates["default_job_workflow_mode"] or ""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "default_job_enhancement_modes" in updates:
        try:
            updates["default_job_enhancement_modes"] = normalize_enhancement_modes(
                list(updates["default_job_enhancement_modes"] or []),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if "content_profile_review_threshold" in updates:
        updates["content_profile_review_threshold"] = max(
            0.0,
            min(1.0, float(updates["content_profile_review_threshold"])),
        )
    if "content_profile_auto_review_min_accuracy" in updates:
        updates["content_profile_auto_review_min_accuracy"] = max(
            0.0,
            min(1.0, float(updates["content_profile_auto_review_min_accuracy"])),
        )
    if "content_profile_auto_review_min_samples" in updates:
        updates["content_profile_auto_review_min_samples"] = max(
            1,
            min(10000, int(updates["content_profile_auto_review_min_samples"])),
        )
    if "avatar_safe_margin" in updates:
        updates["avatar_safe_margin"] = max(0.0, min(0.4, float(updates["avatar_safe_margin"])))
    if "avatar_overlay_scale" in updates:
        updates["avatar_overlay_scale"] = max(0.08, min(0.5, float(updates["avatar_overlay_scale"])))
    if "director_rewrite_strength" in updates:
        updates["director_rewrite_strength"] = max(0.0, min(1.0, float(updates["director_rewrite_strength"])))
    if "glossary_correction_review_threshold" in updates:
        updates["glossary_correction_review_threshold"] = max(
            0.0,
            min(1.0, float(updates["glossary_correction_review_threshold"])),
        )
    if "cover_selection_review_gap" in updates:
        updates["cover_selection_review_gap"] = max(
            0.0,
            min(1.0, float(updates["cover_selection_review_gap"])),
        )
    if "packaging_selection_review_gap" in updates:
        updates["packaging_selection_review_gap"] = max(
            0.0,
            min(1.0, float(updates["packaging_selection_review_gap"])),
        )
    if "packaging_selection_min_score" in updates:
        updates["packaging_selection_min_score"] = max(
            0.0,
            min(1.0, float(updates["packaging_selection_min_score"])),
        )
    if "quality_auto_rerun_below_score" in updates:
        updates["quality_auto_rerun_below_score"] = max(
            0.0,
            min(100.0, float(updates["quality_auto_rerun_below_score"])),
        )
    if "quality_auto_rerun_max_attempts" in updates:
        updates["quality_auto_rerun_max_attempts"] = max(0, min(5, int(updates["quality_auto_rerun_max_attempts"])))
    if "telegram_agent_task_timeout_sec" in updates:
        updates["telegram_agent_task_timeout_sec"] = max(30, min(7200, int(updates["telegram_agent_task_timeout_sec"])))
    if "telegram_agent_result_max_chars" in updates:
        updates["telegram_agent_result_max_chars"] = max(500, min(12000, int(updates["telegram_agent_result_max_chars"])))
    current_provider = updates.get(
        "transcription_provider",
        overrides.get("transcription_provider", DEFAULT_TRANSCRIPTION_PROVIDER),
    )
    current_model = updates.get("transcription_model", overrides.get("transcription_model"))
    provider, model = normalize_transcription_settings(current_provider, current_model)
    updates["transcription_provider"] = provider
    updates["transcription_model"] = model

    apply_runtime_overrides(updates)

    return get_config()


@router.delete("/overrides", status_code=204)
def reset_config():
    """Reset all runtime overrides — revert to env vars."""
    clear_runtime_overrides()
