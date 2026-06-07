from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from roughcut.db.models import Artifact, SubtitleItem
from roughcut.media.subtitle_spans import drop_redundant_synthetic_word_payloads
from roughcut.providers.transcription.base import TranscriptResult
from roughcut.review.model_identity import model_numbers_conflict
from roughcut.speech.alignment import tokenize_alignment_text
from roughcut.speech.postprocess import SubtitleSegmentationAnalysis

ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER = "transcript_fact_layer"
ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER = "canonical_transcript_layer"
ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER = "subtitle_projection_layer"
CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION = "20260607_alignment_v3"
SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION = "20260607_readability_v10"
SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION = "20260607_landscape_v2"


@dataclass(frozen=True)
class TranscriptFactWord:
    word: str
    start: float
    end: float
    raw_payload: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "word": self.word,
            "start": round(float(self.start), 3),
            "end": round(float(self.end), 3),
            "raw_payload": dict(self.raw_payload),
        }


@dataclass(frozen=True)
class TranscriptFactSegment:
    index: int
    start: float
    end: float
    text: str
    speaker: str | None
    words: tuple[TranscriptFactWord, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": int(self.index),
            "start": round(float(self.start), 3),
            "end": round(float(self.end), 3),
            "text": self.text,
            "speaker": self.speaker,
            "words": [word.as_dict() for word in self.words],
        }


@dataclass(frozen=True)
class TranscriptFactLayer:
    segments: tuple[TranscriptFactSegment, ...]

    def as_dict(self) -> dict[str, Any]:
        total_duration = 0.0
        if self.segments:
            total_duration = max(float(segment.end) for segment in self.segments)
        return {
            "layer": "transcript_fact",
            "segment_count": len(self.segments),
            "word_segment_count": sum(1 for segment in self.segments if segment.words),
            "duration": round(total_duration, 3),
            "segments": [segment.as_dict() for segment in self.segments],
        }


@dataclass(frozen=True)
class TranscriptSourceSegment:
    index: int
    source_kind: str
    source_id: str | None
    start: float
    end: float
    text_raw: str
    text_norm: str | None
    text_final: str | None
    speaker: str | None
    words: tuple[TranscriptFactWord, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": int(self.index),
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "start": round(float(self.start), 3),
            "end": round(float(self.end), 3),
            "text_raw": self.text_raw,
            "text_norm": self.text_norm,
            "text_final": self.text_final,
            "speaker": self.speaker,
            "word_count": len(self.words),
            "words": [word.as_dict() for word in self.words],
        }


@dataclass(frozen=True)
class CanonicalTranscriptWord:
    word: str
    start: float
    end: float
    alignment: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "word": self.word,
            "start": round(float(self.start), 3),
            "end": round(float(self.end), 3),
            "alignment": dict(self.alignment),
        }


@dataclass(frozen=True)
class CanonicalTranscriptSegment:
    index: int
    start: float
    end: float
    source_kind: str
    source_id: str | None
    text_raw: str
    text_canonical: str
    source_subtitle_index: int
    accepted_corrections: tuple[dict[str, Any], ...]
    pending_corrections: tuple[dict[str, Any], ...]
    words: tuple[CanonicalTranscriptWord, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": int(self.index),
            "start": round(float(self.start), 3),
            "end": round(float(self.end), 3),
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "text": self.text_canonical,
            "text_raw": self.text_raw,
            "text_canonical": self.text_canonical,
            "source_subtitle_index": int(self.source_subtitle_index),
            "accepted_corrections": [dict(item) for item in self.accepted_corrections],
            "pending_corrections": [dict(item) for item in self.pending_corrections],
            "words": [word.as_dict() for word in self.words],
        }


@dataclass(frozen=True)
class CanonicalTranscriptLayer:
    segments: tuple[CanonicalTranscriptSegment, ...]
    source_basis: str
    correction_metrics: dict[str, Any]
    alignment_engine_version: str = CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION

    def as_dict(self) -> dict[str, Any]:
        total_duration = 0.0
        if self.segments:
            total_duration = max(float(segment.end) for segment in self.segments)
        return {
            "layer": "canonical_transcript",
            "source_basis": self.source_basis,
            "segment_count": len(self.segments),
            "word_segment_count": sum(1 for segment in self.segments if segment.words),
            "word_count": sum(len(segment.words) for segment in self.segments),
            "duration": round(total_duration, 3),
            "correction_metrics": dict(self.correction_metrics),
            "alignment_engine_version": str(
                self.alignment_engine_version or CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION
            ),
            "segments": [segment.as_dict() for segment in self.segments],
        }


@dataclass(frozen=True)
class SubtitleProjectionEntry:
    index: int
    start: float
    end: float
    source_kind: str
    source_id: str | None
    text_raw: str
    text_norm: str | None
    text_final: str | None
    words: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "index": int(self.index),
            "start": round(float(self.start), 3),
            "end": round(float(self.end), 3),
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "text_raw": self.text_raw,
            "text_norm": self.text_norm,
            "text_final": self.text_final,
        }
        if self.words:
            payload["words"] = [dict(word) for word in self.words if isinstance(word, dict)]
        return payload


