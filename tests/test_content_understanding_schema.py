from roughcut.review.content_understanding_schema import (
    ContentUnderstanding,
    SubjectEntity,
    map_content_understanding_to_legacy_profile,
)


def test_map_content_understanding_to_legacy_profile_keeps_non_product_subjects_sparse():
    understanding = ContentUnderstanding(
        video_type="tutorial",
        content_domain="ai",
        primary_subject="ComfyUI 工作流",
        subject_entities=[
            SubjectEntity(kind="software", name="ComfyUI", brand="", model="工作流")
        ],
        video_theme="ComfyUI 节点编排与工作流实操",
        summary="这条视频主要演示 ComfyUI 工作流搭建和节点编排。",
        hook_line="工作流直接讲透",
        engagement_question="你更想看哪类节点工作流？",
        search_queries=["ComfyUI workflow", "ComfyUI 节点编排"],
        evidence_spans=[],
        uncertainties=[],
        confidence={"overall": 0.82},
        needs_review=False,
        review_reasons=[],
    )

    legacy = map_content_understanding_to_legacy_profile(understanding)

    assert legacy["content_kind"] == "tutorial"
    assert legacy["subject_domain"] == "ai"
    assert legacy["subject_type"] == "ComfyUI 工作流"
    assert legacy["subject_brand"] == ""
    assert legacy["subject_model"] == ""


def test_map_content_understanding_to_legacy_profile_drops_unknown_placeholder_fields():
    understanding = ContentUnderstanding(
        video_type="unknown",
        content_domain="unknown",
        primary_subject="unknown",
        subject_entities=[],
        video_theme="待确认",
        summary="这条视频当前主题待进一步确认，建议结合字幕、画面文字和人工核对后再继续包装。",
        hook_line="内容待人工确认",
        engagement_question="这条视频主要在讲什么？",
        search_queries=[],
        evidence_spans=[],
        uncertainties=["证据不足"],
        confidence={},
        needs_review=True,
        review_reasons=["证据不足"],
    )

    legacy = map_content_understanding_to_legacy_profile(understanding)

    assert legacy["content_kind"] == ""
    assert legacy["subject_domain"] == ""
    assert legacy["subject_type"] == ""
    assert legacy["video_theme"] == ""
