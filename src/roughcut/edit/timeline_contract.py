from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from roughcut.edit.rule_registry import pause_cut_reasons, speech_explicit_cut_reasons, speech_review_cut_reasons
from roughcut.edit.subtitle_surfaces import subtitle_display_rule_text
from roughcut.media.silence import SilenceSegment

SYNTHETIC_ALIGNMENT_SOURCES = {
    "canonical_realign",
    "synthetic",
    "segment_only",
    "provider_missing",
    "roughcut_synthesized",
    "postprocess_text_fallback",
    "canonical_segment_fallback",
}


@dataclass(frozen=True)
class SourceTimelineUnit:
    unit_type: str
    start: float
    end: float
    text: str = ""
    source_index: int = 0
    source_kind: str = ""
    trusted: bool = True

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "type": self.unit_type,
            "start": round(float(self.start), 3),
            "end": round(float(self.end), 3),
            "duration_sec": round(self.duration, 3),
            "source_index": int(self.source_index),
            "source_kind": self.source_kind,
            "trusted": bool(self.trusted),
        }
        if self.text:
            payload["text"] = self.text
        return payload


def audit_edit_decision_contract(
    *,
    duration: float,
    edit_segments: list[Any],
    transcript_segments: list[dict[str, Any]],
    subtitle_items: list[dict[str, Any]],
    silence_segments: list[SilenceSegment],
    min_kept_pause_sec: float = 0.55,
) -> dict[str, Any]:
    speech_explicit_reasons = speech_explicit_cut_reasons()
    speech_review_reasons = speech_review_cut_reasons()
    pause_reasons = pause_cut_reasons()
    speech_units = _build_speech_units(transcript_segments)
    pause_units = _build_pause_units(silence_segments, duration=duration)
    segments = _normalize_edit_segments(edit_segments, duration=duration)
    subtitle_ranges = _normalize_subtitle_ranges(subtitle_items)
    suppressed_subtitle_ranges = _normalize_suppressed_subtitle_ranges(subtitle_items)

    blocking: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    cut_speech: list[dict[str, Any]] = []
    cut_pauses: list[dict[str, Any]] = []
    kept_long_pauses: list[dict[str, Any]] = []

    for unit in speech_units:
        removed = _overlapping_decision_parts(unit, segments, decision_type="remove")
        kept = _overlapping_decision_parts(unit, segments, decision_type="keep")
        if removed:
            dominant = _dominant_decision_part(removed)
            reason = str(dominant.get("reason") or "").strip()
            payload = {
                **unit.as_dict(),
                "decision": "cut",
                "reason": reason,
                "overlap_sec": round(sum(float(item["overlap"]) for item in removed), 3),
            }
            cut_speech.append(payload)
            if not reason:
                blocking.append({**payload, "issue": "speech_cut_without_reason"})
            elif reason in speech_explicit_reasons:
                pass
            elif unit.trusted and reason in speech_review_reasons:
                blocking.append({**payload, "issue": "trusted_speech_cut_by_non_speech_reason"})
            elif reason not in speech_explicit_reasons | speech_review_reasons:
                warnings.append({**payload, "issue": "speech_cut_by_unknown_reason"})
        if kept and not _unit_has_subtitle_coverage(unit, subtitle_ranges):
            suppressed_overlap = _overlapping_suppressed_subtitle(unit, suppressed_subtitle_ranges)
            payload = {
                **unit.as_dict(),
                "decision": "keep",
                "issue": "kept_speech_display_suppressed" if suppressed_overlap else "kept_speech_without_subtitle",
            }
            if suppressed_overlap:
                payload["display_suppressed_reason"] = str(suppressed_overlap.get("reason") or "")
                payload["subtitle_overlap_sec"] = round(float(suppressed_overlap.get("overlap") or 0.0), 3)
            if unit.trusted:
                blocking.append(payload)
            else:
                warnings.append(payload)

    for unit in pause_units:
        removed = _overlapping_decision_parts(unit, segments, decision_type="remove")
        kept = _overlapping_decision_parts(unit, segments, decision_type="keep")
        if removed:
            dominant = _dominant_decision_part(removed)
            reason = str(dominant.get("reason") or "").strip()
            payload = {
                **unit.as_dict(),
                "decision": "cut",
                "reason": reason,
                "overlap_sec": round(sum(float(item["overlap"]) for item in removed), 3),
            }
            cut_pauses.append(payload)
            if not reason:
                blocking.append({**payload, "issue": "pause_cut_without_reason"})
            elif reason not in pause_reasons:
                warnings.append({**payload, "issue": "pause_cut_by_unexpected_reason"})
        kept_duration = sum(float(item["overlap"]) for item in kept)
        if kept_duration >= min_kept_pause_sec:
            payload = {
                **unit.as_dict(),
                "decision": "keep",
                "overlap_sec": round(kept_duration, 3),
                "issue": "long_pause_kept_without_reason",
            }
            kept_long_pauses.append(payload)
            warnings.append(payload)

    issue_counts: dict[str, int] = {}
    for item in [*blocking, *warnings]:
        issue = str(item.get("issue") or "")
        if issue:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1

    return {
        "contract_version": "source_timeline_v1",
        "blocking": bool(blocking),
        "blocking_issue_count": len(blocking),
        "warning_issue_count": len(warnings),
        "issue_counts": issue_counts,
        "speech_unit_count": len(speech_units),
        "pause_unit_count": len(pause_units),
        "cut_speech_unit_count": len(cut_speech),
        "cut_pause_unit_count": len(cut_pauses),
        "kept_long_pause_count": len(kept_long_pauses),
        "blocking_examples": blocking[:12],
        "warning_examples": warnings[:12],
        "cut_speech_examples": cut_speech[:12],
        "cut_pause_examples": cut_pauses[:12],
        "kept_long_pause_examples": kept_long_pauses[:12],
    }


