from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from roughcut.db.models import Artifact, GlossaryTerm, Job, JobStep, RenderOutput, SubtitleItem, Timeline
from roughcut.media.audio import NoAudioStreamError
from roughcut.media.probe import MediaMeta
from roughcut.pipeline.steps import (
    _get_cover_seek,
    _infer_subject_domain_for_memory,
    _load_latest_artifact,
    _load_latest_optional_artifact,
    _resolve_subtitle_split_profile,
    _load_latest_timeline,
    _record_source_integrity,
    _select_cover_source_video,
    _select_preferred_content_profile_artifact,
    _workflow_template_subject_domain,
    run_ai_director,
    run_avatar_commentary,
    run_content_profile,
    run_extract_audio,
    run_glossary_review,
    run_platform_package,
    run_probe,
    run_transcribe,
)
from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment


class _FakeTelegramReviewBotService:
    def __init__(self) -> None:
        self.content_profile_notifications: list[uuid.UUID] = []

    async def notify_content_profile_review(self, job_id: uuid.UUID) -> None:
        self.content_profile_notifications.append(job_id)


def test_workflow_template_subject_domain_defaults_edc_tactical_to_edc():
    assert _workflow_template_subject_domain("edc_tactical") == "edc"


def test_infer_subject_domain_for_memory_falls_back_to_workflow_template_scope():
    assert (
        _infer_subject_domain_for_memory(
            workflow_template="edc_tactical",
            subtitle_items=[],
            content_profile={},
            source_name="20260301-171443.mp4",
        )
        == "edc"
    )


@pytest.mark.asyncio
async def test_run_probe_starts_and_cleans_up_step_heartbeat(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    heartbeat_calls: list[dict[str, object]] = []

    class FakeHeartbeat:
        def __init__(self) -> None:
            self.cancelled = False

        def cancel(self) -> None:
            self.cancelled = True

        def __await__(self):
            async def _done():
                return None

            return _done().__await__()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="probe", status="running"))
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_probe(_path: Path) -> MediaMeta:
        return MediaMeta(
            duration=12.3,
            width=1920,
            height=1080,
            fps=30.0,
            video_codec="h264",
            audio_codec="aac",
            audio_sample_rate=48000,
            audio_channels=2,
            file_size=source_path.stat().st_size,
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
            bit_rate=1024,
        )

    def fake_spawn_step_heartbeat(*, step_id, detail: str, progress: float | None = None):
        task = FakeHeartbeat()
        heartbeat_calls.append(
            {
                "step_id": step_id,
                "detail": detail,
                "progress": progress,
                "task": task,
            }
        )
        return task

    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "probe", fake_probe)
    monkeypatch.setattr(steps_mod, "validate_media", lambda _meta: None)
    monkeypatch.setattr(steps_mod, "_hash_file", lambda _path: "sha256-demo")
    monkeypatch.setattr(steps_mod, "_spawn_step_heartbeat", fake_spawn_step_heartbeat)

    result = await run_probe(str(job_id))

    assert result == {"duration": 12.3, "file_hash": "sha256-demo"}
    assert heartbeat_calls, "probe should keep the step heartbeat alive during long-running source work"
    assert heartbeat_calls[0]["detail"] == "下载源视频并准备探测媒体参数"
    assert heartbeat_calls[0]["progress"] == 0.1
    assert heartbeat_calls[0]["task"].cancelled is True


def test_resolve_subtitle_split_profile_prefers_faster_portrait_subtitles():
    portrait = _resolve_subtitle_split_profile(width=1080, height=1920)
    landscape = _resolve_subtitle_split_profile(width=1920, height=1080)

    assert portrait["orientation"] == "portrait"
    assert portrait["max_duration"] < landscape["max_duration"]
    assert portrait["max_chars"] < landscape["max_chars"]
    assert portrait["max_chars"] == 12
    assert landscape["max_chars"] == 18


def test_workflow_template_subject_domain_does_not_treat_templates_as_domains():
    assert _workflow_template_subject_domain("unboxing_standard") is None
    assert _workflow_template_subject_domain("tutorial_standard") is None
    assert _workflow_template_subject_domain("edc_tactical") is None


def test_infer_subject_domain_for_memory_uses_current_content_evidence():
    assert _infer_subject_domain_for_memory(
        workflow_template="unboxing_standard",
        subtitle_items=[{"text_final": "今天开箱这个手电，重点看泛光、聚光和夜骑补光。"}],
        content_profile={},
        source_name="20260209-124735.mp4",
    ) == "edc"

    assert _infer_subject_domain_for_memory(
        workflow_template="unboxing_standard",
        subtitle_items=[{"text_final": "今天主要演示节点编排、工作流和模型推理。"}],
        content_profile={},
        source_name="demo.mp4",
    ) == "ai"

    assert _infer_subject_domain_for_memory(
        workflow_template="review_standard",
        subtitle_items=[{"text_final": "今天主要聊这台手机的屏幕、芯片、相机和续航。"}],
        content_profile={},
        source_name="phone.mp4",
    ) == "tech"

    assert _infer_subject_domain_for_memory(
        workflow_template="unboxing_standard",
        subtitle_items=[{"text_final": "这次重点看机能包的分仓、挂点和通勤穿搭。"}],
        content_profile={},
        source_name="bag.mp4",
    ) == "functional"

    assert _infer_subject_domain_for_memory(
        workflow_template="unboxing_standard",
        subtitle_items=[{"text_final": "今天开箱这把工具钳，重点看钳头、批头和螺丝刀。"}],
        content_profile={},
        source_name="tool.mp4",
    ) == "tools"


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
async def test_run_glossary_review_prefers_content_profile_subject_domain_for_memory_scope(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    captured: dict[str, object] = {}

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                workflow_template="unboxing_standard",
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
                text_raw="这句只是提到了工作流和节点编排。",
                text_norm="这句只是提到了工作流和节点编排。",
                text_final="这句只是提到了工作流和节点编排。",
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_brand": "傲雷",
                    "subject_model": "司令官2Ultra",
                    "subject_type": "EDC手电",
                    "subject_domain": "edc",
                    "video_theme": "手电开箱",
                    "workflow_template": "unboxing_standard",
                },
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    async def fake_apply_glossary_corrections(*args, **kwargs):
        return []

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        captured["subject_domain"] = kwargs.get("subject_domain")
        return {}

    async def fake_enrich_content_profile(**kwargs):
        return kwargs["profile"]

    async def fake_load_recent_subtitle_examples(*args, **kwargs):
        return []

    async def fake_load_related_profile_subtitle_examples(*args, **kwargs):
        return []

    def fake_build_subtitle_review_memory(**kwargs):
        captured["review_memory_subject_domain"] = kwargs.get("subject_domain")
        return {}

    async def fake_polish_subtitle_items(*args, **kwargs):
        return 0

    monkeypatch.setattr(steps_mod, "apply_glossary_corrections", fake_apply_glossary_corrections)
    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "enrich_content_profile", fake_enrich_content_profile)
    monkeypatch.setattr(steps_mod, "_load_recent_subtitle_examples", fake_load_recent_subtitle_examples)
    monkeypatch.setattr(steps_mod, "_load_related_profile_subtitle_examples", fake_load_related_profile_subtitle_examples)
    monkeypatch.setattr(steps_mod, "build_subtitle_review_memory", fake_build_subtitle_review_memory)
    monkeypatch.setattr(steps_mod, "polish_subtitle_items", fake_polish_subtitle_items)

    await run_glossary_review(str(job_id))

    assert captured["subject_domain"] == "edc"
    assert captured["review_memory_subject_domain"] == "edc"


@pytest.mark.asyncio
async def test_run_glossary_review_passes_include_research_when_enabled(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    captured: dict[str, object] = {}
    settings = SimpleNamespace(
        research_verifier_enabled=True,
        correction_framework_version="multisource_v1",
    )

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                workflow_template="unboxing_standard",
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
                text_raw="这句只是提到了机能包和 VX07 面料。",
                text_norm="这句只是提到了机能包和 VX07 面料。",
                text_final="这句只是提到了机能包和 VX07 面料。",
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_type": "机能双肩包",
                    "video_theme": "机能包开箱",
                    "transcript_excerpt": "[0.0-1.0] 这句只是提到了机能包和 VX07 面料。",
                },
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)

    async def fake_apply_glossary_corrections(*args, **kwargs):
        return []

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_load_recent_subtitle_examples(*args, **kwargs):
        return []

    async def fake_load_related_profile_subtitle_examples(*args, **kwargs):
        return []

    def fake_build_subtitle_review_memory(**kwargs):
        return {}

    async def fake_polish_subtitle_items(*args, **kwargs):
        return 0

    async def fake_enrich_content_profile(**kwargs):
        captured["include_research"] = kwargs["include_research"]
        return kwargs["profile"]

    monkeypatch.setattr(steps_mod, "apply_glossary_corrections", fake_apply_glossary_corrections)
    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_load_recent_subtitle_examples", fake_load_recent_subtitle_examples)
    monkeypatch.setattr(steps_mod, "_load_related_profile_subtitle_examples", fake_load_related_profile_subtitle_examples)
    monkeypatch.setattr(steps_mod, "build_subtitle_review_memory", fake_build_subtitle_review_memory)
    monkeypatch.setattr(steps_mod, "polish_subtitle_items", fake_polish_subtitle_items)
    monkeypatch.setattr(steps_mod, "enrich_content_profile", fake_enrich_content_profile)

    await run_glossary_review(str(job_id))

    assert captured["include_research"] is True


@pytest.mark.asyncio
async def test_run_transcribe_uses_strict_memory_scope_without_domain_signal(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"wav")
    captured: dict[str, object] = {}

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="20260209-124735.mp4",
                status="processing",
                language="zh-CN",
                workflow_template="unboxing_standard",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="transcribe", status="running"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="audio_wav",
                storage_path="jobs/demo/audio.wav",
                data_json={},
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        steps_mod,
        "get_settings",
        lambda: SimpleNamespace(
            transcription_dialect="zh-CN",
            asr_evidence_enabled=False,
            ocr_enabled=False,
            entity_graph_enabled=False,
            research_verifier_enabled=False,
            correction_framework_version="multisource_v1",
        ),
    )

    async def fake_resolve_storage_reference(*args, **kwargs):
        return audio_path

    async def fake_load_recent_subtitle_examples(*args, **kwargs):
        return [{"text_final": "RunningHub 的无限画布和工作流。", "source_name": "history.srt"}]

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        captured["subject_domain"] = kwargs.get("subject_domain")
        captured["strict_subject_domain"] = kwargs.get("strict_subject_domain")
        return {}

    def fake_build_subtitle_review_memory(**kwargs):
        captured["review_memory_subject_domain"] = kwargs.get("subject_domain")
        return {"subject_domain": kwargs.get("subject_domain"), "terms": [], "aliases": []}

    async def fake_transcribe_audio(*args, **kwargs):
        captured["prompt"] = kwargs.get("prompt")
        return TranscriptResult(
            segments=[TranscriptSegment(index=0, start=0.0, end=1.0, text="测试")],
            language="zh-CN",
            duration=1.0,
        )

    monkeypatch.setattr(steps_mod, "_resolve_storage_reference", fake_resolve_storage_reference)
    monkeypatch.setattr(steps_mod, "_load_recent_subtitle_examples", fake_load_recent_subtitle_examples)
    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "build_subtitle_review_memory", fake_build_subtitle_review_memory)
    monkeypatch.setattr(steps_mod, "transcribe_audio", fake_transcribe_audio)

    await run_transcribe(str(job_id))

    assert captured["subject_domain"] is None
    assert captured["strict_subject_domain"] is True
    assert captured["review_memory_subject_domain"] is None
    assert isinstance(captured["prompt"], str)

    async with factory() as session:
        step = (
            await session.execute(select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "transcribe"))
        ).scalar_one()
        assert step.metadata_["correction_framework"]["version"] == "multisource_v1"
        assert step.metadata_["correction_framework"]["flags"]["asr_evidence_enabled"] is False

        transcript_evidence = (
            await session.execute(
                select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "transcript_evidence")
            )
        ).scalar_one_or_none()
        assert transcript_evidence is None


