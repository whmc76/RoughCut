"""
Business logic for each pipeline step.
Each function takes job_id + step info and does the actual work.
These are called by Celery tasks (which handle the async→sync bridge).
"""
from __future__ import annotations

import asyncio
import hashlib
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select

from fastcut.db.models import Artifact, Job, JobStep, SubtitleItem, TranscriptSegment
from fastcut.db.session import get_session_factory
from fastcut.edit.decisions import build_edit_decision
from fastcut.edit.otio_export import export_to_otio
from fastcut.edit.render_plan import build_render_plan, save_render_plan
from fastcut.edit.timeline import save_editorial_timeline
from fastcut.media.audio import extract_audio
from fastcut.media.output import build_output_name, extract_cover_frame, get_output_dir, write_srt_file
from fastcut.media.probe import probe, validate_media
from fastcut.media.render import render_video
from fastcut.media.silence import detect_silence
from fastcut.review.glossary_engine import apply_glossary_corrections
from fastcut.speech.postprocess import save_subtitle_items, split_into_subtitles
from fastcut.speech.transcribe import transcribe_audio
from fastcut.storage.s3 import get_storage, job_key


async def _resolve_source(job, tmpdir: str) -> Path:
    """
    Return a local Path for the job's source file.
    If source_path is already a local file, return it directly.
    Otherwise download from S3 to tmpdir.
    """
    source_path = Path(job.source_path)
    if source_path.exists():
        return source_path
    # It's an S3 key — download to tmpdir
    local = Path(tmpdir) / job.source_name
    storage = get_storage()
    await storage.async_download_file(job.source_path, local)
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


async def run_probe(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "probe")
        )
        step = step_result.scalar_one()

        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = await _resolve_source(job, tmpdir)
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

        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = await _resolve_source(job, tmpdir)
            audio_path = Path(tmpdir) / "audio.wav"
            await extract_audio(source_path, audio_path)

            # Upload to S3
            storage = get_storage()
            key = job_key(job_id, "audio.wav")
            await storage.async_upload_file(audio_path, key)

        artifact = Artifact(
            job_id=job.id,
            step_id=step.id,
            artifact_type="audio_wav",
            storage_path=key,
        )
        session.add(artifact)
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

        # Get audio artifact key
        audio_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job.id, Artifact.artifact_type == "audio_wav")
        )
        audio_artifact = audio_result.scalar_one()

        storage = get_storage()
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "audio.wav"
            await storage.async_download_file(audio_artifact.storage_path, audio_path)

            result = await transcribe_audio(job.id, step, audio_path, job.language, session)

        await session.commit()
        return {"segment_count": len(result.segments), "duration": result.duration}


async def run_subtitle_postprocess(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))

        # Load transcript segments
        seg_result = await session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.job_id == job.id, TranscriptSegment.version == 1)
            .order_by(TranscriptSegment.segment_index)
        )
        segments = seg_result.scalars().all()

        entries = split_into_subtitles(segments)
        items = await save_subtitle_items(job.id, entries, session)
        await session.commit()

        return {"subtitle_count": len(items)}


async def run_glossary_review(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))

        item_result = await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
        subtitle_items = item_result.scalars().all()

        corrections = await apply_glossary_corrections(job.id, subtitle_items, session)
        await session.commit()

        return {"correction_count": len(corrections)}


async def run_edit_plan(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))

        # Get media meta for duration
        meta_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job.id, Artifact.artifact_type == "media_meta")
        )
        meta_artifact = meta_result.scalar_one()
        duration = meta_artifact.data_json["duration"]

        # Get audio for silence detection
        audio_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job.id, Artifact.artifact_type == "audio_wav")
        )
        audio_artifact = audio_result.scalar_one()

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
            }
            for si in subtitle_items
        ]

        storage = get_storage()
        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "audio.wav"
            await storage.async_download_file(audio_artifact.storage_path, audio_path)
            silences = detect_silence(audio_path)

        decision = build_edit_decision(
            source_path=job.source_path,
            duration=duration,
            silence_segments=silences,
            subtitle_items=subtitle_dicts,
        )

        editorial_timeline = await save_editorial_timeline(job.id, decision, session)

        # Export OTIO
        try:
            otio_str = export_to_otio(decision.to_dict())
            editorial_timeline.otio_data = otio_str
        except Exception:
            pass  # OTIO optional

        render_plan_dict = build_render_plan(editorial_timeline_id=editorial_timeline.id)
        await save_render_plan(job.id, render_plan_dict, session)

        await session.commit()
        return {"timeline_id": str(editorial_timeline.id)}