@dataclass(frozen=True)
class SubtitleProjectionLayer:
    entries: tuple[SubtitleProjectionEntry, ...]
    projection_basis: str
    transcript_layer: str
    split_profile: dict[str, Any]
    segmentation_analysis: dict[str, Any]
    boundary_refine: dict[str, Any]
    quality_report: dict[str, Any]
    segmentation_engine_version: str = SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION
    split_profile_version: str = SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION
    canonical_alignment_engine_version: str = ""

    def as_dict(self) -> dict[str, Any]:
        total_duration = 0.0
        if self.entries:
            total_duration = max(float(entry.end) for entry in self.entries)
        return {
            "layer": "subtitle_projection",
            "projection_kind": str(self.projection_basis or "display_baseline"),
            "transcript_layer": str(self.transcript_layer or "subtitle_projection"),
            "entry_count": len(self.entries),
            "duration": round(total_duration, 3),
            "split_profile": dict(self.split_profile),
            "segmentation_analysis": dict(self.segmentation_analysis),
            "boundary_refine": dict(self.boundary_refine),
            "quality_report": dict(self.quality_report),
            "segmentation_engine_version": str(
                self.segmentation_engine_version or SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION
            ),
            "split_profile_version": str(
                self.split_profile_version or SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION
            ),
            "canonical_alignment_engine_version": str(self.canonical_alignment_engine_version or ""),
            "entries": [entry.as_dict() for entry in self.entries],
        }


def canonical_transcript_data_is_current(canonical_data: dict[str, Any] | None) -> bool:
    return (
        str((canonical_data or {}).get("alignment_engine_version") or "").strip()
        == CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION
    )


def subtitle_projection_data_is_current(projection_data: dict[str, Any] | None) -> bool:
    if (
        str((projection_data or {}).get("segmentation_engine_version") or "").strip()
        != SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION
    ):
        return False
    if (
        str((projection_data or {}).get("split_profile_version") or "").strip()
        != SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION
    ):
        return False
    if str((projection_data or {}).get("transcript_layer") or "").strip() == "canonical_transcript":
        return (
            str((projection_data or {}).get("canonical_alignment_engine_version") or "").strip()
            == CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION
        )
    return True


def build_transcript_fact_layer(transcript_segments: list[Any]) -> TranscriptFactLayer:
    return TranscriptFactLayer(
        segments=tuple(
            _build_transcript_fact_segment(
                index=int(getattr(row, "segment_index", index) or index),
                start=float(getattr(row, "start_time", 0.0) or 0.0),
                end=float(getattr(row, "end_time", 0.0) or 0.0),
                text=str(getattr(row, "text", "") or ""),
                speaker=getattr(row, "speaker", None),
                raw_words=drop_redundant_synthetic_word_payloads(list(getattr(row, "words_json", None) or [])),
            )
            for index, row in enumerate(list(transcript_segments or []))
        )
    )


def build_transcript_fact_layer_from_result(result: TranscriptResult) -> TranscriptFactLayer:
    segments: list[TranscriptFactSegment] = []
    for index, segment in enumerate(list(getattr(result, "segments", None) or [])):
        segments.append(
            _build_transcript_fact_segment(
                index=int(getattr(segment, "index", index) or index),
                start=float(getattr(segment, "start", 0.0) or 0.0),
                end=float(getattr(segment, "end", 0.0) or 0.0),
                text=str(getattr(segment, "text", "") or ""),
                speaker=getattr(segment, "speaker", None),
                raw_words=[
                    {
                        "word": getattr(word, "word", ""),
                        "start": getattr(word, "start", 0.0),
                        "end": getattr(word, "end", 0.0),
                        **dict(getattr(word, "raw_payload", {}) or {}),
                    }
                    for word in list(getattr(segment, "words", None) or [])
                ],
            )
        )
    segments.sort(key=lambda item: (item.index, item.start, item.end))
    return TranscriptFactLayer(segments=tuple(segments))


def _build_transcript_fact_segment(
    *,
    index: int,
    start: float,
    end: float,
    text: str,
    speaker: str | None,
    raw_words: list[Any],
) -> TranscriptFactSegment:
    words = _build_transcript_fact_words(raw_words)
    return TranscriptFactSegment(
        index=index,
        start=start,
        end=end,
        text=text,
        speaker=speaker,
        words=tuple(words),
    )


def _build_transcript_fact_words(raw_words: list[Any]) -> list[TranscriptFactWord]:
    payloads: list[dict[str, Any]] = []
    for raw_word in list(raw_words or []):
        payload = _coerce_word_payload(raw_word)
        if payload is None:
            continue
        payloads.append(payload)
    words: list[TranscriptFactWord] = []
    for payload in drop_redundant_synthetic_word_payloads(payloads):
        words.append(
            TranscriptFactWord(
                word=str(payload["word"]),
                start=float(payload["start"]),
                end=float(payload["end"]),
                raw_payload=dict(payload),
            )
        )
    return words


def _coerce_word_payload(raw_word: Any) -> dict[str, Any] | None:
    if raw_word is None:
        return None

    if isinstance(raw_word, TranscriptFactWord):
        payload = dict(raw_word.raw_payload)
        payload.setdefault("word", raw_word.word)
        payload.setdefault("start", raw_word.start)
        payload.setdefault("end", raw_word.end)
    elif isinstance(raw_word, dict):
        payload = dict(raw_word)
    elif hasattr(raw_word, "__dict__"):
        payload = {key: value for key, value in vars(raw_word).items() if not key.startswith("_")}
    else:
        payload = {}

    word_text = str(payload.get("word") or getattr(raw_word, "word", "") or "").strip()
    if not word_text:
        return None

    try:
        word_start = float(payload.get("start") if payload.get("start") is not None else getattr(raw_word, "start", 0.0) or 0.0)
    except (TypeError, ValueError):
        word_start = 0.0
    try:
        word_end = float(payload.get("end") if payload.get("end") is not None else getattr(raw_word, "end", word_start) or word_start)
    except (TypeError, ValueError):
        word_end = word_start

    payload["word"] = word_text
    payload["start"] = max(0.0, word_start)
    payload["end"] = max(payload["start"], word_end)
    return payload


def _looks_like_transcript_segments(rows: list[Any] | None) -> bool:
    for row in list(rows or []):
        if any(hasattr(row, field) for field in ("text_raw", "text_norm", "text_final")):
            return False
    return any(hasattr(row, "text") for row in list(rows or []))


