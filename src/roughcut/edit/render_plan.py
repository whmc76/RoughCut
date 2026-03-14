from __future__ import annotations

import copy
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.edit.presets import get_workflow_preset
from roughcut.db.models import Timeline


def build_render_plan(
    editorial_timeline_id: uuid.UUID,
    *,
    workflow_preset: str = "unboxing_default",
    subtitle_version: int = 1,
    subtitle_style: str = "bold_yellow_outline",
    subtitle_motion_style: str = "motion_static",
    smart_effect_style: str = "smart_effect_rhythm",
    cover_style: str | None = None,
    title_style: str = "preset_default",
    target_lufs: float = -14.0,
    peak_limit: float = -1.0,
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
            "style": smart_effect_style,
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
    style: str = "smart_effect_rhythm",
) -> dict[str, Any]:
    tokens = _smart_effect_tokens(style)
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
        "style": style,
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
    if plain_plan.get("editing_accents"):
        plain_plan["editing_accents"] = {
            **copy.deepcopy(plain_plan["editing_accents"]),
            "emphasis_overlays": [],
            "sound_effects": [],
        }
    else:
        plain_plan["editing_accents"] = {
            "style": "plain",
            "transitions": {
                "enabled": False,
                "transition": "none",
                "duration_sec": 0.0,
                "boundary_indexes": [],
            },
            "emphasis_overlays": [],
            "sound_effects": [],
        }
    return plain_plan


def _select_transition_boundaries(keep_segments: list[dict[str, Any]]) -> list[int]:
    candidates: list[tuple[float, int]] = []
    for idx in range(len(keep_segments) - 1):
        current = keep_segments[idx]
        following = keep_segments[idx + 1]
        current_duration = float(current.get("end", 0.0) or 0.0) - float(current.get("start", 0.0) or 0.0)
        next_duration = float(following.get("end", 0.0) or 0.0) - float(following.get("start", 0.0) or 0.0)
        removed_gap = float(following.get("start", 0.0) or 0.0) - float(current.get("end", 0.0) or 0.0)
        if current_duration < 1.6 or next_duration < 1.6:
            continue
        if removed_gap < 0.45:
            continue
        candidates.append((removed_gap, idx))
    selected = sorted(idx for _gap, idx in sorted(candidates, reverse=True)[:2])
    return selected


def _smart_effect_tokens(style: str) -> dict[str, Any]:
    mapping: dict[str, dict[str, Any]] = {
        "smart_effect_rhythm": {
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
        "smart_effect_minimal": {
            "transition": "fade",
            "transition_duration_sec": 0.1,
            "sound_duration_sec": 0.06,
            "sound_frequency": 900,
            "sound_volume": 0.018,
        },
    }
    return mapping.get(style, mapping["smart_effect_rhythm"])


def _select_emphasis_overlays(subtitle_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for item in subtitle_items:
        text = _normalize_overlay_text(item)
        if not text:
            continue
        start_time = float(item.get("start_time", 0.0) or 0.0)
        end_time = float(item.get("end_time", 0.0) or 0.0)
        duration = max(0.0, end_time - start_time)
        if duration < 0.6:
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
                    "end_time": round(min(end_time, start_time + 1.1), 3),
                },
            )
        )

    chosen: list[dict[str, Any]] = []
    for _score, overlay in sorted(candidates, key=lambda item: (-item[0], item[1]["start_time"])):
        if any(abs(overlay["start_time"] - existing["start_time"]) < 8.0 for existing in chosen):
            continue
        chosen.append(overlay)
        if len(chosen) >= 2:
            break
    return sorted(chosen, key=lambda item: item["start_time"])


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
