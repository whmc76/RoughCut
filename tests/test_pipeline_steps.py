from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from roughcut.db.models import Artifact, Job, JobStep, SubtitleItem, Timeline
from roughcut.pipeline.steps import _load_latest_artifact, _load_latest_timeline, _record_source_integrity, run_glossary_review


def test_record_source_integrity_writes_debug_report(tmp_path: Path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"roughcut")
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()

    actual_hash = _record_source_integrity(
        source,
        source_ref="jobs/123/video.mp4",
        expected_hash=None,
        debug_dir=debug_dir,
        downloaded=True,
    )

    payload = json.loads((debug_dir / "source.integrity.json").read_text(encoding="utf-8"))
    assert payload["actual_sha256"] == actual_hash
    assert payload["downloaded_from_storage"] is True
    assert payload["hash_match"] is True


def test_record_source_integrity_rejects_hash_mismatch(tmp_path: Path):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"roughcut")

    with pytest.raises(ValueError, match="Downloaded source hash mismatch"):
        _record_source_integrity(
            source,
            source_ref="jobs/123/video.mp4",
            expected_hash="deadbeef",
            debug_dir=None,
            downloaded=True,
        )


@pytest.mark.asyncio
async def test_run_glossary_review_loads_recent_subtitles_without_name_error(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    captured_recent_subtitles: list[dict] = []

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="edc_tactical",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="glossary_review", status="running"))
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="OLIGHT",
                text_norm="OLIGHT",
                text_final="OLIGHT",
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_brand": "OLIGHT傲雷",
                    "subject_model": "SLIM二代凹卡版",
                    "subject_type": "手电筒",
                    "video_theme": "手电筒开箱与上手体验",
                    "preset_name": "edc_tactical",
                },
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    async def fake_apply_glossary_corrections(*args, **kwargs):
        return []

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_load_recent_subtitle_examples(*args, **kwargs):
        return [{"text_final": "历史字幕"}]

    async def fake_load_related_profile_subtitle_examples(*args, **kwargs):
        return [{"text_final": "相似字幕"}]

    async def fake_enrich_content_profile(**kwargs):
        return kwargs["profile"]

    monkeypatch.setattr(steps_mod, "apply_glossary_corrections", fake_apply_glossary_corrections)
    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_load_recent_subtitle_examples", fake_load_recent_subtitle_examples)
    monkeypatch.setattr(steps_mod, "_load_related_profile_subtitle_examples", fake_load_related_profile_subtitle_examples)
    monkeypatch.setattr(steps_mod, "enrich_content_profile", fake_enrich_content_profile)

    def fake_build_subtitle_review_memory(**kwargs):
        captured_recent_subtitles.extend(kwargs["recent_subtitles"])
        return {"recent_subtitles_count": len(kwargs["recent_subtitles"])}

    async def fake_polish_subtitle_items(*args, **kwargs):
        assert kwargs["review_memory"]["recent_subtitles_count"] == 3
        return 1

    monkeypatch.setattr(steps_mod, "build_subtitle_review_memory", fake_build_subtitle_review_memory)
    monkeypatch.setattr(steps_mod, "polish_subtitle_items", fake_polish_subtitle_items)

    result = await run_glossary_review(str(job_id))

    assert result["polished_count"] == 1
    assert len(captured_recent_subtitles) == 3


@pytest.mark.asyncio
async def test_load_latest_artifact_prefers_most_recent_row(db_session):
    job_id = uuid.uuid4()
    db_session.add(
        Job(
            id=job_id,
            source_path="jobs/demo/source.mp4",
            source_name="source.mp4",
            status="processing",
            language="zh-CN",
        )
    )
    older = Artifact(
        job_id=job_id,
        artifact_type="audio_wav",
        storage_path="jobs/demo/older.wav",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(older)
    await db_session.commit()

    newer = Artifact(
        job_id=job_id,
        artifact_type="audio_wav",
        storage_path="jobs/demo/newer.wav",
        created_at=older.created_at + timedelta(seconds=1),
    )
    db_session.add(newer)
    await db_session.commit()

    artifact = await _load_latest_artifact(db_session, job_id, "audio_wav")

    assert artifact.storage_path == "jobs/demo/newer.wav"


@pytest.mark.asyncio
async def test_load_latest_timeline_prefers_most_recent_row(db_session):
    job_id = uuid.uuid4()
    db_session.add(
        Job(
            id=job_id,
            source_path="jobs/demo/source.mp4",
            source_name="source.mp4",
            status="processing",
            language="zh-CN",
        )
    )
    older = Timeline(job_id=job_id, version=1, timeline_type="editorial", data_json={"version": "older"})
    db_session.add(older)
    await db_session.commit()

    newer = Timeline(job_id=job_id, version=2, timeline_type="editorial", data_json={"version": "newer"})
    db_session.add(newer)
    await db_session.commit()

    timeline = await _load_latest_timeline(db_session, job_id, "editorial")

    assert timeline.data_json == {"version": "newer"}
