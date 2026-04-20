from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import delete, select

from roughcut.config import get_settings
from roughcut.creative.modes import resolve_live_batch_enhancement_modes
from roughcut.db.models import Artifact, Job, JobStep, RenderOutput, SubtitleCorrection, SubtitleItem, Timeline, TranscriptSegment
from roughcut.media.output import get_cover_manifest_path, get_legacy_cover_manifest_path
from roughcut.db.session import get_session_factory
from roughcut.pipeline.orchestrator import PIPELINE_STEPS
from roughcut.pipeline.live_readiness import build_live_readiness_summary, collect_job_issue_codes
from roughcut.pipeline.quality import assess_job_quality
from roughcut.pipeline.steps import run_step_sync
from roughcut.runtime_health import build_readiness_payload
from roughcut.review.final_review_state import mark_final_review_approved
from roughcut.review.content_profile import apply_content_profile_feedback
from roughcut.review.content_profile_memory import record_content_profile_feedback_memory
from roughcut.review.subtitle_consistency import ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT
from roughcut.review.subtitle_quality import ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT
from roughcut.review.subtitle_term_resolution import ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH
from roughcut.speech.subtitle_pipeline import ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER
from roughcut.watcher.folder_watcher import create_jobs_for_inventory_paths

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


@dataclass
class StepRun:
    step: str
    status: str
    elapsed_seconds: float
    detail: str = ""
    error: str = ""


@dataclass
class LiveStageValidation:
    stage: str
    status: str
    summary: str
    issue_codes: list[str] = field(default_factory=list)


@dataclass
class JobRunReport:
    job_id: str
    source_path: str
    source_name: str
    status: str
    output_path: str | None
    cover_path: str | None
    output_duration_sec: float
    transcript_segment_count: int
    subtitle_count: int
    correction_count: int
    keep_ratio: float
    cover_variant_count: int
    platform_doc: str | None
    quality_score: float | None
    quality_grade: str | None
    quality_issue_codes: list[str]
    live_stage_validations: list[LiveStageValidation]
    content_profile: dict[str, Any] | None
    steps: list[StepRun]
    notes: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a full-chain RoughCut batch on unedited local videos.")
    parser.add_argument("--source-dir", type=Path, default=ROOT / "watch")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--channel-profile", default="edc_tactical")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--scan-mode", choices=["fast", "precise"], default="fast")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "output" / "test" / "fullchain-batch")
    parser.add_argument(
        "--stop-after",
        choices=PIPELINE_STEPS,
        default=None,
        help="Stop after the specified step and still collect a partial report",
    )
    parser.add_argument("--output-dir", default=None)
    parser.add_argument(
        "--enhancement-mode",
        dest="enhancement_modes",
        action="append",
        default=[],
        help="Repeatable enhancement mode override",
    )
    parser.add_argument(
        "--source-name",
        dest="source_names",
        action="append",
        default=[],
        help="Repeatable exact source filename filter",
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=None,
        help="Optional JSON array or newline-delimited text file of exact source filenames to run",
    )
    parser.add_argument(
        "--pollution-audit",
        type=Path,
        default=None,
        help="Optional subtitle_pollution_audit.json used to derive exact source filenames",
    )
    parser.add_argument(
        "--manual-review-only",
        action="store_true",
        help="When used with --pollution-audit, only rerun jobs marked manual_review_required",
    )
    parser.add_argument(
        "--force-rerun-existing",
        action="store_true",
        help="Reset and rerun matching jobs even if a finished render already exists",
    )
    parser.add_argument(
        "--golden-manifest",
        type=Path,
        default=None,
        help="Optional JSON array or newline-delimited text file of golden source names",
    )
    parser.add_argument(
        "--previous-batch-report",
        dest="previous_batch_reports",
        action="append",
        default=[],
        help="Repeatable prior batch_report.json path used to evaluate consecutive stable runs",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    ensure_batch_runtime_ready()
    enhancement_modes = resolve_live_batch_enhancement_modes(args.enhancement_modes)
    target_source_names = resolve_target_source_names(
        explicit_source_names=args.source_names,
        source_manifest=args.source_manifest,
        pollution_audit=args.pollution_audit,
        manual_review_only=args.manual_review_only,
    )

    print(f"[batch] scanning source files {args.source_dir}", flush=True)
    source_items = select_source_candidates(
        args.source_dir,
        max(args.limit * 4, args.limit),
        source_names=target_source_names,
    )
    if not source_items:
        raise SystemExit("No source videos found.")
    print(f"[batch] candidate sources {len(source_items)}", flush=True)

    reports: list[JobRunReport] = []
    for item in source_items:
        write_batch_progress(
            report_dir=args.report_dir,
            source_dir=args.source_dir,
            channel_profile=args.channel_profile,
            language=args.language,
            output_dir=args.output_dir,
            enhancement_modes=enhancement_modes,
            reports=reports,
            current_item=item,
            status="running",
        )
        job_id = asyncio.run(
            prepare_job_for_source(
                Path(item["path"]),
                channel_profile=args.channel_profile,
                language=args.language,
                output_dir=args.output_dir,
                enhancement_modes=enhancement_modes,
                force_rerun_existing=args.force_rerun_existing,
            )
        )
        if not job_id:
            continue
        print(f"[batch] running {item.get('source_name')} job={job_id}", flush=True)
        write_batch_progress(
            report_dir=args.report_dir,
            source_dir=args.source_dir,
            channel_profile=args.channel_profile,
            language=args.language,
            output_dir=args.output_dir,
            enhancement_modes=enhancement_modes,
            reports=reports,
            current_item=item,
            current_job_id=job_id,
            status="running",
        )
        reports.append(run_job(job_id, item, stop_after=args.stop_after))
        write_batch_progress(
            report_dir=args.report_dir,
            source_dir=args.source_dir,
            channel_profile=args.channel_profile,
            language=args.language,
            output_dir=args.output_dir,
            enhancement_modes=enhancement_modes,
            reports=reports,
            status="running",
        )
        if len(reports) >= args.limit:
            break

    if not reports:
        raise SystemExit("No jobs were created from the pending inventory.")

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(args.source_dir),
        "channel_profile": args.channel_profile,
        "language": args.language,
        "output_dir": args.output_dir,
        "enhancement_modes": enhancement_modes,
        "job_count": len(reports),
        "success_count": sum(1 for report in reports if report.status == "done"),
        "failed_count": sum(1 for report in reports if report.status != "done"),
        "jobs": [asdict(report) for report in reports],
    }
    golden_source_names = resolve_golden_source_names(
        source_names=target_source_names,
        golden_manifest=args.golden_manifest,
    )
    previous_summaries = load_previous_batch_summaries(args.previous_batch_reports)
    live_readiness = asdict(
        build_live_readiness_summary(
            summary,
            golden_source_names=golden_source_names,
            previous_summaries=previous_summaries,
        )
    )
    summary["live_readiness"] = live_readiness
    (args.report_dir / "batch_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.report_dir / "batch_report.md").write_text(
        render_markdown(summary),
        encoding="utf-8",
    )
    progress_path = args.report_dir / "batch_progress.json"
    if progress_path.exists():
        progress_path.unlink()
    print(json.dumps(build_console_summary(summary), ensure_ascii=False, indent=2), flush=True)
    print(f"\nJSON report: {args.report_dir / 'batch_report.json'}", flush=True)
    print(f"Markdown report: {args.report_dir / 'batch_report.md'}", flush=True)


