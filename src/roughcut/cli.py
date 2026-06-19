from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
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
from roughcut.pipeline.live_readiness import load_live_readiness_snapshot
from roughcut.storage.runtime_cleanup import cleanup_workspace_runtime_files, workspace_runtime_cleanup_targets


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


def _read_env_file_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, raw_value = stripped.split("=", 1)
        if name.strip() != key:
            continue
        value = raw_value.split("#", 1)[0].strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        return value
    return ""


def _configured_int(key: str, default: int) -> int:
    value = os.getenv(key, "").strip()
    if not value:
        repo_root = _repo_root()
        for env_path in (repo_root / "roughcut.ports.env", repo_root / ".env"):
            value = _read_env_file_value(env_path, key).strip()
            if value:
                break
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


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


@cli.command("cleanup-runtime")
@click.option("--dry-run", is_flag=True, default=False, help="List disposable workspace runtime directories without deleting them")
@click.option("--json-output", "json_output", is_flag=True, default=False, help="Print machine-readable JSON")
def cleanup_runtime(dry_run: bool, json_output: bool):
    """Remove disposable workspace runtime/debug scratch directories."""
    repo_root = _repo_root()
    targets = [path for path in workspace_runtime_cleanup_targets(repo_root)]
    existing_targets = [path for path in targets if path.exists()]
    removed_targets = existing_targets if dry_run else cleanup_workspace_runtime_files(repo_root)

    payload = {
        "repo_root": str(repo_root),
        "dry_run": dry_run,
        "targets": [str(path) for path in targets],
        "existing_targets": [str(path) for path in existing_targets],
        "removed_targets": [str(path) for path in removed_targets],
    }
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if dry_run:
        for path in existing_targets:
            click.echo(f"[would-remove] {path}")
        if not existing_targets:
            click.echo("[ok] no disposable workspace runtime directories found")
        return
    for path in removed_targets:
        click.echo(f"[removed] {path}")
    if not removed_targets:
        click.echo("[ok] no disposable workspace runtime directories found")


@cli.command()
@click.option("--host", default="0.0.0.0", help="Bind host")
@click.option("--port", default=None, type=int, help="Bind port. Defaults to ROUGHCUT_API_PORT in roughcut.ports.env.")
@click.option("--reload", is_flag=True, default=False, help="Enable auto-reload (dev)")
@click.option(
    "--workers",
    default=None,
    type=int,
    help="Number of uvicorn workers. Defaults to ROUGHCUT_API_WORKERS or 1.",
)
@click.option(
    "--timeout-graceful-shutdown",
    default=None,
    type=int,
    help="Seconds to wait for in-flight requests during shutdown/reload.",
)
@click.option(
    "--timeout-keep-alive",
    default=None,
    type=int,
    help="Seconds to keep idle HTTP connections open.",
)
@click.option(
    "--limit-concurrency",
    default=None,
    type=int,
    help="Maximum concurrent connections/tasks accepted by uvicorn.",
)
@click.option(
    "--backlog",
    default=None,
    type=int,
    help="Socket listen backlog.",
)
def api(
    host: str,
    port: int | None,
    reload: bool,
    workers: int | None,
    timeout_graceful_shutdown: int | None,
    timeout_keep_alive: int | None,
    limit_concurrency: int | None,
    backlog: int | None,
):
    """Start the FastAPI server."""
    bind_port = port if port is not None else _configured_int("ROUGHCUT_API_PORT", 38471)
    resolved_workers = workers if workers is not None else _configured_int("ROUGHCUT_API_WORKERS", 1)
    resolved_graceful_shutdown = (
        timeout_graceful_shutdown
        if timeout_graceful_shutdown is not None
        else _configured_int("ROUGHCUT_API_GRACEFUL_SHUTDOWN_SEC", 8)
    )
    resolved_keep_alive = (
        timeout_keep_alive
        if timeout_keep_alive is not None
        else _configured_int("ROUGHCUT_API_KEEP_ALIVE_SEC", 3)
    )
    resolved_backlog = backlog if backlog is not None else _configured_int("ROUGHCUT_API_BACKLOG", 4096)
    resolved_limit_concurrency = limit_concurrency
    if resolved_limit_concurrency is None:
        configured_limit = os.getenv("ROUGHCUT_API_LIMIT_CONCURRENCY", "").strip()
        if configured_limit:
            try:
                resolved_limit_concurrency = max(1, int(configured_limit))
            except ValueError:
                resolved_limit_concurrency = None
    uvicorn.run(
        "roughcut.main:app",
        host=host,
        port=bind_port,
        reload=reload,
        reload_dirs=[str(_repo_root() / "src")] if reload else None,
        workers=resolved_workers if not reload else 1,
        log_level="info",
        timeout_graceful_shutdown=max(1, resolved_graceful_shutdown),
        timeout_keep_alive=max(1, resolved_keep_alive),
        limit_concurrency=resolved_limit_concurrency,
        backlog=max(1, resolved_backlog),
    )


