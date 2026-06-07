from __future__ import annotations

from typing import Any

from roughcut.edit.cut_analysis import CUT_ANALYSIS_SCHEMA_VERSION
from roughcut.edit.multimodal_trim_review import (
    multimodal_trim_review_auto_cut_candidates,
)
from roughcut.edit.smart_cut_rules import default_smart_cut_rules_payload, normalize_smart_cut_rules_payload


ARTIFACT_TYPE_REFINE_DECISION_PLAN = "refine_decision_plan"
REFINE_DECISION_PLAN_SCHEMA_VERSION = "refine_decision_plan.v1"


def _segment_payloads(segments: list[dict[str, Any]] | None) -> list[dict[str, float]]:
    payloads: list[dict[str, float]] = []
    for item in segments or []:
        if not isinstance(item, dict):
            continue
        try:
            start = max(0.0, float(item.get("start", 0.0) or 0.0))
            end = max(start, float(item.get("end", start) or start))
        except (TypeError, ValueError):
            continue
        payloads.append({"start": round(start, 3), "end": round(end, 3)})
    return payloads


def normalize_refine_keep_segments(payload: dict[str, Any] | None) -> list[dict[str, float]]:
    if not isinstance(payload, dict):
        return []
    return _segment_payloads(payload.get("keep_segments"))


def editorial_keep_segments(payload: dict[str, Any] | None) -> list[dict[str, float]]:
    if not isinstance(payload, dict):
        return []
    return _segment_payloads(
        [
            item
            for item in list(payload.get("segments") or [])
            if isinstance(item, dict) and item.get("type") == "keep"
        ]
    )


def _merge_segment_ranges(ranges: list[dict[str, float]]) -> list[dict[str, float]]:
    ordered = sorted(
        (
            {"start": float(item["start"]), "end": float(item["end"])}
            for item in ranges
            if float(item["end"]) > float(item["start"])
        ),
        key=lambda item: (item["start"], item["end"]),
    )
    merged: list[dict[str, float]] = []
    for item in ordered:
        if not merged or item["start"] > merged[-1]["end"] + 1e-6:
            merged.append(item)
            continue
        merged[-1]["end"] = max(merged[-1]["end"], item["end"])
    return [{"start": round(item["start"], 3), "end": round(item["end"], 3)} for item in merged]


def _apply_remove_ranges_to_keep_segments(
    keep_segments: list[dict[str, Any]] | None,
    remove_ranges: list[dict[str, Any]] | None,
) -> list[dict[str, float]]:
    keep_ranges = _merge_segment_ranges(_segment_payloads(keep_segments))
    remove_payloads = _merge_segment_ranges(_segment_payloads(remove_ranges))
    if not keep_ranges or not remove_payloads:
        return keep_ranges
    resolved: list[dict[str, float]] = []
    for keep in keep_ranges:
        keep_start = float(keep["start"])
        keep_end = float(keep["end"])
        cursor = keep_start
        for removal in remove_payloads:
            remove_start = max(keep_start, float(removal["start"]))
            remove_end = min(keep_end, float(removal["end"]))
            if remove_end <= cursor + 1e-6:
                continue
            if remove_start >= keep_end - 1e-6:
                break
            if remove_start > cursor + 0.02:
                resolved.append({"start": round(cursor, 3), "end": round(remove_start, 3)})
            cursor = max(cursor, remove_end)
            if cursor >= keep_end - 0.02:
                break
        if cursor < keep_end - 0.02:
            resolved.append({"start": round(cursor, 3), "end": round(keep_end, 3)})
    return _merge_segment_ranges(resolved)


def _multimodal_auto_refine_keep_segments(
    keep_segments: list[dict[str, Any]] | None,
    cut_analysis: dict[str, Any] | None,
    *,
    mode: str,
) -> tuple[list[dict[str, float]], int]:
    base_keep_segments = _segment_payloads(keep_segments)
    if str(mode or "").strip() != "auto_refine":
        return base_keep_segments, 0
    auto_cut_candidates = multimodal_trim_review_auto_cut_candidates(cut_analysis)
    if not auto_cut_candidates:
        return base_keep_segments, 0
    remove_ranges = [
        {"start": float(item.get("start", 0.0) or 0.0), "end": float(item.get("end", 0.0) or 0.0)}
        for item in auto_cut_candidates
    ]
    return _apply_remove_ranges_to_keep_segments(base_keep_segments, remove_ranges), len(auto_cut_candidates)


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
    if payload_timeline_id == str(editorial_timeline_id or "").strip() and payload_timeline_version == int(editorial_timeline_version or 0):
        resolved = normalize_refine_keep_segments(plan)
        if resolved:
            return resolved
    return editorial_keep_segments({"segments": list(fallback_segments or [])})


