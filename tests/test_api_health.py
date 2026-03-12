from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

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
    assert data["transcription_models"]["local_whisper"][0] == "base"
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
async def test_watch_root_inventory_enqueue_selected_item(client: AsyncClient, monkeypatch: pytest.MonkeyPatch):
    import roughcut.api.review as review_api
    from roughcut.db.models import WatchRoot
    from roughcut.db.session import get_session_factory

    async def fake_create_jobs_for_inventory_paths(file_paths: list[str], *, channel_profile: str | None = None, language: str = "zh-CN"):
        assert file_paths == ["/tmp/videos-enqueue/a.mp4"]
        assert channel_profile == "demo"
        return [{"path": "/tmp/videos-enqueue/a.mp4", "job_id": "job-123"}]

    monkeypatch.setattr(review_api, "create_jobs_for_inventory_paths", fake_create_jobs_for_inventory_paths)

    created = await client.post(
        "/api/v1/watch-roots",
        json={"path": "/tmp/videos-enqueue", "enabled": True, "channel_profile": "demo"},
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
            ]
        )
        await session.commit()

    response = await client.get("/api/v1/jobs")
    assert response.status_code == 200
    item = next(job for job in response.json() if job["id"] == str(job_id))
    assert item["content_subject"] == "LEATHERMAN ARC · 多功能工具钳 · 开箱与上手体验"
    assert item["content_summary"] == "围绕 ARC 的刀具配置和实际上手手感展开。"


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
    assert data["memory"]["field_preferences"]["subject_brand"][0]["value"] == "LEATHERMAN"
    assert data["memory"]["cloud"]["words"]
    assert any(word["label"] == "LEATHERMAN ARC" for word in data["memory"]["cloud"]["words"])
