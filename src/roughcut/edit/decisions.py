from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from roughcut.media.scene import SceneBoundary
from roughcut.media.silence import SilenceSegment


FILLER_WORDS = [
    "那个", "这个", "嗯", "啊", "呃", "就是说", "然后就", "对吧对吧",
    "就是那个", "这个嘛", "我觉得那个",
]

FILLER_PATTERN = re.compile(
    r"(?:" + "|".join(re.escape(w) for w in FILLER_WORDS) + r")",
    re.UNICODE,
)
HEDGE_PATTERN = re.compile(
    r"(其实|也算|算是|上是|当然|吧|一下|一点|更加|感觉|可能|好像|还是|就|都|也|会|这个|那个|的话)",
    re.UNICODE,
)
PUNCTUATION_PATTERN = re.compile(r"[，。！？!?、；;：:,.\-\s]+", re.UNICODE)
_EDC_CONFLICT_TERMS = ("摄影", "光线", "灯光", "灯具", "补光", "曝光", "色温")
_CAMERA_CONFLICT_TERMS = ("折刀", "开刃", "刀尖", "柄材", "背夹", "钢码")
_ANCHOR_KEYWORDS = (
    "开箱",
    "对比",
    "升级",
    "区别",
    "差异",
    "实测",
    "体验",
    "推荐",
    "参数",
    "尺寸",
    "重量",
    "亮度",
    "续航",
    "功率",
    "容量",
    "价格",
    "便携",
    "口感",
    "味道",
    "口气",
    "零糖",
    "益生菌",
    "含片",
    "弹射",
    "莱德曼",
)
_BRIDGE_OPENERS = (
    "你看",
    "比如",
    "比如说",
    "平时",
    "正常来说",
    "当你",
    "另外",
    "另外呢",
    "然后",
    "然后呢",
    "其实",
    "我们都知道",
)
_NUMERIC_SIGNAL_PATTERN = re.compile(r"\d", re.UNICODE)
_NON_WORD_PATTERN = re.compile(r"[，。！？!?、；;：:,.~\-—_\s\[\]【】()（）]+", re.UNICODE)
_NOISE_MARKER_TERMS = (
    "噪音",
    "杂音",
    "电流",
    "风声",
    "破音",
    "爆麦",
    "喷麦",
    "卡顿",
    "笑声",
    "掌声",
    "音乐",
    "咳嗽",
)
_NOISE_INTERJECTION_CHARS = frozenset("啊嗯呃哦哎诶欸哈呵咳")
_RESTART_CUE_TERMS = (
    "重来",
    "重讲",
    "重新讲",
    "重新说",
    "重说",
    "再来一遍",
    "再讲一遍",
    "再说一遍",
    "说错了",
    "讲错了",
    "口误",
    "嘴瓢",
    "卡壳",
    "前面不算",
    "刚才不对",
)
_RESTART_SHORT_CUES = frozenset({"重来", "重讲", "重说", "重新", "再来", "再说", "口误", "说错", "讲错"})
_TERMINAL_PUNCTUATION_CHARS = "。！？!?…~"
_INCOMPLETE_TAIL_SUFFIXES = (
    "的",
    "了",
    "是",
    "在",
    "把",
    "跟",
    "和",
    "给",
    "就",
    "又",
    "还",
    "更",
    "最",
    "很",
    "再",
    "并",
    "但",
    "而",
    "如果",
    "因为",
    "所以",
    "然后",
    "而且",
    "或者",
    "以及",
    "就是",
)
_CONTINUATION_HEAD_PREFIXES = (
    "然后",
    "所以",
    "但是",
    "不过",
    "而且",
    "以及",
    "另外",
    "再",
    "那",
    "就是",
    "其实",
    "因为",
)
_MICRO_KEEP_NO_SUBTITLE_MAX_SEC = 0.75
_MICRO_KEEP_BRIDGE_MAX_SEC = 0.6
_KEEP_TRIM_PAD_BEFORE_SEC = 0.18
_KEEP_TRIM_PAD_AFTER_SEC = 0.24
_KEEP_TRIM_PAD_BEFORE_STRONG_SEC = 0.24
_KEEP_TRIM_PAD_AFTER_STRONG_SEC = 0.32
_KEEP_EDGE_TRIM_MAX_SEC = 0.35
_KEEP_EDGE_TRIM_MAX_STRONG_SEC = 0.55
_STRONG_SUBTITLE_SIGNAL_SCORE = 2.0
_SHORT_KEEP_AUDIO_SAFE_SEC = 1.4
_SHORT_SUBTITLE_SPAN_SEC = 0.7
_SHORT_SUBTITLE_PAD_BEFORE_BONUS_SEC = 0.06
_SHORT_SUBTITLE_PAD_AFTER_BONUS_SEC = 0.08
_KEEP_CONTINUATION_PAD_BEFORE_BONUS_SEC = 0.08
_KEEP_INCOMPLETE_PAD_AFTER_BONUS_SEC = 0.18
_RETAKE_MAX_GAP_SEC = 4.5
_RETAKE_MAX_WINDOW_ITEMS = 4
_RETAKE_MIN_PREFIX_LEN = 4
_RETAKE_MAX_FRAGMENT_CHARS = 24
_SILENCE_CUT_SCORE_THRESHOLD = 0.32
_SILENCE_DURATION_SCORE_BASE = 0.22
_SILENCE_DURATION_SCORE_PER_SEC = 0.35
_SILENCE_DURATION_SCORE_MAX = 0.55
_SCENE_SNAP_TOLERANCE_SEC = 0.24
_MIN_CUT_DURATION_SEC = 0.08
_TRANSCRIPT_EVIDENCE_WINDOW_SEC = 0.45


