from __future__ import annotations

import copy
from typing import Any, Sequence

from roughcut.edit.subtitle_surfaces import subtitle_display_rule_text


HYPERFRAMES_PLAN_SCHEMA = "roughcut.hyperframes.plan.v1"
HYPERFRAMES_ENGINE = "hyperframes"
HYPERFRAMES_RENDER_BACKEND = "ffmpeg"

HYPERFRAMES_OPTION_KEYS = (
    "smart_effects",
    "subtitle_emphasis",
    "sound_cues",
    "progress_bar",
    "chapter_cards",
    "unified_subtitle_style",
)
DEFAULT_HYPERFRAMES_OPTIONS = {key: True for key in HYPERFRAMES_OPTION_KEYS}
DEFAULT_HYPERFRAMES_SUBTITLE_STYLE = "keyword_highlight"
DEFAULT_HYPERFRAMES_SUBTITLE_MOTION_STYLE = "motion_pop"


def normalize_options(value: dict[str, Any] | None) -> dict[str, bool]:
    source = value if isinstance(value, dict) else {}
    return {
        key: bool(source[key]) if key in source else default
        for key, default in DEFAULT_HYPERFRAMES_OPTIONS.items()
    }


def build_plan(
    *,
    width: int,
    height: int,
    duration_sec: float,
    elements: Sequence[dict[str, Any]],
    source: str = "roughcut.hyperframes",
    metadata: dict[str, Any] | None = None,
    tracks: Sequence[str] | None = None,
) -> dict[str, Any]:
    normalized_elements = [_normalize_element(index, item) for index, item in enumerate(elements, start=1)]
    element_tracks = {str(item.get("track") or "overlay") for item in normalized_elements}
    declared_tracks = {str(item) for item in list(tracks or []) if str(item).strip()}
    return {
        "schema": HYPERFRAMES_PLAN_SCHEMA,
        "engine": HYPERFRAMES_ENGINE,
        "render_backend": HYPERFRAMES_RENDER_BACKEND,
        "source": source,
        "canvas": {"width": int(width), "height": int(height), "fps": 28},
        "duration_sec": round(max(0.0, float(duration_sec)), 3),
        "tracks": sorted(element_tracks | declared_tracks),
        "elements": normalized_elements,
        "element_count": len(normalized_elements),
        "effect_count": sum(len(item.get("effects") or []) for item in normalized_elements),
        "metadata": copy.deepcopy(metadata or {}),
    }


def build_static_packaging_plan(
    *,
    subtitles_plan: dict[str, Any] | None = None,
    editing_accents: dict[str, Any] | None = None,
    focus_plan: dict[str, Any] | None = None,
    audio_cues: Sequence[dict[str, Any]] | None = None,
    options: dict[str, Any] | None = None,
    source: str = "roughcut.edit.render_plan",
) -> dict[str, Any]:
    resolved_options = normalize_options(options)
    resolved_subtitles = _resolve_subtitle_metadata(subtitles_plan, options=resolved_options)
    resolved_accents = copy.deepcopy(editing_accents or {})
    metadata = {
        "options": resolved_options,
        "subtitle": resolved_subtitles,
        "effects": {
            "style": str(resolved_accents.get("style") or "smart_effect_commercial"),
            "transitions": copy.deepcopy((resolved_accents.get("transitions") or {})),
            "preserve_color": bool(resolved_accents.get("preserve_color")),
            "suppress_full_frame_color_flash": bool(resolved_accents.get("suppress_full_frame_color_flash")),
        },
        "overlay_plan": {
            "style": str(resolved_accents.get("style") or "smart_effect_commercial"),
            "emphasis_overlays": copy.deepcopy(list(resolved_accents.get("emphasis_overlays") or [])),
            "sound_effects": copy.deepcopy(list(resolved_accents.get("sound_effects") or [])),
        },
        "focus": copy.deepcopy(focus_plan or {}),
        "audio_cues": copy.deepcopy(list(audio_cues or [])),
        "render_contract": {
            "visual_timeline_owner": HYPERFRAMES_ENGINE,
            "execution_backend": HYPERFRAMES_RENDER_BACKEND,
        },
    }
    tracks = [
        "subtitles",
        "subtitle_emphasis",
        "transitions",
        "smart_effects",
        "sound_cues",
        "progress_bar",
        "chapter_cards",
    ]
    return build_plan(width=0, height=0, duration_sec=0.0, elements=[], source=source, metadata=metadata, tracks=tracks)


