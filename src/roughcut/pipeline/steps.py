"""
Business logic for each pipeline step.
Each function takes job_id + step info and does the actual work.
These are called by Celery tasks (which handle the async→sync bridge).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import select

from roughcut.config import get_settings
from roughcut.db.models import Artifact, GlossaryTerm, Job, JobStep, RenderOutput, SubtitleItem, TranscriptSegment
from roughcut.db.session import get_session_factory
from roughcut.edit.decisions import build_edit_decision
from roughcut.edit.otio_export import export_to_otio
from roughcut.edit.render_plan import build_render_plan, save_render_plan
from roughcut.edit.timeline import save_editorial_timeline
from roughcut.media.audio import extract_audio
from roughcut.media.output import build_output_name, extract_cover_frame, get_output_dir, write_srt_file
from roughcut.media.subtitles import remap_subtitles_to_timeline
from roughcut.media.probe import probe, validate_media
from roughcut.media.render import render_video
from roughcut.media.silence import detect_silence
from roughcut.review.content_profile import enrich_content_profile, infer_content_profile, polish_subtitle_items
from roughcut.review.glossary_engine import apply_glossary_corrections
from roughcut.review.platform_copy import generate_platform_packaging, save_platform_packaging_markdown
from roughcut.speech.postprocess import save_subtitle_items, split_into_subtitles
from roughcut.speech.transcribe import transcribe_audio
from roughcut.storage.s3 import get_storage, job_key


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


async def run_content_profile(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "content_profile")
        )
        step = step_result.scalar_one()

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

        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = await _resolve_source(job, tmpdir, expected_hash=job.file_hash)
            content_profile = await infer_content_profile(
                source_path=source_path,
                source_name=job.source_name,
                subtitle_items=subtitle_dicts,
                channel_profile=job.channel_profile,
                include_research=False,
            )

        artifact = Artifact(
            job_id=job.id,
            step_id=step.id,
            artifact_type="content_profile_draft",
            data_json=content_profile,
        )
        session.add(artifact)
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

        item_result = await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
        subtitle_items = item_result.scalars().all()

        corrections = await apply_glossary_corrections(job.id, subtitle_items, session)
        glossary_result = await session.execute(select(GlossaryTerm))
        glossary_terms = glossary_result.scalars().all()

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
                )
        else:
            content_profile = await enrich_content_profile(
                profile=content_profile,
                source_name=job.source_name,
                channel_profile=job.channel_profile,
                transcript_excerpt=str(content_profile.get("transcript_excerpt") or ""),
                include_research=True,
            )

        polished_count = await polish_subtitle_items(
            subtitle_items,
            content_profile=content_profile,
            glossary_terms=[
                {
                    "wrong_forms": term.wrong_forms,
                    "correct_form": term.correct_form,
                    "category": term.category,
                }
                for term in glossary_terms
            ],
        )

        artifact = Artifact(
            job_id=job.id,
            step_id=None,
            artifact_type="content_profile",
            data_json=content_profile,
        )
        session.add(artifact)
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

        render_plan_dict = build_render_plan(
            editorial_timeline_id=editorial_timeline.id,
            workflow_preset=job.channel_profile or "unboxing_default",
        )
        await save_render_plan(job.id, render_plan_dict, session)

        await session.commit()
        return {"timeline_id": str(editorial_timeline.id)}


async def run_render(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        from roughcut.db.models import RenderOutput, Timeline

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
        )
        session.add(render_output)
        await session.flush()
        render_output_id = render_output.id

        await session.commit()

    # Render (outside transaction — can be long)
    # Build canonical output name: YYYYMMDD_OriginalStem
    out_name = build_output_name(job.source_name, job.created_at)
    out_dir = get_output_dir()
    debug_dir = Path(get_settings().render_debug_dir) / f"{job_id}_{out_name}"
    debug_dir.mkdir(parents=True, exist_ok=True)
    local_mp4 = out_dir / f"{out_name}.mp4"
    local_srt = out_dir / f"{out_name}.srt"
    local_cover = out_dir / f"{out_name}_cover.jpg"

    with tempfile.TemporaryDirectory() as tmpdir:
        source_path = await _resolve_source(
            job,
            tmpdir,
            expected_hash=job.file_hash,
            debug_dir=debug_dir,
        )
        tmp_mp4 = Path(tmpdir) / "output.mp4"
        await render_video(
            source_path=source_path,
            render_plan=render_plan_timeline.data_json,
            editorial_timeline=editorial_timeline.data_json,
            output_path=tmp_mp4,
            subtitle_items=subtitle_dicts,
            debug_dir=debug_dir,
        )
        import shutil
        shutil.copy2(tmp_mp4, local_mp4)

        # Write SRT with remapped timestamps (matches the edited video)
        keep_segments = [
            s for s in editorial_timeline.data_json.get("segments", [])
            if s.get("type") == "keep"
        ]
        remapped_subtitles = remap_subtitles_to_timeline(subtitle_dicts, keep_segments)
        write_srt_file(remapped_subtitles, local_srt)

        # Extract cover frame: use 10% into video duration for a representative shot
        try:
            meta_result = await _get_cover_seek(job.id, tmpdir)
            cover_variants = await extract_cover_frame(
                tmp_mp4,
                local_cover,
                seek_sec=meta_result,
                content_profile=content_profile,
            )
        except Exception:
            local_cover = None  # Cover is non-critical
            cover_variants = []

    # Also upload to S3/MinIO for API download endpoint (non-critical — local file is primary)
    output_key = job_key(job_id, "output.mp4")
    try:
        storage = get_storage()
        await storage.async_upload_file(local_mp4, output_key)
    except Exception:
        pass  # Local file is the primary delivery; S3 is for the download API

    # Update render output
    local_paths = {
        "mp4": str(local_mp4),
        "srt": str(local_srt),
        "cover": str(local_cover) if local_cover else None,
        "cover_variants": [str(path) for path in cover_variants] if local_cover else [],
        "output_name": out_name,
    }
    async with get_session_factory()() as session:
        render_output = await session.get(RenderOutput, render_output_id)
        render_output.output_path = str(local_mp4)
        render_output.status = "done"
        render_output.progress = 1.0
        await session.commit()

    return {"output_key": output_key, "local": local_paths}


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
        artifact = Artifact(
            job_id=job.id,
            step_id=step.id if step else None,
            artifact_type="platform_packaging_md",
            storage_path=str(output_md),
            data_json=packaging,
        )
        session.add(artifact)
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
