from __future__ import annotations

from roughcut.edit.skills import apply_review_focus_overrides, resolve_editing_skill


def test_resolve_editing_skill_prefers_workflow_template():
    skill = resolve_editing_skill(workflow_template="commentary_focus", content_profile={"content_kind": "gameplay"})

    assert skill["key"] == "commentary_focus"
    assert skill["transition_max_count"] == 1
    assert skill["overlay_max_count"] == 2


def test_resolve_editing_skill_falls_back_to_content_kind():
    skill = resolve_editing_skill(workflow_template=None, content_profile={"content_kind": "tutorial"})

    assert skill["key"] == "tutorial_standard"
    assert skill["section_policy"]["detail"]["insert_allowed"] is True
    assert skill["section_policy"]["hook"]["music_entry_allowed"] is False
    assert skill["section_policy"]["detail"]["broll_anchor_bias"] < 0.5
    assert skill["silence_floor_sec"] > 0.5


def test_apply_review_focus_overrides_adjusts_skill_for_hook_boundary():
    skill = apply_review_focus_overrides(
        resolve_editing_skill(workflow_template="unboxing_standard", content_profile={}),
        review_focus="hook_boundary",
    )

    assert skill["review_focus"] == "hook_boundary"
    assert skill["silence_floor_sec"] > 0.5
    assert skill["continuation_guard_penalty"] > 0.35
    assert skill["section_policy"]["hook"]["trim_intensity"] == "preserve"
    assert skill["focus_cut_guard"]["hook"] > 0.0