def build_render_plan(
    *,
    width: int,
    height: int,
    duration_sec: float,
    subtitles_plan: dict[str, Any] | None = None,
    subtitle_items: Sequence[dict[str, Any]] | None = None,
    overlay_plan: dict[str, Any] | None = None,
    editing_accents: dict[str, Any] | None = None,
    focus_plan: dict[str, Any] | None = None,
    audio_cues: Sequence[dict[str, Any]] | None = None,
    options: dict[str, Any] | None = None,
    source: str = "roughcut.media.render",
) -> dict[str, Any]:
    static_plan = build_static_packaging_plan(
        subtitles_plan=subtitles_plan,
        editing_accents=editing_accents,
        focus_plan=focus_plan,
        audio_cues=audio_cues,
        options=options,
        source=source,
    )
    metadata = copy.deepcopy(static_plan.get("metadata") or {})
    resolved_options = normalize_options(metadata.get("options"))
    resolved_overlay_plan = _merge_overlay_plan(
        metadata.get("overlay_plan"),
        overlay_plan,
        sound_cues_enabled=resolved_options["sound_cues"],
    )
    metadata["overlay_plan"] = resolved_overlay_plan
    metadata["duration_sec"] = round(max(0.0, float(duration_sec)), 3)
    metadata["canvas"] = {"width": int(width), "height": int(height)}
    elements: list[dict[str, Any]] = []
    if resolved_options["subtitle_emphasis"]:
        elements.extend(_subtitle_emphasis_elements(subtitle_items or [], width=width, height=height))
    if resolved_options["chapter_cards"]:
        elements.extend(_chapter_card_elements(focus_plan or {}, duration_sec=duration_sec, width=width, height=height))
    if resolved_options["progress_bar"]:
        elements.append(
            shape_element(
                element_id="hf_progress_bar",
                track="progress_bar",
                start_sec=0.0,
                end_sec=max(0.01, float(duration_sec or 0.0)),
                shape="progress_bar",
                style="hyperframes_progress_default",
                layer=80,
                position=(0, max(0, int(height) - 12)),
                effects=[{"type": "linear_progress", "duration_sec": round(max(0.0, float(duration_sec or 0.0)), 3)}],
            )
        )
    return build_plan(
        width=width,
        height=height,
        duration_sec=duration_sec,
        elements=elements,
        source=source,
        metadata=metadata,
        tracks=static_plan.get("tracks") or [],
    )


def is_hyperframes_plan(value: Any) -> bool:
    return isinstance(value, dict) and value.get("schema") == HYPERFRAMES_PLAN_SCHEMA and value.get("engine") == HYPERFRAMES_ENGINE


def subtitle_style_name(plan: dict[str, Any] | None, fallback: str = "bold_yellow_outline") -> str:
    subtitle = _metadata_dict(plan).get("subtitle") if isinstance(_metadata_dict(plan).get("subtitle"), dict) else {}
    return str(subtitle.get("style") or fallback or DEFAULT_HYPERFRAMES_SUBTITLE_STYLE)


def subtitle_motion_style(plan: dict[str, Any] | None, fallback: str = "motion_static") -> str:
    subtitle = _metadata_dict(plan).get("subtitle") if isinstance(_metadata_dict(plan).get("subtitle"), dict) else {}
    return str(subtitle.get("motion_style") or fallback or DEFAULT_HYPERFRAMES_SUBTITLE_MOTION_STYLE)


def unified_subtitle_style_enabled(plan: dict[str, Any] | None) -> bool:
    if not is_hyperframes_plan(plan):
        return False
    options = normalize_options(_metadata_dict(plan).get("options") if isinstance(_metadata_dict(plan).get("options"), dict) else None)
    return bool(options.get("unified_subtitle_style"))


def progress_bar_enabled(plan: dict[str, Any] | None) -> bool:
    if not is_hyperframes_plan(plan):
        return False
    options = normalize_options(_metadata_dict(plan).get("options") if isinstance(_metadata_dict(plan).get("options"), dict) else None)
    return bool(options.get("progress_bar"))


