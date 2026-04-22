from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ["TELEGRAM_REMOTE_REVIEW_ENABLED"] = "false"
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_TRANSCRIPTION_PROVIDER = "local_http_asr"
DEFAULT_TRANSCRIPTION_MODEL = "local-asr-current"
DEFAULT_LOCAL_ASR_API_BASE_URL = "http://127.0.0.1:6001"

from sqlalchemy import select

from roughcut.db.models import Artifact, Job, JobStep, SubtitleCorrection, SubtitleItem, TranscriptSegment
from roughcut.db.session import get_session_factory
from roughcut.pipeline.orchestrator import create_job_steps
from roughcut.pipeline.steps import run_step_sync
from roughcut.watcher.folder_watcher import create_jobs_for_inventory_paths

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
CORE_SUBTITLE_PROOF_STEPS = [
    "subtitle_postprocess",
    "subtitle_term_resolution",
    "subtitle_consistency_review",
    "glossary_review",
    "transcript_review",
]
LIVE_TEST_STEPS = [
    "probe",
    "extract_audio",
    "transcribe",
    *CORE_SUBTITLE_PROOF_STEPS,
]
SUBTITLE_EVAL_STEPS = list(CORE_SUBTITLE_PROOF_STEPS)
SKIPPED_DOWNSTREAM_STEPS = [
    "subtitle_translation",
    "content_profile",
    "summary_review",
    "ai_director",
    "avatar_commentary",
    "edit_plan",
    "render",
    "final_review",
    "platform_package",
]
CONTENT_PROFILE_ARTIFACT_TYPES = ("content_profile_final", "content_profile", "content_profile_draft")


@dataclass
class RowReport:
    source_name: str
    source_path: str
    status: str
    job_id: str | None
    job_origin: str | None
    workflow_template: str | None
    transcription_provider: str | None
    transcription_model: str | None
    local_asr_api_base_url: str | None
    subtitle_count: int | None
    correction_count: int | None
    auto_accepted_correction_count: int | None
    pending_correction_count: int | None
    term_patch_count: int | None
    term_pending_count: int | None
    lexical_bad_term_total: int | None
    semantic_bad_term_total: int | None
    bad_term_total: int | None
    short_fragment_count: int | None
    short_fragment_rate: float | None
    filler_count: int | None
    filler_rate: float | None
    low_signal_count: int | None
    low_signal_rate: float | None
    subtitle_quality_score: float | None
    subtitle_quality_blocking: bool | None
    subtitle_quality_blocking_reasons: list[str]
    subtitle_quality_warning_reasons: list[str]
    subtitle_consistency_score: float | None
    subtitle_consistency_blocking: bool | None
    subtitle_consistency_blocking_reasons: list[str]
    subtitle_consistency_warning_reasons: list[str]
    content_profile_artifact_type: str | None
    needs_review: bool | None
    review_reasons: list[str]
    subject_brand: str | None
    subject_model: str | None
    subject_type: str | None
    video_theme: str | None
    summary: str | None
    subtitle_excerpt: list[str]
    step_statuses: dict[str, str]
    error: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run live subtitle/proofreading validation on sampled videos without edit/render steps."
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path(r"Y:\EDC系列\视频原片"),
    )
    parser.add_argument("--sample-count", type=int, default=10)
    parser.add_argument("--random-seed", type=int, default=20260420)
    parser.add_argument("--workflow-template", default="edc_tactical")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--transcription-provider", default=DEFAULT_TRANSCRIPTION_PROVIDER)
    parser.add_argument("--transcription-model", default=DEFAULT_TRANSCRIPTION_MODEL)
    parser.add_argument("--local-asr-api-base-url", default=DEFAULT_LOCAL_ASR_API_BASE_URL)
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=ROOT / "output" / "test",
    )
    parser.add_argument(
        "--report-prefix",
        default="live_subtitle_proof_batch",
    )
    parser.add_argument(
        "--samples",
        nargs="*",
        default=[],
        help="Optional explicit file names to run instead of random sampling.",
    )
    return parser.parse_args()


def _safe_float(value: Any) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float | None]) -> float | None:
    numbers = [float(item) for item in values if item is not None]
    if not numbers:
        return None
    return round(sum(numbers) / len(numbers), 2)


