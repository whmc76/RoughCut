from __future__ import annotations

from types import SimpleNamespace

from roughcut.edit.presets import get_workflow_preset
import pytest

from roughcut.review.content_profile import (
    _build_search_queries,
    _fallback_profile,
    _seed_profile_from_subtitles,
    _seed_profile_from_user_memory,
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


def test_seed_profile_from_user_memory_matches_transcript_and_keywords():
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

    assert profile["subject_brand"] == "LEATHERMAN"
    assert profile["subject_model"] == "ARC"
    assert "LEATHERMAN ARC" in profile["search_queries"]


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
