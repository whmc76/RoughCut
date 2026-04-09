from __future__ import annotations

from copy import deepcopy
from typing import Any

from roughcut.edit.presets import get_workflow_preset, normalize_workflow_template_name

_DEFAULT_SECTION_POLICY = {
    "hook": {
        "overlay_weight": 1.3,
        "transition_boost": 0.55,
        "music_entry_allowed": False,
        "music_entry_bonus": 0.0,
        "insert_allowed": False,
        "insert_priority": 0.0,
        "broll_allowed": False,
        "broll_anchor_bias": 0.2,
        "trim_intensity": "balanced",
        "packaging_intent": "hook_focus",
    },
    "detail": {
        "overlay_weight": 1.0,
        "transition_boost": 1.2,
        "music_entry_allowed": True,
        "music_entry_bonus": 0.1,
        "insert_allowed": True,
        "insert_priority": 1.0,
        "broll_allowed": True,
        "broll_anchor_bias": 0.48,
        "trim_intensity": "balanced",
        "packaging_intent": "detail_support",
    },
    "body": {
        "overlay_weight": 0.35,
        "transition_boost": 0.9,
        "music_entry_allowed": True,
        "music_entry_bonus": 0.05,
        "insert_allowed": True,
        "insert_priority": 0.75,
        "broll_allowed": True,
        "broll_anchor_bias": 0.52,
        "trim_intensity": "balanced",
        "packaging_intent": "body_support",
    },
    "cta": {
        "overlay_weight": -1.0,
        "transition_boost": 0.8,
        "music_entry_allowed": False,
        "music_entry_bonus": -0.2,
        "insert_allowed": False,
        "insert_priority": -1.0,
        "broll_allowed": False,
        "broll_anchor_bias": 0.8,
        "trim_intensity": "preserve",
        "packaging_intent": "cta_protect",
    },
}

