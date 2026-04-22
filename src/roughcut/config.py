from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
import shutil
import sys
from typing import Any

from pydantic import Field, ValidationInfo, field_validator
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
from roughcut.speech.dialects import DEFAULT_TRANSCRIPTION_DIALECT, normalize_transcription_dialect

DEFAULT_JOB_WORKFLOW_MODE = "standard_edit"
DEFAULT_OUTPUT_ROOT = Path(os.getenv("ROUGHCUT_OUTPUT_ROOT", "F:/roughcut_outputs")).expanduser()
DEFAULT_TEST_OUTPUT_ROOT = Path(
    os.getenv("ROUGHCUT_TEST_OUTPUT_ROOT", str((DEFAULT_OUTPUT_ROOT / "tests").as_posix()))
).expanduser()
DEFAULT_HEYGEM_SHARED_ROOT = Path(
    os.getenv("HEYGEM_SHARED_ROOT", str((DEFAULT_OUTPUT_ROOT / "heygem").as_posix()))
).expanduser()
DEFAULT_HEYGEM_VOICE_ROOT = Path(
    os.getenv("HEYGEM_VOICE_ROOT", str((DEFAULT_OUTPUT_ROOT / "voice_refs").as_posix()))
).expanduser()
SECRET_SETTINGS: tuple[str, ...] = (
    "openai_api_key",
    "anthropic_api_key",
    "minimax_api_key",
    "minimax_coding_plan_api_key",
    "ollama_api_key",
    "avatar_api_key",
    "voice_clone_api_key",
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
        "local-asr-current",
    ],
}
MULTIMODAL_FALLBACK_PROVIDER_VALUES: tuple[str, ...] = MULTIMODAL_PROVIDER_VALUES
HYBRID_REASONING_PROVIDER_VALUES: tuple[str, ...] = REASONING_PROVIDER_VALUES
LLM_ROUTING_MODE_VALUES: tuple[str, ...] = ("bundled", "hybrid_performance")
HYBRID_SEARCH_MODE_VALUES: tuple[str, ...] = ("off", "entity_gated", "follow_provider")
REASONING_EFFORT_VALUES: tuple[str, ...] = ("minimal", "low", "medium", "high")
DEFAULT_REASONING_PROVIDER = "openai"
DEFAULT_REASONING_MODEL = "gpt-5.4"
DEFAULT_BACKUP_REASONING_PROVIDER = "openai"
DEFAULT_BACKUP_REASONING_MODEL = "gpt-5.4-mini"
DEFAULT_BACKUP_VISION_MODEL = "gpt-5.4-mini"
DEFAULT_HYBRID_ANALYSIS_PROVIDER = "openai"
DEFAULT_HYBRID_ANALYSIS_MODEL = "gpt-5.4"
DEFAULT_HYBRID_COPY_PROVIDER = "openai"
DEFAULT_HYBRID_COPY_MODEL = "gpt-5.4-mini"
DEFAULT_MINIMAX_REASONING_MODEL = "MiniMax-M2.7"
DEFAULT_SEARCH_FALLBACK_PROVIDER = "openai"
DEFAULT_BACKUP_SEARCH_FALLBACK_PROVIDER = "openai"
DEFAULT_MULTIMODAL_FALLBACK_PROVIDER = "openai"
DEFAULT_MULTIMODAL_FALLBACK_MODEL = "gpt-5.4-mini"
DEFAULT_MODEL_SEARCH_HELPER_PATH = Path(__file__).resolve().parents[2] / "scripts" / "codex_model_search_helper.py"
MINIMAX_REASONING_MODEL_ALIASES: dict[str, str] = {
    "minimax-m2.7-highspeed": "MiniMax-M2.7",
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
    "local_http_asr": "local-asr-current",
}
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
PROFILE_BINDABLE_SETTINGS: tuple[str, ...] = (
    "transcription_provider",
    "transcription_model",
    "transcription_dialect",
    "transcription_alignment_mode",
    "transcription_alignment_min_word_coverage",
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
    "avatar_presenter_id",
    "avatar_layout_template",
    "avatar_safe_margin",
    "avatar_overlay_scale",
    "voice_provider",
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
    "subtitle_filler_cleanup_enabled",
    "quality_auto_rerun_enabled",
    "quality_auto_rerun_below_score",
    "quality_auto_rerun_max_attempts",
    "ocr_enabled",
    "entity_graph_enabled",
    "asr_evidence_enabled",
    "research_verifier_enabled",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://roughcut:roughcut@localhost:5432/roughcut"

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
    cleanup_job_storage_on_terminal: bool = True
    cleanup_render_debug_on_terminal: bool = True
    cleanup_heygem_temp_on_terminal: bool = True

    # Transcription
    transcription_provider: str = DEFAULT_TRANSCRIPTION_PROVIDER  # local_http_asr | openai | funasr | faster_whisper
    transcription_model: str = DEFAULT_TRANSCRIPTION_MODELS[DEFAULT_TRANSCRIPTION_PROVIDER]
    transcription_dialect: str = DEFAULT_TRANSCRIPTION_DIALECT
    transcription_alignment_mode: str = "auto"  # auto | provider_only | synthetic
    transcription_alignment_min_word_coverage: float = 0.72
    local_asr_api_base_url: str = "http://127.0.0.1:6001"
    local_asr_model_name: str = "vibevoice-asr-int8"
    local_asr_display_name: str = "VibeVoice INT8"
    local_asr_health_path: str = "/health"
    local_asr_transcribe_path: str = "/transcribe"
    local_asr_hotwords_field: str = "hotwords"
    local_asr_max_new_tokens: int = 4096
    watch_auto_scan_interval_sec: int = 45
    watch_auto_settle_seconds: int = 45
    watch_auto_merge_enabled: bool = True
    watch_auto_merge_min_score: float = 0.72
    watch_auto_enqueue_enabled: bool = True
    watch_auto_max_active_jobs: int = 2
    watch_auto_max_jobs_per_root: int = 1
    gpu_retry_enabled: bool = True
    gpu_retry_base_delay_sec: int = 90
    gpu_retry_max_delay_sec: int = 900
    gpu_busy_utilization_threshold: int = 92
    gpu_busy_memory_threshold: float = 0.92
    step_heartbeat_interval_sec: int = 20
    step_stale_recovery_enabled: bool = True
    step_stale_timeout_sec: int = 900
    step_dispatch_stale_timeout_sec: int = 3600
    transcribe_runtime_timeout_sec: int = 900
    render_dispatch_concurrency: int = 1
    render_step_stale_timeout_sec: int = 5400
    render_step_prepackaging_stale_timeout_sec: int = 1500
    render_step_packaging_stale_timeout_sec: int = 2400
    runtime_preflight_docker_enabled: bool = False
    docker_gpu_guard_enabled: bool = False
    docker_gpu_guard_idle_timeout_sec: int = 900
    heygem_docker_guard_enabled: bool = True
    heygem_docker_compose_file: str = "E:/WorkSpace/heygem/docker-compose.yml"
    heygem_docker_env_file: str = "E:/WorkSpace/heygem/.env"
    heygem_docker_services: str = "heygem"
    heygem_docker_idle_timeout_sec: int = 900
    indextts2_docker_guard_enabled: bool = True
    indextts2_docker_compose_file: str = "E:/WorkSpace/indextts2-service/docker-compose.yml"
    indextts2_docker_env_file: str = "E:/WorkSpace/indextts2-service/.env"
    indextts2_docker_services: str = "indextts2"
    indextts2_docker_idle_timeout_sec: int = 900
    local_asr_docker_guard_enabled: bool = True
    local_asr_docker_compose_file: str = "E:/WorkSpace/VibeVoice-service/docker-compose.yml"
    local_asr_docker_env_file: str = "E:/WorkSpace/VibeVoice-service/.env"
    local_asr_docker_services: str = "vibevoice-asr"
    local_asr_docker_idle_timeout_sec: int = 900
    funasr_auto_unload_enabled: bool = True
    funasr_idle_unload_sec: int = 600

    # Reasoning
    llm_mode: str = "performance"  # performance | local
    llm_routing_mode: str = "bundled"  # bundled | hybrid_performance
    reasoning_provider: str = DEFAULT_REASONING_PROVIDER  # openai | anthropic | minimax | ollama
    reasoning_model: str = DEFAULT_REASONING_MODEL
    reasoning_effort: str = "medium"
    llm_backup_enabled: bool = True
    backup_reasoning_provider: str = DEFAULT_BACKUP_REASONING_PROVIDER
    backup_reasoning_model: str = DEFAULT_BACKUP_REASONING_MODEL
    backup_reasoning_effort: str = "medium"
    backup_vision_model: str = DEFAULT_BACKUP_VISION_MODEL
    backup_search_provider: str = "auto"
    backup_search_fallback_provider: str = DEFAULT_BACKUP_SEARCH_FALLBACK_PROVIDER
    backup_model_search_helper: str = ""
    local_reasoning_model: str = "qwen3.5:9b"
    local_vision_model: str = ""
    hybrid_analysis_provider: str = DEFAULT_HYBRID_ANALYSIS_PROVIDER
    hybrid_analysis_model: str = DEFAULT_HYBRID_ANALYSIS_MODEL
    hybrid_analysis_effort: str = "medium"
    hybrid_analysis_search_mode: str = "entity_gated"  # off | entity_gated | follow_provider
    hybrid_copy_provider: str = DEFAULT_HYBRID_COPY_PROVIDER
    hybrid_copy_model: str = DEFAULT_HYBRID_COPY_MODEL
    hybrid_copy_effort: str = "high"
    hybrid_copy_search_mode: str = "follow_provider"  # off | entity_gated | follow_provider
    multimodal_fallback_provider: str = DEFAULT_MULTIMODAL_FALLBACK_PROVIDER
    multimodal_fallback_model: str = DEFAULT_MULTIMODAL_FALLBACK_MODEL

    # Search (Phase 2)
    search_provider: str = "auto"  # auto | openai | anthropic | minimax | ollama | model | searxng
    search_fallback_provider: str = DEFAULT_SEARCH_FALLBACK_PROVIDER  # openai | anthropic | minimax | ollama | model | searxng
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
    voice_provider: str = "indextts2"
    voice_clone_api_base_url: str = "http://127.0.0.1:49204"
    voice_clone_api_key: str = ""
    voice_clone_voice_id: str = ""
    director_rewrite_strength: float = 0.55

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
    allowed_extensions: list[str] = [".mp4", ".mov", ".mkv", ".avi", ".webm"]

    # Output
    output_dir: str = str((DEFAULT_OUTPUT_ROOT / "output").as_posix())
    preferred_ui_language: str = "zh-CN"
    output_name_pattern: str = "{date}_{stem}"  # {date}=YYYYMMDD, {stem}=original filename stem
    render_debug_dir: str = str((DEFAULT_OUTPUT_ROOT / "render-debug").as_posix())
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
    vision_model: str = ""

    # Subtitle style (burned into video) — neon/fluorescent: black text + green glow
    subtitle_font: str = "Microsoft YaHei"
    subtitle_font_size: int = 144                # pt at PlayResY; tuned for large 1-2 line subtitles
    subtitle_color: str = "000000"               # text color RGB hex (black)
    subtitle_outline_color: str = "00FF00"       # outline/glow color RGB hex (neon green)
    subtitle_outline_width: int = 5              # outline thickness; thick = fluorescent glow

    # Cover settings
    cover_candidate_count: int = 10             # frames to sample for best-cover selection
    cover_output_variants: int = 5              # export multiple cover variants for manual selection
    cover_title: str = ""                        # manual cover title override; empty = auto-generate
    cover_title_font_path: str = "C:/Windows/Fonts/msyhbd.ttc"
    auto_select_cover_variant: bool = True
    cover_selection_review_gap: float = 0.08
    packaging_selection_review_gap: float = 0.08
    packaging_selection_min_score: float = 0.6
    edit_decision_llm_review_enabled: bool = True
    edit_decision_llm_review_max_candidates: int = 6
    edit_decision_llm_review_timeout_sec: int = 30
    edit_decision_llm_review_min_confidence: float = 0.72
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
    # Default to manual review until the strategy has verified >=90% average accuracy.
    auto_confirm_content_profile: bool = False
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
        return _normalize_reasoning_effort(self.reasoning_effort) or "medium"

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
        provider_value = DEFAULT_TRANSCRIPTION_PROVIDER
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
        return ""
    if normalized_provider != "minimax":
        return model_value
    return MINIMAX_REASONING_MODEL_ALIASES.get(model_value.lower(), model_value)


def _has_minimax_reasoning_credentials(settings: Any) -> bool:
    return bool(str(getattr(settings, "minimax_api_key", "") or "").strip())


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
        return helper_kind == "codex"
    helper_command = str(getattr(settings, "openai_api_key_helper", "") or "").strip().lower()
    return "codex" in helper_command


def _has_openai_codex_reasoning_bridge(settings: Any) -> bool:
    if not uses_codex_auth_helper(settings):
        return False
    return bool(shutil.which(_resolve_codex_bridge_command(settings)))


def _openai_responses_credentials_unavailable(settings: Any) -> bool:
    direct_key = str(getattr(settings, "openai_api_key", "") or "").strip()
    return uses_codex_auth_helper(settings) and not direct_key and not _has_openai_codex_reasoning_bridge(settings)


def _openai_responses_route_likely_unavailable(settings: Any) -> bool:
    provider = str(getattr(settings, "active_reasoning_provider", "") or getattr(settings, "reasoning_provider", "")).strip().lower()
    return provider == "openai" and _openai_responses_credentials_unavailable(settings)


def resolve_transcription_provider_plan(provider: object, model: object) -> list[tuple[str, str]]:
    provider_value, model_value = normalize_transcription_settings(provider, model)
    try:
        start_index = TRANSCRIPTION_PROVIDER_PRIORITY.index(provider_value)
    except ValueError:
        start_index = 0

    plan: list[tuple[str, str]] = []
    for index, candidate in enumerate(TRANSCRIPTION_PROVIDER_PRIORITY):
        if index < start_index:
            continue
        candidate_model = model_value if candidate == provider_value else DEFAULT_TRANSCRIPTION_MODELS[candidate]
        plan.append((candidate, candidate_model))
    return plan


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

    for key in ("openai_auth_mode", "anthropic_auth_mode"):
        if key in normalized:
            normalized[key] = normalize_auth_mode(normalized.get(key))

    if "llm_routing_mode" in normalized:
        routing_mode = str(normalized.get("llm_routing_mode") or "").strip().lower()
        normalized["llm_routing_mode"] = routing_mode if routing_mode in LLM_ROUTING_MODE_VALUES else "bundled"

    if "search_provider" in normalized:
        normalized["search_provider"] = "auto"

    if "search_fallback_provider" in normalized:
        fallback = str(normalized.get("search_fallback_provider") or "").strip().lower()
        normalized["search_fallback_provider"] = (
            fallback if fallback in SEARCH_FALLBACK_PROVIDER_VALUES else "searxng"
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

    for key in ("reasoning_effort", "backup_reasoning_effort", "hybrid_analysis_effort", "hybrid_copy_effort"):
        if key in normalized:
            normalized[key] = _normalize_reasoning_effort(normalized.get(key)) or (
                "high" if key == "hybrid_copy_effort" else "medium"
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
    ):
        if key in normalized:
            normalized[key] = str(normalized.get(key) or "").strip()

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

    return normalized


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
        _normalize_reasoning_effort(getattr(settings, "hybrid_analysis_effort", "medium")) or "medium",
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
        _normalize_reasoning_effort(getattr(settings, "reasoning_effort", "medium")) or "medium",
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
        _normalize_reasoning_effort(getattr(settings, "backup_reasoning_effort", "medium")) or "medium",
    )
    object.__setattr__(
        settings,
        "backup_vision_model",
        str(getattr(settings, "backup_vision_model", "") or "").strip() or DEFAULT_BACKUP_VISION_MODEL,
    )
    backup_search_provider = str(getattr(settings, "backup_search_provider", "") or "").strip().lower()
    if backup_search_provider not in SEARCH_PROVIDER_VALUES:
        backup_search_provider = "auto"
    object.__setattr__(settings, "backup_search_provider", backup_search_provider)
    backup_search_fallback = str(getattr(settings, "backup_search_fallback_provider", "") or "").strip().lower()
    if backup_search_fallback not in SEARCH_FALLBACK_PROVIDER_VALUES:
        backup_search_fallback = DEFAULT_BACKUP_SEARCH_FALLBACK_PROVIDER
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
    object.__setattr__(settings, "search_provider", "auto")
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
        "reasoning_effort": _normalize_reasoning_effort(getattr(current, "backup_reasoning_effort", "medium")) or "medium",
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
        if (
            selected_provider == "openai"
            and _openai_responses_route_likely_unavailable(current)
            and _has_minimax_reasoning_credentials(current)
        ):
            selected_provider = "minimax"
            selected_model = DEFAULT_MINIMAX_REASONING_MODEL
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
        selected_provider = str(
            getattr(current, "hybrid_copy_provider", DEFAULT_HYBRID_COPY_PROVIDER)
            or DEFAULT_HYBRID_COPY_PROVIDER
        ).strip().lower()
        selected_model = str(
            getattr(current, "hybrid_copy_model", DEFAULT_HYBRID_COPY_MODEL)
            or DEFAULT_HYBRID_COPY_MODEL
        ).strip()
        if (
            selected_provider == "openai"
            and _openai_responses_route_likely_unavailable(current)
            and _has_minimax_reasoning_credentials(current)
        ):
            selected_provider = "minimax"
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
