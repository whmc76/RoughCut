from __future__ import annotations

import os
import subprocess
import sys
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, distinct, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from roughcut.api.options import normalize_channel_profile, normalize_job_language
from roughcut.api.schemas import (
    ContentProfileApprovalStatsOut,
    ContentProfileMemoryStatsOut,
    ContentProfileConfirmIn,
    ContentProfileReviewOut,
    JobActivityOut,
    JobOut,
    OpenFolderOut,
    ReportOut,
    ReviewApplyRequest,
)
from roughcut.config import get_settings
from roughcut.config import apply_runtime_overrides
from roughcut.creative.modes import normalize_enhancement_modes, normalize_workflow_mode
from roughcut.db.models import (
    Artifact,
    ContentProfileCorrection,
    ContentProfileKeywordStat,
    FactClaim,
    FactEvidence,
    Job,
    JobStep,
    RenderOutput,
    ReviewAction,
    SubtitleCorrection,
    SubtitleItem,
    Timeline,
    TranscriptSegment,
)
from roughcut.db.session import get_session
from roughcut.pipeline.celery_app import celery_app
from roughcut.pipeline.orchestrator import PIPELINE_STEPS, create_job_steps
from roughcut.pipeline.quality import QUALITY_ARTIFACT_TYPE
from roughcut.review.content_profile import _extract_reference_frames
from roughcut.review.content_profile import apply_content_profile_feedback
from roughcut.review.content_profile import build_reviewed_transcript_excerpt
from roughcut.review.content_profile_memory import (
    _build_field_preferences,
    _build_keyword_preferences,
    _build_recent_corrections,
    build_content_profile_memory_cloud,
    load_content_profile_user_memory,
    record_content_profile_feedback_memory,
)
from roughcut.review.content_profile_review_stats import (
    apply_current_content_profile_review_policy,
    build_content_profile_auto_review_gate,
    summarize_content_profile_review_stats,
    record_content_profile_manual_review,
)
from roughcut.review.domain_glossaries import detect_glossary_domains
from roughcut.review.report import generate_report
from roughcut.storage.s3 import get_storage, job_key

router = APIRouter(prefix="/jobs", tags=["jobs"])

STEP_LABELS = {
    "probe": "探测媒体信息",
    "extract_audio": "提取音频",
    "transcribe": "语音转写",
    "subtitle_postprocess": "字幕后处理",
    "subtitle_translation": "字幕翻译",
    "content_profile": "内容摘要",
    "summary_review": "信息核对",
    "glossary_review": "术语纠错",
    "ai_director": "AI导演",
    "avatar_commentary": "数字人解说",
    "edit_plan": "剪辑决策",
    "render": "渲染输出",
    "final_review": "成片审核",
    "platform_package": "平台文案",
}

STEP_ORDER = {step_name: index for index, step_name in enumerate(PIPELINE_STEPS)}

PROFILE_ARTIFACT_PRIORITY = {
    "content_profile_final": 3,
    "content_profile": 2,
    "content_profile_draft": 1,
}
_CONTENT_PROFILE_THUMBNAIL_CACHE_VERSION = "v2"


@router.get("", response_model=list[JobOut])
async def list_jobs(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps), selectinload(Job.artifacts))
        .order_by(Job.updated_at.desc(), Job.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    jobs = result.scalars().all()
    _attach_job_previews(jobs)
    return jobs


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    file: UploadFile = File(...),
    language: str = Form("zh-CN"),
    channel_profile: str | None = Form(None),
    workflow_mode: str | None = Form(None),
    enhancement_modes: list[str] | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    try:
        language = normalize_job_language(language)
        channel_profile = normalize_channel_profile(channel_profile)
        workflow_mode = normalize_workflow_mode(workflow_mode or settings.default_job_workflow_mode)
        enhancement_modes = normalize_enhancement_modes(
            enhancement_modes if enhancement_modes is not None else settings.default_job_enhancement_modes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Validate extension
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in settings.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"File extension {suffix!r} not allowed. Allowed: {settings.allowed_extensions}",
        )

    # Save to temp file and check size
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        content = await file.read()
        if len(content) > settings.max_upload_size_bytes:
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=413, detail="File too large")
        tmp.write(content)

    try:
        # Upload to S3
        job_id = uuid.uuid4()
        storage = get_storage()
        storage.ensure_bucket()
        s3_key = job_key(str(job_id), file.filename or f"video{suffix}")
        storage.upload_file(tmp_path, s3_key)

        # Create job
        job = Job(
            id=job_id,
            source_path=s3_key,
            source_name=file.filename or f"video{suffix}",
            status="pending",
            language=language,
            channel_profile=channel_profile,
            workflow_mode=workflow_mode,
            enhancement_modes=enhancement_modes,
        )
        session.add(job)

        # Create all pipeline steps
        steps = create_job_steps(job_id)
        for step in steps:
            session.add(step)

        await session.commit()
        await session.refresh(job)

        # Reload with steps
        result = await session.execute(
            select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).where(Job.id == job_id)
        )
        job = result.scalar_one()
        _attach_job_preview(job)

    finally:
        tmp_path.unlink(missing_ok=True)

    return job


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _attach_job_preview(job)
    return job


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in {"done", "failed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"Job already {job.status}")

    _revoke_running_steps(job.steps or [])

    now = datetime.now(timezone.utc)
    job.status = "cancelled"
    job.error_message = "Cancelled by user"
    job.updated_at = now
    for step in job.steps or []:
        if step.status == "pending":
            step.status = "skipped"
            step.finished_at = now
        elif step.status == "running":
            step.status = "cancelled"
            step.error_message = "Cancelled by user"
            step.finished_at = now
            step.metadata_ = {
                **(step.metadata_ or {}),
                "detail": "任务已取消，后续流程停止。",
                "updated_at": now.isoformat(),
            }
    await session.commit()
    await session.refresh(job)
    _attach_job_preview(job)
    return job


@router.post("/{job_id}/restart", response_model=JobOut)
async def restart_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"done", "cancelled", "failed", "needs_review"}:
        raise HTTPException(status_code=409, detail="Only completed, review-paused, cancelled, or failed jobs can be restarted")

    _revoke_running_steps(job.steps or [])
    await _clear_job_runtime_state(job_id, session)

    now = datetime.now(timezone.utc)
    job.status = "pending"
    job.error_message = None
    job.updated_at = now
    job.file_hash = None
    existing_step_names = {step.step_name for step in job.steps or []}
    for step_name in PIPELINE_STEPS:
        if step_name in existing_step_names:
            continue
        step = JobStep(job_id=job.id, step_name=step_name, status="pending")
        session.add(step)
        (job.steps or []).append(step)

    ordered_steps = _ordered_steps(job.steps or [])
    for step in ordered_steps:
        step.status = "pending"
        step.attempt = 0
        step.started_at = None
        step.finished_at = None
        step.error_message = None
        step.metadata_ = None
    if ordered_steps:
        ordered_steps[0].metadata_ = {
            "detail": "任务已重新开始，等待调度器派发。",
            "updated_at": now.isoformat(),
        }

    await session.commit()
    result = await session.execute(
        select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).where(Job.id == job_id)
    )
    job = result.scalar_one()
    _attach_job_preview(job)
    return job


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    _revoke_running_steps(job.steps or [])
    await _clear_job_runtime_state(job_id, session)
    await session.execute(delete(JobStep).where(JobStep.job_id == job_id))
    await session.execute(delete(Job).where(Job.id == job_id))
    await session.commit()


