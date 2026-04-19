from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_create_job_accepts_multiple_uploaded_files_as_merged_task(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.jobs as jobs_api
    from roughcut.db.models import JobStep
    from roughcut.db.session import get_session_factory
    from sqlalchemy import select

    uploaded_payloads: dict[str, bytes] = {}

    class FakeStorage:
        def ensure_bucket(self) -> None:
            return None

        def upload_file(self, local_path: Path, key: str) -> str:
            uploaded_payloads[key] = Path(local_path).read_bytes()
            return key

    async def fake_merge_upload_files(file_paths: list[Path], *, output_path: Path) -> Path:
        output_path.write_bytes(b"|".join(path.read_bytes() for path in file_paths))
        return output_path

    monkeypatch.setattr(jobs_api, "get_storage", lambda: FakeStorage())
    monkeypatch.setattr(jobs_api, "_merge_upload_files_for_job", fake_merge_upload_files)

    response = await client.post(
        "/api/v1/jobs",
        data={
            "language": "zh-CN",
            "workflow_mode": "standard_edit",
            "video_description": "保留前后两段关键镜头",
        },
        files=[
            ("files", ("part-1.mp4", b"video-part-1", "video/mp4")),
            ("files", ("part-2.mp4", b"video-part-2", "video/mp4")),
        ],
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_name"] == "merged_2_part-1.mp4"
    assert payload["merged_source_names"] == ["part-1.mp4", "part-2.mp4"]
    assert payload["status"] == "pending"
    assert any(key.endswith("/merged_2_part-1.mp4") for key in uploaded_payloads)

    async with get_session_factory()() as session:
        result = await session.execute(
            select(JobStep).where(
                JobStep.job_id == uuid.UUID(payload["id"]),
                JobStep.step_name == "content_profile",
            )
        )
        step = result.scalar_one()

    assert step.metadata_["source_context"]["video_description"] == "保留前后两段关键镜头"
    assert step.metadata_["source_context"]["allow_related_profiles"] is True
    assert step.metadata_["source_context"]["merged_source_names"] == ["part-1.mp4", "part-2.mp4"]


@pytest.mark.asyncio
async def test_create_job_keeps_legacy_single_file_field(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.jobs as jobs_api

    uploaded_payloads: dict[str, bytes] = {}

    class FakeStorage:
        def ensure_bucket(self) -> None:
            return None

        def upload_file(self, local_path: Path, key: str) -> str:
            uploaded_payloads[key] = Path(local_path).read_bytes()
            return key

    monkeypatch.setattr(jobs_api, "get_storage", lambda: FakeStorage())

    response = await client.post(
        "/api/v1/jobs",
        data={"language": "zh-CN"},
        files={"file": ("single.mp4", b"single-video", "video/mp4")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["source_name"] == "single.mp4"
    assert payload["merged_source_names"] == []
    assert payload["status"] == "pending"
    assert any(key.endswith("/single.mp4") for key in uploaded_payloads)


def test_job_content_preview_ignores_generic_placeholder_subject_fields():
    from roughcut.api.jobs import _resolve_job_content_preview
    from roughcut.db.models import Artifact

    preview = _resolve_job_content_preview(
        [
            Artifact(
                artifact_type="content_profile",
                data_json={
                    "subject_brand": "",
                    "subject_model": "",
                    "subject_type": "unknown",
                    "video_theme": "待确认",
                    "summary": "这条视频当前主题待进一步确认，建议结合字幕、画面文字和人工核对后再继续包装。",
                    "content_understanding": {
                        "needs_review": True,
                        "primary_subject": "unknown",
                        "video_theme": "待确认",
                    },
                },
            )
        ]
    )

    assert preview["subject"] is None
    assert preview["summary"] == "这条视频当前主题待进一步确认，建议结合字幕、画面文字和人工核对后再继续包装。"


def test_job_content_preview_normalizes_bag_aliases_only_with_trusted_context():
    from roughcut.api.jobs import _resolve_job_content_preview
    from roughcut.db.models import Artifact

    preview = _resolve_job_content_preview(
        [
            Artifact(
                artifact_type="content_profile_final",
                data_json={
                    "content_kind": "unboxing",
                    "workflow_template": "unboxing_standard",
                    "subject_domain": "functional",
                    "subject_type": "EDC机能包",
                    "video_theme": "机能双肩包开箱评测",
                    "summary": "up主开箱赫斯郡与船长联名的两款机能双肩包。",
                    "content_understanding": {
                        "video_type": "unboxing",
                        "content_domain": "functional",
                    },
                },
            )
        ]
    )

    assert preview["summary"] == "up主开箱HSJUN与BOLTBOAT联名的两款机能双肩包。"


def test_job_content_preview_keeps_aliases_without_trusted_context():
    from roughcut.api.jobs import _resolve_job_content_preview
    from roughcut.db.models import Artifact

    preview = _resolve_job_content_preview(
        [
            Artifact(
                artifact_type="content_profile",
                data_json={
                    "subject_type": "unknown",
                    "video_theme": "待确认",
                    "summary": "这次主要聊赫斯郡和船长。",
                    "content_understanding": {
                        "video_type": "",
                        "content_domain": "",
                    },
                },
            )
        ]
    )

    assert preview["summary"] == "这次主要聊赫斯郡和船长。"


@pytest.mark.asyncio
async def test_health_detail_reports_runtime_surfaces(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.health as health_api

    async def fake_readiness():
        return {
            "status": "ready",
            "checks": {
                "database": {"status": "ok", "detail": "ok"},
                "redis": {"status": "ok", "detail": "ok"},
                "storage": {"status": "ok", "detail": "ok"},
            },
        }

    async def fake_lock_snapshot():
        return {
            "status": "held",
            "leader_active": True,
            "detail": "active leader",
        }

    async def fake_managed_services():
        return [
            {"name": "heygem", "url": "http://127.0.0.1:49202", "status": "ok", "enabled": True},
            {"name": "indextts2", "url": "http://127.0.0.1:49204", "status": "failed", "enabled": True},
        ]

    async def fake_watch_snapshot():
        return {
            "roots_total": 2,
            "running_scans": 1,
            "cached_pending_total": 3,
            "auto_enqueue_enabled": True,
            "auto_merge_enabled": True,
            "active_jobs": 1,
            "running_gpu_steps": 0,
            "idle_slots": 1,
        }

    monkeypatch.setattr(health_api, "build_readiness_payload", fake_readiness)
    monkeypatch.setattr(health_api, "get_orchestrator_lock_snapshot", fake_lock_snapshot)
    monkeypatch.setattr(health_api, "get_managed_service_snapshots", fake_managed_services)
    monkeypatch.setattr(health_api, "get_watch_root_auto_duty_snapshot", fake_watch_snapshot)

    response = await client.get("/api/v1/health/detail")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["readiness"]["status"] == "ready"
    assert payload["orchestrator_lock"]["status"] == "held"
    assert payload["managed_services"][1]["status"] == "failed"
    assert payload["watch_automation"]["running_scans"] == 1


@pytest.mark.asyncio
async def test_glossary_empty_list(client: AsyncClient):
    response = await client.get("/api/v1/glossary")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_glossary_builtin_packs_endpoint(client: AsyncClient):
    response = await client.get("/api/v1/glossary/builtin-packs")
    assert response.status_code == 200
    data = response.json()
    domains = {item["domain"] for item in data}
    assert {"edc", "outdoor", "tech", "ai", "functional", "tools", "travel", "food", "finance", "news", "sports"}.issubset(domains)
    edc_pack = next(item for item in data if item["domain"] == "edc")
    tech_pack = next(item for item in data if item["domain"] == "tech")
    ai_pack = next(item for item in data if item["domain"] == "ai")
    functional_pack = next(item for item in data if item["domain"] == "functional")
    tools_pack = next(item for item in data if item["domain"] == "tools")
    assert edc_pack["term_count"] >= 20
    assert any(term["correct_form"] == "EDC" for term in edc_pack["terms"])
    assert any(term["correct_form"] == "潮玩" for term in edc_pack["terms"])
    assert any(term["correct_form"] == "户外" for term in edc_pack["terms"])
    assert any(term["correct_form"] in {"芯片", "手机", "耳机"} for term in tech_pack["terms"])
    assert any(term["correct_form"] in {"工作流", "ComfyUI", "模型"} for term in ai_pack["terms"])
    assert any(term["correct_form"] in {"机能", "机能装备", "tomtoc"} for term in functional_pack["terms"])
    assert any(term["correct_form"] in {"NexTool", "工具钳", "SATA"} for term in tools_pack["terms"])


@pytest.mark.asyncio
async def test_config_has_extended_provider_fields(client: AsyncClient):
    response = await client.get("/api/v1/config")
    assert response.status_code == 200
    data = response.json()
    assert "transcription_dialect" in data
    assert "qwen_asr_api_base_url" in data
    assert "avatar_provider" in data
    assert "voice_provider" in data
    assert "minimax_api_key_set" in data
    assert "openai_base_url" not in data
    assert "avatar_api_base_url" not in data
    assert "voice_clone_api_base_url" not in data
    assert "output_dir" not in data


@pytest.mark.asyncio
async def test_runtime_environment_exposes_env_managed_fields(client: AsyncClient):
    response = await client.get("/api/v1/config/environment")
    assert response.status_code == 200
    data = response.json()
    assert "openai_base_url" in data
    assert "openai_auth_mode" in data
    assert "avatar_api_base_url" in data
    assert "avatar_training_api_base_url" in data
    assert "voice_clone_api_base_url" in data
    assert "output_dir" in data


@pytest.mark.asyncio
async def test_config_patch_updates_preferred_ui_language(client: AsyncClient):
    response = await client.patch("/api/v1/config", json={"preferred_ui_language": "en-US"})

    assert response.status_code == 200
    assert response.json()["preferred_ui_language"] == "en-US"


@pytest.mark.asyncio
async def test_config_patch_rejects_env_managed_fields(client: AsyncClient, tmp_path: Path):
    response = await client.patch(
        "/api/v1/config",
        json={
            "openai_base_url": "https://override.invalid/v1",
            "output_dir": str(tmp_path / "exports"),
        },
    )

    assert response.status_code == 400
    assert "startup env only" in response.json()["detail"]


@pytest.mark.asyncio
async def test_config_options_exposes_transcription_models(client: AsyncClient):
    response = await client.get("/api/v1/config/options")
    assert response.status_code == 200
    data = response.json()
    assert data["job_languages"][0]["value"] == "zh-CN"
    assert data["workflow_templates"][0]["value"] == ""
    assert data["workflow_modes"][0]["value"] == "standard_edit"
    assert any(item["value"] == "avatar_commentary" for item in data["enhancement_modes"])
    assert any(item["value"] == "mandarin" for item in data["transcription_dialects"])
    assert any(item["value"] == "beijing" for item in data["transcription_dialects"])
    assert any(item["value"] == "heygem" for item in data["avatar_providers"])
    assert any(item["value"] == "indextts2" for item in data["voice_providers"])
    assert any(item["key"] == "long_text_to_video" and item["status"] == "planned" for item in data["creative_mode_catalog"]["workflow_modes"])
    assert data["transcription_models"]["faster_whisper"][0] == "large-v3"
    assert data["transcription_models"]["openai"] == ["gpt-4o-transcribe", "gpt-4o-mini-transcribe"]
    assert data["transcription_models"]["qwen3_asr"][0] == "qwen3-asr-1.7b"
    assert "qwen3-asr-0.6b" in data["transcription_models"]["qwen3_asr"]
    assert "large-v3-turbo" in data["transcription_models"]["faster_whisper"]
    assert "large-v3" in data["transcription_models"]["faster_whisper"]
    assert any(item["value"] == "unboxing_standard" for item in data["workflow_templates"])
    assert all(item["value"] != "edc_tactical" for item in data["workflow_templates"])
    assert any(item["value"] == "ollama" for item in data["multimodal_fallback_providers"])
    assert any(item["value"] == "auto" for item in data["search_providers"])


@pytest.mark.asyncio
async def test_avatar_materials_endpoint_exposes_requirements(client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.avatar_materials as avatar_materials_api
    import roughcut.avatar.materials as avatar_materials_mod

    monkeypatch.setattr(avatar_materials_mod, "_AVATAR_MATERIALS_ROOT", tmp_path / "avatar_materials")
    async def fake_training_available():
        return False

    monkeypatch.setattr(avatar_materials_api, "is_heygem_training_available", fake_training_available)

    response = await client.get("/api/v1/avatar-materials")

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "heygem"
    assert data["training_api_available"] is False
    assert any(section["title"] == "档案组成" for section in data["sections"])
    assert any(section["title"] == "必须满足" for section in data["sections"])
    assert data["profiles"] == []


@pytest.mark.asyncio
async def test_avatar_materials_endpoint_warns_on_demo_profiles(client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.avatar_materials as avatar_materials_api
    import roughcut.avatar.materials as avatar_materials_mod

    monkeypatch.setattr(avatar_materials_mod, "_AVATAR_MATERIALS_ROOT", tmp_path / "avatar_materials")

    profile_dir = tmp_path / "avatar_materials" / "profiles" / "demo_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    avatar_materials_mod.save_avatar_material_profile(
        {
            "id": "demo-profile-1",
            "display_name": "demo creator a",
            "presenter_alias": "CreatorDemoA",
            "notes": "demo profile",
            "profile_dir": str(profile_dir),
            "training_status": "ready_for_manual_training",
            "training_provider": "heygem",
            "training_api_available": True,
            "next_action": "ready",
            "capability_status": {
                "heygem_avatar": "ready",
                "voice_clone": "ready",
                "portrait_reference": "ready",
                "preview": "ready",
            },
            "blocking_issues": [],
            "warnings": [],
            "created_at": "2026-03-26T00:00:00Z",
            "files": [],
            "preview_runs": [],
            "creator_profile": {
                "identity": {"public_name": "CreatorDemoA", "title": None, "bio": None},
                "positioning": {
                    "creator_focus": None,
                    "expertise": [],
                    "audience": None,
                    "style": None,
                    "tone_keywords": [],
                },
                "publishing": {
                    "primary_platform": None,
                    "active_platforms": [],
                    "signature": None,
                    "default_call_to_action": None,
                    "description_strategy": None,
                },
                "business": {
                    "contact": None,
                    "collaboration_notes": None,
                    "availability": None,
                },
                "archive_notes": None,
            },
            "profile_dashboard": {
                "completeness_score": 20,
                "section_status": {
                    "identity": False,
                    "positioning": False,
                    "publishing": False,
                    "business": False,
                    "materials": True,
                },
                "material_counts": {
                    "speaking_videos": 1,
                    "portrait_photos": 1,
                    "voice_samples": 1,
                },
                    "strengths": ["demo pipeline ready"],
                    "next_steps": [],
                },
            }
        )

    async def fake_training_available():
        return False

    monkeypatch.setattr(avatar_materials_api, "is_heygem_training_available", fake_training_available)

    response = await client.get("/api/v1/avatar-materials")

    assert response.status_code == 200
    data = response.json()
    assert len(data["profiles"]) == 1
    assert data["warnings"]
    assert "demo creator a" in data["warnings"][0]
    assert "profiles.json" in data["warnings"][0]


@pytest.mark.asyncio
async def test_avatar_materials_upload_creates_profile(client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.avatar_materials as avatar_materials_api
    import roughcut.avatar.materials as avatar_materials_mod

    monkeypatch.setattr(avatar_materials_mod, "_AVATAR_MATERIALS_ROOT", tmp_path / "avatar_materials")

    async def fake_probe(path: Path):
        class Meta:
            duration = 24.0 if path.suffix.lower() == ".mp4" else 12.0
            width = 1920
            height = 1080
            fps = 30.0
            video_codec = "h264"
            audio_codec = "aac"
            audio_sample_rate = 48000
            audio_channels = 2
            format_name = "mov,mp4,m4a,3gp,3g2,mj2"
            bit_rate = 128000

        assert path.suffix.lower() in {".mp4", ".wav"}
        return Meta()

    monkeypatch.setattr(avatar_materials_api, "probe", fake_probe)
    async def fake_training_available():
        return True

    async def fake_prepare_voice_sample_artifacts(
        file_record: dict[str, object],
        *,
        attempt_preprocess: bool = True,
        require_preprocess: bool = False,
    ):
        assert attempt_preprocess is True
        assert require_preprocess is False
        file_record["artifacts"] = {
            "normalized_wav_path": str(tmp_path / "voice.wav"),
            "training_reference_name": "voice.wav",
            "training_preprocess": {
                "code": 0,
                "reference_audio_text": "测试参考文本",
                "asr_format_audio_url": "/tmp/voice.wav",
            },
        }
        return file_record

    monkeypatch.setattr(avatar_materials_api, "is_heygem_training_available", fake_training_available)
    monkeypatch.setattr(avatar_materials_api, "prepare_voice_sample_artifacts", fake_prepare_voice_sample_artifacts)

    response = await client.post(
        "/api/v1/avatar-materials/profiles",
        data={
            "display_name": "测试数字人",
            "creator_profile_json": json.dumps(
                {
                    "identity": {
                        "public_name": "测试作者",
                        "title": "EDC评测作者",
                    },
                    "positioning": {
                        "creator_focus": "手电开箱、EDC装备",
                        "expertise": ["手电", "EDC"],
                    },
                    "publishing": {
                        "primary_platform": "B站",
                        "active_platforms": ["B站", "小红书"],
                    },
                },
                ensure_ascii=False,
            ),
        },
        files=[
            ("speaking_videos", ("presenter.mp4", b"fake-video", "video/mp4")),
            ("portrait_photos", ("portrait.jpg", b"fake-image", "image/jpeg")),
            ("voice_samples", ("voice.wav", b"fake-audio", "audio/wav")),
        ],
    )

    assert response.status_code == 201
    data = response.json()
    assert len(data["profiles"]) == 1
    profile = data["profiles"][0]
    assert profile["display_name"] == "测试数字人"
    assert profile["training_status"] == "ready_for_manual_training"
    assert profile["capability_status"]["heygem_avatar"] == "ready"
    assert profile["capability_status"]["voice_clone"] == "ready"
    assert profile["capability_status"]["portrait_reference"] == "ready"
    assert profile["capability_status"]["preview"] == "ready"
    assert profile["training_api_available"] is True
    assert profile["personal_info"]["public_name"] == "测试作者"
    assert profile["personal_info"]["title"] == "EDC评测作者"
    assert profile["personal_info"]["creator_focus"] == "手电开箱、EDC装备"
    assert profile["personal_info"]["expertise"] == ["手电", "EDC"]
    assert profile["creator_profile"]["identity"]["public_name"] == "测试作者"
    assert profile["creator_profile"]["publishing"]["primary_platform"] == "B站"
    assert profile["profile_dashboard"]["section_status"]["identity"] is True
    assert profile["profile_dashboard"]["section_status"]["publishing"] is True
    assert any(item["role"] == "speaking_video" for item in profile["files"])
    assert any(item["role"] == "portrait_photo" for item in profile["files"])
    assert any(item["role"] == "voice_sample" for item in profile["files"])
    voice_file = next(item for item in profile["files"] if item["role"] == "voice_sample")
    assert voice_file["artifacts"]["training_preprocess"]["reference_audio_text"] == "测试参考文本"


@pytest.mark.asyncio
async def test_avatar_materials_upload_preview_ready_without_training_api(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.avatar_materials as avatar_materials_api
    import roughcut.avatar.materials as avatar_materials_mod

    monkeypatch.setattr(avatar_materials_mod, "_AVATAR_MATERIALS_ROOT", tmp_path / "avatar_materials")

    async def fake_probe(path: Path):
        class Meta:
            duration = 24.0 if path.suffix.lower() == ".mp4" else 12.0
            width = 1920
            height = 1080
            fps = 30.0
            video_codec = "h264"
            audio_codec = "aac"
            audio_sample_rate = 48000
            audio_channels = 2
            format_name = "mov,mp4,m4a,3gp,3g2,mj2"
            bit_rate = 128000

        return Meta()

    async def fake_training_available():
        return False

    async def fake_prepare_voice_sample_artifacts(
        file_record: dict[str, object],
        *,
        attempt_preprocess: bool = True,
        require_preprocess: bool = False,
    ):
        assert attempt_preprocess is False
        assert require_preprocess is False
        file_record["artifacts"] = {
            "normalized_wav_path": str(tmp_path / "voice_fallback.wav"),
            "training_reference_name": "voice_fallback.wav",
        }
        return file_record

    monkeypatch.setattr(avatar_materials_api, "probe", fake_probe)
    monkeypatch.setattr(avatar_materials_api, "is_heygem_training_available", fake_training_available)
    monkeypatch.setattr(avatar_materials_api, "prepare_voice_sample_artifacts", fake_prepare_voice_sample_artifacts)

    response = await client.post(
        "/api/v1/avatar-materials/profiles",
        data={"display_name": "无训练接口预览"},
        files=[
            ("speaking_videos", ("presenter.mp4", b"fake-video", "video/mp4")),
            ("voice_samples", ("voice.wav", b"fake-audio", "audio/wav")),
        ],
    )

    assert response.status_code == 201
    profile = response.json()["profiles"][0]
    assert profile["training_api_available"] is False
    assert profile["capability_status"]["preview"] == "ready"
    assert isinstance(profile["next_action"], str)
    assert profile["next_action"]


@pytest.mark.asyncio
async def test_avatar_material_preview_creates_run(client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.avatar_materials as avatar_materials_api
    import roughcut.avatar.materials as avatar_materials_mod

    monkeypatch.setattr(avatar_materials_mod, "_AVATAR_MATERIALS_ROOT", tmp_path / "avatar_materials")

    profile_dir = tmp_path / "avatar_materials" / "profiles" / "demo_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    preview_path = profile_dir / "previews" / "preview.mp4"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_bytes(b"fake-preview")

    avatar_materials_mod.save_avatar_material_profile(
        {
            "id": "profile-1",
            "display_name": "测试数字人",
            "presenter_alias": None,
            "notes": None,
            "profile_dir": str(profile_dir),
            "training_status": "ready_for_manual_training",
            "training_provider": "heygem",
            "training_api_available": True,
            "next_action": "ready",
            "capability_status": {
                "heygem_avatar": "ready",
                "voice_clone": "ready",
                "portrait_reference": "ready",
                "preview": "ready",
            },
            "blocking_issues": [],
            "warnings": [],
            "created_at": "2026-03-12T00:00:00Z",
            "files": [],
            "preview_runs": [],
        }
    )

    async def fake_generate_avatar_preview(*, profile: dict[str, object], script: str):
        assert profile["id"] == "profile-1"
        return {
            "id": "preview-1",
            "status": "completed",
            "script": script,
            "task_code": "task-1",
            "output_path": str(preview_path),
            "output_size_bytes": len(b"fake-preview"),
            "duration_sec": 3.2,
            "width": 1080,
            "height": 1920,
            "preview_mode": "source_audio_fallback",
            "fallback_reason": "training_preprocess_unavailable",
            "created_at": "2026-03-12T00:00:05Z",
        }

    async def fake_training_available():
        return True

    monkeypatch.setattr(avatar_materials_api, "generate_avatar_preview", fake_generate_avatar_preview)
    monkeypatch.setattr(avatar_materials_api, "is_heygem_training_available", fake_training_available)

    response = await client.post(
        "/api/v1/avatar-materials/profiles/profile-1/preview",
        json={"script": "这是一条测试预览"},
    )

    assert response.status_code == 200
    data = response.json()
    profile = data["profiles"][0]
    assert profile["preview_runs"][0]["id"] == "preview-1"
    assert profile["preview_runs"][0]["status"] == "completed"
    assert profile["preview_runs"][0]["preview_mode"] == "source_audio_fallback"
    assert profile["preview_runs"][0]["fallback_reason"] == "training_preprocess_unavailable"

    file_response = await client.get("/api/v1/avatar-materials/profiles/profile-1/preview-runs/preview-1/file")
    assert file_response.status_code == 200
    assert file_response.content == b"fake-preview"


@pytest.mark.asyncio
async def test_avatar_material_file_endpoint_resolves_legacy_windows_storage_paths(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.avatar.materials as avatar_materials_mod

    monkeypatch.setattr(avatar_materials_mod, "_AVATAR_MATERIALS_ROOT", tmp_path / "avatar_materials")

    profile_dir = tmp_path / "avatar_materials" / "profiles" / "demo_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    speaking_video = profile_dir / "presenter.mp4"
    preview_path = profile_dir / "previews" / "preview.mp4"
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    speaking_video.write_bytes(b"legacy-video")
    preview_path.write_bytes(b"legacy-preview")

    legacy_video_path = r"E:\WorkSpace\RoughCut\data\avatar_materials\profiles\demo_profile\presenter.mp4"
    legacy_preview_path = r"E:\WorkSpace\RoughCut\data\avatar_materials\profiles\demo_profile\previews\preview.mp4"

    avatar_materials_mod.save_avatar_material_profile(
        {
            "id": "profile-legacy",
            "display_name": "Legacy Profile",
            "presenter_alias": None,
            "notes": None,
            "profile_dir": r"E:\WorkSpace\RoughCut\data\avatar_materials\profiles\demo_profile",
            "training_status": "ready_for_manual_training",
            "training_provider": "heygem",
            "training_api_available": True,
            "next_action": "ready",
            "capability_status": {
                "heygem_avatar": "ready",
                "voice_clone": "ready",
                "portrait_reference": "ready",
                "preview": "ready",
            },
            "blocking_issues": [],
            "warnings": [],
            "created_at": "2026-03-12T00:00:00Z",
            "files": [
                {
                    "id": "file-legacy",
                    "original_name": "presenter.mp4",
                    "stored_name": "presenter.mp4",
                    "kind": "video",
                    "role": "speaking_video",
                    "role_label": "讲话视频片段",
                    "pipeline_target": "heygem_avatar",
                    "content_type": "video/mp4",
                    "size_bytes": len(b"legacy-video"),
                    "path": legacy_video_path,
                    "created_at": "2026-03-12T00:00:00Z",
                    "probe": None,
                    "artifacts": None,
                    "checks": [],
                }
            ],
            "preview_runs": [
                {
                    "id": "preview-legacy",
                    "status": "completed",
                    "script": "legacy preview",
                    "output_path": legacy_preview_path,
                    "created_at": "2026-03-12T00:00:05Z",
                }
            ],
        }
    )

    file_response = await client.get("/api/v1/avatar-materials/profiles/profile-legacy/files/file-legacy")
    assert file_response.status_code == 200
    assert file_response.content == b"legacy-video"

    preview_response = await client.get("/api/v1/avatar-materials/profiles/profile-legacy/preview-runs/preview-legacy/file")
    assert preview_response.status_code == 200
    assert preview_response.content == b"legacy-preview"


@pytest.mark.asyncio
async def test_avatar_material_file_endpoint_falls_back_to_unique_sibling_when_stored_name_is_stale(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.avatar.materials as avatar_materials_mod

    monkeypatch.setattr(avatar_materials_mod, "_AVATAR_MATERIALS_ROOT", tmp_path / "avatar_materials")

    profile_dir = tmp_path / "avatar_materials" / "profiles" / "legacy_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    actual_video = profile_dir / "_.mp4"
    actual_video.write_bytes(b"rescued-video")

    avatar_materials_mod.save_avatar_material_profile(
        {
            "id": "profile-stale-name",
            "display_name": "Legacy Filename",
            "presenter_alias": None,
            "notes": None,
            "profile_dir": r"E:\WorkSpace\RoughCut\data\avatar_materials\profiles\legacy_profile",
            "training_status": "ready_for_manual_training",
            "training_provider": "heygem",
            "training_api_available": True,
            "next_action": "ready",
            "capability_status": {
                "heygem_avatar": "ready",
                "voice_clone": "ready",
                "portrait_reference": "ready",
                "preview": "ready",
            },
            "blocking_issues": [],
            "warnings": [],
            "created_at": "2026-03-12T00:00:00Z",
            "files": [
                {
                    "id": "file-stale-name",
                    "original_name": "主播镜头1-合并-20260313-151353.mp4",
                    "stored_name": "_1-_-20260313-151353.mp4",
                    "kind": "video",
                    "role": "speaking_video",
                    "role_label": "讲话视频片段",
                    "pipeline_target": "heygem_avatar",
                    "content_type": "video/mp4",
                    "size_bytes": len(b"rescued-video"),
                    "path": r"E:\WorkSpace\RoughCut\data\avatar_materials\profiles\legacy_profile\_1-_-20260313-151353.mp4",
                    "created_at": "2026-03-12T00:00:00Z",
                    "probe": None,
                    "artifacts": None,
                    "checks": [],
                }
            ],
            "preview_runs": [],
        }
    )

    response = await client.get("/api/v1/avatar-materials/profiles/profile-stale-name/files/file-stale-name")
    assert response.status_code == 200
    assert response.content == b"rescued-video"


@pytest.mark.asyncio
async def test_watch_root_rejects_unknown_workflow_template(client: AsyncClient):
    response = await client.post(
        "/api/v1/watch-roots",
        json={"path": "/tmp/videos-invalid", "enabled": True, "workflow_template": "free_text_profile"},
    )

    assert response.status_code == 422
    assert "Unsupported workflow_template" in response.text


@pytest.mark.asyncio
async def test_job_upload_rejects_unknown_language(client: AsyncClient):
    response = await client.post(
        "/api/v1/jobs",
        files={"file": ("demo.mp4", b"video", "video/mp4")},
        data={"language": "zh_cn_free_text"},
    )

    assert response.status_code == 422
    assert "Unsupported language" in response.text


@pytest.mark.asyncio
async def test_job_upload_rejects_unavailable_workflow_mode(client: AsyncClient):
    response = await client.post(
        "/api/v1/jobs",
        files={"file": ("demo.mp4", b"video", "video/mp4")},
        data={"workflow_mode": "long_text_to_video"},
    )

    assert response.status_code == 422
    assert "workflow_mode not available yet" in response.text


@pytest.mark.asyncio
async def test_job_upload_rejects_unknown_enhancement_mode(client: AsyncClient):
    response = await client.post(
        "/api/v1/jobs",
        files={"file": ("demo.mp4", b"video", "video/mp4")},
        data={"enhancement_modes": "director_plus"},
    )

    assert response.status_code == 422
    assert "Unsupported enhancement_mode" in response.text


@pytest.mark.asyncio
async def test_job_upload_persists_video_description_to_content_profile_step(client: AsyncClient, db_engine):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from roughcut.db.models import JobStep

    response = await client.post(
        "/api/v1/jobs",
        files={"file": ("demo.mp4", b"video", "video/mp4")},
        data={"video_description": "这是一期数码开箱，保留按键手感和细节近景，节奏偏快。"},
    )

    assert response.status_code == 201
    job_id = response.json()["id"]

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            select(JobStep).where(JobStep.job_id == uuid.UUID(job_id), JobStep.step_name == "content_profile")
        )
        step = result.scalar_one()
        assert step.metadata_["source_context"]["video_description"] == "这是一期数码开箱，保留按键手感和细节近景，节奏偏快。"


@pytest.mark.asyncio
async def test_job_upload_extracts_filename_brief_into_video_description(client: AsyncClient, db_engine):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from roughcut.db.models import JobStep

    response = await client.post(
        "/api/v1/jobs",
        files={"file": ("20260316_狐蝠工业_FXX1小副包_开箱测评.mp4", b"video", "video/mp4")},
    )

    assert response.status_code == 201
    job_id = response.json()["id"]

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(
            select(JobStep).where(JobStep.job_id == uuid.UUID(job_id), JobStep.step_name == "content_profile")
        )
        step = result.scalar_one()
        assert step.metadata_["source_context"]["video_description"].startswith("任务说明依据文件名：")
        assert "狐蝠工业 FXX1小副包 开箱测评" in step.metadata_["source_context"]["video_description"]


@pytest.mark.asyncio
async def test_glossary_crud(client: AsyncClient):
    # Create
    resp = await client.post(
        "/api/v1/glossary",
        json={"wrong_forms": ["GPT4", "gpt4"], "correct_form": "GPT-4", "category": "brand"},
    )
    assert resp.status_code == 201
    term_id = resp.json()["id"]

    # Read
    resp = await client.get(f"/api/v1/glossary/{term_id}")
    assert resp.status_code == 200
    assert resp.json()["correct_form"] == "GPT-4"

    # Update
    resp = await client.patch(
        f"/api/v1/glossary/{term_id}",
        json={"correct_form": "GPT-4o"},
    )
    assert resp.status_code == 200
    assert resp.json()["correct_form"] == "GPT-4o"

    # Delete
    resp = await client.delete(f"/api/v1/glossary/{term_id}")
    assert resp.status_code == 204

    # Confirm deleted
    resp = await client.get(f"/api/v1/glossary/{term_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_watch_roots_crud(client: AsyncClient):
    resp = await client.post(
        "/api/v1/watch-roots",
        json={"path": "/tmp/videos", "enabled": True, "ingest_mode": "task_only"},
    )
    assert resp.status_code == 201
    created = resp.json()
    root_id = created["id"]
    assert created["scan_mode"] == "fast"
    assert created["ingest_mode"] == "task_only"

    resp = await client.get("/api/v1/watch-roots")
    assert resp.status_code == 200
    roots = resp.json()
    assert any(r["id"] == root_id and r["scan_mode"] == "fast" and r["ingest_mode"] == "task_only" for r in roots)

    resp = await client.delete(f"/api/v1/watch-roots/{root_id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_watch_roots_crud_persists_bound_config_profile(client: AsyncClient):
    from roughcut.db.models import ConfigProfile
    from roughcut.db.session import get_session_factory

    profile_id = uuid.uuid4()
    async with get_session_factory()() as session:
        session.add(
            ConfigProfile(
                id=profile_id,
                name="FAS标准",
                description="EDC潮玩开箱新品介绍",
                settings_json={
                    "reasoning_model": "profile-reasoner",
                    "default_job_workflow_mode": "standard_edit",
                    "default_job_enhancement_modes": ["ai_director"],
                },
                packaging_json={
                    "copy_style": "attention_grabbing",
                    "subtitle_style": "bold_yellow_outline",
                    "cover_style": "preset_default",
                    "title_style": "preset_default",
                    "smart_effect_style": "smart_effect_rhythm",
                    "subtitle_motion_style": "motion_static",
                    "enabled": True,
                },
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    resp = await client.post(
        "/api/v1/watch-roots",
        json={"path": "/tmp/videos-profile", "enabled": True, "config_profile_id": str(profile_id)},
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["config_profile_id"] == str(profile_id)

    resp = await client.get("/api/v1/watch-roots")
    assert resp.status_code == 200
    roots = resp.json()
    assert any(r["id"] == created["id"] and r["config_profile_id"] == str(profile_id) for r in roots)


@pytest.mark.asyncio
async def test_watch_root_inventory(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.review as review_api

    async def fake_scan_watch_root_inventory(
        path: str,
        *,
        recursive: bool = True,
        scan_mode: str = "fast",
        output_dir: str | None = None,
    ):
        assert path == "/tmp/videos"
        assert scan_mode == "precise"
        assert output_dir is None
        return {
            "pending": [
                {
                    "path": "/tmp/videos/a.mp4",
                    "relative_path": "a.mp4",
                    "source_name": "a.mp4",
                    "stem": "a",
                    "size_bytes": 123,
                    "modified_at": "2026-03-11T18:00:00",
                    "duration_sec": 12.5,
                    "width": 1920,
                    "height": 1080,
                    "fps": 30.0,
                    "status": "pending",
                    "dedupe_reason": None,
                    "matched_job_id": None,
                    "matched_output_path": None,
                }
            ],
            "deduped": [],
        }

    monkeypatch.setattr(review_api, "scan_watch_root_inventory", fake_scan_watch_root_inventory)

    created = await client.post(
        "/api/v1/watch-roots",
        json={"path": "/tmp/videos", "enabled": True, "scan_mode": "precise"},
    )
    root_id = created.json()["id"]

    response = await client.get(f"/api/v1/watch-roots/{root_id}/inventory")
    assert response.status_code == 200
    data = response.json()
    assert len(data["pending"]) == 1
    assert data["pending"][0]["source_name"] == "a.mp4"


@pytest.mark.asyncio
async def test_watch_root_inventory_scan_status(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.review as review_api
    watch_path = "/tmp/videos-scan"

    def fake_start_watch_root_inventory_scan(
        path: str,
        *,
        force: bool = False,
        recursive: bool = True,
        scan_mode: str = "fast",
        output_dir: str | None = None,
    ):
        assert path == watch_path
        assert force is True
        assert scan_mode == "precise"
        assert output_dir is None
        return {
            "root_path": path,
            "scan_mode": scan_mode,
            "status": "running",
            "started_at": "2026-03-11T18:00:00",
            "updated_at": "2026-03-11T18:00:01",
            "finished_at": None,
            "total_files": 10,
            "processed_files": 3,
            "pending_count": 2,
            "deduped_count": 1,
            "current_file": "subdir/a.mp4",
            "current_phase": "hashing",
            "current_file_size_bytes": 1024,
            "current_file_processed_bytes": 512,
            "error": None,
            "inventory": {"pending": [], "deduped": []},
        }

    def fake_get_watch_root_inventory_scan_status(
        path: str,
        *,
        include_inventory: bool = True,
        inventory_limit: int | None = None,
    ):
        assert path == watch_path
        assert include_inventory is False
        assert inventory_limit is None
        return {
            "root_path": path,
            "scan_mode": "precise",
            "status": "done",
            "started_at": "2026-03-11T18:00:00",
            "updated_at": "2026-03-11T18:00:03",
            "finished_at": "2026-03-11T18:00:03",
            "total_files": 10,
            "processed_files": 10,
            "pending_count": 4,
            "deduped_count": 6,
            "current_file": None,
            "current_phase": None,
            "current_file_size_bytes": None,
            "current_file_processed_bytes": None,
            "error": None,
            "inventory": {"pending": [], "deduped": []},
        }

    monkeypatch.setattr(review_api, "start_watch_root_inventory_scan", fake_start_watch_root_inventory_scan)
    monkeypatch.setattr(review_api, "get_watch_root_inventory_scan_status", fake_get_watch_root_inventory_scan_status)

    created = await client.post(
        "/api/v1/watch-roots",
        json={"path": watch_path, "enabled": True, "scan_mode": "precise"},
    )
    root_id = created.json()["id"]

    started = await client.post(f"/api/v1/watch-roots/{root_id}/inventory/scan", json={"force": True})
    assert started.status_code == 200
    assert started.json()["status"] == "running"
    assert started.json()["processed_files"] == 3
    assert started.json()["scan_mode"] == "precise"

    status = await client.get(f"/api/v1/watch-roots/{root_id}/inventory/status")
    assert status.status_code == 200
    assert status.json()["status"] == "done"
    assert status.json()["deduped_count"] == 6


@pytest.mark.asyncio
async def test_watch_root_inventory_status_uses_cached_snapshot(client: AsyncClient):
    from roughcut.db.models import WatchRoot
    from roughcut.db.session import get_session_factory

    created = await client.post("/api/v1/watch-roots", json={"path": "/tmp/videos-cache", "enabled": True})
    root_id = created.json()["id"]

    async with get_session_factory()() as session:
        root = await session.get(WatchRoot, uuid.UUID(root_id))
        root.inventory_cache_json = {
            "root_path": "/tmp/videos-cache",
            "scan_mode": "fast",
            "status": "done",
            "started_at": "2026-03-11T18:00:00",
            "updated_at": "2026-03-11T18:00:10",
            "finished_at": "2026-03-11T18:00:10",
            "total_files": 2,
            "processed_files": 2,
            "pending_count": 1,
            "deduped_count": 1,
            "current_file": None,
            "current_phase": None,
            "current_file_size_bytes": None,
            "current_file_processed_bytes": None,
            "error": None,
            "inventory": {
                "pending": [
                    {
                        "path": "/tmp/videos-cache/a.mp4",
                        "relative_path": "a.mp4",
                        "source_name": "a.mp4",
                        "stem": "a",
                        "size_bytes": 123,
                        "modified_at": "2026-03-11T18:00:00",
                        "duration_sec": 12.5,
                        "width": 1920,
                        "height": 1080,
                        "fps": 30.0,
                        "status": "pending",
                        "dedupe_reason": None,
                        "matched_job_id": None,
                        "matched_output_path": None,
                    }
                ],
                "deduped": [],
            },
        }
        await session.commit()

    summary = await client.get(f"/api/v1/watch-roots/{root_id}/inventory/status?include_inventory=false")
    assert summary.status_code == 200
    assert summary.json()["status"] == "done"
    assert summary.json()["scan_mode"] == "fast"
    assert summary.json()["inventory"]["pending"] == []

    full = await client.get(f"/api/v1/watch-roots/{root_id}/inventory/status?include_inventory=true")
    assert full.status_code == 200
    assert full.json()["pending_count"] == 1
    assert full.json()["inventory"]["pending"][0]["source_name"] == "a.mp4"


@pytest.mark.asyncio
async def test_watch_root_inventory_enqueue_selected_item(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.review as review_api
    from roughcut.db.models import WatchRoot
    from roughcut.db.session import get_session_factory

    async def fake_create_jobs_for_inventory_paths(
        file_paths: list[str],
        *,
        workflow_template: str | None = None,
        language: str = "zh-CN",
        output_dir: str | None = None,
        config_profile_id: uuid.UUID | None = None,
        awaiting_initialization: bool = False,
    ):
        assert file_paths == ["/tmp/videos-enqueue/a.mp4"]
        assert workflow_template == "edc_tactical"
        assert output_dir is None
        assert config_profile_id is None
        assert awaiting_initialization is False
        return [{"path": "/tmp/videos-enqueue/a.mp4", "job_id": "job-123"}]

    monkeypatch.setattr(review_api, "create_jobs_for_inventory_paths", fake_create_jobs_for_inventory_paths)

    created = await client.post(
        "/api/v1/watch-roots",
        json={"path": "/tmp/videos-enqueue", "enabled": True, "workflow_template": "edc_tactical"},
    )
    root_id = created.json()["id"]

    async with get_session_factory()() as session:
        root = await session.get(WatchRoot, uuid.UUID(root_id))
        root.inventory_cache_json = {
            "root_path": "/tmp/videos-enqueue",
            "scan_mode": "fast",
            "status": "done",
            "started_at": "2026-03-11T18:00:00",
            "updated_at": "2026-03-11T18:00:10",
            "finished_at": "2026-03-11T18:00:10",
            "total_files": 2,
            "processed_files": 2,
            "pending_count": 2,
            "deduped_count": 0,
            "current_file": None,
            "current_phase": None,
            "current_file_size_bytes": None,
            "current_file_processed_bytes": None,
            "error": None,
            "inventory": {
                "pending": [
                    {
                        "path": "/tmp/videos-enqueue/a.mp4",
                        "relative_path": "a.mp4",
                        "source_name": "a.mp4",
                        "stem": "a",
                        "size_bytes": 123,
                        "modified_at": "2026-03-11T18:00:00",
                        "duration_sec": 12.5,
                        "width": 1920,
                        "height": 1080,
                        "fps": 30.0,
                        "status": "pending",
                        "dedupe_reason": None,
                        "matched_job_id": None,
                        "matched_output_path": None,
                    },
                    {
                        "path": "/tmp/videos-enqueue/b.mp4",
                        "relative_path": "b.mp4",
                        "source_name": "b.mp4",
                        "stem": "b",
                        "size_bytes": 456,
                        "modified_at": "2026-03-11T18:00:00",
                        "duration_sec": 23.4,
                        "width": 1920,
                        "height": 1080,
                        "fps": 30.0,
                        "status": "pending",
                        "dedupe_reason": None,
                        "matched_job_id": None,
                        "matched_output_path": None,
                    },
                ],
                "deduped": [],
            },
        }
        await session.commit()

    response = await client.post(
        f"/api/v1/watch-roots/{root_id}/inventory/enqueue",
        json={"relative_paths": ["a.mp4"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["requested_count"] == 1
    assert data["created_count"] == 1
    assert data["created_job_ids"] == ["job-123"]

    inventory = await client.get(f"/api/v1/watch-roots/{root_id}/inventory/status?include_inventory=true")
    assert inventory.status_code == 200
    payload = inventory.json()["inventory"]
    assert len(payload["pending"]) == 1
    assert payload["pending"][0]["relative_path"] == "b.mp4"
    assert payload["deduped"][-1]["matched_job_id"] == "job-123"
    assert payload["deduped"][-1]["dedupe_reason"] == "job:pending"


@pytest.mark.asyncio
async def test_watch_root_inventory_enqueue_all(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.review as review_api
    from roughcut.db.models import WatchRoot
    from roughcut.db.session import get_session_factory

    async def fake_create_jobs_for_inventory_paths(
        file_paths: list[str],
        *,
        workflow_template: str | None = None,
        language: str = "zh-CN",
        output_dir: str | None = None,
        config_profile_id: uuid.UUID | None = None,
        awaiting_initialization: bool = False,
    ):
        assert file_paths == ["/tmp/videos-batch/a.mp4", "/tmp/videos-batch/b.mp4"]
        assert output_dir is None
        assert config_profile_id is None
        assert awaiting_initialization is False
        return [
            {"path": "/tmp/videos-batch/a.mp4", "job_id": "job-a"},
            {"path": "/tmp/videos-batch/b.mp4", "job_id": None},
        ]

    monkeypatch.setattr(review_api, "create_jobs_for_inventory_paths", fake_create_jobs_for_inventory_paths)

    created = await client.post(
        "/api/v1/watch-roots",
        json={"path": "/tmp/videos-batch", "enabled": True},
    )
    root_id = created.json()["id"]

    async with get_session_factory()() as session:
        root = await session.get(WatchRoot, uuid.UUID(root_id))
        root.inventory_cache_json = {
            "root_path": "/tmp/videos-batch",
            "scan_mode": "fast",
            "status": "done",
            "started_at": "2026-03-11T18:00:00",
            "updated_at": "2026-03-11T18:00:10",
            "finished_at": "2026-03-11T18:00:10",
            "total_files": 2,
            "processed_files": 2,
            "pending_count": 2,
            "deduped_count": 0,
            "current_file": None,
            "current_phase": None,
            "current_file_size_bytes": None,
            "current_file_processed_bytes": None,
            "error": None,
            "inventory": {
                "pending": [
                    {
                        "path": "/tmp/videos-batch/a.mp4",
                        "relative_path": "a.mp4",
                        "source_name": "a.mp4",
                        "stem": "a",
                        "size_bytes": 123,
                        "modified_at": "2026-03-11T18:00:00",
                        "duration_sec": None,
                        "width": None,
                        "height": None,
                        "fps": None,
                        "status": "pending",
                        "dedupe_reason": None,
                        "matched_job_id": None,
                        "matched_output_path": None,
                    },
                    {
                        "path": "/tmp/videos-batch/b.mp4",
                        "relative_path": "b.mp4",
                        "source_name": "b.mp4",
                        "stem": "b",
                        "size_bytes": 456,
                        "modified_at": "2026-03-11T18:00:00",
                        "duration_sec": None,
                        "width": None,
                        "height": None,
                        "fps": None,
                        "status": "pending",
                        "dedupe_reason": None,
                        "matched_job_id": None,
                        "matched_output_path": None,
                    },
                ],
                "deduped": [],
            },
        }
        await session.commit()

    response = await client.post(
        f"/api/v1/watch-roots/{root_id}/inventory/enqueue",
        json={"enqueue_all": True},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["requested_count"] == 2
    assert data["created_count"] == 1
    assert data["skipped_count"] == 1

    inventory = await client.get(f"/api/v1/watch-roots/{root_id}/inventory/status?include_inventory=true")
    payload = inventory.json()["inventory"]
    assert payload["pending"] == []
    assert len(payload["deduped"]) == 2


@pytest.mark.asyncio
async def test_watch_root_inventory_thumbnail(client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import roughcut.api.review as review_api

    preview = tmp_path / "preview.jpg"
    preview.write_bytes(b"fake-jpeg")

    async def fake_ensure_watch_inventory_thumbnail(watch_path: str, relative_path: str, *, width: int = 320):
        assert watch_path == "/tmp/videos-thumb"
        assert relative_path == "a.mp4"
        return preview

    monkeypatch.setattr(review_api, "ensure_watch_inventory_thumbnail", fake_ensure_watch_inventory_thumbnail)

    created = await client.post(
        "/api/v1/watch-roots",
        json={"path": "/tmp/videos-thumb", "enabled": True},
    )
    root_id = created.json()["id"]

    response = await client.get(f"/api/v1/watch-roots/{root_id}/inventory/thumbnail?relative_path=a.mp4")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/jpeg")
    assert response.content == b"fake-jpeg"


@pytest.mark.asyncio
async def test_control_stop_schedules_script(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.control as control_api

    called: dict[str, bool] = {"stop_docker": False}

    def fake_launch_stop_script(*, stop_docker: bool) -> None:
        called["stop_docker"] = stop_docker

    monkeypatch.setattr(control_api, "_launch_stop_script", fake_launch_stop_script)

    response = await client.post("/api/v1/control/stop", json={"stop_docker": True})
    assert response.status_code == 202
    assert response.json()["status"] == "scheduled"
    assert called["stop_docker"] is True


@pytest.mark.asyncio
async def test_control_status_reports_services(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.control as control_api

    monkeypatch.setattr(
        control_api,
        "_running_compose_service_names",
        lambda: {"orchestrator", "worker-media"},
    )
    monkeypatch.setattr(
        control_api,
        "_running_container_names",
        lambda: {"roughcut-postgres-1", "roughcut-redis-1"},
    )

    def fake_has_process(needle: str) -> bool:
        if "orchestrator" in needle or "media_queue" in needle or "llm_queue" in needle:
            raise AssertionError("compose-backed services must not rely on command-line matching")
        return False

    monkeypatch.setattr(control_api, "_has_process", fake_has_process)

    async def fake_readiness():
        return {
            "status": "ready",
            "checks": {
                "database": {"status": "ok", "detail": "ok"},
                "redis": {"status": "ok", "detail": "ok"},
                "storage": {"status": "ok", "detail": "ok"},
            },
        }
    async def fake_lock_snapshot():
        return {
            "status": "held",
            "leader_active": True,
            "detail": "active orchestrator leader",
        }
    monkeypatch.setattr(control_api, "build_readiness_payload", fake_readiness)
    monkeypatch.setattr(control_api, "get_orchestrator_lock_snapshot", fake_lock_snapshot)

    response = await client.get("/api/v1/control/status")
    assert response.status_code == 200
    payload = response.json()
    data = payload["services"]
    assert data["api"] is True
    assert data["telegram_agent"] is False
    assert data["orchestrator"] is True
    assert data["media_worker"] is True
    assert data["llm_worker"] is False
    assert data["postgres"] is True
    assert data["redis"] is True
    assert payload["runtime"]["readiness_status"] == "ready"
    assert payload["runtime"]["orchestrator_lock"]["status"] == "held"
    assert payload["runtime"]["orchestrator_lock"]["leader_active"] is True


@pytest.mark.asyncio
async def test_control_status_falls_back_to_runtime_probes_when_compose_is_unavailable(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.control as control_api

    monkeypatch.setattr(control_api, "_running_compose_service_names", lambda: set())
    monkeypatch.setattr(control_api, "_running_container_names", lambda: set())
    monkeypatch.setattr(control_api, "_running_celery_queues", lambda: {"media_queue", "llm_queue"})
    monkeypatch.setattr(control_api, "_has_process", lambda needle: False)

    async def fake_readiness():
        return {
            "status": "ready",
            "checks": {
                "database": {"status": "ok", "detail": "ok"},
                "redis": {"status": "ok", "detail": "ok"},
                "storage": {"status": "ok", "detail": "ok"},
            },
        }

    async def fake_lock_snapshot():
        return {
            "status": "held",
            "leader_active": True,
            "detail": "active orchestrator leader",
        }

    monkeypatch.setattr(control_api, "build_readiness_payload", fake_readiness)
    monkeypatch.setattr(control_api, "get_orchestrator_lock_snapshot", fake_lock_snapshot)

    response = await client.get("/api/v1/control/status")

    assert response.status_code == 200
    payload = response.json()
    data = payload["services"]
    assert data["orchestrator"] is True
    assert data["media_worker"] is True
    assert data["llm_worker"] is True
    assert data["postgres"] is True
    assert data["redis"] is True


@pytest.mark.asyncio
async def test_control_status_exposes_review_notification_runtime_snapshot(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.control as control_api

    monkeypatch.setattr(control_api, "_running_compose_service_names", lambda: set())
    monkeypatch.setattr(control_api, "_running_container_names", lambda: set())
    monkeypatch.setattr(control_api, "_running_celery_queues", lambda: set())
    monkeypatch.setattr(control_api, "_has_process", lambda needle: False)

    async def fake_readiness():
        return {"status": "ready", "checks": {}}

    async def fake_lock_snapshot():
        return {"status": "free", "leader_active": False}

    monkeypatch.setattr(control_api, "build_readiness_payload", fake_readiness)
    monkeypatch.setattr(control_api, "get_orchestrator_lock_snapshot", fake_lock_snapshot)
    monkeypatch.setattr(
        control_api,
        "build_review_notification_snapshot",
        lambda limit=10: {
            "state_dir": "F:/roughcut_outputs/telegram-agent",
            "store_file": "F:/roughcut_outputs/telegram-agent/review_notifications.json",
            "summary": {"total": 3, "pending": 1, "due_now": 1, "failed": 1, "delivered": 1},
            "items": [
                {
                    "notification_id": "n-1",
                    "kind": "content_profile",
                    "job_id": "job-1",
                    "status": "pending",
                    "attempt_count": 2,
                    "next_attempt_at": "2026-04-17T00:00:00+00:00",
                    "last_error": "network down",
                    "force_full_review": False,
                    "updated_at": "2026-04-17T00:00:00+00:00",
                }
            ],
        },
    )

    response = await client.get("/api/v1/control/status")

    assert response.status_code == 200
    payload = response.json()
    snapshot = payload["runtime"]["review_notifications"]
    assert snapshot["summary"]["total"] == 3
    assert snapshot["summary"]["failed"] == 1
    assert snapshot["items"][0]["notification_id"] == "n-1"


@pytest.mark.asyncio
async def test_control_status_exposes_live_readiness_runtime_snapshot(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.control as control_api

    monkeypatch.setattr(control_api, "_running_compose_service_names", lambda: set())
    monkeypatch.setattr(control_api, "_running_container_names", lambda: set())
    monkeypatch.setattr(control_api, "_running_celery_queues", lambda: set())
    monkeypatch.setattr(control_api, "_has_process", lambda needle: False)

    async def fake_readiness():
        return {"status": "ready", "checks": {}}

    async def fake_lock_snapshot():
        return {"status": "free", "leader_active": False}

    monkeypatch.setattr(control_api, "build_readiness_payload", fake_readiness)
    monkeypatch.setattr(control_api, "get_orchestrator_lock_snapshot", fake_lock_snapshot)
    monkeypatch.setattr(
        control_api,
        "load_live_readiness_snapshot",
        lambda: {
            "status": "fail",
            "gate_passed": False,
            "summary": "未满足 live dry run 准入门槛",
            "stable_run_count": 2,
            "required_stable_runs": 3,
            "failure_reasons": ["连续稳定批次不足：2/3"],
            "warning_reasons": [],
            "report_file": "E:/WorkSpace/RoughCut/output/test/fullchain-batch/batch_report.json",
            "detail": "",
        },
    )

    response = await client.get("/api/v1/control/status")

    assert response.status_code == 200
    payload = response.json()
    snapshot = payload["runtime"]["live_readiness"]
    assert snapshot["status"] == "fail"
    assert snapshot["stable_run_count"] == 2
    assert snapshot["failure_reasons"] == ["连续稳定批次不足：2/3"]


@pytest.mark.asyncio
async def test_control_status_falls_back_when_live_readiness_snapshot_fails(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.control as control_api

    monkeypatch.setattr(control_api, "_running_compose_service_names", lambda: set())
    monkeypatch.setattr(control_api, "_running_container_names", lambda: set())
    monkeypatch.setattr(control_api, "_running_celery_queues", lambda: set())
    monkeypatch.setattr(control_api, "_has_process", lambda needle: False)

    async def fake_readiness():
        return {"status": "ready", "checks": {}}

    async def fake_lock_snapshot():
        return {"status": "free", "leader_active": False}

    monkeypatch.setattr(control_api, "build_readiness_payload", fake_readiness)
    monkeypatch.setattr(control_api, "get_orchestrator_lock_snapshot", fake_lock_snapshot)

    def boom():
        raise RuntimeError("cannot read batch report")

    monkeypatch.setattr(control_api, "load_live_readiness_snapshot", boom)

    response = await client.get("/api/v1/control/status")

    assert response.status_code == 200
    payload = response.json()
    snapshot = payload["runtime"]["live_readiness"]
    assert snapshot["status"] == "unknown"
    assert snapshot["gate_passed"] is False
    assert "cannot read batch report" in snapshot["detail"]


@pytest.mark.asyncio
async def test_control_review_notification_status_filters_by_job_id(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.control as control_api

    observed: dict[str, object] = {}

    def fake_snapshot(*, statuses=None, job_id=None, kind=None, limit=20):
        observed.update({"statuses": statuses, "job_id": job_id, "kind": kind, "limit": limit})
        return {"summary": {"total": 1, "pending": 1, "due_now": 0, "failed": 0, "delivered": 0}, "items": []}

    monkeypatch.setattr(control_api, "build_review_notification_snapshot", fake_snapshot)

    response = await client.get("/api/v1/control/review-notifications", params={"job_id": "job-1", "status": "pending", "limit": 5})

    assert response.status_code == 200
    assert observed == {"statuses": ["pending"], "job_id": "job-1", "kind": "", "limit": 5}


@pytest.mark.asyncio
async def test_control_requeue_review_notification_returns_updated_record(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.control as control_api

    monkeypatch.setattr(
        control_api,
        "requeue_review_notification",
        lambda notification_id: SimpleNamespace(
            notification_id=notification_id,
            kind="content_profile",
            job_id="job-1",
            status="pending",
            attempt_count=0,
            next_attempt_at="2026-04-17T00:00:00+00:00",
            last_error="",
            force_full_review=False,
            updated_at="2026-04-17T00:00:00+00:00",
        ),
    )

    response = await client.post("/api/v1/control/review-notifications/requeue", json={"notification_id": "n-1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "requeued"
    assert payload["notification"]["notification_id"] == "n-1"


@pytest.mark.asyncio
async def test_control_drop_review_notification_returns_deleted_id(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.control as control_api

    monkeypatch.setattr(
        control_api,
        "get_review_notification_store",
        lambda: SimpleNamespace(get=lambda notification_id: {"notification_id": notification_id}),
    )
    monkeypatch.setattr(control_api, "drop_review_notification", lambda notification_id: True)

    response = await client.post("/api/v1/control/review-notifications/drop", json={"notification_id": "n-1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload == {"status": "dropped", "notification_id": "n-1"}


@pytest.mark.asyncio
async def test_control_requeue_batch_review_notifications_returns_count(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.control as control_api

    monkeypatch.setattr(
        control_api,
        "requeue_review_notifications",
        lambda notification_ids: [SimpleNamespace(notification_id=item) for item in notification_ids[:1]],
    )

    response = await client.post("/api/v1/control/review-notifications/requeue-batch", json={"notification_ids": ["n-1", "n-2"]})

    assert response.status_code == 200
    assert response.json() == {"status": "requeued", "count": 1, "notification_ids": ["n-1"]}


@pytest.mark.asyncio
async def test_control_requeue_review_notification_returns_404_when_missing(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.control as control_api

    monkeypatch.setattr(control_api, "requeue_review_notification", lambda notification_id: None)

    response = await client.post("/api/v1/control/review-notifications/requeue", json={"notification_id": "n-404"})

    assert response.status_code == 404
    assert "Review notification not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_control_review_notification_routes_reject_blank_id(client: AsyncClient):
    response = await client.post("/api/v1/control/review-notifications/requeue", json={"notification_id": "   "})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_control_requeue_review_notification_returns_503_when_store_unreadable(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.control as control_api

    monkeypatch.setattr(
        control_api,
        "requeue_review_notification",
        lambda notification_id: (_ for _ in ()).throw(RuntimeError("Review notification store is unreadable")),
    )

    response = await client.post("/api/v1/control/review-notifications/requeue", json={"notification_id": "n-1"})

    assert response.status_code == 503
    assert "Review notification store is unreadable" in response.json()["detail"]


def test_control_running_compose_service_names_handles_missing_docker(monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.control as control_api

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("docker not found")

    monkeypatch.setattr(control_api.subprocess, "run", fake_run)
    assert control_api._running_compose_service_names() == set()


def test_control_running_container_names_handles_missing_docker(monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.control as control_api

    def fake_run(*args, **kwargs):
        raise FileNotFoundError("docker not found")

    monkeypatch.setattr(control_api.subprocess, "run", fake_run)
    assert control_api._running_container_names() == set()


def test_control_has_process_handles_missing_shell(monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.control as control_api

    def fake_pick_shell():
        raise RuntimeError("shell not available")

    monkeypatch.setattr(control_api, "_pick_shell", fake_pick_shell)
    assert control_api._has_process("roughcut") is False


@pytest.mark.asyncio
async def test_job_list_includes_content_preview(client: AsyncClient):
    from roughcut.db.models import Artifact, Job
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/arc.mp4",
                source_name="arc.mp4",
                status="needs_review",
                language="zh-CN",
                workflow_template="edc_tactical",
                enhancement_modes=["avatar_commentary"],
            )
        )
        session.add_all(
            [
                Artifact(
                    job_id=job_id,
                    artifact_type="content_profile_draft",
                    data_json={
                        "subject_brand": "LEATHERMAN",
                        "subject_model": "ARC",
                        "subject_type": "多功能工具钳",
                        "video_theme": "开箱",
                        "summary": "草稿摘要",
                    },
                ),
                Artifact(
                    job_id=job_id,
                    artifact_type="content_profile_final",
                    data_json={
                        "subject_brand": "LEATHERMAN",
                        "subject_model": "ARC",
                        "subject_type": "多功能工具钳",
                        "video_theme": "开箱与上手体验",
                        "summary": "围绕 ARC 的刀具配置和实际上手手感展开。",
                    },
                ),
                Artifact(
                    job_id=job_id,
                    artifact_type="render_outputs",
                    data_json={
                        "avatar_result": {
                            "status": "done",
                            "detail": "数字人口播已作为画中画写入成片。",
                        },
                    },
                ),
                Artifact(
                    job_id=job_id,
                    artifact_type="quality_assessment",
                    data_json={
                        "score": 82.5,
                        "grade": "B",
                        "issue_codes": ["detail_blind", "generic_video_theme"],
                    },
                ),
            ]
        )
        await session.commit()

    response = await client.get("/api/v1/jobs")
    assert response.status_code == 200
    item = next(job for job in response.json() if job["id"] == str(job_id))
    assert item["content_subject"] == "LEATHERMAN ARC · 多功能工具钳 · 开箱与上手体验"
    assert item["content_summary"] == "围绕 ARC 的刀具配置和实际上手手感展开。"
    assert item["quality_score"] == 82.5
    assert item["quality_grade"] == "B"
    assert item["quality_summary"] == "B 82.5 · 2 个扣分项"
    assert item["quality_issue_codes"] == ["detail_blind", "generic_video_theme"]
    assert item["timeline_diagnostics"] is None
    assert item["avatar_delivery_status"] == "done"
    assert item["avatar_delivery_summary"] == "数字人口播已作为画中画写入成片。"


@pytest.mark.asyncio
async def test_jobs_list_quality_preview_falls_back_to_subtitle_stage_reports(client: AsyncClient):
    from roughcut.db.models import Artifact, Job
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/subtitle-preview.mp4",
                source_name="subtitle-preview.mp4",
                status="done",
                language="zh-CN",
            )
        )
        session.add_all(
            [
                Artifact(
                    job_id=job_id,
                    artifact_type="content_profile_final",
                    data_json={
                        "subject_brand": "Loop露普",
                        "subject_model": "SK05二代UV版",
                        "subject_type": "EDC手电",
                        "video_theme": "SK05二代UV版与一代亮度续航对比",
                        "summary": "围绕 Loop露普 SK05二代UV版 和一代做亮度、续航与 UV 功能差异对比。",
                        "engagement_question": "你更在意二代的 UV 功能还是亮度升级？",
                        "review_mode": "auto_confirmed",
                        "automation_review": {"score": 0.95},
                    },
                ),
                Artifact(
                    job_id=job_id,
                    artifact_type="subtitle_term_resolution_patch",
                    data_json={
                        "metrics": {
                            "patch_count": 3,
                            "pending_count": 2,
                            "auto_applied_count": 1,
                        }
                    },
                ),
                Artifact(
                    job_id=job_id,
                    artifact_type="subtitle_consistency_report",
                    data_json={
                        "score": 87.0,
                        "blocking": False,
                        "blocking_reasons": [],
                        "warning_reasons": ["已应用词级纠偏 1 处"],
                    },
                ),
            ]
        )
        await session.commit()

    response = await client.get("/api/v1/jobs")
    assert response.status_code == 200
    item = next(job for job in response.json() if job["id"] == str(job_id))
    assert item["quality_score"] == 87.0
    assert item["quality_grade"] == "B"
    assert item["quality_summary"] == "术语解析 3 条 · 一致性审校 87.0"
    assert item["quality_issue_codes"] == ["术语解析待确认 2 条", "已应用词级纠偏 1 处"]


@pytest.mark.asyncio
async def test_job_restart_allows_done_jobs(client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import roughcut.api.jobs as jobs_api
    from roughcut.db.models import Artifact, Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(jobs_api.tempfile, "gettempdir", lambda: str(tmp_path))

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/restart.mp4",
                source_name="restart.mp4",
                status="done",
                language="zh-CN",
                file_hash="hash-demo",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="render",
                status="done",
                attempt=1,
                started_at=now,
                finished_at=now,
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="platform_packaging_md",
                data_json={"title": "demo"},
            )
        )
        await session.commit()

    cached_dir = tmp_path / "roughcut_content_profile_frames" / "v2" / str(job_id)
    cached_dir.mkdir(parents=True, exist_ok=True)
    cached_thumb = cached_dir / "profile_00.jpg"
    cached_thumb.write_bytes(b"stale-black-thumb")

    response = await client.post(f"/api/v1/jobs/{job_id}/restart")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["file_hash"] is None
    assert data["steps"][0]["status"] == "pending"
    assert data["steps"][0]["attempt"] == 0
    assert not cached_thumb.exists()

    activity = await client.get(f"/api/v1/jobs/{job_id}/activity")
    assert activity.status_code == 200
    activity_data = activity.json()
    assert activity_data["current_step"]["step_name"] == "probe"
    assert activity_data["current_step"]["detail"] == "任务已重新开始，等待调度器派发。"


@pytest.mark.asyncio
async def test_job_restart_allows_needs_review_jobs(client: AsyncClient):
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/review.mp4",
                source_name="review.mp4",
                status="needs_review",
                language="zh-CN",
                enhancement_modes=["avatar_commentary"],
            )
        )
        session.add_all(
            [
                JobStep(job_id=job_id, step_name="probe", status="done", attempt=1),
                JobStep(job_id=job_id, step_name="extract_audio", status="done", attempt=1),
                JobStep(job_id=job_id, step_name="summary_review", status="pending"),
            ]
        )
        await session.commit()

    response = await client.post(f"/api/v1/jobs/{job_id}/restart")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["steps"][0]["step_name"] == "probe"
    assert data["steps"][0]["status"] == "pending"
    assert all(step["attempt"] == 0 for step in data["steps"])


@pytest.mark.asyncio
async def test_job_restart_allows_processing_jobs(client: AsyncClient):
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/processing.mp4",
                source_name="processing.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="probe",
                status="running",
                attempt=1,
            )
        )
        await session.commit()

    response = await client.post(f"/api/v1/jobs/{job_id}/restart")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["steps"][0]["step_name"] == "probe"
    assert data["steps"][0]["status"] == "pending"
    assert data["steps"][0]["attempt"] == 0


@pytest.mark.asyncio
async def test_job_initialize_starts_awaiting_init_job(client: AsyncClient):
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/task-only.mp4",
                source_name="task-only.mp4",
                status="awaiting_init",
                language="zh-CN",
                workflow_mode="standard_edit",
                enhancement_modes=[],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="probe", status="pending"))
        session.add(
            JobStep(
                job_id=job_id,
                step_name="content_profile",
                status="pending",
                metadata_={"source_context": {"merged_source_names": ["task-only.mp4"]}},
            )
        )
        await session.commit()

    response = await client.post(
        f"/api/v1/jobs/{job_id}/initialize",
        json={
            "language": "zh-CN",
            "workflow_template": "edc_tactical",
            "workflow_mode": "standard_edit",
            "enhancement_modes": ["auto_review"],
            "output_dir": "/tmp/output-init",
            "video_description": "这是一期工具开箱，重点保留近景细节和开合手感。",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["awaiting_initialization"] is False
    assert data["video_description"] == "这是一期工具开箱，重点保留近景细节和开合手感。"
    assert data["workflow_template"] == "edc_tactical"
    assert data["enhancement_modes"] == ["auto_review"]

    activity = await client.get(f"/api/v1/jobs/{job_id}/activity")
    assert activity.status_code == 200
    activity_data = activity.json()
    assert activity_data["current_step"]["step_name"] == "probe"
    assert activity_data["current_step"]["detail"] == "任务已初始化，等待调度器派发。"


@pytest.mark.asyncio
async def test_get_job_exposes_standardized_review_context(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/final-review-card.mp4",
                source_name="final-review-card.mp4",
                status="needs_review",
                language="zh-CN",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="done"))
        session.add(JobStep(job_id=job_id, step_name="final_review", status="pending"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="quality_assessment",
                data_json={"score": 91.2, "grade": "A", "issue_codes": []},
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()

    assert data["review_step"] == "final_review"
    assert data["review_label"] == "成片审核"
    assert data["review_detail"] == "等待审核成片后继续生成平台文案。"


@pytest.mark.asyncio
async def test_get_job_prefers_subtitle_review_context_when_manual_review_is_required(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/subtitle-manual-review.mp4",
                source_name="subtitle-manual-review.mp4",
                status="needs_review",
                language="zh-CN",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="done"))
        session.add(JobStep(job_id=job_id, step_name="final_review", status="done"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="subtitle_quality_report",
                data_json={
                    "score": 52.0,
                    "blocking": True,
                    "blocking_reasons": ["检测到语义污染 4 处，必须人工确认"],
                    "warning_reasons": [],
                    "metrics": {
                        "semantic_bad_term_total": 4,
                        "lexical_bad_term_total": 1,
                    },
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="quality_assessment",
                data_json={
                    "score": 52.0,
                    "grade": "D",
                    "issue_codes": ["subtitle_semantic_contamination"],
                    "manual_review_required": True,
                },
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()

    assert data["review_step"] == "summary_review"
    assert data["review_label"] == "字幕复核"
    assert "仅允许词级纠偏" in data["review_detail"]


@pytest.mark.asyncio
async def test_job_activity_sorts_pending_steps_and_hides_avatar_until_reached(client: AsyncClient):
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/pending.mp4",
                source_name="pending.mp4",
                status="pending",
                language="zh-CN",
                enhancement_modes=["avatar_commentary"],
            )
        )
        session.add_all(
            [
                JobStep(job_id=job_id, step_name="avatar_commentary", status="pending"),
                JobStep(job_id=job_id, step_name="extract_audio", status="pending"),
                JobStep(job_id=job_id, step_name="probe", status="pending"),
                JobStep(job_id=job_id, step_name="transcribe", status="pending"),
            ]
        )
        await session.commit()

    activity = await client.get(f"/api/v1/jobs/{job_id}/activity")
    assert activity.status_code == 200
    activity_data = activity.json()
    assert activity_data["current_step"]["step_name"] == "probe"
    assert activity_data["current_step"]["detail"] == "等待调度器派发。"

    jobs_response = await client.get("/api/v1/jobs")
    assert jobs_response.status_code == 200
    item = next(job for job in jobs_response.json() if job["id"] == str(job_id))
    assert item["avatar_delivery_status"] is None
    assert item["avatar_delivery_summary"] is None


@pytest.mark.asyncio
async def test_open_job_folder_prefers_render_output(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    import roughcut.api.jobs as jobs_api
    from roughcut.db.models import Job, RenderOutput
    from roughcut.db.session import get_session_factory

    opened: dict[str, str] = {}
    monkeypatch.setattr(jobs_api, "_open_in_file_manager", lambda path: opened.setdefault("path", str(path)))

    output_path = tmp_path / "exports" / "demo.mp4"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(b"demo")
    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="done",
                language="zh-CN",
            )
        )
        session.add(RenderOutput(job_id=job_id, status="done", progress=1.0, output_path=str(output_path)))
        await session.commit()

    response = await client.post(f"/api/v1/jobs/{job_id}/open-folder")
    assert response.status_code == 200
    assert response.json()["kind"] == "output"
    assert response.json()["path"] == str(output_path)
    assert opened["path"] == str(output_path)


@pytest.mark.asyncio
async def test_content_profile_memory_stats_endpoint(client: AsyncClient):
    from roughcut.db.models import ContentProfileCorrection, ContentProfileKeywordStat
    from roughcut.db.session import get_session_factory

    async with get_session_factory()() as session:
        session.add_all(
            [
                ContentProfileCorrection(
                    job_id=uuid.uuid4(),
                    source_name="a.mp4",
                    subject_domain="edc",
                    field_name="subject_brand",
                    original_value="",
                    corrected_value="LEATHERMAN",
                ),
                ContentProfileCorrection(
                    job_id=uuid.uuid4(),
                    source_name="b.mp4",
                    subject_domain="edc",
                    field_name="subject_model",
                    original_value="",
                    corrected_value="ARC",
                ),
                ContentProfileKeywordStat(scope_type="global", scope_value="", keyword="LEATHERMAN ARC", usage_count=2),
                ContentProfileKeywordStat(scope_type="subject_domain", scope_value="edc", keyword="多功能工具钳", usage_count=3),
            ]
        )
        await session.commit()

    response = await client.get("/api/v1/jobs/stats/content-profile-memory?subject_domain=edc")
    assert response.status_code == 200
    data = response.json()
    assert data["scope"] == "subject_domain"
    assert data["subject_domain"] == "edc"
    assert "edc" in data["subject_domains"]
    assert data["total_corrections"] >= 2
    assert data["total_keywords"] >= 3
    assert data["field_preferences"]["subject_brand"][0]["value"] == "LEATHERMAN"
    assert any(item["keyword"] == "多功能工具钳" for item in data["keyword_preferences"])


@pytest.mark.asyncio
async def test_job_activity_stream(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, JobStep, RenderOutput, SubtitleCorrection, Timeline
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    async with get_session_factory()() as session:
        job = Job(
            id=job_id,
            source_path="jobs/demo/source.mp4",
            source_name="demo.mp4",
            status="processing",
            language="zh-CN",
        )
        session.add(job)
        session.add_all(
            [
                JobStep(
                    job_id=job_id,
                    step_name="probe",
                    status="done",
                    started_at=now,
                    finished_at=now,
                    metadata_={"detail": "已写入媒体信息", "progress": 1.0, "updated_at": now.isoformat()},
                ),
                JobStep(
                    job_id=job_id,
                    step_name="render",
                    status="running",
                    started_at=now,
                    metadata_={"detail": "执行 FFmpeg 渲染成片", "progress": 0.35, "updated_at": now.isoformat()},
                ),
            ]
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile",
                data_json={
                    "subject_type": "录屏教学",
                    "video_theme": "软件流程演示与步骤讲解",
                    "workflow_template": "tutorial_standard",
                    "summary": "主要展示完整操作流程。",
                },
            )
        )
        session.add(
            Timeline(
                job_id=job_id,
                timeline_type="editorial",
                data_json={
                    "segments": [
                        {"start": 0.0, "end": 10.0, "type": "keep"},
                        {"start": 10.0, "end": 12.0, "type": "remove", "reason": "silence"},
                        {"start": 20.0, "end": 21.5, "type": "remove", "reason": "filler_word"},
                    ]
                },
            )
        )
        session.add(RenderOutput(job_id=job_id, status="running", progress=0.35))
        session.add(
            SubtitleCorrection(
                job_id=job_id,
                subtitle_item_id=None,
                original_span="剪映",
                suggested_span="Premiere Pro",
                change_type="brand",
                confidence=0.92,
                source="glossary",
                auto_applied=False,
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}/activity")
    assert response.status_code == 200
    data = response.json()
    assert data["current_step"]["step_name"] == "render"
    assert data["current_step"]["detail"].startswith("执行 FFmpeg 渲染成片")
    subtitle_decision = next(item for item in data["decisions"] if item["kind"] == "subtitle_review")
    assert subtitle_decision["detail"] == "待审 1 条，词级自动/已接受 0 条"


@pytest.mark.asyncio
async def test_job_activity_failed_job_exposes_error_and_stuck_diagnostic(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, JobStep
    from roughcut.db.session import get_session_factory
    from roughcut.recovery.stuck_step_recovery import STUCK_STEP_DIAGNOSTIC_ARTIFACT_TYPE

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/fail.mp4",
                source_name="fail.mp4",
                status="failed",
                language="zh-CN",
                error_message="render 步骤卡住并已超过重试上限",
            )
        )
        session.add_all(
            [
                JobStep(
                    job_id=job_id,
                    step_name="probe",
                    status="done",
                    attempt=1,
                    started_at=now,
                    finished_at=now,
                    metadata_={"detail": "已写入媒体信息", "updated_at": now.isoformat()},
                ),
                JobStep(
                    job_id=job_id,
                    step_name="render",
                    status="failed",
                    attempt=3,
                    started_at=now,
                    finished_at=now,
                    error_message="FFmpeg 渲染执行失败，返回码 1",
                    metadata_={"detail": "渲染容器返回失败状态", "updated_at": now.isoformat(), "recovery_summary": "已写入卡住诊断"},
                ),
            ]
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type=STUCK_STEP_DIAGNOSTIC_ARTIFACT_TYPE,
                data_json={
                    "step_name": "render",
                    "summary": "render step appears stuck",
                    "root_cause": "GPU 输出队列长期无响应",
                    "confidence": 0.84,
                    "recommended_action": {
                        "kind": "reset_to_pending",
                        "reason": "清理旧任务状态并重新入队",
                    },
                    "evidence": {
                        "stale_after_sec": 1200,
                        "attempt": 3,
                    },
                },
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}/activity")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert data["current_step"]["step_name"] == "render"
    assert "FFmpeg 渲染执行失败" in (data["current_step"]["detail"] or "")
    assert any(
        event["type"] == "error" and "render 步骤卡住" in (event["detail"] or "")
        for event in data["events"]
    )
    assert any("卡住诊断" in event["title"] and "GPU 输出队列长期无响应" in (event["detail"] or "") for event in data["events"])


@pytest.mark.asyncio
async def test_apply_review_persists_glossary_terms_by_domain_not_workflow_template(client: AsyncClient):
    from sqlalchemy import select

    from roughcut.db.models import Artifact, GlossaryTerm, Job, SubtitleCorrection
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    correction_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/ai.mp4",
                source_name="ai.mp4",
                status="needs_review",
                language="zh-CN",
                workflow_template="tutorial_standard",
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile",
                data_json={
                    "video_theme": "AI 工作流演示",
                    "summary": "主要介绍节点编排、工作流和模型推理。",
                    "subject_domain": "ai",
                },
            )
        )
        session.add(
            SubtitleCorrection(
                id=correction_id,
                job_id=job_id,
                subtitle_item_id=None,
                original_span="康飞UI",
                suggested_span="ComfyUI",
                change_type="brand",
                confidence=0.94,
                source="glossary",
                auto_applied=False,
            )
        )
        await session.commit()

    response = await client.post(
        f"/api/v1/jobs/{job_id}/review/apply",
        json={
            "actions": [
                {
                    "target_type": "subtitle_correction",
                    "target_id": str(correction_id),
                    "action": "accepted",
                }
            ]
        },
    )
    assert response.status_code == 200

    async with get_session_factory()() as session:
        result = await session.execute(select(GlossaryTerm).where(GlossaryTerm.correct_form == "ComfyUI"))
        terms = result.scalars().all()

    assert any(item.scope_type == "domain" and item.scope_value == "ai" for item in terms)
    assert all(item.scope_type != "workflow_template" for item in terms)


@pytest.mark.asyncio
async def test_job_token_usage_endpoint_returns_aggregated_report(client: AsyncClient):
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="demo.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        session.add_all(
            [
                JobStep(
                    job_id=job_id,
                    step_name="content_profile",
                    status="done",
                    metadata_={
                        "cache": {
                            "content_profile": {
                                "namespace": "content_profile.infer",
                                "key": "cache-key-1",
                                "hit": True,
                            }
                        },
                        "llm_usage": {
                            "calls": 2,
                            "prompt_tokens": 1200,
                            "completion_tokens": 320,
                            "total_tokens": 1520,
                            "by_operation": {
                                "content_profile.visual_transcript_fuse": {
                                    "calls": 1,
                                    "prompt_tokens": 700,
                                    "completion_tokens": 180,
                                    "total_tokens": 880,
                                },
                                "content_profile.text_refine": {
                                    "calls": 1,
                                    "prompt_tokens": 500,
                                    "completion_tokens": 140,
                                    "total_tokens": 640,
                                },
                            },
                            "by_model": {
                                "MiniMax-M2.7-highspeed": {
                                    "provider": "minimax",
                                    "kind": "reasoning",
                                    "calls": 2,
                                    "prompt_tokens": 1200,
                                    "completion_tokens": 320,
                                    "total_tokens": 1520,
                                }
                            },
                        }
                    },
                ),
                JobStep(
                    job_id=job_id,
                    step_name="platform_package",
                    status="running",
                    metadata_={
                        "llm_usage": {
                            "calls": 1,
                            "prompt_tokens": 860,
                            "completion_tokens": 240,
                            "total_tokens": 1100,
                            "by_operation": {
                                "platform_package.generate_packaging": {
                                    "calls": 1,
                                    "prompt_tokens": 860,
                                    "completion_tokens": 240,
                                    "total_tokens": 1100,
                                }
                            },
                            "by_model": {
                                "MiniMax-M2.7-highspeed": {
                                    "provider": "minimax",
                                    "kind": "reasoning",
                                    "calls": 1,
                                    "prompt_tokens": 860,
                                    "completion_tokens": 240,
                                    "total_tokens": 1100,
                                }
                            },
                        }
                    },
                ),
            ]
        )
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}/token-usage")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == str(job_id)
    assert data["has_telemetry"] is True
    assert data["total_calls"] == 3
    assert data["total_prompt_tokens"] == 2060
    assert data["total_completion_tokens"] == 560
    assert data["total_tokens"] == 2620
    assert data["cache"]["hits"] == 1
    assert data["cache"]["avoided_calls"] == 1
    assert data["steps"][0]["step_name"] == "content_profile"
    assert data["steps"][0]["cache_entries"][0]["name"] == "content_profile"
    assert data["steps"][0]["operations"][0]["operation"] == "content_profile.visual_transcript_fuse"
    assert data["models"][0]["model"] == "MiniMax-M2.7-highspeed"


@pytest.mark.asyncio
async def test_jobs_usage_summary_endpoint_rolls_up_cache_and_tokens(client: AsyncClient):
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    async with get_session_factory()() as session:
        first_job_id = uuid.uuid4()
        second_job_id = uuid.uuid4()
        session.add_all(
            [
                Job(
                    id=first_job_id,
                    source_path="jobs/demo/one.mp4",
                    source_name="one.mp4",
                    status="done",
                    language="zh-CN",
                ),
                Job(
                    id=second_job_id,
                    source_path="jobs/demo/two.mp4",
                    source_name="two.mp4",
                    status="done",
                    language="zh-CN",
                ),
                JobStep(
                    job_id=first_job_id,
                    step_name="content_profile",
                    status="done",
                    metadata_={
                        "cache": {
                            "content_profile": {
                                "namespace": "content_profile.infer",
                                "key": "k1",
                                "hit": True,
                                "usage_baseline": {
                                    "calls": 2,
                                    "prompt_tokens": 1000,
                                    "completion_tokens": 300,
                                    "total_tokens": 1300,
                                },
                            }
                        },
                        "llm_usage": {
                            "calls": 2,
                            "prompt_tokens": 1000,
                            "completion_tokens": 300,
                            "total_tokens": 1300,
                            "by_model": {
                                "MiniMax-M2.7-highspeed": {
                                    "provider": "minimax",
                                    "kind": "reasoning",
                                    "calls": 2,
                                    "prompt_tokens": 1000,
                                    "completion_tokens": 300,
                                    "total_tokens": 1300,
                                }
                            },
                        },
                    },
                ),
                JobStep(
                    job_id=second_job_id,
                    step_name="platform_package",
                    status="done",
                    metadata_={
                        "cache": {"platform_packaging": {"namespace": "platform_package.generate", "key": "k2", "hit": False}},
                        "llm_usage": {
                            "calls": 1,
                            "prompt_tokens": 800,
                            "completion_tokens": 200,
                            "total_tokens": 1000,
                            "by_model": {
                                "gpt-4.1-mini": {
                                    "provider": "openai",
                                    "kind": "reasoning",
                                    "calls": 1,
                                    "prompt_tokens": 800,
                                    "completion_tokens": 200,
                                    "total_tokens": 1000,
                                }
                            },
                        },
                    },
                ),
            ]
        )
        await session.commit()

    response = await client.get("/api/v1/jobs/usage-summary")
    assert response.status_code == 200
    data = response.json()
    assert data["job_count"] >= 2
    assert data["jobs_with_telemetry"] >= 2
    assert data["total_calls"] >= 3
    assert data["total_tokens"] >= 2300
    assert data["cache"]["hits"] >= 1
    assert data["cache"]["misses"] >= 1
    assert data["cache"]["saved_total_tokens"] >= 1300
    assert any(item["step_name"] == "content_profile" for item in data["top_steps"])
    assert any(item["model"] == "MiniMax-M2.7-highspeed" for item in data["top_models"])
    assert any(item["provider"] == "minimax" for item in data["top_providers"])


@pytest.mark.asyncio
async def test_jobs_usage_trend_endpoint_returns_daily_points(client: AsyncClient):
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    now = datetime.now(timezone.utc).replace(hour=10, minute=0, second=0, microsecond=0)

    async with get_session_factory()() as session:
        first_job_id = uuid.uuid4()
        second_job_id = uuid.uuid4()
        session.add_all(
            [
                    Job(
                        id=first_job_id,
                        source_path="jobs/demo/one.mp4",
                        source_name="one.mp4",
                        status="done",
                        language="zh-CN",
                        updated_at=now - timedelta(days=1),
                    ),
                    Job(
                        id=second_job_id,
                        source_path="jobs/demo/two.mp4",
                        source_name="two.mp4",
                        status="done",
                        language="zh-CN",
                        updated_at=now,
                    ),
                JobStep(
                    job_id=first_job_id,
                    step_name="content_profile",
                    status="done",
                    metadata_={
                        "cache": {
                            "content_profile": {
                                "namespace": "content_profile.infer",
                                "key": "k1",
                                "hit": True,
                                "usage_baseline": {
                                    "calls": 2,
                                    "prompt_tokens": 1000,
                                    "completion_tokens": 300,
                                    "total_tokens": 1300,
                                },
                            }
                        },
                        "llm_usage": {
                            "calls": 2,
                            "prompt_tokens": 1000,
                            "completion_tokens": 300,
                            "total_tokens": 1300,
                            "by_model": {
                                "MiniMax-M2.7-highspeed": {
                                    "provider": "minimax",
                                    "kind": "reasoning",
                                    "calls": 2,
                                    "prompt_tokens": 1000,
                                    "completion_tokens": 300,
                                    "total_tokens": 1300,
                                }
                            },
                        }
                    },
                ),
                JobStep(
                    job_id=second_job_id,
                    step_name="platform_package",
                    status="done",
                    metadata_={
                        "llm_usage": {
                            "calls": 1,
                            "prompt_tokens": 800,
                            "completion_tokens": 200,
                            "total_tokens": 1000,
                            "by_model": {
                                "gpt-4.1-mini": {
                                    "provider": "openai",
                                    "kind": "reasoning",
                                    "calls": 1,
                                    "prompt_tokens": 800,
                                    "completion_tokens": 200,
                                    "total_tokens": 1000,
                                }
                            },
                        }
                    },
                ),
            ]
        )
        await session.commit()

    response = await client.get("/api/v1/jobs/usage-trend?days=2&limit=500")
    assert response.status_code == 200
    data = response.json()
    assert data["days"] == 2
    assert len(data["points"]) == 2
    assert data["points"][0]["date"] <= data["points"][1]["date"]
    assert any(point["total_tokens"] >= 1000 for point in data["points"])
    assert any(point["cache"]["saved_total_tokens"] >= 1300 for point in data["points"])
    assert any(point.get("top_entry", {}).get("dimension") == "step" for point in data["points"] if point["total_tokens"])


@pytest.mark.asyncio
async def test_jobs_usage_trend_endpoint_passes_step_name_filter(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.jobs as jobs_api
    from roughcut.db.models import Job
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    captured: dict[str, object] = {}

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/filter.mp4",
                source_name="filter.mp4",
                status="done",
                language="zh-CN",
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    def fake_build_jobs_usage_trend(jobs, *, days, step_labels, focus_type=None, focus_name=None, step_name=None, now=None):
        captured["days"] = days
        captured["focus_type"] = focus_type
        captured["focus_name"] = focus_name
        captured["step_name"] = step_name
        return {
            "days": days,
            "focus_type": focus_type,
            "focus_name": focus_name,
            "points": [
                {
                    "date": "2026-03-22",
                    "label": "03-22",
                    "job_count": len(jobs),
                    "jobs_with_telemetry": 1,
                    "total_calls": 1,
                    "total_prompt_tokens": 800,
                    "total_completion_tokens": 200,
                    "total_tokens": 1000,
                    "cache": {
                        "total_entries": 1,
                        "hits": 0,
                        "misses": 1,
                        "hit_rate": 0.0,
                        "avoided_calls": 0,
                        "steps_with_hits": 0,
                    },
                    "top_entry": {"dimension": "step", "name": "platform_package", "label": "平台文案", "total_tokens": 1000},
                    "top_step": {"step_name": "platform_package", "label": "平台文案", "total_tokens": 1000},
                }
            ],
        }

    monkeypatch.setattr(jobs_api, "build_jobs_usage_trend", fake_build_jobs_usage_trend)

    response = await client.get("/api/v1/jobs/usage-trend?days=1&limit=1&step_name=platform_package")
    assert response.status_code == 200
    data = response.json()
    assert captured["days"] == 1
    assert captured["step_name"] == "platform_package"
    assert data["points"][0]["total_tokens"] == 1000
    assert data["points"][0]["top_step"]["step_name"] == "platform_package"


@pytest.mark.asyncio
async def test_jobs_usage_trend_endpoint_passes_model_focus(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.jobs as jobs_api
    from roughcut.db.models import Job
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    captured: dict[str, object] = {}

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/filter-model.mp4",
                source_name="filter-model.mp4",
                status="done",
                language="zh-CN",
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    def fake_build_jobs_usage_trend(jobs, *, days, step_labels, focus_type=None, focus_name=None, step_name=None, now=None):
        captured["days"] = days
        captured["focus_type"] = focus_type
        captured["focus_name"] = focus_name
        return {
            "days": days,
            "focus_type": focus_type,
            "focus_name": focus_name,
            "points": [
                {
                    "date": "2026-03-22",
                    "label": "03-22",
                    "job_count": len(jobs),
                    "jobs_with_telemetry": 1,
                    "total_calls": 2,
                    "total_prompt_tokens": 1000,
                    "total_completion_tokens": 300,
                    "total_tokens": 1300,
                    "cache": {
                        "total_entries": 0,
                        "hits": 0,
                        "misses": 0,
                        "hit_rate": 0.0,
                        "avoided_calls": 0,
                        "steps_with_hits": 0,
                    },
                    "top_entry": {
                        "dimension": "model",
                        "name": "MiniMax-M2.7-highspeed",
                        "label": "MiniMax-M2.7-highspeed",
                        "total_tokens": 1300,
                    },
                    "top_step": None,
                }
            ],
        }

    monkeypatch.setattr(jobs_api, "build_jobs_usage_trend", fake_build_jobs_usage_trend)

    response = await client.get("/api/v1/jobs/usage-trend?days=1&limit=1&focus_type=model&focus_name=MiniMax-M2.7-highspeed")
    assert response.status_code == 200
    data = response.json()
    assert captured["focus_type"] == "model"
    assert captured["focus_name"] == "MiniMax-M2.7-highspeed"
    assert data["focus_type"] == "model"
    assert data["points"][0]["top_entry"]["dimension"] == "model"


@pytest.mark.asyncio
async def test_job_activity_reports_avatar_final_delivery_result(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, RenderOutput
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/avatar.mp4",
                source_name="avatar.mp4",
                status="done",
                language="zh-CN",
                enhancement_modes=["avatar_commentary"],
            )
        )
        session.add_all(
            [
                Artifact(
                    job_id=job_id,
                    artifact_type="avatar_commentary_plan",
                    data_json={
                        "mode": "full_track_audio_passthrough",
                        "provider": "heygem",
                        "layout_template": "picture_in_picture_right",
                    },
                ),
                Artifact(
                    job_id=job_id,
                    artifact_type="render_outputs",
                    data_json={
                        "packaged_mp4": "output/avatar.mp4",
                        "avatar_result": {
                            "status": "done",
                            "detail": "数字人口播已作为画中画写入成片。",
                            "profile_name": "店播数字人A",
                        },
                    },
                ),
            ]
        )
        session.add(RenderOutput(job_id=job_id, status="done", progress=1.0, output_path="output/avatar.mp4"))
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}/activity")
    assert response.status_code == 200
    data = response.json()
    avatar_decision = next(item for item in data["decisions"] if item["kind"] == "avatar_commentary")
    assert avatar_decision["status"] == "done"
    assert avatar_decision["summary"] == "数字人口播已合成进成片"
    assert "画中画写入成片" in avatar_decision["detail"]
    assert any(event["title"] == "数字人成片结果已回写" for event in data["events"])


@pytest.mark.asyncio
async def test_job_activity_reports_quality_assessment_decision(client: AsyncClient):
    from roughcut.db.models import Artifact, Job
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/quality.mp4",
                source_name="quality.mp4",
                status="done",
                language="zh-CN",
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="quality_assessment",
                data_json={
                    "score": 64.0,
                    "grade": "C",
                    "issue_codes": ["detail_blind", "subtitle_sync_issue"],
                    "recommended_rerun_steps": ["content_profile", "render", "platform_package"],
                },
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}/activity")
    assert response.status_code == 200
    data = response.json()
    quality_decision = next(item for item in data["decisions"] if item["kind"] == "quality_assessment")
    quality_event = next(item for item in data["events"] if item["title"] == "质量评分已更新")
    assert quality_decision["step_name"] == "final_review"
    assert quality_decision["summary"] == "C 64.0 · 2 个扣分项"
    assert "detail_blind" in quality_decision["detail"]
    assert "content_profile" in quality_decision["detail"]
    assert quality_event["step_name"] == "final_review"


@pytest.mark.asyncio
async def test_job_activity_reports_quality_assessment_manual_review_requirement(client: AsyncClient):
    from roughcut.db.models import Artifact, Job
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/quality-manual-review.mp4",
                source_name="quality-manual-review.mp4",
                status="needs_review",
                language="zh-CN",
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="quality_assessment",
                data_json={
                    "score": 52.0,
                    "grade": "D",
                    "issue_codes": ["subtitle_semantic_contamination"],
                    "recommended_rerun_steps": [],
                    "manual_review_required": True,
                },
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}/activity")
    assert response.status_code == 200
    data = response.json()
    quality_decision = next(item for item in data["decisions"] if item["kind"] == "quality_assessment")
    assert quality_decision["summary"] == "D 52.0 · 1 个扣分项 · 人工复核"
    assert "subtitle_semantic_contamination" in quality_decision["detail"]
    assert "必须人工复核" in quality_decision["detail"]
    assert "建议补跑" not in quality_decision["detail"]


@pytest.mark.asyncio
async def test_job_activity_reports_subtitle_stage_decisions_and_events(client: AsyncClient):
    from roughcut.db.models import Artifact, Job
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/subtitle-activity.mp4",
                source_name="subtitle-activity.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        session.add_all(
            [
                Artifact(
                    job_id=job_id,
                    artifact_type="subtitle_quality_report",
                    data_json={
                        "score": 61.5,
                        "blocking": True,
                        "blocking_reasons": ["热词/型号错词残留 2 处"],
                        "warning_reasons": ["独立语气词偏多 1.2%"],
                        "metrics": {"identity_missing": False},
                    },
                ),
                Artifact(
                    job_id=job_id,
                    artifact_type="subtitle_term_resolution_patch",
                    data_json={
                        "metrics": {
                            "patch_count": 3,
                            "pending_count": 2,
                            "auto_applied_count": 1,
                        }
                    },
                ),
                Artifact(
                    job_id=job_id,
                    artifact_type="subtitle_consistency_report",
                    data_json={
                        "score": 87.0,
                        "blocking": False,
                        "blocking_reasons": [],
                        "warning_reasons": ["字幕术语已自动纠偏 1 处"],
                    },
                ),
            ]
        )
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}/activity")
    assert response.status_code == 200
    data = response.json()

    decision_kinds = [item["kind"] for item in data["decisions"]]
    assert "subtitle_quality" in decision_kinds
    assert "subtitle_term_resolution" in decision_kinds
    assert "subtitle_consistency_review" in decision_kinds

    subtitle_quality_decision = next(item for item in data["decisions"] if item["kind"] == "subtitle_quality")
    assert subtitle_quality_decision["status"] == "needs_review"
    assert subtitle_quality_decision["summary"] == "字幕质检 61.5 分"
    assert subtitle_quality_decision["detail"] == "热词/型号错词残留 2 处"
    assert subtitle_quality_decision["review_route"] == "subtitle_review"
    assert subtitle_quality_decision["review_label"] == "字幕质量复核"
    assert subtitle_quality_decision["recommended_action"].startswith("先处理字幕质量阻断")
    assert subtitle_quality_decision["rerun_start_step"] == "subtitle_postprocess"
    assert subtitle_quality_decision["rerun_steps"][0] == "subtitle_postprocess"
    assert subtitle_quality_decision["issue_codes"] == ["subtitle_quality_blocking"]

    subtitle_term_resolution_decision = next(
        item for item in data["decisions"] if item["kind"] == "subtitle_term_resolution"
    )
    assert subtitle_term_resolution_decision["review_route"] == "subtitle_review"
    assert subtitle_term_resolution_decision["review_label"] == "术语候选确认"
    assert subtitle_term_resolution_decision["rerun_start_step"] == "subtitle_term_resolution"
    assert subtitle_term_resolution_decision["issue_codes"] == ["subtitle_terms_pending"]

    subtitle_consistency_decision = next(
        item for item in data["decisions"] if item["kind"] == "subtitle_consistency_review"
    )
    assert subtitle_consistency_decision["review_route"] is None
    assert subtitle_consistency_decision["review_label"] == "一致性提示"
    assert subtitle_consistency_decision["rerun_start_step"] == "subtitle_consistency_review"
    assert subtitle_consistency_decision["issue_codes"] == ["subtitle_consistency_warning"]

    assert any(event["title"] == "字幕阶段验收已生成" for event in data["events"])
    assert any(event["title"] == "字幕术语解析已生成" for event in data["events"])
    assert any(event["title"] == "字幕一致性审校已生成" for event in data["events"])


@pytest.mark.asyncio
async def test_job_activity_reports_quality_rerun_event_with_source_and_reason(client: AsyncClient):
    from roughcut.db.models import Artifact, Job
    from roughcut.db.session import get_session_factory
    from roughcut.pipeline.orchestrator import create_job_steps

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/rerun-activity.mp4",
                source_name="rerun-activity.mp4",
                status="done",
                language="zh-CN",
            )
        )
        for step in create_job_steps(job_id):
            step.status = "done"
            session.add(step)
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="quality_assessment",
                data_json={
                    "score": 72.0,
                    "grade": "C",
                    "issue_codes": ["subtitle_quality_blocking"],
                    "recommended_rerun_step": "subtitle_postprocess",
                    "recommended_rerun_steps": [
                        "subtitle_postprocess",
                        "subtitle_term_resolution",
                        "subtitle_consistency_review",
                    ],
                },
            )
        )
        await session.commit()

    rerun_response = await client.post(
        f"/api/v1/jobs/{job_id}/rerun",
        json={"issue_code": "subtitle_quality_blocking", "note": "回退字幕链重新处理"},
    )
    assert rerun_response.status_code == 200

    response = await client.get(f"/api/v1/jobs/{job_id}/activity")
    assert response.status_code == 200
    data = response.json()

    rerun_event = next(item for item in data["events"] if item["title"] == "已请求从 subtitle_postprocess 重跑")
    assert rerun_event["type"] == "review_action"
    assert rerun_event["status"] == "processing"
    assert rerun_event["step_name"] == "subtitle_postprocess"
    assert "触发来源：Web" in rerun_event["detail"]
    assert "问题：subtitle_quality_blocking" in rerun_event["detail"]
    assert "回退链路：subtitle_postprocess -> subtitle_term_resolution -> subtitle_consistency_review" in rerun_event["detail"]


@pytest.mark.asyncio
async def test_job_activity_prefers_confirmed_content_profile_and_review_specific_waiting_detail(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/final-review-activity.mp4",
                source_name="final-review-activity.mp4",
                status="needs_review",
                language="zh-CN",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="final_review",
                status="pending",
                metadata_={"detail": "等待审核成片后继续。"},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_draft",
                created_at=datetime.now(timezone.utc),
                data_json={
                    "subject_type": "草稿主题",
                    "video_theme": "草稿视频主题",
                    "summary": "这是一版不该出现在终审活动流里的草稿摘要。",
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                created_at=datetime.now(timezone.utc),
                data_json={
                    "subject_type": "确认后主题",
                    "video_theme": "确认后视频主题",
                    "summary": "这是一版已经确认过的最终摘要。",
                },
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}/activity")
    assert response.status_code == 200
    data = response.json()

    assert data["review_step"] == "final_review"
    assert data["review_detail"] == "等待审核成片后继续生成平台文案。"
    assert data["current_step"]["step_name"] == "final_review"
    assert data["current_step"]["detail"] == "等待审核成片后继续生成平台文案。"

    profile_decision = next(item for item in data["decisions"] if item["kind"] == "content_profile")
    assert profile_decision["status"] == "done"
    assert "确认后主题" in profile_decision["summary"]
    assert "这是一版已经确认过的最终摘要。" in profile_decision["detail"]


@pytest.mark.asyncio
async def test_job_preview_uses_subtitle_review_context_when_summary_review_is_blocked_by_subtitle_gate(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/subtitle-review-context.mp4",
                source_name="subtitle-review-context.mp4",
                status="needs_review",
                language="zh-CN",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        session.add(
                Artifact(
                    job_id=job_id,
                    artifact_type="subtitle_term_resolution_patch",
                    data_json={
                        "autocorrect_policy": "lexical_only",
                        "metrics": {
                            "patch_count": 4,
                            "pending_count": 2,
                            "auto_applied_count": 1,
                        }
                },
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()

    assert data["review_step"] == "summary_review"
    assert data["review_label"] == "字幕复核"
    assert "先人工确认 2 条词级术语候选" in data["review_detail"]


@pytest.mark.asyncio
async def test_job_activity_routes_semantic_contamination_to_semantic_review(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/semantic-contamination.mp4",
                source_name="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
                status="needs_review",
                language="zh-CN",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="subtitle_quality_report",
                data_json={
                    "score": 52.0,
                    "blocking": True,
                    "blocking_reasons": ["检测到语义污染 4 处，必须人工确认"],
                    "warning_reasons": [],
                    "metrics": {
                        "identity_missing": False,
                        "semantic_bad_term_total": 4,
                        "lexical_bad_term_total": 1,
                    },
                },
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}/activity")
    assert response.status_code == 200
    data = response.json()

    subtitle_quality_decision = next(item for item in data["decisions"] if item["kind"] == "subtitle_quality")
    assert subtitle_quality_decision["review_label"] == "语义污染复核"
    assert subtitle_quality_decision["issue_codes"] == ["subtitle_semantic_contamination"]
    assert "仅允许词级纠偏" in subtitle_quality_decision["recommended_action"]


@pytest.mark.asyncio
async def test_job_activity_standardizes_platform_package_pending_detail(client: AsyncClient):
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/platform-package.mp4",
                source_name="platform-package.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="platform_package", status="pending"))
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}/activity")
    assert response.status_code == 200
    data = response.json()

    assert data["current_step"]["step_name"] == "platform_package"
    assert data["current_step"]["detail"] == "等待调度器派发生成平台文案。"


@pytest.mark.asyncio
async def test_content_profile_endpoint_returns_memory_cloud(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, JobStep
    from roughcut.db.session import get_session_factory
    from roughcut.review.content_profile_memory import record_content_profile_feedback_memory

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    async with get_session_factory()() as session:
        job = Job(
            id=job_id,
            source_path="jobs/demo/memory.mp4",
            source_name="memory.mp4",
            status="needs_review",
            language="zh-CN",
            workflow_template="edc_tactical",
            workflow_mode="standard_edit",
            enhancement_modes=["avatar_commentary"],
        )
        session.add(job)
        session.add(
            JobStep(
                job_id=job_id,
                step_name="summary_review",
                status="running",
                started_at=now,
                metadata_={"detail": "首次品牌/型号证据不足，需人工确认后再继续。"},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_draft",
                data_json={
                    "subject_brand": "LEATHERMAN",
                    "subject_model": "ARC",
                    "subject_type": "多功能工具钳",
                    "video_theme": "开箱与上手体验",
                    "summary": "围绕 LEATHERMAN ARC 展开。",
                    "search_queries": ["LEATHERMAN ARC", "LEATHERMAN ARC 开箱"],
                    "identity_review": {
                        "required": True,
                        "first_seen_brand": True,
                        "first_seen_model": True,
                        "conservative_summary": True,
                        "support_sources": ["transcript", "source_name"],
                        "evidence_strength": "weak",
                        "reason": "开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认",
                        "evidence_bundle": {
                            "candidate_brand": "LEATHERMAN",
                            "candidate_model": "ARC",
                            "matched_subtitle_snippets": ["[0.0-1.0] LEATHERMAN ARC 开箱"],
                            "matched_glossary_aliases": {"brand": ["莱泽曼"], "model": []},
                            "matched_source_name_terms": ["ARC"],
                            "matched_visible_text_terms": [],
                            "matched_evidence_terms": [],
                        },
                    },
                    "automation_review": {
                        "review_reasons": ["首次品牌/型号证据不足，已退化为保守摘要"],
                        "blocking_reasons": ["开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认"],
                    },
                },
            )
        )
        await session.flush()
        await record_content_profile_feedback_memory(
            session,
            job=job,
            draft_profile={"subject_brand": "", "subject_model": "", "subject_type": "开箱产品"},
            final_profile={"search_queries": ["LEATHERMAN ARC", "多功能工具钳"]},
            user_feedback={
                "subject_brand": "LEATHERMAN",
                "subject_model": "ARC",
                "keywords": ["LEATHERMAN ARC", "多功能工具钳"],
            },
        )
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}/content-profile")
    assert response.status_code == 200
    data = response.json()
    assert data["draft"]["subject_brand"] == "LEATHERMAN"
    assert data["review_step_status"] == "running"
    assert data["review_step_detail"] == "首次品牌/型号证据不足，需人工确认后再继续。"
    assert data["review_reasons"] == ["首次品牌/型号证据不足，已退化为保守摘要"]
    assert data["blocking_reasons"] == ["开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认"]
    assert data["draft"]["content_understanding"]["primary_subject"] == "多功能工具钳"
    assert data["draft"]["content_understanding"]["video_type"] == ""
    assert data["draft"]["content_understanding"]["content_domain"] == ""
    assert data["identity_review"]["evidence_bundle"]["matched_glossary_aliases"]["brand"] == ["莱泽曼"]
    assert data["workflow_mode"] == "standard_edit"
    assert data["enhancement_modes"] == ["avatar_commentary"]
    assert data["ocr_evidence"] == {}
    assert data["transcript_evidence"] == {}
    assert data["entity_resolution_trace"] == {}
    assert data["memory"]["field_preferences"]["subject_brand"][0]["value"] == "LEATHERMAN"
    assert data["memory"]["cloud"]["words"]
    assert any(word["label"] == "LEATHERMAN ARC" for word in data["memory"]["cloud"]["words"])


@pytest.mark.asyncio
async def test_content_profile_endpoint_normalizes_content_understanding_block_for_draft_and_final(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/understanding.mp4",
                source_name="understanding.mp4",
                status="needs_review",
                language="zh-CN",
                workflow_template="edc_tactical",
                workflow_mode="standard_edit",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="summary_review",
                status="running",
                started_at=now,
                metadata_={"detail": "等待人工确认。"},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_draft",
                data_json={
                    "subject_type": "旧字段",
                    "content_understanding": {
                        "video_type": "开箱体验",
                        "primary_subject": "EDC机能包",
                        "search_queries": ["LEATHERMAN ARC", " leatherman arc ", "多功能工具钳"],
                        "confidence": {"overall": 0.8},
                        "needs_review": True,
                    },
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_type": "最终字段",
                    "video_theme": "最终主题",
                    "summary": "最终摘要",
                    "hook_line": "最终钩子",
                    "engagement_question": "最终提问",
                    "content_understanding": {
                        "video_type": " tutorial ",
                        "search_queries": ["  教程 ", "教程", "流程"],
                        "confidence": {"overall": 0.95},
                    },
                },
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}/content-profile")
    assert response.status_code == 200
    data = response.json()
    draft_understanding = data["draft"]["content_understanding"]
    assert draft_understanding["video_type"] == "unboxing"
    assert draft_understanding["content_domain"] == ""
    assert draft_understanding["primary_subject"] == "EDC机能包"
    assert draft_understanding["subject_entities"] == []
    assert draft_understanding["video_theme"] == ""
    assert draft_understanding["summary"] == ""
    assert draft_understanding["hook_line"] == ""
    assert draft_understanding["engagement_question"] == ""
    assert draft_understanding["search_queries"] == ["LEATHERMAN ARC", "多功能工具钳"]
    assert draft_understanding["evidence_spans"] == []
    assert draft_understanding["uncertainties"] == []
    assert draft_understanding["confidence"] == {"overall": 0.8}
    assert draft_understanding["needs_review"] is True
    assert draft_understanding["review_reasons"] == []

    final_understanding = data["final"]["content_understanding"]
    assert final_understanding["video_type"] == "tutorial"
    assert final_understanding["content_domain"] == ""
    assert final_understanding["primary_subject"] == "最终字段"
    assert final_understanding["subject_entities"] == []
    assert final_understanding["video_theme"] == "最终主题"
    assert final_understanding["summary"] == "最终摘要"
    assert final_understanding["hook_line"] == "最终钩子"
    assert final_understanding["engagement_question"] == "最终提问"
    assert final_understanding["search_queries"] == ["教程", "流程"]
    assert final_understanding["evidence_spans"] == []
    assert final_understanding["uncertainties"] == []
    assert final_understanding["confidence"] == {"overall": 0.95}
    assert final_understanding["needs_review"] is False
    assert final_understanding["review_reasons"] == []


@pytest.mark.asyncio
async def test_content_profile_endpoint_keeps_review_draft_when_legacy_profile_is_stale(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/stale-legacy.mp4",
                source_name="stale-legacy.mp4",
                status="needs_review",
                language="zh-CN",
                workflow_template="edc_tactical",
                workflow_mode="standard_edit",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="summary_review",
                status="pending",
                started_at=now,
                metadata_={"detail": "等待人工确认。"},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile",
                data_json={
                    "summary": "旧摘要里混进了脏数据",
                    "keywords": ["LOGOLOGO", "2.5]好开始吧[3.7, 6.3]今天今天是一个。"],
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_draft",
                data_json={
                    "summary": "新 draft 摘要",
                    "keywords": ["DCF", "PF"],
                    "content_understanding": {
                        "summary": "新 draft 摘要",
                        "search_queries": ["DCF 开箱", "PF 开箱"],
                    },
                },
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}/content-profile")
    assert response.status_code == 200
    data = response.json()
    assert data["draft"]["summary"] == "新 draft 摘要"
    assert data["draft"]["keywords"] == ["DCF", "PF"]
    assert data["final"] is None


@pytest.mark.asyncio
async def test_content_profile_endpoint_exposes_evidence_artifacts(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/evidence.mp4",
                source_name="evidence.mp4",
                status="needs_review",
                language="zh-CN",
                workflow_template="edc_tactical",
                workflow_mode="standard_edit",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="summary_review",
                status="running",
                started_at=now,
                metadata_={"detail": "等待人工确认。"},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_draft",
                data_json={
                    "subject_brand": "狐蝠工业",
                    "subject_model": "FXX1小副包",
                    "subject_type": "EDC机能包",
                    "video_theme": "开箱与上手评测",
                    "summary": "围绕狐蝠工业 FXX1小副包展开。",
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_ocr",
                data_json={
                    "source_name": "evidence.mp4",
                    "frame_count": 2,
                    "line_count": 3,
                    "available": True,
                    "status": "ok",
                    "visible_text": "狐蝠工业 FXX1小副包 开箱",
                    "raw_snippets": [
                        {
                            "frame_index": 0,
                            "timestamp": 0.0,
                            "text": "狐蝠工业",
                            "confidence": 0.99,
                            "box": [0, 0, 10, 10],
                            "frame_path": "/tmp/frame-0.jpg",
                        }
                    ],
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="transcript_evidence",
                data_json={
                    "provider": "qwen3_asr",
                    "model": "qwen3-asr-1.7b",
                    "prompt": "请优先识别品牌与型号。",
                    "segments": [{"start": 0.0, "end": 1.2, "text": "这期开箱狐蝠工业 FXX1小副包。"}],
                },
            )
        )
        await session.commit()

    response = await client.get(f"/api/v1/jobs/{job_id}/content-profile")
    assert response.status_code == 200
    data = response.json()
    assert data["ocr_evidence"]["visible_text"] == "狐蝠工业 FXX1小副包 开箱"
    assert data["transcript_evidence"]["provider"] == "qwen3_asr"
    assert data["transcript_evidence"]["prompt"] == "请优先识别品牌与型号。"
    assert data["entity_resolution_trace"] == {}

    confirm_response = await client.post(f"/api/v1/jobs/{job_id}/content-profile/confirm", json={})
    assert confirm_response.status_code == 200
    confirm_data = confirm_response.json()
    assert confirm_data["ocr_evidence"]["visible_text"] == "狐蝠工业 FXX1小副包 开箱"
    assert confirm_data["transcript_evidence"]["model"] == "qwen3-asr-1.7b"
    assert confirm_data["entity_resolution_trace"] == {}


@pytest.mark.asyncio
async def test_confirm_content_profile_persists_identity_alias_memory_on_simple_approval(client: AsyncClient):
    from sqlalchemy import select

    from roughcut.db.models import Artifact, Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/fxx1.mp4",
                source_name="20260316_鸿福_F叉二一小副包_开箱测评.mp4",
                status="needs_review",
                language="zh-CN",
                workflow_template="edc_tactical",
                workflow_mode="standard_edit",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="summary_review",
                status="pending",
                started_at=now,
                metadata_={"detail": "首次品牌/型号证据不足，需人工确认后再继续。"},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_draft",
                data_json={
                    "subject_brand": "狐蝠工业",
                    "subject_model": "FXX1小副包",
                    "subject_type": "EDC机能包",
                    "video_theme": "狐蝠工业FXX1小副包开箱与上手评测",
                    "summary": "这条视频主要围绕一款EDC机能包展开，具体品牌型号待人工确认。",
                    "search_queries": ["狐蝠工业 FXX1小副包"],
                    "identity_review": {
                        "required": True,
                        "first_seen_brand": True,
                        "first_seen_model": True,
                        "conservative_summary": True,
                        "support_sources": ["transcript", "source_name"],
                        "evidence_strength": "weak",
                        "reason": "开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认",
                        "evidence_bundle": {
                            "candidate_brand": "狐蝠工业",
                            "candidate_model": "FXX1小副包",
                            "matched_subtitle_snippets": ["[0.0-1.8] 这期鸿福 F叉二一小副包做个开箱测评。"],
                            "matched_glossary_aliases": {
                                "brand": ["鸿福"],
                                "model": ["F叉二一小副包"],
                            },
                            "matched_source_name_terms": ["鸿福", "F叉二一小副包"],
                            "matched_visible_text_terms": [],
                            "matched_evidence_terms": [],
                        },
                    },
                    "automation_review": {
                        "review_reasons": ["首次品牌/型号证据不足，已退化为保守摘要"],
                        "blocking_reasons": ["开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认"],
                    },
                },
            )
        )
        await session.commit()

    response = await client.post(f"/api/v1/jobs/{job_id}/content-profile/confirm", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "processing"
    assert any(
        item["field_name"] == "subject_brand"
        and item["original_value"] == "鸿福"
        and item["corrected_value"] == "狐蝠工业"
        for item in data["memory"]["recent_corrections"]
    )
    assert any(
        item["field_name"] == "subject_model"
        and item["original_value"] == "F叉二一小副包"
        and item["corrected_value"] == "FXX1小副包"
        for item in data["memory"]["recent_corrections"]
    )

    async with get_session_factory()() as session:
        downstream_context = (
            await session.execute(
                select(Artifact)
                .where(Artifact.job_id == job_id, Artifact.artifact_type == "downstream_context")
                .order_by(Artifact.created_at.desc(), Artifact.id.desc())
            )
        ).scalars().first()

    assert downstream_context is not None
    assert downstream_context.data_json["resolved_profile"]["subject_brand"] == "狐蝠工业"
    assert downstream_context.data_json["manual_review_applied"] is True


@pytest.mark.asyncio
async def test_confirm_content_profile_persists_identity_alias_terms_to_domain_glossary(client: AsyncClient):
    from sqlalchemy import select

    from roughcut.db.models import Artifact, GlossaryTerm, Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/fxx1-glossary.mp4",
                source_name="20260316_鸿福_F叉二一小副包_开箱测评.mp4",
                status="needs_review",
                language="zh-CN",
                workflow_template="edc_tactical",
                workflow_mode="standard_edit",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="summary_review",
                status="pending",
                started_at=now,
                metadata_={"detail": "首次品牌/型号证据不足，需人工确认后再继续。"},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_draft",
                data_json={
                    "subject_brand": "狐蝠工业",
                    "subject_model": "FXX1小副包",
                    "subject_type": "EDC机能包",
                    "subject_domain": "edc",
                    "video_theme": "狐蝠工业FXX1小副包开箱与上手评测",
                    "summary": "这条视频主要围绕一款EDC机能包展开，具体品牌型号待人工确认。",
                    "search_queries": ["狐蝠工业 FXX1小副包"],
                    "identity_review": {
                        "required": True,
                        "first_seen_brand": True,
                        "first_seen_model": True,
                        "conservative_summary": True,
                        "support_sources": ["transcript", "source_name"],
                        "evidence_strength": "weak",
                        "reason": "开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认",
                        "evidence_bundle": {
                            "candidate_brand": "狐蝠工业",
                            "candidate_model": "FXX1小副包",
                            "matched_subtitle_snippets": ["[0.0-1.8] 这期鸿福 F叉二一小副包做个开箱测评。"],
                            "matched_glossary_aliases": {
                                "brand": ["鸿福"],
                                "model": ["F叉二一小副包"],
                            },
                            "matched_source_name_terms": ["鸿福", "F叉二一小副包"],
                            "matched_visible_text_terms": [],
                            "matched_evidence_terms": [],
                        },
                    },
                },
            )
        )
        await session.commit()

    response = await client.post(f"/api/v1/jobs/{job_id}/content-profile/confirm", json={})
    assert response.status_code == 200

    async with get_session_factory()() as session:
        result = await session.execute(
            select(GlossaryTerm).where(
                GlossaryTerm.correct_form.in_(["狐蝠工业", "FXX1小副包"]),
            )
        )
        terms = result.scalars().all()

    brand_term = next(item for item in terms if item.correct_form == "狐蝠工业" and item.scope_type == "domain")
    model_term = next(item for item in terms if item.correct_form == "FXX1小副包" and item.scope_type == "domain")
    assert "鸿福" in brand_term.wrong_forms
    assert "F叉二一小副包" in model_term.wrong_forms
    assert all(item.scope_type != "workflow_template" for item in terms)


@pytest.mark.asyncio
async def test_confirm_content_profile_persists_reviewed_terms_and_keywords_to_domain_glossary(client: AsyncClient):
    from sqlalchemy import select

    from roughcut.db.models import Artifact, GlossaryTerm, Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/comfyui-review.mp4",
                source_name="comfyui-review.mp4",
                status="needs_review",
                language="zh-CN",
                workflow_template="tutorial_standard",
                workflow_mode="standard_edit",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="summary_review",
                status="pending",
                started_at=now,
                metadata_={"detail": "等待人工确认。"},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_draft",
                data_json={
                    "subject_brand": "康飞UI",
                    "subject_model": "节点流",
                    "subject_type": "AI工作流",
                    "subject_domain": "ai",
                    "video_theme": "AI 工作流演示",
                    "summary": "主要介绍康飞UI的节点流和工作流搭建。",
                    "search_queries": ["康飞UI 工作流"],
                },
            )
        )
        await session.commit()

    response = await client.post(
        f"/api/v1/jobs/{job_id}/content-profile/confirm",
        json={
            "subject_brand": "ComfyUI",
            "subject_model": "节点编排",
            "subject_type": "AI工作流",
            "keywords": ["ComfyUI 工作流", "节点编排"],
        },
    )
    assert response.status_code == 200

    async with get_session_factory()() as session:
        result = await session.execute(
            select(GlossaryTerm).where(
                GlossaryTerm.scope_type == "domain",
                GlossaryTerm.scope_value == "ai",
            )
        )
        terms = result.scalars().all()

    brand_term = next(item for item in terms if item.correct_form == "ComfyUI")
    model_term = next(item for item in terms if item.correct_form == "节点编排")
    subject_term = next(item for item in terms if item.correct_form == "AI工作流")
    keyword_term = next(item for item in terms if item.correct_form == "ComfyUI 工作流")
    assert "康飞UI" in brand_term.wrong_forms
    assert "节点流" in model_term.wrong_forms
    assert subject_term.wrong_forms == []
    assert keyword_term.wrong_forms == []


@pytest.mark.asyncio
async def test_confirm_content_profile_persists_explicit_video_type_feedback(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/review.mp4",
                source_name="review.mp4",
                status="needs_review",
                language="zh-CN",
                workflow_template="unboxing_standard",
                workflow_mode="standard_edit",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="summary_review",
                status="pending",
                started_at=now,
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_draft",
                data_json={
                    "subject_type": "AI创作工具",
                    "summary": "待人工确认后继续。",
                    "content_understanding": {
                        "video_type": "unboxing",
                        "primary_subject": "AI创作工具",
                        "needs_review": True,
                    },
                },
            )
        )
        await session.commit()

    response = await client.post(
        f"/api/v1/jobs/{job_id}/content-profile/confirm",
        json={"video_type": "tutorial"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["final"]["content_understanding"]["video_type"] == "tutorial"


@pytest.mark.asyncio
async def test_confirm_content_profile_touches_runtime_refresh_hold(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from roughcut.db.models import Artifact, Job, JobStep
    from roughcut.db.session import get_session_factory

    hold_path = tmp_path / "runtime-refresh-hold.json"
    monkeypatch.setenv("ROUGHCUT_RUNTIME_REFRESH_HOLD_PATH", str(hold_path))

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/review.mp4",
                source_name="review.mp4",
                status="needs_review",
                language="zh-CN",
                workflow_template="unboxing_standard",
                workflow_mode="standard_edit",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="summary_review",
                status="pending",
                started_at=now,
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_draft",
                data_json={
                    "subject_type": "AI创作工具",
                    "summary": "待人工确认后继续。",
                    "automation_review": {
                        "review_reasons": ["主题待确认"],
                        "blocking_reasons": ["缺少稳定证据"],
                    },
                },
            )
        )
        await session.commit()

    response = await client.post(f"/api/v1/jobs/{job_id}/content-profile/confirm", json={})
    assert response.status_code == 200
    assert hold_path.exists()
    payload = json.loads(hold_path.read_text(encoding="utf-8"))
    assert payload["reason"] == "content_profile_confirm"
    assert payload["job_id"] == str(job_id)
    assert payload["expires_at_utc"].endswith("Z")