def _build_transcript_source_segment_from_subtitle_item(item: Any, *, index: int) -> TranscriptSourceSegment:
    raw_source_index = getattr(item, "item_index", None)
    if raw_source_index is None:
        raw_source_index = index
    source_id = str(getattr(item, "id", "") or "") or None
    text_raw = str(getattr(item, "text_raw", "") or "")
    text_norm = getattr(item, "text_norm", None)
    text_final = getattr(item, "text_final", None)
    start = float(getattr(item, "start_time", 0.0) or 0.0)
    end = float(getattr(item, "end_time", 0.0) or 0.0)
    words = tuple(
        _build_transcript_fact_words(
            list(getattr(item, "words", None) or getattr(item, "words_json", None) or [])
        )
    )
    return TranscriptSourceSegment(
        index=int(raw_source_index),
        source_kind="subtitle_item",
        source_id=source_id,
        start=start,
        end=end,
        text_raw=text_raw,
        text_norm=text_norm,
        text_final=text_final,
        speaker=None,
        words=words,
    )


def _build_transcript_source_segment_from_transcript_segment(segment: Any, *, index: int) -> TranscriptSourceSegment:
    raw_source_index = getattr(segment, "index", None)
    if raw_source_index is None:
        raw_source_index = getattr(segment, "segment_index", None)
    if raw_source_index is None:
        raw_source_index = index
    source_id = str(getattr(segment, "id", "") or getattr(segment, "segment_index", raw_source_index) or raw_source_index) or None
    text = str(getattr(segment, "text", "") or "")
    start = float(getattr(segment, "start", 0.0) or getattr(segment, "start_time", 0.0) or 0.0)
    end = float(getattr(segment, "end", 0.0) or getattr(segment, "end_time", 0.0) or 0.0)
    words = tuple(
        _build_transcript_fact_words(list(getattr(segment, "words", None) or getattr(segment, "words_json", None) or []))
    )
    return TranscriptSourceSegment(
        index=int(raw_source_index),
        source_kind="transcript_segment",
        source_id=source_id,
        start=start,
        end=end,
        text_raw=text,
        text_norm=getattr(segment, "text_norm", None),
        text_final=getattr(segment, "text_final", None),
        speaker=getattr(segment, "speaker", None),
        words=words,
    )


def _normalize_transcript_source_segments(
    subtitle_items: list[Any] | None = None,
    *,
    transcript_segments: list[Any] | None = None,
) -> tuple[TranscriptSourceSegment, ...]:
    if transcript_segments is None and subtitle_items is not None and _looks_like_transcript_segments(subtitle_items):
        transcript_segments = subtitle_items
        subtitle_items = None

    source_segments: list[TranscriptSourceSegment] = []
    if transcript_segments is not None:
        for order_index, segment in enumerate(
            sorted(
                list(transcript_segments or []),
                key=lambda current: (
                    float(getattr(current, "start", getattr(current, "start_time", 0.0)) or 0.0),
                    float(getattr(current, "end", getattr(current, "end_time", 0.0)) or 0.0),
                    int(getattr(current, "index", getattr(current, "segment_index", 0)) or 0),
                ),
            )
        ):
            source_segments.append(
                _build_transcript_source_segment_from_transcript_segment(segment, index=order_index)
            )
        return tuple(source_segments)

    for order_index, item in enumerate(
        sorted(
            list(subtitle_items or []),
            key=lambda current: (
                float(getattr(current, "start_time", 0.0) or 0.0),
                float(getattr(current, "end_time", 0.0) or 0.0),
                int(getattr(current, "item_index", 0) or 0),
            ),
        )
    ):
        source_segments.append(_build_transcript_source_segment_from_subtitle_item(item, index=order_index))
    return tuple(source_segments)


def _reference_words_for_source_segment(
    source_segment: TranscriptSourceSegment,
    *,
    reference_segments: list[Any] | None,
) -> tuple[dict[str, Any], ...]:
    if source_segment.words:
        return tuple(
            {
                "word": word.word,
                "start": word.start,
                "end": word.end,
                "source_index": source_segment.index,
                "source_word": word.word,
            }
            for word in source_segment.words
        )
    return _extract_reference_words_for_timespan(
        reference_segments,
        start=source_segment.start,
        end=source_segment.end,
    )


def _build_canonical_transcript_layer_from_source_segments(
    source_segments: tuple[TranscriptSourceSegment, ...],
    *,
    corrections: list[Any] | None = None,
    source_basis: str,
    reference_segments: list[Any] | None = None,
) -> CanonicalTranscriptLayer:
    corrections_by_source_id: dict[str, list[dict[str, Any]]] = {}
    accepted_count = 0
    pending_count = 0

    for correction in list(corrections or []):
        payload = _serialize_correction(correction)
        source_id = payload.pop("source_id", "")
        if not source_id:
            continue
        corrections_by_source_id.setdefault(source_id, []).append(payload)
        if payload["status"] == "accepted":
            accepted_count += 1
        elif payload["status"] == "pending":
            pending_count += 1

    segments: list[CanonicalTranscriptSegment] = []
    for source_segment in source_segments:
        source_id = source_segment.source_id or ""
        item_corrections = corrections_by_source_id.get(source_id, [])
        accepted_corrections = tuple(payload for payload in item_corrections if payload["status"] == "accepted")
        pending_corrections = tuple(payload for payload in item_corrections if payload["status"] == "pending")
        text_raw = str(source_segment.text_raw or "")
        canonical_text = str(source_segment.text_final or source_segment.text_norm or text_raw)
        canonical_text = _apply_accepted_corrections(canonical_text, accepted_corrections)
        canonical_words = _build_canonical_transcript_words(
            canonical_text,
            start=source_segment.start,
            end=source_segment.end,
            reference_words=_reference_words_for_source_segment(
                source_segment,
                reference_segments=reference_segments,
            ),
        )
        segments.append(
            CanonicalTranscriptSegment(
                index=int(source_segment.index),
                start=source_segment.start,
                end=source_segment.end,
                source_kind=source_segment.source_kind,
                source_id=source_segment.source_id,
                text_raw=text_raw,
                text_canonical=canonical_text,
                source_subtitle_index=int(source_segment.index),
                accepted_corrections=accepted_corrections,
                pending_corrections=pending_corrections,
                words=canonical_words,
            )
        )

    return CanonicalTranscriptLayer(
        segments=tuple(segments),
        source_basis=str(source_basis or "subtitle_projection_review"),
        correction_metrics={
            "accepted_correction_count": accepted_count,
            "pending_correction_count": pending_count,
        },
    )


