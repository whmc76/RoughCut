from __future__ import annotations

import re
from typing import Any

STRATEGY_REVIEW_CONTEXT_SCHEMA_VERSION = "strategy_review_context.v1"

STRATEGY_REVIEW_CONTEXT_KEYS = (
    "strategy_review_gates",
    "strategy_storyboard_review",
    "strategy_timeline_preview",
)


def normalize_strategy_review_context(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    context = {
        key: dict(payload.get(key) or {})
        for key in STRATEGY_REVIEW_CONTEXT_KEYS
        if isinstance(payload.get(key), dict) and payload.get(key)
    }
    if context:
        context["schema"] = STRATEGY_REVIEW_CONTEXT_SCHEMA_VERSION
    return context


def strategy_review_context_from_profile(content_profile: dict[str, Any] | None) -> dict[str, Any]:
    profile = content_profile if isinstance(content_profile, dict) else {}
    return normalize_strategy_review_context(profile.get("strategy_review_context"))


def strategy_review_pipeline_plan(strategy_review_context: dict[str, Any] | None) -> dict[str, Any]:
    context = normalize_strategy_review_context(strategy_review_context)
    gates = context.get("strategy_review_gates")
    if not isinstance(gates, dict):
        return {}
    pipeline_plan = gates.get("pipeline_plan")
    return dict(pipeline_plan) if isinstance(pipeline_plan, dict) else {}


def strategy_review_gate_status(strategy_review_context: dict[str, Any] | None) -> dict[str, Any]:
    context = normalize_strategy_review_context(strategy_review_context)
    gates = context.get("strategy_review_gates")
    if not isinstance(gates, dict):
        return {}
    status = gates.get("review_gate_status")
    return dict(status) if isinstance(status, dict) else {}


def strategy_review_timeline_preview_windows(content_profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    context = strategy_review_context_from_profile(content_profile)
    if not _strategy_review_context_allows_material_insert_windows(context):
        return []
    timeline = context.get("strategy_timeline_preview")
    if not isinstance(timeline, dict):
        return []
    windows: list[dict[str, Any]] = []
    for index, segment in enumerate(list(timeline.get("segments") or [])):
        if not isinstance(segment, dict):
            continue
        bounds = _segment_time_bounds(segment)
        if bounds is None:
            continue
        start_sec, end_sec = bounds
        if end_sec <= start_sec:
            continue
        role = str(segment.get("role") or "timeline_preview").strip() or "timeline_preview"
        text = str(segment.get("text") or "").strip()
        windows.append(
            {
                "index": index,
                "role": role,
                "start_sec": start_sec,
                "end_sec": end_sec,
                "anchor_sec": _segment_anchor_sec(segment, start_sec=start_sec, end_sec=end_sec),
                "priority": _timeline_preview_window_priority(role),
                "packaging_intent": _timeline_preview_packaging_intent(role, text),
                "source": "strategy_timeline_preview",
                "segment_id": str(segment.get("segment_id") or f"preview_{index + 1}"),
            }
        )
    return windows


def _strategy_review_context_allows_material_insert_windows(context: dict[str, Any]) -> bool:
    pipeline_plan = strategy_review_pipeline_plan(context)
    strategy_type = str(pipeline_plan.get("strategy_type") or "").strip()
    enabled_features = {
        str(item or "").strip()
        for item in list(pipeline_plan.get("enabled_features") or [])
        if str(item or "").strip()
    }
    review_gates = {
        str(item or "").strip()
        for item in list(pipeline_plan.get("review_gates") or [])
        if str(item or "").strip()
    }
    return (
        strategy_type == "narrative_assembly"
        or "material_insert_plan" in enabled_features
        or "timeline_preview" in enabled_features
        or "timeline_preview_required" in review_gates
    )


def _segment_time_bounds(segment: dict[str, Any]) -> tuple[float, float] | None:
    start = _optional_float(segment.get("start_time", segment.get("start_sec")))
    end = _optional_float(segment.get("end_time", segment.get("end_sec")))
    if start is not None and end is not None:
        return max(0.0, start), max(0.0, end)
    timestamp = str(segment.get("timestamp") or segment.get("time_range") or "").strip()
    if not timestamp:
        return None
    matches = re.findall(r"(?:(\d{1,2}):)?(\d{1,2})(?::(\d{1,2}(?:\.\d+)?))?", timestamp)
    if len(matches) < 2:
        return None
    start_sec = _timestamp_match_to_seconds(matches[0])
    end_sec = _timestamp_match_to_seconds(matches[1])
    if start_sec is None or end_sec is None:
        return None
    return max(0.0, start_sec), max(0.0, end_sec)


def _segment_anchor_sec(segment: dict[str, Any], *, start_sec: float, end_sec: float) -> float:
    anchor = _optional_float(segment.get("anchor_sec", segment.get("broll_anchor_sec")))
    if anchor is None:
        anchor = (start_sec + end_sec) / 2.0
    return max(start_sec, min(float(anchor), end_sec))


def _timeline_preview_window_priority(role: str) -> float:
    role_key = str(role or "").strip().lower()
    if role_key in {"material_insert", "assembly", "broll", "supporting_material"}:
        return 0.92
    if role_key in {"evidence", "detail", "background"}:
        return 0.86
    return 0.78


def _timeline_preview_packaging_intent(role: str, text: str) -> str:
    role_key = str(role or "").strip().lower()
    text_key = str(text or "").strip().lower()
    if role_key in {"material_insert", "assembly", "broll", "supporting_material"}:
        return "strategy_timeline_material_insert"
    if any(token in text_key for token in ("素材", "原始", "插入", "画面", "broll", "b-roll")):
        return "strategy_timeline_material_insert"
    return "strategy_timeline_support"


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp_match_to_seconds(match: tuple[str, str, str]) -> float | None:
    hour_or_empty, minute_or_second, second_or_empty = match
    try:
        if second_or_empty:
            hours = int(hour_or_empty or 0)
            minutes = int(minute_or_second or 0)
            seconds = float(second_or_empty)
            return hours * 3600.0 + minutes * 60.0 + seconds
        return float(minute_or_second)
    except (TypeError, ValueError):
        return None