@dataclass
class EditSegment:
    start: float
    end: float
    type: str
    reason: str = ""


@dataclass
class CutCandidate:
    start: float
    end: float
    reason: str
    score: float = 1.0
    hard: bool = False
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 4),
            "end": round(self.end, 4),
            "reason": self.reason,
            "score": round(self.score, 4),
            "hard": self.hard,
            "signals": list(self.signals),
        }


@dataclass
class EditDecision:
    source: str
    segments: list[EditSegment] = field(default_factory=list)
    analysis: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        payload = {
            "version": 2,
            "source": self.source,
            "segments": [
                {"start": s.start, "end": s.end, "type": s.type, "reason": s.reason}
                for s in self.segments
            ],
        }
        if self.analysis:
            payload["analysis"] = self.analysis
        return payload


def build_edit_decision(
    source_path: str,
    duration: float,
    silence_segments: list[SilenceSegment],
    subtitle_items: list[dict] | None = None,
    content_profile: dict | None = None,
    *,
    transcript_segments: list[dict] | None = None,
    scene_boundaries: list[SceneBoundary | dict[str, Any] | float] | None = None,
    min_silence_to_cut: float = 0.5,
    cut_fillers: bool = True,
) -> EditDecision:
    normalized_subtitles = _normalize_subtitle_items(subtitle_items or [])
    normalized_transcript = _normalize_transcript_segments(transcript_segments or [])
    enriched_subtitles = _enrich_subtitle_items_with_transcript_evidence(
        normalized_subtitles,
        normalized_transcript,
    )
    scene_points = _normalize_scene_points(scene_boundaries or [])

    candidates: list[CutCandidate] = []
    candidates.extend(
        _build_silence_cut_candidates(
            silence_segments,
            subtitle_items=enriched_subtitles,
            transcript_segments=normalized_transcript,
            content_profile=content_profile,
            scene_points=scene_points,
            min_silence_to_cut=min_silence_to_cut,
        )
    )
    if cut_fillers and enriched_subtitles:
        candidates.extend(
            _build_subtitle_cut_candidates(
                enriched_subtitles,
                content_profile=content_profile,
            )
        )
        candidates.extend(_build_hard_cut_candidates(
            _collect_restart_retake_cuts(enriched_subtitles, content_profile=content_profile)
        ))

    merged_cuts = _merge_cut_intervals(
        [(candidate.start, candidate.end, candidate.reason) for candidate in candidates]
    )
    segments = _build_segments_from_cuts(duration=duration, merged_cuts=merged_cuts)
    if subtitle_items is not None:
        segments = _refine_segments_for_pacing(
            segments,
            subtitle_items=enriched_subtitles,
            transcript_segments=normalized_transcript,
            content_profile=content_profile,
            duration=duration,
        )
    segments = _merge_adjacent_segments(segments)
    return EditDecision(
        source=source_path,
        segments=segments,
        analysis={
            "candidate_count": len(candidates),
            "scene_boundary_count": len(scene_points),
            "transcript_segment_count": len(normalized_transcript),
            "accepted_cuts": [candidate.to_dict() for candidate in candidates],
        },
    )


def _build_silence_cut_candidates(
    silence_segments: list[SilenceSegment],
    *,
    subtitle_items: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    content_profile: dict | None,
    scene_points: list[float],
    min_silence_to_cut: float,
) -> list[CutCandidate]:
    candidates: list[CutCandidate] = []
    for silence in silence_segments:
        if silence.duration < min_silence_to_cut:
            continue
        candidate = _score_silence_cut(
            silence,
            subtitle_items=subtitle_items,
            transcript_segments=transcript_segments,
            content_profile=content_profile,
            scene_points=scene_points,
            min_silence_to_cut=min_silence_to_cut,
        )
        if candidate.score >= _SILENCE_CUT_SCORE_THRESHOLD and candidate.end - candidate.start >= _MIN_CUT_DURATION_SEC:
            candidates.append(candidate)
    return candidates


