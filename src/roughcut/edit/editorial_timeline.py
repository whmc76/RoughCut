from __future__ import annotations

import copy
from typing import Any


def normalize_keep_segments_payloads(
    segments: list[dict[str, Any]] | None,
    *,
    upper_bound: float | None = None,
    merge_gap_sec: float = 0.0,
    minimum_duration_sec: float = 0.0,
) -> list[dict[str, float]]:
    normalized: list[dict[str, float]] = []
    resolved_upper_bound = None if upper_bound is None else max(0.0, float(upper_bound or 0.0))
    for item in list(segments or []):
        if not isinstance(item, dict):
            continue
        try:
            start = max(0.0, float(item.get("start", 0.0) or 0.0))
            end = max(start, float(item.get("end", start) or start))
        except (TypeError, ValueError):
            continue
        if resolved_upper_bound is not None:
            start = min(start, resolved_upper_bound)
            end = min(end, resolved_upper_bound)
        if end <= start + float(minimum_duration_sec or 0.0):
            continue
        normalized.append({"start": round(start, 3), "end": round(end, 3)})
    normalized.sort(key=lambda segment: (segment["start"], segment["end"]))
    merged: list[dict[str, float]] = []
    for item in normalized:
        if not merged:
            merged.append(dict(item))
            continue
        previous = merged[-1]
        if item["start"] <= previous["end"] + max(0.0, float(merge_gap_sec or 0.0)):
            previous["end"] = round(max(previous["end"], item["end"]), 3)
            continue
        merged.append(dict(item))
    return merged


def editorial_keep_segments(payload: dict[str, Any] | None) -> list[dict[str, float]]:
    if not isinstance(payload, dict):
        return []
    return normalize_keep_segments_payloads(
        [
            item
            for item in list(payload.get("segments") or [])
            if isinstance(item, dict) and item.get("type") == "keep"
        ]
    )


def editorial_timeline_segments(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    return [
        copy.deepcopy(item)
        for item in list(payload.get("segments") or [])
        if isinstance(item, dict)
    ]


def editorial_cut_segments(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    return [
        copy.deepcopy(item)
        for item in list(payload.get("segments") or [])
        if isinstance(item, dict) and str(item.get("type") or "").strip() in {"cut", "remove"}
    ]


def editorial_timeline_subtitle_projection(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    subtitle_projection = payload.get("subtitle_projection")
    if not isinstance(subtitle_projection, dict):
        return None
    return copy.deepcopy(subtitle_projection)


def editorial_timeline_analysis(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return copy.deepcopy(payload.get("analysis") or {})


def build_editorial_segments_from_keep_segments(
    keep_segments: list[dict[str, Any]] | None,
    *,
    source_duration_sec: float,
    keep_reason: str = "manual_editor_keep",
    cut_reason: str = "manual_editor_removed",
) -> list[dict[str, Any]]:
    normalized_keep_segments = normalize_keep_segments_payloads(keep_segments)
    segments: list[dict[str, Any]] = []
    cursor = 0.0
    for keep_segment in normalized_keep_segments:
        start = float(keep_segment["start"])
        end = float(keep_segment["end"])
        if start > cursor + 1e-6:
            segments.append(
                {
                    "start": round(cursor, 3),
                    "end": round(start, 3),
                    "type": "cut",
                    "reason": cut_reason,
                }
            )
        segments.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "type": "keep",
                "reason": keep_reason,
            }
        )
        cursor = end
    resolved_source_duration = max(0.0, float(source_duration_sec or 0.0))
    if resolved_source_duration > cursor + 1e-6:
        segments.append(
            {
                "start": round(cursor, 3),
                "end": round(resolved_source_duration, 3),
                "type": "cut",
                "reason": cut_reason,
            }
        )
    return segments


def resolve_refine_keep_segments_for_timeline(
    payload: dict[str, Any] | None,
    *,
    editorial_timeline_id: str,
    editorial_timeline_version: int,
    fallback_segments: list[dict[str, Any]] | None = None,
) -> list[dict[str, float]]:
    plan = payload if isinstance(payload, dict) else {}
    payload_timeline_id = str(plan.get("editorial_timeline_id") or "").strip()
    payload_timeline_version = int(plan.get("editorial_timeline_version") or 0)
    if (
        payload_timeline_id == str(editorial_timeline_id or "").strip()
        and payload_timeline_version == int(editorial_timeline_version or 0)
    ):
        resolved = normalize_keep_segments_payloads(list(plan.get("keep_segments") or []))
        if resolved:
            return resolved
    return normalize_keep_segments_payloads(
        [
            item
            for item in list(fallback_segments or [])
            if isinstance(item, dict) and item.get("type") == "keep"
        ]
    )


def resolve_editorial_keep_segments(
    *,
    editorial_timeline_payload: dict[str, Any] | None,
    refine_plan_payload: dict[str, Any] | None = None,
    editorial_timeline_id: str | None = None,
    editorial_timeline_version: int | None = None,
    prefer_refine_plan: bool = True,
    upper_bound: float | None = None,
    merge_gap_sec: float = 0.0,
    minimum_duration_sec: float = 0.0,
) -> list[dict[str, float]]:
    if prefer_refine_plan and editorial_timeline_id is not None and editorial_timeline_version is not None:
        refine_resolved = resolve_refine_keep_segments_for_timeline(
            refine_plan_payload,
            editorial_timeline_id=str(editorial_timeline_id),
            editorial_timeline_version=int(editorial_timeline_version),
            fallback_segments=[],
        )
        if refine_resolved:
            return normalize_keep_segments_payloads(
                refine_resolved,
                upper_bound=upper_bound,
                merge_gap_sec=merge_gap_sec,
                minimum_duration_sec=minimum_duration_sec,
            )
    editorial_segments = [
        item
        for item in list((editorial_timeline_payload or {}).get("segments") or [])
        if isinstance(item, dict) and item.get("type") == "keep"
    ] if isinstance(editorial_timeline_payload, dict) else []
    return normalize_keep_segments_payloads(
        editorial_segments,
        upper_bound=upper_bound,
        merge_gap_sec=merge_gap_sec,
        minimum_duration_sec=minimum_duration_sec,
    )
