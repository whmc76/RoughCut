from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.db.models import Artifact, Job, JobStep, ReviewAction
from roughcut.pipeline.orchestrator import _reset_job_for_quality_rerun
from roughcut.pipeline.quality import QUALITY_ARTIFACT_TYPE
from roughcut.pipeline.rerun_actions import (
    MANUAL_REVIEW_ONLY_ISSUES,
    QUALITY_RERUN_STEPS,
    has_manual_review_only_issue_codes,
    rerun_chain_from_step,
    rerun_start_step_for_issue,
)


@dataclass(slots=True)
class JobRerunRequest:
    issue_code: str | None = None
    rerun_start_step: str | None = None
    note: str | None = None


@dataclass(slots=True)
class JobRerunPlan:
    rerun_start_step: str
    rerun_steps: list[str]
    issue_codes: list[str]
    note: str | None = None


def build_job_rerun_detail(plan: JobRerunPlan) -> str:
    issue_text = f"问题：{', '.join(plan.issue_codes)}；" if plan.issue_codes else ""
    chain_text = " -> ".join(plan.rerun_steps) if plan.rerun_steps else plan.rerun_start_step
    detail = (
        f"已接受重跑请求，等待调度器从 {plan.rerun_start_step} 接管。"
        f"{issue_text}链路：{chain_text}"
    )
    if plan.note:
        detail = f"{detail}。备注：{plan.note}"
    return detail


def normalize_quality_rerun_steps(values: Any) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        step_name = str(value or "").strip()
        if not step_name or step_name not in QUALITY_RERUN_STEPS or step_name in normalized:
            continue
        normalized.append(step_name)
    return normalized


def latest_quality_assessment_payload(artifacts: list[Artifact]) -> dict[str, Any] | None:
    for artifact in reversed(artifacts):
        if artifact.artifact_type == QUALITY_ARTIFACT_TYPE and isinstance(artifact.data_json, dict):
            return artifact.data_json
    return None


def _raise_manual_review_required(issue_codes: list[str]) -> None:
    manual_only_codes = [
        issue_code
        for issue_code in issue_codes
        if issue_code in MANUAL_REVIEW_ONLY_ISSUES
    ]
    issue_text = ", ".join(manual_only_codes or issue_codes or ["manual_review_required"])
    raise HTTPException(
        status_code=409,
        detail=f"Issues require manual review before rerun: {issue_text}",
    )


def resolve_job_rerun_request(
    *,
    request: JobRerunRequest | None,
    artifacts: list[Artifact],
) -> JobRerunPlan:
    issue_code = str((request.issue_code if request else None) or "").strip()
    rerun_start_step = str((request.rerun_start_step if request else None) or "").strip()
    note = str((request.note if request else None) or "").strip() or None

    if issue_code and rerun_start_step:
        mapped_step = rerun_start_step_for_issue(issue_code)
        if mapped_step and mapped_step != rerun_start_step:
            raise HTTPException(
                status_code=400,
                detail=f"issue_code {issue_code} conflicts with rerun_start_step {rerun_start_step}",
            )

    if rerun_start_step:
        if rerun_start_step not in QUALITY_RERUN_STEPS:
            raise HTTPException(status_code=400, detail=f"Unsupported rerun_start_step: {rerun_start_step}")
        return JobRerunPlan(
            rerun_start_step=rerun_start_step,
            rerun_steps=rerun_chain_from_step(rerun_start_step),
            issue_codes=[issue_code] if issue_code else [],
            note=note,
        )

    quality_payload = latest_quality_assessment_payload(artifacts)
    quality_issue_codes = [
        str(value).strip()
        for value in ((quality_payload or {}).get("issue_codes") or [])
        if str(value).strip()
    ]
    quality_rerun_steps = normalize_quality_rerun_steps((quality_payload or {}).get("recommended_rerun_steps"))
    quality_requires_manual_review = has_manual_review_only_issue_codes(quality_issue_codes)

    if issue_code:
        if issue_code in MANUAL_REVIEW_ONLY_ISSUES:
            _raise_manual_review_required([issue_code])
        if quality_requires_manual_review:
            _raise_manual_review_required(quality_issue_codes)
        mapped_step = rerun_start_step_for_issue(issue_code)
        if mapped_step:
            return JobRerunPlan(
                rerun_start_step=mapped_step,
                rerun_steps=rerun_chain_from_step(mapped_step),
                issue_codes=[issue_code],
                note=note,
            )
        if issue_code in quality_issue_codes and quality_rerun_steps:
            return JobRerunPlan(
                rerun_start_step=quality_rerun_steps[0],
                rerun_steps=quality_rerun_steps,
                issue_codes=[issue_code],
                note=note,
            )
        raise HTTPException(status_code=400, detail=f"Unsupported issue_code: {issue_code}")

    if quality_requires_manual_review:
        _raise_manual_review_required(quality_issue_codes)
    if not quality_rerun_steps:
        raise HTTPException(status_code=409, detail="No rerun plan available for this job")
    return JobRerunPlan(
        rerun_start_step=quality_rerun_steps[0],
        rerun_steps=quality_rerun_steps,
        issue_codes=quality_issue_codes,
        note=note,
    )


async def execute_job_rerun_plan(
    session: AsyncSession,
    *,
    job: Job,
    steps: list[JobStep],
    plan: JobRerunPlan,
    via: str,
) -> None:
    first_step = next((step for step in steps if step.step_name == plan.rerun_start_step), None)
    if first_step is None:
        raise HTTPException(status_code=409, detail=f"Job step {plan.rerun_start_step} is missing")

    await _reset_job_for_quality_rerun(
        session,
        job,
        steps,
        rerun_steps=list(plan.rerun_steps),
        issue_codes=plan.issue_codes or ["manual_rerun"],
    )

    metadata = dict(first_step.metadata_ or {})
    metadata.update(
        {
            "rerun_requested_via": via,
            "rerun_issue_codes": list(plan.issue_codes),
            "rerun_start_step": plan.rerun_start_step,
            "rerun_steps": list(plan.rerun_steps),
        }
    )
    if plan.note:
        metadata["rerun_request_note"] = plan.note
    first_step.metadata_ = metadata

    session.add(
        ReviewAction(
            job_id=job.id,
            target_type="quality_rerun",
            target_id=job.id,
            action=plan.rerun_start_step,
            override_text=plan.note or (",".join(plan.issue_codes) if plan.issue_codes else None),
        )
    )
