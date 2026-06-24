from __future__ import annotations

import copy
import re
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.edit.presets import get_workflow_preset, normalize_workflow_template_name
from roughcut.edit.strategy_review_context import strategy_review_context_from_profile
from roughcut.edit.subtitle_surfaces import subtitle_display_rule_text
from roughcut.db.models import Timeline
from roughcut.edit.local_audio_cues import normalize_local_music_plan
from roughcut.edit.local_insert_plan import normalize_local_insert_plan
from roughcut.hyperframes import build_static_packaging_plan
from roughcut.packaging.library import resolve_insert_transition_overlap

_DEFAULT_SMART_EFFECT_STYLE = "smart_effect_commercial"
_RENAMED_SMART_EFFECT_STYLE_KEYS = {
    "smart_effect_rhythm": _DEFAULT_SMART_EFFECT_STYLE,
}
_UNBOXING_WORKFLOW_PRESETS = {"unboxing_standard", "edc_tactical"}
_COLOR_SHIFTING_SMART_EFFECT_STYLES = {
    "smart_effect_glitch",
    "smart_effect_cinematic",
    "smart_effect_atmosphere",
    "smart_effect_glitch_ai",
    "smart_effect_cinematic_ai",
    "smart_effect_atmosphere_ai",
}
_PRODUCT_FIDELITY_TERMS = {
    "unboxing",
    "product",
    "product_review",
    "product_showcase",
    "review",
    "showcase",
    "gear",
    "hardware",
    "edc",
    "tool",
    "knife",
    "flashlight",
    "camera",
    "phone",
    "keyboard",
    "开箱",
    "拆箱",
    "产品",
    "展示",
    "测评",
    "评测",
    "实拍",
    "对比",
    "参数",
    "细节",
    "外观",
    "手电",
}
_CONTENT_PROFILE_EFFECT_POLICY_KEYS = (
    "content_kind",
    "video_type",
    "video_theme",
    "subject_domain",
    "subject_type",
    "summary",
    "hook_line",
)
_AI_SMART_EFFECT_STYLE_VARIANTS = {
    "smart_effect_commercial": "smart_effect_commercial_ai",
    "smart_effect_punch": "smart_effect_punch_ai",
    "smart_effect_glitch": "smart_effect_glitch_ai",
    "smart_effect_cinematic": "smart_effect_cinematic_ai",
    "smart_effect_atmosphere": "smart_effect_atmosphere_ai",
    "smart_effect_minimal": "smart_effect_minimal_ai",
}
_OVERLAY_LABEL_MAX_CJK_CHARS = 8
_OVERLAY_LABEL_MAX_ASCII_CHARS = 14
_OVERLAY_LABEL_TERMS = (
    "快拆结构",
    "锁定细节",
    "演示容量",
    "实测背负",
    "防滑纹",
    "背负系统",
    "快拆",
    "锁定",
    "演示",
    "容量",
    "对比",
    "实测",
    "背负",
    "细节",
    "功能",
    "区别",
    "开箱",
    "快开",
    "收纳",
    "肩带",
    "刀型",
    "刃材",
)
_OVERLAY_LABEL_STOP_WORDS = (
    "因为",
    "所以",
    "然后",
    "但是",
    "就是",
    "这个",
    "那个",
    "这里",
    "那边",
    "你看",
    "我们",
    "可以",
    "还是",
    "不太",
    "不算",
)
_OVERLAY_LABEL_BAD_SUFFIX_MARKERS = (
    "怎么",
    "怎样",
    "一遍",
    "一下",
    "起来",
    "进去",
    "出来",
    "过去",
    "过来",
)
_OVERLAY_LABEL_ALLOWED_SUFFIXES = (
    "结构",
    "细节",
    "方式",
    "按键",
    "过程",
    "效果",
    "功能",
    "位置",
    "体验",
    "容量",
    "背负",
)


def _render_plan_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def render_plan_workflow_preset(payload: dict[str, Any] | None, *, default: str = "unboxing_standard") -> str:
    return str(_render_plan_payload(payload).get("workflow_preset") or default)


def render_plan_loudness(payload: dict[str, Any] | None) -> dict[str, Any]:
    return copy.deepcopy(_render_plan_payload(payload).get("loudness") or {})


def render_plan_voice_processing(payload: dict[str, Any] | None) -> dict[str, Any]:
    return copy.deepcopy(_render_plan_payload(payload).get("voice_processing") or {})


def render_plan_delivery(payload: dict[str, Any] | None) -> dict[str, Any]:
    return copy.deepcopy(_render_plan_payload(payload).get("delivery") or {})


def render_plan_cover(payload: dict[str, Any] | None) -> dict[str, Any]:
    return copy.deepcopy(_render_plan_payload(payload).get("cover") or {})


def render_plan_manual_editor(payload: dict[str, Any] | None) -> dict[str, Any]:
    return copy.deepcopy(_render_plan_payload(payload).get("manual_editor") or {})


def render_plan_automatic_gate(payload: dict[str, Any] | None) -> dict[str, Any]:
    return copy.deepcopy(_render_plan_payload(payload).get("automatic_gate") or {})


def render_plan_avatar_commentary(payload: dict[str, Any] | None) -> dict[str, Any]:
    return copy.deepcopy(_render_plan_payload(payload).get("avatar_commentary") or {})


def render_plan_ai_director(payload: dict[str, Any] | None) -> dict[str, Any]:
    return copy.deepcopy(_render_plan_payload(payload).get("ai_director") or {})


def render_plan_strategy_review_context(payload: dict[str, Any] | None) -> dict[str, Any]:
    return copy.deepcopy(_render_plan_payload(payload).get("strategy_review_context") or {})


