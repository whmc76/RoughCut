from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from roughcut.edit.strategy_review_context import (
    normalize_strategy_review_context,
    strategy_review_pipeline_plan,
)


STRATEGY_RENDER_VALIDATION_SCHEMA_VERSION = "strategy_render_validation.v1"


def projection_output_fallback_reasons(
    diagnostics: Mapping[str, Any] | None,
    *,
    include_refresh_required: bool = False,
) -> list[str]:
    payload = diagnostics if isinstance(diagnostics, Mapping) else {}
    reasons: list[str] = []
    if bool(payload.get("rebuilt_from_canonical_fallback")):
        reasons.append("subtitle_projection_rebuilt_from_canonical_fallback")
    if bool(payload.get("source_projection_fallback_applied")):
        reasons.append("subtitle_projection_source_fallback_applied")
    if bool(
        payload.get("projection_validation_fallback_used")
        or payload.get("fallback_used")
    ):
        reasons.append("subtitle_projection_validation_fallback_used")
    if include_refresh_required and bool(payload.get("projection_refresh_required")):
        reasons.append("subtitle_projection_refresh_required")
    return _dedupe(reasons)


def insert_plan_output_fallback_reasons(insert_plan: Mapping[str, Any] | None) -> list[str]:
    payload = insert_plan if isinstance(insert_plan, Mapping) else {}
    selection_source = str(payload.get("selection_source") or "").strip().lower()
    if selection_source == "deterministic_fallback":
        return ["insert_slot_deterministic_fallback"]
    return []


def platform_packaging_output_fallback_reasons(
    packaging: Mapping[str, Any] | None,
    *,
    renderless_mode: bool = False,
) -> list[str]:
    payload = packaging if isinstance(packaging, Mapping) else {}
    reasons: list[str] = []
    generation_mode = str(payload.get("generation_mode") or "").strip().lower()
    if renderless_mode or generation_mode == "renderless_copy_only":
        reasons.append("platform_packaging_renderless_only")
    for item in payload.get("generation_repair_trace") or []:
        if not isinstance(item, Mapping):
            continue
        status = str(item.get("status") or "").strip().lower()
        if "fallback" in status:
            reasons.append(f"platform_packaging_{status}")
    reasons.extend(
        projection_output_fallback_reasons(
            payload.get("subtitle_projection_repair"),
            include_refresh_required=False,
        )
    )
    return _dedupe(reasons)


def render_output_blocking_reasons(
    *,
    avatar_result: Mapping[str, Any] | None,
    subtitle_projection_repair: Mapping[str, Any] | None,
    strategy_review_context: Mapping[str, Any] | None = None,
    render_plan: Mapping[str, Any] | None = None,
    cut_boundary_evidence: Mapping[str, Any] | None = None,
) -> list[str]:
    del avatar_result
    reasons = projection_output_fallback_reasons(
        subtitle_projection_repair,
        include_refresh_required=False,
    )
    reasons.extend(
        strategy_render_validation_blocking_reasons(
            strategy_review_context,
            render_plan=render_plan,
            cut_boundary_evidence=cut_boundary_evidence,
        )
    )
    return _dedupe(reasons)


