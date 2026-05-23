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


def test_short_low_information_title_blocks_publish() -> None:
    result = assess_platform_titles(
        "xiaohongshu",
        [
            "MOT风灵锆合金到手真香吗",
            "版本差异先看",
            "MOT风灵推牌开箱先看手感",
        ],
        content_profile=_profile(),
    )

    assert result["publish_ready"] is False
    assert any("信息量过弱" in reason or "没有主体锚点" in reason for reason in result["blocking_reasons"])
    assert any("创作方向" in hint or "具体主体" in hint for hint in result["repair_hints"])


def test_short_anchored_hook_title_passes() -> None:
    result = assess_platform_titles(
        "xiaohongshu",
        [
            "MOT风灵锆合金到手真香吗",
            "MOT风灵推牌开箱先看手感",
            "风灵音叉推牌细节太毒",
        ],
        content_profile=_profile(),
    )

    assert result["publish_ready"] is True
    assert result["blocking_reasons"] == []


def test_chinese_source_youtube_titles_do_not_need_english_review_terms() -> None:
    result = assess_platform_titles(
        "youtube",
        [
            "MOT风灵音叉推牌锆合金版开箱评测",
            "MOT风灵锆合金版上手体验和细节差异",
            "MOT风灵推牌锆合金版值不值得选",
        ],
        content_profile=_profile(),
    )

    assert result["publish_ready"] is True
    assert not any("平台常用表达" in warning for warning in result["warnings"])
    assert not any("YouTube 自动改成英文" in hint for hint in result["repair_hints"])