def render_plan_video_transform(payload: dict[str, Any] | None) -> dict[str, Any]:
    plan = _render_plan_payload(payload)
    manual_editor = copy.deepcopy(plan.get("manual_editor") or {})
    delivery = copy.deepcopy(plan.get("delivery") or {})
    video_transform = copy.deepcopy(manual_editor.get("video_transform") or {})
    if "aspect_ratio" not in video_transform:
        video_transform["aspect_ratio"] = delivery.get("aspect_ratio") or "source"
    if "resolution_mode" not in video_transform:
        video_transform["resolution_mode"] = delivery.get("resolution_mode") or "source"
    if "resolution_preset" not in video_transform:
        video_transform["resolution_preset"] = delivery.get("resolution_preset") or "1080p"
    return video_transform


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
    include_cover: bool = False,
    target_lufs: float = -16.0,
    peak_limit: float = -2.0,
    noise_reduction: bool = True,
    intro: dict | None = None,
    outro: dict | None = None,
    insert: dict | None = None,
    watermark: dict | None = None,
    music: dict | None = None,
    focus_plan: dict[str, Any] | None = None,
    timeline_analysis: dict[str, Any] | None = None,
    editing_skill: dict[str, Any] | None = None,
    editing_accents: dict | None = None,
    content_profile: dict[str, Any] | None = None,
    creative_profile: dict[str, Any] | None = None,
    ai_director_plan: dict[str, Any] | None = None,
    avatar_commentary_plan: dict[str, Any] | None = None,
    export_resolution_mode: str = "source",
    export_resolution_preset: str = "1080p",
    export_frame_rate_mode: str = "source",
    export_frame_rate_preset: str = "30",
) -> dict:
    preset = get_workflow_preset(workflow_preset)
    content_effect_policy = build_content_effect_policy(
        workflow_preset=preset.name,
        content_profile=content_profile,
    )
    strategy_review_context = strategy_review_context_from_profile(content_profile)
    preserve_color = bool(content_effect_policy.get("preserve_color"))
    resolved_effect_style = _resolve_workflow_smart_effect_style(
        smart_effect_style,
        workflow_preset=preset.name,
        preserve_color=preserve_color,
    )
    resolved_timeline_analysis = timeline_analysis or {}
    resolved_editing_skill = editing_skill or {}
    section_choreography = _build_section_choreography(
        timeline_analysis=resolved_timeline_analysis,
        editing_skill=resolved_editing_skill,
    )
    bound_insert = _bind_insert_to_section_choreography(
        normalize_local_insert_plan(insert),
        section_choreography=section_choreography,
    )
    bound_subtitles = _bind_subtitles_to_choreography(
        {
            "style": subtitle_style,
            "motion_style": subtitle_motion_style,
            "version": subtitle_version,
        },
        section_choreography=section_choreography,
        editing_skill=resolved_editing_skill,
    )
    if isinstance(editing_accents, dict):
        resolved_editing_accents = copy.deepcopy(editing_accents)
        resolved_editing_accents["style"] = _resolve_workflow_smart_effect_style(
            str(resolved_editing_accents.get("style") or resolved_effect_style),
            workflow_preset=preset.name,
            preserve_color=preserve_color,
        )
        if preserve_color:
            resolved_editing_accents["preserve_color"] = True
            resolved_editing_accents["suppress_full_frame_color_flash"] = bool(
                content_effect_policy.get("disallow_full_frame_color_flash")
            )
    else:
        resolved_editing_accents = {
            "style": resolved_effect_style,
            "transitions": {
                "enabled": True,
                "transition": "fade",
                "duration_sec": 0.12,
                "boundary_indexes": [],
            },
            "emphasis_overlays": [],
            "sound_effects": [],
        }
        if preserve_color:
            resolved_editing_accents["preserve_color"] = True
            resolved_editing_accents["suppress_full_frame_color_flash"] = bool(
                content_effect_policy.get("disallow_full_frame_color_flash")
            )
    if content_effect_policy:
        resolved_editing_accents["effect_policy"] = copy.deepcopy(content_effect_policy)
    normalized_music = normalize_local_music_plan(
        _bind_music_to_choreography(music, section_choreography=section_choreography, insert=bound_insert)
    )
    hyperframes_plan = build_static_packaging_plan(
        subtitles_plan=bound_subtitles,
        editing_accents=resolved_editing_accents,
        focus_plan=copy.deepcopy(focus_plan or {}) if isinstance(focus_plan, dict) and focus_plan else None,
        audio_cues=list((normalized_music or {}).get("audio_cues") or []) if isinstance(normalized_music, dict) else [],
        source="roughcut.edit.render_plan",
    )
    plan = {
        "editorial_timeline_id": str(editorial_timeline_id),
        "render_engine": "hyperframes",
        "visual_timeline_engine": "hyperframes",
        "workflow_preset": preset.name,
        "loudness": {
            "target_lufs": target_lufs,
            "peak_limit": peak_limit,
        },
        "voice_processing": {
            "noise_reduction": noise_reduction,
            "compression": "gentle",
        },
        "subtitles": bound_subtitles,
        "intro": intro,
        "outro": outro,
        "insert": bound_insert,
        "watermark": watermark,
        "music": normalized_music,
        "focus": copy.deepcopy(focus_plan or {}) if isinstance(focus_plan, dict) and focus_plan else None,
        "timeline_analysis": resolved_timeline_analysis,
        "editing_skill": resolved_editing_skill,
        "section_choreography": section_choreography,
        "creative_profile": creative_profile,
        "content_effect_policy": content_effect_policy,
        "ai_director": ai_director_plan,
        "avatar_commentary": avatar_commentary_plan,
        "strategy_review_context": copy.deepcopy(strategy_review_context),
        "manual_editor": {
            "strategy_review_context": copy.deepcopy(strategy_review_context),
        },
        "editing_accents": resolved_editing_accents,
        "delivery": {
            "resolution_mode": export_resolution_mode,
            "resolution_preset": export_resolution_preset,
            "frame_rate_mode": export_frame_rate_mode,
            "frame_rate_preset": export_frame_rate_preset,
        },
    }
    plan["hyperframes"] = hyperframes_plan
    plan["packaging_timeline"] = {
        "timeline_analysis": copy.deepcopy(plan["timeline_analysis"] or {}),
        "editing_skill": copy.deepcopy(plan["editing_skill"] or {}),
        "section_choreography": copy.deepcopy(plan["section_choreography"] or {}),
        "subtitles": copy.deepcopy(plan["subtitles"] or {}),
        "packaging": {
            "intro": copy.deepcopy(plan.get("intro")),
            "outro": copy.deepcopy(plan.get("outro")),
            "insert": copy.deepcopy(plan.get("insert")),
            "watermark": copy.deepcopy(plan.get("watermark")),
            "music": copy.deepcopy(plan.get("music")),
        },
        "editing_accents": copy.deepcopy(plan["editing_accents"] or {}),
        "strategy_review_context": copy.deepcopy(strategy_review_context),
        "focus": copy.deepcopy(plan.get("focus")) if isinstance(plan.get("focus"), dict) else None,
        "hyperframes": copy.deepcopy(hyperframes_plan),
    }
    if include_cover:
        plan["cover"] = {
            "style": cover_style or preset.cover_style,
            "title_style": title_style,
            "variant_count": preset.cover_variant_count,
        }
    return plan


