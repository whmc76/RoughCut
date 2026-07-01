from __future__ import annotations

from typing import Any, Final


CapabilityState = str

CAPABILITY_KEYS: Final[tuple[str, ...]] = (
    "speech_density_trim",
    "reference_style_analysis",
    "source_media_inspection",
    "screen_focus",
    "chapter_cards",
    "stock_footage_retrieval",
    "generative_scene_plan",
    "local_broll_insert",
    "local_audio_cues",
    "soundtrack_audio_mix",
    "highlight_window_selection",
    "multi_material_assembly",
    "cost_budget_governance",
    "delivery_quality_governance",
)

VALID_CAPABILITY_STATES: Final[set[str]] = {
    "auto_apply",
    "suggest",
    "manual_required",
    "disabled",
}

CAPABILITY_METADATA: Final[dict[str, dict[str, str]]] = {
    "speech_density_trim": {
        "label": "智能自动剪辑",
        "layer": "editorial",
        "description": "Single editorial authority for speech cleanup, pacing compression, and low-risk smart delete candidates.",
    },
    "reference_style_analysis": {
        "label": "参考视频风格分析",
        "layer": "candidate",
        "description": "Analyze a reference or source clip for hook structure, pacing, scene rhythm, caption style, and reusable creative constraints.",
    },
    "source_media_inspection": {
        "label": "源素材体检",
        "layer": "candidate",
        "description": "Probe uploaded media, scene changes, keyframes, audio continuity, and production implications before edit planning.",
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
    "stock_footage_retrieval": {
        "label": "开放素材检索",
        "layer": "candidate",
        "description": "Plan retrieval of royalty-safe B-roll, stills, archive clips, and creator-approved external support material.",
    },
    "generative_scene_plan": {
        "label": "生成式分镜成片",
        "layer": "candidate",
        "description": "Turn a prompt or script into scene beats, asset requirements, generated media slots, and render-runtime constraints.",
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
    "soundtrack_audio_mix": {
        "label": "音乐音效混音",
        "layer": "audio",
        "description": "Plan narration, BGM, SFX, ducking, fades, loudness, and audio balance as one soundtrack contract.",
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
    "cost_budget_governance": {
        "label": "成本预算治理",
        "layer": "candidate",
        "description": "Estimate tool/provider cost, surface paid-vs-local tradeoffs, and require confirmation before expensive generation.",
    },
    "delivery_quality_governance": {
        "label": "交付质量门",
        "layer": "validation",
        "description": "Validate output duration, audio, frame samples, subtitle timing, delivery promises, and render diagnostics before handoff.",
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
