from __future__ import annotations

from types import SimpleNamespace

from roughcut.speech.subtitle_pipeline import (
    ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
    build_canonical_transcript_layer,
    build_canonical_transcript_layer_from_transcript_segments,
    build_subtitle_projection_layer,
    build_subtitle_projection_layer_from_transcript_segments,
    build_transcript_fact_layer,
)


def test_build_transcript_fact_layer_preserves_segment_and_word_evidence():
    rows = [
        SimpleNamespace(
            segment_index=1,
            start_time=0.5,
            end_time=1.5,
            text="需要提神",
            speaker=None,
            words_json=[
                {"word": "需要", "start": 0.5, "end": 0.9, "confidence": 0.8},
                {"word": "提神", "start": 0.9, "end": 1.5, "confidence": 0.9},
            ],
        )
    ]

    layer = build_transcript_fact_layer(rows).as_dict()

    assert layer["layer"] == "transcript_fact"
    assert layer["segment_count"] == 1
    assert layer["word_segment_count"] == 1
    assert layer["segments"][0]["text"] == "需要提神"
    assert layer["segments"][0]["words"][1]["word"] == "提神"
    assert layer["segments"][0]["words"][1]["raw_payload"]["confidence"] == 0.9


def test_build_subtitle_projection_layer_uses_time_sorted_projection_entries():
    items = [
        SimpleNamespace(
            item_index=2,
            start_time=1.5,
            end_time=2.0,
            text_raw="第二条",
            text_norm="第二条",
            text_final="第二条",
        ),
        SimpleNamespace(
            item_index=1,
            start_time=0.0,
            end_time=1.2,
            text_raw="第一条",
            text_norm="第一条",
            text_final="第一条",
        ),
    ]

    layer = build_subtitle_projection_layer(
        items,
        segmentation_analysis={"entry_count": 2},
        split_profile={"orientation": "landscape"},
        boundary_refine={"attempted_windows": 0, "accepted_windows": 0},
        quality_report={"score": 0.91, "blocking": False},
    ).as_dict()

    assert layer["layer"] == "subtitle_projection"
    assert layer["entry_count"] == 2
    assert layer["projection_kind"] == "display_baseline"
    assert layer["transcript_layer"] == "subtitle_projection"
    assert layer["entries"][0]["text_raw"] == "第一条"
    assert layer["entries"][1]["text_raw"] == "第二条"
    assert layer["entries"][0]["source_kind"] == "subtitle_item"
    assert layer["split_profile"]["orientation"] == "landscape"
    assert layer["quality_report"]["score"] == 0.91


def test_build_canonical_transcript_layer_applies_accepted_corrections():
    items = [
        SimpleNamespace(
            id="item-2",
            item_index=2,
            start_time=1.5,
            end_time=2.0,
            text_raw="后面讲错了欧莱特",
            text_norm="后面讲错了欧莱特",
            text_final="后面讲错了欧莱特",
        ),
        SimpleNamespace(
            id="item-1",
            item_index=1,
            start_time=0.0,
            end_time=1.2,
            text_raw="先看欧莱特司令官二",
            text_norm="先看欧莱特司令官二",
            text_final="先看欧莱特司令官二",
        ),
    ]

    layer = build_canonical_transcript_layer(
        items,
        corrections=[
            {
                "subtitle_item_id": "item-1",
                "original_span": "欧莱特",
                "suggested_span": "傲雷",
                "auto_applied": True,
                "human_decision": "accepted",
                "source": "glossary_match",
                "change_type": "glossary",
                "confidence": 0.97,
            },
            {
                "subtitle_item_id": "item-1",
                "original_span": "司令官二",
                "suggested_span": "司令官2",
                "auto_applied": False,
                "human_decision": "pending",
                "source": "glossary_match",
                "change_type": "glossary",
                "confidence": 0.7,
            },
        ],
    ).as_dict()

    assert ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER == "canonical_transcript_layer"
    assert layer["layer"] == "canonical_transcript"
    assert layer["segment_count"] == 2
    assert layer["segments"][0]["text"] == "先看傲雷司令官二"
    assert layer["segments"][0]["accepted_corrections"][0]["accepted"] == "傲雷"
    assert layer["segments"][0]["pending_corrections"][0]["accepted"] == "司令官2"
    assert layer["word_segment_count"] == 2
    assert layer["word_count"] >= 2
    assert layer["segments"][0]["words"]
    assert layer["segments"][0]["words"][0]["alignment"]["source"] == "canonical_realign"
    assert layer["segments"][0]["source_kind"] == "subtitle_item"
    assert layer["correction_metrics"]["accepted_correction_count"] == 1
    assert layer["correction_metrics"]["pending_correction_count"] == 1


