from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import click
import uvicorn

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


if __name__ == "__main__":
    cli()
