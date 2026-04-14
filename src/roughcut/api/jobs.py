from __future__ import annotations

import asyncio
import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, distinct, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value
from pydantic import BaseModel

from roughcut.api.options import normalize_job_language, normalize_workflow_template
from roughcut.api.schemas import (
    ContentProfileApprovalStatsOut,
    ContentProfileMemoryStatsOut,
    ContentProfileConfirmIn,
    ContentProfileReviewOut,
    JobActivityOut,
    JobInitializeIn,
    JobOut,
    JobsUsageSummaryOut,
    JobsUsageTrendOut,
    OpenFolderOut,
    ReportOut,
    ReviewApplyRequest,
    TokenUsageReportOut,
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
    GlossaryTerm,
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
from roughcut.media.variant_timeline_bundle import resolve_effective_variant_timeline_bundle
from roughcut.recovery.stuck_step_recovery import STUCK_STEP_DIAGNOSTIC_ARTIFACT_TYPE
from roughcut.review.content_understanding_schema import normalize_video_type
from roughcut.review.content_profile import _probe_duration, build_reviewed_transcript_excerpt
from roughcut.review.content_profile_feedback import apply_content_profile_feedback
from roughcut.review.content_profile_keywords import normalize_query_list
from roughcut.review.content_profile_memory import (
    _build_field_preferences,
    _build_keyword_preferences,
    _build_recent_corrections,
    build_content_profile_memory_cloud,
    load_content_profile_user_memory,
    record_content_profile_feedback_memory,
)
from roughcut.review.downstream_context import build_downstream_context
from roughcut.review.model_identity import model_numbers_conflict
from roughcut.review.content_profile_review_stats import (
    apply_current_content_profile_review_policy,
    build_content_profile_auto_review_gate,
    summarize_content_profile_review_stats,
    record_content_profile_manual_review,
)
from roughcut.review.domain_glossaries import detect_glossary_domains
from roughcut.review.subtitle_memory import build_subtitle_review_memory
from roughcut.review.report import generate_report
from roughcut.runtime_refresh_hold import touch_runtime_refresh_hold
from roughcut.storage.s3 import get_storage, job_key
from roughcut.storage.runtime_cleanup import cleanup_job_runtime_files
from roughcut.source_context import enrich_source_context_with_filename_hints
from roughcut.usage import build_job_token_report, build_jobs_usage_summary, build_jobs_usage_trend

router = APIRouter(prefix="/jobs", tags=["jobs"])

_CONTENT_PROFILE_PLACEHOLDER_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCAAJABADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDwCiiitzI//9k="
)

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
_LIST_PREVIEW_ARTIFACT_TYPES = (
    "content_profile_final",
    "content_profile",
    "content_profile_draft",
    QUALITY_ARTIFACT_TYPE,
    "variant_timeline_bundle",
    "render_outputs",
    "avatar_commentary_plan",
)

PROFILE_ARTIFACT_PRIORITY = {
    "content_profile_final": 3,
    "content_profile": 1,
    "content_profile_draft": 1,
}
_CONTENT_PROFILE_ARTIFACT_TYPES = ("content_profile_final", "content_profile", "content_profile_draft")
_CONTENT_PROFILE_THUMBNAIL_CACHE_VERSION = "v2"
_CONTENT_PROFILE_THUMBNAIL_LOCKS: dict[str, asyncio.Lock] = {}
_CONTENT_PROFILE_THUMBNAIL_GENERATION_SEMAPHORE = asyncio.Semaphore(2)
_CONTENT_PROFILE_THUMBNAIL_WARM_TASKS: dict[str, asyncio.Task] = {}
_CONTENT_PROFILE_PLACEHOLDER_RETRY_SECONDS = 300


class FinalReviewDecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = None


class FinalReviewDecisionOut(BaseModel):
    job_id: str
    decision: Literal["approve", "reject"]
    job_status: str
    review_step_status: str
    rerun_triggered: bool = False
    note: str | None = None


class FinalReviewVariantTimelineRerenderOut(BaseModel):
    job_id: str
    job_status: str
    rerun_steps: list[str]
    validation_status: str | None = None
    validation_issue_count: int = 0


def _ensure_content_understanding_payload(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(profile, dict):
        return profile
    enriched = dict(profile)
    existing_block = profile.get("content_understanding") if isinstance(profile.get("content_understanding"), dict) else {}
    content_understanding = dict(existing_block)

    def _first_text(*values: Any) -> str:
        for value in values:
            text = str(value or "").strip()
            if text:
                return text
        return ""

    def _list_value(value: Any) -> list[Any]:
        return list(value) if isinstance(value, list) else []

    normalized_search_queries = normalize_query_list(
        [str(item).strip() for item in _list_value(content_understanding.get("search_queries")) if str(item).strip()]
    )
    if not normalized_search_queries:
        normalized_search_queries = normalize_query_list(
            [str(item).strip() for item in _list_value(enriched.get("search_queries")) if str(item).strip()]
        )

    if "needs_review" in content_understanding:
        needs_review = bool(content_understanding.get("needs_review"))
    else:
        needs_review = bool(enriched.get("review_required") or False)

    review_reasons = _list_value(content_understanding.get("review_reasons"))
    if not review_reasons:
        review_reasons = [str(item).strip() for item in _list_value(enriched.get("review_reasons")) if str(item).strip()]
    else:
        review_reasons = [str(item).strip() for item in review_reasons if str(item).strip()]

    content_understanding.update(
        {
            "video_type": normalize_video_type(
                _first_text(
                    content_understanding.get("video_type"),
                    enriched.get("content_kind"),
                    enriched.get("video_type"),
                    enriched.get("subject_type"),
                    content_understanding.get("subject_type"),
                )
            ),
            "content_domain": _first_text(
                content_understanding.get("content_domain"),
                enriched.get("subject_domain"),
                enriched.get("content_domain"),
            ),
            "primary_subject": _first_text(
                content_understanding.get("primary_subject"),
                enriched.get("primary_subject"),
                enriched.get("subject_type"),
            ),
            "subject_entities": _list_value(content_understanding.get("subject_entities")),
            "video_theme": _first_text(content_understanding.get("video_theme"), enriched.get("video_theme")),
            "summary": _first_text(content_understanding.get("summary"), enriched.get("summary")),
            "hook_line": _first_text(content_understanding.get("hook_line"), enriched.get("hook_line")),
            "engagement_question": _first_text(
                content_understanding.get("engagement_question"),
                content_understanding.get("question"),
                enriched.get("engagement_question"),
                enriched.get("question"),
            ),
            "search_queries": normalized_search_queries,
            "evidence_spans": _list_value(content_understanding.get("evidence_spans")),
            "uncertainties": _list_value(content_understanding.get("uncertainties")),
            "confidence": dict(content_understanding.get("confidence")) if isinstance(content_understanding.get("confidence"), dict) else {},
            "needs_review": needs_review,
            "review_reasons": review_reasons,
        }
    )
    enriched["content_understanding"] = content_understanding
    return enriched


def _select_preferred_content_profile_artifact(artifacts: list[Artifact]) -> Artifact | None:
    if not artifacts:
        return None
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    finals = [artifact for artifact in artifacts if str(artifact.artifact_type or "").strip() == "content_profile_final"]
    if finals:
        return max(
            finals,
            key=lambda artifact: (
                PROFILE_ARTIFACT_PRIORITY.get(str(artifact.artifact_type or "").strip(), 0),
                artifact.created_at or epoch,
            ),
        )
    return max(
        artifacts,
        key=lambda artifact: (
            PROFILE_ARTIFACT_PRIORITY.get(str(artifact.artifact_type or "").strip(), 0),
            artifact.created_at or epoch,
        ),
    )


async def _load_latest_optional_artifact(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    artifact_types: tuple[str, ...] | list[str],
) -> Artifact | None:
    result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(list(artifact_types)),
        )
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    artifacts = result.scalars().all()
    if set(artifact_types).issuperset(_CONTENT_PROFILE_ARTIFACT_TYPES):
        return _select_preferred_content_profile_artifact(artifacts)
    return artifacts[0] if artifacts else None


def _coerce_artifact_payload(artifact: Artifact | None) -> dict[str, Any]:
    if artifact is None or not isinstance(artifact.data_json, dict):
        return {}
    return dict(artifact.data_json)


async def _load_content_profile_review_evidence(
    job_id: uuid.UUID,
    session: AsyncSession,
) -> dict[str, dict[str, Any]]:
    evidence_result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(["content_profile_ocr", "transcript_evidence", "entity_resolution_trace"]),
        )
        .order_by(Artifact.created_at.desc())
    )
    evidence_artifacts = evidence_result.scalars().all()
    ocr_artifact = next(
        (item for item in evidence_artifacts if item.artifact_type == "content_profile_ocr"),
        None,
    )
    transcript_artifact = next(
        (item for item in evidence_artifacts if item.artifact_type == "transcript_evidence"),
        None,
    )
    entity_resolution_artifact = next(
        (item for item in evidence_artifacts if item.artifact_type == "entity_resolution_trace"),
        None,
    )
    return {
        "ocr_evidence": _coerce_artifact_payload(ocr_artifact),
        "transcript_evidence": _coerce_artifact_payload(transcript_artifact),
        "entity_resolution_trace": _coerce_artifact_payload(entity_resolution_artifact),
    }


@router.get("", response_model=list[JobOut])
async def list_jobs(
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps))
        .order_by(Job.updated_at.desc(), Job.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    jobs = result.scalars().all()
    if jobs:
        job_ids = [job.id for job in jobs]
        artifact_result = await session.execute(
            select(Artifact)
            .where(
                Artifact.job_id.in_(job_ids),
                Artifact.artifact_type.in_(_LIST_PREVIEW_ARTIFACT_TYPES),
            )
            .order_by(Artifact.job_id.asc(), Artifact.created_at.desc(), Artifact.id.desc())
        )
        artifacts_by_job: dict[uuid.UUID, list[Artifact]] = {}
        for artifact in artifact_result.scalars().all():
            artifacts_by_job.setdefault(artifact.job_id, []).append(artifact)
        for job in jobs:
            set_committed_value(job, "artifacts", artifacts_by_job.get(job.id, []))
    _attach_job_previews(jobs, lightweight=True)
    return jobs


@router.get("/usage-summary", response_model=JobsUsageSummaryOut)
async def get_jobs_usage_summary(limit: int = 60, session: AsyncSession = Depends(get_session)):
    normalized_limit = max(1, min(int(limit or 60), 500))
    result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps))
        .order_by(Job.updated_at.desc())
        .limit(normalized_limit)
    )
    jobs = result.scalars().all()
    summary = build_jobs_usage_summary(jobs, step_labels=STEP_LABELS)
    return JobsUsageSummaryOut(
        job_count=int(summary.get("job_count") or 0),
        jobs_with_telemetry=int(summary.get("jobs_with_telemetry") or 0),
        total_calls=int(summary.get("total_calls") or 0),
        total_prompt_tokens=int(summary.get("total_prompt_tokens") or 0),
        total_completion_tokens=int(summary.get("total_completion_tokens") or 0),
        total_tokens=int(summary.get("total_tokens") or 0),
        cache=dict(summary.get("cache") or {}),
        top_steps=list(summary.get("top_steps") or []),
        top_models=list(summary.get("top_models") or []),
        top_providers=list(summary.get("top_providers") or []),
    )


