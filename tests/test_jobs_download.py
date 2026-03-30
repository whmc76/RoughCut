from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from roughcut.db.models import Job, RenderOutput


@pytest.mark.asyncio
async def test_job_download_routes_serve_local_rendered_files(client, db_session, tmp_path: Path):
    job_id = uuid.uuid4()
    packaged = tmp_path / "20260330_demo_横版_成片.mp4"
    plain = tmp_path / "20260330_demo_横版_素板.mp4"
    packaged.write_bytes(b"packaged-video")
    plain.write_bytes(b"plain-video")

    db_session.add(
        Job(
            id=job_id,
            source_path=str(tmp_path / "source.mp4"),
            source_name="source.mp4",
            status="done",
            language="zh-CN",
        )
    )
    db_session.add(
        RenderOutput(
            job_id=job_id,
            output_path=str(packaged),
            status="done",
            progress=1.0,
        )
    )
    await db_session.commit()

    meta_response = await client.get(f"/api/v1/jobs/{job_id}/download?variant=plain")

    assert meta_response.status_code == 200
    assert meta_response.json()["url"].endswith(f"/api/v1/jobs/{job_id}/download/file?variant=plain")

    file_response = await client.get(f"/api/v1/jobs/{job_id}/download/file?variant=plain")

    assert file_response.status_code == 200
    assert file_response.content == b"plain-video"
