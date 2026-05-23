from __future__ import annotations

import pytest

from roughcut.review import platform_copy
from roughcut.review.platform_body_quality import assess_platform_body


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


def test_platform_packaging_hardening_does_not_replace_llm_copy() -> None:
    content_profile = {
        "subject_brand": "MOT",
        "subject_model": "风灵音叉推牌",
        "subject_type": "锆合金版本",
        "video_theme": "开箱上手",
    }
    raw = _valid_packaging()
    for key in raw["platforms"]:
        raw["platforms"][key]["titles"] = ["先看细节", "真实体验", "MOT 风灵音叉推牌到手"]
        raw["platforms"][key]["description"] = "今天回到老本行，第一眼先看细节，建议发布前人工核对具体型号。"

    normalized = platform_copy.normalize_platform_packaging(
        raw,
        content_profile=content_profile,
        copy_style="attention_grabbing",
        fact_sheet={"status": "unverified"},
    )
    hardened = platform_copy._harden_platform_packaging_for_publish(
        normalized,
        content_profile=content_profile,
        copy_style="attention_grabbing",
        fact_sheet={"status": "unverified"},
    )
    assert hardened["platforms"]["xiaohongshu"]["titles"] == ["先看细节", "真实体验", "MOT 风灵音叉推牌到手"]
    assert all("第一" not in platform["description"] for platform in hardened["platforms"].values())
    assert any(
        platform_copy._assess_platform_packaging_quality(
            hardened,
            content_profile=content_profile,
            fact_sheet={"status": "unverified"},
        )["blocking_reasons"]
    )


def test_normalize_ignores_polluted_subject_anchor_without_synthesizing_copy() -> None:
    content_profile = {
        "subject_model": "MOT 风灵音叉推牌 锆合金版本，建议发布前人工核对具体型号与参数。",
        "subject_type": "音叉推牌",
        "video_theme": "开箱上手",
    }
    raw = _valid_packaging()
    for key in raw["platforms"]:
        raw["platforms"][key]["titles"] = ["先看细节", "真实体验", "MOT 风灵音叉推牌到手"]
        raw["platforms"][key]["description"] = "MOT 风灵音叉推牌这次主要看开箱、声音和近景细节，到手后的质感比较直观。"

    normalized = platform_copy.normalize_platform_packaging(
        raw,
        content_profile=content_profile,
        copy_style="attention_grabbing",
        fact_sheet={"status": "unverified"},
    )
    assessment = platform_copy._assess_platform_packaging_quality(
        normalized,
        content_profile=content_profile,
        fact_sheet={"status": "unverified"},
    )

    assert not any("人工核对" in reason for reason in assessment["blocking_reasons"])
    assert normalized["platforms"]["xiaohongshu"]["titles"] == ["先看细节", "真实体验", "MOT 风灵音叉推牌到手"]


def test_normalize_keeps_bad_titles_for_quality_gate_instead_of_forcing_safe_titles() -> None:
    content_profile = {
        "subject_model": "MOT 风灵音叉推牌 锆合金版本",
        "subject_type": "锆合金版本",
    }
    raw = _valid_packaging()
    raw["platforms"]["xiaohongshu"]["titles"] = ["产品细节先看", "产品开箱体验", "产品到手记录"]
    raw["platforms"]["wechat_channels"]["titles"] = ["产品开箱体验", "产品细节总结", "产品到手记录"]

    normalized = platform_copy.normalize_platform_packaging(
        raw,
        content_profile=content_profile,
        copy_style="attention_grabbing",
        fact_sheet={"status": "unverified"},
    )

    assert platform_copy._assess_platform_packaging_quality(
        normalized,
        content_profile=content_profile,
        fact_sheet={"status": "unverified"},
    )["blocking_reasons"]


def test_compact_product_label_truncates_model_before_generic_subject() -> None:
    content_profile = {
        "subject_model": "MOT 风灵音叉推牌 锆合金版本",
        "subject_type": "产品",
    }

    label = platform_copy._compact_product_label(content_profile, label="视频号")

    assert "产品" not in label
    assert "MOT" in label


