from __future__ import annotations

import copy
import re
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
DEFAULT_HYPERFRAMES_OPTIONS["progress_bar"] = False
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
    chapter_analysis: dict[str, Any] | None = None,
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
        "chapter_analysis": copy.deepcopy(chapter_analysis or {}),
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
        "chapter_cards",
    ]
    if resolved_options["progress_bar"]:
        tracks.append("progress_bar")
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
    chapter_analysis: dict[str, Any] | None = None,
    section_choreography: dict[str, Any] | None = None,
    audio_cues: Sequence[dict[str, Any]] | None = None,
    options: dict[str, Any] | None = None,
    source: str = "roughcut.media.render",
) -> dict[str, Any]:
    static_plan = build_static_packaging_plan(
        subtitles_plan=subtitles_plan,
        editing_accents=editing_accents,
        focus_plan=focus_plan,
        chapter_analysis=chapter_analysis,
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
    chapter_segments = _resolve_chapter_segments(
        chapter_analysis=chapter_analysis or metadata.get("chapter_analysis") or {},
        focus_plan=focus_plan or {},
        subtitle_items=subtitle_items or [],
        section_choreography=section_choreography or {},
        duration_sec=duration_sec,
    )
    metadata["chapters"] = {
        "segments": copy.deepcopy(chapter_segments),
        "source": chapter_segments[0].get("source") if chapter_segments else "",
    }
    elements: list[dict[str, Any]] = []
    if resolved_options["subtitle_emphasis"]:
        elements.extend(_subtitle_emphasis_elements(subtitle_items or [], width=width, height=height))
    if resolved_options["chapter_cards"]:
        elements.extend(_chapter_card_elements(chapter_segments, duration_sec=duration_sec, width=width, height=height))
    if resolved_options["progress_bar"]:
        progress_element = shape_element(
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
        progress_element["segments"] = copy.deepcopy(chapter_segments)
        elements.append(progress_element)
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


def chapter_segments(plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not is_hyperframes_plan(plan):
        return []
    metadata = _metadata_dict(plan)
    chapters = metadata.get("chapters") if isinstance(metadata.get("chapters"), dict) else {}
    segments = [
        dict(item)
        for item in list((chapters or {}).get("segments") or [])
        if isinstance(item, dict)
    ]
    if segments:
        return segments
    for element in list(plan.get("elements") or []):
        if not isinstance(element, dict):
            continue
        if str(element.get("track") or "") != "progress_bar":
            continue
        return [
            dict(item)
            for item in list(element.get("segments") or [])
            if isinstance(item, dict)
        ]
    return []


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
    chapter_segments: Sequence[dict[str, Any]],
    *,
    duration_sec: float,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    for index, segment in enumerate([dict(item) for item in chapter_segments if isinstance(item, dict)][:8]):
        start = max(0.0, float(segment.get("start_sec", segment.get("start_time", 0.0)) or 0.0))
        segment_end = max(start + 1.4, float(segment.get("end_sec", segment.get("end_time", start + 2.8)) or start + 2.8))
        end = min(segment_end, max(start + 0.01, float(duration_sec or segment_end)))
        title = str(segment.get("title") or segment.get("text") or "").strip()[:18]
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


def _resolve_chapter_segments(
    *,
    chapter_analysis: dict[str, Any],
    focus_plan: dict[str, Any],
    subtitle_items: Sequence[dict[str, Any]],
    section_choreography: dict[str, Any],
    duration_sec: float,
) -> list[dict[str, Any]]:
    duration = max(0.0, float(duration_sec or 0.0))
    candidates = [
        _chapter_segments_from_chapter_analysis(chapter_analysis, duration_sec=duration),
        _chapter_segments_from_subtitles(subtitle_items, duration_sec=duration),
        _chapter_segments_from_section_choreography(section_choreography, duration_sec=duration),
        _chapter_segments_from_focus_cards(focus_plan, duration_sec=duration),
        _chapter_segments_from_subtitle_timeline(subtitle_items, duration_sec=duration),
    ]
    for segments in candidates:
        normalized = _normalize_chapter_segments(segments, duration_sec=duration)
        if len(normalized) >= 2:
            return normalized[:8]
    for segments in candidates:
        normalized = _normalize_chapter_segments(segments, duration_sec=duration)
        if normalized:
            return normalized[:8]
    return []


def _chapter_segments_from_chapter_analysis(
    chapter_analysis: dict[str, Any],
    *,
    duration_sec: float,
) -> list[dict[str, Any]]:
    if not isinstance(chapter_analysis, dict):
        return []
    chapters = chapter_analysis.get("chapters")
    if not isinstance(chapters, list):
        return []
    segments: list[dict[str, Any]] = []
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        start = max(0.0, float(chapter.get("start_sec", chapter.get("start_time", 0.0)) or 0.0))
        end = max(start, float(chapter.get("end_sec", chapter.get("end_time", start)) or start))
        if duration_sec > 0:
            start = min(start, duration_sec)
            end = min(max(start, end), duration_sec)
        title = _chapter_title_from_payload(chapter, role="semantic_topic")
        if not title:
            continue
        segments.append(
            {
                "start_sec": round(start, 3),
                "end_sec": round(end, 3),
                "role": str(chapter.get("role") or "semantic_topic"),
                "title": title,
                "source": str(chapter.get("source") or chapter_analysis.get("source") or "llm_chapter_analysis"),
            }
        )
    return segments


def _chapter_segments_from_subtitles(
    subtitle_items: Sequence[dict[str, Any]],
    *,
    duration_sec: float,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for item in sorted(
        [dict(raw) for raw in subtitle_items if isinstance(raw, dict)],
        key=lambda raw: float(raw.get("start_time", 0.0) or 0.0),
    ):
        start = max(0.0, float(item.get("start_time", 0.0) or 0.0))
        end = max(start, float(item.get("end_time", start) or start))
        if end <= start:
            continue
        role = str(
            item.get("subtitle_section_role")
            or item.get("section_role")
            or item.get("role")
            or ""
        ).strip().lower()
        if not role:
            continue
        title = _chapter_title_from_payload(item, role=role)
        if not groups or str(groups[-1].get("role") or "") != role or start - float(groups[-1].get("end_sec", 0.0) or 0.0) > 3.2:
            groups.append(
                {
                    "start_sec": round(start, 3),
                    "end_sec": round(end, 3),
                    "role": role,
                    "title": title,
                    "source": "subtitle_section_roles",
                }
            )
            continue
        groups[-1]["end_sec"] = round(max(float(groups[-1].get("end_sec", 0.0) or 0.0), end), 3)
    if groups and duration_sec > 0:
        groups[-1]["end_sec"] = min(duration_sec, max(float(groups[-1]["end_sec"]), duration_sec))
    return groups


def _chapter_segments_from_subtitle_timeline(
    subtitle_items: Sequence[dict[str, Any]],
    *,
    duration_sec: float,
) -> list[dict[str, Any]]:
    items = [
        dict(raw)
        for raw in subtitle_items
        if isinstance(raw, dict) and _clean_chapter_title(subtitle_display_rule_text(raw))
    ]
    if not items:
        return []
    items.sort(key=lambda raw: float(raw.get("start_time", 0.0) or 0.0))
    first_start = max(0.0, float(items[0].get("start_time", 0.0) or 0.0))
    last_end = max(
        first_start,
        max(float(item.get("end_time", item.get("start_time", 0.0)) or item.get("start_time", 0.0) or 0.0) for item in items),
    )
    duration = max(duration_sec, last_end)
    if duration <= 0:
        return []
    target_count = max(1, min(6, int(round(duration / 45.0)) or 1))
    if len(items) >= 8 and target_count < 3:
        target_count = 3
    elif len(items) >= 4 and target_count < 2:
        target_count = 2
    if len(items) < 3:
        target_count = 1

    segments: list[dict[str, Any]] = []
    for index in range(target_count):
        start = first_start + ((duration - first_start) * index / target_count)
        end = first_start + ((duration - first_start) * (index + 1) / target_count)
        bucket = [
            item for item in items
            if _subtitle_midpoint(item) >= start - 1e-6 and _subtitle_midpoint(item) < end + 1e-6
        ]
        if not bucket:
            continue
        segment_start = max(0.0, float(bucket[0].get("start_time", start) or start))
        segment_end = max(segment_start, float(bucket[-1].get("end_time", end) or end))
        if index == target_count - 1 and duration_sec > 0:
            segment_end = max(segment_end, duration_sec)
        title = _chapter_title_from_payload(bucket[0], role="section")
        segments.append(
            {
                "start_sec": round(segment_start, 3),
                "end_sec": round(segment_end, 3),
                "role": "section",
                "title": title,
                "source": "subtitle_timeline_fallback",
            }
        )
    return segments


def _subtitle_midpoint(item: dict[str, Any]) -> float:
    start = float(item.get("start_time", 0.0) or 0.0)
    end = float(item.get("end_time", start) or start)
    return (start + max(start, end)) / 2.0


def _chapter_segments_from_section_choreography(
    section_choreography: dict[str, Any],
    *,
    duration_sec: float,
) -> list[dict[str, Any]]:
    sections = [dict(item) for item in list((section_choreography or {}).get("sections") or []) if isinstance(item, dict)]
    if not sections:
        return []
    max_end = max((float(item.get("end_sec", item.get("end_time", 0.0)) or 0.0) for item in sections), default=0.0)
    scale = 1.0
    if duration_sec > 0 and max_end > duration_sec + 1.0:
        scale = duration_sec / max_end
    segments: list[dict[str, Any]] = []
    for section in sections:
        start = max(0.0, float(section.get("start_sec", section.get("start_time", 0.0)) or 0.0) * scale)
        end = max(start, float(section.get("end_sec", section.get("end_time", start)) or start) * scale)
        role = str(section.get("role") or section.get("packaging_intent") or "").strip().lower()
        segments.append(
            {
                "start_sec": round(start, 3),
                "end_sec": round(end, 3),
                "role": role,
                "title": _chapter_title_from_payload(section, role=role),
                "source": "section_choreography",
            }
        )
    return segments


def _chapter_segments_from_focus_cards(
    focus_plan: dict[str, Any],
    *,
    duration_sec: float,
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for card in [dict(item) for item in list((focus_plan or {}).get("chapter_cards") or []) if isinstance(item, dict)]:
        start = max(0.0, float(card.get("start_time", card.get("start_sec", 0.0)) or 0.0))
        end = max(start + 1.2, float(card.get("end_time", card.get("end_sec", start + 2.2)) or start + 2.2))
        if duration_sec > 0:
            end = min(end, duration_sec)
        role = str(card.get("role") or card.get("card_type") or "").strip().lower()
        segments.append(
            {
                "start_sec": round(start, 3),
                "end_sec": round(end, 3),
                "role": role,
                "title": _chapter_title_from_payload(card, role=role),
                "source": "focus_chapter_cards",
            }
        )
    return segments


def _normalize_chapter_segments(
    segments: Sequence[dict[str, Any]],
    *,
    duration_sec: float,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    duration = max(0.0, float(duration_sec or 0.0))
    for raw in sorted([dict(item) for item in segments if isinstance(item, dict)], key=lambda item: float(item.get("start_sec", 0.0) or 0.0)):
        start = max(0.0, float(raw.get("start_sec", raw.get("start_time", 0.0)) or 0.0))
        end = max(start, float(raw.get("end_sec", raw.get("end_time", start)) or start))
        if duration > 0:
            start = min(start, duration)
            end = min(max(end, start), duration)
        if end - start < 0.55:
            continue
        role = str(raw.get("role") or "").strip().lower()
        title = _chapter_title_from_payload(raw, role=role)
        if not title:
            continue
        if normalized and start < float(normalized[-1]["end_sec"]):
            start = float(normalized[-1]["end_sec"])
        if end - start < 0.55:
            continue
        normalized.append(
            {
                "start_sec": round(start, 3),
                "end_sec": round(end, 3),
                "title": title,
                "role": role,
                "source": str(raw.get("source") or ""),
            }
        )
    return normalized


_CHAPTER_TITLE_KEYS = (
    "title_short",
    "short_title",
    "title",
    "chapter_title",
    "heading",
    "headline",
    "name",
    "label",
    "topic",
    "display_text",
    "text",
    "text_final",
    "text_norm",
    "text_raw",
    "section_title",
)


def _chapter_title_from_payload(payload: dict[str, Any], *, role: str) -> str:
    for key in _CHAPTER_TITLE_KEYS:
        text = _clean_chapter_title(payload.get(key))
        if text:
            return text
    subtitle_text = _clean_chapter_title(subtitle_display_rule_text(payload))
    return subtitle_text or _chapter_title(role=role)


def _clean_chapter_title(value: Any) -> str:
    if value is None:
        return ""
    text = _normalize_chapter_title_text(value)
    return _clean_llm_chapter_title(text)


_CHAPTER_TITLE_SENTENCE_MARKERS = (
    "这个",
    "那个",
    "就是",
    "然后",
    "但是",
    "所以",
    "因为",
    "可能",
    "其实",
    "感觉",
    "我觉得",
    "可以说",
    "本质上",
)


def _clean_llm_chapter_title(value: Any) -> str:
    text = _normalize_chapter_title_text(value)
    if not text:
        return ""
    if not _chapter_title_looks_like_sentence(text) and _chapter_title_visual_units(text) <= 8.0:
        return text
    if _chapter_title_looks_like_sentence(text):
        return ""
    return _clip_chapter_title(text)


def _normalize_chapter_title_text(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or ""))
    text = re.sub(r"[\"'“”‘’《》【】\[\]()（）]", "", text)
    return text.strip(" -_：:，,。.;；！？!?")


def _chapter_title_looks_like_sentence(text: str) -> bool:
    if len(text) > 14:
        return True
    return any(marker in text for marker in _CHAPTER_TITLE_SENTENCE_MARKERS)


def _clip_chapter_title(text: str) -> str:
    normalized = _normalize_chapter_title_text(text)
    if not normalized:
        return ""
    if _chapter_title_visual_units(normalized) <= 8.0:
        return normalized
    clipped = ""
    units = 0.0
    for char in normalized:
        units += 1.0 if "\u4e00" <= char <= "\u9fff" else 0.55
        if units > 8.0:
            break
        clipped += char
    return clipped.strip(" -_：:，,。.;；！？!?")


def _chapter_title_visual_units(text: str) -> float:
    return sum(1.0 if "\u4e00" <= char <= "\u9fff" else 0.55 for char in str(text or ""))


def _chapter_title(*, role: str) -> str:
    normalized_role = str(role or "").strip().lower()
    labels = {
        "hook": "开场",
        "lead": "开场",
        "opening": "开场",
        "detail": "细节",
        "detail_support": "细节",
        "body": "展示",
        "focus": "重点",
        "action": "演示",
        "demo": "演示",
        "showcase": "展示",
        "summary": "总结",
        "conclusion": "总结",
        "cta": "总结",
        "cta_protect": "总结",
    }
    return labels.get(normalized_role, "章节")


def _normalize_element(index: int, item: dict[str, Any]) -> dict[str, Any]:
    element = dict(item)
    element.setdefault("id", f"hf_{index:04d}")
    start = max(0.0, float(element.get("start_sec") or 0.0))
    end = max(start + 0.01, float(element.get("end_sec") or start + 0.01))
    element["start_sec"] = round(start, 3)
    element["end_sec"] = round(end, 3)
    element["effects"] = [dict(effect) for effect in element.get("effects") or [] if isinstance(effect, dict)]
    return element
