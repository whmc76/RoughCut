from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select

from roughcut.config import get_settings
from roughcut.creative.modes import normalize_enhancement_modes
from roughcut.db.models import Artifact, Job, JobStep, RenderOutput, SubtitleCorrection, SubtitleItem, Timeline
from roughcut.media.output import get_cover_manifest_path, get_legacy_cover_manifest_path
from roughcut.db.session import get_session_factory
from roughcut.pipeline.steps import run_step_sync
from roughcut.review.content_profile import apply_content_profile_feedback
from roughcut.review.content_profile_memory import record_content_profile_feedback_memory
from roughcut.watcher.folder_watcher import create_jobs_for_inventory_paths

PIPELINE_STEPS = [
    "probe",
    "extract_audio",
    "transcribe",
    "subtitle_postprocess",
    "content_profile",
    "glossary_review",
    "ai_director",
    "avatar_commentary",
    "edit_plan",
    "render",
    "platform_package",
]

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}


@dataclass
class StepRun:
    step: str
    status: str
    elapsed_seconds: float
    detail: str = ""
    error: str = ""


@dataclass
class JobRunReport:
    job_id: str
    source_path: str
    source_name: str
    status: str
    output_path: str | None
    output_duration_sec: float
    subtitle_count: int
    correction_count: int
    keep_ratio: float
    cover_variant_count: int
    platform_doc: str | None
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.report_dir.mkdir(parents=True, exist_ok=True)

    print(f"[batch] scanning source files {args.source_dir}", flush=True)
    source_items = select_source_candidates(args.source_dir, max(args.limit * 4, args.limit))
    if not source_items:
        raise SystemExit("No source videos found.")
    print(f"[batch] candidate sources {len(source_items)}", flush=True)

    reports: list[JobRunReport] = []
    for item in source_items:
        job_id = asyncio.run(
            prepare_job_for_source(
                Path(item["path"]),
                channel_profile=args.channel_profile,
                language=args.language,
            )
        )
        if not job_id:
            continue
        print(f"[batch] running {item.get('source_name')} job={job_id}", flush=True)
        reports.append(run_job(job_id, item))
        if len(reports) >= args.limit:
            break

    if not reports:
        raise SystemExit("No jobs were created from the pending inventory.")

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(args.source_dir),
        "channel_profile": args.channel_profile,
        "language": args.language,
        "job_count": len(reports),
        "success_count": sum(1 for report in reports if report.status == "done"),
        "failed_count": sum(1 for report in reports if report.status != "done"),
        "jobs": [asdict(report) for report in reports],
    }
    (args.report_dir / "batch_report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.report_dir / "batch_report.md").write_text(
        render_markdown(summary),
        encoding="utf-8",
    )
    print(json.dumps(build_console_summary(summary), ensure_ascii=False, indent=2), flush=True)
    print(f"\nJSON report: {args.report_dir / 'batch_report.json'}", flush=True)
    print(f"Markdown report: {args.report_dir / 'batch_report.md'}", flush=True)


def select_source_candidates(source_dir: Path, limit: int) -> list[dict[str, Any]]:
    candidates = [
        path
        for path in source_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS and "已剪" not in path.stem
    ]
    candidates.sort(key=lambda path: (path.stat().st_size, path.name.lower()))
    return [{"path": str(path), "source_name": path.name} for path in candidates[:limit]]


