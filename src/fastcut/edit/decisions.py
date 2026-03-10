from __future__ import annotations

import re
from dataclasses import dataclass, field

from fastcut.media.silence import SilenceSegment


# Chinese filler words that should be cut
FILLER_WORDS = [
    "那个", "这个", "嗯", "啊", "呃", "就是说", "然后就", "对吧对吧",
    "就是那个", "这个嘛", "我觉得那个",
]

FILLER_PATTERN = re.compile(
    r"(?:" + "|".join(re.escape(w) for w in FILLER_WORDS) + r")",
    re.UNICODE,
)


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
            text = item.get("text_norm") or item.get("text_raw", "")
            if FILLER_PATTERN.search(text):
                # Mark entire subtitle item as candidate for removal
                # Only remove if it's purely filler (no real content)
                clean = FILLER_PATTERN.sub("", text).strip()
                if len(clean) <= 2:
                    cuts.append((item["start_time"], item["end_time"], "filler_word"))

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