def ensure_batch_runtime_ready() -> None:
    readiness = asyncio.run(build_readiness_payload())
    failed_checks = {
        name: check
        for name, check in dict(readiness.get("checks") or {}).items()
        if str(check.get("status") or "").strip().lower() == "failed"
    }
    if not failed_checks:
        return
    detail = "; ".join(
        f"{name}={str(check.get('detail') or '').strip() or 'failed'}"
        for name, check in failed_checks.items()
    )
    raise SystemExit(f"Runtime readiness failed: {detail}")


def write_batch_progress(
    *,
    report_dir: Path,
    source_dir: Path,
    channel_profile: str,
    language: str,
    output_dir: str | None,
    enhancement_modes: list[str],
    reports: list[JobRunReport],
    current_item: dict[str, Any] | None = None,
    current_job_id: str | None = None,
    status: str = "running",
) -> None:
    progress_payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "source_dir": str(source_dir),
        "channel_profile": channel_profile,
        "language": language,
        "output_dir": output_dir,
        "enhancement_modes": list(enhancement_modes),
        "completed_job_count": len(reports),
        "jobs": [asdict(report) for report in reports],
        "current": {
            "job_id": current_job_id or "",
            "source_name": str((current_item or {}).get("source_name") or ""),
            "source_path": str((current_item or {}).get("path") or ""),
        },
    }
    (report_dir / "batch_progress.json").write_text(
        json.dumps(progress_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def select_source_candidates(source_dir: Path, limit: int, *, source_names: list[str] | None = None) -> list[dict[str, Any]]:
    candidates = [
        path
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS and "已剪" not in path.stem
    ]
    if source_names:
        by_name = {path.name: path for path in candidates}
        ordered = [by_name[name] for name in source_names if name in by_name]
        return [{"path": str(path), "source_name": path.name} for path in ordered[:limit]]
    candidates.sort(key=lambda path: (path.stat().st_size, path.name.lower()))
    return [{"path": str(path), "source_name": path.name} for path in candidates[:limit]]


async def prepare_job_for_source(
    source_path: Path,
    *,
    channel_profile: str,
    language: str,
    output_dir: str | None,
    enhancement_modes: list[str],
    force_rerun_existing: bool,
) -> str | None:
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Job).where(Job.source_name == source_path.name).order_by(Job.created_at.desc())
        )
        jobs = result.scalars().all()
        for job in jobs:
            render_result = await session.execute(
                select(RenderOutput)
                .where(RenderOutput.job_id == job.id, RenderOutput.status == "done")
                .order_by(RenderOutput.created_at.desc())
            )
            render = render_result.scalars().first()
            if render and render.output_path and Path(render.output_path).exists() and not force_rerun_existing:
                return None

        reusable = jobs[0] if jobs else None
        if reusable is not None:
            await reset_job_for_batch_rerun(
                session,
                reusable,
                enhancement_modes=enhancement_modes,
                output_dir=output_dir,
            )
            await session.commit()
            return str(reusable.id)

    created = await create_jobs_for_inventory_paths(
        [str(source_path)],
        workflow_template=channel_profile,
        language=language,
        output_dir=output_dir,
    )
    job_id = str(created[0].get("job_id") or "").strip() or None
    if not job_id:
        return None
    if enhancement_modes:
        await override_job_batch_settings(job_id, enhancement_modes=enhancement_modes, output_dir=output_dir)
    return job_id


