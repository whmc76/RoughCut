from roughcut.review.content_profile_artifacts import build_content_profile_artifact_payloads


def test_content_profile_artifact_payloads_include_video_understanding() -> None:
    payloads = build_content_profile_artifact_payloads(
        draft_profile={
            "summary": "这期围绕 NITECORE EDC17 展开。",
            "video_understanding": {
                "schema_version": "video_understanding_v1",
                "global_understanding": {"video_theme": "NITECORE EDC17 开箱"},
            },
        },
        final_profile=None,
        downstream_profile={"summary": "downstream"},
        subtitle_quality_report={"score": 96.0},
    )

    assert payloads.video_understanding == {
        "schema_version": "video_understanding_v1",
        "global_understanding": {"video_theme": "NITECORE EDC17 开箱"},
    }
