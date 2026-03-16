from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select


def _pending_item(path: Path) -> dict:
    stat = path.stat()
    return {
        "path": str(path),
        "relative_path": path.name,
        "source_name": path.name,
        "stem": path.stem,
        "summary_hint": path.stem,
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "duration_sec": None,
        "width": None,
        "height": None,
        "fps": None,
        "status": "pending",
        "dedupe_reason": None,
        "matched_job_id": None,
        "matched_output_path": None,
    }


@pytest.mark.asyncio
async def test_watch_auto_duty_enqueues_settled_pending_item(tmp_path, monkeypatch, db_engine):
    import roughcut.watcher.folder_watcher as watcher_mod
    from roughcut.db.models import WatchRoot
    from roughcut.db.session import get_session_factory

    source = tmp_path / "clip_a.mp4"
    source.write_bytes(b"video-a")
    os.utime(source, (time.time() - 120, time.time() - 120))
    root_id = None

    async with get_session_factory()() as session:
        root = WatchRoot(
            path=str(tmp_path),
            enabled=True,
            scan_mode="fast",
            inventory_cache_json={
                "root_path": str(tmp_path),
                "scan_mode": "fast",
                "status": "done",
                "started_at": "",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "total_files": 1,
                "processed_files": 1,
                "pending_count": 1,
                "deduped_count": 0,
                "current_file": None,
                "current_phase": None,
                "current_file_size_bytes": None,
                "current_file_processed_bytes": None,
                "error": None,
                "inventory": {
                    "pending": [_pending_item(source)],
                    "deduped": [],
                },
            },
            inventory_cache_updated_at=datetime.now(timezone.utc),
        )
        session.add(root)
        await session.commit()
        root_id = root.id

    async def fake_create_jobs(file_paths: list[str], *, channel_profile: str | None = None, language: str = "zh-CN"):
        assert file_paths == [str(source)]
        return [{"path": str(source), "job_id": "job-auto-1"}]

    async def no_merge_groups(*args, **kwargs):
        return []

    async def idle_scheduler_state(session):
        return {"active_jobs": 0, "running_gpu_steps": 0}

    monkeypatch.setattr(watcher_mod, "create_jobs_for_inventory_paths", fake_create_jobs)
    monkeypatch.setattr(watcher_mod, "suggest_merge_groups_for_inventory_items", no_merge_groups)
    monkeypatch.setattr(watcher_mod, "_load_auto_scheduler_state", idle_scheduler_state)

    summary = await watcher_mod.run_watch_root_auto_duty()

    assert summary["auto_enqueued_jobs"] == 1

    async with get_session_factory()() as session:
        root = await session.get(WatchRoot, root_id)
        payload = root.inventory_cache_json
        assert payload["pending_count"] == 0
        assert payload["deduped_count"] == 1
        assert payload["inventory"]["deduped"][0]["matched_job_id"] == "job-auto-1"
        assert payload["inventory"]["deduped"][0]["dedupe_reason"] == "job:auto_enqueued"


