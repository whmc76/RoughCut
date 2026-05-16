from roughcut.review.subtitle_term_resolution import _should_ignore_patch_candidate, build_subtitle_term_resolution_patch


def test_ignore_flashlight_reflection_patch_in_knife_context() -> None:
    assert _should_ignore_patch_candidate(
        original_span="反光",
        suggested_span="泛光",
        content_profile={"subject_domain": "knife", "subject_type": "EDC折刀"},
    )


def test_allow_flashlight_reflection_patch_in_flashlight_context() -> None:
    assert not _should_ignore_patch_candidate(
        original_span="反光",
        suggested_span="泛光",
        content_profile={"subject_domain": "flashlight", "subject_type": "手电"},
    )


def test_ignore_cross_subject_brand_patch_when_profile_keeps_original_brand() -> None:
    assert _should_ignore_patch_candidate(
        original_span="狐蝠工业",
        suggested_span="HSJUN x BOLTBOAT",
        content_profile={
            "subject_brand": "狐蝠工业",
            "video_theme": "狐蝠工业阵风双肩包使用体验",
            "summary": "这条视频围绕狐蝠工业阵风展开。",
        },
    )


def test_ignore_model_patch_when_numbers_conflict() -> None:
    assert _should_ignore_patch_candidate(
        original_span="EDC17",
        suggested_span="EDC37",
        content_profile={"subject_domain": "flashlight", "subject_model": "EDC17"},
    )


def test_unconfirmed_topic_fact_downgrades_auto_applied_term_patch() -> None:
    patch = build_subtitle_term_resolution_patch(
        corrections=[
            {
                "subtitle_item_id": "s1",
                "original_span": "EDC幺七",
                "suggested_span": "EDC17",
                "change_type": "term",
                "confidence": 0.97,
                "source": "glossary",
                "auto_applied": True,
            }
        ],
        source_name="demo.mp4",
        content_profile={
            "subject_model": "EDC17",
            "topic_fact_confirmation": {
                "status": "needs_review",
                "review_reasons": ["品牌/型号缺少深度调研或内部实体库交叉印证"],
            },
        },
    )

    assert patch["automatic_rewrites_allowed"] is False
    assert patch["metrics"]["auto_applied_count"] == 0
    assert patch["metrics"]["pending_count"] == 1
    assert patch["patches"][0]["auto_applied"] is False
    assert patch["patches"][0]["auto_apply_downgraded"] is True
