from __future__ import annotations

from typing import Any


_ROLE_BASE_SCORE: dict[str, float] = {
    "hook": 0.48,
    "detail": 0.82,
    "body": 0.68,
    "cta": 0.08,
}

_CONTENT_KIND_ROLE_BONUS: dict[str, dict[str, float]] = {
    "gameplay": {"hook": 0.12, "detail": 0.18, "body": 0.16},
    "vlog": {"body": 0.14, "detail": 0.08},
    "food": {"detail": 0.18, "body": 0.12},
    "tutorial": {"detail": 0.12, "body": 0.08},
    "unboxing": {"detail": 0.16, "body": 0.1},
    "commentary": {"body": 0.06},
}

_HIGHLIGHT_LONGFORM_MIN_SEC = 12.0
_HIGHLIGHT_MIN_WINDOW_SEC = 1.8
_HIGHLIGHT_MAX_WINDOW_SEC = 16.0


def build_local_highlight_candidates(
    *,
    annotated_items: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    emphasis_candidates: list[dict[str, Any]],
    multimodal_segment_hints: list[dict[str, Any]] | None = None,
    content_profile: dict[str, Any] | None = None,
    editing_skill: dict[str, Any] | None = None,
    duration: float | None = None,
    max_count: int = 4,
) -> list[dict[str, Any]]:
    total_duration = max(0.0, float(duration or 0.0))
    if total_duration < _HIGHLIGHT_LONGFORM_MIN_SEC:
        return []

    content_kind = str((content_profile or {}).get("content_kind") or "").strip().lower()
    skill_key = str((editing_skill or {}).get("key") or "").strip().lower()
    ranked: list[tuple[float, dict[str, Any]]] = []

    for index, section in enumerate(sections):
        role = str(section.get("role") or "").strip().lower()
        if role == "cta":
            continue
        start_sec = round(float(section.get("start_sec", 0.0) or 0.0), 3)
        end_sec = round(float(section.get("end_sec", start_sec) or start_sec), 3)
        window_duration = max(0.0, end_sec - start_sec)
        if window_duration < _HIGHLIGHT_MIN_WINDOW_SEC:
            continue

        highlighted_emphasis = [
            candidate
            for candidate in emphasis_candidates
            if float(candidate.get("start_time", 0.0) or 0.0) < end_sec
            and float(candidate.get("end_time", 0.0) or 0.0) > start_sec
        ]
        overlapping_items = [
            item
            for item in annotated_items
            if float(item.get("start_time", 0.0) or 0.0) < end_sec
            and float(item.get("end_time", 0.0) or 0.0) > start_sec
        ]
        if not overlapping_items:
            continue

        avg_signal = sum(float(item.get("signal", 0.0) or 0.0) for item in overlapping_items) / len(overlapping_items)
        multimodal_bonus, multimodal_roles = _highlight_multimodal_bonus(
            start_sec,
            end_sec,
            multimodal_segment_hints=multimodal_segment_hints,
        )
        emphasis_bonus = min(0.36, 0.12 * len(highlighted_emphasis))
        longform_bonus = 0.08 if total_duration >= 20.0 else 0.0
        role_bonus = _CONTENT_KIND_ROLE_BONUS.get(content_kind, {}).get(role, 0.0)
        gameplay_bonus = 0.08 if skill_key == "gameplay_highlight" and role in {"hook", "detail", "body"} else 0.0

        score = (
            _ROLE_BASE_SCORE.get(role, 0.4)
            + min(0.46, avg_signal * 0.18)
            + emphasis_bonus
            + multimodal_bonus
            + role_bonus
            + gameplay_bonus
            + longform_bonus
        )
        if score < 0.9:
            continue

        candidate = {
            "index": len(ranked),
            "section_index": index,
            "role": role,
            "start_sec": start_sec,
            "end_sec": round(min(end_sec, start_sec + _HIGHLIGHT_MAX_WINDOW_SEC), 3),
            "duration_sec": round(min(window_duration, _HIGHLIGHT_MAX_WINDOW_SEC), 3),
            "score": round(min(score, 1.99), 3),
            "reasons": _highlight_reasons(
                role=role,
                avg_signal=avg_signal,
                emphasis_count=len(highlighted_emphasis),
                multimodal_roles=multimodal_roles,
            ),
            "source_item_indexes": [int(item.get("index", 0) or 0) for item in overlapping_items],
            "source_emphasis_indexes": list(range(len(highlighted_emphasis))),
        }
        ranked.append((float(candidate["score"]), candidate))

    chosen: list[dict[str, Any]] = []
    for _score, candidate in sorted(ranked, key=lambda item: (-item[0], float(item[1]["start_sec"]))):
        if any(_windows_overlap(candidate, existing) for existing in chosen):
            continue
        candidate["index"] = len(chosen)
        chosen.append(candidate)
        if len(chosen) >= max_count:
            break
    return chosen


def _highlight_multimodal_bonus(
    start_sec: float,
    end_sec: float,
    *,
    multimodal_segment_hints: list[dict[str, Any]] | None,
) -> tuple[float, list[str]]:
    best_bonus = 0.0
    matched_roles: list[str] = []
    for hint in list(multimodal_segment_hints or []):
        if not isinstance(hint, dict):
            continue
        hint_start = float(hint.get("start", 0.0) or 0.0)
        hint_end = float(hint.get("end", hint_start) or hint_start)
        overlap = max(0.0, min(end_sec, hint_end) - max(start_sec, hint_start))
        if overlap <= 0.0:
            continue
        role = str(hint.get("role") or "").strip().lower()
        matched_roles.append(role)
        keep_priority = str(hint.get("keep_priority") or "").strip().lower()
        confidence = float(hint.get("confidence", 0.0) or 0.0)
        if keep_priority == "high":
            best_bonus = max(best_bonus, 0.18 + min(0.14, confidence * 0.12))
        elif keep_priority == "medium":
            best_bonus = max(best_bonus, 0.08 + min(0.08, confidence * 0.08))
    return round(best_bonus, 3), sorted(set(role for role in matched_roles if role))


def _highlight_reasons(
    *,
    role: str,
    avg_signal: float,
    emphasis_count: int,
    multimodal_roles: list[str],
) -> list[str]:
    reasons: list[str] = [f"命中 {role or 'body'} 段候选窗口"]
    if avg_signal >= 1.4:
        reasons.append("字幕语义信号较强")
    if emphasis_count > 0:
        reasons.append("窗口内存在强调候选")
    if multimodal_roles:
        reasons.append(f"视频理解提示命中 {','.join(multimodal_roles[:2])}")
    return reasons


def _windows_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_start = float(left.get("start_sec", 0.0) or 0.0)
    left_end = float(left.get("end_sec", left_start) or left_start)
    right_start = float(right.get("start_sec", 0.0) or 0.0)
    right_end = float(right.get("end_sec", right_start) or right_start)
    return max(left_start, right_start) < min(left_end, right_end)
