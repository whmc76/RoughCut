from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from roughcut.db.models import Artifact, Job, JobStep, SubtitleItem, Timeline
from roughcut.pipeline.steps import (
    _get_cover_seek,
    _load_latest_artifact,
    _load_latest_optional_artifact,
    _load_latest_timeline,
    _record_source_integrity,
    _select_cover_source_video,
    _select_preferred_content_profile_artifact,
    run_ai_director,
    run_avatar_commentary,
    run_content_profile,
    run_glossary_review,
)


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
        assert kwargs["allow_llm"] is False
        return 1

    monkeypatch.setattr(steps_mod, "build_subtitle_review_memory", fake_build_subtitle_review_memory)
    monkeypatch.setattr(steps_mod, "polish_subtitle_items", fake_polish_subtitle_items)

    result = await run_glossary_review(str(job_id))

    assert result["polished_count"] == 1
    assert result["auto_accepted_correction_count"] == 0
    assert result["pending_correction_count"] == 0
    assert len(captured_recent_subtitles) == 3


@pytest.mark.asyncio
async def test_run_content_profile_auto_confirms_high_confidence_profile(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="screen_tutorial",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="content_profile", status="running"))
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        for index, text in enumerate(
            [
                "这期演示剪映里怎么批量处理字幕样式",
                "先导入字幕模板再统一调整字号",
                "第二步要把描边和阴影一起改掉",
                "第三步检查时间轴里有没有错位",
                "最后导出预设方便下次复用",
                "这样整个流程就能稳定复现",
            ]
        ):
            session.add(
                SubtitleItem(
                    job_id=job_id,
                    version=1,
                    item_index=index,
                    start_time=float(index),
                    end_time=float(index) + 1.0,
                    text_raw=text,
                    text_norm=text,
                    text_final=text,
                )
            )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        return {
            "preset_name": "screen_tutorial",
            "subject_type": "剪映字幕工作流",
            "video_theme": "批量字幕样式调整步骤讲解",
            "summary": "这条视频主要围绕剪映字幕工作流展开，重点讲清批量调样式、检查错位和复用预设的完整步骤。",
            "engagement_question": "你做批量字幕时最容易卡在样式统一还是时间轴检查？",
            "search_queries": ["剪映 批量字幕 样式", "剪映 字幕 预设 导出"],
            "cover_title": {"top": "剪映", "main": "批量字幕流程", "bottom": "样式统一教程"},
            "evidence": [{"title": "剪映字幕文档"}],
        }

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)

    result = await run_content_profile(str(job_id))

    assert result["auto_confirmed"] is True
    assert result["automation_score"] >= 0.72

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id).order_by(Artifact.created_at.asc())
        )
        artifacts = artifact_result.scalars().all()
        artifact_map = {item.artifact_type: item.data_json for item in artifacts}
        assert set(artifact_map) == {"content_profile_draft", "content_profile_final"}

        draft = artifact_map["content_profile_draft"]
        final = artifact_map["content_profile_final"]
        assert draft["automation_review"]["auto_confirm"] is True
        assert draft["creative_profile"]["workflow_mode"] == "standard_edit"
        assert draft["creative_profile"]["enhancement_modes"] == []
        assert final["review_mode"] == "auto_confirmed"

        review_step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
        )
        review_step = review_step_result.scalar_one()
        assert review_step.status == "done"
        assert review_step.metadata_["auto_confirmed"] is True


@pytest.mark.asyncio
async def test_run_ai_director_generates_plan_for_enabled_job(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/director.mp4",
                source_name="director.mp4",
                status="processing",
                language="zh-CN",
                enhancement_modes=["ai_director"],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="ai_director", status="running"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_type": "科普讲解",
                    "summary": "讲清楚一个复杂概念的关键判断路径。",
                    "engagement_question": "你会怎么解释给第一次接触的人？",
                },
            )
        )
        for index, text in enumerate(["先说结论", "中间补背景", "最后抛问题"]):
            session.add(
                SubtitleItem(
                    job_id=job_id,
                    version=1,
                    item_index=index,
                    start_time=float(index) * 3,
                    end_time=float(index) * 3 + 2.0,
                    text_raw=text,
                    text_norm=text,
                    text_final=text,
                )
            )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    async def fake_build_ai_director_plan(**kwargs):
        return {
            "opening_hook": "这条内容最该先讲清楚的结论，我先替你拎出来。",
            "bridge_line": "这里应该补一层背景说明。",
            "voice_provider": "edge",
            "voiceover_segments": [{"segment_id": "director_hook", "rewritten_text": "新钩子"}],
            "dubbing_request": {"provider": "edge"},
        }

    monkeypatch.setattr(steps_mod, "build_ai_director_plan", fake_build_ai_director_plan)

    result = await run_ai_director(str(job_id))

    assert result["enabled"] is True
    assert result["voiceover_segment_count"] == 1

    async with factory() as session:
        artifact = await _load_latest_optional_artifact(session, job_id=job_id, artifact_types=("ai_director_plan",))
        assert artifact is not None
        assert artifact.data_json["voice_provider"] == "edge"


