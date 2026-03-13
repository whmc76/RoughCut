from __future__ import annotations

from types import SimpleNamespace

from roughcut.edit.presets import get_workflow_preset
import pytest

from roughcut.review.content_profile import (
    _build_search_queries,
    _fallback_profile,
    _seed_profile_from_subtitles,
    _seed_profile_from_user_memory,
    assess_content_profile_automation,
    apply_content_profile_feedback,
    build_transcript_excerpt,
    build_cover_title,
    enrich_content_profile,
    polish_subtitle_items,
)


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


def test_build_cover_title_drops_edc_prefix_from_subject_type():
    preset = get_workflow_preset("edc_tactical")
    title = build_cover_title(
        {
            "subject_brand": "REATE",
            "subject_model": "",
            "subject_type": "EDC折刀",
            "video_theme": "折刀雕刻开箱",
            "hook_line": "REATE 这把雕刻折刀终于来了",
        },
        preset,
    )

    assert title["top"] == "REATE"
    assert title["main"] == "REATE折刀"


def test_build_cover_title_prefers_specific_ai_feature_anchor():
    preset = get_workflow_preset("screen_tutorial")
    title = build_cover_title(
        {
            "subject_brand": "RunningHub",
            "subject_model": "无限画布",
            "subject_type": "AI工作流创作平台",
            "video_theme": "RunningHub 无限画布新功能上线与实操演示",
            "hook_line": "RunningHub 刚上线无限画布，漫剧工作流终于顺了",
        },
        preset,
    )

    assert title["top"] == "RUNNINGHUB"
    assert title["main"] == "无限画布"
    assert title["bottom"] == "这功能强得离谱"


def test_build_cover_title_upgrades_software_hook_to_more_explosive_copy():
    preset = get_workflow_preset("screen_tutorial")
    title = build_cover_title(
        {
            "subject_brand": "RunningHub",
            "subject_model": "工作流",
            "subject_type": "AI工作流创作平台",
            "video_theme": "RunningHub 工作流搭建与节点编排教程",
            "hook_line": "RunningHub 工作流教程",
        },
        preset,
    )

    assert title["bottom"] == "核心流程直接起飞"


def test_build_cover_title_respects_global_copy_style():
    preset = get_workflow_preset("screen_tutorial")
    title = build_cover_title(
        {
            "subject_brand": "RunningHub",
            "subject_model": "无限画布",
            "subject_type": "AI工作流创作平台",
            "video_theme": "RunningHub 无限画布新功能上线与实操演示",
            "copy_style": "trusted_expert",
        },
        preset,
    )

    assert title["bottom"] == "无限画布关键差异讲明白"


def test_fallback_profile_does_not_use_timestamp_as_model():
    profile = _fallback_profile(
        source_name="20260130-140529.mp4",
        channel_profile=None,
        transcript_excerpt="",
    )

    assert profile["subject_model"] == ""
    assert "20260130-140529" not in profile["summary"]


def test_build_search_queries_ignores_timestamp_filename():
    queries = _build_search_queries(
        {
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "开箱产品",
            "search_queries": [],
        },
        "20260130-140529.mp4",
    )

    assert "20260130-140529" not in queries


def test_build_search_queries_uses_transcript_signal_terms_for_proactive_search():
    queries = _build_search_queries(
        {
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "多功能工具钳",
            "search_queries": [],
        },
        "20260130-140529.mp4",
        transcript_excerpt="[220.0-222.0] ARC 这把工具真的很顺手",
    )

    assert "ARC 开箱" in queries
    assert "ARC 多功能工具钳" in queries


def test_build_search_queries_prefers_ai_feature_anchor_for_software_topics():
    queries = _build_search_queries(
        {
            "subject_brand": "RunningHub",
            "subject_model": "无限画布",
            "subject_type": "AI工作流创作平台",
            "search_queries": [],
        },
        "RH无限画布 快速漫剧.mp4",
        transcript_excerpt="[12.0-18.0] 今天 RunningHub 上线了无限画布功能，拿来做漫剧工作流。",
    )

    assert "RunningHub 无限画布" in queries
    assert "RunningHub 无限画布 教程" in queries
    assert "RunningHub 无限画布 漫剧" in queries


