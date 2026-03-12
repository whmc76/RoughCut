"""
Business logic for each pipeline step.
Each function takes job_id + step info and does the actual work.
These are called by Celery tasks (which handle the async→sync bridge).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from roughcut.config import get_settings
from roughcut.db.models import Artifact, GlossaryTerm, Job, JobStep, RenderOutput, SubtitleItem, Timeline, TranscriptSegment
from roughcut.db.session import get_session_factory
from roughcut.edit.decisions import build_edit_decision
from roughcut.edit.otio_export import export_to_otio
from roughcut.edit.render_plan import (
    build_plain_render_plan,
    build_render_plan,
    build_restrained_editing_accents,
    save_render_plan,
)
from roughcut.edit.timeline import save_editorial_timeline
from roughcut.media.audio import extract_audio
from roughcut.media.output import build_output_name, extract_cover_frame, get_output_project_dir, write_srt_file
from roughcut.media.subtitles import remap_subtitles_to_timeline
from roughcut.media.probe import probe, validate_media
from roughcut.media.render import render_video
from roughcut.media.silence import detect_silence
from roughcut.packaging.library import resolve_packaging_plan_for_job
from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message
from roughcut.review.content_profile import enrich_content_profile, infer_content_profile, polish_subtitle_items
from roughcut.review.content_profile_memory import load_content_profile_user_memory
from roughcut.review.glossary_engine import apply_glossary_corrections
from roughcut.review.platform_copy import generate_platform_packaging, save_platform_packaging_markdown
from roughcut.review.subtitle_memory import build_subtitle_review_memory, build_transcription_prompt
from roughcut.speech.postprocess import save_subtitle_items, split_into_subtitles
from roughcut.speech.transcribe import transcribe_audio
from roughcut.storage.s3 import get_storage, job_key


STEP_LABELS = {
    "probe": "探测媒体信息",
    "extract_audio": "提取音频",
    "transcribe": "语音转写",
    "subtitle_postprocess": "字幕后处理",
    "content_profile": "内容摘要",
    "summary_review": "人工确认",
    "glossary_review": "术语纠错",
    "edit_plan": "剪辑决策",
    "render": "渲染输出",
    "platform_package": "平台文案",
}

logger = logging.getLogger(__name__)


async def _set_step_progress(
    session,
    step: JobStep | None,
    *,
    detail: str,
    progress: float | None = None,
) -> None:
    if step is None:
        return
    metadata = dict(step.metadata_ or {})
    metadata["detail"] = detail
    metadata["label"] = STEP_LABELS.get(step.step_name, step.step_name)
    now = datetime.now(timezone.utc)
    metadata["updated_at"] = now.isoformat()
    if progress is not None:
        metadata["progress"] = max(0.0, min(1.0, progress))
    elapsed_seconds = _compute_step_elapsed_seconds(step, now=now)
    if elapsed_seconds is not None:
        metadata["elapsed_seconds"] = round(elapsed_seconds, 3)
    step.metadata_ = metadata
    await session.commit()


def _compute_step_elapsed_seconds(step: JobStep | None, *, now: datetime | None = None) -> float | None:
    if step is None or step.started_at is None:
        return None
    end_time = step.finished_at or now or datetime.now(timezone.utc)
    return max(0.0, (end_time - step.started_at).total_seconds())


async def _resolve_source(
    job,
    tmpdir: str,
    *,
    expected_hash: str | None = None,
    debug_dir: Path | None = None,
) -> Path:
    """
    Return a local Path for the job's source file.
    If source_path is already a local file, return it directly.
    Otherwise download from S3 to tmpdir.
    """
    source_path = Path(job.source_path)
    if source_path.exists():
        _record_source_integrity(
            source_path,
            source_ref=job.source_path,
            expected_hash=expected_hash,
            debug_dir=debug_dir,
            downloaded=False,
        )
        return source_path
    # It's an S3 key — download to tmpdir
    local = Path(tmpdir) / job.source_name
    storage = get_storage()
    await storage.async_download_file(job.source_path, local)
    _record_source_integrity(
        local,
        source_ref=job.source_path,
        expected_hash=expected_hash,
        debug_dir=debug_dir,
        downloaded=True,
    )
    return local


async def _get_job_and_step(job_id: str, step_name: str):
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        if not job:
            raise ValueError(f"Job {job_id} not found")
        result = await session.execute(
            select(JobStep)
            .where(JobStep.job_id == job.id, JobStep.step_name == step_name)
        )
        step = result.scalar_one_or_none()
        if not step:
            raise ValueError(f"Step {step_name} not found for job {job_id}")
    return job, step


async def _load_latest_artifact(session, job_id: uuid.UUID, artifact_type: str) -> Artifact:
    result = await session.execute(
        select(Artifact)
        .where(Artifact.job_id == job_id, Artifact.artifact_type == artifact_type)
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    artifact = result.scalars().first()
    if artifact is None:
        raise ValueError(f"Artifact not found: {artifact_type}")
    return artifact


async def _load_latest_timeline(session, job_id: uuid.UUID, timeline_type: str) -> Timeline:
    result = await session.execute(
        select(Timeline)
        .where(Timeline.job_id == job_id, Timeline.timeline_type == timeline_type)
        .order_by(Timeline.version.desc(), Timeline.created_at.desc(), Timeline.id.desc())
    )
    timeline = result.scalars().first()
    if timeline is None:
        raise ValueError(f"Timeline not found: {timeline_type}")
    return timeline


def _serialize_glossary_terms(terms: list[GlossaryTerm]) -> list[dict[str, str | list[str] | None]]:
    return [
        {
            "wrong_forms": term.wrong_forms,
            "correct_form": term.correct_form,
            "category": term.category,
            "context_hint": term.context_hint,
        }
        for term in terms
    ]


async def _load_recent_subtitle_examples(
    session,
    *,
    channel_profile: str | None,
    exclude_job_id: uuid.UUID,
    limit: int = 160,
) -> list[dict[str, str]]:
    stmt = (
        select(SubtitleItem, Job.source_name)
        .join(Job, SubtitleItem.job_id == Job.id)
        .where(SubtitleItem.version == 1, SubtitleItem.job_id != exclude_job_id)
        .order_by(SubtitleItem.created_at.desc())
        .limit(limit)
    )
    if channel_profile:
        stmt = stmt.where(Job.channel_profile == channel_profile)

    result = await session.execute(stmt)
    return [
        {
            "text_raw": subtitle_item.text_raw or "",
            "text_norm": subtitle_item.text_norm or "",
            "text_final": subtitle_item.text_final or "",
            "source_name": source_name or "",
        }
        for subtitle_item, source_name in result.all()
    ]


async def _load_related_profile_subtitle_examples(
    session,
    *,
    content_profile: dict | None,
    exclude_job_id: uuid.UUID,
    limit: int = 160,
) -> list[dict[str, str]]:
    if not content_profile:
        return []

    artifact_result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id != exclude_job_id,
            Artifact.artifact_type.in_(["content_profile_final", "content_profile", "content_profile_draft"]),
        )
        .order_by(Artifact.created_at.desc())
        .limit(120)
    )
    ranked_job_ids: list[uuid.UUID] = []
    seen_jobs: set[uuid.UUID] = set()
    for artifact in artifact_result.scalars().all():
        if artifact.job_id in seen_jobs:
            continue
        if _content_profile_similarity_score(content_profile, artifact.data_json or {}) <= 0:
            continue
        seen_jobs.add(artifact.job_id)
        ranked_job_ids.append(artifact.job_id)
        if len(ranked_job_ids) >= 10:
            break

    if not ranked_job_ids:
        return []

    subtitle_result = await session.execute(
        select(SubtitleItem, Job.source_name)
        .join(Job, SubtitleItem.job_id == Job.id)
        .where(SubtitleItem.version == 1, SubtitleItem.job_id.in_(ranked_job_ids))
        .order_by(SubtitleItem.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "text_raw": subtitle_item.text_raw or "",
            "text_norm": subtitle_item.text_norm or "",
            "text_final": subtitle_item.text_final or "",
            "source_name": source_name or "",
        }
        for subtitle_item, source_name in subtitle_result.all()
    ]


def _content_profile_similarity_score(current: dict, candidate: dict) -> int:
    score = 0
    for key, weight in (
        ("subject_brand", 4),
        ("subject_model", 5),
        ("subject_type", 3),
        ("video_theme", 2),
    ):
        left = _normalize_profile_value(current.get(key))
        right = _normalize_profile_value(candidate.get(key))
        if not left or not right:
            continue
        if left == right:
            score += weight
        elif left in right or right in left:
            score += max(1, weight - 1)
    return score


def _normalize_profile_value(value: object) -> str:
    return "".join(str(value or "").strip().upper().split())


async def run_probe(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "probe")
        )
        step = step_result.scalar_one()
        await _set_step_progress(session, step, detail="下载源视频并准备探测媒体参数", progress=0.1)

        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = await _resolve_source(job, tmpdir)
            await _set_step_progress(session, step, detail="读取分辨率、时长、编码与文件哈希", progress=0.45)
            meta = await probe(source_path)
            validate_media(meta)
            file_hash = _hash_file(source_path)

        job.file_hash = file_hash
        artifact = Artifact(
            job_id=job.id,
            step_id=step.id,
            artifact_type="media_meta",
            data_json={
                "duration": meta.duration,
                "width": meta.width,
                "height": meta.height,
                "fps": meta.fps,
                "video_codec": meta.video_codec,
                "audio_codec": meta.audio_codec,
                "audio_sample_rate": meta.audio_sample_rate,
                "audio_channels": meta.audio_channels,
                "file_size": meta.file_size,
                "format_name": meta.format_name,
                "bit_rate": meta.bit_rate,
                "file_hash": file_hash,
            },
        )
        session.add(artifact)
        await _set_step_progress(session, step, detail="已写入媒体信息", progress=1.0)
        await session.commit()

        return {"duration": meta.duration, "file_hash": file_hash}


async def run_extract_audio(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "extract_audio")
        )
        step = step_result.scalar_one()
        await _set_step_progress(session, step, detail="下载源视频", progress=0.1)

        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = await _resolve_source(job, tmpdir)
            audio_path = Path(tmpdir) / "audio.wav"
            await _set_step_progress(session, step, detail="提取音频轨道", progress=0.45)
            await extract_audio(source_path, audio_path)

            # Upload to S3
            storage = get_storage()
            key = job_key(job_id, "audio.wav")
            await _set_step_progress(session, step, detail="上传音频到对象存储", progress=0.8)
            await storage.async_upload_file(audio_path, key)

        artifact = Artifact(
            job_id=job.id,
            step_id=step.id,
            artifact_type="audio_wav",
            storage_path=key,
        )
        session.add(artifact)
        await _set_step_progress(session, step, detail="音频已就绪", progress=1.0)
        await session.commit()

        return {"audio_key": key}


async def run_transcribe(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "transcribe")
        )
        step = step_result.scalar_one()
        await _set_step_progress(session, step, detail="加载音频并准备转写", progress=0.1)

        # Get audio artifact key
        audio_artifact = await _load_latest_artifact(session, job.id, "audio_wav")

        storage = get_storage()
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "audio.wav"
            await storage.async_download_file(audio_artifact.storage_path, audio_path)
            await _set_step_progress(session, step, detail=f"加载 {job.language} 转写模型", progress=0.2)
            glossary_result = await session.execute(select(GlossaryTerm))
            glossary_terms = glossary_result.scalars().all()
            user_memory = await load_content_profile_user_memory(session, channel_profile=job.channel_profile)
            recent_subtitles = await _load_recent_subtitle_examples(
                session,
                channel_profile=job.channel_profile,
                exclude_job_id=job.id,
            )
            review_memory = build_subtitle_review_memory(
                channel_profile=job.channel_profile,
                glossary_terms=_serialize_glossary_terms(glossary_terms),
                user_memory=user_memory,
                recent_subtitles=recent_subtitles,
                include_recent_terms=False,
                include_recent_examples=False,
            )
            transcription_prompt = build_transcription_prompt(
                source_name=job.source_name,
                channel_profile=job.channel_profile,
                review_memory=review_memory,
            )

            progress_loop = asyncio.get_running_loop()
            last_progress = {"progress": 0.0, "ts": 0.0}
            accept_progress_updates = {"value": True}
            pending_progress_updates = []

            async def _persist_transcribe_progress(progress: float, detail: str) -> None:
                progress_factory = get_session_factory()
                async with progress_factory() as progress_session:
                    step_ref = await progress_session.get(JobStep, step.id)
                    if step_ref is None:
                        return
                    await _set_step_progress(progress_session, step_ref, detail=detail, progress=progress)

            def _on_transcribe_progress(payload: dict) -> None:
                if not accept_progress_updates["value"]:
                    return
                total_duration = float(payload.get("total_duration") or 0.0)
                segment_end = float(payload.get("segment_end") or 0.0)
                segment_count = int(payload.get("segment_count") or 0)
                raw_progress = float(payload.get("progress") or 0.0)
                scaled_progress = 0.25 + (raw_progress * 0.7)
                now = time.monotonic()
                if scaled_progress - last_progress["progress"] < 0.03 and now - last_progress["ts"] < 1.5:
                    return
                last_progress["progress"] = scaled_progress
                last_progress["ts"] = now
                detail = f"已转写 {segment_count} 段，覆盖 {segment_end:.0f}s / {total_duration:.0f}s"
                future = asyncio.run_coroutine_threadsafe(
                    _persist_transcribe_progress(scaled_progress, detail),
                    progress_loop,
                )
                pending_progress_updates.append(future)

            await _set_step_progress(session, step, detail=f"使用 {job.language} 模型执行转写", progress=0.25)
            result = await transcribe_audio(
                job.id,
                step,
                audio_path,
                job.language,
                session,
                prompt=transcription_prompt,
                progress_callback=_on_transcribe_progress,
            )
            accept_progress_updates["value"] = False
            if pending_progress_updates:
                await asyncio.gather(
                    *(asyncio.wrap_future(future) for future in pending_progress_updates),
                    return_exceptions=True,
                )

        await _set_step_progress(session, step, detail=f"转写完成，共 {len(result.segments)} 段", progress=1.0)
        await session.commit()
        return {"segment_count": len(result.segments), "duration": result.duration}


async def run_subtitle_postprocess(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "subtitle_postprocess")
        )
        step = step_result.scalar_one()
        started = time.perf_counter()
        await _set_step_progress(session, step, detail="加载转写结果并切分字幕", progress=0.25)

        # Load transcript segments
        seg_result = await session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.job_id == job.id, TranscriptSegment.version == 1)
            .order_by(TranscriptSegment.segment_index)
        )
        segments = seg_result.scalars().all()
        load_elapsed = time.perf_counter() - started

        split_started = time.perf_counter()
        entries = split_into_subtitles(segments)
        split_elapsed = time.perf_counter() - split_started
        await _set_step_progress(session, step, detail=f"生成字幕条目 {len(entries)} 条", progress=0.7)
        save_started = time.perf_counter()
        items = await save_subtitle_items(job.id, entries, session)
        glossary_result = await session.execute(select(GlossaryTerm))
        glossary_terms = glossary_result.scalars().all()
        user_memory = await load_content_profile_user_memory(session, channel_profile=job.channel_profile)
        recent_subtitles = await _load_recent_subtitle_examples(
            session,
            channel_profile=job.channel_profile,
            exclude_job_id=job.id,
        )
        review_memory = build_subtitle_review_memory(
            channel_profile=job.channel_profile,
            glossary_terms=_serialize_glossary_terms(glossary_terms),
            user_memory=user_memory,
            recent_subtitles=[
                {
                    "text_raw": item.text_raw,
                    "text_norm": item.text_norm,
                    "text_final": item.text_final,
                    "source_name": job.source_name,
                }
                for item in items
            ],
            include_recent_terms=False,
            include_recent_examples=False,
        )
        polished_count = await polish_subtitle_items(
            items,
            content_profile={"preset_name": job.channel_profile or "unboxing_default"},
            glossary_terms=_serialize_glossary_terms(glossary_terms),
            review_memory=review_memory,
            allow_llm=False,
        )
        save_elapsed = time.perf_counter() - save_started
        total_elapsed = time.perf_counter() - started
        await _set_step_progress(
            session,
            step,
            detail=f"字幕后处理完成，{len(segments)} 段 -> {len(items)} 条，纠正 {polished_count} 条，用时 {total_elapsed:.1f}s",
            progress=1.0,
        )
        await session.commit()
        logger.info(
            "subtitle_postprocess finished job=%s segments=%s subtitles=%s elapsed=%.2fs load=%.2fs split=%.2fs save=%.2fs",
            job_id,
            len(segments),
            len(items),
            total_elapsed,
            load_elapsed,
            split_elapsed,
            save_elapsed,
        )

        return {
            "segment_count": len(segments),
            "subtitle_count": len(items),
            "polished_count": polished_count,
            "elapsed_seconds": round(total_elapsed, 3),
            "load_seconds": round(load_elapsed, 3),
            "split_seconds": round(split_elapsed, 3),
            "save_seconds": round(save_elapsed, 3),
        }


async def run_content_profile(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "content_profile")
        )
        step = step_result.scalar_one()
        await _set_step_progress(session, step, detail="整理字幕上下文并识别视频类型", progress=0.15)

        item_result = await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
        subtitle_items = item_result.scalars().all()
        subtitle_dicts = [
            {
                "index": item.item_index,
                "start_time": item.start_time,
                "end_time": item.end_time,
                "text_raw": item.text_raw,
                "text_norm": item.text_norm,
                "text_final": item.text_final,
            }
            for item in subtitle_items
        ]
        user_memory = await load_content_profile_user_memory(session, channel_profile=job.channel_profile)

        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = await _resolve_source(job, tmpdir, expected_hash=job.file_hash)
            await _set_step_progress(session, step, detail="抽取画面并分析主题、主体与剪辑预设", progress=0.55)
            content_profile = await infer_content_profile(
                source_path=source_path,
                source_name=job.source_name,
                subtitle_items=subtitle_dicts,
                channel_profile=job.channel_profile,
                user_memory=user_memory,
                include_research=True,
            )

        artifact = Artifact(
            job_id=job.id,
            step_id=step.id,
            artifact_type="content_profile_draft",
            data_json=content_profile,
        )
        session.add(artifact)
        subject = " / ".join(
            part for part in [
                content_profile.get("subject_type"),
                content_profile.get("video_theme"),
            ] if part
        ).strip()
        await _set_step_progress(session, step, detail=f"已生成内容摘要：{subject or '待人工确认'}", progress=1.0)
        await session.commit()

        return {
            "subject_brand": content_profile.get("subject_brand"),
            "subject_model": content_profile.get("subject_model"),
            "subject_type": content_profile.get("subject_type"),
            "video_theme": content_profile.get("video_theme"),
        }


async def run_glossary_review(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "glossary_review")
        )
        step = step_result.scalar_one()
        await _set_step_progress(session, step, detail="应用术语词表并收集字幕上下文", progress=0.15)

        item_result = await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
        subtitle_items = item_result.scalars().all()

        corrections = await apply_glossary_corrections(job.id, subtitle_items, session)
        glossary_result = await session.execute(select(GlossaryTerm))
        glossary_terms = glossary_result.scalars().all()
        await _set_step_progress(session, step, detail=f"已识别 {len(corrections)} 处术语纠错候选", progress=0.45)

        subtitle_dicts = [
            {
                "index": item.item_index,
                "start_time": item.start_time,
                "end_time": item.end_time,
                "text_raw": item.text_raw,
                "text_norm": item.text_norm,
                "text_final": item.text_final,
            }
            for item in subtitle_items
        ]
        user_memory = await load_content_profile_user_memory(session, channel_profile=job.channel_profile)

        profile_result = await session.execute(
            select(Artifact)
            .where(
                Artifact.job_id == job.id,
                Artifact.artifact_type.in_(["content_profile_final", "content_profile_draft"]),
            )
            .order_by(Artifact.created_at.desc())
        )
        profile_artifacts = profile_result.scalars().all()
        content_profile = profile_artifacts[0].data_json if profile_artifacts else None
        if not content_profile:
            with tempfile.TemporaryDirectory() as tmpdir:
                source_path = await _resolve_source(job, tmpdir, expected_hash=job.file_hash)
                content_profile = await infer_content_profile(
                    source_path=source_path,
                    source_name=job.source_name,
                    subtitle_items=subtitle_dicts,
                    channel_profile=job.channel_profile,
                    user_memory=user_memory,
                )
        else:
            content_profile = await enrich_content_profile(
                profile=content_profile,
                source_name=job.source_name,
                channel_profile=job.channel_profile,
                transcript_excerpt=str(content_profile.get("transcript_excerpt") or ""),
                user_memory=user_memory,
                include_research=True,
            )
        recent_subtitles = await _load_recent_subtitle_examples(
            session,
            channel_profile=job.channel_profile,
            exclude_job_id=job.id,
        )
        related_subtitles = await _load_related_profile_subtitle_examples(
            session,
            content_profile=content_profile,
            exclude_job_id=job.id,
        )

        polished_count = await polish_subtitle_items(
            subtitle_items,
            content_profile=content_profile,
            glossary_terms=_serialize_glossary_terms(glossary_terms),
            review_memory=build_subtitle_review_memory(
                channel_profile=job.channel_profile,
                glossary_terms=_serialize_glossary_terms(glossary_terms),
                user_memory=user_memory,
                recent_subtitles=subtitle_dicts + related_subtitles + recent_subtitles,
                content_profile=content_profile,
                include_recent_terms=False,
                include_recent_examples=False,
            ),
        )

        artifact = Artifact(
            job_id=job.id,
            step_id=None,
            artifact_type="content_profile",
            data_json=content_profile,
        )
        session.add(artifact)
        await _set_step_progress(session, step, detail=f"字幕润色完成，更新 {polished_count} 条", progress=1.0)
        await session.commit()

        return {
            "correction_count": len(corrections),
            "polished_count": polished_count,
            "preset": content_profile.get("preset_name"),
            "subject": " ".join(
                part for part in [
                    content_profile.get("subject_brand"),
                    content_profile.get("subject_model"),
                ] if part
            ).strip(),
        }


async def run_edit_plan(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "edit_plan")
        )
        step = step_result.scalar_one()
        await _set_step_progress(session, step, detail="加载媒体参数、字幕与音频", progress=0.15)

        # Get media meta for duration
        meta_artifact = await _load_latest_artifact(session, job.id, "media_meta")
        duration = meta_artifact.data_json["duration"]

        # Get audio for silence detection
        audio_artifact = await _load_latest_artifact(session, job.id, "audio_wav")

        # Get subtitle items for filler detection
        item_result = await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
        subtitle_items = item_result.scalars().all()
        subtitle_dicts = [
            {
                "index": si.item_index,
                "start_time": si.start_time,
                "end_time": si.end_time,
                "text_raw": si.text_raw,
                "text_norm": si.text_norm,
                "text_final": si.text_final,
            }
            for si in subtitle_items
        ]

        profile_result = await session.execute(
            select(Artifact)
            .where(
                Artifact.job_id == job.id,
                Artifact.artifact_type.in_(["content_profile_final", "content_profile", "content_profile_draft"]),
            )
            .order_by(Artifact.created_at.desc())
        )
        profile_artifact = profile_result.scalars().first()
        content_profile = profile_artifact.data_json if profile_artifact else None

        storage = get_storage()
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "audio.wav"
            await storage.async_download_file(audio_artifact.storage_path, audio_path)
            await _set_step_progress(session, step, detail="检测静音和明显废话段", progress=0.5)
            silences = detect_silence(audio_path)

        decision = build_edit_decision(
            source_path=job.source_path,
            duration=duration,
            silence_segments=silences,
            subtitle_items=subtitle_dicts,
        )
        await _set_step_progress(session, step, detail="生成剪辑时间线与渲染计划", progress=0.85)

        editorial_timeline = await save_editorial_timeline(job.id, decision, session)

        # Export OTIO
        try:
            otio_str = export_to_otio(decision.to_dict())
            editorial_timeline.otio_data = otio_str
        except Exception:
            pass  # OTIO optional

        packaging_plan = resolve_packaging_plan_for_job(str(job.id))
        keep_segments = [segment for segment in decision.to_dict().get("segments", []) if segment.get("type") == "keep"]
        remapped_subtitles = remap_subtitles_to_timeline(subtitle_dicts, keep_segments)
        packaging_plan["insert"] = await _plan_insert_asset_slot(
            job_id=str(job.id),
            insert_plan=packaging_plan.get("insert"),
            subtitle_items=remapped_subtitles,
            content_profile=content_profile,
        )

        render_plan_dict = build_render_plan(
            editorial_timeline_id=editorial_timeline.id,
            workflow_preset=job.channel_profile or "unboxing_default",
            subtitle_style=str(packaging_plan.get("subtitle_style") or "bold_yellow_outline"),
            cover_style=(
                None
                if str(packaging_plan.get("cover_style") or "preset_default") == "preset_default"
                else str(packaging_plan.get("cover_style"))
            ),
            title_style=str(packaging_plan.get("title_style") or "preset_default"),
            intro=packaging_plan.get("intro"),
            outro=packaging_plan.get("outro"),
            insert=packaging_plan.get("insert"),
            watermark=packaging_plan.get("watermark"),
            music=packaging_plan.get("music"),
            editing_accents=build_restrained_editing_accents(
                keep_segments=keep_segments,
                subtitle_items=remapped_subtitles,
            ),
        )
        await save_render_plan(job.id, render_plan_dict, session)

        await _set_step_progress(session, step, detail="剪辑决策已生成", progress=1.0)
        await session.commit()
        return {"timeline_id": str(editorial_timeline.id)}


async def run_render(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        from roughcut.db.models import RenderOutput, Timeline

        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "render")
        )
        step = step_result.scalar_one()
        await _set_step_progress(session, step, detail="准备时间线、字幕和输出目录", progress=0.05)

        # Get timelines
        editorial_timeline = await _load_latest_timeline(session, job.id, "editorial")
        render_plan_timeline = await _load_latest_timeline(session, job.id, "render_plan")
        has_packaging = any(
            render_plan_timeline.data_json.get(key)
            for key in ("intro", "outro", "insert", "watermark", "music")
        )
        has_editing_accents = bool(
            (render_plan_timeline.data_json.get("editing_accents") or {}).get("transitions", {}).get("boundary_indexes")
            or (render_plan_timeline.data_json.get("editing_accents") or {}).get("emphasis_overlays")
            or (render_plan_timeline.data_json.get("editing_accents") or {}).get("sound_effects")
        )

        content_profile_result = await session.execute(
            select(Artifact)
            .where(Artifact.job_id == job.id, Artifact.artifact_type == "content_profile")
            .order_by(Artifact.created_at.desc())
        )
        content_profile_artifact = content_profile_result.scalars().first()
        content_profile = content_profile_artifact.data_json if content_profile_artifact else None

        # Get subtitle items
        item_result = await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
        subtitle_items = item_result.scalars().all()
        subtitle_dicts = [
            {
                "start_time": si.start_time,
                "end_time": si.end_time,
                "text_raw": si.text_raw,
                "text_norm": si.text_norm,
                "text_final": si.text_final,
            }
            for si in subtitle_items
        ]

        # Create render output record
        render_output = RenderOutput(
            job_id=job.id,
            timeline_id=editorial_timeline.id,
            status="running",
            progress=0.05,
        )
        session.add(render_output)
        await session.flush()
        render_output_id = render_output.id

        await session.commit()

    # Render (outside transaction — can be long)
    # Build canonical output name: YYYYMMDD_OriginalStem
    out_name = build_output_name(job.source_name, job.created_at)
    out_dir = get_output_project_dir(job.source_name, job.created_at)
    debug_dir = Path(get_settings().render_debug_dir) / f"{job_id}_{out_name}"
    debug_dir.mkdir(parents=True, exist_ok=True)
    local_packaged_mp4 = out_dir / f"{out_name}.mp4"
    local_plain_mp4 = out_dir / f"{out_name}_plain.mp4"
    local_packaged_srt = out_dir / f"{out_name}.srt"
    local_plain_srt = out_dir / f"{out_name}_plain.srt"
    local_cover = out_dir / f"{out_name}_cover.jpg"

    with tempfile.TemporaryDirectory() as tmpdir:
        async with get_session_factory()() as session:
            step_result = await session.execute(
                select(JobStep).where(JobStep.job_id == uuid.UUID(job_id), JobStep.step_name == "render")
            )
            render_step = step_result.scalar_one_or_none()
            if render_step:
                await _set_step_progress(
                    session,
                    render_step,
                    detail=(
                        "先渲染素版，再生成包装版"
                        if (has_packaging or has_editing_accents)
                        else "执行 FFmpeg 渲染成片"
                    ),
                    progress=0.35,
                )
        source_path = await _resolve_source(
            job,
            tmpdir,
            expected_hash=job.file_hash,
            debug_dir=debug_dir,
        )
        tmp_plain_mp4 = Path(tmpdir) / "output_plain.mp4"
        tmp_packaged_mp4 = Path(tmpdir) / "output_packaged.mp4"
        plain_render_plan = build_plain_render_plan(render_plan_timeline.data_json)
        await render_video(
            source_path=source_path,
            render_plan=plain_render_plan,
            editorial_timeline=editorial_timeline.data_json,
            output_path=tmp_plain_mp4,
            subtitle_items=subtitle_dicts,
            debug_dir=debug_dir / "plain",
        )
        async with get_session_factory()() as session:
            step_result = await session.execute(
                select(JobStep).where(JobStep.job_id == uuid.UUID(job_id), JobStep.step_name == "render")
            )
            render_step = step_result.scalar_one_or_none()
            render_output = await session.get(RenderOutput, render_output_id)
            if render_step:
                await _set_step_progress(
                    session,
                    render_step,
                    detail="素版已完成，开始生成包装版",
                    progress=0.55,
                )
            if render_output:
                render_output.progress = 0.55
                await session.commit()
        await render_video(
            source_path=source_path,
            render_plan=render_plan_timeline.data_json,
            editorial_timeline=editorial_timeline.data_json,
            output_path=tmp_packaged_mp4,
            subtitle_items=subtitle_dicts,
            debug_dir=debug_dir / "packaged",
        )
        import shutil
        shutil.copy2(tmp_plain_mp4, local_plain_mp4)
        shutil.copy2(tmp_packaged_mp4, local_packaged_mp4)
        async with get_session_factory()() as session:
            step_result = await session.execute(
                select(JobStep).where(JobStep.job_id == uuid.UUID(job_id), JobStep.step_name == "render")
            )
            render_step = step_result.scalar_one_or_none()
            render_output = await session.get(RenderOutput, render_output_id)
            if render_step:
                await _set_step_progress(session, render_step, detail="生成字幕文件与封面图", progress=0.75)
            if render_output:
                render_output.progress = 0.75
                await session.commit()

        # Write SRT with remapped timestamps (matches the edited video)
        keep_segments = [
            s for s in editorial_timeline.data_json.get("segments", [])
            if s.get("type") == "keep"
        ]
        remapped_subtitles = remap_subtitles_to_timeline(subtitle_dicts, keep_segments)
        packaged_subtitles = await _map_subtitles_to_packaged_timeline(
            remapped_subtitles,
            render_plan_timeline.data_json,
        )
        write_srt_file(packaged_subtitles, local_packaged_srt)
        write_srt_file(remapped_subtitles, local_plain_srt)

        # Extract cover frame: use 10% into video duration for a representative shot
        try:
            meta_result = await _get_cover_seek(job.id, tmpdir)
            cover_variants = await extract_cover_frame(
                tmp_packaged_mp4,
                local_cover,
                seek_sec=meta_result,
                content_profile=content_profile,
                cover_style=(render_plan_timeline.data_json.get("cover") or {}).get("style"),
                title_style=(render_plan_timeline.data_json.get("cover") or {}).get("title_style"),
            )
        except Exception:
            local_cover = None  # Cover is non-critical
            cover_variants = []

    # Also upload to S3/MinIO for API download endpoint (non-critical — local file is primary)
    packaged_output_key = job_key(job_id, "output.mp4")
    plain_output_key = job_key(job_id, "output_plain.mp4")
    try:
        storage = get_storage()
        await storage.async_upload_file(local_packaged_mp4, packaged_output_key)
        await storage.async_upload_file(local_plain_mp4, plain_output_key)
    except Exception:
        pass  # Local file is the primary delivery; S3 is for the download API

    # Update render output
    local_paths = {
        "mp4": str(local_packaged_mp4),
        "srt": str(local_packaged_srt),
        "packaged_mp4": str(local_packaged_mp4),
        "plain_mp4": str(local_plain_mp4),
        "packaged_srt": str(local_packaged_srt),
        "plain_srt": str(local_plain_srt),
        "cover": str(local_cover) if local_cover else None,
        "cover_variants": [str(path) for path in cover_variants] if local_cover else [],
        "output_name": out_name,
    }
    async with get_session_factory()() as session:
        render_output = await session.get(RenderOutput, render_output_id)
        render_output.output_path = str(local_packaged_mp4)
        render_output.status = "done"
        render_output.progress = 1.0
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == uuid.UUID(job_id), JobStep.step_name == "render")
        )
        render_step = step_result.scalar_one_or_none()
        session.add(
            Artifact(
                job_id=uuid.UUID(job_id),
                step_id=render_step.id if render_step else None,
                artifact_type="render_outputs",
                data_json={
                    "plain_mp4": str(local_plain_mp4),
                    "packaged_mp4": str(local_packaged_mp4),
                    "plain_srt": str(local_plain_srt),
                    "packaged_srt": str(local_packaged_srt),
                    "packaged_output_key": packaged_output_key,
                    "plain_output_key": plain_output_key,
                },
            )
        )
        if render_step:
            await _set_step_progress(
                session,
                render_step,
                detail=(
                    "素版与包装版均已输出"
                    if (has_packaging or has_editing_accents)
                    else "渲染完成，成片与字幕已输出"
                ),
                progress=1.0,
            )
        await session.commit()

    return {"output_key": packaged_output_key, "local": local_paths}


async def run_platform_package(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        if not job:
            raise ValueError(f"Job {job_id} not found")

        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "platform_package")
        )
        step = step_result.scalar_one_or_none()
        await _set_step_progress(session, step, detail="整理成片信息并生成平台文案", progress=0.2)

        content_profile_result = await session.execute(
            select(Artifact)
            .where(Artifact.job_id == job.id, Artifact.artifact_type == "content_profile")
            .order_by(Artifact.created_at.desc())
        )
        content_profile_artifact = content_profile_result.scalars().first()
        content_profile = content_profile_artifact.data_json if content_profile_artifact else None

        item_result = await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
        subtitle_items = item_result.scalars().all()
        subtitle_dicts = [
            {
                "index": si.item_index,
                "start_time": si.start_time,
                "end_time": si.end_time,
                "text_raw": si.text_raw,
                "text_norm": si.text_norm,
                "text_final": si.text_final,
            }
            for si in subtitle_items
        ]

        render_output_result = await session.execute(
            select(RenderOutput)
            .where(RenderOutput.job_id == job.id, RenderOutput.status == "done")
            .order_by(RenderOutput.created_at.desc())
        )
        render_output = render_output_result.scalars().first()
        if not render_output or not render_output.output_path:
            raise ValueError("Rendered output not found; platform package requires a finished render")

    packaging = await generate_platform_packaging(
        source_name=job.source_name,
        content_profile=content_profile,
        subtitle_items=subtitle_dicts,
    )

    output_mp4 = Path(render_output.output_path)
    output_md = output_mp4.with_name(f"{output_mp4.stem}_publish.md")
    save_platform_packaging_markdown(output_md, packaging)

    async with get_session_factory()() as session:
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "platform_package")
        )
        current_step = step_result.scalar_one_or_none()
        artifact = Artifact(
            job_id=job.id,
            step_id=current_step.id if current_step else None,
            artifact_type="platform_packaging_md",
            storage_path=str(output_md),
            data_json=packaging,
        )
        session.add(artifact)
        if current_step is not None:
            await _set_step_progress(session, current_step, detail="平台文案已生成", progress=1.0)
        await session.commit()

    return {"markdown": str(output_md)}


async def _get_cover_seek(job_id, tmpdir: str) -> float:
    """
    Determine a good seek time for cover frame extraction.
    Uses ~10% of video duration, with 5s minimum and 30s maximum.
    Falls back to 5.0s if no media_meta artifact found.
    """
    factory = get_session_factory()
    async with factory() as session:
        from roughcut.db.models import Artifact
        result = await session.execute(
            select(Artifact).where(
                Artifact.job_id == job_id,
                Artifact.artifact_type == "media_meta",
            )
        )
        artifact = result.scalar_one_or_none()
        if artifact and artifact.data_json:
            duration = artifact.data_json.get("duration", 60.0)
            seek = max(5.0, min(30.0, duration * 0.10))
            return round(seek, 1)
    return 5.0


async def _plan_insert_asset_slot(
    *,
    job_id: str,
    insert_plan: dict | None,
    subtitle_items: list[dict],
    content_profile: dict | None,
) -> dict | None:
    if not insert_plan:
        return None
    if not subtitle_items:
        insert_plan["insert_after_sec"] = 0.0
        insert_plan["reason"] = "没有可用字幕，默认插入到开头。"
        return insert_plan

    candidates = [
        item for item in subtitle_items
        if float(item.get("end_time", 0.0) or 0.0) > 8.0
    ]
    if not candidates:
        first = subtitle_items[min(len(subtitle_items) - 1, max(0, len(subtitle_items) // 2))]
        insert_plan["insert_after_sec"] = float(first.get("end_time", 0.0) or 0.0)
        insert_plan["reason"] = "字幕太短，回退到中间位置插入。"
        return insert_plan

    transcript_excerpt = "\n".join(
        f"[{float(item.get('start_time', 0.0)):.1f}-{float(item.get('end_time', 0.0)):.1f}] "
        f"{item.get('text_final') or item.get('text_norm') or item.get('text_raw') or ''}"
        for item in candidates[:48]
    )
    fallback = candidates[len(candidates) // 2]
    fallback_sec = float(fallback.get("end_time", 0.0) or 0.0)

    try:
        provider = get_reasoning_provider()
        prompt = (
            "你在给一条中文短视频安排一段植入素材的插入点。"
            "请根据字幕节奏和内容结构，找一个最自然、不打断关键论点的位置。"
            "优先选择一句话讲完之后、下一个话题开始之前；不要插在开场 8 秒内，也不要插在结尾收束段。"
            "如果视频主题是开箱评测，优先放在产品基础介绍讲完、进入细节体验之前。"
            "输出 JSON："
            '{"insert_after_sec":0.0,"reason":""}'
            f"\n视频信息：{json.dumps(content_profile or {}, ensure_ascii=False)}"
            f"\n候选字幕（已映射到剪后时间轴）：\n{transcript_excerpt}"
            f"\n如果拿不准，就返回 {fallback_sec:.1f} 附近的自然停顿。"
        )
        response = await provider.complete(
            [
                Message(role="system", content="你是短视频植入编排助手，只输出 JSON。"),
                Message(role="user", content=prompt),
            ],
            temperature=0.1,
            max_tokens=300,
            json_mode=True,
        )
        data = response.as_json()
        chosen = float(data.get("insert_after_sec", fallback_sec) or fallback_sec)
        max_sec = float(candidates[-1].get("end_time", fallback_sec) or fallback_sec)
        insert_plan["insert_after_sec"] = max(8.0, min(chosen, max_sec))
        insert_plan["reason"] = str(data.get("reason") or "").strip() or "LLM 选择了较自然的转场点。"
        return insert_plan
    except Exception:
        insert_plan["insert_after_sec"] = fallback_sec
        insert_plan["reason"] = "LLM 未返回可靠结果，回退到中间自然停顿。"
        return insert_plan


async def _map_subtitles_to_packaged_timeline(
    subtitle_items: list[dict],
    render_plan: dict,
) -> list[dict]:
    if not subtitle_items:
        return []

    mapped = [dict(item) for item in subtitle_items]
    leading_offset = 0.0

    intro_plan = render_plan.get("intro")
    if intro_plan and intro_plan.get("path"):
        intro_duration = await _probe_media_duration(Path(intro_plan["path"]))
        if intro_duration > 0:
            leading_offset += intro_duration
            for item in mapped:
                item["start_time"] = float(item["start_time"]) + intro_duration
                item["end_time"] = float(item["end_time"]) + intro_duration

    insert_plan = render_plan.get("insert")
    if insert_plan and insert_plan.get("path"):
        insert_duration = await _probe_media_duration(Path(insert_plan["path"]))
        insert_after_sec = float(insert_plan.get("insert_after_sec", 0.0) or 0.0) + leading_offset
        if insert_duration > 0:
            mapped = _shift_subtitles_for_insert(
                mapped,
                insert_after_sec=insert_after_sec,
                insert_duration=insert_duration,
            )

    return mapped


async def _probe_media_duration(path: Path) -> float:
    try:
        return max(0.0, float((await probe(path)).duration or 0.0))
    except Exception:
        return 0.0


def _shift_subtitles_for_insert(
    subtitle_items: list[dict],
    *,
    insert_after_sec: float,
    insert_duration: float,
) -> list[dict]:
    shifted: list[dict] = []
    for item in subtitle_items:
        start_time = float(item.get("start_time", 0.0) or 0.0)
        end_time = float(item.get("end_time", 0.0) or 0.0)
        if end_time <= insert_after_sec:
            shifted.append(dict(item))
            continue
        if start_time >= insert_after_sec:
            shifted_item = dict(item)
            shifted_item["start_time"] = start_time + insert_duration
            shifted_item["end_time"] = end_time + insert_duration
            shifted.append(shifted_item)
            continue

        head = dict(item)
        head["start_time"] = start_time
        head["end_time"] = insert_after_sec

        tail = dict(item)
        tail["start_time"] = insert_after_sec + insert_duration
        tail["end_time"] = end_time + insert_duration
        shifted.extend([head, tail])
    return shifted


def _hash_file(path: Path, chunk_size: int = 65536) -> str:
    sha256 = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()


def _record_source_integrity(
    local_path: Path,
    *,
    source_ref: str,
    expected_hash: str | None,
    debug_dir: Path | None,
    downloaded: bool,
) -> str:
    actual_hash = _hash_file(local_path)
    payload = {
        "source_ref": source_ref,
        "local_path": str(local_path),
        "downloaded_from_storage": downloaded,
        "expected_sha256": expected_hash,
        "actual_sha256": actual_hash,
        "hash_match": expected_hash in (None, "", actual_hash),
        "size_bytes": local_path.stat().st_size,
    }
    if debug_dir is not None:
        (debug_dir / "source.integrity.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if expected_hash and actual_hash != expected_hash:
        raise ValueError(
            f"Downloaded source hash mismatch: expected {expected_hash}, got {actual_hash}"
        )
    return actual_hash


def run_step_sync(step_name: str, job_id: str) -> dict:
    """Synchronous entry point for Celery tasks."""
    # Force-reset engine singleton so asyncpg doesn't reuse connections from a previous event loop
    import roughcut.db.session as _sess
    _sess._engine = None
    _sess._session_factory = None

    step_map = {
        "probe": run_probe,
        "extract_audio": run_extract_audio,
        "transcribe": run_transcribe,
        "subtitle_postprocess": run_subtitle_postprocess,
        "content_profile": run_content_profile,
        "glossary_review": run_glossary_review,
        "edit_plan": run_edit_plan,
        "render": run_render,
        "platform_package": run_platform_package,
    }
    fn = step_map.get(step_name)
    if not fn:
        raise ValueError(f"Unknown step: {step_name}")
    return asyncio.run(fn(job_id))
