from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import click
import uvicorn
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from roughcut.config import get_settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@click.group()
def cli():
    """RoughCut - Automated video editing & subtitle review."""


@dataclass
class DoctorCheck:
    name: str
    status: str
    detail: str
    critical: bool = False


@dataclass
class QualityAuditRow:
    job_id: str
    source_name: str
    status: str
    score: float
    grade: str
    issue_codes: list[str]
    recommended_rerun_steps: list[str]


@dataclass
class ContentProfileApprovalStatsRow:
    updated_at: str | None
    auto_review_enabled: bool
    review_threshold: float
    required_accuracy: float
    minimum_sample_size: int
    gate_passed: bool
    detail: str
    measured_accuracy: float | None
    sample_size: int
    manual_review_total: int
    approved_without_changes: int
    corrected_after_review: int
    eligible_manual_review_total: int
    eligible_approved_without_changes: int
    eligible_corrected_after_review: int
    eligible_approval_accuracy: float | None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_repo_path(value: str, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return repo_root / path


def _build_doctor_checks() -> list[DoctorCheck]:
    repo_root = _repo_root()
    settings = get_settings()
    output_dir = _resolve_repo_path(settings.output_dir, repo_root)
    debug_dir = _resolve_repo_path(settings.render_debug_dir, repo_root)
    env_file = repo_root / ".env"
    env_example = repo_root / ".env.example"

    checks: list[DoctorCheck] = []
    checks.append(
        DoctorCheck(
            name="python",
            status="ok" if sys.version_info >= (3, 11) else "fail",
            detail=f"Python {sys.version.split()[0]}",
            critical=True,
        )
    )
    checks.append(
        DoctorCheck(
            name="ffmpeg",
            status="ok" if shutil.which("ffmpeg") else "fail",
            detail=shutil.which("ffmpeg") or "ffmpeg not found in PATH",
            critical=True,
        )
    )
    checks.append(
        DoctorCheck(
            name="ffprobe",
            status="ok" if shutil.which("ffprobe") else "fail",
            detail=shutil.which("ffprobe") or "ffprobe not found in PATH",
            critical=True,
        )
    )
    checks.append(
        DoctorCheck(
            name="uv",
            status="ok" if shutil.which("uv") else "warn",
            detail=shutil.which("uv") or "uv not found; fallback to pip/manual install",
        )
    )
    checks.append(
        DoctorCheck(
            name="docker",
            status="ok" if shutil.which("docker") else "warn",
            detail=shutil.which("docker") or "docker not found; container deployment unavailable",
        )
    )
    checks.append(
        DoctorCheck(
            name="env",
            status="ok" if env_file.exists() else ("warn" if env_example.exists() else "fail"),
            detail=str(env_file if env_file.exists() else env_example if env_example.exists() else repo_root / ".env"),
            critical=not env_example.exists(),
        )
    )
    checks.append(
        DoctorCheck(
            name="output_dir",
            status="ok" if output_dir.exists() else "warn",
            detail=str(output_dir),
        )
    )
    checks.append(
        DoctorCheck(
            name="render_debug_dir",
            status="ok" if debug_dir.exists() else "warn",
            detail=str(debug_dir),
        )
    )
    checks.append(
        DoctorCheck(
            name="watch_dir",
            status="ok" if (repo_root / "watch").exists() else "warn",
            detail=str(repo_root / "watch"),
        )
    )
    return checks


@cli.command()
@click.option("--force-env", is_flag=True, default=False, help="Overwrite .env from .env.example if it exists")
@click.option("--skip-env", is_flag=True, default=False, help="Do not create .env from .env.example")
def init(force_env: bool, skip_env: bool):
    """Initialize local directories and starter config for uv-based development."""
    repo_root = _repo_root()
    settings = get_settings()
    output_dir = _resolve_repo_path(settings.output_dir, repo_root)
    debug_dir = _resolve_repo_path(settings.render_debug_dir, repo_root)
    watch_dir = repo_root / "watch"
    env_file = repo_root / ".env"
    env_example = repo_root / ".env.example"

    for path in (output_dir, debug_dir, watch_dir):
        path.mkdir(parents=True, exist_ok=True)
        click.echo(f"[ok] ensured {path}")

    if not skip_env and env_example.exists():
        if force_env or not env_file.exists():
            shutil.copy2(env_example, env_file)
            click.echo(f"[ok] wrote {env_file}")
        else:
            click.echo(f"[skip] existing {env_file}")
    elif not skip_env:
        click.echo(f"[warn] missing template: {env_example}")

    click.echo("Init complete. Next steps:")
    click.echo("  1. uv sync --extra dev")
    click.echo("  2. uv run roughcut doctor")
    click.echo("  3. uv run roughcut migrate")


@cli.command()
@click.option("--json-output", "json_output", is_flag=True, default=False, help="Print machine-readable JSON")
def doctor(json_output: bool):
    """Validate local prerequisites for uv or Docker-based deployment."""
    checks = _build_doctor_checks()
    if json_output:
        click.echo(json.dumps([asdict(item) for item in checks], ensure_ascii=False, indent=2))
    else:
        for item in checks:
            click.echo(f"[{item.status.upper()}] {item.name}: {item.detail}")
    if any(item.critical and item.status == "fail" for item in checks):
        raise SystemExit(1)


@cli.command()
@click.option("--host", default="0.0.0.0", help="Bind host")
@click.option("--port", default=8000, type=int, help="Bind port")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload (dev)")
@click.option("--workers", default=1, type=int, help="Number of uvicorn workers")
def api(host: str, port: int, reload: bool, workers: int):
    """Start the FastAPI server."""
    uvicorn.run(
        "roughcut.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,
        log_level="info",
    )


@cli.command()
@click.option("--poll-interval", default=5.0, type=float, help="Poll interval in seconds")
def orchestrator(poll_interval: float):
    """Start the pipeline orchestrator process."""
    from roughcut.pipeline.orchestrator import run_orchestrator
    click.echo(f"Starting orchestrator (poll every {poll_interval}s)")
    asyncio.run(run_orchestrator(poll_interval=poll_interval))


@cli.command()
@click.argument("path")
@click.option("--workflow-template", default=None, help="Default workflow template")
@click.option("--language", default="zh-CN", help="Language code")
def watcher(path: str, workflow_template: str | None, language: str):
    """Watch a directory for new video files."""
    from roughcut.watcher.folder_watcher import watch_directory
    click.echo(f"Watching: {path} (lang={language}, template={workflow_template})")
    asyncio.run(watch_directory(path, workflow_template=workflow_template, language=language))


@cli.command()
@click.option("--queue", required=True, type=click.Choice(["media_queue", "llm_queue", "all"]))
@click.option("--concurrency", default=2, type=int)
@click.option(
    "--pool",
    default="solo" if os.name == "nt" else "prefork",
    type=click.Choice(["solo", "prefork"]),
    show_default=True,
)
@click.option("--hostname", default=None, help="Explicit Celery node name")
@click.option("--without-gossip", is_flag=True, default=False, help="Disable worker gossip")
@click.option("--without-mingle", is_flag=True, default=False, help="Disable startup mingle")
def worker(
    queue: str,
    concurrency: int,
    pool: str,
    hostname: str | None,
    without_gossip: bool,
    without_mingle: bool,
):
    """Start a Celery worker for the specified queue."""
    from roughcut.pipeline.celery_app import celery_app

    queues = ["media_queue", "llm_queue"] if queue == "all" else [queue]
    node_label = hostname or "auto"
    click.echo(
        f"Starting worker for queues: {queues} "
        f"(pool={pool}, concurrency={concurrency}, hostname={node_label})"
    )
    argv = [
        "worker",
        f"--queues={','.join(queues)}",
        f"--concurrency={concurrency}",
        f"--pool={pool}",
        "--loglevel=info",
    ]
    if hostname:
        argv.append(f"--hostname={hostname}")
    if without_gossip:
        argv.append("--without-gossip")
    if without_mingle:
        argv.append("--without-mingle")
    celery_app.worker_main(argv=argv)


@cli.command("telegram-agent")
def telegram_agent():
    """Start the standalone Telegram agent process."""
    from roughcut.review.telegram_bot import get_telegram_review_bot_service

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    click.echo("Starting Telegram agent")
    asyncio.run(get_telegram_review_bot_service().run_forever())


@cli.command("recover-job-index")
@click.option("--endpoint-url", required=True, help="S3/MinIO endpoint URL")
@click.option("--access-key-id", default="minioadmin", show_default=True, help="S3 access key")
@click.option("--secret-access-key", default="minioadmin", show_default=True, help="S3 secret key")
@click.option("--bucket", default="jobs", show_default=True, help="Bucket to scan")
@click.option("--limit", default=None, type=int, help="Max jobs to recover")
@click.option("--dry-run", is_flag=True, default=False, help="Inspect candidates without writing the database")
@click.option("--json-output", "json_output", is_flag=True, default=False, help="Print machine-readable JSON")
def recover_job_index(
    endpoint_url: str,
    access_key_id: str,
    secret_access_key: str,
    bucket: str,
    limit: int | None,
    dry_run: bool,
    json_output: bool,
):
    """Recover missing job rows from an S3/MinIO bucket listing."""
    from roughcut.recovery.job_index_restore import apply_recovered_jobs, collect_recovered_jobs

    candidates = collect_recovered_jobs(
        endpoint_url=endpoint_url,
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        bucket=bucket,
        limit=limit,
    )
    if dry_run:
        payload = {
            "candidates": len(candidates),
            "jobs": [
                {
                    "job_id": item.job_id,
                    "source_name": item.source_name,
                    "status": item.status,
                    "enhancement_modes": item.enhancement_modes,
                    "created_at": item.created_at.isoformat(),
                    "updated_at": item.updated_at.isoformat(),
                }
                for item in candidates
            ],
        }
    else:
        payload = asyncio.run(apply_recovered_jobs(candidates))

    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if dry_run:
        click.echo(f"candidates={payload['candidates']}")
        return
    click.echo(
        " ".join(
            [
                f"candidates={payload['candidates']}",
                f"inserted={payload['inserted']}",
                f"skipped_existing={payload['skipped_existing']}",
            ]
        )
    )


@cli.command()
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--language", default="zh-CN", show_default=True, help="Language code")
@click.option("--workflow-template", "--channel-profile", default=None, help="Default workflow template")
@click.option("--sample-seconds", default=90, type=click.IntRange(1), show_default=True, help="Max seconds to sample from the source")
def clip_test(source: Path, language: str, workflow_template: str | None, sample_seconds: int):
    """Run a full manual pipeline test for one source video."""
    from roughcut.testing.manual_clip import run_manual_clip_test

    click.echo(f"Running clip test for: {source}")
    try:
        report = asyncio.run(
            run_manual_clip_test(
                source,
                language=language,
                workflow_template=workflow_template,
                sample_seconds=sample_seconds,
            )
        )
    except TypeError as exc:
        if "workflow_template" not in str(exc):
            raise
        report = asyncio.run(
            run_manual_clip_test(
                source,
                language=language,
                channel_profile=workflow_template,
                sample_seconds=sample_seconds,
            )
        )
    click.echo(json.dumps(report, ensure_ascii=False, indent=2))


@cli.command()
def migrate():
    """Run Alembic database migrations."""
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=False,
    )
    raise SystemExit(result.returncode)


