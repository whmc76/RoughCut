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