@pytest.mark.asyncio
async def test_run_transcribe_keeps_step_heartbeat_alive_when_provider_is_silent(
    db_engine,
    monkeypatch,
    tmp_path: Path,
):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"wav")
    release_transcribe = asyncio.Event()
    real_sleep = asyncio.sleep

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                workflow_template="unboxing_standard",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="extract_audio", status="done", metadata_={"has_audio": True}))
        session.add(JobStep(job_id=job_id, step_name="transcribe", status="running"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="audio_wav",
                storage_path="jobs/demo/audio.wav",
                data_json={},
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        steps_mod,
        "get_settings",
        lambda: SimpleNamespace(
            transcription_dialect="zh-CN",
            asr_evidence_enabled=False,
            ocr_enabled=False,
            entity_graph_enabled=False,
            research_verifier_enabled=False,
            correction_framework_version="multisource_v1",
            step_heartbeat_interval_sec=20,
            transcribe_runtime_timeout_sec=30,
        ),
    )

    async def fast_sleep(_delay: float):
        await real_sleep(0)

    async def fake_resolve_storage_reference(*args, **kwargs):
        return audio_path

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_load_recent_subtitle_examples(*args, **kwargs):
        return []

    def fake_build_subtitle_review_memory(**kwargs):
        return {"subject_domain": kwargs.get("subject_domain"), "terms": [], "aliases": []}

    async def fake_transcribe_audio(*args, **kwargs):
        await release_transcribe.wait()
        return TranscriptResult(
            segments=[TranscriptSegment(index=0, start=0.0, end=1.0, text="测试")],
            language="zh-CN",
            duration=1.0,
        )

    monkeypatch.setattr(steps_mod.asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(steps_mod, "_resolve_storage_reference", fake_resolve_storage_reference)
    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_load_recent_subtitle_examples", fake_load_recent_subtitle_examples)
    monkeypatch.setattr(steps_mod, "build_subtitle_review_memory", fake_build_subtitle_review_memory)
    monkeypatch.setattr(steps_mod, "transcribe_audio", fake_transcribe_audio)

    task = asyncio.create_task(run_transcribe(str(job_id)))
    try:
        await real_sleep(0.05)
        async with factory() as session:
            step = (
                await session.execute(select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "transcribe"))
            ).scalar_one()
            first_updated_at = datetime.fromisoformat(step.metadata_["updated_at"])

        await real_sleep(0.05)
        async with factory() as session:
            step = (
                await session.execute(select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "transcribe"))
            ).scalar_one()
            second_updated_at = datetime.fromisoformat(step.metadata_["updated_at"])

        assert second_updated_at > first_updated_at
        assert task.done() is False
    finally:
        release_transcribe.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_run_transcribe_times_out_when_provider_hangs(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"wav")
    release_transcribe = asyncio.Event()
    real_sleep = asyncio.sleep

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                workflow_template="unboxing_standard",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="extract_audio", status="done", metadata_={"has_audio": True}))
        session.add(JobStep(job_id=job_id, step_name="transcribe", status="running"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="audio_wav",
                storage_path="jobs/demo/audio.wav",
                data_json={},
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        steps_mod,
        "get_settings",
        lambda: SimpleNamespace(
            transcription_dialect="zh-CN",
            asr_evidence_enabled=False,
            ocr_enabled=False,
            entity_graph_enabled=False,
            research_verifier_enabled=False,
            correction_framework_version="multisource_v1",
            step_heartbeat_interval_sec=20,
            transcribe_runtime_timeout_sec=0.1,
        ),
    )

    async def fake_resolve_storage_reference(*args, **kwargs):
        return audio_path

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_load_recent_subtitle_examples(*args, **kwargs):
        return []

    def fake_build_subtitle_review_memory(**kwargs):
        return {"subject_domain": kwargs.get("subject_domain"), "terms": [], "aliases": []}

    async def fake_transcribe_audio(*args, **kwargs):
        await release_transcribe.wait()
        return TranscriptResult(
            segments=[TranscriptSegment(index=0, start=0.0, end=1.0, text="测试")],
            language="zh-CN",
            duration=1.0,
        )

    monkeypatch.setattr(steps_mod, "_resolve_storage_reference", fake_resolve_storage_reference)
    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_load_recent_subtitle_examples", fake_load_recent_subtitle_examples)
    monkeypatch.setattr(steps_mod, "build_subtitle_review_memory", fake_build_subtitle_review_memory)
    monkeypatch.setattr(steps_mod, "transcribe_audio", fake_transcribe_audio)

    task = asyncio.create_task(run_transcribe(str(job_id)))
    await real_sleep(0.25)

    assert task.done(), "hung transcribe should not stay running forever"
    assert isinstance(task.exception(), asyncio.TimeoutError)


@pytest.mark.asyncio
async def test_run_extract_audio_treats_no_audio_stream_as_non_fatal(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "silent.mp4"
    source_path.write_bytes(b"video")

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/silent.mp4",
                source_name="silent.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="extract_audio", status="running"))
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_extract_audio(*args, **kwargs):
        raise NoAudioStreamError("video has no audio stream")

    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "extract_audio", fake_extract_audio)

    result = await run_extract_audio(str(job_id))

    assert result == {"audio_key": None, "has_audio": False}

    async with factory() as session:
        step = (
            await session.execute(select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "extract_audio"))
        ).scalar_one()
        assert step.metadata_["has_audio"] is False
        assert step.metadata_["audio_optional"] is True

        audio_artifact = (
            await session.execute(select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "audio_wav"))
        ).scalar_one_or_none()
        assert audio_artifact is None


@pytest.mark.asyncio
async def test_run_transcribe_persists_empty_transcript_when_extract_audio_found_no_audio(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod
    import roughcut.speech.transcribe as transcribe_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    captured: dict[str, object] = {}

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/silent.mp4",
                source_name="silent.mp4",
                status="processing",
                language="zh-CN",
                workflow_template="commentary_focus",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="extract_audio", status="done", metadata_={"has_audio": False}))
        session.add(JobStep(job_id=job_id, step_name="transcribe", status="running"))
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        steps_mod,
        "get_settings",
        lambda: SimpleNamespace(
            transcription_dialect="zh-CN",
            asr_evidence_enabled=True,
            ocr_enabled=False,
            entity_graph_enabled=False,
            research_verifier_enabled=False,
            correction_framework_version="multisource_v1",
        ),
    )
    monkeypatch.setattr(
        transcribe_mod,
        "get_settings",
        lambda: SimpleNamespace(asr_evidence_enabled=True),
    )

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_load_recent_subtitle_examples(*args, **kwargs):
        return []

    def fake_build_subtitle_review_memory(**kwargs):
        captured["subject_domain"] = kwargs.get("subject_domain")
        return {}

    async def fake_transcribe_audio(*args, **kwargs):
        raise AssertionError("transcribe_audio should not be called when the source has no audio stream")

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_load_recent_subtitle_examples", fake_load_recent_subtitle_examples)
    monkeypatch.setattr(steps_mod, "build_subtitle_review_memory", fake_build_subtitle_review_memory)
    monkeypatch.setattr(steps_mod, "transcribe_audio", fake_transcribe_audio)

    result = await run_transcribe(str(job_id))

    assert result == {"segment_count": 0, "duration": 0.0, "has_audio": False}
    assert captured["subject_domain"] is None

    async with factory() as session:
        transcript_artifact = (
            await session.execute(select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "transcript"))
        ).scalar_one()
        assert transcript_artifact.data_json["segment_count"] == 0
        assert transcript_artifact.data_json["provider"] == "system"
        assert transcript_artifact.data_json["model"] == "no_audio"

        transcript_evidence = (
            await session.execute(
                select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "transcript_evidence")
            )
        ).scalar_one()
        assert transcript_evidence.data_json["provider"] == "system"
        assert transcript_evidence.data_json["model"] == "no_audio"
        assert transcript_evidence.data_json["context"] == "no_audio_stream"


@pytest.mark.asyncio
async def test_run_content_profile_keeps_manual_review_until_accuracy_gate_passes(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod
    from roughcut.review import content_profile as content_profile_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    fake_review_bot = _FakeTelegramReviewBotService()
    settings = SimpleNamespace(
        auto_confirm_content_profile=True,
        content_profile_review_threshold=0.72,
        content_profile_auto_review_min_accuracy=0.9,
        content_profile_auto_review_min_samples=20,
    )

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="screen_tutorial",
                enhancement_modes=["auto_review"],
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
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "get_telegram_review_bot_service", lambda: fake_review_bot)
    monkeypatch.setattr(content_profile_mod, "get_settings", lambda: settings)

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

    assert result["auto_confirmed"] is False
    assert result["automation_score"] >= 0.72

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id).order_by(Artifact.created_at.asc())
        )
        artifacts = artifact_result.scalars().all()
        artifact_map = {item.artifact_type: item.data_json for item in artifacts}
        assert set(artifact_map) == {"content_profile_draft", "downstream_context"}

        draft = artifact_map["content_profile_draft"]
        assert artifact_map["downstream_context"]["resolved_profile"]["subject_type"] == draft["subject_type"]
        assert draft["automation_review"]["enabled"] is True
        assert draft["automation_review"]["quality_gate_passed"] is True
        assert draft["automation_review"]["approval_accuracy_gate_passed"] is False
        assert draft["automation_review"]["approval_accuracy_sample_size"] == 0
        assert draft["automation_review"]["auto_confirm"] is False
        assert draft["creative_profile"]["workflow_mode"] == "standard_edit"
        assert draft["creative_profile"]["enhancement_modes"] == ["auto_review"]

        review_step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
        )
        review_step = review_step_result.scalar_one()
        assert review_step.status == "pending"
        assert review_step.metadata_ is None

    assert fake_review_bot.content_profile_notifications == [job_id]


@pytest.mark.asyncio
async def test_run_content_profile_auto_confirms_high_confidence_profile_when_accuracy_gate_passes(
    db_engine,
    monkeypatch,
    tmp_path: Path,
):
    import roughcut.pipeline.steps as steps_mod
    from roughcut.review import content_profile as content_profile_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    fake_review_bot = _FakeTelegramReviewBotService()
    settings = SimpleNamespace(
        auto_confirm_content_profile=True,
        content_profile_review_threshold=0.72,
        content_profile_auto_review_min_accuracy=0.9,
        content_profile_auto_review_min_samples=20,
    )

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="screen_tutorial",
                enhancement_modes=["auto_review"],
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
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "get_telegram_review_bot_service", lambda: fake_review_bot)
    monkeypatch.setattr(content_profile_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(
        content_profile_mod,
        "build_content_profile_auto_review_gate",
        lambda **kwargs: {
            "gate_passed": True,
            "detail": "自动放行候选样本人工确认准确率 95.0%，已达到 90% 门槛。",
            "measured_accuracy": 0.95,
            "required_accuracy": float(kwargs["min_accuracy"]),
            "sample_size": 24,
            "minimum_sample_size": int(kwargs["min_samples"]),
            "manual_review_total": 30,
        },
    )

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
        assert set(artifact_map) == {"content_profile_draft", "content_profile_final", "downstream_context"}

        draft = artifact_map["content_profile_draft"]
        final = artifact_map["content_profile_final"]
        assert artifact_map["downstream_context"]["resolved_profile"]["review_mode"] == "auto_confirmed"
        assert draft["automation_review"]["auto_confirm"] is True
        assert draft["automation_review"]["approval_accuracy_gate_passed"] is True
        assert draft["automation_review"]["approval_accuracy_sample_size"] == 24
        assert draft["creative_profile"]["workflow_mode"] == "standard_edit"
        assert draft["creative_profile"]["enhancement_modes"] == ["auto_review"]
        assert final["review_mode"] == "auto_confirmed"

        review_step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
        )
        review_step = review_step_result.scalar_one()
        assert review_step.status == "done"
        assert review_step.metadata_["auto_confirmed"] is True

    assert fake_review_bot.content_profile_notifications == []


@pytest.mark.asyncio
async def test_run_content_profile_keeps_manual_review_when_auto_review_mode_disabled(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod
    from roughcut.review import content_profile as content_profile_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    fake_review_bot = _FakeTelegramReviewBotService()
    settings = SimpleNamespace(
        auto_confirm_content_profile=True,
        content_profile_review_threshold=0.72,
        content_profile_auto_review_min_accuracy=0.9,
        content_profile_auto_review_min_samples=20,
    )

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="screen_tutorial",
                enhancement_modes=[],
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
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "get_telegram_review_bot_service", lambda: fake_review_bot)
    monkeypatch.setattr(content_profile_mod, "get_settings", lambda: settings)

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

    assert result["auto_confirmed"] is False
    assert result["automation_score"] >= 0.72

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id).order_by(Artifact.created_at.asc())
        )
        artifacts = artifact_result.scalars().all()
        artifact_map = {item.artifact_type: item.data_json for item in artifacts}
        assert set(artifact_map) == {"content_profile_draft", "downstream_context"}
        assert artifact_map["content_profile_draft"]["automation_review"]["auto_confirm"] is False
        assert artifact_map["downstream_context"]["manual_review_applied"] is False

        review_step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
        )
        review_step = review_step_result.scalar_one()
        assert review_step.status == "pending"
        assert review_step.metadata_ is None

    assert fake_review_bot.content_profile_notifications == [job_id]


