from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from roughcut.api import jobs as jobs_api
from roughcut.db.models import Artifact, Job, JobStep, SubtitleItem, Timeline, TranscriptSegment
from roughcut.db.session import Base
from roughcut.edit.cut_analysis import CUT_ANALYSIS_SCHEMA_VERSION
from roughcut.speech.subtitle_pipeline import (
    ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
    ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,
)


def _required_step_entries(job_id: uuid.UUID) -> list[tuple[str, str, dict]]:
    return [
        (step_name, "done" if step_name != "render" else "pending", {"progress": 1.0 if step_name != "render" else 0.12})
        for step_name in jobs_api._MANUAL_EDITOR_REQUIRED_STEPS
    ]


def test_manual_editor_session_ready_for_realistic_job(tmp_path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            source_path = tmp_path / "demo.mp4"
            source_path.write_bytes(b"video")
            job = Job(
                id=uuid.uuid4(),
                source_path=str(source_path),
                source_name="demo.mp4",
                status="awaiting_manual_edit",
            )
            job.steps = [
                JobStep(
                    job_id=job.id,
                    step_name=step_name,
                    status=status,
                    metadata_=metadata,
                )
                for step_name, status, metadata in _required_step_entries(job.id)
            ]
            session.add(job)
            session.add(
                Timeline(
                    job_id=job.id,
                    timeline_type="editorial",
                    version=1,
                    data_json={
                        "segments": [
                            {"type": "keep", "start": 0.0, "end": 4.8, "reason": "manual_editor_keep"},
                        ],
                        "subtitle_projection": {
                            "overrides": [
                                {
                                    "index": 0,
                                    "start_time": 0.0,
                                    "end_time": 2.4,
                                    "text_final": "开场白",
                                }
                            ],
                            "items": [
                                {
                                    "index": 0,
                                    "start_time": 0.0,
                                    "end_time": 2.4,
                                    "text_raw": "开场白",
                                    "text_norm": "开场白",
                                    "text_final": "开场白",
                                },
                                {
                                    "index": 1,
                                    "start_time": 2.4,
                                    "end_time": 4.8,
                                    "text_raw": "这是测试内容",
                                    "text_norm": "这是测试内容",
                                    "text_final": "这是测试内容",
                                },
                            ],
                        },
                        "analysis": {
                            "schema": CUT_ANALYSIS_SCHEMA_VERSION,
                            "accepted_cuts": [
                                {
                                    "start": 2.4,
                                    "end": 2.45,
                                    "reason": "filler_word",
                                    "source_text": "嗯",
                                    "filler_mode": "standalone",
                                    "auto_applied": False,
                                    "risk_level": "low",
                                }
                            ],
                            "rule_candidates": [
                                {
                                    "start": 1.8,
                                    "end": 1.84,
                                    "reason": "filler_word",
                                    "source_text": "啊",
                                    "filler_mode": "standalone",
                                    "risk_level": "low",
                                }
                            ],
                            "source_timeline_contract": {
                                "source_timeline_basis": "canonical_transcript",
                            },
                        },
                    },
                )
            )
            session.add(
                Timeline(
                    job_id=job.id,
                    timeline_type="render_plan",
                    version=1,
                    data_json={
                        "manual_editor": {"video_transform": {"rotation_manual": False}},
                        "loudness": {"target_lufs": -18.0},
                        "voice_processing": {"deesser": True},
                    },
                )
            )
            session.add_all(
                [
                    Artifact(
                        job_id=job.id,
                        artifact_type="media_meta",
                        data_json={"duration_sec": 4.8},
                    ),
                    Artifact(
                        job_id=job.id,
                        artifact_type=ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
                        data_json={
                            "alignment_engine_version": "20260607_alignment_v3",
                            "segments": [
                                {
                                    "index": 0,
                                    "start": 0.0,
                                    "end": 2.4,
                                    "text": "开场白",
                                    "text_raw": "开场白",
                                    "text_canonical": "开场白",
                                },
                                {
                                    "index": 1,
                                    "start": 2.4,
                                    "end": 4.8,
                                    "text": "这是测试内容",
                                    "text_raw": "这是测试内容",
                                    "text_canonical": "这是测试内容",
                                },
                            ],
                        },
                    ),
                    TranscriptSegment(
                        job_id=job.id,
                        version=1,
                        segment_index=0,
                        start_time=0.0,
                        end_time=2.4,
                        text="开场白",
                        words_json=[{"word": "开场白", "start": 0.0, "end": 2.4}],
                    ),
                    TranscriptSegment(
                        job_id=job.id,
                        version=1,
                        segment_index=1,
                        start_time=2.4,
                        end_time=4.8,
                        text="这是测试内容",
                        words_json=[{"word": "这是测试内容", "start": 2.4, "end": 4.8}],
                    ),
                    SubtitleItem(
                        job_id=job.id,
                        version=1,
                        item_index=0,
                        start_time=0.0,
                        end_time=2.4,
                        text_raw="开场白",
                        text_norm="开场白",
                        text_final="开场白",
                    ),
                ]
            )
            await session.commit()

            readiness = await jobs_api._build_manual_editor_readiness(job=job, session=session)
            assert readiness.status == "ready"
            assert readiness.can_open_editor is True
            assert readiness.progress_percent == 100

            session_payload = await jobs_api._build_manual_editor_session(job=job, session=session)
            assert session_payload.job_id == str(job.id)
            assert len(session_payload.source_subtitles) > 0
            assert len(session_payload.projected_subtitles) > 0
            assert session_payload.cut_analysis is not None
            assert session_payload.cut_analysis["schema"] == CUT_ANALYSIS_SCHEMA_VERSION
            assert session_payload.editable is True

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_manual_editor_session_fallbacks_without_projection_artifact(tmp_path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            source_path = tmp_path / "fallback.mp4"
            source_path.write_bytes(b"video")
            job = Job(
                id=uuid.uuid4(),
                source_path=str(source_path),
                source_name="fallback.mp4",
                status="awaiting_manual_edit",
            )
            job.steps = [
                JobStep(
                    job_id=job.id,
                    step_name=step_name,
                    status=status,
                    metadata_=metadata,
                )
                for step_name, status, metadata in _required_step_entries(job.id)
            ]
            session.add(job)
            session.add(
                Timeline(
                    job_id=job.id,
                    timeline_type="editorial",
                    version=1,
                    data_json={
                        "segments": [{"type": "keep", "start": 0.0, "end": 1.2, "reason": "manual_editor_keep"}],
                    },
                )
            )
            session.add(
                Timeline(
                    job_id=job.id,
                    timeline_type="render_plan",
                    version=1,
                    data_json={},
                )
            )
            session.add_all(
                [
                    Artifact(
                        job_id=job.id,
                        artifact_type="media_meta",
                        data_json={"duration_sec": 1.2},
                    ),
                    SubtitleItem(
                        job_id=job.id,
                        version=1,
                        item_index=0,
                        start_time=0.0,
                        end_time=1.2,
                        text_raw="这是备选字幕行",
                        text_norm="这是备选字幕行",
                        text_final="这是备选字幕行",
                    ),
                    TranscriptSegment(
                        job_id=job.id,
                        version=1,
                        segment_index=0,
                        start_time=0.0,
                        end_time=1.2,
                        text="这是备选字幕行",
                        words_json=[{"word": "这是备选字幕行", "start": 0.0, "end": 1.2}],
                    ),
                ]
            )
            await session.commit()

            readiness = await jobs_api._build_manual_editor_readiness(job=job, session=session)
            assert readiness.status == "ready"
            assert readiness.current_step is None

            session_payload = await jobs_api._build_manual_editor_session(job=job, session=session)
            assert session_payload.job_id == str(job.id)
            assert session_payload.source_subtitles
            assert session_payload.source_subtitles[0].text_final == "这是备选字幕行"
            assert session_payload.cut_analysis is not None
            assert session_payload.cut_analysis["schema"] == CUT_ANALYSIS_SCHEMA_VERSION

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_manual_editor_session_fallbacks_to_source_when_projection_is_suspicious(tmp_path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            source_path = tmp_path / "suspicious.mp4"
            source_path.write_bytes(b"video")
            job = Job(
                id=uuid.uuid4(),
                source_path=str(source_path),
                source_name="suspicious.mp4",
                status="awaiting_manual_edit",
            )
            job.steps = [
                JobStep(
                    job_id=job.id,
                    step_name=step_name,
                    status=status,
                    metadata_=metadata,
                )
                for step_name, status, metadata in _required_step_entries(job.id)
            ]
            session.add(job)
            session.add(
                Timeline(
                    job_id=job.id,
                    timeline_type="editorial",
                    version=1,
                    data_json={
                        "segments": [
                            {"type": "keep", "start": 0.0, "end": 9.0, "reason": "manual_editor_keep"},
                        ],
                        "analysis": {
                            "schema": CUT_ANALYSIS_SCHEMA_VERSION,
                            "accepted_cuts": [],
                            "rule_candidates": [],
                            "source_timeline_contract": {
                                "source_timeline_basis": "canonical_transcript",
                            },
                        },
                    },
                )
            )
            session.add(
                Timeline(
                    job_id=job.id,
                    timeline_type="render_plan",
                    version=1,
                    data_json={
                        "manual_editor": {},
                        "loudness": {"target_lufs": -18.0},
                    },
                )
            )
            session.add_all(
                [
                    Artifact(
                        job_id=job.id,
                        artifact_type="media_meta",
                        data_json={"duration_sec": 9.0},
                    ),
                    Artifact(
                        job_id=job.id,
                        artifact_type=ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,
                        data_json={
                            "segmentation_engine_version": "3",
                            "split_profile_version": "1",
                            "transcript_layer": "canonical_transcript",
                            "split_profile": {"max_chars": 30, "max_duration": 3.0},
                            "entries": [
                                {
                                    "index": 0,
                                    "start_time": 0.0,
                                    "end_time": 8.4,
                                    "text_raw": "啊",
                                    "text_norm": "啊",
                                    "text_final": "啊",
                                    "transcript_layer": "canonical_transcript",
                                },
                                {
                                    "index": 0,
                                    "start_time": 0.8,
                                    "end_time": 9.0,
                                    "text_raw": "嗯",
                                    "text_norm": "嗯",
                                    "text_final": "嗯",
                                    "transcript_layer": "canonical_transcript",
                                },
                            ],
                        },
                    ),
                    Artifact(
                        job_id=job.id,
                        artifact_type=ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
                        data_json={
                            "alignment_engine_version": "20260607_alignment_v3",
                            "segments": [
                                {
                                    "index": 0,
                                    "start": 0.0,
                                    "end": 4.5,
                                    "text": "这是测试",
                                    "text_raw": "这是测试",
                                    "text_canonical": "这是测试",
                                },
                                {
                                    "index": 1,
                                    "start": 4.5,
                                    "end": 9.0,
                                    "text": "正常句子",
                                    "text_raw": "正常句子",
                                    "text_canonical": "正常句子",
                                },
                            ],
                        },
                    ),
                    TranscriptSegment(
                        job_id=job.id,
                        version=1,
                        segment_index=0,
                        start_time=0.0,
                        end_time=4.5,
                        text="这是测试",
                        words_json=[
                            {"word": "这", "start": 0.0, "end": 0.2},
                            {"word": "是", "start": 0.2, "end": 0.4},
                            {"word": "测", "start": 0.4, "end": 0.6},
                            {"word": "试", "start": 0.6, "end": 1.0},
                        ],
                    ),
                    TranscriptSegment(
                        job_id=job.id,
                        version=1,
                        segment_index=1,
                        start_time=4.5,
                        end_time=9.0,
                        text="正常句子",
                        words_json=[
                            {"word": "正", "start": 4.5, "end": 4.7},
                            {"word": "常", "start": 4.7, "end": 4.9},
                            {"word": "句", "start": 4.9, "end": 5.2},
                            {"word": "子", "start": 5.2, "end": 5.6},
                        ],
                    ),
                ]
            )
            await session.commit()

            readiness = await jobs_api._build_manual_editor_readiness(job=job, session=session)
            assert readiness.status == "ready"
            assert readiness.can_open_editor is True

            session_payload = await jobs_api._build_manual_editor_session(job=job, session=session)
            assert session_payload.projected_subtitles
            assert session_payload.source_subtitle_basis in {"canonical_transcript", "transcript_segment"}
            assert session_payload.projection_diagnostics["source_projection_fallback_applied"] is True
            assert session_payload.projection_diagnostics["source_fallback_projection_count"] >= 2
            assert [item.text_final for item in session_payload.projected_subtitles] == [
                item.text_final for item in session_payload.source_subtitles
            ]
            assert [item.text_final for item in session_payload.source_subtitles] == ["这是测试", "正常句子"]
            assert session_payload.editable is True

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_manual_editor_session_degraded_missing_render_plan(tmp_path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            source_path = tmp_path / "without_render_plan.mp4"
            source_path.write_bytes(b"video")
            job = Job(
                id=uuid.uuid4(),
                source_path=str(source_path),
                source_name="without_render_plan.mp4",
                status="awaiting_manual_edit",
            )
            job.steps = [
                JobStep(
                    job_id=job.id,
                    step_name=step_name,
                    status=status,
                    metadata_=metadata,
                )
                for step_name, status, metadata in _required_step_entries(job.id)
            ]
            session.add(job)
            session.add(
                Timeline(
                    job_id=job.id,
                    timeline_type="editorial",
                    version=1,
                    data_json={
                        "segments": [
                            {"type": "keep", "start": 0.0, "end": 1.8, "reason": "manual_editor_keep"},
                        ],
                    },
                )
            )
            session.add(
                Artifact(
                    job_id=job.id,
                    artifact_type="media_meta",
                    data_json={"duration_sec": 1.8},
                )
            )
            session.add(
                TranscriptSegment(
                    job_id=job.id,
                    version=1,
                    segment_index=0,
                    start_time=0.0,
                    end_time=1.8,
                    text="这是缺失渲染计划的测试",
                    words_json=[
                        {"word": "这是", "start": 0.0, "end": 0.8},
                        {"word": "测试", "start": 0.8, "end": 1.8},
                    ],
                )
            )
            session.add(
                SubtitleItem(
                    job_id=job.id,
                    version=1,
                    item_index=0,
                    start_time=0.0,
                    end_time=1.8,
                    text_raw="这是缺失渲染计划的测试",
                    text_norm="这是缺失渲染计划的测试",
                    text_final="这是缺失渲染计划的测试",
                )
            )
            await session.commit()

            readiness = await jobs_api._build_manual_editor_readiness(job=job, session=session)
            assert readiness.status == "preprocessing"
            assert readiness.can_open_editor is False
            assert readiness.missing == ["render_plan"]
            assert readiness.current_step == "render_plan"

            session_payload = await jobs_api._build_manual_editor_session(job=job, session=session)
            assert session_payload.job_id == str(job.id)
            assert session_payload.render_plan_version is None
            assert session_payload.source_subtitles
            assert session_payload.source_subtitles[0].text_final == "这是缺失渲染计划的测试"
            assert session_payload.cut_analysis["schema"] == CUT_ANALYSIS_SCHEMA_VERSION
            assert session_payload.source_duration_sec == 1.8

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_manual_editor_session_validation_stays_non_mutating_and_fallback_explicit(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        validation_calls: list[dict[str, object]] = []

        def _fake_validate(
            projected_subtitles: list[dict[str, object]],
            *,
            source_subtitles: list[dict[str, object]],
            keep_segments: list[dict[str, object]],
            fallback_source_subtitles: list[dict[str, object]] | None = None,
            apply_annotation_repair: bool = False,
        ) -> SimpleNamespace:
            validation_calls.append(
                {
                    "fallback_source_subtitles": fallback_source_subtitles,
                    "apply_annotation_repair": apply_annotation_repair,
                    "projected_subtitles": list(projected_subtitles),
                }
            )
            return SimpleNamespace(
                mismatch_detected=True,
                fallback_used=False,
                subtitles=[
                    {
                        "index": 99,
                        "start_time": 0.0,
                        "end_time": 1.0,
                        "text_final": "不应自动显示的修复结果",
                    }
                ],
                changed=True,
                input_count=len(projected_subtitles),
                output_count=1,
            )

        monkeypatch.setattr(jobs_api, "validate_projected_subtitles_against_source", _fake_validate)
        monkeypatch.setattr(jobs_api, "_manual_editor_should_apply_source_projection_fallback", lambda *_args, **_kwargs: False)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            source_path = tmp_path / "non_mutating_validation.mp4"
            source_path.write_bytes(b"video")
            job = Job(
                id=uuid.uuid4(),
                source_path=str(source_path),
                source_name="non_mutating_validation.mp4",
                status="awaiting_manual_edit",
            )
            job.steps = [
                JobStep(
                    job_id=job.id,
                    step_name=step_name,
                    status=status,
                    metadata_=metadata,
                )
                for step_name, status, metadata in _required_step_entries(job.id)
            ]
            session.add(job)
            session.add(
                Timeline(
                    job_id=job.id,
                    timeline_type="editorial",
                    version=1,
                    data_json={
                        "segments": [{"type": "keep", "start": 0.0, "end": 4.0}],
                        "analysis": {
                            "schema": CUT_ANALYSIS_SCHEMA_VERSION,
                            "accepted_cuts": [],
                            "rule_candidates": [],
                            "source_timeline_contract": {"source_timeline_basis": "canonical_transcript"},
                        },
                    },
                )
            )
            session.add(
                Timeline(
                    job_id=job.id,
                    timeline_type="render_plan",
                    version=1,
                    data_json={"subtitles": {}, "audio": {}, "loudness": {}, "voice_processing": {}},
                )
            )
            session.add(
                Artifact(
                    job_id=job.id,
                    artifact_type="media_meta",
                    data_json={"duration_sec": 4.0},
                )
            )
            session.add(
                Artifact(
                    job_id=job.id,
                    artifact_type=ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
                    data_json={
                        "alignment_engine_version": "test",
                        "segments": [
                            {
                                "index": 0,
                                "start": 0.0,
                                "end": 2.0,
                                "text_raw": "第一句",
                                "text_canonical": "第一句",
                                "words": [{"word": "第一句", "start": 0.0, "end": 2.0}],
                            },
                            {
                                "index": 1,
                                "start": 2.0,
                                "end": 4.0,
                                "text_raw": "第二句",
                                "text_canonical": "第二句",
                                "words": [{"word": "第二句", "start": 2.0, "end": 4.0}],
                            },
                        ],
                    },
                )
            )
            session.add(
                Artifact(
                    job_id=job.id,
                    artifact_type=ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,
                    data_json={
                        "transcript_layer": "canonical_transcript",
                        "entries": [
                            {"index": 0, "start_time": 0.0, "end_time": 2.0, "text_raw": "第一句", "text_norm": "第一句", "text_final": "第一句"},
                            {"index": 1, "start_time": 2.0, "end_time": 4.0, "text_raw": "第二句", "text_norm": "第二句", "text_final": "第二句"},
                        ],
                    },
                )
            )
            session.add(
                TranscriptSegment(
                    job_id=job.id,
                    version=1,
                    segment_index=0,
                    start_time=0.0,
                    end_time=2.0,
                    text="第一句",
                    words_json=[{"word": "第一句", "start": 0.0, "end": 2.0}],
                )
            )
            session.add(
                TranscriptSegment(
                    job_id=job.id,
                    version=1,
                    segment_index=1,
                    start_time=2.0,
                    end_time=4.0,
                    text="第二句",
                    words_json=[{"word": "第二句", "start": 2.0, "end": 4.0}],
                )
            )
            await session.commit()

            session_payload = await jobs_api._build_manual_editor_session(job=job, session=session)

            assert validation_calls
            assert validation_calls[0]["fallback_source_subtitles"] is None
            assert validation_calls[0]["apply_annotation_repair"] is False
            assert [item.text_final for item in session_payload.projected_subtitles] == ["第一句", "第二句"]
            assert session_payload.projection_diagnostics["projection_validation_fallback_used"] is False
            assert session_payload.projection_diagnostics["source_projection_fallback_applied"] is False

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_manual_editor_session_degraded_invalid_cut_analysis_payloads_are_tolerated(tmp_path) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            source_path = tmp_path / "invalid_cut_analysis.mp4"
            source_path.write_bytes(b"video")
            job = Job(
                id=uuid.uuid4(),
                source_path=str(source_path),
                source_name="invalid_cut_analysis.mp4",
                status="awaiting_manual_edit",
            )
            job.steps = [
                JobStep(
                    job_id=job.id,
                    step_name=step_name,
                    status=status,
                    metadata_=metadata,
                )
                for step_name, status, metadata in _required_step_entries(job.id)
            ]
            session.add(job)
            session.add(
                Timeline(
                    job_id=job.id,
                    timeline_type="editorial",
                    version=1,
                    data_json={
                        "segments": [
                            {"type": "keep", "start": 0.0, "end": 1.6, "reason": "manual_editor_keep"},
                        ],
                        "analysis": {
                            "schema": CUT_ANALYSIS_SCHEMA_VERSION,
                            "accepted_cuts": [
                                {
                                    "start": 0.3,
                                    "end": 0.5,
                                    "reason": "filler_word",
                                    "source_text": "嗯",
                                    "filler_mode": "standalone",
                                    "auto_applied": False,
                                    "risk_level": "low",
                                }
                            ],
                            "rule_candidates": [],
                            "source_timeline_contract": {
                                "source_timeline_basis": "canonical_transcript",
                            },
                        },
                    },
                )
            )
            session.add(
                Timeline(
                    job_id=job.id,
                    timeline_type="render_plan",
                    version=1,
                    data_json={},
                )
            )
            session.add(
                Artifact(
                    job_id=job.id,
                    artifact_type="media_meta",
                    data_json={"duration_sec": 1.6},
                )
            )
            session.add(
                Artifact(
                    job_id=job.id,
                    artifact_type=jobs_api.ARTIFACT_TYPE_CUT_ANALYSIS,
                    data_json={"schema": "legacy_schema", "accepted_cuts": "nonsense"},
                )
            )
            session.add(
                TranscriptSegment(
                    job_id=job.id,
                    version=1,
                    segment_index=0,
                    start_time=0.0,
                    end_time=1.6,
                    text="开头我先说一段",
                    words_json=[
                        {"word": "开头", "start": 0.0, "end": 0.8},
                        {"word": "我", "start": 0.8, "end": 1.2},
                        {"word": "先", "start": 1.2, "end": 1.6},
                    ],
                )
            )
            await session.commit()

            readiness = await jobs_api._build_manual_editor_readiness(job=job, session=session)
            assert readiness.status == "ready"
            assert readiness.can_open_editor is True

            session_payload = await jobs_api._build_manual_editor_session(job=job, session=session)
            assert session_payload.job_id == str(job.id)
            assert session_payload.cut_analysis["schema"] == CUT_ANALYSIS_SCHEMA_VERSION
            assert session_payload.cut_analysis["accepted_cuts"]
            assert session_payload.cut_analysis["accepted_cuts"][0]["source_text"] == "嗯"
            assert session_payload.source_subtitle_basis in {"transcript_segment", "canonical_transcript"}

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())
