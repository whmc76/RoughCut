"""Runtime config API — read/write roughcut_config.json to override env vars."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from roughcut.config import get_settings

router = APIRouter(prefix="/config", tags=["config"])

_CONFIG_FILE = Path("roughcut_config.json")


def _load_overrides() -> dict:
    if _CONFIG_FILE.exists():
        try:
            return json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_overrides(data: dict) -> None:
    _CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


class ConfigOut(BaseModel):
    # Transcription
    transcription_provider: str
    transcription_model: str
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
    anthropic_base_url: str
    anthropic_auth_mode: str
    anthropic_api_key_helper: str
    minimax_base_url: str
    # Keys (masked)
    openai_api_key_set: bool
    anthropic_api_key_set: bool
    minimax_api_key_set: bool
    ollama_base_url: str
    # Security
    max_upload_size_mb: int
    max_video_duration_sec: int
    ffmpeg_timeout_sec: int
    allowed_extensions: list[str]
    # Feature flags
    fact_check_enabled: bool
    # Overrides currently stored
    overrides: dict


class ConfigOptionsOut(BaseModel):
    transcription_models: dict[str, list[str]]


class ConfigPatch(BaseModel):
    transcription_provider: str | None = None
    transcription_model: str | None = None
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
    anthropic_api_key: str | None = None
    anthropic_base_url: str | None = None
    anthropic_auth_mode: str | None = None
    anthropic_api_key_helper: str | None = None
    minimax_api_key: str | None = None
    minimax_base_url: str | None = None
    ollama_base_url: str | None = None
    max_upload_size_mb: int | None = None
    max_video_duration_sec: int | None = None
    ffmpeg_timeout_sec: int | None = None
    allowed_extensions: list[str] | None = None
    fact_check_enabled: bool | None = None


@router.get("", response_model=ConfigOut)
def get_config():
    s = get_settings()
    overrides = _load_overrides()
    return ConfigOut(
        transcription_provider=s.transcription_provider,
        transcription_model=s.transcription_model,
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
        anthropic_base_url=s.anthropic_base_url,
        anthropic_auth_mode=s.anthropic_auth_mode,
        anthropic_api_key_helper=s.anthropic_api_key_helper,
        minimax_base_url=s.minimax_base_url,
        openai_api_key_set=bool(s.openai_api_key),
        anthropic_api_key_set=bool(s.anthropic_api_key),
        minimax_api_key_set=bool(s.minimax_api_key),
        ollama_base_url=s.ollama_base_url,
        max_upload_size_mb=s.max_upload_size_mb,
        max_video_duration_sec=s.max_video_duration_sec,
        ffmpeg_timeout_sec=s.ffmpeg_timeout_sec,
        allowed_extensions=s.allowed_extensions,
        fact_check_enabled=s.fact_check_enabled,
        overrides=overrides,
    )


@router.get("/options", response_model=ConfigOptionsOut)
def get_config_options():
    return ConfigOptionsOut(
        transcription_models={
            "openai": [
                "gpt-4o-transcribe",
            ],
            "local_whisper": [
                "tiny",
                "base",
                "small",
                "medium",
                "large-v3",
                "distil-large-v3",
            ],
        }
    )


@router.patch("", response_model=ConfigOut)
def patch_config(body: ConfigPatch):
    overrides = _load_overrides()

    updates = body.model_dump(exclude_none=True)
    overrides.update(updates)
    _save_overrides(overrides)

    # Apply to current settings object so it takes effect without restart
    s = get_settings()
    for k, v in updates.items():
        if hasattr(s, k):
            object.__setattr__(s, k, v)

    return get_config()


@router.delete("/overrides", status_code=204)
def reset_config():
    """Reset all runtime overrides — revert to env vars."""
    if _CONFIG_FILE.exists():
        _CONFIG_FILE.unlink()
