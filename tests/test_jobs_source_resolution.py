from __future__ import annotations

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
    monkeypatch.setattr(jobs_mod, "_extract_reference_frames", lambda *_args, **_kwargs: [])
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
