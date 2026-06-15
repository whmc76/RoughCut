import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from roughcut.api import avatar_materials
from roughcut.api.avatar_materials import (
    _build_material_checks,
    _build_profile_runtime_state,
    _derive_runtime_preview_capability,
)
from roughcut.avatar.materials import build_creator_profile_dashboard, normalize_avatar_material_profile, normalize_creator_profile
from roughcut.naming import (
    AVATAR_CAPABILITY_GENERATION,
    AVATAR_CAPABILITY_PREVIEW,
    AVATAR_CAPABILITY_VOICE,
)
from roughcut.pipeline.steps import _pick_avatar_profile_speaking_video_path


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


def test_creator_dashboard_counts_only_ready_materials(tmp_path, monkeypatch) -> None:
    material_root = tmp_path / "avatar_materials"
    profile_dir = material_root / "profiles" / "creator"
    profile_dir.mkdir(parents=True)
    voice_path = profile_dir / "voice.m4a"
    voice_path.write_bytes(b"voice")
    monkeypatch.setenv("ROUGHCUT_AVATAR_MATERIALS_DIR", str(material_root))

    dashboard = build_creator_profile_dashboard(
        {
            "files": [
                {"role": "speaking_video", "kind": "audio", "checks": []},
                {"role": "voice_sample", "kind": "audio", "path": str(voice_path), "checks": []},
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


def test_normalize_avatar_material_profile_repairs_stale_file_paths(tmp_path, monkeypatch) -> None:
    material_root = tmp_path / "avatar_materials"
    profile_dir = material_root / "profiles" / "creator"
    profile_dir.mkdir(parents=True)
    actual_video = profile_dir / "_.mp4"
    actual_video.write_bytes(b"video")
    monkeypatch.setenv("ROUGHCUT_AVATAR_MATERIALS_DIR", str(material_root))

    normalized = normalize_avatar_material_profile(
        {
            "profile_dir": str(profile_dir),
            "files": [
                {
                    "role": "speaking_video",
                    "kind": "video",
                    "path": str(profile_dir / "_1-_-20260313-151353.mp4"),
                    "checks": [],
                }
            ],
        }
    )

    assert normalized["files"][0]["path"] == str(actual_video.resolve())


def test_creator_dashboard_requires_existing_material_path(tmp_path, monkeypatch) -> None:
    material_root = tmp_path / "avatar_materials"
    profile_dir = material_root / "profiles" / "creator"
    profile_dir.mkdir(parents=True)
    monkeypatch.setenv("ROUGHCUT_AVATAR_MATERIALS_DIR", str(material_root))

    dashboard = build_creator_profile_dashboard(
        {
            "files": [
                {
                    "role": "speaking_video",
                    "kind": "video",
                    "path": str(profile_dir / "missing.mp4"),
                    "checks": [],
                },
                {
                    "role": "voice_sample",
                    "kind": "audio",
                    "path": str(profile_dir / "missing.m4a"),
                    "checks": [],
                },
            ]
        }
    )

    assert dashboard["material_counts"]["speaking_videos"] == 0
    assert dashboard["material_counts"]["voice_samples"] == 0
    assert dashboard["section_status"]["materials"] is False


def test_pick_avatar_profile_speaking_video_path_uses_resolved_material_path(tmp_path, monkeypatch) -> None:
    material_root = tmp_path / "avatar_materials"
    profile_dir = material_root / "profiles" / "creator"
    profile_dir.mkdir(parents=True)
    actual_video = profile_dir / "_.mp4"
    actual_video.write_bytes(b"video")
    monkeypatch.setenv("ROUGHCUT_AVATAR_MATERIALS_DIR", str(material_root))

    selected = _pick_avatar_profile_speaking_video_path(
        {
            "files": [
                {
                    "role": "speaking_video",
                    "kind": "video",
                    "path": str(profile_dir / "_1-_-20260313-151353.mp4"),
                }
            ]
        }
    )

    assert selected == actual_video.resolve()


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


def test_delete_avatar_material_file_removes_record_and_disk_file(tmp_path, monkeypatch) -> None:
    material_root = tmp_path / "avatar_materials"
    profile_dir = material_root / "profiles" / "creator"
    profile_dir.mkdir(parents=True)
    file_path = profile_dir / "voice.m4a"
    file_path.write_bytes(b"voice")
    (material_root / "profiles.json").write_text(
        json.dumps(
            [
                {
                    "id": "profile-1",
                    "display_name": "FAS",
                    "profile_dir": str(profile_dir),
                    "training_provider": "heygem",
                    "training_api_available": False,
                    "created_at": "2026-06-13T00:00:00Z",
                    "files": [
                        {
                            "id": "file-1",
                            "role": "voice_sample",
                            "kind": "audio",
                            "original_name": "voice.m4a",
                            "path": str(file_path),
                            "content_type": "audio/mp4",
                            "checks": [],
                        }
                    ],
                    "preview_runs": [{"id": "preview-1"}],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    async def unavailable() -> bool:
        return False

    monkeypatch.setenv("ROUGHCUT_AVATAR_MATERIALS_DIR", str(material_root))
    monkeypatch.setattr(avatar_materials, "is_heygem_training_available", unavailable)
    monkeypatch.setattr(avatar_materials, "is_heygem_preview_available", unavailable)
    app = FastAPI()
    app.include_router(avatar_materials.router)

    response = TestClient(app).delete("/avatar-materials/profiles/profile-1/files/file-1")

    assert response.status_code == 200
    assert not file_path.exists()
    payload = response.json()
    assert payload["profiles"][0]["files"] == []
    assert payload["profiles"][0]["preview_runs"] == []
