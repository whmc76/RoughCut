from __future__ import annotations

import pytest

from roughcut.review import platform_copy


def _valid_packaging() -> dict:
    platforms = {}
    for key, _label, _body_label, _tag_label in platform_copy.PLATFORM_ORDER:
        platforms[key] = {
            "titles": [
                "MOT 风灵音叉开箱先看声音细节",
                "MOT 风灵音叉上手后值不值",
                "MOT 风灵音叉这次做工怎么看",
            ],
            "description": "MOT 风灵音叉这次主要看开箱后的声音、握持和近景细节，上手那一下的质感比单看照片更直观。",
            "tags": ["MOT风灵音叉", "音叉推牌", "EDC开箱"],
        }
    return {
        "highlights": {
            "product": "MOT 风灵音叉",
            "video_type": "开箱上手",
            "strongest_selling_point": "声音、细节、做工",
            "strongest_emotion": "真实上手",
            "title_hook": "先看声音细节",
            "engagement_question": "你会怎么选？",
        },
        "platforms": platforms,
    }


def test_platform_packaging_quality_gate_accepts_specific_creator_copy() -> None:
    assessment = platform_copy._assess_platform_packaging_candidate(
        _valid_packaging(),
        content_profile={
            "subject_model": "MOT 风灵音叉",
            "subject_type": "音叉推牌",
            "video_theme": "开箱上手",
        },
        fact_sheet={"status": "unverified"},
    )

    assert assessment["publish_ready"] is True


def test_platform_packaging_quality_gate_rejects_ai_fallback_copy() -> None:
    payload = _valid_packaging()
    payload["platforms"]["douyin"]["description"] = "这条视频主要围绕 MOT 风灵音叉展开，建议发布前人工核对具体型号与参数。"

    assessment = platform_copy._assess_platform_packaging_candidate(
        payload,
        content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
        fact_sheet={"status": "unverified"},
    )

    assert assessment["publish_ready"] is False
    assert any("抖音正文" in reason for reason in assessment["blocking_reasons"])
    assert any("兜底" in hint or "现场观察" in hint for hint in assessment["repair_hints"])


def test_platform_packaging_publishable_raises_on_low_quality_copy() -> None:
    payload = _valid_packaging()
    payload["platforms"]["xiaohongshu"]["titles"] = ["先看细节", "真实体验", "这条视频会怎么发"]
    normalized = platform_copy._normalize_generated_platform_packaging_strict(
        payload,
        content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
    )

    with pytest.raises(RuntimeError, match="文案模型输出质量不达标"):
        platform_copy._assert_platform_packaging_publishable(
            normalized,
            content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
            fact_sheet={"status": "unverified"},
        )
