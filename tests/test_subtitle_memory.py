from __future__ import annotations

from roughcut.review.subtitle_memory import (
    apply_domain_term_corrections,
    build_subtitle_review_memory,
    build_transcription_prompt,
    summarize_subtitle_review_memory,
)


def test_build_subtitle_review_memory_collects_terms_and_examples():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[
            {
                "correct_form": "LEATHERMAN",
                "wrong_forms": ["来泽曼", "来自慢"],
                "category": "brand",
            }
        ],
        user_memory={
            "field_preferences": {
                "subject_model": [{"value": "ARC", "count": 4}],
            },
            "keyword_preferences": [{"keyword": "多功能工具钳 单手开合", "count": 3}],
        },
        recent_subtitles=[
            {
                "text_final": "ARC 这把多功能工具钳的单手开合很顺。",
                "source_name": "demo1.srt",
            },
            {
                "text_final": "我更在意钳头结构和主刀手感。",
                "source_name": "demo2.srt",
            },
        ],
        content_profile={"subject_type": "多功能工具钳"},
    )

    terms = [item["term"] for item in memory["terms"]]
    summary = summarize_subtitle_review_memory(memory)

    assert "LEATHERMAN" in terms
    assert "ARC" in terms
    assert "多功能工具钳" in terms
    assert any(item["wrong"] == "来泽曼" and item["correct"] == "LEATHERMAN" for item in memory["aliases"])
    assert "同类视频常见表达" in summary


def test_build_transcription_prompt_includes_terms_and_aliases():
    prompt = build_transcription_prompt(
        source_name="arc_review.mp4",
        channel_profile="edc_tactical",
        review_memory={
            "terms": [{"term": "LEATHERMAN"}, {"term": "ARC"}, {"term": "多功能工具钳"}],
            "aliases": [{"wrong": "来自慢", "correct": "LEATHERMAN"}],
            "style_examples": [],
        },
    )

    assert "edc_tactical" in prompt
    assert "LEATHERMAN" in prompt
    assert "多功能工具钳" in prompt
    assert "来自慢=LEATHERMAN" in prompt


def test_apply_domain_term_corrections_fixes_edc_aliases_and_near_matches():
    corrected = apply_domain_term_corrections(
        "来自慢这把多功能工具前的单手开和和主到都很顺",
        {
            "terms": [
                {"term": "LEATHERMAN"},
                {"term": "多功能工具钳"},
                {"term": "单手开合"},
                {"term": "主刀"},
            ],
            "aliases": [
                {"wrong": "来自慢", "correct": "LEATHERMAN"},
            ],
            "style_examples": [],
        },
    )

    assert "LEATHERMAN" in corrected
    assert "多功能工具钳" in corrected
    assert "单手开合" in corrected
    assert "主刀" in corrected


def test_apply_domain_term_corrections_fixes_generic_safe_asr_typos():
    corrected = apply_domain_term_corrections(
        "这个螺四非常执用，后面两个罗丝也很好拆",
        {
            "terms": [{"term": "螺丝"}],
            "aliases": [],
            "style_examples": [],
        },
    )

    assert corrected == "这个螺丝非常实用，后面两个螺丝也很好拆"


def test_apply_domain_term_corrections_fixes_edc_phrase_typos():
    corrected = apply_domain_term_corrections(
        "美中部组的地方就是这个电路处理，也不是一定要做得经质的华历，这个键变的效果也不错",
        {
            "terms": [{"term": "美中不足"}, {"term": "电镀"}, {"term": "极致华丽"}, {"term": "渐变"}],
            "aliases": [],
            "style_examples": [],
        },
    )

    assert "美中不足" in corrected
    assert "电镀" in corrected
    assert "极致华丽" in corrected
    assert "渐变" in corrected
    assert "华丽历" not in corrected


def test_build_subtitle_review_memory_injects_default_edc_glossary():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[],
        content_profile={"subject_type": "EDC折刀"},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "EDC" in terms
    assert "FAS" in terms
    assert "贴片" in terms
    assert any(item["correct"] == "极致华丽" for item in memory["aliases"])


def test_build_subtitle_review_memory_injects_ai_and_tech_glossary():
    memory = build_subtitle_review_memory(
        channel_profile="screen_tutorial",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "这个 AI 工作流里要先调提示词，再看 RAG 命中。"}],
        content_profile={"video_theme": "AI工作流搭建教程"},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "提示词" in terms
    assert "RAG" in terms
    assert "工作流" in terms


def test_build_subtitle_review_memory_injects_ai_creator_hotwords():
    memory = build_subtitle_review_memory(
        channel_profile="screen_tutorial",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "RunningHub 的无限画布拿来搭漫剧工作流，ComfyUI 和 OpenClaw 也能接进来。"}],
        content_profile={"video_theme": "RunningHub 无限画布漫剧工作流演示"},
    )

    terms = [item["term"] for item in memory["terms"]]
    alias_map = {(item["wrong"], item["correct"]) for item in memory["aliases"]}

    assert "RunningHub" in terms
    assert "ComfyUI" in terms
    assert "OpenClaw" in terms
    assert "无限画布" in terms
    assert ("running hub", "RunningHub") in alias_map
    assert ("RH", "RunningHub") in alias_map


def test_build_subtitle_review_memory_injects_food_glossary():
    memory = build_subtitle_review_memory(
        channel_profile="food_explore",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "这家店锅气很足，回甘也很干净。"}],
        content_profile={"video_theme": "探店试吃"},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "锅气" in terms
    assert "回甘" in terms
    assert "探店" in terms


def test_build_subtitle_review_memory_injects_finance_glossary():
    memory = build_subtitle_review_memory(
        channel_profile="market_watch",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "美联储如果继续降息，市场会继续看通胀和财报。"}],
        content_profile={"video_theme": "美股与宏观财经快评"},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "美联储" in terms
    assert "降息" in terms
    assert "通胀" in terms
    assert "财报" in terms


def test_build_subtitle_review_memory_injects_news_glossary():
    memory = build_subtitle_review_memory(
        channel_profile="news_briefing",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "外媒关注峰会后的局势变化，联合国也给出了新的表态。"}],
        content_profile={"video_theme": "国际新闻速览"},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "国际新闻" in terms
    assert "外媒" in terms
    assert "峰会" in terms
    assert "联合国" in terms


def test_build_subtitle_review_memory_injects_sports_glossary():
    memory = build_subtitle_review_memory(
        channel_profile="sports_highlight",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[{"text_final": "这场季后赛最后靠三分绝杀，篮板和助攻也都拉满了。"}],
        content_profile={"video_theme": "体育赛事复盘"},
    )

    terms = [item["term"] for item in memory["terms"]]

    assert "季后赛" in terms
    assert "三分" in terms
    assert "绝杀" in terms
    assert "助攻" in terms


def test_build_subtitle_review_memory_prioritizes_aliases_for_ranked_terms():
    memory = build_subtitle_review_memory(
        channel_profile="edc_tactical",
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[],
        content_profile={"subject_type": "EDC折刀"},
    )

    alias_map = {(item["wrong"], item["correct"]) for item in memory["aliases"]}

    assert ("法斯", "FAS") in alias_map
    assert any(correct == "极致华丽" for _, correct in alias_map)
