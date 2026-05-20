from __future__ import annotations

from roughcut.review.platform_title_quality import assess_platform_titles


def _profile() -> dict[str, object]:
    return {
        "subject_brand": "MOT",
        "subject_model": "风灵音叉推牌",
        "subject_type": "EDC 推牌",
        "video_theme": "MOT 风灵音叉推牌开箱与上手体验",
        "search_queries": ["MOT 风灵音叉推牌", "EDC 推牌"],
    }


def test_empty_titles_block_publish() -> None:
    result = assess_platform_titles("douyin", [], content_profile=_profile())

    assert result["publish_ready"] is False
    assert any("少于 3 个" in reason for reason in result["blocking_reasons"])
    assert any("缺少可发布标题" in reason for reason in result["blocking_reasons"])
    assert result["repair_hints"]


def test_unanchored_generic_titles_block_publish() -> None:
    result = assess_platform_titles(
        "douyin",
        ["这条视频会怎么发", "先看细节", "真实体验"],
        content_profile=_profile(),
    )

    assert result["publish_ready"] is False
    assert any("没有主体锚点" in reason for reason in result["blocking_reasons"])
    assert any("没有任何标题命中主体锚点" in reason for reason in result["blocking_reasons"])
    assert any("具体主体" in hint for hint in result["repair_hints"])


def test_repeated_title_angles_warn_without_blocking_when_anchored() -> None:
    result = assess_platform_titles(
        "bilibili",
        [
            "MOT 风灵音叉推牌到底值不值",
            "MOT 风灵音叉推牌到底好不好用",
            "MOT 风灵音叉推牌到底适合谁",
        ],
        content_profile=_profile(),
    )

    assert result["publish_ready"] is True
    assert any("角度重复" in warning for warning in result["warnings"])
    assert any("至少 2 种角度" in hint for hint in result["repair_hints"])


def test_publish_ready_titles_pass() -> None:
    result = assess_platform_titles(
        "douyin",
        [
            "MOT 风灵音叉推牌开箱",
            "风灵音叉推牌到底值不值",
            "EDC 推牌上手先看细节",
        ],
        content_profile=_profile(),
    )

    assert result["publish_ready"] is True
    assert result["blocking_reasons"] == []
