"""Runtime config API backed by the application database."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from roughcut.api.options import (
    JOB_LANGUAGE_OPTIONS,
    MULTIMODAL_FALLBACK_PROVIDER_OPTIONS,
    SEARCH_FALLBACK_PROVIDER_OPTIONS,
    SEARCH_PROVIDER_OPTIONS,
    build_avatar_provider_options,
    build_enhancement_mode_options,
    build_transcription_dialect_options,
    build_voice_provider_options,
    build_workflow_template_options,
    build_workflow_mode_options,
    normalize_job_language,
)
from roughcut.api.provider_catalog import build_provider_check_payload, build_service_status_payload, get_model_catalog_payload
from roughcut.config import (
    AVATAR_PROVIDER_OPTIONS,
    DEFAULT_TRANSCRIPTION_PROVIDER,
    ENV_MANAGED_SETTINGS,
    HYBRID_REASONING_PROVIDER_VALUES,
    PROFILE_BINDABLE_SETTINGS,
    SEARCH_FALLBACK_PROVIDER_VALUES,
    SEARCH_PROVIDER_VALUES,
    TRANSCRIPTION_MODEL_OPTIONS,
    VOICE_PROVIDER_OPTIONS,
    apply_runtime_overrides,
    clear_runtime_overrides,
    get_settings,
    get_session_secret_override_keys,
    load_runtime_overrides,
    normalize_reasoning_model_for_provider,
    canonicalize_transcription_provider_name,
    normalize_transcription_settings,
)
from roughcut.naming import CODING_BACKEND_VALUES
from roughcut.config_profiles import (
    activate_config_profile,
    build_config_profiles_payload,
    create_config_profile,
    delete_config_profile,
    update_config_profile,
)
from roughcut.creative.modes import normalize_enhancement_modes, normalize_workflow_mode
from roughcut.creative.modes import build_mode_catalog
from roughcut.speech.dialects import DEFAULT_TRANSCRIPTION_DIALECT, normalize_transcription_dialect

router = APIRouter(prefix="/config", tags=["config"])

_SECRET_OVERRIDE_KEYS = {
    "openai_api_key",
    "anthropic_api_key",
    "minimax_api_key",
    "minimax_coding_plan_api_key",
    "ollama_api_key",
    "avatar_api_key",
    "voice_clone_api_key",
    "publication_browser_agent_auth_token",
    "telegram_bot_token",
}


class ConfigOut(BaseModel):
    persistence: dict[str, Any]
    # Transcription
    transcription_provider: str
    transcription_model: str
    transcription_dialect: str
    transcription_alignment_mode: str
    transcription_alignment_min_word_coverage: float
    # Reasoning
    llm_mode: str
    llm_routing_mode: str
    reasoning_provider: str
    reasoning_model: str
    llm_backup_enabled: bool
    backup_reasoning_provider: str
    backup_reasoning_model: str
    backup_reasoning_effort: str
    backup_vision_model: str
    backup_search_provider: str
    backup_search_fallback_provider: str
    backup_model_search_helper: str
    local_reasoning_model: str
    local_vision_model: str
    hybrid_analysis_provider: str
    hybrid_analysis_model: str
    hybrid_analysis_search_mode: str
    hybrid_copy_provider: str
    hybrid_copy_model: str
    hybrid_copy_search_mode: str
    multimodal_fallback_provider: str
    multimodal_fallback_model: str
    search_provider: str
    search_fallback_provider: str
    model_search_helper: str
    local_asr_api_base_url: str
    local_asr_model_name: str
    local_asr_display_name: str
    transcription_chunking_enabled: bool
    transcription_chunk_threshold_sec: int
    transcription_chunk_size_sec: int
    transcription_chunk_min_sec: int
    transcription_chunk_overlap_sec: float
    transcription_chunk_request_timeout_sec: int
    transcription_chunk_request_max_retries: int
    transcription_chunk_request_retry_backoff_sec: float
    avatar_provider: str
    avatar_api_key_set: bool
    avatar_presenter_id: str
    avatar_layout_template: str
    avatar_safe_margin: float
    avatar_overlay_scale: float
    voice_provider: str
    voice_clone_api_key_set: bool
    voice_clone_voice_id: str
    director_rewrite_strength: float
    publication_browser_agent_base_url: str
    publication_browser_agent_auth_token_set: bool
    publication_worker_poll_interval_sec: int
    publication_worker_batch_limit: int
    publication_attempt_lease_sec: int
    publication_browser_agent_timeout_sec: int
    ollama_api_key_set: bool
    # Keys (masked)
    openai_api_key_set: bool
    anthropic_api_key_set: bool
    minimax_api_key_set: bool
    minimax_coding_plan_api_key_set: bool
    # Security
    max_upload_size_mb: int
    max_video_duration_sec: int
    ffmpeg_timeout_sec: int
    transcribe_runtime_timeout_sec: int
    allowed_extensions: list[str]
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


class RuntimeEnvironmentOut(BaseModel):
    openai_base_url: str
    openai_auth_mode: str
    openai_api_key_helper: str
    anthropic_base_url: str
    anthropic_auth_mode: str
    anthropic_api_key_helper: str
    minimax_base_url: str
    minimax_api_host: str
    ollama_base_url: str
    avatar_api_base_url: str
    avatar_training_api_base_url: str
    voice_clone_api_base_url: str
    publication_browser_agent_base_url: str
    output_dir: str


class ProviderServiceStatusEntryOut(BaseModel):
    name: str
    base_url: str
    status: str
    error: str | None = None


class ProviderServiceStatusOut(BaseModel):
    checked_at: str
    services: dict[str, ProviderServiceStatusEntryOut]


class ModelCatalogOut(BaseModel):
    provider: str
    kind: str
    models: list[str]
    source: str
    refreshed_at: str
    status: str
    error: str | None = None


class ProviderCheckOut(BaseModel):
    provider: str
    base_url: str
    checked_at: str
    status: str
    detail: str | None = None
    models: list[str] = Field(default_factory=list)


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
    workflow_templates: list[dict[str, str]]
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
    transcription_alignment_mode: str | None = None
    transcription_alignment_min_word_coverage: float | None = None
    llm_mode: str | None = None
    llm_routing_mode: str | None = None
    reasoning_provider: str | None = None
    reasoning_model: str | None = None
    llm_backup_enabled: bool | None = None
    backup_reasoning_provider: str | None = None
    backup_reasoning_model: str | None = None
    backup_reasoning_effort: str | None = None
    backup_vision_model: str | None = None
    backup_search_provider: str | None = None
    backup_search_fallback_provider: str | None = None
    backup_model_search_helper: str | None = None
    local_reasoning_model: str | None = None
    local_vision_model: str | None = None
    hybrid_analysis_provider: str | None = None
    hybrid_analysis_model: str | None = None
    hybrid_analysis_search_mode: str | None = None
    hybrid_copy_provider: str | None = None
    hybrid_copy_model: str | None = None
    hybrid_copy_search_mode: str | None = None
    multimodal_fallback_provider: str | None = None
    multimodal_fallback_model: str | None = None
    search_provider: str | None = None
    search_fallback_provider: str | None = None
    model_search_helper: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_auth_mode: str | None = None
    openai_api_key_helper: str | None = None
    local_asr_api_base_url: str | None = None
    local_asr_model_name: str | None = None
    local_asr_display_name: str | None = None
    transcription_chunking_enabled: bool | None = None
    transcription_chunk_threshold_sec: int | None = None
    transcription_chunk_size_sec: int | None = None
    transcription_chunk_min_sec: int | None = None
    transcription_chunk_overlap_sec: float | None = None
    transcription_chunk_request_timeout_sec: int | None = None
    transcription_chunk_request_max_retries: int | None = None
    transcription_chunk_request_retry_backoff_sec: float | None = None
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
    publication_browser_agent_base_url: str | None = None
    publication_browser_agent_auth_token: str | None = None
    publication_worker_poll_interval_sec: int | None = None
    publication_worker_batch_limit: int | None = None
    publication_attempt_lease_sec: int | None = None
    publication_browser_agent_timeout_sec: int | None = None
    ollama_api_key: str | None = None
    ollama_base_url: str | None = None
    max_upload_size_mb: int | None = None
    max_video_duration_sec: int | None = None
    ffmpeg_timeout_sec: int | None = None
    transcribe_runtime_timeout_sec: int | None = None
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
    reasoning_model = normalize_reasoning_model_for_provider(s.reasoning_provider, s.reasoning_model)
    backup_reasoning_model = normalize_reasoning_model_for_provider(
        s.backup_reasoning_provider,
        s.backup_reasoning_model,
    )
    hybrid_analysis_model = normalize_reasoning_model_for_provider(
        s.hybrid_analysis_provider,
        s.hybrid_analysis_model,
    )
    hybrid_copy_model = normalize_reasoning_model_for_provider(
        s.hybrid_copy_provider,
        s.hybrid_copy_model,
    )
    return ConfigOut(
        persistence={
            "settings_store": "database",
            "profiles_store": "database",
            "packaging_store": "database",
        },
        transcription_provider=s.transcription_provider,
        transcription_model=s.transcription_model,
        transcription_dialect=s.transcription_dialect,
        transcription_alignment_mode=s.transcription_alignment_mode,
        transcription_alignment_min_word_coverage=s.transcription_alignment_min_word_coverage,
        llm_mode=s.llm_mode,
        llm_routing_mode=s.llm_routing_mode,
        reasoning_provider=s.reasoning_provider,
        reasoning_model=reasoning_model,
        llm_backup_enabled=s.llm_backup_enabled,
        backup_reasoning_provider=s.backup_reasoning_provider,
        backup_reasoning_model=backup_reasoning_model,
        backup_reasoning_effort=s.backup_reasoning_effort,
        backup_vision_model=s.backup_vision_model,
        backup_search_provider=s.backup_search_provider,
        backup_search_fallback_provider=s.backup_search_fallback_provider,
        backup_model_search_helper=s.backup_model_search_helper,
        local_reasoning_model=s.local_reasoning_model,
        local_vision_model=s.local_vision_model,
        hybrid_analysis_provider=s.hybrid_analysis_provider,
        hybrid_analysis_model=hybrid_analysis_model,
        hybrid_analysis_search_mode=s.hybrid_analysis_search_mode,
        hybrid_copy_provider=s.hybrid_copy_provider,
        hybrid_copy_model=hybrid_copy_model,
        hybrid_copy_search_mode=s.hybrid_copy_search_mode,
        multimodal_fallback_provider=s.multimodal_fallback_provider,
        multimodal_fallback_model=s.multimodal_fallback_model,
        search_provider=s.search_provider,
        search_fallback_provider=s.search_fallback_provider,
        model_search_helper=s.model_search_helper,
        local_asr_api_base_url=s.local_asr_api_base_url,
        local_asr_model_name=s.local_asr_model_name,
        local_asr_display_name=s.local_asr_display_name,
        transcription_chunking_enabled=s.transcription_chunking_enabled,
        transcription_chunk_threshold_sec=s.transcription_chunk_threshold_sec,
        transcription_chunk_size_sec=s.transcription_chunk_size_sec,
        transcription_chunk_min_sec=s.transcription_chunk_min_sec,
        transcription_chunk_overlap_sec=s.transcription_chunk_overlap_sec,
        transcription_chunk_request_timeout_sec=s.transcription_chunk_request_timeout_sec,
        transcription_chunk_request_max_retries=s.transcription_chunk_request_max_retries,
        transcription_chunk_request_retry_backoff_sec=s.transcription_chunk_request_retry_backoff_sec,
        avatar_provider=s.avatar_provider,
        avatar_api_key_set=bool(s.avatar_api_key),
        avatar_presenter_id=s.avatar_presenter_id,
        avatar_layout_template=s.avatar_layout_template,
        avatar_safe_margin=s.avatar_safe_margin,
        avatar_overlay_scale=s.avatar_overlay_scale,
        voice_provider=s.voice_provider,
        voice_clone_api_key_set=bool(s.voice_clone_api_key),
        voice_clone_voice_id=s.voice_clone_voice_id,
        director_rewrite_strength=s.director_rewrite_strength,
        publication_browser_agent_base_url=s.publication_browser_agent_base_url,
        publication_browser_agent_auth_token_set=bool(s.publication_browser_agent_auth_token),
        publication_worker_poll_interval_sec=s.publication_worker_poll_interval_sec,
        publication_worker_batch_limit=s.publication_worker_batch_limit,
        publication_attempt_lease_sec=s.publication_attempt_lease_sec,
        publication_browser_agent_timeout_sec=s.publication_browser_agent_timeout_sec,
        ollama_api_key_set=bool(s.ollama_api_key),
        openai_api_key_set=bool(s.openai_api_key),
        anthropic_api_key_set=bool(s.anthropic_api_key),
        minimax_api_key_set=bool(s.minimax_api_key),
        minimax_coding_plan_api_key_set=bool(s.minimax_coding_plan_api_key),
        max_upload_size_mb=s.max_upload_size_mb,
        max_video_duration_sec=s.max_video_duration_sec,
        ffmpeg_timeout_sec=s.ffmpeg_timeout_sec,
        transcribe_runtime_timeout_sec=s.transcribe_runtime_timeout_sec,
        allowed_extensions=s.allowed_extensions,
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


@router.get("/environment", response_model=RuntimeEnvironmentOut)
def get_runtime_environment():
    s = get_settings()
    return RuntimeEnvironmentOut(
        openai_base_url=s.openai_base_url,
        openai_auth_mode=s.openai_auth_mode,
        openai_api_key_helper=s.openai_api_key_helper,
        anthropic_base_url=s.anthropic_base_url,
        anthropic_auth_mode=s.anthropic_auth_mode,
        anthropic_api_key_helper=s.anthropic_api_key_helper,
        minimax_base_url=s.minimax_base_url,
        minimax_api_host=s.minimax_api_host,
        ollama_base_url=s.ollama_base_url,
        avatar_api_base_url=s.avatar_api_base_url,
        avatar_training_api_base_url=s.avatar_training_api_base_url,
        voice_clone_api_base_url=s.voice_clone_api_base_url,
        publication_browser_agent_base_url=s.publication_browser_agent_base_url,
        output_dir=s.output_dir,
    )


@router.get("/service-status", response_model=ProviderServiceStatusOut)
def get_service_status():
    return ProviderServiceStatusOut(**build_service_status_payload())


@router.get("/provider-check", response_model=ProviderCheckOut)
def get_provider_check(provider: str):
    try:
        return ProviderCheckOut(**build_provider_check_payload(provider=provider))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/model-catalog", response_model=ModelCatalogOut)
def get_model_catalog(provider: str, kind: str, refresh: int = 0):
    return ModelCatalogOut(**get_model_catalog_payload(provider=provider, kind=kind, refresh=bool(refresh)))


@router.get("/options", response_model=ConfigOptionsOut)
def get_config_options():
    transcription_models = {
        DEFAULT_TRANSCRIPTION_PROVIDER: list(TRANSCRIPTION_MODEL_OPTIONS[DEFAULT_TRANSCRIPTION_PROVIDER]),
    }
    return ConfigOptionsOut(
        job_languages=JOB_LANGUAGE_OPTIONS,
        workflow_templates=build_workflow_template_options(),
        workflow_modes=build_workflow_mode_options(),
        enhancement_modes=build_enhancement_mode_options(),
        transcription_dialects=build_transcription_dialect_options(),
        avatar_providers=build_avatar_provider_options(),
        voice_providers=build_voice_provider_options(),
        creative_mode_catalog=build_mode_catalog(),
        transcription_models=transcription_models,
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
    forbidden_fields = sorted(key for key in updates if key in ENV_MANAGED_SETTINGS)
    if forbidden_fields:
        raise HTTPException(
            status_code=400,
            detail=(
                "These settings are managed by startup env only: "
                f"{', '.join(forbidden_fields)}"
            ),
        )
    if "transcription_provider" in updates:
        provider = canonicalize_transcription_provider_name(updates["transcription_provider"])
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
    if "transcription_alignment_mode" in updates:
        alignment_mode = str(updates["transcription_alignment_mode"] or "").strip().lower()
        if alignment_mode not in {"auto", "provider_only", "synthetic"}:
            raise HTTPException(
                status_code=400,
                detail="transcription_alignment_mode must be auto, provider_only, or synthetic",
            )
        updates["transcription_alignment_mode"] = alignment_mode
    if "transcription_alignment_min_word_coverage" in updates:
        updates["transcription_alignment_min_word_coverage"] = max(
            0.0,
            min(1.0, float(updates["transcription_alignment_min_word_coverage"])),
        )
    if "llm_mode" in updates:
        llm_mode = str(updates["llm_mode"] or "").strip().lower()
        if llm_mode not in {"performance", "local"}:
            raise HTTPException(status_code=400, detail="llm_mode must be performance or local")
        updates["llm_mode"] = llm_mode
    if "llm_routing_mode" in updates:
        routing_mode = str(updates["llm_routing_mode"] or "").strip().lower()
        if routing_mode not in {"bundled", "hybrid_performance"}:
            raise HTTPException(status_code=400, detail="llm_routing_mode must be bundled or hybrid_performance")
        updates["llm_routing_mode"] = routing_mode
    for key in ("reasoning_provider", "backup_reasoning_provider", "multimodal_fallback_provider"):
        if key in updates:
            provider_name = str(updates[key] or "").strip().lower()
            if provider_name not in HYBRID_REASONING_PROVIDER_VALUES:
                raise HTTPException(
                    status_code=400,
                    detail=f"{key} must be one of: {', '.join(HYBRID_REASONING_PROVIDER_VALUES)}",
                )
            updates[key] = provider_name
    if "llm_backup_enabled" in updates:
        updates["llm_backup_enabled"] = bool(updates["llm_backup_enabled"])
    for key in ("reasoning_model", "backup_reasoning_model", "backup_vision_model", "backup_model_search_helper"):
        if key in updates:
            updates[key] = str(updates[key] or "").strip()
    for key in ("reasoning_effort", "backup_reasoning_effort"):
        if key in updates:
            effort = str(updates[key] or "").strip().lower()
            if effort not in {"minimal", "low", "medium", "high"}:
                raise HTTPException(status_code=400, detail=f"{key} must be minimal, low, medium, or high")
            updates[key] = effort
    for key in ("backup_search_provider",):
        if key in updates:
            provider_name = str(updates[key] or "").strip().lower()
            if provider_name not in SEARCH_PROVIDER_VALUES:
                raise HTTPException(
                    status_code=400,
                    detail=f"{key} must be one of: {', '.join(SEARCH_PROVIDER_VALUES)}",
                )
            updates[key] = provider_name
    for key in ("search_fallback_provider", "backup_search_fallback_provider"):
        if key in updates:
            provider_name = str(updates[key] or "").strip().lower()
            if provider_name not in SEARCH_FALLBACK_PROVIDER_VALUES:
                raise HTTPException(
                    status_code=400,
                    detail=f"{key} must be one of: {', '.join(SEARCH_FALLBACK_PROVIDER_VALUES)}",
                )
            updates[key] = provider_name
    for key in ("hybrid_analysis_provider", "hybrid_copy_provider"):
        if key in updates:
            provider_name = str(updates[key] or "").strip().lower()
            if provider_name not in HYBRID_REASONING_PROVIDER_VALUES:
                raise HTTPException(
                    status_code=400,
                    detail=f"{key} must be one of: {', '.join(HYBRID_REASONING_PROVIDER_VALUES)}",
                )
            updates[key] = provider_name
    for key in ("hybrid_analysis_model", "hybrid_copy_model"):
        if key in updates:
            updates[key] = str(updates[key] or "").strip()
    for key in ("hybrid_analysis_search_mode", "hybrid_copy_search_mode"):
        if key in updates:
            search_mode = str(updates[key] or "").strip().lower()
            if search_mode not in {"off", "entity_gated", "follow_provider"}:
                raise HTTPException(status_code=400, detail=f"{key} must be off, entity_gated, or follow_provider")
            updates[key] = search_mode
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
    if "publication_browser_agent_base_url" in updates:
        browser_agent_base_url = str(updates["publication_browser_agent_base_url"]).strip().rstrip("/")
        if not browser_agent_base_url:
            raise HTTPException(status_code=400, detail="publication_browser_agent_base_url cannot be empty")
        updates["publication_browser_agent_base_url"] = browser_agent_base_url
    if "telegram_agent_claude_command" in updates:
        updates["telegram_agent_claude_command"] = str(updates["telegram_agent_claude_command"] or "").strip() or "claude"
    if "telegram_agent_claude_model" in updates:
        updates["telegram_agent_claude_model"] = str(updates["telegram_agent_claude_model"] or "").strip()
    if "telegram_agent_codex_command" in updates:
        updates["telegram_agent_codex_command"] = str(updates["telegram_agent_codex_command"] or "").strip() or "codex"
    if "telegram_agent_codex_model" in updates:
        updates["telegram_agent_codex_model"] = str(updates["telegram_agent_codex_model"] or "").strip()
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
        if backend and backend not in CODING_BACKEND_VALUES:
            raise HTTPException(
                status_code=400,
                detail=f"acp_bridge_backend must be auto or one of: {', '.join(CODING_BACKEND_VALUES)}",
            )
        updates["acp_bridge_backend"] = backend
    if "acp_bridge_fallback_backend" in updates:
        fallback_backend = str(updates["acp_bridge_fallback_backend"] or "").strip().lower()
        if fallback_backend and fallback_backend not in CODING_BACKEND_VALUES:
            raise HTTPException(
                status_code=400,
                detail=f"acp_bridge_fallback_backend must be auto or one of: {', '.join(CODING_BACKEND_VALUES)}",
            )
        updates["acp_bridge_fallback_backend"] = fallback_backend
    if "acp_bridge_claude_model" in updates:
        updates["acp_bridge_claude_model"] = str(updates["acp_bridge_claude_model"] or "").strip()
    if "acp_bridge_codex_command" in updates:
        updates["acp_bridge_codex_command"] = str(updates["acp_bridge_codex_command"] or "").strip() or "codex"
    if "acp_bridge_codex_model" in updates:
        updates["acp_bridge_codex_model"] = str(updates["acp_bridge_codex_model"] or "").strip()
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
    if "publication_worker_poll_interval_sec" in updates:
        updates["publication_worker_poll_interval_sec"] = max(
            5,
            min(3600, int(updates["publication_worker_poll_interval_sec"])),
        )
    if "publication_worker_batch_limit" in updates:
        updates["publication_worker_batch_limit"] = max(1, min(100, int(updates["publication_worker_batch_limit"])))
    if "publication_attempt_lease_sec" in updates:
        updates["publication_attempt_lease_sec"] = max(30, min(7200, int(updates["publication_attempt_lease_sec"])))
    if "publication_browser_agent_timeout_sec" in updates:
        updates["publication_browser_agent_timeout_sec"] = max(
            5,
            min(600, int(updates["publication_browser_agent_timeout_sec"])),
        )
    if "transcribe_runtime_timeout_sec" in updates:
        updates["transcribe_runtime_timeout_sec"] = max(60, min(7200, int(updates["transcribe_runtime_timeout_sec"])))
    if "transcription_chunk_threshold_sec" in updates:
        updates["transcription_chunk_threshold_sec"] = max(
            60,
            min(21600, int(updates["transcription_chunk_threshold_sec"])),
        )
    if "transcription_chunk_size_sec" in updates:
        updates["transcription_chunk_size_sec"] = max(
            15,
            min(1800, int(updates["transcription_chunk_size_sec"])),
        )
    resolved_chunk_size_sec = int(
        updates.get(
            "transcription_chunk_size_sec",
            overrides.get("transcription_chunk_size_sec", get_settings().transcription_chunk_size_sec),
        )
    )
    if "transcription_chunk_min_sec" in updates:
        updates["transcription_chunk_min_sec"] = max(
            5,
            min(resolved_chunk_size_sec, int(updates["transcription_chunk_min_sec"])),
        )
    resolved_chunk_min_sec = int(
        updates.get(
            "transcription_chunk_min_sec",
            overrides.get("transcription_chunk_min_sec", get_settings().transcription_chunk_min_sec),
        )
    )
    if "transcription_chunk_overlap_sec" in updates:
        updates["transcription_chunk_overlap_sec"] = max(
            0.0,
            min(
                max(0.0, float(resolved_chunk_size_sec - resolved_chunk_min_sec)),
                float(updates["transcription_chunk_overlap_sec"]),
            ),
        )
    if "transcription_chunk_request_timeout_sec" in updates:
        updates["transcription_chunk_request_timeout_sec"] = max(
            30,
            min(7200, int(updates["transcription_chunk_request_timeout_sec"])),
        )
    if "transcription_chunk_request_max_retries" in updates:
        updates["transcription_chunk_request_max_retries"] = max(
            0,
            min(8, int(updates["transcription_chunk_request_max_retries"])),
        )
    if "transcription_chunk_request_retry_backoff_sec" in updates:
        updates["transcription_chunk_request_retry_backoff_sec"] = max(
            0.5,
            min(300.0, float(updates["transcription_chunk_request_retry_backoff_sec"])),
        )
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
