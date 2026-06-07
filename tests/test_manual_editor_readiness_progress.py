from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from roughcut.api import jobs as jobs_api
from roughcut.db.models import Artifact, Job, JobStep, Timeline, TranscriptSegment
from roughcut.db.session import Base
from roughcut.pipeline import steps as pipeline_steps


def test_awaiting_manual_edit_preview_exposes_waiting_detail():
    job = Job(
        id=uuid.uuid4(),
        source_path="source.mp4",
        source_name="source.mp4",
        status="awaiting_manual_edit",
    )
    job.steps = [
        JobStep(job_id=job.id, step_name="edit_plan", status="done"),
        JobStep(
            job_id=job.id,
            step_name="render",
            status="pending",
            metadata_={"detail": "智能辅助模式已完成预处理。当前进度仅表示预处理完成度，尚未开始正式渲染；请打开手动调整后点击“正式渲染/重新渲染”提交。"},
        ),
    ]

    jobs_api._attach_job_preview(job)

    assert job.awaiting_manual_edit is True
    assert job.review_step is None
    assert job.review_label == "手动剪辑"
    assert "尚未开始正式渲染" in job.review_detail
    assert "正式渲染/重新渲染" in job.review_detail


def test_awaiting_manual_edit_current_step_uses_manual_waiting_context():
    job = Job(
        id=uuid.uuid4(),
        source_path="source.mp4",
        source_name="source.mp4",
        status="awaiting_manual_edit",
    )
    job.steps = [
        JobStep(job_id=job.id, step_name="edit_plan", status="done"),
        JobStep(job_id=job.id, step_name="render", status="pending"),
    ]

    current_step = jobs_api._build_current_step(job)

    assert current_step is not None
    assert current_step["step_name"] == "edit_plan"
    assert current_step["status"] == "pending"
    assert "当前进度仅表示预处理完成度" in str(current_step["detail"])
    assert "尚未开始正式渲染" in str(current_step["detail"])


def test_awaiting_manual_edit_progress_does_not_count_paused_downstream_steps():
    job = Job(
        id=uuid.uuid4(),
        source_path="source.mp4",
        source_name="source.mp4",
        status="awaiting_manual_edit",
    )
    job.steps = [
        JobStep(job_id=job.id, step_name=step_name, status="done")
        for step_name in jobs_api.PIPELINE_STEPS
        if jobs_api.STEP_ORDER[step_name] < jobs_api.STEP_ORDER["render"]
    ]
    job.steps.extend(
        [
            JobStep(job_id=job.id, step_name="render", status="skipped"),
            JobStep(job_id=job.id, step_name="final_review", status="skipped"),
            JobStep(job_id=job.id, step_name="platform_package", status="skipped"),
        ]
    )

    jobs_api._attach_job_preview(job)

    assert job.progress_percent < 100
    assert job.progress_percent == round(
        len([step for step in jobs_api.PIPELINE_STEPS if jobs_api.STEP_ORDER[step] < jobs_api.STEP_ORDER["render"]])
        / len(jobs_api.PIPELINE_STEPS)
        * 100
    )


