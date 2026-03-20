from __future__ import annotations

from roughcut.pipeline.orchestrator import PIPELINE_STEPS, create_job_steps
from roughcut.review.platform_copy import normalize_platform_packaging, render_platform_packaging_markdown


def test_platform_package_step_appended_to_pipeline():
    steps = create_job_steps(__import__("uuid").uuid4())
    assert "content_profile" in PIPELINE_STEPS
    assert "summary_review" in PIPELINE_STEPS
    assert "final_review" in PIPELINE_STEPS
    assert PIPELINE_STEPS.index("glossary_review") < PIPELINE_STEPS.index("content_profile")
    assert "ai_director" in PIPELINE_STEPS
    assert "avatar_commentary" in PIPELINE_STEPS
    assert PIPELINE_STEPS.index("render") < PIPELINE_STEPS.index("final_review") < PIPELINE_STEPS.index("platform_package")
    assert PIPELINE_STEPS[-1] == "platform_package"
    assert any(step.step_name == "content_profile" for step in steps)
    assert any(step.step_name == "summary_review" for step in steps)
    assert any(step.step_name == "final_review" for step in steps)
    assert any(step.step_name == "ai_director" for step in steps)
    assert any(step.step_name == "avatar_commentary" for step in steps)
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


def test_normalize_platform_packaging_keeps_product_blank_when_identity_is_uncertain():
    packaging = normalize_platform_packaging(
        {
            "highlights": {"product": "LEATHERMAN ARC"},
            "platforms": {
                "bilibili": {"titles": [], "description": "", "tags": []},
                "xiaohongshu": {"titles": [], "description": "", "tags": []},
                "douyin": {"titles": [], "description": "", "tags": []},
                "kuaishou": {"titles": [], "description": "", "tags": []},
                "wechat_channels": {"titles": [], "description": "", "tags": []},
            },
        },
        content_profile={"subject_brand": "", "subject_model": "", "subject_type": "开箱产品", "video_theme": "开箱体验"},
    )

    assert packaging["highlights"]["product"] == ""
    assert packaging["platforms"]["bilibili"]["titles"][0] == "先说重点，这期开箱重点看哪些细节"
    assert "不编产品名" in packaging["platforms"]["bilibili"]["description"]
    assert "工具" not in packaging["platforms"]["bilibili"]["description"]
    assert packaging["platforms"]["bilibili"]["tags"] == ["开箱体验", "开箱", "上手体验", "玩家分享"]


def test_normalize_platform_packaging_preserves_specific_identity_when_available():
    packaging = normalize_platform_packaging(
        {"highlights": {}, "platforms": {"bilibili": {"titles": [], "description": "", "tags": []}}},
        content_profile={"subject_brand": "REATE", "subject_type": "EDC折刀", "video_theme": "折刀雕刻开箱"},
    )

    assert packaging["highlights"]["product"] == "REATE EDC折刀"
    assert packaging["platforms"]["bilibili"]["titles"][0].startswith("REATE EDC折刀：")
    assert packaging["platforms"]["bilibili"]["tags"][:4] == ["REATE", "EDC折刀", "折刀雕刻开箱", "EDC"]


def test_normalize_platform_packaging_prefers_brand_model_in_fallback_copy():
    packaging = normalize_platform_packaging(
        {"highlights": {}, "platforms": {"bilibili": {"titles": [], "description": "", "tags": []}}},
        content_profile={"subject_brand": "Loop露普", "subject_model": "SK05二代Pro UV版", "subject_type": "EDC手电"},
    )

    assert packaging["platforms"]["bilibili"]["titles"][0].startswith("Loop露普 SK05二代Pro UV版：")
    assert "Loop露普 SK05二代Pro UV版" in packaging["platforms"]["bilibili"]["description"]
    assert packaging["platforms"]["xiaohongshu"]["titles"][0] == "Loop露普 SK05二代Pro UV版终于到手，细节直接封神"