@pytest.mark.asyncio
async def test_run_avatar_commentary_generates_plan_for_enabled_job(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/avatar.mp4",
                source_name="avatar.mp4",
                status="processing",
                language="zh-CN",
                enhancement_modes=["avatar_commentary", "ai_director"],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="avatar_commentary", status="running"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "summary": "这是对复杂信息的拆解。",
                    "engagement_question": "你最想让数字人补哪一段？",
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="ai_director_plan",
                data_json={
                    "voiceover_segments": [
                        {
                            "purpose": "hook",
                            "rewritten_text": "我先替你抓重点。",
                            "suggested_start_time": 0.4,
                            "target_duration_sec": 3.2,
                        }
                    ]
                },
            )
        )
        for index, text in enumerate(["开头", "中段", "结尾"]):
            session.add(
                SubtitleItem(
                    job_id=job_id,
                    version=1,
                    item_index=index,
                    start_time=float(index) * 4,
                    end_time=float(index) * 4 + 2.5,
                    text_raw=text,
                    text_norm=text,
                    text_final=text,
                )
            )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    def fake_build_avatar_commentary_plan(**kwargs):
        return {
            "provider": "mock",
            "layout_template": "picture_in_picture_right",
            "segments": [{"segment_id": "avatar_1", "script": "我先替你抓重点。"}],
            "render_request": {"provider": "mock"},
        }

    monkeypatch.setattr(steps_mod, "build_avatar_commentary_plan", fake_build_avatar_commentary_plan)

    result = await run_avatar_commentary(str(job_id))

    assert result["enabled"] is True
    assert result["segment_count"] == 1

    async with factory() as session:
        artifact = await _load_latest_optional_artifact(session, job_id=job_id, artifact_types=("avatar_commentary_plan",))
        assert artifact is not None
        assert artifact.data_json["layout_template"] == "picture_in_picture_right"


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


@pytest.mark.asyncio
async def test_get_cover_seek_uses_latest_media_meta_when_multiple_rows_exist(db_session):
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
    db_session.add(
        Artifact(
            job_id=job_id,
            artifact_type="media_meta",
            created_at=datetime.now(timezone.utc),
            data_json={"duration": 10.0},
        )
    )
    db_session.add(
        Artifact(
            job_id=job_id,
            artifact_type="media_meta",
            created_at=datetime.now(timezone.utc) + timedelta(seconds=1),
            data_json={"duration": 250.0},
        )
    )
    await db_session.commit()

    seek = await _get_cover_seek(job_id, "unused")

    assert seek == 45.0


def test_select_cover_source_video_prefers_plain_render(tmp_path: Path):
    plain = tmp_path / "output_plain.mp4"
    packaged = tmp_path / "output.mp4"
    plain.write_bytes(b"plain")
    packaged.write_bytes(b"packaged")

    selected = _select_cover_source_video(plain, packaged)

    assert selected == plain


def test_select_cover_source_video_falls_back_to_packaged_render(tmp_path: Path):
    plain = tmp_path / "output_plain.mp4"
    packaged = tmp_path / "output.mp4"
    packaged.write_bytes(b"packaged")

    selected = _select_cover_source_video(plain, packaged)

    assert selected == packaged


def test_select_preferred_content_profile_artifact_prefers_final_over_newer_working_copy():
    base_time = datetime(2026, 3, 12, 15, 0, tzinfo=timezone.utc)
    draft = Artifact(
        artifact_type="content_profile_draft",
        created_at=base_time,
        data_json={"kind": "draft"},
    )
    final = Artifact(
        artifact_type="content_profile_final",
        created_at=base_time + timedelta(seconds=1),
        data_json={"kind": "final"},
    )
    working_copy = Artifact(
        artifact_type="content_profile",
        created_at=base_time + timedelta(seconds=2),
        data_json={"kind": "content"},
    )

    selected = _select_preferred_content_profile_artifact([draft, final, working_copy])

    assert selected is final
