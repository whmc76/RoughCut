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
