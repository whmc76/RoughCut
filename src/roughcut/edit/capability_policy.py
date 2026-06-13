from __future__ import annotations

from typing import Any

from roughcut.edit.capabilities import build_disabled_capability_map
from roughcut.edit.skills import resolve_editing_skill
from roughcut.edit.strategy_profile import (
    DEFAULT_STRATEGY_TYPE,
    infer_strategy_content_kind,
    infer_strategy_type,
    normalize_strategy_profile_payload,
    normalize_strategy_type,
)


def infer_capability_content_kind(
    *,
    workflow_template: str | None = None,
    content_profile: dict[str, Any] | None = None,
) -> str:
    return infer_strategy_content_kind(
        workflow_template=workflow_template,
        content_profile=content_profile,
    )


def resolve_capability_strategy_inputs(
    *,
    strategy_profile: dict[str, Any] | None = None,
    workflow_template: str | None = None,
    content_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inferred_strategy_type = infer_strategy_type(
        strategy_profile=strategy_profile,
        workflow_template=workflow_template,
        content_profile=content_profile,
    )
    normalized_strategy_profile = normalize_strategy_profile_payload(
        strategy_profile,
        default_strategy_type=inferred_strategy_type or DEFAULT_STRATEGY_TYPE,
    )
    content_kind = infer_capability_content_kind(
        workflow_template=workflow_template,
        content_profile=content_profile,
    )
    return {
        "strategy_profile": normalized_strategy_profile,
        "strategy_type": normalize_strategy_type(
            normalized_strategy_profile.get("strategy_type") or inferred_strategy_type
        ),
        "content_kind": content_kind,
        "workflow_template": str(workflow_template or "").strip() or None,
        "editing_skill": resolve_editing_skill(
            workflow_template=workflow_template,
            content_profile=content_profile,
        ),
    }


def resolve_default_capability_states(
    *,
    strategy_profile: dict[str, Any] | None = None,
    workflow_template: str | None = None,
    content_profile: dict[str, Any] | None = None,
) -> dict[str, str]:
    resolved = resolve_capability_strategy_inputs(
        strategy_profile=strategy_profile,
        workflow_template=workflow_template,
        content_profile=content_profile,
    )
    strategy_type = str(resolved["strategy_type"])
    content_kind = str(resolved["content_kind"])
    editing_skill = dict(resolved["editing_skill"] or {})
    states = build_disabled_capability_map()

    section_policy = dict(editing_skill.get("section_policy") or {})
    insert_allowed = any(bool((policy or {}).get("insert_allowed")) for policy in section_policy.values())
    music_allowed = any(bool((policy or {}).get("music_entry_allowed")) for policy in section_policy.values())

    if strategy_type == "information_density":
        states["speech_density_trim"] = "auto_apply"
        if content_kind == "tutorial":
            states["screen_focus"] = "suggest"
            states["chapter_cards"] = "suggest"
        elif content_kind in {"vlog", "food"}:
            states["chapter_cards"] = "suggest"
        elif content_kind == "gameplay":
            states["highlight_window_selection"] = "suggest"
        elif content_kind in {"commentary", "unboxing"}:
            states["chapter_cards"] = "disabled"
        if insert_allowed:
            states["local_broll_insert"] = "suggest"
        if music_allowed:
            states["local_audio_cues"] = "suggest"
    elif strategy_type == "step_demonstration":
        states["speech_density_trim"] = "auto_apply"
        states["screen_focus"] = "auto_apply"
        states["chapter_cards"] = "suggest"
        states["local_broll_insert"] = "suggest"
        states["local_audio_cues"] = "suggest"
    elif strategy_type == "experience_and_mood":
        states["speech_density_trim"] = "suggest"
        states["chapter_cards"] = "disabled"
        states["local_broll_insert"] = "suggest"
        states["local_audio_cues"] = "suggest"
    elif strategy_type == "event_highlight":
        states["speech_density_trim"] = "suggest"
        states["highlight_window_selection"] = "suggest"
        states["local_broll_insert"] = "suggest"
        states["local_audio_cues"] = "suggest"
    elif strategy_type == "narrative_assembly":
        states["local_broll_insert"] = "suggest"
        states["local_audio_cues"] = "suggest"
        states["multi_material_assembly"] = "manual_required"

    return states
