from __future__ import annotations

from collections.abc import Mapping
from typing import Any


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
) -> list[str]:
    del avatar_result
    reasons = projection_output_fallback_reasons(
        subtitle_projection_repair,
        include_refresh_required=False,
    )
    return _dedupe(reasons)


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
