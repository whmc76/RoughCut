from __future__ import annotations

from copy import deepcopy
import uuid
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.db.models import Artifact, FactClaim, JobStep, SubtitleCorrection, SubtitleItem, TranscriptSegment
from roughcut.config import get_settings
from roughcut.providers.factory import get_transcription_provider, resolve_transcription_provider_plan
from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment as ProviderTranscriptSegment, TranscriptionProgressCallback, WordTiming
from roughcut.review.evidence_types import ARTIFACT_TYPE_TRANSCRIPT_EVIDENCE
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

    return await persist_transcript_result(
        job_id=job_id,
        step=step,
        glossary_terms=glossary_terms or [],
        language=language,
        result=result,
        review_memory=review_memory,
        selected_model=selected_model,
        selected_provider=selected_provider,
        session=session,
        prompt=prompt,
        attempt_errors=attempt_errors,
    )


async def persist_empty_transcript_result(
    job_id: uuid.UUID,
    step: JobStep,
    *,
    language: str,
    session: AsyncSession,
    prompt: str | None = None,
    reason: str = "no_audio_stream",
    glossary_terms: list[dict] | None = None,
    review_memory: dict | None = None,
) -> TranscriptResult:
    return await persist_transcript_result(
        job_id=job_id,
        step=step,
        language=language,
        session=session,
        prompt=prompt,
        glossary_terms=glossary_terms or [],
        review_memory=review_memory,
        result=TranscriptResult(
            segments=[],
            language=language,
            duration=0.0,
            provider="system",
            model="no_audio",
            raw_payload={"reason": reason},
            raw_segments=[],
            context=reason,
        ),
        selected_provider="system",
        selected_model="no_audio",
        attempt_errors=[],
    )


async def persist_transcript_result(
    *,
    job_id: uuid.UUID,
    step: JobStep,
    language: str,
    session: AsyncSession,
    result: TranscriptResult,
    prompt: str | None,
    glossary_terms: list[dict],
    review_memory: dict | None,
    selected_provider: str | None,
    selected_model: str | None,
    attempt_errors: list[dict[str, str]],
) -> TranscriptResult:
    settings = get_settings()
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
            "language": language,
            "duration": result.duration,
            "segment_count": len(result.segments),
            "provider": selected_provider or result.provider,
            "model": selected_model or result.model,
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
    if bool(getattr(settings, "asr_evidence_enabled", False)):
        session.add(
            Artifact(
                job_id=job_id,
                step_id=step.id,
                artifact_type=ARTIFACT_TYPE_TRANSCRIPT_EVIDENCE,
                data_json={
                    "language": language,
                    "duration": result.duration,
                    "provider": result.provider or selected_provider,
                    "model": result.model or selected_model,
                    "prompt": str(prompt or ""),
                    "context": result.context,
                    "hotword": result.hotword,
                    "attempts": [
                        *attempt_errors,
                        *(
                            [{"provider": selected_provider, "model": selected_model, "error": ""}]
                            if selected_provider
                            else []
                        ),
                    ],
                    "raw_payload": deepcopy(result.raw_payload),
                    "raw_segments": [_serialize_transcript_segment(seg) for seg in (result.raw_segments or [])],
                    "segments": [_serialize_transcript_segment(seg) for seg in result.segments],
                },
            )
        )
    await session.flush()

    return result


def _normalize_transcript_result(
    result: TranscriptResult,
    *,
    glossary_terms: list[dict],
    review_memory: dict | None,
) -> TranscriptResult:
    raw_segments = deepcopy(result.raw_segments or result.segments)
    normalized = deepcopy(result)
    normalized.raw_segments = raw_segments
    normalized.raw_payload = deepcopy(result.raw_payload)

    for raw_seg, seg in zip(raw_segments, normalized.segments):
        seg.raw_text = raw_seg.raw_text or raw_seg.text
        seg.raw_payload = deepcopy(raw_seg.raw_payload)
        seg.provider = seg.provider or raw_seg.provider or result.provider
        seg.model = seg.model or raw_seg.model or result.model
        seg.context = seg.context or raw_seg.context or result.context
        seg.hotword = seg.hotword or raw_seg.hotword or result.hotword
        seg.confidence = seg.confidence if seg.confidence is not None else raw_seg.confidence
        seg.logprob = seg.logprob if seg.logprob is not None else raw_seg.logprob
        seg.alignment = seg.alignment if seg.alignment is not None else raw_seg.alignment

        raw_words = raw_seg.words or []
        for raw_word, word in zip(raw_words, seg.words):
            word.raw_text = raw_word.raw_text or raw_word.word
            word.raw_payload = deepcopy(raw_word.raw_payload)
            word.provider = word.provider or raw_word.provider or seg.provider
            word.model = word.model or raw_word.model or seg.model
            word.context = word.context or raw_word.context or seg.context
            word.hotword = word.hotword or raw_word.hotword or seg.hotword
            word.confidence = word.confidence if word.confidence is not None else raw_word.confidence
            word.logprob = word.logprob if word.logprob is not None else raw_word.logprob
            word.alignment = word.alignment if word.alignment is not None else raw_word.alignment

    for seg in normalized.segments:
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
    return normalized


def _serialize_word_timing(word: WordTiming) -> dict[str, object]:
    return {
        "word": word.word,
        "raw_text": word.raw_text,
        "start": word.start,
        "end": word.end,
        "provider": word.provider,
        "model": word.model,
        "context": word.context,
        "hotword": word.hotword,
        "confidence": word.confidence,
        "logprob": word.logprob,
        "alignment": deepcopy(word.alignment),
        "raw_payload": deepcopy(word.raw_payload),
    }


def _serialize_transcript_segment(seg: ProviderTranscriptSegment) -> dict[str, object]:
    return {
        "index": seg.index,
        "start": seg.start,
        "end": seg.end,
        "text": seg.text,
        "raw_text": seg.raw_text,
        "speaker": seg.speaker,
        "provider": seg.provider,
        "model": seg.model,
        "context": seg.context,
        "hotword": seg.hotword,
        "confidence": seg.confidence,
        "logprob": seg.logprob,
        "alignment": deepcopy(seg.alignment),
        "raw_payload": deepcopy(seg.raw_payload),
        "words": [_serialize_word_timing(word) for word in seg.words],
    }
