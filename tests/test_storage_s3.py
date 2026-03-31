from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_s3_storage_resolve_path_strips_s3_scheme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import roughcut.storage.s3 as s3_mod

    monkeypatch.setattr(
        s3_mod,
        "get_settings",
        lambda: SimpleNamespace(s3_bucket_name="jobs", job_storage_dir=str(tmp_path / "jobs")),
    )

    storage = s3_mod.S3Storage()

    assert storage.resolve_path("s3://jobs/demo/video.mp4") == (tmp_path / "jobs" / "demo" / "video.mp4").resolve()


def test_s3_storage_download_file_reassembles_multipart_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import roughcut.storage.s3 as s3_mod

    monkeypatch.setattr(
        s3_mod,
        "get_settings",
        lambda: SimpleNamespace(s3_bucket_name="jobs", job_storage_dir=str(tmp_path / "jobs")),
    )

    object_dir = tmp_path / "jobs" / "demo" / "output.mp4" / uuid.uuid4().hex
    object_dir.mkdir(parents=True, exist_ok=True)
    (object_dir.parent / "xl.meta").write_text("meta", encoding="utf-8")
    (object_dir / "part.1").write_bytes(b"abc")
    (object_dir / "part.2").write_bytes(b"def")

    storage = s3_mod.S3Storage()
    target = tmp_path / "downloaded.mp4"

    storage.download_file("jobs/demo/output.mp4", target)

    assert target.read_bytes() == b"abcdef"


def test_s3_storage_resolve_path_maps_windows_job_storage_path_into_current_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import roughcut.storage.s3 as s3_mod

    monkeypatch.setattr(
        s3_mod,
        "get_settings",
        lambda: SimpleNamespace(s3_bucket_name="jobs", job_storage_dir=str(tmp_path / "jobs")),
    )

    storage = s3_mod.S3Storage()

    assert storage.resolve_path("F:/roughcut_outputs/jobs/demo/video.mp4") == (
        tmp_path / "jobs" / "demo" / "video.mp4"
    ).resolve()