def _build_speech_units(transcript_segments: list[dict[str, Any]]) -> list[SourceTimelineUnit]:
    units: list[SourceTimelineUnit] = []
    for segment_index, segment in enumerate(transcript_segments or []):
        words = [word for word in list(segment.get("words") or []) if isinstance(word, dict)]
        for word_index, word in enumerate(words):
            text = str(word.get("word") or word.get("raw_text") or "").strip()
            start = _optional_float(word.get("start"))
            end = _optional_float(word.get("end"))
            if not text or start is None or end is None or end <= start:
                continue
            units.append(
                SourceTimelineUnit(
                    unit_type="speech_token",
                    start=start,
                    end=end,
                    text=text,
                    source_index=word_index,
                    source_kind=f"transcript_segment:{segment_index}",
                    trusted=_word_timing_is_trusted(word),
                )
            )
        if words:
            continue
        text = str(segment.get("text") or "").strip()
        start = _optional_float(segment.get("start"))
        end = _optional_float(segment.get("end"))
        if not text or start is None or end is None or end <= start:
            continue
        units.append(
            SourceTimelineUnit(
                unit_type="speech_segment",
                start=start,
                end=end,
                text=text,
                source_index=int(segment.get("index", segment_index) or segment_index),
                source_kind="transcript_segment",
                trusted=_segment_timing_is_trusted(segment),
            )
        )
    return sorted(units, key=lambda item: (item.start, item.end, item.source_kind, item.source_index))


def _build_pause_units(silence_segments: list[SilenceSegment], *, duration: float) -> list[SourceTimelineUnit]:
    units: list[SourceTimelineUnit] = []
    media_duration = max(0.0, float(duration or 0.0))
    for index, silence in enumerate(silence_segments or []):
        start = max(0.0, float(silence.start))
        end = min(media_duration, max(start, float(silence.end))) if media_duration > 0 else max(start, float(silence.end))
        if end <= start + 0.08:
            continue
        units.append(
            SourceTimelineUnit(
                unit_type="pause",
                start=start,
                end=end,
                source_index=index,
                source_kind="audio_vad",
                trusted=True,
            )
        )
    return sorted(units, key=lambda item: (item.start, item.end, item.source_index))