_EDITING_SKILLS: dict[str, dict[str, Any]] = {
    "edc_tactical": {
        "key": "edc_tactical",
        "label": "EDC 战术剪辑",
        "content_kind": "unboxing",
        "silence_floor_sec": 0.46,
        "silence_score_bias": 0.03,
        "continuation_guard_penalty": 0.32,
        "transition_max_count": 3,
        "overlay_max_count": 3,
        "overlay_spacing_sec": 5.8,
        "section_policy": {
            **_DEFAULT_SECTION_POLICY,
            "detail": {
                **_DEFAULT_SECTION_POLICY["detail"],
                "overlay_weight": 1.2,
                "transition_boost": 1.3,
                "music_entry_bonus": 0.14,
                "insert_priority": 1.15,
                "broll_anchor_bias": 0.42,
            },
        },
    },
    "unboxing_standard": {
        "key": "unboxing_standard",
        "label": "开箱评测剪辑",
        "content_kind": "unboxing",
        "silence_floor_sec": 0.5,
        "silence_score_bias": 0.0,
        "continuation_guard_penalty": 0.35,
        "transition_max_count": 3,
        "overlay_max_count": 3,
        "overlay_spacing_sec": 6.2,
        "section_policy": deepcopy(_DEFAULT_SECTION_POLICY),
    },
    "tutorial_standard": {
        "key": "tutorial_standard",
        "label": "教程演示剪辑",
        "content_kind": "tutorial",
        "silence_floor_sec": 0.58,
        "silence_score_bias": -0.02,
        "continuation_guard_penalty": 0.44,
        "transition_max_count": 2,
        "overlay_max_count": 3,
        "overlay_spacing_sec": 5.2,
        "section_policy": {
            **_DEFAULT_SECTION_POLICY,
            "detail": {
                **_DEFAULT_SECTION_POLICY["detail"],
                "overlay_weight": 1.25,
                "transition_boost": 1.05,
                "music_entry_bonus": 0.12,
                "insert_priority": 1.2,
                "broll_anchor_bias": 0.38,
            },
            "body": {
                **_DEFAULT_SECTION_POLICY["body"],
                "overlay_weight": 0.8,
                "transition_boost": 0.75,
                "music_entry_bonus": 0.08,
                "insert_priority": 1.0,
                "broll_anchor_bias": 0.34,
            },
        },
    },
    "vlog_daily": {
        "key": "vlog_daily",
        "label": "日常 Vlog 剪辑",
        "content_kind": "vlog",
        "silence_floor_sec": 0.42,
        "silence_score_bias": 0.04,
        "continuation_guard_penalty": 0.24,
        "transition_max_count": 4,
        "overlay_max_count": 3,
        "overlay_spacing_sec": 4.8,
        "section_policy": {
            **_DEFAULT_SECTION_POLICY,
            "body": {
                **_DEFAULT_SECTION_POLICY["body"],
                "overlay_weight": 0.65,
                "transition_boost": 1.1,
                "music_entry_bonus": 0.12,
                "insert_priority": 0.9,
                "broll_anchor_bias": 0.58,
            },
        },
    },
    "commentary_focus": {
        "key": "commentary_focus",
        "label": "口播观点剪辑",
        "content_kind": "commentary",
        "silence_floor_sec": 0.68,
        "silence_score_bias": -0.05,
        "continuation_guard_penalty": 0.5,
        "transition_max_count": 1,
        "overlay_max_count": 2,
        "overlay_spacing_sec": 8.5,
        "section_policy": {
            **_DEFAULT_SECTION_POLICY,
            "hook": {
                **_DEFAULT_SECTION_POLICY["hook"],
                "overlay_weight": 1.5,
                "trim_intensity": "preserve",
            },
            "detail": {
                **_DEFAULT_SECTION_POLICY["detail"],
                "overlay_weight": 0.7,
                "transition_boost": 0.55,
                "insert_allowed": False,
                "insert_priority": 0.0,
                "broll_allowed": False,
            },
            "body": {
                **_DEFAULT_SECTION_POLICY["body"],
                "overlay_weight": 0.25,
                "transition_boost": 0.45,
                "music_entry_bonus": 0.02,
                "insert_allowed": False,
                "insert_priority": 0.0,
                "broll_allowed": False,
                "trim_intensity": "preserve",
            },
        },
    },
    "gameplay_highlight": {
        "key": "gameplay_highlight",
        "label": "游戏高光剪辑",
        "content_kind": "gameplay",
        "silence_floor_sec": 0.34,
        "silence_score_bias": 0.08,
        "continuation_guard_penalty": 0.18,
        "transition_max_count": 5,
        "overlay_max_count": 5,
        "overlay_spacing_sec": 3.4,
        "section_policy": {
            **_DEFAULT_SECTION_POLICY,
            "hook": {
                **_DEFAULT_SECTION_POLICY["hook"],
                "music_entry_allowed": True,
                "music_entry_bonus": 0.06,
                "transition_boost": 0.9,
                "trim_intensity": "tight",
            },
            "detail": {
                **_DEFAULT_SECTION_POLICY["detail"],
                "overlay_weight": 1.3,
                "transition_boost": 1.4,
                "music_entry_bonus": 0.16,
                "broll_anchor_bias": 0.46,
            },
            "body": {
                **_DEFAULT_SECTION_POLICY["body"],
                "overlay_weight": 0.9,
                "transition_boost": 1.15,
                "music_entry_bonus": 0.12,
                "insert_priority": 0.95,
                "broll_anchor_bias": 0.6,
            },
        },
    },
    "food_explore": {
        "key": "food_explore",
        "label": "美食探店剪辑",
        "content_kind": "food",
        "silence_floor_sec": 0.44,
        "silence_score_bias": 0.04,
        "continuation_guard_penalty": 0.26,
        "transition_max_count": 3,
        "overlay_max_count": 3,
        "overlay_spacing_sec": 5.5,
        "section_policy": {
            **_DEFAULT_SECTION_POLICY,
            "detail": {
                **_DEFAULT_SECTION_POLICY["detail"],
                "overlay_weight": 1.1,
                "transition_boost": 1.15,
                "music_entry_bonus": 0.12,
                "insert_priority": 1.1,
                "broll_anchor_bias": 0.45,
            },
            "body": {
                **_DEFAULT_SECTION_POLICY["body"],
                "overlay_weight": 0.55,
                "transition_boost": 0.95,
                "music_entry_bonus": 0.08,
                "broll_anchor_bias": 0.56,
            },
        },
    },
}

