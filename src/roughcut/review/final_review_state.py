from __future__ import annotations

from datetime import datetime
from typing import Any

from roughcut.db.models import Job, JobStep


def append_final_review_feedback_history(
    metadata: dict[str, Any] | None,
    *,
    note: str,
    now: datetime,
    via: str,
    limit: int = 10,
) -> list[dict[str, str]]:
    history = list((metadata or {}).get("feedback_history") or [])
    history.append({"text": note, "at": now.isoformat(), "via": via})
    return history[-limit:]


def mark_final_review_approved(
    *,
    review_step: JobStep,
    job: Job,
    now: datetime,
    approved_via: str,
    metadata_updates: dict[str, Any] | None = None,
) -> None:
    metadata = dict(review_step.metadata_ or {})
    metadata.update(
        {
            "detail": "成片已人工审核通过，继续生成平台文案。",
            "updated_at": now.isoformat(),
            "approved_via": approved_via,
        }
    )
    if metadata_updates:
        metadata.update(metadata_updates)
    review_step.metadata_ = metadata
    review_step.status = "done"
    review_step.started_at = review_step.started_at or now
    review_step.finished_at = now
    review_step.error_message = None
    job.status = "processing"
    job.error_message = None
    job.updated_at = now


def mark_final_review_pending(
    *,
    review_step: JobStep,
    job: Job,
    now: datetime,
    detail: str,
    note: str,
    via: str,
    metadata_updates: dict[str, Any] | None = None,
) -> None:
    metadata = dict(review_step.metadata_ or {})
    metadata.update(
        {
            "detail": detail,
            "updated_at": now.isoformat(),
            "feedback_history": append_final_review_feedback_history(metadata, note=note, now=now, via=via),
            "latest_feedback": note,
        }
    )
    if metadata_updates:
        metadata.update(metadata_updates)
    review_step.metadata_ = metadata
    review_step.status = "pending"
    review_step.started_at = review_step.started_at or now
    review_step.finished_at = None
    review_step.error_message = None
    job.status = "needs_review"
    job.updated_at = now


def apply_final_review_rerun_metadata(
    *,
    first_step: JobStep | None,
    rerun_plan: Any,
    note: str,
    now: datetime,
    review_user_feedback: dict[str, Any] | None = None,
) -> None:
    if first_step is None:
        return
    first_metadata = dict(first_step.metadata_ or {})
    first_metadata.update(
        {
            "detail": f"人工成片审核要求重跑：{rerun_plan.label}",
            "updated_at": now.isoformat(),
            "review_feedback": note,
            "review_rerun_category": rerun_plan.category,
            "review_rerun_focus": getattr(rerun_plan, "focus", ""),
            "review_rerun_steps": list(rerun_plan.rerun_steps),
            "review_rerun_targets": list(rerun_plan.targets),
        }
    )
    if review_user_feedback:
        first_metadata["review_user_feedback"] = review_user_feedback
    first_step.metadata_ = first_metadata
