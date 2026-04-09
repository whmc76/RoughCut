from __future__ import annotations

import copy
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.edit.presets import get_workflow_preset
from roughcut.db.models import Timeline

_DEFAULT_SMART_EFFECT_STYLE = "smart_effect_commercial"
_LEGACY_SMART_EFFECT_STYLE_ALIASES = {
    "smart_effect_rhythm": _DEFAULT_SMART_EFFECT_STYLE,
}
_AI_SMART_EFFECT_STYLE_VARIANTS = {
    "smart_effect_commercial": "smart_effect_commercial_ai",
    "smart_effect_punch": "smart_effect_punch_ai",
    "smart_effect_glitch": "smart_effect_glitch_ai",
    "smart_effect_cinematic": "smart_effect_cinematic_ai",
    "smart_effect_atmosphere": "smart_effect_atmosphere_ai",
    "smart_effect_minimal": "smart_effect_minimal_ai",
}


def build_render_plan(
    editorial_timeline_id: uuid.UUID,
    *,
    workflow_preset: str = "unboxing_standard",
    subtitle_version: int = 1,
    subtitle_style: str = "bold_yellow_outline",
    subtitle_motion_style: str = "motion_static",
    smart_effect_style: str = _DEFAULT_SMART_EFFECT_STYLE,
    cover_style: str | None = None,
    title_style: str = "preset_default",
    target_lufs: float = -16.0,
    peak_limit: float = -2.0,
    noise_reduction: bool = True,
    intro: dict | None = None,
    outro: dict | None = None,
    insert: dict | None = None,
    watermark: dict | None = None,
    music: dict | None = None,
    editing_accents: dict | None = None,
    creative_profile: dict[str, Any] | None = None,
    ai_director_plan: dict[str, Any] | None = None,
    avatar_commentary_plan: dict[str, Any] | None = None,
    export_resolution_mode: str = "source",
    export_resolution_preset: str = "1080p",
) -> dict:
    preset = get_workflow_preset(workflow_preset)
    resolved_effect_style = _normalize_smart_effect_style(smart_effect_style)
    return {
        "editorial_timeline_id": str(editorial_timeline_id),
        "workflow_preset": preset.name,
        "loudness": {
            "target_lufs": target_lufs,
            "peak_limit": peak_limit,
        },
        "voice_processing": {
            "noise_reduction": noise_reduction,
            "compression": "gentle",
        },
        "subtitles": {
            "style": subtitle_style,
            "motion_style": subtitle_motion_style,
            "version": subtitle_version,
        },
        "intro": intro,
        "outro": outro,
        "insert": insert,
        "watermark": watermark,
        "music": music,
        "creative_profile": creative_profile,
        "ai_director": ai_director_plan,
        "avatar_commentary": avatar_commentary_plan,
        "editing_accents": editing_accents or {
            "style": resolved_effect_style,
            "transitions": {
                "enabled": True,
                "transition": "fade",
                "duration_sec": 0.12,
                "boundary_indexes": [],
            },
            "emphasis_overlays": [],
            "sound_effects": [],
        },
        "cover": {
            "style": cover_style or preset.cover_style,
            "title_style": title_style,
            "variant_count": preset.cover_variant_count,
        },
        "delivery": {
            "resolution_mode": export_resolution_mode,
            "resolution_preset": export_resolution_preset,
        },
    }


def build_smart_editing_accents(
    *,
    keep_segments: list[dict[str, Any]],
    subtitle_items: list[dict[str, Any]],
    style: str = _DEFAULT_SMART_EFFECT_STYLE,
) -> dict[str, Any]:
    resolved_style = _normalize_smart_effect_style(style)
    tokens = _smart_effect_tokens(resolved_style)
    transition_boundaries = _select_transition_boundaries(keep_segments)
    emphasis_overlays = _select_emphasis_overlays(subtitle_items)
    sound_effects = [
        {
            "start_time": overlay["start_time"],
            "duration_sec": tokens["sound_duration_sec"],
            "frequency": tokens["sound_frequency"],
            "volume": tokens["sound_volume"],
        }
        for overlay in emphasis_overlays
    ]
    return {
        "style": resolved_style,
        "transitions": {
            "enabled": bool(transition_boundaries),
            "transition": tokens["transition"],
            "duration_sec": tokens["transition_duration_sec"],
            "boundary_indexes": transition_boundaries,
        },
        "emphasis_overlays": emphasis_overlays,
        "sound_effects": sound_effects,
    }