_CONTENT_KIND_TO_SKILL = {
    "tutorial": "tutorial_standard",
    "vlog": "vlog_daily",
    "commentary": "commentary_focus",
    "gameplay": "gameplay_highlight",
    "food": "food_explore",
    "unboxing": "unboxing_standard",
}


def resolve_editing_skill(
    *,
    workflow_template: str | None = None,
    content_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_template = normalize_workflow_template_name(workflow_template)
    if normalized_template in _EDITING_SKILLS:
        return deepcopy(_EDITING_SKILLS[normalized_template])

    profile = content_profile or {}
    content_kind = str(profile.get("content_kind") or "").strip().lower()
    if content_kind in _CONTENT_KIND_TO_SKILL:
        return deepcopy(_EDITING_SKILLS[_CONTENT_KIND_TO_SKILL[content_kind]])

    preset = get_workflow_preset(workflow_template)
    return deepcopy(_EDITING_SKILLS.get(preset.name, _EDITING_SKILLS[_CONTENT_KIND_TO_SKILL.get(preset.content_kind, "unboxing_standard")]))


def apply_review_focus_overrides(
    editing_skill: dict[str, Any] | None,
    *,
    review_focus: str | None = None,
) -> dict[str, Any]:
    skill = deepcopy(editing_skill or _EDITING_SKILLS["unboxing_standard"])
    if skill.get("_review_focus_applied"):
        return skill
    normalized_focus = str(review_focus or "").strip().lower()
    if not normalized_focus:
        return skill

    section_policy = dict(skill.get("section_policy") or {})
    skill["review_focus"] = normalized_focus
    skill["_review_focus_applied"] = True

    if normalized_focus == "hook_boundary":
        skill["silence_floor_sec"] = round(float(skill.get("silence_floor_sec", 0.5) or 0.5) + 0.12, 3)
        skill["silence_score_bias"] = round(float(skill.get("silence_score_bias", 0.0) or 0.0) - 0.05, 3)
        skill["continuation_guard_penalty"] = round(
            float(skill.get("continuation_guard_penalty", 0.35) or 0.35) + 0.14,
            3,
        )
        hook_policy = {**dict(section_policy.get("hook") or {}), "trim_intensity": "preserve"}
        section_policy["hook"] = hook_policy
        skill["focus_cut_guard"] = {"hook": 0.22}
        skill["focus_keep_energy_bonus"] = {"hook": 0.28}
    elif normalized_focus == "mid_transition":
        skill["silence_floor_sec"] = round(float(skill.get("silence_floor_sec", 0.5) or 0.5) + 0.08, 3)
        skill["silence_score_bias"] = round(float(skill.get("silence_score_bias", 0.0) or 0.0) - 0.03, 3)
        skill["continuation_guard_penalty"] = round(
            float(skill.get("continuation_guard_penalty", 0.35) or 0.35) + 0.08,
            3,
        )
        for role in ("detail", "body"):
            role_policy = {**dict(section_policy.get(role) or {})}
            role_policy["trim_intensity"] = "preserve"
            section_policy[role] = role_policy
        skill["focus_cut_guard"] = {"detail": 0.14, "body": 0.14}
        skill["focus_keep_energy_bonus"] = {"detail": 0.18, "body": 0.18}
    elif normalized_focus == "cta_transition":
        skill["silence_floor_sec"] = round(float(skill.get("silence_floor_sec", 0.5) or 0.5) + 0.14, 3)
        skill["silence_score_bias"] = round(float(skill.get("silence_score_bias", 0.0) or 0.0) - 0.06, 3)
        skill["continuation_guard_penalty"] = round(
            float(skill.get("continuation_guard_penalty", 0.35) or 0.35) + 0.14,
            3,
        )
        cta_policy = {**dict(section_policy.get("cta") or {}), "trim_intensity": "preserve"}
        section_policy["cta"] = cta_policy
        skill["focus_cut_guard"] = {"cta": 0.24}
        skill["focus_keep_energy_bonus"] = {"cta": 0.24}

    skill["section_policy"] = section_policy
    return skill
