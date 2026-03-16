from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
    assert {"gear", "tech", "ai", "travel", "food", "finance", "news", "sports"}.issubset(domains)
    gear_pack = next(item for item in data if item["domain"] == "gear")
    assert gear_pack["term_count"] >= 20
    assert any(term["correct_form"] == "EDC" for term in gear_pack["terms"])
    assert any(term["correct_form"] == "潮玩" for term in gear_pack["terms"])
    assert any(term["correct_form"] == "户外" for term in gear_pack["terms"])


@pytest.mark.asyncio
async def test_config_has_extended_provider_fields(client: AsyncClient):
    response = await client.get("/api/v1/config")
    assert response.status_code == 200
    data = response.json()
    assert "transcription_dialect" in data
    assert "openai_base_url" in data
    assert "qwen_asr_api_base_url" in data
    assert "avatar_provider" in data
    assert "avatar_api_base_url" in data
    assert "avatar_training_api_base_url" in data
    assert "voice_provider" in data
    assert "voice_clone_api_base_url" in data
    assert "anthropic_base_url" in data
    assert "minimax_base_url" in data
    assert "openai_auth_mode" in data
    assert "anthropic_auth_mode" in data
    assert "minimax_api_key_set" in data
    assert "output_dir" in data


@pytest.mark.asyncio
async def test_config_patch_updates_output_dir(client: AsyncClient, tmp_path: Path):
    output_dir = tmp_path / "exports"

    response = await client.patch("/api/v1/config", json={"output_dir": str(output_dir)})

    assert response.status_code == 200
    assert response.json()["output_dir"] == str(output_dir)
    assert output_dir.exists()


@pytest.mark.asyncio
async def test_config_options_exposes_transcription_models(client: AsyncClient):
    response = await client.get("/api/v1/config/options")
    assert response.status_code == 200
    data = response.json()
    assert data["job_languages"][0]["value"] == "zh-CN"
    assert data["channel_profiles"][0]["value"] == ""
    assert data["workflow_modes"][0]["value"] == "standard_edit"
    assert any(item["value"] == "avatar_commentary" for item in data["enhancement_modes"])
    assert any(item["value"] == "mandarin" for item in data["transcription_dialects"])
    assert any(item["value"] == "beijing" for item in data["transcription_dialects"])
    assert any(item["value"] == "heygem" for item in data["avatar_providers"])
    assert any(item["value"] == "indextts2" for item in data["voice_providers"])
    assert any(item["key"] == "long_text_to_video" and item["status"] == "planned" for item in data["creative_mode_catalog"]["workflow_modes"])
    assert data["transcription_models"]["local_whisper"][0] == "large-v3"
    assert data["transcription_models"]["openai"] == ["gpt-4o-transcribe", "gpt-4o-mini-transcribe"]
    assert data["transcription_models"]["qwen_asr"] == ["qwen3-asr-1.7b"]
    assert "large-v3" in data["transcription_models"]["local_whisper"]
    assert any(item["value"] == "edc_tactical" for item in data["channel_profiles"])
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
    assert any(section["title"] == "上传类型与用途" for section in data["sections"])
    assert any(section["title"] == "必须满足" for section in data["sections"])
    assert data["profiles"] == []


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
        data={"display_name": "测试数字人"},
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
async def test_watch_root_rejects_unknown_channel_profile(client: AsyncClient):
    response = await client.post(
        "/api/v1/watch-roots",
        json={"path": "/tmp/videos-invalid", "enabled": True, "channel_profile": "free_text_profile"},
    )

    assert response.status_code == 422
    assert "Unsupported channel_profile" in response.text


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
        json={"path": "/tmp/videos", "enabled": True},
    )
    assert resp.status_code == 201
    created = resp.json()
    root_id = created["id"]
    assert created["scan_mode"] == "fast"

    resp = await client.get("/api/v1/watch-roots")
    assert resp.status_code == 200
    roots = resp.json()
    assert any(r["id"] == root_id and r["scan_mode"] == "fast" for r in roots)

    resp = await client.delete(f"/api/v1/watch-roots/{root_id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_watch_root_inventory(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.review as review_api

    async def fake_scan_watch_root_inventory(path: str, *, recursive: bool = True, scan_mode: str = "fast"):
        assert path == "/tmp/videos"
        assert scan_mode == "precise"
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
    ):
        assert path == watch_path
        assert force is True
        assert scan_mode == "precise"
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

    async def fake_create_jobs_for_inventory_paths(file_paths: list[str], *, channel_profile: str | None = None, language: str = "zh-CN"):
        assert file_paths == ["/tmp/videos-enqueue/a.mp4"]
        assert channel_profile == "edc_tactical"
        return [{"path": "/tmp/videos-enqueue/a.mp4", "job_id": "job-123"}]

    monkeypatch.setattr(review_api, "create_jobs_for_inventory_paths", fake_create_jobs_for_inventory_paths)

    created = await client.post(
        "/api/v1/watch-roots",
        json={"path": "/tmp/videos-enqueue", "enabled": True, "channel_profile": "edc_tactical"},
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

    async def fake_create_jobs_for_inventory_paths(file_paths: list[str], *, channel_profile: str | None = None, language: str = "zh-CN"):
        assert file_paths == ["/tmp/videos-batch/a.mp4", "/tmp/videos-batch/b.mp4"]
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
        "_running_container_names",
        lambda: {"roughcut-postgres-1", "roughcut-redis-1"},
    )
    monkeypatch.setattr(
        control_api,
        "_has_process",
        lambda needle: "orchestrator" in needle or "media_queue" in needle,
    )

    response = await client.get("/api/v1/control/status")
    assert response.status_code == 200
    data = response.json()["services"]
    assert data["api"] is True
    assert data["orchestrator"] is True
    assert data["media_worker"] is True
    assert data["llm_worker"] is False
    assert data["postgres"] is True
    assert data["redis"] is True
    assert data["minio"] is False


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
                channel_profile="edc",
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
            ]
        )
        await session.commit()

    response = await client.get("/api/v1/jobs")
    assert response.status_code == 200
    item = next(job for job in response.json() if job["id"] == str(job_id))
    assert item["content_subject"] == "LEATHERMAN ARC · 多功能工具钳 · 开箱与上手体验"
    assert item["content_summary"] == "围绕 ARC 的刀具配置和实际上手手感展开。"
    assert item["avatar_delivery_status"] == "done"
    assert item["avatar_delivery_summary"] == "数字人口播已作为画中画写入成片。"