async def reset_job_for_batch_rerun(
    session,
    job: Job,
    *,
    enhancement_modes: list[str],
    output_dir: str | None,
) -> None:
    await session.execute(delete(Artifact).where(Artifact.job_id == job.id))
    await session.execute(delete(RenderOutput).where(RenderOutput.job_id == job.id))
    await session.execute(delete(Timeline).where(Timeline.job_id == job.id))
    await session.execute(delete(SubtitleCorrection).where(SubtitleCorrection.job_id == job.id))
    await session.execute(delete(SubtitleItem).where(SubtitleItem.job_id == job.id))
    await session.execute(delete(TranscriptSegment).where(TranscriptSegment.job_id == job.id))

    step_result = await session.execute(select(JobStep).where(JobStep.job_id == job.id))
    existing_steps = {step.step_name: step for step in step_result.scalars().all()}
    now = datetime.now(timezone.utc)
    for step_name in PIPELINE_STEPS:
        step = existing_steps.get(step_name)
        preserved_metadata = {}
        if step is not None and step.step_name == "content_profile" and isinstance(step.metadata_, dict):
            source_context = step.metadata_.get("source_context")
            if isinstance(source_context, dict) and source_context:
                preserved_metadata["source_context"] = dict(source_context)
        if step is None:
            session.add(
                JobStep(
                    job_id=job.id,
                    step_name=step_name,
                    status="pending",
                    attempt=0,
                    metadata_=preserved_metadata or None,
                )
            )
            continue
        step.status = "pending"
        step.attempt = 0
        step.error_message = None
        step.started_at = None
        step.finished_at = None
        step.metadata_ = preserved_metadata or None

    if enhancement_modes:
        job.enhancement_modes = list(enhancement_modes)
    if output_dir:
        job.output_dir = output_dir
    job.status = "pending"
    job.error_message = None
    job.updated_at = now


async def override_job_batch_settings(job_id: str, *, enhancement_modes: list[str], output_dir: str | None) -> None:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        if job is None:
            return
        if enhancement_modes:
            job.enhancement_modes = list(enhancement_modes)
        if output_dir:
            job.output_dir = output_dir
        job.updated_at = datetime.now(timezone.utc)
        await session.commit()


def run_job(job_id: str, item: dict[str, Any], *, stop_after: str | None = None) -> JobRunReport:
    step_runs: list[StepRun] = []
    status = "done"
    current_steps = load_step_statuses(job_id)

    for step_name in PIPELINE_STEPS:
        if current_steps.get(step_name) == "done":
            if stop_after == step_name:
                status = "partial"
                break
            continue
        if step_name == "summary_review":
            started = time.perf_counter()
            auto_confirm_content_profile(job_id)
            current_steps["summary_review"] = "done"
            step_runs.append(
                StepRun(
                    step=step_name,
                    status="done",
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    detail=read_step_detail(job_id, step_name),
                )
            )
            if stop_after == step_name:
                status = "partial"
                break
            continue
        if step_name == "final_review":
            started = time.perf_counter()
            auto_approve_final_review(job_id)
            current_steps["final_review"] = "done"
            step_runs.append(
                StepRun(
                    step=step_name,
                    status="done",
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    detail=read_step_detail(job_id, step_name),
                )
            )
            if stop_after == step_name:
                status = "partial"
                break
            continue
        mark_step(job_id, step_name, "running")
        started = time.perf_counter()
        try:
            run_step_sync(step_name, job_id)
            mark_step(job_id, step_name, "done")
            current_steps[step_name] = "done"
            detail = read_step_detail(job_id, step_name)
            step_runs.append(
                StepRun(
                    step=step_name,
                    status="done",
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    detail=detail,
                )
            )
            if stop_after == step_name:
                status = "partial"
                break
        except Exception as exc:
            status = "failed"
            error_text = f"{type(exc).__name__}: {exc}"
            mark_step(job_id, step_name, "failed", error=error_text)
            step_runs.append(
                StepRun(
                    step=step_name,
                    status="failed",
                    elapsed_seconds=round(time.perf_counter() - started, 3),
                    error=error_text,
                )
            )
            break

    if status in {"done", "failed"}:
        finalize_job(job_id, status)
    collected = asyncio.run(collect_job_report(job_id, item, step_runs, status))
    return collected


def load_step_statuses(job_id: str) -> dict[str, str]:
    async def _load() -> dict[str, str]:
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(select(JobStep).where(JobStep.job_id == uuid.UUID(job_id)))
            return {step.step_name: step.status for step in result.scalars().all()}

    return asyncio.run(_load())


def mark_step(job_id: str, step_name: str, status: str, *, error: str | None = None) -> None:
    async def _update() -> None:
        factory = get_session_factory()
        async with factory() as session:
            job_uuid = uuid.UUID(job_id)
            job = await session.get(Job, job_uuid)
            result = await session.execute(
                select(JobStep).where(JobStep.job_id == job_uuid, JobStep.step_name == step_name)
            )
            step = result.scalar_one()
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


