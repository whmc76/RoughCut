from __future__ import annotations

import hashlib
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

from roughcut.api.schemas import (
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
from roughcut.pipeline.orchestrator import create_job_steps
from roughcut.review.content_profile import _extract_reference_frames
from roughcut.review.content_profile import apply_content_profile_feedback
from roughcut.review.content_profile_memory import (
    _build_field_preferences,
    _build_keyword_preferences,
    _build_recent_corrections,
    build_content_profile_memory_cloud,
    load_content_profile_user_memory,
    record_content_profile_feedback_memory,
)
from roughcut.review.report import generate_report
from roughcut.storage.s3 import get_storage, job_key

router = APIRouter(prefix="/jobs", tags=["jobs"])

STEP_LABELS = {
    "probe": "探测媒体信息",
    "extract_audio": "提取音频",
    "transcribe": "语音转写",
    "subtitle_postprocess": "字幕后处理",
    "content_profile": "内容摘要",
    "summary_review": "信息核对",
    "glossary_review": "术语纠错",
    "edit_plan": "剪辑决策",
    "render": "渲染输出",
    "platform_package": "平台文案",
}

PROFILE_ARTIFACT_PRIORITY = {
    "content_profile_final": 3,
    "content_profile": 2,
    "content_profile_draft": 1,
}


@router.get("", response_model=list[JobOut])
async def list_jobs(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps), selectinload(Job.artifacts))
        .order_by(Job.created_at.desc())
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
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()

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
    if job.status not in {"cancelled", "failed"}:
        raise HTTPException(status_code=409, detail="Only cancelled or failed jobs can be restarted")

    _revoke_running_steps(job.steps or [])
    await _clear_job_runtime_state(job_id, session)

    now = datetime.now(timezone.utc)
    job.status = "pending"
    job.error_message = None
    job.updated_at = now
    job.file_hash = None
    for step in job.steps or []:
        step.status = "pending"
        step.attempt = 0
        step.started_at = None
        step.finished_at = None
        step.error_message = None
        step.metadata_ = None

    await session.commit()
    await session.refresh(job)
    _attach_job_preview(job)
    return job


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

    review_step_result = await session.execute(
        select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
    )
    review_step = review_step_result.scalar_one_or_none()
    user_memory = await load_content_profile_user_memory(session, channel_profile=job.channel_profile)
    memory = dict(user_memory or {})
    memory["cloud"] = build_content_profile_memory_cloud(user_memory)

    return ContentProfileReviewOut(
        job_id=str(job_id),
        status=job.status,
        review_step_status=review_step.status if review_step else "pending",
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

    user_feedback = body.model_dump(exclude_none=True)
    final_profile = await apply_content_profile_feedback(
        draft_profile=draft_artifact.data_json or {},
        source_name=job.source_name,
        channel_profile=job.channel_profile,
        user_feedback=user_feedback,
    )
    final_profile["user_feedback"] = user_feedback

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

    job.status = "processing"
    job.updated_at = datetime.now(timezone.utc)
    await session.flush()
    user_memory = await load_content_profile_user_memory(session, channel_profile=job.channel_profile)
    memory = dict(user_memory or {})
    memory["cloud"] = build_content_profile_memory_cloud(user_memory)
    await session.commit()

    return ContentProfileReviewOut(
        job_id=str(job_id),
        status=job.status,
        review_step_status=review_step.status if review_step else "done",
        draft=draft_artifact.data_json,
        final=final_profile,
        memory=memory,
    )


@router.get("/{job_id}/download")
async def get_download_url(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(RenderOutput)
        .where(RenderOutput.job_id == job_id, RenderOutput.status == "done")
        .order_by(RenderOutput.created_at.desc())
    )
    render_output = result.scalar_one_or_none()
    if not render_output:
        raise HTTPException(status_code=404, detail="Rendered output not found")

    storage = get_storage()
    candidates = [
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
            try:
                output_path.unlink(missing_ok=True)
                output_path.with_suffix(".srt").unlink(missing_ok=True)
            except Exception:
                pass
            try:
                output_path.with_name(f"{output_path.stem}_cover.jpg").unlink(missing_ok=True)
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
                applied += 1

    await session.commit()
    return {"applied": applied}


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
                    "platform_packaging_md",
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
    steps = list(job.steps or [])
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
        return {
            "step_name": next_pending.step_name,
            "label": STEP_LABELS.get(next_pending.step_name, next_pending.step_name),
            "status": next_pending.status,
            "detail": "等待前序步骤完成。",
            "progress": None,
            "updated_at": _iso_or_none(job.updated_at),
        }

    return None


def _build_activity_decisions(
    artifacts: list[Artifact],
    timelines: list[Timeline],
    corrections: list[SubtitleCorrection],
    render_output: RenderOutput | None,
) -> list[dict]:
    decisions: list[dict] = []

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
        accepted = sum(1 for item in corrections if item.human_decision == "accepted")
        pending = sum(1 for item in corrections if not item.human_decision)
        decisions.append(
            {
                "kind": "subtitle_review",
                "title": "字幕与术语",
                "status": "done",
                "summary": f"识别出 {len(corrections)} 处术语/字幕纠错候选",
                "detail": f"待审 {pending} 条，已接受 {accepted} 条",
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
    return None


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
    preview = _resolve_job_content_preview(job.artifacts or [])
    job.content_subject = preview["subject"]
    job.content_summary = preview["summary"]


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
    cache_dir = Path(tempfile.gettempdir()) / "roughcut_content_profile_frames" / str(job.id)
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