def build_plain_render_plan(render_plan: dict[str, Any]) -> dict[str, Any]:
    plain_plan = copy.deepcopy(render_plan)
    for key in ("intro", "outro", "insert", "watermark", "music"):
        plain_plan[key] = None
    plain_plan["subtitles"] = None
    plain_plan["avatar_commentary"] = None
    plain_plan["editing_accents"] = _build_disabled_editing_accents(
        plain_plan.get("editing_accents"),
        style="plain",
    )
    return plain_plan


def build_avatar_render_plan(render_plan: dict[str, Any]) -> dict[str, Any]:
    avatar_plan = copy.deepcopy(render_plan)
    avatar_plan["editing_accents"] = _build_disabled_editing_accents(
        avatar_plan.get("editing_accents"),
        style="avatar_focus",
    )
    return avatar_plan


def build_ai_effect_render_plan(
    render_plan: dict[str, Any],
    *,
    keep_segments: list[dict[str, Any]] | None = None,
    subtitle_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ai_plan = copy.deepcopy(render_plan)
    ai_plan["avatar_commentary"] = None
    base_effect_style = _normalize_smart_effect_style(str((ai_plan.get("editing_accents") or {}).get("style") or ""))
    subtitles = copy.deepcopy(ai_plan.get("subtitles") or {})
    if subtitles:
        subtitles["motion_style"] = _resolve_ai_effect_motion_style(
            str(subtitles.get("motion_style") or ""),
            base_style=base_effect_style,
        )
        ai_plan["subtitles"] = subtitles
    ai_plan["editing_accents"] = _build_ai_effect_editing_accents(
        ai_plan.get("editing_accents"),
        keep_segments=keep_segments or [],
        subtitle_items=subtitle_items or [],
    )
    return ai_plan


def _build_disabled_editing_accents(editing_accents: dict[str, Any] | None, *, style: str) -> dict[str, Any]:
    base = copy.deepcopy(editing_accents) if isinstance(editing_accents, dict) else {}
    transitions = copy.deepcopy(base.get("transitions") or {})
    return {
        **base,
        "style": style,
        "transitions": {
            **transitions,
            "enabled": False,
            "transition": str(transitions.get("transition") or "none"),
            "duration_sec": float(transitions.get("duration_sec") or 0.0),
            "boundary_indexes": [],
        },
        "emphasis_overlays": [],
        "sound_effects": [],
    }


def _select_transition_boundaries(
    keep_segments: list[dict[str, Any]],
    *,
    max_count: int = 2,
    min_segment_duration: float = 1.6,
    min_removed_gap: float = 0.45,
) -> list[int]:
    candidates: list[tuple[float, int]] = []
    for idx in range(len(keep_segments) - 1):
        current = keep_segments[idx]
        following = keep_segments[idx + 1]
        current_duration = float(current.get("end", 0.0) or 0.0) - float(current.get("start", 0.0) or 0.0)
        next_duration = float(following.get("end", 0.0) or 0.0) - float(following.get("start", 0.0) or 0.0)
        removed_gap = float(following.get("start", 0.0) or 0.0) - float(current.get("end", 0.0) or 0.0)
        if current_duration < min_segment_duration or next_duration < min_segment_duration:
            continue
        if removed_gap < min_removed_gap:
            continue
        candidates.append((removed_gap, idx))
    selected = sorted(idx for _gap, idx in sorted(candidates, reverse=True)[:max(0, max_count)])
    return selected


def _normalize_smart_effect_style(style: str) -> str:
    normalized = str(style or "").strip().lower()
    if not normalized:
        return _DEFAULT_SMART_EFFECT_STYLE
    return _LEGACY_SMART_EFFECT_STYLE_ALIASES.get(normalized, normalized)


def _resolve_ai_effect_style_variant(style: str) -> str:
    normalized = _normalize_smart_effect_style(style)
    if normalized in _AI_SMART_EFFECT_STYLE_VARIANTS.values():
        return normalized
    return _AI_SMART_EFFECT_STYLE_VARIANTS.get(normalized, "smart_effect_commercial_ai")


def _smart_effect_tokens(style: str) -> dict[str, Any]:
    mapping: dict[str, dict[str, Any]] = {
        _DEFAULT_SMART_EFFECT_STYLE: {
            "transition": "fade",
            "transition_duration_sec": 0.12,
            "sound_duration_sec": 0.08,
            "sound_frequency": 960,
            "sound_volume": 0.045,
        },
        "smart_effect_punch": {
            "transition": "fadeblack",
            "transition_duration_sec": 0.16,
            "sound_duration_sec": 0.11,
            "sound_frequency": 820,
            "sound_volume": 0.06,
        },
        "smart_effect_glitch": {
            "transition": "pixelize",
            "transition_duration_sec": 0.14,
            "sound_duration_sec": 0.09,
            "sound_frequency": 1320,
            "sound_volume": 0.05,
        },
        "smart_effect_cinematic": {
            "transition": "fade",
            "transition_duration_sec": 0.18,
            "sound_duration_sec": 0.07,
            "sound_frequency": 640,
            "sound_volume": 0.028,
        },
        "smart_effect_atmosphere": {
            "transition": "fade",
            "transition_duration_sec": 0.18,
            "sound_duration_sec": 0.075,
            "sound_frequency": 720,
            "sound_volume": 0.032,
        },
        "smart_effect_minimal": {
            "transition": "fade",
            "transition_duration_sec": 0.1,
            "sound_duration_sec": 0.06,
            "sound_frequency": 900,
            "sound_volume": 0.018,
        },
        "smart_effect_commercial_ai": {
            "transition": "fadeblack",
            "transition_duration_sec": 0.18,
            "sound_duration_sec": 0.11,
            "sound_frequency": 980,
            "sound_volume": 0.07,
            "transition_max_count": 7,
            "overlay_max_count": 7,
            "max_total_overlays": 12,
            "overlay_spacing_sec": 3.6,
            "overlay_max_duration_sec": 1.5,
        },
        "smart_effect_punch_ai": {
            "transition": "fadeblack",
            "transition_duration_sec": 0.18,
            "sound_duration_sec": 0.12,
            "sound_frequency": 1120,
            "sound_volume": 0.078,
            "transition_max_count": 7,
            "overlay_max_count": 7,
            "max_total_overlays": 12,
            "overlay_spacing_sec": 3.8,
            "overlay_max_duration_sec": 1.45,
        },
        "smart_effect_glitch_ai": {
            "transition": "pixelize",
            "transition_duration_sec": 0.16,
            "sound_duration_sec": 0.105,
            "sound_frequency": 1480,
            "sound_volume": 0.068,
            "transition_max_count": 8,
            "overlay_max_count": 7,
            "max_total_overlays": 12,
            "overlay_spacing_sec": 3.4,
            "overlay_max_duration_sec": 1.35,
        },
        "smart_effect_cinematic_ai": {
            "transition": "fade",
            "transition_duration_sec": 0.2,
            "sound_duration_sec": 0.085,
            "sound_frequency": 700,
            "sound_volume": 0.052,
            "transition_max_count": 6,
            "overlay_max_count": 6,
            "max_total_overlays": 10,
            "overlay_spacing_sec": 4.3,
            "overlay_max_duration_sec": 1.7,
        },
        "smart_effect_atmosphere_ai": {
            "transition": "fade",
            "transition_duration_sec": 0.18,
            "sound_duration_sec": 0.09,
            "sound_frequency": 760,
            "sound_volume": 0.056,
            "transition_max_count": 6,
            "overlay_max_count": 6,
            "max_total_overlays": 10,
            "overlay_spacing_sec": 4.1,
            "overlay_max_duration_sec": 1.65,
        },
        "smart_effect_minimal_ai": {
            "transition": "fade",
            "transition_duration_sec": 0.12,
            "sound_duration_sec": 0.075,
            "sound_frequency": 920,
            "sound_volume": 0.042,
            "transition_max_count": 5,
            "overlay_max_count": 5,
            "max_total_overlays": 8,
            "overlay_spacing_sec": 4.8,
            "overlay_max_duration_sec": 1.2,
        },
    }
    normalized = _normalize_smart_effect_style(style)
    return mapping.get(normalized, mapping[_DEFAULT_SMART_EFFECT_STYLE])


def _select_emphasis_overlays(
    subtitle_items: list[dict[str, Any]],
    *,
    max_count: int = 2,
    min_spacing_sec: float = 8.0,
    min_duration_sec: float = 0.6,
    max_duration_sec: float = 1.1,
) -> list[dict[str, Any]]:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for item in subtitle_items:
        text = _normalize_overlay_text(item)
        if not text:
            continue
        start_time = float(item.get("start_time", 0.0) or 0.0)
        end_time = float(item.get("end_time", 0.0) or 0.0)
        duration = max(0.0, end_time - start_time)
        if duration < min_duration_sec:
            continue
        score = _score_overlay_text(text, start_time=start_time)
        if score <= 0:
            continue
        candidates.append(
            (
                score,
                {
                    "text": text,
                    "start_time": round(start_time + 0.05, 3),
                    "end_time": round(min(end_time, start_time + max_duration_sec), 3),
                },
            )
        )

    chosen: list[dict[str, Any]] = []
    for _score, overlay in sorted(candidates, key=lambda item: (-item[0], item[1]["start_time"])):
        if any(abs(overlay["start_time"] - existing["start_time"]) < min_spacing_sec for existing in chosen):
            continue
        chosen.append(overlay)
        if len(chosen) >= max_count:
            break
    return sorted(chosen, key=lambda item: item["start_time"])


def _build_ai_effect_editing_accents(
    editing_accents: dict[str, Any] | None,
    *,
    keep_segments: list[dict[str, Any]],
    subtitle_items: list[dict[str, Any]],
) -> dict[str, Any]:
    base = copy.deepcopy(editing_accents) if isinstance(editing_accents, dict) else {}
    base_style = _normalize_smart_effect_style(str(base.get("style") or ""))
    effect_style = _resolve_ai_effect_style_variant(base_style)
    tokens = _smart_effect_tokens(effect_style)
    base_transitions = copy.deepcopy(base.get("transitions") or {})
    transition_boundaries = sorted(
        {
            *[
                int(index)
                for index in (base_transitions.get("boundary_indexes") or [])
                if isinstance(index, int) or str(index).lstrip("-").isdigit()
            ],
            *_select_transition_boundaries(
                keep_segments,
                max_count=int(tokens.get("transition_max_count") or 6),
                min_segment_duration=1.1,
                min_removed_gap=0.18,
            ),
        }
    )
    text_overlays = _select_emphasis_overlays(
        subtitle_items,
        max_count=int(tokens.get("overlay_max_count") or 6),
        min_spacing_sec=float(tokens.get("overlay_spacing_sec") or 4.0),
        min_duration_sec=0.45,
        max_duration_sec=float(tokens.get("overlay_max_duration_sec") or 1.45),
    )
    base_emphasis_overlays = [dict(item) for item in base.get("emphasis_overlays") or []]
    occupied_times = [
        float(item.get("start_time", 0.0) or 0.0)
        for item in [*base_emphasis_overlays, *text_overlays]
    ]
    pulse_overlays = _build_transition_pulse_overlays(
        keep_segments,
        boundary_indexes=transition_boundaries,
        occupied_times=occupied_times,
    )
    merged_overlays = _merge_ai_effect_overlays(
        base_emphasis_overlays,
        text_overlays,
        pulse_overlays,
        max_count=int(tokens.get("max_total_overlays") or 10),
    )
    sound_effects = [
        {
            "start_time": overlay["start_time"],
            "duration_sec": round(
                tokens["sound_duration_sec"] if overlay.get("text") else max(tokens["sound_duration_sec"] - 0.02, 0.08),
                3,
            ),
            "frequency": tokens["sound_frequency"] if overlay.get("text") else max(tokens["sound_frequency"] - 220, 880),
            "volume": round(
                tokens["sound_volume"] if overlay.get("text") else max(tokens["sound_volume"] - 0.012, 0.04),
                3,
            ),
        }
        for overlay in merged_overlays
    ]
    return {
        **base,
        "style": effect_style,
        "transitions": {
            **base_transitions,
            "enabled": bool(transition_boundaries),
            "transition": tokens["transition"],
            "duration_sec": tokens["transition_duration_sec"],
            "boundary_indexes": transition_boundaries,
        },
        "emphasis_overlays": merged_overlays,
        "sound_effects": sound_effects,
    }


def _merge_ai_effect_overlays(*overlay_groups: list[dict[str, Any]], max_count: int) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    for raw_overlay in sorted(
        [item for group in overlay_groups for item in group],
        key=lambda item: (float(item.get("start_time", 0.0) or 0.0), 0 if str(item.get("text") or "").strip() else 1),
    ):
        overlay = _normalize_overlay_event(raw_overlay)
        if overlay is None:
            continue
        if any(_overlay_signature(overlay) == _overlay_signature(existing) for existing in chosen):
            continue
        chosen.append(overlay)
        if len(chosen) >= max_count:
            break
    return chosen


def _normalize_overlay_event(item: dict[str, Any]) -> dict[str, Any] | None:
    start_time = max(0.0, float(item.get("start_time", 0.0) or 0.0))
    end_time = max(start_time + 0.24, float(item.get("end_time", start_time + 0.42) or start_time + 0.42))
    text = "".join(str(item.get("text") or "").split())[:18]
    if not text and not item.get("allow_empty", True):
        return None
    return {
        "text": text,
        "start_time": round(start_time, 3),
        "end_time": round(end_time, 3),
    }


def _overlay_signature(item: dict[str, Any]) -> tuple[str, float]:
    return str(item.get("text") or ""), round(float(item.get("start_time", 0.0) or 0.0), 2)


def _build_transition_pulse_overlays(
    keep_segments: list[dict[str, Any]],
    *,
    boundary_indexes: list[int],
    occupied_times: list[float],
) -> list[dict[str, Any]]:
    pulses: list[dict[str, Any]] = []
    elapsed = 0.0
    boundary_set = set(boundary_indexes)
    occupied = [float(value) for value in occupied_times]
    for index, segment in enumerate(keep_segments[:-1]):
        duration = max(0.0, float(segment.get("end", 0.0) or 0.0) - float(segment.get("start", 0.0) or 0.0))
        elapsed += duration
        if index not in boundary_set:
            continue
        start_time = round(max(0.0, elapsed - 0.08), 3)
        if any(abs(start_time - existing_time) < 1.8 for existing_time in occupied):
            continue
        pulses.append(
            {
                "text": "",
                "start_time": start_time,
                "end_time": round(start_time + 0.42, 3),
            }
        )
    return pulses


def _resolve_ai_effect_motion_style(current_motion_style: str, *, base_style: str) -> str:
    del current_motion_style
    mapping = {
        "smart_effect_commercial": "motion_strobe",
        "smart_effect_punch": "motion_pop",
        "smart_effect_glitch": "motion_glitch",
        "smart_effect_cinematic": "motion_echo",
        "smart_effect_atmosphere": "motion_ripple",
        "smart_effect_minimal": "motion_slide",
    }
    return mapping.get(_normalize_smart_effect_style(base_style), "motion_strobe")


def _normalize_overlay_text(item: dict[str, Any]) -> str:
    raw = str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
    text = "".join(raw.split())
    text = text.strip("，。！？!?、,.；;：:\"'()（）[]【】")
    if len(text) < 4 or len(text) > 18:
        return ""
    return text[:18]


def _score_overlay_text(text: str, *, start_time: float) -> float:
    score = 0.0
    keywords = ("重点", "关键", "注意", "提醒", "一定", "终于", "真的", "直接", "千万", "别")
    if any(keyword in text for keyword in keywords):
        score += 2.5
    if any(ch.isdigit() for ch in text):
        score += 1.5
    if any(ch.isascii() and ch.isalpha() and ch.isupper() for ch in text):
        score += 1.0
    if start_time <= 12.0:
        score += 1.0
    if len(text) <= 10:
        score += 1.0
    if "?" in text or "？" in text or "!" in text or "！" in text:
        score += 1.0
    return score


async def save_render_plan(
    job_id: uuid.UUID,
    render_plan: dict,
    session: AsyncSession,
    version: int | None = None,
) -> Timeline:
    if version is None:
        result = await session.execute(
            select(func.max(Timeline.version)).where(
                Timeline.job_id == job_id,
                Timeline.timeline_type == "render_plan",
            )
        )
        version = int(result.scalar() or 0) + 1
    timeline = Timeline(
        job_id=job_id,
        version=version,
        timeline_type="render_plan",
        data_json=render_plan,
    )
    session.add(timeline)
    await session.flush()
    return timeline
