from __future__ import annotations

import re
from dataclasses import dataclass, field

from roughcut.media.silence import SilenceSegment


# Chinese filler words that should be cut
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


@dataclass
class EditSegment:
    start: float
    end: float
    type: str  # "keep" | "remove"
    reason: str = ""


@dataclass
class EditDecision:
    source: str
    segments: list[EditSegment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "source": self.source,
            "segments": [
                {"start": s.start, "end": s.end, "type": s.type, "reason": s.reason}
                for s in self.segments
            ],
        }


def build_edit_decision(
    source_path: str,
    duration: float,
    silence_segments: list[SilenceSegment],
    subtitle_items: list[dict] | None = None,
    content_profile: dict | None = None,
    *,
    min_silence_to_cut: float = 0.5,
    cut_fillers: bool = True,
) -> EditDecision:
    """
    Build editorial timeline from silence segments + filler word positions.

    Returns an EditDecision with keep/remove segments.
    """
    # Collect all cut intervals (start, end, reason)
    cuts: list[tuple[float, float, str]] = []

    # Silence cuts
    for silence in silence_segments:
        if silence.duration >= min_silence_to_cut:
            cuts.append((silence.start, silence.end, "silence"))

    # Filler word cuts from subtitle timing
    if cut_fillers and subtitle_items:
        for item in subtitle_items:
            text = item.get("text_final") or item.get("text_norm") or item.get("text_raw", "")
            if FILLER_PATTERN.search(text):
                # Mark entire subtitle item as candidate for removal
                # Only remove if it's purely filler (no real content)
                clean = FILLER_PATTERN.sub("", text).strip()
                if len(clean) <= 2:
                    cuts.append((item["start_time"], item["end_time"], "filler_word"))
                    continue
            if _is_low_signal_subtitle_text(text, content_profile=content_profile):
                cuts.append((item["start_time"], item["end_time"], "low_signal_subtitle"))

    merged_cuts = _merge_cut_intervals(cuts)
    segments = _build_segments_from_cuts(duration=duration, merged_cuts=merged_cuts)
    if subtitle_items is not None:
        segments = _refine_segments_for_pacing(
            segments,
            subtitle_items=subtitle_items,
            content_profile=content_profile,
            duration=duration,
        )
    segments = _merge_adjacent_segments(segments)
    return EditDecision(source=source_path, segments=segments)


def _merge_cut_intervals(cuts: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    cuts.sort(key=lambda x: x[0])
    merged_cuts: list[tuple[float, float, str]] = []
    for cut in cuts:
        if merged_cuts and cut[0] <= merged_cuts[-1][1]:
            prev = merged_cuts[-1]
            merged_cuts[-1] = (prev[0], max(prev[1], cut[1]), prev[2])
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
    subtitle_items: list[dict],
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
            if seg_duration <= _MICRO_KEEP_NO_SUBTITLE_MAX_SEC:
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
            refined.append(
                EditSegment(start=segment.start, end=trimmed_start, type="remove", reason="timing_trim")
            )
        refined.append(EditSegment(start=trimmed_start, end=trimmed_end, type="keep"))
        if segment.end - trimmed_end >= 0.08:
            refined.append(
                EditSegment(start=trimmed_end, end=segment.end, type="remove", reason="timing_trim")
            )

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


def _overlapping_subtitle_items(start_time: float, end_time: float, subtitle_items: list[dict]) -> list[dict]:
    overlaps: list[dict] = []
    for item in subtitle_items:
        item_start = float(item.get("start_time", 0.0) or 0.0)
        item_end = float(item.get("end_time", 0.0) or 0.0)
        if min(end_time, item_end) - max(start_time, item_start) > 0.0:
            overlaps.append(item)
    return overlaps


def _subtitle_text(item: dict) -> str:
    return str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "")


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