def apply_runtime_transcription_env(args: argparse.Namespace) -> None:
    os.environ["TRANSCRIPTION_PROVIDER"] = str(args.transcription_provider or DEFAULT_TRANSCRIPTION_PROVIDER).strip()
    os.environ["TRANSCRIPTION_MODEL"] = str(args.transcription_model or DEFAULT_TRANSCRIPTION_MODEL).strip()
    os.environ["LOCAL_ASR_API_BASE_URL"] = str(
        args.local_asr_api_base_url or DEFAULT_LOCAL_ASR_API_BASE_URL
    ).strip()


def list_source_files(source_dir: Path) -> list[Path]:
    files = [
        path
        for path in source_dir.rglob("*")
        if path.is_file()
        and path.suffix.lower() in VIDEO_EXTENSIONS
        and "已剪" not in path.stem
        and "已剪辑" not in path.stem
    ]
    files.sort(key=lambda path: (str(path.parent).lower(), path.name.lower()))
    return files


def select_files(files: list[Path], *, sample_count: int, random_seed: int, samples: list[str]) -> list[Path]:
    requested = [str(item).strip() for item in (samples or []) if str(item).strip()]
    if requested:
        requested_set = set(requested)
        selected = [path for path in files if path.name in requested_set]
        missing = [name for name in requested if name not in {path.name for path in selected}]
        if missing:
            raise RuntimeError(f"Missing requested samples: {', '.join(missing)}")
        return selected

    if sample_count <= 0:
        raise RuntimeError("sample-count must be greater than 0")
    if sample_count >= len(files):
        return list(files)

    rng = random.Random(random_seed)
    return sorted(rng.sample(files, sample_count), key=lambda path: path.name.lower())


