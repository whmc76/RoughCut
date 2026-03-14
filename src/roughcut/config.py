from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_OVERRIDES_FILE = Path("roughcut_config.json")
DEFAULT_JOB_WORKFLOW_MODE = "standard_edit"
TRANSCRIPTION_MODEL_OPTIONS: dict[str, list[str]] = {
    "funasr": [
        "sensevoice-small",
    ],
    "local_whisper": [
        "base",
        "small",
        "medium",
        "large-v3",
        "distil-large-v3",
    ],
    "openai": [
        "gpt-4o-transcribe",
        "gpt-4o-mini-transcribe",
    ],
}
DEFAULT_TRANSCRIPTION_PROVIDER = "openai"
DEFAULT_TRANSCRIPTION_MODELS: dict[str, str] = {
    "funasr": "sensevoice-small",
    "local_whisper": "base",
    "openai": "gpt-4o-transcribe",
}
AVATAR_PROVIDER_OPTIONS: tuple[str, ...] = ("heygem",)
VOICE_PROVIDER_OPTIONS: tuple[str, ...] = ("indextts2", "runninghub")


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

    # Transcription
    transcription_provider: str = DEFAULT_TRANSCRIPTION_PROVIDER  # openai | local_whisper | funasr
    transcription_model: str = DEFAULT_TRANSCRIPTION_MODELS[DEFAULT_TRANSCRIPTION_PROVIDER]

    # Reasoning
    llm_mode: str = "performance"  # performance | local
    reasoning_provider: str = "openai"  # openai | anthropic | minimax | ollama
    reasoning_model: str = "gpt-4o-mini"
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
    avatar_overlay_scale: float = 0.24

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
    allowed_extensions: list[str] = [".mp4", ".mov", ".mkv", ".avi", ".webm"]

    # Output
    output_dir: str = "data/output"
    output_name_pattern: str = "{date}_{stem}"  # {date}=YYYYMMDD, {stem}=original filename stem
    render_debug_dir: str = "logs/render-debug"
    default_job_workflow_mode: str = DEFAULT_JOB_WORKFLOW_MODE
    default_job_enhancement_modes: list[str] = []

    # Vision model (for rotation detection, cover selection)
    # Set to a vision-capable model name, e.g. "llava:13b" or "moondream" for Ollama,
    # "gpt-4o" for OpenAI. Empty string = attempt with reasoning_model.
    vision_model: str = ""

    # Subtitle style (burned into video) — neon/fluorescent: black text + green glow
    subtitle_font: str = "Microsoft YaHei"
    subtitle_font_size: int = 80                 # pt at PlayResY; increase for larger text
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

    # Feature flags
    fact_check_enabled: bool = False
    auto_confirm_content_profile: bool = True
    content_profile_review_threshold: float = 0.72
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


def normalize_transcription_settings(provider: object, model: object) -> tuple[str, str]:
    provider_value = str(provider or DEFAULT_TRANSCRIPTION_PROVIDER).strip().lower() or DEFAULT_TRANSCRIPTION_PROVIDER
    if provider_value not in TRANSCRIPTION_MODEL_OPTIONS:
        provider_value = DEFAULT_TRANSCRIPTION_PROVIDER

    model_value = str(model or "").strip()
    allowed_models = TRANSCRIPTION_MODEL_OPTIONS[provider_value]
    if model_value not in allowed_models:
        model_value = DEFAULT_TRANSCRIPTION_MODELS[provider_value]

    return provider_value, model_value


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        if _OVERRIDES_FILE.exists():
            try:
                overrides = json.loads(_OVERRIDES_FILE.read_text(encoding="utf-8"))
            except Exception:
                overrides = {}
            for key, value in overrides.items():
                if hasattr(_settings, key):
                    object.__setattr__(_settings, key, value)
        provider, model = normalize_transcription_settings(
            _settings.transcription_provider,
            _settings.transcription_model,
        )
        object.__setattr__(_settings, "transcription_provider", provider)
        object.__setattr__(_settings, "transcription_model", model)
        object.__setattr__(
            _settings,
            "default_job_workflow_mode",
            _normalize_default_workflow_mode(getattr(_settings, "default_job_workflow_mode", DEFAULT_JOB_WORKFLOW_MODE)),
        )
        object.__setattr__(
            _settings,
            "default_job_enhancement_modes",
            _normalize_default_enhancement_modes(getattr(_settings, "default_job_enhancement_modes", []) or []),
        )
    return _settings


def load_runtime_overrides() -> dict[str, Any]:
    if _OVERRIDES_FILE.exists():
        try:
            payload = json.loads(_OVERRIDES_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def save_runtime_overrides(data: dict[str, Any]) -> None:
    _OVERRIDES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def apply_runtime_overrides(updates: dict[str, Any]) -> Settings:
    overrides = load_runtime_overrides()
    overrides.update(updates)
    save_runtime_overrides(overrides)

    settings = get_settings()
    for key, value in updates.items():
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
        "default_job_workflow_mode",
        _normalize_default_workflow_mode(getattr(settings, "default_job_workflow_mode", DEFAULT_JOB_WORKFLOW_MODE)),
    )
    object.__setattr__(
        settings,
        "default_job_enhancement_modes",
        _normalize_default_enhancement_modes(getattr(settings, "default_job_enhancement_modes", []) or []),
    )
    return settings


def _normalize_default_workflow_mode(value: object) -> str:
    from roughcut.creative.modes import normalize_workflow_mode

    return normalize_workflow_mode(str(value or DEFAULT_JOB_WORKFLOW_MODE))


def _normalize_default_enhancement_modes(value: object) -> list[str]:
    from roughcut.creative.modes import normalize_enhancement_modes

    if isinstance(value, (list, tuple, set)):
        return normalize_enhancement_modes(list(value))
    return normalize_enhancement_modes([])
