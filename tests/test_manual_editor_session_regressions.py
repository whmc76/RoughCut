from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from roughcut.api import jobs as jobs_api
from roughcut.db.models import Artifact, Job, JobStep, SubtitleItem, Timeline, TranscriptSegment
from roughcut.db.session import Base
from roughcut.edit.cut_analysis import CUT_ANALYSIS_SCHEMA_VERSION, build_cut_analysis_payload
from roughcut.pipeline import steps as pipeline_steps
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


def test_manual_editor_session_reuses_render_plan_context_for_video_transform_and_audio_defaults(tmp_path, monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    captured_video_transforms: list[dict] = []
    captured_render_plan_contexts: list[dict] = []
    render_plan_payloads: list[object] = []
    cut_analysis_editorial_payloads: list[object] = []

    monkeypatch.setattr(
        jobs_api,
        "_manual_editor_render_plan_context",
        lambda _payload: {
            "video_transform": {
                "rotation_manual": True,
                "rotation_cw": 90,
                "aspect_ratio": "9:16",
                "resolution_mode": "specified",
                "resolution_preset": "1440p",
            },
            "loudness": {"target_lufs": -18.0},
            "voice_processing": {"noise_reduction": True},
        },
    )

    def _capture_manual_video_transform(
        _render_plan: dict | None,
        *,
        render_plan_context: dict | None = None,
        video_transform: dict | None = None,
    ) -> dict:
        render_plan_payloads.append(_render_plan)
        assert isinstance(render_plan_context, dict)
        assert video_transform is None
        captured_render_plan_contexts.append(dict(render_plan_context))
        captured_video_transforms.append(dict(render_plan_context.get("video_transform") or {}))
        return dict(render_plan_context.get("video_transform") or {})

    monkeypatch.setattr(
        jobs_api,
        "_manual_video_transform_from_render_plan",
        _capture_manual_video_transform,
    )

    async def _capture_cut_analysis_payload(_session, **kwargs):
        cut_analysis_editorial_payloads.append(kwargs.get("editorial_timeline_payload"))
        return build_cut_analysis_payload(
            editorial_analysis=dict(kwargs.get("editorial_analysis") or {}),
            source_name="context_reuse.mp4",
            job_flow_mode="auto",
            source_subtitles=[],
            smart_cut_rules=None,
            content_profile=None,
        )

    monkeypatch.setattr(
        jobs_api,
        "_load_manual_editor_cut_analysis_payload",
        _capture_cut_analysis_payload,
    )

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            source_path = tmp_path / "context_reuse.mp4"
            source_path.write_bytes(b"video")
            job = Job(
                id=uuid.uuid4(),
                source_path=str(source_path),
                source_name="context_reuse.mp4",
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
                    data_json={
                        "manual_editor": {
                            "video_transform": {
                                "rotation_manual": True,
                                "rotation_cw": 90,
                                "aspect_ratio": "9:16",
                                "resolution_mode": "specified",
                                "resolution_preset": "1440p",
                            }
                        },
                        "loudness": {"target_lufs": -18.0},
                        "voice_processing": {"noise_reduction": True},
                    },
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

            session_payload = await jobs_api._build_manual_editor_session(job=job, session=session)

            assert captured_video_transforms == [
                {
                    "rotation_manual": True,
                    "rotation_cw": 90,
                    "aspect_ratio": "9:16",
                    "resolution_mode": "specified",
                    "resolution_preset": "1440p",
                }
            ]
            assert captured_render_plan_contexts == [
                {
                    "video_transform": {
                        "rotation_manual": True,
                        "rotation_cw": 90,
                        "aspect_ratio": "9:16",
                        "resolution_mode": "specified",
                        "resolution_preset": "1440p",
                    },
                    "loudness": {"target_lufs": -18.0},
                    "voice_processing": {"noise_reduction": True},
                }
            ]
            assert render_plan_payloads == [None]
            assert cut_analysis_editorial_payloads == [None]
            assert session_payload.base_video_transform.rotation_cw == 90
            assert session_payload.base_video_transform.aspect_ratio == "9:16"
            assert session_payload.refine_decision_plan["audio_defaults"] == {
                "target_lufs": -18.0,
                "noise_reduction": True,
            }

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
            assert session_payload.projection_diagnostics["source_projection_fallback_applied"] is False
            assert session_payload.projection_diagnostics["display_projection_basis"] == "source_timeline_projection"
            assert session_payload.projection_diagnostics["source_fallback_projection_count"] >= 2
            assert [item.text_final for item in session_payload.source_subtitles] == ["这是测试", "正常句子"]
            assert [item.text_final for item in session_payload.projected_subtitles] == [
                item.text_final for item in session_payload.source_subtitles
            ]
            assert session_payload.editable is True

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_manual_editor_session_validates_the_same_source_fallback_projection_it_displays(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        validation_inputs: list[list[str]] = []

        def _fake_validate(
            projected_subtitles: list[dict[str, object]],
            *,
            source_subtitles: list[dict[str, object]],
            keep_segments: list[dict[str, object]],
            fallback_source_subtitles: list[dict[str, object]] | None = None,
            apply_annotation_repair: bool = False,
        ) -> SimpleNamespace:
            validation_inputs.append([str(item.get("text_final") or "") for item in projected_subtitles])
            return SimpleNamespace(
                mismatch_detected=False,
                fallback_used=False,
                subtitles=list(projected_subtitles),
                changed=False,
                input_count=len(projected_subtitles),
                output_count=len(projected_subtitles),
            )

        monkeypatch.setattr(jobs_api, "validate_projected_subtitles_against_source", _fake_validate)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            source_path = tmp_path / "suspicious-validated.mp4"
            source_path.write_bytes(b"video")
            job = Job(
                id=uuid.uuid4(),
                source_path=str(source_path),
                source_name="suspicious-validated.mp4",
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
                    data_json={"manual_editor": {}, "loudness": {"target_lufs": -18.0}},
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
                            "entries": [
                                {"index": 0, "start_time": 0.0, "end_time": 8.4, "text_raw": "啊", "text_norm": "啊", "text_final": "啊"},
                                {"index": 0, "start_time": 0.8, "end_time": 9.0, "text_raw": "嗯", "text_norm": "嗯", "text_final": "嗯"},
                            ],
                        },
                    ),
                    Artifact(
                        job_id=job.id,
                        artifact_type=ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
                        data_json={
                            "alignment_engine_version": "20260607_alignment_v3",
                            "segments": [
                                {"index": 0, "start": 0.0, "end": 4.5, "text": "这是测试", "text_raw": "这是测试", "text_canonical": "这是测试"},
                                {"index": 1, "start": 4.5, "end": 9.0, "text": "正常句子", "text_raw": "正常句子", "text_canonical": "正常句子"},
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
                        words_json=[{"word": "这", "start": 0.0, "end": 0.2}],
                    ),
                    TranscriptSegment(
                        job_id=job.id,
                        version=1,
                        segment_index=1,
                        start_time=4.5,
                        end_time=9.0,
                        text="正常句子",
                        words_json=[{"word": "正", "start": 4.5, "end": 4.7}],
                    ),
                ]
            )
            await session.commit()

            session_payload = await jobs_api._build_manual_editor_session(job=job, session=session)

            assert validation_inputs == [["这是测试", "正常句子"]]
            assert [item.text_final for item in session_payload.projected_subtitles] == ["这是测试", "正常句子"]
            assert session_payload.editable is True
            assert session_payload.detail is None

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


def test_manual_editor_apply_keeps_frontend_managed_auto_cuts_out_of_subtitle_only_change_scope(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        rerun_plans: list[object] = []
        multimodal_review_calls: list[dict[str, object]] = []
        packaging_resolve_calls: list[dict[str, object]] = []
        insert_plan_calls: list[dict[str, object]] = []
        music_plan_calls: list[dict[str, object]] = []
        timeline_analysis_calls: list[dict[str, object]] = []
        editing_accents_calls: list[dict[str, object]] = []
        packaging_helper_calls: dict[str, list[dict[str, object]]] = {
            "editing_skill": [],
            "editing_accents": [],
            "timeline_analysis": [],
            "subtitles": [],
        }
        packaging_helper_calls: dict[str, list[dict[str, object]]] = {
            "editing_skill": [],
            "editing_accents": [],
            "timeline_analysis": [],
            "subtitles": [],
        }
        video_transform_render_payloads: list[object] = []
        video_transform_inputs: list[dict[str, object]] = []
        packaging_plan_render_payloads: list[object] = []
        packaging_plan_inputs: list[dict[str, object]] = []
        refine_render_plan_payloads: list[object] = []
        captured_editorial_analyses: list[dict[str, object] | None] = []
        captured_editorial_payloads: list[object] = []
        cut_payload = build_cut_analysis_payload(
            editorial_analysis={
                "accepted_cuts": [
                    {"start": 1.0, "end": 1.3, "reason": "filler_word", "auto_applied": True},
                ],
            },
            source_name="apply-demo.mp4",
            job_flow_mode="auto",
        )

        async def _fake_load_source_subtitles(_session, *, job):
            return [
                {
                    "index": 0,
                    "start_time": 0.0,
                    "end_time": 5.0,
                    "text_raw": "原始字幕",
                    "text_norm": "原始字幕",
                    "text_final": "原始字幕",
                    "projection_source": "transcript_segment",
                }
            ]

        async def _fake_load_profile(_session, *, job_id):
            return None, {}

        async def _fake_load_cut_analysis_payload(_session, **_kwargs):
            captured_editorial_payloads.append(_kwargs.get("editorial_timeline_payload"))
            editorial_analysis = _kwargs.get("editorial_analysis")
            captured_editorial_analyses.append(
                dict(editorial_analysis) if isinstance(editorial_analysis, dict) else editorial_analysis
            )
            return dict(cut_payload)

        async def _fake_review_multimodal(payload, **_kwargs):
            multimodal_review_calls.append(dict(payload))
            return payload

        async def _fake_insert_asset_slot(**_kwargs):
            insert_plan_calls.append(dict(_kwargs))
            return None

        async def _fake_plan_music_entry(**_kwargs):
            music_plan_calls.append(dict(_kwargs))
            return None

        async def _fake_noop(*_args, **_kwargs):
            return None

        async def _fake_execute_job_rerun_plan(_session, *, job, steps, plan, via):
            rerun_plans.append(plan)

        original_packaging_plan_from_render_plan = jobs_api._manual_editor_packaging_plan_from_render_plan
        original_manual_video_transform_from_render_plan = jobs_api._manual_video_transform_from_render_plan
        original_manual_editor_build_refine_decision_plan = jobs_api._manual_editor_build_refine_decision_plan_from_render_plan

        def _capture_packaging_plan(render_plan, **kwargs):
            packaging_plan_render_payloads.append(render_plan)
            packaging_plan_inputs.append(
                {
                    "packaging_timeline": kwargs.get("packaging_timeline"),
                    "delivery": kwargs.get("delivery"),
                    "render_plan_context": kwargs.get("render_plan_context"),
                }
            )
            return original_packaging_plan_from_render_plan(render_plan, **kwargs)

        def _capture_manual_video_transform(render_plan, **kwargs):
            video_transform_render_payloads.append(render_plan)
            video_transform_inputs.append(
                {
                    "render_plan_context": kwargs.get("render_plan_context"),
                    "video_transform": kwargs.get("video_transform"),
                }
            )
            return original_manual_video_transform_from_render_plan(render_plan, **kwargs)

        def _capture_refine_decision_plan(**kwargs):
            refine_render_plan_payloads.append(kwargs.get("render_plan_data"))
            return original_manual_editor_build_refine_decision_plan(**kwargs)

        monkeypatch.setattr(jobs_api, "_load_manual_editor_aligned_source_subtitle_dicts", _fake_load_source_subtitles)
        monkeypatch.setattr(jobs_api, "_load_manual_editor_preferred_downstream_profile", _fake_load_profile)
        monkeypatch.setattr(jobs_api, "_load_manual_editor_cut_analysis_payload", _fake_load_cut_analysis_payload)
        monkeypatch.setattr(jobs_api, "validate_projected_subtitles_against_source", lambda subtitles, **_kwargs: SimpleNamespace(
            mismatch_detected=False,
            fallback_used=False,
            subtitles=list(subtitles),
            changed=False,
            input_count=len(subtitles),
            output_count=len(subtitles),
        ))
        monkeypatch.setattr(jobs_api, "review_multimodal_trim_review_payload", _fake_review_multimodal)
        monkeypatch.setattr(jobs_api, "apply_multimodal_trim_review_to_cut_analysis", lambda payload, _review: payload)
        monkeypatch.setattr(
            jobs_api,
            "resolve_packaging_plan_for_job",
            lambda *_args, **_kwargs: (packaging_resolve_calls.append(dict(_kwargs)) or {}),
        )
        monkeypatch.setattr(
            jobs_api,
            "infer_timeline_analysis",
            lambda *_args, **_kwargs: (timeline_analysis_calls.append(dict(_kwargs)) or {"pace": "tight"}),
        )
        monkeypatch.setattr(
            jobs_api,
            "build_smart_editing_accents",
            lambda **_kwargs: (editing_accents_calls.append(dict(_kwargs)) or {"style": "test"}),
        )
        monkeypatch.setattr(pipeline_steps, "_job_creative_profile", lambda _job: {})
        monkeypatch.setattr(pipeline_steps, "_plan_insert_asset_slot", _fake_insert_asset_slot)
        monkeypatch.setattr(pipeline_steps, "_plan_music_entry", _fake_plan_music_entry)
        monkeypatch.setattr(jobs_api, "build_render_plan", lambda **_kwargs: {"delivery": {}, "subtitles": {"version": 1}})
        monkeypatch.setattr(jobs_api, "_manual_editor_packaging_plan_from_render_plan", _capture_packaging_plan)
        monkeypatch.setattr(jobs_api, "_manual_video_transform_from_render_plan", _capture_manual_video_transform)
        monkeypatch.setattr(jobs_api, "_manual_editor_build_refine_decision_plan_from_render_plan", _capture_refine_decision_plan)
        monkeypatch.setattr(jobs_api, "_record_manual_subtitle_replacement_memory", _fake_noop)
        monkeypatch.setattr(jobs_api, "_persist_manual_video_summary_evidence", _fake_noop)
        monkeypatch.setattr(jobs_api, "_persist_manual_video_summary_source_context", _fake_noop)
        monkeypatch.setattr(jobs_api, "touch_runtime_refresh_hold", lambda **_kwargs: None)
        monkeypatch.setattr(jobs_api, "execute_job_rerun_plan", _fake_execute_job_rerun_plan)
        monkeypatch.setattr(jobs_api, "export_to_otio", lambda _payload: None)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            source_path = tmp_path / "apply-demo.mp4"
            source_path.write_bytes(b"video")
            job = Job(
                id=uuid.uuid4(),
                source_path=str(source_path),
                source_name="apply-demo.mp4",
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
                        "source": str(source_path),
                        "segments": [
                            {"type": "keep", "start": 0.0, "end": 1.0, "reason": "manual_editor_keep"},
                            {"type": "keep", "start": 1.3, "end": 5.0, "reason": "manual_editor_keep"},
                        ],
                        "analysis": {
                            "schema": CUT_ANALYSIS_SCHEMA_VERSION,
                            "accepted_cuts": [],
                            "rule_candidates": [],
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
                        "voice_processing": {"noise_reduction": True},
                        "subtitles": {"version": 1},
                    },
                )
            )
            session.add(Artifact(job_id=job.id, artifact_type="media_meta", data_json={"duration_sec": 5.0}))
            await session.commit()

            editorial_timeline = await jobs_api._load_latest_timeline_by_type(session, job_id=job.id, timeline_type="editorial")
            render_plan_timeline = await jobs_api._load_latest_timeline_by_type(session, job_id=job.id, timeline_type="render_plan")
            source_subtitles = await _fake_load_source_subtitles(session, job=job)
            subtitle_fingerprint = jobs_api._manual_editor_subtitle_fingerprint(source_subtitles)

            result = await jobs_api.apply_manual_editor_timeline(
                job.id,
                jobs_api.ManualEditorApplyIn(
                    keep_segments=[{"start": 0.0, "end": 5.0}],
                    subtitle_overrides=[{"index": 0, "text_final": "修改后的字幕"}],
                    base_timeline_id=str(editorial_timeline.id),
                    base_timeline_version=int(editorial_timeline.version or 1),
                    base_render_plan_version=int(render_plan_timeline.version or 1),
                    base_subtitle_fingerprint=subtitle_fingerprint,
                ),
                session=session,
            )

            refine_result = await session.execute(
                select(Artifact)
                .where(
                    Artifact.job_id == job.id,
                    Artifact.artifact_type == jobs_api.ARTIFACT_TYPE_REFINE_DECISION_PLAN,
                )
                .order_by(Artifact.created_at.desc(), Artifact.id.desc())
            )
            refine_artifact = refine_result.scalars().first()
            assert refine_artifact is not None
            refine_payload = refine_artifact.data_json if isinstance(refine_artifact.data_json, dict) else {}

            editorial_result = await session.execute(
                select(Timeline)
                .where(Timeline.job_id == job.id, Timeline.timeline_type == "editorial")
                .order_by(Timeline.version.desc(), Timeline.id.desc())
            )
            latest_editorial = editorial_result.scalars().first()
            editorial_payload = latest_editorial.data_json if latest_editorial and isinstance(latest_editorial.data_json, dict) else {}

            assert result.change_scope == "subtitle_only"
            assert result.render_strategy == "reuse_timeline_effect_plan"
            assert result.keep_segment_count == 2
            assert multimodal_review_calls == []
            assert packaging_resolve_calls == []
            assert insert_plan_calls == []
            assert music_plan_calls == []
            assert timeline_analysis_calls == []
            assert editing_accents_calls == []
            assert video_transform_render_payloads == [None]
            assert len(video_transform_inputs) == 1
            assert video_transform_inputs[0]["video_transform"] is None
            assert video_transform_inputs[0]["render_plan_context"] is not None
            assert video_transform_inputs[0]["render_plan_context"]["video_transform"] == {
                "aspect_ratio": "source",
                "resolution_mode": "source",
                "resolution_preset": "1080p",
            }
            assert video_transform_inputs[0]["render_plan_context"]["loudness"] == {"target_lufs": -18.0}
            assert video_transform_inputs[0]["render_plan_context"]["voice_processing"] == {"noise_reduction": True}
            assert packaging_plan_render_payloads == [None]
            assert len(packaging_plan_inputs) == 1
            assert packaging_plan_inputs[0]["packaging_timeline"] is None
            assert packaging_plan_inputs[0]["delivery"] is None
            assert packaging_plan_inputs[0]["render_plan_context"] is not None
            assert packaging_plan_inputs[0]["render_plan_context"]["packaging_timeline"] == {
                "timeline_analysis": {},
                "editing_skill": {},
                "section_choreography": {},
                "subtitles": {"version": 1},
                "packaging": {
                    "intro": None,
                    "outro": None,
                    "insert": None,
                    "watermark": None,
                    "music": None,
                },
                "editing_accents": {},
            }
            assert packaging_plan_inputs[0]["render_plan_context"]["delivery"] == {}
            assert packaging_plan_inputs[0]["render_plan_context"]["loudness"] == {"target_lufs": -18.0}
            assert packaging_plan_inputs[0]["render_plan_context"]["voice_processing"] == {"noise_reduction": True}
            assert refine_render_plan_payloads == [None]
            assert captured_editorial_payloads == [None, None]
            assert rerun_plans and rerun_plans[-1].issue_codes == ["manual_subtitle_edit"]
            assert refine_payload.get("keep_segments") == [{"start": 0.0, "end": 1.0}, {"start": 1.3, "end": 5.0}]
            assert editorial_payload.get("analysis", {}).get("manual_editor", {}).get("change_scope") == "subtitle_only"
            assert editorial_payload.get("subtitle_projection", {}).get("items", [{}])[0].get("text_final") == "修改后的字幕"
            assert captured_editorial_analyses[0] == {
                "schema": CUT_ANALYSIS_SCHEMA_VERSION,
                "accepted_cuts": [],
                "rule_candidates": [],
            }
            assert captured_editorial_analyses[-1] is not None
            assert captured_editorial_analyses[-1].get("manual_editor", {}).get("change_scope") == "subtitle_only"

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_manual_editor_apply_skips_no_material_change_rerun(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        rerun_plans: list[object] = []
        captured_refine_audio_defaults: list[dict[str, object]] = []
        packaging_helper_calls: dict[str, list[dict[str, object]]] = {
            "editing_skill": [],
            "editing_accents": [],
            "timeline_analysis": [],
            "subtitles": [],
        }

        async def _fake_load_source_subtitles(_session, *, job):
            return [
                {
                    "index": 0,
                    "start_time": 0.0,
                    "end_time": 5.0,
                    "text_raw": "原始字幕",
                    "text_norm": "原始字幕",
                    "text_final": "原始字幕",
                    "projection_source": "transcript_segment",
                }
            ]

        async def _fake_load_profile(_session, *, job_id):
            return None, {}

        async def _fake_load_cut_analysis_payload(_session, **_kwargs):
            return build_cut_analysis_payload(
                editorial_analysis={
                    "accepted_cuts": [],
                    "rule_candidates": [],
                },
                source_name="apply-demo.mp4",
                job_flow_mode="auto",
            )

        async def _fake_noop(*_args, **_kwargs):
            return None

        async def _fake_execute_job_rerun_plan(_session, *, job, steps, plan, via):
            rerun_plans.append(plan)

        monkeypatch.setattr(jobs_api, "_load_manual_editor_aligned_source_subtitle_dicts", _fake_load_source_subtitles)
        monkeypatch.setattr(jobs_api, "_load_manual_editor_preferred_downstream_profile", _fake_load_profile)
        monkeypatch.setattr(jobs_api, "_load_manual_editor_cut_analysis_payload", _fake_load_cut_analysis_payload)
        monkeypatch.setattr(jobs_api, "validate_projected_subtitles_against_source", lambda subtitles, **_kwargs: SimpleNamespace(
            mismatch_detected=False,
            fallback_used=False,
            subtitles=list(subtitles),
            changed=False,
            input_count=len(subtitles),
            output_count=len(subtitles),
        ))
        monkeypatch.setattr(jobs_api, "review_multimodal_trim_review_payload", _fake_noop)
        monkeypatch.setattr(jobs_api, "apply_multimodal_trim_review_to_cut_analysis", lambda payload, _review: payload)
        monkeypatch.setattr(jobs_api, "resolve_packaging_plan_for_job", lambda *_args, **_kwargs: {})
        original_packaging_timeline_editing_skill = jobs_api.packaging_timeline_editing_skill
        original_packaging_timeline_editing_accents = jobs_api.packaging_timeline_editing_accents
        original_packaging_timeline_analysis = jobs_api.packaging_timeline_analysis
        original_packaging_timeline_subtitles = jobs_api.packaging_timeline_subtitles
        monkeypatch.setattr(
            jobs_api,
            "packaging_timeline_editing_skill",
            lambda payload: (
                packaging_helper_calls["editing_skill"].append(dict(payload or {}))
                or original_packaging_timeline_editing_skill(payload)
            ),
        )
        monkeypatch.setattr(
            jobs_api,
            "packaging_timeline_editing_accents",
            lambda payload: (
                packaging_helper_calls["editing_accents"].append(dict(payload or {}))
                or original_packaging_timeline_editing_accents(payload)
            ),
        )
        monkeypatch.setattr(
            jobs_api,
            "packaging_timeline_analysis",
            lambda payload: (
                packaging_helper_calls["timeline_analysis"].append(dict(payload or {}))
                or original_packaging_timeline_analysis(payload)
            ),
        )
        monkeypatch.setattr(
            jobs_api,
            "packaging_timeline_subtitles",
            lambda payload: (
                packaging_helper_calls["subtitles"].append(dict(payload or {}))
                or original_packaging_timeline_subtitles(payload)
            ),
        )
        monkeypatch.setattr(pipeline_steps, "_job_creative_profile", lambda _job: {})
        monkeypatch.setattr(pipeline_steps, "_plan_insert_asset_slot", _fake_noop)
        monkeypatch.setattr(pipeline_steps, "_plan_music_entry", _fake_noop)
        original_render_plan_delivery = jobs_api.render_plan_delivery
        monkeypatch.setattr(
            jobs_api,
            "render_plan_delivery",
            lambda payload: (
                (_ for _ in ()).throw(AssertionError("should not reread rebuilt render-plan delivery"))
                if isinstance(payload, dict) and payload.get("__rebuilt__")
                else original_render_plan_delivery(payload)
            ),
        )
        monkeypatch.setattr(
            jobs_api,
            "build_render_plan",
            lambda **_kwargs: {"__rebuilt__": True, "delivery": {"should_not": "be_read"}, "subtitles": {"version": 1}},
        )
        monkeypatch.setattr(
            jobs_api,
            "build_refine_decision_plan_from_render_plan",
            lambda **kwargs: (
                captured_refine_audio_defaults.append(dict(kwargs.get("audio_defaults") or {}))
                or {"schema": "refine_decision_plan.v1", "audio_defaults": dict(kwargs.get("audio_defaults") or {})}
            ),
        )
        monkeypatch.setattr(jobs_api, "_record_manual_subtitle_replacement_memory", _fake_noop)
        monkeypatch.setattr(jobs_api, "_persist_manual_video_summary_evidence", _fake_noop)
        monkeypatch.setattr(jobs_api, "_persist_manual_video_summary_source_context", _fake_noop)
        monkeypatch.setattr(jobs_api, "touch_runtime_refresh_hold", lambda **_kwargs: None)
        monkeypatch.setattr(jobs_api, "execute_job_rerun_plan", _fake_execute_job_rerun_plan)
        monkeypatch.setattr(jobs_api, "export_to_otio", lambda _payload: None)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            source_path = tmp_path / "apply-demo.mp4"
            source_path.write_bytes(b"video")
            job = Job(
                id=uuid.uuid4(),
                source_path=str(source_path),
                source_name="apply-demo.mp4",
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
                        "source": str(source_path),
                        "segments": [
                            {"type": "keep", "start": 0.0, "end": 1.0, "reason": "manual_editor_keep"},
                            {"type": "keep", "start": 1.3, "end": 5.0, "reason": "manual_editor_keep"},
                        ],
                        "analysis": {
                            "schema": CUT_ANALYSIS_SCHEMA_VERSION,
                            "accepted_cuts": [],
                            "rule_candidates": [],
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
                        "voice_processing": {"noise_reduction": True},
                        "subtitles": {"version": 1},
                    },
                )
            )
            session.add(Artifact(job_id=job.id, artifact_type="media_meta", data_json={"duration_sec": 5.0}))
            await session.commit()

            editorial_timeline = await jobs_api._load_latest_timeline_by_type(session, job_id=job.id, timeline_type="editorial")
            render_plan_timeline = await jobs_api._load_latest_timeline_by_type(session, job_id=job.id, timeline_type="render_plan")
            source_subtitles = await _fake_load_source_subtitles(session, job=job)
            subtitle_fingerprint = jobs_api._manual_editor_subtitle_fingerprint(source_subtitles)

            result = await jobs_api.apply_manual_editor_timeline(
                job.id,
                jobs_api.ManualEditorApplyIn(
                    keep_segments=[{"start": 0.0, "end": 1.0}, {"start": 1.3, "end": 5.0}],
                    video_summary="新的视频摘要",
                    base_timeline_id=str(editorial_timeline.id),
                    base_timeline_version=int(editorial_timeline.version or 1),
                    base_render_plan_version=int(render_plan_timeline.version or 1),
                    base_subtitle_fingerprint=subtitle_fingerprint,
                ),
                session=session,
            )

            assert result.change_scope == "no_material_change"
            assert result.render_strategy == "metadata_refresh_render"
            assert result.rerun_steps == []
            assert "无需触发剪辑重跑" in str(result.detail)
            assert rerun_plans == []
            assert captured_refine_audio_defaults == [{"target_lufs": -18.0, "noise_reduction": True}]
            assert len(packaging_helper_calls["editing_skill"]) == 1
            assert len(packaging_helper_calls["editing_accents"]) == 1
            assert len(packaging_helper_calls["timeline_analysis"]) == 1
            assert len(packaging_helper_calls["subtitles"]) == 1

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_manual_editor_draft_reuses_editorial_analysis_context_for_cut_analysis_loader(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        captured_editorial_analyses: list[dict[str, object] | None] = []
        captured_refine_render_payloads: list[object] = []
        captured_refine_audio_defaults: list[dict[str, object]] = []
        captured_editorial_payloads: list[object] = []
        captured_render_plan_context_payloads: list[dict[str, object]] = []

        async def _fake_load_source_subtitles(_session, *, job):
            return [
                {
                    "index": 0,
                    "start_time": 0.0,
                    "end_time": 5.0,
                    "text_raw": "原始字幕",
                    "text_norm": "原始字幕",
                    "text_final": "原始字幕",
                }
            ]

        async def _fake_load_cut_analysis_payload(_session, *, editorial_analysis=None, **_kwargs):
            captured_editorial_payloads.append(_kwargs.get("editorial_timeline_payload"))
            captured_editorial_analyses.append(dict(editorial_analysis) if isinstance(editorial_analysis, dict) else editorial_analysis)
            return {
                "schema": CUT_ANALYSIS_SCHEMA_VERSION,
                "accepted_cuts": [],
                "rule_candidates": [],
            }

        async def _fake_noop(*_args, **_kwargs):
            return None

        async def _fake_profile(*_args, **_kwargs):
            return None, {}

        async def _fake_review(*_args, **_kwargs):
            return {}

        monkeypatch.setattr(jobs_api, "_load_manual_editor_aligned_source_subtitle_dicts", _fake_load_source_subtitles)
        monkeypatch.setattr(jobs_api, "_load_manual_editor_cut_analysis_payload", _fake_load_cut_analysis_payload)
        monkeypatch.setattr(jobs_api, "_load_manual_editor_preferred_downstream_profile", _fake_profile)
        monkeypatch.setattr(jobs_api, "review_multimodal_trim_review_payload", _fake_review)
        monkeypatch.setattr(jobs_api, "apply_multimodal_trim_review_to_cut_analysis", lambda payload, _review: payload)
        monkeypatch.setattr(
            jobs_api,
            "_manual_editor_render_plan_context",
            lambda _payload: (
                captured_render_plan_context_payloads.append(dict(_payload or {}))
                or {
                    "loudness": {"target_lufs": -18.0},
                    "voice_processing": {"noise_reduction": True},
                }
            ),
        )
        monkeypatch.setattr(jobs_api, "_persist_manual_video_summary_evidence", _fake_noop)
        monkeypatch.setattr(jobs_api, "_persist_manual_video_summary_source_context", _fake_noop)
        monkeypatch.setattr(
            jobs_api,
            "_manual_editor_build_refine_decision_plan_from_render_plan",
            lambda **_kwargs: (
                captured_refine_render_payloads.append(_kwargs.get("render_plan_data"))
                or captured_refine_audio_defaults.append(dict(_kwargs.get("audio_defaults") or {}))
                or {"schema": "refine_decision_plan.v1"}
            ),
        )

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            source_path = tmp_path / "draft-demo.mp4"
            source_path.write_bytes(b"video")
            job = Job(
                id=uuid.uuid4(),
                source_path=str(source_path),
                source_name="draft-demo.mp4",
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
                            {"type": "keep", "start": 0.0, "end": 5.0, "reason": "manual_editor_keep"},
                        ],
                        "analysis": {
                            "schema": CUT_ANALYSIS_SCHEMA_VERSION,
                            "accepted_cuts": [],
                            "rule_candidates": [],
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
                        "voice_processing": {"noise_reduction": True},
                        "subtitles": {"version": 1},
                    },
                )
            )
            session.add(Artifact(job_id=job.id, artifact_type="media_meta", data_json={"duration_sec": 5.0}))
            await session.commit()

            editorial_timeline = await jobs_api._load_latest_timeline_by_type(session, job_id=job.id, timeline_type="editorial")
            render_plan_timeline = await jobs_api._load_latest_timeline_by_type(session, job_id=job.id, timeline_type="render_plan")
            source_subtitles = await _fake_load_source_subtitles(session, job=job)
            subtitle_fingerprint = jobs_api._manual_editor_subtitle_fingerprint(source_subtitles)

            result = await jobs_api.save_manual_editor_draft(
                job.id,
                jobs_api.ManualEditorApplyIn(
                    keep_segments=[{"start": 0.0, "end": 5.0}],
                    base_timeline_id=str(editorial_timeline.id),
                    base_timeline_version=int(editorial_timeline.version or 1),
                    base_render_plan_version=int(render_plan_timeline.version or 1),
                    base_subtitle_fingerprint=subtitle_fingerprint,
                ),
                session=session,
            )

            assert result.keep_segment_count == 1
            assert captured_editorial_analyses == [
                {
                    "schema": CUT_ANALYSIS_SCHEMA_VERSION,
                    "accepted_cuts": [],
                    "rule_candidates": [],
                }
            ]
            assert captured_editorial_payloads == [None]
            assert captured_refine_render_payloads == [None]
            assert captured_refine_audio_defaults == [{"target_lufs": -18.0, "noise_reduction": True}]
            assert captured_render_plan_context_payloads == [
                {
                    "manual_editor": {},
                    "loudness": {"target_lufs": -18.0},
                    "voice_processing": {"noise_reduction": True},
                    "subtitles": {"version": 1},
                }
            ]

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_manual_editor_apply_blocks_projection_fallback_from_becoming_new_production_timeline(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        rerun_plans: list[object] = []

        async def _fake_load_source_subtitles(_session, *, job):
            return [
                {
                    "index": 0,
                    "start_time": 0.0,
                    "end_time": 5.0,
                    "text_raw": "原始字幕",
                    "text_norm": "原始字幕",
                    "text_final": "原始字幕",
                    "projection_source": "transcript_segment",
                }
            ]

        async def _fake_load_profile(_session, *, job_id):
            return None, {}

        async def _fake_load_cut_analysis_payload(_session, **_kwargs):
            return build_cut_analysis_payload(
                editorial_analysis={
                    "accepted_cuts": [],
                    "rule_candidates": [],
                },
                source_name="apply-demo.mp4",
                job_flow_mode="auto",
            )

        async def _fake_noop(*_args, **_kwargs):
            return None

        async def _fake_execute_job_rerun_plan(_session, *, job, steps, plan, via):
            rerun_plans.append(plan)

        monkeypatch.setattr(jobs_api, "_load_manual_editor_aligned_source_subtitle_dicts", _fake_load_source_subtitles)
        monkeypatch.setattr(jobs_api, "_load_manual_editor_preferred_downstream_profile", _fake_load_profile)
        monkeypatch.setattr(jobs_api, "_load_manual_editor_cut_analysis_payload", _fake_load_cut_analysis_payload)
        monkeypatch.setattr(
            jobs_api,
            "validate_projected_subtitles_against_source",
            lambda subtitles, **_kwargs: SimpleNamespace(
                mismatch_detected=True,
                fallback_used=True,
                subtitles=list(subtitles),
                changed=True,
                input_count=len(subtitles),
                output_count=len(subtitles),
            ),
        )
        monkeypatch.setattr(jobs_api, "review_multimodal_trim_review_payload", _fake_noop)
        monkeypatch.setattr(jobs_api, "apply_multimodal_trim_review_to_cut_analysis", lambda payload, _review: payload)
        monkeypatch.setattr(jobs_api, "resolve_packaging_plan_for_job", lambda *_args, **_kwargs: {})
        monkeypatch.setattr(pipeline_steps, "_job_creative_profile", lambda _job: {})
        monkeypatch.setattr(pipeline_steps, "_plan_insert_asset_slot", _fake_noop)
        monkeypatch.setattr(pipeline_steps, "_plan_music_entry", _fake_noop)
        monkeypatch.setattr(jobs_api, "_record_manual_subtitle_replacement_memory", _fake_noop)
        monkeypatch.setattr(jobs_api, "_persist_manual_video_summary_evidence", _fake_noop)
        monkeypatch.setattr(jobs_api, "_persist_manual_video_summary_source_context", _fake_noop)
        monkeypatch.setattr(jobs_api, "touch_runtime_refresh_hold", lambda **_kwargs: None)
        monkeypatch.setattr(jobs_api, "execute_job_rerun_plan", _fake_execute_job_rerun_plan)
        monkeypatch.setattr(jobs_api, "export_to_otio", lambda _payload: None)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            source_path = tmp_path / "apply-demo.mp4"
            source_path.write_bytes(b"video")
            job = Job(
                id=uuid.uuid4(),
                source_path=str(source_path),
                source_name="apply-demo.mp4",
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
                        "source": str(source_path),
                        "segments": [
                            {"type": "keep", "start": 0.0, "end": 5.0, "reason": "manual_editor_keep"},
                        ],
                        "analysis": {
                            "schema": CUT_ANALYSIS_SCHEMA_VERSION,
                            "accepted_cuts": [],
                            "rule_candidates": [],
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
                        "voice_processing": {"noise_reduction": True},
                        "subtitles": {"version": 1},
                    },
                )
            )
            session.add(Artifact(job_id=job.id, artifact_type="media_meta", data_json={"duration_sec": 5.0}))
            await session.commit()

            editorial_timeline = await jobs_api._load_latest_timeline_by_type(session, job_id=job.id, timeline_type="editorial")
            render_plan_timeline = await jobs_api._load_latest_timeline_by_type(session, job_id=job.id, timeline_type="render_plan")
            source_subtitles = await _fake_load_source_subtitles(session, job=job)
            subtitle_fingerprint = jobs_api._manual_editor_subtitle_fingerprint(source_subtitles)

            with pytest.raises(HTTPException) as exc_info:
                await jobs_api.apply_manual_editor_timeline(
                    job.id,
                    jobs_api.ManualEditorApplyIn(
                        keep_segments=[{"start": 0.0, "end": 5.0}],
                        base_timeline_id=str(editorial_timeline.id),
                        base_timeline_version=int(editorial_timeline.version or 1),
                        base_render_plan_version=int(render_plan_timeline.version or 1),
                        base_subtitle_fingerprint=subtitle_fingerprint,
                    ),
                    session=session,
                )

            assert exc_info.value.status_code == 409
            assert "fallback subtitle projection result" in str(exc_info.value.detail)
            assert "subtitle_projection_validation_fallback_used" in str(exc_info.value.detail)
            assert rerun_plans == []

            editorial_result = await session.execute(
                select(Timeline)
                .where(Timeline.job_id == job.id, Timeline.timeline_type == "editorial")
                .order_by(Timeline.version.desc(), Timeline.id.desc())
            )
            render_plan_result = await session.execute(
                select(Timeline)
                .where(Timeline.job_id == job.id, Timeline.timeline_type == "render_plan")
                .order_by(Timeline.version.desc(), Timeline.id.desc())
            )
            assert len(list(editorial_result.scalars().all())) == 1
            assert len(list(render_plan_result.scalars().all())) == 1

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_manual_editor_apply_reuses_previous_packaging_effect_style_for_timeline_change(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        rerun_plans: list[object] = []
        multimodal_review_calls: list[dict[str, object]] = []
        packaging_resolve_calls: list[dict[str, object]] = []
        insert_plan_calls: list[dict[str, object]] = []
        music_plan_calls: list[dict[str, object]] = []
        timeline_analysis_calls: list[dict[str, object]] = []
        editing_accents_calls: list[dict[str, object]] = []
        packaging_helper_calls: dict[str, list[dict[str, object]]] = {
            "editing_skill": [],
            "editing_accents": [],
            "timeline_analysis": [],
            "subtitles": [],
        }

        async def _fake_load_source_subtitles(_session, *, job):
            return [
                {
                    "index": 0,
                    "start_time": 0.0,
                    "end_time": 5.0,
                    "text_raw": "原始字幕",
                    "text_norm": "原始字幕",
                    "text_final": "原始字幕",
                    "projection_source": "transcript_segment",
                }
            ]

        async def _fake_load_profile(_session, *, job_id):
            return None, {}

        async def _fake_load_cut_analysis_payload(_session, **_kwargs):
            return build_cut_analysis_payload(
                editorial_analysis={
                    "accepted_cuts": [],
                    "rule_candidates": [],
                },
                source_name="apply-demo.mp4",
                job_flow_mode="auto",
            )

        async def _fake_review_multimodal(payload, **_kwargs):
            multimodal_review_calls.append(dict(payload))
            return payload

        async def _fake_insert_asset_slot(**_kwargs):
            insert_plan_calls.append(dict(_kwargs))
            return None

        async def _fake_plan_music_entry(**_kwargs):
            music_plan_calls.append(dict(_kwargs))
            return None

        async def _fake_noop(*_args, **_kwargs):
            return None

        async def _fake_execute_job_rerun_plan(_session, *, job, steps, plan, via):
            rerun_plans.append(plan)

        monkeypatch.setattr(jobs_api, "_load_manual_editor_aligned_source_subtitle_dicts", _fake_load_source_subtitles)
        monkeypatch.setattr(jobs_api, "_load_manual_editor_preferred_downstream_profile", _fake_load_profile)
        monkeypatch.setattr(jobs_api, "_load_manual_editor_cut_analysis_payload", _fake_load_cut_analysis_payload)
        monkeypatch.setattr(jobs_api, "validate_projected_subtitles_against_source", lambda subtitles, **_kwargs: SimpleNamespace(
            mismatch_detected=False,
            fallback_used=False,
            subtitles=list(subtitles),
            changed=False,
            input_count=len(subtitles),
            output_count=len(subtitles),
        ))
        monkeypatch.setattr(jobs_api, "review_multimodal_trim_review_payload", _fake_review_multimodal)
        monkeypatch.setattr(jobs_api, "apply_multimodal_trim_review_to_cut_analysis", lambda payload, _review: payload)
        monkeypatch.setattr(
            jobs_api,
            "resolve_packaging_plan_for_job",
            lambda *_args, **_kwargs: (packaging_resolve_calls.append(dict(_kwargs)) or {}),
        )
        original_packaging_timeline_editing_skill = jobs_api.packaging_timeline_editing_skill
        original_packaging_timeline_editing_accents = jobs_api.packaging_timeline_editing_accents
        original_packaging_timeline_analysis = jobs_api.packaging_timeline_analysis
        original_packaging_timeline_subtitles = jobs_api.packaging_timeline_subtitles
        monkeypatch.setattr(
            jobs_api,
            "packaging_timeline_editing_skill",
            lambda payload: (
                packaging_helper_calls["editing_skill"].append(dict(payload or {}))
                or original_packaging_timeline_editing_skill(payload)
            ),
        )
        monkeypatch.setattr(
            jobs_api,
            "packaging_timeline_editing_accents",
            lambda payload: (
                packaging_helper_calls["editing_accents"].append(dict(payload or {}))
                or original_packaging_timeline_editing_accents(payload)
            ),
        )
        monkeypatch.setattr(
            jobs_api,
            "packaging_timeline_analysis",
            lambda payload: (
                packaging_helper_calls["timeline_analysis"].append(dict(payload or {}))
                or original_packaging_timeline_analysis(payload)
            ),
        )
        monkeypatch.setattr(
            jobs_api,
            "packaging_timeline_subtitles",
            lambda payload: (
                packaging_helper_calls["subtitles"].append(dict(payload or {}))
                or original_packaging_timeline_subtitles(payload)
            ),
        )
        monkeypatch.setattr(
            jobs_api,
            "infer_timeline_analysis",
            lambda *_args, **_kwargs: (timeline_analysis_calls.append(dict(_kwargs)) or {"pace": "tight"}),
        )
        monkeypatch.setattr(
            jobs_api,
            "build_smart_editing_accents",
            lambda **_kwargs: (editing_accents_calls.append(dict(_kwargs)) or {"style": str(_kwargs.get("style") or "")}),
        )
        monkeypatch.setattr(pipeline_steps, "_job_creative_profile", lambda _job: {})
        monkeypatch.setattr(pipeline_steps, "_plan_insert_asset_slot", _fake_insert_asset_slot)
        monkeypatch.setattr(pipeline_steps, "_plan_music_entry", _fake_plan_music_entry)
        monkeypatch.setattr(jobs_api, "_record_manual_subtitle_replacement_memory", _fake_noop)
        monkeypatch.setattr(jobs_api, "_persist_manual_video_summary_evidence", _fake_noop)
        monkeypatch.setattr(jobs_api, "_persist_manual_video_summary_source_context", _fake_noop)
        monkeypatch.setattr(jobs_api, "touch_runtime_refresh_hold", lambda **_kwargs: None)
        monkeypatch.setattr(jobs_api, "execute_job_rerun_plan", _fake_execute_job_rerun_plan)
        monkeypatch.setattr(jobs_api, "export_to_otio", lambda _payload: None)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            source_path = tmp_path / "apply-demo.mp4"
            source_path.write_bytes(b"video")
            job = Job(
                id=uuid.uuid4(),
                source_path=str(source_path),
                source_name="apply-demo.mp4",
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
                        "source": str(source_path),
                        "segments": [
                            {"type": "keep", "start": 0.0, "end": 1.0, "reason": "manual_editor_keep"},
                            {"type": "keep", "start": 1.3, "end": 5.0, "reason": "manual_editor_keep"},
                        ],
                        "analysis": {
                            "schema": CUT_ANALYSIS_SCHEMA_VERSION,
                            "accepted_cuts": [],
                            "rule_candidates": [],
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
                        "voice_processing": {"noise_reduction": True},
                        "packaging_timeline": {
                            "subtitles": {"version": 1},
                            "timeline_analysis": {"pace": "legacy"},
                            "editing_skill": {"pace": "tight"},
                            "editing_accents": {"style": "smart_effect_punch"},
                        },
                    },
                )
            )
            session.add(Artifact(job_id=job.id, artifact_type="media_meta", data_json={"duration_sec": 5.0}))
            await session.commit()

            editorial_timeline = await jobs_api._load_latest_timeline_by_type(session, job_id=job.id, timeline_type="editorial")
            render_plan_timeline = await jobs_api._load_latest_timeline_by_type(session, job_id=job.id, timeline_type="render_plan")
            source_subtitles = await _fake_load_source_subtitles(session, job=job)
            subtitle_fingerprint = jobs_api._manual_editor_subtitle_fingerprint(source_subtitles)

            result = await jobs_api.apply_manual_editor_timeline(
                job.id,
                jobs_api.ManualEditorApplyIn(
                    keep_segments=[{"start": 0.0, "end": 5.0}],
                    base_timeline_id=str(editorial_timeline.id),
                    base_timeline_version=int(editorial_timeline.version or 1),
                    base_render_plan_version=int(render_plan_timeline.version or 1),
                    base_subtitle_fingerprint=subtitle_fingerprint,
                ),
                session=session,
            )

            render_plan_result = await session.execute(
                select(Timeline)
                .where(Timeline.job_id == job.id, Timeline.timeline_type == "render_plan")
                .order_by(Timeline.version.desc(), Timeline.id.desc())
            )
            latest_render_plan = render_plan_result.scalars().first()
            latest_render_plan_payload = (
                latest_render_plan.data_json
                if latest_render_plan and isinstance(latest_render_plan.data_json, dict)
                else {}
            )

            assert result.change_scope == "timeline"
            assert result.render_strategy == "full_timeline_render"
            assert result.keep_segment_count == 1
            assert multimodal_review_calls != []
            assert len(packaging_resolve_calls) == 1
            assert len(insert_plan_calls) == 1
            assert len(music_plan_calls) == 1
            assert len(timeline_analysis_calls) == 1
            assert len(editing_accents_calls) == 1
            assert editing_accents_calls[0]["style"] == "smart_effect_punch"
            assert len(packaging_helper_calls["editing_skill"]) == 1
            assert len(packaging_helper_calls["editing_accents"]) == 1
            assert len(packaging_helper_calls["subtitles"]) == 1
            assert rerun_plans and rerun_plans[-1].issue_codes == ["manual_timeline_edit"]
            assert rerun_plans[-1].rerun_steps == ["render"]
            assert latest_render_plan_payload.get("editing_accents", {}).get("style") == "smart_effect_punch"

    try:
        asyncio.run(_run())
    finally:
        asyncio.run(engine.dispose())


def test_manual_editor_apply_blocks_insert_fallback_from_becoming_new_production_render_plan(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        rerun_plans: list[object] = []

        async def _fake_load_source_subtitles(_session, *, job):
            return [
                {
                    "index": 0,
                    "start_time": 0.0,
                    "end_time": 5.0,
                    "text_raw": "原始字幕",
                    "text_norm": "原始字幕",
                    "text_final": "原始字幕",
                    "projection_source": "transcript_segment",
                }
            ]

        async def _fake_load_profile(_session, *, job_id):
            return None, {}

        async def _fake_load_cut_analysis_payload(_session, **_kwargs):
            return build_cut_analysis_payload(
                editorial_analysis={
                    "accepted_cuts": [],
                    "rule_candidates": [],
                },
                source_name="apply-demo.mp4",
                job_flow_mode="auto",
            )

        async def _fake_insert_asset_slot(**_kwargs):
            return {
                "insert_after_sec": 2.5,
                "selection_source": "deterministic_fallback",
                "reason": "fallback",
            }

        async def _fake_plan_music_entry(**_kwargs):
            return None

        async def _fake_noop(*_args, **_kwargs):
            return None

        async def _fake_execute_job_rerun_plan(_session, *, job, steps, plan, via):
            rerun_plans.append(plan)

        monkeypatch.setattr(jobs_api, "_load_manual_editor_aligned_source_subtitle_dicts", _fake_load_source_subtitles)
        monkeypatch.setattr(jobs_api, "_load_manual_editor_preferred_downstream_profile", _fake_load_profile)
        monkeypatch.setattr(jobs_api, "_load_manual_editor_cut_analysis_payload", _fake_load_cut_analysis_payload)
        monkeypatch.setattr(
            jobs_api,
            "validate_projected_subtitles_against_source",
            lambda subtitles, **_kwargs: SimpleNamespace(
                mismatch_detected=False,
                fallback_used=False,
                subtitles=list(subtitles),
                changed=False,
                input_count=len(subtitles),
                output_count=len(subtitles),
            ),
        )
        monkeypatch.setattr(jobs_api, "review_multimodal_trim_review_payload", _fake_noop)
        monkeypatch.setattr(jobs_api, "apply_multimodal_trim_review_to_cut_analysis", lambda payload, _review: payload)
        monkeypatch.setattr(jobs_api, "resolve_packaging_plan_for_job", lambda *_args, **_kwargs: {"insert": {}})
        monkeypatch.setattr(jobs_api, "infer_timeline_analysis", lambda *_args, **_kwargs: {"pace": "tight"})
        monkeypatch.setattr(jobs_api, "build_smart_editing_accents", lambda **_kwargs: {"style": "smart_effect_punch"})
        monkeypatch.setattr(pipeline_steps, "_job_creative_profile", lambda _job: {})
        monkeypatch.setattr(pipeline_steps, "_plan_insert_asset_slot", _fake_insert_asset_slot)
        monkeypatch.setattr(pipeline_steps, "_plan_music_entry", _fake_plan_music_entry)
        monkeypatch.setattr(jobs_api, "_record_manual_subtitle_replacement_memory", _fake_noop)
        monkeypatch.setattr(jobs_api, "_persist_manual_video_summary_evidence", _fake_noop)
        monkeypatch.setattr(jobs_api, "_persist_manual_video_summary_source_context", _fake_noop)
        monkeypatch.setattr(jobs_api, "touch_runtime_refresh_hold", lambda **_kwargs: None)
        monkeypatch.setattr(jobs_api, "execute_job_rerun_plan", _fake_execute_job_rerun_plan)
        monkeypatch.setattr(jobs_api, "export_to_otio", lambda _payload: None)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            source_path = tmp_path / "apply-demo.mp4"
            source_path.write_bytes(b"video")
            job = Job(
                id=uuid.uuid4(),
                source_path=str(source_path),
                source_name="apply-demo.mp4",
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
                        "source": str(source_path),
                        "segments": [
                            {"type": "keep", "start": 0.0, "end": 1.0, "reason": "manual_editor_keep"},
                            {"type": "keep", "start": 1.3, "end": 5.0, "reason": "manual_editor_keep"},
                        ],
                        "analysis": {
                            "schema": CUT_ANALYSIS_SCHEMA_VERSION,
                            "accepted_cuts": [],
                            "rule_candidates": [],
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
                        "voice_processing": {"noise_reduction": True},
                        "packaging_timeline": {
                            "subtitles": {"version": 1},
                            "timeline_analysis": {"pace": "legacy"},
                            "editing_skill": {"pace": "tight"},
                            "editing_accents": {"style": "smart_effect_punch"},
                        },
                    },
                )
            )
            session.add(Artifact(job_id=job.id, artifact_type="media_meta", data_json={"duration_sec": 5.0}))
            await session.commit()

            editorial_timeline = await jobs_api._load_latest_timeline_by_type(session, job_id=job.id, timeline_type="editorial")
            render_plan_timeline = await jobs_api._load_latest_timeline_by_type(session, job_id=job.id, timeline_type="render_plan")
            source_subtitles = await _fake_load_source_subtitles(session, job=job)
            subtitle_fingerprint = jobs_api._manual_editor_subtitle_fingerprint(source_subtitles)

            with pytest.raises(HTTPException) as exc_info:
                await jobs_api.apply_manual_editor_timeline(
                    job.id,
                    jobs_api.ManualEditorApplyIn(
                        keep_segments=[{"start": 0.0, "end": 5.0}],
                        base_timeline_id=str(editorial_timeline.id),
                        base_timeline_version=int(editorial_timeline.version or 1),
                        base_render_plan_version=int(render_plan_timeline.version or 1),
                        base_subtitle_fingerprint=subtitle_fingerprint,
                    ),
                    session=session,
                )

            assert exc_info.value.status_code == 409
            assert "fallback packaging plan result" in str(exc_info.value.detail)
            assert "insert_slot_deterministic_fallback" in str(exc_info.value.detail)
            assert rerun_plans == []

            editorial_result = await session.execute(
                select(Timeline)
                .where(Timeline.job_id == job.id, Timeline.timeline_type == "editorial")
                .order_by(Timeline.version.desc(), Timeline.id.desc())
            )
            render_plan_result = await session.execute(
                select(Timeline)
                .where(Timeline.job_id == job.id, Timeline.timeline_type == "render_plan")
                .order_by(Timeline.version.desc(), Timeline.id.desc())
            )
            assert len(list(editorial_result.scalars().all())) == 1
            assert len(list(render_plan_result.scalars().all())) == 1

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
            assert session_payload.projection_diagnostics["display_projection_basis"] == "source_timeline_projection"

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
