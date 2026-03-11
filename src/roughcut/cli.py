from __future__ import annotations

import asyncio
import logging

import click
import uvicorn


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@click.group()
def cli():
    """RoughCut - Automated video editing & subtitle review."""


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
def worker(queue: str, concurrency: int):
    """Start a Celery worker for the specified queue."""
    from roughcut.pipeline.celery_app import celery_app

    queues = ["media_queue", "llm_queue"] if queue == "all" else [queue]
    click.echo(f"Starting worker for queues: {queues}")
    celery_app.worker_main(
        argv=[
            "worker",
            f"--queues={','.join(queues)}",
            f"--concurrency={concurrency}",
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
