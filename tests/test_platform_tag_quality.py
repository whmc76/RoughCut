from __future__ import annotations

from roughcut.review.platform_tag_quality import assess_platform_tags


def test_empty_tags_block_publish():
    result = assess_platform_tags("douyin", [])

    assert result["publish_ready"] is False
    assert result["normalized_tags"] == []
    assert any("标签为空" in reason for reason in result["blocking_reasons"])
    assert any("主体/品类/品牌/场景锚点" in hint for hint in result["repair_hints"])


def test_duplicate_tags_are_deduped_with_warning():
    result = assess_platform_tags(
        "bilibili",
        ["#OLIGHT", "olight", "EDC", "edc", "露营手电"],
        content_profile={"subject_brand": "OLIGHT", "subject_type": "手电"},
    )

    assert result["publish_ready"] is True
    assert result["normalized_tags"] == ["OLIGHT", "EDC", "露营手电"]
    assert any("已去重重复标签" in warning for warning in result["warnings"])


def test_generic_only_tags_block_without_anchor():
    result = assess_platform_tags("xiaohongshu", ["EDC", "开箱", "体验"])

    assert result["publish_ready"] is False
    assert any("缺少主体/品类/品牌/场景锚点" in reason for reason in result["blocking_reasons"])
    assert any("只有泛标签组合" in reason for reason in result["blocking_reasons"])
    assert any("减少 EDC/开箱/体验" in hint for hint in result["repair_hints"])


def test_subject_anchor_tag_passes():
    result = assess_platform_tags(
        "douyin",
        ["EDC", "OLIGHT Arkfeld", "露营手电", "夜跑装备"],
        content_profile={
            "subject_brand": "OLIGHT",
            "subject_model": "Arkfeld",
            "subject_type": "手电",
            "usage_scene": "夜跑",
        },
    )

    assert result["publish_ready"] is True
    assert result["blocking_reasons"] == []
    assert result["normalized_tags"] == ["EDC", "OLIGHT Arkfeld", "露营手电", "夜跑装备"]
