from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from roughcut.speech.dialects import DEFAULT_TRANSCRIPTION_DIALECT, normalize_transcription_dialect

_OVERRIDES_FILE = Path("roughcut_config.json")
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
    "qwen_asr_api_base_url",
)
TRANSCRIPTION_PROVIDER_ALIASES: dict[str, str] = {
    "fast": "faster_whisper",
    "faster-whisper": "faster_whisper",
    "local_whisper": "faster_whisper",
    "qwen3-asr": "qwen3_asr",
    "qwen3asr": "qwen3_asr",
    "qwen_asr": "qwen3_asr",
}
TRANSCRIPTION_PROVIDER_PRIORITY: tuple[str, ...] = (
    "openai",
    "qwen3_asr",
    "funasr",
    "faster_whisper",
)
TRANSCRIPTION_MODEL_OPTIONS: dict[str, list[str]] = {
    "funasr": [
        "sensevoice-small",
    ],
    "faster_whisper": [
        "large-v3",
        "base",
        "small",
        "medium",
        "distil-large-v3",
    ],
    "openai": [
        "gpt-4o-transcribe",
        "gpt-4o-mini-transcribe",
    ],
    "qwen3_asr": [
        "qwen3-asr-1.7b",
    ],
}


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
DEFAULT_TRANSCRIPTION_PROVIDER = "openai"
DEFAULT_TRANSCRIPTION_MODELS: dict[str, str] = {
    "funasr": "sensevoice-small",
    "faster_whisper": "large-v3",
    "openai": "gpt-4o-transcribe",
    "qwen3_asr": "qwen3-asr-1.7b",
}
AVATAR_PROVIDER_OPTIONS: tuple[str, ...] = ("heygem",)
VOICE_PROVIDER_OPTIONS: tuple[str, ...] = ("indextts2", "runninghub")
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
    "qwen_asr_api_base_url",
    "llm_mode",
    "reasoning_provider",
    "reasoning_model",
    "local_reasoning_model",
    "local_vision_model",
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
    transcription_provider: str = DEFAULT_TRANSCRIPTION_PROVIDER  # openai | qwen3_asr | funasr | faster_whisper
    transcription_model: str = DEFAULT_TRANSCRIPTION_MODELS[DEFAULT_TRANSCRIPTION_PROVIDER]
    transcription_dialect: str = DEFAULT_TRANSCRIPTION_DIALECT
    qwen_asr_api_base_url: str = "http://127.0.0.1:18096"
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
    transcribe_runtime_timeout_sec: int = 900
    render_step_stale_timeout_sec: int = 5400
    docker_gpu_guard_enabled: bool = True
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
    qwen_asr_docker_guard_enabled: bool = True
    qwen_asr_docker_compose_file: str = "E:/WorkSpace/asr-qwen3-asr-1.7b/docker-compose.yml"
    qwen_asr_docker_env_file: str = ""
    qwen_asr_docker_services: str = "qwen3asr,asr"
    qwen_asr_docker_idle_timeout_sec: int = 900
    funasr_auto_unload_enabled: bool = True
    funasr_idle_unload_sec: int = 600

    # Reasoning
    llm_mode: str = "performance"  # performance | local
    reasoning_provider: str = "minimax"  # openai | anthropic | minimax | ollama
    reasoning_model: str = "MiniMax-M2.7-highspeed"
    local_reasoning_model: str = "qwen3.5:9b"
    local_vision_model: str = ""
    multimodal_fallback_provider: str = "ollama"  # local backup for visual tasks
    multimodal_fallback_model: str = ""

    # Search (Phase 2)
    search_provider: str = "auto"  # auto | openai | anthropic | minimax | ollama | model | searxng
    search_fallback_provider: str = "searxng"  # openai | anthropic | minimax | ollama | model | searxng
    model_search_helper: str = ""
    searxng_url: str = "http://localhost:8080"

    # API Keys
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_auth_mode: str = "api_key"  # api_key | codex_compat
    openai_api_key_helper: str = ""
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_auth_mode: str = "api_key"  # api_key | claude_code_compat
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
    render_video_encoder: str = "auto"          # auto | libx264 | h264_nvenc
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
    telegram_agent_claude_model: str = "opus"
    telegram_agent_codex_command: str = "codex"
    telegram_agent_codex_model: str = "gpt-5.4-mini"
    telegram_agent_acp_command: str = ""
    telegram_agent_task_timeout_sec: int = 900
    telegram_agent_result_max_chars: int = 3500
    telegram_agent_state_dir: str = str((DEFAULT_OUTPUT_ROOT / "telegram-agent").as_posix())
    acp_bridge_backend: str = Field(default="codex", validation_alias="ROUGHCUT_ACP_BRIDGE_BACKEND")
    acp_bridge_fallback_backend: str = Field(default="claude", validation_alias="ROUGHCUT_ACP_BRIDGE_FALLBACK_BACKEND")
    acp_bridge_claude_model: str = Field(default="opus", validation_alias="ROUGHCUT_ACP_BRIDGE_CLAUDE_MODEL")
    acp_bridge_codex_command: str = Field(default="codex", validation_alias="ROUGHCUT_ACP_BRIDGE_CODEX_COMMAND")
    acp_bridge_codex_model: str = Field(default="gpt-5.4-mini", validation_alias="ROUGHCUT_ACP_BRIDGE_CODEX_MODEL")
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
            # Handle comma-separated string (legacy) or JSON-like
            v = v.strip()
            if not v.startswith("["):
                return [ext.strip() for ext in v.split(",")]
        return v  # type: ignore[return-value]

    @property
    def max_upload_size_bytes(self) -> int:
        if self.max_upload_size_mb <= 0:
            return 0
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def active_reasoning_provider(self) -> str:
        return "ollama" if self.llm_mode == "local" else self.reasoning_provider

    @property
    def active_reasoning_model(self) -> str:
        return self.local_reasoning_model if self.llm_mode == "local" else self.reasoning_model

    @property
    def active_vision_model(self) -> str:
        if self.llm_mode == "local":
            return self.local_vision_model or self.vision_model
        return self.vision_model or self.reasoning_model

    @property
    def active_search_provider(self) -> str:
        return self.search_provider