async def run_render(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        from fastcut.db.models import RenderOutput, Timeline

        job = await session.get(Job, uuid.UUID(job_id))

        # Get timelines
        editorial_result = await session.execute(
            select(Timeline).where(Timeline.job_id == job.id, Timeline.timeline_type == "editorial")
        )
        editorial_timeline = editorial_result.scalar_one()

        render_plan_result = await session.execute(
            select(Timeline).where(Timeline.job_id == job.id, Timeline.timeline_type == "render_plan")
        )
        render_plan_timeline = render_plan_result.scalar_one()

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
        )
        session.add(render_output)
        await session.flush()
        render_output_id = render_output.id

        await session.commit()

    # Render (outside transaction — can be long)
    # Build canonical output name: YYYYMMDD_OriginalStem
    out_name = build_output_name(job.source_name, job.created_at)
    out_dir = get_output_dir()
    local_mp4 = out_dir / f"{out_name}.mp4"
    local_srt = out_dir / f"{out_name}.srt"
    local_cover = out_dir / f"{out_name}_cover.jpg"

    with tempfile.TemporaryDirectory() as tmpdir:
        source_path = await _resolve_source(job, tmpdir)
        tmp_mp4 = Path(tmpdir) / "output.mp4"
        await render_video(
            source_path=source_path,
            render_plan=render_plan_timeline.data_json,
            editorial_timeline=editorial_timeline.data_json,
            output_path=tmp_mp4,
            subtitle_items=subtitle_dicts,
        )
        import shutil
        shutil.copy2(tmp_mp4, local_mp4)

        # Write SRT alongside
        write_srt_file(subtitle_dicts, local_srt)

        # Extract cover frame (source still in tmpdir)
        try:
            await extract_cover_frame(source_path, local_cover)
        except Exception:
            local_cover = None  # Cover is non-critical

    # Also upload to S3/MinIO for API download endpoint
    storage = get_storage()
    output_key = job_key(job_id, "output.mp4")
    await storage.async_upload_file(local_mp4, output_key)

    # Update render output
    local_paths = {
        "mp4": str(local_mp4),
        "srt": str(local_srt),
        "cover": str(local_cover) if local_cover else None,
        "output_name": out_name,
    }
    async with get_session_factory()() as session:
        render_output = await session.get(RenderOutput, render_output_id)
        render_output.output_path = str(local_mp4)
        render_output.status = "done"
        render_output.progress = 1.0
        await session.commit()

    return {"output_key": output_key, "local": local_paths}


def _hash_file(path: Path, chunk_size: int = 65536) -> str:
    sha256 = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()


def run_step_sync(step_name: str, job_id: str) -> dict:
    """Synchronous entry point for Celery tasks."""
    # Force-reset engine singleton so asyncpg doesn't reuse connections from a previous event loop
    import fastcut.db.session as _sess
    _sess._engine = None
    _sess._session_factory = None

    step_map = {
        "probe": run_probe,
        "extract_audio": run_extract_audio,
        "transcribe": run_transcribe,
        "subtitle_postprocess": run_subtitle_postprocess,
        "glossary_review": run_glossary_review,
        "edit_plan": run_edit_plan,
        "render": run_render,
    }
    fn = step_map.get(step_name)
    if not fn:
        raise ValueError(f"Unknown step: {step_name}")
    return asyncio.run(fn(job_id))
