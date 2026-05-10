from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment
from roughcut.review.content_profile import (
    _fallback_polish_text,
    _is_safe_subtitle_polish,
    apply_glossary_terms,
)
from roughcut.review.glossary_engine import assess_glossary_correction_automation
from roughcut.speech.subtitle_pipeline import _apply_accepted_corrections
from roughcut.speech.subtitle_segmentation import normalize_display_numbers, normalize_display_text
from roughcut.speech.transcribe import _normalize_transcript_result


def test_display_number_transcription_does_not_rewrite_non_numeric_facts() -> None:
    assert normalize_display_text("我懒得看了") == "我懒得看了"
    assert normalize_display_numbers("我在我的理解是一个EDC小零食") == "我在我的理解是一个EDC小零食"
    assert normalize_display_numbers("我在我的理解是1个EDC小零食") == "我在我的理解是一个EDC小零食"


def test_subtitle_polish_rejects_deletions_digitized_quantifiers_and_neighbor_models() -> None:
    glossary_terms = [{"correct_form": "EDC37", "wrong_forms": ["EDC17"]}]

    assert not _is_safe_subtitle_polish(
        original_text="我懒得看了",
        polished_text="懒得看了",
        prev_text="",
        next_text="",
        glossary_terms=[],
        review_memory=None,
        content_profile={},
    )
    assert not _is_safe_subtitle_polish(
        original_text="这个EDC17手电有UV和白光模式",
        polished_text="这个EDC37手电有UV和白光模式",
        prev_text="",
        next_text="",
        glossary_terms=glossary_terms,
        review_memory=None,
        content_profile={"subject_model": "EDC17"},
    )


def test_subtitle_polish_allows_explicit_non_conflicting_term_fix() -> None:
    glossary_terms = [{"correct_form": "NITECORE", "wrong_forms": ["耐特科尔"]}]

    assert _is_safe_subtitle_polish(
        original_text="这个耐特科尔EDC17手电",
        polished_text="这个NITECORE EDC17手电",
        prev_text="",
        next_text="",
        glossary_terms=glossary_terms,
        review_memory=None,
        content_profile={},
    )


def test_fallback_polish_keeps_base_fact_when_glossary_suggests_neighbor_model() -> None:
    glossary_terms = [{"correct_form": "EDC37", "wrong_forms": ["EDC17"]}]

    assert (
        _fallback_polish_text(
            "这个EDC17手电有UV和白光模式",
            glossary_terms=glossary_terms,
            review_memory=None,
            preserve_display_numbers=True,
        )
        == "这个EDC17手电有UV和白光模式"
    )
    assert apply_glossary_terms("这个EDC17手电", glossary_terms) == "这个EDC17手电"


def test_fallback_polish_does_not_expand_model_alias_with_comparison_model() -> None:
    review_memory = {
        "aliases": [
            {"wrong": "EDC17", "correct": "EDC17 / EDC37", "evidence_strong": True},
        ]
    }

    assert (
        _fallback_polish_text(
            "也是前两个月出的这个EDC17",
            glossary_terms=[],
            review_memory=review_memory,
            preserve_display_numbers=True,
        )
        == "也是前两个月出的这个EDC17"
    )


def test_accepted_corrections_do_not_rewrite_conflicting_model_numbers() -> None:
    corrections = (
        {
            "original": "EDC17",
            "accepted": "EDC37",
            "status": "accepted",
            "source": "glossary_match",
            "change_type": "glossary",
            "confidence": 0.99,
        },
    )

    assert _apply_accepted_corrections("这个EDC17手电", corrections) == "这个EDC17手电"


def test_glossary_automation_blocks_neighbor_model_rewrite() -> None:
    automation = assess_glossary_correction_automation(
        full_text="这个EDC17手电",
        original_span="EDC17",
        suggested_span="EDC37",
        match_start=2,
        match_end=7,
        confidence=0.95,
    )

    assert automation["auto_apply"] is False
    assert "型号数字冲突，不能自动改写相邻型号" in automation["blocking_reasons"]


def test_transcript_cleanup_keeps_normal_spoken_sentence() -> None:
    result = TranscriptResult(
        segments=[
            TranscriptSegment(
                index=0,
                start=0.0,
                end=2.0,
                text="我懒得看了",
            )
        ],
        language="zh-CN",
        duration=2.0,
        raw_payload={},
    )

    normalized = _normalize_transcript_result(result, glossary_terms=[], review_memory={})

    assert normalized.segments[0].text == "我懒得看了"
