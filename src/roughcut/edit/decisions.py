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

    # Sort cuts by start time and merge overlapping
    cuts.sort(key=lambda x: x[0])
    merged_cuts: list[tuple[float, float, str]] = []
    for cut in cuts:
        if merged_cuts and cut[0] <= merged_cuts[-1][1]:
            prev = merged_cuts[-1]
            merged_cuts[-1] = (prev[0], max(prev[1], cut[1]), prev[2])
        else:
            merged_cuts.append(cut)

    # Build keep/remove segments
    segments: list[EditSegment] = []
    cursor = 0.0

    for cut_start, cut_end, reason in merged_cuts:
        if cursor < cut_start:
            segments.append(EditSegment(start=cursor, end=cut_start, type="keep"))
        segments.append(EditSegment(start=cut_start, end=cut_end, type="remove", reason=reason))
        cursor = cut_end

    # Final keep segment
    if cursor < duration:
        segments.append(EditSegment(start=cursor, end=duration, type="keep"))

    return EditDecision(source=source_path, segments=segments)


def _is_low_signal_subtitle_text(text: str, *, content_profile: dict | None = None) -> bool:
    compact = PUNCTUATION_PATTERN.sub("", str(text or "").strip())
    if not compact:
        return True
    if "�" in compact:
        return True
    if len(compact) <= 2:
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
    if _looks_like_subject_conflict_subtitle(compact, content_profile=content_profile):
        return True

    return False


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
