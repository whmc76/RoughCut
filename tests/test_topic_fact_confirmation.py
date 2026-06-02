from roughcut.review.content_profile import assess_content_profile_automation
from roughcut.review.topic_fact_confirmation import build_topic_fact_confirmation_snapshot


def test_topic_fact_confirmation_uses_research_and_entity_evidence() -> None:
    snapshot = build_topic_fact_confirmation_snapshot(
        {
            "subject_domain": "flashlight",
            "subject_brand": "NITECORE",
            "subject_model": "EDC17",
            "subject_type": "NITECORE EDC17 手电",
            "video_theme": "NITECORE EDC17 与 EDC37 开箱对比",
            "summary": "这期围绕 NITECORE EDC17 与 EDC37 的外观和功能差异展开。",
            "transcript_excerpt": "今天看 NITECORE EDC17 和 EDC37。",
            "source_context": {"video_description": "手电新品对比"},
            "content_understanding": {
                "confidence": {"overall": 0.78},
                "search_queries": ["NITECORE EDC17 EDC37"],
                "needs_review": False,
            },
            "verification_evidence": {
                "search_queries": ["NITECORE EDC17 EDC37"],
                "online_count": 2,
                "entity_catalog_count": 1,
                "entity_catalog_candidates": [
                    {
                        "brand": "NITECORE",
                        "model": "EDC17",
                        "subject_type": "手电",
                        "evidence_strength": "strong",
                    }
                ],
            },
        }
    )

    assert snapshot["confirmed"] is True
    assert snapshot["status"] == "confirmed"
    assert "online_research" in snapshot["support_sources"]
    assert "internal_entity_catalog" in snapshot["support_sources"]
    assert snapshot["research_expansion"]["search_queries"] == ["NITECORE EDC17 EDC37"]


def test_topic_fact_confirmation_requires_review_without_cross_evidence() -> None:
    snapshot = build_topic_fact_confirmation_snapshot(
        {
            "subject_brand": "NOC",
            "subject_model": "MT332",
            "subject_type": "NOC MT332 折刀",
            "video_theme": "NOC MT332 细节展示",
            "content_understanding": {
                "confidence": {"overall": 0.66},
                "needs_review": False,
            },
        }
    )

    assert snapshot["confirmed"] is False
    assert "品牌/型号缺少深度调研或内部实体库交叉印证" in snapshot["review_reasons"]


def test_topic_fact_confirmation_reads_video_understanding_as_support_source() -> None:
    snapshot = build_topic_fact_confirmation_snapshot(
        {
            "video_understanding": {
                "global_understanding": {
                    "content_domain": "flashlight",
                    "primary_subject": {
                        "brand": "NITECORE",
                        "model": "EDC17",
                        "type": "NITECORE EDC17 手电",
                    },
                    "video_theme": "NITECORE EDC17 开箱对比",
                    "summary": "这期围绕 NITECORE EDC17 和 EDC37 的对比体验展开。",
                },
                "review": {"confidence": {"overall": 0.79}},
                "evidence": {"visual_semantic_evidence": {"subject_candidates": ["flashlight"]}},
            },
            "content_understanding": {
                "confidence": {"overall": 0.74},
                "needs_review": False,
            },
            "verification_evidence": {
                "online_count": 1,
                "entity_catalog_count": 1,
            },
        }
    )

    assert snapshot["subject"]["brand"] == "NITECORE"
    assert snapshot["subject"]["model"] == "EDC17"
    assert snapshot["subject"]["theme"] == "NITECORE EDC17 开箱对比"
    assert "video_understanding" in snapshot["support_sources"]


def test_content_profile_automation_surfaces_topic_fact_review_reasons() -> None:
    automation = assess_content_profile_automation(
        {
            "workflow_template": "edc_tactical",
            "subject_domain": "knife",
            "subject_brand": "NOC",
            "subject_model": "MT332",
            "subject_type": "NOC MT332 折刀",
            "video_theme": "NOC MT332 细节展示",
            "summary": "这条视频展示 NOC MT332 折刀细节。",
            "cover_title": {"top": "NOC", "main": "MT332细节", "bottom": "折刀外观"},
            "engagement_question": "你更关注这款折刀的哪个细节？",
            "search_queries": ["NOC MT332"],
            "content_understanding": {"confidence": {"overall": 0.66}, "needs_review": False},
        },
        subtitle_items=[{"text_final": "今天看一下这款折刀的细节。"} for _ in range(8)],
        source_name="NOC MT332.mp4",
        auto_confirm_enabled=True,
        threshold=0.92,
    )

    assert "品牌/型号缺少深度调研或内部实体库交叉印证" in automation["review_reasons"]
    assert automation["blocking_reasons"] == []