def build_canonical_transcript_layer(
    subtitle_items: list[Any] | None = None,
    *,
    corrections: list[Any] | None = None,
    source_basis: str = "subtitle_projection_review",
    reference_segments: list[Any] | None = None,
    transcript_segments: list[Any] | None = None,
) -> CanonicalTranscriptLayer:
    source_segments = _normalize_transcript_source_segments(
        subtitle_items,
        transcript_segments=transcript_segments,
    )
    resolved_source_basis = str(source_basis or "subtitle_projection_review")
    if transcript_segments is not None or _looks_like_transcript_segments(subtitle_items):
        if resolved_source_basis == "subtitle_projection_review":
            resolved_source_basis = "transcript_first"
    return _build_canonical_transcript_layer_from_source_segments(
        source_segments,
        corrections=corrections,
        source_basis=resolved_source_basis,
        reference_segments=reference_segments,
    )


def build_canonical_transcript_layer_from_transcript_segments(
    transcript_segments: list[Any],
    *,
    corrections: list[Any] | None = None,
    source_basis: str = "transcript_first",
    reference_segments: list[Any] | None = None,
) -> CanonicalTranscriptLayer:
    return build_canonical_transcript_layer(
        None,
        corrections=corrections,
        source_basis=source_basis,
        reference_segments=reference_segments,
        transcript_segments=transcript_segments,
    )


def _serialize_correction(correction: Any) -> dict[str, Any]:
    human_decision = str(_correction_attr(correction, "human_decision") or "").strip().lower()
    auto_applied = bool(_correction_attr(correction, "auto_applied"))
    status = "accepted" if auto_applied or human_decision == "accepted" else "pending" if human_decision != "rejected" else "rejected"
    accepted = str(_correction_attr(correction, "human_override") or _correction_attr(correction, "suggested_span") or "").strip()
    original = str(_correction_attr(correction, "original_span") or "").strip()
    subtitle_item_id = str(_correction_attr(correction, "subtitle_item_id") or "").strip()
    transcript_segment_id = str(_correction_attr(correction, "transcript_segment_id") or "").strip()
    source_id = subtitle_item_id or transcript_segment_id
    return {
        "subtitle_item_id": subtitle_item_id,
        "transcript_segment_id": transcript_segment_id,
        "source_id": source_id,
        "source_kind": "subtitle_item" if subtitle_item_id else "transcript_segment" if transcript_segment_id else "",
        "original": original,
        "accepted": accepted,
        "status": status,
        "human_decision": human_decision or None,
        "human_override": str(_correction_attr(correction, "human_override") or "").strip() or None,
        "auto_applied": auto_applied,
        "source": str(_correction_attr(correction, "source") or "").strip(),
        "change_type": str(_correction_attr(correction, "change_type") or "").strip(),
        "confidence": _correction_attr(correction, "confidence"),
    }


def _correction_attr(correction: Any, key: str) -> Any:
    if isinstance(correction, dict):
        return correction.get(key)
    return getattr(correction, key, None)


def _apply_accepted_corrections(text: str, corrections: tuple[dict[str, Any], ...]) -> str:
    resolved = str(text or "")
    for correction in corrections:
        if str(correction.get("status") or "").strip().lower() != "accepted":
            continue
        if bool(correction.get("auto_applied")):
            continue
        human_decision = str(correction.get("human_decision") or "").strip().lower()
        if human_decision and human_decision != "accepted":
            continue
        original = str(correction.get("original") or correction.get("original_span") or "").strip()
        accepted = str(correction.get("accepted") or correction.get("suggested_span") or "").strip()
        if not original or not accepted or original == accepted:
            continue
        if model_numbers_conflict(original, accepted):
            continue
        if original not in resolved:
            continue
        resolved = resolved.replace(original, accepted, 1)
    return resolved