def test_build_transcript_excerpt_pulls_high_signal_items_from_later_segments():
    subtitle_items = [
        {"start_time": 0.0, "end_time": 1.0, "text_raw": "开场闲聊"},
        {"start_time": 2.0, "end_time": 3.0, "text_raw": "继续随便说两句"},
        {"start_time": 220.0, "end_time": 222.0, "text_raw": "ARC 这把工具真的很顺手"},
    ]

    excerpt = build_transcript_excerpt(subtitle_items, max_items=3, max_chars=200)

    assert "ARC" in excerpt


def test_seed_profile_from_subtitles_handles_edc_asr_aliases():
    profile = _seed_profile_from_subtitles(
        [
            {"text_raw": "来自慢的这个定位上来说是他家最高端的产品"},
            {"text_raw": "ARC 这把工具的单手开合很舒服"},
        ]
    )

    assert profile["subject_brand"] == "LEATHERMAN"
    assert profile["subject_model"] == "ARC"
    assert profile["subject_type"] == "多功能工具钳"


def test_seed_profile_from_subtitles_detects_reate_folding_knife_signals():
    profile = _seed_profile_from_subtitles(
        [
            {"text_raw": "这把锐特折刀的梯片手感不错"},
            {"text_raw": "柄身细节和锁片结构这次都做了调整"},
        ]
    )

    assert profile["subject_brand"] == "REATE"
    assert profile["subject_type"] == "EDC折刀"


def test_seed_profile_from_subtitles_detects_runninghub_infinite_canvas_theme():
    profile = _seed_profile_from_subtitles(
        [
            {"text_raw": "今天 RunningHub 上线了一个全新的功能叫无限画布"},
            {"text_raw": "这个功能很适合拿来搭漫剧工作流和节点编排"},
        ]
    )

    assert profile["subject_brand"] == "RunningHub"
    assert profile["subject_model"] == "无限画布"
    assert profile["subject_type"] == "AI工作流创作平台"
    assert "无限画布" in profile["video_theme"]
    assert any("RunningHub 无限画布" in item for item in profile["search_queries"])


def test_seed_profile_from_subtitles_prefers_runninghub_from_rh_alias_over_later_model_names():
    profile = _seed_profile_from_subtitles(
        [
            {"text_raw": "今天那个 RH 上线了一个全新的功能，叫无限画布。"},
            {"text_raw": "后面这个工作流里也能接 Gemini 和 OpenAI。"},
        ]
    )

    assert profile["subject_brand"] == "RunningHub"
    assert profile["subject_model"] == "无限画布"


def test_seed_profile_from_user_memory_is_disabled_to_avoid_cross_episode_contamination():
    profile = _seed_profile_from_user_memory(
        "这次来聊 ARC 这把工具的单手开合和锁点机构",
        {
            "field_preferences": {
                "subject_brand": [{"value": "LEATHERMAN", "count": 3}],
                "subject_model": [{"value": "ARC", "count": 5}],
            },
            "keyword_preferences": [{"keyword": "LEATHERMAN ARC", "count": 4}],
        },
    )

    assert profile == {}