@cli.group()
def quality():
    """Audit and improve job quality."""


@quality.command("audit")
@click.option("--limit", default=20, type=int, show_default=True, help="Max jobs to print")
@click.option("--status", "statuses", multiple=True, help="Filter job status, repeatable")
@click.option("--persist", is_flag=True, default=False, help="Persist quality_assessment artifacts")
@click.option("--json-output", "json_output", is_flag=True, default=False, help="Print machine-readable JSON")
def quality_audit(limit: int, statuses: tuple[str, ...], persist: bool, json_output: bool):
    """Score jobs and sort from lowest quality upward."""
    rows = asyncio.run(_quality_audit_async(limit=limit, statuses=list(statuses), persist=persist))
    if json_output:
        click.echo(json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2))
        return
    for row in rows:
        click.echo(f"{row.score:>5.1f} {row.grade} {row.status:<12} {row.job_id} {row.source_name}")
        click.echo(f"  issues={', '.join(row.issue_codes) if row.issue_codes else '-'}")
        click.echo(f"  rerun={', '.join(row.recommended_rerun_steps) if row.recommended_rerun_steps else '-'}")


@quality.command("improve")
@click.option("--limit", default=3, type=int, show_default=True, help="Max jobs to process")
@click.option("--max-score", default=74.9, type=float, show_default=True, help="Only process jobs below this score")
@click.option("--status", "statuses", multiple=True, default=("done",), help="Filter job status, repeatable")
@click.option(
    "--max-processing",
    default=6,
    type=int,
    show_default=True,
    help="Do not trigger new improvements when processing jobs already reach this cap",
)
@click.option("--dry-run", is_flag=True, default=False, help="Preview which jobs would be processed")
@click.option("--json-output", "json_output", is_flag=True, default=False, help="Print machine-readable JSON")
def quality_improve(
    limit: int,
    max_score: float,
    statuses: tuple[str, ...],
    max_processing: int,
    dry_run: bool,
    json_output: bool,
):
    """Trigger auto-improvement from the lowest-scoring eligible jobs."""
    result = asyncio.run(
        _quality_improve_async(
            limit=limit,
            max_score=max_score,
            statuses=list(statuses),
            max_processing=max_processing,
            dry_run=dry_run,
        )
    )
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    for item in result["jobs"]:
        click.echo(
            f"{item['action']:<8} {item['score']:>5.1f} {item['grade']} {item['status']:<12} {item['job_id']} {item['source_name']}"
        )
        click.echo(f"  issues={', '.join(item['issue_codes']) if item['issue_codes'] else '-'}")
        click.echo(f"  rerun={', '.join(item['recommended_rerun_steps']) if item['recommended_rerun_steps'] else '-'}")
    click.echo(
        " ".join(
            [
                f"processed={result['processed_count']}",
                f"dry_run={str(dry_run).lower()}",
                f"eligible={result['eligible_count']}",
                f"total_scanned={result['total_scanned']}",
                f"processing_now={result['processing_count']}",
                f"available_slots={result['available_slots']}",
            ]
        )
    )