def _normalize_edit_segments(edit_segments: list[Any], *, duration: float) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    media_duration = max(0.0, float(duration or 0.0))
    for item in edit_segments or []:
        start = _optional_float(getattr(item, "start", None) if not isinstance(item, dict) else item.get("start"))
        end = _optional_float(getattr(item, "end", None) if not isinstance(item, dict) else item.get("end"))
        if start is None or end is None:
            continue
        start = max(0.0, start)
        end = min(media_duration, end) if media_duration > 0 else end
        if end <= start:
            continue
        segment_type = str(getattr(item, "type", "") if not isinstance(item, dict) else item.get("type") or "").strip()
        reason = str(getattr(item, "reason", "") if not isinstance(item, dict) else item.get("reason") or "").strip()
        normalized.append({"start": start, "end": end, "type": segment_type, "reason": reason})
    return sorted(normalized, key=lambda item: (float(item["start"]), float(item["end"])))


def _normalize_subtitle_ranges(subtitle_items: list[dict[str, Any]]) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    for item in subtitle_items or []:
        start = _optional_float(item.get("start_time", item.get("start")))
        end = _optional_float(item.get("end_time", item.get("end")))
        text = subtitle_display_rule_text(item)
        if start is None or end is None or end <= start or not text:
            continue
        ranges.append((start, end))
    return sorted(ranges)


def _normalize_suppressed_subtitle_ranges(subtitle_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    for item in subtitle_items or []:
        start = _optional_float(item.get("start_time", item.get("start")))
        end = _optional_float(item.get("end_time", item.get("end")))
        reason = str(item.get("display_suppressed_reason") or "").strip()
        text = subtitle_display_rule_text(item)
        if start is None or end is None or end <= start or not reason or text:
            continue
        ranges.append({"start": start, "end": end, "reason": reason})
    return sorted(ranges, key=lambda item: (float(item["start"]), float(item["end"])))


def _overlapping_suppressed_subtitle(
    unit: SourceTimelineUnit,
    suppressed_subtitle_ranges: list[dict[str, Any]],
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    for item in suppressed_subtitle_ranges:
        overlap = min(unit.end, float(item["end"])) - max(unit.start, float(item["start"]))
        if overlap <= 0.001:
            continue
        payload = {**item, "overlap": overlap}
        if best is None or overlap > float(best.get("overlap") or 0.0):
            best = payload
    return best


def _overlapping_decision_parts(
    unit: SourceTimelineUnit,
    segments: list[dict[str, Any]],
    *,
    decision_type: str,
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for segment in segments:
        if str(segment.get("type") or "") != decision_type:
            continue
        overlap = min(unit.end, float(segment["end"])) - max(unit.start, float(segment["start"]))
        if overlap <= 0.001:
            continue
        parts.append({**segment, "overlap": overlap})
    return parts


def _dominant_decision_part(parts: list[dict[str, Any]]) -> dict[str, Any]:
    if not parts:
        return {}
    return max(parts, key=lambda item: (float(item.get("overlap") or 0.0), float(item.get("end") or 0.0) - float(item.get("start") or 0.0)))


def _unit_has_subtitle_coverage(unit: SourceTimelineUnit, subtitle_ranges: list[tuple[float, float]]) -> bool:
    if not subtitle_ranges:
        return False
    unit_duration = max(0.001, unit.end - unit.start)
    overlap = 0.0
    for start, end in subtitle_ranges:
        overlap += max(0.0, min(unit.end, end) - max(unit.start, start))
    return overlap / unit_duration >= 0.35 or overlap >= 0.06


def _word_timing_is_trusted(word: dict[str, Any]) -> bool:
    return _alignment_source(word) not in SYNTHETIC_ALIGNMENT_SOURCES


def _segment_timing_is_trusted(segment: dict[str, Any]) -> bool:
    return _alignment_source(segment) not in SYNTHETIC_ALIGNMENT_SOURCES


def _alignment_source(payload: dict[str, Any]) -> str:
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
    if not math.isfinite(number):
        return None
    return number