@pytest.mark.asyncio
async def test_run_content_profile_passes_effective_glossary_terms_into_inference(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    captured: dict[str, object] = {}

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="unboxing_default",
                enhancement_modes=[],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="content_profile", status="running"))
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        session.add(
            GlossaryTerm(
                wrong_forms=["鸿福", "狐蝠"],
                correct_form="狐蝠工业",
                category="bag_brand",
                context_hint="主流机能包品牌",
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="这期鸿福 F叉二一小副包做个开箱测评。",
                text_norm="这期鸿福 F叉二一小副包做个开箱测评。",
                text_final="这期鸿福 F叉二一小副包做个开箱测评。",
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        captured["glossary_terms"] = kwargs.get("glossary_terms")
        return {
            "preset_name": "unboxing_default",
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
            "subject_type": "EDC机能包",
            "video_theme": "狐蝠工业FXX1小副包开箱与上手评测",
            "summary": "这条视频主要围绕狐蝠工业 FXX1小副包展开，重点看分仓、挂点和日常收纳。",
            "engagement_question": "你更看重副包的分仓还是挂点？",
            "search_queries": ["狐蝠工业 FXX1小副包"],
            "cover_title": {"top": "狐蝠工业", "main": "FXX1小副包", "bottom": "分仓挂点先看"},
            "evidence": [{"title": "狐蝠工业 FXX1小副包"}],
        }

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)

    result = await run_content_profile(str(job_id))

    assert result["subject_brand"] == "狐蝠工业"
    assert any(
        item.get("correct_form") == "狐蝠工业"
        for item in list(captured.get("glossary_terms") or [])
    )


@pytest.mark.asyncio
async def test_run_content_profile_blocks_auto_confirm_for_first_seen_product_identity(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod
    from roughcut.review import content_profile as content_profile_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    fake_review_bot = _FakeTelegramReviewBotService()
    settings = SimpleNamespace(
        auto_confirm_content_profile=True,
        content_profile_review_threshold=0.72,
        content_profile_auto_review_min_accuracy=0.9,
        content_profile_auto_review_min_samples=20,
    )

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="IMG_0025.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="unboxing_default",
                enhancement_modes=["auto_review"],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="content_profile", status="running"))
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        session.add(
            GlossaryTerm(
                wrong_forms=["鸿福", "狐蝠"],
                correct_form="狐蝠工业",
                category="bag_brand",
                context_hint="主流机能包品牌",
            )
        )
        session.add(
            GlossaryTerm(
                wrong_forms=["F叉二一小副包"],
                correct_form="FXX1小副包",
                category="bag_model",
                context_hint="机能包型号",
            )
        )
        for index, text in enumerate(
            [
                "这期鸿福 F叉二一小副包做个开箱测评。",
                "重点看分仓和挂点设计。",
                "日常收纳会更直观一点。",
                "整体装载和细节也都聊一下。",
                "最后再说说通勤场景适不适合。",
                "这次主要还是上手体验。",
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
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "get_telegram_review_bot_service", lambda: fake_review_bot)
    monkeypatch.setattr(content_profile_mod, "get_settings", lambda: settings)

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        return {
            "preset_name": "unboxing_default",
            "subject_brand": "狐蝠工业",
            "subject_model": "FXX1小副包",
            "subject_type": "EDC机能包",
            "video_theme": "狐蝠工业FXX1小副包开箱与上手评测",
            "summary": "这条视频主要围绕狐蝠工业 FXX1小副包展开，重点看分仓、挂点和日常收纳。",
            "engagement_question": "你更看重副包的分仓还是挂点？",
            "search_queries": ["狐蝠工业 FXX1小副包", "FXX1小副包 开箱"],
            "cover_title": {"top": "狐蝠工业", "main": "FXX1小副包", "bottom": "分仓挂点先看"},
            "evidence": [],
        }

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)

    result = await run_content_profile(str(job_id))

    assert result["auto_confirmed"] is False

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "content_profile_draft")
        )
        draft = artifact_result.scalar_one()
        assert "具体品牌型号待人工确认" in draft.data_json["summary"]
        assert draft.data_json["automation_review"]["identity_review"]["required"] is True

        review_step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
        )
        review_step = review_step_result.scalar_one()
        assert review_step.status == "pending"
        assert "首次品牌/型号" in review_step.metadata_["detail"]

    assert fake_review_bot.content_profile_notifications == [job_id]


@pytest.mark.asyncio
async def test_run_subtitle_translation_generates_english_artifact_when_enabled(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="edc_tactical",
                enhancement_modes=["multilingual_translation"],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="subtitle_translation", status="running"))
        for index, text in enumerate(["这是第一句。", "这是第二句。"]):
            session.add(
                SubtitleItem(
                    job_id=job_id,
                    version=1,
                    item_index=index,
                    start_time=float(index),
                    end_time=float(index) + 1.2,
                    text_raw=text,
                    text_norm=text,
                    text_final=text,
                )
            )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    async def fake_translate_subtitle_items(subtitle_items, *, target_language=None, target_language_mode="auto", preferred_ui_language="zh-CN"):
        assert target_language_mode == "auto"
        assert preferred_ui_language == "zh-CN"
        return {
            "target_language": "en",
            "target_language_mode": "auto",
            "source_language": "zh-CN",
            "item_count": 2,
            "items": [
                {"index": 0, "text_source": "这是第一句。", "text_translated": "This is the first line."},
                {"index": 1, "text_source": "这是第二句。", "text_translated": "This is the second line."},
            ],
        }

    monkeypatch.setattr(steps_mod, "translate_subtitle_items", fake_translate_subtitle_items)

    result = await steps_mod.run_subtitle_translation(str(job_id))

    assert result["enabled"] is True
    assert result["source_language"] == "zh-CN"
    assert result["target_language_mode"] == "auto"
    assert result["target_language"] == "en"
    assert result["translated_count"] == 2

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "subtitle_translation")
        )
        artifact = artifact_result.scalar_one()
        assert artifact.data_json["target_language"] == "en"
        assert artifact.data_json["target_language_mode"] == "auto"
        assert artifact.data_json["items"][0]["text_translated"] == "This is the first line."


@pytest.mark.asyncio
async def test_run_subtitle_translation_skips_when_mode_disabled(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                enhancement_modes=[],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="subtitle_translation", status="running"))
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    result = await steps_mod.run_subtitle_translation(str(job_id))

    assert result == {"enabled": False, "skipped": True}

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "subtitle_translation")
        )
        assert artifact_result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_run_subtitle_translation_skips_when_source_matches_target_language(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="en-US",
                enhancement_modes=["multilingual_translation"],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="subtitle_translation", status="running"))
        for index, text in enumerate(["This is the first line.", "This is the second line."]):
            session.add(
                SubtitleItem(
                    job_id=job_id,
                    version=1,
                    item_index=index,
                    start_time=float(index),
                    end_time=float(index) + 1.2,
                    text_raw=text,
                    text_norm=text,
                    text_final=text,
                )
            )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(
        steps_mod,
        "get_settings",
        lambda: SimpleNamespace(preferred_ui_language="en-US"),
    )

    async def fail_translate_subtitle_items(*args, **kwargs):
        raise AssertionError("translate_subtitle_items should not be called when source and target match")

    monkeypatch.setattr(steps_mod, "translate_subtitle_items", fail_translate_subtitle_items)

    result = await steps_mod.run_subtitle_translation(str(job_id))

    assert result["enabled"] is True
    assert result["skipped"] is True
    assert result["reason"] == "same_language"
    assert result["source_language"] == "en-US"
    assert result["target_language"] == "en"
    assert result["translated_count"] == 0

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "subtitle_translation")
        )
        assert artifact_result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_run_content_profile_does_not_trust_seeded_profile_without_current_identity_evidence(db_engine, monkeypatch):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = Path(__file__)
    fake_review_bot = _FakeTelegramReviewBotService()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="E:/videos/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="edc_tactical",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="content_profile", status="running"))
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile",
                data_json={
                    "subject_brand": "Loop露普",
                    "subject_model": "SK05二代Pro UV版",
                    "subject_type": "手电",
                    "video_theme": "手电开箱评测",
                    "preset_name": "edc_tactical",
                },
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="这期重点看夹持、补光范围和实际手感。",
                text_norm="这期重点看夹持、补光范围和实际手感。",
                text_final="这期重点看夹持、补光范围和实际手感。",
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(steps_mod, "get_telegram_review_bot_service", lambda: fake_review_bot)

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_enrich_content_profile(**kwargs):
        profile = dict(kwargs["profile"])
        profile["engagement_question"] = "你更看重 UV 还是主灯？"
        return profile

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        return {
            "subject_brand": "Loop¶��",
            "subject_model": "SK05����Pro UV��",
            "subject_type": "�ֵ�",
            "video_theme": "�ֵ翪������",
            "engagement_question": "\u4f60\u66f4\u770b\u91cd UV \u8fd8\u662f\u4e3b\u706f\uff1f",
            "workflow_template": "edc_tactical",
        }

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "enrich_content_profile", fake_enrich_content_profile)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)

    result = await run_content_profile(str(job_id))

    assert result["subject_brand"] in {"", None}
    assert result["subject_model"] in {"", None}

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "content_profile_draft")
        )
        draft = artifact_result.scalar_one()
        assert draft.data_json["subject_brand"] in {"", None}
        assert draft.data_json["subject_model"] in {"", None}
        assert draft.data_json["engagement_question"] == "你更看重 UV 还是主灯？"

    assert fake_review_bot.content_profile_notifications == [job_id]


@pytest.mark.asyncio
async def test_run_content_profile_applies_llm_resolved_final_review_feedback_and_bypasses_summary_review(
    db_engine,
    monkeypatch,
    tmp_path: Path,
):
    import roughcut.pipeline.steps as steps_mod
    from roughcut.review import content_profile as content_profile_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    fake_review_bot = _FakeTelegramReviewBotService()
    settings = SimpleNamespace(
        auto_confirm_content_profile=False,
        content_profile_review_threshold=0.72,
        content_profile_auto_review_min_accuracy=0.9,
        content_profile_auto_review_min_samples=20,
    )

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                workflow_template="edc_tactical",
                enhancement_modes=[],
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="content_profile",
                status="running",
                metadata_={
                    "review_feedback": "品牌改成傲雷，型号改成司令官2Ultra。",
                    "review_user_feedback": {
                        "subject_brand": "傲雷",
                        "subject_model": "司令官2Ultra",
                    },
                },
            )
        )
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        for index, text in enumerate(
            [
                "这次对比 slim2 的 ultra 版本和 pro 版差别。",
                "我更喜欢 ultra 这个版本的手感。",
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
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "get_telegram_review_bot_service", lambda: fake_review_bot)
    monkeypatch.setattr(content_profile_mod, "get_settings", lambda: settings)

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        return {
            "preset_name": "edc_tactical",
            "subject_brand": "OLIGHT",
            "subject_model": "SLIM2 Ultra",
            "subject_type": "EDC手电",
            "video_theme": "SLIM2 Ultra 与 PRO 版本对比",
            "summary": "视频围绕 SLIM2 Ultra 与 PRO 版本对比展开。",
            "engagement_question": "你更喜欢 ultra 还是 pro？",
            "search_queries": ["SLIM2 Ultra 手电"],
            "cover_title": {"top": "SLIM2", "main": "Ultra对比", "bottom": "版本怎么选"},
            "evidence": [],
        }

    async def fake_resolve_content_profile_review_feedback(**kwargs):
        assert kwargs["review_feedback"] == "品牌改成傲雷，型号改成司令官2Ultra。"
        assert kwargs["proposed_feedback"] == {
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
        }
        return {
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
            "subject_type": "傲雷司令官2手电筒",
        }

    async def fake_apply_content_profile_feedback(**kwargs):
        assert kwargs["user_feedback"] == {
            "subject_brand": "傲雷",
            "subject_model": "司令官2Ultra",
            "subject_type": "傲雷司令官2手电筒",
        }
        profile = dict(kwargs["draft_profile"])
        profile.update(
            {
                "subject_brand": "傲雷",
                "subject_model": "司令官2Ultra",
                "subject_type": "傲雷司令官2Ultra手电筒",
                "video_theme": "傲雷司令官2Ultra 版本选择与上手对比",
                "summary": "视频围绕傲雷司令官2Ultra的版本差异与上手体验展开。",
                "user_feedback": dict(kwargs["user_feedback"]),
                "review_mode": "manual_confirmed",
            }
        )
        return profile

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)
    monkeypatch.setattr(steps_mod, "build_review_feedback_verification_bundle", AsyncMock(return_value=None))
    monkeypatch.setattr(steps_mod, "resolve_content_profile_review_feedback", fake_resolve_content_profile_review_feedback)
    monkeypatch.setattr(steps_mod, "apply_content_profile_feedback", fake_apply_content_profile_feedback)

    result = await run_content_profile(str(job_id))

    assert result["subject_brand"] == "傲雷"
    assert result["subject_model"] == "司令官2Ultra"

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id).order_by(Artifact.created_at.asc())
        )
        artifacts = artifact_result.scalars().all()
        artifact_map = {item.artifact_type: item.data_json for item in artifacts}
        assert set(artifact_map) == {"content_profile_draft", "content_profile_final", "downstream_context"}
        assert artifact_map["content_profile_final"]["review_mode"] == "manual_confirmed"
        assert artifact_map["content_profile_final"]["subject_brand"] == "傲雷"
        assert artifact_map["content_profile_final"]["subject_model"] == "司令官2Ultra"
        assert artifact_map["downstream_context"]["resolved_profile"]["subject_brand"] == "傲雷"
        assert artifact_map["downstream_context"]["manual_review_applied"] is True

        review_step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
        )
        review_step = review_step_result.scalar_one()
        assert review_step.status == "done"
        assert review_step.metadata_["detail"] == "已应用成片审核修正并确认内容摘要，继续后续流程。"

    assert fake_review_bot.content_profile_notifications == []


