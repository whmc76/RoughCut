from __future__ import annotations

from types import SimpleNamespace

from roughcut.review.subtitle_consistency import build_subtitle_consistency_report
from roughcut.review.subtitle_term_resolution import build_subtitle_term_resolution_patch


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


def test_build_subtitle_term_resolution_patch_filters_brand_alias_noise():
    patch = build_subtitle_term_resolution_patch(
        corrections=[
            SimpleNamespace(
                subtitle_item_id="1",
                original_span="狐蝠",
                suggested_span="狐蝠工业",
                change_type="glossary",
                confidence=0.98,
                source="glossary_match",
                auto_applied=False,
                human_decision="pending",
            ),
            SimpleNamespace(
                subtitle_item_id="2",
                original_span="PSIGEAR",
                suggested_span="狐蝠工业",
                change_type="glossary",
                confidence=0.98,
                source="glossary_match",
                auto_applied=False,
                human_decision="pending",
            ),
        ],
        source_name="20260301-171940 狐蝠工业foxbat 阵风 机能双肩包使用体验.mp4",
        content_profile={"subject_brand": "狐蝠工业", "subject_model": "阵风", "subject_type": "EDC机能包"},
    )

    assert patch["metrics"]["patch_count"] == 0
    assert patch["metrics"]["pending_count"] == 0
    assert patch["blocking"] is False


def test_build_subtitle_consistency_report_filters_brand_alias_noise_candidates():
    report = build_subtitle_consistency_report(
        subtitle_items=[{"text_final": "PSIGEAR 的水壶套还不错。"}],
        corrections=[
            SimpleNamespace(
                original_span="狐蝠工业",
                suggested_span="FOXBAT狐蝠工业",
                auto_applied=False,
                human_decision="pending",
                confidence=0.98,
            ),
            SimpleNamespace(
                original_span="PSIGEAR",
                suggested_span="狐蝠工业",
                auto_applied=False,
                human_decision="pending",
                confidence=0.98,
            ),
        ],
        source_name="20260301-171940 狐蝠工业foxbat 阵风 机能双肩包使用体验.mp4",
        content_profile={"subject_brand": "狐蝠工业", "subject_model": "阵风", "subject_type": "EDC机能包"},
    )

    assert report["metrics"]["pending_patch_count"] == 0
    assert report["blocking"] is False
    assert not any(item["kind"] == "term_patch" for item in report["conflicts"]["subtitle_vs_filename"])
