from __future__ import annotations

from typing import Any, Iterable, Mapping

ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH = "subtitle_term_resolution_patch"


def _correction_attr(correction: Any, key: str) -> Any:
    if isinstance(correction, Mapping):
        return correction.get(key)
    return getattr(correction, key, None)


def _profile_candidate_terms(content_profile: Mapping[str, Any] | None) -> list[str]:
    profile = content_profile or {}
    candidates: list[str] = []
    for key in ("subject_brand", "subject_model", "subject_type", "video_theme"):
        value = str(profile.get(key) or "").strip()
        if value and value not in candidates:
            candidates.append(value)
    for item in profile.get("search_queries") or []:
        value = str(item or "").strip()
        if value and value not in candidates:
            candidates.append(value)
    return candidates[:12]


def build_subtitle_term_resolution_patch(
    *,
    corrections: Iterable[Any],
    source_name: str = "",
    content_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    patches: list[dict[str, Any]] = []
    confidence_total = 0.0
    confidence_count = 0
    auto_applied_count = 0
    accepted_count = 0
    pending_count = 0

    for correction in corrections:
        confidence_raw = _correction_attr(correction, "confidence")
        try:
            confidence = float(confidence_raw) if confidence_raw is not None else None
        except (TypeError, ValueError):
            confidence = None
        auto_applied = bool(_correction_attr(correction, "auto_applied"))
        human_decision = str(_correction_attr(correction, "human_decision") or "").strip().lower()
        if auto_applied:
            auto_applied_count += 1
        if auto_applied or human_decision == "accepted":
            accepted_count += 1
        if human_decision not in {"accepted", "rejected"} and not auto_applied:
            pending_count += 1
        if confidence is not None:
            confidence_total += confidence
            confidence_count += 1
        patches.append(
            {
                "subtitle_item_id": str(_correction_attr(correction, "subtitle_item_id") or ""),
                "original_span": str(_correction_attr(correction, "original_span") or "").strip(),
                "suggested_span": str(_correction_attr(correction, "suggested_span") or "").strip(),
                "change_type": str(_correction_attr(correction, "change_type") or "").strip(),
                "confidence": confidence,
                "source": str(_correction_attr(correction, "source") or "").strip(),
                "auto_applied": auto_applied,
                "human_decision": human_decision or None,
            }
        )

    average_confidence = round(confidence_total / confidence_count, 3) if confidence_count else None
    candidate_terms = _profile_candidate_terms(content_profile)
    return {
        "source_name": source_name,
        "candidate_terms": candidate_terms,
        "patches": patches,
        "evidence": {
            "candidate_terms": candidate_terms,
            "source_name": source_name,
        },
        "confidence": average_confidence,
        "scope": "subtitle_terms",
        "blocking": pending_count > 0,
        "metrics": {
            "patch_count": len(patches),
            "auto_applied_count": auto_applied_count,
            "accepted_count": accepted_count,
            "pending_count": pending_count,
        },
    }