@pytest.mark.asyncio
async def test_run_content_profile_keeps_summary_review_pending_when_final_review_feedback_cannot_be_resolved(
    db_engine,
    monkeypatch,
    tmp_path: Path,
):
    import roughcut.pipeline.steps as steps_mod
    from roughcut.review import content_profile as content_profile_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    fake_review_bot = _FakeTelegramReviewBotService()
    settings = SimpleNamespace(
        auto_confirm_content_profile=False,
        content_profile_review_threshold=0.72,
        content_profile_auto_review_min_accuracy=0.9,
        content_profile_auto_review_min_samples=20,
    )

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                workflow_template="edc_tactical",
                enhancement_modes=[],
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="content_profile",
                status="running",
                metadata_={
                    "review_feedback": "品牌改成傲雷，型号改成司令官2Ultra。",
                    "review_user_feedback": {
                        "subject_brand": "傲雷",
                        "subject_model": "司令官2Ultra",
                    },
                },
            )
        )
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="这次对比 slim2 的 ultra 版本。",
                text_norm="这次对比 slim2 的 ultra 版本。",
                text_final="这次对比 slim2 的 ultra 版本。",
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "get_telegram_review_bot_service", lambda: fake_review_bot)
    monkeypatch.setattr(content_profile_mod, "get_settings", lambda: settings)

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        return {
            "subject_brand": "OLIGHT",
            "subject_model": "SLIM2 Ultra",
            "subject_type": "EDC手电",
            "video_theme": "SLIM2 Ultra 与 PRO 版本对比",
            "summary": "视频围绕 SLIM2 Ultra 与 PRO 版本对比展开。",
            "engagement_question": "你更喜欢 ultra 还是 pro？",
            "search_queries": ["SLIM2 Ultra 手电"],
            "cover_title": {"top": "SLIM2", "main": "Ultra对比", "bottom": "版本怎么选"},
            "evidence": [],
        }

    async def fake_resolve_content_profile_review_feedback(**kwargs):
        return {}

    async def fail_apply_content_profile_feedback(**kwargs):
        raise AssertionError("empty resolved patch should not be applied")

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)
    monkeypatch.setattr(steps_mod, "build_review_feedback_verification_bundle", AsyncMock(return_value=None))
    monkeypatch.setattr(steps_mod, "resolve_content_profile_review_feedback", fake_resolve_content_profile_review_feedback)
    monkeypatch.setattr(steps_mod, "apply_content_profile_feedback", fail_apply_content_profile_feedback)

    await run_content_profile(str(job_id))

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job_id).order_by(Artifact.created_at.asc())
        )
        artifacts = artifact_result.scalars().all()
        artifact_map = {item.artifact_type: item.data_json for item in artifacts}
        assert set(artifact_map) == {"content_profile_draft", "downstream_context"}
        assert (
            artifact_map["downstream_context"]["resolved_profile"]["subject_brand"]
            == artifact_map["content_profile_draft"]["subject_brand"]
        )

        review_step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
        )
        review_step = review_step_result.scalar_one()
        assert review_step.status == "pending"

    assert fake_review_bot.content_profile_notifications == [job_id]


@pytest.mark.asyncio
async def test_run_content_profile_resets_stale_manual_confirmed_summary_review_when_review_feedback_cannot_be_resolved(
    db_engine,
    monkeypatch,
    tmp_path: Path,
):
    import roughcut.pipeline.steps as steps_mod
    from roughcut.review import content_profile as content_profile_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    fake_review_bot = _FakeTelegramReviewBotService()
    settings = SimpleNamespace(
        auto_confirm_content_profile=False,
        content_profile_review_threshold=0.72,
        content_profile_auto_review_min_accuracy=0.9,
        content_profile_auto_review_min_samples=20,
    )

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                workflow_template="edc_tactical",
                enhancement_modes=[],
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="content_profile",
                status="running",
                metadata_={
                    "review_feedback": "品牌改成傲雷，型号改成司令官2Ultra。",
                    "review_user_feedback": {
                        "subject_brand": "傲雷",
                        "subject_model": "司令官2Ultra",
                    },
                },
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="summary_review",
                status="done",
                metadata_={
                    "detail": "已应用成片审核修正并确认内容摘要，继续后续流程。",
                    "manual_confirmed": True,
                    "review_user_feedback": {
                        "subject_brand": "傲雷",
                        "subject_model": "司令官2Ultra",
                    },
                    "resolved_review_user_feedback": {
                        "subject_brand": "傲雷",
                        "subject_model": "司令官2Ultra",
                    },
                },
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="这次对比 slim2 的 ultra 版本。",
                text_norm="这次对比 slim2 的 ultra 版本。",
                text_final="这次对比 slim2 的 ultra 版本。",
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "get_telegram_review_bot_service", lambda: fake_review_bot)
    monkeypatch.setattr(content_profile_mod, "get_settings", lambda: settings)

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        return {
            "subject_brand": "OLIGHT",
            "subject_model": "SLIM2 Ultra",
            "subject_type": "EDC手电",
            "video_theme": "SLIM2 Ultra 与 PRO 版本对比",
            "summary": "视频围绕 SLIM2 Ultra 与 PRO 版本对比展开。",
            "engagement_question": "你更喜欢 ultra 还是 pro？",
            "search_queries": ["SLIM2 Ultra 手电"],
            "cover_title": {"top": "SLIM2", "main": "Ultra对比", "bottom": "版本怎么选"},
            "evidence": [],
        }

    async def fake_resolve_content_profile_review_feedback(**kwargs):
        return {}

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)
    monkeypatch.setattr(steps_mod, "build_review_feedback_verification_bundle", AsyncMock(return_value=None))
    monkeypatch.setattr(steps_mod, "resolve_content_profile_review_feedback", fake_resolve_content_profile_review_feedback)

    await run_content_profile(str(job_id))

    async with factory() as session:
        review_step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
        )
        review_step = review_step_result.scalar_one()
        assert review_step.status == "pending"
        assert review_step.metadata_["detail"] == "成片审核修正尚未确认到当前主体，等待人工继续确认。"
        assert review_step.metadata_["manual_confirmed"] is False
        assert review_step.metadata_["resolved_review_user_feedback"] == {}


@pytest.mark.asyncio
async def test_run_content_profile_persists_dedicated_ocr_artifact_when_enabled(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    fake_review_bot = _FakeTelegramReviewBotService()
    settings = SimpleNamespace(
        auto_confirm_content_profile=False,
        content_profile_review_threshold=0.72,
        content_profile_auto_review_min_accuracy=0.9,
        content_profile_auto_review_min_samples=20,
        ocr_enabled=True,
        entity_graph_enabled=False,
        asr_evidence_enabled=False,
        research_verifier_enabled=False,
        correction_framework_version="multisource_v1",
    )

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
        session.add(JobStep(job_id=job_id, step_name="content_profile", status="running"))
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="这期看傲雷新手电。",
                text_norm="这期看傲雷新手电。",
                text_final="这期看傲雷新手电。",
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "get_telegram_review_bot_service", lambda: fake_review_bot)

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        return {
            "subject_brand": "傲雷",
            "subject_model": "司令官2 Ultra",
            "subject_type": "手电筒",
            "video_theme": "傲雷手电开箱",
            "visible_text": "傲雷 司令官2 Ultra",
            "ocr_profile": {
                "available": True,
                "status": "ok",
                "visible_text": "傲雷 司令官2 Ultra",
                "raw_snippets": [{"text": "傲雷 司令官2 Ultra"}],
                "normalized_subject_candidates": [{"normalized_text": "傲雷 司令官2 ultra"}],
            },
        }

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)

    await run_content_profile(str(job_id))

    async with factory() as session:
        artifacts = (
            await session.execute(select(Artifact).where(Artifact.job_id == job_id).order_by(Artifact.created_at.asc()))
        ).scalars().all()
        artifact_map = {item.artifact_type: item.data_json for item in artifacts}

        assert "content_profile_draft" in artifact_map
        assert "content_profile_ocr" in artifact_map
        assert "ocr_profile" not in artifact_map["content_profile_draft"]
        assert artifact_map["content_profile_ocr"]["visible_text"] == "傲雷 司令官2 Ultra"


@pytest.mark.asyncio
async def test_run_content_profile_passes_include_research_when_enabled(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.llm_cache as llm_cache_mod
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    fake_review_bot = _FakeTelegramReviewBotService()
    settings = SimpleNamespace(
        auto_confirm_content_profile=False,
        content_profile_review_threshold=0.72,
        content_profile_auto_review_min_accuracy=0.9,
        content_profile_auto_review_min_samples=20,
        ocr_enabled=False,
        entity_graph_enabled=False,
        asr_evidence_enabled=False,
        research_verifier_enabled=True,
        correction_framework_version="multisource_v1",
        output_dir=str(tmp_path / "output"),
        step_heartbeat_interval_sec=20,
    )
    captured: dict[str, object] = {}

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                file_hash="hash-demo",
                status="processing",
                language="zh-CN",
                channel_profile="edc_tactical",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="content_profile", status="running"))
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="这期主要看赫斯郡和船家联名的机能双剑包。",
                text_norm="这期主要看赫斯郡和船家联名的机能双剑包。",
                text_final="这期主要看赫斯郡和船家联名的机能双剑包。",
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "get_telegram_review_bot_service", lambda: fake_review_bot)
    monkeypatch.setattr(llm_cache_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "list_packaging_assets", lambda: {"config": {"copy_style": "attention_grabbing"}})

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        captured["include_research"] = kwargs["include_research"]
        return {
            "subject_type": "机能双肩包",
            "video_theme": "联名机能双肩包开箱",
            "summary": "这条视频主要围绕机能双肩包展开。",
            "engagement_question": "你更偏黑色还是白色版本？",
            "search_queries": ["机能双肩包 评测"],
        }

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)

    await run_content_profile(str(job_id))

    assert captured["include_research"] is True


@pytest.mark.asyncio
async def test_run_content_profile_reinfers_fresh_when_old_profile_artifact_exists(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    fake_review_bot = _FakeTelegramReviewBotService()
    infer_calls: list[dict[str, object]] = []

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
        session.add(JobStep(job_id=job_id, step_name="content_profile", status="running"))
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile",
                data_json={
                    "subject_brand": "COMFYUI",
                    "subject_model": "",
                    "subject_type": "AI图像工作流工具",
                    "video_theme": "COMFYUI 工作流演示",
                },
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="今天我们收到了一个新的手电筒",
                text_norm="今天我们收到了一个新的手电筒",
                text_final="今天我们收到了一个新的手电筒",
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=1,
                start_time=1.0,
                end_time=2.0,
                text_raw="今天收到 OLIGHT Arkflex 这个新手电筒",
                text_norm="今天收到 OLIGHT Arkflex 这个新手电筒",
                text_final="今天收到 OLIGHT Arkflex 这个新手电筒",
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(steps_mod, "get_telegram_review_bot_service", lambda: fake_review_bot)

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        infer_calls.append(kwargs)
        return {
            "subject_brand": "OLIGHT",
            "subject_model": "Arkflex",
            "subject_type": "手电筒",
            "video_theme": "OLIGHT Arkflex 手电开箱",
            "engagement_question": "你会拿它做 EDC 吗？",
            "workflow_template": "edc_tactical",
        }

    async def fail_enrich_content_profile(**kwargs):
        raise AssertionError("run_content_profile should not seed from an older same-job content profile artifact")

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)
    monkeypatch.setattr(steps_mod, "enrich_content_profile", fail_enrich_content_profile)

    result = await run_content_profile(str(job_id))

    assert infer_calls
    assert result["subject_brand"] == "OLIGHT"
    assert result["subject_model"] in {"Arkflex", "", None}
    assert "COMFYUI" not in str(result.get("video_theme") or "").upper()

    async with factory() as session:
        draft = (
            await session.execute(
                select(Artifact)
                .where(Artifact.job_id == job_id, Artifact.artifact_type == "content_profile_draft")
                .order_by(Artifact.created_at.desc(), Artifact.id.desc())
            )
        ).scalars().first()
        assert draft is not None
        assert draft.data_json["subject_brand"] == "OLIGHT"
        assert draft.data_json["subject_model"] in {"Arkflex", "", None}
        assert "COMFYUI" not in str(draft.data_json.get("video_theme") or "").upper()

    assert fake_review_bot.content_profile_notifications == [job_id]


@pytest.mark.asyncio
async def test_run_content_profile_reuses_strict_cache_for_identical_inputs(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.llm_cache as llm_cache_mod
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    fake_review_bot = _FakeTelegramReviewBotService()
    settings = SimpleNamespace(
        auto_confirm_content_profile=False,
        content_profile_review_threshold=0.72,
        content_profile_auto_review_min_accuracy=0.9,
        content_profile_auto_review_min_samples=20,
        output_dir=str(tmp_path / "output"),
        step_heartbeat_interval_sec=20,
    )
    infer_calls = {"count": 0}

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                file_hash="hash-demo",
                status="processing",
                language="zh-CN",
                channel_profile="screen_tutorial",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="content_profile", status="running"))
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="这期演示剪映里怎么批量处理字幕样式",
                text_norm="这期演示剪映里怎么批量处理字幕样式",
                text_final="这期演示剪映里怎么批量处理字幕样式",
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "get_telegram_review_bot_service", lambda: fake_review_bot)
    monkeypatch.setattr(llm_cache_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "list_packaging_assets", lambda: {"config": {"copy_style": "attention_grabbing"}})

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        infer_calls["count"] += 1
        return {
            "preset_name": "screen_tutorial",
            "subject_type": "剪映字幕工作流",
            "video_theme": "批量字幕样式调整步骤讲解",
            "summary": "讲清批量字幕样式调整流程。",
            "engagement_question": "你做批量字幕时最容易卡在哪一步？",
            "search_queries": ["剪映 批量字幕 样式"],
            "cover_title": {"top": "剪映", "main": "字幕样式流程", "bottom": "批量调整"},
        }

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)

    await run_content_profile(str(job_id))
    await run_content_profile(str(job_id))

    assert infer_calls["count"] == 1

    async with factory() as session:
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "content_profile")
        )
        step = step_result.scalar_one()
        assert step.metadata_["cache"]["content_profile"]["hit"] is True