def test_assess_content_profile_automation_blocks_product_profile_without_identity():
    assessment = assess_content_profile_automation(
        {
            "preset_name": "unboxing_upgrade",
            "subject_type": "多功能工具钳",
            "video_theme": "升级结构与上手体验",
            "summary": "这条视频主要围绕多功能工具钳的升级结构和上手体验展开，重点看开合手感和锁定机构。",
            "engagement_question": "这次升级你最在意开合还是锁定机构？",
            "search_queries": ["工具钳 升级 开箱", "工具钳 锁定机构"],
            "cover_title": {"top": "工具钳", "main": "升级结构开箱", "bottom": "锁定机构细看"},
            "evidence": [{"title": "demo"}],
        },
        subtitle_items=[
            {"text_raw": "这次先看升级后的锁定机构"},
            {"text_raw": "后面再看实际开合手感"},
            {"text_raw": "整体结构变化比较明显"},
            {"text_raw": "握持和受力也有变化"},
            {"text_raw": "我会重点看耐用度"},
            {"text_raw": "最后聊聊值不值得升级"},
        ],
    )

    assert assessment["auto_confirm"] is False
    assert "开箱类视频未识别出可验证主体" in assessment["blocking_reasons"]


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
            "subject_brand": "REATE",
            "subject_model": "马年限定版",
            "subject_type": "EDC折刀",
            "hook_line": "REATE 这把雕刻折刀终于来了",
            "engagement_question": "这把 REATE 折刀你最想先看雕刻细节还是开合手感？",
            "summary": "这是用户确认后的摘要",
            "keywords": ["REATE 折刀", "马年限定版", "EDC折刀"],
        },
    )

    assert result["subject_brand"] == "REATE"
    assert result["subject_model"] == "马年限定版"
    assert result["subject_type"] == "EDC折刀"
    assert result["summary"] == "这是用户确认后的摘要"
    assert result["engagement_question"] == "这把 REATE 折刀你最想先看雕刻细节还是开合手感？"
    assert result["search_queries"]
    assert any("REATE" in item for item in result["search_queries"])
    assert any(token in result["cover_title"]["main"] for token in ("REATE", "马年限定版"))


