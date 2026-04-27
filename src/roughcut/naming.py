from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class NamedOption:
    value: str
    label: str
    capability: str = ""

    def as_select_option(self) -> dict[str, str]:
        return {"value": self.value, "label": self.label}


TRANSCRIPTION_PROVIDER_VALUES: tuple[str, ...] = (
    "local_http_asr",
    "openai",
    "funasr",
    "faster_whisper",
)
TRANSCRIPTION_PROVIDER_ALIASES: dict[str, str] = {
    "faster-whisper": "faster_whisper",
    "local_asr": "local_http_asr",
    "local-asr": "local_http_asr",
    "local-http-asr": "local_http_asr",
}

REASONING_PROVIDER_VALUES: tuple[str, ...] = ("openai", "anthropic", "minimax", "ollama")
REASONING_PROVIDER_FALLBACK_ORDER: tuple[str, ...] = ("minimax", "openai", "anthropic", "ollama")
SEARCH_PROVIDER_VALUES: tuple[str, ...] = (
    "auto",
    *REASONING_PROVIDER_VALUES,
    "model",
    "searxng",
)
SEARCH_FALLBACK_PROVIDER_VALUES: tuple[str, ...] = tuple(
    value for value in SEARCH_PROVIDER_VALUES if value != "auto"
)
MULTIMODAL_PROVIDER_VALUES: tuple[str, ...] = REASONING_PROVIDER_VALUES

AVATAR_PROVIDER_VALUES: tuple[str, ...] = ("heygem",)
VOICE_PROVIDER_VALUES: tuple[str, ...] = ("indextts2", "runninghub")

CODING_BACKEND_VALUES: tuple[str, ...] = ("codex", "claude")
CODING_BACKEND_PROVIDER_MAP: dict[str, tuple[str, ...]] = {
    "codex": ("openai",),
    "claude": ("anthropic",),
}
DEFAULT_CODING_BACKEND_MODELS: dict[str, str] = {
    "codex": "gpt-5.4-mini",
    "claude": "opus",
}

AUTH_MODE_VALUES: tuple[str, ...] = ("api_key", "helper")
AUTH_MODE_ALIASES: dict[str, str] = {
    "codex_compat": "helper",
    "codex-helper": "helper",
    "codex_helper": "helper",
}

AVATAR_CAPABILITY_GENERATION = "avatar_generation"
AVATAR_CAPABILITY_VOICE = "voice_clone"
AVATAR_CAPABILITY_PORTRAIT = "portrait_reference"
AVATAR_CAPABILITY_PREVIEW = "preview"
AVATAR_CAPABILITY_STATUS_KEYS: tuple[str, ...] = (
    AVATAR_CAPABILITY_GENERATION,
    AVATAR_CAPABILITY_VOICE,
    AVATAR_CAPABILITY_PORTRAIT,
    AVATAR_CAPABILITY_PREVIEW,
)

PROVIDER_DISPLAY_OPTIONS: tuple[NamedOption, ...] = (
    NamedOption("anthropic", "Anthropic", "reasoning"),
    NamedOption("heygem", "HeyGem", "avatar"),
    NamedOption("indextts2", "IndexTTS2", "voice"),
    NamedOption("minimax", "MiniMax", "reasoning"),
    NamedOption("model", "模型辅助搜索", "search"),
    NamedOption("ollama", "Ollama", "reasoning"),
    NamedOption("openai", "OpenAI", "reasoning"),
    NamedOption("local_http_asr", "本地 HTTP ASR", "transcription"),
    NamedOption("runninghub", "RunningHub", "voice"),
    NamedOption("searxng", "SearXNG", "search"),
    NamedOption("funasr", "FunASR", "transcription"),
    NamedOption("faster_whisper", "Faster Whisper", "transcription"),
)

PROVIDER_LABELS: dict[str, str] = {
    option.value: option.label
    for option in PROVIDER_DISPLAY_OPTIONS
}


def normalize_choice(
    value: object,
    *,
    allowed_values: Iterable[str],
    default: str = "",
    aliases: dict[str, str] | None = None,
) -> str:
    normalized = str(value or "").strip().lower()
    if aliases:
        normalized = aliases.get(normalized, normalized)
    allowed = tuple(allowed_values)
    if normalized in allowed:
        return normalized
    return default if default in allowed or not allowed else allowed[0]


def normalize_auth_mode(value: object) -> str:
    return normalize_choice(
        value,
        allowed_values=AUTH_MODE_VALUES,
        default="api_key",
        aliases=AUTH_MODE_ALIASES,
    )


def build_named_options(values: Iterable[str], *, include_auto_label: str = "Auto") -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for value in values:
        label = include_auto_label if value == "auto" else PROVIDER_LABELS.get(value, value)
        options.append({"value": value, "label": label})
    return options


def normalize_avatar_capability_key(value: object) -> str:
    return str(value or "").strip().lower()


def normalize_avatar_capability_status(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        value = {}
    normalized: dict[str, str] = {}
    for raw_key, raw_status in value.items():
        key = normalize_avatar_capability_key(raw_key)
        if key not in AVATAR_CAPABILITY_STATUS_KEYS:
            continue
        normalized[key] = str(raw_status or "").strip().lower() or "missing"
    for key in AVATAR_CAPABILITY_STATUS_KEYS:
        normalized.setdefault(key, "missing")
    return normalized