def refine_plan_audio_defaults(render_plan_data: dict[str, Any] | None) -> dict[str, Any]:
    payload = render_plan_data if isinstance(render_plan_data, dict) else {}
    return {
        **dict(payload.get("loudness") or {}),
        **dict(payload.get("voice_processing") or {}),
    }


def build_refine_decision_plan_payload(
    *,
    keep_segments: list[dict[str, Any]] | None,
    source_duration_sec: float,
    mode: str,
    subtitle_fingerprint: str | None = None,
    render_plan_version: int | None = None,
    cut_analysis: dict[str, Any] | None = None,
    audio_defaults: dict[str, Any] | None = None,
    video_transform: dict[str, Any] | None = None,
    smart_cut_rules: dict[str, Any] | None = None,
    note: str | None = None,
    editorial_timeline_id: str | None = None,
    editorial_timeline_version: int | None = None,
) -> dict[str, Any]:
    analysis = cut_analysis if isinstance(cut_analysis, dict) else {}
    resolved_keep_segments, multimodal_auto_apply_cut_count = _multimodal_auto_refine_keep_segments(
        keep_segments,
        analysis,
        mode=mode,
    )
    auto_count = int(analysis.get("auto_apply_candidate_count") or 0)
    manual_count = int(analysis.get("manual_confirm_candidate_count") or 0)
    return {
        "schema": REFINE_DECISION_PLAN_SCHEMA_VERSION,
        "mode": str(mode or "manual_refine"),
        "source_duration_sec": round(max(0.0, float(source_duration_sec or 0.0)), 3),
        "subtitle_fingerprint": str(subtitle_fingerprint or "").strip() or None,
        "render_plan_version": render_plan_version,
        "editorial_timeline_id": str(editorial_timeline_id or "").strip() or None,
        "editorial_timeline_version": editorial_timeline_version,
        "keep_segments": resolved_keep_segments,
        "candidate_summary": {
            "total": int(analysis.get("candidate_count") or (auto_count + manual_count)),
            "auto_apply": auto_count,
            "manual_confirm": manual_count,
            "multimodal_auto_apply": multimodal_auto_apply_cut_count,
            "analysis_schema": str(analysis.get("schema") or CUT_ANALYSIS_SCHEMA_VERSION),
        },
        "multimodal_auto_apply_cut_count": multimodal_auto_apply_cut_count,
        "multimodal_trim_review_summary": dict(analysis.get("multimodal_trim_review_summary") or {}),
        "audio_defaults": dict(audio_defaults or {}),
        "video_transform": dict(video_transform or {}),
        "smart_cut_rules": normalize_smart_cut_rules_payload(smart_cut_rules)
        if smart_cut_rules is not None
        else default_smart_cut_rules_payload(),
        "note": str(note or "").strip() or None,
    }


def build_refine_decision_plan_from_render_plan(
    *,
    keep_segments: list[dict[str, Any]] | None,
    source_duration_sec: float,
    mode: str,
    subtitle_fingerprint: str | None = None,
    render_plan_data: dict[str, Any] | None = None,
    render_plan_version: int | None = None,
    cut_analysis: dict[str, Any] | None = None,
    video_transform: dict[str, Any] | None = None,
    smart_cut_rules: dict[str, Any] | None = None,
    note: str | None = None,
    editorial_timeline_id: str | None = None,
    editorial_timeline_version: int | None = None,
) -> dict[str, Any]:
    return build_refine_decision_plan_payload(
        keep_segments=keep_segments,
        source_duration_sec=source_duration_sec,
        mode=mode,
        subtitle_fingerprint=subtitle_fingerprint,
        render_plan_version=render_plan_version,
        cut_analysis=cut_analysis,
        audio_defaults=refine_plan_audio_defaults(render_plan_data),
        video_transform=video_transform,
        smart_cut_rules=smart_cut_rules,
        note=note,
        editorial_timeline_id=editorial_timeline_id,
        editorial_timeline_version=editorial_timeline_version,
    )