@router.get("/{job_id}/report", response_model=ReportOut)
async def get_report(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    report = await generate_report(job_id, session)
    return report


@router.get("/{job_id}/timeline")
async def get_timeline(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Timeline).where(Timeline.job_id == job_id, Timeline.timeline_type == "editorial")
    )
    timeline = result.scalar_one_or_none()
    if not timeline:
        raise HTTPException(status_code=404, detail="Timeline not found")
    return {"id": str(timeline.id), "version": timeline.version, "data": timeline.data_json}


@router.get("/{job_id}/content-profile", response_model=ContentProfileReviewOut)
async def get_content_profile(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    from roughcut.db.models import Artifact

    artifact_result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(["content_profile_draft", "content_profile_final"]),
        )
        .order_by(Artifact.created_at.desc())
    )
    artifacts = artifact_result.scalars().all()
    draft = next((item.data_json for item in artifacts if item.artifact_type == "content_profile_draft"), None)
    final = next((item.data_json for item in artifacts if item.artifact_type == "content_profile_final"), None)
    settings = get_settings()
    if isinstance(draft, dict):
        draft = apply_current_content_profile_review_policy(draft, settings=settings)
    if isinstance(final, dict):
        final = apply_current_content_profile_review_policy(final, settings=settings)

    review_step_result = await session.execute(
        select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
    )
    review_step = review_step_result.scalar_one_or_none()
    active_profile = final if isinstance(final, dict) and final else draft if isinstance(draft, dict) and draft else {}
    automation_review = active_profile.get("automation_review") if isinstance(active_profile, dict) else {}
    user_memory = await load_content_profile_user_memory(session, channel_profile=job.channel_profile)
    memory = dict(user_memory or {})
    memory["cloud"] = build_content_profile_memory_cloud(user_memory)

    review_step_detail = None
    if review_step is not None:
        review_step_detail = str((review_step.metadata_ or {}).get("detail") or "").strip() or None
    review_reasons = list((automation_review or {}).get("review_reasons") or [])
    blocking_reasons = list((automation_review or {}).get("blocking_reasons") or [])
    if review_step is not None:
        review_reasons = review_reasons or list((review_step.metadata_ or {}).get("review_reasons") or [])
        blocking_reasons = blocking_reasons or list((review_step.metadata_ or {}).get("blocking_reasons") or [])
    identity_review = (
        (active_profile or {}).get("identity_review")
        if isinstance(active_profile, dict)
        else None
    )
    if identity_review is None and review_step is not None:
        candidate = (review_step.metadata_ or {}).get("identity_review")
        identity_review = candidate if isinstance(candidate, dict) else None

    return ContentProfileReviewOut(
        job_id=str(job_id),
        status=job.status,
        review_step_status=review_step.status if review_step else "pending",
        review_step_detail=review_step_detail,
        review_reasons=review_reasons,
        blocking_reasons=blocking_reasons,
        identity_review=identity_review,
        workflow_mode=str(getattr(job, "workflow_mode", "") or "standard_edit"),
        enhancement_modes=list(getattr(job, "enhancement_modes", []) or []),
        draft=draft,
        final=final,
        memory=memory,
    )