_settings: Settings | None = None
_session_secret_overrides: dict[str, Any] = {}


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
    legacy = _load_runtime_overrides_from_legacy_file()
    legacy_persisted, legacy_secrets = _split_runtime_overrides(legacy)
    _update_session_secret_overrides(legacy_secrets)
    try:
        from roughcut.state_store import RUNTIME_OVERRIDES_KEY, delete_setting, get_json_setting, set_json_setting

        payload = get_json_setting(RUNTIME_OVERRIDES_KEY, default=None)
        if isinstance(payload, dict):
            persisted, secrets = _split_runtime_overrides(payload)
            _update_session_secret_overrides(secrets)
            if persisted != payload:
                if persisted:
                    set_json_setting(RUNTIME_OVERRIDES_KEY, persisted)
                else:
                    delete_setting(RUNTIME_OVERRIDES_KEY)
            if legacy:
                _OVERRIDES_FILE.unlink(missing_ok=True)
            return persisted
        if legacy_persisted:
            set_json_setting(RUNTIME_OVERRIDES_KEY, legacy_persisted)
            _OVERRIDES_FILE.unlink(missing_ok=True)
            return legacy_persisted
        if legacy:
            _OVERRIDES_FILE.unlink(missing_ok=True)
        return {}
    except Exception:
        if legacy != legacy_persisted:
            if legacy_persisted:
                _OVERRIDES_FILE.write_text(json.dumps(legacy_persisted, indent=2, ensure_ascii=False), encoding="utf-8")
            else:
                _OVERRIDES_FILE.unlink(missing_ok=True)
        return legacy_persisted


def save_runtime_overrides(data: dict[str, Any]) -> None:
    persisted, secrets = _split_runtime_overrides(data)
    _update_session_secret_overrides(secrets)
    try:
        from roughcut.state_store import RUNTIME_OVERRIDES_KEY, delete_setting, set_json_setting

        if persisted:
            set_json_setting(RUNTIME_OVERRIDES_KEY, persisted)
        else:
            delete_setting(RUNTIME_OVERRIDES_KEY)
        _OVERRIDES_FILE.unlink(missing_ok=True)
    except Exception:
        if persisted:
            _OVERRIDES_FILE.write_text(json.dumps(persisted, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            _OVERRIDES_FILE.unlink(missing_ok=True)


def clear_runtime_overrides() -> None:
    global _settings
    try:
        from roughcut.state_store import RUNTIME_OVERRIDES_KEY, delete_setting

        delete_setting(RUNTIME_OVERRIDES_KEY)
    except Exception:
        pass
    _session_secret_overrides.clear()
    _OVERRIDES_FILE.unlink(missing_ok=True)
    _settings = None


def apply_runtime_overrides(updates: dict[str, Any]) -> Settings:
    filtered_updates = _strip_env_managed_updates(updates)
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
        _apply_settings_overrides(_settings, _strip_env_managed_updates(dict(updates)))
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


def _load_runtime_overrides_from_legacy_file() -> dict[str, Any]:
    if not _OVERRIDES_FILE.exists():
        return {}
    try:
        payload = json.loads(_OVERRIDES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def get_session_secret_override_keys() -> list[str]:
    return sorted(_session_secret_overrides.keys())


def _apply_settings_overrides(settings: Settings, updates: dict[str, Any]) -> None:
    for key, value in updates.items():
        if hasattr(settings, key):
            object.__setattr__(settings, key, value)


def _normalize_settings(settings: Settings) -> None:
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