def overlay_plan_from_plan(plan: dict[str, Any] | None, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = _metadata_dict(plan)
    resolved = copy.deepcopy(metadata.get("overlay_plan") if isinstance(metadata.get("overlay_plan"), dict) else {})
    if not resolved:
        resolved = copy.deepcopy(fallback or {})
    return resolved


def effects_from_plan(plan: dict[str, Any] | None, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = _metadata_dict(plan)
    effects = copy.deepcopy(metadata.get("effects") if isinstance(metadata.get("effects"), dict) else {})
    base = copy.deepcopy(fallback or {})
    if effects.get("style"):
        base["style"] = effects["style"]
    if effects.get("transitions"):
        base["transitions"] = effects["transitions"]
    for key in ("preserve_color", "suppress_full_frame_color_flash"):
        if key in effects:
            base[key] = bool(effects[key])
    return base


def apply_subtitle_style_to_items(items: Sequence[dict[str, Any]], plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not unified_subtitle_style_enabled(plan):
        return [dict(item) for item in items if isinstance(item, dict)]
    style = subtitle_style_name(plan, DEFAULT_HYPERFRAMES_SUBTITLE_STYLE)
    motion = subtitle_motion_style(plan, DEFAULT_HYPERFRAMES_SUBTITLE_MOTION_STYLE)
    styled: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item["style_name"] = style
        item["motion_style"] = motion
        styled.append(item)
    return styled


def text_element(
    *,
    element_id: str,
    track: str,
    start_sec: float,
    end_sec: float,
    text: str,
    style: str,
    layer: int,
    position: tuple[int, int],
    effects: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": element_id,
        "kind": "text",
        "track": track,
        "layer": int(layer),
        "start_sec": round(max(0.0, float(start_sec)), 3),
        "end_sec": round(max(0.0, float(end_sec)), 3),
        "text": str(text or ""),
        "style": str(style or ""),
        "position": {"x": int(position[0]), "y": int(position[1])},
        "effects": list(effects),
    }


def shape_element(
    *,
    element_id: str,
    track: str,
    start_sec: float,
    end_sec: float,
    shape: str,
    style: str,
    layer: int,
    position: tuple[int, int],
    effects: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": element_id,
        "kind": "shape",
        "track": track,
        "layer": int(layer),
        "start_sec": round(max(0.0, float(start_sec)), 3),
        "end_sec": round(max(0.0, float(end_sec)), 3),
        "shape": str(shape or ""),
        "style": str(style or ""),
        "position": {"x": int(position[0]), "y": int(position[1])},
        "effects": list(effects),
    }


def fade_in_out(in_ms: int = 100, out_ms: int = 180) -> dict[str, Any]:
    return {"type": "fade", "in_ms": int(in_ms), "out_ms": int(out_ms)}


def pop(scale_from: float = 0.82, scale_to: float = 1.04, duration_ms: int = 220) -> dict[str, Any]:
    return {
        "type": "scale_keyframes",
        "keyframes": [
            {"time_ms": 0, "scale": round(float(scale_from), 3), "easing": "ease_out_back"},
            {"time_ms": int(duration_ms), "scale": round(float(scale_to), 3), "easing": "ease_out"},
            {"time_ms": int(duration_ms) + 160, "scale": 1.0, "easing": "ease_in_out"},
        ],
    }


def slide(from_xy: tuple[int, int], to_xy: tuple[int, int], duration_ms: int = 220) -> dict[str, Any]:
    return {
        "type": "position_keyframes",
        "keyframes": [
            {"time_ms": 0, "x": int(from_xy[0]), "y": int(from_xy[1]), "easing": "ease_out_cubic"},
            {"time_ms": int(duration_ms), "x": int(to_xy[0]), "y": int(to_xy[1]), "easing": "ease_out"},
        ],
    }


def pulse(duration_ms: int = 640) -> dict[str, Any]:
    return {
        "type": "pulse",
        "duration_ms": int(duration_ms),
        "scale": 1.06,
        "repeat": "while_visible",
    }


def _metadata_dict(plan: dict[str, Any] | None) -> dict[str, Any]:
    if not is_hyperframes_plan(plan):
        return {}
    metadata = plan.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _resolve_subtitle_metadata(subtitles_plan: dict[str, Any] | None, *, options: dict[str, bool]) -> dict[str, Any]:
    source = subtitles_plan if isinstance(subtitles_plan, dict) else {}
    style = str(source.get("style") or "").strip()
    motion = str(source.get("motion_style") or "").strip()
    if options["unified_subtitle_style"]:
        style = style or DEFAULT_HYPERFRAMES_SUBTITLE_STYLE
        motion = motion or DEFAULT_HYPERFRAMES_SUBTITLE_MOTION_STYLE
    return {
        "style": style or "bold_yellow_outline",
        "motion_style": motion or "motion_static",
        "version": int(source.get("version") or 1),
        "unified": bool(options["unified_subtitle_style"]),
        "emphasis_enabled": bool(options["subtitle_emphasis"]),
    }


def _merge_overlay_plan(
    base: dict[str, Any] | None,
    override: dict[str, Any] | None,
    *,
    sound_cues_enabled: bool,
) -> dict[str, Any]:
    resolved = copy.deepcopy(base or {})
    explicit = copy.deepcopy(override or {})
    if explicit.get("style"):
        resolved["style"] = explicit["style"]
    resolved["emphasis_overlays"] = list(explicit.get("emphasis_overlays") or resolved.get("emphasis_overlays") or [])
    sound_effects = list(explicit.get("sound_effects") or resolved.get("sound_effects") or [])
    if sound_cues_enabled and not sound_effects:
        sound_effects = _sound_effects_from_overlays(resolved["emphasis_overlays"])
    resolved["sound_effects"] = sound_effects if sound_cues_enabled else []
    return resolved


def _sound_effects_from_overlays(overlays: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, overlay in enumerate(overlays):
        if not isinstance(overlay, dict):
            continue
        start_time = max(0.0, float(overlay.get("start_time") or 0.0))
        events.append(
            {
                "start_time": round(start_time, 3),
                "duration_sec": 0.12,
                "frequency": 1180 + (index % 3) * 90,
                "volume": 0.055,
                "source": "hyperframes_emphasis",
            }
        )
    return events[:14]


def _subtitle_emphasis_elements(
    subtitle_items: Sequence[dict[str, Any]],
    *,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    for index, item in enumerate(subtitle_items):
        if not isinstance(item, dict):
            continue
        unit_role = str(item.get("subtitle_unit_role") or "").strip().lower()
        if unit_role not in {"lead", "focus", "action"}:
            continue
        text = "".join(subtitle_display_rule_text(item).split())[:14]
        if not text:
            continue
        start = max(0.0, float(item.get("start_time") or 0.0))
        end = max(start + 0.55, float(item.get("end_time") or start + 0.9))
        elements.append(
            text_element(
                element_id=f"hf_subtitle_emphasis_{index:04d}",
                track="subtitle_emphasis",
                start_sec=start,
                end_sec=end,
                text=text,
                style="keyword_sticker",
                layer=52,
                position=(int(width * 0.5), int(height * 0.2)),
                effects=[fade_in_out(90, 120), pop()],
            )
        )
    return elements[:8]


def _chapter_card_elements(
    focus_plan: dict[str, Any],
    *,
    duration_sec: float,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    cards = [
        dict(item)
        for item in list((focus_plan or {}).get("chapter_cards") or [])
        if isinstance(item, dict)
    ]
    elements: list[dict[str, Any]] = []
    for index, card in enumerate(cards[:8]):
        start = max(0.0, float(card.get("start_time", card.get("start_sec", 0.0)) or 0.0))
        end = min(max(start + 1.2, float(card.get("end_time", card.get("end_sec", start + 2.2)) or start + 2.2)), max(start + 0.01, float(duration_sec or start + 2.2)))
        title = str(card.get("title") or card.get("text") or "").strip()[:18]
        if not title:
            continue
        elements.append(
            text_element(
                element_id=f"hf_chapter_card_{index:04d}",
                track="chapter_cards",
                start_sec=start,
                end_sec=end,
                text=title,
                style="bottom_chapter_pill",
                layer=48,
                position=(max(28, int(width * 0.04)), max(36, int(height) - 82)),
                effects=[
                    fade_in_out(120, 180),
                    slide(
                        (max(28, int(width * 0.04)) - 48, max(36, int(height) - 82)),
                        (max(28, int(width * 0.04)), max(36, int(height) - 82)),
                    ),
                ],
            )
        )
    return elements


def _normalize_element(index: int, item: dict[str, Any]) -> dict[str, Any]:
    element = dict(item)
    element.setdefault("id", f"hf_{index:04d}")
    start = max(0.0, float(element.get("start_sec") or 0.0))
    end = max(start + 0.01, float(element.get("end_sec") or start + 0.01))
    element["start_sec"] = round(start, 3)
    element["end_sec"] = round(end, 3)
    element["effects"] = [dict(effect) for effect in element.get("effects") or [] if isinstance(effect, dict)]
    return element
