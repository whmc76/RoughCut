from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from roughcut.media.subtitles import remap_subtitles_to_timeline

@dataclass(frozen=True)
class SubtitleProjectionValidationResult:
    subtitles: list[dict[str, Any]]
    mismatch_detected: bool
    fallback_used: bool


@dataclass(frozen=True)
class TranscriptProjectionSpeechUnit:
    unit_type: str
    start: float
    end: float
    text: str
    source_index: int
    source_kind: str
    trusted: bool

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "type": self.unit_type,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "duration_sec": round(self.duration, 3),
            "source_index": self.source_index,
            "source_kind": self.source_kind,
            "trusted": self.trusted,
        }
        if self.text:
            payload["text"] = self.text
        return payload


SYNTHETIC_TRANSCRIPT_ALIGNMENT_SOURCES = {
    "canonical_realign",
    "canonical_segment_fallback",
    "postprocess_text_fallback",
    "provider_missing",
    "roughcut_synthesized",
    "segment_only",
    "synthetic",
}


def subtitle_projection_display_text(item: dict[str, Any]) -> str:
    return str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or item.get("text") or "")


def compact_projection_text(value: object) -> str:
    return re.sub(r"[\s，,。.!！?？、；;：:“”\"'‘’（）()[\]【】]+", "", str(value or ""))


def projection_text_common_subsequence_ratio(left: str, right: str) -> float:
    left_chars = list(left)
    right_chars = list(right)
    if not left_chars or not right_chars:
        return 0.0
    previous = [0] * (len(right_chars) + 1)
    for left_char in left_chars:
        diagonal = 0
        for right_index, right_char in enumerate(right_chars):
            saved = previous[right_index + 1]
            previous[right_index + 1] = (
                diagonal + 1
                if left_char == right_char
                else max(previous[right_index + 1], previous[right_index])
            )
            diagonal = saved
    return previous[-1] / max(len(left_chars), len(right_chars))


def source_ranges_for_output_range(
    output_start: float,
    output_end: float,
    keep_segments: list[dict[str, Any]],
) -> list[tuple[float, float]]:
    start = min(float(output_start or 0.0), float(output_end or 0.0))
    end = max(float(output_start or 0.0), float(output_end or 0.0))
    ranges: list[tuple[float, float]] = []
    output_cursor = 0.0
    for segment in sorted(keep_segments, key=lambda item: float(item.get("start", 0.0) or 0.0)):
        source_start = float(segment.get("start", 0.0) or 0.0)
        source_end = float(segment.get("end", source_start) or source_start)
        if source_end <= source_start:
            continue
        segment_output_start = output_cursor
        segment_output_end = output_cursor + (source_end - source_start)
        output_cursor = segment_output_end
        overlap_start = max(start, segment_output_start)
        overlap_end = min(end, segment_output_end)
        if overlap_end <= overlap_start + 0.001:
            continue
        ranges.append((
            source_start + (overlap_start - segment_output_start),
            source_start + (overlap_end - segment_output_start),
        ))
    return ranges