def test_normalize_platform_packaging_applies_global_copy_style_to_fallbacks():
    packaging = normalize_platform_packaging(
        {"highlights": {}, "platforms": {"bilibili": {"titles": [], "description": "", "tags": []}}},
        content_profile={"subject_brand": "RunningHub", "subject_model": "无限画布", "subject_type": "AI工作流创作平台", "hook_line": "这功能强得离谱"},
        copy_style="trusted_expert",
    )

    assert "关键差异" in packaging["platforms"]["bilibili"]["titles"][0]
    assert packaging["platforms"]["bilibili"]["description"].startswith("先把核心判断放前面，")


def test_normalize_platform_packaging_applies_platform_bias_to_descriptions():
    packaging = normalize_platform_packaging(
        {
            "highlights": {},
            "platforms": {
                "bilibili": {"titles": [], "description": "", "tags": []},
                "xiaohongshu": {"titles": [], "description": "", "tags": []},
                "douyin": {"titles": [], "description": "", "tags": []},
                "kuaishou": {"titles": [], "description": "", "tags": []},
                "wechat_channels": {"titles": [], "description": "", "tags": []},
            },
        },
        content_profile={"subject_brand": "RunningHub", "subject_model": "无限画布", "subject_type": "AI工作流创作平台"},
        copy_style="attention_grabbing",
    )

    assert "核心判断" in packaging["platforms"]["bilibili"]["description"]
    assert "真实开箱分享" not in packaging["platforms"]["bilibili"]["description"]
    assert "真实开箱分享" in packaging["platforms"]["xiaohongshu"]["description"]
    assert "压进这一条里了" in packaging["platforms"]["douyin"]["description"]
    assert "按实话给你讲" in packaging["platforms"]["kuaishou"]["description"]
    assert "方便快速做判断" in packaging["platforms"]["wechat_channels"]["description"]


def test_normalize_platform_packaging_strips_unverified_spec_claims():
    packaging = normalize_platform_packaging(
        {
            "highlights": {
                "strongest_selling_point": "极亮直接翻倍到2500流明",
                "title_hook": "还没发布呢闲鱼已经有人卖了",
            },
            "platforms": {
                "bilibili": {
                    "titles": ["极亮2500流明！SK05二代Pro UV版升级太狠了"],
                    "description": "极亮直接翻倍到2500流明，UV灯功率1200毫瓦。",
                    "tags": [],
                }
            },
        },
        content_profile={"subject_brand": "Loop露普", "subject_model": "SK05二代Pro UV版", "subject_type": "手电"},
        fact_sheet={"status": "unverified", "verified_facts": [], "official_sources": []},
    )

    assert packaging["highlights"]["strongest_selling_point"] == ""
    assert "2500" not in packaging["platforms"]["bilibili"]["titles"][0]
    assert "1200" not in packaging["platforms"]["bilibili"]["description"]


def test_normalize_platform_packaging_keeps_verified_spec_claims():
    packaging = normalize_platform_packaging(
        {
            "highlights": {
                "strongest_selling_point": "总光通量4360流明，射程405米",
            },
            "platforms": {
                "bilibili": {
                    "titles": ["SK05 Pro 4360流明和405米射程到底够不够用"],
                    "description": "这次重点看4360流明总光通量和405米射程。",
                    "tags": [],
                }
            },
        },
        content_profile={"subject_brand": "Loop", "subject_model": "SK05 Pro", "subject_type": "手电"},
        fact_sheet={
            "status": "verified",
            "verified_facts": [
                {"fact": "总光通量 4360 lm", "source_url": "https://example.com/spec", "source_title": "spec"},
                {"fact": "射程 405 m", "source_url": "https://example.com/spec", "source_title": "spec"},
            ],
            "official_sources": [{"title": "spec", "url": "https://example.com/spec"}],
        },
    )

    assert "4360" in packaging["platforms"]["bilibili"]["titles"][0]
    assert "405" in packaging["platforms"]["bilibili"]["description"]


def test_normalize_platform_packaging_replaces_wrong_near_sound_identity_with_confirmed_anchor():
    packaging = normalize_platform_packaging(
        {
            "highlights": {
                "title_hook": "今天给大家介绍一个意料之外的新品，陆虎SK零五二代。",
            },
            "platforms": {
                "bilibili": {
                    "titles": ["Loop露普EDC手电：今天给大家介绍一个意料之外的新品，陆虎SK零五二代。"],
                    "description": "这次开箱的是Loop露普EDC手电。",
                    "tags": [],
                }
            },
        },
        content_profile={"subject_brand": "Loop露普", "subject_model": "SK05二代Pro UV版", "subject_type": "手电"},
        fact_sheet={"status": "unverified", "verified_facts": [], "official_sources": []},
    )

    assert packaging["highlights"]["title_hook"] == "这次重点看哪些细节"
    assert packaging["platforms"]["bilibili"]["titles"][0].startswith("Loop露普 SK05二代Pro UV版：")
    assert "陆虎" not in packaging["platforms"]["bilibili"]["titles"][0]