def _build_canonical_transcript_words(
    text: str,
    *,
    start: float,
    end: float,
    reference_words: tuple[dict[str, Any], ...] = (),
) -> tuple[CanonicalTranscriptWord, ...]:
    tokens = tokenize_alignment_text(text)
    if not tokens:
        return ()

    reference_tokens = _expand_reference_tokens(reference_words)
    baseline_words = _build_proportional_canonical_words(
        tokens,
        start=start,
        end=end,
        strategy="segment_span_proportional",
    )
    if not reference_tokens:
        return baseline_words

    words: list[CanonicalTranscriptWord | None] = _build_canonical_words_from_reference_units(
        tokens,
        reference_tokens=reference_tokens,
        baseline_words=baseline_words,
        segment_start=float(start),
        segment_end=float(end),
    )

    reference_span_start = max(float(start), min(float(token["start"]) for token in reference_tokens))
    reference_span_end = min(float(end), max(float(token["end"]) for token in reference_tokens))
    if reference_span_end < reference_span_start:
        reference_span_start = float(start)
        reference_span_end = float(end)

    missing_start = 0
    while missing_start < len(tokens):
        if words[missing_start] is not None:
            missing_start += 1
            continue
        missing_end = missing_start
        while missing_end < len(tokens) and words[missing_end] is None:
            missing_end += 1
        block_tokens = tokens[missing_start:missing_end]
        left_anchor = words[missing_start - 1].end if missing_start > 0 and words[missing_start - 1] is not None else reference_span_start
        right_anchor = words[missing_end].start if missing_end < len(words) and words[missing_end] is not None else reference_span_end
        block_start, block_end, strategy = _resolve_canonical_interpolation_span(
            baseline_words,
            missing_start=missing_start,
            missing_end=missing_end,
            left_anchor=float(left_anchor),
            right_anchor=float(right_anchor),
            segment_start=float(start),
            segment_end=float(end),
        )
        block_words = _build_proportional_canonical_words(
            block_tokens,
            start=block_start,
            end=block_end,
            strategy=strategy,
            token_offset=missing_start,
            token_count=len(tokens),
        )
        for offset, word in enumerate(block_words):
            words[missing_start + offset] = word
        missing_start = missing_end

    return _normalize_canonical_word_timeline(
        tuple(word for word in words if word is not None),
        segment_start=float(start),
        segment_end=float(end),
    )


def _build_canonical_words_from_reference_units(
    tokens: list[str],
    *,
    reference_tokens: tuple[dict[str, Any], ...],
    baseline_words: tuple[CanonicalTranscriptWord, ...],
    segment_start: float,
    segment_end: float,
) -> list[CanonicalTranscriptWord | None]:
    reference_units = _expand_reference_alignment_units(reference_tokens)
    target_units = _expand_target_alignment_units(tokens)
    if not reference_units or not target_units:
        return [None] * len(tokens)

    matches_by_token: dict[int, list[dict[str, Any]]] = {}
    matcher = difflib.SequenceMatcher(
        a=[str(unit["unit"]) for unit in reference_units],
        b=[str(unit["unit"]) for unit in target_units],
        autojunk=False,
    )
    for tag, source_start, source_end, target_start, target_end in matcher.get_opcodes():
        if tag != "equal":
            continue
        match_count = min(source_end - source_start, target_end - target_start)
        for offset in range(match_count):
            target_unit = target_units[target_start + offset]
            reference_unit = reference_units[source_start + offset]
            matches_by_token.setdefault(int(target_unit["token_index"]), []).append(reference_unit)

    words: list[CanonicalTranscriptWord | None] = [None] * len(tokens)
    for token_index, token in enumerate(tokens):
        token_unit_count = sum(1 for unit in target_units if int(unit["token_index"]) == token_index)
        reference_matches = matches_by_token.get(token_index, [])
        matched_word = _build_reference_matched_canonical_word(
            token,
            token_index=token_index,
            token_count=len(tokens),
            token_unit_count=token_unit_count,
            reference_matches=reference_matches,
            baseline_word=baseline_words[token_index],
            segment_start=segment_start,
            segment_end=segment_end,
        )
        if matched_word is not None:
            words[token_index] = matched_word
    return words


def _build_reference_matched_canonical_word(
    token: str,
    *,
    token_index: int,
    token_count: int,
    token_unit_count: int,
    reference_matches: list[dict[str, Any]],
    baseline_word: CanonicalTranscriptWord,
    segment_start: float,
    segment_end: float,
) -> CanonicalTranscriptWord | None:
    if token_unit_count <= 0 or not reference_matches:
        return None
    coverage = len(reference_matches) / max(1, token_unit_count)
    if not _canonical_token_match_is_reliable(token, coverage=coverage, token_unit_count=token_unit_count):
        return None
    starts = [float(item["start"]) for item in reference_matches]
    ends = [float(item["end"]) for item in reference_matches]
    match_start = max(segment_start, min(starts))
    match_end = min(segment_end, max(ends))
    if match_end <= match_start:
        return None
    if not _canonical_reference_match_is_temporally_plausible(
        match_start=match_start,
        match_end=match_end,
        baseline_word=baseline_word,
        segment_start=segment_start,
        segment_end=segment_end,
    ):
        return None
    first_reference = min(reference_matches, key=lambda item: (float(item["start"]), int(item["source_index"])))
    last_reference = max(reference_matches, key=lambda item: (float(item["end"]), int(item["source_index"])))
    return CanonicalTranscriptWord(
        word=token,
        start=round(match_start, 3),
        end=round(max(match_start, match_end), 3),
        alignment={
            "source": "canonical_realign",
            "strategy": "reference_unit_match",
            "token_index": token_index,
            "token_count": token_count,
            "coverage": round(float(coverage), 4),
            "reference_word": str(first_reference.get("source_word") or ""),
            "reference_token": str(first_reference.get("reference_token") or ""),
            "reference_index": int(first_reference.get("source_index") or 0),
            "reference_end_word": str(last_reference.get("source_word") or ""),
            "reference_end_index": int(last_reference.get("source_index") or 0),
        },
    )


_WEAK_CANONICAL_ANCHOR_TOKENS = {
    "的", "了", "呢", "吗", "嘛", "啊", "呀", "哦", "哈", "把", "给", "在", "向", "和", "与", "及",
    "就", "也", "还", "很", "都", "又", "才", "再", "并", "跟", "让", "被", "地", "得", "是", "有",
    "我", "你", "他", "她", "它", "这", "那", "会", "要", "能", "可", "先",
}


