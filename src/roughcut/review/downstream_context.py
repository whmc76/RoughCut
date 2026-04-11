from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_TRACKED_FIELDS = (
    "subject_brand",
    "subject_model",
    "subject_type",
    "subject_domain",
    "video_theme",
    "summary",
    "hook_line",
    "engagement_question",
    "visible_text",
    "correction_notes",
    "supplemental_context",
    "search_queries",
    "cover_title",
    "creative_preferences",
)

_ARTIFACT_PRIORITY = {
    "downstream_context": 4,
    "content_profile_final": 3,
    "content_profile": 2,
    "content_profile_draft": 1,
}


def build_downstream_context(content_profile: dict[str, Any] | None) -> dict[str, Any]:
    base_profile = dict(content_profile or {})
    manual_feedback = _normalized_manual_feedback(base_profile)
    resolved_profile = dict(base_profile)
    field_sources: dict[str, str] = {}

    for key in _TRACKED_FIELDS:
        if _has_value(manual_feedback.get(key)):
            resolved_profile[key] = manual_feedback[key]
            field_sources[key] = "manual_review"
            continue
        if _has_value(resolved_profile.get(key)):
            field_sources[key] = "base_profile"

    manual_review_applied = bool(
        str(base_profile.get("review_mode") or "").strip() == "manual_confirmed" or manual_feedback
    )
    research_applied = bool(_research_evidence_items(base_profile))

    resolved_profile["resolved_review_user_feedback"] = dict(base_profile.get("resolved_review_user_feedback") or {})
    resolved_profile["manual_review_applied"] = manual_review_applied
    resolved_profile["research_applied"] = research_applied
    resolved_profile["field_sources"] = dict(field_sources)

    return {
        "resolved_profile": resolved_profile,
        "field_sources": field_sources,
        "manual_review_applied": manual_review_applied,
        "research_applied": research_applied,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def resolve_downstream_profile(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("resolved_profile"), dict):
        resolved = dict(payload.get("resolved_profile") or {})
        resolved["manual_review_applied"] = bool(payload.get("manual_review_applied"))
        resolved["research_applied"] = bool(payload.get("research_applied"))
        resolved["field_sources"] = dict(payload.get("field_sources") or {})
        return resolved
    return dict(build_downstream_context(payload).get("resolved_profile") or {})


def select_resolved_downstream_profile(artifacts: list[Any]) -> dict[str, Any]:
    selected: Any | None = None
    selected_rank = -1
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    for artifact in artifacts or []:
        rank = _ARTIFACT_PRIORITY.get(str(getattr(artifact, "artifact_type", "") or "").strip(), 0)
        if rank < selected_rank:
            continue
        if rank == selected_rank and selected is not None:
            artifact_created_at = getattr(artifact, "created_at", None) or epoch
            selected_created_at = getattr(selected, "created_at", None) or epoch
            if artifact_created_at <= selected_created_at:
                continue
        selected = artifact
        selected_rank = rank
    if selected is None or not isinstance(getattr(selected, "data_json", None), dict):
        return {}
    return resolve_downstream_profile(selected.data_json)


def _normalized_manual_feedback(content_profile: dict[str, Any]) -> dict[str, Any]:
    payload = content_profile.get("resolved_review_user_feedback")
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key in _TRACKED_FIELDS:
        value = payload.get(key)
        if _has_value(value):
            normalized[key] = value
    return normalized


def _research_evidence_items(content_profile: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in (content_profile.get("evidence") or [])
        if isinstance(item, dict) and any(str(item.get(key) or "").strip() for key in ("title", "url", "snippet"))
    ]


def _has_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return value is not None