def read_step_detail(job_id: str, step_name: str) -> str:
    async def _read() -> str:
        factory = get_session_factory()
        async with factory() as session:
            job_uuid = uuid.UUID(job_id)
            result = await session.execute(
                select(JobStep).where(JobStep.job_id == job_uuid, JobStep.step_name == step_name)
            )
            step = result.scalar_one_or_none()
            metadata = (step.metadata_ or {}) if step else {}
            return str(metadata.get("detail") or "")

    return asyncio.run(_read())


def auto_confirm_content_profile(job_id: str) -> None:
    async def _confirm() -> None:
        factory = get_session_factory()
        async with factory() as session:
            job_uuid = uuid.UUID(job_id)
            job = await session.get(Job, job_uuid)
            draft_result = await session.execute(
                select(Artifact)
                .where(Artifact.job_id == job.id, Artifact.artifact_type == "content_profile_draft")
                .order_by(Artifact.created_at.desc())
            )
            draft_artifact = draft_result.scalars().first()
            if draft_artifact is None:
                raise RuntimeError("content_profile_draft not found")

            final_profile = dict(draft_artifact.data_json or {})
            final_profile["review_mode"] = str(final_profile.get("review_mode") or "manual_confirmed")
            final_profile["user_feedback"] = {}

            review_result = await session.execute(
                select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "summary_review")
            )
            review_step = review_result.scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if review_step is not None:
                review_step.status = "done"
                review_step.started_at = review_step.started_at or now
                review_step.finished_at = now
                review_step.error_message = None

            session.add(
                Artifact(
                    job_id=job.id,
                    step_id=review_step.id if review_step else None,
                    artifact_type="content_profile_final",
                    data_json=final_profile,
                )
            )
            job.status = "processing"
            job.updated_at = now
            await session.commit()

    asyncio.run(_confirm())


def auto_approve_final_review(job_id: str) -> None:
    async def _approve() -> None:
        factory = get_session_factory()
        async with factory() as session:
            job_uuid = uuid.UUID(job_id)
            job = await session.get(Job, job_uuid)
            review_result = await session.execute(
                select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "final_review")
            )
            review_step = review_result.scalar_one_or_none()
            if review_step is None:
                raise RuntimeError("final_review step not found")
            now = datetime.now(timezone.utc)
            mark_final_review_approved(
                review_step=review_step,
                job=job,
                now=now,
                approved_via="batch_test",
                metadata_updates={"batch_auto_approved": True},
            )
            await session.commit()

    asyncio.run(_approve())


def finalize_job(job_id: str, status: str) -> None:
    async def _finalize() -> None:
        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(Job, uuid.UUID(job_id))
            now = datetime.now(timezone.utc)
            job.status = status
            job.updated_at = now
            if status != "done":
                job.error_message = job.error_message or "Batch full-chain run failed"
            await session.commit()

    asyncio.run(_finalize())


