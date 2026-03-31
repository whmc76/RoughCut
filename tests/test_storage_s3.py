from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


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