@cli.command()
@click.option("--poll-interval", default=5.0, type=float, help="Poll interval in seconds")
def orchestrator(poll_interval: float):
    """Start the pipeline orchestrator process."""
    from roughcut.pipeline.orchestrator import run_orchestrator
    click.echo(f"Starting orchestrator (poll every {poll_interval}s)")
    asyncio.run(run_orchestrator(poll_interval=poll_interval))


@cli.command("intelligent-copy-task-runner")
@click.option("--task-id", required=True)
@click.option("--folder-path", required=True)
@click.option("--copy-style", default=None)
@click.option("--platform", "platforms", multiple=True)
@click.option("--use-existing-cover/--no-use-existing-cover", default=False)
@click.option("--creator-profile-id", default=None)
@click.option("--creator-profile-name", default=None)
def intelligent_copy_task_runner(
    task_id: str,
    folder_path: str,
    copy_style: str | None,
    platforms: tuple[str, ...],
    use_existing_cover: bool,
    creator_profile_id: str | None,
    creator_profile_name: str | None,
):
    """Run one intelligent copy generation task in a dedicated process."""
    from roughcut.api.intelligent_copy import _run_generation_task_thread

    _run_generation_task_thread(
        task_id,
        folder_path,
        copy_style,
        list(platforms) or None,
        use_existing_cover,
        creator_profile_id,
        creator_profile_name,
    )


@cli.command()
@click.argument("path")
@click.option("--workflow-template", default=None, help="Default workflow template")
@click.option("--language", default="zh-CN", help="Language code")
def watcher(path: str, workflow_template: str | None, language: str):
    """Watch a directory for new video files."""
    from roughcut.watcher.folder_watcher import watch_directory
    click.echo(f"Watching: {path} (lang={language}, template={workflow_template})")
    asyncio.run(watch_directory(path, workflow_template=workflow_template, language=language))


@cli.group()
def remix():
    """Build script-driven source-footage remix outputs."""