async def collect_job_report(
    job_id: str,
    item: dict[str, Any],
    step_runs: list[StepRun],
    status: str,
) -> JobRunReport:
    factory = get_session_factory()
    async with factory() as session:
        job_uuid = uuid.UUID(job_id)
        job = await session.get(Job, job_uuid)

        subtitle_result = await session.execute(
            select(SubtitleItem).where(SubtitleItem.job_id == job_uuid, SubtitleItem.version == 1)
        )
        subtitles = subtitle_result.scalars().all()

        transcript_result = await session.execute(
            select(TranscriptSegment).where(TranscriptSegment.job_id == job_uuid, TranscriptSegment.version == 1)
        )
        transcript_segments = transcript_result.scalars().all()

        correction_result = await session.execute(
            select(SubtitleCorrection).where(SubtitleCorrection.job_id == job_uuid)
        )
        corrections = correction_result.scalars().all()

        step_result = await session.execute(select(JobStep).where(JobStep.job_id == job_uuid))
        steps = step_result.scalars().all()

        render_result = await session.execute(
            select(RenderOutput)
            .where(RenderOutput.job_id == job_uuid, RenderOutput.status == "done")
            .order_by(RenderOutput.created_at.desc())
        )
        render_output = render_result.scalars().first()

        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job.id).order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
        artifacts = artifact_result.scalars().all()
        render_artifact = next((artifact for artifact in artifacts if artifact.artifact_type == "render_outputs"), None)
        packaging_artifact = next((artifact for artifact in artifacts if artifact.artifact_type == "platform_packaging_md"), None)
        subtitle_quality_artifact = next(
            (artifact for artifact in artifacts if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT),
            None,
        )
        subtitle_projection_artifact = next(
            (artifact for artifact in artifacts if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER),
            None,
        )
        subtitle_term_resolution_artifact = next(
            (artifact for artifact in artifacts if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH),
            None,
        )
        subtitle_consistency_artifact = next(
            (artifact for artifact in artifacts if artifact.artifact_type == ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT),
            None,
        )
        profile_artifact = next(
            (
                artifact
                for artifact in artifacts
                if artifact.artifact_type in {"content_profile_final", "content_profile", "content_profile_draft", "downstream_context"}
            ),
            None,
        )

        timeline_result = await session.execute(
            select(Timeline).where(Timeline.job_id == job_uuid, Timeline.timeline_type == "editorial")
        )
        editorial_timeline = timeline_result.scalar_one_or_none()

    keep_ratio = compute_keep_ratio(editorial_timeline.data_json if editorial_timeline else None)
    output_path = str(render_output.output_path) if render_output and render_output.output_path else None
    output_duration = probe_duration(Path(output_path)) if output_path else 0.0
    render_payload = render_artifact.data_json if render_artifact and isinstance(render_artifact.data_json, dict) else {}
    cover_path = str(render_payload.get("cover") or "").strip() or None
    platform_doc = str(packaging_artifact.storage_path or "").strip() if packaging_artifact else None
    if not platform_doc and output_path:
        platform_doc = str(Path(output_path).with_name(f"{Path(output_path).stem}_publish.md"))

    cover_variants = [
        str(item).strip()
        for item in (render_payload.get("cover_variants") or [])
        if str(item).strip()
    ]
    cover_manifest = get_cover_manifest_path(Path(cover_path)) if cover_path else None
    if cover_manifest and not cover_manifest.exists():
        legacy_manifest = get_legacy_cover_manifest_path(Path(cover_path))
        cover_manifest = legacy_manifest if legacy_manifest.exists() else cover_manifest
    cover_variant_count = len(cover_variants)
    if cover_variant_count == 0 and cover_manifest and cover_manifest.exists():
        try:
            cover_variant_count = len(json.loads(cover_manifest.read_text(encoding="utf-8")))
        except Exception:
            cover_variant_count = 0

    quality_assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitles,
        corrections=corrections,
        completion_candidate=(status == "done"),
    )
    subtitle_projection_data = (
        subtitle_projection_artifact.data_json
        if subtitle_projection_artifact and isinstance(subtitle_projection_artifact.data_json, dict)
        else {}
    )
    effective_subtitle_count = len(list(subtitle_projection_data.get("entries") or [])) or len(subtitles)
    live_stage_validations = build_live_stage_validations(
        step_statuses={step.step_name: step.status for step in steps},
        transcript_segment_count=len(transcript_segments),
        subtitle_count=effective_subtitle_count,
        keep_ratio=keep_ratio,
        profile=profile_artifact.data_json if profile_artifact else None,
        platform_doc=platform_doc,
        subtitle_quality_report=subtitle_quality_artifact.data_json if subtitle_quality_artifact else None,
        subtitle_term_resolution_patch=(
            subtitle_term_resolution_artifact.data_json if subtitle_term_resolution_artifact else None
        ),
        subtitle_consistency_report=subtitle_consistency_artifact.data_json if subtitle_consistency_artifact else None,
        quality_assessment=quality_assessment,
    )

    notes = build_job_notes(
        status=status,
        output_duration=output_duration,
        transcript_segment_count=len(transcript_segments),
        subtitle_count=effective_subtitle_count,
        correction_count=len(corrections),
        keep_ratio=keep_ratio,
        cover_path=cover_path,
        cover_variant_count=cover_variant_count,
        platform_doc=platform_doc,
        quality_assessment=quality_assessment,
        live_stage_validations=live_stage_validations,
    )

    return JobRunReport(
        job_id=str(job_id),
        source_path=str(item.get("path") or ""),
        source_name=str(item.get("source_name") or job.source_name),
        status=status,
        output_path=output_path,
        cover_path=cover_path if cover_path and Path(cover_path).exists() else None,
        output_duration_sec=round(output_duration, 3),
        transcript_segment_count=len(transcript_segments),
        subtitle_count=effective_subtitle_count,
        correction_count=len(corrections),
        keep_ratio=round(keep_ratio, 3),
        cover_variant_count=cover_variant_count,
        platform_doc=platform_doc if platform_doc and Path(platform_doc).exists() else None,
        quality_score=quality_assessment.get("score"),
        quality_grade=quality_assessment.get("grade"),
        quality_issue_codes=list(quality_assessment.get("issue_codes") or []),
        live_stage_validations=live_stage_validations,
        content_profile=profile_artifact.data_json if profile_artifact else None,
        steps=step_runs,
        notes=notes,
    )


def compute_keep_ratio(editorial_timeline: dict[str, Any] | None) -> float:
    segments = list((editorial_timeline or {}).get("segments") or [])
    if not segments:
        return 0.0
    kept = 0.0
    total = 0.0
    for segment in segments:
        start = float(segment.get("start", 0.0) or 0.0)
        end = float(segment.get("end", 0.0) or 0.0)
        duration = max(0.0, end - start)
        total += duration
        if segment.get("type") == "keep":
            kept += duration
    return (kept / total) if total > 0 else 0.0