def validate_projected_subtitles_against_transcript(
    projected_subtitles: list[dict[str, Any]],
    *,
    transcript_segments: list[dict[str, Any]],
    keep_segments: list[dict[str, Any]],
    min_coverage_ratio: float = 0.35,
    min_overlap_sec: float = 0.06,
) -> dict[str, Any]:
    speech_units = _build_transcript_projection_speech_units(transcript_segments)
    keep_ranges = _normalize_time_ranges(keep_segments)
    projected_source_ranges = _projected_subtitle_source_ranges(projected_subtitles, keep_segments)

    blocking: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    kept_unit_count = 0
    covered_unit_count = 0

    for unit in speech_units:
        kept_overlap = _range_overlap(unit.start, unit.end, keep_ranges)
        if not _has_sufficient_overlap(
            overlap=kept_overlap,
            duration=unit.duration,
            min_coverage_ratio=min_coverage_ratio,
            min_overlap_sec=min_overlap_sec,
        ):
            continue
        kept_unit_count += 1
        subtitle_overlap = _range_overlap(unit.start, unit.end, projected_source_ranges)
        if _has_sufficient_overlap(
            overlap=subtitle_overlap,
            duration=unit.duration,
            min_coverage_ratio=min_coverage_ratio,
            min_overlap_sec=min_overlap_sec,
        ):
            covered_unit_count += 1
            continue

        payload = {
            **unit.as_dict(),
            "issue": (
                "kept_transcript_speech_missing_projected_subtitle"
                if unit.trusted
                else "synthetic_timing_speech_missing_projected_subtitle"
            ),
            "kept_overlap_sec": round(kept_overlap, 3),
            "subtitle_overlap_sec": round(subtitle_overlap, 3),
        }
        if unit.trusted:
            blocking.append(payload)
        else:
            warnings.append(payload)

    issue_counts: dict[str, int] = {}
    for item in [*blocking, *warnings]:
        issue = str(item.get("issue") or "")
        if issue:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1

    return {
        "validation_version": "source_transcript_projection_v1",
        "blocking": bool(blocking),
        "blocking_issue_count": len(blocking),
        "warning_issue_count": len(warnings),
        "issue_counts": issue_counts,
        "speech_unit_count": len(speech_units),
        "kept_speech_unit_count": kept_unit_count,
        "covered_speech_unit_count": covered_unit_count,
        "missing_speech_unit_count": len(blocking) + len(warnings),
        "blocking_examples": blocking[:12],
        "warning_examples": warnings[:12],
    }


