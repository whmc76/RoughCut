from __future__ import annotations

from typing import Any, Final


CapabilityState = str

CAPABILITY_KEYS: Final[tuple[str, ...]] = (
    "speech_density_trim",
    "screen_focus",
    "chapter_cards",
    "local_broll_insert",
    "local_audio_cues",
    "highlight_window_selection",
    "multi_material_assembly",
)

VALID_CAPABILITY_STATES: Final[set[str]] = {
    "auto_apply",
    "suggest",
    "manual_required",
    "disabled",
}

CAPABILITY_METADATA: Final[dict[str, dict[str, str]]] = {
    "speech_density_trim": {
        "label": "语速密度剪辑",
        "layer": "editorial",
        "description": "Speech-driven low-risk density trimming on uploaded source material.",
    },
    "screen_focus": {
        "label": "教程画面聚焦",
        "layer": "packaging",
        "description": "Focus events, local zoom, and hotspot emphasis for tutorial-style jobs.",
    },
    "chapter_cards": {
        "label": "章节卡片包装",
        "layer": "packaging",
        "description": "Section or step cards derived from local structure and transcript boundaries.",
    },
    "local_broll_insert": {
        "label": "本地插片组装",
        "layer": "packaging",
        "description": "Insert locally uploaded clips or stills into packaged variants.",
    },
    "local_audio_cues": {
        "label": "本地音乐音效",
        "layer": "packaging",
        "description": "Use locally uploaded BGM or SFX in packaged variants.",
    },
    "highlight_window_selection": {
        "label": "高光窗口提炼",
        "layer": "candidate",
        "description": "Propose highlight windows from long uploaded source material.",
    },
    "multi_material_assembly": {
        "label": "多素材组装",
        "layer": "candidate",
        "description": "Assemble multiple uploaded materials into one composed timeline.",
    },
}


def normalize_capability_state(value: Any, *, default: CapabilityState = "disabled") -> CapabilityState:
    normalized = str(value or "").strip().lower()
    if normalized in VALID_CAPABILITY_STATES:
        return normalized
    return default


def build_disabled_capability_map() -> dict[str, CapabilityState]:
    return {key: "disabled" for key in CAPABILITY_KEYS}


def build_capability_catalog() -> list[dict[str, str]]:
    return [
        {
            "key": key,
            "label": CAPABILITY_METADATA[key].get("label", key),
            "layer": CAPABILITY_METADATA[key].get("layer", ""),
            "description": CAPABILITY_METADATA[key].get("description", ""),
        }
        for key in CAPABILITY_KEYS
    ]


def normalize_capability_overrides(overrides: dict[str, Any] | None) -> dict[str, CapabilityState]:
    if not isinstance(overrides, dict):
        return {}
    normalized: dict[str, CapabilityState] = {}
    for key in CAPABILITY_KEYS:
        if key in overrides:
            normalized[key] = normalize_capability_state(overrides.get(key))
    return normalized
