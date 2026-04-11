from __future__ import annotations

from roughcut.review.downstream_context import build_downstream_context, resolve_downstream_profile


def test_build_downstream_context_prefers_manual_review_over_base_profile():
    context = build_downstream_context(
        {
            "subject_brand": "耐克",
            "subject_model": "SK05",
            "subject_type": "手电筒",
            "video_theme": "旧主题",
            "summary": "旧摘要",
            "review_mode": "manual_confirmed",
            "resolved_review_user_feedback": {
                "subject_brand": "傲雷",
                "subject_model": "司令官2Ultra",
                "subject_type": "司令官2Ultra手电筒",
                "video_theme": "傲雷司令官2Ultra版本选购与参数对比",
                "correction_notes": "重点核对品牌和型号写法。",
                "supplemental_context": "这是 EDC 手电版本对比稿。",
                "creative_preferences": [
                    {"tag": "comparison_focus", "label": "突出差异对比"},
                    {"tag": "closeup_focus", "label": "突出近景特写"},
                ],
            },
            "evidence": [{"title": "Spec 1", "url": "https://example.com/spec1"}],
        }
    )

    resolved = context["resolved_profile"]

    assert resolved["subject_brand"] == "傲雷"
    assert resolved["subject_model"] == "司令官2Ultra"
    assert resolved["subject_type"] == "司令官2Ultra手电筒"
    assert resolved["video_theme"] == "傲雷司令官2Ultra版本选购与参数对比"
    assert resolved["correction_notes"] == "重点核对品牌和型号写法。"
    assert resolved["supplemental_context"] == "这是 EDC 手电版本对比稿。"
    assert resolved["creative_preferences"][0]["tag"] == "comparison_focus"
    assert context["field_sources"]["subject_brand"] == "manual_review"
    assert context["field_sources"]["video_theme"] == "manual_review"
    assert context["field_sources"]["correction_notes"] == "manual_review"
    assert context["field_sources"]["creative_preferences"] == "manual_review"
    assert context["manual_review_applied"] is True
    assert context["research_applied"] is True


def test_resolve_downstream_profile_returns_resolved_profile_from_context():
    profile = resolve_downstream_profile(
        {
            "resolved_profile": {
                "subject_brand": "傲雷",
                "subject_model": "司令官2Ultra",
            },
            "field_sources": {
                "subject_brand": "manual_review",
            },
            "manual_review_applied": True,
            "research_applied": False,
        }
    )

    assert profile["subject_brand"] == "傲雷"
    assert profile["subject_model"] == "司令官2Ultra"
    assert profile["manual_review_applied"] is True
    assert profile["research_applied"] is False
    assert profile["field_sources"]["subject_brand"] == "manual_review"


def test_resolve_downstream_profile_builds_context_from_plain_content_profile():
    profile = resolve_downstream_profile(
        {
            "subject_brand": "Loop露普",
            "subject_model": "SK05二代Pro UV版",
            "evidence": [{"title": "Spec 1"}],
        }
    )

    assert profile["subject_brand"] == "Loop露普"
    assert profile["subject_model"] == "SK05二代Pro UV版"
    assert profile["manual_review_applied"] is False
    assert profile["research_applied"] is True
    assert profile["field_sources"]["subject_brand"] == "base_profile"
