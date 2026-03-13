from __future__ import annotations

from typing import Final

from roughcut.creative.modes import (
    build_active_enhancement_mode_options,
    build_active_workflow_mode_options,
)
from roughcut.config import AVATAR_PROVIDER_OPTIONS, VOICE_PROVIDER_OPTIONS
from roughcut.edit.presets import PRESETS

DEFAULT_JOB_LANGUAGE: Final[str] = "zh-CN"

JOB_LANGUAGE_OPTIONS: Final[list[dict[str, str]]] = [
    {"value": "zh-CN", "label": "简体中文"},
    {"value": "zh-TW", "label": "繁体中文"},
    {"value": "en-US", "label": "English"},
    {"value": "ja-JP", "label": "日本语"},
    {"value": "ko-KR", "label": "한국어"},
    {"value": "de-DE", "label": "Deutsch"},
    {"value": "fr-FR", "label": "Francais"},
    {"value": "es-ES", "label": "Espanol"},
]

MULTIMODAL_FALLBACK_PROVIDER_OPTIONS: Final[list[dict[str, str]]] = [
    {"value": "openai", "label": "OpenAI"},
    {"value": "anthropic", "label": "Anthropic"},
    {"value": "minimax", "label": "MiniMax"},
    {"value": "ollama", "label": "Ollama"},
]

SEARCH_PROVIDER_OPTIONS: Final[list[dict[str, str]]] = [
    {"value": "auto", "label": "自动选择"},
    {"value": "openai", "label": "OpenAI"},
    {"value": "anthropic", "label": "Anthropic"},
    {"value": "minimax", "label": "MiniMax"},
    {"value": "ollama", "label": "Ollama"},
    {"value": "model", "label": "模型辅助搜索"},
    {"value": "searxng", "label": "SearXNG"},
]

SEARCH_FALLBACK_PROVIDER_OPTIONS: Final[list[dict[str, str]]] = [
    option for option in SEARCH_PROVIDER_OPTIONS if option["value"] != "auto"
]

_ALLOWED_JOB_LANGUAGES = {option["value"] for option in JOB_LANGUAGE_OPTIONS}
_ALLOWED_CHANNEL_PROFILES = set(PRESETS)


def build_channel_profile_options() -> list[dict[str, str]]:
    return [
        {"value": "", "label": "自动匹配"},
        *[
            {"value": preset.name, "label": f"{preset.label} ({preset.name})"}
            for preset in PRESETS.values()
        ],
    ]


def build_workflow_mode_options() -> list[dict[str, str]]:
    return build_active_workflow_mode_options()


def build_enhancement_mode_options() -> list[dict[str, str]]:
    return build_active_enhancement_mode_options()


def build_avatar_provider_options() -> list[dict[str, str]]:
    return [{"value": item, "label": item} for item in AVATAR_PROVIDER_OPTIONS]


def build_voice_provider_options() -> list[dict[str, str]]:
    return [{"value": item, "label": item} for item in VOICE_PROVIDER_OPTIONS]


def normalize_job_language(value: str | None) -> str:
    normalized = str(value or DEFAULT_JOB_LANGUAGE).strip() or DEFAULT_JOB_LANGUAGE
    if normalized not in _ALLOWED_JOB_LANGUAGES:
        raise ValueError(f"Unsupported language: {normalized}")
    return normalized


def normalize_channel_profile(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if normalized not in _ALLOWED_CHANNEL_PROFILES:
        raise ValueError(f"Unsupported channel_profile: {normalized}")
    return normalized
