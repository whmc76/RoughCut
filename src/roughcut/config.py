from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
import shutil
import sys
from typing import Any

from pydantic import AliasChoices, Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from roughcut.naming import (
    AVATAR_PROVIDER_VALUES,
    CODING_BACKEND_PROVIDER_MAP,
    CODING_BACKEND_VALUES,
    DEFAULT_CODING_BACKEND_MODELS,
    MULTIMODAL_PROVIDER_VALUES,
    REASONING_PROVIDER_VALUES,
    SEARCH_FALLBACK_PROVIDER_VALUES,
    SEARCH_PROVIDER_VALUES,
    TRANSCRIPTION_PROVIDER_ALIASES,
    TRANSCRIPTION_PROVIDER_VALUES,
    VOICE_PROVIDER_VALUES,
    normalize_auth_mode,
)
from roughcut.providers.zhipu_compat import (
    DEFAULT_ZHIPU_BASE_URL,
    DEFAULT_ZHIPU_CODING_BASE_URL,
    DEFAULT_ZHIPU_MCP_HTTP_BASE_URL,
)
from roughcut.speech.dialects import DEFAULT_TRANSCRIPTION_DIALECT, normalize_transcription_dialect

DEFAULT_JOB_WORKFLOW_MODE = "standard_edit"
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = Path(
    os.getenv("ROUGHCUT_OUTPUT_ROOT", str((DEFAULT_PROJECT_ROOT / "data" / "runtime").as_posix()))
).expanduser()
DEFAULT_PACKAGING_ASSET_ROOT = Path(
    os.getenv(
        "ROUGHCUT_PACKAGING_ASSET_DIR",
        os.getenv("PACKAGING_ASSET_DIR", str((DEFAULT_PROJECT_ROOT / "assets" / "packaging").as_posix())),
    )
).expanduser()
DEFAULT_TEST_OUTPUT_ROOT = Path(
    os.getenv("ROUGHCUT_TEST_OUTPUT_ROOT", str((DEFAULT_OUTPUT_ROOT / "tests").as_posix()))
).expanduser()
DEFAULT_HEYGEM_SHARED_ROOT = Path(
    os.getenv(
        "HEYGEM_SHARED_ROOT",
        os.getenv("HEYGEM_DATA_DIR", str((DEFAULT_OUTPUT_ROOT / "heygem-shared").as_posix())),
    )
).expanduser()
DEFAULT_HEYGEM_VOICE_ROOT = Path(
    os.getenv(
        "HEYGEM_VOICE_ROOT",
        str((DEFAULT_HEYGEM_SHARED_ROOT / "voice" / "data").as_posix()),
    )
).expanduser()
SECRET_SETTINGS: tuple[str, ...] = (
    "openai_api_key",
    "anthropic_api_key",
    "minimax_api_key",
    "minimax_coding_plan_api_key",
    "zhipu_api_key",
    "ollama_api_key",
    "avatar_api_key",
    "voice_clone_api_key",
    "publication_browser_agent_auth_token",
    "telegram_bot_token",
)
ENV_MANAGED_SETTINGS: tuple[str, ...] = (
    "openai_base_url",
    "openai_auth_mode",
    "openai_api_key_helper",
    "anthropic_base_url",
    "anthropic_auth_mode",
    "anthropic_api_key_helper",
    "minimax_base_url",
    "minimax_api_host",
    "zhipu_base_url",
    "zhipu_coding_base_url",
    "zhipu_mcp_http_base_url",
    "zhipu_auth_mode",
    "zhipu_api_key_helper",
    "ollama_base_url",
    "avatar_api_base_url",
    "avatar_training_api_base_url",
    "voice_clone_api_base_url",
    "output_dir",
)
ENV_EXPLICIT_OVERRIDE_SETTINGS: tuple[str, ...] = ENV_MANAGED_SETTINGS + (
    "transcription_provider",
    "transcription_model",
    "transcription_dialect",
    "local_asr_api_base_url",
    "local_asr_model_name",
    "local_asr_display_name",
    "telegram_agent_state_dir",
    "telegram_remote_review_enabled",
    "telegram_bot_api_base_url",
    "telegram_bot_token",
    "telegram_bot_chat_id",
    "publication_browser_agent_auth_token",
    "publication_worker_poll_interval_sec",
    "publication_worker_batch_limit",
    "publication_attempt_lease_sec",
    "publication_browser_agent_timeout_sec",
    "publication_browser_cdp_url",
    "publication_x_username",
)
TRANSCRIPTION_PROVIDER_PRIORITY: tuple[str, ...] = TRANSCRIPTION_PROVIDER_VALUES
TRANSCRIPTION_MODEL_OPTIONS: dict[str, list[str]] = {
    "funasr": [
        "sensevoice-small",
    ],
    "faster_whisper": [
        "large-v3",
        "large-v3-turbo",
        "distil-large-v3",
        "base",
        "small",
        "medium",
    ],
    "openai": [
        "gpt-4o-transcribe",
        "gpt-4o-mini-transcribe",
    ],
    "local_http_asr": [
        "qwen3-asr-1.7b-forced-aligner",
        "fun-asr-nano-2512",
        "faster-whisper-large-v3-beam5-nohot",
    ],
}
MULTIMODAL_FALLBACK_PROVIDER_VALUES: tuple[str, ...] = MULTIMODAL_PROVIDER_VALUES
HYBRID_REASONING_PROVIDER_VALUES: tuple[str, ...] = REASONING_PROVIDER_VALUES
LLM_ROUTING_MODE_VALUES: tuple[str, ...] = ("bundled", "hybrid_performance")
HYBRID_SEARCH_MODE_VALUES: tuple[str, ...] = ("off", "entity_gated", "follow_provider")
REASONING_EFFORT_VALUES: tuple[str, ...] = ("minimal", "low", "medium", "high", "xhigh", "max", "ultracode")
DEFAULT_MINIMAX_REASONING_MODEL = "MiniMax-M3"
DEFAULT_SEARCH_PROVIDER = "searxng"
DEFAULT_SEARCH_FALLBACK_PROVIDER = "searxng"
DEFAULT_BACKUP_SEARCH_PROVIDER = "searxng"
DEFAULT_BACKUP_SEARCH_FALLBACK_PROVIDER = "searxng"
DEFAULT_MODEL_SEARCH_HELPER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "codex_model_search_helper.py"
DEFAULT_ZHIPU_REASONING_MODEL = "glm-5.2"
DEFAULT_ZHIPU_VISION_MODEL = "glm-4.6v-flash"
DEFAULT_ZHIPU_SEARCH_ENGINE = "search_pro"
DEFAULT_REASONING_PROVIDER = "zhipu"
DEFAULT_REASONING_MODEL = DEFAULT_ZHIPU_REASONING_MODEL
DEFAULT_BACKUP_REASONING_PROVIDER = "zhipu"
DEFAULT_BACKUP_REASONING_MODEL = DEFAULT_ZHIPU_REASONING_MODEL
DEFAULT_BACKUP_VISION_MODEL = DEFAULT_ZHIPU_VISION_MODEL
DEFAULT_HYBRID_ANALYSIS_PROVIDER = "zhipu"
DEFAULT_HYBRID_ANALYSIS_MODEL = DEFAULT_ZHIPU_REASONING_MODEL
DEFAULT_HYBRID_COPY_PROVIDER = "zhipu"
DEFAULT_HYBRID_COPY_MODEL = DEFAULT_ZHIPU_REASONING_MODEL
DEFAULT_MULTIMODAL_FALLBACK_PROVIDER = "zhipu"
DEFAULT_MULTIMODAL_FALLBACK_MODEL = DEFAULT_ZHIPU_VISION_MODEL
MINIMAX_REASONING_MODEL_ALIASES: dict[str, str] = {
    "minimax-m3": "MiniMax-M3",
    "minimax-m2.7": "MiniMax-M3",
    "minimax-m2.7-highspeed": "MiniMax-M3",
}
ZHIPU_REASONING_MODEL_ALIASES: dict[str, str] = {
    "glm-5.2[1m]": "glm-5.2",
}


def build_default_model_search_helper() -> str:
    helper_path = DEFAULT_MODEL_SEARCH_HELPER_PATH
    if not helper_path.exists():
        return ""
    python_executable = str(Path(sys.executable).resolve() if sys.executable else "python")
    return f'"{python_executable}" "{helper_path.resolve()}"'


def resolve_heygem_shared_root(*, ensure_exists: bool = True) -> Path:
    """Resolve the host-accessible HeyGem shared directory.

    Prefer an existing `HEYGEM_SHARED_ROOT` first. If that path is a container-only
    mount like `/code/data` from a host process, fall back to `HEYGEM_SHARED_HOST_DIR`
    before creating any directories.
    """

    raw_root = str(os.getenv("HEYGEM_SHARED_ROOT") or "").strip()
    raw_host_dir = str(os.getenv("HEYGEM_SHARED_HOST_DIR") or "").strip()

    candidates: list[Path] = []
    if raw_root:
        candidates.append(Path(raw_root).expanduser())
    if raw_host_dir:
        host_path = Path(raw_host_dir).expanduser()
        if all(host_path != candidate for candidate in candidates):
            candidates.append(host_path)

    for candidate in candidates:
        if candidate.exists():
            if ensure_exists:
                (candidate / "inputs" / "audio").mkdir(parents=True, exist_ok=True)
                (candidate / "inputs" / "video").mkdir(parents=True, exist_ok=True)
                (candidate / "temp").mkdir(parents=True, exist_ok=True)
                (candidate / "result").mkdir(parents=True, exist_ok=True)
            return candidate

    if raw_host_dir:
        resolved = Path(raw_host_dir).expanduser()
    elif raw_root:
        resolved = Path(raw_root).expanduser()
    else:
        resolved = DEFAULT_HEYGEM_SHARED_ROOT

    if ensure_exists:
        (resolved / "inputs" / "audio").mkdir(parents=True, exist_ok=True)
        (resolved / "inputs" / "video").mkdir(parents=True, exist_ok=True)
        (resolved / "temp").mkdir(parents=True, exist_ok=True)
        (resolved / "result").mkdir(parents=True, exist_ok=True)
    return resolved
