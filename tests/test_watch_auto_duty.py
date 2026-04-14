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

    async def fake_create_jobs(
        file_paths: list[str],
        *,
        workflow_template: str | None = None,
        output_dir: str | None = None,
        config_profile_id: uuid.UUID | str | None = None,
        awaiting_initialization: bool = False,
    ):
        assert file_paths == [str(source)]
        assert awaiting_initialization is False
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
async def test_watch_auto_duty_task_only_mode_creates_awaiting_init_jobs_without_auto_merge(tmp_path, monkeypatch, db_engine):
    import roughcut.watcher.folder_watcher as watcher_mod
    from roughcut.db.models import WatchRoot
    from roughcut.db.session import get_session_factory

    source = tmp_path / "clip_task_only.mp4"
    source.write_bytes(b"video-task-only")
    old_time = time.time() - 180
    os.utime(source, (old_time, old_time))

    async with get_session_factory()() as session:
        root = WatchRoot(
            path=str(tmp_path),
            enabled=True,
            scan_mode="fast",
            ingest_mode="task_only",
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

    async def fake_create_jobs(
        file_paths: list[str],
        *,
        workflow_template: str | None = None,
        output_dir: str | None = None,
        config_profile_id: uuid.UUID | str | None = None,
        awaiting_initialization: bool = False,
    ):
        assert file_paths == [str(source)]
        assert awaiting_initialization is True
        return [{"path": str(source), "job_id": "job-awaiting-init-1"}]

    async def should_not_merge(*args, **kwargs):
        raise AssertionError("task_only mode should not trigger auto merge")

    async def saturated_scheduler_state(session):
        return {"active_jobs": 99, "running_gpu_steps": 0}

    monkeypatch.setattr(watcher_mod, "create_jobs_for_inventory_paths", fake_create_jobs)
    monkeypatch.setattr(watcher_mod, "suggest_merge_groups_for_inventory_items", should_not_merge)
    monkeypatch.setattr(watcher_mod, "_load_auto_scheduler_state", saturated_scheduler_state)

    summary = await watcher_mod.run_watch_root_auto_duty()

    assert summary["auto_enqueued_jobs"] == 1
    assert summary["auto_merged_jobs"] == 0


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

    async def fake_create_merged_job(
        file_paths: list[str],
        *,
        workflow_template: str | None = None,
        output_dir: str | None = None,
        config_profile_id: uuid.UUID | str | None = None,
        awaiting_initialization: bool = False,
    ):
        assert file_paths == [str(clip_a), str(clip_b)]
        assert awaiting_initialization is False
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


@pytest.mark.asyncio
async def test_watch_auto_duty_adds_descriptive_filename_to_video_description(tmp_path, monkeypatch, db_engine):
    import roughcut.watcher.folder_watcher as watcher_mod
    from roughcut.db.models import Job, JobStep, WatchRoot
    from roughcut.db.session import get_session_factory
    from sqlalchemy import select

    class _FakeStorage:
        def ensure_bucket(self) -> None:
            return None

        def upload_file(self, local_path: Path, key: str) -> str:
            assert local_path.exists()
            assert key.startswith("jobs/")
            return key

    source = tmp_path / "20260316_狐蝠工业_FXX1小副包_开箱测评.mp4"
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
        result = await session.execute(
            select(JobStep).where(JobStep.job_id == created_job_id, JobStep.step_name == "content_profile")
        )
        step = result.scalar_one()
        assert step.metadata_["source_context"]["video_description"].startswith("任务说明依据文件名：")
        assert "狐蝠工业 FXX1小副包 开箱测评" in step.metadata_["source_context"]["video_description"]


@pytest.mark.asyncio
async def test_suggest_merge_groups_uses_subject_tokens_and_visual_similarity(tmp_path, monkeypatch):
    import roughcut.watcher.folder_watcher as watcher_mod

    clip_a = tmp_path / "clip_a.mp4"
    clip_b = tmp_path / "clip_b.mp4"
    clip_a.write_bytes(b"video-a")
    clip_b.write_bytes(b"video-b")
    old_time = time.time() - 180
    os.utime(clip_a, (old_time, old_time))
    os.utime(clip_b, (old_time + 20, old_time + 20))

    summaries = {
        str(clip_a): "LEATHERMAN ARC 多功能工具钳开箱，展示做工和锁定结构。",
        str(clip_b): "继续对 LEATHERMAN ARC 多功能钳做细节展示，补充上手和结构体验。",
    }

    async def fake_signature(path: Path) -> str | None:
        if path == clip_a:
            return "1" * 256
        if path == clip_b:
            return "1" * 240 + "0" * 16
        return None

    monkeypatch.setattr(watcher_mod, "_safe_parse_summary", lambda path: summaries.get(str(path), ""))
    monkeypatch.setattr(watcher_mod, "_extract_visual_signature", fake_signature)

    items = [_pending_item(clip_a), _pending_item(clip_b)]
    items[0]["duration_sec"] = 42.0
    items[1]["duration_sec"] = 44.0
    items[0]["source_name"] = "LEATHERMAN_ARC_part1.mp4"
    items[1]["source_name"] = "LEATHERMAN_ARC_part2.mp4"

    groups = await watcher_mod.suggest_merge_groups_for_inventory_items(
        items,
        time_window_seconds=180,
        min_score=0.62,
    )

    assert len(groups) == 1
    assert groups[0]["relative_paths"] == [clip_a.name, clip_b.name]
    assert "主体关键词相似" in groups[0]["reasons"]
    assert "摘要文本相似" in groups[0]["reasons"]
    assert "画面特征相似" in groups[0]["reasons"]


@pytest.mark.asyncio
async def test_suggest_merge_groups_boosts_timestamp_sequence_clips_without_sidecar_summary(tmp_path, monkeypatch):
    import roughcut.watcher.folder_watcher as watcher_mod

    clip_a = tmp_path / "20260209-124735.mp4"
    clip_b = tmp_path / "20260209-131541.mp4"
    clip_a.write_bytes(b"video-a")
    clip_b.write_bytes(b"video-b")
    base_time = time.time() - 180
    os.utime(clip_a, (base_time, base_time))
    os.utime(clip_b, (base_time + 98, base_time + 98))

    async def fake_signature(path: Path) -> str | None:
        if path == clip_a:
            return "1" * 256
        if path == clip_b:
            return "1" * 216 + "0" * 40
        return None

    monkeypatch.setattr(watcher_mod, "_safe_parse_summary", lambda path: "")
    monkeypatch.setattr(watcher_mod, "_extract_visual_signature", fake_signature)

    items = [_pending_item(clip_a), _pending_item(clip_b)]
    items[0]["duration_sec"] = 140.0
    items[1]["duration_sec"] = 118.0
    items[0]["width"] = 1080
    items[0]["height"] = 1920
    items[1]["width"] = 1080
    items[1]["height"] = 1920

    groups = await watcher_mod.suggest_merge_groups_for_inventory_items(
        items,
        time_window_seconds=480,
        min_score=0.62,
    )

    assert len(groups) == 1
    assert groups[0]["relative_paths"] == [clip_a.name, clip_b.name]
    assert groups[0]["score"] >= 0.62
    assert "连续拍摄片段" in groups[0]["reasons"]
    assert "画面特征相似" in groups[0]["reasons"]


@pytest.mark.asyncio
async def test_create_merged_job_for_inventory_paths_only_manual_merge_enables_related_profiles(tmp_path, monkeypatch):
    import roughcut.watcher.folder_watcher as watcher_mod

    clip_a = tmp_path / "20260130-134317.mp4"
    clip_b = tmp_path / "20260130-140529.mp4"
    clip_a.write_bytes(b"video-a")
    clip_b.write_bytes(b"video-b")
    merged_output = tmp_path / "watch_merge_demo.mp4"
    merged_output.write_bytes(b"merged-video")
    captured: dict[str, object] = {}

    async def fake_merge(file_paths: list[Path], *, output_path: Path) -> Path:
        assert file_paths == [clip_a.resolve(), clip_b.resolve()]
        return merged_output

    async def fake_create_job_for_file(
        file_path: Path,
        workflow_template: str | None = None,
        language: str = "zh-CN",
        output_dir: str | None = None,
        *,
        config_profile_id: uuid.UUID | str | None = None,
        content_profile_source_context: dict[str, object] | None = None,
        awaiting_initialization: bool = False,
    ) -> str:
        captured["file_path"] = file_path
        captured["source_context"] = content_profile_source_context
        captured["output_dir"] = output_dir
        captured["awaiting_initialization"] = awaiting_initialization
        return "job-merged-1"

    monkeypatch.setattr(watcher_mod, "_merge_videos_for_job", fake_merge)
    monkeypatch.setattr(watcher_mod, "_create_job_for_file", fake_create_job_for_file)

    job_id = await watcher_mod.create_merged_job_for_inventory_paths(
        [str(clip_a), str(clip_b)],
        output_dir=str(tmp_path / "final-out"),
        allow_related_profiles=True,
    )
    assert job_id == "job-merged-1"
    assert captured["file_path"] == merged_output
    assert captured["output_dir"] == str(tmp_path / "final-out")
    assert captured["awaiting_initialization"] is False
    assert captured["source_context"] == {
        "allow_related_profiles": True,
        "merged_source_names": [clip_a.name, clip_b.name],
    }

    captured.clear()
    merged_output.write_bytes(b"merged-video")

    job_id = await watcher_mod.create_merged_job_for_inventory_paths(
        [str(clip_a), str(clip_b)],
    )
    assert job_id == "job-merged-1"
    assert captured["source_context"] is None