async def _clone_rerun_job_from_existing(
    session,
    *,
    source_job: Job,
    workflow_template: str,
    language: str,
) -> str:
    transcript_rows = (
        await session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.job_id == source_job.id, TranscriptSegment.version == 1)
            .order_by(TranscriptSegment.segment_index)
        )
    ).scalars().all()
    media_meta_artifact = (
        await session.execute(
            select(Artifact)
            .where(Artifact.job_id == source_job.id, Artifact.artifact_type == "media_meta")
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
    ).scalars().first()
    audio_artifact = (
        await session.execute(
            select(Artifact)
            .where(Artifact.job_id == source_job.id, Artifact.artifact_type == "audio_wav")
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
    ).scalars().first()
    job_id = uuid.uuid4()
    cloned_job = Job(
        id=job_id,
        source_path=source_job.source_path,
        source_name=source_job.source_name,
        file_hash=source_job.file_hash,
        status="pending",
        error_message=None,
        workflow_template=workflow_template or source_job.workflow_template,
        output_dir=source_job.output_dir,
        config_profile_id=source_job.config_profile_id,
        config_profile_snapshot_json=dict(source_job.config_profile_snapshot_json or {}) or None,
        packaging_snapshot_json=dict(source_job.packaging_snapshot_json or {}) or None,
        language=language or source_job.language,
        workflow_mode=source_job.workflow_mode,
        enhancement_modes=list(source_job.enhancement_modes or []),
    )
    session.add(cloned_job)
    step_map: dict[str, JobStep] = {}
    now = datetime.now(timezone.utc)
    for step in create_job_steps(job_id):
        if step.step_name == "probe" and media_meta_artifact is not None:
            step.status = "done"
            step.started_at = now
            step.finished_at = now
            step.metadata_ = {
                "detail": f"cloned_from:{source_job.id}",
                "progress": 1.0,
                "label": step.step_name,
                "updated_at": now.isoformat(),
            }
        elif step.step_name == "extract_audio" and audio_artifact is not None:
            step.status = "done"
            step.started_at = now
            step.finished_at = now
            step.metadata_ = {
                "detail": f"cloned_from:{source_job.id}",
                "progress": 1.0,
                "label": step.step_name,
                "updated_at": now.isoformat(),
            }
        elif step.step_name == "transcribe" and transcript_rows:
            step.status = "done"
            step.started_at = now
            step.finished_at = now
            step.metadata_ = {
                "detail": f"cloned_from:{source_job.id}",
                "progress": 1.0,
                "label": step.step_name,
                "updated_at": now.isoformat(),
            }
        session.add(step)
        step_map[step.step_name] = step

    if media_meta_artifact is not None and step_map.get("probe") is not None:
        session.add(
            Artifact(
                job_id=job_id,
                step_id=step_map["probe"].id,
                artifact_type="media_meta",
                storage_path=media_meta_artifact.storage_path,
                data_json=dict(media_meta_artifact.data_json or {}) or None,
            )
        )
    if audio_artifact is not None and step_map.get("extract_audio") is not None:
        session.add(
            Artifact(
                job_id=job_id,
                step_id=step_map["extract_audio"].id,
                artifact_type="audio_wav",
                storage_path=audio_artifact.storage_path,
                data_json=dict(audio_artifact.data_json or {}) or None,
            )
        )
    for row in transcript_rows:
        session.add(
            TranscriptSegment(
                job_id=job_id,
                version=row.version,
                segment_index=row.segment_index,
                start_time=row.start_time,
                end_time=row.end_time,
                speaker=row.speaker,
                text=row.text,
                words_json=list(row.words_json or []),
            )
        )
    return str(job_id)


async def _pick_reusable_source_job(session, *, source_name: str) -> Job | None:
    candidates = (
        await session.execute(
            select(Job).where(Job.source_name == source_name).order_by(Job.created_at.desc(), Job.id.desc())
        )
    ).scalars().all()
    for candidate in candidates:
        transcript_exists = (
            await session.execute(
                select(TranscriptSegment.id)
                .where(TranscriptSegment.job_id == candidate.id, TranscriptSegment.version == 1)
                .limit(1)
            )
        ).scalar_one_or_none()
        if transcript_exists is not None:
            return candidate
    return candidates[0] if candidates else None


async def clone_or_prepare_job_for_source(
    source_path: Path,
    *,
    workflow_template: str,
    language: str,
) -> tuple[str, str]:
    factory = get_session_factory()
    async with factory() as session:
        existing_job = await _pick_reusable_source_job(session, source_name=source_path.name)
        if existing_job is not None:
            job_id = await _clone_rerun_job_from_existing(
                session,
                source_job=existing_job,
                workflow_template=workflow_template,
                language=language,
            )
            await session.commit()
            transcript_exists = (
                await session.execute(
                    select(TranscriptSegment.id)
                    .where(TranscriptSegment.job_id == existing_job.id, TranscriptSegment.version == 1)
                    .limit(1)
                )
            ).scalar_one_or_none()
            return job_id, "cloned_transcript_eval" if transcript_exists is not None else "cloned_source_eval"

    created = await create_jobs_for_inventory_paths(
        [str(source_path)],
        workflow_template=workflow_template,
        language=language,
    )
    job_id = str(created[0].get("job_id") or "").strip()
    if not job_id:
        raise RuntimeError(f"Failed to create job for {source_path.name}")
    return job_id, "fresh_import"


def mark_step(job_id: str, step_name: str, status: str, *, error: str | None = None) -> None:
    async def _update() -> None:
        factory = get_session_factory()
        async with factory() as session:
            step = (
                await session.execute(
                    select(JobStep).where(JobStep.job_id == uuid.UUID(job_id), JobStep.step_name == step_name)
                )
            ).scalar_one()
            now = datetime.now(timezone.utc)
            step.status = status
            if status == "running":
                step.started_at = now
                step.finished_at = None
                step.error_message = None
            elif status in {"done", "failed", "cancelled"}:
                step.finished_at = now
                step.error_message = error
            await session.commit()

    asyncio.run(_update())


def finalize_job(job_id: str, *, status: str, error: str | None = None) -> None:
    async def _finalize() -> None:
        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(Job, uuid.UUID(job_id))
            if job is None:
                return
            job.status = status
            job.error_message = error
            job.updated_at = datetime.now(timezone.utc)
            await session.commit()

    asyncio.run(_finalize())


def run_job_steps(job_id: str, *, steps: list[str]) -> None:
    for step_name in steps:
        mark_step(job_id, step_name, "running")
        try:
            run_step_sync(step_name, job_id)
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
            mark_step(job_id, step_name, "failed", error=error_text)
            finalize_job(job_id, status="failed", error=error_text)
            raise
        mark_step(job_id, step_name, "done")


async def _load_latest_artifact(
    session,
    *,
    job_uuid: uuid.UUID,
    artifact_types: tuple[str, ...],
) -> Artifact | None:
    return (
        await session.execute(
            select(Artifact)
            .where(Artifact.job_id == job_uuid, Artifact.artifact_type.in_(artifact_types))
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
    ).scalars().first()


def _subtitle_line(item: SubtitleItem) -> str:
    for value in (item.text_final, item.text_norm, item.text_raw):
        text = str(value or "").strip()
        if text:
            return text
    return ""


async def collect_row_report(
    *,
    source_path: Path,
    job_id: str,
    job_origin: str,
    workflow_template: str,
    transcription_provider: str,
    transcription_model: str,
    local_asr_api_base_url: str,
    error: str | None = None,
) -> RowReport:
    factory = get_session_factory()
    async with factory() as session:
        job_uuid = uuid.UUID(job_id)
        quality_artifact = await _load_latest_artifact(
            session,
            job_uuid=job_uuid,
            artifact_types=("subtitle_quality_report",),
        )
        consistency_artifact = await _load_latest_artifact(
            session,
            job_uuid=job_uuid,
            artifact_types=("subtitle_consistency_report",),
        )
        term_patch_artifact = await _load_latest_artifact(
            session,
            job_uuid=job_uuid,
            artifact_types=("subtitle_term_resolution_patch",),
        )
        profile_artifact = await _load_latest_artifact(
            session,
            job_uuid=job_uuid,
            artifact_types=CONTENT_PROFILE_ARTIFACT_TYPES,
        )
        corrections = (
            await session.execute(select(SubtitleCorrection).where(SubtitleCorrection.job_id == job_uuid))
        ).scalars().all()
        subtitle_rows = (
            await session.execute(
                select(SubtitleItem)
                .where(SubtitleItem.job_id == job_uuid)
                .order_by(SubtitleItem.version.desc(), SubtitleItem.item_index.asc())
            )
        ).scalars().all()
        latest_subtitle_version = max((int(item.version or 0) for item in subtitle_rows), default=0)
        subtitles = [item for item in subtitle_rows if int(item.version or 0) == latest_subtitle_version]
        steps = (
            await session.execute(
                select(JobStep).where(JobStep.job_id == job_uuid).order_by(JobStep.id.asc())
            )
        ).scalars().all()

        quality = dict((quality_artifact.data_json if quality_artifact else None) or {})
        consistency = dict((consistency_artifact.data_json if consistency_artifact else None) or {})
        term_patch = dict((term_patch_artifact.data_json if term_patch_artifact else None) or {})
        profile = dict((profile_artifact.data_json if profile_artifact else None) or {})
        verification_gate = dict(profile.get("verification_gate") or {})
        quality_metrics = dict(quality.get("metrics") or {})

        auto_accepted_corrections = sum(
            1 for item in corrections if bool(item.auto_applied) or item.human_decision == "accepted"
        )
        pending_corrections = sum(
            1 for item in corrections if item.human_decision not in {"accepted", "rejected"}
        )
        review_reasons = [
            str(item).strip()
            for item in list(profile.get("review_reasons") or verification_gate.get("review_reasons") or [])
            if str(item).strip()
        ]

        return RowReport(
            source_name=source_path.name,
            source_path=str(source_path),
            status="failed" if error else "done",
            job_id=job_id,
            job_origin=job_origin,
            workflow_template=workflow_template,
            transcription_provider=transcription_provider,
            transcription_model=transcription_model,
            local_asr_api_base_url=local_asr_api_base_url,
            subtitle_count=len(subtitles),
            correction_count=len(corrections),
            auto_accepted_correction_count=auto_accepted_corrections,
            pending_correction_count=pending_corrections,
            term_patch_count=int(((term_patch.get("metrics") or {}).get("patch_count")) or 0) if term_patch else None,
            term_pending_count=int(((term_patch.get("metrics") or {}).get("pending_count")) or 0) if term_patch else None,
            lexical_bad_term_total=int(quality_metrics.get("lexical_bad_term_total") or 0) if quality else None,
            semantic_bad_term_total=int(quality_metrics.get("semantic_bad_term_total") or 0) if quality else None,
            bad_term_total=int(quality_metrics.get("bad_term_total") or 0) if quality else None,
            short_fragment_count=int(quality_metrics.get("short_fragment_count") or 0) if quality else None,
            short_fragment_rate=_safe_float(quality_metrics.get("short_fragment_rate")) if quality else None,
            filler_count=int(quality_metrics.get("filler_count") or 0) if quality else None,
            filler_rate=_safe_float(quality_metrics.get("filler_rate")) if quality else None,
            low_signal_count=int(quality_metrics.get("low_signal_count") or 0) if quality else None,
            low_signal_rate=_safe_float(quality_metrics.get("low_signal_rate")) if quality else None,
            subtitle_quality_score=_safe_float(quality.get("score")),
            subtitle_quality_blocking=bool(quality.get("blocking")) if quality else None,
            subtitle_quality_blocking_reasons=[
                str(item).strip() for item in list(quality.get("blocking_reasons") or []) if str(item).strip()
            ],
            subtitle_quality_warning_reasons=[
                str(item).strip() for item in list(quality.get("warning_reasons") or []) if str(item).strip()
            ],
            subtitle_consistency_score=_safe_float(consistency.get("score")),
            subtitle_consistency_blocking=bool(consistency.get("blocking")) if consistency else None,
            subtitle_consistency_blocking_reasons=[
                str(item).strip() for item in list(consistency.get("blocking_reasons") or []) if str(item).strip()
            ],
            subtitle_consistency_warning_reasons=[
                str(item).strip() for item in list(consistency.get("warning_reasons") or []) if str(item).strip()
            ],
            content_profile_artifact_type=str(profile_artifact.artifact_type) if profile_artifact else None,
            needs_review=bool(profile.get("needs_review") or verification_gate.get("needs_review")) if profile else None,
            review_reasons=review_reasons,
            subject_brand=str(profile.get("subject_brand") or "").strip() or None,
            subject_model=str(profile.get("subject_model") or "").strip() or None,
            subject_type=str(profile.get("subject_type") or "").strip() or None,
            video_theme=str(profile.get("video_theme") or "").strip() or None,
            summary=str(profile.get("summary") or "").strip() or None,
            subtitle_excerpt=[line for line in (_subtitle_line(item) for item in subtitles[:8]) if line],
            step_statuses={str(item.step_name): str(item.status) for item in steps},
            error=error,
        )


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Live Subtitle Proofreading Batch Report",
        "",
        f"- created_at: {report.get('created_at')}",
        f"- source_dir: {report.get('source_dir')}",
        f"- sample_count: {report.get('sample_count')}",
        f"- random_seed: {report.get('random_seed')}",
        f"- workflow_template: {report.get('workflow_template')}",
        f"- transcription_provider: {report.get('transcription_provider')}",
        f"- transcription_model: {report.get('transcription_model')}",
        f"- local_asr_api_base_url: {report.get('local_asr_api_base_url')}",
        f"- executed_steps: {', '.join(report.get('executed_steps') or [])}",
        f"- skipped_steps: {', '.join(report.get('skipped_steps') or [])}",
        "",
        "## Summary",
        "",
        f"- done_count: {report.get('done_count')}",
        f"- failed_count: {report.get('failed_count')}",
        f"- subtitle_quality_blocking_jobs: {report.get('summary_metrics', {}).get('subtitle_quality_blocking_jobs')}",
        f"- subtitle_consistency_blocking_jobs: {report.get('summary_metrics', {}).get('subtitle_consistency_blocking_jobs')}",
        f"- needs_review_jobs: {report.get('summary_metrics', {}).get('needs_review_jobs')}",
        f"- jobs_with_pending_corrections: {report.get('summary_metrics', {}).get('jobs_with_pending_corrections')}",
        f"- avg_short_fragment_rate: {report.get('summary_metrics', {}).get('avg_short_fragment_rate')}",
        f"- avg_filler_rate: {report.get('summary_metrics', {}).get('avg_filler_rate')}",
        f"- total_lexical_bad_terms: {report.get('summary_metrics', {}).get('total_lexical_bad_terms')}",
        f"- total_semantic_bad_terms: {report.get('summary_metrics', {}).get('total_semantic_bad_terms')}",
        f"- total_pending_term_patches: {report.get('summary_metrics', {}).get('total_pending_term_patches')}",
        f"- avg_subtitle_quality_score: {report.get('summary_metrics', {}).get('avg_subtitle_quality_score')}",
        f"- avg_subtitle_consistency_score: {report.get('summary_metrics', {}).get('avg_subtitle_consistency_score')}",
        "",
        "## Samples",
        "",
    ]
    for sample in report.get("sample_files") or []:
        lines.append(f"- {sample}")
    lines.extend(["", "## Jobs", ""])
    for row in report.get("rows") or []:
        lines.append(f"### {row.get('source_name')}")
        lines.append(f"- status: {row.get('status')}")
        lines.append(f"- job_id: {row.get('job_id') or ''}")
        lines.append(
            f"- transcription: {row.get('transcription_provider') or ''} / {row.get('transcription_model') or ''} @ {row.get('local_asr_api_base_url') or ''}"
        )
        lines.append(f"- subtitle_count: {row.get('subtitle_count')}")
        lines.append(f"- correction_count: {row.get('correction_count')}")
        lines.append(
            f"- auto_accepted_correction_count: {row.get('auto_accepted_correction_count')} | pending_correction_count: {row.get('pending_correction_count')}"
        )
        lines.append(
            f"- segmentation: short_fragments={row.get('short_fragment_count')} ({row.get('short_fragment_rate')}), fillers={row.get('filler_count')} ({row.get('filler_rate')}), low_signal={row.get('low_signal_count')} ({row.get('low_signal_rate')})"
        )
        lines.append(
            f"- proofreading: bad_terms={row.get('bad_term_total')} | lexical={row.get('lexical_bad_term_total')} | semantic={row.get('semantic_bad_term_total')} | term_patch_count={row.get('term_patch_count')} | term_pending_count={row.get('term_pending_count')}"
        )
        lines.append(
            f"- subtitle_quality_score: {row.get('subtitle_quality_score')} | blocking: {row.get('subtitle_quality_blocking')}"
        )
        if row.get("subtitle_quality_blocking_reasons"):
            lines.append(f"- subtitle_quality_blocking_reasons: {' / '.join(row.get('subtitle_quality_blocking_reasons') or [])}")
        if row.get("subtitle_quality_warning_reasons"):
            lines.append(f"- subtitle_quality_warning_reasons: {' / '.join(row.get('subtitle_quality_warning_reasons') or [])}")
        lines.append(f"- subtitle_consistency_score: {row.get('subtitle_consistency_score')} | blocking: {row.get('subtitle_consistency_blocking')}")
        if row.get("subtitle_consistency_blocking_reasons"):
            lines.append(
                f"- subtitle_consistency_blocking_reasons: {' / '.join(row.get('subtitle_consistency_blocking_reasons') or [])}"
            )
        if row.get("subtitle_consistency_warning_reasons"):
            lines.append(
                f"- subtitle_consistency_warning_reasons: {' / '.join(row.get('subtitle_consistency_warning_reasons') or [])}"
            )
        subject = " ".join(part for part in [row.get("subject_brand"), row.get("subject_model")] if part)
        if subject:
            lines.append(f"- subject: {subject}")
        if row.get("subject_type"):
            lines.append(f"- subject_type: {row.get('subject_type')}")
        if row.get("video_theme"):
            lines.append(f"- video_theme: {row.get('video_theme')}")
        if row.get("needs_review") is not None:
            lines.append(f"- needs_review: {row.get('needs_review')}")
        if row.get("review_reasons"):
            lines.append(f"- review_reasons: {' / '.join(row.get('review_reasons') or [])}")
        if row.get("summary"):
            lines.append(f"- summary: {row.get('summary')}")
        if row.get("subtitle_excerpt"):
            lines.append(f"- subtitle_excerpt: {' | '.join(row.get('subtitle_excerpt') or [])}")
        if row.get("error"):
            lines.append(f"- error: {row.get('error')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    args = parse_args()
    apply_runtime_transcription_env(args)
    files = list_source_files(args.source_dir)
    if not files:
        raise SystemExit(f"No source videos found in {args.source_dir}")

    selected_files = select_files(
        files,
        sample_count=max(1, int(args.sample_count or 0)),
        random_seed=int(args.random_seed or 0),
        samples=list(args.samples or []),
    )

    rows: list[RowReport] = []
    for index, path in enumerate(selected_files, start=1):
        print(f"[{index}/{len(selected_files)}] {path.name}", flush=True)
        job_id = ""
        job_origin = ""
        error_text: str | None = None
        try:
            job_id, job_origin = asyncio.run(
                clone_or_prepare_job_for_source(
                    path,
                    workflow_template=args.workflow_template,
                    language=args.language,
                )
            )
            steps_to_run = SUBTITLE_EVAL_STEPS if job_origin == "cloned_transcript_eval" else LIVE_TEST_STEPS
            run_job_steps(job_id, steps=steps_to_run)
            finalize_job(job_id, status="done")
        except Exception as exc:
            error_text = f"{type(exc).__name__}: {exc}"
        if job_id:
            row = asyncio.run(
                collect_row_report(
                    source_path=path,
                    job_id=job_id,
                    job_origin=job_origin,
                    workflow_template=args.workflow_template,
                    transcription_provider=args.transcription_provider,
                    transcription_model=args.transcription_model,
                    local_asr_api_base_url=args.local_asr_api_base_url,
                    error=error_text,
                )
            )
        else:
            row = RowReport(
                source_name=path.name,
                source_path=str(path),
                status="failed",
                job_id=None,
                job_origin=job_origin or None,
                workflow_template=args.workflow_template,
                transcription_provider=args.transcription_provider,
                transcription_model=args.transcription_model,
                local_asr_api_base_url=args.local_asr_api_base_url,
                subtitle_count=None,
                correction_count=None,
                auto_accepted_correction_count=None,
                pending_correction_count=None,
                term_patch_count=None,
                term_pending_count=None,
                lexical_bad_term_total=None,
                semantic_bad_term_total=None,
                bad_term_total=None,
                short_fragment_count=None,
                short_fragment_rate=None,
                filler_count=None,
                filler_rate=None,
                low_signal_count=None,
                low_signal_rate=None,
                subtitle_quality_score=None,
                subtitle_quality_blocking=None,
                subtitle_quality_blocking_reasons=[],
                subtitle_quality_warning_reasons=[],
                subtitle_consistency_score=None,
                subtitle_consistency_blocking=None,
                subtitle_consistency_blocking_reasons=[],
                subtitle_consistency_warning_reasons=[],
                content_profile_artifact_type=None,
                needs_review=None,
                review_reasons=[],
                subject_brand=None,
                subject_model=None,
                subject_type=None,
                video_theme=None,
                summary=None,
                subtitle_excerpt=[],
                step_statuses={},
                error=error_text,
            )
        rows.append(row)

    done_rows = [row for row in rows if row.status == "done"]
    failed_rows = [row for row in rows if row.status == "failed"]
    summary_metrics = {
        "subtitle_quality_blocking_jobs": sum(1 for row in done_rows if bool(row.subtitle_quality_blocking)),
        "subtitle_consistency_blocking_jobs": sum(1 for row in done_rows if bool(row.subtitle_consistency_blocking)),
        "needs_review_jobs": sum(1 for row in done_rows if bool(row.needs_review)),
        "jobs_with_pending_corrections": sum(1 for row in done_rows if int(row.pending_correction_count or 0) > 0),
        "avg_short_fragment_rate": _mean([row.short_fragment_rate for row in done_rows]),
        "avg_filler_rate": _mean([row.filler_rate for row in done_rows]),
        "total_lexical_bad_terms": sum(int(row.lexical_bad_term_total or 0) for row in done_rows),
        "total_semantic_bad_terms": sum(int(row.semantic_bad_term_total or 0) for row in done_rows),
        "total_pending_term_patches": sum(int(row.term_pending_count or 0) for row in done_rows),
        "avg_subtitle_quality_score": _mean([row.subtitle_quality_score for row in done_rows]),
        "avg_subtitle_consistency_score": _mean([row.subtitle_consistency_score for row in done_rows]),
    }
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(args.source_dir),
        "sample_count": len(selected_files),
        "random_seed": int(args.random_seed or 0),
        "workflow_template": args.workflow_template,
        "language": args.language,
        "transcription_provider": args.transcription_provider,
        "transcription_model": args.transcription_model,
        "local_asr_api_base_url": args.local_asr_api_base_url,
        "executed_steps": list(LIVE_TEST_STEPS),
        "skipped_steps": list(SKIPPED_DOWNSTREAM_STEPS),
        "sample_files": [path.name for path in selected_files],
        "done_count": len(done_rows),
        "failed_count": len(failed_rows),
        "summary_metrics": summary_metrics,
        "rows": [asdict(row) for row in rows],
    }

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    args.report_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.report_dir / f"{args.report_prefix}_{timestamp}.json"
    md_path = args.report_dir / f"{args.report_prefix}_{timestamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "done_count": len(done_rows),
                "failed_count": len(failed_rows),
                "sample_count": len(selected_files),
                "report_json": str(json_path),
                "report_md": str(md_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