def strategy_timeline_preview_validation(
    strategy_review_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    context = normalize_strategy_review_context(strategy_review_context)
    pipeline_plan = strategy_review_pipeline_plan(context)
    review_gates = _string_set(pipeline_plan.get("review_gates"))
    strategy_policy = (
        pipeline_plan.get("strategy_policy")
        if isinstance(pipeline_plan.get("strategy_policy"), Mapping)
        else {}
    )
    render_validation_policy = (
        strategy_policy.get("render_validation_policy")
        if isinstance(strategy_policy.get("render_validation_policy"), Mapping)
        else {}
    )
    required = bool(
        "timeline_preview_required" in review_gates
        or render_validation_policy.get("check_timeline_preview_alignment")
    )
    timeline_preview = (
        context.get("strategy_timeline_preview")
        if isinstance(context.get("strategy_timeline_preview"), Mapping)
        else {}
    )
    segments = [
        segment
        for segment in list(timeline_preview.get("segments") or [])
        if isinstance(segment, Mapping)
    ]
    payload = {
        "schema": STRATEGY_RENDER_VALIDATION_SCHEMA_VERSION,
        "check": "strategy_timeline_preview_alignment",
        "strategy_type": str(pipeline_plan.get("strategy_type") or "").strip(),
        "review_gates": sorted(review_gates),
        "required": required,
        "segment_count": len(segments),
        "blocking": False,
        "status": "not_required",
    }
    if not required:
        return payload
    if segments:
        payload["status"] = "ok"
        return payload
    payload.update(
        {
            "status": "blocking",
            "blocking": True,
            "reason": "strategy_timeline_preview_missing",
        }
    )
    return payload


def strategy_storyboard_validation(
    strategy_review_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    context = normalize_strategy_review_context(strategy_review_context)
    pipeline_plan = strategy_review_pipeline_plan(context)
    review_gates = _string_set(pipeline_plan.get("review_gates"))
    strategy_policy = (
        pipeline_plan.get("strategy_policy")
        if isinstance(pipeline_plan.get("strategy_policy"), Mapping)
        else {}
    )
    render_validation_policy = (
        strategy_policy.get("render_validation_policy")
        if isinstance(strategy_policy.get("render_validation_policy"), Mapping)
        else {}
    )
    required = bool(
        "storyboard_review_required" in review_gates
        or render_validation_policy.get("check_storyboard_alignment")
    )
    storyboard = (
        context.get("strategy_storyboard_review")
        if isinstance(context.get("strategy_storyboard_review"), Mapping)
        else {}
    )
    panels = [
        panel
        for panel in list(storyboard.get("panels") or [])
        if isinstance(panel, Mapping)
    ]
    payload = {
        "schema": STRATEGY_RENDER_VALIDATION_SCHEMA_VERSION,
        "check": "strategy_storyboard_alignment",
        "strategy_type": str(pipeline_plan.get("strategy_type") or "").strip(),
        "review_gates": sorted(review_gates),
        "required": required,
        "panel_count": len(panels),
        "blocking": False,
        "status": "not_required",
    }
    if not required:
        return payload
    if panels:
        payload["status"] = "ok"
        return payload
    payload.update(
        {
            "status": "blocking",
            "blocking": True,
            "reason": "strategy_storyboard_review_missing",
        }
    )
    return payload


def strategy_render_validation_summary(
    strategy_review_context: Mapping[str, Any] | None,
    *,
    render_plan: Mapping[str, Any] | None = None,
    cut_boundary_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    checks = [
        strategy_timeline_preview_validation(strategy_review_context),
        strategy_storyboard_validation(strategy_review_context),
        strategy_overlay_subtitle_occlusion_validation(
            strategy_review_context,
            render_plan=render_plan,
        ),
        strategy_cut_boundary_validation(
            strategy_review_context,
            cut_boundary_evidence=cut_boundary_evidence,
        ),
    ]
    blocking_checks = [check for check in checks if bool(check.get("blocking"))]
    required_checks = [check for check in checks if bool(check.get("required"))]
    primary = blocking_checks[0] if blocking_checks else (required_checks[0] if required_checks else checks[0])
    blocking_reasons = [
        str(check.get("reason") or "").strip()
        for check in blocking_checks
        if str(check.get("reason") or "").strip()
    ]
    payload = {
        "schema": STRATEGY_RENDER_VALIDATION_SCHEMA_VERSION,
        "check": str(primary.get("check") or "strategy_render_validation"),
        "strategy_type": str(primary.get("strategy_type") or "").strip(),
        "review_gates": list(primary.get("review_gates") or []),
        "required": bool(required_checks),
        "blocking": bool(blocking_checks),
        "status": "blocking" if blocking_checks else ("ok" if required_checks else "not_required"),
        "checks": checks,
        "blocking_reasons": blocking_reasons,
        "segment_count": int(checks[0].get("segment_count") or 0),
        "panel_count": int(checks[1].get("panel_count") or 0),
        "overlay_count": int(checks[2].get("overlay_count") or 0),
        "unsafe_overlay_count": int(checks[2].get("unsafe_overlay_count") or 0),
        "accepted_cut_count": int(checks[3].get("accepted_cut_count") or 0),
        "high_risk_cut_count": int(checks[3].get("high_risk_cut_count") or 0),
        "blocking_high_risk_cut_count": int(checks[3].get("blocking_high_risk_cut_count") or 0),
        "boundary_energy_evidence_count": int(checks[3].get("boundary_energy_evidence_count") or 0),
        "boundary_frame_sample_count": int(checks[3].get("boundary_frame_sample_count") or 0),
        "boundary_waveform_sample_count": int(checks[3].get("boundary_waveform_sample_count") or 0),
    }
    if blocking_reasons:
        payload["reason"] = blocking_reasons[0]
    return payload


def strategy_cut_boundary_validation(
    strategy_review_context: Mapping[str, Any] | None,
    *,
    cut_boundary_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    context = normalize_strategy_review_context(strategy_review_context)
    pipeline_plan = strategy_review_pipeline_plan(context)
    review_gates = _string_set(pipeline_plan.get("review_gates"))
    strategy_policy = (
        pipeline_plan.get("strategy_policy")
        if isinstance(pipeline_plan.get("strategy_policy"), Mapping)
        else {}
    )
    render_validation_policy = (
        strategy_policy.get("render_validation_policy")
        if isinstance(strategy_policy.get("render_validation_policy"), Mapping)
        else {}
    )
    required = bool(
        render_validation_policy.get("check_cut_boundaries")
        or render_validation_policy.get("check_highlight_boundary_frames")
    )
    payload = {
        "schema": STRATEGY_RENDER_VALIDATION_SCHEMA_VERSION,
        "check": "strategy_cut_boundary_evidence",
        "strategy_type": str(pipeline_plan.get("strategy_type") or "").strip(),
        "review_gates": sorted(review_gates),
        "required": required,
        "accepted_cut_count": 0,
        "high_risk_cut_count": 0,
        "blocking_high_risk_cut_count": 0,
        "boundary_energy_evidence_count": 0,
        "boundary_frame_sample_count": 0,
        "boundary_waveform_sample_count": 0,
        "blocking": False,
        "status": "not_required",
    }
    if not required:
        return payload
    if not isinstance(cut_boundary_evidence, Mapping) or not cut_boundary_evidence:
        payload["status"] = "not_evaluated"
        return payload

    cut_summary = (
        cut_boundary_evidence.get("cut_analysis_summary")
        if isinstance(cut_boundary_evidence.get("cut_analysis_summary"), Mapping)
        else {}
    )
    high_risk_cuts = [
        cut
        for cut in list(cut_boundary_evidence.get("high_risk_cuts") or [])
        if isinstance(cut, Mapping)
    ]
    explicit_blocking_count = _optional_int(cut_boundary_evidence.get("blocking_high_risk_cut_count"))
    blocking_high_risk_cut_count = (
        explicit_blocking_count
        if explicit_blocking_count is not None
        else len(
            [
                cut
                for cut in high_risk_cuts
                if cut.get("blocking") is not False
                and str(cut.get("review_priority") or "blocking") != "advisory"
            ]
        )
    )
    accepted_cut_count = _optional_int(cut_summary.get("accepted_cut_count")) or 0
    boundary_energy_evidence_count = len(
        [
            cut
            for cut in high_risk_cuts
            if _optional_float(cut.get("boundary_keep_energy")) is not None
        ]
    )
    frame_sample_count, waveform_sample_count = _cut_boundary_sample_counts(cut_boundary_evidence)
    payload.update(
        {
            "accepted_cut_count": accepted_cut_count,
            "high_risk_cut_count": len(high_risk_cuts),
            "blocking_high_risk_cut_count": blocking_high_risk_cut_count,
            "boundary_energy_evidence_count": boundary_energy_evidence_count,
            "boundary_frame_sample_count": frame_sample_count,
            "boundary_waveform_sample_count": waveform_sample_count,
            "status": "ok",
        }
    )
    if blocking_high_risk_cut_count > 0:
        payload.update(
            {
                "status": "blocking",
                "blocking": True,
                "reason": "strategy_cut_boundary_high_risk_unresolved",
            }
        )
    highlight_frame_samples_required = bool(render_validation_policy.get("check_highlight_boundary_frames"))
    if (
        highlight_frame_samples_required
        and not bool(payload.get("blocking"))
        and frame_sample_count <= 0
        and (accepted_cut_count > 0 or high_risk_cuts)
    ):
        payload.update(
            {
                "status": "blocking",
                "blocking": True,
                "reason": "strategy_cut_boundary_frame_samples_missing",
            }
        )
    return payload


def strategy_overlay_subtitle_occlusion_validation(
    strategy_review_context: Mapping[str, Any] | None,
    *,
    render_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    context = normalize_strategy_review_context(strategy_review_context)
    pipeline_plan = strategy_review_pipeline_plan(context)
    review_gates = _string_set(pipeline_plan.get("review_gates"))
    strategy_policy = (
        pipeline_plan.get("strategy_policy")
        if isinstance(pipeline_plan.get("strategy_policy"), Mapping)
        else {}
    )
    render_validation_policy = (
        strategy_policy.get("render_validation_policy")
        if isinstance(strategy_policy.get("render_validation_policy"), Mapping)
        else {}
    )
    required = bool(render_validation_policy.get("check_overlay_subtitle_occlusion"))
    payload = {
        "schema": STRATEGY_RENDER_VALIDATION_SCHEMA_VERSION,
        "check": "strategy_overlay_subtitle_occlusion",
        "strategy_type": str(pipeline_plan.get("strategy_type") or "").strip(),
        "review_gates": sorted(review_gates),
        "required": required,
        "subtitle_track_present": False,
        "overlay_count": 0,
        "unsafe_overlay_count": 0,
        "blocking": False,
        "status": "not_required",
    }
    if not required:
        return payload
    if not isinstance(render_plan, Mapping) or not render_plan:
        payload["status"] = "not_evaluated"
        return payload

    packaging_timeline = _render_plan_packaging_timeline(render_plan)
    subtitles = (
        packaging_timeline.get("subtitles")
        if isinstance(packaging_timeline.get("subtitles"), Mapping)
        else render_plan.get("subtitles")
    )
    editing_accents = (
        packaging_timeline.get("editing_accents")
        if isinstance(packaging_timeline.get("editing_accents"), Mapping)
        else render_plan.get("editing_accents")
    )
    subtitle_track_present = bool(isinstance(subtitles, Mapping) and subtitles)
    overlays = [
        overlay
        for overlay in list((editing_accents or {}).get("emphasis_overlays") or [])
        if isinstance(overlay, Mapping) and str(overlay.get("text") or "").strip()
    ]
    unsafe_overlays = [
        overlay
        for overlay in overlays
        if not _overlay_subtitle_safe(overlay)
    ]
    payload.update(
        {
            "subtitle_track_present": subtitle_track_present,
            "overlay_count": len(overlays),
            "unsafe_overlay_count": len(unsafe_overlays),
            "status": "ok",
        }
    )
    if subtitle_track_present and unsafe_overlays:
        payload.update(
            {
                "status": "blocking",
                "blocking": True,
                "reason": "strategy_overlay_subtitle_occlusion_unverified",
            }
        )
    return payload


def strategy_render_validation_blocking_reasons(
    strategy_review_context: Mapping[str, Any] | None,
    *,
    render_plan: Mapping[str, Any] | None = None,
    cut_boundary_evidence: Mapping[str, Any] | None = None,
) -> list[str]:
    validation = strategy_render_validation_summary(
        strategy_review_context,
        render_plan=render_plan,
        cut_boundary_evidence=cut_boundary_evidence,
    )
    reasons = [
        str(item or "").strip()
        for item in list(validation.get("blocking_reasons") or [])
        if str(item or "").strip()
    ]
    if reasons:
        return _dedupe(reasons)
    if bool(validation.get("blocking")):
        reason = str(validation.get("reason") or "").strip()
        return [reason] if reason else ["strategy_render_validation_blocked"]
    return []


def _render_plan_packaging_timeline(render_plan: Mapping[str, Any]) -> dict[str, Any]:
    packaging_timeline = render_plan.get("packaging_timeline")
    if isinstance(packaging_timeline, Mapping):
        return dict(packaging_timeline)
    return dict(render_plan)


def _overlay_subtitle_safe(overlay: Mapping[str, Any]) -> bool:
    if bool(overlay.get("subtitle_safe")):
        return True
    safe_zone = str(overlay.get("safe_zone") or "").strip().lower()
    if safe_zone in {"top", "upper", "upper_third", "top_center", "upper_left", "upper_right", "above_subtitles"}:
        return True
    placement = str(overlay.get("placement") or overlay.get("position") or "").strip().lower()
    if placement in {"top", "upper", "top_center", "upper_left", "upper_right", "left_upper", "right_upper"}:
        return True
    treatment = str(overlay.get("visual_treatment") or "").strip().lower()
    if treatment in {"hook_pop", "keyword_sticker", "beat_pulse", "keyword_pop"}:
        return True
    y_ratio = _optional_float(overlay.get("y_ratio"))
    return y_ratio is not None and y_ratio <= 0.4


def _optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _cut_boundary_sample_counts(cut_boundary_evidence: Mapping[str, Any]) -> tuple[int, int]:
    sample_sources: list[Mapping[str, Any]] = [cut_boundary_evidence]
    sample_manifest = cut_boundary_evidence.get("cut_boundary_sample_manifest")
    if isinstance(sample_manifest, Mapping):
        sample_sources.append(sample_manifest)
    sample_manifest = cut_boundary_evidence.get("boundary_sample_manifest")
    if isinstance(sample_manifest, Mapping):
        sample_sources.append(sample_manifest)

    frame_count = 0
    waveform_count = 0
    for source in sample_sources:
        samples = [
            item
            for item in list(source.get("boundary_samples") or source.get("samples") or [])
            if isinstance(item, Mapping)
        ]
        for sample in samples:
            frame_paths = [
                str(item or "").strip()
                for item in list(sample.get("frame_paths") or sample.get("frames") or [])
                if str(item or "").strip()
            ]
            if frame_paths or str(sample.get("frame_path") or "").strip():
                frame_count += max(1, len(frame_paths))
            waveform_paths = [
                str(item or "").strip()
                for item in list(sample.get("waveform_paths") or [])
                if str(item or "").strip()
            ]
            if (
                waveform_paths
                or str(sample.get("waveform_path") or "").strip()
                or isinstance(sample.get("waveform_peaks"), Mapping)
                or isinstance(sample.get("waveform_window"), Mapping)
            ):
                waveform_count += max(1, len(waveform_paths))
    return frame_count, waveform_count


def creator_refine_output_fallback_reasons(
    refine_meta: Mapping[str, Any] | None,
) -> list[str]:
    payload = refine_meta if isinstance(refine_meta, Mapping) else {}
    source = str(payload.get("source") or "").strip().lower()
    if source and source != "llm":
        return [f"creator_refine_{source}"]
    return []


def intelligent_copy_cover_brief_fallback_reasons(
    cover_brief: Mapping[str, Any] | None,
) -> list[str]:
    payload = cover_brief if isinstance(cover_brief, Mapping) else {}
    source = str(payload.get("strategy_source") or "").strip().lower()
    if source and source != "llm":
        return [f"intelligent_copy_cover_brief_{source}"]
    return []


def intelligent_copy_material_context_fallback_reasons(
    *,
    packaging: Mapping[str, Any] | None,
    cover_brief: Mapping[str, Any] | None,
) -> list[str]:
    reasons = platform_packaging_output_fallback_reasons(
        packaging,
        renderless_mode=False,
    )
    reasons.extend(intelligent_copy_cover_brief_fallback_reasons(cover_brief))
    return _dedupe(reasons)


def _runtime_result_blocking_reasons(
    label: str,
    payload: Mapping[str, Any] | None,
) -> list[str]:
    data = payload if isinstance(payload, Mapping) else {}
    status = str(data.get("status") or "").strip().lower()
    fallback_generated = bool(data.get("fallback_generated"))
    if status not in {"degraded", "failed", "blocked"} and not fallback_generated:
        return []
    reason = str(data.get("reason") or ("fallback_generated" if fallback_generated else status)).strip().lower()
    if fallback_generated and not reason:
        reason = "fallback_generated"
    return [f"{label}_{reason}"]


def _string_set(items: Any) -> set[str]:
    return {
        str(item or "").strip()
        for item in list(items or [])
        if str(item or "").strip()
    }


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
