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