async def prepare_job_for_source(
    source_path: Path,
    *,
    channel_profile: str,
    language: str,
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
            if render and render.output_path and Path(render.output_path).exists():
                return None

        reusable = jobs[0] if jobs else None
        if reusable is not None:
            default_modes = list(get_settings().default_job_enhancement_modes or [])
            step_result = await session.execute(select(JobStep).where(JobStep.job_id == reusable.id))
            existing_steps = {step.step_name: step for step in step_result.scalars().all()}
            for step_name in PIPELINE_STEPS:
                step = existing_steps.get(step_name)
                if step is None:
                    session.add(
                        JobStep(
                            job_id=reusable.id,
                            step_name=step_name,
                            status="pending",
                            attempt=0,
                        )
                    )
                    continue
                step.status = "pending"
                step.error_message = None
                step.started_at = None
                step.finished_at = None
                step.metadata_ = None
            reusable.enhancement_modes = normalize_enhancement_modes(
                list(reusable.enhancement_modes or []) + default_modes
            )
            reusable.status = "pending"
            reusable.error_message = None
            reusable.updated_at = datetime.now(timezone.utc)
            await session.commit()
            return str(reusable.id)

    created = await create_jobs_for_inventory_paths(
        [str(source_path)],
        channel_profile=channel_profile,
        language=language,
    )
    return str(created[0].get("job_id") or "").strip() or None


def run_job(job_id: str, item: dict[str, Any]) -> JobRunReport:
    step_runs: list[StepRun] = []
    status = "done"
    current_steps = load_step_statuses(job_id)

    for step_name in PIPELINE_STEPS:
        if current_steps.get(step_name) == "done":
            if step_name == "content_profile" and current_steps.get("summary_review") != "done":
                auto_confirm_content_profile(job_id)
                current_steps["summary_review"] = "done"
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
            if step_name == "content_profile":
                auto_confirm_content_profile(job_id)
                current_steps["summary_review"] = "done"
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

            final_profile = await apply_content_profile_feedback(
                draft_profile=draft_artifact.data_json or {},
                source_name=job.source_name,
                channel_profile=job.channel_profile,
                user_feedback={},
            )
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
            await record_content_profile_feedback_memory(
                session,
                job=job,
                draft_profile=draft_artifact.data_json or {},
                final_profile=final_profile,
                user_feedback={},
            )
            job.status = "processing"
            job.updated_at = now
            await session.commit()

    asyncio.run(_confirm())


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

        correction_result = await session.execute(
            select(SubtitleCorrection).where(SubtitleCorrection.job_id == job_uuid)
        )
        corrections = correction_result.scalars().all()

        render_result = await session.execute(
            select(RenderOutput)
            .where(RenderOutput.job_id == job_uuid, RenderOutput.status == "done")
            .order_by(RenderOutput.created_at.desc())
        )
        render_output = render_result.scalars().first()

        profile_result = await session.execute(
            select(Artifact)
            .where(
                Artifact.job_id == job.id,
                Artifact.artifact_type.in_(["content_profile_final", "content_profile", "content_profile_draft"]),
            )
            .order_by(Artifact.created_at.desc())
        )
        profile_artifact = profile_result.scalars().first()

        timeline_result = await session.execute(
            select(Timeline).where(Timeline.job_id == job_uuid, Timeline.timeline_type == "editorial")
        )
        editorial_timeline = timeline_result.scalar_one_or_none()

    keep_ratio = compute_keep_ratio(editorial_timeline.data_json if editorial_timeline else None)
    output_path = str(render_output.output_path) if render_output and render_output.output_path else None
    output_duration = probe_duration(Path(output_path)) if output_path else 0.0
    platform_doc = str(Path(output_path).with_name(f"{Path(output_path).stem}_publish.md")) if output_path else None
    cover_manifest = get_cover_manifest_path(Path(output_path)) if output_path else None
    if cover_manifest and not cover_manifest.exists():
        legacy_manifest = get_legacy_cover_manifest_path(Path(output_path))
        cover_manifest = legacy_manifest if legacy_manifest.exists() else cover_manifest
    cover_variant_count = 0
    if cover_manifest and cover_manifest.exists():
        try:
            cover_variant_count = len(json.loads(cover_manifest.read_text(encoding="utf-8")))
        except Exception:
            cover_variant_count = 0

    notes = build_job_notes(
        status=status,
        output_duration=output_duration,
        subtitle_count=len(subtitles),
        correction_count=len(corrections),
        keep_ratio=keep_ratio,
        cover_variant_count=cover_variant_count,
        platform_doc=platform_doc,
    )

    return JobRunReport(
        job_id=str(job_id),
        source_path=str(item.get("path") or ""),
        source_name=str(item.get("source_name") or job.source_name),
        status=status,
        output_path=output_path,
        output_duration_sec=round(output_duration, 3),
        subtitle_count=len(subtitles),
        correction_count=len(corrections),
        keep_ratio=round(keep_ratio, 3),
        cover_variant_count=cover_variant_count,
        platform_doc=platform_doc if platform_doc and Path(platform_doc).exists() else None,
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


def build_job_notes(
    *,
    status: str,
    output_duration: float,
    subtitle_count: int,
    correction_count: int,
    keep_ratio: float,
    cover_variant_count: int,
    platform_doc: str | None,
) -> list[str]:
    notes: list[str] = []
    if status == "done":
        notes.append("全链路跑通")
    else:
        notes.append("任务未完整跑通")
    if output_duration > 0:
        notes.append(f"成片时长 {output_duration:.1f}s")
    if subtitle_count > 0:
        notes.append(f"字幕 {subtitle_count} 条")
    if correction_count > 0:
        notes.append(f"术语/字幕纠正 {correction_count} 处")
    if keep_ratio > 0:
        notes.append(f"保留比 {keep_ratio:.0%}")
    if cover_variant_count >= 5:
        notes.append(f"封面候选 {cover_variant_count} 张")
    if platform_doc and Path(platform_doc).exists():
        notes.append("平台文案已导出")
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
    return {
        "job_count": summary["job_count"],
        "success_count": summary["success_count"],
        "failed_count": summary["failed_count"],
        "jobs": [
            {
                "source_name": job["source_name"],
                "status": job["status"],
                "output_duration_sec": job["output_duration_sec"],
                "subtitle_count": job["subtitle_count"],
                "keep_ratio": job["keep_ratio"],
                "notes": job["notes"][:4],
            }
            for job in jobs
        ],
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Full-Chain Batch Report",
        "",
        f"- created_at: {summary['created_at']}",
        f"- source_dir: {summary['source_dir']}",
        f"- channel_profile: {summary['channel_profile']}",
        f"- language: {summary['language']}",
        f"- success_count: {summary['success_count']}/{summary['job_count']}",
        "",
    ]
    for job in summary["jobs"]:
        lines.append(f"## {job['source_name']}")
        lines.append(f"- status: {job['status']}")
        lines.append(f"- output_path: {job['output_path'] or ''}")
        lines.append(f"- output_duration_sec: {job['output_duration_sec']}")
        lines.append(f"- subtitle_count: {job['subtitle_count']}")
        lines.append(f"- correction_count: {job['correction_count']}")
        lines.append(f"- keep_ratio: {job['keep_ratio']}")
        lines.append(f"- cover_variant_count: {job['cover_variant_count']}")
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
        if job.get("notes"):
            lines.append("- notes: " + " / ".join(job["notes"]))
        lines.append("")
    return "\n".join(lines).strip() + "\n"


if __name__ == "__main__":
    main()