def build_live_stage_validations(
    *,
    step_statuses: dict[str, str],
    transcript_segment_count: int,
    subtitle_count: int,
    keep_ratio: float,
    profile: dict[str, Any] | None,
    platform_doc: str | None,
    subtitle_quality_report: dict[str, Any] | None,
    subtitle_term_resolution_patch: dict[str, Any] | None,
    subtitle_consistency_report: dict[str, Any] | None,
    quality_assessment: dict[str, Any] | None,
) -> list[LiveStageValidation]:
    issue_codes = {str(code) for code in (quality_assessment or {}).get("issue_codes") or []}
    subtitle_quality_report = subtitle_quality_report if isinstance(subtitle_quality_report, dict) else {}
    subtitle_term_resolution_patch = (
        subtitle_term_resolution_patch if isinstance(subtitle_term_resolution_patch, dict) else {}
    )
    subtitle_consistency_report = subtitle_consistency_report if isinstance(subtitle_consistency_report, dict) else {}
    profile_issue_codes = [
        code
        for code in (
            "missing_content_profile",
            "low_profile_confidence",
            "profile_unconfirmed",
            "generic_subject_type",
            "generic_video_theme",
            "generic_summary",
            "thin_summary",
            "detail_blind",
            "detail_coverage_low",
            "comparison_blind",
        )
        if code in issue_codes
    ]
    subtitle_quality_blocking = bool(subtitle_quality_report.get("blocking"))
    subtitle_quality_warnings = list(subtitle_quality_report.get("warning_reasons") or [])
    pending_term_count = int((subtitle_term_resolution_patch.get("metrics") or {}).get("pending_count") or 0)
    subtitle_consistency_blocking = bool(subtitle_consistency_report.get("blocking"))
    subtitle_consistency_warnings = list(subtitle_consistency_report.get("warning_reasons") or [])
    has_term_resolution_step = "subtitle_term_resolution" in step_statuses
    has_consistency_step = "subtitle_consistency_review" in step_statuses
    has_summary_review_step = "summary_review" in step_statuses
    has_final_review_step = "final_review" in step_statuses
    validations = [
        LiveStageValidation(
            stage="transcribe",
            status="pass" if step_statuses.get("transcribe") == "done" and transcript_segment_count > 0 else "fail",
            summary=f"ASR 产出 {transcript_segment_count} 条 transcript segment",
            issue_codes=["missing_transcript"] if transcript_segment_count <= 0 else [],
        ),
        LiveStageValidation(
            stage="subtitle_postprocess",
            status=(
                "fail"
                if step_statuses.get("subtitle_postprocess") != "done" or subtitle_count <= 0 or subtitle_quality_blocking
                else "warn"
                if subtitle_quality_warnings
                else "pass"
            ),
            summary=(
                f"字幕后处理产出 {subtitle_count} 条字幕，基础质检阻断 {len(subtitle_quality_report.get('blocking_reasons') or [])} 项"
                if subtitle_quality_blocking
                else f"字幕后处理产出 {subtitle_count} 条字幕"
            ),
            issue_codes=(
                list(subtitle_quality_report.get("blocking_reasons") or [])
                if subtitle_quality_blocking
                else ["missing_subtitles"]
                if subtitle_count <= 0
                else list(subtitle_quality_warnings)
            ),
        ),
        LiveStageValidation(
            stage="subtitle_term_resolution",
            status=(
                "fail"
                if pending_term_count > 0
                or (has_term_resolution_step and step_statuses.get("subtitle_term_resolution") != "done")
                else "pass"
            ),
            summary=(
                f"术语候选 {int((subtitle_term_resolution_patch.get('metrics') or {}).get('patch_count') or 0)} 条，待确认 {pending_term_count} 条"
                if pending_term_count > 0 or subtitle_term_resolution_patch
                else "术语解析未启用或无待确认项"
            ),
            issue_codes=["subtitle_terms_pending"] if pending_term_count > 0 else [],
        ),
        LiveStageValidation(
            stage="subtitle_consistency_review",
            status=(
                "fail"
                if subtitle_consistency_blocking
                or (has_consistency_step and step_statuses.get("subtitle_consistency_review") != "done")
                else "warn"
                if subtitle_consistency_warnings
                else "pass"
            ),
            summary=(
                "字幕一致性存在阻断项"
                if subtitle_consistency_blocking
                else "字幕一致性存在提醒项"
                if subtitle_consistency_warnings
                else "字幕一致性审校通过"
                if has_consistency_step
                else "字幕一致性审校未启用"
            ),
            issue_codes=(
                list(subtitle_consistency_report.get("blocking_reasons") or [])
                if subtitle_consistency_blocking
                else list(subtitle_consistency_warnings)
            ),
        ),
        LiveStageValidation(
            stage="content_profile",
            status="pass" if step_statuses.get("content_profile") == "done" and profile and not profile_issue_codes else "fail",
            summary="内容画像已通过 live 质量门禁" if profile and not profile_issue_codes else "内容画像存在质量问题",
            issue_codes=profile_issue_codes,
        ),
        LiveStageValidation(
            stage="summary_review",
            status="pass" if not has_summary_review_step or step_statuses.get("summary_review") == "done" else "fail",
            summary=(
                "内容画像已确认冻结"
                if step_statuses.get("summary_review") == "done"
                else "内容画像无需人工确认"
                if not has_summary_review_step
                else "内容画像仍待确认"
            ),
            issue_codes=[] if not has_summary_review_step or step_statuses.get("summary_review") == "done" else ["summary_review_pending"],
        ),
        LiveStageValidation(
            stage="edit_plan",
            status="pass" if step_statuses.get("edit_plan") == "done" and keep_ratio > 0 else "fail",
            summary=f"剪辑保留比 {keep_ratio:.0%}" if keep_ratio > 0 else "剪辑保留段为空或未生成",
            issue_codes=["empty_edit_plan"] if keep_ratio <= 0 else [],
        ),
        LiveStageValidation(
            stage="render",
            status="pass" if step_statuses.get("render") == "done" and "subtitle_sync_issue" not in issue_codes else "fail",
            summary="导出成片字幕同步正常" if "subtitle_sync_issue" not in issue_codes else "导出层存在字幕同步/结构问题",
            issue_codes=["subtitle_sync_issue"] if "subtitle_sync_issue" in issue_codes else [],
        ),
        LiveStageValidation(
            stage="final_review",
            status="pass" if not has_final_review_step or step_statuses.get("final_review") == "done" else "fail",
            summary=(
                "成片审核已通过"
                if step_statuses.get("final_review") == "done"
                else "成片无需人工审核"
                if not has_final_review_step
                else "成片审核未通过"
            ),
            issue_codes=[] if not has_final_review_step or step_statuses.get("final_review") == "done" else ["final_review_pending"],
        ),
        LiveStageValidation(
            stage="platform_package",
            status="pass" if step_statuses.get("platform_package") == "done" and platform_doc and Path(platform_doc).exists() else "fail",
            summary="平台包装文案已导出" if platform_doc and Path(platform_doc).exists() else "平台包装文案未导出",
            issue_codes=["missing_platform_package"] if not (platform_doc and Path(platform_doc).exists()) else [],
        ),
    ]
    return validations