@quality.command("content-profile-review-stats")
@click.option("--json-output", "json_output", is_flag=True, default=False, help="Print machine-readable JSON")
def quality_content_profile_review_stats(json_output: bool):
    """Show whether content-profile auto-review is allowed to be re-enabled."""
    row = _content_profile_review_stats()
    payload = asdict(row)
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    measured = f"{row.measured_accuracy:.1%}" if row.measured_accuracy is not None else "n/a"
    eligible = f"{row.eligible_approval_accuracy:.1%}" if row.eligible_approval_accuracy is not None else "n/a"
    click.echo(f"auto_review_enabled={str(row.auto_review_enabled).lower()} gate_passed={str(row.gate_passed).lower()}")
    click.echo(
        f"quality_threshold={row.review_threshold:.0%} required_accuracy={row.required_accuracy:.0%} "
        f"minimum_sample_size={row.minimum_sample_size}"
    )
    click.echo(
        f"measured_accuracy={measured} eligible_sample_size={row.sample_size} "
        f"manual_review_total={row.manual_review_total}"
    )
    click.echo(
        f"approved_without_changes={row.approved_without_changes} corrected_after_review={row.corrected_after_review}"
    )
    click.echo(
        f"eligible_approved_without_changes={row.eligible_approved_without_changes} "
        f"eligible_corrected_after_review={row.eligible_corrected_after_review} "
        f"eligible_accuracy={eligible}"
    )
    click.echo(f"detail={row.detail}")
    if row.updated_at:
        click.echo(f"updated_at={row.updated_at}")


