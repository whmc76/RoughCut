from __future__ import annotations

from typing import Any


ARTIFACT_TYPE_MULTIMODAL_TRIM_REVIEW = "multimodal_trim_review"
MULTIMODAL_TRIM_REVIEW_SCHEMA_VERSION = "multimodal_trim_review.v1"


def _candidate_id(item: dict[str, Any]) -> str:
    reason = str(item.get("reason") or "").strip()
    start = round(float(item.get("start", 0.0) or 0.0), 3)
    end = round(float(item.get("end", start) or start), 3)
    source_text = str(item.get("source_text") or "").strip()
    return f"{reason}:{start:.3f}:{end:.3f}:{source_text}"


def multimodal_trim_review_candidates(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return []
    return [dict(item) for item in candidates if isinstance(item, dict)]


def build_multimodal_trim_review_payload(
    cut_analysis: dict[str, Any] | None,
    *,
    source_name: str = "",
    job_flow_mode: str = "auto",
) -> dict[str, Any]:
    analysis = cut_analysis if isinstance(cut_analysis, dict) else {}
    pending: list[dict[str, Any]] = []
    for item in list(analysis.get("rule_candidates") or []):
        if not isinstance(item, dict):
            continue
        if not bool(item.get("multimodal_review_required")):
            continue
        pending.append(
            {
                "candidate_id": _candidate_id(item),
                "start": round(float(item.get("start", 0.0) or 0.0), 3),
                "end": round(float(item.get("end", item.get("start", 0.0)) or item.get("start", 0.0) or 0.0), 3),
                "reason": str(item.get("reason") or "").strip(),
                "source_text": str(item.get("source_text") or "").strip() or None,
                "score": round(float(item.get("score", 0.0) or 0.0), 3),
                "multimodal_roles": [
                    str(role).strip()
                    for role in list(item.get("multimodal_roles") or [])
                    if str(role).strip()
                ][:4],
                "multimodal_keep_priority": str(item.get("multimodal_keep_priority") or "").strip() or None,
                "multimodal_confidence": round(float(item.get("multimodal_confidence", 0.0) or 0.0), 3),
                "review_state": "pending",
            }
        )
    return {
        "schema": MULTIMODAL_TRIM_REVIEW_SCHEMA_VERSION,
        "source_name": str(source_name or ""),
        "job_flow_mode": str(job_flow_mode or "auto"),
        "reviewed": False,
        "candidate_count": len(pending),
        "pending_count": len(pending),
        "accepted_count": 0,
        "rejected_count": 0,
        "candidates": pending,
    }