@pytest.mark.asyncio
async def test_run_content_profile_does_not_inject_related_profile_source_context_for_independent_clip(
    db_engine,
    monkeypatch,
    tmp_path: Path,
):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    related_job_id = uuid.uuid4()
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    fake_review_bot = _FakeTelegramReviewBotService()
    settings = SimpleNamespace(
        auto_confirm_content_profile=False,
        content_profile_review_threshold=0.72,
        content_profile_auto_review_min_accuracy=0.9,
        content_profile_auto_review_min_samples=20,
    )
    captured: dict[str, object] = {}

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/current.mp4",
                source_name="20260130-140529.mp4",
                file_hash="hash-current",
                status="processing",
                language="zh-CN",
                channel_profile="edc_tactical",
                output_dir=str(tmp_path / "out"),
            )
        )
        session.add(
            Job(
                id=related_job_id,
                source_path="jobs/demo/related.mp4",
                source_name="20260130-134317.mp4",
                file_hash="hash-related",
                status="needs_review",
                language="zh-CN",
                channel_profile="edc_tactical",
                output_dir=str(tmp_path / "out"),
            )
        )
        session.add(JobStep(job_id=job_id, step_name="content_profile", status="running"))
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        session.add(
            Artifact(
                job_id=related_job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_brand": "LEATHERMAN",
                    "subject_model": "ARC",
                    "subject_type": "多功能工具钳",
                    "video_theme": "LEATHERMAN ARC 多功能工具钳开箱测评",
                    "summary": "这条视频主要围绕 LEATHERMAN ARC 展开。",
                    "search_queries": ["LEATHERMAN ARC 开箱"],
                },
            )
        )
        for index, text in enumerate(
            [
                "这条主要继续看这把工具钳的单手开合",
                "后面再补一下钳头结构和批头替换",
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
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "get_telegram_review_bot_service", lambda: fake_review_bot)
    monkeypatch.setattr(steps_mod, "list_packaging_assets", lambda: {"config": {"copy_style": "attention_grabbing"}})

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        captured["source_context"] = kwargs.get("source_context") or {}
        return {
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "多功能工具钳",
            "video_theme": "",
            "summary": "这条视频主要围绕多功能工具钳展开，内容方向偏产品开箱与上手体验，适合后续做搜索校验、字幕纠错和剪辑包装。",
            "search_queries": [],
            "source_context": dict(kwargs.get("source_context") or {}),
            "workflow_template": "edc_tactical",
        }

    async def fake_enrich_content_profile(**kwargs):
        return dict(kwargs["profile"])

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)
    monkeypatch.setattr(steps_mod, "enrich_content_profile", fake_enrich_content_profile)

    result = await run_content_profile(str(job_id))

    related_profiles = list((captured["source_context"] or {}).get("related_profiles") or [])
    assert related_profiles == []
    assert result["subject_brand"] == ""
    assert result["subject_model"] == ""
    assert "ARC" not in str(result.get("video_theme") or "")

    async with factory() as session:
        draft_result = await session.execute(
            select(Artifact)
            .where(Artifact.job_id == job_id, Artifact.artifact_type == "content_profile_draft")
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
        draft = draft_result.scalars().first()
        assert draft is not None
        assert "ARC" not in str((draft.data_json or {}).get("summary") or "")


@pytest.mark.asyncio
async def test_run_content_profile_injects_related_profile_source_context_only_for_manual_merged_clip(
    db_engine,
    monkeypatch,
    tmp_path: Path,
):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    related_job_id = uuid.uuid4()
    source_path = tmp_path / "watch_merge_demo.mp4"
    source_path.write_bytes(b"video")
    fake_review_bot = _FakeTelegramReviewBotService()
    settings = SimpleNamespace(
        auto_confirm_content_profile=False,
        content_profile_review_threshold=0.72,
        content_profile_auto_review_min_accuracy=0.9,
        content_profile_auto_review_min_samples=20,
    )
    captured: dict[str, object] = {}

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/watch_merge_demo.mp4",
                source_name="watch_merge_demo.mp4",
                file_hash="hash-current",
                status="processing",
                language="zh-CN",
                channel_profile="edc_tactical",
                output_dir=str(tmp_path / "out"),
            )
        )
        session.add(
            Job(
                id=related_job_id,
                source_path="jobs/demo/related.mp4",
                source_name="20260130-134317.mp4",
                file_hash="hash-related",
                status="needs_review",
                language="zh-CN",
                channel_profile="edc_tactical",
                output_dir=str(tmp_path / "out"),
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="content_profile",
                status="running",
                metadata_={
                    "source_context": {
                        "allow_related_profiles": True,
                        "merged_source_names": ["20260130-134317.mp4"],
                    }
                },
            )
        )
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        session.add(
            Artifact(
                job_id=related_job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_brand": "LEATHERMAN",
                    "subject_model": "ARC",
                    "subject_type": "多功能工具钳",
                    "video_theme": "LEATHERMAN ARC 多功能工具钳开箱测评",
                    "summary": "这条视频主要围绕 LEATHERMAN ARC 展开。",
                    "search_queries": ["LEATHERMAN ARC 开箱"],
                },
            )
        )
        for index, text in enumerate(
            [
                "这条主要继续看这把工具钳的单手开合",
                "后面再补一下钳头结构和批头替换",
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
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "get_telegram_review_bot_service", lambda: fake_review_bot)
    monkeypatch.setattr(steps_mod, "list_packaging_assets", lambda: {"config": {"copy_style": "attention_grabbing"}})

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        captured["source_context"] = kwargs.get("source_context") or {}
        return {
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "多功能工具钳",
            "video_theme": "",
            "summary": "这条视频主要围绕多功能工具钳展开，内容方向偏产品开箱与上手体验，适合后续做搜索校验、字幕纠错和剪辑包装。",
            "search_queries": [],
            "source_context": dict(kwargs.get("source_context") or {}),
            "workflow_template": "edc_tactical",
        }

    async def fake_enrich_content_profile(**kwargs):
        return dict(kwargs["profile"])

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)
    monkeypatch.setattr(steps_mod, "enrich_content_profile", fake_enrich_content_profile)

    result = await run_content_profile(str(job_id))

    related_profiles = list((captured["source_context"] or {}).get("related_profiles") or [])
    assert related_profiles
    assert related_profiles[0]["subject_model"] == "ARC"
    assert result["subject_brand"] == "LEATHERMAN"
    assert result["subject_model"] == "ARC"
    assert "ARC" in str(result.get("video_theme") or "")


@pytest.mark.asyncio
async def test_run_content_profile_ignores_stale_infer_cache_after_framework_version_bump(
    db_engine,
    monkeypatch,
    tmp_path: Path,
):
    import roughcut.llm_cache as llm_cache_mod
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "digital-host.mp4"
    source_path.write_bytes(b"video")
    fake_review_bot = _FakeTelegramReviewBotService()
    settings = SimpleNamespace(
        auto_confirm_content_profile=False,
        content_profile_review_threshold=0.72,
        content_profile_auto_review_min_accuracy=0.9,
        content_profile_auto_review_min_samples=20,
        output_dir=str(tmp_path / "output"),
        step_heartbeat_interval_sec=20,
    )
    infer_calls = {"count": 0}
    subtitle_texts = [
        "大家好欢迎来到我的。",
        "播数字人播客测试现场。",
        "今天想和大家简单聊一聊看看数。",
        "字人的表达是否自然清晰。",
        "互动有没有更加温度。",
        "未来希望通过这样的方式把更多有。",
    ]

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/digital-host.mp4",
                source_name="8ab62636b25b4b6ba8398467ddfb371a.mp4",
                file_hash="digital-host-hash",
                status="processing",
                language="zh-CN",
                channel_profile="",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="content_profile", status="running"))
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        for index, text in enumerate(subtitle_texts):
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
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "get_telegram_review_bot_service", lambda: fake_review_bot)
    monkeypatch.setattr(llm_cache_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "list_packaging_assets", lambda: {"config": {"copy_style": "attention_grabbing"}})

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        infer_calls["count"] += 1
        return {
            "workflow_template": "commentary_focus",
            "content_kind": "commentary",
            "subject_type": "数字人口播",
            "video_theme": "数字人口播表达自然度测试",
            "summary": "这条视频主要围绕数字人口播表达自然度测试展开，重点看表达清晰度和互动感。",
            "engagement_question": "你觉得这种数字人口播的表达自然吗？",
            "search_queries": ["数字人口播 表达 自然度", "数字人 播客 测试"],
            "cover_title": {"top": "数字人", "main": "口播表达测试", "bottom": "自然度如何"},
        }

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)

    transcript_excerpt = steps_mod.build_transcript_excerpt(
        [
            {
                "index": index,
                "start_time": float(index),
                "end_time": float(index) + 1.0,
                "text_raw": text,
                "text_norm": text,
                "text_final": text,
            }
            for index, text in enumerate(subtitle_texts)
        ]
    )
    stale_fingerprint = steps_mod.build_content_profile_cache_fingerprint(
        source_name="8ab62636b25b4b6ba8398467ddfb371a.mp4",
        source_file_hash="digital-host-hash",
        workflow_template="",
        transcript_excerpt=transcript_excerpt,
        glossary_terms=[],
        user_memory={},
        include_research=False,
        copy_style="attention_grabbing",
    )
    stale_fingerprint["version"] = "2026-04-01.enrich.v2"
    stale_key = llm_cache_mod.build_cache_key("content_profile.infer", stale_fingerprint)
    llm_cache_mod.save_cached_json(
        "content_profile.infer",
        stale_key,
        fingerprint=stale_fingerprint,
        result={
            "workflow_template": "unboxing_standard",
            "content_kind": "unboxing",
            "summary": "这条视频主要围绕开箱产品展开，内容方向偏产品开箱与上手体验，适合后续做搜索校验、字幕纠错和剪辑包装。",
            "engagement_question": "潮玩EDC开箱你最想先看哪项细节？",
            "search_queries": [],
            "subject_brand": "",
            "subject_model": "",
            "subject_type": "",
            "subject_domain": "",
            "video_theme": "",
            "cover_title": {"top": "开箱", "main": "潮玩EDC开箱", "bottom": "这次升级够不够狠"},
        },
    )

    await run_content_profile(str(job_id))

    assert infer_calls["count"] == 1

    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact)
            .where(Artifact.job_id == job_id, Artifact.artifact_type == "content_profile_draft")
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
        draft = artifact_result.scalars().first()
        assert draft is not None
        assert draft.data_json["workflow_template"] == "commentary_focus"
        assert draft.data_json["content_kind"] == "commentary"
        assert "开箱产品" not in str(draft.data_json.get("summary") or "")

        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "content_profile")
        )
        step = step_result.scalar_one()
        assert step.metadata_["cache"]["content_profile"]["hit"] is False


