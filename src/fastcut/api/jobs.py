from __future__ import annotations

import hashlib
import shutil
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from fastcut.api.schemas import JobOut, ReportOut, ReviewApplyRequest
from fastcut.config import get_settings
from fastcut.db.models import Job, JobStep, RenderOutput, ReviewAction, SubtitleCorrection, Timeline
from fastcut.db.session import get_session
from fastcut.pipeline.orchestrator import create_job_steps
from fastcut.review.report import generate_report
from fastcut.storage.s3 import get_storage, job_key

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
async def list_jobs(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps))
        .order_by(Job.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


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
            select(Job).options(selectinload(Job.steps)).where(Job.id == job_id)
        )
        job = result.scalar_one()

    finally:
        tmp_path.unlink(missing_ok=True)

    return job


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Job).options(selectinload(Job.steps)).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
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
    url = storage.get_presigned_url(render_output.output_path, expires_in=3600)
    return {"url": url, "expires_in": 3600}


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
