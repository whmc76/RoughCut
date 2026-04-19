from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Any

from roughcut.db.models import Artifact, SubtitleItem
from roughcut.providers.transcription.base import TranscriptResult
from roughcut.speech.alignment import tokenize_alignment_text
from roughcut.speech.postprocess import SubtitleSegmentationAnalysis

ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER = "transcript_fact_layer"
ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER = "canonical_transcript_layer"
ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER = "subtitle_projection_layer"


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

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": int(self.index),
            "start": round(float(self.start), 3),
            "end": round(float(self.end), 3),
            "source_kind": self.source_kind,
            "source_id": self.source_id,
            "text_raw": self.text_raw,
            "text_norm": self.text_norm,
            "text_final": self.text_final,
        }


@dataclass(frozen=True)
class SubtitleProjectionLayer:
    entries: tuple[SubtitleProjectionEntry, ...]
    projection_basis: str
    transcript_layer: str
    split_profile: dict[str, Any]
    segmentation_analysis: dict[str, Any]
    boundary_refine: dict[str, Any]
    quality_report: dict[str, Any]

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
            "entries": [entry.as_dict() for entry in self.entries],
        }


def build_transcript_fact_layer(transcript_segments: list[Any]) -> TranscriptFactLayer:
    return TranscriptFactLayer(
        segments=tuple(
            _build_transcript_fact_segment(
                index=int(getattr(row, "segment_index", index) or index),
                start=float(getattr(row, "start_time", 0.0) or 0.0),
                end=float(getattr(row, "end_time", 0.0) or 0.0),
                text=str(getattr(row, "text", "") or ""),
                speaker=getattr(row, "speaker", None),
                raw_words=list(getattr(row, "words_json", None) or []),
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
    words: list[TranscriptFactWord] = []
    for raw_word in list(raw_words or []):
        payload = _coerce_word_payload(raw_word)
        if payload is None:
            continue
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
        words=(),
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
        text_raw = str(source_segment.text_norm or source_segment.text_raw or "")
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
        "source": str(_correction_attr(correction, "source") or "").strip(),
        "change_type": str(_correction_attr(correction, "change_type") or "").strip(),
        "confidence": _correction_attr(correction, "confidence"),
    }


def _correction_attr(correction: Any, key: str) -> Any:
    if isinstance(correction, dict):
        return correction.get(key)
    return getattr(correction, key, None)


def _apply_accepted_corrections(text: str, corrections: tuple[dict[str, Any], ...]) -> str:
    result = str(text or "")
    for correction in corrections:
        original = str(correction.get("original") or "").strip()
        accepted = str(correction.get("accepted") or "").strip()
        if not original or not accepted or original == accepted:
            continue
        if original in result:
            result = result.replace(original, accepted, 1)
    return result


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
    if not reference_tokens:
        return _build_proportional_canonical_words(
            tokens,
            start=start,
            end=end,
            strategy="segment_span_proportional",
        )

    words: list[CanonicalTranscriptWord | None] = [None] * len(tokens)
    reference_text = [token["word"] for token in reference_tokens]
    matcher = difflib.SequenceMatcher(a=reference_text, b=tokens, autojunk=False)
    for tag, source_start, source_end, target_start, target_end in matcher.get_opcodes():
        if tag == "delete":
            continue
        source_count = source_end - source_start
        target_count = target_end - target_start
        if source_count <= 0 or target_count <= 0 or source_count != target_count:
            continue
        strategy = "reference_word_match" if tag == "equal" else "reference_word_replace"
        for offset in range(target_count):
            reference_token = reference_tokens[source_start + offset]
            words[target_start + offset] = CanonicalTranscriptWord(
                word=tokens[target_start + offset],
                start=round(float(reference_token["start"]), 3),
                end=round(float(reference_token["end"]), 3),
                alignment={
                    "source": "canonical_realign",
                    "strategy": strategy,
                    "token_index": target_start + offset,
                    "token_count": len(tokens),
                    "reference_word": reference_token["source_word"],
                    "reference_token": reference_token["word"],
                    "reference_index": int(reference_token["source_index"]),
                },
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
        if right_anchor < left_anchor:
            right_anchor = left_anchor
        block_words = _build_proportional_canonical_words(
            block_tokens,
            start=left_anchor,
            end=right_anchor,
            strategy="reference_span_interpolate",
            token_offset=missing_start,
            token_count=len(tokens),
        )
        for offset, word in enumerate(block_words):
            words[missing_start + offset] = word
        missing_start = missing_end

    return tuple(word for word in words if word is not None)


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
        raw_words = list(getattr(segment, "words_json", None) or getattr(segment, "words", None) or [])
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