def test_normalize_platform_packaging_adds_author_info_by_platform_strategy():
    author_profile = {
        "display_name": "赛博迪克朗",
        "presenter_alias": "CyberDickLang",
        "creator_profile": {
            "identity": {
                "public_name": "赛博迪克朗",
                "title": "EDC评测作者",
            },
            "positioning": {
                "creator_focus": "手电开箱、EDC装备",
                "style": "真实上手、不接硬广",
                "expertise": ["手电", "EDC", "工具"],
            },
        },
    }

    packaging = normalize_platform_packaging(
        {"highlights": {}, "platforms": {"bilibili": {"titles": [], "description": "", "tags": []}}},
        content_profile={"subject_brand": "Loop露普", "subject_model": "SK05二代Pro UV版", "subject_type": "手电"},
        author_profile=author_profile,
    )

    assert "赛博迪克朗" in packaging["platforms"]["bilibili"]["description"]
    assert "长期关注手电开箱、EDC装备" in packaging["platforms"]["bilibili"]["description"]
    assert "平时主要分享手电开箱、EDC装备" in packaging["platforms"]["xiaohongshu"]["description"]
    assert "平时就盯手电开箱、EDC装备" in packaging["platforms"]["douyin"]["description"]
    assert "平时就爱折腾手电开箱、EDC装备" in packaging["platforms"]["kuaishou"]["description"]


def test_normalize_platform_packaging_rewrites_overly_similar_descriptions():
    same_description = "这次开箱的是Loop露普 SK05二代Pro UV版，重点看细节、质感和真实上手体验，方便快速做判断。"

    packaging = normalize_platform_packaging(
        {
            "highlights": {},
            "platforms": {
                "bilibili": {"titles": [], "description": same_description, "tags": []},
                "xiaohongshu": {"titles": [], "description": same_description, "tags": []},
                "douyin": {"titles": [], "description": same_description, "tags": []},
                "kuaishou": {"titles": [], "description": same_description, "tags": []},
                "wechat_channels": {"titles": [], "description": same_description, "tags": []},
            },
        },
        content_profile={"subject_brand": "Loop露普", "subject_model": "SK05二代Pro UV版", "subject_type": "手电"},
    )

    descriptions = [
        packaging["platforms"][key]["description"]
        for key in ["bilibili", "xiaohongshu", "douyin", "kuaishou", "wechat_channels"]
    ]

    assert len(set(descriptions)) == 5
    assert "不是硬广，更像一次有质感的真实开箱分享" in packaging["platforms"]["xiaohongshu"]["description"]
    assert "按实话给你讲" in packaging["platforms"]["kuaishou"]["description"]


def test_build_fallback_description_uses_creator_cta_and_primary_platform():
    packaging = normalize_platform_packaging(
        {"highlights": {}, "platforms": {"wechat_channels": {"titles": [], "description": "", "tags": []}}},
        content_profile={"subject_brand": "Loop露普", "subject_model": "SK05二代Pro UV版", "subject_type": "手电"},
        author_profile={
            "display_name": "赛博迪克朗",
            "creator_profile": {
                "identity": {"public_name": "赛博迪克朗", "title": "EDC评测作者"},
                "positioning": {"creator_focus": "手电开箱、EDC装备"},
                "publishing": {
                    "primary_platform": "视频号",
                    "default_call_to_action": "评论区告诉我你更想看哪类实测？",
                    "description_strategy": "视频号优先强调可信度和结论。",
                },
            },
        },
    )

    assert "主内容阵地在视频号" in packaging["platforms"]["wechat_channels"]["description"]
    assert packaging["platforms"]["wechat_channels"]["description"].endswith("评论区告诉我你更想看哪类实测？")
