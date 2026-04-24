from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import math
import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.db.models import Artifact, FactClaim, JobStep, SubtitleCorrection, SubtitleItem, TranscriptSegment
from roughcut.config import get_settings
from roughcut.providers.factory import get_transcription_provider, resolve_transcription_provider_plan
from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment as ProviderTranscriptSegment, TranscriptionProgressCallback, WordTiming
from roughcut.providers.transcription.chunking import extract_chunking_summary
from roughcut.review.evidence_types import ARTIFACT_TYPE_TRANSCRIPT_EVIDENCE
from roughcut.review.hotword_learning import extract_prompt_hotwords, record_prompted_hotwords
from roughcut.review.subtitle_memory import apply_domain_term_corrections, resolve_transcription_category_scope
from roughcut.speech.alignment import AlignmentSettings, enhance_transcript_alignment
from roughcut.speech.subtitle_pipeline import (
    ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER,
    build_transcript_fact_layer_from_result,
)

_TRANSCRIPT_TAIL_CTA_NOISE_RE = re.compile(
    r"(感谢观看|请不吝点赞|打赏支持|"
    r"点赞.{0,8}(订阅|关注|收藏|转发)|"
    r"(订阅|关注|收藏).{0,8}点赞|"
    r"转发.{0,8}(点赞|订阅|关注|收藏))",
    re.IGNORECASE,
)
_SEMANTIC_HALLUCINATION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"鱼头的小章鱼"), ""),
    (re.compile(r"新品小车"), ""),
)
_DUPLICATE_BRAND_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(狐蝠工业){2,}", re.IGNORECASE), "狐蝠工业"),
    (re.compile(r"(NITECORE){2,}", re.IGNORECASE), "NITECORE"),
    (re.compile(r"(OLIGHT){2,}", re.IGNORECASE), "OLIGHT"),
)
_FLASHLIGHT_CONTAMINATION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"电折刀"), "手电"),
    (re.compile(r"\bEDC(17|23|37)折刀(?:帕)?\b", re.IGNORECASE), r"EDC\1"),
    (re.compile(r"(?<![A-Za-z0-9])幺[七7](?![A-Za-z0-9])"), "EDC17"),
)
_FLASHLIGHT_EDC_ALT_LIST_RE = re.compile(
    r"(?<![A-Za-z0-9])(EDC(?:17|23|37))(?:\s*/\s*(EDC(?:17|23|37)))+(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_KNIFE_MATERIAL_SURFACE_MISHEARD_RE = re.compile(r"钢瓦|盖瓦|锆瓦|(?:钢马|锆马).{0,16}泛光")


def _is_brand_like_term(term: dict) -> bool:
    category = str(term.get("category") or "").strip().lower()
    return bool(category and "brand" in category)


def _compact_transcript_noise_text(text: str) -> str:
    return re.sub(r"[\s\u3000,，.。!！?？:：;；/\\|_\-]+", "", str(text or ""))


def _looks_like_tail_cta_noise(text: str) -> bool:
    compact = _compact_transcript_noise_text(text)
    if not compact or len(compact) > 40:
        return False
    if "感谢观看" in compact:
        return True
    if "请不吝点赞" in compact or "打赏支持" in compact:
        return True
    return bool(_TRANSCRIPT_TAIL_CTA_NOISE_RE.search(compact))


def _is_tail_noise_candidate(
    *,
    order_index: int,
    segment_count: int,
    start: float,
    end: float,
    duration: float,
) -> bool:
    if end <= start or (end - start) > 8.0:
        return False
    if order_index >= max(segment_count - 2, 0):
        return True
    tail_start = max(duration - 20.0, duration * 0.85)
    return end >= tail_start


def _filter_tail_cta_noise_segments(result: TranscriptResult) -> list[dict[str, Any]]:
    segment_count = len(list(result.segments or []))
    if segment_count <= 0:
        return []

    duration = max(
        float(result.duration or 0.0),
        max((float(getattr(seg, "end", 0.0) or 0.0) for seg in list(result.segments or [])), default=0.0),
    )
    kept_segments: list[ProviderTranscriptSegment] = []
    dropped_segments: list[dict[str, Any]] = []
    for order_index, seg in enumerate(list(result.segments or [])):
        start = float(getattr(seg, "start", 0.0) or 0.0)
        end = float(getattr(seg, "end", 0.0) or 0.0)
        text = str(getattr(seg, "raw_text", None) or getattr(seg, "text", "") or "").strip()
        if (
            text
            and _is_tail_noise_candidate(
                order_index=order_index,
                segment_count=segment_count,
                start=start,
                end=end,
                duration=duration,
            )
            and _looks_like_tail_cta_noise(text)
        ):
            dropped_segments.append(
                {
                    "index": int(getattr(seg, "index", order_index) or order_index),
                    "start": start,
                    "end": end,
                    "text": str(getattr(seg, "text", "") or ""),
                    "raw_text": str(getattr(seg, "raw_text", None) or getattr(seg, "text", "") or ""),
                    "reason": "tail_cta_noise",
                }
            )
            continue
        kept_segments.append(seg)
    if dropped_segments:
        result.segments = kept_segments
        filtering = dict(result.raw_payload.get("_roughcut_filtering") or {})
        filtering["dropped_tail_cta_segments"] = dropped_segments
        result.raw_payload["_roughcut_filtering"] = filtering
    return dropped_segments


def _normalize_semantic_contamination_text(text: str, *, category_scope: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    for pattern, replacement in _SEMANTIC_HALLUCINATION_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    for pattern, replacement in _DUPLICATE_BRAND_PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    if category_scope == "flashlight":
        for pattern, replacement in _FLASHLIGHT_CONTAMINATION_PATTERNS:
            cleaned = pattern.sub(replacement, cleaned)
        cleaned = _collapse_flashlight_edc_alt_lists(cleaned)
    elif category_scope == "knife":
        cleaned = _normalize_knife_material_surface_text(cleaned)
    cleaned = re.sub(r"[，,]{2,}", "，", cleaned)
    cleaned = re.sub(r"[。]{2,}", "。", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ，,。；;、")
    return cleaned.strip()


def _collapse_flashlight_edc_alt_lists(text: str) -> str:
    """Collapse ASR alternative lists like "EDC17 / EDC37 / EDC37"."""

    def replace(match: re.Match[str]) -> str:
        models = re.findall(r"EDC(?:17|23|37)", match.group(0), flags=re.IGNORECASE)
        normalized = [item.upper() for item in models]
        if len(normalized) >= 3 or len(set(normalized)) < len(normalized):
            return normalized[0]
        return match.group(0)

    return _FLASHLIGHT_EDC_ALT_LIST_RE.sub(replace, text)


def _normalize_knife_material_surface_text(text: str) -> str:
    if not _KNIFE_MATERIAL_SURFACE_MISHEARD_RE.search(text):
        return text
    cleaned = text.replace("钢瓦", "钢马").replace("盖瓦", "锆马").replace("锆瓦", "锆马")
    if "钢马" in cleaned or "锆马" in cleaned:
        cleaned = cleaned.replace("泛光", "反光")
    return cleaned


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
    prompt_hotwords = extract_prompt_hotwords(prompt)
    chunking_summary = extract_chunking_summary(result.raw_payload if isinstance(result.raw_payload, dict) else {})
    result = _normalize_transcript_result(
        result,
        glossary_terms=glossary_terms or [],
        review_memory=review_memory,
        alignment_settings=AlignmentSettings(
            mode=str(getattr(settings, "transcription_alignment_mode", "auto") or "auto"),
            min_word_coverage=float(getattr(settings, "transcription_alignment_min_word_coverage", 0.72) or 0.72),
        ),
    )
    transcript_fact_layer = build_transcript_fact_layer_from_result(result)

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
            words_json=[_serialize_word_timing(w) for w in seg.words],
        )
        session.add(db_seg)

    # Save artifact metadata
    artifact = Artifact(
        job_id=job_id,
        step_id=step.id,
        artifact_type="transcript",
        data_json=_json_safe_value({
            "language": language,
            "duration": result.duration,
            "segment_count": len(result.segments),
            "provider": selected_provider or result.provider,
            "model": selected_model or result.model,
            "chunking": _json_safe_value(chunking_summary),
            "alignment": _json_safe_value(deepcopy(result.alignment)),
            "attempts": [
                *attempt_errors,
                *(
                    [{"provider": selected_provider, "model": selected_model, "error": ""}]
                    if selected_provider
                    else []
                ),
            ],
        }),
    )
    session.add(artifact)
    session.add(
        Artifact(
            job_id=job_id,
            step_id=step.id,
            artifact_type=ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER,
            data_json=_json_safe_value(transcript_fact_layer.as_dict()),
        )
    )
    if bool(getattr(settings, "asr_evidence_enabled", False)):
        session.add(
            Artifact(
                job_id=job_id,
                step_id=step.id,
                artifact_type=ARTIFACT_TYPE_TRANSCRIPT_EVIDENCE,
                data_json=_json_safe_value({
                    "language": language,
                    "duration": result.duration,
                    "provider": result.provider or selected_provider,
                    "model": result.model or selected_model,
                    "chunking": _json_safe_value(chunking_summary),
                    "prompt": str(prompt or ""),
                    "prompt_hotwords": prompt_hotwords,
                    "prompt_hotword_count": len(prompt_hotwords),
                    "context": result.context,
                    "hotword": result.hotword,
                    "alignment": _json_safe_value(deepcopy(result.alignment)),
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
                }),
            )
        )
    await record_prompted_hotwords(session, prompt_hotwords=prompt_hotwords)
    await session.flush()

    return result


def _normalize_transcript_result(
    result: TranscriptResult,
    *,
    glossary_terms: list[dict],
    review_memory: dict | None,
    alignment_settings: AlignmentSettings | None = None,
) -> TranscriptResult:
    raw_segments = deepcopy(result.raw_segments or result.segments)
    normalized = deepcopy(result)
    normalized.raw_segments = raw_segments
    normalized.raw_payload = deepcopy(result.raw_payload)
    category_scope = resolve_transcription_category_scope(review_memory)

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
        cleaned_text = _normalize_semantic_contamination_text(text, category_scope=category_scope)
        if cleaned_text != text:
            filtering = dict(normalized.raw_payload.get("_roughcut_filtering") or {})
            semantic_cleanup = list(filtering.get("semantic_cleanup") or [])
            semantic_cleanup.append(
                {
                    "segment_index": int(getattr(seg, "index", 0) or 0),
                    "category_scope": category_scope,
                    "before": text,
                    "after": cleaned_text,
                }
            )
            filtering["semantic_cleanup"] = semantic_cleanup[:80]
            normalized.raw_payload["_roughcut_filtering"] = filtering
        text = cleaned_text
        seg.text = text
    normalized.segments = [seg for seg in normalized.segments if str(seg.text or "").strip()]
    _filter_tail_cta_noise_segments(normalized)
    return enhance_transcript_alignment(normalized, settings=alignment_settings)


def _serialize_word_timing(word: WordTiming) -> dict[str, object]:
    return {
        "word": word.word,
        "raw_text": word.raw_text,
        "start": _json_safe_value(word.start),
        "end": _json_safe_value(word.end),
        "provider": word.provider,
        "model": word.model,
        "context": word.context,
        "hotword": word.hotword,
        "confidence": _json_safe_value(word.confidence),
        "logprob": _json_safe_value(word.logprob),
        "alignment": _json_safe_value(deepcopy(word.alignment)),
        "raw_payload": _json_safe_value(deepcopy(word.raw_payload)),
    }


def _serialize_transcript_segment(seg: ProviderTranscriptSegment) -> dict[str, object]:
    return {
        "index": seg.index,
        "start": _json_safe_value(seg.start),
        "end": _json_safe_value(seg.end),
        "text": seg.text,
        "raw_text": seg.raw_text,
        "speaker": seg.speaker,
        "provider": seg.provider,
        "model": seg.model,
        "context": seg.context,
        "hotword": seg.hotword,
        "confidence": _json_safe_value(seg.confidence),
        "logprob": _json_safe_value(seg.logprob),
        "alignment": _json_safe_value(deepcopy(seg.alignment)),
        "raw_payload": _json_safe_value(deepcopy(seg.raw_payload)),
        "words": [_serialize_word_timing(word) for word in seg.words],
    }


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_value(item) for item in value]

    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            scalar = item_method()
        except Exception:
            scalar = None
        else:
            if scalar is not value:
                return _json_safe_value(scalar)

    for attr in ("model_dump", "dict", "to_dict"):
        method = getattr(value, attr, None)
        if not callable(method):
            continue
        try:
            dumped = method()
        except TypeError:
            try:
                dumped = method(mode="json")
            except Exception:
                continue
        except Exception:
            continue
        return _json_safe_value(dumped)

    if hasattr(value, "__dict__"):
        return {
            key: _json_safe_value(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }

    return repr(value)