def build_smart_editing_accents(
    *,
    keep_segments: list[dict[str, Any]],
    subtitle_items: list[dict[str, Any]],
    timeline_analysis: dict[str, Any] | None = None,
    editing_skill: dict[str, Any] | None = None,
    style: str = _DEFAULT_SMART_EFFECT_STYLE,
) -> dict[str, Any]:
    resolved_style = _normalize_smart_effect_style(style)
    tokens = _smart_effect_tokens(resolved_style)
    resolved_skill = _resolve_effect_editing_skill(editing_skill, timeline_analysis=timeline_analysis)
    review_focus = _resolve_review_focus_for_accents(
        editing_skill=resolved_skill,
        timeline_analysis=timeline_analysis,
    )
    base_transition_max_count = int(tokens.get("transition_max_count") or 4)
    skill_transition_max_count = int((resolved_skill or {}).get("transition_max_count") or 0)
    transition_max_count = _resolve_review_focus_transition_max_count(
        max(base_transition_max_count, skill_transition_max_count),
        review_focus=review_focus,
    )
    base_overlay_max_count = int(tokens.get("overlay_max_count") or 6)
    skill_overlay_max_count = int((resolved_skill or {}).get("overlay_max_count") or 0)
    base_overlay_spacing_sec = float(tokens.get("overlay_spacing_sec") or 4.2)
    skill_overlay_spacing_sec = float((resolved_skill or {}).get("overlay_spacing_sec") or 0.0)
    overlay_max_count, overlay_spacing_sec = _resolve_review_focus_overlay_constraints(
        max(base_overlay_max_count, skill_overlay_max_count),
        min(base_overlay_spacing_sec, skill_overlay_spacing_sec) if skill_overlay_spacing_sec > 0 else base_overlay_spacing_sec,
        review_focus=review_focus,
    )
    transition_boundaries = _select_transition_boundaries(
        keep_segments,
        timeline_analysis=timeline_analysis,
        editing_skill=resolved_skill,
        max_count=transition_max_count,
    )
    emphasis_overlays = _select_emphasis_overlays(
        subtitle_items,
        timeline_analysis=timeline_analysis,
        editing_skill=resolved_skill,
        preferred_candidates=list((timeline_analysis or {}).get("emphasis_candidates") or []),
        max_count=overlay_max_count,
        min_spacing_sec=overlay_spacing_sec,
        max_duration_sec=float(tokens.get("overlay_max_duration_sec") or 1.35),
    )
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
        "social_packaging": _build_social_packaging_strategy(
            style=resolved_style,
            tokens=tokens,
            overlay_count=len(emphasis_overlays),
            transition_count=len(transition_boundaries),
            review_focus=review_focus,
        ),
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
    timeline_analysis: dict[str, Any] | None = None,
    editing_skill: dict[str, Any] | None = None,
    reuse_bound_assets: bool = False,
) -> dict[str, Any]:
    ai_plan = copy.deepcopy(render_plan)
    ai_plan["avatar_commentary"] = None
    workflow_preset = str(ai_plan.get("workflow_preset") or "").strip()
    effect_policy = (
        ai_plan.get("content_effect_policy")
        if isinstance(ai_plan.get("content_effect_policy"), dict)
        else build_content_effect_policy(
            workflow_preset=workflow_preset,
            content_profile=ai_plan.get("content_profile") if isinstance(ai_plan.get("content_profile"), dict) else None,
        )
    )
    preserve_color = bool((ai_plan.get("editing_accents") or {}).get("preserve_color")) or bool(
        (effect_policy or {}).get("preserve_color")
    )
    resolved_timeline_analysis = timeline_analysis or (ai_plan.get("timeline_analysis") if isinstance(ai_plan.get("timeline_analysis"), dict) else {})
    resolved_editing_skill = editing_skill or (ai_plan.get("editing_skill") if isinstance(ai_plan.get("editing_skill"), dict) else {})
    if reuse_bound_assets and isinstance(ai_plan.get("section_choreography"), dict):
        ai_plan["section_choreography"] = copy.deepcopy(ai_plan.get("section_choreography") or {})
    else:
        ai_plan["section_choreography"] = _build_section_choreography(
            timeline_analysis=resolved_timeline_analysis,
            editing_skill=resolved_editing_skill,
            style_variant="ai_effect",
        )
        ai_plan["insert"] = _bind_insert_to_section_choreography(
            ai_plan.get("insert"),
            section_choreography=ai_plan.get("section_choreography") or {},
        )
        ai_plan["music"] = _bind_music_to_choreography(
            ai_plan.get("music"),
            section_choreography=ai_plan.get("section_choreography") or {},
            insert=ai_plan.get("insert"),
        )
    base_effect_style = _resolve_workflow_smart_effect_style(
        str((ai_plan.get("editing_accents") or {}).get("style") or ""),
        workflow_preset=workflow_preset,
        preserve_color=preserve_color,
    )
    subtitles = copy.deepcopy(ai_plan.get("subtitles") or {})
    if subtitles:
        subtitles["motion_style"] = _resolve_ai_effect_motion_style(
            str(subtitles.get("motion_style") or ""),
            base_style=base_effect_style,
        )
        ai_plan["subtitles"] = (
            subtitles
            if reuse_bound_assets
            else _bind_subtitles_to_choreography(
                subtitles,
                section_choreography=ai_plan.get("section_choreography") or {},
                editing_skill=resolved_editing_skill,
            )
        )
    ai_plan["editing_accents"] = _build_ai_effect_editing_accents(
        ai_plan.get("editing_accents"),
        keep_segments=keep_segments or [],
        subtitle_items=subtitle_items or [],
        timeline_analysis=resolved_timeline_analysis,
        editing_skill=resolved_editing_skill,
        workflow_preset=workflow_preset,
        preserve_color=preserve_color,
        reuse_event_structure=reuse_bound_assets,
    )
    ai_plan["hyperframes"] = build_static_packaging_plan(
        subtitles_plan=ai_plan.get("subtitles") if isinstance(ai_plan.get("subtitles"), dict) else None,
        editing_accents=ai_plan.get("editing_accents") if isinstance(ai_plan.get("editing_accents"), dict) else None,
        focus_plan=ai_plan.get("focus") if isinstance(ai_plan.get("focus"), dict) else None,
        audio_cues=list(((ai_plan.get("music") or {}).get("audio_cues") or [])) if isinstance(ai_plan.get("music"), dict) else [],
        source="roughcut.edit.render_plan.ai_effect",
    )
    packaging_timeline = dict(ai_plan.get("packaging_timeline") or {})
    packaging_timeline["subtitles"] = copy.deepcopy(ai_plan.get("subtitles") or {})
    packaging_timeline["section_choreography"] = copy.deepcopy(ai_plan.get("section_choreography") or {})
    packaging_timeline["editing_accents"] = copy.deepcopy(ai_plan.get("editing_accents") or {})
    packaging_timeline["focus"] = copy.deepcopy(ai_plan.get("focus")) if isinstance(ai_plan.get("focus"), dict) else None
    packaging_timeline["hyperframes"] = copy.deepcopy(ai_plan["hyperframes"])
    ai_plan["packaging_timeline"] = packaging_timeline
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
    timeline_analysis: dict[str, Any] | None = None,
    editing_skill: dict[str, Any] | None = None,
    max_count: int = 2,
    min_segment_duration: float = 1.6,
    min_removed_gap: float = 0.45,
) -> list[int]:
    boundary_targets = _build_semantic_boundary_targets(
        keep_segments,
        timeline_analysis=timeline_analysis,
        editing_skill=editing_skill,
    )
    targeted_indexes = {int(target["index"]) for target in boundary_targets}
    boundary_target_boosts: dict[int, float] = {}
    for target in boundary_targets:
        raw_target_index = target.get("index", -1)
        target_index = int(raw_target_index if raw_target_index is not None else -1)
        if target_index < 0:
            continue
        boundary_target_boosts[target_index] = max(
            float(target.get("boost", 0.0) or 0.0),
            float(boundary_target_boosts.get(target_index, 0.0) or 0.0),
        )
    candidates: list[tuple[float, int]] = []
    for idx in range(len(keep_segments) - 1):
        if targeted_indexes and idx not in targeted_indexes:
            continue
        current = keep_segments[idx]
        following = keep_segments[idx + 1]
        current_duration = float(current.get("end", 0.0) or 0.0) - float(current.get("start", 0.0) or 0.0)
        next_duration = float(following.get("end", 0.0) or 0.0) - float(following.get("start", 0.0) or 0.0)
        removed_gap = float(following.get("start", 0.0) or 0.0) - float(current.get("end", 0.0) or 0.0)
        if current_duration < min_segment_duration or next_duration < min_segment_duration:
            continue
        if removed_gap < min_removed_gap:
            continue
        score = removed_gap
        score += float(boundary_target_boosts.get(idx, 0.0) or 0.0)
        candidates.append((score, idx))
    selected = sorted(idx for _gap, idx in sorted(candidates, reverse=True)[:max(0, max_count)])
    return selected


def _normalize_smart_effect_style(style: str) -> str:
    normalized = str(style or "").strip().lower()
    if not normalized:
        return _DEFAULT_SMART_EFFECT_STYLE
    return _RENAMED_SMART_EFFECT_STYLE_KEYS.get(normalized, normalized)


def _should_preserve_smart_effect_color(*, workflow_preset: str | None) -> bool:
    normalized = normalize_workflow_template_name(workflow_preset)
    return normalized in _UNBOXING_WORKFLOW_PRESETS


