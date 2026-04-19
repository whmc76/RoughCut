from __future__ import annotations

from roughcut.review.subtitle_consistency import build_subtitle_consistency_report


def test_build_subtitle_consistency_report_flags_flashlight_model_knife_drift():
    report = build_subtitle_consistency_report(
        subtitle_items=[
            {"text_final": "刀幺七啊。"},
            {"text_final": "EDC17折刀帕。"},
            {"text_final": "刀三七是之前我。"},
        ],
        source_name="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
        content_profile={"subject_brand": "NITECORE", "subject_model": "EDC17", "subject_type": "EDC手电"},
    )

    conflicts = report["conflicts"]["subtitle_vs_filename"]
    summary_conflicts = report["conflicts"]["subtitle_vs_summary"]

    assert report["blocking"] is True
    assert any("手电型号误写成折刀语义" in item["detail"] for item in conflicts)
    assert any("只允许人工复核" in item["detail"] for item in summary_conflicts)
    assert report["metrics"]["semantic_bad_term_total"] == 3
