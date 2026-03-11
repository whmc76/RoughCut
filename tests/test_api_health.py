from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
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
async def test_config_has_extended_provider_fields(client: AsyncClient):
    response = await client.get("/api/v1/config")
    assert response.status_code == 200
    data = response.json()
    assert "openai_base_url" in data
    assert "anthropic_base_url" in data
    assert "minimax_base_url" in data
    assert "openai_auth_mode" in data
    assert "anthropic_auth_mode" in data
    assert "minimax_api_key_set" in data


@pytest.mark.asyncio
async def test_config_options_exposes_transcription_models(client: AsyncClient):
    response = await client.get("/api/v1/config/options")
    assert response.status_code == 200
    data = response.json()
    assert data["transcription_models"]["openai"] == ["gpt-4o-transcribe"]
    assert "large-v3" in data["transcription_models"]["local_whisper"]


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
    assert data["current_step"]["detail"] == "执行 FFmpeg 渲染成片"
    assert round(data["render"]["progress"], 2) == 0.35
    kinds = {item["kind"] for item in data["decisions"]}
    assert "content_profile" in kinds
    assert "edit_plan" in kinds
    assert "subtitle_review" in kinds
    assert any(event["title"] == "渲染输出" for event in data["events"])
