from roughcut.creative.director import _build_video_understanding_prompt_section
from roughcut.edit.skills import resolve_editing_skill
from roughcut.review.content_profile_memory import merge_content_profile_creative_preferences


def _video_understanding_profile() -> dict:
    return {
        "video_understanding": {
            "global_understanding": {
                "style_profile": {
                    "pace": "fast",
                    "information_density": "high",
                },
            },
            "automation_hints": {
                "editing_bias": {
                    "protect_roles": ["comparison", "detail_showcase", "demo"],
                    "preferred_sections": ["hook", "demo"],
                }
            },
        }
    }


def test_video_understanding_infers_creative_preferences() -> None:
    preferences = merge_content_profile_creative_preferences(_video_understanding_profile())
    tags = {item["tag"] for item in preferences}

    assert "comparison_focus" in tags
    assert "detail_focus" in tags
    assert "practical_demo" in tags
    assert "fast_paced" in tags
    assert "workflow_breakdown" in tags
    assert "conclusion_first" in tags


def test_video_understanding_influences_editing_skill() -> None:
    skill = resolve_editing_skill(
        workflow_template="unboxing_standard",
        content_profile=_video_understanding_profile(),
    )

    assert skill["silence_floor_sec"] == 0.42
    assert skill["continuation_guard_penalty"] == 0.43
    assert "comparison_focus" in skill["creative_preferences"]
    assert skill["section_policy"]["detail"]["trim_intensity"] == "preserve"
    assert skill["section_policy"]["detail"]["overlay_weight"] > 1.3


def test_video_understanding_prompt_section_exposes_multimodal_context() -> None:
    section = _build_video_understanding_prompt_section(
        {
            "video_understanding": {
                "global_understanding": {
                    "video_theme": "NITECORE EDC17 开箱对比",
                    "summary": "重点看上手和差异。",
                    "narrative_structure": [{"label": "hook", "start": 0.0, "end": 4.0}],
                    "style_profile": {"pace": "fast"},
                },
                "automation_hints": {
                    "editing_bias": {
                        "protect_roles": ["comparison", "detail_showcase"],
                    }
                },
            }
        }
    )

    assert "多模态视频理解" in section
    assert "NITECORE EDC17 开箱对比" in section
    assert "comparison" in section