def _run_script_footage_remix(
    *,
    source_root: Path | None,
    episodes: str,
    production_manifest: Path | None,
    task_status: str,
    output_dir: Path | None,
    api_base: str,
    qwen3_asr_base: str,
    creator_profile: str,
    creator_profile_path: Path | None,
    tts_provider: str,
    tts_timeout_sec: float,
    tts_poll_sec: float,
    force: bool,
    force_tts: bool,
    skip_tts_asr_align: bool,
    skip_source_asr_index: bool,
) -> None:
    """Run the script-footage remix builder."""
    repo_root = _repo_root()
    script_path = repo_root / "scripts" / "build_script_footage_remix_samples.py"
    if not script_path.exists():
        raise click.ClickException(f"Script-footage remix builder not found: {script_path}")
    manifest_payload: dict[str, Any] = {}
    if production_manifest is not None:
        manifest_path = production_manifest if production_manifest.is_absolute() else repo_root / production_manifest
        try:
            loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise click.ClickException(f"Cannot read production manifest: {manifest_path}: {exc}") from exc
        if isinstance(loaded_manifest, dict):
            manifest_payload = loaded_manifest
    if source_root is None:
        if production_manifest is None:
            raise click.ClickException("--source-root is required when --production-manifest is not set.")
        manifest_source_root = str(manifest_payload.get("source_root") or "").strip()
        if not manifest_source_root:
            raise click.ClickException("Production manifest missing source_root")
        source_root = Path(manifest_source_root)
    if not str(creator_profile or "").strip():
        creator_profile = str(manifest_payload.get("creator_profile") or "").strip()
    resolved_output_dir = output_dir or repo_root / "output" / "script-footage-remix-full-script-samples"
    command = [
        sys.executable,
        str(script_path),
        "--source-root",
        str(source_root),
        "--episodes",
        str(episodes),
        "--output-dir",
        str(resolved_output_dir),
        "--api-base",
        str(api_base),
        "--qwen3-asr-base",
        str(qwen3_asr_base),
        "--creator-profile",
        str(creator_profile),
        "--tts-provider",
        str(tts_provider),
        "--tts-timeout-sec",
        str(tts_timeout_sec),
        "--tts-poll-sec",
        str(tts_poll_sec),
    ]
    if production_manifest is not None:
        command.extend(["--production-manifest", str(production_manifest), "--task-status", str(task_status)])
    if creator_profile_path is not None:
        command.extend(["--creator-profile-path", str(creator_profile_path)])
    if skip_tts_asr_align:
        command.append("--skip-tts-asr-align")
    if skip_source_asr_index:
        command.append("--skip-source-asr-index")
    if force:
        command.append("--force")
    if force_tts:
        command.append("--force-tts")
    click.echo(" ".join(command))
    result = subprocess.run(command, cwd=repo_root, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _script_footage_options(command):
    command = click.option("--skip-source-asr-index", is_flag=True, default=False, help="Debug only: skip Source-ASR clip positioning index.")(command)
    command = click.option("--skip-tts-asr-align", is_flag=True, default=False, help="Debug only: skip TTS-ASR subtitle alignment.")(command)
    command = click.option("--force-tts", is_flag=True, default=False, help="Regenerate TTS audio even when cached narration exists.")(command)
    command = click.option("--force", is_flag=True, default=False, help="Regenerate existing intermediate and output artifacts.")(command)
    command = click.option("--tts-poll-sec", default=3.0, type=float, show_default=True, help="Polling interval for TTS API runs.")(command)
    command = click.option("--tts-timeout-sec", default=300.0, type=float, show_default=True, help="Maximum time to wait for one TTS API run.")(command)
    command = click.option("--tts-provider", type=click.Choice(["moss_tts_local", "cosyvoice3"]), default="moss_tts_local", show_default=True)(command)
    command = click.option("--creator-profile-path", type=click.Path(path_type=Path), default=None, help="Explicit creator profile JSON path.")(command)
    command = click.option("--creator-profile", default="", help="Creator profile slug bound to this remix task.")(command)
    command = click.option("--qwen3-asr-base", default="http://127.0.0.1:30230", show_default=True, help="Qwen3-ASR service base URL.")(command)
    command = click.option("--api-base", default="http://127.0.0.1:38471", show_default=True, help="RoughCut API base for MOSS/CosyVoice TTS.")(command)
    command = click.option("--output-dir", type=click.Path(path_type=Path), default=None, help="Output directory for renders and reports.")(command)
    command = click.option("--task-status", default="pending", show_default=True, type=click.Choice(["pending", "blocked_missing_script", "done", "all"]), help="Task status to read from --production-manifest.")(command)
    command = click.option("--production-manifest", type=click.Path(path_type=Path), default=None, help="Formal production task manifest; pending tasks define episode order.")(command)
    command = click.option("--episodes", default="1", show_default=True, help="Comma-separated episode numbers when no production manifest is supplied.")(command)
    command = click.option(
        "--source-root",
        type=click.Path(path_type=Path),
        default=None,
        help="Source root containing scripts and source footage. Required unless --production-manifest has source_root.",
    )(command)
    return command


@remix.command("script-footage")
@_script_footage_options
def remix_script_footage(
    source_root: Path | None,
    episodes: str,
    production_manifest: Path | None,
    task_status: str,
    output_dir: Path | None,
    api_base: str,
    qwen3_asr_base: str,
    creator_profile: str,
    creator_profile_path: Path | None,
    tts_provider: str,
    tts_timeout_sec: float,
    tts_poll_sec: float,
    force: bool,
    force_tts: bool,
    skip_tts_asr_align: bool,
    skip_source_asr_index: bool,
):
    """Run the generic script-footage remix chain."""
    _run_script_footage_remix(
        source_root=source_root,
        episodes=episodes,
        production_manifest=production_manifest,
        task_status=task_status,
        output_dir=output_dir,
        api_base=api_base,
        qwen3_asr_base=qwen3_asr_base,
        creator_profile=creator_profile,
        creator_profile_path=creator_profile_path,
        tts_provider=tts_provider,
        tts_timeout_sec=tts_timeout_sec,
        tts_poll_sec=tts_poll_sec,
        force=force,
        force_tts=force_tts,
        skip_tts_asr_align=skip_tts_asr_align,
        skip_source_asr_index=skip_source_asr_index,
    )
@cli.command()
@click.option(
    "--queue",
    required=True,
    type=click.Choice(["media_queue", "llm_queue", "agent_queue", "publication_queue", "all"]),
)
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
    queues = ["media_queue", "llm_queue", "agent_queue", "publication_queue"] if queue == "all" else [queue]
    os.environ["ROUGHCUT_WORKER_QUEUES"] = ",".join(queues)
    from roughcut.pipeline.celery_app import celery_app
    from roughcut.pipeline.celery_app import schedule_publication_worker_bootstrap

    schedule_publication_worker_bootstrap(celery_app)
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


@cli.command("review-notifications")
@click.option("--status", "statuses", multiple=True, help="Filter by status, can repeat")
@click.option("--job-id", default="", help="Filter by job id")
@click.option("--kind", default="", help="Filter by review kind")
@click.option("--limit", default=20, show_default=True, type=click.IntRange(1), help="Max rows to show")
@click.option("--requeue", "requeue_id", default="", help="Requeue one notification by id")
@click.option("--drop", "drop_id", default="", help="Delete one notification by id")
@click.option("--requeue-filtered", is_flag=True, default=False, help="Requeue all currently filtered notifications")
@click.option("--drop-filtered", is_flag=True, default=False, help="Delete all currently filtered notifications")
@click.option("--json-output", "json_output", is_flag=True, default=False, help="Print machine-readable JSON")
def review_notifications(
    statuses: tuple[str, ...],
    job_id: str,
    kind: str,
    limit: int,
    requeue_id: str,
    drop_id: str,
    requeue_filtered: bool,
    drop_filtered: bool,
    json_output: bool,
):
    """Inspect and manage the Telegram review notification retry queue."""
    from roughcut.telegram.review_notification_service import (
        build_review_notification_snapshot,
        drop_review_notification,
        drop_review_notifications,
        list_review_notifications,
        requeue_review_notification,
        requeue_review_notifications,
    )

    normalized_statuses = tuple(str(item).strip() for item in statuses if str(item).strip())
    normalized_job_id = str(job_id or "").strip()
    normalized_kind = str(kind or "").strip()
    requeue_id = str(requeue_id or "").strip()
    drop_id = str(drop_id or "").strip()

    if sum(1 for item in (bool(requeue_id), bool(drop_id), bool(requeue_filtered), bool(drop_filtered)) if item) > 1:
        raise click.ClickException("Use only one action at a time.")

    if requeue_id:
        try:
            record = requeue_review_notification(requeue_id)
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc
        if record is None:
            raise click.ClickException(f"Notification not found: {requeue_id}")
        payload = {
            "action": "requeued",
            "notification": asdict(record) if hasattr(record, "__dataclass_fields__") else dict(vars(record)),
        }
        if json_output:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        click.echo(
            " ".join(
                [
                    "requeued",
                    record.notification_id,
                    f"kind={record.kind}",
                    f"job={record.job_id}",
                    f"status={record.status}",
                ]
            )
        )
        return

    if drop_id:
        try:
            deleted = drop_review_notification(drop_id)
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc
        if not deleted:
            raise click.ClickException(f"Notification not found: {drop_id}")
        payload = {"action": "dropped", "notification_id": drop_id}
        if json_output:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        click.echo(f"dropped {drop_id}")
        return

    if requeue_filtered or drop_filtered:
        records = list_review_notifications(
            statuses=list(normalized_statuses) or None,
            job_id=normalized_job_id or None,
            kind=normalized_kind or None,
            limit=limit,
        )
        notification_ids = [item.notification_id for item in records]
        payload = {
            "action": "requeued" if requeue_filtered else "dropped",
            "count": 0,
            "notification_ids": [],
            "filters": {"statuses": list(normalized_statuses), "job_id": normalized_job_id, "kind": normalized_kind},
        }
        if notification_ids:
            try:
                if requeue_filtered:
                    updated = requeue_review_notifications(notification_ids)
                    payload["count"] = len(updated)
                    payload["notification_ids"] = [item.notification_id for item in updated]
                else:
                    deleted_ids = drop_review_notifications(notification_ids)
                    payload["count"] = len(deleted_ids)
                    payload["notification_ids"] = deleted_ids
            except RuntimeError as exc:
                raise click.ClickException(str(exc)) from exc
        if json_output:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        if not payload["count"]:
            click.echo("No notifications matched the current filters.")
            return
        click.echo(
            f"{payload['action']} {payload['count']} notifications"
            + (f" job={normalized_job_id}" if normalized_job_id else "")
            + (f" kind={normalized_kind}" if normalized_kind else "")
        )
        return

    snapshot = build_review_notification_snapshot(
        statuses=list(normalized_statuses) or None,
        job_id=normalized_job_id or None,
        kind=normalized_kind or None,
        limit=limit,
    )
    payload = {
        **snapshot,
        "filters": {"statuses": list(normalized_statuses), "job_id": normalized_job_id, "kind": normalized_kind},
    }
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    summary = payload["summary"]
    click.echo(
        " ".join(
            [
                f"total={summary['total']}",
                f"pending={summary['pending']}",
                f"due_now={summary['due_now']}",
                f"failed={summary['failed']}",
                f"delivered={summary['delivered']}",
            ]
        )
    )
    click.echo(f"store={payload['store_file']}")
    if payload.get("detail"):
        click.echo(f"detail={payload['detail']}")
    for item in payload["items"]:
        click.echo(
            " ".join(
                [
                    item["status"],
                    item["notification_id"],
                    f"kind={item['kind']}",
                    f"job={item['job_id']}",
                    f"attempts={item['attempt_count']}",
                    f"next={item['next_attempt_at']}",
                    f"error={item['last_error'] or '-'}",
                ]
            )
        )


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


@quality.command("live-readiness")
@click.option("--report-path", default="", help="Optional path to batch_report.json")
@click.option("--require-pass", is_flag=True, default=False, help="Exit with code 1 when the live-readiness gate is not passed")
@click.option("--json-output", "json_output", is_flag=True, default=False, help="Print machine-readable JSON")
def quality_live_readiness(report_path: str, require_pass: bool, json_output: bool):
    """Inspect the current live dry run gate verdict from the latest batch report."""
    normalized_report_path = str(report_path or "").strip()
    try:
        snapshot = load_live_readiness_snapshot(normalized_report_path or None)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        **snapshot,
        "report_path_input": normalized_report_path,
    }
    if json_output:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        if require_pass and not bool(payload.get("gate_passed")):
            raise SystemExit(1)
        return

    click.echo(
        " ".join(
            [
                f"status={payload.get('status') or 'unknown'}",
                f"gate_passed={str(bool(payload.get('gate_passed'))).lower()}",
                f"stable_runs={payload.get('stable_run_count', 0)}/{payload.get('required_stable_runs', 0)}",
            ]
        )
    )
    click.echo(f"summary={payload.get('summary') or ''}")
    if payload.get("report_file"):
        click.echo(f"report={payload['report_file']}")
    if payload.get("report_created_at"):
        click.echo(f"created_at={payload['report_created_at']}")
    if payload.get("golden_job_count") is not None or payload.get("evaluated_job_count") is not None:
        click.echo(
            " ".join(
                [
                    f"golden_jobs={payload.get('golden_job_count', 0)}",
                    f"evaluated_jobs={payload.get('evaluated_job_count', 0)}",
                ]
            )
        )
    if payload.get("failure_reasons"):
        click.echo("failures=" + " / ".join(str(item) for item in payload["failure_reasons"]))
    if payload.get("warning_reasons"):
        click.echo("warnings=" + " / ".join(str(item) for item in payload["warning_reasons"]))
    if payload.get("detail"):
        click.echo(f"detail={payload['detail']}")
    if require_pass and not bool(payload.get("gate_passed")):
        raise SystemExit(1)


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