@pytest.mark.asyncio
async def test_job_restart_allows_done_jobs(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

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

    response = await client.post(f"/api/v1/jobs/{job_id}/restart")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["file_hash"] is None
    assert data["steps"][0]["status"] == "pending"
    assert data["steps"][0]["attempt"] == 0

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
                    channel_profile="edc",
                    field_name="subject_brand",
                    original_value="",
                    corrected_value="LEATHERMAN",
                ),
                ContentProfileCorrection(
                    job_id=uuid.uuid4(),
                    source_name="b.mp4",
                    channel_profile="edc",
                    field_name="subject_model",
                    original_value="",
                    corrected_value="ARC",
                ),
                ContentProfileKeywordStat(scope_type="global", scope_value="", keyword="LEATHERMAN ARC", usage_count=2),
                ContentProfileKeywordStat(scope_type="channel_profile", scope_value="edc", keyword="多功能工具钳", usage_count=3),
            ]
        )
        await session.commit()

    response = await client.get("/api/v1/jobs/stats/content-profile-memory?channel_profile=edc")
    assert response.status_code == 200
    data = response.json()
    assert data["scope"] == "channel_profile"
    assert data["channel_profile"] == "edc"
    assert "edc" in data["channel_profiles"]
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
                    "preset_name": "screen_tutorial",
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
    assert subtitle_decision["detail"] == "待审 1 条，自动/已接受 0 条"


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
            channel_profile="edc_memory_demo",
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
    assert data["workflow_mode"] == "standard_edit"
    assert data["enhancement_modes"] == ["avatar_commentary"]
    assert data["memory"]["field_preferences"]["subject_brand"][0]["value"] == "LEATHERMAN"
    assert data["memory"]["cloud"]["words"]
    assert any(word["label"] == "LEATHERMAN ARC" for word in data["memory"]["cloud"]["words"])
