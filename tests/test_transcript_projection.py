from __future__ import annotations

from types import SimpleNamespace

from roughcut.speech.transcript_projection import (
    ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
    ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,
    ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER,
    build_canonical_transcript_layer,
    build_subtitle_projection_layer,
    build_transcript_fact_layer,
)


def test_transcript_projection_module_builds_fact_and_projection_layers():
    fact_layer = build_transcript_fact_layer(
        [
            SimpleNamespace(
                segment_index=3,
                start_time=0.0,
                end_time=1.0,
                text="hello",
                speaker="narrator",
                words_json=[{"word": "hello", "start": 0.0, "end": 1.0}],
            )
        ]
    ).as_dict()

    projection_layer = build_subtitle_projection_layer(
        [
            SimpleNamespace(
                item_index=2,
                start_time=0.0,
                end_time=1.0,
                text_raw="hello",
                text_norm="hello",
                text_final="hello",
            )
        ],
        segmentation_analysis={"entry_count": 1},
        split_profile={"orientation": "landscape"},
        boundary_refine={"attempted_windows": 0},
        quality_report={"score": 1.0},
    ).as_dict()

    canonical_layer = build_canonical_transcript_layer(
        [
            SimpleNamespace(
                id="item-1",
                item_index=2,
                start_time=0.0,
                end_time=1.0,
                text_raw="olight",
                text_norm="olight",
                text_final="olight",
            )
        ],
        corrections=[
            {
                "subtitle_item_id": "item-1",
                "original_span": "olight",
                "suggested_span": "OLIGHT",
                "auto_applied": True,
                "human_decision": "accepted",
            }
        ],
    ).as_dict()

    assert ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER == "transcript_fact_layer"
    assert ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER == "canonical_transcript_layer"
    assert ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER == "subtitle_projection_layer"
    assert fact_layer["segment_count"] == 1
    assert canonical_layer["segments"][0]["text"] == "OLIGHT"
    assert canonical_layer["word_segment_count"] == 1
    assert canonical_layer["segments"][0]["words"]
    assert canonical_layer["segments"][0]["words"][0]["alignment"]["source"] == "canonical_realign"
    assert projection_layer["entry_count"] == 1
    assert projection_layer["projection_kind"] == "display_baseline"
    assert projection_layer["transcript_layer"] == "subtitle_projection"