@router.get("/usage-trend", response_model=JobsUsageTrendOut)
async def get_jobs_usage_trend(
    days: int = 7,
    limit: int = 120,
    focus_type: str | None = None,
    focus_name: str | None = None,
    step_name: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    normalized_limit = max(1, min(int(limit or 120), 500))
    result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps))
        .order_by(Job.updated_at.desc())
        .limit(normalized_limit)
    )
    jobs = result.scalars().all()
    trend = build_jobs_usage_trend(
        jobs,
        days=days,
        step_labels=STEP_LABELS,
        focus_type=focus_type,
        focus_name=focus_name,
        step_name=step_name,
    )
    return JobsUsageTrendOut(
        days=int(trend.get("days") or 7),
        focus_type=trend.get("focus_type"),
        focus_name=trend.get("focus_name"),
        points=list(trend.get("points") or []),
    )


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(
    file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
    language: str = Form("zh-CN"),
    workflow_template: str | None = Form(None),
    workflow_mode: str | None = Form(None),
    enhancement_modes: list[str] | None = Form(None),
    output_dir: str | None = Form(None),
    video_description: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
):
    settings = get_settings()
    uploaded_files = _normalize_uploaded_sources(file=file, files=files)
    if not uploaded_files:
        raise HTTPException(status_code=422, detail="At least one file is required")

    try:
        language = normalize_job_language(language)
        workflow_template = normalize_workflow_template(workflow_template)
        workflow_mode = normalize_workflow_mode(workflow_mode or settings.default_job_workflow_mode)
        output_dir = str(output_dir or "").strip() or None
        video_description = _normalize_video_description(video_description)
        enhancement_modes = normalize_enhancement_modes(
            enhancement_modes if enhancement_modes is not None else settings.default_job_enhancement_modes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_root = Path(tmpdir)
        local_source_files = [
            await _save_uploaded_file(upload, target_dir=temp_root, index=index, settings=settings)
            for index, upload in enumerate(uploaded_files)
        ]

        if len(local_source_files) == 1:
            source_path = local_source_files[0]
            source_name = Path(uploaded_files[0].filename or source_path.name).name
        else:
            source_name = _build_merged_source_name(uploaded_files)
            source_path = await _merge_upload_files_for_job(local_source_files, output_path=temp_root / source_name)

        source_context = _build_job_source_context(
            uploaded_files=uploaded_files,
            source_name=source_name,
            video_description=video_description,
        )

        job_id = uuid.uuid4()
        storage = get_storage()
        storage.ensure_bucket()
        s3_key = job_key(str(job_id), source_name)
        storage.upload_file(source_path, s3_key)

        job = Job(
            id=job_id,
            source_path=s3_key,
            source_name=source_name,
            status="pending",
            language=language,
            workflow_template=workflow_template,
            workflow_mode=workflow_mode,
            enhancement_modes=enhancement_modes,
            output_dir=output_dir,
        )
        session.add(job)

        steps = create_job_steps(job_id)
        for step in steps:
            if step.step_name == "content_profile" and source_context:
                step.metadata_ = {
                    **(step.metadata_ or {}),
                    "source_context": source_context,
                }
            session.add(step)

        await session.commit()
        await session.refresh(job)

        result = await session.execute(
            select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).where(Job.id == job_id)
        )
        job = result.scalar_one()
        _attach_job_preview(job)

    return job


def _normalize_video_description(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return normalized[:4000]


def _normalize_uploaded_sources(
    *,
    file: UploadFile | None,
    files: list[UploadFile] | None,
) -> list[UploadFile]:
    normalized = [item for item in (files or []) if item is not None]
    if normalized:
        return normalized
    if file is not None:
        return [file]
    return []


def _concat_list_entry(path: Path) -> str:
    normalized = str(path).replace("\\", "/")
    escaped = normalized.replace("'", "\\'")
    return f"file '{escaped}'"


async def _run_concat_ffmpeg(
    list_file: Path,
    output_path: Path,
    *,
    transcode: bool,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-movflags",
        "+faststart",
    ]
    if transcode:
        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
            ]
        )
    else:
        cmd.extend(["-c", "copy"])
    cmd.append(str(output_path))

    settings = get_settings()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.ffmpeg_timeout_sec,
        ),
    )


async def _merge_upload_files_for_job(file_paths: list[Path], *, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        list_file = Path(tmpdir) / "files.txt"
        with list_file.open("w", encoding="utf-8") as handle:
            for path in file_paths:
                handle.write(_concat_list_entry(path))
                handle.write("\n")

        result = await _run_concat_ffmpeg(list_file, output_path, transcode=False)
        if result.returncode != 0:
            if output_path.exists():
                output_path.unlink()
            result = await _run_concat_ffmpeg(list_file, output_path, transcode=True)

    if result.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"ffmpeg concat merge failed: {result.stderr[-500:]}")
    return output_path


def _build_merged_source_name(uploaded_files: list[UploadFile]) -> str:
    first_name = str(uploaded_files[0].filename or "").strip() if uploaded_files else ""
    first_stem = Path(first_name or "video").stem or "video"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", first_stem).strip("._-") or "video"
    return f"merged_{len(uploaded_files)}_{safe_stem[:48]}.mp4"


def _build_job_source_context(
    *,
    uploaded_files: list[UploadFile] | None = None,
    source_name: str | None = None,
    video_description: str | None,
    merged_source_names: list[str] | None = None,
    allow_related_profiles: bool = False,
) -> dict[str, Any] | None:
    source_context: dict[str, Any] = {}
    if video_description:
        source_context["video_description"] = video_description
    resolved_merged_source_names = [
        str(item).strip()
        for item in (merged_source_names or [])
        if str(item).strip()
    ]
    if uploaded_files and len(uploaded_files) > 1 and not resolved_merged_source_names:
        resolved_merged_source_names = [
            str(item.filename or "").strip()
            for item in uploaded_files
            if str(item.filename or "").strip()
        ]
    if resolved_merged_source_names:
        source_context["allow_related_profiles"] = bool(allow_related_profiles or len(resolved_merged_source_names) > 1)
    return enrich_source_context_with_filename_hints(
        source_context,
        source_name=source_name,
        merged_source_names=resolved_merged_source_names,
    )


async def _save_uploaded_file(
    upload: UploadFile,
    *,
    target_dir: Path,
    index: int,
    settings,
) -> Path:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in settings.allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"File extension {suffix!r} not allowed. Allowed: {settings.allowed_extensions}",
        )

    original_name = Path(upload.filename or f"video_{index + 1}{suffix}").name
    target_path = target_dir / f"{index:02d}_{original_name}"
    total_size = 0

    try:
        with target_path.open("wb") as handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if settings.max_upload_size_bytes > 0 and total_size > settings.max_upload_size_bytes:
                    raise HTTPException(status_code=413, detail="File too large")
                handle.write(chunk)
    finally:
        await upload.close()

    return target_path


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
        metadata = dict(step.metadata_ or {})
        last_task_id = str(metadata.pop("task_id", "") or "").strip()
        metadata.pop("queue", None)
        metadata.pop("retry_wait_until", None)
        metadata.pop("retry_after_sec", None)
        if last_task_id:
            metadata["last_task_id"] = last_task_id
        metadata["updated_at"] = now.isoformat()
        if step.status == "pending":
            step.status = "skipped"
            step.finished_at = now
            step.metadata_ = {
                **metadata,
                "detail": "任务已取消，后续流程停止。",
            }
        elif step.status == "running":
            step.status = "cancelled"
            step.error_message = "Cancelled by user"
            step.finished_at = now
            step.metadata_ = {
                **metadata,
                "detail": "任务已取消，后续流程停止。",
            }
    render_outputs_result = await session.execute(select(RenderOutput).where(RenderOutput.job_id == job_id))
    render_outputs = render_outputs_result.scalars().all()
    await session.commit()
    cleanup_job_runtime_files(
        str(job_id),
        artifacts=list(job.artifacts or []),
        render_outputs=render_outputs,
        purge_deliverables=True,
        preserve_storage_keys=[str(job.source_path or "").strip()],
    )
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
    if job.status not in {"done", "cancelled", "failed", "needs_review", "processing", "running"}:
        raise HTTPException(
            status_code=409,
            detail="Only completed, running, review-paused, cancelled, or failed jobs can be restarted",
        )

    _revoke_running_steps(job.steps or [])
    await _clear_job_runtime_state(job_id, session, source_path=str(job.source_path or "").strip())

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


