from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment
from roughcut.review.content_profile import (
    _fallback_polish_text,
    _is_safe_subtitle_polish,
    apply_glossary_terms,
)
from roughcut.review.glossary_engine import assess_glossary_correction_automation
from roughcut.pipeline.steps import _build_reference_segment_adapters, _build_transcript_first_canonical_layer
from roughcut.speech.subtitle_pipeline import _apply_accepted_corrections, build_canonical_transcript_layer, build_transcript_fact_layer
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


def test_human_accepted_corrections_rewrite_canonical_text() -> None:
    corrections = (
        {
            "original": "耐特科尔",
            "accepted": "NITECORE",
            "status": "accepted",
            "human_decision": "accepted",
            "auto_applied": False,
            "source": "human_review",
            "change_type": "manual",
            "confidence": 1.0,
        },
    )

    assert _apply_accepted_corrections("这个耐特科尔EDC17手电", corrections) == "这个NITECOREEDC17手电"


def test_auto_applied_corrections_do_not_rewrite_canonical_text() -> None:
    corrections = (
        {
            "original": "奈特科尔",
            "accepted": "NITECORE",
            "status": "accepted",
            "auto_applied": True,
            "source": "glossary_match",
            "change_type": "glossary",
            "confidence": 0.99,
        },
    )

    assert _apply_accepted_corrections("这个奈特科尔也可以", corrections) == "这个奈特科尔也可以"


def test_human_accepted_correction_updates_canonical_segment_text() -> None:
    class Subtitle:
        id = "subtitle-1"
        item_index = 0
        start_time = 0.0
        end_time = 2.0
        text_raw = "这个耐特科尔EDC17手电"
        text_norm = "这个耐特科尔EDC17手电"
        text_final = None

    corrections = [
        {
            "subtitle_item_id": "subtitle-1",
            "original_span": "耐特科尔",
            "suggested_span": "NITECORE",
            "human_decision": "accepted",
            "auto_applied": False,
            "source": "human_review",
            "change_type": "manual",
            "confidence": 1.0,
        }
    ]

    layer = build_canonical_transcript_layer([Subtitle()], corrections=corrections)

    assert layer.segments[0].text_canonical == "这个NITECOREEDC17手电"
    assert layer.segments[0].accepted_corrections[0]["human_decision"] == "accepted"


def test_canonical_transcript_layer_preserves_source_raw_filler_text() -> None:
    class Subtitle:
        id = "subtitle-1"
        item_index = 0
        start_time = 0.0
        end_time = 2.0
        text_raw = "啊我靠饮恨"
        text_norm = "我靠饮恨"
        text_final = None

    layer = build_canonical_transcript_layer([Subtitle()], corrections=[])

    assert layer.segments[0].text_raw == "啊我靠饮恨"
    assert layer.segments[0].text_canonical == "我靠饮恨"


def test_canonical_transcript_layer_uses_canonical_surface_when_display_is_suppressed() -> None:
    class Subtitle:
        id = "subtitle-1"
        item_index = 0
        start_time = 0.0
        end_time = 2.0
        text_raw = "那个 EDC 折刀"
        text_norm = "这是 MAXACE 美杜莎4"
        text_final = ""
        display_suppressed_reason = "standalone_filler"

    layer = build_canonical_transcript_layer([Subtitle()], corrections=[])

    assert layer.segments[0].text_raw == "那个 EDC 折刀"
    assert layer.segments[0].text_canonical == "这是 MAXACE 美杜莎4"


def test_canonical_transcript_layer_preserves_explicit_canonical_surface_from_dict_transcript_segments() -> None:
    layer = build_canonical_transcript_layer(
        transcript_segments=[
            {
                "index": 0,
                "start": 0.0,
                "end": 1.0,
                "text": "generic text should not override canonical transcript",
                "text_raw": "你看到的是EC手电",
                "text_canonical": "你看到的是EDC手电",
            }
        ],
        corrections=[],
    )

    assert layer.source_basis == "transcript_first"
    assert layer.segments[0].text_raw == "generic text should not override canonical transcript"
    assert layer.segments[0].text_canonical == "你看到的是EDC手电"


def test_canonical_transcript_layer_preserves_explicit_surfaces_from_dict_subtitle_items() -> None:
    layer = build_canonical_transcript_layer(
        [
            {
                "id": "subtitle-1",
                "item_index": 0,
                "start_time": 0.0,
                "end_time": 2.0,
                "text_raw": "那个 EDC 折刀",
                "text_norm": "这是 MAXACE 美杜莎4",
                "text_final": "",
                "display_suppressed_reason": "standalone_filler",
            }
        ],
        corrections=[],
    )

    assert layer.segments[0].text_raw == "那个 EDC 折刀"
    assert layer.segments[0].text_canonical == "这是 MAXACE 美杜莎4"


def test_canonical_transcript_layer_sorts_dict_subtitle_items_by_timing() -> None:
    layer = build_canonical_transcript_layer(
        [
            {
                "id": "subtitle-2",
                "item_index": 2,
                "start_time": 3.0,
                "end_time": 4.0,
                "text_raw": "第二段",
                "text_norm": "第二段",
            },
            {
                "id": "subtitle-1",
                "item_index": 1,
                "start_time": 1.0,
                "end_time": 2.0,
                "text_raw": "第一段",
                "text_norm": "第一段",
            },
        ],
        corrections=[],
    )

    assert [segment.index for segment in layer.segments] == [1, 2]
    assert [segment.text_canonical for segment in layer.segments] == ["第一段", "第二段"]


def test_transcript_fact_layer_prefers_explicit_canonical_surface_from_dict_segments() -> None:
    layer = build_transcript_fact_layer(
        [
            {
                "index": 0,
                "start": 0.0,
                "end": 1.0,
                "text": "generic text should not override canonical transcript",
                "text_canonical": "你看到的是EDC手电",
            }
        ]
    )

    assert layer.segments[0].text == "你看到的是EDC手电"


def test_transcript_segment_adapters_preserve_explicit_raw_and_canonical_surfaces() -> None:
    adapters = _build_reference_segment_adapters(
        [
            {
                "segment_index": 0,
                "start_time": 0.0,
                "end_time": 1.0,
                "text": "generic text should not override explicit raw speech",
                "text_raw": "你看到的是EC手电",
                "text_canonical": "你看到的是EDC手电",
            }
        ]
    )

    layer = build_canonical_transcript_layer(
        transcript_segments=adapters,
        corrections=[],
        source_basis="subtitle_postprocess",
    )

    assert adapters[0].text == "你看到的是EC手电"
    assert layer.segments[0].text_raw == "你看到的是EC手电"
    assert layer.segments[0].text_canonical == "你看到的是EDC手电"


def test_transcript_first_canonical_layer_preserves_explicit_raw_and_canonical_surfaces() -> None:
    transcript_rows = [
        type(
            "TranscriptRow",
            (),
            {
                "segment_index": 0,
                "start_time": 0.0,
                "end_time": 1.0,
                "text": "generic text should not override explicit raw speech",
                "text_raw": "你看到的是EC手电",
                "text_canonical": "你看到的是EDC手电",
            },
        )()
    ]

    layer = _build_transcript_first_canonical_layer(
        transcript_rows=transcript_rows,
        subtitle_items=[],
        corrections=[],
    )

    assert layer.segments[0].text_raw == "你看到的是EC手电"
    assert layer.segments[0].text_canonical == "你看到的是EDC手电"


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