@pytest.mark.asyncio
async def test_enrich_content_profile_uses_llm_to_replace_generic_engagement_question(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    class FakeResponse:
        def as_json(self):
            return {"engagement_question": "ARC这次升级你最在意单手开合还是钳头？"}

    class FakeProvider:
        async def complete(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", lambda: FakeProvider())

    result = await enrich_content_profile(
        profile={
            "subject_brand": "LEATHERMAN",
            "subject_model": "ARC",
            "subject_type": "多功能工具钳",
            "video_theme": "升级开箱与上手体验",
            "engagement_question": "你觉得这次到手值不值？",
        },
        source_name="arc.mp4",
        channel_profile=None,
        transcript_excerpt="这次重点看 ARC 的单手开合和钳头结构。",
        include_research=False,
    )

    assert result["engagement_question"] == "ARC这次升级你最在意单手开合还是钳头？"


@pytest.mark.asyncio
async def test_enrich_content_profile_falls_back_to_contextual_question_when_llm_unavailable(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    result = await enrich_content_profile(
        profile={
            "subject_brand": "LEATHERMAN",
            "subject_model": "ARC",
            "subject_type": "多功能工具钳",
            "video_theme": "升级开箱与上手体验",
            "engagement_question": "你觉得这次到手值不值？",
        },
        source_name="arc.mp4",
        channel_profile=None,
        transcript_excerpt="这次重点看 ARC 的单手开合和钳头结构。",
        include_research=False,
    )

    assert result["engagement_question"] == "LEATHERMANARC这次升级你最在意哪一项？"


@pytest.mark.asyncio
async def test_enrich_content_profile_clears_unverified_brand_model(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    result = await enrich_content_profile(
        profile={
            "subject_brand": "LEATHERMAN 莱泽曼",
            "subject_model": "ARC",
            "subject_type": "工具钳",
            "video_theme": "开箱评测",
            "visible_text": "LEATHERMAN ARC",
            "summary": "这次莱泽曼 ARC 的开箱主要看整体结构。",
            "engagement_question": "这把莱泽曼 ARC 值不值入手？",
            "search_queries": ["LEATHERMAN ARC", "LEATHERMAN ARC 开箱"],
            "cover_title": {
                "top": "莱泽曼ARC",
                "main": "旗舰工具钳开箱",
                "bottom": "360°彩合金结构+双咔哒开合",
            },
        },
        source_name="20260211-120947.mp4",
        channel_profile=None,
        transcript_excerpt="这次先看彩钛结构和组装细节，后面再看开合手感。",
        include_research=False,
    )

    assert result["subject_brand"] == ""
    assert result["subject_model"] == ""
    assert result["visible_text"] == ""
    assert not result["search_queries"]
    assert "ARC" not in result["cover_title"]["top"]
    assert "莱泽曼" not in result["summary"]
    assert "ARC" not in result["engagement_question"]


@pytest.mark.asyncio
async def test_enrich_content_profile_preserves_confirmed_user_feedback(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    result = await enrich_content_profile(
        profile={
            "subject_brand": "LEATHERMAN",
            "subject_model": "ARC",
            "subject_type": "工具钳",
            "video_theme": "开箱评测",
            "visible_text": "LEATHERMAN ARC",
            "summary": "这期是 REATE 折刀雕刻开箱，不是工具钳节目。",
            "engagement_question": "这把 REATE 折刀你最想先看雕刻细节还是开合手感？",
            "user_feedback": {
                "subject_brand": "REATE",
                "subject_type": "EDC折刀",
                "video_theme": "折刀雕刻开箱",
                "summary": "这期是 REATE 折刀雕刻开箱，不是工具钳节目。",
                "engagement_question": "这把 REATE 折刀你最想先看雕刻细节还是开合手感？",
                "hook_line": "REATE 这把雕刻折刀终于来了",
                "keywords": ["REATE 折刀", "折刀雕刻开箱"],
            },
        },
        source_name="20260211-120947.mp4",
        channel_profile=None,
        transcript_excerpt="这次先看柄身雕刻和组装细节，后面再看开合手感。",
        include_research=False,
    )

    assert result["subject_brand"] == "REATE"
    assert result["subject_type"] == "EDC折刀"
    assert result["video_theme"] == "折刀雕刻开箱"
    assert result["summary"] == "这期是 REATE 折刀雕刻开箱，不是工具钳节目。"
    assert result["engagement_question"] == "这把 REATE 折刀你最想先看雕刻细节还是开合手感？"
    assert any("REATE" in item for item in result["search_queries"])
    assert result["cover_title"]["top"] == "REATE"


@pytest.mark.asyncio
async def test_polish_subtitle_items_fallback_uses_review_memory(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    def raising_provider():
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", raising_provider)

    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=2.0,
        text_raw="来自慢这把多功能工具前的主到和单手开和都不错",
        text_norm="来自慢这把多功能工具前的主到和单手开和都不错",
        text_final=None,
    )

    polished = await polish_subtitle_items(
        [item],
        content_profile={"preset_name": "edc_tactical"},
        glossary_terms=[],
        review_memory={
            "terms": [
                {"term": "LEATHERMAN"},
                {"term": "多功能工具钳"},
                {"term": "主刀"},
                {"term": "单手开合"},
            ],
            "aliases": [{"wrong": "来自慢", "correct": "LEATHERMAN"}],
            "style_examples": [],
        },
    )

    assert polished == 1
    assert "LEATHERMAN" in item.text_final
    assert "多功能工具钳" in item.text_final
    assert "主刀" in item.text_final
    assert "单手开合" in item.text_final
    assert "来自慢" not in item.text_final
    assert "主到" not in item.text_final


@pytest.mark.asyncio
async def test_polish_subtitle_items_rejects_cross_episode_rewrite(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_profile as content_profile_module

    class FakeResponse:
        def as_json(self):
            return {
                "items": [
                    {"index": 0, "text_final": "LEATHERMAN ARC深雕版，360度无死角钛合金雕刻"}
                ]
            }

    class FakeProvider:
        async def complete(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(content_profile_module, "get_reasoning_provider", lambda: FakeProvider())

    item = SimpleNamespace(
        item_index=0,
        start_time=0.0,
        end_time=2.0,
        text_raw="这把 Reate 折刀先看手柄雕刻细节",
        text_norm="这把 Reate 折刀先看手柄雕刻细节",
        text_final=None,
    )

    polished = await polish_subtitle_items(
        [item],
        content_profile={
            "preset_name": "edc_tactical",
            "subject_brand": "REATE",
            "subject_model": "",
            "subject_type": "EDC折刀",
        },
        glossary_terms=[],
        review_memory={
            "terms": [{"term": "REATE"}],
            "aliases": [],
            "style_examples": [],
        },
    )

    assert polished == 1
    assert item.text_final == "这把 REATE 折刀先看手柄雕刻细节"
    assert "LEATHERMAN" not in item.text_final
    assert "ARC" not in item.text_final
