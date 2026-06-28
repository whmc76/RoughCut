from __future__ import annotations

from typing import Any

from roughcut.edit.cut_analysis import CUT_ANALYSIS_SCHEMA_VERSION, cut_analysis_refine_auto_cut_candidates
from roughcut.edit.editorial_timeline import (
    normalize_keep_segments_payloads,
    resolve_refine_keep_segments_for_timeline as resolve_refine_keep_segments_for_timeline,
)
from roughcut.edit.multimodal_trim_review import (
    multimodal_trim_review_auto_cut_candidates,
)
from roughcut.edit.smart_cut_rules import default_smart_cut_rules_payload, normalize_smart_cut_rules_payload
from roughcut.edit.strategy_profile import (
    DEFAULT_STRATEGY_TYPE,
    normalize_strategy_profile_payload,
    normalize_strategy_type,
    payload_strategy_profile,
)


ARTIFACT_TYPE_REFINE_DECISION_PLAN = "refine_decision_plan"
REFINE_DECISION_PLAN_SCHEMA_VERSION = "refine_decision_plan.v1"

def normalize_refine_keep_segments(payload: dict[str, Any] | None) -> list[dict[str, float]]:
    if not isinstance(payload, dict):
        return []
    return normalize_keep_segments_payloads(list(payload.get("keep_segments") or []))


def normalize_refine_decision_plan_strategy_metadata(
    payload: dict[str, Any] | None,
    *,
    cut_analysis: dict[str, Any] | None = None,
    default_strategy_type: Any = DEFAULT_STRATEGY_TYPE,
) -> dict[str, Any]:
    plan = dict(payload or {}) if isinstance(payload, dict) else {}
    normalized_strategy_profile = normalize_strategy_profile_payload(
        plan.get("strategy_profile")
        if isinstance(plan.get("strategy_profile"), dict)
        else payload_strategy_profile(cut_analysis, default_strategy_type=default_strategy_type),
        default_strategy_type=plan.get("strategy_type")
        or (cut_analysis or {}).get("strategy_type")
        or default_strategy_type,
    )
    plan["strategy_profile"] = normalized_strategy_profile
    plan["strategy_type"] = normalize_strategy_type(
        plan.get("strategy_type")
        or normalized_strategy_profile.get("strategy_type")
        or (cut_analysis or {}).get("strategy_type")
        or default_strategy_type
    )
    return plan


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
    keep_ranges = _merge_segment_ranges(normalize_keep_segments_payloads(keep_segments))
    remove_payloads = _merge_segment_ranges(normalize_keep_segments_payloads(remove_ranges))
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


def _has_authoritative_accepted_cut_contract(cut_analysis: dict[str, Any] | None) -> bool:
    return isinstance(cut_analysis, dict) and ("accepted_cuts" in cut_analysis or "accepted_cut_count" in cut_analysis)


def _multimodal_auto_refine_keep_segments(
    keep_segments: list[dict[str, Any]] | None,
    cut_analysis: dict[str, Any] | None,
    *,
    mode: str,
) -> tuple[list[dict[str, float]], int]:
    base_keep_segments = normalize_keep_segments_payloads(keep_segments)
    if str(mode or "").strip() != "auto_refine":
        return base_keep_segments, 0
    if _has_authoritative_accepted_cut_contract(cut_analysis):
        return base_keep_segments, 0
    auto_cut_candidates = multimodal_trim_review_auto_cut_candidates(cut_analysis)
    if not auto_cut_candidates:
        return base_keep_segments, 0
    remove_ranges = [
        {"start": float(item.get("start", 0.0) or 0.0), "end": float(item.get("end", 0.0) or 0.0)}
        for item in auto_cut_candidates
    ]
    return _apply_remove_ranges_to_keep_segments(base_keep_segments, remove_ranges), len(auto_cut_candidates)


