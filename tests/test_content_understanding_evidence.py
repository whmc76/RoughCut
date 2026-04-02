from __future__ import annotations

from roughcut.review.content_understanding_evidence import build_evidence_bundle


def test_build_evidence_bundle_keeps_evidence_only_fields():
    bundle = build_evidence_bundle(
        source_name="IMG_1234.mp4",
        subtitle_items=[
            {
                "text_final": "今天看下这个包的分仓和挂点",
                "start_time": 0.0,
                "end_time": 2.0,
            }
        ],
        transcript_excerpt="[0.0-2.0] 今天看下这个包的分仓和挂点",
        visible_text="FXX1",
        ocr_profile={"visible_text": "FXX1"},
        visual_hints={"subject_type": "EDC机能包", "visible_text": "FXX1"},
    )

    assert bundle["transcript_excerpt"] == "[0.0-2.0] 今天看下这个包的分仓和挂点"
    assert bundle["visible_text"] == "FXX1"
    assert "subject_type" not in bundle
    assert bundle["candidate_hints"]["visual_hints"]["subject_type"] == "EDC机能包"


def test_build_evidence_bundle_collects_generic_semantic_fact_inputs():
    bundle = build_evidence_bundle(
        source_name="HSJUN_BOLTBOAT_review.mp4",
        subtitle_items=[
            {
                "text_final": "这是 hsjun 和 boltboat 联名的包",
                "start_time": 0.0,
                "end_time": 2.0,
            },
            {
                "text_final": "它叫游刃，今天主要看结构和背负",
                "start_time": 2.0,
                "end_time": 4.0,
            },
        ],
        transcript_excerpt="[0.0-2.0] 这是 hsjun 和 boltboat 联名的包 [2.0-4.0] 它叫游刃",
        visible_text="BOLTBOAT HSJUN",
        ocr_profile={"visible_text": "BOLTBOAT HSJUN"},
        visual_hints={"subject_brand": "HSJUN", "subject_model": "游刃"},
    )

    semantic_inputs = bundle["semantic_fact_inputs"]

    assert "HSJUN_BOLTBOAT_review.mp4" in semantic_inputs["source_name"]
    assert "这是 hsjun 和 boltboat 联名的包" in semantic_inputs["subtitle_lines"]
    assert "它叫游刃，今天主要看结构和背负" in semantic_inputs["subtitle_lines"]
    assert semantic_inputs["transcript_text"].startswith("[0.0-2.0]")
    assert semantic_inputs["visible_text"] == "BOLTBOAT HSJUN"
    assert "HSJUN" in semantic_inputs["hint_candidates"]
    assert "游刃" in semantic_inputs["hint_candidates"]
