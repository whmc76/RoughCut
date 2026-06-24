from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from roughcut.edit.strategy_review_context import normalize_strategy_review_context

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
    "creative_preferences",
)

_PUBLICATION_ONLY_FIELDS = (
    "cover_title",
    "cover_style",
    "cover_style_label",
    "cover_variant_count",
)

_ARTIFACT_PRIORITY = {
    "downstream_context": 4,
    "content_profile_final": 3,
    "content_profile": 2,
    "content_profile_draft": 1,
}

_STRATEGY_REVIEW_ARTIFACT_TYPES = {
    "strategy_review_gates",
    "strategy_storyboard_review",
    "strategy_timeline_preview",
}


def build_downstream_context(
    content_profile: dict[str, Any] | None,
    *,
    strategy_review_gates: dict[str, Any] | None = None,
    strategy_storyboard_review: dict[str, Any] | None = None,
    strategy_timeline_preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base_profile = strip_publication_only_profile_fields(content_profile)
    manual_feedback = _normalized_manual_feedback(base_profile)
    resolved_profile = dict(base_profile)
    field_sources: dict[str, str] = {}
    strategy_review_context = build_strategy_review_context(
        strategy_review_gates=strategy_review_gates,
        strategy_storyboard_review=strategy_storyboard_review,
        strategy_timeline_preview=strategy_timeline_preview,
        existing_context=base_profile.get("strategy_review_context"),
    )

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
    if strategy_review_context:
        resolved_profile["strategy_review_context"] = strategy_review_context

    context = {
        "resolved_profile": resolved_profile,
        "field_sources": field_sources,
        "manual_review_applied": manual_review_applied,
        "research_applied": research_applied,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if strategy_review_context:
        context["strategy_review_context"] = strategy_review_context
    return context


def resolve_downstream_profile(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    if isinstance(payload.get("resolved_profile"), dict):
        resolved = strip_publication_only_profile_fields(payload.get("resolved_profile"))
        resolved["manual_review_applied"] = bool(payload.get("manual_review_applied"))
        resolved["research_applied"] = bool(payload.get("research_applied"))
        resolved["field_sources"] = dict(payload.get("field_sources") or {})
        strategy_review_context = build_strategy_review_context(
            existing_context=payload.get("strategy_review_context") or resolved.get("strategy_review_context")
        )
        if strategy_review_context:
            resolved["strategy_review_context"] = strategy_review_context
        return resolved
    return strip_publication_only_profile_fields(build_downstream_context(payload).get("resolved_profile"))


def strip_publication_only_profile_fields(content_profile: dict[str, Any] | None) -> dict[str, Any]:
    """Return the editing/downstream profile without publish-stage creative fields."""
    profile = dict(content_profile or {})
    for key in _PUBLICATION_ONLY_FIELDS:
        profile.pop(key, None)
    manual_feedback = profile.get("resolved_review_user_feedback")
    if isinstance(manual_feedback, dict):
        profile["resolved_review_user_feedback"] = {
            key: value
            for key, value in manual_feedback.items()
            if key not in _PUBLICATION_ONLY_FIELDS
        }
    return profile


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
    profile = resolve_downstream_profile(selected.data_json)
    return attach_strategy_review_context(
        profile,
        select_strategy_review_artifact_context(artifacts),
    )


def build_strategy_review_context(
    *,
    strategy_review_gates: dict[str, Any] | None = None,
    strategy_storyboard_review: dict[str, Any] | None = None,
    strategy_timeline_preview: dict[str, Any] | None = None,
    existing_context: Any = None,
) -> dict[str, Any]:
    context = dict(existing_context or {}) if isinstance(existing_context, dict) else {}
    if isinstance(strategy_review_gates, dict) and strategy_review_gates:
        context["strategy_review_gates"] = dict(strategy_review_gates)
    if isinstance(strategy_storyboard_review, dict) and strategy_storyboard_review:
        context["strategy_storyboard_review"] = dict(strategy_storyboard_review)
    if isinstance(strategy_timeline_preview, dict) and strategy_timeline_preview:
        context["strategy_timeline_preview"] = dict(strategy_timeline_preview)
    return normalize_strategy_review_context(context)


def attach_strategy_review_context(
    profile: dict[str, Any] | None,
    strategy_review_context: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved = dict(profile or {})
    context = build_strategy_review_context(existing_context=strategy_review_context)
    if context:
        resolved["strategy_review_context"] = context
    return resolved


def select_strategy_review_artifact_context(artifacts: list[Any]) -> dict[str, Any]:
    selected: dict[str, Any] = {}
    selected_created_at: dict[str, datetime] = {}
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    for artifact in artifacts or []:
        artifact_type = str(getattr(artifact, "artifact_type", "") or "").strip()
        if artifact_type not in _STRATEGY_REVIEW_ARTIFACT_TYPES:
            continue
        data_json = getattr(artifact, "data_json", None)
        if not isinstance(data_json, dict):
            continue
        created_at = getattr(artifact, "created_at", None) or epoch
        if artifact_type in selected_created_at and created_at <= selected_created_at[artifact_type]:
            continue
        selected[artifact_type] = dict(data_json)
        selected_created_at[artifact_type] = created_at
    return build_strategy_review_context(
        strategy_review_gates=selected.get("strategy_review_gates"),
        strategy_storyboard_review=selected.get("strategy_storyboard_review"),
        strategy_timeline_preview=selected.get("strategy_timeline_preview"),
    )


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
