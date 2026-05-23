from roughcut.api.avatar_materials import (
    _build_material_checks,
    _build_profile_runtime_state,
    _derive_runtime_preview_capability,
)
from roughcut.avatar.materials import build_creator_profile_dashboard, normalize_creator_profile
from roughcut.naming import (
    AVATAR_CAPABILITY_GENERATION,
    AVATAR_CAPABILITY_PREVIEW,
    AVATAR_CAPABILITY_VOICE,
)


def test_material_checks_reject_role_kind_mismatch() -> None:
    checks = _build_material_checks(role="speaking_video", kind="audio", meta={})

    assert checks == [
        {
            "level": "error",
            "message": "讲话视频片段字段只接受视频文件，当前文件识别为音频。",
        }
    ]


def test_runtime_capability_requires_matching_material_kind_for_legacy_records() -> None:
    capability, next_action = _derive_runtime_preview_capability(
        {"avatar_generation": "ready", "voice_clone": "ready", "preview": "ready"},
        [
            {"role": "speaking_video", "kind": "audio", "checks": []},
            {"role": "voice_sample", "kind": "audio", "checks": []},
        ],
        preview_service_available=True,
    )

    assert capability[AVATAR_CAPABILITY_GENERATION] == "missing"
    assert capability[AVATAR_CAPABILITY_VOICE] == "ready"
    assert capability[AVATAR_CAPABILITY_PREVIEW] == "missing"
    assert "讲话视频片段" in next_action


def test_runtime_capability_keeps_independent_ready_materials_when_one_role_blocks() -> None:
    capability, next_action = _derive_runtime_preview_capability(
        {},
        [
            {"role": "speaking_video", "kind": "video", "checks": []},
            {
                "role": "voice_sample",
                "kind": "image",
                "checks": [{"level": "error", "message": "声音采样字段只接受音频文件。"}],
            },
        ],
        preview_service_available=True,
    )

    assert capability[AVATAR_CAPABILITY_GENERATION] == "ready"
    assert capability[AVATAR_CAPABILITY_VOICE] == "missing"
    assert capability[AVATAR_CAPABILITY_PREVIEW] == "missing"
    assert "阻塞项" in next_action


def test_profile_runtime_state_does_not_ready_voice_when_voice_file_blocks() -> None:
    state = _build_profile_runtime_state(
        speaking_video_count=1,
        portrait_photo_count=0,
        voice_sample_count=1,
        training_api_available=False,
        preview_service_available=True,
        blocking_issues=["voice.png: 声音采样字段只接受音频文件，当前文件识别为图片。"],
        warnings=[],
    )

    assert state["capability_status"][AVATAR_CAPABILITY_GENERATION] == "ready"
    assert state["capability_status"][AVATAR_CAPABILITY_VOICE] == "missing"
    assert state["capability_status"][AVATAR_CAPABILITY_PREVIEW] == "missing"


def test_creator_dashboard_counts_only_ready_materials() -> None:
    dashboard = build_creator_profile_dashboard(
        {
            "files": [
                {"role": "speaking_video", "kind": "audio", "checks": []},
                {"role": "voice_sample", "kind": "audio", "checks": []},
                {
                    "role": "portrait_photo",
                    "kind": "image",
                    "checks": [{"level": "error", "message": "遮挡严重"}],
                },
            ]
        }
    )

    assert dashboard["material_counts"] == {
        "speaking_videos": 0,
        "portrait_photos": 0,
        "voice_samples": 1,
    }
    assert dashboard["section_status"]["materials"] is False


def test_creator_profile_preserves_cover_packaging_scheme() -> None:
    profile = normalize_creator_profile(
        {
            "publishing": {
                "cover_style": "edc_cinematic_hero",
                "cover_style_label": "EDC 电影英雄封面",
                "cover_packaging_scheme": "edc_cinematic_hero",
            }
        },
        personal_info=None,
        display_name="FAS",
    )

    assert profile["publishing"]["cover_style"] == "edc_cinematic_hero"
    assert profile["publishing"]["cover_style_label"] == "EDC 电影英雄封面"
    assert profile["publishing"]["cover_packaging_scheme"] == "edc_cinematic_hero"