@router.post("/{job_id}/initialize", response_model=JobOut)
async def initialize_job(
    job_id: uuid.UUID,
    body: JobInitializeIn,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "awaiting_init":
        raise HTTPException(status_code=409, detail="Only awaiting-init jobs can be initialized")

    now = datetime.now(timezone.utc)
    existing_source_context = _extract_job_source_context_from_steps(job.steps or [])
    source_context = _build_job_source_context(
        source_name=job.source_name,
        video_description=body.video_description,
        merged_source_names=[
            str(item).strip()
            for item in (existing_source_context.get("merged_source_names") or [])
            if str(item).strip()
        ],
        allow_related_profiles=bool(existing_source_context.get("allow_related_profiles")),
    )

    job.status = "pending"
    job.error_message = None
    job.updated_at = now
    job.language = body.language
    job.workflow_template = body.workflow_template
    job.workflow_mode = body.workflow_mode
    job.enhancement_modes = body.enhancement_modes
    job.output_dir = body.output_dir

    existing_step_names = {step.step_name for step in job.steps or []}
    for step_name in PIPELINE_STEPS:
        if step_name in existing_step_names:
            continue
        step = JobStep(job_id=job.id, step_name=step_name, status="pending")
        session.add(step)
        (job.steps or []).append(step)

    ordered_steps = _ordered_steps(job.steps or [])
    for step in ordered_steps:
        preserved_source_context = source_context if step.step_name == "content_profile" and source_context else None
        step.status = "pending"
        step.attempt = 0
        step.started_at = None
        step.finished_at = None
        step.error_message = None
        step.metadata_ = {"source_context": preserved_source_context} if preserved_source_context else None
    if ordered_steps:
        ordered_steps[0].metadata_ = {
            **(ordered_steps[0].metadata_ or {}),
            "detail": "任务已初始化，等待调度器派发。",
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
    await _clear_job_runtime_state(job_id, session, source_path="")
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
    if str(job.status or "").strip() == "needs_review":
        touch_runtime_refresh_hold(reason="content_profile_review", job_id=str(job_id), hold_seconds=90)

    from roughcut.db.models import Artifact

    artifact_result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(_CONTENT_PROFILE_ARTIFACT_TYPES),
        )
        .order_by(Artifact.created_at.desc())
    )
    artifacts = artifact_result.scalars().all()
    draft = next((item.data_json for item in artifacts if item.artifact_type == "content_profile_draft"), None)
    final = next((item.data_json for item in artifacts if item.artifact_type == "content_profile_final"), None)
    legacy = next((item.data_json for item in artifacts if item.artifact_type == "content_profile"), None)
    has_draft_artifact = isinstance(draft, dict) and bool(draft)
    if not isinstance(draft, dict) or not draft:
        draft = legacy
    if not isinstance(final, dict) or not final:
        final = None if has_draft_artifact else legacy
    settings = get_settings()
    if isinstance(draft, dict):
        draft = apply_current_content_profile_review_policy(draft, settings=settings)
        draft = _ensure_content_understanding_payload(draft)
    if isinstance(final, dict):
        final = apply_current_content_profile_review_policy(final, settings=settings)
        final = _ensure_content_understanding_payload(final)

    review_step_result = await session.execute(
        select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "summary_review")
    )
    review_step = review_step_result.scalar_one_or_none()
    active_profile = final if isinstance(final, dict) and final else draft if isinstance(draft, dict) and draft else {}
    automation_review = active_profile.get("automation_review") if isinstance(active_profile, dict) else {}
    user_memory = await load_content_profile_user_memory(session, subject_domain=(active_profile or {}).get("subject_domain"))
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
    evidence = await _load_content_profile_review_evidence(job_id, session)

    return ContentProfileReviewOut(
        job_id=str(job_id),
        status=job.status,
        review_step_status=review_step.status if review_step else "pending",
        review_step_detail=review_step_detail,
        review_reasons=review_reasons,
        blocking_reasons=blocking_reasons,
        identity_review=identity_review,
        **evidence,
        workflow_mode=str(getattr(job, "workflow_mode", "") or "standard_edit"),
        enhancement_modes=list(getattr(job, "enhancement_modes", []) or []),
        draft=draft,
        final=final,
        memory=memory,
    )