@router.get("/stats/content-profile-memory", response_model=ContentProfileMemoryStatsOut)
async def get_content_profile_memory_stats(
    channel_profile: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    user_memory = await load_content_profile_user_memory(session, channel_profile=channel_profile)
    channel_profile_result = await session.execute(
        select(distinct(ContentProfileCorrection.channel_profile))
        .where(ContentProfileCorrection.channel_profile.is_not(None))
        .order_by(ContentProfileCorrection.channel_profile)
    )
    channel_profiles = [item for item in channel_profile_result.scalars().all() if item]

    correction_result = await session.execute(
        select(ContentProfileCorrection).order_by(ContentProfileCorrection.created_at.desc()).limit(240)
    )
    corrections = correction_result.scalars().all()

    keyword_result = await session.execute(select(ContentProfileKeywordStat))
    keyword_stats = keyword_result.scalars().all()

    total_corrections = sum(
        1
        for item in corrections
        if not channel_profile or item.channel_profile in {None, channel_profile}
    )
    total_keywords = sum(
        int(item.usage_count or 0)
        for item in keyword_stats
        if item.scope_type == "global"
        or (channel_profile and item.scope_type == "channel_profile" and item.scope_value == channel_profile)
    )

    return ContentProfileMemoryStatsOut(
        scope="channel_profile" if channel_profile else "global",
        channel_profile=channel_profile,
        channel_profiles=channel_profiles,
        total_corrections=total_corrections,
        total_keywords=total_keywords,
        field_preferences=_build_field_preferences(corrections, channel_profile=channel_profile, limit=6),
        keyword_preferences=_build_keyword_preferences(keyword_stats, channel_profile=channel_profile, limit=18),
        recent_corrections=_build_recent_corrections(corrections, channel_profile=channel_profile, limit=12),
        cloud=build_content_profile_memory_cloud(user_memory),
    )


@router.get("/stats/content-profile-approval", response_model=ContentProfileApprovalStatsOut)
async def get_content_profile_approval_stats():
    settings = get_settings()
    required_accuracy = float(getattr(settings, "content_profile_auto_review_min_accuracy", 0.9) or 0.9)
    minimum_sample_size = int(getattr(settings, "content_profile_auto_review_min_samples", 20) or 20)
    summary = summarize_content_profile_review_stats(
        min_accuracy=required_accuracy,
        min_samples=minimum_sample_size,
    )
    return ContentProfileApprovalStatsOut(
        updated_at=summary["updated_at"],
        auto_review_enabled=bool(getattr(settings, "auto_confirm_content_profile", False)),
        review_threshold=float(getattr(settings, "content_profile_review_threshold", 0.9) or 0.9),
        required_accuracy=summary["required_accuracy"],
        minimum_sample_size=summary["minimum_sample_size"],
        gate_passed=summary["gate_passed"],
        detail=str(summary["detail"]),
        measured_accuracy=summary["measured_accuracy"],
        sample_size=int(summary["sample_size"]),
        manual_review_total=int(summary["manual_review_total"]),
        approved_without_changes=int(summary["approved_without_changes"]),
        corrected_after_review=int(summary["corrected_after_review"]),
        eligible_manual_review_total=int(summary["eligible_manual_review_total"]),
        eligible_approved_without_changes=int(summary["eligible_approved_without_changes"]),
        eligible_corrected_after_review=int(summary["eligible_corrected_after_review"]),
        eligible_approval_accuracy=summary["eligible_approval_accuracy"],
    )


@router.post("/{job_id}/open-folder", response_model=OpenFolderOut)
async def open_job_folder(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    target_path, kind = await _resolve_job_open_target(job, session)
    if target_path is None:
        raise HTTPException(status_code=409, detail="当前任务没有可打开的本地文件夹")

    try:
        _open_in_file_manager(target_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"打开文件夹失败：{exc}") from exc

    return OpenFolderOut(path=str(target_path), kind=kind)


@router.get("/{job_id}/content-profile/thumbnail")
async def get_content_profile_thumbnail(
    job_id: uuid.UUID,
    index: int = 0,
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if index < 0 or index > 2:
        raise HTTPException(status_code=400, detail="Thumbnail index out of range")

    try:
        thumbnail = await _ensure_content_profile_thumbnail(job, index=index)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(thumbnail, media_type="image/jpeg")


@router.post("/{job_id}/content-profile/confirm", response_model=ContentProfileReviewOut)
async def confirm_content_profile(
    job_id: uuid.UUID,
    body: ContentProfileConfirmIn,
    session: AsyncSession = Depends(get_session),
):
    from datetime import datetime, timezone

    from roughcut.db.models import Artifact

    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    artifact_result = await session.execute(
        select(Artifact)
        .where(Artifact.job_id == job_id, Artifact.artifact_type == "content_profile_draft")
        .order_by(Artifact.created_at.desc())
    )
    draft_artifact = artifact_result.scalars().first()
    if not draft_artifact:
        raise HTTPException(status_code=404, detail="Content profile draft not found")

    subtitle_item_result = await session.execute(
        select(SubtitleItem)
        .where(SubtitleItem.job_id == job_id, SubtitleItem.version == 1)
        .order_by(SubtitleItem.item_index)
    )
    subtitle_items = subtitle_item_result.scalars().all()
    correction_result = await session.execute(
        select(SubtitleCorrection).where(SubtitleCorrection.job_id == job_id)
    )
    accepted_corrections = [
        {
            "item_index": next(
                (
                    item.item_index
                    for item in subtitle_items
                    if correction.subtitle_item_id and item.id == correction.subtitle_item_id
                ),
                None,
            ),
            "original": correction.original_span,
            "accepted": str(correction.human_override or correction.suggested_span or "").strip(),
        }
        for correction in correction_result.scalars().all()
        if correction.human_decision == "accepted"
    ]
    reviewed_subtitle_excerpt = build_reviewed_transcript_excerpt(
        [
            {
                "index": item.item_index,
                "start_time": item.start_time,
                "end_time": item.end_time,
                "text_raw": item.text_raw,
                "text_norm": item.text_norm,
                "text_final": item.text_final,
            }
            for item in subtitle_items
        ],
        accepted_corrections,
    )

    user_feedback = body.model_dump(exclude_none=True)
    workflow_mode = str(user_feedback.pop("workflow_mode", "") or getattr(job, "workflow_mode", "standard_edit"))
    enhancement_modes = list(user_feedback.pop("enhancement_modes", None) or getattr(job, "enhancement_modes", []) or [])
    final_profile = await apply_content_profile_feedback(
        draft_profile=draft_artifact.data_json or {},
        source_name=job.source_name,
        channel_profile=job.channel_profile,
        user_feedback=user_feedback,
        reviewed_subtitle_excerpt=reviewed_subtitle_excerpt,
        accepted_corrections=accepted_corrections,
    )
    final_profile["user_feedback"] = user_feedback
    manual_review_outcome = record_content_profile_manual_review(
        job_id=str(job.id),
        draft_artifact_id=str(draft_artifact.id),
        draft_profile=draft_artifact.data_json or {},
        final_profile=final_profile,
    )
    automation_review = final_profile.get("automation_review") if isinstance(final_profile, dict) else {}
    if isinstance(automation_review, dict):
        settings = get_settings()
        accuracy_gate = build_content_profile_auto_review_gate(
            min_accuracy=float(getattr(settings, "content_profile_auto_review_min_accuracy", 0.9) or 0.9),
            min_samples=int(getattr(settings, "content_profile_auto_review_min_samples", 20) or 20),
        )
        automation_review.update(
            {
                "approval_accuracy_gate_passed": bool(accuracy_gate["gate_passed"]),
                "approval_accuracy": accuracy_gate["measured_accuracy"],
                "approval_accuracy_required": accuracy_gate["required_accuracy"],
                "approval_accuracy_sample_size": accuracy_gate["sample_size"],
                "approval_accuracy_min_samples": accuracy_gate["minimum_sample_size"],
                "approval_accuracy_detail": accuracy_gate["detail"],
                "manual_review_sample_size": accuracy_gate["manual_review_total"],
            }
        )
        final_profile["automation_review"] = automation_review
    final_profile["manual_review_outcome"] = manual_review_outcome

    review_step_result = await session.execute(
        select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
    )
    review_step = review_step_result.scalar_one_or_none()
    if review_step:
        review_step.status = "done"
        review_step.finished_at = datetime.now(timezone.utc)
        review_step.error_message = None

    artifact = Artifact(
        job_id=job.id,
        step_id=review_step.id if review_step else None,
        artifact_type="content_profile_final",
        data_json=final_profile,
    )
    session.add(artifact)
    await record_content_profile_feedback_memory(
        session,
        job=job,
        draft_profile=draft_artifact.data_json or {},
        final_profile=final_profile,
        user_feedback=user_feedback,
    )

    job.workflow_mode = normalize_workflow_mode(workflow_mode)
    job.enhancement_modes = normalize_enhancement_modes(enhancement_modes)
    job.status = "processing"
    job.updated_at = datetime.now(timezone.utc)
    await session.flush()
    apply_runtime_overrides(
        {
            "default_job_workflow_mode": job.workflow_mode,
            "default_job_enhancement_modes": list(job.enhancement_modes or []),
        }
    )
    user_memory = await load_content_profile_user_memory(session, channel_profile=job.channel_profile)
    memory = dict(user_memory or {})
    memory["cloud"] = build_content_profile_memory_cloud(user_memory)
    await session.commit()

    review_step_detail = None
    if review_step is not None:
        review_step_detail = str((review_step.metadata_ or {}).get("detail") or "").strip() or None
    automation_review = final_profile.get("automation_review") if isinstance(final_profile, dict) else {}
    identity_review = final_profile.get("identity_review") if isinstance(final_profile, dict) else None

    return ContentProfileReviewOut(
        job_id=str(job_id),
        status=job.status,
        review_step_status=review_step.status if review_step else "done",
        review_step_detail=review_step_detail,
        review_reasons=list((automation_review or {}).get("review_reasons") or []),
        blocking_reasons=list((automation_review or {}).get("blocking_reasons") or []),
        identity_review=identity_review if isinstance(identity_review, dict) else None,
        workflow_mode=job.workflow_mode,
        enhancement_modes=list(job.enhancement_modes or []),
        draft=draft_artifact.data_json,
        final=final_profile,
        memory=memory,
    )


@router.get("/{job_id}/download")
async def get_download_url(
    job_id: uuid.UUID,
    variant: str = "packaged",
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(RenderOutput)
        .where(RenderOutput.job_id == job_id, RenderOutput.status == "done")
        .order_by(RenderOutput.created_at.desc())
    )
    render_output = result.scalar_one_or_none()
    if not render_output:
        raise HTTPException(status_code=404, detail="Rendered output not found")

    variant_value = str(variant or "packaged").strip().lower()
    if variant_value not in {"packaged", "plain"}:
        raise HTTPException(status_code=400, detail="variant must be 'packaged' or 'plain'")

    artifact_result = await session.execute(
        select(Artifact)
        .where(Artifact.job_id == job_id, Artifact.artifact_type == "render_outputs")
        .order_by(Artifact.created_at.desc())
    )
    outputs_artifact = artifact_result.scalars().first()
    outputs_data = outputs_artifact.data_json if outputs_artifact and outputs_artifact.data_json else {}

    storage = get_storage()
    if variant_value == "plain":
        candidates = [
            str(outputs_data.get("plain_output_key") or ""),
            job_key(str(job_id), "output_plain.mp4"),
        ]
    else:
        candidates = [
            str(outputs_data.get("packaged_output_key") or ""),
            job_key(str(job_id), "output.mp4"),
            render_output.output_path,
        ]
    object_key = next(
        (key for key in candidates if key and storage.object_exists(key)),
        None,
    )
    if not object_key:
        raise HTTPException(status_code=404, detail="Rendered object not found in storage")

    url = storage.get_presigned_url(object_key, expires_in=3600)
    return {"url": url, "expires_in": 3600}


def _revoke_running_steps(steps: list[JobStep]) -> None:
    for step in steps:
        if step.status != "running":
            continue
        task_id = (step.metadata_ or {}).get("task_id")
        if not task_id:
            continue
        try:
            celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
        except Exception:
            pass


async def _clear_job_runtime_state(job_id: uuid.UUID, session: AsyncSession) -> None:
    packaging_artifacts = await session.execute(
        select(Artifact).where(Artifact.job_id == job_id)
    )
    for artifact in packaging_artifacts.scalars().all():
        if artifact.storage_path:
            try:
                Path(artifact.storage_path).unlink(missing_ok=True)
            except Exception:
                pass

    render_outputs = await session.execute(select(RenderOutput).where(RenderOutput.job_id == job_id))
    for item in render_outputs.scalars().all():
        if item.output_path:
            output_path = Path(item.output_path)
            output_dir = output_path.parent
            if output_dir.name == output_path.stem:
                try:
                    shutil.rmtree(output_dir, ignore_errors=True)
                    continue
                except Exception:
                    pass
            try:
                output_path.unlink(missing_ok=True)
                output_path.with_suffix(".srt").unlink(missing_ok=True)
            except Exception:
                pass
            for candidate in output_dir.glob(f"{output_path.stem}_cover*"):
                try:
                    candidate.unlink(missing_ok=True)
                except Exception:
                    pass
            try:
                output_path.with_name(f"{output_path.stem}_publish.md").unlink(missing_ok=True)
            except Exception:
                pass

    await session.execute(
        delete(FactEvidence).where(FactEvidence.claim_id.in_(select(FactClaim.id).where(FactClaim.job_id == job_id)))
    )
    await session.execute(delete(FactClaim).where(FactClaim.job_id == job_id))
    await session.execute(delete(ReviewAction).where(ReviewAction.job_id == job_id))
    await session.execute(delete(RenderOutput).where(RenderOutput.job_id == job_id))
    await session.execute(delete(Timeline).where(Timeline.job_id == job_id))
    await session.execute(delete(Artifact).where(Artifact.job_id == job_id))
    await session.execute(delete(SubtitleCorrection).where(SubtitleCorrection.job_id == job_id))
    await session.execute(delete(SubtitleItem).where(SubtitleItem.job_id == job_id))
    await session.execute(delete(TranscriptSegment).where(TranscriptSegment.job_id == job_id))


@router.post("/{job_id}/review/apply")
async def apply_review(
    job_id: uuid.UUID,
    request: ReviewApplyRequest,
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    applied = 0
    for action in request.actions:
        # Record review action
        review = ReviewAction(
            job_id=job_id,
            target_type=action.target_type,
            target_id=action.target_id,
            action=action.action,
            override_text=action.override_text,
        )
        session.add(review)

        # Apply to subtitle correction if applicable
        if action.target_type == "subtitle_correction":
            correction = await session.get(SubtitleCorrection, action.target_id)
            if correction and correction.job_id == job_id:
                correction.human_decision = action.action
                if action.override_text:
                    correction.human_override = action.override_text
                if action.action == "accepted":
                    await _persist_reviewed_glossary_term(
                        session,
                        job=job,
                        correction=correction,
                    )
                applied += 1

    await session.commit()
    return {"applied": applied}


async def _persist_reviewed_glossary_term(
    session: AsyncSession,
    *,
    job: Job,
    correction: SubtitleCorrection,
) -> None:
    suggested = str(correction.human_override or correction.suggested_span or "").strip()
    original = str(correction.original_span or "").strip()
    if not suggested or not original or suggested == original:
        return

    profile_artifact = await _load_latest_artifact(
        session,
        job.id,
        _CONTENT_PROFILE_ARTIFACT_TYPES,
    )
    content_profile = {}
    if profile_artifact and isinstance(profile_artifact.payload_json, dict):
        content_profile = dict(profile_artifact.payload_json)

    detected_domains = detect_glossary_domains(
        channel_profile=job.channel_profile,
        content_profile=content_profile,
    )
    scopes: list[tuple[str, str]] = []
    for domain in detected_domains:
        pair = ("domain", domain)
        if pair not in scopes:
            scopes.append(pair)
    if job.channel_profile:
        scopes.append(("channel_profile", job.channel_profile))

    for scope_type, scope_value in scopes:
        result = await session.execute(
            select(GlossaryTerm).where(
                GlossaryTerm.scope_type == scope_type,
                GlossaryTerm.scope_value == scope_value,
                GlossaryTerm.correct_form == suggested,
            )
        )
        term = result.scalar_one_or_none()
        if term is None:
            session.add(
                GlossaryTerm(
                    scope_type=scope_type,
                    scope_value=scope_value,
                    wrong_forms=[original],
                    correct_form=suggested,
                    category=correction.change_type,
                    context_hint=f"reviewed_from_job:{job.channel_profile or 'uncategorized'}",
                )
            )
            continue
        wrong_forms = [str(item or "").strip() for item in (term.wrong_forms or []) if str(item or "").strip()]
        if original not in wrong_forms and original != suggested:
            wrong_forms.append(original)
            term.wrong_forms = wrong_forms


@router.get("/{job_id}/activity", response_model=JobActivityOut)
async def get_job_activity(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job_result = await session.execute(
        select(Job).options(selectinload(Job.steps)).where(Job.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    artifact_result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(
                [
                    "media_meta",
                    "content_profile_draft",
                    "content_profile_final",
                    "content_profile",
                    "ai_director_plan",
                    "avatar_commentary_plan",
                    "render_outputs",
                    "platform_packaging_md",
                    QUALITY_ARTIFACT_TYPE,
                ]
            ),
        )
        .order_by(Artifact.created_at.desc())
    )
    artifacts = artifact_result.scalars().all()

    timeline_result = await session.execute(
        select(Timeline).where(
            Timeline.job_id == job_id,
            Timeline.timeline_type.in_(["editorial", "render_plan"]),
        )
    )
    timelines = timeline_result.scalars().all()

    render_result = await session.execute(
        select(RenderOutput).where(RenderOutput.job_id == job_id).order_by(RenderOutput.created_at.desc())
    )
    render_output = render_result.scalars().first()

    correction_result = await session.execute(
        select(SubtitleCorrection).where(SubtitleCorrection.job_id == job_id)
    )
    corrections = correction_result.scalars().all()

    current_step = _build_current_step(job)
    decisions = _build_activity_decisions(artifacts, timelines, corrections, render_output)
    events = _build_activity_events(job.steps or [], artifacts, timelines, render_output)

    render_payload = None
    if render_output is not None:
        render_payload = {
            "status": render_output.status,
            "progress": float(render_output.progress or 0.0),
            "output_path": render_output.output_path,
            "updated_at": _iso_or_none(render_output.created_at),
        }

    return JobActivityOut(
        job_id=str(job.id),
        status=job.status,
        current_step=current_step,
        render=render_payload,
        decisions=decisions,
        events=events,
    )


def _build_current_step(job: Job) -> dict | None:
    steps = _ordered_steps(job.steps or [])
    running = next((step for step in steps if step.status == "running"), None)
    if running:
        meta = running.metadata_ or {}
        detail = _decorate_step_detail(
            meta.get("detail"),
            _step_elapsed_seconds(running),
            running=running.status == "running",
        )
        return {
            "step_name": running.step_name,
            "label": STEP_LABELS.get(running.step_name, running.step_name),
            "status": running.status,
            "detail": detail,
            "progress": meta.get("progress"),
            "updated_at": meta.get("updated_at") or _iso_or_none(running.started_at),
        }

    if job.status == "needs_review":
        waiting_review = next(
            (
                step for step in steps
                if step.step_name in {"summary_review", "final_review"} and step.status == "pending"
            ),
            None,
        )
        if waiting_review is not None:
            review_detail = (
                "等待核对内容信息后继续。"
                if waiting_review.step_name == "summary_review"
                else "等待审核成片后继续。"
            )
            return {
                "step_name": waiting_review.step_name,
                "label": STEP_LABELS[waiting_review.step_name],
                "status": "needs_review",
                "detail": review_detail,
                "progress": None,
                "updated_at": _iso_or_none(job.updated_at),
            }
        return {
            "step_name": "summary_review",
            "label": STEP_LABELS["summary_review"],
            "status": "needs_review",
            "detail": "等待核对内容信息后继续。",
            "progress": None,
            "updated_at": _iso_or_none(job.updated_at),
        }

    next_pending = next((step for step in steps if step.status == "pending"), None)
    if next_pending:
        meta = next_pending.metadata_ or {}
        detail = meta.get("detail")
        if not detail:
            detail = "等待调度器派发。" if _are_previous_steps_complete(steps, next_pending.step_name) else "等待前序步骤完成。"
        return {
            "step_name": next_pending.step_name,
            "label": STEP_LABELS.get(next_pending.step_name, next_pending.step_name),
            "status": next_pending.status,
            "detail": detail,
            "progress": None,
            "updated_at": meta.get("updated_at") or _iso_or_none(job.updated_at),
        }

    return None


def _build_activity_decisions(
    artifacts: list[Artifact],
    timelines: list[Timeline],
    corrections: list[SubtitleCorrection],
    render_output: RenderOutput | None,
) -> list[dict]:
    decisions: list[dict] = []
    render_outputs_artifact = next((artifact for artifact in artifacts if artifact.artifact_type == "render_outputs"), None)
    render_outputs = render_outputs_artifact.data_json if render_outputs_artifact and render_outputs_artifact.data_json else {}

    profile = next(
        (
            artifact for artifact in artifacts
            if artifact.artifact_type in {"content_profile", "content_profile_final", "content_profile_draft"}
        ),
        None,
    )
    if profile and profile.data_json:
        data = profile.data_json
        subject = " · ".join(
            part for part in [data.get("subject_type"), data.get("video_theme")] if part
        ).strip() or "已生成视频类型识别"
        detail = "；".join(
            part for part in [
                f"策略：{data.get('preset_name')}" if data.get("preset_name") else "",
                f"摘要：{data.get('summary')}" if data.get("summary") else "",
            ] if part
        ) or None
        decisions.append(
            {
                "kind": "content_profile",
                "title": "内容识别",
                "status": "done" if profile.artifact_type != "content_profile_draft" else "needs_review",
                "summary": subject,
                "detail": detail,
                "updated_at": _iso_or_none(profile.created_at),
            }
        )

    if corrections:
        accepted = sum(1 for item in corrections if item.auto_applied or item.human_decision == "accepted")
        pending = sum(1 for item in corrections if item.human_decision not in {"accepted", "rejected"})
        decisions.append(
            {
                "kind": "subtitle_review",
                "title": "字幕与术语",
                "status": "done",
                "summary": f"识别出 {len(corrections)} 处术语/字幕纠错候选",
                "detail": f"待审 {pending} 条，自动/已接受 {accepted} 条",
                "updated_at": _iso_or_none(max((item.created_at for item in corrections), default=None)),
            }
        )

    editorial = next((timeline for timeline in timelines if timeline.timeline_type == "editorial"), None)
    if editorial and editorial.data_json:
        remove_segments = [
            segment for segment in editorial.data_json.get("segments", [])
            if segment.get("type") == "remove"
        ]
        total_cut = sum(float(segment.get("end", 0) or 0) - float(segment.get("start", 0) or 0) for segment in remove_segments)
        reasons: dict[str, int] = {}
        for segment in remove_segments:
            reason = str(segment.get("reason") or "other")
            reasons[reason] = reasons.get(reason, 0) + 1
        detail = "；".join(f"{reason} {count} 段" for reason, count in sorted(reasons.items())) or "无删减建议"
        decisions.append(
            {
                "kind": "edit_plan",
                "title": "剪辑决策",
                "status": "done",
                "summary": f"建议移除 {len(remove_segments)} 段，共 {total_cut:.1f} 秒",
                "detail": detail,
                "updated_at": _iso_or_none(editorial.created_at),
            }
        )

    if render_output is not None:
        decisions.append(
            {
                "kind": "render",
                "title": "渲染状态",
                "status": render_output.status,
                "summary": f"成片输出进度 {round(float(render_output.progress or 0.0) * 100)}%",
                "detail": render_output.output_path or "正在生成输出文件",
                "updated_at": _iso_or_none(render_output.created_at),
            }
        )

    ai_director = next((artifact for artifact in artifacts if artifact.artifact_type == "ai_director_plan"), None)
    if ai_director and ai_director.data_json:
        plan = ai_director.data_json
        decisions.append(
            {
                "kind": "ai_director",
                "title": "AI导演",
                "status": "done",
                "summary": f"生成 {len(plan.get('voiceover_segments') or [])} 段导演重配音建议",
                "detail": str(plan.get("opening_hook") or plan.get("bridge_line") or "已输出导演建议稿"),
                "updated_at": _iso_or_none(ai_director.created_at),
            }
        )

    avatar_plan = next((artifact for artifact in artifacts if artifact.artifact_type == "avatar_commentary_plan"), None)
    if avatar_plan and avatar_plan.data_json:
        plan = avatar_plan.data_json
        avatar_result = render_outputs.get("avatar_result") if isinstance(render_outputs, dict) else None
        avatar_status = _resolve_avatar_activity_status(plan, avatar_result)
        decisions.append(
            {
                "kind": "avatar_commentary",
                "title": "数字人解说",
                "status": avatar_status["status"],
                "summary": avatar_status["summary"],
                "detail": avatar_status["detail"],
                "updated_at": avatar_status["updated_at"] or _iso_or_none(avatar_plan.created_at),
            }
        )

    packaging = next((artifact for artifact in artifacts if artifact.artifact_type == "platform_packaging_md"), None)
    if packaging:
        data = packaging.data_json or {}
        title = ""
        for platform in ("douyin", "xiaohongshu", "bilibili"):
            pack = data.get(platform) or {}
            titles = pack.get("titles") or []
            if titles:
                title = str(titles[0]).strip()
                break
        decisions.append(
            {
                "kind": "platform_package",
                "title": "平台文案",
                "status": "done",
                "summary": "已生成发布文案包",
                "detail": title or packaging.storage_path,
                "updated_at": _iso_or_none(packaging.created_at),
            }
        )

    quality = next((artifact for artifact in artifacts if artifact.artifact_type == QUALITY_ARTIFACT_TYPE and artifact.data_json), None)
    if quality and quality.data_json:
        data = quality.data_json
        score = data.get("score")
        grade = str(data.get("grade") or "").strip()
        recommended_steps = [str(item).strip() for item in (data.get("recommended_rerun_steps") or []) if str(item).strip()]
        issue_codes = [str(item).strip() for item in (data.get("issue_codes") or []) if str(item).strip()]
        summary_parts = []
        if grade or score is not None:
            summary_parts.append(f"{grade} {float(score):.1f}" if grade and score is not None else str(grade or score))
        if issue_codes:
            summary_parts.append(f"{len(issue_codes)} 个扣分项")
        decisions.append(
            {
                "kind": "quality_assessment",
                "title": "质量评分",
                "status": "done",
                "summary": " · ".join(part for part in summary_parts if part).strip() or "质量评分已更新",
                "detail": (
                    "；".join(
                        part for part in [
                            f"问题：{', '.join(issue_codes)}" if issue_codes else "",
                            f"建议补跑：{', '.join(recommended_steps)}" if recommended_steps else "",
                        ]
                        if part
                    )
                    or None
                ),
                "updated_at": _iso_or_none(quality.created_at),
            }
        )

    return decisions


def _build_activity_events(
    steps: list[JobStep],
    artifacts: list[Artifact],
    timelines: list[Timeline],
    render_output: RenderOutput | None,
) -> list[dict]:
    events: list[dict] = []

    for step in steps:
        label = STEP_LABELS.get(step.step_name, step.step_name)
        metadata = step.metadata_ or {}
        elapsed_seconds = _step_elapsed_seconds(step)
        if step.started_at:
            events.append(
                {
                    "timestamp": _iso_or_none(step.started_at),
                    "type": "step",
                    "status": "running" if step.status == "running" else "started",
                    "title": f"{label}开始",
                    "detail": None,
                }
            )
        if step.finished_at:
            events.append(
                {
                    "timestamp": _iso_or_none(step.finished_at),
                    "type": "step",
                    "status": step.status,
                    "title": f"{label}{'完成' if step.status == 'done' else '结束'}",
                    "detail": _decorate_step_detail(
                        step.error_message or metadata.get("detail"),
                        elapsed_seconds,
                        running=False,
                    ),
                }
            )
        updated_at = metadata.get("updated_at")
        if step.status == "running" and updated_at:
            events.append(
                {
                    "timestamp": updated_at,
                    "type": "progress",
                    "status": step.status,
                    "title": label,
                    "detail": _decorate_step_detail(metadata.get("detail"), elapsed_seconds, running=True),
                }
            )

    for artifact in artifacts:
        summary = _artifact_event_summary(artifact)
        if summary:
            events.append(
                {
                    "timestamp": _iso_or_none(artifact.created_at),
                    "type": "artifact",
                    "status": "done",
                    "title": summary["title"],
                    "detail": summary["detail"],
                }
            )

    for timeline in timelines:
        if timeline.timeline_type == "editorial":
            events.append(
                {
                    "timestamp": _iso_or_none(timeline.created_at),
                    "type": "decision",
                    "status": "done",
                    "title": "剪辑时间线已生成",
                    "detail": "系统已产出保留/删除片段决策。",
                }
            )

    if render_output is not None:
        events.append(
            {
                "timestamp": _iso_or_none(render_output.created_at),
                "type": "render",
                "status": render_output.status,
                "title": "渲染输出",
                "detail": f"当前进度 {round(float(render_output.progress or 0.0) * 100)}%",
            }
        )

    events = [event for event in events if event["timestamp"]]
    events.sort(key=lambda item: item["timestamp"], reverse=True)
    return events[:20]


def _artifact_event_summary(artifact: Artifact) -> dict | None:
    data = artifact.data_json or {}
    if artifact.artifact_type == "media_meta":
        width = data.get("width")
        height = data.get("height")
        duration = data.get("duration")
        return {
            "title": "媒体参数已识别",
            "detail": f"{width}×{height} · {duration:.1f}s" if width and height and duration else "媒体信息已写入",
        }
    if artifact.artifact_type == "content_profile_draft":
        return {
            "title": "内容摘要草稿已生成",
            "detail": str(data.get("summary") or data.get("video_theme") or "等待人工确认"),
        }
    if artifact.artifact_type in {"content_profile", "content_profile_final"}:
        return {
            "title": "内容摘要已确认",
            "detail": str(data.get("summary") or data.get("video_theme") or "内容识别完成"),
        }
    if artifact.artifact_type == "platform_packaging_md":
        return {
            "title": "平台文案已生成",
            "detail": artifact.storage_path or "发布文案已写入 Markdown",
        }
    if artifact.artifact_type == "ai_director_plan":
        return {
            "title": "AI 导演建议已生成",
            "detail": str(data.get("opening_hook") or "已输出改写与重配音计划"),
        }
    if artifact.artifact_type == "avatar_commentary_plan":
        placement = str(data.get("overlay_position") or data.get("layout_template") or "").strip()
        return {
            "title": "数字人解说计划已生成",
            "detail": (
                f"{len(data.get('segments') or [])} 段解说位待渲染"
                + (f" · {placement}" if placement else "")
            ),
        }
    if artifact.artifact_type == "render_outputs":
        avatar_result = data.get("avatar_result") if isinstance(data, dict) else None
        if isinstance(avatar_result, dict) and avatar_result.get("status"):
            return {
                "title": "数字人成片结果已回写",
                "detail": str(avatar_result.get("detail") or avatar_result.get("status") or "数字人结果已更新"),
            }
    if artifact.artifact_type == QUALITY_ARTIFACT_TYPE:
        score = data.get("score") if isinstance(data, dict) else None
        grade = str(data.get("grade") or "").strip() if isinstance(data, dict) else ""
        issue_codes = [str(item).strip() for item in (data.get("issue_codes") or []) if str(item).strip()] if isinstance(data, dict) else []
        title = "质量评分已更新"
        detail = " · ".join(
            part
            for part in [
                f"{grade} {float(score):.1f}" if grade and score is not None else (str(score) if score is not None else ""),
                f"{len(issue_codes)} 个扣分项" if issue_codes else "",
            ]
            if part
        )
        return {
            "title": title,
            "detail": detail or "质量评分已写入",
        }
    return None


def _resolve_avatar_activity_status(
    plan: dict,
    avatar_result: dict | None,
) -> dict[str, str | None]:
    placement = str(plan.get("overlay_position") or plan.get("layout_template") or plan.get("provider") or "").strip()
    if avatar_result:
        status_value = str(avatar_result.get("status") or "").strip().lower()
        if status_value == "done":
            summary = "数字人口播已合成进成片"
            detail = str(
                avatar_result.get("detail")
                or avatar_result.get("profile_name")
                or placement
                or "数字人画中画已完成"
            )
            return {"status": "done", "summary": summary, "detail": detail, "updated_at": None}
        if status_value in {"degraded", "failed"}:
            summary = "数字人未写入成片，已回退普通成片"
            detail = str(
                avatar_result.get("detail")
                or avatar_result.get("reason")
                or plan.get("provider")
                or "数字人渲染失败，已自动降级"
            )
            return {"status": "failed", "summary": summary, "detail": detail, "updated_at": None}

    render_execution = plan.get("render_execution") if isinstance(plan, dict) else None
    render_status = str((render_execution or {}).get("status") or "").strip().lower()
    if render_status in {"success", "partial"}:
        return {
            "status": "done",
            "summary": "数字人素材已生成，等待合成进成片",
            "detail": str(placement or "数字人素材已准备完成"),
            "updated_at": None,
        }
    if render_status in {"failed"}:
        return {
            "status": "failed",
            "summary": "数字人素材生成失败",
            "detail": str((render_execution or {}).get("error") or plan.get("provider") or "数字人生成失败"),
            "updated_at": None,
        }

    return {
        "status": "done",
        "summary": f"规划 {len(plan.get('segments') or [])} 段数字人口播插入位",
        "detail": str(placement or "已生成数字人解说计划"),
        "updated_at": None,
    }


def _step_elapsed_seconds(step: JobStep) -> float | None:
    metadata = step.metadata_ or {}
    raw_elapsed = metadata.get("elapsed_seconds")
    if raw_elapsed is not None:
        try:
            return max(0.0, float(raw_elapsed))
        except (TypeError, ValueError):
            pass
    if step.started_at is None:
        return None
    start_time = _coerce_utc(step.started_at)
    end_time = _coerce_utc(step.finished_at) if step.finished_at is not None else datetime.now(timezone.utc)
    return max(0.0, (end_time - start_time).total_seconds())


def _decorate_step_detail(detail: str | None, elapsed_seconds: float | None, *, running: bool) -> str | None:
    elapsed_text = _format_elapsed(elapsed_seconds)
    base = (detail or "").strip()
    if elapsed_text:
        suffix = f"已运行 {elapsed_text}" if running else f"用时 {elapsed_text}"
        if base:
            if suffix in base or "用时 " in base or "已运行 " in base:
                return base
            return f"{base} · {suffix}"
        return suffix
    return base or None


def _format_elapsed(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    if seconds < 1:
        return f"{seconds:.1f}s"
    if seconds < 10:
        return f"{seconds:.1f}s"
    total_seconds = max(0, int(round(seconds)))
    minutes, sec = divmod(total_seconds, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minute}m {sec}s"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _attach_job_previews(jobs: list[Job]) -> None:
    for job in jobs:
        _attach_job_preview(job)


def _attach_job_preview(job: Job) -> None:
    if job.steps:
        job.steps.sort(key=_step_sort_key)
    preview = _resolve_job_content_preview(job.artifacts or [])
    job.content_subject = preview["subject"]
    job.content_summary = preview["summary"]
    quality_preview = _resolve_job_quality_preview(job.artifacts or [])
    job.quality_score = quality_preview["score"]
    job.quality_grade = quality_preview["grade"]
    job.quality_summary = quality_preview["summary"]
    job.quality_issue_codes = quality_preview["issue_codes"]
    avatar_preview = _resolve_job_avatar_preview(job)
    job.avatar_delivery_status = avatar_preview["status"]
    job.avatar_delivery_summary = avatar_preview["summary"]
    job.progress_percent = _calculate_job_progress_percent(job)


def _calculate_job_progress_percent(job: Job) -> int:
    steps = list(job.steps or [])
    if not steps:
        return 0

    total = len(steps)
    done_count = sum(1 for step in steps if step.status in {"done", "skipped"})
    running_count = sum(1 for step in steps if step.status == "running")
    base_progress = done_count / total
    running_bonus = (0.5 / total) if running_count else 0.0
    progress = max(0.0, min(1.0, base_progress + running_bonus))

    if job.status == "done":
        return 100
    if job.status in {"failed", "cancelled"}:
        return round(base_progress * 100)
    return round(progress * 100)


def _ordered_steps(steps: list[JobStep]) -> list[JobStep]:
    return sorted(steps, key=_step_sort_key)


def _step_sort_key(step: JobStep) -> tuple[int, datetime]:
    created = step.started_at or step.finished_at or datetime.min.replace(tzinfo=timezone.utc)
    return (STEP_ORDER.get(step.step_name, len(STEP_ORDER)), created)


def _find_step(steps: list[JobStep], step_name: str) -> JobStep | None:
    return next((step for step in steps if step.step_name == step_name), None)


def _are_previous_steps_complete(steps: list[JobStep], step_name: str) -> bool:
    step_index = STEP_ORDER.get(step_name, len(STEP_ORDER))
    for step in _ordered_steps(steps):
        if STEP_ORDER.get(step.step_name, len(STEP_ORDER)) >= step_index:
            break
        if step.status not in {"done", "skipped"}:
            return False
    return True


def _has_reached_step(job: Job, step_name: str) -> bool:
    steps = list(job.steps or [])
    target = _find_step(steps, step_name)
    if target is None:
        return False
    if target.status in {"running", "done", "failed", "skipped"}:
        return True
    if target.attempt > 0 or target.started_at is not None or target.finished_at is not None:
        return True
    return any(
        STEP_ORDER.get(step.step_name, -1) > STEP_ORDER.get(step_name, -1)
        and step.status in {"running", "done", "failed", "skipped"}
        for step in steps
    )


def _resolve_job_content_preview(artifacts: list[Artifact]) -> dict[str, str | None]:
    profile = _select_preview_artifact(artifacts)
    if not profile or not profile.data_json:
        return {"subject": None, "summary": None}

    data = profile.data_json
    product = " ".join(
        part.strip()
        for part in [str(data.get("subject_brand") or "").strip(), str(data.get("subject_model") or "").strip()]
        if part and str(part).strip()
    ).strip()
    subject_parts = [
        product,
        str(data.get("subject_type") or "").strip(),
        str(data.get("video_theme") or "").strip(),
    ]
    subject = " · ".join(part for part in subject_parts if part).strip() or None
    summary = str(data.get("summary") or data.get("hook_line") or "").strip() or None
    return {"subject": subject, "summary": summary}


def _resolve_job_avatar_preview(job: Job) -> dict[str, str | None]:
    enabled_modes = set(getattr(job, "enhancement_modes", []) or [])
    if "avatar_commentary" not in enabled_modes:
        return {"status": None, "summary": None}

    artifacts = list(job.artifacts or [])
    render_outputs_artifact = next(
        (artifact for artifact in artifacts if artifact.artifact_type == "render_outputs" and artifact.data_json),
        None,
    )
    render_outputs = render_outputs_artifact.data_json if render_outputs_artifact else {}
    avatar_result = render_outputs.get("avatar_result") if isinstance(render_outputs, dict) else None
    if isinstance(avatar_result, dict):
        status = str(avatar_result.get("status") or "").strip().lower()
        if status == "done":
            return {
                "status": "done",
                "summary": str(avatar_result.get("detail") or "数字人口播已写入成片"),
            }
        if status in {"degraded", "failed"}:
            return {
                "status": "failed",
                "summary": str(avatar_result.get("detail") or "数字人未写入成片，已回退普通成片"),
            }

    avatar_plan = next(
        (artifact for artifact in artifacts if artifact.artifact_type == "avatar_commentary_plan" and artifact.data_json),
        None,
    )
    if avatar_plan is None:
        if not _has_reached_step(job, "avatar_commentary"):
            return {"status": None, "summary": None}
        avatar_step = _find_step(job.steps or [], "avatar_commentary")
        if avatar_step and avatar_step.status == "running":
            return {
                "status": "running",
                "summary": str((avatar_step.metadata_ or {}).get("detail") or "正在生成数字人计划"),
            }
        if job.status in {"failed", "cancelled"} or (avatar_step and avatar_step.status == "failed"):
            return {"status": "failed", "summary": "数字人流程未完成"}
        return {"status": "pending", "summary": "等待生成数字人计划"}

    plan = avatar_plan.data_json or {}
    render_execution = plan.get("render_execution") if isinstance(plan, dict) else None
    render_status = str((render_execution or {}).get("status") or "").strip().lower()
    if render_status in {"success", "partial"}:
        return {"status": "running", "summary": "数字人素材已生成，等待合成进成片"}
    if render_status == "failed":
        return {
            "status": "failed",
            "summary": str((render_execution or {}).get("error") or "数字人素材生成失败"),
        }
    return {"status": "running", "summary": "数字人计划已生成，等待渲染落地"}


def _resolve_job_quality_preview(artifacts: list[Artifact]) -> dict[str, Any]:
    quality = next(
        (artifact for artifact in artifacts if artifact.artifact_type == QUALITY_ARTIFACT_TYPE and artifact.data_json),
        None,
    )
    if quality is None or not isinstance(quality.data_json, dict):
        return {"score": None, "grade": None, "summary": None, "issue_codes": []}

    data = quality.data_json
    score_raw = data.get("score")
    try:
        score = float(score_raw) if score_raw is not None else None
    except (TypeError, ValueError):
        score = None
    grade = str(data.get("grade") or "").strip() or None
    issue_codes = [str(item).strip() for item in (data.get("issue_codes") or []) if str(item).strip()]
    summary = " · ".join(
        part
        for part in [
            f"{grade} {score:.1f}" if grade and score is not None else (grade or (f"{score:.1f}" if score is not None else "")),
            f"{len(issue_codes)} 个扣分项" if issue_codes else "",
        ]
        if part
    ) or None
    return {
        "score": score,
        "grade": grade,
        "summary": summary,
        "issue_codes": issue_codes,
    }


def _select_preview_artifact(artifacts: list[Artifact]) -> Artifact | None:
    candidates = [
        artifact
        for artifact in artifacts
        if artifact.artifact_type in PROFILE_ARTIFACT_PRIORITY and artifact.data_json
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda artifact: (
            PROFILE_ARTIFACT_PRIORITY.get(artifact.artifact_type, 0),
            artifact.created_at or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    return candidates[0]


async def _resolve_job_open_target(job: Job, session: AsyncSession) -> tuple[Path | None, str]:
    render_result = await session.execute(
        select(RenderOutput)
        .where(RenderOutput.job_id == job.id, RenderOutput.output_path.is_not(None))
        .order_by(RenderOutput.created_at.desc())
    )
    for item in render_result.scalars().all():
        if not item.output_path:
            continue
        output_path = Path(item.output_path)
        if output_path.exists():
            return output_path, "output"

    source_path = Path(job.source_path)
    if source_path.exists():
        return source_path, "source"
    return None, "none"


def _open_in_file_manager(target_path: Path) -> None:
    if os.name == "nt":
        if target_path.is_file():
            subprocess.Popen(["explorer", "/select,", str(target_path)])
        else:
            os.startfile(str(target_path))
        return
    open_path = target_path.parent if target_path.is_file() else target_path
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(open_path)])
        return
    subprocess.Popen(["xdg-open", str(open_path)])


async def _ensure_content_profile_thumbnail(job: Job, *, index: int) -> Path:
    cache_dir = (
        Path(tempfile.gettempdir())
        / "roughcut_content_profile_frames"
        / _CONTENT_PROFILE_THUMBNAIL_CACHE_VERSION
        / str(job.id)
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"profile_{index:02d}.jpg"
    if cached.exists():
        return cached

    with tempfile.TemporaryDirectory() as tmpdir:
        source_path = await _resolve_job_source(job, tmpdir)
        frames = _extract_reference_frames(source_path, cache_dir, count=3)
    if not frames:
        raise RuntimeError("Unable to extract content profile thumbnails")
    if not cached.exists():
        raise FileNotFoundError("Requested thumbnail was not generated")
    return cached


async def _resolve_job_source(job: Job, tmpdir: str) -> Path:
    source_path = Path(job.source_path)
    if source_path.exists():
        return source_path
    local_path = Path(tmpdir) / job.source_name
    storage = get_storage()
    await storage.async_download_file(job.source_path, local_path)
    return local_path


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
