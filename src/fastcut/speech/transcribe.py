from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from fastcut.db.models import Artifact, JobStep, TranscriptSegment
from fastcut.providers.factory import get_transcription_provider
from fastcut.providers.transcription.base import TranscriptResult


async def transcribe_audio(
    job_id: uuid.UUID,
    step: JobStep,
    audio_path: Path,
    language: str,
    session: AsyncSession,
) -> TranscriptResult:
    """
    Transcribe audio using the configured TranscriptionProvider.
    Writes TranscriptSegment rows and an artifact to the DB.
    """
    provider = get_transcription_provider()
    result = await provider.transcribe(audio_path, language=language)

    # Persist segments
    for seg in result.segments:
        db_seg = TranscriptSegment(
            job_id=job_id,
            version=1,
            segment_index=seg.index,
            start_time=seg.start,
            end_time=seg.end,
            speaker=seg.speaker,
            text=seg.text,
            words_json=[{"word": w.word, "start": w.start, "end": w.end} for w in seg.words],
        )
        session.add(db_seg)

    # Save artifact metadata
    artifact = Artifact(
        job_id=job_id,
        step_id=step.id,
        artifact_type="transcript",
        data_json={
            "language": result.language,
            "duration": result.duration,
            "segment_count": len(result.segments),
        },
    )
    session.add(artifact)
    await session.flush()

    return result