def test_strict_normalization_caps_titles_to_three() -> None:
    raw = _valid_packaging()
    raw["platforms"]["xiaohongshu"]["titles"] = [
        "MOT 风灵音叉到手值不值",
        "MOT 风灵音叉声音细节实拍",
        "MOT 风灵音叉做工怎么选",
        "MOT 风灵音叉第四条不该保留",
        "MOT 风灵音叉第五条不该保留",
    ]

    normalized = platform_copy._normalize_generated_platform_packaging_strict(
        raw,
        content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
    )

    assert normalized["platforms"]["xiaohongshu"]["titles"] == [
        "MOT 风灵音叉到手值不值",
        "MOT 风灵音叉声音细节实拍",
        "MOT 风灵音叉做工怎么选",
    ]


def test_fact_guardrail_does_not_synthesize_replacement_copy() -> None:
    raw = _valid_packaging()
    raw["highlights"]["title_hook"] = "续航提升 100%"
    raw["platforms"]["xiaohongshu"]["titles"] = [
        "MOT 风灵音叉续航提升 100%",
        "MOT 风灵音叉价格贵一倍",
        "MOT 风灵音叉到手值不值",
    ]
    raw["platforms"]["xiaohongshu"]["description"] = "MOT 风灵音叉这次续航提升 100%，价格也贵一倍。"

    guarded = platform_copy._enforce_packaging_fact_guardrails(
        raw,
        content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
        copy_style="attention_grabbing",
        fact_sheet={"status": "unverified", "verified_facts": []},
    )

    assert guarded["highlights"]["title_hook"] == ""
    assert guarded["platforms"]["xiaohongshu"]["titles"] == ["MOT 风灵音叉到手值不值"]
    assert guarded["platforms"]["xiaohongshu"]["description"] == ""


def test_description_variation_gate_does_not_synthesize_replacements() -> None:
    raw = _valid_packaging()
    duplicate = "MOT 风灵音叉这次看声音、握持和近景细节，上手质感比单看照片更直观。"
    raw["platforms"]["xiaohongshu"]["description"] = duplicate
    raw["platforms"]["douyin"]["description"] = duplicate

    varied = platform_copy._enforce_platform_description_variation(
        raw,
        content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
        copy_style="attention_grabbing",
        author_profile=None,
    )

    assert varied["platforms"]["xiaohongshu"]["description"] == duplicate
    assert varied["platforms"]["douyin"]["description"] == duplicate


def test_body_quality_allows_first_impression_context() -> None:
    result = assess_platform_body(
        "xiaohongshu",
        "MOT 风灵音叉推牌锆合金版本到手，第一眼先看做工和外观，细节、手感和近景质感都按实拍来聊。",
        content_profile={"subject_model": "MOT 风灵音叉推牌锆合金版本"},
        fact_sheet={"status": "unverified"},
    )

    assert result["publish_ready"] is True
    assert not any("第一" in reason for reason in result["blocking_reasons"])


def test_body_quality_accepts_english_platform_anchor_tokens() -> None:
    result = assess_platform_body(
        "youtube",
        "A hands-on look at the MOT Fengling Zirconium Alloy version, focusing on build quality, version differences, and real handling impressions.",
        content_profile={"subject_model": "MOT 风灵音叉推牌 锆合金版本"},
        fact_sheet={"status": "unverified"},
    )

    assert result["publish_ready"] is True
    assert not any("主体锚点" in reason for reason in result["blocking_reasons"])
    assert not any("体验细节" in reason for reason in result["blocking_reasons"])


def test_source_language_instruction_blocks_implicit_youtube_translation() -> None:
    instruction = platform_copy._build_source_language_instruction("zh-CN")

    assert "所有平台" in instruction
    assert "YouTube" in instruction
    assert "不能" in instruction
    assert "英文" in instruction


def test_normalize_does_not_backfill_missing_description() -> None:
    raw = _valid_packaging()
    raw["platforms"]["xiaohongshu"]["description"] = ""

    normalized = platform_copy.normalize_platform_packaging(
        raw,
        content_profile={"subject_model": "MOT 风灵音叉", "subject_type": "音叉推牌"},
        copy_style="attention_grabbing",
        fact_sheet={"status": "unverified"},
    )

    assert normalized["platforms"]["xiaohongshu"]["description"] == ""