def build_job_notes(
    *,
    status: str,
    output_duration: float,
    transcript_segment_count: int,
    subtitle_count: int,
    correction_count: int,
    keep_ratio: float,
    cover_path: str | None,
    cover_variant_count: int,
    platform_doc: str | None,
    quality_assessment: dict[str, Any] | None,
    live_stage_validations: list[LiveStageValidation],
) -> list[str]:
    notes: list[str] = []
    if status == "done":
        notes.append("全链路跑通")
    elif status == "partial":
        notes.append("执行到指定阶段后停止")
    else:
        notes.append("任务未完整跑通")
    if output_duration > 0:
        notes.append(f"成片时长 {output_duration:.1f}s")
    if transcript_segment_count > 0:
        notes.append(f"ASR片段 {transcript_segment_count} 条")
    if subtitle_count > 0:
        notes.append(f"字幕 {subtitle_count} 条")
    if correction_count > 0:
        notes.append(f"术语/字幕纠正 {correction_count} 处")
    if keep_ratio > 0:
        notes.append(f"保留比 {keep_ratio:.0%}")
    if cover_path and Path(cover_path).exists():
        notes.append("封面已导出")
    if cover_variant_count >= 5:
        notes.append(f"封面候选 {cover_variant_count} 张")
    if platform_doc and Path(platform_doc).exists():
        notes.append("平台文案已导出")
    if isinstance(quality_assessment, dict):
        grade = str(quality_assessment.get("grade") or "").strip()
        score = quality_assessment.get("score")
        if grade and score is not None:
            notes.append(f"质量分 {grade} {float(score):.1f}")
    failing_stages = [item.stage for item in live_stage_validations if item.status != "pass"]
    if failing_stages:
        notes.append("live校验失败: " + "、".join(failing_stages[:4]))
    elif live_stage_validations:
        notes.append("live校验通过")
    return notes


def probe_duration(path: Path) -> float:
    import subprocess

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        data = json.loads(result.stdout or "{}")
        return float(data.get("format", {}).get("duration", 0.0) or 0.0)
    except Exception:
        return 0.0