@pytest.mark.asyncio
async def test_run_content_profile_rebuilds_cache_when_non_excerpt_subtitles_change(
    db_engine,
    monkeypatch,
    tmp_path: Path,
):
    import roughcut.llm_cache as llm_cache_mod
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    source_path = tmp_path / "long-commentary.mp4"
    source_path.write_bytes(b"video")
    fake_review_bot = _FakeTelegramReviewBotService()
    settings = SimpleNamespace(
        auto_confirm_content_profile=False,
        content_profile_review_threshold=0.72,
        content_profile_auto_review_min_accuracy=0.9,
        content_profile_auto_review_min_samples=20,
        output_dir=str(tmp_path / "output"),
        step_heartbeat_interval_sec=20,
    )
    infer_calls = {"count": 0}

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/long-commentary.mp4",
                source_name="long-commentary.mp4",
                file_hash="long-commentary-hash",
                status="processing",
                language="zh-CN",
                channel_profile="",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="content_profile", status="running"))
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="pending"))
        for index in range(30):
            text = f"第{index:02d}句"
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
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "get_telegram_review_bot_service", lambda: fake_review_bot)
    monkeypatch.setattr(llm_cache_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(steps_mod, "list_packaging_assets", lambda: {"config": {"copy_style": "attention_grabbing"}})

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_resolve_source(*args, **kwargs):
        return source_path

    async def fake_infer_content_profile(**kwargs):
        infer_calls["count"] += 1
        transcript_excerpt = str(kwargs.get("subtitle_items", [{}])[0].get("text_final") or "")
        return {
            "workflow_template": "commentary_focus",
            "content_kind": "commentary",
            "subject_type": "口播观点",
            "video_theme": f"第{infer_calls['count']}轮口播主题",
            "summary": f"第{infer_calls['count']}轮摘要",
            "engagement_question": "你更在意口播信息密度还是表达自然度？",
            "search_queries": [transcript_excerpt],
            "cover_title": {"top": "口播", "main": f"第{infer_calls['count']}轮", "bottom": "缓存刷新"},
        }

    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_resolve_source", fake_resolve_source)
    monkeypatch.setattr(steps_mod, "infer_content_profile", fake_infer_content_profile)

    await run_content_profile(str(job_id))

    async with factory() as session:
        middle_item = (
            await session.execute(
                select(SubtitleItem).where(
                    SubtitleItem.job_id == job_id,
                    SubtitleItem.version == 1,
                    SubtitleItem.item_index == 20,
                )
            )
        ).scalar_one()
        middle_item.text_raw = "数字人口播"
        middle_item.text_norm = "数字人口播"
        middle_item.text_final = "数字人口播"
        await session.commit()

    await run_content_profile(str(job_id))

    assert infer_calls["count"] == 2

    async with factory() as session:
        drafts = (
            await session.execute(
                select(Artifact)
                .where(Artifact.job_id == job_id, Artifact.artifact_type == "content_profile_draft")
                .order_by(Artifact.created_at.asc(), Artifact.id.asc())
            )
        ).scalars().all()
        assert drafts
        assert any(item.data_json.get("video_theme") == "第2轮口播主题" for item in drafts)


@pytest.mark.asyncio
async def test_run_edit_plan_repolishes_subtitles_with_llm_after_content_profile_confirmed(
    db_engine,
    monkeypatch,
    tmp_path: Path,
):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    editorial_timeline_id = uuid.uuid4()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake-audio")
    keep_segments = [{"type": "keep", "start_time": 0.0, "end_time": 2.0}]
    polish_calls: dict[str, object] = {}

    class FakeDecision:
        def to_dict(self):
            return {"segments": keep_segments}

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="unboxing_standard",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="edit_plan", status="running"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="media_meta",
                data_json={"duration": 12.0},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="audio_wav",
                storage_path="jobs/demo/audio.wav",
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "workflow_template": "unboxing_standard",
                    "subject_domain": "edc",
                    "subject_type": "EDC手电",
                    "subject_brand": "傲雷",
                    "subject_model": "司令官2 Ultra",
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="downstream_context",
                data_json={
                    "resolved_profile": {
                        "workflow_template": "unboxing_standard",
                        "subject_domain": "edc",
                        "subject_type": "校对后的手电",
                        "subject_brand": "傲雷校对版",
                        "subject_model": "司令官2 Ultra 校对版",
                    },
                    "field_sources": {
                        "subject_brand": "manual_review",
                        "subject_model": "manual_review",
                    },
                    "manual_review_applied": True,
                    "research_applied": False,
                },
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=2.0,
                text_raw="这次拿到1个新的手电筒。",
                text_norm="这次拿到1个新的手电筒。",
                text_final="这次拿到1个新的手电筒。",
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    async def fake_resolve_storage_reference(*args, **kwargs):
        return audio_path

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_load_recent_subtitle_examples(*args, **kwargs):
        return []

    async def fake_load_related_profile_subtitle_examples(*args, **kwargs):
        return []

    def fake_build_subtitle_review_memory(**kwargs):
        return {"mode": "formal_polish"}

    async def fake_polish_subtitle_items(subtitle_items, **kwargs):
        polish_calls["allow_llm"] = kwargs["allow_llm"]
        polish_calls["content_profile"] = kwargs["content_profile"]
        subtitle_items[0].text_final = "这次拿到一个新的手电筒。"
        return 1

    async def fake_save_editorial_timeline(*args, **kwargs):
        return SimpleNamespace(id=editorial_timeline_id, data_json={"segments": keep_segments}, otio_data=None)

    async def fake_plan_insert_asset_slot(**kwargs):
        return None

    async def fake_plan_music_entry(**kwargs):
        return None

    async def fake_save_render_plan(*args, **kwargs):
        return None

    monkeypatch.setattr(steps_mod, "_resolve_storage_reference", fake_resolve_storage_reference)
    monkeypatch.setattr(steps_mod, "detect_silence", lambda *args, **kwargs: [])
    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_load_recent_subtitle_examples", fake_load_recent_subtitle_examples)
    monkeypatch.setattr(steps_mod, "_load_related_profile_subtitle_examples", fake_load_related_profile_subtitle_examples)
    monkeypatch.setattr(steps_mod, "build_subtitle_review_memory", fake_build_subtitle_review_memory)
    monkeypatch.setattr(steps_mod, "polish_subtitle_items", fake_polish_subtitle_items)
    monkeypatch.setattr(steps_mod, "build_edit_decision", lambda **kwargs: FakeDecision())
    monkeypatch.setattr(steps_mod, "save_editorial_timeline", fake_save_editorial_timeline)
    monkeypatch.setattr(steps_mod, "export_to_otio", lambda *args, **kwargs: "otio")
    monkeypatch.setattr(
        steps_mod,
        "resolve_packaging_plan_for_job",
        lambda *args, **kwargs: {
            "subtitle_style": "bold_yellow_outline",
            "subtitle_motion_style": "motion_static",
            "smart_effect_style": "smart_effect_rhythm",
        },
    )
    monkeypatch.setattr(steps_mod, "remap_subtitles_to_timeline", lambda subtitles, segments: subtitles)
    monkeypatch.setattr(steps_mod, "_plan_insert_asset_slot", fake_plan_insert_asset_slot)
    monkeypatch.setattr(steps_mod, "_plan_music_entry", fake_plan_music_entry)
    monkeypatch.setattr(steps_mod, "build_render_plan", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(steps_mod, "build_smart_editing_accents", lambda **kwargs: {})
    monkeypatch.setattr(steps_mod, "save_render_plan", fake_save_render_plan)

    result = await steps_mod.run_edit_plan(str(job_id))

    assert result["timeline_id"] == str(editorial_timeline_id)
    assert polish_calls["allow_llm"] is True
    assert polish_calls["content_profile"]["subject_brand"] == "傲雷校对版"
    assert polish_calls["content_profile"]["subject_model"] == "司令官2 Ultra 校对版"

    async with factory() as session:
        subtitle = (
            await session.execute(
                select(SubtitleItem).where(SubtitleItem.job_id == job_id, SubtitleItem.item_index == 0)
            )
        ).scalar_one()
        assert subtitle.text_final == "这次拿到一个新的手电筒。"


@pytest.mark.asyncio
async def test_run_edit_plan_falls_back_when_llm_polish_or_insert_slot_times_out(
    db_engine,
    monkeypatch,
    tmp_path: Path,
):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    editorial_timeline_id = uuid.uuid4()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake-audio")
    keep_segments = [{"type": "keep", "start_time": 0.0, "end_time": 12.0}]
    polish_modes: list[bool] = []
    insert_modes: list[bool] = []
    saved_render_plan: dict[str, object] = {}

    class FakeDecision:
        def to_dict(self):
            return {"segments": keep_segments}

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                channel_profile="unboxing_standard",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="edit_plan", status="running"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="media_meta",
                data_json={"duration": 12.0},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="audio_wav",
                storage_path="jobs/demo/audio.wav",
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "workflow_template": "unboxing_standard",
                    "subject_domain": "edc",
                    "subject_type": "EDC手电",
                    "subject_brand": "傲雷",
                    "subject_model": "司令官2 Ultra",
                },
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=12.0,
                text_raw="这次拿到1个新的手电筒。",
                text_norm="这次拿到1个新的手电筒。",
                text_final="这次拿到1个新的手电筒。",
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(steps_mod, "_EDIT_PLAN_SUBTITLE_POLISH_TIMEOUT_SEC", 0.01)
    monkeypatch.setattr(steps_mod, "_EDIT_PLAN_INSERT_SLOT_TIMEOUT_SEC", 0.01)

    async def fake_resolve_storage_reference(*args, **kwargs):
        return audio_path

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_load_recent_subtitle_examples(*args, **kwargs):
        return []

    async def fake_load_related_profile_subtitle_examples(*args, **kwargs):
        return []

    def fake_build_subtitle_review_memory(**kwargs):
        return {"mode": "formal_polish"}

    async def fake_polish_subtitle_items(subtitle_items, **kwargs):
        allow_llm = bool(kwargs["allow_llm"])
        polish_modes.append(allow_llm)
        if allow_llm:
            await asyncio.sleep(0.05)
        subtitle_items[0].text_final = "这次拿到一个新的手电筒。"
        return 1

    async def fake_save_editorial_timeline(*args, **kwargs):
        return SimpleNamespace(id=editorial_timeline_id, data_json={"segments": keep_segments}, otio_data=None)

    async def fake_plan_insert_asset_slot(**kwargs):
        allow_llm = bool(kwargs.get("allow_llm", True))
        insert_modes.append(allow_llm)
        if allow_llm:
            await asyncio.sleep(0.05)
        plan = dict(kwargs["insert_plan"] or {})
        plan["insert_after_sec"] = 9.0
        plan["reason"] = "fallback"
        return plan

    async def fake_plan_music_entry(**kwargs):
        return kwargs["music_plan"]

    async def fake_save_render_plan(*args, **kwargs):
        saved_render_plan.update(args[1] if len(args) > 1 else kwargs.get("render_plan_dict") or {})
        return None

    monkeypatch.setattr(steps_mod, "_resolve_storage_reference", fake_resolve_storage_reference)
    monkeypatch.setattr(steps_mod, "detect_silence", lambda *args, **kwargs: [])
    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_load_recent_subtitle_examples", fake_load_recent_subtitle_examples)
    monkeypatch.setattr(steps_mod, "_load_related_profile_subtitle_examples", fake_load_related_profile_subtitle_examples)
    monkeypatch.setattr(steps_mod, "build_subtitle_review_memory", fake_build_subtitle_review_memory)
    monkeypatch.setattr(steps_mod, "polish_subtitle_items", fake_polish_subtitle_items)
    monkeypatch.setattr(steps_mod, "build_edit_decision", lambda **kwargs: FakeDecision())
    monkeypatch.setattr(steps_mod, "save_editorial_timeline", fake_save_editorial_timeline)
    monkeypatch.setattr(steps_mod, "export_to_otio", lambda *args, **kwargs: "otio")
    monkeypatch.setattr(
        steps_mod,
        "resolve_packaging_plan_for_job",
        lambda *args, **kwargs: {
            "subtitle_style": "bold_yellow_outline",
            "subtitle_motion_style": "motion_static",
            "smart_effect_style": "smart_effect_rhythm",
            "insert": {"path": "insert.mp4"},
        },
    )
    monkeypatch.setattr(steps_mod, "remap_subtitles_to_timeline", lambda subtitles, segments: subtitles)
    monkeypatch.setattr(steps_mod, "_plan_insert_asset_slot", fake_plan_insert_asset_slot)
    monkeypatch.setattr(steps_mod, "_plan_music_entry", fake_plan_music_entry)
    monkeypatch.setattr(steps_mod, "build_render_plan", lambda **kwargs: kwargs)
    monkeypatch.setattr(steps_mod, "build_smart_editing_accents", lambda **kwargs: {})
    monkeypatch.setattr(steps_mod, "save_render_plan", fake_save_render_plan)

    result = await steps_mod.run_edit_plan(str(job_id))

    assert result["timeline_id"] == str(editorial_timeline_id)
    assert polish_modes == [True, False]
    assert insert_modes == [True, False]
    assert saved_render_plan["insert"]["insert_after_sec"] == 9.0

    async with factory() as session:
        subtitle = (
            await session.execute(
                select(SubtitleItem).where(SubtitleItem.job_id == job_id, SubtitleItem.item_index == 0)
            )
        ).scalar_one()
        assert subtitle.text_final == "这次拿到一个新的手电筒。"


@pytest.mark.asyncio
async def test_run_edit_plan_applies_review_rerun_focus_to_editing_skill(
    db_engine,
    monkeypatch,
    tmp_path: Path,
):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    editorial_timeline_id = uuid.uuid4()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake-audio")
    captured: dict[str, object] = {}

    class FakeDecision:
        analysis = {}

        def to_dict(self):
            return {"segments": [{"type": "keep", "start": 0.0, "end": 2.0}]}

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
                workflow_template="unboxing_standard",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="edit_plan",
                status="running",
                metadata_={"review_rerun_focus": "hook_boundary"},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="media_meta",
                data_json={"duration": 12.0},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="audio_wav",
                storage_path="jobs/demo/audio.wav",
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={"workflow_template": "unboxing_standard"},
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=2.0,
                text_raw="先说结论这把很稳。",
                text_norm="先说结论这把很稳。",
                text_final="先说结论这把很稳。",
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    async def fake_resolve_storage_reference(*args, **kwargs):
        return audio_path

    async def fake_load_content_profile_user_memory(*args, **kwargs):
        return {}

    async def fake_load_recent_subtitle_examples(*args, **kwargs):
        return []

    async def fake_load_related_profile_subtitle_examples(*args, **kwargs):
        return []

    async def fake_polish_subtitle_items(*args, **kwargs):
        return 0

    def fake_build_edit_decision(**kwargs):
        captured["decision_skill"] = kwargs["editing_skill"]
        return FakeDecision()

    def fake_infer_timeline_analysis(*args, **kwargs):
        captured["timeline_skill"] = kwargs["editing_skill"]
        return {
            "hook_end_sec": 2.0,
            "cta_start_sec": None,
            "semantic_sections": [],
            "section_directives": [],
            "section_actions": [],
            "editing_skill": kwargs["editing_skill"],
            "emphasis_candidates": [],
        }

    async def fake_save_editorial_timeline(*args, **kwargs):
        return SimpleNamespace(id=editorial_timeline_id, data_json={"segments": []}, otio_data=None)

    async def fake_plan_insert_asset_slot(**kwargs):
        return None

    async def fake_plan_music_entry(**kwargs):
        return None

    async def fake_save_render_plan(*args, **kwargs):
        return None

    monkeypatch.setattr(steps_mod, "_resolve_storage_reference", fake_resolve_storage_reference)
    monkeypatch.setattr(steps_mod, "detect_silence", lambda *args, **kwargs: [])
    monkeypatch.setattr(steps_mod, "load_content_profile_user_memory", fake_load_content_profile_user_memory)
    monkeypatch.setattr(steps_mod, "_load_recent_subtitle_examples", fake_load_recent_subtitle_examples)
    monkeypatch.setattr(steps_mod, "_load_related_profile_subtitle_examples", fake_load_related_profile_subtitle_examples)
    monkeypatch.setattr(steps_mod, "build_subtitle_review_memory", lambda **kwargs: {})
    monkeypatch.setattr(steps_mod, "polish_subtitle_items", fake_polish_subtitle_items)
    monkeypatch.setattr(steps_mod, "build_edit_decision", fake_build_edit_decision)
    monkeypatch.setattr(steps_mod, "infer_timeline_analysis", fake_infer_timeline_analysis)
    monkeypatch.setattr(steps_mod, "save_editorial_timeline", fake_save_editorial_timeline)
    monkeypatch.setattr(steps_mod, "export_to_otio", lambda *args, **kwargs: "otio")
    monkeypatch.setattr(
        steps_mod,
        "resolve_packaging_plan_for_job",
        lambda *args, **kwargs: {
            "subtitle_style": "bold_yellow_outline",
            "subtitle_motion_style": "motion_static",
            "smart_effect_style": "smart_effect_rhythm",
        },
    )
    monkeypatch.setattr(steps_mod, "remap_subtitles_to_timeline", lambda subtitles, segments: subtitles)
    monkeypatch.setattr(steps_mod, "_plan_insert_asset_slot", fake_plan_insert_asset_slot)
    monkeypatch.setattr(steps_mod, "_plan_music_entry", fake_plan_music_entry)
    monkeypatch.setattr(steps_mod, "build_render_plan", lambda **kwargs: {"ok": True})
    monkeypatch.setattr(steps_mod, "build_smart_editing_accents", lambda **kwargs: {})
    monkeypatch.setattr(steps_mod, "save_render_plan", fake_save_render_plan)

    result = await steps_mod.run_edit_plan(str(job_id))

    assert result["timeline_id"] == str(editorial_timeline_id)
    decision_skill = dict(captured["decision_skill"] or {})
    timeline_skill = dict(captured["timeline_skill"] or {})
    assert decision_skill["review_focus"] == "hook_boundary"
    assert decision_skill["silence_floor_sec"] > 0.5
    assert decision_skill["section_policy"]["hook"]["trim_intensity"] == "preserve"
    assert timeline_skill["review_focus"] == "hook_boundary"


@pytest.mark.asyncio
async def test_run_platform_package_reuses_cached_fact_sheet_and_packaging(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.llm_cache as llm_cache_mod
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    output_path = tmp_path / "rendered.mp4"
    output_path.write_bytes(b"rendered")
    settings = SimpleNamespace(
        output_dir=str(tmp_path / "output"),
        step_heartbeat_interval_sec=20,
    )
    call_counts = {"fact_sheet": 0, "packaging": 0}

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                file_hash="hash-demo",
                status="processing",
                language="zh-CN",
                channel_profile="edc_tactical",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="platform_package", status="running"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_brand": "Loop露普",
                    "subject_model": "SK05二代Pro UV版",
                    "subject_type": "EDC手电",
                    "video_theme": "上手开箱",
                    "search_queries": ["Loop露普 SK05 UV"],
                    "evidence": [
                        {"title": "Spec 1", "url": "https://example.com/spec1", "snippet": "4360流明"},
                        {"title": "Spec 2", "url": "https://example.com/spec2", "snippet": "405米"},
                    ],
                },
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="这次重点看紫外和主灯。",
                text_norm="这次重点看紫外和主灯。",
                text_final="这次重点看紫外和主灯。",
            )
        )
        session.add(
            RenderOutput(
                job_id=job_id,
                status="done",
                output_path=str(output_path),
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(steps_mod, "list_packaging_assets", lambda: {"config": {"copy_style": "attention_grabbing"}})
    monkeypatch.setattr(steps_mod, "_select_default_avatar_profile", lambda: {"display_name": "作者A"})
    monkeypatch.setattr(llm_cache_mod, "get_settings", lambda: settings)

    async def fake_build_packaging_fact_sheet(**kwargs):
        call_counts["fact_sheet"] += 1
        return {
            "status": "verified",
            "verified_facts": [{"fact": "总光通量 4360 lm", "source_url": "https://example.com/spec1", "source_title": "Spec 1"}],
            "official_sources": [{"title": "Spec 1", "url": "https://example.com/spec1"}],
            "guardrail_summary": "",
        }

    async def fake_generate_platform_packaging(**kwargs):
        call_counts["packaging"] += 1
        return {
            "highlights": {
                "product": "Loop露普 SK05二代Pro UV版",
                "video_type": "开箱体验",
                "strongest_selling_point": "主灯和紫外双线都能看",
                "strongest_emotion": "终于到手",
                "title_hook": "这次升级到底值不值",
                "engagement_question": "你更看重 UV 还是主灯？",
            },
            "platforms": {
                "bilibili": {"titles": ["标题1", "标题2", "标题3", "标题4", "标题5"], "description": "简介", "tags": ["EDC"]},
                "xiaohongshu": {"titles": ["小红书1", "小红书2", "小红书3", "小红书4", "小红书5"], "description": "正文", "tags": ["手电"]},
                "douyin": {"titles": ["抖音1", "抖音2", "抖音3", "抖音4", "抖音5"], "description": "短简介", "tags": ["开箱"]},
                "kuaishou": {"titles": ["快手1", "快手2", "快手3", "快手4", "快手5"], "description": "快手简介", "tags": ["玩家"]},
                "wechat_channels": {"titles": ["视频号1", "视频号2", "视频号3", "视频号4", "视频号5"], "description": "视频号简介", "tags": ["分享"]},
            },
            "fact_sheet": kwargs["fact_sheet"],
        }

    monkeypatch.setattr(steps_mod, "build_packaging_fact_sheet", fake_build_packaging_fact_sheet)
    monkeypatch.setattr(steps_mod, "generate_platform_packaging", fake_generate_platform_packaging)

    await run_platform_package(str(job_id))
    await run_platform_package(str(job_id))

    assert call_counts == {"fact_sheet": 1, "packaging": 1}

    async with factory() as session:
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "platform_package")
        )
        step = step_result.scalar_one()
        assert step.metadata_["cache"]["platform_fact_sheet"]["hit"] is True
        assert step.metadata_["cache"]["platform_packaging"]["hit"] is True