@quality.command("backfill-content-profile-policy")
@click.option("--json-output", "json_output", is_flag=True, default=False, help="Print machine-readable JSON")
def quality_backfill_content_profile_policy(json_output: bool):
    """Rewrite stored content-profile artifacts with the current review policy fields."""
    result = asyncio.run(_backfill_content_profile_policy_async())
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    click.echo(
        " ".join(
            [
                f"updated_artifacts={result['updated_artifacts']}",
                f"scanned_artifacts={result['scanned_artifacts']}",
                f"job_count={result['job_count']}",
            ]
        )
    )


async def _quality_audit_async(*, limit: int, statuses: list[str], persist: bool) -> list[QualityAuditRow]:
    from roughcut.db.models import Artifact, Job, SubtitleCorrection, SubtitleItem
    from roughcut.db.session import get_session_factory
    from roughcut.pipeline.orchestrator import _latest_quality_assessment
    from roughcut.pipeline.quality import QUALITY_ARTIFACT_TYPE, assess_job_quality

    normalized_statuses = {item.strip() for item in statuses if item.strip()}
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(Job).options(selectinload(Job.steps), selectinload(Job.artifacts)).order_by(Job.updated_at.desc(), Job.created_at.desc())
        jobs = (await session.execute(stmt)).scalars().all()
        rows: list[QualityAuditRow] = []
        for job in jobs:
            if normalized_statuses and job.status not in normalized_statuses:
                continue
            subtitle_items = (
                await session.execute(select(SubtitleItem).where(SubtitleItem.job_id == job.id).order_by(SubtitleItem.item_index.asc()))
            ).scalars().all()
            corrections = (
                await session.execute(select(SubtitleCorrection).where(SubtitleCorrection.job_id == job.id))
            ).scalars().all()
            assessment = assess_job_quality(
                job=job,
                steps=list(job.steps or []),
                artifacts=list(job.artifacts or []),
                subtitle_items=subtitle_items,
                corrections=corrections,
                completion_candidate=(job.status == "done"),
            )
            if persist:
                previous = _latest_quality_assessment(list(job.artifacts or []))
                previous_payload = previous.data_json if previous and isinstance(previous.data_json, dict) else {}
                payload = {
                    **assessment,
                    "auto_rerun_count": int(previous_payload.get("auto_rerun_count") or 0),
                    "auto_rerun_history": list(previous_payload.get("auto_rerun_history") or []),
                    "auto_rerun_triggered": False,
                }
                session.add(Artifact(job_id=job.id, artifact_type=QUALITY_ARTIFACT_TYPE, data_json=payload))
            rows.append(
                QualityAuditRow(
                    job_id=str(job.id),
                    source_name=job.source_name,
                    status=job.status,
                    score=float(assessment["score"]),
                    grade=str(assessment["grade"]),
                    issue_codes=[str(item) for item in assessment.get("issue_codes") or []],
                    recommended_rerun_steps=[str(item) for item in assessment.get("recommended_rerun_steps") or []],
                )
            )
        if persist:
            await session.commit()
    rows.sort(key=lambda item: (item.score, item.status, item.source_name.lower()))
    return rows[: max(0, limit)]


