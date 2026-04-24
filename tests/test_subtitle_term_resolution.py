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