@pytest.mark.asyncio
async def test_run_platform_package_passes_resolved_review_feedback_into_packaging_context(
    db_engine,
    monkeypatch,
    tmp_path: Path,
):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    output_path = tmp_path / "rendered.mp4"
    output_path.write_bytes(b"rendered")
    settings = SimpleNamespace(
        output_dir=str(tmp_path / "output"),
        step_heartbeat_interval_sec=20,
    )
    captured: dict[str, Any] = {}

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                file_hash="hash-demo",
                status="processing",
                language="zh-CN",
                channel_profile="edc_tactical",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="platform_package", status="running"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_brand": "耐克",
                    "subject_model": "SK05",
                    "subject_type": "手电筒",
                    "video_theme": "旧主题",
                    "hook_line": "旧钩子",
                    "review_mode": "manual_confirmed",
                    "resolved_review_user_feedback": {
                        "subject_brand": "傲雷",
                        "subject_model": "司令官2Ultra",
                        "subject_type": "SLIM2代ULTRA版手电筒",
                        "video_theme": "傲雷司令官2Ultra版本选购与参数对比",
                        "hook_line": "司令官2Ultra到底值不值",
                        "search_queries": ["傲雷 司令官2Ultra", "傲雷 司令官2Ultra 手电"],
                    },
                },
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="这次重点看司令官2Ultra。",
                text_norm="这次重点看司令官2Ultra。",
                text_final="这次重点看司令官2Ultra。",
            )
        )
        session.add(
            RenderOutput(
                job_id=job_id,
                status="done",
                output_path=str(output_path),
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(steps_mod, "list_packaging_assets", lambda: {"config": {"copy_style": "attention_grabbing"}})
    monkeypatch.setattr(steps_mod, "_select_default_avatar_profile", lambda: {"display_name": "作者A"})
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)

    async def fake_build_packaging_fact_sheet(**kwargs):
        captured["fact_sheet_content_profile"] = dict(kwargs["content_profile"])
        return {
            "status": "verified",
            "verified_facts": [{"fact": "司令官2Ultra 为手电产品线", "source_url": "https://example.com/spec1", "source_title": "Spec 1"}],
            "official_sources": [{"title": "Spec 1", "url": "https://example.com/spec1"}],
            "guardrail_summary": "",
        }

    async def fake_generate_platform_packaging(**kwargs):
        captured["generate_content_profile"] = dict(kwargs["content_profile"])
        captured["prompt_brief"] = dict(kwargs["prompt_brief"])
        return {
            "highlights": {
                "product": "傲雷 司令官2Ultra",
                "video_type": "开箱体验",
                "strongest_selling_point": "版本差异一眼看清",
                "strongest_emotion": "这次终于对上型号了",
                "title_hook": "司令官2Ultra到底值不值",
                "engagement_question": "你更想看哪一版？",
            },
            "platforms": {
                "bilibili": {"titles": ["标题1", "标题2", "标题3", "标题4", "标题5"], "description": "简介", "tags": ["手电"]},
                "xiaohongshu": {"titles": ["小红书1", "小红书2", "小红书3", "小红书4", "小红书5"], "description": "正文", "tags": ["手电"]},
                "douyin": {"titles": ["抖音1", "抖音2", "抖音3", "抖音4", "抖音5"], "description": "短简介", "tags": ["手电"]},
                "kuaishou": {"titles": ["快手1", "快手2", "快手3", "快手4", "快手5"], "description": "快手简介", "tags": ["手电"]},
                "wechat_channels": {"titles": ["视频号1", "视频号2", "视频号3", "视频号4", "视频号5"], "description": "视频号简介", "tags": ["手电"]},
            },
            "fact_sheet": kwargs["fact_sheet"],
        }

    monkeypatch.setattr(steps_mod, "build_packaging_fact_sheet", fake_build_packaging_fact_sheet)
    monkeypatch.setattr(steps_mod, "generate_platform_packaging", fake_generate_platform_packaging)

    await run_platform_package(str(job_id))

    assert captured["fact_sheet_content_profile"]["resolved_review_user_feedback"]["subject_brand"] == "傲雷"
    assert captured["generate_content_profile"]["resolved_review_user_feedback"]["subject_model"] == "司令官2Ultra"
    assert captured["prompt_brief"]["manual_review_applied"] is True
    assert captured["prompt_brief"]["resolved_review_user_feedback"]["video_theme"] == "傲雷司令官2Ultra版本选购与参数对比"


@pytest.mark.asyncio
async def test_run_platform_package_prefers_downstream_context_profile(
    db_engine,
    monkeypatch,
    tmp_path: Path,
):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    output_path = tmp_path / "rendered.mp4"
    output_path.write_bytes(b"rendered")
    settings = SimpleNamespace(
        output_dir=str(tmp_path / "output"),
        step_heartbeat_interval_sec=20,
    )
    captured: dict[str, Any] = {}

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                file_hash="hash-demo",
                status="processing",
                language="zh-CN",
                channel_profile="edc_tactical",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="platform_package", status="running"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_brand": "耐克",
                    "subject_model": "SK05",
                    "subject_type": "手电筒",
                    "video_theme": "旧主题",
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="downstream_context",
                data_json={
                    "resolved_profile": {
                        "subject_brand": "傲雷",
                        "subject_model": "司令官2Ultra",
                        "subject_type": "手电筒",
                        "video_theme": "傲雷司令官2Ultra版本选购与参数对比",
                    },
                    "field_sources": {
                        "subject_brand": "manual_review",
                        "subject_model": "manual_review",
                    },
                    "manual_review_applied": True,
                    "research_applied": True,
                },
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=1.0,
                text_raw="这次重点看司令官2Ultra。",
                text_norm="这次重点看司令官2Ultra。",
                text_final="这次重点看司令官2Ultra。",
            )
        )
        session.add(
            RenderOutput(
                job_id=job_id,
                status="done",
                output_path=str(output_path),
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)
    monkeypatch.setattr(steps_mod, "list_packaging_assets", lambda: {"config": {"copy_style": "attention_grabbing"}})
    monkeypatch.setattr(steps_mod, "_select_default_avatar_profile", lambda: {"display_name": "作者A"})
    monkeypatch.setattr(steps_mod, "get_settings", lambda: settings)

    async def fake_build_packaging_fact_sheet(**kwargs):
        captured["fact_sheet_content_profile"] = dict(kwargs["content_profile"])
        return {
            "status": "verified",
            "verified_facts": [],
            "official_sources": [],
            "guardrail_summary": "",
        }

    async def fake_generate_platform_packaging(**kwargs):
        captured["generate_content_profile"] = dict(kwargs["content_profile"])
        return {
            "highlights": {
                "product": "傲雷 司令官2Ultra",
                "video_type": "开箱体验",
                "strongest_selling_point": "版本差异一眼看清",
                "strongest_emotion": "这次终于对上型号了",
                "title_hook": "司令官2Ultra到底值不值",
                "engagement_question": "你更想看哪一版？",
            },
            "platforms": {
                "bilibili": {"titles": ["标题1", "标题2", "标题3", "标题4", "标题5"], "description": "简介", "tags": ["手电"]},
                "xiaohongshu": {"titles": ["小红书1", "小红书2", "小红书3", "小红书4", "小红书5"], "description": "正文", "tags": ["手电"]},
                "douyin": {"titles": ["抖音1", "抖音2", "抖音3", "抖音4", "抖音5"], "description": "短简介", "tags": ["手电"]},
                "kuaishou": {"titles": ["快手1", "快手2", "快手3", "快手4", "快手5"], "description": "快手简介", "tags": ["手电"]},
                "wechat_channels": {"titles": ["视频号1", "视频号2", "视频号3", "视频号4", "视频号5"], "description": "视频号简介", "tags": ["手电"]},
            },
            "fact_sheet": kwargs["fact_sheet"],
        }

    monkeypatch.setattr(steps_mod, "build_packaging_fact_sheet", fake_build_packaging_fact_sheet)
    monkeypatch.setattr(steps_mod, "generate_platform_packaging", fake_generate_platform_packaging)

    await run_platform_package(str(job_id))

    assert captured["fact_sheet_content_profile"]["subject_brand"] == "傲雷"
    assert captured["generate_content_profile"]["subject_model"] == "司令官2Ultra"


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
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="downstream_context",
                data_json={
                    "resolved_profile": {
                        "subject_type": "校对后的科普讲解",
                        "summary": "综合调研后，主题应聚焦在版本差异与选购逻辑。",
                        "engagement_question": "你会怎么解释 Ultra 和 Pro 的差别？",
                    },
                    "field_sources": {
                        "summary": "research",
                    },
                    "manual_review_applied": True,
                    "research_applied": True,
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
    captured: dict[str, Any] = {}

    async def fake_build_ai_director_plan(**kwargs):
        captured["content_profile"] = dict(kwargs["content_profile"])
        return {
            "opening_hook": "这条内容最该先讲清楚的结论，我先替你拎出来。",
            "bridge_line": "这里应该补一层背景说明。",
            "voice_provider": "indextts2",
            "voiceover_segments": [{"segment_id": "director_hook", "rewritten_text": "新钩子"}],
            "dubbing_request": {"provider": "indextts2"},
        }

    monkeypatch.setattr(steps_mod, "build_ai_director_plan", fake_build_ai_director_plan)

    result = await run_ai_director(str(job_id))

    assert result["enabled"] is True
    assert result["voiceover_segment_count"] == 1
    assert captured["content_profile"]["subject_type"] == "校对后的科普讲解"
    assert captured["content_profile"]["summary"] == "综合调研后，主题应聚焦在版本差异与选购逻辑。"

    async with factory() as session:
        artifact = await _load_latest_optional_artifact(session, job_id=job_id, artifact_types=("ai_director_plan",))
        assert artifact is not None
        assert artifact.data_json["voice_provider"] == "indextts2"


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
                artifact_type="downstream_context",
                data_json={
                    "resolved_profile": {
                        "summary": "人工校对后，应把数字人解说聚焦在型号纠偏与选购建议。",
                        "engagement_question": "你最想让数字人补型号差异还是参数差异？",
                    },
                    "field_sources": {
                        "summary": "manual_review",
                    },
                    "manual_review_applied": True,
                    "research_applied": True,
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
    captured: dict[str, Any] = {}

    def fake_build_avatar_commentary_plan(**kwargs):
        captured["content_profile"] = dict(kwargs["content_profile"])
        return {
            "provider": "heygem",
            "layout_template": "picture_in_picture_right",
            "segments": [{"segment_id": "avatar_1", "script": "我先替你抓重点。"}],
            "render_request": {"provider": "heygem"},
        }

    monkeypatch.setattr(steps_mod, "build_avatar_commentary_plan", fake_build_avatar_commentary_plan)

    result = await run_avatar_commentary(str(job_id))

    assert result["enabled"] is True
    assert result["segment_count"] == 1
    assert captured["content_profile"]["summary"] == "人工校对后，应把数字人解说聚焦在型号纠偏与选购建议。"
    assert captured["content_profile"]["engagement_question"] == "你最想让数字人补型号差异还是参数差异？"

    async with factory() as session:
        artifact = await _load_latest_optional_artifact(session, job_id=job_id, artifact_types=("avatar_commentary_plan",))
        assert artifact is not None
        assert artifact.data_json["layout_template"] == "picture_in_picture_right"


@pytest.mark.asyncio
async def test_run_avatar_commentary_segmented_passthrough_renders_only_once(db_engine, monkeypatch, tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    job_id = uuid.uuid4()
    audio_source = tmp_path / "source.wav"
    audio_source.write_bytes(b"wav")
    provider_calls: list[dict] = []

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/avatar.mp4",
                source_name="avatar.mp4",
                status="processing",
                language="zh-CN",
                enhancement_modes=["avatar_commentary"],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="avatar_commentary", status="running"))
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="audio_wav",
                storage_path="jobs/demo/source.wav",
                data_json={},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={"summary": "数字人解说测试"},
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=2.0,
                text_raw="测试字幕",
                text_norm="测试字幕",
                text_final="测试字幕",
            )
        )
        await session.commit()

    monkeypatch.setattr(steps_mod, "get_session_factory", lambda: factory)

    def fake_build_avatar_commentary_plan(**kwargs):
        return {
            "provider": "heygem",
            "mode": "segmented_audio_passthrough",
            "layout_template": "picture_in_picture_right",
            "segments": [
                {
                    "segment_id": "avatar_seg_001",
                    "script": "测试字幕",
                    "start_time": 0.0,
                    "end_time": 2.0,
                    "duration_sec": 2.0,
                    "purpose": "commentary",
                }
            ],
            "render_request": {"provider": "heygem"},
        }

    class FakeStorage:
        async def async_download_file(self, storage_path, local_path):
            Path(local_path).write_bytes(audio_source.read_bytes())

    async def fake_extract_audio_clip(source_audio_path, clip_path, start_time, end_time):
        Path(clip_path).write_bytes(b"clip")

    def fake_select_default_avatar_profile():
        return {"id": "profile-1", "display_name": "测试数字人"}

    def fake_pick_avatar_profile_speaking_video_path(profile):
        presenter_path = tmp_path / "presenter.mp4"
        presenter_path.write_bytes(b"video")
        return presenter_path

    class FakeAvatarProvider:
        def execute_render(self, *, job_id, request):
            provider_calls.append(request)
            return {
                "provider": "heygem",
                "status": "success",
                "segments": [
                    {
                        "segment_id": "avatar_seg_001",
                        "status": "success",
                        "result": "/avatar_seg_001.mp4",
                        "local_result_path": str(tmp_path / "avatar_seg_001.mp4"),
                    }
                ],
            }

    monkeypatch.setattr(steps_mod, "build_avatar_commentary_plan", fake_build_avatar_commentary_plan)
    monkeypatch.setattr(steps_mod, "get_storage", lambda: FakeStorage())
    monkeypatch.setattr(steps_mod, "extract_audio_clip", fake_extract_audio_clip)
    monkeypatch.setattr(steps_mod, "_select_default_avatar_profile", fake_select_default_avatar_profile)
    monkeypatch.setattr(steps_mod, "_pick_avatar_profile_speaking_video_path", fake_pick_avatar_profile_speaking_video_path)
    monkeypatch.setattr(steps_mod, "get_avatar_provider", lambda: FakeAvatarProvider())

    result = await run_avatar_commentary(str(job_id))

    assert result["render_status"] == "success"
    assert len(provider_calls) == 1
    assert provider_calls[0]["segments"][0]["audio_url"].endswith("avatar_seg_001.wav")

    async with factory() as session:
        artifact = await _load_latest_optional_artifact(session, job_id=job_id, artifact_types=("avatar_commentary_plan",))
        assert artifact is not None
        assert artifact.data_json["render_execution"]["status"] == "success"
        assert artifact.data_json["segments"][0]["video_status"] == "success"
        assert artifact.data_json["segments"][0]["video_local_path"].endswith("avatar_seg_001.mp4")


