from __future__ import annotations

from roughcut.pipeline.orchestrator import PIPELINE_STEPS, create_job_steps
from roughcut.review.platform_copy import normalize_platform_packaging, render_platform_packaging_markdown


def test_platform_package_step_appended_to_pipeline():
    steps = create_job_steps(__import__("uuid").uuid4())
    assert "content_profile" in PIPELINE_STEPS
    assert "summary_review" in PIPELINE_STEPS
    assert PIPELINE_STEPS[-1] == "platform_package"
    assert any(step.step_name == "content_profile" for step in steps)
    assert any(step.step_name == "summary_review" for step in steps)
    assert steps[-1].step_name == "platform_package"


def test_render_platform_packaging_markdown_outputs_all_platforms():
    packaging = normalize_platform_packaging(
        {
            "highlights": {
                "product": "FAS 工具钳",
                "video_type": "开箱体验",
                "strongest_selling_point": "结构和细节",
                "strongest_emotion": "等很久终于到手",
                "title_hook": "值不值",
                "engagement_question": "你觉得值不值？",
            },
            "platforms": {
                "bilibili": {"titles": ["标题1", "标题2", "标题3", "标题4", "标题5"], "description": "简介", "tags": ["EDC", "开箱"]},
                "xiaohongshu": {"titles": ["小红书1", "小红书2", "小红书3", "小红书4", "小红书5"], "description": "正文", "tags": ["桌搭", "收藏"]},
                "douyin": {"titles": ["抖音1", "抖音2", "抖音3", "抖音4", "抖音5"], "description": "短简介", "tags": ["工具"]},
                "kuaishou": {"titles": ["快手1", "快手2", "快手3", "快手4", "快手5"], "description": "快手简介", "tags": ["玩家"]},
                "wechat_channels": {"titles": ["视频号1", "视频号2", "视频号3", "视频号4", "视频号5"], "description": "视频号简介", "tags": ["分享"]},
            },
        },
        content_profile={"subject_brand": "FAS", "subject_type": "工具钳"},
    )

    markdown = render_platform_packaging_markdown(packaging)

    assert "# 视频爆点提炼" in markdown
    assert "# B站" in markdown
    assert "# 小红书" in markdown
    assert "# 抖音" in markdown
    assert "# 快手" in markdown
    assert "# 视频号" in markdown
    assert "#EDC" in markdown


def test_normalize_platform_packaging_backfills_missing_titles():
    packaging = normalize_platform_packaging(
        {"highlights": {}, "platforms": {"bilibili": {"titles": ["只给一个"], "description": "", "tags": []}}},
        content_profile={"subject_brand": "FAS", "subject_type": "工具钳", "hook_line": "这次升级到位吗"},
    )

    assert len(packaging["platforms"]["bilibili"]["titles"]) == 5
    assert packaging["platforms"]["bilibili"]["description"]
    assert packaging["platforms"]["bilibili"]["tags"]
