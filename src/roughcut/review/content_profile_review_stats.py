from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from roughcut.config import get_settings


_STATS_FILE = Path(__file__).resolve().parents[3] / "data" / "content_profile_review_stats.json"
_TRACKED_PROFILE_FIELDS = (
    "subject_brand",
    "subject_model",
    "subject_type",
    "video_theme",
    "hook_line",
    "visible_text",
    "summary",
    "engagement_question",
    "search_queries",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_bucket() -> dict[str, int]:
    return {
        "manual_review_total": 0,
        "approved_without_changes": 0,
        "corrected_after_review": 0,
        "eligible_manual_review_total": 0,
        "eligible_approved_without_changes": 0,
        "eligible_corrected_after_review": 0,
    }


def _default_stats() -> dict[str, Any]:
    return {
        "updated_at": None,
        "overall": _default_bucket(),
        "records": {},
    }


def _normalize_bucket(bucket: dict[str, Any] | None) -> dict[str, int]:
    normalized = _default_bucket()
    for key in normalized:
        try:
            normalized[key] = max(0, int((bucket or {}).get(key) or 0))
        except (TypeError, ValueError):
            normalized[key] = 0
    return normalized


def load_content_profile_review_stats() -> dict[str, Any]:
    if not _STATS_FILE.exists():
        return _default_stats()
    try:
        payload = json.loads(_STATS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return _default_stats()
    if not isinstance(payload, dict):
        return _default_stats()
    return {
        "updated_at": payload.get("updated_at"),
        "overall": _normalize_bucket(payload.get("overall")),
        "records": payload.get("records") if isinstance(payload.get("records"), dict) else {},
    }


def _save_content_profile_review_stats(payload: dict[str, Any]) -> None:
    _STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _STATS_FILE.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(_STATS_FILE)


def _summarize_bucket(bucket: dict[str, int]) -> dict[str, Any]:
    eligible_total = int(bucket.get("eligible_manual_review_total") or 0)
    eligible_approved = int(bucket.get("eligible_approved_without_changes") or 0)
    accuracy = None
    if eligible_total > 0:
        accuracy = round(eligible_approved / eligible_total, 4)
    return {
        **bucket,
        "eligible_approval_accuracy": accuracy,
    }


def summarize_content_profile_review_stats(*, min_accuracy: float, min_samples: int) -> dict[str, Any]:
    stats = load_content_profile_review_stats()
    summary = _summarize_bucket(stats["overall"])
    gate = build_content_profile_auto_review_gate(
        min_accuracy=min_accuracy,
        min_samples=min_samples,
    )
    return {
        "updated_at": stats.get("updated_at"),
        "manual_review_total": int(summary["manual_review_total"] or 0),
        "approved_without_changes": int(summary["approved_without_changes"] or 0),
        "corrected_after_review": int(summary["corrected_after_review"] or 0),
        "eligible_manual_review_total": int(summary["eligible_manual_review_total"] or 0),
        "eligible_approved_without_changes": int(summary["eligible_approved_without_changes"] or 0),
        "eligible_corrected_after_review": int(summary["eligible_corrected_after_review"] or 0),
        "eligible_approval_accuracy": summary.get("eligible_approval_accuracy"),
        "gate_passed": bool(gate["gate_passed"]),
        "detail": gate["detail"],
        "measured_accuracy": gate["measured_accuracy"],
        "required_accuracy": gate["required_accuracy"],
        "sample_size": gate["sample_size"],
        "minimum_sample_size": gate["minimum_sample_size"],
    }


def build_content_profile_auto_review_gate(*, min_accuracy: float, min_samples: int) -> dict[str, Any]:
    stats = load_content_profile_review_stats()
    summary = _summarize_bucket(stats["overall"])
    eligible_total = int(summary["eligible_manual_review_total"] or 0)
    accuracy = summary["eligible_approval_accuracy"]
    enough_samples = eligible_total >= max(1, int(min_samples))
    gate_passed = bool(
        enough_samples
        and accuracy is not None
        and float(accuracy) >= max(0.0, min(1.0, float(min_accuracy)))
    )

    if eligible_total == 0:
        detail = "自动放行候选样本暂无人工审核记录，暂不允许自动审核。"
    elif not enough_samples:
        detail = f"自动放行候选样本不足（{eligible_total}/{min_samples}），暂不允许自动审核。"
    elif accuracy is None:
        detail = "自动放行候选样本准确率暂不可用，暂不允许自动审核。"
    elif gate_passed:
        detail = f"自动放行候选样本人工确认准确率 {accuracy:.1%}，已达到 {min_accuracy:.0%} 门槛。"
    else:
        detail = f"自动放行候选样本人工确认准确率 {accuracy:.1%}，未达到 {min_accuracy:.0%} 门槛。"

    return {
        "gate_passed": gate_passed,
        "detail": detail,
        "measured_accuracy": accuracy,
        "required_accuracy": max(0.0, min(1.0, float(min_accuracy))),
        "sample_size": eligible_total,
        "minimum_sample_size": max(1, int(min_samples)),
        "manual_review_total": int(summary["manual_review_total"] or 0),
    }


def apply_current_content_profile_review_policy(
    profile: dict[str, Any] | None,
    *,
    settings: Any | None = None,
) -> dict[str, Any]:
    enriched = dict(profile or {})
    automation = enriched.get("automation_review")
    if not isinstance(automation, dict):
        return enriched

    settings = settings or get_settings()
    threshold = max(0.0, min(1.0, float(getattr(settings, "content_profile_review_threshold", 0.9) or 0.9)))
    try:
        score = float(automation.get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    blocking_reasons = list(automation.get("blocking_reasons") or [])
    quality_gate_passed = score >= threshold and not blocking_reasons
    accuracy_gate = build_content_profile_auto_review_gate(
        min_accuracy=float(getattr(settings, "content_profile_auto_review_min_accuracy", 0.9) or 0.9),
        min_samples=int(getattr(settings, "content_profile_auto_review_min_samples", 20) or 20),
    )

    merged = dict(automation)
    merged.update(
        {
            "enabled": bool(getattr(settings, "auto_confirm_content_profile", False)),
            "threshold": threshold,
            "quality_gate_passed": quality_gate_passed,
            "approval_accuracy_gate_passed": bool(accuracy_gate["gate_passed"]),
            "approval_accuracy": accuracy_gate["measured_accuracy"],
            "approval_accuracy_required": accuracy_gate["required_accuracy"],
            "approval_accuracy_sample_size": accuracy_gate["sample_size"],
            "approval_accuracy_min_samples": accuracy_gate["minimum_sample_size"],
            "approval_accuracy_detail": accuracy_gate["detail"],
            "manual_review_sample_size": accuracy_gate["manual_review_total"],
        }
    )
    merged["auto_confirm"] = bool(merged["enabled"] and quality_gate_passed and accuracy_gate["gate_passed"])
    enriched["automation_review"] = merged
    return enriched


def record_content_profile_manual_review(
    *,
    job_id: str,
    draft_artifact_id: str,
    draft_profile: dict[str, Any] | None,
    final_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    stats = load_content_profile_review_stats()
    records = stats.setdefault("records", {})
    record_key = str(draft_artifact_id)
    existing = records.get(record_key)
    if isinstance(existing, dict):
        gate = build_content_profile_auto_review_gate(
            min_accuracy=float(existing.get("required_accuracy") or 0.9),
            min_samples=int(existing.get("minimum_sample_size") or 20),
        )
        return {
            "approved_without_changes": bool(existing.get("approved_without_changes")),
            "changed_fields": list(existing.get("changed_fields") or []),
            "quality_gate_candidate": bool(existing.get("quality_gate_candidate")),
            "gate": gate,
        }

    changed_fields = _collect_changed_fields(draft_profile or {}, final_profile or {})
    approved_without_changes = not changed_fields
    quality_gate_candidate = _draft_quality_gate_candidate(draft_profile or {})

    bucket = _normalize_bucket(stats.get("overall"))
    bucket["manual_review_total"] += 1
    if approved_without_changes:
        bucket["approved_without_changes"] += 1
    else:
        bucket["corrected_after_review"] += 1

    if quality_gate_candidate:
        bucket["eligible_manual_review_total"] += 1
        if approved_without_changes:
            bucket["eligible_approved_without_changes"] += 1
        else:
            bucket["eligible_corrected_after_review"] += 1

    stats["overall"] = bucket
    stats["updated_at"] = _now_iso()
    records[record_key] = {
        "job_id": str(job_id),
        "recorded_at": stats["updated_at"],
        "approved_without_changes": approved_without_changes,
        "changed_fields": changed_fields,
        "quality_gate_candidate": quality_gate_candidate,
    }
    _save_content_profile_review_stats(stats)

    return {
        "approved_without_changes": approved_without_changes,
        "changed_fields": changed_fields,
        "quality_gate_candidate": quality_gate_candidate,
    }


def _draft_quality_gate_candidate(profile: dict[str, Any]) -> bool:
    automation = profile.get("automation_review")
    if not isinstance(automation, dict):
        return False
    if "quality_gate_passed" in automation:
        return bool(automation.get("quality_gate_passed"))
    blocking_reasons = list(automation.get("blocking_reasons") or [])
    try:
        score = float(automation.get("score") or 0.0)
        threshold = float(automation.get("threshold") or 1.0)
    except (TypeError, ValueError):
        return False
    return score >= threshold and not blocking_reasons


def _collect_changed_fields(draft_profile: dict[str, Any], final_profile: dict[str, Any]) -> list[str]:
    changed: list[str] = []
    for field_name in _TRACKED_PROFILE_FIELDS:
        if _normalized_profile_field(draft_profile.get(field_name), field_name=field_name) != _normalized_profile_field(
            final_profile.get(field_name),
            field_name=field_name,
        ):
            changed.append(field_name)
    return changed


def _normalized_profile_field(value: Any, *, field_name: str) -> Any:
    if field_name == "search_queries":
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value or []:
            token = _normalize_text(item)
            if token and token not in seen:
                seen.add(token)
                normalized.append(token)
        return normalized
    return _normalize_text(value)


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())
