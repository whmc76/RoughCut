from __future__ import annotations

import os
from types import SimpleNamespace
import uuid
from pathlib import Path

import pytest

from roughcut.db.models import Job


@pytest.mark.asyncio
async def test_resolve_job_source_falls_back_to_output_plain_when_source_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.jobs as jobs_mod

    job_id = uuid.uuid4()
    downloaded: list[str] = []

    class FakeStorage:
        def resolve_path(self, _key: str) -> Path:
            return tmp_path / "missing-source.mp4"

        async def async_download_file(self, key: str, local_path: Path) -> Path:
            downloaded.append(key)
            if key != f"jobs/{job_id}/output_plain.mp4":
                raise FileNotFoundError(key)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(b"video")
            return local_path

    job = Job(
        id=job_id,
        source_path=f"s3://jobs/{job_id}/missing.mp4",
        source_name="missing.mp4",
        status="done",
        language="zh-CN",
        workflow_mode="standard_edit",
        enhancement_modes=[],
    )

    monkeypatch.setattr(jobs_mod, "get_storage", lambda: FakeStorage())

    resolved = await jobs_mod._resolve_job_source(job, str(tmp_path / "tmp"))

    assert resolved.read_bytes() == b"video"
    assert downloaded == [
        f"s3://jobs/{job_id}/missing.mp4",
        f"jobs/{job_id}/output_plain.mp4",
    ]


@pytest.mark.asyncio
async def test_ensure_content_profile_thumbnail_generates_placeholder_when_extraction_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.jobs as jobs_mod

    async def fake_resolve_job_source(_job: Job, _tmpdir: str) -> Path:
        source = tmp_path / "source.mp4"
        source.write_bytes(b"video")
        return source

    monkeypatch.setattr(jobs_mod, "_resolve_job_source", fake_resolve_job_source)
    monkeypatch.setattr(jobs_mod, "_extract_reference_frame", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(jobs_mod.tempfile, "gettempdir", lambda: str(tmp_path))

    job = Job(
        id=uuid.uuid4(),
        source_path="s3://jobs/demo/missing.mp4",
        source_name="missing.mp4",
        status="done",
        language="zh-CN",
        workflow_mode="standard_edit",
        enhancement_modes=[],
    )

    thumbnail = await jobs_mod._ensure_content_profile_thumbnail(job, index=0)

    assert thumbnail.exists()
    assert thumbnail.read_bytes()[:2] == b"\xff\xd8"


@pytest.mark.asyncio
async def test_ensure_content_profile_thumbnail_generates_placeholder_when_source_cannot_be_resolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.jobs as jobs_mod

    async def fail_resolve_job_source(_job: Job, _tmpdir: str) -> Path:
        raise FileNotFoundError("missing source")

    monkeypatch.setattr(jobs_mod, "_resolve_job_source", fail_resolve_job_source)
    monkeypatch.setattr(jobs_mod.tempfile, "gettempdir", lambda: str(tmp_path))

    job = Job(
        id=uuid.uuid4(),
        source_path="s3://jobs/demo/missing.mp4",
        source_name="missing.mp4",
        status="failed",
        language="zh-CN",
        workflow_mode="standard_edit",
        enhancement_modes=[],
    )

    thumbnail = await jobs_mod._ensure_content_profile_thumbnail(job, index=0)

    assert thumbnail.exists()
    assert thumbnail.read_bytes()[:2] == b"\xff\xd8"


@pytest.mark.asyncio
async def test_ensure_content_profile_thumbnail_rebuilds_stale_placeholder_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.jobs as jobs_mod

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    async def fake_resolve_job_source(_job: Job, _tmpdir: str) -> Path:
        return source

    def fake_extract_reference_frame(_source: Path, cache_dir: Path, index: int, _total_frames: int) -> bool:
        (cache_dir / f"profile_{index:02d}.jpg").write_bytes(b"\xff\xd8fresh-thumb")
        return True

    monkeypatch.setattr(jobs_mod, "_resolve_job_source", fake_resolve_job_source)
    monkeypatch.setattr(jobs_mod, "_extract_reference_frame", fake_extract_reference_frame)
    monkeypatch.setattr(jobs_mod.tempfile, "gettempdir", lambda: str(tmp_path))

    job = Job(
        id=uuid.uuid4(),
        source_path="s3://jobs/demo/thumb.mp4",
        source_name="thumb.mp4",
        status="done",
        language="zh-CN",
        workflow_mode="standard_edit",
        enhancement_modes=[],
    )

    cache_dir = tmp_path / "roughcut_content_profile_frames" / "v2" / str(job.id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / "profile_00.jpg"
    cached.write_bytes(jobs_mod._CONTENT_PROFILE_PLACEHOLDER_JPEG)
    os.utime(cached, (0, 0))

    thumbnail = await jobs_mod._ensure_content_profile_thumbnail(job, index=0)

    assert thumbnail == cached
    assert thumbnail.read_bytes() == b"\xff\xd8fresh-thumb"


def test_extract_reference_frame_falls_back_to_update_mode_when_primary_command_creates_no_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.api.jobs as jobs_mod

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "profile_00.jpg"
    calls: list[list[str]] = []

    monkeypatch.setattr(jobs_mod, "_probe_duration", lambda _source: 30.0)

    def fake_run(cmd: list[str], capture_output: bool, timeout: int):
        calls.append(cmd)
        if cmd[0] == "ffmpeg" and "-update" in cmd:
            output.write_bytes(b"\xff\xd8fresh-thumb")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(jobs_mod.subprocess, "run", fake_run)

    assert jobs_mod._extract_reference_frame(source, tmp_path, 0, 3) is True
    assert output.read_bytes() == b"\xff\xd8fresh-thumb"
    assert len(calls) == 2
    assert "-update" not in calls[0]
    assert "-update" in calls[1]
