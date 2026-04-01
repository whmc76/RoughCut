from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.db.models import Artifact, FactClaim, JobStep, SubtitleCorrection, SubtitleItem, TranscriptSegment
from roughcut.config import get_settings
from roughcut.providers.factory import get_transcription_provider, resolve_transcription_provider_plan
from roughcut.providers.transcription.base import TranscriptResult, TranscriptionProgressCallback
from roughcut.review.subtitle_memory import apply_domain_term_corrections


def _is_brand_like_term(term: dict) -> bool:
    category = str(term.get("category") or "").strip().lower()
    return bool(category and "brand" in category)


async def execute_transcription_plan(
    *,
    audio_path: Path,
    language: str,
    prompt: str | None,
    provider_plan: list[tuple[str, str]],
    progress_callback: TranscriptionProgressCallback | None = None,
) -> tuple[TranscriptResult, str, str, list[dict[str, str]]]:
    attempt_errors: list[dict[str, str]] = []
    for provider_name, model_name in provider_plan:
        try:
            provider = get_transcription_provider(provider=provider_name, model=model_name)
            result = await provider.transcribe(
                audio_path,
                language=language,
                prompt=prompt,
                progress_callback=progress_callback,
            )
            return result, provider_name, model_name, attempt_errors
        except Exception as exc:
            attempt_errors.append(
                {
                    "provider": provider_name,
                    "model": model_name,
                    "error": str(exc),
                }
            )

    failure_summary = "; ".join(
        f"{item['provider']}/{item['model']}: {item['error']}"
        for item in attempt_errors
    )
    raise RuntimeError(f"All transcription providers failed: {failure_summary}")


async def transcribe_audio(
    job_id: uuid.UUID,
    step: JobStep,
    audio_path: Path,
    language: str,
    session: AsyncSession,
    prompt: str | None = None,
    progress_callback: TranscriptionProgressCallback | None = None,
    glossary_terms: list[dict] | None = None,
    review_memory: dict | None = None,
) -> TranscriptResult:
    """
    Transcribe audio using the configured TranscriptionProvider.
    Writes TranscriptSegment rows and an artifact to the DB.
    """
    settings = get_settings()
    provider_plan = resolve_transcription_provider_plan(
        provider=settings.transcription_provider,
        model=settings.transcription_model,
    )
    result, selected_provider, selected_model, attempt_errors = await execute_transcription_plan(
        audio_path=audio_path,
        language=language,
        prompt=prompt,
        provider_plan=provider_plan,
        progress_callback=progress_callback,
    )

    result = _normalize_transcript_result(
        result,
        glossary_terms=glossary_terms or [],
        review_memory=review_memory,
    )

    # Replace the previous transcript-derived rows on rerun instead of appending
    # another copy with the same indexes and stale downstream references.
    await session.execute(delete(SubtitleCorrection).where(SubtitleCorrection.job_id == job_id))
    await session.execute(delete(FactClaim).where(FactClaim.job_id == job_id))
    await session.execute(delete(SubtitleItem).where(SubtitleItem.job_id == job_id, SubtitleItem.version == 1))
    await session.execute(delete(TranscriptSegment).where(TranscriptSegment.job_id == job_id, TranscriptSegment.version == 1))

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
            "provider": selected_provider,
            "model": selected_model,
            "attempts": [
                *attempt_errors,
                *(
                    [{"provider": selected_provider, "model": selected_model, "error": ""}]
                    if selected_provider
                    else []
                ),
            ],
        },
    )
    session.add(artifact)
    await session.flush()

    return result


def _normalize_transcript_result(
    result: TranscriptResult,
    *,
    glossary_terms: list[dict],
    review_memory: dict | None,
) -> TranscriptResult:
    for seg in result.segments:
        text = str(seg.text or "").strip()
        if not text:
            continue
        for term in glossary_terms:
            if _is_brand_like_term(term):
                continue
            correct_form = str(term.get("correct_form") or "").strip()
            if not correct_form:
                continue
            for wrong_form in term.get("wrong_forms") or []:
                wrong = str(wrong_form or "").strip()
                if wrong and wrong != correct_form:
                    text = text.replace(wrong, correct_form)
        text = apply_domain_term_corrections(text, review_memory)
        seg.text = text
    return result