def _canonical_token_match_is_reliable(token: str, *, coverage: float, token_unit_count: int) -> bool:
    stripped = _strip_canonical_alignment_punctuation(token)
    if not stripped:
        return False
    if token_unit_count <= 1:
        return bool(re.search(r"[A-Za-z0-9]", stripped)) and coverage >= 1.0
    if stripped in _WEAK_CANONICAL_ANCHOR_TOKENS:
        return False
    if re.fullmatch(r"[A-Za-z0-9_\-./]+", stripped):
        return coverage >= 0.67
    return coverage >= 0.6


def _canonical_reference_match_is_temporally_plausible(
    *,
    match_start: float,
    match_end: float,
    baseline_word: CanonicalTranscriptWord,
    segment_start: float,
    segment_end: float,
) -> bool:
    segment_duration = max(0.001, float(segment_end) - float(segment_start))
    tolerance = min(6.0, max(1.25, segment_duration * 0.20))
    match_midpoint = (float(match_start) + float(match_end)) * 0.5
    baseline_midpoint = (float(baseline_word.start) + float(baseline_word.end)) * 0.5
    if abs(match_midpoint - baseline_midpoint) > tolerance:
        return False
    return True


def _resolve_canonical_interpolation_span(
    baseline_words: tuple[CanonicalTranscriptWord, ...],
    *,
    missing_start: int,
    missing_end: int,
    left_anchor: float,
    right_anchor: float,
    segment_start: float,
    segment_end: float,
) -> tuple[float, float, str]:
    baseline_start = float(baseline_words[missing_start].start)
    baseline_end = float(baseline_words[missing_end - 1].end)
    if right_anchor < left_anchor:
        return float(left_anchor), float(left_anchor), "reference_span_interpolate"
    anchor_duration = max(0.0, float(right_anchor) - float(left_anchor))
    baseline_duration = max(0.001, baseline_end - baseline_start)
    anchor_midpoint = (float(left_anchor) + float(right_anchor)) * 0.5
    baseline_midpoint = (baseline_start + baseline_end) * 0.5
    segment_duration = max(0.001, float(segment_end) - float(segment_start))
    if anchor_duration < baseline_duration * 0.45:
        return _clamp_canonical_baseline_span_to_anchors(
            baseline_start,
            baseline_end,
            left_anchor=left_anchor,
            right_anchor=right_anchor,
        )
    if abs(anchor_midpoint - baseline_midpoint) > min(6.0, max(1.5, segment_duration * 0.22)):
        return _clamp_canonical_baseline_span_to_anchors(
            baseline_start,
            baseline_end,
            left_anchor=left_anchor,
            right_anchor=right_anchor,
        )
    return float(left_anchor), float(right_anchor), "reference_span_interpolate"


def _clamp_canonical_baseline_span_to_anchors(
    baseline_start: float,
    baseline_end: float,
    *,
    left_anchor: float,
    right_anchor: float,
) -> tuple[float, float, str]:
    resolved_start = float(baseline_start)
    resolved_end = float(baseline_end)
    if right_anchor <= left_anchor:
        anchor = float(left_anchor)
        return anchor, anchor, "reference_span_interpolate"
    if resolved_end <= left_anchor and right_anchor > left_anchor:
        return float(left_anchor), float(right_anchor), "reference_span_interpolate"
    if resolved_start >= right_anchor and right_anchor > left_anchor:
        return float(left_anchor), float(right_anchor), "reference_span_interpolate"
    if left_anchor <= resolved_end and resolved_start < left_anchor:
        resolved_start = float(left_anchor)
    if right_anchor >= resolved_start and resolved_end > right_anchor:
        resolved_end = float(right_anchor)
    if resolved_end <= resolved_start and right_anchor > left_anchor:
        return float(left_anchor), float(right_anchor), "reference_span_interpolate"
    return resolved_start, max(resolved_start, resolved_end), "segment_span_proportional"


_CANONICAL_MIN_WORD_DURATION_SEC = 0.04


def _normalize_canonical_word_timeline(
    words: tuple[CanonicalTranscriptWord, ...],
    *,
    segment_start: float,
    segment_end: float,
) -> tuple[CanonicalTranscriptWord, ...]:
    if not words:
        return ()
    segment_start = float(segment_start)
    segment_end = max(segment_start, float(segment_end))
    segment_duration = max(0.0, segment_end - segment_start)
    min_duration = min(_CANONICAL_MIN_WORD_DURATION_SEC, segment_duration / max(len(words) * 2, 1))
    cursor = segment_start
    normalized: list[CanonicalTranscriptWord] = []
    for word in words:
        original_start = float(word.start)
        original_end = float(word.end)
        start = max(segment_start, original_start, cursor)
        end = max(start, original_end)
        if min_duration > 0 and end - start < min_duration:
            end = start + min_duration
        if end > segment_end:
            end = segment_end
            if min_duration > 0 and end - start < min_duration:
                start = max(cursor, end - min_duration)
                start = min(start, end)
        start = round(max(segment_start, min(start, segment_end)), 3)
        end = round(max(start, min(end, segment_end)), 3)
        alignment = dict(word.alignment)
        if abs(start - original_start) > 0.0005 or abs(end - original_end) > 0.0005:
            alignment["timing_normalized"] = True
        normalized.append(
            CanonicalTranscriptWord(
                word=word.word,
                start=start,
                end=end,
                alignment=alignment,
            )
        )
        cursor = end
    return tuple(normalized)