def _score_silence_cut(
    silence: SilenceSegment,
    *,
    subtitle_items: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    content_profile: dict | None,
    scene_points: list[float],
    min_silence_to_cut: float,
) -> CutCandidate:
    score = min(
        _SILENCE_DURATION_SCORE_MAX,
        _SILENCE_DURATION_SCORE_BASE + max(0.0, silence.duration - min_silence_to_cut) * _SILENCE_DURATION_SCORE_PER_SEC,
    )
    signals = [f"silence_duration={silence.duration:.2f}s"]
    previous_item = _find_previous_subtitle(silence.start, subtitle_items)
    next_item = _find_next_subtitle(silence.end, subtitle_items)
    overlaps = _overlapping_subtitle_items(silence.start, silence.end, subtitle_items)

    if not overlaps:
        score += 0.10
        signals.append("clean_gap")
    if previous_item is not None and _is_low_signal_subtitle_text(_subtitle_text(previous_item), content_profile=content_profile):
        score += 0.16
        signals.append("prev_low_signal")
    if next_item is not None and _is_low_signal_subtitle_text(_subtitle_text(next_item), content_profile=content_profile):
        score += 0.12
        signals.append("next_low_signal")
    if previous_item is not None and _is_restart_cue_text(_subtitle_text(previous_item)):
        score += 0.18
        signals.append("restart_cue_prev")
    if next_item is not None and _is_restart_cue_text(_subtitle_text(next_item)):
        score += 0.18
        signals.append("restart_cue_next")
    if _looks_like_sentence_continuation(previous_item, next_item):
        score -= 0.35
        signals.append("continuation_guard")
    if _looks_like_semantic_bridge(previous_item, next_item, content_profile=content_profile):
        score -= 0.08
        signals.append("semantic_bridge")

    previous_speaker = str((previous_item or {}).get("dominant_speaker") or "").strip()
    next_speaker = str((next_item or {}).get("dominant_speaker") or "").strip()
    if previous_speaker and next_speaker:
        if previous_speaker == next_speaker:
            score -= 0.08
            signals.append("same_speaker")
        else:
            score += 0.14
            signals.append("speaker_change")

    confidence_penalty = _silence_confidence_penalty(
        silence,
        previous_item=previous_item,
        next_item=next_item,
        transcript_segments=transcript_segments,
    )
    if confidence_penalty:
        score += confidence_penalty
        signals.append(f"confidence_guard={confidence_penalty:.2f}")

    cut_start = silence.start
    cut_end = silence.end
    snapped_start = _snap_edge(cut_start, scene_points, tolerance=_SCENE_SNAP_TOLERANCE_SEC, lower_bound=0.0, upper_bound=cut_end - _MIN_CUT_DURATION_SEC)
    if snapped_start is not None:
        cut_start = snapped_start
        score += 0.06
        signals.append("scene_snap_start")
    snapped_end = _snap_edge(cut_end, scene_points, tolerance=_SCENE_SNAP_TOLERANCE_SEC, lower_bound=cut_start + _MIN_CUT_DURATION_SEC, upper_bound=max(cut_end, cut_start + _MIN_CUT_DURATION_SEC))
    if snapped_end is not None:
        cut_end = snapped_end
        score += 0.06
        signals.append("scene_snap_end")

    return CutCandidate(
        start=max(0.0, cut_start),
        end=max(max(0.0, cut_start), cut_end),
        reason="silence",
        score=max(0.0, score),
        signals=signals,
    )


def _build_subtitle_cut_candidates(
    subtitle_items: list[dict[str, Any]],
    *,
    content_profile: dict | None,
) -> list[CutCandidate]:
    candidates: list[CutCandidate] = []
    for item in subtitle_items:
        text = _subtitle_text(item)
        if FILLER_PATTERN.search(text):
            clean = FILLER_PATTERN.sub("", text).strip()
            if len(clean) <= 2:
                candidates.append(
                    CutCandidate(
                        start=float(item["start_time"]),
                        end=float(item["end_time"]),
                        reason="filler_word",
                        hard=True,
                        signals=["pure_filler"],
                    )
                )
                continue
        if _is_low_signal_subtitle_text(text, content_profile=content_profile):
            candidates.append(
                CutCandidate(
                    start=float(item["start_time"]),
                    end=float(item["end_time"]),
                    reason="low_signal_subtitle",
                    hard=True,
                    signals=["low_signal_text"],
                )
            )
    return candidates


def _build_hard_cut_candidates(cuts: list[tuple[float, float, str]]) -> list[CutCandidate]:
    return [
        CutCandidate(start=start, end=end, reason=reason, hard=True, signals=["hard_rule"])
        for start, end, reason in cuts
        if end > start
    ]


def _normalize_subtitle_items(subtitle_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in subtitle_items:
        start_time = _as_float(item.get("start_time"))
        end_time = _as_float(item.get("end_time"))
        if end_time <= start_time:
            continue
        normalized.append(
            {
                **dict(item),
                "start_time": start_time,
                "end_time": end_time,
                "text_raw": str(item.get("text_raw") or ""),
                "text_norm": str(item.get("text_norm") or ""),
                "text_final": str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or ""),
            }
        )
    normalized.sort(key=lambda item: (item["start_time"], item["end_time"]))
    return normalized