def _content_profile_review_stats() -> ContentProfileApprovalStatsRow:
    from roughcut.review.content_profile_review_stats import summarize_content_profile_review_stats

    settings = get_settings()
    summary = summarize_content_profile_review_stats(
        min_accuracy=float(getattr(settings, "content_profile_auto_review_min_accuracy", 0.9) or 0.9),
        min_samples=int(getattr(settings, "content_profile_auto_review_min_samples", 20) or 20),
    )
    return ContentProfileApprovalStatsRow(
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


async def _backfill_content_profile_policy_async() -> dict[str, int]:
    from roughcut.db.models import Artifact
    from roughcut.db.session import get_session_factory
    from roughcut.review.content_profile_review_stats import apply_current_content_profile_review_policy

    scanned_artifacts = 0
    updated_artifacts = 0
    touched_job_ids: set[str] = set()
    factory = get_session_factory()
    async with factory() as session:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.artifact_type.in_(["content_profile_draft", "content_profile_final"]))
        )
        artifacts = artifact_result.scalars().all()
        settings = get_settings()
        for artifact in artifacts:
            if not isinstance(artifact.data_json, dict):
                continue
            scanned_artifacts += 1
            updated = apply_current_content_profile_review_policy(artifact.data_json, settings=settings)
            if updated != artifact.data_json:
                artifact.data_json = updated
                updated_artifacts += 1
                touched_job_ids.add(str(artifact.job_id))
        await session.commit()
    return {
        "scanned_artifacts": scanned_artifacts,
        "updated_artifacts": updated_artifacts,
        "job_count": len(touched_job_ids),
    }


