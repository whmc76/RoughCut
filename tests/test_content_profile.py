from __future__ import annotations

from roughcut.edit.presets import get_workflow_preset
import pytest

from roughcut.review.content_profile import apply_content_profile_feedback, build_cover_title


def test_build_cover_title_avoids_generic_main_line():
    preset = get_workflow_preset("unboxing_upgrade")
    title = build_cover_title(
        {
            "subject_brand": "曼（MAN）",
            "subject_model": "工具钳（具体型号未知）",
            "subject_type": "多功能工具钳",
            "video_theme": "产品开箱与上手体验",
            "hook_line": "",
        },
        preset,
    )

    assert title["top"] == "MAN"
    assert title["main"] == "MAN多功能工具钳"
    assert title["bottom"] == "这次升级够不够狠"


def test_build_cover_title_prefers_visible_english_brand():
    preset = get_workflow_preset("unboxing_upgrade")
    title = build_cover_title(
        {
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "战术钳",
            "video_theme": "",
            "visible_text": "LEATHERMAN SURGE",
            "hook_line": "",
        },
        preset,
    )

    assert title["top"] == "LEATHERMAN"
    assert title["main"] == "LEATHERMAN战术钳"


@pytest.mark.asyncio
async def test_apply_content_profile_feedback_prefers_user_values():
    result = await apply_content_profile_feedback(
        draft_profile={
            "subject_brand": "FAS",
            "subject_model": "旧型号",
            "subject_type": "工具钳",
            "video_theme": "开箱评测",
            "transcript_excerpt": "测试字幕",
        },
        source_name="video.mp4",
        channel_profile=None,
        user_feedback={
            "subject_model": "马年限定版",
            "summary": "这是用户确认后的摘要",
            "keywords": ["FAS", "马年限定版", "工具钳"],
        },
    )

    assert result["subject_model"] == "马年限定版"
    assert result["summary"] == "这是用户确认后的摘要"
    assert result["search_queries"]
    assert any("FAS" in item for item in result["search_queries"])