def _normalize_transcript_segments(transcript_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(transcript_segments):
        payload = dict(item) if isinstance(item, dict) else {
            "index": getattr(item, "index", index),
            "start": getattr(item, "start", getattr(item, "start_time", 0.0)),
            "end": getattr(item, "end", getattr(item, "end_time", 0.0)),
            "text": getattr(item, "text", ""),
            "speaker": getattr(item, "speaker", None),
            "words": getattr(item, "words", getattr(item, "words_json", [])),
            "confidence": getattr(item, "confidence", None),
            "logprob": getattr(item, "logprob", None),
            "alignment": getattr(item, "alignment", None),
        }
        start = _as_float(payload.get("start"), fallback=_as_float(payload.get("start_time")))
        end = _as_float(payload.get("end"), fallback=_as_float(payload.get("end_time")))
        if end <= start:
            continue
        words: list[dict[str, Any]] = []
        for word in payload.get("words") or payload.get("words_json") or []:
            if isinstance(word, dict):
                word_start = _as_float(word.get("start"))
                word_end = _as_float(word.get("end"), fallback=word_start)
                words.append(
                    {
                        "word": str(word.get("word") or word.get("raw_text") or ""),
                        "start": word_start,
                        "end": word_end,
                        "confidence": _optional_float(word.get("confidence")),
                        "logprob": _optional_float(word.get("logprob")),
                        "alignment": word.get("alignment"),
                    }
                )
        normalized.append(
            {
                "index": int(payload.get("index", index) or index),
                "start": start,
                "end": end,
                "text": str(payload.get("text") or payload.get("raw_text") or ""),
                "speaker": str(payload.get("speaker") or "").strip() or None,
                "confidence": _optional_float(payload.get("confidence")),
                "logprob": _optional_float(payload.get("logprob")),
                "alignment": payload.get("alignment"),
                "words": words,
            }
        )
    normalized.sort(key=lambda item: (item["start"], item["end"]))
    return normalized


def _normalize_scene_points(scene_boundaries: list[SceneBoundary | dict[str, Any] | float]) -> list[float]:
    points: list[float] = []
    for boundary in scene_boundaries:
        if isinstance(boundary, (int, float)):
            if float(boundary) >= 0:
                points.append(float(boundary))
            continue
        if isinstance(boundary, dict):
            for key in ("start", "end"):
                value = _optional_float(boundary.get(key))
                if value is not None and value >= 0:
                    points.append(value)
            continue
        for key in ("start", "end"):
            value = _optional_float(getattr(boundary, key, None))
            if value is not None and value >= 0:
                points.append(value)
    return sorted({round(point, 3) for point in points})


def _enrich_subtitle_items_with_transcript_evidence(
    subtitle_items: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in subtitle_items:
        overlaps = _overlapping_transcript_segments(item["start_time"], item["end_time"], transcript_segments)
        confidence_values: list[float] = []
        logprob_values: list[float] = []
        speaker_labels: list[str] = []
        has_alignment = False
        word_count = 0
        for segment in overlaps:
            if segment.get("confidence") is not None:
                confidence_values.append(float(segment["confidence"]))
            if segment.get("logprob") is not None:
                logprob_values.append(float(segment["logprob"]))
            speaker = str(segment.get("speaker") or "").strip()
            if speaker:
                speaker_labels.append(speaker)
            if segment.get("alignment") is not None:
                has_alignment = True
            words = list(segment.get("words") or [])
            word_count += len(words)
            for word in words:
                if word.get("confidence") is not None:
                    confidence_values.append(float(word["confidence"]))
                if word.get("logprob") is not None:
                    logprob_values.append(float(word["logprob"]))
                if word.get("alignment") is not None:
                    has_alignment = True
        enriched.append(
            {
                **item,
                "avg_confidence": _mean(confidence_values),
                "avg_logprob": _mean(logprob_values),
                "dominant_speaker": _dominant_label(speaker_labels),
                "speaker_labels": sorted(set(speaker_labels)),
                "has_speaker_change": len(set(speaker_labels)) > 1,
                "alignment_supported": has_alignment,
                "word_count": word_count,
            }
        )
    return enriched


def _merge_cut_intervals(cuts: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    cuts.sort(key=lambda x: x[0])
    merged_cuts: list[tuple[float, float, str]] = []
    for cut in cuts:
        if merged_cuts and cut[0] <= merged_cuts[-1][1]:
            prev = merged_cuts[-1]
            merged_reason = prev[2] if _cut_reason_priority(prev[2]) >= _cut_reason_priority(cut[2]) else cut[2]
            merged_cuts[-1] = (prev[0], max(prev[1], cut[1]), merged_reason)
        else:
            merged_cuts.append(cut)
    return merged_cuts


def _build_segments_from_cuts(*, duration: float, merged_cuts: list[tuple[float, float, str]]) -> list[EditSegment]:
    segments: list[EditSegment] = []
    cursor = 0.0
    for cut_start, cut_end, reason in merged_cuts:
        if cursor < cut_start:
            segments.append(EditSegment(start=cursor, end=cut_start, type="keep"))
        segments.append(EditSegment(start=cut_start, end=cut_end, type="remove", reason=reason))
        cursor = cut_end
    if cursor < duration:
        segments.append(EditSegment(start=cursor, end=duration, type="keep"))
    return segments


def _refine_segments_for_pacing(
    segments: list[EditSegment],
    *,
    subtitle_items: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    content_profile: dict | None,
    duration: float,
) -> list[EditSegment]:
    refined: list[EditSegment] = []
    for segment in segments:
        if segment.type != "keep":
            refined.append(segment)
            continue

        seg_duration = max(0.0, segment.end - segment.start)
        overlaps = _overlapping_subtitle_items(segment.start, segment.end, subtitle_items)
        if not overlaps:
            transcript_overlaps = _overlapping_transcript_segments(segment.start, segment.end, transcript_segments)
            if seg_duration <= _MICRO_KEEP_NO_SUBTITLE_MAX_SEC and not transcript_overlaps:
                refined.append(EditSegment(start=segment.start, end=segment.end, type="remove", reason="micro_keep"))
            else:
                refined.append(segment)
            continue

        max_signal = max(_subtitle_signal_score(_subtitle_text(item), content_profile=content_profile) for item in overlaps)
        overlap_start = min(float(item.get("start_time", 0.0) or 0.0) for item in overlaps)
        overlap_end = max(float(item.get("end_time", 0.0) or 0.0) for item in overlaps)
        overlap_duration = max(0.0, overlap_end - overlap_start)
        pad_before = _KEEP_TRIM_PAD_BEFORE_STRONG_SEC if max_signal >= _STRONG_SUBTITLE_SIGNAL_SCORE else _KEEP_TRIM_PAD_BEFORE_SEC
        pad_after = _KEEP_TRIM_PAD_AFTER_STRONG_SEC if max_signal >= _STRONG_SUBTITLE_SIGNAL_SCORE else _KEEP_TRIM_PAD_AFTER_SEC
        max_edge_trim = _KEEP_EDGE_TRIM_MAX_STRONG_SEC if max_signal >= _STRONG_SUBTITLE_SIGNAL_SCORE else _KEEP_EDGE_TRIM_MAX_SEC
        if overlap_duration <= _SHORT_SUBTITLE_SPAN_SEC:
            pad_before += _SHORT_SUBTITLE_PAD_BEFORE_BONUS_SEC
            pad_after += _SHORT_SUBTITLE_PAD_AFTER_BONUS_SEC
        first_overlap = min(overlaps, key=lambda item: float(item.get("start_time", 0.0) or 0.0))
        last_overlap = max(overlaps, key=lambda item: float(item.get("end_time", 0.0) or 0.0))
        if _looks_like_continuation_head(_subtitle_text(first_overlap)):
            pad_before += _KEEP_CONTINUATION_PAD_BEFORE_BONUS_SEC
        if _looks_like_incomplete_tail(_subtitle_text(last_overlap)):
            pad_after += _KEEP_INCOMPLETE_PAD_AFTER_BONUS_SEC

        if seg_duration <= _SHORT_KEEP_AUDIO_SAFE_SEC:
            refined.append(segment)
            continue

        desired_start = max(segment.start, overlap_start - pad_before)
        desired_end = min(segment.end, overlap_end + pad_after)
        trimmed_start = segment.start + min(max(0.0, desired_start - segment.start), max_edge_trim)
        trimmed_end = segment.end - min(max(0.0, segment.end - desired_end), max_edge_trim)
        if trimmed_end <= trimmed_start + 0.08:
            trimmed_start = segment.start
            trimmed_end = segment.end

        if trimmed_start - segment.start >= 0.08:
            refined.append(EditSegment(start=segment.start, end=trimmed_start, type="remove", reason="timing_trim"))
        refined.append(EditSegment(start=trimmed_start, end=trimmed_end, type="keep"))
        if segment.end - trimmed_end >= 0.08:
            refined.append(EditSegment(start=trimmed_end, end=segment.end, type="remove", reason="timing_trim"))

    refined = _merge_adjacent_segments(refined)
    collapsed: list[EditSegment] = []
    for index, segment in enumerate(refined):
        if segment.type != "keep":
            collapsed.append(segment)
            continue
        seg_duration = max(0.0, segment.end - segment.start)
        overlaps = _overlapping_subtitle_items(segment.start, segment.end, subtitle_items)
        max_signal = max(
            (_subtitle_signal_score(_subtitle_text(item), content_profile=content_profile) for item in overlaps),
            default=0.0,
        )
        surrounded_by_removes = (
            index > 0
            and index < len(refined) - 1
            and refined[index - 1].type == "remove"
            and refined[index + 1].type == "remove"
        )
        if surrounded_by_removes and seg_duration <= _MICRO_KEEP_BRIDGE_MAX_SEC and max_signal < _STRONG_SUBTITLE_SIGNAL_SCORE:
            collapsed.append(EditSegment(start=segment.start, end=segment.end, type="remove", reason="micro_keep_bridge"))
            continue
        collapsed.append(segment)

    merged = _merge_adjacent_segments(collapsed)
    if merged and merged[0].start > 0:
        merged.insert(0, EditSegment(start=0.0, end=merged[0].start, type="remove", reason="gap_fill"))
    if merged and merged[-1].end < duration:
        merged.append(EditSegment(start=merged[-1].end, end=duration, type="remove", reason="gap_fill"))
    return _merge_adjacent_segments(merged)


def _merge_adjacent_segments(segments: list[EditSegment]) -> list[EditSegment]:
    ordered = sorted(
        (segment for segment in segments if segment.end > segment.start),
        key=lambda segment: (segment.start, segment.end),
    )
    merged: list[EditSegment] = []
    for segment in ordered:
        if not merged:
            merged.append(segment)
            continue
        previous = merged[-1]
        same_type = previous.type == segment.type
        touching = segment.start <= previous.end + 1e-6
        if same_type and touching:
            merged[-1] = EditSegment(
                start=previous.start,
                end=max(previous.end, segment.end),
                type=previous.type,
                reason=previous.reason or segment.reason,
            )
            continue
        merged.append(segment)
    return merged


def _overlapping_subtitle_items(start_time: float, end_time: float, subtitle_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    overlaps: list[dict[str, Any]] = []
    for item in subtitle_items:
        item_start = float(item.get("start_time", 0.0) or 0.0)
        item_end = float(item.get("end_time", 0.0) or 0.0)
        if min(end_time, item_end) - max(start_time, item_start) > 0.0:
            overlaps.append(item)
    return overlaps


def _overlapping_transcript_segments(start_time: float, end_time: float, transcript_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    overlaps: list[dict[str, Any]] = []
    for item in transcript_segments:
        item_start = float(item.get("start", 0.0) or 0.0)
        item_end = float(item.get("end", 0.0) or 0.0)
        if min(end_time, item_end) - max(start_time, item_start) > 0.0:
            overlaps.append(item)
    return overlaps


def _find_previous_subtitle(time_point: float, subtitle_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    previous: dict[str, Any] | None = None
    for item in subtitle_items:
        if float(item.get("end_time", 0.0) or 0.0) <= time_point + 1e-6:
            previous = item
            continue
        break
    return previous


def _find_next_subtitle(time_point: float, subtitle_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in subtitle_items:
        if float(item.get("start_time", 0.0) or 0.0) >= time_point - 1e-6:
            return item
    return None


def _subtitle_text(item: dict) -> str:
    return str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "")


def _compact_subtitle_text(text: str) -> str:
    return _NON_WORD_PATTERN.sub("", str(text or "").strip()).upper()


def _subtitle_signal_score(text: str, *, content_profile: dict | None) -> float:
    compact = PUNCTUATION_PATTERN.sub("", str(text or "").strip())
    if not compact:
        return 0.0
    score = 0.0
    if _NUMERIC_SIGNAL_PATTERN.search(compact):
        score += 1.0
    if any(keyword in compact for keyword in _ANCHOR_KEYWORDS):
        score += 1.5
    for token in _extract_subject_tokens(content_profile or {}):
        if token and token in compact.upper():
            score += 2.5
            break
    if len(compact) >= 10:
        score += 0.5
    if any(compact.startswith(prefix) for prefix in _BRIDGE_OPENERS):
        score -= 1.0
    if _is_low_signal_subtitle_text(compact, content_profile=content_profile):
        score -= 1.5
    return score


def _is_low_signal_subtitle_text(text: str, *, content_profile: dict | None = None) -> bool:
    compact = PUNCTUATION_PATTERN.sub("", str(text or "").strip())
    if not compact:
        return True
    if "�" in compact:
        return True
    if _looks_like_noise_subtitle(compact):
        return True
    if len(compact) <= 2:
        return True
    if len(compact) <= 8 and any(compact.startswith(prefix) for prefix in _BRIDGE_OPENERS) and not _has_anchor_signal(compact, content_profile=content_profile):
        return True
    repeated_chunk = re.search(r"(.{2,8})\1{1,}", compact)
    if repeated_chunk:
        return True
    unique_chars = len(set(compact))
    if len(compact) >= 8 and unique_chars <= max(2, len(compact) // 5):
        return True
    repeated_token_match = re.fullmatch(r"(.{1,6})", compact)
    if repeated_token_match and compact.count(repeated_token_match.group(1)) >= 3:
        return True
    stripped_hedge = HEDGE_PATTERN.sub("", compact)
    if len(compact) <= 12 and len(stripped_hedge) <= 4 and not re.search(r"[A-Za-z0-9]", stripped_hedge):
        return True
    if len(compact) <= 18 and len(stripped_hedge) <= max(4, int(len(compact) * 0.38)):
        return True
    if len(compact) <= 14 and len(stripped_hedge) <= 5 and not _has_anchor_signal(compact, content_profile=content_profile):
        return True
    if _looks_like_subject_conflict_subtitle(compact, content_profile=content_profile):
        return True
    return False


def _looks_like_noise_subtitle(text: str) -> bool:
    compact = _compact_subtitle_text(text)
    if not compact:
        return False
    if any(marker in compact for marker in _NOISE_MARKER_TERMS):
        return True
    if len(compact) <= 6 and set(compact) <= _NOISE_INTERJECTION_CHARS and len(compact) >= 3:
        return True
    if len(compact) <= 8 and re.fullmatch(r"([啊嗯呃哦哎诶欸哈呵咳])\1{2,}", compact):
        return True
    return False


def _looks_like_incomplete_tail(text: str) -> bool:
    raw = str(text or "").strip()
    compact = _compact_subtitle_text(raw)
    if len(compact) < _RETAKE_MIN_PREFIX_LEN:
        return False
    if raw and raw[-1] in _TERMINAL_PUNCTUATION_CHARS:
        return False
    if any(compact.endswith(token) for token in _INCOMPLETE_TAIL_SUFFIXES):
        return True
    return len(compact) <= 10 and compact[-1] in {"的", "了", "是", "在", "把", "跟", "和", "给", "就", "又", "更", "最", "很"}


def _looks_like_continuation_head(text: str) -> bool:
    compact = _compact_subtitle_text(text)
    return any(compact.startswith(prefix) for prefix in _CONTINUATION_HEAD_PREFIXES)


def _looks_like_sentence_continuation(
    previous_item: dict[str, Any] | None,
    next_item: dict[str, Any] | None,
) -> bool:
    if previous_item is None or next_item is None:
        return False
    previous_text = _subtitle_text(previous_item)
    next_text = _subtitle_text(next_item)
    if _looks_like_incomplete_tail(previous_text):
        return True
    if _looks_like_continuation_head(next_text):
        return True
    compact_previous = _compact_subtitle_text(previous_text)
    compact_next = _compact_subtitle_text(next_text)
    return bool(
        compact_previous
        and compact_next
        and compact_previous[-1] not in _TERMINAL_PUNCTUATION_CHARS
        and compact_next[:1] in {"而", "但", "并", "就", "也"}
    )


def _looks_like_semantic_bridge(
    previous_item: dict[str, Any] | None,
    next_item: dict[str, Any] | None,
    *,
    content_profile: dict | None,
) -> bool:
    if previous_item is None or next_item is None:
        return False
    previous_text = _subtitle_text(previous_item)
    next_text = _subtitle_text(next_item)
    return (
        _subtitle_signal_score(previous_text, content_profile=content_profile) >= _STRONG_SUBTITLE_SIGNAL_SCORE
        and _subtitle_signal_score(next_text, content_profile=content_profile) >= _STRONG_SUBTITLE_SIGNAL_SCORE
    )


def _collect_restart_retake_cuts(
    subtitle_items: list[dict],
    *,
    content_profile: dict | None,
) -> list[tuple[float, float, str]]:
    ordered = sorted(
        subtitle_items,
        key=lambda item: (
            float(item.get("start_time", 0.0) or 0.0),
            float(item.get("end_time", 0.0) or 0.0),
        ),
    )
    cuts: list[tuple[float, float, str]] = []
    for start_index, item in enumerate(ordered):
        fragment_text = _subtitle_text(item)
        fragment_compact = _compact_subtitle_text(fragment_text)
        if (
            len(fragment_compact) < _RETAKE_MIN_PREFIX_LEN
            or len(fragment_compact) > _RETAKE_MAX_FRAGMENT_CHARS
            or not _looks_like_incomplete_tail(fragment_text)
        ):
            continue
        fragment_start = float(item.get("start_time", 0.0) or 0.0)
        fragment_end = float(item.get("end_time", 0.0) or 0.0)
        lookahead_stop = min(len(ordered), start_index + _RETAKE_MAX_WINDOW_ITEMS + 1)
        for next_index in range(start_index + 1, lookahead_stop):
            next_item = ordered[next_index]
            next_start = float(next_item.get("start_time", 0.0) or 0.0)
            if next_start - fragment_end > _RETAKE_MAX_GAP_SEC:
                break
            next_text = _subtitle_text(next_item)
            next_compact = _compact_subtitle_text(next_text)
            if not _looks_like_retake_match(fragment_compact, next_compact):
                continue
            if not _retake_window_is_disposable(
                ordered,
                start_index=start_index,
                next_index=next_index,
                content_profile=content_profile,
            ):
                continue
            if next_start - fragment_start >= 0.18:
                cuts.append((fragment_start, next_start, "restart_retake"))
            break
    return cuts


def _looks_like_retake_match(fragment_compact: str, next_compact: str) -> bool:
    if not fragment_compact or not next_compact:
        return False
    if len(next_compact) < len(fragment_compact) + 3:
        return False
    prefix_len = 0
    for left, right in zip(fragment_compact, next_compact):
        if left != right:
            break
        prefix_len += 1
    return prefix_len >= min(len(fragment_compact), 8) and prefix_len >= _RETAKE_MIN_PREFIX_LEN


def _retake_window_is_disposable(
    ordered: list[dict],
    *,
    start_index: int,
    next_index: int,
    content_profile: dict | None,
) -> bool:
    if next_index <= start_index + 1:
        return True
    saw_restart_cue = False
    for middle_item in ordered[start_index + 1:next_index]:
        middle_text = _subtitle_text(middle_item)
        if _is_restart_cue_text(middle_text):
            saw_restart_cue = True
            continue
        if _is_low_signal_subtitle_text(middle_text, content_profile=content_profile):
            continue
        return False
    return saw_restart_cue


def _is_restart_cue_text(text: str) -> bool:
    compact = _compact_subtitle_text(text)
    if not compact:
        return False
    if any(term in compact for term in _RESTART_CUE_TERMS):
        return True
    return compact in _RESTART_SHORT_CUES


def _has_anchor_signal(text: str, *, content_profile: dict | None) -> bool:
    normalized = str(text or "")
    if _NUMERIC_SIGNAL_PATTERN.search(normalized):
        return True
    if any(keyword in normalized for keyword in _ANCHOR_KEYWORDS):
        return True
    subject_tokens = _extract_subject_tokens(content_profile or {})
    return any(token in normalized.upper() for token in subject_tokens)


def _looks_like_subject_conflict_subtitle(text: str, *, content_profile: dict | None) -> bool:
    profile = content_profile or {}
    family = _subject_family(str(profile.get("subject_type") or ""))
    if not family:
        return False
    conflict_terms: tuple[str, ...] = ()
    if family == "edc":
        conflict_terms = _EDC_CONFLICT_TERMS
    elif family == "camera":
        conflict_terms = _CAMERA_CONFLICT_TERMS
    if not conflict_terms:
        return False
    normalized = str(text or "")
    if not any(term in normalized for term in conflict_terms):
        return False
    subject_tokens = _extract_subject_tokens(profile)
    if subject_tokens and not any(token in normalized.upper() for token in subject_tokens):
        return False
    return len(normalized) <= 18


def _extract_subject_tokens(profile: dict) -> set[str]:
    tokens: set[str] = set()
    for key in ("subject_brand", "subject_model", "visible_text"):
        raw = str(profile.get(key) or "")
        for token in re.findall(r"[A-Za-z0-9-]{2,}", raw.upper()):
            tokens.add(token)
            tokens.add(token.replace("-", ""))
    return {token for token in tokens if token}


def _subject_family(subject_type: str) -> str:
    normalized = str(subject_type or "").strip()
    if not normalized:
        return ""
    if any(token in normalized for token in ("折刀", "工具钳", "战术", "EDC", "刀", "背夹", "柄材")):
        return "edc"
    if any(token in normalized for token in ("相机", "镜头", "摄影", "灯", "补光")):
        return "camera"
    return ""


def _cut_reason_priority(reason: str) -> int:
    priorities = {
        "restart_retake": 5,
        "noise_subtitle": 4,
        "low_signal_subtitle": 4,
        "filler_word": 4,
        "timing_trim": 3,
        "silence": 2,
        "micro_keep": 1,
        "micro_keep_bridge": 1,
        "gap_fill": 0,
    }
    return priorities.get(str(reason or "").strip(), 0)


def _silence_confidence_penalty(
    silence: SilenceSegment,
    *,
    previous_item: dict[str, Any] | None,
    next_item: dict[str, Any] | None,
    transcript_segments: list[dict[str, Any]],
) -> float:
    candidates: list[float] = []
    for item in (previous_item, next_item):
        confidence = _optional_float((item or {}).get("avg_confidence"))
        if confidence is not None:
            candidates.append(confidence)
    nearby_segments = _overlapping_transcript_segments(
        max(0.0, silence.start - _TRANSCRIPT_EVIDENCE_WINDOW_SEC),
        silence.end + _TRANSCRIPT_EVIDENCE_WINDOW_SEC,
        transcript_segments,
    )
    for item in nearby_segments:
        confidence = _optional_float(item.get("confidence"))
        if confidence is not None:
            candidates.append(confidence)
    if not candidates:
        return 0.0
    average_confidence = _mean(candidates)
    if average_confidence is None:
        return 0.0
    if average_confidence < 0.55:
        return -0.18
    if average_confidence < 0.68:
        return -0.10
    return 0.0


def _snap_edge(
    edge: float,
    scene_points: list[float],
    *,
    tolerance: float,
    lower_bound: float,
    upper_bound: float,
) -> float | None:
    nearest: float | None = None
    nearest_distance = math.inf
    for point in scene_points:
        if point < lower_bound - 1e-6 or point > upper_bound + 1e-6:
            continue
        distance = abs(point - edge)
        if distance <= tolerance and distance < nearest_distance:
            nearest = point
            nearest_distance = distance
    return nearest


def _dominant_label(labels: list[str]) -> str | None:
    if not labels:
        return None
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return max(sorted(counts), key=lambda label: counts[label])


def _mean(values: list[float]) -> float | None:
    filtered = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not filtered:
        return None
    return sum(filtered) / len(filtered)


def _as_float(value: Any, *, fallback: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _optional_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
