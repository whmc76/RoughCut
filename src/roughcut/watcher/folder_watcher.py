"""
Folder watcher: monitors directories for new video files,
deduplicates by SHA256 hash, creates jobs via DB, triggers pipeline.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from roughcut.config import get_settings
from roughcut.db.models import Job, WatchRoot
from roughcut.db.session import get_session_factory
from roughcut.media.probe import probe
from roughcut.media.output import get_output_dir
from roughcut.pipeline.orchestrator import create_job_steps
from roughcut.storage.s3 import get_storage, job_key

logger = logging.getLogger(__name__)

_SCAN_TASKS: dict[str, asyncio.Task] = {}
_SCAN_STATES: dict[str, "WatchInventoryScanState"] = {}
_SCAN_FILE_CACHE: dict[str, dict[str, "CachedWatchFileResult"]] = {}


@dataclass
class WatchInventoryItem:
    path: str
    relative_path: str
    source_name: str
    stem: str
    size_bytes: int
    modified_at: str
    duration_sec: float | None
    width: int | None
    height: int | None
    fps: float | None
    status: str
    dedupe_reason: str | None = None
    matched_job_id: str | None = None
    matched_output_path: str | None = None


@dataclass
class CachedWatchFileResult:
    size_bytes: int
    modified_at: str
    modified_ns: int
    file_hash: str | None
    duration_sec: float | None
    width: int | None
    height: int | None
    fps: float | None


@dataclass
class WatchInventoryScanState:
    root_path: str
    scan_mode: str
    status: str
    started_at: str
    updated_at: str
    finished_at: str | None
    total_files: int
    processed_files: int
    pending_count: int
    deduped_count: int
    current_file: str | None
    current_phase: str | None
    current_file_size_bytes: int | None
    current_file_processed_bytes: int | None
    error: str | None
    pending: list[dict]
    deduped: list[dict]

    def to_dict(self, *, include_inventory: bool = True, inventory_limit: int | None = None) -> dict:
        if include_inventory:
            pending = list(self.pending)
            deduped = list(self.deduped)
            if inventory_limit is not None:
                pending = pending[:inventory_limit]
                deduped = deduped[:inventory_limit]
        else:
            pending = []
            deduped = []
        return {
            "root_path": self.root_path,
            "scan_mode": self.scan_mode,
            "status": self.status,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "total_files": self.total_files,
            "processed_files": self.processed_files,
            "pending_count": self.pending_count,
            "deduped_count": self.deduped_count,
            "current_file": self.current_file,
            "current_phase": self.current_phase,
            "current_file_size_bytes": self.current_file_size_bytes,
            "current_file_processed_bytes": self.current_file_processed_bytes,
            "error": self.error,
            "inventory": {
                "pending": pending,
                "deduped": deduped,
            },
        }


def _hash_file(
    path: Path,
    chunk_size: int = 65536,
    progress_callback: Callable[[int, int], None] | None = None,
) -> str:
    sha256 = hashlib.sha256()
    total = path.stat().st_size
    processed = 0
    last_reported = 0
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
            processed += len(chunk)
            if progress_callback and (processed == total or processed - last_reported >= 8 * 1024 * 1024):
                progress_callback(processed, total)
                last_reported = processed
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


async def scan_watch_root_inventory(
    watch_path: str,
    *,
    recursive: bool = True,
    scan_mode: str = "fast",
) -> dict[str, list[dict]]:
    mode = _normalize_scan_mode(scan_mode)
    state = _new_scan_state(watch_path, scan_mode=mode)
    payload = await _scan_watch_root_inventory_impl(watch_path, recursive=recursive, state=state, scan_mode=mode)
    state.status = "done"
    state.current_file = None
    state.current_phase = None
    state.finished_at = _now_iso()
    state.updated_at = state.finished_at
    _SCAN_STATES[watch_path] = state
    return payload


def start_watch_root_inventory_scan(
    watch_path: str,
    *,
    recursive: bool = True,
    scan_mode: str = "fast",
    force: bool = False,
) -> dict:
    mode = _normalize_scan_mode(scan_mode)
    existing = _SCAN_TASKS.get(watch_path)
    if existing and not existing.done() and not force:
        return get_watch_root_inventory_scan_status(watch_path, include_inventory=False) or _new_scan_state(watch_path, scan_mode=mode).to_dict(include_inventory=False)
    if existing and not existing.done() and force:
        existing.cancel()

    state = _new_scan_state(watch_path, scan_mode=mode)
    _SCAN_STATES[watch_path] = state
    _SCAN_TASKS[watch_path] = asyncio.create_task(
        _run_watch_root_inventory_scan(watch_path, recursive=recursive, state=state, scan_mode=mode)
    )
    return state.to_dict(include_inventory=False)


def get_watch_root_inventory_scan_status(
    watch_path: str,
    *,
    include_inventory: bool = True,
    inventory_limit: int | None = None,
) -> dict | None:
    state = _SCAN_STATES.get(watch_path)
    if not state:
        return None
    return state.to_dict(include_inventory=include_inventory, inventory_limit=inventory_limit)


async def _run_watch_root_inventory_scan(
    watch_path: str,
    *,
    recursive: bool,
    state: WatchInventoryScanState,
    scan_mode: str,
) -> None:
    try:
        payload = await _scan_watch_root_inventory_impl(
            watch_path,
            recursive=recursive,
            state=state,
            scan_mode=scan_mode,
        )
        state.pending = payload["pending"]
        state.deduped = payload["deduped"]
        state.pending_count = len(state.pending)
        state.deduped_count = len(state.deduped)
        state.status = "done"
        state.current_file = None
        state.current_phase = None
        state.current_file_size_bytes = None
        state.current_file_processed_bytes = None
        state.finished_at = _now_iso()
        state.updated_at = state.finished_at
    except Exception as exc:
        state.status = "failed"
        state.current_file = None
        state.current_phase = None
        state.error = str(exc)
        state.finished_at = _now_iso()
        state.updated_at = state.finished_at
    finally:
        await _persist_scan_snapshot(watch_path, state)
        _SCAN_STATES[watch_path] = state
        _SCAN_TASKS.pop(watch_path, None)


async def _scan_watch_root_inventory_impl(
    watch_path: str,
    *,
    recursive: bool,
    state: WatchInventoryScanState,
    scan_mode: str,
) -> dict[str, list[dict]]:
    settings = get_settings()
    root = Path(watch_path)
    if not root.exists():
        raise FileNotFoundError(f"Watch path does not exist: {watch_path}")
    if not root.is_dir():
        raise NotADirectoryError(f"Watch path is not a directory: {watch_path}")

    pattern = "**/*" if recursive else "*"
    candidates = sorted(
        [
            path for path in root.glob(pattern)
            if path.is_file() and path.suffix.lower() in settings.allowed_extensions
        ],
        key=lambda p: (str(p.parent).lower(), p.name.lower()),
    )
    state.total_files = len(candidates)
    state.updated_at = _now_iso()

    output_dir = get_output_dir()
    existing_outputs = {
        path.stem: str(path)
        for path in output_dir.glob("*.mp4")
    }

    from sqlalchemy import select

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(select(Job.id, Job.file_hash, Job.source_name, Job.status))
        rows = result.all()

    jobs_by_hash = {
        file_hash: {"id": str(job_id), "source_name": source_name, "status": status}
        for job_id, file_hash, source_name, status in rows
        if file_hash
    }
    jobs_by_source_name = {
        str(source_name).lower(): {"id": str(job_id), "status": status}
        for job_id, _, source_name, status in rows
        if source_name and status != "failed"
    }

    pending: list[dict] = []
    deduped: list[dict] = []
    root_cache = _SCAN_FILE_CACHE.setdefault(watch_path, {})

    for index, file_path in enumerate(candidates, start=1):
        state.current_file = str(file_path.relative_to(root))
        state.current_phase = "indexing"
        state.current_file_size_bytes = file_path.stat().st_size
        state.current_file_processed_bytes = 0
        state.processed_files = index - 1
        state.updated_at = _now_iso()
        stat = file_path.stat()
        stem = file_path.stem
        item = WatchInventoryItem(
            path=str(file_path),
            relative_path=str(file_path.relative_to(root)),
            source_name=file_path.name,
            stem=stem,
            size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
            duration_sec=None,
            width=None,
            height=None,
            fps=None,
            status="pending",
        )

        cache_key = str(file_path)
        cached = root_cache.get(cache_key)
        cache_hit = cached is not None and cached.size_bytes == stat.st_size and cached.modified_ns == stat.st_mtime_ns
        file_hash: str | None = None
        if cache_hit:
            item.duration_sec = cached.duration_sec
            item.width = cached.width
            item.height = cached.height
            item.fps = cached.fps
            state.current_phase = "cached"
            state.current_file_processed_bytes = state.current_file_size_bytes
            state.updated_at = _now_iso()

        matched_by_name = jobs_by_source_name.get(file_path.name.lower())
        if matched_by_name:
            item.status = "deduped"
            item.dedupe_reason = f"job_name:{matched_by_name['status']}"
            item.matched_job_id = matched_by_name["id"]
            deduped_item = asdict(item)
            deduped.append(deduped_item)
            state.deduped = list(deduped)
            state.deduped_count = len(deduped)
            state.processed_files = index
            state.current_phase = "dedupe"
            state.current_file_processed_bytes = state.current_file_size_bytes
            state.updated_at = _now_iso()
            continue

        if "已剪" in file_path.stem or "已剪辑" in file_path.stem:
            item.status = "deduped"
            item.dedupe_reason = "filename_marked_edited"
            deduped_item = asdict(item)
            deduped.append(deduped_item)
            state.deduped = list(deduped)
            state.deduped_count = len(deduped)
            state.processed_files = index
            state.current_phase = "dedupe"
            state.current_file_processed_bytes = state.current_file_size_bytes
            state.updated_at = _now_iso()
            continue

        matched_output = next(
            (out_path for out_stem, out_path in existing_outputs.items() if out_stem.endswith(f"_{stem}") or out_stem == stem),
            None,
        )
        if matched_output:
            item.status = "deduped"
            item.dedupe_reason = "existing_output"
            item.matched_output_path = matched_output
            deduped_item = asdict(item)
            deduped.append(deduped_item)
            state.deduped = list(deduped)
            state.deduped_count = len(deduped)
            state.processed_files = index
            state.current_file_processed_bytes = state.current_file_size_bytes
            state.updated_at = _now_iso()
            continue

        if scan_mode == "precise":
            file_hash = cached.file_hash if cache_hit else None
            if not file_hash:
                state.current_phase = "hashing"
                state.current_file_processed_bytes = 0
                state.updated_at = _now_iso()
                file_hash = await asyncio.to_thread(
                    _hash_file,
                    file_path,
                    progress_callback=lambda processed, total: _update_scan_file_progress(state, processed, total),
                )
            matched_job = jobs_by_hash.get(file_hash)
            if matched_job:
                item.status = "deduped"
                item.dedupe_reason = f"job:{matched_job['status']}"
                item.matched_job_id = matched_job["id"]
                deduped_item = asdict(item)
                deduped.append(deduped_item)
                state.deduped = list(deduped)
                state.deduped_count = len(deduped)
                state.processed_files = index
                state.current_file_processed_bytes = state.current_file_size_bytes
                state.updated_at = _now_iso()
                root_cache[cache_key] = CachedWatchFileResult(
                    size_bytes=stat.st_size,
                    modified_at=item.modified_at,
                    modified_ns=stat.st_mtime_ns,
                    file_hash=file_hash,
                    duration_sec=item.duration_sec,
                    width=item.width,
                    height=item.height,
                    fps=item.fps,
                )
                continue

        try:
            if cache_hit:
                state.current_phase = "cached"
            else:
                state.current_phase = "probing"
                state.current_file_processed_bytes = max(1, int((state.current_file_size_bytes or 0) * 0.5))
                state.updated_at = _now_iso()
                meta = await probe(file_path)
                item.duration_sec = meta.duration
                item.width = meta.width or None
                item.height = meta.height or None
                item.fps = meta.fps or None
        except Exception:
            pass

        root_cache[cache_key] = CachedWatchFileResult(
            size_bytes=stat.st_size,
            modified_at=item.modified_at,
            modified_ns=stat.st_mtime_ns,
            file_hash=file_hash if file_hash is not None else (cached.file_hash if cache_hit else None),
            duration_sec=item.duration_sec,
            width=item.width,
            height=item.height,
            fps=item.fps,
        )

        pending_item = asdict(item)
        pending.append(pending_item)
        state.pending = list(pending)
        state.pending_count = len(pending)
        state.processed_files = index
        state.current_file_processed_bytes = state.current_file_size_bytes
        state.updated_at = _now_iso()

    return {"pending": pending, "deduped": deduped}


def _new_scan_state(watch_path: str, *, scan_mode: str) -> WatchInventoryScanState:
    now = _now_iso()
    return WatchInventoryScanState(
        root_path=watch_path,
        scan_mode=_normalize_scan_mode(scan_mode),
        status="running",
        started_at=now,
        updated_at=now,
        finished_at=None,
        total_files=0,
        processed_files=0,
        pending_count=0,
        deduped_count=0,
        current_file=None,
        current_phase=None,
        current_file_size_bytes=None,
        current_file_processed_bytes=None,
        error=None,
        pending=[],
        deduped=[],
    )


def _normalize_scan_mode(scan_mode: str | None) -> str:
    if scan_mode == "precise":
        return "precise"
    return "fast"


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _update_scan_file_progress(state: WatchInventoryScanState, processed: int, total: int) -> None:
    state.current_file_size_bytes = total
    state.current_file_processed_bytes = processed
    state.updated_at = _now_iso()


async def _persist_scan_snapshot(watch_path: str, state: WatchInventoryScanState) -> None:
    factory = get_session_factory()
    async with factory() as session:
        from sqlalchemy import select

        result = await session.execute(select(WatchRoot).where(WatchRoot.path == watch_path))
        root = result.scalar_one_or_none()
        if root is None:
            return
        root.inventory_cache_json = state.to_dict(include_inventory=True)
        root.inventory_cache_updated_at = datetime.utcnow()
        await session.commit()


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