def test_manual_editor_readiness_progress_includes_running_step_progress():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            required_steps = list(jobs_api._MANUAL_EDITOR_REQUIRED_STEPS)
            job = Job(
                id=uuid.uuid4(),
                source_path="source.mp4",
                source_name="source.mp4",
                status="processing",
            )
            job.steps = [
                JobStep(
                    job_id=job.id,
                    step_name=required_steps[0],
                    status="done",
                    metadata_={"progress": 1.0},
                ),
                JobStep(
                    job_id=job.id,
                    step_name=required_steps[1],
                    status="running",
                    metadata_={"progress": 0.5, "detail": "转写进行到一半"},
                ),
            ]
            session.add(job)
            await session.commit()

            readiness = await jobs_api._build_manual_editor_readiness(job=job, session=session)

            assert readiness.current_step == required_steps[1]
            readiness_unit_count = len(required_steps) + len(jobs_api._MANUAL_EDITOR_REQUIRED_OUTPUT_LABELS)
            assert readiness.progress_percent == round((1.0 + 0.5) / readiness_unit_count * 100)
            running_step = readiness.required_steps[1]
            assert running_step.progress == 0.5
            assert running_step.detail == "转写进行到一半"

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_manual_editor_source_rows_prefer_transcript_anchor_over_canonical_layer() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            job = Job(
                id=uuid.uuid4(),
                source_path="source.mp4",
                source_name="source.mp4",
                status="awaiting_manual_edit",
            )
            step = JobStep(job_id=job.id, step_name="transcript_review", status="done")
            session.add_all(
                [
                    job,
                    step,
                    TranscriptSegment(
                        job_id=job.id,
                        version=1,
                        segment_index=0,
                        start_time=0.0,
                        end_time=3.0,
                        text="原生锚点稿",
                        words_json=[{"word": "原", "start": 0.0, "end": 0.3}],
                    ),
                    Artifact(
                        job_id=job.id,
                        step_id=step.id,
                        artifact_type="canonical_transcript_layer",
                        data_json={
                            "segments": [
                                {
                                    "index": 0,
                                    "start": 0.0,
                                    "end": 3.0,
                                    "text_raw": "原生锚点稿",
                                    "text_canonical": "规范层文案",
                                    "words": [{"word": "规", "start": 0.0, "end": 0.3}],
                                }
                            ]
                        },
                    ),
                ]
            )
            await session.commit()

            rows = await jobs_api._load_manual_editor_source_subtitle_dicts(session, job_id=job.id)

            assert rows
            assert rows[0]["projection_source"] == "transcript_segment"
            assert rows[0]["text_final"] == "原生锚点稿"

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_edit_plan_source_subtitles_prefer_aligned_raw_rows_over_clean_projection_layer() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            job = Job(
                id=uuid.uuid4(),
                source_path="source.mp4",
                source_name="source.mp4",
                status="processing",
            )
            step = JobStep(job_id=job.id, step_name="transcript_review", status="done")
            session.add_all(
                [
                    job,
                    step,
                    TranscriptSegment(
                        job_id=job.id,
                        version=1,
                        segment_index=0,
                        start_time=0.0,
                        end_time=1.2,
                        text="嗯，这个真的不太行。",
                        words_json=[
                            {"word": "嗯", "start": 0.0, "end": 0.18},
                            {"word": "这", "start": 0.18, "end": 0.3},
                            {"word": "个", "start": 0.3, "end": 0.42},
                            {"word": "真", "start": 0.42, "end": 0.54},
                            {"word": "的", "start": 0.54, "end": 0.66},
                            {"word": "不", "start": 0.66, "end": 0.78},
                            {"word": "太", "start": 0.78, "end": 0.96},
                            {"word": "行", "start": 0.96, "end": 1.14},
                        ],
                    ),
                    Artifact(
                        job_id=job.id,
                        step_id=step.id,
                        artifact_type=pipeline_steps.ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,
                        data_json={
                            "entries": [
                                {
                                    "index": 0,
                                    "start_time": 0.0,
                                    "end_time": 1.14,
                                    "text_raw": "这个真的不太行",
                                    "text_norm": "这个真的不太行",
                                    "text_final": "这个真的不太行",
                                }
                            ]
                        },
                    ),
                ]
            )
            await session.commit()

            rows = await pipeline_steps._load_edit_plan_source_subtitles(session, job=job)

            assert rows
            assert rows[0]["projection_source"] == "transcript_segment"
            assert "嗯" in rows[0]["text_final"]

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_manual_editor_readiness_failed_step_prefers_error_message():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            job = Job(
                id=uuid.uuid4(),
                source_path="source.mp4",
                source_name="source.mp4",
                status="failed",
                error_message="任务失败汇总",
            )
            job.steps = [
                JobStep(
                    job_id=job.id,
                    step_name="content_profile",
                    status="failed",
                    error_message="步骤 content_profile 已达到最大重试次数 3，不再自动重试。",
                    metadata_={
                        "progress": 1.0,
                        "detail": "已自动确认内容摘要：旧状态说明不应该覆盖失败原因",
                    },
                ),
            ]
            session.add(job)
            await session.commit()

            readiness = await jobs_api._build_manual_editor_readiness(job=job, session=session)

            assert readiness.status == "failed"
            assert readiness.detail == "步骤 content_profile 已达到最大重试次数 3，不再自动重试。"

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_manual_editor_readiness_does_not_report_complete_when_outputs_are_missing(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        source_path = tmp_path / "source.mp4"
        source_path.write_bytes(b"video")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            job = Job(
                id=uuid.uuid4(),
                source_path=str(source_path),
                source_name="source.mp4",
                status="processing",
            )
            job.steps = [
                JobStep(
                    job_id=job.id,
                    step_name=step_name,
                    status="done",
                    metadata_={"progress": 1.0},
                )
                for step_name in jobs_api._MANUAL_EDITOR_REQUIRED_STEPS
            ]
            session.add(job)
            session.add(Artifact(job_id=job.id, artifact_type="media_meta", data_json={"duration_sec": 1.0}))
            await session.commit()

            readiness = await jobs_api._build_manual_editor_readiness(job=job, session=session)

            assert readiness.status == "preprocessing"
            assert readiness.can_open_editor is False
            assert readiness.progress_percent < 100
            assert readiness.current_step == "editorial_timeline"
            assert readiness.missing == ["editorial_timeline", "render_plan"]
            assert "剪辑时间线、渲染计划" in str(readiness.detail)

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_manual_editor_readiness_ready_clears_current_step(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        source_path = tmp_path / "source.mp4"
        source_path.write_bytes(b"video")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            job = Job(
                id=uuid.uuid4(),
                source_path=str(source_path),
                source_name="source.mp4",
                status="awaiting_manual_edit",
            )
            job.steps = [
                JobStep(
                    job_id=job.id,
                    step_name=step_name,
                    status="pending" if step_name == "summary_review" else "done",
                    metadata_={"progress": 0.0 if step_name == "summary_review" else 1.0},
                )
                for step_name in jobs_api._MANUAL_EDITOR_REQUIRED_STEPS
            ]
            session.add(job)
            session.add_all(
                [
                    Artifact(job_id=job.id, artifact_type="media_meta", data_json={"duration_sec": 1.0}),
                    Timeline(job_id=job.id, timeline_type="editorial", version=1, data_json={"segments": []}),
                    Timeline(job_id=job.id, timeline_type="render_plan", version=1, data_json={}),
                ]
            )
            await session.commit()

            readiness = await jobs_api._build_manual_editor_readiness(job=job, session=session)

            assert readiness.status == "ready"
            assert readiness.can_open_editor is True
            assert readiness.current_step is None
            assert readiness.progress_percent == 100

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())
