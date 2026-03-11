"""
Folder watcher: monitors directories for new video files,
deduplicates by SHA256 hash, creates jobs via DB, triggers pipeline.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from roughcut.config import get_settings
from roughcut.db.models import Job, WatchRoot
from roughcut.db.session import get_session_factory
from roughcut.pipeline.orchestrator import create_job_steps
from roughcut.storage.s3 import get_storage, job_key

logger = logging.getLogger(__name__)


def _hash_file(path: Path, chunk_size: int = 65536) -> str:
    sha256 = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()


async def _file_already_processed(file_hash: str) -> bool:
    """Return True if a job with this hash already exists."""
    from sqlalchemy import select
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Job).where(Job.file_hash == file_hash)
        )
        return result.scalar_one_or_none() is not None


async def _create_job_for_file(
    file_path: Path,
    channel_profile: str | None = None,
    language: str = "zh-CN",
) -> str:
    """Upload file to S3, create job + steps in DB. Returns job_id."""
    settings = get_settings()

    # Compute hash first for dedup
    file_hash = _hash_file(file_path)
    if await _file_already_processed(file_hash):
        logger.info(f"File already processed (hash={file_hash[:8]}): {file_path}")
        return ""

    job_id = uuid.uuid4()
    storage = get_storage()
    storage.ensure_bucket()

    s3_key = job_key(str(job_id), file_path.name)
    storage.upload_file(file_path, s3_key)
    logger.info(f"Uploaded {file_path.name} → {s3_key}")

    factory = get_session_factory()
    async with factory() as session:
        job = Job(
            id=job_id,
            source_path=s3_key,
            source_name=file_path.name,
            file_hash=file_hash,
            status="pending",
            language=language,
            channel_profile=channel_profile,
        )
        session.add(job)
        for step in create_job_steps(job_id):
            session.add(step)
        await session.commit()

    logger.info(f"Created job {job_id} for {file_path.name}")
    return str(job_id)


class VideoFileHandler(FileSystemEventHandler):
    def __init__(
        self,
        channel_profile: str | None,
        language: str,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._channel_profile = channel_profile
        self._language = language
        self._loop = loop
        self._settings = get_settings()

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(str(event.src_path))
        if path.suffix.lower() not in self._settings.allowed_extensions:
            return
        logger.info(f"New file detected: {path}")
        asyncio.run_coroutine_threadsafe(
            _create_job_for_file(path, self._channel_profile, self._language),
            self._loop,
        )


async def watch_directory(
    watch_path: str,
    channel_profile: str | None = None,
    language: str = "zh-CN",
) -> None:
    """Watch a directory for new video files. Runs until cancelled."""
    path = Path(watch_path)
    if not path.exists():
        raise FileNotFoundError(f"Watch path does not exist: {watch_path}")

    loop = asyncio.get_running_loop()
    handler = VideoFileHandler(channel_profile, language, loop)
    observer = Observer()
    observer.schedule(handler, str(path), recursive=True)
    observer.start()
    logger.info(f"Watching directory: {path}")

    try:
        while True:
            await asyncio.sleep(1)
    finally:
        observer.stop()
        observer.join()


async def watch_from_db() -> None:
    """Load watch roots from DB and start watching all enabled ones."""
    from sqlalchemy import select
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(WatchRoot).where(WatchRoot.enabled == True)
        )
        roots = result.scalars().all()

    if not roots:
        logger.warning("No watch roots configured in DB")
        return

    tasks = [
        asyncio.create_task(
            watch_directory(root.path, root.channel_profile)
        )
        for root in roots
    ]
    await asyncio.gather(*tasks)
