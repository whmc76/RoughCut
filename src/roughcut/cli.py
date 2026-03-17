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
@click.option("--channel-profile", default=None, help="Channel profile name")
@click.option("--language", default="zh-CN", help="Language code")
def watcher(path: str, channel_profile: str | None, language: str):
    """Watch a directory for new video files."""
    from roughcut.watcher.folder_watcher import watch_directory
    click.echo(f"Watching: {path} (lang={language}, profile={channel_profile})")
    asyncio.run(watch_directory(path, channel_profile=channel_profile, language=language))


@cli.command()
@click.option("--queue", required=True, type=click.Choice(["media_queue", "llm_queue", "all"]))
@click.option("--concurrency", default=2, type=int)
@click.option(
    "--pool",
    default="solo" if os.name == "nt" else "prefork",
    type=click.Choice(["solo", "prefork"]),
    show_default=True,
)
def worker(queue: str, concurrency: int, pool: str):
    """Start a Celery worker for the specified queue."""
    from roughcut.pipeline.celery_app import celery_app

    queues = ["media_queue", "llm_queue"] if queue == "all" else [queue]
    click.echo(f"Starting worker for queues: {queues} (pool={pool}, concurrency={concurrency})")
    celery_app.worker_main(
        argv=[
            "worker",
            f"--queues={','.join(queues)}",
            f"--concurrency={concurrency}",
            f"--pool={pool}",
            "--loglevel=info",
        ]
    )


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


async def _quality_audit_async(*, limit: int, statuses: list[str], persist: bool) -> list[QualityAuditRow]:
    from roughcut.db.models import Artifact, Job, JobStep, SubtitleCorrection, SubtitleItem
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


async def _quality_improve_async(
    *,
    limit: int,
    max_score: float,
    statuses: list[str],
    max_processing: int,
    dry_run: bool,
) -> dict[str, Any]:
    from roughcut.db.models import Job, JobStep
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