@router.get("/stats/content-profile-memory", response_model=ContentProfileMemoryStatsOut)
async def get_content_profile_memory_stats(
    subject_domain: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    user_memory = await load_content_profile_user_memory(session, subject_domain=subject_domain)
    subject_domain_result = await session.execute(
        select(distinct(ContentProfileCorrection.subject_domain))
        .where(ContentProfileCorrection.subject_domain.is_not(None))
        .order_by(ContentProfileCorrection.subject_domain)
    )
    subject_domains = [item for item in subject_domain_result.scalars().all() if item]

    correction_result = await session.execute(
        select(ContentProfileCorrection).order_by(ContentProfileCorrection.created_at.desc()).limit(240)
    )
    corrections = correction_result.scalars().all()

    keyword_result = await session.execute(select(ContentProfileKeywordStat))
    keyword_stats = keyword_result.scalars().all()

    total_corrections = sum(
        1
        for item in corrections
        if not subject_domain or item.subject_domain in {None, subject_domain}
    )
    total_keywords = sum(
        int(item.usage_count or 0)
        for item in keyword_stats
        if item.scope_type == "global"
        or (subject_domain and item.scope_type == "subject_domain" and item.scope_value == subject_domain)
    )

    return ContentProfileMemoryStatsOut(
        scope="subject_domain" if subject_domain else "global",
        subject_domain=subject_domain,
        subject_domains=subject_domains,
        total_corrections=total_corrections,
        total_keywords=total_keywords,
        field_preferences=_build_field_preferences(corrections, subject_domain=subject_domain, limit=6),
        keyword_preferences=_build_keyword_preferences(keyword_stats, subject_domain=subject_domain, limit=18),
        recent_corrections=_build_recent_corrections(corrections, subject_domain=subject_domain, limit=12),
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
    return FileResponse(
        thumbnail,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.post("/{job_id}/content-profile/thumbnails/warm")
async def warm_content_profile_thumbnails(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    for index in (0, 1, 2):
        _spawn_content_profile_thumbnail_generation(job, index=index)
    return {"status": "accepted", "job_id": str(job_id)}


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
    touch_runtime_refresh_hold(reason="content_profile_confirm", job_id=str(job_id), hold_seconds=120)

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
        workflow_template=job.workflow_template,
        user_feedback=user_feedback,
        reviewed_subtitle_excerpt=reviewed_subtitle_excerpt,
        accepted_corrections=accepted_corrections,
        skip_model_refinement=True,
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
    session.add(
        Artifact(
            job_id=job.id,
            step_id=review_step.id if review_step else None,
            artifact_type="downstream_context",
            data_json=build_downstream_context(final_profile),
        )
    )
    await record_content_profile_feedback_memory(
        session,
        job=job,
        draft_profile=draft_artifact.data_json or {},
        final_profile=final_profile,
        user_feedback=user_feedback,
    )
    await _persist_confirmed_content_profile_glossary_terms(
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
    user_memory = await load_content_profile_user_memory(
        session,
        subject_domain=str(final_profile.get("subject_domain") or ""),
    )
    memory = dict(user_memory or {})
    memory["cloud"] = build_content_profile_memory_cloud(user_memory)
    await session.commit()

    review_step_detail = None
    if review_step is not None:
        review_step_detail = str((review_step.metadata_ or {}).get("detail") or "").strip() or None
    automation_review = final_profile.get("automation_review") if isinstance(final_profile, dict) else {}
    identity_review = final_profile.get("identity_review") if isinstance(final_profile, dict) else None
    evidence = await _load_content_profile_review_evidence(job_id, session)
    draft_profile = _ensure_content_understanding_payload(draft_artifact.data_json)
    final_profile = _ensure_content_understanding_payload(final_profile)

    return ContentProfileReviewOut(
        job_id=str(job_id),
        status=job.status,
        review_step_status=review_step.status if review_step else "done",
        review_step_detail=review_step_detail,
        review_reasons=list((automation_review or {}).get("review_reasons") or []),
        blocking_reasons=list((automation_review or {}).get("blocking_reasons") or []),
        identity_review=identity_review if isinstance(identity_review, dict) else None,
        **evidence,
        workflow_mode=job.workflow_mode,
        enhancement_modes=list(job.enhancement_modes or []),
        draft=draft_profile,
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
    _resolve_download_variant_path(render_output, variant_value)
    return {
        "url": f"/api/v1/jobs/{job_id}/download/file?variant={variant_value}",
        "expires_in": None,
    }


@router.get("/{job_id}/download/file")
async def download_rendered_file(
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

    download_path = _resolve_download_variant_path(render_output, variant_value)
    filename = download_path.name
    media_type = "video/mp4" if download_path.suffix.lower() == ".mp4" else "application/octet-stream"
    return FileResponse(path=download_path, filename=filename, media_type=media_type)


def _resolve_download_variant_path(render_output: RenderOutput, variant: str) -> Path:
    base_output = Path(str(render_output.output_path or "")).expanduser()
    if not base_output.exists():
        raise HTTPException(status_code=404, detail="Rendered output file not found")

    if variant == "packaged":
        return base_output

    candidate_names = [
        base_output.name.replace("成片", "素板"),
        base_output.name.replace("成片", "素版"),
        base_output.name.replace("packaged", "plain"),
    ]
    for candidate_name in candidate_names:
        candidate = base_output.with_name(candidate_name)
        if candidate.exists():
            return candidate

    raise HTTPException(status_code=404, detail="Plain rendered output not found")


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


async def _clear_job_runtime_state(job_id: uuid.UUID, session: AsyncSession, *, source_path: str = "") -> None:
    packaging_artifacts = await session.execute(
        select(Artifact).where(Artifact.job_id == job_id)
    )
    render_outputs = await session.execute(select(RenderOutput).where(RenderOutput.job_id == job_id))
    artifact_rows = packaging_artifacts.scalars().all()
    render_output_rows = render_outputs.scalars().all()
    cleanup_job_runtime_files(
        str(job_id),
        artifacts=artifact_rows,
        render_outputs=render_output_rows,
        purge_deliverables=True,
        preserve_storage_keys=[source_path] if source_path else [],
    )
    _clear_content_profile_thumbnail_cache(job_id)

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
    touch_runtime_refresh_hold(reason="review_apply", job_id=str(job_id), hold_seconds=90)

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


@router.post("/{job_id}/final-review", response_model=FinalReviewDecisionOut)
async def apply_final_review_decision(
    job_id: uuid.UUID,
    request: FinalReviewDecisionIn,
    session: AsyncSession = Depends(get_session),
):
    job_result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps))
        .where(Job.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    review_step = next((step for step in job.steps or [] if step.step_name == "final_review"), None)
    if review_step is None:
        raise HTTPException(status_code=404, detail="Final review step not found")

    decision = str(request.decision or "").strip().lower()
    note = str(request.note or "").strip() or None
    if decision == "reject" and not note:
        raise HTTPException(status_code=400, detail="note is required when decision is reject")
    if decision == "approve" and review_step.status == "done":
        return FinalReviewDecisionOut(
            job_id=str(job.id),
            decision="approve",
            job_status=str(job.status),
            review_step_status=str(review_step.status),
            rerun_triggered=False,
            note=note,
        )
    if review_step.status == "done" and decision == "reject":
        raise HTTPException(status_code=409, detail="Final review has already been approved")

    now = datetime.now(timezone.utc)
    session.add(
        ReviewAction(
            job_id=job.id,
            target_type="final_review",
            target_id=job.id,
            action=decision,
            override_text=note,
        )
    )

    if decision == "approve":
        metadata = dict(review_step.metadata_ or {})
        metadata.update(
            {
                "detail": "成片已人工审核通过，继续生成平台文案。",
                "updated_at": now.isoformat(),
                "approved_via": "web",
            }
        )
        review_step.metadata_ = metadata
        review_step.status = "done"
        review_step.finished_at = now
        review_step.error_message = None
        job.status = "processing"
        job.error_message = None
        job.updated_at = now
        await session.commit()
        return FinalReviewDecisionOut(
            job_id=str(job.id),
            decision="approve",
            job_status=str(job.status),
            review_step_status=str(review_step.status),
            rerun_triggered=False,
            note=note,
        )

    feedback_history = list((review_step.metadata_ or {}).get("feedback_history") or [])
    feedback_history.append({"text": note, "at": now.isoformat(), "via": "web"})
    rerun_triggered = False

    from roughcut.pipeline.orchestrator import _reset_job_for_quality_rerun
    from roughcut.review.telegram_bot import (
        _build_final_review_rerun_plans,
        _combine_final_review_rerun_plans,
        _extract_final_review_content_profile_feedback,
    )

    rerun_plan = _combine_final_review_rerun_plans(_build_final_review_rerun_plans(note))
    if rerun_plan is not None:
        review_user_feedback = _extract_final_review_content_profile_feedback(note)
        steps = (
            await session.execute(
                select(JobStep).where(JobStep.job_id == job.id).order_by(JobStep.id.asc())
            )
        ).scalars().all()
        await _reset_job_for_quality_rerun(
            session,
            job,
            steps,
            rerun_steps=list(rerun_plan.rerun_steps),
            issue_codes=[f"manual_review:{rerun_plan.category}"],
        )
        first_step = next((step for step in steps if step.step_name == rerun_plan.trigger_step), None)
        if first_step is not None:
            first_metadata = dict(first_step.metadata_ or {})
            first_metadata.update(
                {
                    "detail": f"人工成片审核要求重跑：{rerun_plan.label}",
                    "updated_at": now.isoformat(),
                    "review_feedback": note,
                    "review_rerun_category": rerun_plan.category,
                    "review_rerun_steps": list(rerun_plan.rerun_steps),
                    "review_rerun_targets": list(rerun_plan.targets),
                }
            )
            if review_user_feedback:
                first_metadata["review_user_feedback"] = review_user_feedback
            first_step.metadata_ = first_metadata
        rerun_triggered = True
        await session.commit()
        return FinalReviewDecisionOut(
            job_id=str(job.id),
            decision="reject",
            job_status=str(job.status),
            review_step_status=str(review_step.status),
            rerun_triggered=rerun_triggered,
            note=note,
        )

    metadata = dict(review_step.metadata_ or {})
    metadata.update(
        {
            "detail": "已收到成片修改意见，任务保持暂停，等待人工处理后再继续。",
            "updated_at": now.isoformat(),
            "feedback_history": feedback_history[-10:],
            "latest_feedback": note,
        }
    )
    review_step.metadata_ = metadata
    review_step.started_at = review_step.started_at or now
    job.status = "needs_review"
    job.updated_at = now
    await session.commit()
    return FinalReviewDecisionOut(
        job_id=str(job.id),
        decision="reject",
        job_status=str(job.status),
        review_step_status=str(review_step.status),
        rerun_triggered=rerun_triggered,
        note=note,
    )


@router.post("/{job_id}/final-review/rerender-variant-timeline", response_model=FinalReviewVariantTimelineRerenderOut)
async def rerender_final_review_variant_timeline(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
):
    job_result = await session.execute(
        select(Job)
        .options(selectinload(Job.steps))
        .where(Job.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    artifacts = (
        await session.execute(
            select(Artifact).where(Artifact.job_id == job.id).order_by(Artifact.created_at.asc(), Artifact.id.asc())
        )
    ).scalars().all()
    bundle = _resolve_effective_variant_bundle_from_artifacts(artifacts)
    validation = bundle.get("validation") if isinstance(bundle, dict) else None
    issues = [str(item).strip() for item in (validation.get("issues") or []) if str(item).strip()] if isinstance(validation, dict) else []
    validation_status = str(validation.get("status") or "").strip().lower() if isinstance(validation, dict) else None
    if not issues or validation_status not in {"warning", "error"}:
        raise HTTPException(status_code=409, detail="No variant timeline warning detected for this job")

    steps = list(job.steps or [])
    if not steps:
        raise HTTPException(status_code=409, detail="Job steps are missing")

    rerun_steps = ["render", "final_review", "platform_package"]

    from roughcut.pipeline.orchestrator import _reset_job_for_quality_rerun

    await _reset_job_for_quality_rerun(
        session,
        job,
        steps,
        rerun_steps=rerun_steps,
        issue_codes=["variant_timeline_warning"],
    )

    now = datetime.now(timezone.utc)
    render_step = next((step for step in steps if step.step_name == "render"), None)
    if render_step is not None:
        metadata = dict(render_step.metadata_ or {})
        metadata.update(
            {
                "detail": "时间轴对齐告警触发重渲染：render -> final_review -> platform_package",
                "updated_at": now.isoformat(),
                "variant_timeline_validation_status": validation_status,
                "variant_timeline_validation_issues": issues[:10],
            }
        )
        render_step.metadata_ = metadata

    session.add(
        ReviewAction(
            job_id=job.id,
            target_type="final_review",
            target_id=job.id,
            action="rerender_variant_timeline",
            override_text="时间轴对齐告警触发重渲染",
        )
    )
    await session.commit()
    return FinalReviewVariantTimelineRerenderOut(
        job_id=str(job.id),
        job_status=str(job.status),
        rerun_steps=rerun_steps,
        validation_status=validation_status,
        validation_issue_count=len(issues),
    )


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

    profile_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job.id,
        artifact_types=_CONTENT_PROFILE_ARTIFACT_TYPES,
    )
    content_profile = {}
    if profile_artifact and isinstance(profile_artifact.data_json, dict):
        content_profile = dict(profile_artifact.data_json)

    detected_domains = detect_glossary_domains(
        workflow_template=job.workflow_template,
        content_profile=content_profile,
    )
    scopes: list[tuple[str, str]] = []
    for domain in detected_domains:
        pair = ("domain", domain)
        if pair not in scopes:
            scopes.append(pair)

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
                    context_hint=f"reviewed_from_job:{job.workflow_template or 'auto'}",
                )
            )
            continue
        wrong_forms = [str(item or "").strip() for item in (term.wrong_forms or []) if str(item or "").strip()]
        if original not in wrong_forms and original != suggested:
            wrong_forms.append(original)
            term.wrong_forms = wrong_forms


def _normalize_review_glossary_value(value: Any, *, max_length: int = 64) -> str:
    return " ".join(str(value or "").strip().split())[:max_length]


def _is_generic_review_hotword(value: str) -> bool:
    normalized = _normalize_review_glossary_value(value, max_length=64)
    lowered = normalized.lower()
    return lowered in {
        "",
        "unknown",
        "待确认",
        "未确认",
        "产品",
        "开箱产品",
        "主体",
        "视频主题",
        "内容主题",
    }


def _should_persist_review_alias(original: Any, corrected: Any) -> bool:
    original_text = _normalize_review_glossary_value(original, max_length=48)
    corrected_text = _normalize_review_glossary_value(corrected, max_length=48)
    if not original_text or not corrected_text or original_text == corrected_text:
        return False
    if model_numbers_conflict(original_text, corrected_text):
        return False
    if _is_generic_review_hotword(original_text) or _is_generic_review_hotword(corrected_text):
        return False
    return True


def _should_persist_review_hotword(value: Any, *, allow_phrase: bool = False) -> bool:
    text = _normalize_review_glossary_value(value, max_length=64 if allow_phrase else 48)
    if not text or _is_generic_review_hotword(text):
        return False
    if "\n" in text or "\r" in text:
        return False
    if not allow_phrase and len(text) < 2:
        return False
    if allow_phrase and len(text) < 2:
        return False
    return True


def _extract_confirmed_content_profile_alias_rows(final_profile: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    if not isinstance(final_profile, dict):
        return []
    identity_review = final_profile.get("identity_review")
    if not isinstance(identity_review, dict):
        return []
    evidence_bundle = identity_review.get("evidence_bundle")
    if not isinstance(evidence_bundle, dict):
        return []
    matched_glossary_aliases = evidence_bundle.get("matched_glossary_aliases")
    if not isinstance(matched_glossary_aliases, dict):
        return []

    rows: list[tuple[str, str, str]] = []
    field_specs = (
        ("subject_brand", "brand", "candidate_brand"),
        ("subject_model", "model", "candidate_model"),
    )
    for field_name, alias_key, candidate_key in field_specs:
        final_value = _normalize_review_glossary_value((final_profile or {}).get(field_name), max_length=48)
        candidate_value = _normalize_review_glossary_value(evidence_bundle.get(candidate_key), max_length=48)
        if not final_value or not candidate_value or final_value != candidate_value:
            continue
        for alias in matched_glossary_aliases.get(alias_key) or []:
            alias_value = _normalize_review_glossary_value(alias, max_length=48)
            if _should_persist_review_alias(alias_value, final_value):
                rows.append((field_name, alias_value, final_value))
    return rows


def _resolve_content_profile_glossary_scopes(
    *,
    job: Job,
    content_profile: dict[str, Any] | None,
) -> list[tuple[str, str]]:
    detected_domains = detect_glossary_domains(
        workflow_template=job.workflow_template,
        content_profile=content_profile or {},
    )
    scopes: list[tuple[str, str]] = []
    for domain in detected_domains:
        pair = ("domain", domain)
        if pair not in scopes:
            scopes.append(pair)
    return scopes


async def _upsert_review_glossary_term(
    session: AsyncSession,
    *,
    scope_type: str,
    scope_value: str,
    correct_form: str,
    wrong_form: str | None = None,
    category: str | None = None,
    context_hint: str | None = None,
) -> None:
    normalized_correct = _normalize_review_glossary_value(correct_form, max_length=64)
    normalized_wrong = _normalize_review_glossary_value(wrong_form, max_length=48) if wrong_form else ""
    conflicting_model_alias = bool(
        normalized_wrong and model_numbers_conflict(normalized_wrong, normalized_correct)
    )
    if not normalized_correct:
        return

    result = await session.execute(
        select(GlossaryTerm).where(
            GlossaryTerm.scope_type == scope_type,
            GlossaryTerm.scope_value == scope_value,
            GlossaryTerm.correct_form == normalized_correct,
        )
    )
    term = result.scalar_one_or_none()
    if term is None:
        wrong_forms = (
            [normalized_wrong]
            if normalized_wrong and normalized_wrong != normalized_correct and not conflicting_model_alias
            else []
        )
        session.add(
            GlossaryTerm(
                scope_type=scope_type,
                scope_value=scope_value,
                wrong_forms=wrong_forms,
                correct_form=normalized_correct,
                category=category,
                context_hint=context_hint,
            )
        )
        return

    wrong_forms = [str(item or "").strip() for item in (term.wrong_forms or []) if str(item or "").strip()]
    if (
        normalized_wrong
        and normalized_wrong != normalized_correct
        and not conflicting_model_alias
        and normalized_wrong not in wrong_forms
    ):
        wrong_forms.append(normalized_wrong)
        term.wrong_forms = wrong_forms
    if not term.category and category:
        term.category = category
    if not term.context_hint and context_hint:
        term.context_hint = context_hint


async def _persist_confirmed_content_profile_glossary_terms(
    session: AsyncSession,
    *,
    job: Job,
    draft_profile: dict[str, Any] | None,
    final_profile: dict[str, Any] | None,
    user_feedback: dict[str, Any] | None,
    context_hint: str | None = None,
) -> None:
    scopes = _resolve_content_profile_glossary_scopes(job=job, content_profile=final_profile)
    if not scopes:
        return

    draft_payload = draft_profile if isinstance(draft_profile, dict) else {}
    final_payload = final_profile if isinstance(final_profile, dict) else {}
    feedback_payload = user_feedback if isinstance(user_feedback, dict) else {}
    resolved_context_hint = context_hint or f"manual_content_profile_review:{job.workflow_template or 'auto'}"

    alias_rows: list[tuple[str, str, str, str]] = []
    for field_name, category in (("subject_brand", "brand"), ("subject_model", "model")):
        original_value = _normalize_review_glossary_value(draft_payload.get(field_name), max_length=48)
        corrected_value = _normalize_review_glossary_value(final_payload.get(field_name), max_length=48)
        if _should_persist_review_alias(original_value, corrected_value):
            alias_rows.append((field_name, original_value, corrected_value, category))

    for field_name, alias_value, canonical_value in _extract_confirmed_content_profile_alias_rows(final_payload):
        category = "brand" if field_name == "subject_brand" else "model"
        if _should_persist_review_alias(alias_value, canonical_value):
            alias_rows.append((field_name, alias_value, canonical_value, category))

    seen_alias_pairs: set[tuple[str, str, str]] = set()
    for field_name, wrong_value, correct_value, category in alias_rows:
        key = (field_name, wrong_value, correct_value)
        if key in seen_alias_pairs:
            continue
        seen_alias_pairs.add(key)
        for scope_type, scope_value in scopes:
            await _upsert_review_glossary_term(
                session,
                scope_type=scope_type,
                scope_value=scope_value,
                correct_form=correct_value,
                wrong_form=wrong_value,
                category=category,
                context_hint=resolved_context_hint,
            )

    canonical_terms: list[tuple[str, str]] = []
    for field_name, category in (
        ("subject_brand", "brand"),
        ("subject_model", "model"),
        ("subject_type", "subject_type"),
    ):
        value = _normalize_review_glossary_value(final_payload.get(field_name), max_length=48)
        if _should_persist_review_hotword(value):
            canonical_terms.append((value, category))

    keywords = feedback_payload.get("keywords")
    if not isinstance(keywords, list) or not keywords:
        keywords = final_payload.get("search_queries") or []
    normalized_keywords = normalize_query_list(
        [_normalize_review_glossary_value(item, max_length=64) for item in keywords if str(item or "").strip()]
    )
    for keyword in normalized_keywords:
        if _should_persist_review_hotword(keyword, allow_phrase=True):
            canonical_terms.append((keyword, "hotword"))

    seen_terms: set[tuple[str, str]] = set()
    for correct_value, category in canonical_terms:
        key = (correct_value, category)
        if key in seen_terms:
            continue
        seen_terms.add(key)
        for scope_type, scope_value in scopes:
            await _upsert_review_glossary_term(
                session,
                scope_type=scope_type,
                scope_value=scope_value,
                correct_form=correct_value,
                category=category,
                context_hint=resolved_context_hint,
            )


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
                    STUCK_STEP_DIAGNOSTIC_ARTIFACT_TYPE,
                    QUALITY_ARTIFACT_TYPE,
                ]
            ),
        )
        .order_by(Artifact.created_at.desc())
    )
    artifacts = artifact_result.scalars().all()
    set_committed_value(job, "artifacts", artifacts)
    _attach_job_preview(job, lightweight=True)

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
    events = _build_activity_events(job.steps or [], artifacts, timelines, render_output, job=job)

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
        review_step=job.review_step,
        review_detail=job.review_detail,
        current_step=current_step,
        render=render_payload,
        decisions=decisions,
        events=events,
    )


@router.get("/{job_id}/token-usage", response_model=TokenUsageReportOut)
async def get_job_token_usage(job_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    job_result = await session.execute(
        select(Job).options(selectinload(Job.steps)).where(Job.id == job_id)
    )
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    report = build_job_token_report(job.steps or [], step_labels=STEP_LABELS)
    return TokenUsageReportOut(
        job_id=str(job.id),
        has_telemetry=bool(report.get("has_telemetry")),
        total_calls=int(report.get("total_calls") or 0),
        total_prompt_tokens=int(report.get("total_prompt_tokens") or 0),
        total_completion_tokens=int(report.get("total_completion_tokens") or 0),
        total_tokens=int(report.get("total_tokens") or 0),
        steps=list(report.get("steps") or []),
        models=list(report.get("models") or []),
        cache=dict(report.get("cache") or {}),
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

    if job.status in {"failed", "cancelled"}:
        terminal_statuses = {"failed", "cancelled"}
        failed_step = _latest_terminal_step(steps, statuses=terminal_statuses)
        if failed_step is not None:
            return {
                "step_name": failed_step.step_name,
                "label": STEP_LABELS.get(failed_step.step_name, failed_step.step_name),
                "status": failed_step.status,
                "detail": _coalesce_step_error_detail(
                    failed_step,
                    fallback=job.error_message,
                ),
                "progress": None,
                "updated_at": _iso_or_none(failed_step.finished_at or failed_step.started_at or job.updated_at),
            }
        return {
            "step_name": steps[0].step_name if steps else "系统",
            "label": STEP_LABELS.get(steps[0].step_name, "任务") if steps else "任务",
            "status": job.status,
            "detail": job.error_message or "任务已结束但未产生可追踪步骤记录",
            "progress": None,
            "updated_at": _iso_or_none(job.updated_at),
        }

    if job.status == "needs_review":
        review_context = _resolve_job_review_context(job)
        if review_context["step_name"] is not None:
            return {
                "step_name": review_context["step_name"],
                "label": review_context["label"],
                "status": "needs_review",
                "detail": review_context["detail"],
                "progress": None,
                "updated_at": _iso_or_none(job.updated_at),
            }
        return {
            "step_name": "summary_review",
            "label": STEP_LABELS["summary_review"],
            "status": "needs_review",
            "detail": _review_step_waiting_detail("summary_review"),
            "progress": None,
            "updated_at": _iso_or_none(job.updated_at),
        }

    next_pending = next((step for step in steps if step.status == "pending"), None)
    if next_pending:
        meta = next_pending.metadata_ or {}
        detail = _pending_step_transition_detail(meta.get("detail"), next_pending, steps)
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

    profile = _select_preferred_content_profile_artifact([
        artifact
        for artifact in artifacts
        if artifact.artifact_type in {"content_profile", "content_profile_final", "content_profile_draft"}
    ])
    if profile and profile.data_json:
        data = profile.data_json
        subject = " · ".join(
            part for part in [data.get("subject_type"), data.get("video_theme")] if part
        ).strip() or "已生成视频类型识别"
        detail = "；".join(
            part for part in [
                f"模板：{data.get('workflow_template')}" if data.get("workflow_template") else "",
                f"摘要：{data.get('summary')}" if data.get("summary") else "",
            ] if part
        ) or None
        decisions.append(
            {
                "kind": "content_profile",
                "step_name": "content_profile",
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
                "step_name": "glossary_review",
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
                "step_name": "edit_plan",
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
                "step_name": "render",
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
                "step_name": "ai_director",
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
                "step_name": "avatar_commentary",
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
                "step_name": "platform_package",
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
        bundle = _resolve_effective_variant_bundle_from_artifacts(artifacts)
        timing_summary = _resolve_variant_timing_summary(bundle)
        validation_summary = _summarize_variant_timeline_validation(bundle)
        validation_detail = _describe_variant_timeline_validation(bundle)
        summary_parts = []
        if grade or score is not None:
            summary_parts.append(f"{grade} {float(score):.1f}" if grade and score is not None else str(grade or score))
        if issue_codes:
            summary_parts.append(f"{len(issue_codes)} 个扣分项")
        if timing_summary:
            summary_parts.append(timing_summary)
        if validation_summary:
            summary_parts.append(validation_summary)
        decisions.append(
            {
                "kind": "quality_assessment",
                "step_name": "final_review",
                "title": "质量评分",
                "status": "done",
                "summary": " · ".join(part for part in summary_parts if part).strip() or "质量评分已更新",
                "detail": (
                    "；".join(
                        part for part in [
                            f"问题：{', '.join(issue_codes)}" if issue_codes else "",
                            f"建议补跑：{', '.join(recommended_steps)}" if recommended_steps else "",
                            f"时间轴校验：{validation_detail}" if validation_detail else "",
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
    *,
    job: Job | None = None,
) -> list[dict]:
    events: list[dict] = []
    terminal_step = _latest_terminal_step(steps, statuses={"failed", "cancelled"}) if steps else None

    if job is not None and job.status in {"failed", "cancelled"} and job.error_message:
        events.append(
            {
                "timestamp": _iso_or_none(job.updated_at),
                "type": "error" if job.status == "failed" else "cancelled",
                "status": job.status,
                "step_name": terminal_step.step_name if terminal_step is not None else None,
                "title": "任务失败" if job.status == "failed" else "任务已取消",
                "detail": job.error_message,
            }
        )

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
                    "step_name": step.step_name,
                    "title": f"{label}开始",
                    "detail": None,
                }
            )
        if step.finished_at:
            if step.status in {"failed", "cancelled"}:
                detail = _coalesce_step_error_detail(step, fallback=step.error_message)
            else:
                detail = step.error_message or metadata.get("detail")
            events.append(
                {
                    "timestamp": _iso_or_none(step.finished_at),
                    "type": "step",
                    "status": step.status,
                    "step_name": step.step_name,
                    "title": f"{label}{'完成' if step.status == 'done' else '结束'}",
                    "detail": _decorate_step_detail(
                        detail,
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
                    "step_name": step.step_name,
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
                    "step_name": summary.get("step_name"),
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
                    "step_name": "edit_plan",
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
                "step_name": "render",
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
            "step_name": "probe",
            "title": "媒体参数已识别",
            "detail": f"{width}×{height} · {duration:.1f}s" if width and height and duration else "媒体信息已写入",
        }
    if artifact.artifact_type == "content_profile_draft":
        return {
            "step_name": "content_profile",
            "title": "内容摘要草稿已生成",
            "detail": str(data.get("summary") or data.get("video_theme") or "等待人工确认"),
        }
    if artifact.artifact_type in {"content_profile", "content_profile_final"}:
        return {
            "step_name": "summary_review" if artifact.artifact_type == "content_profile_final" else "content_profile",
            "title": "内容摘要已确认",
            "detail": str(data.get("summary") or data.get("video_theme") or "内容识别完成"),
        }
    if artifact.artifact_type == "platform_packaging_md":
        return {
            "step_name": "platform_package",
            "title": "平台文案已生成",
            "detail": artifact.storage_path or "发布文案已写入 Markdown",
        }
    if artifact.artifact_type == "ai_director_plan":
        return {
            "step_name": "ai_director",
            "title": "AI 导演建议已生成",
            "detail": str(data.get("opening_hook") or "已输出改写与重配音计划"),
        }
    if artifact.artifact_type == "avatar_commentary_plan":
        placement = str(data.get("overlay_position") or data.get("layout_template") or "").strip()
        return {
            "step_name": "avatar_commentary",
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
                "step_name": "avatar_commentary",
                "title": "数字人成片结果已回写",
                "detail": str(avatar_result.get("detail") or avatar_result.get("status") or "数字人结果已更新"),
            }
    if artifact.artifact_type == STUCK_STEP_DIAGNOSTIC_ARTIFACT_TYPE:
        return _stuck_step_diagnostic_summary(data)
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
            "step_name": "final_review",
            "title": title,
            "detail": detail or "质量评分已写入",
        }
    return None


def _latest_terminal_step(
    steps: list[JobStep],
    *,
    statuses: set[str] | None = None,
) -> JobStep | None:
    if not steps:
        return None
    allowed_statuses = set(statuses or {"done", "failed", "skipped", "cancelled"})
    for step in reversed(_ordered_steps(steps)):
        if step.status in allowed_statuses:
            return step
    return None


def _coalesce_step_error_detail(step: JobStep, *, fallback: str | None = None) -> str | None:
    metadata = step.metadata_ or {}
    details = []

    step_error = str(step.error_message or "").strip()
    if step_error:
        details.append(step_error)

    detail = str(metadata.get("detail") or "").strip()
    if detail:
        details.append(detail)

    recovery_summary = str(metadata.get("recovery_summary") or "").strip()
    if recovery_summary:
        details.append(f"恢复建议：{recovery_summary}")

    recovery_root_cause = str(metadata.get("recovery_root_cause") or "").strip()
    if recovery_root_cause:
        details.append(f"恢复根因：{recovery_root_cause}")

    if fallback:
        fallback_text = str(fallback).strip()
        if fallback_text and fallback_text not in details:
            details.append(fallback_text)

    cleaned_details = [item for item in details if item]
    return " · ".join(cleaned_details) if cleaned_details else None


def _pending_step_transition_detail(
    detail: Any,
    step: JobStep,
    steps: list[JobStep],
) -> str:
    raw_detail = str(detail or "").strip()
    if raw_detail:
        return raw_detail
    if _are_previous_steps_complete(steps, step.step_name):
        standardized_detail = _pending_step_standard_detail(step.step_name)
        if standardized_detail:
            return standardized_detail
        return "等待调度器派发。"
    return "等待前序步骤完成。"


def _stuck_step_diagnostic_summary(data: object) -> dict[str, str] | None:
    payload = data if isinstance(data, dict) else {}
    step_name = str(payload.get("step_name") or "未命名步骤").strip()
    summary = str(payload.get("summary") or "").strip()
    root_cause = str(payload.get("root_cause") or "").strip()
    confidence = payload.get("confidence")
    evidence = payload.get("evidence") if isinstance(payload, dict) else None
    recommended_action = payload.get("recommended_action") if isinstance(payload, dict) else None
    action_parts: list[str] = []
    if isinstance(recommended_action, dict):
        action_kind = str(recommended_action.get("kind") or "").strip()
        action_reason = str(recommended_action.get("reason") or "").strip()
        if action_kind:
            action_parts.append(action_kind)
        if action_reason:
            action_parts.append(action_reason)
    action = " / ".join(part for part in action_parts if part)

    stale_after = ""
    if isinstance(evidence, dict):
        stale_after_sec = evidence.get("stale_after_sec")
        if stale_after_sec is not None:
            stale_after = f"（阈值 {stale_after_sec}s）"

    details: list[str] = []
    if summary:
        details.append(summary)
    if root_cause:
        details.append(f"根因：{root_cause}")
    if action:
        details.append(f"恢复建议：{action}{stale_after}")
    if isinstance(confidence, (float, int)):
        details.append(f"置信度：{float(confidence):.2f}")

    return {
        "step_name": step_name or None,
        "title": f"{step_name} 卡住诊断",
        "detail": " · ".join(part for part in details if part) or "检测到步骤卡住并已写入诊断记录。",
    }


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


def _attach_job_previews(jobs: list[Job], *, lightweight: bool = False) -> None:
    for job in jobs:
        _attach_job_preview(job, lightweight=lightweight)


def _attach_job_preview(job: Job, *, lightweight: bool = False) -> None:
    if job.steps:
        job.steps.sort(key=_step_sort_key)
    source_context = _extract_job_source_context_from_steps(job.steps or [])
    job.merged_source_names = _resolve_job_merged_source_names(job)
    job.video_description = str(source_context.get("video_description") or "").strip() or None
    preview = _resolve_job_content_preview(job.artifacts or [], apply_review_memory=not lightweight)
    job.content_subject = preview["subject"]
    job.content_summary = preview["summary"]
    quality_preview = _resolve_job_quality_preview(job.artifacts or [])
    job.quality_score = quality_preview["score"]
    job.quality_grade = quality_preview["grade"]
    job.quality_summary = quality_preview["summary"]
    job.quality_issue_codes = quality_preview["issue_codes"]
    job.timeline_diagnostics = _resolve_job_timeline_diagnostics_preview(job.artifacts or [])
    avatar_preview = _resolve_job_avatar_preview(job)
    job.avatar_delivery_status = avatar_preview["status"]
    job.avatar_delivery_summary = avatar_preview["summary"]
    auto_review_preview = _resolve_job_auto_review_preview(job)
    job.auto_review_mode_enabled = bool(auto_review_preview["mode_enabled"])
    job.auto_review_status = auto_review_preview["status"]
    job.auto_review_summary = auto_review_preview["summary"]
    job.auto_review_reasons = list(auto_review_preview["reasons"] or [])
    review_preview = _resolve_job_review_context(job)
    job.review_step = review_preview["step_name"]
    job.review_label = review_preview["label"]
    job.review_detail = review_preview["detail"]
    job.awaiting_initialization = str(job.status or "").strip() == "awaiting_init"
    job.progress_percent = _calculate_job_progress_percent(job)


def _extract_job_source_context_from_steps(steps: list[JobStep]) -> dict[str, Any]:
    for step in list(steps or []):
        if step.step_name != "content_profile" or not isinstance(step.metadata_, dict):
            continue
        source_context = step.metadata_.get("source_context")
        if isinstance(source_context, dict):
            return dict(source_context)
    return {}


def _resolve_job_merged_source_names(job: Job) -> list[str]:
    source_context = _extract_job_source_context_from_steps(job.steps or [])
    merged_source_names = [
        str(item).strip()
        for item in (source_context.get("merged_source_names") or [])
        if str(item).strip()
    ]
    if merged_source_names:
        return merged_source_names
    return []


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


def _resolve_job_content_preview(
    artifacts: list[Artifact],
    *,
    apply_review_memory: bool = True,
) -> dict[str, str | None]:
    profile = _select_preview_artifact(artifacts)
    if not profile or not profile.data_json:
        return {"subject": None, "summary": None}

    data = profile.data_json
    def _normalize_preview_value(value: object) -> str:
        normalized = str(value or "").strip()
        if normalized.lower() in {"unknown", "n/a", "none", "null"}:
            return ""
        if normalized in {"未知", "待确认", "内容待确认", "待人工确认", "未识别"}:
            return ""
        return normalized

    product = " ".join(
        part.strip()
        for part in [
            _normalize_preview_value(data.get("subject_brand")),
            _normalize_preview_value(data.get("subject_model")),
        ]
        if part and str(part).strip()
    ).strip()
    subject_parts = [
        product,
        _normalize_preview_value(data.get("subject_type")),
        _normalize_preview_value(data.get("video_theme")),
    ]
    subject = " · ".join(part for part in subject_parts if part).strip() or None
    summary = str(data.get("summary") or data.get("hook_line") or "").strip() or None
    if apply_review_memory:
        subject = _normalize_preview_text_with_review_memory(subject, data)
        summary = _normalize_preview_text_with_review_memory(summary, data)
    return {"subject": subject, "summary": summary}


def _normalize_preview_text_with_review_memory(text: str | None, data: dict[str, Any]) -> str | None:
    value = str(text or "").strip() or None
    if not value:
        return None
    if not _preview_has_trusted_review_context(data):
        return value
    review_memory = _build_preview_review_memory(data)
    if not review_memory:
        return value
    normalized = _apply_preview_alias_corrections(value, review_memory)
    return str(normalized or "").strip() or value


def _preview_has_trusted_review_context(data: dict[str, Any]) -> bool:
    payload = data if isinstance(data, dict) else {}
    content_understanding = payload.get("content_understanding") if isinstance(payload.get("content_understanding"), dict) else {}
    video_type = normalize_video_type(
        str(content_understanding.get("video_type") or payload.get("content_kind") or "").strip()
    )
    if not video_type:
        return False
    explicit_domain = str(content_understanding.get("content_domain") or payload.get("subject_domain") or "").strip()
    if explicit_domain:
        return True
    context_profile = {
        "subject_type": str(payload.get("subject_type") or "").strip(),
        "video_theme": str(payload.get("video_theme") or "").strip(),
    }
    detected_domains = detect_glossary_domains(
        workflow_template=str(payload.get("workflow_template") or "").strip() or None,
        content_profile=context_profile,
        subtitle_items=None,
    )
    return bool(detected_domains)


def _build_preview_review_memory(data: dict[str, Any]) -> dict[str, Any] | None:
    payload = data if isinstance(data, dict) else {}
    content_understanding = payload.get("content_understanding") if isinstance(payload.get("content_understanding"), dict) else {}
    subject_domain = str(content_understanding.get("content_domain") or payload.get("subject_domain") or "").strip() or None
    preview_profile = {
        "workflow_template": str(payload.get("workflow_template") or "").strip(),
        "content_kind": str(payload.get("content_kind") or "").strip(),
        "subject_domain": subject_domain or "",
        "subject_brand": str(payload.get("subject_brand") or "").strip(),
        "subject_model": str(payload.get("subject_model") or "").strip(),
        "subject_type": str(payload.get("subject_type") or "").strip(),
        "video_theme": str(payload.get("video_theme") or "").strip(),
    }
    return build_subtitle_review_memory(
        workflow_template=preview_profile["workflow_template"] or None,
        subject_domain=subject_domain,
        glossary_terms=[],
        user_memory={},
        recent_subtitles=[],
        content_profile=preview_profile,
        include_recent_terms=False,
        include_recent_examples=False,
    )


def _apply_preview_alias_corrections(text: str, review_memory: dict[str, Any] | None) -> str:
    result = str(text or "").strip()
    if not result:
        return result
    for item in (review_memory or {}).get("aliases") or []:
        wrong = str(item.get("wrong") or "").strip()
        correct = str(item.get("correct") or "").strip()
        if not wrong or not correct or wrong == correct:
            continue
        result = re.sub(re.escape(wrong), correct, result, flags=re.IGNORECASE)
    return result


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _resolve_job_auto_review_preview(job: Job) -> dict[str, Any]:
    enabled_modes = set(getattr(job, "enhancement_modes", []) or [])
    if "auto_review" not in enabled_modes:
        return {
            "mode_enabled": False,
            "status": None,
            "summary": None,
            "reasons": [],
        }

    review_step = _find_step(list(job.steps or []), "summary_review")
    profile_artifact = _select_preview_artifact(list(job.artifacts or []))
    profile_payload = profile_artifact.data_json if profile_artifact and isinstance(profile_artifact.data_json, dict) else {}
    automation = profile_payload.get("automation_review") if isinstance(profile_payload.get("automation_review"), dict) else {}

    auto_confirmed = bool((review_step.metadata_ or {}).get("auto_confirmed")) if review_step is not None else False
    if not auto_confirmed:
        auto_confirmed = str(profile_payload.get("review_mode") or "").strip().lower() == "auto_confirmed"
    if auto_confirmed:
        detail = str((review_step.metadata_ or {}).get("detail") or "").strip() if review_step is not None else ""
        return {
            "mode_enabled": True,
            "status": "applied",
            "summary": detail or "已自动确认预审核并继续执行。",
            "reasons": [],
        }

    if not profile_payload:
        waiting_detail = "已启用，等待内容画像后评估是否自动放行。"
        if _has_reached_step(job, "content_profile"):
            waiting_detail = "已启用，等待系统完成自动审核评估。"
        return {
            "mode_enabled": True,
            "status": "enabled",
            "summary": waiting_detail,
            "reasons": [],
        }

    blocking_reasons = [
        str(item).strip()
        for item in (automation.get("blocking_reasons") or [])
        if str(item).strip()
    ]
    review_reasons = [
        str(item).strip()
        for item in (automation.get("review_reasons") or [])
        if str(item).strip()
    ]
    approval_accuracy_detail = str(automation.get("approval_accuracy_detail") or "").strip()
    quality_gate_passed = bool(automation.get("quality_gate_passed"))
    accuracy_gate_passed = bool(automation.get("approval_accuracy_gate_passed"))
    score = _coerce_float(automation.get("score"))
    threshold = _coerce_float(automation.get("threshold"))

    reasons: list[str] = []
    if blocking_reasons:
        reasons.extend(blocking_reasons)
    elif review_reasons:
        reasons.extend(review_reasons)
    if approval_accuracy_detail and not accuracy_gate_passed and approval_accuracy_detail not in reasons:
        reasons.append(approval_accuracy_detail)

    if blocking_reasons:
        summary = "已启用，但本次命中人工复核条件，未自动放行。"
        status = "blocked"
    elif not quality_gate_passed:
        if score is not None and threshold is not None:
            summary = f"已启用，但当前摘要得分 {score:.2f} 未达到自动放行阈值 {threshold:.2f}。"
        else:
            summary = "已启用，但当前摘要未达到自动放行阈值。"
        status = "blocked"
    elif not accuracy_gate_passed:
        summary = approval_accuracy_detail or "已启用，但自动放行准确率门槛尚未通过。"
        status = "blocked"
    else:
        summary = "已启用，等待系统在摘要阶段自动判定是否直接放行。"
        status = "enabled"

    return {
        "mode_enabled": True,
        "status": status,
        "summary": summary,
        "reasons": reasons,
    }


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
    bundle = _resolve_effective_variant_bundle_from_artifacts(artifacts)
    timing_summary = _resolve_variant_timing_summary(bundle)
    validation_summary = _summarize_variant_timeline_validation(bundle)
    summary = " · ".join(
        part
        for part in [
            f"{grade} {score:.1f}" if grade and score is not None else (grade or (f"{score:.1f}" if score is not None else "")),
            f"{len(issue_codes)} 个扣分项" if issue_codes else "",
            timing_summary or "",
            validation_summary or "",
        ]
        if part
    ) or None
    return {
        "score": score,
        "grade": grade,
        "summary": summary,
        "issue_codes": issue_codes,
    }


def _resolve_job_timeline_diagnostics_preview(artifacts: list[Artifact]) -> dict[str, Any] | None:
    bundle = _resolve_effective_variant_bundle_from_artifacts(artifacts)
    timeline_rules = bundle.get("timeline_rules") if isinstance(bundle, dict) else None
    diagnostics = timeline_rules.get("diagnostics") if isinstance(timeline_rules, dict) else None
    if not isinstance(diagnostics, dict):
        return None

    review_flags = diagnostics.get("review_flags") if isinstance(diagnostics.get("review_flags"), dict) else {}
    llm_cut_review = diagnostics.get("llm_cut_review") if isinstance(diagnostics.get("llm_cut_review"), dict) else {}
    high_risk_cuts = [item for item in (diagnostics.get("high_risk_cuts") or []) if isinstance(item, dict)]
    high_energy_keeps = [item for item in (diagnostics.get("high_energy_keeps") or []) if isinstance(item, dict)]
    review_reasons = [str(item).strip() for item in (review_flags.get("review_reasons") or []) if str(item).strip()]

    preview = {
        "review_recommended": bool(review_flags.get("review_recommended")),
        "review_reasons": review_reasons[:3],
        "high_risk_cut_count": len(high_risk_cuts),
        "high_energy_keep_count": len(high_energy_keeps),
        "llm_reviewed": bool(llm_cut_review.get("reviewed")),
        "llm_candidate_count": int(llm_cut_review.get("candidate_count") or 0),
        "llm_restored_cut_count": int(llm_cut_review.get("restored_cut_count") or 0),
        "llm_provider": str(llm_cut_review.get("provider") or "").strip() or None,
        "llm_summary": str(llm_cut_review.get("summary") or "").strip() or None,
    }
    if any(
        (
            preview["review_recommended"],
            preview["high_risk_cut_count"],
            preview["high_energy_keep_count"],
            preview["llm_reviewed"],
            preview["llm_restored_cut_count"],
            preview["review_reasons"],
            preview["llm_summary"],
        )
    ):
        return preview
    return None


def _resolve_waiting_review_step(steps: list[JobStep]) -> JobStep | None:
    return next(
        (
            step for step in steps
            if step.step_name in {"summary_review", "final_review"} and step.status == "pending"
        ),
        None,
    )


def _review_step_waiting_detail(step_name: str) -> str:
    normalized = str(step_name or "").strip().lower()
    if normalized == "final_review":
        return "等待审核成片后继续生成平台文案。"
    return "等待确认摘要后继续剪辑与渲染。"


def _pending_step_standard_detail(step_name: str) -> str | None:
    normalized = str(step_name or "").strip().lower()
    if normalized == "summary_review":
        return "等待人工确认摘要。"
    if normalized == "final_review":
        return "等待人工审核成片。"
    if normalized == "platform_package":
        return "等待调度器派发生成平台文案。"
    return None


def _job_has_final_review_signals(job: Job | None) -> bool:
    if job is None:
        return False
    return bool(
        getattr(job, "quality_score", None) is not None
        or str(getattr(job, "quality_grade", "") or "").strip()
        or str(getattr(job, "quality_summary", "") or "").strip()
        or list(getattr(job, "quality_issue_codes", []) or [])
        or getattr(job, "timeline_diagnostics", None)
    )


def _resolve_job_review_context(job: Job) -> dict[str, str | None]:
    if str(job.status or "").strip() != "needs_review":
        return {"step_name": None, "label": None, "detail": None}

    steps = _ordered_steps(job.steps or [])
    review_step = _resolve_waiting_review_step(steps)
    if review_step is None:
        final_review_step = _find_step(steps, "final_review")
        summary_review_step = _find_step(steps, "summary_review")
        if final_review_step is not None and final_review_step.status != "done" and (
            _job_has_final_review_signals(job) or summary_review_step is None
        ):
            review_step = final_review_step
        elif summary_review_step is not None and summary_review_step.status != "done":
            review_step = summary_review_step
        elif final_review_step is not None and final_review_step.status != "done":
            review_step = final_review_step

    if review_step is None:
        return {
            "step_name": "summary_review",
            "label": STEP_LABELS["summary_review"],
            "detail": _review_step_waiting_detail("summary_review"),
        }

    return {
        "step_name": review_step.step_name,
        "label": STEP_LABELS.get(review_step.step_name, review_step.step_name),
        "detail": _review_step_waiting_detail(review_step.step_name),
    }


def _resolve_effective_variant_bundle_from_artifacts(artifacts: list[Artifact]) -> dict[str, Any] | None:
    bundle_artifact = next(
        (artifact for artifact in artifacts if artifact.artifact_type == "variant_timeline_bundle" and artifact.data_json),
        None,
    )
    render_outputs_artifact = next(
        (artifact for artifact in artifacts if artifact.artifact_type == "render_outputs" and artifact.data_json),
        None,
    )
    return resolve_effective_variant_timeline_bundle(
        bundle_artifact.data_json if bundle_artifact and isinstance(bundle_artifact.data_json, dict) else None,
        render_outputs=render_outputs_artifact.data_json if render_outputs_artifact and isinstance(render_outputs_artifact.data_json, dict) else {},
    )


def _resolve_variant_timing_summary(bundle: dict[str, Any] | None) -> str | None:
    if bundle is None or not isinstance(bundle, dict):
        return None
    variants = bundle.get("variants")
    if not isinstance(variants, dict):
        return None
    packaged_variant = variants.get("packaged")
    if not isinstance(packaged_variant, dict):
        return None
    subtitle_events = packaged_variant.get("subtitle_events")
    if not isinstance(subtitle_events, list):
        return None

    event_count = 0
    first_start: float | None = None
    last_end: float | None = None
    for item in subtitle_events:
        if not isinstance(item, dict):
            continue
        event_count += 1
        start_value = _coerce_timing_value(
            item.get("start_time", item.get("start_sec", item.get("start")))
        )
        end_value = _coerce_timing_value(item.get("end_time", item.get("end_sec", item.get("end"))))
        if start_value is not None:
            first_start = start_value if first_start is None else min(first_start, start_value)
        if end_value is not None:
            last_end = end_value if last_end is None else max(last_end, end_value)

    if event_count <= 0:
        return None

    parts = [f"packaged {event_count} 条字幕"]
    if first_start is not None and last_end is not None:
        parts.append(f"{first_start:.1f}-{last_end:.1f}s")
    elif first_start is not None:
        parts.append(f"起始 {first_start:.1f}s")
    elif last_end is not None:
        parts.append(f"结束 {last_end:.1f}s")
    return " · ".join(parts)


def _summarize_variant_timeline_validation(bundle: dict[str, Any] | None) -> str | None:
    validation = bundle.get("validation") if isinstance(bundle, dict) else None
    if not isinstance(validation, dict):
        return None
    issues = [str(item).strip() for item in (validation.get("issues") or []) if str(item).strip()]
    status = str(validation.get("status") or "").strip().lower()
    if not issues and status in {"", "ok"}:
        return None
    label = "时间轴异常" if status == "error" else "时间轴告警"
    return f"{label} {len(issues)} 项" if issues else label


def _describe_variant_timeline_validation(bundle: dict[str, Any] | None, *, limit: int = 3) -> str | None:
    validation = bundle.get("validation") if isinstance(bundle, dict) else None
    if not isinstance(validation, dict):
        return None
    issues = [str(item).strip() for item in (validation.get("issues") or []) if str(item).strip()]
    if not issues:
        return None
    visible = issues[:limit]
    if len(issues) > limit:
        visible.append(f"其余 {len(issues) - limit} 项省略")
    return "；".join(visible)


def _coerce_timing_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    cache_dir = _content_profile_thumbnail_cache_dir(job.id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"profile_{index:02d}.jpg"
    if cached.exists() and not _should_retry_placeholder_thumbnail(cached):
        return cached

    lock = _CONTENT_PROFILE_THUMBNAIL_LOCKS.setdefault(f"{job.id}:{index}", asyncio.Lock())
    async with lock:
        if cached.exists() and not _should_retry_placeholder_thumbnail(cached):
            return cached
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                source_path = await _resolve_job_source(job, tmpdir)
            except FileNotFoundError:
                _write_content_profile_placeholder_thumbnail(job, cached, index=index)
                return cached
            loop = asyncio.get_running_loop()
            async with _CONTENT_PROFILE_THUMBNAIL_GENERATION_SEMAPHORE:
                success = await loop.run_in_executor(
                    None,
                    _extract_reference_frame,
                    source_path,
                    cache_dir,
                    index,
                    3,
                )
            if not success:
                _write_content_profile_placeholder_thumbnail(job, cached, index=index)
                return cached
        if not cached.exists():
            _write_content_profile_placeholder_thumbnail(job, cached, index=index)
    return cached


def _content_profile_thumbnail_cache_dir(job_id: uuid.UUID | str) -> Path:
    return (
        Path(tempfile.gettempdir())
        / "roughcut_content_profile_frames"
        / _CONTENT_PROFILE_THUMBNAIL_CACHE_VERSION
        / str(job_id)
    )


def _clear_content_profile_thumbnail_cache(job_id: uuid.UUID | str) -> None:
    job_id_str = str(job_id)
    prefix = f"{job_id_str}:"
    for key in [key for key in _CONTENT_PROFILE_THUMBNAIL_WARM_TASKS if key.startswith(prefix)]:
        task = _CONTENT_PROFILE_THUMBNAIL_WARM_TASKS.pop(key, None)
        if task and not task.done():
            task.cancel()
    for key in [key for key in _CONTENT_PROFILE_THUMBNAIL_LOCKS if key.startswith(prefix)]:
        _CONTENT_PROFILE_THUMBNAIL_LOCKS.pop(key, None)
    shutil.rmtree(_content_profile_thumbnail_cache_dir(job_id_str), ignore_errors=True)


def _spawn_content_profile_thumbnail_generation(job: Job, *, index: int) -> bool:
    key = f"{job.id}:{index}"
    existing = _CONTENT_PROFILE_THUMBNAIL_WARM_TASKS.get(key)
    if existing and not existing.done():
        return False

    async def runner() -> bool:
        try:
            await _ensure_content_profile_thumbnail(job, index=index)
        except Exception:
            return False
        return True

    task = asyncio.create_task(runner())
    _CONTENT_PROFILE_THUMBNAIL_WARM_TASKS[key] = task

    def _cleanup(_task: asyncio.Task) -> None:
        _CONTENT_PROFILE_THUMBNAIL_WARM_TASKS.pop(key, None)

    task.add_done_callback(_cleanup)
    return True


def _extract_reference_frame(source_path: Path, cache_dir: Path, index: int, total_frames: int) -> bool:
    out = cache_dir / f"profile_{index:02d}.jpg"
    out.unlink(missing_ok=True)
    try:
        total_frames = max(1, min(int(total_frames or 1), 10))
        index = max(0, min(int(index or 0), total_frames - 1))
        duration = _probe_duration(source_path)
        if duration <= 0:
            return False

        safe_margin = min(max(duration * 0.08, 1.0), max(duration / 4, 0.0))
        usable_start = safe_margin if duration > safe_margin * 2 else 0.0
        usable_end = duration - safe_margin if duration > safe_margin * 2 else duration
        usable_duration = max(usable_end - usable_start, duration)
        segment_start = usable_start + (usable_duration * index / max(total_frames, 1))
        segment_end = usable_start + (usable_duration * (index + 1) / max(total_frames, 1))
        segment_length = max(segment_end - segment_start, 0.8)
        seek = max(segment_start + (segment_length / 2), 0.0)

        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{segment_start:.2f}",
                "-t",
                f"{segment_length:.2f}",
                "-i",
                str(source_path),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                "-vf",
                "thumbnail=90,scale=960:-2",
                str(out),
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0 or not out.exists():
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{seek:.2f}",
                    "-i",
                    str(source_path),
                    "-frames:v",
                    "1",
                    "-update",
                    "1",
                    "-q:v",
                    "3",
                    "-vf",
                    "scale=960:-2",
                    str(out),
                ],
                capture_output=True,
                timeout=20,
            )
        return result.returncode == 0 and out.exists()
    except Exception:
        return False



async def _resolve_job_source(job: Job, tmpdir: str) -> Path:
    storage = get_storage()
    candidate_keys = [
        str(job.source_path or "").strip(),
        job_key(str(job.id), "output_plain.mp4"),
        job_key(str(job.id), "output.mp4"),
        job_key(str(job.id), "output_ai_effect.mp4"),
    ]
    resolve_path = getattr(storage, "resolve_path", None)

    for candidate_key in candidate_keys:
        if not candidate_key:
            continue
        if callable(resolve_path):
            resolved = resolve_path(candidate_key)
            if resolved.exists() and resolved.is_file():
                return resolved
        local_name = Path(str(candidate_key).replace("s3://", "", 1)).name or job.source_name
        local_path = Path(tmpdir) / local_name
        try:
            await storage.async_download_file(candidate_key, local_path)
        except FileNotFoundError:
            continue
        if local_path.exists():
            return local_path

    raise FileNotFoundError(f"Unable to resolve source media for job {job.id}")


def _write_content_profile_placeholder_thumbnail(job: Job, target_path: Path, *, index: int) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(_CONTENT_PROFILE_PLACEHOLDER_JPEG)


def _is_content_profile_placeholder_thumbnail(path: Path) -> bool:
    try:
        return path.is_file() and path.read_bytes() == _CONTENT_PROFILE_PLACEHOLDER_JPEG
    except OSError:
        return False


def _should_retry_placeholder_thumbnail(path: Path) -> bool:
    if not path.exists():
        return True
    if not _is_content_profile_placeholder_thumbnail(path):
        return False
    try:
        age_seconds = max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return True
    return age_seconds >= _CONTENT_PROFILE_PLACEHOLDER_RETRY_SECONDS


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