async def _quality_improve_async(
    *,
    limit: int,
    max_score: float,
    statuses: list[str],
    max_processing: int,
    dry_run: bool,
) -> dict[str, Any]:
    from roughcut.db.models import Job
    from roughcut.db.session import get_session_factory
    from roughcut.pipeline.orchestrator import _assess_and_maybe_rerun_job

    audit_rows = await _quality_audit_async(limit=10000, statuses=statuses, persist=False)
    eligible_rows = [row for row in audit_rows if row.score <= max_score]
    result_rows: list[dict[str, Any]] = []
    factory = get_session_factory()
    async with factory() as session:
        processing_count = int(
            (
                await session.execute(
                    select(func.count()).select_from(Job).where(Job.status == "processing")
                )
            ).scalar_one()
        )
        available_slots = max(0, max_processing - processing_count)
        effective_limit = min(max(0, limit), available_slots)
        selected_rows = eligible_rows[:effective_limit] if dry_run else eligible_rows

        if dry_run or not selected_rows or effective_limit <= 0:
            for row in selected_rows:
                result_rows.append(
                    {
                        **asdict(row),
                        "action": "would_run",
                    }
                )
            return {
                "processed_count": 0,
                "eligible_count": len(eligible_rows),
                "total_scanned": len(audit_rows),
                "processing_count": processing_count,
                "available_slots": available_slots,
                "jobs": result_rows,
            }

        selected_ids = {uuid.UUID(row.job_id): row for row in eligible_rows}
        jobs = (
            await session.execute(
                select(Job)
                .options(selectinload(Job.steps), selectinload(Job.artifacts))
                .where(Job.id.in_(list(selected_ids)))
            )
        ).scalars().all()
        triggered_count = 0
        for job in jobs:
            row = selected_ids[job.id]
            rerun_started = await _assess_and_maybe_rerun_job(session, job, list(job.steps or []))
            if not rerun_started and triggered_count >= max(0, limit):
                continue
            action = "triggered" if rerun_started else "skipped"
            if rerun_started:
                triggered_count += 1
            result_rows.append(
                {
                    **asdict(row),
                    "action": action,
                }
            )
            if triggered_count >= effective_limit:
                break
        await session.commit()

    result_rows.sort(key=lambda item: (item["score"], item["source_name"].lower()))
    return {
        "processed_count": sum(1 for item in result_rows if item["action"] == "triggered"),
        "eligible_count": len(eligible_rows),
        "total_scanned": len(audit_rows),
        "processing_count": processing_count,
        "available_slots": available_slots,
        "jobs": result_rows,
    }


if __name__ == "__main__":
    cli()