def test_build_canonical_transcript_layer_reuses_reference_word_timings_when_available():
    items = [
        SimpleNamespace(
            id="item-1",
            item_index=0,
            start_time=0.0,
            end_time=1.0,
            text_raw="OLIGHT baton",
            text_norm="OLIGHT baton",
            text_final="OLIGHT baton",
        )
    ]

    reference_segments = [
        SimpleNamespace(
            segment_index=0,
            start_time=0.0,
            end_time=1.0,
            text="olight baton",
            words_json=[
                {"word": "OLIGHT", "start": 0.05, "end": 0.45},
                {"word": "baton", "start": 0.5, "end": 0.9},
            ],
        )
    ]

    layer = build_canonical_transcript_layer(
        items,
        corrections=[],
        reference_segments=reference_segments,
    ).as_dict()

    words = layer["segments"][0]["words"]
    assert [word["word"] for word in words] == ["OLIGHT", "baton"]
    assert words[0]["start"] == 0.05
    assert words[0]["end"] == 0.45
    assert words[0]["alignment"]["strategy"] == "reference_word_match"
    assert words[1]["start"] == 0.5
    assert words[1]["end"] == 0.9


def test_build_canonical_transcript_layer_accepts_transcript_segments_directly():
    transcript_segments = [
        SimpleNamespace(
            id="segment-1",
            index=5,
            start=0.0,
            end=1.1,
            text="hello world",
            speaker="narrator",
            words=[
                SimpleNamespace(word="hello", start=0.0, end=0.45, raw_payload={"confidence": 0.93}),
                SimpleNamespace(word="world", start=0.45, end=1.1, raw_payload={"confidence": 0.91}),
            ],
        )
    ]

    layer = build_canonical_transcript_layer(transcript_segments).as_dict()

    assert layer["layer"] == "canonical_transcript"
    assert layer["source_basis"] == "transcript_first"
    assert layer["segment_count"] == 1
    assert layer["segments"][0]["source_kind"] == "transcript_segment"
    assert layer["segments"][0]["source_id"] == "segment-1"
    assert layer["segments"][0]["text"] == "hello world"
    assert layer["segments"][0]["words"][0]["start"] == 0.0
    assert layer["segments"][0]["words"][1]["end"] == 1.1


def test_build_transcript_first_apis_project_from_transcript_segments():
    transcript_segments = [
        SimpleNamespace(
            id="segment-2",
            index=3,
            start=1.0,
            end=2.0,
            text="transcript first",
            words=[
                SimpleNamespace(word="transcript", start=1.0, end=1.5, raw_payload={"confidence": 0.88}),
                SimpleNamespace(word="first", start=1.5, end=2.0, raw_payload={"confidence": 0.86}),
            ],
        )
    ]

    projection_layer = build_subtitle_projection_layer_from_transcript_segments(
        transcript_segments,
        segmentation_analysis={"entry_count": 1},
        split_profile={"orientation": "portrait"},
        boundary_refine={"attempted_windows": 0, "accepted_windows": 0},
        quality_report={"score": 0.99, "blocking": False},
    ).as_dict()

    canonical_layer = build_canonical_transcript_layer_from_transcript_segments(
        transcript_segments,
        source_basis="transcript_first",
    ).as_dict()

    assert projection_layer["projection_kind"] == "transcript_first"
    assert projection_layer["transcript_layer"] == "transcript_projection"
    assert projection_layer["entry_count"] == 1
    assert projection_layer["entries"][0]["source_kind"] == "transcript_segment"
    assert projection_layer["entries"][0]["source_id"] == "segment-2"
    assert canonical_layer["source_basis"] == "transcript_first"
    assert canonical_layer["segments"][0]["source_kind"] == "transcript_segment"