def _build_proportional_canonical_words(
    tokens: list[str],
    *,
    start: float,
    end: float,
    strategy: str,
    token_offset: int = 0,
    token_count: int | None = None,
) -> tuple[CanonicalTranscriptWord, ...]:
    duration = max(0.0, float(end) - float(start))
    total_weight = sum(_canonical_word_weight(token) for token in tokens) or float(len(tokens) or 1)
    cursor = float(start)
    words: list[CanonicalTranscriptWord] = []
    resolved_count = int(token_count or len(tokens))
    for index, token in enumerate(tokens):
        weight = _canonical_word_weight(token)
        slice_duration = duration * weight / total_weight if duration > 0 else 0.0
        next_end = float(end) if index == len(tokens) - 1 else cursor + slice_duration
        words.append(
            CanonicalTranscriptWord(
                word=token,
                start=round(cursor, 3),
                end=round(max(cursor, next_end), 3),
                alignment={
                    "source": "canonical_realign",
                    "strategy": strategy,
                    "token_index": token_offset + index,
                    "token_count": resolved_count,
                },
            )
        )
        cursor = next_end
    return tuple(words)


def _extract_reference_words_for_timespan(
    reference_segments: list[Any] | None,
    *,
    start: float,
    end: float,
) -> tuple[dict[str, Any], ...]:
    if not reference_segments:
        return ()

    clipped_words: list[dict[str, Any]] = []
    segment_start = float(start)
    segment_end = float(end)
    for segment in list(reference_segments or []):
        raw_words = drop_redundant_synthetic_word_payloads(
            list(getattr(segment, "words_json", None) or getattr(segment, "words", None) or [])
        )
        for source_index, raw_word in enumerate(raw_words):
            payload = _coerce_word_payload(raw_word)
            if payload is None:
                continue
            word = str(payload.get("word") or "").strip()
            raw_start = payload.get("start")
            raw_end = payload.get("end")
            word_start = float(segment_start if raw_start is None else raw_start)
            word_end = float(word_start if raw_end is None else raw_end)
            word_end = max(word_start, word_end)
            if word_end <= segment_start or word_start >= segment_end:
                continue
            clipped_start = max(segment_start, word_start)
            clipped_end = min(segment_end, word_end)
            clipped_words.append(
                {
                    "word": word,
                    "start": round(clipped_start, 3),
                    "end": round(max(clipped_start, clipped_end), 3),
                    "source_index": source_index,
                    "source_word": word,
                }
            )
    clipped_words.sort(key=lambda item: (float(item["start"]), float(item["end"]), int(item["source_index"])))
    return tuple(clipped_words)


def _build_segmentation_adapters_from_transcript_segments(transcript_segments: list[Any]) -> list[SimpleNamespace]:
    adapters: list[SimpleNamespace] = []
    for index, segment in enumerate(list(transcript_segments or [])):
        start = float(getattr(segment, "start_time", getattr(segment, "start", 0.0)) or 0.0)
        end = float(getattr(segment, "end_time", getattr(segment, "end", start)) or start)
        raw_words = drop_redundant_synthetic_word_payloads(
            list(getattr(segment, "words_json", None) or getattr(segment, "words", None) or [])
        )
        words_json = [word.as_dict() for word in _build_transcript_fact_words(raw_words)]
        adapters.append(
            SimpleNamespace(
                segment_index=int(getattr(segment, "segment_index", getattr(segment, "index", index)) or index),
                start_time=start,
                end_time=max(start, end),
                text=str(getattr(segment, "text", "") or ""),
                words_json=words_json,
            )
        )
    return adapters


def _build_projection_entries_from_transcript_words(
    transcript_segments: list[Any],
    *,
    max_chars: int,
    max_duration: float,
) -> tuple[SubtitleProjectionEntry, ...]:
    from roughcut.speech.subtitle_segmentation import segment_subtitles

    segmentation_segments = _build_segmentation_adapters_from_transcript_segments(transcript_segments)
    if not segmentation_segments:
        return ()
    result = segment_subtitles(
        segmentation_segments,
        max_chars=max_chars,
        max_duration=max_duration,
    )
    return tuple(
        SubtitleProjectionEntry(
            index=index,
            start=float(entry.start),
            end=float(entry.end),
            source_kind="transcript_word_projection",
            source_id=None,
            text_raw=str(entry.text_raw or ""),
            text_norm=str(entry.text_norm or ""),
            text_final=str(entry.text_raw or ""),
            words=tuple(dict(word) for word in tuple(entry.words or ()) if isinstance(word, dict)),
        )
        for index, entry in enumerate(result.entries)
    )