@pytest.mark.asyncio
async def test_overlay_avatar_picture_in_picture_keeps_video_visible_without_corner_mask(tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    base_video = tmp_path / "base.mp4"
    avatar_video = tmp_path / "avatar.mp4"
    output_video = tmp_path / "output.mp4"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=360x640:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(base_video),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=120x160:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(avatar_video),
        ],
        check=True,
        capture_output=True,
    )

    await steps_mod._overlay_avatar_picture_in_picture(
        base_video_path=base_video,
        avatar_video_path=avatar_video,
        output_path=output_video,
        position="bottom_right",
        scale=0.28,
        margin=20,
        corner_radius=26,
        border_width=4,
        border_color="#F4E4B8",
    )

    frame_path = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(output_video), "-frames:v", "1", str(frame_path)],
        check=True,
        capture_output=True,
    )

    probe = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(frame_path),
            "-vf",
            "crop=100:140:240:460,format=rgb24",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=False,
    )

    assert output_video.exists()
    assert probe.returncode == 0
    assert any(channel > 0 for channel in probe.stdout)


def _read_png_pixel(path: Path, x: int, y: int) -> tuple[int, int, int]:
    probe = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"crop=1:1:{x}:{y},format=rgb24",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
        check=True,
    )
    pixel = probe.stdout[:3]
    assert len(pixel) == 3
    return pixel[0], pixel[1], pixel[2]


@pytest.mark.asyncio
async def test_overlay_avatar_picture_in_picture_applies_rounded_corners_and_border(tmp_path: Path):
    import roughcut.pipeline.steps as steps_mod

    base_video = tmp_path / "base.mp4"
    avatar_video = tmp_path / "avatar.mp4"
    output_video = tmp_path / "output.mp4"

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=360x640:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(base_video),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=120x160:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(avatar_video),
        ],
        check=True,
        capture_output=True,
    )

    await steps_mod._overlay_avatar_picture_in_picture(
        base_video_path=base_video,
        avatar_video_path=avatar_video,
        output_path=output_video,
        position="bottom_right",
        scale=0.28,
        margin=20,
        corner_radius=26,
        border_width=4,
        border_color="#F4E4B8",
    )

    frame_path = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(output_video), "-frames:v", "1", str(frame_path)],
        check=True,
        capture_output=True,
    )

    masked_corner_pixel = _read_png_pixel(frame_path, 145, 365)
    border_pixel = _read_png_pixel(frame_path, 158, 378)
    avatar_pixel = _read_png_pixel(frame_path, 170, 390)

    assert masked_corner_pixel == (0, 0, 0)
    assert border_pixel != (0, 0, 0)
    assert avatar_pixel[0] > 150 and avatar_pixel[1] < 80 and avatar_pixel[2] < 80


def test_build_avatar_picture_in_picture_filters_retunes_duration_and_fps():
    import roughcut.pipeline.steps as steps_mod

    filters = steps_mod._build_avatar_picture_in_picture_filters(
        base_duration=700.59,
        base_fps=29.97,
        avatar_duration=699.403,
        avatar_fps=25.0,
        overlay_width=320,
        overlay_height=320,
    )

    assert filters.startswith("scale=320:320")
    assert "setpts=PTS*" in filters
    assert "trim=duration=700.590000" in filters
    assert "settb=AVTB,framerate=fps=30000/1001:interp_start=15:interp_end=240:scene=100" in filters


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


def test_select_cover_source_video_requires_plain_render(tmp_path: Path):
    plain = tmp_path / "output_plain.mp4"
    packaged = tmp_path / "output.mp4"
    packaged.write_bytes(b"packaged")

    with pytest.raises(FileNotFoundError, match="Plain render is required for cover extraction"):
        _select_cover_source_video(plain, packaged)


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


def test_select_preferred_content_profile_artifact_prefers_latest_draft_over_older_working_copy():
    base_time = datetime(2026, 3, 12, 15, 0, tzinfo=timezone.utc)
    working_copy = Artifact(
        artifact_type="content_profile",
        created_at=base_time,
        data_json={"kind": "content"},
    )
    draft = Artifact(
        artifact_type="content_profile_draft",
        created_at=base_time + timedelta(seconds=5),
        data_json={"kind": "draft"},
    )

    selected = _select_preferred_content_profile_artifact([working_copy, draft])

    assert selected is draft