def build_content_effect_policy(
    *,
    workflow_preset: str | None,
    content_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    content_class = _resolve_content_effect_class(content_profile)
    preserve_color = _should_preserve_smart_effect_color(workflow_preset=workflow_preset) or content_class == "product_fidelity"
    return {
        "content_class": content_class or "general",
        "preserve_color": preserve_color,
        "disallow_full_frame_color_shift": preserve_color,
        "disallow_full_frame_color_flash": preserve_color,
        "allow_overlay_text": True,
        "allow_subtitle_motion": True,
        "allow_local_audio_cues": True,
        "allowed_effects": (
            ["subtitle_motion", "text_emphasis_overlay", "local_audio_cue", "clean_transition"]
            if preserve_color
            else ["subtitle_motion", "text_emphasis_overlay", "local_audio_cue", "color_flash", "stylized_transition"]
        ),
        "blocked_effects": (
            ["global_color_shift", "full_frame_color_flash", "global_zoom_crop"]
            if preserve_color
            else []
        ),
    }


def _resolve_content_effect_class(content_profile: dict[str, Any] | None) -> str | None:
    if not isinstance(content_profile, dict):
        return None
    values = list(_iter_content_policy_texts(content_profile))
    normalized_blob = " ".join(value.lower() for value in values)
    if any(term in normalized_blob for term in _PRODUCT_FIDELITY_TERMS):
        return "product_fidelity"
    return None


def _iter_content_policy_texts(content_profile: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in _CONTENT_PROFILE_EFFECT_POLICY_KEYS:
        value = content_profile.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    for nested_key in ("content_understanding", "video_global", "topic_fact_confirmation"):
        nested = content_profile.get(nested_key)
        if not isinstance(nested, dict):
            continue
        for key in _CONTENT_PROFILE_EFFECT_POLICY_KEYS:
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
    entities = content_profile.get("entities")
    if isinstance(entities, list):
        for entity in entities:
            if not isinstance(entity, dict):
                continue
            for key in ("kind", "name", "category", "type"):
                value = entity.get(key)
                if isinstance(value, str) and value.strip():
                    values.append(value.strip())
    return values


def _resolve_workflow_smart_effect_style(
    style: str,
    *,
    workflow_preset: str | None,
    preserve_color: bool | None = None,
) -> str:
    normalized = _normalize_smart_effect_style(style)
    should_preserve = _should_preserve_smart_effect_color(workflow_preset=workflow_preset) if preserve_color is None else preserve_color
    if should_preserve and normalized in _COLOR_SHIFTING_SMART_EFFECT_STYLES:
        return _DEFAULT_SMART_EFFECT_STYLE
    return normalized


def _resolve_effect_editing_skill(
    editing_skill: dict[str, Any] | None,
    *,
    timeline_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(editing_skill, dict) and editing_skill:
        return editing_skill
    skill_from_analysis = (timeline_analysis or {}).get("editing_skill")
    if isinstance(skill_from_analysis, dict):
        return skill_from_analysis
    return {}


def _resolve_ai_effect_style_variant(style: str) -> str:
    normalized = _normalize_smart_effect_style(style)
    if normalized in _AI_SMART_EFFECT_STYLE_VARIANTS.values():
        return normalized
    return _AI_SMART_EFFECT_STYLE_VARIANTS.get(normalized, "smart_effect_commercial_ai")


def _build_social_packaging_strategy(
    *,
    style: str,
    tokens: dict[str, Any],
    overlay_count: int,
    transition_count: int,
    review_focus: str,
) -> dict[str, Any]:
    return {
        "strategy": "hyperframes_social_retention_v2",
        "style": _normalize_smart_effect_style(style),
        "principles": [
            "hook_first_screen",
            "pattern_interrupt_every_3_to_5_seconds",
            "animated_keyword_captions",
            "one_text_zone_per_frame",
            "bottom_progress_and_chapter_context",
            "product_color_fidelity",
        ],
        "target_density": {
            "transition_max_count": int(tokens.get("transition_max_count") or 0),
            "overlay_max_count": int(tokens.get("overlay_max_count") or 0),
            "max_total_overlays": int(tokens.get("max_total_overlays") or tokens.get("overlay_max_count") or 0),
            "overlay_spacing_sec": round(float(tokens.get("overlay_spacing_sec") or 0.0), 3),
        },
        "resolved_density": {
            "transition_count": int(transition_count),
            "overlay_count": int(overlay_count),
        },
        "review_focus": str(review_focus or ""),
    }


def _smart_effect_tokens(style: str) -> dict[str, Any]:
    mapping: dict[str, dict[str, Any]] = {
        _DEFAULT_SMART_EFFECT_STYLE: {
            "transition": "fade",
            "transition_duration_sec": 0.12,
            "sound_duration_sec": 0.08,
            "sound_frequency": 960,
            "sound_volume": 0.045,
            "transition_max_count": 4,
            "overlay_max_count": 6,
            "max_total_overlays": 10,
            "overlay_spacing_sec": 4.2,
            "overlay_max_duration_sec": 1.35,
        },
        "smart_effect_punch": {
            "transition": "fadeblack",
            "transition_duration_sec": 0.16,
            "sound_duration_sec": 0.11,
            "sound_frequency": 820,
            "sound_volume": 0.06,
            "transition_max_count": 5,
            "overlay_max_count": 7,
            "max_total_overlays": 11,
            "overlay_spacing_sec": 3.6,
            "overlay_max_duration_sec": 1.35,
        },
        "smart_effect_glitch": {
            "transition": "pixelize",
            "transition_duration_sec": 0.14,
            "sound_duration_sec": 0.09,
            "sound_frequency": 1320,
            "sound_volume": 0.05,
            "transition_max_count": 5,
            "overlay_max_count": 7,
            "max_total_overlays": 11,
            "overlay_spacing_sec": 3.4,
            "overlay_max_duration_sec": 1.25,
        },
        "smart_effect_cinematic": {
            "transition": "fade",
            "transition_duration_sec": 0.18,
            "sound_duration_sec": 0.07,
            "sound_frequency": 640,
            "sound_volume": 0.028,
            "transition_max_count": 4,
            "overlay_max_count": 5,
            "max_total_overlays": 9,
            "overlay_spacing_sec": 4.8,
            "overlay_max_duration_sec": 1.55,
        },
        "smart_effect_atmosphere": {
            "transition": "fade",
            "transition_duration_sec": 0.18,
            "sound_duration_sec": 0.075,
            "sound_frequency": 720,
            "sound_volume": 0.032,
            "transition_max_count": 4,
            "overlay_max_count": 5,
            "max_total_overlays": 9,
            "overlay_spacing_sec": 4.6,
            "overlay_max_duration_sec": 1.5,
        },
        "smart_effect_minimal": {
            "transition": "fade",
            "transition_duration_sec": 0.1,
            "sound_duration_sec": 0.06,
            "sound_frequency": 900,
            "sound_volume": 0.018,
            "transition_max_count": 3,
            "overlay_max_count": 4,
            "max_total_overlays": 7,
            "overlay_spacing_sec": 5.2,
            "overlay_max_duration_sec": 1.15,
        },
        "smart_effect_commercial_ai": {
            "transition": "fadeblack",
            "transition_duration_sec": 0.18,
            "sound_duration_sec": 0.11,
            "sound_frequency": 980,
            "sound_volume": 0.07,
            "transition_max_count": 7,
            "overlay_max_count": 10,
            "max_total_overlays": 16,
            "overlay_spacing_sec": 2.8,
            "overlay_max_duration_sec": 1.5,
        },
        "smart_effect_punch_ai": {
            "transition": "fadeblack",
            "transition_duration_sec": 0.18,
            "sound_duration_sec": 0.12,
            "sound_frequency": 1120,
            "sound_volume": 0.078,
            "transition_max_count": 7,
            "overlay_max_count": 10,
            "max_total_overlays": 16,
            "overlay_spacing_sec": 2.8,
            "overlay_max_duration_sec": 1.45,
        },
        "smart_effect_glitch_ai": {
            "transition": "pixelize",
            "transition_duration_sec": 0.16,
            "sound_duration_sec": 0.105,
            "sound_frequency": 1480,
            "sound_volume": 0.068,
            "transition_max_count": 8,
            "overlay_max_count": 10,
            "max_total_overlays": 16,
            "overlay_spacing_sec": 2.7,
            "overlay_max_duration_sec": 1.35,
        },
        "smart_effect_cinematic_ai": {
            "transition": "fade",
            "transition_duration_sec": 0.2,
            "sound_duration_sec": 0.085,
            "sound_frequency": 700,
            "sound_volume": 0.052,
            "transition_max_count": 6,
            "overlay_max_count": 8,
            "max_total_overlays": 14,
            "overlay_spacing_sec": 3.6,
            "overlay_max_duration_sec": 1.7,
        },
        "smart_effect_atmosphere_ai": {
            "transition": "fade",
            "transition_duration_sec": 0.18,
            "sound_duration_sec": 0.09,
            "sound_frequency": 760,
            "sound_volume": 0.056,
            "transition_max_count": 6,
            "overlay_max_count": 8,
            "max_total_overlays": 14,
            "overlay_spacing_sec": 3.5,
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


def _bind_insert_to_section_choreography(
    insert: dict[str, Any] | None,
    *,
    section_choreography: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(insert, dict):
        return insert
    resolved_insert = copy.deepcopy(insert)
    matched_section = _resolve_insert_section_choreography(
        resolved_insert,
        section_choreography=section_choreography,
    )
    if not matched_section:
        return resolved_insert
    resolved_insert["insert_transition_mode"] = str(
        matched_section.get("transition_mode")
        or resolved_insert.get("insert_transition_mode")
        or "restrained"
    )
    resolved_insert["insert_overlay_focus"] = str(
        matched_section.get("overlay_focus")
        or resolved_insert.get("insert_overlay_focus")
        or ""
    )
    resolved_insert["insert_cta_protection"] = bool(
        matched_section.get("cta_protection")
        or resolved_insert.get("insert_cta_protection")
    )
    resolved_insert["insert_packaging_intent"] = str(
        resolved_insert.get("insert_packaging_intent")
        or matched_section.get("packaging_intent")
        or ""
    )
    resolved_insert["insert_creative_preferences"] = list(
        matched_section.get("creative_preferences")
        or resolved_insert.get("insert_creative_preferences")
        or []
    )
    resolved_insert["insert_creative_rationale"] = str(
        matched_section.get("creative_rationale")
        or resolved_insert.get("insert_creative_rationale")
        or ""
    )
    return resolved_insert


def _resolve_insert_section_choreography(
    insert: dict[str, Any],
    *,
    section_choreography: dict[str, Any] | None,
) -> dict[str, Any] | None:
    sections = list((section_choreography or {}).get("sections") or [])
    if not sections:
        return None
    insert_section_index = insert.get("insert_section_index")
    if isinstance(insert_section_index, int):
        for section in sections:
            if int(section.get("index", -1) or -1) == insert_section_index:
                return section
    insert_after_sec = float(insert.get("insert_after_sec", 0.0) or 0.0)
    for section in sections:
        start_sec = float(section.get("start_sec", 0.0) or 0.0)
        end_sec = float(section.get("end_sec", 0.0) or 0.0)
        if start_sec - 1e-6 <= insert_after_sec <= end_sec + 1e-6:
            return section
    return min(
        sections,
        key=lambda section: abs(
            insert_after_sec - float(section.get("transition_anchor_sec", section.get("start_sec", 0.0)) or 0.0)
        ),
        default=None,
    )


def _bind_music_to_choreography(
    music: dict[str, Any] | None,
    *,
    section_choreography: dict[str, Any] | None,
    insert: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(music, dict):
        return music
    resolved_music = copy.deepcopy(music)
    matched_section = _resolve_music_section_choreography(
        resolved_music,
        section_choreography=section_choreography,
    )
    transition_mode = str((matched_section or {}).get("transition_mode") or "restrained")
    resolved_music["music_transition_mode"] = transition_mode
    resolved_music["music_entry_fade_sec"] = _resolve_music_entry_fade_sec(transition_mode)
    resolved_music["music_ducking_profile"] = _resolve_music_ducking_profile(
        transition_mode=transition_mode,
        packaging_intent=str((insert or {}).get("insert_packaging_intent") or ""),
    )
    resolved_music["duck_windows"] = _build_music_duck_windows(
        insert=insert,
        transition_mode=transition_mode,
        ducking_profile=resolved_music["music_ducking_profile"],
    )
    return resolved_music


def _bind_subtitles_to_choreography(
    subtitles: dict[str, Any] | None,
    *,
    section_choreography: dict[str, Any] | None,
    editing_skill: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(subtitles, dict):
        return subtitles
    resolved_subtitles = copy.deepcopy(subtitles)
    sections = list((section_choreography or {}).get("sections") or [])
    if not sections:
        return resolved_subtitles
    base_style = str(resolved_subtitles.get("style") or "bold_yellow_outline")
    base_motion = str(resolved_subtitles.get("motion_style") or "motion_static")
    style_variant = str((section_choreography or {}).get("style_variant") or "base").strip().lower()
    energetic_skill = str((editing_skill or {}).get("key") or "").strip().lower() in {
        "gameplay_highlight",
        "food_explore",
    }
    section_profiles: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        section_profiles.append(
            _resolve_subtitle_section_profile(
                section,
                base_style=base_style,
                base_motion=base_motion,
                style_variant=style_variant,
                energetic_skill=energetic_skill,
            )
        )
    resolved_subtitles["section_profiles"] = section_profiles
    resolved_subtitles["default_linger_sec"] = 0.06 if energetic_skill else 0.04
    resolved_subtitles["timing_guard_sec"] = 0.05 if energetic_skill else 0.07
    resolved_subtitles["choreography_summary"] = {
        "profile_count": len(section_profiles),
        "cta_profile_count": sum(1 for item in section_profiles if bool(item.get("cta_protection"))),
        "hero_profile_count": sum(1 for item in section_profiles if str(item.get("emphasis_level") or "") == "hero"),
    }
    return resolved_subtitles


def _resolve_subtitle_section_profile(
    section: dict[str, Any],
    *,
    base_style: str,
    base_motion: str,
    style_variant: str,
    energetic_skill: bool,
) -> dict[str, Any]:
    role = str(section.get("role") or "").strip().lower()
    packaging_intent = str(section.get("packaging_intent") or "").strip().lower()
    transition_mode = str(section.get("transition_mode") or "restrained").strip().lower()
    overlay_focus = str(section.get("overlay_focus") or "medium").strip().lower()
    cta_protection = bool(section.get("cta_protection"))
    style_name = base_style
    motion_style = base_motion
    margin_v_delta = 0
    linger_sec = 0.04
    guard_sec = 0.07
    emphasis_level = "support"

    if cta_protection or packaging_intent == "cta_protect" or role == "cta":
        style_name = "white_minimal"
        motion_style = "motion_static"
        margin_v_delta = 18
        linger_sec = 0.0
        guard_sec = 0.08
        emphasis_level = "quiet"
    elif packaging_intent == "hook_focus" or role == "hook":
        style_name = "teaser_glow" if style_variant != "ai_effect" else "sale_banner"
        if style_variant == "ai_effect":
            motion_style = "motion_strobe"
        else:
            motion_style = "motion_pop" if transition_mode != "protect" else "motion_static"
        margin_v_delta = 0
        linger_sec = 0.1 if transition_mode == "accented" else 0.06
        guard_sec = 0.04
        emphasis_level = "hero"
    elif packaging_intent == "detail_support" or role == "detail":
        if style_variant == "ai_effect":
            style_name = "cyber_orange" if overlay_focus == "high" else "coupon_green"
        else:
            style_name = "keyword_highlight" if overlay_focus == "high" else "clean_box"
        if style_variant == "ai_effect":
            motion_style = "motion_glitch" if transition_mode == "accented" else "motion_strobe"
        else:
            motion_style = "motion_ripple" if transition_mode == "accented" else "motion_slide"
        margin_v_delta = 6 if overlay_focus == "high" else 0
        linger_sec = 0.08 if overlay_focus == "high" else 0.05
        guard_sec = 0.05
        emphasis_level = "support"
    elif role == "body":
        style_name = base_style if style_variant != "ai_effect" else "amber_news"
        motion_style = "motion_echo" if energetic_skill and transition_mode == "accented" else base_motion
        margin_v_delta = 4 if overlay_focus == "medium" else 0
        linger_sec = 0.06 if energetic_skill else 0.04
        guard_sec = 0.06
        emphasis_level = "steady"

    return {
        "index": int(section.get("index", 0) or 0),
        "role": role,
        "start_sec": round(float(section.get("start_sec", 0.0) or 0.0), 3),
        "end_sec": round(float(section.get("end_sec", 0.0) or 0.0), 3),
        "packaging_intent": packaging_intent,
        "cta_protection": cta_protection,
        "style_name": style_name,
        "motion_style": motion_style,
        "margin_v_delta": int(margin_v_delta),
        "linger_sec": round(float(linger_sec), 3),
        "guard_sec": round(float(guard_sec), 3),
        "emphasis_level": emphasis_level,
    }


def _resolve_music_section_choreography(
    music: dict[str, Any],
    *,
    section_choreography: dict[str, Any] | None,
) -> dict[str, Any] | None:
    enter_sec = float(music.get("enter_sec", 0.0) or 0.0)
    for section in list((section_choreography or {}).get("sections") or []):
        start_sec = float(section.get("start_sec", 0.0) or 0.0)
        end_sec = float(section.get("end_sec", start_sec) or start_sec)
        if start_sec - 1e-6 <= enter_sec <= end_sec + 1e-6:
            return section
    return None


def _resolve_music_entry_fade_sec(transition_mode: str) -> float:
    mapping = {
        "accented": 0.42,
        "restrained": 0.28,
        "protect": 0.18,
    }
    return round(float(mapping.get(str(transition_mode or "restrained").strip().lower(), 0.28)), 3)


def _resolve_music_ducking_profile(*, transition_mode: str, packaging_intent: str) -> dict[str, float]:
    mode = str(transition_mode or "restrained").strip().lower()
    intent = str(packaging_intent or "").strip().lower()
    target_volume = {
        "accented": 0.42,
        "restrained": 0.54,
        "protect": 0.66,
    }.get(mode, 0.54)
    if intent == "hook_focus":
        target_volume = min(target_volume, 0.46)
    elif intent == "cta_protect":
        target_volume = max(target_volume, 0.7)
    return {
        "target_volume": round(target_volume, 3),
        "lead_sec": 0.12 if mode == "accented" else 0.08,
        "tail_sec": 0.18 if mode == "accented" else 0.12,
    }


def _build_music_duck_windows(
    *,
    insert: dict[str, Any] | None,
    transition_mode: str,
    ducking_profile: dict[str, float],
) -> list[dict[str, Any]]:
    if not isinstance(insert, dict) or not insert.get("path"):
        return []
    insert_after_sec = float(insert.get("insert_after_sec", 0.0) or 0.0)
    runtime_duration = float(insert.get("insert_target_duration_sec", 0.0) or 0.0)
    if runtime_duration <= 0.0:
        runtime_duration = 1.2
    overlap = resolve_insert_transition_overlap(
        insert,
        runtime_duration_sec=runtime_duration,
        insert_after_sec=insert_after_sec,
        source_duration=insert_after_sec + runtime_duration + 1.0,
    )
    visible_start = max(0.0, insert_after_sec - float(overlap.get("entry_sec", 0.0) or 0.0))
    visible_end = max(visible_start, visible_start + runtime_duration)
    lead_sec = float(ducking_profile.get("lead_sec", 0.08) or 0.08)
    tail_sec = float(ducking_profile.get("tail_sec", 0.12) or 0.12)
    return [
        {
            "start_sec": round(max(0.0, visible_start - lead_sec), 3),
            "end_sec": round(visible_end + tail_sec, 3),
            "target_volume": round(float(ducking_profile.get("target_volume", 0.54) or 0.54), 3),
            "reason": f"insert_{str(transition_mode or 'restrained').strip().lower()}",
        }
    ]


def _build_section_choreography(
    *,
    timeline_analysis: dict[str, Any] | None = None,
    editing_skill: dict[str, Any] | None = None,
    style_variant: str = "base",
) -> dict[str, Any]:
    actions = list((timeline_analysis or {}).get("section_actions") or [])
    directives = list((timeline_analysis or {}).get("section_directives") or [])
    if not actions:
        return {}

    directive_by_index = {
        int(directive.get("index", -1)): directive
        for directive in directives
        if isinstance(directive, dict) and (isinstance(directive.get("index"), int) or str(directive.get("index", "")).lstrip("-").isdigit())
    }
    sections: list[dict[str, Any]] = []
    review_focus = str((editing_skill or {}).get("review_focus") or "").strip().lower()
    for action in actions:
        if not isinstance(action, dict):
            continue
        action_index = int(action.get("index", len(sections)) or 0)
        directive = directive_by_index.get(action_index, {})
        transition_boost = float(action.get("transition_boost", 0.0) or 0.0)
        overlay_weight = float((directive or {}).get("overlay_weight", 0.0) or 0.0)
        packaging_intent = str(action.get("packaging_intent") or "")
        if packaging_intent == "cta_protect":
            transition_mode = "protect"
        elif transition_boost >= 1.0:
            transition_mode = "accented"
        else:
            transition_mode = "restrained"
        if overlay_weight >= 1.0:
            overlay_focus = "high"
        elif overlay_weight > 0.0:
            overlay_focus = "medium"
        else:
            overlay_focus = "none"
        focus_bias = _resolve_review_focus_section_bias(
            role=str(action.get("role") or ""),
            packaging_intent=packaging_intent,
            review_focus=review_focus,
        )
        sections.append(
            {
                "index": action_index,
                "role": str(action.get("role") or ""),
                "start_sec": round(float(action.get("start_sec", 0.0) or 0.0), 3),
                "end_sec": round(float(action.get("end_sec", 0.0) or 0.0), 3),
                "summary": str(action.get("summary") or directive.get("summary") or "").strip(),
                "chapter_title": str(action.get("summary") or directive.get("summary") or "").strip(),
                "packaging_intent": packaging_intent,
                "trim_intensity": str(action.get("trim_intensity") or "balanced"),
                "transition_mode": transition_mode,
                "transition_anchor_sec": round(float(action.get("transition_anchor_sec", action.get("start_sec", 0.0)) or 0.0), 3),
                "overlay_focus": overlay_focus,
                "broll_window": {
                    "enabled": bool(action.get("broll_allowed")),
                    "anchor_sec": round(float(action.get("broll_anchor_sec", 0.0) or 0.0), 3),
                },
                "cta_protection": packaging_intent == "cta_protect",
                "review_focus_mode": str(focus_bias.get("mode") or ""),
                "transition_energy_bias": round(float(focus_bias.get("transition_energy_bias", 0.0) or 0.0), 3),
                "overlay_density_bias": int(focus_bias.get("overlay_density_bias", 0) or 0),
                "creative_preferences": list(action.get("creative_preferences") or directive.get("creative_preferences") or []),
                "creative_rationale": str(action.get("creative_rationale") or directive.get("creative_rationale") or ""),
            }
        )

    return {
        "style_variant": style_variant,
        "editing_skill_key": str((editing_skill or {}).get("key") or ""),
        "review_focus": review_focus,
        "sections": sections,
        "summary": {
            "section_count": len(sections),
            "broll_section_count": sum(1 for item in sections if bool((item.get("broll_window") or {}).get("enabled"))),
            "cta_protected": any(bool(item.get("cta_protection")) for item in sections),
            "creative_preference_count": len(list((editing_skill or {}).get("creative_preferences") or [])),
        },
    }


def _resolve_review_focus_section_bias(
    *,
    role: str,
    packaging_intent: str,
    review_focus: str,
) -> dict[str, Any]:
    normalized_role = str(role or "").strip().lower()
    normalized_intent = str(packaging_intent or "").strip().lower()
    normalized_focus = str(review_focus or "").strip().lower()
    if normalized_focus == "hook_boundary" and (normalized_role == "hook" or normalized_intent == "hook_focus"):
        return {
            "mode": "hook_boundary_smooth",
            "transition_energy_bias": -0.18,
            "overlay_density_bias": -1,
        }
    if normalized_focus == "mid_transition" and normalized_role in {"detail", "body"}:
        return {
            "mode": "mid_transition_smooth",
            "transition_energy_bias": -0.12,
            "overlay_density_bias": -1,
        }
    if normalized_focus == "cta_transition" and (normalized_role == "cta" or normalized_intent == "cta_protect"):
        return {
            "mode": "cta_transition_protect",
            "transition_energy_bias": -0.22,
            "overlay_density_bias": -1,
        }
    return {
        "mode": "",
        "transition_energy_bias": 0.0,
        "overlay_density_bias": 0,
    }


def _resolve_review_focus_for_accents(
    *,
    editing_skill: dict[str, Any] | None,
    timeline_analysis: dict[str, Any] | None = None,
) -> str:
    direct_focus = str((editing_skill or {}).get("review_focus") or "").strip().lower()
    if direct_focus:
        return direct_focus
    return str(((timeline_analysis or {}).get("editing_skill") or {}).get("review_focus") or "").strip().lower()


def _resolve_review_focus_transition_max_count(max_count: int, *, review_focus: str) -> int:
    normalized_focus = str(review_focus or "").strip().lower()
    if not normalized_focus:
        return max_count
    return max(1, min(max_count, 1))


def _resolve_review_focus_overlay_constraints(
    max_count: int,
    min_spacing_sec: float,
    *,
    review_focus: str,
) -> tuple[int, float]:
    normalized_focus = str(review_focus or "").strip().lower()
    if normalized_focus == "mid_transition":
        return max(1, min(max_count, 2)), max(min_spacing_sec, 4.6)
    if normalized_focus in {"hook_boundary", "cta_transition"}:
        return max(1, min(max_count, 1)), max(min_spacing_sec, 5.8)
    return max_count, min_spacing_sec


def _review_focus_transition_boost(*, role: str, review_focus: str) -> float:
    normalized_role = str(role or "").strip().lower()
    normalized_focus = str(review_focus or "").strip().lower()
    if normalized_focus == "hook_boundary":
        return 1.15 if normalized_role == "hook" else -0.12
    if normalized_focus == "mid_transition":
        return 0.75 if normalized_role in {"detail", "body"} else -0.08
    if normalized_focus == "cta_transition":
        return 1.15 if normalized_role == "cta" else -0.14
    return 0.0


def _review_focus_overlay_score_bonus(
    start_time: float,
    *,
    role: str,
    review_focus: str,
    timeline_analysis: dict[str, Any] | None = None,
) -> float:
    normalized_focus = str(review_focus or "").strip().lower()
    if not normalized_focus:
        return 0.0
    directive = _find_section_directive(start_time, timeline_analysis=timeline_analysis)
    resolved_role = str(role or (directive or {}).get("role") or "").strip().lower()
    if not resolved_role:
        resolved_role = str(((directive or {}).get("packaging_intent") or "")).strip().lower()
    if normalized_focus == "hook_boundary":
        return 1.0 if resolved_role in {"hook", "hook_focus"} else -0.18
    if normalized_focus == "mid_transition":
        return 0.72 if resolved_role in {"detail", "body", "detail_support", "body_support"} else -0.12
    if normalized_focus == "cta_transition":
        return -0.55 if resolved_role in {"cta", "cta_protect"} else -0.08
    return 0.0


def _build_semantic_boundary_targets(
    keep_segments: list[dict[str, Any]],
    *,
    timeline_analysis: dict[str, Any] | None,
    editing_skill: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    review_focus = _resolve_review_focus_for_accents(
        editing_skill=editing_skill,
        timeline_analysis=timeline_analysis,
    )
    section_actions = list((timeline_analysis or {}).get("section_actions") or [])
    if len(keep_segments) >= 2 and section_actions:
        boundary_positions: list[float] = []
        elapsed = 0.0
        for segment in keep_segments[:-1]:
            elapsed += max(0.0, float(segment.get("end", 0.0) or 0.0) - float(segment.get("start", 0.0) or 0.0))
            boundary_positions.append(round(elapsed, 3))

        targets: list[dict[str, Any]] = []
        for action in section_actions:
            if not isinstance(action, dict):
                continue
            target_time = float(action.get("transition_anchor_sec", action.get("start_sec", 0.0)) or 0.0)
            boundary_index = _nearest_boundary_index(boundary_positions, target_time)
            if boundary_index is None:
                continue
            targets.append(
                {
                    "index": boundary_index,
                    "time_sec": round(target_time, 3),
                    "from_role": "",
                    "to_role": str(action.get("role") or ""),
                    "boost": round(
                        float(action.get("transition_boost", 0.0) or 0.0)
                        + _review_focus_transition_boost(
                            role=str(action.get("role") or ""),
                            review_focus=review_focus,
                        ),
                        3,
                    ),
                }
            )
        if targets:
            return targets

    sections = list((timeline_analysis or {}).get("semantic_sections") or [])
    if len(keep_segments) < 2 or not sections:
        return []

    boundary_positions: list[float] = []
    elapsed = 0.0
    for segment in keep_segments[:-1]:
        elapsed += max(0.0, float(segment.get("end", 0.0) or 0.0) - float(segment.get("start", 0.0) or 0.0))
        boundary_positions.append(round(elapsed, 3))

    targets: list[dict[str, Any]] = []
    for previous, current in zip(sections, sections[1:]):
        role = str(current.get("role") or "")
        if role == "cta":
            boost = 0.8
        elif role == "detail":
            boost = 1.2
        elif role == "body":
            boost = 0.9
        else:
            boost = 0.6
        target_time = float(current.get("start_sec", 0.0) or 0.0)
        boundary_index = _nearest_boundary_index(boundary_positions, target_time)
        if boundary_index is None:
            continue
        targets.append(
            {
                "index": boundary_index,
                "time_sec": round(target_time, 3),
                "from_role": str(previous.get("role") or ""),
                "to_role": role,
                "boost": round(boost + _review_focus_transition_boost(role=role, review_focus=review_focus), 3),
            }
        )
    return targets


def _nearest_boundary_index(boundary_positions: list[float], target_time: float) -> int | None:
    nearest_index: int | None = None
    nearest_distance = float("inf")
    for index, boundary_time in enumerate(boundary_positions):
        distance = abs(boundary_time - target_time)
        if distance < nearest_distance:
            nearest_distance = distance
            nearest_index = index
    return nearest_index


def _select_emphasis_overlays(
    subtitle_items: list[dict[str, Any]],
    *,
    timeline_analysis: dict[str, Any] | None = None,
    editing_skill: dict[str, Any] | None = None,
    preferred_candidates: list[dict[str, Any]] | None = None,
    max_count: int = 2,
    min_spacing_sec: float = 8.0,
    min_duration_sec: float = 0.6,
    max_duration_sec: float = 1.1,
) -> list[dict[str, Any]]:
    review_focus = _resolve_review_focus_for_accents(
        editing_skill=editing_skill,
        timeline_analysis=timeline_analysis,
    )
    candidates: list[tuple[float, dict[str, Any]]] = []
    for item in preferred_candidates or []:
        text = _normalize_overlay_label_text(str(item.get("text") or ""))
        if not text:
            continue
        start_time = float(item.get("start_time", 0.0) or 0.0)
        overlay_weight = _resolve_overlay_weight(start_time, timeline_analysis=timeline_analysis)
        if overlay_weight <= -0.5:
            continue
        end_time = max(start_time + min_duration_sec, float(item.get("end_time", start_time + max_duration_sec) or start_time + max_duration_sec))
        role = str(item.get("role") or "")
        score = (
            float(item.get("score", 0.0) or 0.0)
            + (0.6 if role == "hook" else 0.0)
            + overlay_weight
            + _review_focus_overlay_score_bonus(start_time, role=role, review_focus=review_focus, timeline_analysis=timeline_analysis)
        )
        candidates.append(
            (
                score,
                {
                    "text": text,
                    "start_time": round(start_time + 0.05, 3),
                    "end_time": round(min(end_time, start_time + max_duration_sec), 3),
                    "source": "timeline_emphasis_candidate",
                    "role": role,
                    "visual_treatment": _resolve_overlay_visual_treatment(
                        start_time,
                        role=role,
                        timeline_analysis=timeline_analysis,
                    ),
                    "transform_intensity": _resolve_overlay_transform_intensity(
                        start_time,
                        role=role,
                        timeline_analysis=timeline_analysis,
                    ),
                },
            )
        )
    for item in subtitle_items:
        text = _normalize_overlay_text(item)
        if not text:
            continue
        start_time = float(item.get("start_time", 0.0) or 0.0)
        overlay_weight = _resolve_overlay_weight(start_time, timeline_analysis=timeline_analysis)
        if overlay_weight <= -0.5:
            continue
        end_time = float(item.get("end_time", 0.0) or 0.0)
        duration = max(0.0, end_time - start_time)
        if duration < min_duration_sec:
            continue
        score = _score_overlay_text(text, start_time=start_time) + overlay_weight + _review_focus_overlay_score_bonus(
            start_time,
            role="",
            review_focus=review_focus,
            timeline_analysis=timeline_analysis,
        )
        if score <= 0:
            continue
        candidates.append(
            (
                score,
                {
                    "text": text,
                    "start_time": round(start_time + 0.05, 3),
                    "end_time": round(min(end_time, start_time + max_duration_sec), 3),
                    "source": "subtitle_keyword",
                    "role": str(item.get("subtitle_unit_role") or ""),
                    "visual_treatment": _resolve_overlay_visual_treatment(
                        start_time,
                        role=str(item.get("subtitle_unit_role") or ""),
                        timeline_analysis=timeline_analysis,
                    ),
                    "transform_intensity": _resolve_overlay_transform_intensity(
                        start_time,
                        role=str(item.get("subtitle_unit_role") or ""),
                        timeline_analysis=timeline_analysis,
                    ),
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


def _resolve_overlay_weight(
    start_time: float,
    *,
    timeline_analysis: dict[str, Any] | None = None,
) -> float:
    directive = _find_section_directive(start_time, timeline_analysis=timeline_analysis)
    if directive is None:
        return 0.0
    return float(directive.get("overlay_weight", 0.0) or 0.0)


def _resolve_overlay_visual_treatment(
    start_time: float,
    *,
    role: str,
    timeline_analysis: dict[str, Any] | None = None,
) -> str:
    directive = _find_section_directive(start_time, timeline_analysis=timeline_analysis)
    resolved_role = str(role or (directive or {}).get("role") or "").strip().lower()
    packaging_intent = str((directive or {}).get("packaging_intent") or "").strip().lower()
    if resolved_role in {"hook", "lead"} or packaging_intent == "hook_focus" or start_time <= 3.0:
        return "hook_pop"
    if resolved_role in {"focus", "detail"} or packaging_intent == "detail_support":
        return "keyword_sticker"
    if resolved_role == "action":
        return "beat_pulse"
    return "keyword_pop"


def _resolve_overlay_transform_intensity(
    start_time: float,
    *,
    role: str,
    timeline_analysis: dict[str, Any] | None = None,
) -> float:
    directive = _find_section_directive(start_time, timeline_analysis=timeline_analysis)
    resolved_role = str(role or (directive or {}).get("role") or "").strip().lower()
    packaging_intent = str((directive or {}).get("packaging_intent") or "").strip().lower()
    intensity = 1.0
    if start_time <= 3.0 or resolved_role in {"hook", "lead"} or packaging_intent == "hook_focus":
        intensity *= 1.16
    if resolved_role in {"focus", "detail"} or packaging_intent == "detail_support":
        intensity *= 1.08
    if packaging_intent == "cta_protect" or resolved_role == "cta":
        intensity *= 0.72
    return round(max(0.68, min(1.3, intensity)), 3)


def _find_section_directive(
    time_sec: float,
    *,
    timeline_analysis: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    directives = list((timeline_analysis or {}).get("section_directives") or [])
    for directive in directives:
        if not isinstance(directive, dict):
            continue
        start_sec = float(directive.get("start_sec", 0.0) or 0.0)
        end_sec = float(directive.get("end_sec", start_sec) or start_sec)
        if start_sec - 1e-6 <= time_sec <= end_sec + 1e-6:
            return directive

    for section in list((timeline_analysis or {}).get("semantic_sections") or []):
        if not isinstance(section, dict):
            continue
        start_sec = float(section.get("start_sec", 0.0) or 0.0)
        end_sec = float(section.get("end_sec", start_sec) or start_sec)
        if not (start_sec - 1e-6 <= time_sec <= end_sec + 1e-6):
            continue
        role = str(section.get("role") or "")
        if role == "hook":
            return {"overlay_weight": 1.3}
        if role == "detail":
            return {"overlay_weight": 1.0}
        if role == "body":
            return {"overlay_weight": 0.35}
        if role == "cta":
            return {"overlay_weight": -1.0}
        return {"overlay_weight": 0.0}
    return None


def _build_ai_effect_editing_accents(
    editing_accents: dict[str, Any] | None,
    *,
    keep_segments: list[dict[str, Any]],
    subtitle_items: list[dict[str, Any]],
    timeline_analysis: dict[str, Any] | None,
    editing_skill: dict[str, Any] | None,
    workflow_preset: str | None,
    preserve_color: bool,
    reuse_event_structure: bool = False,
) -> dict[str, Any]:
    base = copy.deepcopy(editing_accents) if isinstance(editing_accents, dict) else {}
    base_style = _resolve_workflow_smart_effect_style(
        str(base.get("style") or ""),
        workflow_preset=workflow_preset,
    )
    effect_style = _resolve_ai_effect_style_variant(base_style)
    tokens = _smart_effect_tokens(effect_style)
    resolved_skill = _resolve_effect_editing_skill(editing_skill, timeline_analysis=timeline_analysis)
    review_focus = _resolve_review_focus_for_accents(
        editing_skill=resolved_skill,
        timeline_analysis=timeline_analysis,
    )
    focused_transition_max_count = _resolve_review_focus_transition_max_count(
        int((resolved_skill or {}).get("transition_max_count") or 0),
        review_focus=review_focus,
    )
    focused_overlay_max_count, focused_overlay_spacing_sec = _resolve_review_focus_overlay_constraints(
        int((resolved_skill or {}).get("overlay_max_count") or 0),
        float((resolved_skill or {}).get("overlay_spacing_sec") or tokens.get("overlay_spacing_sec") or 4.0),
        review_focus=review_focus,
    )
    base_transitions = copy.deepcopy(base.get("transitions") or {})
    base_emphasis_overlays = [dict(item) for item in base.get("emphasis_overlays") or []]
    if reuse_event_structure:
        transition_boundaries = sorted(
            [
                int(index)
                for index in (base_transitions.get("boundary_indexes") or [])
                if isinstance(index, int) or str(index).lstrip("-").isdigit()
            ]
        )
        merged_overlays = base_emphasis_overlays
        sound_effects = [dict(item) for item in base.get("sound_effects") or []]
    else:
        transition_boundaries = sorted(
            {
                *[
                    int(index)
                    for index in (base_transitions.get("boundary_indexes") or [])
                    if isinstance(index, int) or str(index).lstrip("-").isdigit()
                ],
                *_select_transition_boundaries(
                    keep_segments,
                    timeline_analysis=timeline_analysis,
                    editing_skill=resolved_skill,
                    max_count=min(
                        int(tokens.get("transition_max_count") or 6),
                        focused_transition_max_count or int(tokens.get("transition_max_count") or 6),
                    ),
                    min_segment_duration=1.1,
                    min_removed_gap=0.18,
                ),
            }
        )
        text_overlays = _select_emphasis_overlays(
            subtitle_items,
            timeline_analysis=timeline_analysis,
            editing_skill=resolved_skill,
            preferred_candidates=list((timeline_analysis or {}).get("emphasis_candidates") or []),
            max_count=min(
                int(tokens.get("overlay_max_count") or 6),
                focused_overlay_max_count or int(tokens.get("overlay_max_count") or 6),
            ),
            min_spacing_sec=min(
                float(tokens.get("overlay_spacing_sec") or 4.0),
                focused_overlay_spacing_sec,
            ),
            min_duration_sec=0.45,
            max_duration_sec=float(tokens.get("overlay_max_duration_sec") or 1.45),
        )
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
        "preserve_color": preserve_color,
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
    text = _normalize_overlay_label_text(str(item.get("text") or ""))
    if not text and not item.get("allow_empty", True):
        return None
    normalized = {
        "text": text,
        "start_time": round(start_time, 3),
        "end_time": round(end_time, 3),
    }
    for key in ("source", "role", "visual_treatment", "subtitle_unit_role", "packaging_intent"):
        if str(item.get(key) or "").strip():
            normalized[key] = str(item.get(key) or "").strip()
    if "transform_intensity" in item:
        normalized["transform_intensity"] = round(max(0.65, min(1.35, float(item.get("transform_intensity") or 1.0))), 3)
    return normalized


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
    raw = subtitle_display_rule_text(item)
    return _extract_overlay_label_text(raw)


def _extract_overlay_label_text(raw: str) -> str:
    text = _compact_overlay_text(raw)
    if not text:
        return ""
    model_match = re.search(r"\b[A-Z][A-Z0-9+\-]{1,}(?:mini|MAX|PRO|Plus|Ultra)?\b", text, flags=re.IGNORECASE)
    if model_match:
        return _normalize_overlay_label_text(model_match.group(0))
    for term in _OVERLAY_LABEL_TERMS:
        if term not in text:
            continue
        phrase = _overlay_phrase_around_term(text, term)
        label = _normalize_overlay_label_text(phrase)
        if label:
            return label
    return ""


def _overlay_phrase_around_term(text: str, term: str) -> str:
    start = text.find(term)
    if start < 0:
        return term
    end = min(len(text), start + max(len(term), _OVERLAY_LABEL_MAX_CJK_CHARS))
    phrase = text[start:end]
    for marker in ("，", "。", "！", "？", ",", ".", "!", "?", "、", "；", ";", "：", ":"):
        marker_index = phrase.find(marker)
        if marker_index >= 0:
            phrase = phrase[:marker_index]
    for marker in ("一下", "一个", "这个", "那个", "这里", "那边"):
        marker_index = phrase.find(marker, len(term))
        if marker_index >= 0:
            phrase = phrase[:marker_index]
    while len(phrase) > len(term) and phrase[-1] in "的了吧吗呢啊哦哈啦呀嘛":
        phrase = phrase[:-1]
    suffix = phrase[len(term):]
    if suffix and any(marker in suffix for marker in _OVERLAY_LABEL_BAD_SUFFIX_MARKERS):
        return term
    if suffix and not phrase.endswith(_OVERLAY_LABEL_ALLOWED_SUFFIXES):
        return term
    return phrase or term


def _normalize_overlay_label_text(raw: str) -> str:
    text = _compact_overlay_text(raw)
    if len(text) < 2:
        return ""
    cjk_count = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    ascii_count = sum(1 for ch in text if ch.isascii() and ch.isalnum())
    if cjk_count and cjk_count > _OVERLAY_LABEL_MAX_CJK_CHARS:
        return ""
    if not cjk_count and ascii_count > _OVERLAY_LABEL_MAX_ASCII_CHARS:
        return ""
    if cjk_count >= 5 and any(stop_word in text for stop_word in _OVERLAY_LABEL_STOP_WORDS):
        return ""
    if any(mark in text for mark in ("，", "。", "！", "？", ",", ".", "!", "?", "；", ";", "：", ":")):
        return ""
    return text


def _compact_overlay_text(raw: str) -> str:
    text = "".join(str(raw or "").split())
    return text.strip("，。！？!?、,.；;：:\"'()（）[]【】<>《》")


def _score_overlay_text(text: str, *, start_time: float) -> float:
    score = 0.0
    keywords = (
        "重点",
        "关键",
        "注意",
        "提醒",
        "一定",
        "终于",
        "真的",
        "直接",
        "千万",
        "别",
        "你看",
        "看",
        "这里",
        "这个",
        "区别",
        "对比",
        "实测",
        "演示",
        "细节",
        "功能",
        "快拆",
        "锁定",
        "容量",
        "背负",
        "EDC",
        "MT",
        "FXX",
    )
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