@pytest.mark.asyncio
async def test_watch_auto_duty_prefers_auto_merge_when_group_detected(tmp_path, monkeypatch, db_engine):
    import roughcut.watcher.folder_watcher as watcher_mod
    from roughcut.db.models import WatchRoot
    from roughcut.db.session import get_session_factory

    clip_a = tmp_path / "merge_a.mp4"
    clip_b = tmp_path / "merge_b.mp4"
    clip_a.write_bytes(b"video-a")
    clip_b.write_bytes(b"video-b")
    old_time = time.time() - 180
    os.utime(clip_a, (old_time, old_time))
    os.utime(clip_b, (old_time, old_time))

    async with get_session_factory()() as session:
        root = WatchRoot(
            path=str(tmp_path),
            enabled=True,
            scan_mode="fast",
            inventory_cache_json={
                "root_path": str(tmp_path),
                "scan_mode": "fast",
                "status": "done",
                "started_at": "",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
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
                    "pending": [_pending_item(clip_a), _pending_item(clip_b)],
                    "deduped": [],
                },
            },
            inventory_cache_updated_at=datetime.now(timezone.utc),
        )
        session.add(root)
        await session.commit()
        root_id = root.id

    async def fake_suggest_groups(items: list[dict], **kwargs):
        return [{"relative_paths": [clip_a.name, clip_b.name], "score": 0.93, "reasons": ["拍摄时间接近", "摘要文本相似"]}]

    async def fake_create_merged_job(file_paths: list[str], *, channel_profile: str | None = None, language: str = "zh-CN"):
        assert file_paths == [str(clip_a), str(clip_b)]
        return "job-merge-1"

    async def fail_enqueue(*args, **kwargs):
        raise AssertionError("plain enqueue should not run when auto merge succeeds first")

    async def idle_scheduler_state(session):
        return {"active_jobs": 0, "running_gpu_steps": 0}

    monkeypatch.setattr(watcher_mod, "suggest_merge_groups_for_inventory_items", fake_suggest_groups)
    monkeypatch.setattr(watcher_mod, "create_merged_job_for_inventory_paths", fake_create_merged_job)
    monkeypatch.setattr(watcher_mod, "create_jobs_for_inventory_paths", fail_enqueue)
    monkeypatch.setattr(watcher_mod, "_load_auto_scheduler_state", idle_scheduler_state)

    summary = await watcher_mod.run_watch_root_auto_duty()

    assert summary["auto_merged_jobs"] == 1

    async with get_session_factory()() as session:
        root = await session.get(WatchRoot, root_id)
        payload = root.inventory_cache_json
        assert payload["pending_count"] == 0
        assert payload["deduped_count"] == 2
        assert all(item["matched_job_id"] == "job-merge-1" for item in payload["inventory"]["deduped"])
        assert all(item["dedupe_reason"] == "job:auto_merged" for item in payload["inventory"]["deduped"])


@pytest.mark.asyncio
async def test_watch_auto_duty_creates_real_job_records_for_settled_file(tmp_path, monkeypatch, db_engine):
    import roughcut.watcher.folder_watcher as watcher_mod
    from roughcut.db.models import Job, JobStep, WatchRoot
    from roughcut.db.session import get_session_factory

    class _FakeStorage:
        def ensure_bucket(self) -> None:
            return None

        def upload_file(self, local_path: Path, key: str) -> str:
            assert local_path.exists()
            assert key.startswith("jobs/")
            return key

    source = tmp_path / "1742112233445.mp4"
    source.write_bytes(b"video-a")
    old_time = time.time() - 180
    os.utime(source, (old_time, old_time))

    async with get_session_factory()() as session:
        root = WatchRoot(
            path=str(tmp_path),
            enabled=True,
            scan_mode="fast",
            inventory_cache_json={
                "root_path": str(tmp_path),
                "scan_mode": "fast",
                "status": "done",
                "started_at": "",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "total_files": 1,
                "processed_files": 1,
                "pending_count": 1,
                "deduped_count": 0,
                "current_file": None,
                "current_phase": None,
                "current_file_size_bytes": None,
                "current_file_processed_bytes": None,
                "error": None,
                "inventory": {
                    "pending": [_pending_item(source)],
                    "deduped": [],
                },
            },
            inventory_cache_updated_at=datetime.now(timezone.utc),
        )
        session.add(root)
        await session.commit()
        root_id = root.id

    async def no_merge_groups(*args, **kwargs):
        return []

    async def never_processed(*_args, **_kwargs):
        return False

    async def idle_scheduler_state(session):
        return {"active_jobs": 0, "running_gpu_steps": 0}

    monkeypatch.setattr(watcher_mod, "get_storage", lambda: _FakeStorage())
    monkeypatch.setattr(watcher_mod, "_file_already_processed", never_processed)
    monkeypatch.setattr(watcher_mod, "suggest_merge_groups_for_inventory_items", no_merge_groups)
    monkeypatch.setattr(watcher_mod, "_load_auto_scheduler_state", idle_scheduler_state)

    summary = await watcher_mod.run_watch_root_auto_duty()

    assert summary["auto_enqueued_jobs"] == 1

    async with get_session_factory()() as session:
        root = await session.get(WatchRoot, root_id)
        payload = root.inventory_cache_json
        created_job_id = uuid.UUID(payload["inventory"]["deduped"][0]["matched_job_id"])

        job = await session.get(Job, created_job_id)
        assert job is not None
        assert job.source_name == source.name
        assert job.status == "pending"

        step_result = await session.execute(select(JobStep).where(JobStep.job_id == job.id))
        steps = step_result.scalars().all()
        assert len(steps) >= 1