def _expand_reference_tokens(reference_words: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    tokens: list[dict[str, Any]] = []
    for reference in reference_words:
        source_word = str(reference.get("word") or "").strip()
        if not source_word:
            continue
        subtokens = tokenize_alignment_text(source_word)
        if not subtokens:
            subtokens = [source_word]
        token_words = _build_proportional_canonical_words(
            subtokens,
            start=float(reference.get("start") or 0.0),
            end=float(reference.get("end") or 0.0),
            strategy="reference_word_expand",
            token_count=len(subtokens),
        )
        for token_index, token_word in enumerate(token_words):
            tokens.append(
                {
                    "word": token_word.word,
                    "start": token_word.start,
                    "end": token_word.end,
                    "source_word": source_word,
                    "source_index": int(reference.get("source_index") or 0),
                    "subtoken_index": token_index,
                }
            )
    return tuple(tokens)


def _expand_reference_alignment_units(reference_tokens: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for reference in reference_tokens:
        text_units = _canonical_alignment_units(str(reference.get("word") or ""))
        if not text_units:
            continue
        start = float(reference.get("start") or 0.0)
        end = max(start, float(reference.get("end", start) or start))
        duration = max(0.0, end - start)
        unit_span = duration / max(len(text_units), 1)
        for unit_index, unit in enumerate(text_units):
            unit_start = start + unit_index * unit_span
            unit_end = end if unit_index == len(text_units) - 1 else unit_start + unit_span
            units.append(
                {
                    "unit": unit,
                    "start": round(unit_start, 3),
                    "end": round(max(unit_start, unit_end), 3),
                    "source_word": str(reference.get("source_word") or reference.get("word") or ""),
                    "reference_token": str(reference.get("word") or ""),
                    "source_index": int(reference.get("source_index") or 0),
                }
            )
    return units


def _expand_target_alignment_units(tokens: list[str]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for token_index, token in enumerate(tokens):
        for unit_index, unit in enumerate(_canonical_alignment_units(token)):
            units.append(
                {
                    "unit": unit,
                    "token_index": token_index,
                    "unit_index": unit_index,
                }
            )
    return units


def _canonical_alignment_units(text: str) -> list[str]:
    compact = _strip_canonical_alignment_punctuation(text)
    if not compact:
        return []
    return [char.lower() for char in compact if char.strip()]


def _strip_canonical_alignment_punctuation(text: str) -> str:
    return re.sub(r"[\s，。！？!?；;：:,、（）()[]【】{}\"'《》<>]+", "", str(text or "").strip())


def _canonical_word_weight(token: str) -> float:
    value = str(token or "")
    if not value:
        return 0.0
    if all(char in "，。！？!?；;：:,、（）()[]【】{}\"'《》<>" for char in value):
        return 0.35
    return max(0.8, float(len(value)))


def build_subtitle_projection_layer(
    subtitle_items: list[SubtitleItem] | None = None,
    *,
    segmentation_analysis: SubtitleSegmentationAnalysis | dict[str, Any],
    split_profile: dict[str, Any],
    boundary_refine: dict[str, Any] | None,
    quality_report: dict[str, Any] | None,
    projection_basis: str = "display_baseline",
    transcript_layer: str = "subtitle_projection",
    transcript_segments: list[Any] | None = None,
) -> SubtitleProjectionLayer:
    analysis_payload = (
        segmentation_analysis.as_dict()
        if hasattr(segmentation_analysis, "as_dict")
        else dict(segmentation_analysis or {})
    )
    source_segments = _normalize_transcript_source_segments(
        subtitle_items,
        transcript_segments=transcript_segments,
    )
    resolved_projection_basis = str(projection_basis or "display_baseline")
    resolved_transcript_layer = str(transcript_layer or "subtitle_projection")
    if transcript_segments is not None or _looks_like_transcript_segments(subtitle_items):
        if resolved_projection_basis == "display_baseline":
            resolved_projection_basis = "transcript_first"
        if resolved_transcript_layer == "subtitle_projection":
            resolved_transcript_layer = "transcript_projection"
    entries = ()
    if transcript_segments is not None:
        entries = _build_projection_entries_from_transcript_words(
            transcript_segments,
            max_chars=int((split_profile or {}).get("max_chars") or 30),
            max_duration=float((split_profile or {}).get("max_duration") or 5.0),
        )
    if not entries:
        entries = tuple(
            SubtitleProjectionEntry(
                index=int(source.index),
                start=source.start,
                end=source.end,
                source_kind=source.source_kind,
                source_id=source.source_id,
                text_raw=source.text_raw,
                text_norm=source.text_norm,
                text_final=source.text_final,
                words=tuple(
                    word.as_dict() if hasattr(word, "as_dict") else dict(word)
                    for word in tuple(source.words or ())
                    if hasattr(word, "as_dict") or isinstance(word, dict)
                ),
            )
            for source in source_segments
        )
    return SubtitleProjectionLayer(
        entries=entries,
        projection_basis=resolved_projection_basis,
        transcript_layer=resolved_transcript_layer,
        split_profile=dict(split_profile or {}),
        segmentation_analysis=analysis_payload,
        boundary_refine=dict(boundary_refine or {}),
        quality_report=dict(quality_report or {}),
        segmentation_engine_version=SUBTITLE_PROJECTION_SEGMENTATION_ENGINE_VERSION,
        split_profile_version=SUBTITLE_PROJECTION_SPLIT_PROFILE_VERSION,
        canonical_alignment_engine_version=(
            CANONICAL_TRANSCRIPT_ALIGNMENT_ENGINE_VERSION
            if resolved_transcript_layer == "canonical_transcript"
            else ""
        ),
    )


def build_subtitle_projection_layer_from_transcript_segments(
    transcript_segments: list[Any],
    *,
    segmentation_analysis: SubtitleSegmentationAnalysis | dict[str, Any],
    split_profile: dict[str, Any],
    boundary_refine: dict[str, Any] | None,
    quality_report: dict[str, Any] | None,
    projection_basis: str = "transcript_first",
    transcript_layer: str = "transcript_projection",
) -> SubtitleProjectionLayer:
    return build_subtitle_projection_layer(
        None,
        segmentation_analysis=segmentation_analysis,
        split_profile=split_profile,
        boundary_refine=boundary_refine,
        quality_report=quality_report,
        projection_basis=projection_basis,
        transcript_layer=transcript_layer,
        transcript_segments=transcript_segments,
    )


def build_subtitle_architecture_artifacts(
    *,
    job_id: Any,
    step_id: Any,
    transcript_fact_layer: TranscriptFactLayer,
    canonical_transcript_layer: CanonicalTranscriptLayer | None,
    subtitle_projection_layer: SubtitleProjectionLayer,
) -> list[Artifact]:
    artifacts = [
        Artifact(
            job_id=job_id,
            step_id=step_id,
            artifact_type=ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER,
            data_json=transcript_fact_layer.as_dict(),
        ),
    ]
    if canonical_transcript_layer is not None:
        artifacts.append(
            Artifact(
                job_id=job_id,
                step_id=step_id,
                artifact_type=ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
                data_json=canonical_transcript_layer.as_dict(),
            )
        )
    artifacts.append(
        Artifact(
            job_id=job_id,
            step_id=step_id,
            artifact_type=ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,
            data_json=subtitle_projection_layer.as_dict(),
        )
    )
    return artifacts
