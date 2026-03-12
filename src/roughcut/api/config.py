"""Runtime config API — read/write roughcut_config.json to override env vars."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from roughcut.api.options import (
    JOB_LANGUAGE_OPTIONS,
    MULTIMODAL_FALLBACK_PROVIDER_OPTIONS,
    SEARCH_FALLBACK_PROVIDER_OPTIONS,
    SEARCH_PROVIDER_OPTIONS,
    build_channel_profile_options,
)
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
    ollama_api_key_set: bool
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
    output_dir: str
    # Feature flags
    fact_check_enabled: bool
    auto_confirm_content_profile: bool
    content_profile_review_threshold: float
    auto_accept_glossary_corrections: bool
    glossary_correction_review_threshold: float
    auto_select_cover_variant: bool
    cover_selection_review_gap: float
    packaging_selection_review_gap: float
    packaging_selection_min_score: float
    # Overrides currently stored
    overrides: dict


class ConfigOptionsOut(BaseModel):
    job_languages: list[dict[str, str]]
    channel_profiles: list[dict[str, str]]
    transcription_models: dict[str, list[str]]
    multimodal_fallback_providers: list[dict[str, str]]
    search_providers: list[dict[str, str]]
    search_fallback_providers: list[dict[str, str]]


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
    ollama_api_key: str | None = None
    ollama_base_url: str | None = None
    max_upload_size_mb: int | None = None
    max_video_duration_sec: int | None = None
    ffmpeg_timeout_sec: int | None = None
    allowed_extensions: list[str] | None = None
    output_dir: str | None = None
    fact_check_enabled: bool | None = None
    auto_confirm_content_profile: bool | None = None
    content_profile_review_threshold: float | None = None
    auto_accept_glossary_corrections: bool | None = None
    glossary_correction_review_threshold: float | None = None
    auto_select_cover_variant: bool | None = None
    cover_selection_review_gap: float | None = None
    packaging_selection_review_gap: float | None = None
    packaging_selection_min_score: float | None = None


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
        ollama_api_key_set=bool(s.ollama_api_key),
        openai_api_key_set=bool(s.openai_api_key),
        anthropic_api_key_set=bool(s.anthropic_api_key),
        minimax_api_key_set=bool(s.minimax_api_key),
        ollama_base_url=s.ollama_base_url,
        max_upload_size_mb=s.max_upload_size_mb,
        max_video_duration_sec=s.max_video_duration_sec,
        ffmpeg_timeout_sec=s.ffmpeg_timeout_sec,
        allowed_extensions=s.allowed_extensions,
        output_dir=s.output_dir,
        fact_check_enabled=s.fact_check_enabled,
        auto_confirm_content_profile=s.auto_confirm_content_profile,
        content_profile_review_threshold=s.content_profile_review_threshold,
        auto_accept_glossary_corrections=s.auto_accept_glossary_corrections,
        glossary_correction_review_threshold=s.glossary_correction_review_threshold,
        auto_select_cover_variant=s.auto_select_cover_variant,
        cover_selection_review_gap=s.cover_selection_review_gap,
        packaging_selection_review_gap=s.packaging_selection_review_gap,
        packaging_selection_min_score=s.packaging_selection_min_score,
        overrides=overrides,
    )


@router.get("/options", response_model=ConfigOptionsOut)
def get_config_options():
    return ConfigOptionsOut(
        job_languages=JOB_LANGUAGE_OPTIONS,
        channel_profiles=build_channel_profile_options(),
        transcription_models={
            "local_whisper": [
                "base",
                "small",
                "medium",
                "large-v3",
                "distil-large-v3",
            ],
            "openai": [
                "gpt-4o-transcribe",
            ],
        },
        multimodal_fallback_providers=MULTIMODAL_FALLBACK_PROVIDER_OPTIONS,
        search_providers=SEARCH_PROVIDER_OPTIONS,
        search_fallback_providers=SEARCH_FALLBACK_PROVIDER_OPTIONS,
    )


@router.patch("", response_model=ConfigOut)
def patch_config(body: ConfigPatch):
    overrides = _load_overrides()

    updates = body.model_dump(exclude_none=True)
    if "output_dir" in updates:
        output_dir = str(updates["output_dir"]).strip()
        if not output_dir:
            raise HTTPException(status_code=400, detail="output_dir cannot be empty")
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        updates["output_dir"] = output_dir
    if "content_profile_review_threshold" in updates:
        updates["content_profile_review_threshold"] = max(
            0.0,
            min(1.0, float(updates["content_profile_review_threshold"])),
        )
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