def annotate_projected_subtitle_sources(
    projected_subtitles: list[dict[str, Any]],
    source_subtitles: list[dict[str, Any]],
    keep_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not projected_subtitles or not source_subtitles or not keep_segments:
        return projected_subtitles
    source_rows: list[dict[str, Any]] = []
    for fallback_index, item in enumerate(source_subtitles):
        try:
            source_index = int(item.get("source_index", item.get("index", fallback_index)) or fallback_index)
            start_time = float(item.get("start_time", item.get("start", 0.0)) or 0.0)
            end_time = float(item.get("end_time", item.get("end", start_time)) or start_time)
        except (TypeError, ValueError):
            continue
        if end_time <= start_time:
            continue
        source_rows.append({"index": source_index, "start": start_time, "end": end_time})
    if not source_rows:
        return projected_subtitles

    annotated: list[dict[str, Any]] = []
    for item in projected_subtitles:
        payload = dict(item)
        output_start = float(payload.get("start_time", payload.get("start", 0.0)) or 0.0)
        output_end = float(payload.get("end_time", payload.get("end", output_start)) or output_start)
        source_ranges = source_ranges_for_output_range(output_start, output_end, keep_segments)
        overlap_by_source: dict[int, float] = {}
        for range_start, range_end in source_ranges:
            for source in source_rows:
                overlap = min(range_end, source["end"]) - max(range_start, source["start"])
                if overlap <= 0.001:
                    continue
                source_index = int(source["index"])
                overlap_by_source[source_index] = overlap_by_source.get(source_index, 0.0) + overlap
        if overlap_by_source:
            source_indexes = [
                source_index
                for source_index, _overlap in sorted(
                    overlap_by_source.items(),
                    key=lambda pair: (-pair[1], pair[0]),
                )
            ]
            payload["source_index"] = source_indexes[0]
            payload["source_indexes"] = source_indexes
        annotated.append(payload)
    return annotated


def projection_has_source_text_mismatch(
    projected_subtitles: list[dict[str, Any]],
    source_subtitles: list[dict[str, Any]],
) -> bool:
    if not projected_subtitles or not source_subtitles:
        return False

    source_by_index: dict[int, dict[str, Any]] = {}
    for fallback_index, item in enumerate(source_subtitles):
        try:
            source_index = int(item.get("source_index", item.get("index", fallback_index)) or fallback_index)
        except (TypeError, ValueError):
            continue
        source_by_index[source_index] = item

    severe_mismatches = 0
    checked = 0
    for item in projected_subtitles:
        raw_source_indexes = item.get("source_indexes")
        if isinstance(raw_source_indexes, list):
            source_indexes = []
            for raw_index in raw_source_indexes[:3]:
                try:
                    source_indexes.append(int(raw_index))
                except (TypeError, ValueError):
                    continue
        else:
            source_indexes = []
        if not source_indexes:
            try:
                source_indexes = [int(item.get("source_index", item.get("index", 0)) or 0)]
            except (TypeError, ValueError):
                source_indexes = []

        source_text = "".join(
            subtitle_projection_display_text(source_by_index[source_index])
            for source_index in source_indexes
            if source_index in source_by_index
        )
        projected_key = compact_projection_text(subtitle_projection_display_text(item))
        source_key = compact_projection_text(source_text)
        if len(source_key) < 4 or len(projected_key) < 4:
            continue
        checked += 1
        if len(source_key) > len(projected_key) and source_key.find(projected_key) >= 0:
            continue
        similarity = projection_text_common_subsequence_ratio(source_key, projected_key)
        length_ratio = max(len(source_key), len(projected_key)) / max(1, min(len(source_key), len(projected_key)))
        if similarity < 0.32 and length_ratio >= 1.8:
            severe_mismatches += 1
            if severe_mismatches >= 1:
                return True
    return checked >= 4 and severe_mismatches / checked >= 0.25


def _source_indexes_for_projection_item(item: dict[str, Any]) -> set[int]:
    indexes: set[int] = set()
    raw_indexes = item.get("source_indexes")
    if isinstance(raw_indexes, list):
        for raw_index in raw_indexes:
            try:
                indexes.add(int(raw_index))
            except (TypeError, ValueError):
                continue
    try:
        indexes.add(int(item.get("source_index", item.get("index", 0)) or 0))
    except (TypeError, ValueError):
        pass
    return indexes


def _subtitle_output_overlap(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_start = float(left.get("start_time", left.get("start", 0.0)) or 0.0)
    left_end = float(left.get("end_time", left.get("end", left_start)) or left_start)
    right_start = float(right.get("start_time", right.get("start", 0.0)) or 0.0)
    right_end = float(right.get("end_time", right.get("end", right_start)) or right_start)
    return min(left_end, right_end) - max(left_start, right_start)


def _repair_projection_text_drift_from_span_fallback(
    projected_subtitles: list[dict[str, Any]],
    *,
    source_subtitles: list[dict[str, Any]],
    keep_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not projected_subtitles or not source_subtitles or not keep_segments:
        return projected_subtitles

    replacements_by_position: dict[int, list[dict[str, Any]]] = {}
    for index, projected_item in enumerate(projected_subtitles):
        projected_key = compact_projection_text(subtitle_projection_display_text(projected_item))
        if len(projected_key) < 6:
            continue
        local_fallback = _local_span_fallback_for_projected_item(
            projected_item,
            source_subtitles=source_subtitles,
            keep_segments=keep_segments,
        )
        if not local_fallback:
            continue
        fallback_key = compact_projection_text("".join(subtitle_projection_display_text(item) for item in local_fallback))
        if len(fallback_key) < 4 or projected_key == fallback_key:
            continue
        length_ratio = max(len(projected_key), len(fallback_key)) / max(1, min(len(projected_key), len(fallback_key)))
        length_delta = abs(len(projected_key) - len(fallback_key))
        similarity = projection_text_common_subsequence_ratio(fallback_key, projected_key)
        if similarity < 0.72:
            continue
        if length_ratio < 1.12 and length_delta < 2:
            continue
        projected_sources = _source_indexes_for_projection_item(projected_item)
        fallback_sources = set().union(*(_source_indexes_for_projection_item(item) for item in local_fallback))
        if projected_sources and fallback_sources and not projected_sources.intersection(fallback_sources):
            continue
        replacements_by_position[index] = sorted(
            [dict(item) for item in local_fallback],
            key=lambda item: float(item.get("start_time", 0.0) or 0.0),
        )

    if not replacements_by_position:
        return projected_subtitles

    repaired: list[dict[str, Any]] = []
    for index, item in enumerate(projected_subtitles):
        replacements = replacements_by_position.get(index)
        if replacements is None:
            repaired.append(item)
            continue
        repaired.extend(replacements)
    return sorted(repaired, key=lambda item: (float(item.get("start_time", 0.0) or 0.0), float(item.get("end_time", 0.0) or 0.0)))


def _local_span_fallback_for_projected_item(
    projected_item: dict[str, Any],
    *,
    source_subtitles: list[dict[str, Any]],
    keep_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output_start = float(projected_item.get("start_time", projected_item.get("start", 0.0)) or 0.0)
    output_end = float(projected_item.get("end_time", projected_item.get("end", output_start)) or output_start)
    if output_end <= output_start + 0.001:
        return []
    source_ranges = source_ranges_for_output_range(output_start, output_end, keep_segments)
    if not source_ranges:
        return []

    projected_sources = _source_indexes_for_projection_item(projected_item)
    relevant_sources: list[dict[str, Any]] = []
    for fallback_index, source in enumerate(source_subtitles):
        try:
            source_index = int(source.get("source_index", source.get("index", fallback_index)) or fallback_index)
            source_start = float(source.get("start_time", source.get("start", 0.0)) or 0.0)
            source_end = float(source.get("end_time", source.get("end", source_start)) or source_start)
        except (TypeError, ValueError):
            continue
        if source_end <= source_start:
            continue
        if projected_sources and source_index not in projected_sources:
            continue
        if not any(min(range_end, source_end) - max(range_start, source_start) > 0.001 for range_start, range_end in source_ranges):
            continue
        relevant_sources.append(source)
    if not relevant_sources:
        return []

    local_keep_segments = [{"start": start, "end": end} for start, end in source_ranges if end > start + 0.001]
    local_fallback = remap_subtitles_to_timeline(relevant_sources, local_keep_segments)
    adjusted: list[dict[str, Any]] = []
    for item in local_fallback:
        payload = dict(item)
        start_time = float(payload.get("start_time", 0.0) or 0.0)
        end_time = float(payload.get("end_time", start_time) or start_time)
        payload["start_time"] = round(output_start + start_time, 3)
        payload["end_time"] = round(output_start + end_time, 3)
        adjusted.append(payload)
    return adjusted


def validate_projected_subtitles_against_source(
    projected_subtitles: list[dict[str, Any]],
    *,
    source_subtitles: list[dict[str, Any]],
    keep_segments: list[dict[str, Any]],
    fallback_source_subtitles: list[dict[str, Any]] | None = None,
) -> SubtitleProjectionValidationResult:
    annotated = annotate_projected_subtitle_sources(
        projected_subtitles,
        source_subtitles,
        keep_segments,
    )
    annotated = _repair_projection_text_drift_from_span_fallback(
        annotated,
        source_subtitles=source_subtitles,
        keep_segments=keep_segments,
    )
    mismatch = projection_has_source_text_mismatch(annotated, source_subtitles)
    if not mismatch or fallback_source_subtitles is None:
        return SubtitleProjectionValidationResult(
            subtitles=annotated,
            mismatch_detected=mismatch,
            fallback_used=False,
        )

    fallback = remap_subtitles_to_timeline(fallback_source_subtitles, keep_segments)
    fallback = annotate_projected_subtitle_sources(fallback, source_subtitles, keep_segments)
    return SubtitleProjectionValidationResult(
        subtitles=fallback,
        mismatch_detected=True,
        fallback_used=True,
    )


def _build_transcript_projection_speech_units(
    transcript_segments: list[dict[str, Any]],
) -> list[TranscriptProjectionSpeechUnit]:
    units: list[TranscriptProjectionSpeechUnit] = []
    for segment_index, segment in enumerate(transcript_segments or []):
        if not isinstance(segment, dict):
            continue
        words = [word for word in list(segment.get("words") or []) if isinstance(word, dict)]
        for word_index, word in enumerate(words):
            text = str(word.get("word") or word.get("raw_text") or word.get("text") or "").strip()
            start = _optional_float(word.get("start"))
            end = _optional_float(word.get("end"))
            if not text or start is None or end is None or end <= start:
                continue
            units.append(
                TranscriptProjectionSpeechUnit(
                    unit_type="speech_token",
                    start=start,
                    end=end,
                    text=text,
                    source_index=word_index,
                    source_kind=f"transcript_segment:{segment_index}",
                    trusted=_transcript_projection_timing_is_trusted(word),
                )
            )
        if words:
            continue
        text = str(segment.get("text") or segment.get("text_raw") or "").strip()
        start = _optional_float(segment.get("start_time", segment.get("start")))
        end = _optional_float(segment.get("end_time", segment.get("end")))
        if not text or start is None or end is None or end <= start:
            continue
        units.append(
            TranscriptProjectionSpeechUnit(
                unit_type="speech_segment",
                start=start,
                end=end,
                text=text,
                source_index=int(segment.get("index", segment_index) or segment_index),
                source_kind="transcript_segment",
                trusted=_transcript_projection_timing_is_trusted(segment),
            )
        )
    return sorted(units, key=lambda item: (item.start, item.end, item.source_kind, item.source_index))


def _projected_subtitle_source_ranges(
    projected_subtitles: list[dict[str, Any]],
    keep_segments: list[dict[str, Any]],
) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    for item in projected_subtitles or []:
        if not isinstance(item, dict):
            continue
        if not compact_projection_text(subtitle_projection_display_text(item)):
            continue
        start = _optional_float(item.get("start_time", item.get("start")))
        end = _optional_float(item.get("end_time", item.get("end")))
        if start is None or end is None or end <= start:
            continue
        ranges.extend(source_ranges_for_output_range(start, end, keep_segments))
    return sorted((start, end) for start, end in ranges if end > start)


def _normalize_time_ranges(items: list[dict[str, Any]]) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        start = _optional_float(item.get("start_time", item.get("start")))
        end = _optional_float(item.get("end_time", item.get("end")))
        if start is None or end is None or end <= start:
            continue
        ranges.append((start, end))
    return sorted(ranges)


def _range_overlap(start: float, end: float, ranges: list[tuple[float, float]]) -> float:
    return sum(max(0.0, min(end, range_end) - max(start, range_start)) for range_start, range_end in ranges)


def _has_sufficient_overlap(
    *,
    overlap: float,
    duration: float,
    min_coverage_ratio: float,
    min_overlap_sec: float,
) -> bool:
    if overlap <= 0.001:
        return False
    return overlap / max(0.001, duration) >= min_coverage_ratio or overlap >= min_overlap_sec


def _transcript_projection_timing_is_trusted(payload: dict[str, Any]) -> bool:
    return _transcript_projection_alignment_source(payload) not in SYNTHETIC_TRANSCRIPT_ALIGNMENT_SOURCES


def _transcript_projection_alignment_source(payload: dict[str, Any]) -> str:
    alignment = payload.get("alignment")
    if isinstance(alignment, dict):
        source = str(alignment.get("source") or "").strip().lower()
        if source:
            return source
        roughcut = alignment.get("_roughcut")
        if isinstance(roughcut, dict):
            source = str(roughcut.get("source") or "").strip().lower()
            if source:
                return source
    raw_payload = payload.get("raw_payload")
    if isinstance(raw_payload, dict):
        for key in ("source", "_roughcut_source"):
            source = str(raw_payload.get(key) or "").strip().lower()
            if source:
                return source
    return "provider"


def _optional_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number
