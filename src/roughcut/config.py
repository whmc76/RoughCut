from __future__ import annotations

import json
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_OVERRIDES_FILE = Path("roughcut_config.json")


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
    transcription_provider: str = "openai"  # openai | local_whisper
    transcription_model: str = "gpt-4o-transcribe"

    # Reasoning
    llm_mode: str = "performance"  # performance | local
    reasoning_provider: str = "openai"  # openai | anthropic | minimax | ollama
    reasoning_model: str = "gpt-4o-mini"
    local_reasoning_model: str = "qwen3.5:9b"
    local_vision_model: str = ""
    multimodal_fallback_provider: str = "ollama"  # local backup for visual tasks
    multimodal_fallback_model: str = ""

    # Search (Phase 2)
    search_provider: str = "auto"  # auto | model | searxng
    search_fallback_provider: str = "searxng"
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
    ollama_base_url: str = "http://localhost:11434"

    # Security
    max_upload_size_mb: int = 2048
    max_video_duration_sec: int = 7200
    ffmpeg_timeout_sec: int = 600
    allowed_extensions: list[str] = [".mp4", ".mov", ".mkv", ".avi", ".webm"]

    # Output
    output_dir: str = "Y:/EDC系列/AI粗剪"
    output_name_pattern: str = "{date}_{stem}"  # {date}=YYYYMMDD, {stem}=original filename stem
    render_debug_dir: str = "logs/render-debug"

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

    # Feature flags
    fact_check_enabled: bool = False

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
        return self.search_fallback_provider if self.llm_mode == "local" else self.search_provider


_settings: Settings | None = None


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
    return _settings