def _rule_auto_refine_keep_segments(
    keep_segments: list[dict[str, Any]] | None,
    cut_analysis: dict[str, Any] | None,
    *,
    mode: str,
) -> tuple[list[dict[str, float]], int]:
    base_keep_segments = normalize_keep_segments_payloads(keep_segments)
    if str(mode or "").strip() != "auto_refine":
        return base_keep_segments, 0
    auto_rule_candidates = cut_analysis_refine_auto_cut_candidates(cut_analysis)
    if not auto_rule_candidates:
        return base_keep_segments, 0
    remove_ranges = [
        {"start": float(item.get("start", 0.0) or 0.0), "end": float(item.get("end", 0.0) or 0.0)}
        for item in auto_rule_candidates
    ]
    return _apply_remove_ranges_to_keep_segments(base_keep_segments, remove_ranges), len(auto_rule_candidates)

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
    strategy_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis = cut_analysis if isinstance(cut_analysis, dict) else {}
    normalized_strategy_profile = normalize_strategy_profile_payload(
        strategy_profile if isinstance(strategy_profile, dict) else payload_strategy_profile(analysis),
        default_strategy_type=analysis.get("strategy_type") or DEFAULT_STRATEGY_TYPE,
    )
    strategy_type = normalize_strategy_type(
        normalized_strategy_profile.get("strategy_type") or analysis.get("strategy_type") or DEFAULT_STRATEGY_TYPE
    )
    resolved_keep_segments, rule_auto_apply_cut_count = _rule_auto_refine_keep_segments(
        keep_segments,
        analysis,
        mode=mode,
    )
    resolved_keep_segments, multimodal_auto_apply_cut_count = _multimodal_auto_refine_keep_segments(
        resolved_keep_segments,
        analysis,
        mode=mode,
    )
    auto_count = int(analysis.get("auto_apply_candidate_count") or 0)
    manual_count = int(analysis.get("manual_confirm_candidate_count") or 0)
    candidate_risk_summary = (
        dict(analysis.get("candidate_risk_summary") or {})
        if isinstance(analysis.get("candidate_risk_summary"), dict)
        else {}
    )
    return {
        "schema": REFINE_DECISION_PLAN_SCHEMA_VERSION,
        "mode": str(mode or "manual_refine"),
        "source_duration_sec": round(max(0.0, float(source_duration_sec or 0.0)), 3),
        "subtitle_fingerprint": str(subtitle_fingerprint or "").strip() or None,
        "render_plan_version": render_plan_version,
        "editorial_timeline_id": str(editorial_timeline_id or "").strip() or None,
        "editorial_timeline_version": editorial_timeline_version,
        "strategy_type": strategy_type,
        "strategy_profile": normalized_strategy_profile,
        "keep_segments": resolved_keep_segments,
        "candidate_summary": {
            "total": int(analysis.get("candidate_count") or (auto_count + manual_count)),
            "auto_apply": auto_count,
            "manual_confirm": manual_count,
            "rule_auto_apply": rule_auto_apply_cut_count,
            "multimodal_auto_apply": multimodal_auto_apply_cut_count,
            "analysis_schema": str(analysis.get("schema") or CUT_ANALYSIS_SCHEMA_VERSION),
            "risk_levels": candidate_risk_summary,
        },
        "rule_auto_apply_cut_count": rule_auto_apply_cut_count,
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
    audio_defaults: dict[str, Any] | None = None,
    video_transform: dict[str, Any] | None = None,
    smart_cut_rules: dict[str, Any] | None = None,
    note: str | None = None,
    editorial_timeline_id: str | None = None,
    editorial_timeline_version: int | None = None,
    strategy_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_refine_decision_plan_payload(
        keep_segments=keep_segments,
        source_duration_sec=source_duration_sec,
        mode=mode,
        subtitle_fingerprint=subtitle_fingerprint,
        render_plan_version=render_plan_version,
        cut_analysis=cut_analysis,
        audio_defaults=(
            dict(audio_defaults)
            if isinstance(audio_defaults, dict)
            else refine_plan_audio_defaults(render_plan_data)
        ),
        video_transform=video_transform,
        smart_cut_rules=smart_cut_rules,
        note=note,
        editorial_timeline_id=editorial_timeline_id,
        editorial_timeline_version=editorial_timeline_version,
        strategy_profile=strategy_profile,
    )
