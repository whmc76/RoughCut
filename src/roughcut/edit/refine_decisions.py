from __future__ import annotations

from typing import Any

from roughcut.edit.cut_analysis import CUT_ANALYSIS_SCHEMA_VERSION
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
        "keep_segments": _segment_payloads(keep_segments),
        "candidate_summary": {
            "total": int(analysis.get("candidate_count") or (auto_count + manual_count)),
            "auto_apply": auto_count,
            "manual_confirm": manual_count,
            "analysis_schema": str(analysis.get("schema") or CUT_ANALYSIS_SCHEMA_VERSION),
        },
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