def build_console_summary(summary: dict[str, Any]) -> dict[str, Any]:
    jobs = summary["jobs"]
    payload = {
        "job_count": summary["job_count"],
        "success_count": summary["success_count"],
        "failed_count": summary["failed_count"],
        "jobs": [
            {
                "source_name": job["source_name"],
                "status": job["status"],
                "output_duration_sec": job["output_duration_sec"],
                "quality_score": job.get("quality_score"),
                "quality_grade": job.get("quality_grade"),
                "subtitle_count": job["subtitle_count"],
                "keep_ratio": job["keep_ratio"],
                "notes": job["notes"][:4],
            }
            for job in jobs
        ],
    }
    if isinstance(summary.get("live_readiness"), dict):
        payload["live_readiness"] = {
            "status": summary["live_readiness"].get("status"),
            "gate_passed": summary["live_readiness"].get("gate_passed"),
            "summary": summary["live_readiness"].get("summary"),
            "stable_run_count": summary["live_readiness"].get("stable_run_count"),
        }
    return payload


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Full-Chain Batch Report",
        "",
        f"- created_at: {summary['created_at']}",
        f"- source_dir: {summary['source_dir']}",
        f"- channel_profile: {summary['channel_profile']}",
        f"- language: {summary['language']}",
        f"- output_dir: {summary.get('output_dir') or ''}",
        f"- enhancement_modes: {', '.join(summary.get('enhancement_modes') or [])}",
        f"- success_count: {summary['success_count']}/{summary['job_count']}",
        "",
    ]
    live_readiness = summary.get("live_readiness") if isinstance(summary.get("live_readiness"), dict) else {}
    if live_readiness:
        lines.extend(
            [
                "## Live Readiness",
                "",
                f"- status: {live_readiness.get('status')}",
                f"- gate_passed: {str(bool(live_readiness.get('gate_passed'))).lower()}",
                f"- summary: {live_readiness.get('summary') or ''}",
                f"- stable_run_count: {live_readiness.get('stable_run_count')}/{live_readiness.get('required_stable_runs')}",
                f"- golden_job_count: {live_readiness.get('golden_job_count')}",
                f"- evaluated_job_count: {live_readiness.get('evaluated_job_count')}",
            ]
        )
        checks = live_readiness.get("checks") if isinstance(live_readiness.get("checks"), dict) else {}
        if checks:
            lines.append("- checks:")
            for key, value in checks.items():
                if isinstance(value, dict):
                    lines.append(
                        f"  - {key}: pass={str(bool(value.get('passed'))).lower()} "
                        f"actual={value.get('actual')} required={value.get('required')}"
                    )
        if live_readiness.get("failure_reasons"):
            lines.append("- failure_reasons: " + " / ".join(live_readiness["failure_reasons"]))
        if live_readiness.get("warning_reasons"):
            lines.append("- warning_reasons: " + " / ".join(live_readiness["warning_reasons"]))
        lines.append("")
    for job in summary["jobs"]:
        lines.append(f"## {job['source_name']}")
        lines.append(f"- status: {job['status']}")
        lines.append(f"- output_path: {job['output_path'] or ''}")
        lines.append(f"- cover_path: {job.get('cover_path') or ''}")
        lines.append(f"- output_duration_sec: {job['output_duration_sec']}")
        lines.append(f"- transcript_segment_count: {job.get('transcript_segment_count', 0)}")
        lines.append(f"- subtitle_count: {job['subtitle_count']}")
        lines.append(f"- correction_count: {job['correction_count']}")
        lines.append(f"- keep_ratio: {job['keep_ratio']}")
        lines.append(f"- cover_variant_count: {job['cover_variant_count']}")
        if job.get("quality_score") is not None:
            lines.append(f"- quality: {job.get('quality_grade') or ''} {job['quality_score']}")
        if job.get("quality_issue_codes"):
            lines.append("- quality_issue_codes: " + ", ".join(job["quality_issue_codes"]))
        if job.get("live_stage_validations"):
            lines.append(
                "- live_stage_validations: "
                + " / ".join(
                    f"{item['stage']}={item['status']}"
                    for item in job["live_stage_validations"]
                )
            )
            for item in job["live_stage_validations"]:
                detail = f"  - {item['stage']}: {item['status']} | {item['summary']}"
                issue_codes = list(item.get("issue_codes") or [])
                if issue_codes:
                    detail += " | issues=" + ", ".join(issue_codes)
                lines.append(detail)
        if job.get("content_profile"):
            profile = job["content_profile"]
            lines.append(
                "- content_profile: "
                + " | ".join(
                    filter(
                        None,
                        [
                            str(profile.get("subject_brand") or "").strip(),
                            str(profile.get("subject_model") or "").strip(),
                            str(profile.get("subject_type") or "").strip(),
                            str(profile.get("video_theme") or "").strip(),
                        ],
                    )
                )
            )
        if job.get("steps"):
            lines.append("- steps:")
            for item in job["steps"]:
                step_line = f"  - {item['step']}: {item['status']} ({item['elapsed_seconds']}s)"
                if item.get("detail"):
                    step_line += f" | {item['detail']}"
                if item.get("error"):
                    step_line += f" | error={item['error']}"
                lines.append(step_line)
        if job.get("notes"):
            lines.append("- notes: " + " / ".join(job["notes"]))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def resolve_golden_source_names(*, source_names: list[str] | None, golden_manifest: Path | None) -> list[str]:
    manifest_names = load_golden_manifest(golden_manifest) if golden_manifest else []
    explicit_names = [str(item).strip() for item in list(source_names or []) if str(item).strip()]
    ordered: list[str] = []
    for name in [*explicit_names, *manifest_names]:
        if name and name not in ordered:
            ordered.append(name)
    return ordered


def resolve_target_source_names(
    *,
    explicit_source_names: list[str] | None,
    source_manifest: Path | None,
    pollution_audit: Path | None,
    manual_review_only: bool,
) -> list[str]:
    ordered: list[str] = []

    def _append(names: list[str]) -> None:
        for name in names:
            normalized = str(name or "").strip()
            if normalized and normalized not in ordered:
                ordered.append(normalized)

    _append([str(item).strip() for item in list(explicit_source_names or []) if str(item).strip()])
    _append(load_golden_manifest(source_manifest) if source_manifest else [])
    _append(load_source_names_from_pollution_audit(pollution_audit, manual_review_only=manual_review_only))
    return ordered


def load_source_names_from_pollution_audit(
    path: Path | None,
    *,
    manual_review_only: bool,
) -> list[str]:
    if path is None or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return []

    names: list[str] = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        if manual_review_only and not bool(item.get("manual_review_required")):
            continue
        source_name = str(item.get("source_name") or "").strip()
        if source_name and source_name not in names:
            names.append(source_name)
    return names


def load_golden_manifest(path: Path | None) -> list[str]:
    if path is None:
        return []
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("golden manifest JSON must be an array of source names")
        return [str(item).strip() for item in data if str(item).strip()]
    return [line.strip() for line in raw.splitlines() if line.strip()]


def load_previous_batch_summaries(paths: list[str] | list[Path]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for raw_path in list(paths or []):
        path = Path(raw_path)
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            summaries.append(payload)
    return summaries


if __name__ == "__main__":
    main()
