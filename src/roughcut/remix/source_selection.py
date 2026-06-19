from __future__ import annotations

from collections.abc import Sequence

from roughcut.remix.contracts import GateIssue, GateResult, SourceAnchor


def build_even_story_starts(
    *,
    source_duration_sec: float,
    clip_count: int,
    clip_duration_sec: float,
    start_guard_sec: float = 22.0,
    end_guard_sec: float = 35.0,
) -> list[float]:
    first = min(max(0.0, start_guard_sec), max(0.0, source_duration_sec - clip_duration_sec))
    latest = max(first, source_duration_sec - end_guard_sec - clip_duration_sec)
    if clip_count <= 1:
        return [round(first, 3)]
    return [round(first + (latest - first) * index / max(1, clip_count - 1), 3) for index in range(clip_count)]


def select_source_asr_clip_starts(
    anchors: Sequence[SourceAnchor],
    *,
    source_duration_sec: float,
    clip_count: int,
    clip_duration_sec: float,
    min_gap_sec: float | None = None,
) -> list[float]:
    usable = [anchor for anchor in anchors if anchor.status == "done" and anchor.end_sec > anchor.start_sec]
    if not usable:
        return build_even_story_starts(
            source_duration_sec=source_duration_sec,
            clip_count=clip_count,
            clip_duration_sec=clip_duration_sec,
        )
    resolved_min_gap = float(min_gap_sec) if min_gap_sec is not None else max(8.0, clip_duration_sec * 0.82)
    scored = sorted(usable, key=lambda item: (float(item.score), -float(item.start_sec)), reverse=True)
    selected: list[float] = []
    for anchor in scored:
        start = float(anchor.start_sec)
        if all(abs(start - existing) >= resolved_min_gap for existing in selected):
            selected.append(start)
        if len(selected) >= clip_count:
            break
    if len(selected) < clip_count:
        for start in build_even_story_starts(
            source_duration_sec=source_duration_sec,
            clip_count=clip_count,
            clip_duration_sec=clip_duration_sec,
        ):
            if all(abs(start - existing) >= resolved_min_gap for existing in selected):
                selected.append(start)
            if len(selected) >= clip_count:
                break
    if len(selected) < clip_count:
        selected = build_even_story_starts(
            source_duration_sec=source_duration_sec,
            clip_count=clip_count,
            clip_duration_sec=clip_duration_sec,
        )
    return sorted(round(value, 3) for value in selected[:clip_count])


def evaluate_source_asr_index(
    anchors: Sequence[SourceAnchor],
    *,
    min_candidate_count: int = 10,
    min_usable_count: int = 3,
) -> GateResult:
    usable_count = sum(1 for anchor in anchors if anchor.status == "done" and anchor.end_sec > anchor.start_sec)
    issues: list[GateIssue] = []
    status = "pass"
    if len(anchors) < min_candidate_count:
        status = "warn"
        issues.append(
            GateIssue(
                code="source_asr_candidate_count_low",
                severity="warn",
                message="Source-ASR generated fewer candidate windows than the target.",
                evidence={"candidate_count": len(anchors), "min_candidate_count": min_candidate_count},
            )
        )
    if usable_count < min_usable_count:
        status = "fail"
        issues.append(
            GateIssue(
                code="source_asr_usable_anchor_count_low",
                severity="error",
                message="Source-ASR usable anchors are below the hard gate.",
                evidence={"usable_count": usable_count, "min_usable_count": min_usable_count},
            )
        )
    return GateResult(
        status=status,  # type: ignore[arg-type]
        issues=tuple(issues),
        metrics={"source_asr_candidate_count": len(anchors), "source_asr_usable_anchor_count": usable_count},
    )