DEFAULT_TRANSCRIPTION_PROVIDER = "local_http_asr"
DEFAULT_TRANSCRIPTION_MODELS: dict[str, str] = {
    "funasr": "sensevoice-small",
    "faster_whisper": "large-v3",
    "openai": "gpt-4o-transcribe",
    "local_http_asr": "qwen3-asr-1.7b-forced-aligner",
}
LEGACY_LOCAL_HTTP_ASR_MODELS: tuple[str, ...] = (
    "local-asr-current",
    "vibevoice-asr-int8",
    "moss-audio-8b-instruct",
)
LEGACY_LOCAL_HTTP_ASR_URLS: tuple[str, ...] = (
    "http://127.0.0.1:6001",
    "http://localhost:6001",
    "http://127.0.0.1:30080",
    "http://localhost:30080",
)
AVATAR_PROVIDER_OPTIONS: tuple[str, ...] = AVATAR_PROVIDER_VALUES
VOICE_PROVIDER_OPTIONS: tuple[str, ...] = VOICE_PROVIDER_VALUES
CONTENT_UNDERSTANDING_CAPABILITY_SLOTS: tuple[str, ...] = (
    "asr",
    "visual_understanding",
    "ocr",
    "hybrid_retrieval",
    "reasoning",
    "verification",
)
GLOBAL_MODEL_ROUTE_SETTINGS: tuple[str, ...] = (
    "transcription_provider",
    "transcription_model",
    "local_asr_api_base_url",
    "local_asr_model_name",
    "local_asr_display_name",
    "llm_mode",
    "llm_routing_mode",
    "reasoning_provider",
    "reasoning_model",
    "reasoning_effort",
    "llm_backup_enabled",
    "backup_reasoning_provider",
    "backup_reasoning_model",
    "backup_reasoning_effort",
    "backup_vision_model",
    "backup_search_provider",
    "backup_search_fallback_provider",
    "backup_model_search_helper",
    "local_reasoning_model",
    "local_vision_model",
    "hybrid_analysis_provider",
    "hybrid_analysis_model",
    "hybrid_analysis_effort",
    "hybrid_analysis_search_mode",
    "hybrid_copy_provider",
    "hybrid_copy_model",
    "hybrid_copy_effort",
    "hybrid_copy_search_mode",
    "multimodal_fallback_provider",
    "multimodal_fallback_model",
    "search_provider",
    "search_fallback_provider",
    "model_search_helper",
    "avatar_provider",
    "voice_provider",
    "ocr_provider",
    "intelligent_copy_cover_image_generation_enabled",
    "intelligent_copy_cover_image_backend",
    "intelligent_copy_cover_image_model",
    "intelligent_copy_cover_image_quality",
    "intelligent_copy_cover_image_timeout_sec",
    "intelligent_copy_cover_codex_runner_model",
    "intelligent_copy_cover_codex_runner_effort",
)
PROFILE_BINDABLE_SETTINGS: tuple[str, ...] = (
    "transcription_dialect",
    "transcription_alignment_mode",
    "transcription_alignment_min_word_coverage",
    "transcription_chunking_enabled",
    "transcription_chunk_threshold_sec",
    "transcription_chunk_size_sec",
    "transcription_chunk_min_sec",
    "transcription_chunk_overlap_sec",
    "transcription_chunk_request_timeout_sec",
    "transcription_chunk_request_max_retries",
    "transcription_chunk_request_retry_backoff_sec",
    "avatar_presenter_id",
    "avatar_layout_template",
    "avatar_safe_margin",
    "avatar_overlay_scale",
    "voice_clone_voice_id",
    "director_rewrite_strength",
    "default_job_workflow_mode",
    "default_job_enhancement_modes",
    "fact_check_enabled",
    "auto_confirm_content_profile",
    "content_profile_review_threshold",
    "content_profile_auto_review_min_accuracy",
    "content_profile_auto_review_min_samples",
    "auto_accept_glossary_corrections",
    "glossary_correction_review_threshold",
    "auto_select_cover_variant",
    "cover_selection_review_gap",
    "packaging_selection_review_gap",
    "packaging_selection_min_score",
    "streamlined_asr_pipeline_enabled",
    "subtitle_filler_cleanup_enabled",
    "render_subtitle_alignment_policy",
    "quality_auto_rerun_enabled",
    "quality_auto_rerun_below_score",
    "quality_auto_rerun_max_attempts",
    "ocr_enabled",
    "entity_graph_enabled",
    "asr_evidence_enabled",
    "research_verifier_enabled",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "roughcut.ports.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://roughcut:roughcut@localhost:5432/roughcut"
    db_pool_size: int = Field(default=8, ge=1)
    db_max_overflow: int = Field(default=8, ge=0)
    db_pool_timeout_sec: float = Field(default=30.0, gt=0)
    db_pool_recycle_sec: int = Field(default=1800, ge=0)
    db_use_null_pool: bool = False

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Storage
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key_id: str = "minioadmin"
    s3_secret_access_key: str = "minioadmin"
    s3_bucket_name: str = "roughcut"
    s3_region: str = "us-east-1"
    job_storage_dir: str = str((DEFAULT_OUTPUT_ROOT / "jobs").as_posix())
    packaging_asset_dir: str = Field(
        default=str(DEFAULT_PACKAGING_ASSET_ROOT.as_posix()),
        validation_alias=AliasChoices("PACKAGING_ASSET_DIR", "ROUGHCUT_PACKAGING_ASSET_DIR"),
    )
    packaging_asset_storage_backend: str = Field(
        default="local",
        validation_alias=AliasChoices("PACKAGING_ASSET_STORAGE_BACKEND", "ROUGHCUT_PACKAGING_ASSET_STORAGE_BACKEND"),
    )
    cleanup_job_storage_on_terminal: bool = True
    cleanup_render_debug_on_terminal: bool = True
    cleanup_heygem_temp_on_terminal: bool = True

    # Transcription
    transcription_provider: str = DEFAULT_TRANSCRIPTION_PROVIDER  # local_http_asr | openai | funasr | faster_whisper
    transcription_model: str = DEFAULT_TRANSCRIPTION_MODELS[DEFAULT_TRANSCRIPTION_PROVIDER]
    transcription_dialect: str = DEFAULT_TRANSCRIPTION_DIALECT
    transcription_alignment_mode: str = "auto"  # auto | provider_only | synthetic
    transcription_alignment_min_word_coverage: float = 0.72
    local_asr_api_base_url: str = "http://127.0.0.1:30230"
    local_asr_model_name: str = "qwen3-asr-1.7b-forced-aligner"
    local_asr_display_name: str = "Qwen3-ASR 1.7B + ForcedAligner"
    local_asr_health_path: str = "/health"
    local_asr_transcribe_path: str = "/transcribe"
    local_asr_hotwords_field: str = "hotwords"
    local_asr_hotwords_enabled: bool = True
    local_asr_beam_size: int = 5
    local_asr_best_of: int = 5
    local_asr_condition_on_previous_text: bool = False
    local_asr_vad_filter: bool = True
    local_asr_max_new_tokens: int = 256
    transcription_chunking_enabled: bool = True
    transcription_chunk_threshold_sec: int = 300
    transcription_chunk_size_sec: int = 300
    transcription_chunk_min_sec: int = 60
    transcription_chunk_overlap_sec: float = 0.0
    transcription_chunk_request_timeout_sec: int = 900
    transcription_chunk_request_max_retries: int = 2
    transcription_chunk_request_retry_backoff_sec: float = 5.0
    watch_auto_scan_interval_sec: int = 45
    watch_auto_settle_seconds: int = 45
    watch_auto_merge_enabled: bool = True
    watch_auto_merge_min_score: float = 0.72
    watch_auto_enqueue_enabled: bool = True
    watch_auto_duty_enabled: bool = True
    watch_auto_max_active_jobs: int = 2
    watch_auto_max_jobs_per_root: int = 1
    gpu_retry_enabled: bool = True
    gpu_retry_base_delay_sec: int = 90
    gpu_retry_max_delay_sec: int = 900
    gpu_busy_utilization_threshold: int = 92
    gpu_busy_memory_threshold: float = 0.92
    step_heartbeat_interval_sec: int = 20
    startup_recovery_enabled: bool = True
    step_stale_recovery_enabled: bool = True
    step_lost_task_recovery_enabled: bool = True
    step_lost_task_grace_sec: int = 120
    step_dispatch_lost_task_grace_sec: int = 300
    step_recovery_inspect_timeout_sec: float = 1.0
    step_stale_timeout_sec: int = 900
    step_dispatch_stale_timeout_sec: int = 3600
    transcribe_runtime_timeout_sec: int = 900
    edit_plan_scene_detection_timeout_sec: int = 180
    edit_plan_scene_detection_frame_skip: int = 2
    manual_editor_preview_runtime_timeout_sec: int = 300
    render_dispatch_concurrency: int = 1
    render_step_stale_timeout_sec: int = 5400
    render_step_prepackaging_stale_timeout_sec: int = 1500
    render_step_packaging_stale_timeout_sec: int = 2400
    avatar_render_no_progress_timeout_sec: int = 0
    runtime_preflight_docker_enabled: bool = False
    docker_gpu_guard_enabled: bool = True
    docker_gpu_guard_idle_timeout_sec: int = 900
    docker_gpu_guard_ready_timeout_sec: int = 240
    heygem_docker_guard_enabled: bool = True
    heygem_docker_compose_file: str = str((DEFAULT_PROJECT_ROOT.parent / "heygem" / "docker-compose.yml").as_posix())
    heygem_docker_env_file: str = str((DEFAULT_PROJECT_ROOT.parent / "heygem" / ".env").as_posix())
    heygem_docker_services: str = "heygem"
    heygem_docker_idle_timeout_sec: int = 10
    indextts2_docker_guard_enabled: bool = False
    indextts2_docker_compose_file: str = str((DEFAULT_PROJECT_ROOT.parent / "indextts2-service" / "docker-compose.yml").as_posix())
    indextts2_docker_env_file: str = str((DEFAULT_PROJECT_ROOT.parent / "indextts2-service" / ".env").as_posix())
    indextts2_docker_services: str = "indextts2"
    indextts2_docker_idle_timeout_sec: int = 10
    local_asr_docker_guard_enabled: bool = True
    local_asr_docker_compose_file: str = str((DEFAULT_PROJECT_ROOT / "docker-compose.asr-matrix.yml").as_posix())
    local_asr_docker_env_file: str = ""
    local_asr_docker_services: str = "qwen3-asr"
    local_asr_docker_idle_timeout_sec: int = 10
    cosyvoice3_tts_api_base_url: str = "http://127.0.0.1:30180"
    cosyvoice3_tts_health_path: str = "/health"
    cosyvoice3_tts_sample_rate: int = 24000
    cosyvoice3_tts_docker_guard_enabled: bool = True
    cosyvoice3_tts_docker_compose_file: str = str((DEFAULT_PROJECT_ROOT / "docker-compose.cosyvoice3.yml").as_posix())
    cosyvoice3_tts_docker_env_file: str = ""
    cosyvoice3_tts_docker_services: str = "cosyvoice3-tts"
    cosyvoice3_tts_docker_idle_timeout_sec: int = 10
    moss_tts_local_api_base_url: str = "http://127.0.0.1:30191"
    moss_tts_local_health_path: str = "/health"
    moss_tts_local_sample_rate: int = 24000
    moss_tts_local_docker_guard_enabled: bool = True
    moss_tts_local_docker_compose_file: str = str((DEFAULT_PROJECT_ROOT / "docker-compose.moss-tts-local.yml").as_posix())
    moss_tts_local_docker_env_file: str = ""
    moss_tts_local_docker_services: str = "moss-tts-local"
    moss_tts_local_docker_idle_timeout_sec: int = 10
    moss_tts_local_docker_ready_timeout_sec: int = 900
    funasr_auto_unload_enabled: bool = True
    funasr_idle_unload_sec: int = 600

    # Reasoning
    llm_mode: str = "performance"  # performance | local
    llm_routing_mode: str = "bundled"  # bundled | hybrid_performance
    reasoning_provider: str = DEFAULT_REASONING_PROVIDER  # openai | anthropic | minimax | zhipu | ollama
    reasoning_model: str = DEFAULT_REASONING_MODEL
    reasoning_effort: str = "low"
    llm_backup_enabled: bool = True
    backup_reasoning_provider: str = DEFAULT_BACKUP_REASONING_PROVIDER
    backup_reasoning_model: str = DEFAULT_BACKUP_REASONING_MODEL
    backup_reasoning_effort: str = "low"
    backup_vision_model: str = DEFAULT_BACKUP_VISION_MODEL
    backup_search_provider: str = DEFAULT_BACKUP_SEARCH_PROVIDER
    backup_search_fallback_provider: str = DEFAULT_BACKUP_SEARCH_FALLBACK_PROVIDER
    backup_model_search_helper: str = ""
    local_reasoning_model: str = "qwen3.5:9b"
    local_vision_model: str = ""
    hybrid_analysis_provider: str = DEFAULT_HYBRID_ANALYSIS_PROVIDER
    hybrid_analysis_model: str = DEFAULT_HYBRID_ANALYSIS_MODEL
    hybrid_analysis_effort: str = "low"
    hybrid_analysis_search_mode: str = "entity_gated"  # off | entity_gated | follow_provider
    hybrid_copy_provider: str = DEFAULT_HYBRID_COPY_PROVIDER
    hybrid_copy_model: str = DEFAULT_HYBRID_COPY_MODEL
    hybrid_copy_effort: str = "max"
    hybrid_copy_search_mode: str = "follow_provider"  # off | entity_gated | follow_provider
    multimodal_fallback_provider: str = DEFAULT_MULTIMODAL_FALLBACK_PROVIDER
    multimodal_fallback_model: str = DEFAULT_MULTIMODAL_FALLBACK_MODEL

    # Search (Phase 2)
    search_provider: str = DEFAULT_SEARCH_PROVIDER  # auto | openai | anthropic | minimax | zhipu | ollama | model | searxng
    search_fallback_provider: str = DEFAULT_SEARCH_FALLBACK_PROVIDER  # openai | anthropic | minimax | zhipu | ollama | model | searxng
    model_search_helper: str = ""
    searxng_url: str = "http://localhost:8080"

    # API Keys
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_auth_mode: str = "api_key"  # api_key | helper
    openai_api_key_helper: str = ""
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_auth_mode: str = "api_key"  # api_key | helper
    anthropic_api_key_helper: str = ""
    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimaxi.com/v1"
    minimax_api_host: str = "https://api.minimaxi.com"
    minimax_coding_plan_api_key: str = ""
    zhipu_api_key: str = ""
    zhipu_base_url: str = DEFAULT_ZHIPU_BASE_URL
    zhipu_coding_base_url: str = DEFAULT_ZHIPU_CODING_BASE_URL
    zhipu_mcp_http_base_url: str = DEFAULT_ZHIPU_MCP_HTTP_BASE_URL
    zhipu_auth_mode: str = "api_key"  # api_key | helper
    zhipu_api_key_helper: str = ""
    zhipu_search_engine: str = DEFAULT_ZHIPU_SEARCH_ENGINE
    ollama_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # Avatar / Digital Human
    avatar_provider: str = "heygem"
    avatar_api_base_url: str = "http://127.0.0.1:49202"
    avatar_training_api_base_url: str = "http://127.0.0.1:49204"
    avatar_api_key: str = ""
    avatar_presenter_id: str = ""
    avatar_layout_template: str = "picture_in_picture_right"
    avatar_safe_margin: float = 0.08
    avatar_overlay_scale: float = 0.18

    # Voice / AI Director dubbing
    voice_provider: str = "runninghub"
    voice_clone_api_base_url: str = "https://www.runninghub.cn"
    voice_clone_api_key: str = ""
    voice_clone_voice_id: str = "2003864334474354690"
    director_rewrite_strength: float = 0.55

    # Publication / browser-agent
    publication_browser_agent_base_url: str = "http://127.0.0.1:49310"
    publication_browser_cdp_url: str = "http://127.0.0.1:9222"
    publication_browser_agent_auth_token: str = ""
    publication_reconcile_callback_base_url: str = ""
    publication_worker_poll_interval_sec: int = 30
    publication_worker_batch_limit: int = 5
    publication_attempt_lease_sec: int = 300
    publication_browser_agent_timeout_sec: int = 60
    publication_social_auto_upload_root: str = ""
    publication_social_auto_upload_python: str = "python"
    publication_social_auto_upload_timeout_sec: int = 1800
    publication_social_auto_upload_platforms: str = ""
    publication_social_auto_upload_auto_login: bool = False
    publication_social_auto_upload_headless: bool = True
    publication_x_username: str = ""
    publication_platform_active_schedule_times: str = (
        "douyin=20:30,kuaishou=20:00,xiaohongshu=21:00,bilibili=18:00,wechat-channels=20:00"
    )
    publication_cover_auto_heal_enabled: bool = True
    publication_cover_auto_heal_max_attempts: int = 1

    # Security
    max_upload_size_mb: int = 2048
    max_video_duration_sec: int = 7200
    ffmpeg_timeout_sec: int = 600
    render_video_encoder: str = "auto"          # auto | libx264 | h264_qsv | h264_amf | h264_nvenc
    render_cpu_preset: str = "veryfast"         # x264 preset for CPU fallback
    render_crf: int = 19                        # x264 constant quality target
    render_nvenc_preset: str = "p5"             # NVENC preset balancing speed/quality
    render_nvenc_cq: int = 21                   # NVENC constant quality target
    render_audio_bitrate: str = "192k"
    render_ffmpeg_threads: int = 0              # 0 lets ffmpeg choose; set >0 to cap encode threads
    render_ffmpeg_filter_threads: int = 0       # 0 lets ffmpeg choose; set >0 to cap filter graph threads
    allowed_extensions: list[str] = [".mp4", ".mov", ".mkv", ".avi", ".webm"]

    # Output
    output_dir: str = str((DEFAULT_OUTPUT_ROOT / "output").as_posix())
    preferred_ui_language: str = "zh-CN"
    output_name_pattern: str = "{date}_{stem}"  # {date}=YYYYMMDD, {stem}=original filename stem
    render_debug_dir: str = str((DEFAULT_OUTPUT_ROOT / "render-debug").as_posix())
    render_subtitle_alignment_policy: str = "adaptive"  # adaptive | strict
    telegram_agent_enabled: bool = False
    telegram_agent_claude_enabled: bool = False
    telegram_agent_claude_command: str = "claude"
    telegram_agent_claude_model: str = ""
    telegram_agent_codex_command: str = "codex"
    telegram_agent_codex_model: str = ""
    telegram_agent_acp_command: str = ""
    telegram_agent_task_timeout_sec: int = 900
    telegram_agent_result_max_chars: int = 3500
    telegram_agent_state_dir: str = str((DEFAULT_OUTPUT_ROOT / "telegram-agent").as_posix())
    acp_bridge_backend: str = Field(default="", validation_alias="ROUGHCUT_ACP_BRIDGE_BACKEND")
    acp_bridge_fallback_backend: str = Field(default="", validation_alias="ROUGHCUT_ACP_BRIDGE_FALLBACK_BACKEND")
    acp_bridge_claude_model: str = Field(default="", validation_alias="ROUGHCUT_ACP_BRIDGE_CLAUDE_MODEL")
    acp_bridge_codex_command: str = Field(default="codex", validation_alias="ROUGHCUT_ACP_BRIDGE_CODEX_COMMAND")
    acp_bridge_codex_model: str = Field(default="", validation_alias="ROUGHCUT_ACP_BRIDGE_CODEX_MODEL")
    telegram_remote_review_enabled: bool = False
    telegram_bot_api_base_url: str = "https://api.telegram.org"
    telegram_bot_token: str = ""
    telegram_bot_chat_id: str = ""
    default_job_workflow_mode: str = DEFAULT_JOB_WORKFLOW_MODE
    default_job_enhancement_modes: list[str] = []

    # Vision model (for rotation detection, cover selection)
    # Set to a vision-capable model name, e.g. "llava:13b" or "moondream" for Ollama,
    # "gpt-4o" for OpenAI. Empty string = attempt with reasoning_model.
    vision_model: str = DEFAULT_ZHIPU_VISION_MODEL

    # Subtitle style (burned into video) — neon/fluorescent: black text + green glow
    subtitle_font: str = "Microsoft YaHei"
    subtitle_font_size: int = 144                # pt at PlayResY; tuned for large 1-2 line subtitles
    subtitle_color: str = "000000"               # text color RGB hex (black)
    subtitle_outline_color: str = "00FF00"       # outline/glow color RGB hex (neon green)
    subtitle_outline_width: int = 5              # outline thickness; thick = fluorescent glow

    # Cover settings
    cover_candidate_count: int = 10             # frames to sample for best-cover selection
    cover_output_variants: int = 5              # export multiple cover variants for manual selection
    render_cover_generation_enabled: bool = False  # cover generation belongs to publication by default
    cover_title: str = ""                        # manual cover title override; empty = auto-generate
    cover_title_font_path: str = "C:/Windows/Fonts/msyhbd.ttc"
    auto_select_cover_variant: bool = True
    cover_selection_review_gap: float = 0.08
    intelligent_copy_cover_image_generation_enabled: bool = True
    intelligent_copy_cover_image_backend: str = "codex_builtin"  # codex_builtin | openai_images_api | minimax_images_api | dreamina_web
    intelligent_copy_cover_image_model: str = "image2"
    intelligent_copy_cover_image_quality: str = "medium"
    intelligent_copy_cover_image_timeout_sec: int = 240
    intelligent_copy_cover_codex_max_attempts: int = 1
    intelligent_copy_cover_codex_runner_model: str = "gpt-5.4-mini"
    intelligent_copy_cover_codex_runner_effort: str = "low"
    intelligent_copy_cover_dreamina_command: str = "node"
    intelligent_copy_cover_dreamina_runner_script: str = ""
    intelligent_copy_cover_dreamina_cdp_base_url: str = "http://127.0.0.1:9222"
    intelligent_copy_cover_dreamina_cookie_source_base_url: str = "http://127.0.0.1:9222"
    intelligent_copy_cover_dreamina_page_url: str = "https://jimeng.jianying.com/ai-tool/generate/?type=image"
    intelligent_copy_cover_dreamina_page_url_pattern: str = "jimeng.jianying.com/ai-tool/generate"
    intelligent_copy_cover_dreamina_user_data_dir: str = "./data/runtime/dreamina-profile"
    intelligent_copy_cover_dreamina_headless_user_data_dir: str = (
        "./data/runtime/dreamina-profile-headless"
    )
    intelligent_copy_cover_dreamina_template_path: str = ""
    intelligent_copy_cover_dreamina_submit_state_path: str = ""
    intelligent_copy_cover_dreamina_executable_path: str = ""
    intelligent_copy_cover_dreamina_http_replay_enabled: bool = True
    intelligent_copy_cover_dreamina_auto_launch: bool = True
    intelligent_copy_cover_dreamina_headless: bool = True
    intelligent_copy_cover_dreamina_keep_alive: bool = False
    intelligent_copy_cover_dreamina_poll_interval_ms: int = 5000
    intelligent_copy_cover_dreamina_poll_timeout_ms: int = 300000
    intelligent_copy_cover_dreamina_submit_timeout_ms: int = 60000
    intelligent_copy_cover_dreamina_capture_timeout_ms: int = 120000
    intelligent_copy_cover_dreamina_min_submit_interval_ms: int = 45000
    smart_director_asset_generation_enabled: bool = True
    smart_director_asset_generation_max_items: int = 4
    smart_director_image_generation_provider: str = "dreamina_web"
    smart_director_image_generation_model: str = ""
    smart_director_video_generation_provider: str = "jimeng_cli"
    smart_director_video_generation_command: str = ""
    smart_director_video_generation_timeout_sec: int = 900
    packaging_selection_review_gap: float = 0.08
    packaging_selection_min_score: float = 0.6
    edit_decision_llm_review_enabled: bool = True
    edit_decision_llm_review_max_candidates: int = 6
    edit_decision_llm_review_timeout_sec: int = 30
    edit_decision_llm_review_min_confidence: float = 0.72
    edit_decision_waste_discovery_enabled: bool = True
    edit_decision_waste_discovery_max_subtitles: int = 160
    edit_decision_waste_discovery_max_candidates: int = 8
    edit_decision_waste_discovery_timeout_sec: int = 45
    edit_decision_waste_discovery_min_confidence: float = 0.68
    multimodal_trim_review_enabled: bool = True
    multimodal_trim_review_max_candidates: int = 4
    multimodal_trim_review_timeout_sec: int = 20
    multimodal_trim_review_min_confidence: float = 0.72
    streamlined_asr_pipeline_enabled: bool = False
    subtitle_filler_cleanup_enabled: bool = True
    quality_auto_rerun_enabled: bool = True
    quality_auto_rerun_below_score: float = 75.0
    quality_auto_rerun_max_attempts: int = 1
    correction_framework_version: str = "multisource_v1"
    ocr_provider: str = "paddleocr"
    ocr_enabled: bool = False
    entity_graph_enabled: bool = False
    asr_evidence_enabled: bool = False
    research_verifier_enabled: bool = False

    # Feature flags
    fact_check_enabled: bool = False
    # Review is exception-only by default: normal jobs auto-continue, blockers pause.
    auto_confirm_content_profile: bool = True
    content_profile_review_threshold: float = 0.9
    content_profile_auto_review_min_accuracy: float = 0.9
    content_profile_auto_review_min_samples: int = 20
    auto_accept_glossary_corrections: bool = True
    glossary_correction_review_threshold: float = 0.9

    @field_validator("allowed_extensions", mode="before")
    @classmethod
    def parse_extensions(cls, v: object) -> list[str]:
        if isinstance(v, str):
            # Handle comma-separated string or JSON-like input.
            v = v.strip()
            if not v.startswith("["):
                return [ext.strip() for ext in v.split(",")]
        return v  # type: ignore[return-value]

    @field_validator("reasoning_model", mode="after")
    @classmethod
    def normalize_reasoning_model_field(cls, value: str, info: ValidationInfo) -> str:
        return normalize_reasoning_model_for_provider(info.data.get("reasoning_provider"), value)

    @field_validator("backup_reasoning_model", mode="after")
    @classmethod
    def normalize_backup_reasoning_model_field(cls, value: str, info: ValidationInfo) -> str:
        return normalize_reasoning_model_for_provider(info.data.get("backup_reasoning_provider"), value)

    @field_validator("hybrid_analysis_model", mode="after")
    @classmethod
    def normalize_hybrid_analysis_model_field(cls, value: str, info: ValidationInfo) -> str:
        return normalize_reasoning_model_for_provider(info.data.get("hybrid_analysis_provider"), value)

    @field_validator("hybrid_copy_model", mode="after")
    @classmethod
    def normalize_hybrid_copy_model_field(cls, value: str, info: ValidationInfo) -> str:
        return normalize_reasoning_model_for_provider(info.data.get("hybrid_copy_provider"), value)

    @property
    def max_upload_size_bytes(self) -> int:
        if self.max_upload_size_mb <= 0:
            return 0
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def active_reasoning_provider(self) -> str:
        route_provider = str(_get_llm_route_override("reasoning_provider") or "").strip().lower()
        if route_provider:
            return route_provider
        return "ollama" if self.llm_mode == "local" else self.reasoning_provider

    @property
    def active_reasoning_model(self) -> str:
        route_model = str(_get_llm_route_override("reasoning_model") or "").strip()
        if route_model:
            return route_model
        return self.local_reasoning_model if self.llm_mode == "local" else self.reasoning_model

    @property
    def active_reasoning_effort(self) -> str:
        route_effort = _normalize_reasoning_effort(_get_llm_route_override("reasoning_effort"))
        if route_effort:
            return route_effort
        if self.llm_mode == "local":
            return "medium"
        return _normalize_reasoning_effort(self.reasoning_effort) or "low"

    @property
    def active_vision_model(self) -> str:
        route_model = str(_get_llm_route_override("vision_model") or "").strip()
        if route_model:
            return route_model
        if self.llm_mode == "local":
            return self.local_vision_model or self.vision_model
        return self.vision_model or self.reasoning_model

    @property
    def active_search_provider(self) -> str:
        route_provider = str(_get_llm_route_override("search_provider") or "").strip().lower()
        if route_provider:
            return route_provider
        return self.search_provider

    @property
    def active_search_fallback_provider(self) -> str:
        route_provider = str(_get_llm_route_override("search_fallback_provider") or "").strip().lower()
        if route_provider:
            return route_provider
        return self.search_fallback_provider

    @property
    def active_model_search_helper(self) -> str:
        route_helper = str(_get_llm_route_override("model_search_helper") or "").strip()
        if route_helper:
            return route_helper
        helper = str(self.model_search_helper or "").strip()
        if helper:
            return helper
        if uses_codex_auth_helper(self):
            return build_default_model_search_helper()
        return ""

    @property
    def active_multimodal_fallback_provider(self) -> str:
        route_provider = str(_get_llm_route_override("multimodal_fallback_provider") or "").strip().lower()
        if route_provider:
            return route_provider
        return self.multimodal_fallback_provider

    @property
    def active_multimodal_fallback_model(self) -> str:
        route_model = str(_get_llm_route_override("multimodal_fallback_model") or "").strip()
        if route_model:
            return route_model
        return self.multimodal_fallback_model


_settings: Settings | None = None
_session_secret_overrides: dict[str, Any] = {}
_llm_route_overrides: ContextVar[dict[str, Any]] = ContextVar("roughcut_llm_route_overrides", default={})


def canonicalize_transcription_provider_name(provider: object) -> str:
    provider_value = str(provider or DEFAULT_TRANSCRIPTION_PROVIDER).strip().lower() or DEFAULT_TRANSCRIPTION_PROVIDER
    return TRANSCRIPTION_PROVIDER_ALIASES.get(provider_value, provider_value)


def normalize_transcription_provider_name(provider: object) -> str:
    provider_value = canonicalize_transcription_provider_name(provider)
    if provider_value not in TRANSCRIPTION_MODEL_OPTIONS:
        return DEFAULT_TRANSCRIPTION_PROVIDER
    return provider_value


def normalize_transcription_settings(provider: object, model: object) -> tuple[str, str]:
    provider_value = normalize_transcription_provider_name(provider)

    model_value = str(model or "").strip()
    allowed_models = TRANSCRIPTION_MODEL_OPTIONS[provider_value]
    if model_value not in allowed_models:
        model_value = DEFAULT_TRANSCRIPTION_MODELS[provider_value]

    return provider_value, model_value


def normalize_reasoning_model_for_provider(provider: object, model: object) -> str:
    normalized_provider = str(provider or "").strip().lower()
    model_value = str(model or "").strip()
    if not model_value:
        return DEFAULT_ZHIPU_REASONING_MODEL if normalized_provider == "zhipu" else ""
    if normalized_provider == "zhipu":
        return ZHIPU_REASONING_MODEL_ALIASES.get(model_value.lower(), model_value)
    if normalized_provider != "minimax":
        return model_value
    return MINIMAX_REASONING_MODEL_ALIASES.get(model_value.lower(), model_value)


def _has_minimax_reasoning_credentials(settings: Any) -> bool:
    return bool(str(getattr(settings, "minimax_api_key", "") or "").strip())


def _has_zhipu_reasoning_credentials(settings: Any) -> bool:
    auth_mode = normalize_auth_mode(getattr(settings, "zhipu_auth_mode", ""))
    if auth_mode == "helper":
        return bool(str(getattr(settings, "zhipu_api_key_helper", "") or "").strip())
    return bool(str(getattr(settings, "zhipu_api_key", "") or "").strip())


def _has_configured_searxng(settings: Any) -> bool:
    return bool(str(getattr(settings, "searxng_url", "") or "").strip())


def _resolve_codex_bridge_command(settings: Any) -> str:
    return str(
        os.getenv("ROUGHCUT_CODEX_HOST_BRIDGE_CODEX_COMMAND")
        or getattr(settings, "telegram_agent_codex_command", "")
        or getattr(settings, "acp_bridge_codex_command", "")
        or "codex"
    ).strip() or "codex"


def uses_codex_auth_helper(settings: Any) -> bool:
    auth_mode = normalize_auth_mode(getattr(settings, "openai_auth_mode", ""))
    if auth_mode != "helper":
        return False
    helper_kind = str(os.getenv("ROUGHCUT_OPENAI_AUTH_HELPER_KIND", "") or "").strip().lower()
    if helper_kind:
        return helper_kind in {"codex", "codex_cli", "codex-bridge", "codex_bridge"}
    helper_command = str(getattr(settings, "openai_api_key_helper", "") or "").strip().lower()
    command_head = helper_command.split(maxsplit=1)[0] if helper_command else ""
    if Path(command_head).name in {"codex", "codex.exe"}:
        return True
    return "print_codex_access_token.py" in helper_command


def _has_openai_codex_reasoning_bridge(settings: Any) -> bool:
    if not uses_codex_auth_helper(settings):
        return False
    return bool(shutil.which(_resolve_codex_bridge_command(settings)))


def _openai_responses_credentials_unavailable(settings: Any) -> bool:
    direct_key = str(getattr(settings, "openai_api_key", "") or "").strip()
    return uses_codex_auth_helper(settings) and not direct_key and not _has_openai_codex_reasoning_bridge(settings)


def _openai_responses_route_uses_codex_bridge(settings: Any) -> bool:
    direct_key = str(getattr(settings, "openai_api_key", "") or "").strip()
    return uses_codex_auth_helper(settings) and not direct_key and _has_openai_codex_reasoning_bridge(settings)


def _openai_responses_route_likely_unavailable(settings: Any) -> bool:
    provider = str(getattr(settings, "active_reasoning_provider", "") or getattr(settings, "reasoning_provider", "")).strip().lower()
    return provider == "openai" and _openai_responses_credentials_unavailable(settings)


def resolve_transcription_provider_plan(provider: object, model: object) -> list[tuple[str, str]]:
    provider_value, model_value = normalize_transcription_settings(provider, model)
    return [(provider_value, model_value)]


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _apply_settings_overrides(_settings, load_runtime_overrides())
        _apply_settings_overrides(_settings, _session_secret_overrides)
        _normalize_settings(_settings)
    return _settings


def load_runtime_overrides() -> dict[str, Any]:
    try:
        from roughcut.state_store import RUNTIME_OVERRIDES_KEY, delete_setting, get_json_setting, set_json_setting

        payload = get_json_setting(RUNTIME_OVERRIDES_KEY, default=None)
        if isinstance(payload, dict):
            normalized_payload = _normalize_runtime_override_values(payload)
            persisted, secrets = _split_runtime_overrides(normalized_payload)
            _update_session_secret_overrides(secrets)
            if persisted != normalized_payload:
                if persisted:
                    set_json_setting(RUNTIME_OVERRIDES_KEY, persisted)
                else:
                    delete_setting(RUNTIME_OVERRIDES_KEY)
            return persisted
        return {}
    except Exception:
        return {}


def save_runtime_overrides(data: dict[str, Any]) -> None:
    normalized_data = _normalize_runtime_override_values(data)
    persisted, secrets = _split_runtime_overrides(normalized_data)
    _update_session_secret_overrides(secrets)
    from roughcut.state_store import RUNTIME_OVERRIDES_KEY, delete_setting, set_json_setting

    if persisted:
        set_json_setting(RUNTIME_OVERRIDES_KEY, persisted)
    else:
        delete_setting(RUNTIME_OVERRIDES_KEY)


def clear_runtime_overrides() -> None:
    global _settings
    try:
        from roughcut.state_store import RUNTIME_OVERRIDES_KEY, delete_setting

        delete_setting(RUNTIME_OVERRIDES_KEY)
    except Exception:
        pass
    _session_secret_overrides.clear()
    _settings = None


def apply_runtime_overrides(updates: dict[str, Any]) -> Settings:
    filtered_updates = _normalize_runtime_override_values(_strip_env_managed_updates(updates))
    overrides = load_runtime_overrides()
    overrides.update(filtered_updates)
    save_runtime_overrides(overrides)

    settings = get_settings()
    for key, value in filtered_updates.items():
        if hasattr(settings, key):
            object.__setattr__(settings, key, value)

    provider, model = normalize_transcription_settings(
        settings.transcription_provider,
        settings.transcription_model,
    )
    object.__setattr__(settings, "transcription_provider", provider)
    object.__setattr__(settings, "transcription_model", model)
    object.__setattr__(
        settings,
        "transcription_dialect",
        normalize_transcription_dialect(getattr(settings, "transcription_dialect", DEFAULT_TRANSCRIPTION_DIALECT)),
    )
    object.__setattr__(
        settings,
        "default_job_workflow_mode",
        _normalize_default_workflow_mode(getattr(settings, "default_job_workflow_mode", DEFAULT_JOB_WORKFLOW_MODE)),
    )
    object.__setattr__(
        settings,
        "default_job_enhancement_modes",
        _normalize_default_enhancement_modes(getattr(settings, "default_job_enhancement_modes", []) or []),
    )
    return settings


def apply_in_memory_runtime_overrides(updates: dict[str, Any] | None = None) -> Settings:
    global _settings
    _settings = Settings()
    _apply_settings_overrides(_settings, load_runtime_overrides())
    _apply_settings_overrides(_settings, _session_secret_overrides)
    if updates:
        _apply_settings_overrides(_settings, _normalize_runtime_override_values(_strip_env_managed_updates(dict(updates))))
    _normalize_settings(_settings)
    return _settings


def _normalize_default_workflow_mode(value: object) -> str:
    from roughcut.creative.modes import normalize_workflow_mode

    return normalize_workflow_mode(str(value or DEFAULT_JOB_WORKFLOW_MODE))


def _normalize_default_enhancement_modes(value: object) -> list[str]:
    from roughcut.creative.modes import normalize_enhancement_modes

    if isinstance(value, (list, tuple, set)):
        return normalize_enhancement_modes(list(value))
    return normalize_enhancement_modes([])


def get_session_secret_override_keys() -> list[str]:
    return sorted(_session_secret_overrides.keys())


def _apply_settings_overrides(settings: Settings, updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if key in ENV_MANAGED_SETTINGS or _has_explicit_env_override(key):
            continue
        if hasattr(settings, key):
            object.__setattr__(settings, key, value)


def _normalize_settings(settings: Settings) -> None:
    object.__setattr__(settings, "openai_auth_mode", normalize_auth_mode(getattr(settings, "openai_auth_mode", "api_key")))
    object.__setattr__(settings, "anthropic_auth_mode", normalize_auth_mode(getattr(settings, "anthropic_auth_mode", "api_key")))
    object.__setattr__(settings, "zhipu_auth_mode", normalize_auth_mode(getattr(settings, "zhipu_auth_mode", "api_key")))
    provider, model = normalize_transcription_settings(
        settings.transcription_provider,
        settings.transcription_model,
    )
    object.__setattr__(settings, "transcription_provider", provider)
    object.__setattr__(settings, "transcription_model", model)
    object.__setattr__(
        settings,
        "transcription_dialect",
        normalize_transcription_dialect(getattr(settings, "transcription_dialect", DEFAULT_TRANSCRIPTION_DIALECT)),
    )
    object.__setattr__(
        settings,
        "default_job_workflow_mode",
        _normalize_default_workflow_mode(getattr(settings, "default_job_workflow_mode", DEFAULT_JOB_WORKFLOW_MODE)),
    )
    object.__setattr__(
        settings,
        "default_job_enhancement_modes",
        _normalize_default_enhancement_modes(getattr(settings, "default_job_enhancement_modes", []) or []),
    )
    _normalize_llm_capability_bundle_settings(settings)


def normalize_coding_backend_name(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in CODING_BACKEND_VALUES else ""


def coding_backend_for_provider(provider: object) -> str:
    normalized_provider = str(provider or "").strip().lower()
    for backend, providers in CODING_BACKEND_PROVIDER_MAP.items():
        if normalized_provider in providers:
            return backend
    return ""


def _iter_coding_model_route_candidates(settings: Settings | None = None) -> list[tuple[str, str]]:
    current = settings or get_settings()
    reasoning_candidate = (
        str(getattr(current, "active_reasoning_provider", "") or "").strip().lower(),
        str(getattr(current, "active_reasoning_model", "") or "").strip(),
    )
    hybrid_candidates = [
        (
            str(getattr(current, "hybrid_analysis_provider", "") or "").strip().lower(),
            str(getattr(current, "hybrid_analysis_model", "") or "").strip(),
        ),
        (
            str(getattr(current, "hybrid_copy_provider", "") or "").strip().lower(),
            str(getattr(current, "hybrid_copy_model", "") or "").strip(),
        ),
    ]
    ordered_candidates = (
        [*hybrid_candidates, reasoning_candidate]
        if is_hybrid_routing_enabled(current)
        else [reasoning_candidate, *hybrid_candidates]
    )
    deduped: list[tuple[str, str]] = []
    for provider, model in ordered_candidates:
        if not provider or not model:
            continue
        candidate = (provider, model)
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def infer_coding_backends(
    settings: Settings | None = None,
    *,
    claude_enabled: bool | None = None,
) -> list[str]:
    current = settings or get_settings()
    allow_claude = (
        bool(getattr(current, "telegram_agent_claude_enabled", False))
        if claude_enabled is None
        else bool(claude_enabled)
    )
    backends: list[str] = []
    for provider, _model in _iter_coding_model_route_candidates(current):
        backend = coding_backend_for_provider(provider)
        if not backend:
            continue
        if backend == "claude" and not allow_claude:
            continue
        if backend not in backends:
            backends.append(backend)
    if not backends:
        backends.append("codex")
        if allow_claude:
            backends.append("claude")
    return backends


def resolve_coding_backend_model(
    backend: str,
    *,
    settings: Settings | None = None,
    explicit_model: object = "",
    allow_default: bool = True,
) -> str:
    normalized_backend = normalize_coding_backend_name(backend)
    explicit = str(explicit_model or "").strip()
    if explicit:
        return explicit
    if not normalized_backend:
        return ""
    allowed_providers = CODING_BACKEND_PROVIDER_MAP.get(normalized_backend, ())
    for provider, model in _iter_coding_model_route_candidates(settings):
        if provider in allowed_providers and model:
            return model
    if allow_default:
        return DEFAULT_CODING_BACKEND_MODELS.get(normalized_backend, "")
    return ""


def _normalize_runtime_override_values(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)

    for key in ("openai_auth_mode", "anthropic_auth_mode", "zhipu_auth_mode"):
        if key in normalized:
            normalized[key] = normalize_auth_mode(normalized.get(key))

    if "llm_routing_mode" in normalized:
        routing_mode = str(normalized.get("llm_routing_mode") or "").strip().lower()
        normalized["llm_routing_mode"] = routing_mode if routing_mode in LLM_ROUTING_MODE_VALUES else "bundled"

    if "search_provider" in normalized:
        provider = str(normalized.get("search_provider") or "").strip().lower()
        normalized["search_provider"] = provider if provider in SEARCH_PROVIDER_VALUES else DEFAULT_SEARCH_PROVIDER

    if "search_fallback_provider" in normalized:
        fallback = str(normalized.get("search_fallback_provider") or "").strip().lower()
        normalized["search_fallback_provider"] = (
            fallback if fallback in SEARCH_FALLBACK_PROVIDER_VALUES else DEFAULT_SEARCH_FALLBACK_PROVIDER
        )

    if "backup_search_provider" in normalized:
        backup_search = str(normalized.get("backup_search_provider") or "").strip().lower()
        normalized["backup_search_provider"] = backup_search if backup_search in SEARCH_PROVIDER_VALUES else "auto"

    if "backup_search_fallback_provider" in normalized:
        fallback = str(normalized.get("backup_search_fallback_provider") or "").strip().lower()
        normalized["backup_search_fallback_provider"] = (
            fallback if fallback in SEARCH_FALLBACK_PROVIDER_VALUES else DEFAULT_BACKUP_SEARCH_FALLBACK_PROVIDER
        )

    if "multimodal_fallback_provider" in normalized:
        fallback = str(normalized.get("multimodal_fallback_provider") or "").strip().lower()
        normalized["multimodal_fallback_provider"] = (
            fallback if fallback in MULTIMODAL_FALLBACK_PROVIDER_VALUES else DEFAULT_MULTIMODAL_FALLBACK_PROVIDER
        )

    if "backup_vision_model" in normalized:
        normalized["backup_vision_model"] = str(normalized.get("backup_vision_model") or "").strip()

    if "model_search_helper" in normalized:
        normalized["model_search_helper"] = str(normalized.get("model_search_helper") or "").strip()

    if "backup_model_search_helper" in normalized:
        normalized["backup_model_search_helper"] = str(normalized.get("backup_model_search_helper") or "").strip()

    if "reasoning_provider" in normalized:
        normalized["reasoning_provider"] = str(normalized.get("reasoning_provider") or "").strip().lower()

    if "reasoning_model" in normalized:
        normalized["reasoning_model"] = normalize_reasoning_model_for_provider(
            normalized.get("reasoning_provider"),
            normalized.get("reasoning_model"),
        )

    if "backup_reasoning_provider" in normalized:
        provider = str(normalized.get("backup_reasoning_provider") or "").strip().lower()
        normalized["backup_reasoning_provider"] = (
            provider if provider in HYBRID_REASONING_PROVIDER_VALUES else DEFAULT_BACKUP_REASONING_PROVIDER
        )
    if "backup_reasoning_model" in normalized:
        normalized["backup_reasoning_model"] = normalize_reasoning_model_for_provider(
            normalized.get("backup_reasoning_provider"),
            normalized.get("backup_reasoning_model"),
        )

    for key in (
        "reasoning_effort",
        "backup_reasoning_effort",
        "hybrid_analysis_effort",
        "hybrid_copy_effort",
        "intelligent_copy_cover_codex_runner_effort",
    ):
        if key in normalized:
            normalized[key] = _normalize_reasoning_effort(normalized.get(key)) or (
                "high" if key == "hybrid_copy_effort" else "low"
            )

    for key in ("hybrid_analysis_provider", "hybrid_copy_provider"):
        if key in normalized:
            provider = str(normalized.get(key) or "").strip().lower()
            normalized[key] = provider if provider in HYBRID_REASONING_PROVIDER_VALUES else (
                DEFAULT_HYBRID_ANALYSIS_PROVIDER if key == "hybrid_analysis_provider" else DEFAULT_HYBRID_COPY_PROVIDER
            )

    for key in ("hybrid_analysis_model", "hybrid_copy_model"):
        if key in normalized:
            provider_key = "hybrid_analysis_provider" if key == "hybrid_analysis_model" else "hybrid_copy_provider"
            normalized[key] = normalize_reasoning_model_for_provider(
                normalized.get(provider_key),
                normalized.get(key),
            )

    for key in (
        "telegram_agent_claude_model",
        "telegram_agent_codex_model",
        "acp_bridge_claude_model",
        "acp_bridge_codex_model",
        "intelligent_copy_cover_image_model",
        "intelligent_copy_cover_image_quality",
        "intelligent_copy_cover_codex_runner_model",
        "intelligent_copy_cover_dreamina_command",
        "intelligent_copy_cover_dreamina_runner_script",
        "intelligent_copy_cover_dreamina_cdp_base_url",
        "intelligent_copy_cover_dreamina_cookie_source_base_url",
        "intelligent_copy_cover_dreamina_page_url",
        "intelligent_copy_cover_dreamina_page_url_pattern",
        "intelligent_copy_cover_dreamina_user_data_dir",
        "intelligent_copy_cover_dreamina_headless_user_data_dir",
        "intelligent_copy_cover_dreamina_template_path",
        "intelligent_copy_cover_dreamina_submit_state_path",
        "intelligent_copy_cover_dreamina_executable_path",
    ):
        if key in normalized:
            normalized[key] = str(normalized.get(key) or "").strip()

    if "intelligent_copy_cover_image_backend" in normalized:
        backend = str(normalized.get("intelligent_copy_cover_image_backend") or "").strip().lower()
        if backend in {"codex", "codex_cli", "codex_imagegen"}:
            backend = "codex_builtin"
        if backend == "openai_api":
            backend = "openai_images_api"
        if backend in {"minimax", "minimax_api"}:
            backend = "minimax_images_api"
        if backend in {"dreamina", "dreamina_cdp", "dreamina_web_cdp"}:
            backend = "dreamina_web"
        normalized["intelligent_copy_cover_image_backend"] = backend if backend in {
            "codex_builtin",
            "openai_images_api",
            "minimax_images_api",
            "dreamina_web",
        } else "codex_builtin"

    for key in ("acp_bridge_backend", "acp_bridge_fallback_backend"):
        if key in normalized:
            normalized[key] = normalize_coding_backend_name(normalized.get(key))

    for key in ("hybrid_analysis_search_mode", "hybrid_copy_search_mode"):
        if key in normalized:
            search_mode = str(normalized.get(key) or "").strip().lower()
            normalized[key] = search_mode if search_mode in HYBRID_SEARCH_MODE_VALUES else (
                "entity_gated" if key == "hybrid_analysis_search_mode" else "follow_provider"
            )

    if "llm_mode" in normalized:
        llm_mode = str(normalized.get("llm_mode") or "").strip().lower()
        normalized["llm_mode"] = llm_mode if llm_mode in {"performance", "local"} else "performance"

    _upgrade_legacy_local_http_asr_overrides(normalized)
    return normalized


def _upgrade_legacy_local_http_asr_overrides(normalized: dict[str, Any]) -> None:
    provider = canonicalize_transcription_provider_name(
        normalized.get("transcription_provider", DEFAULT_TRANSCRIPTION_PROVIDER)
    )
    if provider != "local_http_asr":
        return

    model = str(normalized.get("transcription_model") or "").strip().lower()
    actual_model = str(normalized.get("local_asr_model_name") or "").strip().lower()
    base_url = str(normalized.get("local_asr_api_base_url") or "").strip().rstrip("/")
    display_name = str(normalized.get("local_asr_display_name") or "").strip().lower()
    uses_legacy_local_asr = (
        model in LEGACY_LOCAL_HTTP_ASR_MODELS
        or actual_model in LEGACY_LOCAL_HTTP_ASR_MODELS
        or base_url in LEGACY_LOCAL_HTTP_ASR_URLS
        or display_name in {"moss-audio 8b instruct", "vibevoice int8"}
    )
    if not uses_legacy_local_asr:
        return

    normalized["transcription_provider"] = "local_http_asr"
    normalized["transcription_model"] = DEFAULT_TRANSCRIPTION_MODELS["local_http_asr"]
    normalized["local_asr_api_base_url"] = Settings.model_fields["local_asr_api_base_url"].default
    normalized["local_asr_model_name"] = Settings.model_fields["local_asr_model_name"].default
    normalized["local_asr_display_name"] = Settings.model_fields["local_asr_display_name"].default


def _normalize_llm_capability_bundle_settings(settings: Settings) -> None:
    routing_mode = str(getattr(settings, "llm_routing_mode", "") or "").strip().lower()
    if routing_mode not in LLM_ROUTING_MODE_VALUES:
        routing_mode = "bundled"
    object.__setattr__(settings, "llm_routing_mode", routing_mode)

    reasoning_provider = str(getattr(settings, "reasoning_provider", "") or "").strip().lower()
    if reasoning_provider not in HYBRID_REASONING_PROVIDER_VALUES:
        reasoning_provider = DEFAULT_REASONING_PROVIDER
    object.__setattr__(settings, "reasoning_provider", reasoning_provider)
    object.__setattr__(
        settings,
        "reasoning_model",
        normalize_reasoning_model_for_provider(
            reasoning_provider,
            str(getattr(settings, "reasoning_model", "") or "").strip() or DEFAULT_REASONING_MODEL,
        ) or DEFAULT_REASONING_MODEL,
    )

    analysis_provider = str(getattr(settings, "hybrid_analysis_provider", "") or "").strip().lower()
    if analysis_provider not in HYBRID_REASONING_PROVIDER_VALUES:
        analysis_provider = DEFAULT_HYBRID_ANALYSIS_PROVIDER
    object.__setattr__(settings, "hybrid_analysis_provider", analysis_provider)

    copy_provider = str(getattr(settings, "hybrid_copy_provider", "") or "").strip().lower()
    if copy_provider not in HYBRID_REASONING_PROVIDER_VALUES:
        copy_provider = DEFAULT_HYBRID_COPY_PROVIDER
    object.__setattr__(settings, "hybrid_copy_provider", copy_provider)

    object.__setattr__(
        settings,
        "hybrid_analysis_model",
        normalize_reasoning_model_for_provider(
            analysis_provider,
            str(getattr(settings, "hybrid_analysis_model", "") or "").strip() or DEFAULT_HYBRID_ANALYSIS_MODEL,
        ) or DEFAULT_HYBRID_ANALYSIS_MODEL,
    )
    object.__setattr__(
        settings,
        "hybrid_analysis_effort",
        _normalize_reasoning_effort(getattr(settings, "hybrid_analysis_effort", "low")) or "low",
    )
    object.__setattr__(
        settings,
        "hybrid_copy_model",
        normalize_reasoning_model_for_provider(
            copy_provider,
            str(getattr(settings, "hybrid_copy_model", "") or "").strip() or DEFAULT_HYBRID_COPY_MODEL,
        ) or DEFAULT_HYBRID_COPY_MODEL,
    )
    object.__setattr__(
        settings,
        "hybrid_copy_effort",
        _normalize_reasoning_effort(getattr(settings, "hybrid_copy_effort", "high")) or "high",
    )
    object.__setattr__(
        settings,
        "reasoning_effort",
        _normalize_reasoning_effort(getattr(settings, "reasoning_effort", "low")) or "low",
    )
    object.__setattr__(settings, "llm_backup_enabled", bool(getattr(settings, "llm_backup_enabled", True)))
    backup_provider = str(getattr(settings, "backup_reasoning_provider", "") or "").strip().lower()
    if backup_provider not in HYBRID_REASONING_PROVIDER_VALUES:
        backup_provider = DEFAULT_BACKUP_REASONING_PROVIDER
    object.__setattr__(settings, "backup_reasoning_provider", backup_provider)
    object.__setattr__(
        settings,
        "backup_reasoning_model",
        normalize_reasoning_model_for_provider(
            backup_provider,
            str(getattr(settings, "backup_reasoning_model", "") or "").strip() or DEFAULT_BACKUP_REASONING_MODEL,
        ) or DEFAULT_BACKUP_REASONING_MODEL,
    )
    object.__setattr__(
        settings,
        "backup_reasoning_effort",
        _normalize_reasoning_effort(getattr(settings, "backup_reasoning_effort", "low")) or "low",
    )
    object.__setattr__(
        settings,
        "backup_vision_model",
        str(getattr(settings, "backup_vision_model", "") or "").strip() or DEFAULT_BACKUP_VISION_MODEL,
    )
    backup_search_provider = str(getattr(settings, "backup_search_provider", "") or "").strip().lower()
    if backup_search_provider not in SEARCH_PROVIDER_VALUES:
        backup_search_provider = "auto"
    if backup_search_provider == "minimax" and not _has_minimax_reasoning_credentials(settings) and _has_configured_searxng(settings):
        backup_search_provider = "searxng"
    if backup_search_provider == "zhipu" and not _has_zhipu_reasoning_credentials(settings) and _has_configured_searxng(settings):
        backup_search_provider = "searxng"
    object.__setattr__(settings, "backup_search_provider", backup_search_provider)
    backup_search_fallback = str(getattr(settings, "backup_search_fallback_provider", "") or "").strip().lower()
    if backup_search_fallback not in SEARCH_FALLBACK_PROVIDER_VALUES:
        backup_search_fallback = DEFAULT_BACKUP_SEARCH_FALLBACK_PROVIDER
    if backup_search_fallback == "minimax" and not _has_minimax_reasoning_credentials(settings) and _has_configured_searxng(settings):
        backup_search_fallback = "searxng"
    if backup_search_fallback == "zhipu" and not _has_zhipu_reasoning_credentials(settings) and _has_configured_searxng(settings):
        backup_search_fallback = "searxng"
    object.__setattr__(settings, "backup_search_fallback_provider", backup_search_fallback)
    object.__setattr__(
        settings,
        "backup_model_search_helper",
        str(getattr(settings, "backup_model_search_helper", "") or "").strip(),
    )

    analysis_search_mode = str(getattr(settings, "hybrid_analysis_search_mode", "") or "").strip().lower()
    if analysis_search_mode not in HYBRID_SEARCH_MODE_VALUES:
        analysis_search_mode = "entity_gated"
    object.__setattr__(settings, "hybrid_analysis_search_mode", analysis_search_mode)

    copy_search_mode = str(getattr(settings, "hybrid_copy_search_mode", "") or "").strip().lower()
    if copy_search_mode not in HYBRID_SEARCH_MODE_VALUES:
        copy_search_mode = "follow_provider"
    object.__setattr__(settings, "hybrid_copy_search_mode", copy_search_mode)

    search_fallback = str(getattr(settings, "search_fallback_provider", "") or "").strip().lower()
    if search_fallback not in SEARCH_FALLBACK_PROVIDER_VALUES:
        search_fallback = DEFAULT_SEARCH_FALLBACK_PROVIDER
    search_provider = str(getattr(settings, "search_provider", "") or "").strip().lower()
    if search_provider not in SEARCH_PROVIDER_VALUES:
        search_provider = DEFAULT_SEARCH_PROVIDER
    if search_provider == "minimax" and not _has_minimax_reasoning_credentials(settings) and _has_configured_searxng(settings):
        search_provider = "searxng"
    if search_provider == "zhipu" and not _has_zhipu_reasoning_credentials(settings) and _has_configured_searxng(settings):
        search_provider = "searxng"
    if search_fallback == "minimax" and not _has_minimax_reasoning_credentials(settings) and _has_configured_searxng(settings):
        search_fallback = "searxng"
    if search_fallback == "zhipu" and not _has_zhipu_reasoning_credentials(settings) and _has_configured_searxng(settings):
        search_fallback = "searxng"
    object.__setattr__(settings, "search_provider", search_provider)
    object.__setattr__(settings, "search_fallback_provider", search_fallback)

    multimodal_fallback = str(getattr(settings, "multimodal_fallback_provider", "") or "").strip().lower()
    if multimodal_fallback not in MULTIMODAL_FALLBACK_PROVIDER_VALUES:
        multimodal_fallback = DEFAULT_MULTIMODAL_FALLBACK_PROVIDER
    object.__setattr__(settings, "multimodal_fallback_provider", multimodal_fallback)
    object.__setattr__(
        settings,
        "multimodal_fallback_model",
        str(getattr(settings, "multimodal_fallback_model", "") or "").strip() or DEFAULT_MULTIMODAL_FALLBACK_MODEL,
    )


def _get_llm_route_override(key: str) -> Any:
    overrides = _llm_route_overrides.get({})
    return overrides.get(key)


def resolve_backup_llm_route(*, settings: Settings | None = None) -> dict[str, Any]:
    current = settings or get_settings()
    if not bool(getattr(current, "llm_backup_enabled", False)):
        return {}

    provider = str(getattr(current, "backup_reasoning_provider", "") or "").strip().lower()
    model = normalize_reasoning_model_for_provider(
        provider,
        str(getattr(current, "backup_reasoning_model", "") or "").strip(),
    )
    if not provider or not model:
        return {}
    if provider == "openai" and _openai_responses_credentials_unavailable(current):
        return {}

    route: dict[str, Any] = {
        "reasoning_provider": provider,
        "reasoning_model": model,
        "reasoning_effort": _normalize_reasoning_effort(getattr(current, "backup_reasoning_effort", "low")) or "low",
        "vision_model": str(getattr(current, "backup_vision_model", "") or "").strip() or model,
        "search_provider": str(getattr(current, "backup_search_provider", "auto") or "auto").strip().lower() or "auto",
        "search_fallback_provider": (
            str(
                getattr(current, "backup_search_fallback_provider", DEFAULT_BACKUP_SEARCH_FALLBACK_PROVIDER)
                or DEFAULT_BACKUP_SEARCH_FALLBACK_PROVIDER
            ).strip().lower()
            or DEFAULT_BACKUP_SEARCH_FALLBACK_PROVIDER
        ),
        "model_search_helper": str(getattr(current, "backup_model_search_helper", "") or "").strip(),
    }
    if route["search_provider"] != "model" and route["search_fallback_provider"] != "model":
        route["model_search_helper"] = ""
    return route


def has_distinct_backup_llm_route(*, settings: Settings | None = None) -> bool:
    current = settings or get_settings()
    route = resolve_backup_llm_route(settings=current)
    if not route:
        return False
    active_provider = str(getattr(current, "active_reasoning_provider", "") or "").strip().lower()
    active_model = str(getattr(current, "active_reasoning_model", "") or "").strip()
    return (
        str(route.get("reasoning_provider") or "").strip().lower() != active_provider
        or str(route.get("reasoning_model") or "").strip() != active_model
    )


def _profile_has_specific_identity(profile: dict[str, Any] | None) -> bool:
    candidate = profile or {}
    brand = str(candidate.get("subject_brand") or "").strip()
    model = str(candidate.get("subject_model") or "").strip()
    subject_type = str(candidate.get("subject_type") or "").strip()
    if brand and model:
        return True
    if model and len(model) >= 3:
        return True
    if subject_type and all(token not in subject_type for token in ("内容", "视频", "产品", "口播", "素材")):
        return True
    return False


def is_hybrid_routing_enabled(settings: Settings | None = None) -> bool:
    current = settings or get_settings()
    llm_mode = str(getattr(current, "llm_mode", "performance") or "performance").strip().lower()
    routing_mode = str(getattr(current, "llm_routing_mode", "bundled") or "bundled").strip().lower()
    return llm_mode == "performance" and routing_mode == "hybrid_performance"


def resolve_llm_task_route(task_name: str, *, settings: Settings | None = None) -> dict[str, Any]:
    current = settings or get_settings()
    if not is_hybrid_routing_enabled(current):
        return {}

    normalized_task = str(task_name or "").strip().lower()
    if normalized_task in {"subtitle", "subtitle_postprocess", "subtitle_translation", "content_profile", "copy_verify", "edit_plan"}:
        selected_provider = str(
            getattr(current, "hybrid_analysis_provider", DEFAULT_HYBRID_ANALYSIS_PROVIDER)
            or DEFAULT_HYBRID_ANALYSIS_PROVIDER
        ).strip().lower()
        selected_model = str(
            getattr(current, "hybrid_analysis_model", DEFAULT_HYBRID_ANALYSIS_MODEL)
            or DEFAULT_HYBRID_ANALYSIS_MODEL
        ).strip()
        route = {
            "reasoning_provider": selected_provider,
            "reasoning_model": normalize_reasoning_model_for_provider(
                selected_provider,
                selected_model,
            ),
        }
        effort = _normalize_reasoning_effort(getattr(current, "hybrid_analysis_effort", ""))
        if effort:
            route["reasoning_effort"] = effort
        return route
    if normalized_task == "copy":
        active_provider = str(
            getattr(current, "active_reasoning_provider", "")
            or getattr(current, "reasoning_provider", "")
            or ""
        ).strip().lower()
        if active_provider == "openai" and uses_codex_auth_helper(current):
            return {}
        selected_provider = str(
            getattr(current, "hybrid_copy_provider", DEFAULT_HYBRID_COPY_PROVIDER)
            or DEFAULT_HYBRID_COPY_PROVIDER
        ).strip().lower()
        if selected_provider not in HYBRID_REASONING_PROVIDER_VALUES:
            selected_provider = DEFAULT_HYBRID_COPY_PROVIDER
        selected_model = str(
            getattr(current, "hybrid_copy_model", DEFAULT_HYBRID_COPY_MODEL)
            or DEFAULT_HYBRID_COPY_MODEL
        ).strip()
        if (
            selected_provider == "minimax"
            and (selected_model.lower().startswith("gpt-") or selected_model.lower().startswith("o"))
        ):
            selected_model = DEFAULT_MINIMAX_REASONING_MODEL
        route = {
            "reasoning_provider": selected_provider,
            "reasoning_model": normalize_reasoning_model_for_provider(
                selected_provider,
                selected_model,
            ),
        }
        effort = _normalize_reasoning_effort(getattr(current, "hybrid_copy_effort", ""))
        if effort:
            route["reasoning_effort"] = effort
        return route
    return {}


def _normalize_reasoning_effort(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in REASONING_EFFORT_VALUES:
        return normalized
    return ""


def should_enable_task_search(
    task_name: str,
    *,
    default_enabled: bool,
    profile: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> bool:
    current = settings or get_settings()
    if not default_enabled:
        return False
    if not is_hybrid_routing_enabled(current):
        return default_enabled

    normalized_task = str(task_name or "").strip().lower()
    if normalized_task in {"subtitle", "subtitle_translation", "content_profile", "copy_verify"}:
        search_mode = str(getattr(current, "hybrid_analysis_search_mode", "entity_gated") or "entity_gated").strip().lower()
    elif normalized_task == "copy":
        search_mode = str(getattr(current, "hybrid_copy_search_mode", "follow_provider") or "follow_provider").strip().lower()
    else:
        return default_enabled

    if search_mode == "off":
        return False
    if search_mode == "follow_provider":
        return True
    if search_mode == "entity_gated":
        return _profile_has_specific_identity(profile)
    return default_enabled


@contextmanager
def llm_task_route(
    task_name: str,
    *,
    search_enabled: bool | None = None,
    settings: Settings | None = None,
):
    current = settings or get_settings()
    overrides = dict(resolve_llm_task_route(task_name, settings=current))
    if overrides:
        effective_search_enabled = True if search_enabled is None else bool(search_enabled)
        if not effective_search_enabled:
            overrides["search_provider"] = "disabled"
    existing = dict(_llm_route_overrides.get({}))
    merged = {**existing, **overrides}
    token = _llm_route_overrides.set(merged)
    try:
        yield
    finally:
        _llm_route_overrides.reset(token)


@contextmanager
def llm_backup_route(*, settings: Settings | None = None):
    current = settings or get_settings()
    overrides = dict(resolve_backup_llm_route(settings=current))
    existing = dict(_llm_route_overrides.get({}))
    if not overrides:
        yield
        return
    merged = {**existing, **overrides}
    token = _llm_route_overrides.set(merged)
    try:
        yield
    finally:
        _llm_route_overrides.reset(token)


def _split_runtime_overrides(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    persisted: dict[str, Any] = {}
    secrets: dict[str, Any] = {}
    for key, value in data.items():
        if key in SECRET_SETTINGS:
            if str(value or "").strip():
                secrets[key] = value
            continue
        if key in ENV_MANAGED_SETTINGS or _has_explicit_env_override(key):
            continue
        persisted[key] = value
    return persisted, secrets


def _update_session_secret_overrides(updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if key not in SECRET_SETTINGS:
            continue
        if str(value or "").strip():
            _session_secret_overrides[key] = value
        else:
            _session_secret_overrides.pop(key, None)


def _strip_env_managed_updates(updates: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in updates.items()
        if key not in ENV_MANAGED_SETTINGS and not _has_explicit_env_override(key)
    }


def _has_explicit_env_override(key: str) -> bool:
    if key not in ENV_EXPLICIT_OVERRIDE_SETTINGS:
        return False
    for env_name in _env_names_for_setting(key):
        value = os.getenv(env_name)
        if value is not None and str(value).strip():
            return True
    return False


def _env_names_for_setting(key: str) -> tuple[str, ...]:
    names = {str(key or "").upper()}
    field = Settings.model_fields.get(key)
    if field is not None:
        validation_alias = getattr(field, "validation_alias", None)
        if isinstance(validation_alias, str) and validation_alias.strip():
            names.add(validation_alias.strip())
    return tuple(sorted(names))
