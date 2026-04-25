from roughcut.review.subtitle_term_resolution import _should_ignore_patch_candidate


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
