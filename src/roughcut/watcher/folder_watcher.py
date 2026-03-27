"""
Folder watcher: monitors directories for new video files,
deduplicates by SHA256 hash, creates jobs via DB, triggers pipeline.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import subprocess
import uuid
import json
import tempfile
import re
from difflib import SequenceMatcher
from datetime import datetime, timezone
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

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
    summary_hint: str | None
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


def replace_watch_root_inventory_scan_snapshot(watch_path: str, payload: dict) -> None:
    state = _SCAN_STATES.get(watch_path)
    if state is None:
        return
    state.scan_mode = payload.get("scan_mode") or state.scan_mode
    state.status = payload.get("status") or state.status
    state.started_at = payload.get("started_at") or state.started_at
    state.updated_at = payload.get("updated_at") or state.updated_at
    state.finished_at = payload.get("finished_at")
    state.total_files = int(payload.get("total_files") or 0)
    state.processed_files = int(payload.get("processed_files") or 0)
    state.pending_count = int(payload.get("pending_count") or 0)
    state.deduped_count = int(payload.get("deduped_count") or 0)
    state.current_file = payload.get("current_file")
    state.current_phase = payload.get("current_phase")
    state.current_file_size_bytes = payload.get("current_file_size_bytes")
    state.current_file_processed_bytes = payload.get("current_file_processed_bytes")
    state.error = payload.get("error")
    inventory = payload.get("inventory") or {}
    state.pending = list(inventory.get("pending") or [])
    state.deduped = list(inventory.get("deduped") or [])


async def create_jobs_for_inventory_paths(
    file_paths: list[str],
    *,
    channel_profile: str | None = None,
    language: str = "zh-CN",
) -> list[dict[str, str | None]]:
    results: list[dict[str, str | None]] = []
    for file_path in file_paths:
        job_id = await _create_job_for_file(Path(file_path), channel_profile, language)
        results.append({"path": file_path, "job_id": job_id or None})
    return results


async def ensure_watch_inventory_thumbnail(
    watch_path: str,
    relative_path: str,
    *,
    width: int = 320,
) -> Path:
    root = Path(watch_path).resolve()
    source = (root / relative_path).resolve()
    source.relative_to(root)
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(str(source))

    stat = source.stat()
    cache_root = Path("output/test/watch-previews") / hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:12]
    cache_root.mkdir(parents=True, exist_ok=True)
    cache_name = hashlib.sha1(
        f"{relative_path}|{stat.st_mtime_ns}|{stat.st_size}|{width}".encode("utf-8")
    ).hexdigest()
    output_path = cache_root / f"{cache_name}.jpg"
    if output_path.exists():
        return output_path

    seek_sec = 0.5
    try:
        meta = await probe(source)
        if meta.duration > 0:
            seek_sec = max(0.0, min(meta.duration * 0.1, max(meta.duration - 0.1, 0.0)))
    except Exception:
        pass

    settings = get_settings()
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{seek_sec:.2f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:-2",
        str(output_path),
    ]
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.ffmpeg_timeout_sec,
        ),
    )
    if result.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"ffmpeg thumbnail failed: {result.stderr[-500:]}")
    return output_path


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
        for path in output_dir.rglob("*.mp4")
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
            summary_hint=_build_inventory_summary_hint(file_path),
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
                state.current_file_processed_bytes = None
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
    return datetime.now(timezone.utc).isoformat()


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
        root.inventory_cache_updated_at = datetime.now(timezone.utc)
        await session.commit()


async def _create_job_for_file(
    file_path: Path,
    channel_profile: str | None = None,
    language: str = "zh-CN",
) -> str:
    """Upload file to S3, create job + steps in DB. Returns job_id."""
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
        settings = get_settings()
        job = Job(
            id=job_id,
            source_path=s3_key,
            source_name=file_path.name,
            file_hash=file_hash,
            status="pending",
            language=language,
            channel_profile=channel_profile,
            workflow_mode=settings.default_job_workflow_mode,
            enhancement_modes=list(settings.default_job_enhancement_modes or []),
        )
        session.add(job)
        for step in create_job_steps(job_id):
            session.add(step)
        await session.commit()

    logger.info(f"Created job {job_id} for {file_path.name}")
    return str(job_id)


def _concat_list_entry(path: Path) -> str:
    normalized = str(path).replace("\\", "/")
    escaped = normalized.replace("'", "\\'")
    return f"file '{escaped}'"


async def _run_concat_ffmpeg(
    list_file: Path,
    output_path: Path,
    *,
    transcode: bool,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-movflags",
        "+faststart",
    ]
    if transcode:
        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "18",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
            ]
        )
    else:
        cmd.extend(["-c", "copy"])
    cmd.append(str(output_path))
    settings = get_settings()

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=settings.ffmpeg_timeout_sec,
        ),
    )


async def _merge_videos_for_job(file_paths: list[Path], *, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        list_file = Path(tmpdir) / "files.txt"
        with list_file.open("w", encoding="utf-8") as handle:
            for path in file_paths:
                handle.write(_concat_list_entry(path))
                handle.write("\n")

        result = await _run_concat_ffmpeg(list_file, output_path, transcode=False)
        if result.returncode != 0:
            logger.warning("Video merge with stream copy failed, fallback to transcode: %s", result.stderr[-400:])
            if output_path.exists():
                output_path.unlink()
            result = await _run_concat_ffmpeg(list_file, output_path, transcode=True)

    if result.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"ffmpeg concat merge failed: {result.stderr[-500:]}")
    return output_path


async def create_merged_job_for_inventory_paths(
    file_paths: list[str],
    *,
    channel_profile: str | None = None,
    language: str = "zh-CN",
) -> str | None:
    if len(file_paths) < 2:
        raise ValueError("At least two files are required to create a merged job")

    resolved_paths = [Path(file_path).resolve() for file_path in file_paths]
    for path in resolved_paths:
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(str(path))

    output_dir = Path("output/test/watch-merged")
    output_path = output_dir / f"watch_merge_{uuid.uuid4().hex}.mp4"

    merged_path = await _merge_videos_for_job(resolved_paths, output_path=output_path)
    try:
        return await _create_job_for_file(merged_path, channel_profile, language)
    finally:
        if merged_path.exists():
            merged_path.unlink()


def _to_unix_timestamp(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except ValueError:
        return 0.0


def _safe_parse_summary(path: Path) -> str:
    candidates = [
        path.with_name(f"{path.stem}.summary.txt"),
        path.with_name(f"{path.stem}.summary"),
        path.with_name(f"{path.stem}.txt"),
        path.with_name(f"{path.stem}.meta.json"),
    ]
    for candidate in candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        try:
            if candidate.suffix.lower() == ".json":
                text = candidate.read_text(encoding="utf-8").strip()
                if not text:
                    continue
                data = json.loads(text)
                if not isinstance(data, dict):
                    continue
                for key in ("summary", "desc", "description", "caption", "notes"):
                    value = data.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
            else:
                text = candidate.read_text(encoding="utf-8").strip()
                if text:
                    return text
        except Exception:
            continue
    return ""


def _build_inventory_summary_hint(path: Path) -> str:
    summary = _safe_parse_summary(path)
    if summary:
        return re.sub(r"\s+", " ", summary).strip()[:140]
    stem = Path(path).stem
    normalized = re.sub(r"[_\-]+", " ", stem)
    normalized = re.sub(r"\b\d{6,}\b", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized[:80]


def _file_timestamp_metrics(path: Path) -> tuple[float, float]:
    stat = path.stat()
    # Windows 中 st_ctime 通常接近文件创建时间；Linux 环境常作为元数据修改时间，
    # 这里保留作为二级时间特征使用。
    return float(stat.st_ctime), float(stat.st_mtime)


def _extract_name_tokens(value: str) -> set[str]:
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", Path(value).stem.lower())
    tokens = {token for token in normalized.split(" ") if len(token) >= 2}
    return tokens


def _reason_tags(scores: dict[str, float]) -> list[str]:
    reasons: list[str] = []
    if scores["time"] >= 0.55:
        reasons.append("拍摄时间接近")
    if scores["name"] >= 0.35:
        reasons.append("文件名关键词相似")
    if scores["duration"] >= 0.55:
        reasons.append("时长接近")
    if scores["summary"] >= 0.30:
        reasons.append("摘要文本相似")
    if not reasons:
        reasons.append("整体特征接近")
    return reasons


async def _extract_visual_signature(path: Path) -> str | None:
    settings = get_settings()
    cmd = [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        "-ss",
        "0.5",
        "-i",
        str(path),
        "-vf",
        "scale=16:16,format=gray",
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "pipe:1",
    ]
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            capture_output=True,
            text=False,
            timeout=min(settings.ffmpeg_timeout_sec, 120),
        ),
    )
    if result.returncode != 0 or not result.stdout:
        return None

    raw = result.stdout
    if len(raw) < 128:
        return None
    payload = raw[:256]
    average = sum(payload) / len(payload)
    return "".join("1" if value >= average else "0" for value in payload)


def _signature_similarity(a: str | None, b: str | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    distance = sum(1 for ch_a, ch_b in zip(a, b) if ch_a != ch_b)
    return 1.0 - distance / max(len(a), 1)


def _token_similarity(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _summary_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left.lower(), right.lower()).ratio()


def _find(parent: list[int], index: int) -> int:
    while parent[index] != index:
        parent[index] = parent[parent[index]]
        index = parent[index]
    return index


def _union(parent: list[int], left: int, right: int) -> None:
    left_root = _find(parent, left)
    right_root = _find(parent, right)
    if left_root != right_root:
        parent[right_root] = left_root


async def suggest_merge_groups_for_inventory_items(
    items: list[dict],
    *,
    time_window_seconds: int = 480,
    min_score: float = 0.62,
    min_group_size: int = 2,
    max_groups: int = 8,
) -> list[dict[str, Any]]:
    if len(items) < min_group_size:
        return []

    prepared: list[dict[str, Any]] = []
    for item in items:
        path = Path(str(item.get("path")))
        if not path.exists():
            continue
        created_at, modified_at = _file_timestamp_metrics(path)
        prepared.append(
            {
                "path": str(path),
                "relative_path": str(item.get("relative_path") or item.get("source_name")),
                "created_at": created_at,
                "modified": _to_unix_timestamp(str(item.get("modified_at"))) or modified_at,
                "duration": float(item.get("duration_sec") or 0.0),
                "size": int(item.get("size_bytes") or 0),
                "source_name": str(item.get("source_name") or path.name),
                "summary": _safe_parse_summary(path),
                "signature": None,
                "name_tokens": _extract_name_tokens(str(item.get("source_name") or path.name)),
            }
        )

    signatures = await asyncio.gather(
        *(
            _extract_visual_signature(Path(item["path"]))
            for item in prepared
        ),
        return_exceptions=True,
    )
    for index, signature in enumerate(signatures):
        if isinstance(signature, Exception):
            logger.warning("Failed to extract visual signature for %s: %s", prepared[index]["path"], signature)
            prepared[index]["signature"] = None
        else:
            prepared[index]["signature"] = signature

    if len(prepared) < 2:
        return []

    prepared.sort(key=lambda item: item["modified"])

    filtered = [item for item in prepared if item["relative_path"]]
    if len(filtered) < min_group_size:
        return []

    parent = list(range(len(filtered)))
    pair_scores: dict[tuple[int, int], float] = {}
    pair_reasons: dict[tuple[int, int], list[str]] = {}

    for left in range(len(filtered)):
        for right in range(left + 1, len(filtered)):
            left_item = filtered[left]
            right_item = filtered[right]

            created_gap = abs(left_item["created_at"] - right_item["created_at"])
            modified_gap = abs(left_item["modified"] - right_item["modified"])
            nearest_time_gap = min(created_gap, modified_gap)
            if nearest_time_gap > time_window_seconds * 2:
                continue

            created_score = max(0.0, 1 - (created_gap / max(time_window_seconds, 1)))
            modified_score = max(0.0, 1 - (modified_gap / max(time_window_seconds, 1)))
            time_score = max(created_score, modified_score)
            duration_gap = abs(left_item["duration"] - right_item["duration"])
            duration_score = 1 - min(duration_gap / 90.0, 1.0)
            name_score = _token_similarity(left_item["name_tokens"], right_item["name_tokens"])
            summary_score = _summary_similarity(left_item["summary"], right_item["summary"])
            visual_score = _signature_similarity(left_item["signature"], right_item["signature"])

            score = (
                time_score * 0.46
                + summary_score * 0.24
                + visual_score * 0.2
                + name_score * 0.06
                + duration_score * 0.04
            )
            if score < min_score:
                continue

            pair = (left, right)
            pair_scores[pair] = score
            pair_reasons[pair] = _reason_tags(
                {
                    "time": time_score,
                    "name": name_score,
                    "duration": duration_score,
                    "summary": summary_score,
                    "visual": visual_score,
                }
            )
            _union(parent, left, right)

    groups: dict[int, list[int]] = {}
    for index in range(len(filtered)):
        groups.setdefault(_find(parent, index), []).append(index)

    results: list[dict[str, Any]] = []
    for indexes in groups.values():
        if len(indexes) < min_group_size:
            continue

        scores: list[float] = []
        reason_set: set[str] = set()
        for left in range(len(indexes)):
            for right in range(left + 1, len(indexes)):
                pair = (indexes[left], indexes[right])
                pair_score = pair_scores.get(pair)
                if pair_score is None:
                    continue
                scores.append(pair_score)
                reason_set.update(pair_reasons.get(pair, []))
        if not scores:
            continue

        candidate_score = sum(scores) / len(scores)
        if candidate_score < min_score:
            continue

        relative_paths = [filtered[index]["relative_path"] for index in indexes]
        if len(relative_paths) < min_group_size:
            continue

        results.append(
            {
                "relative_paths": relative_paths,
                "score": candidate_score,
                "reasons": sorted(reason_set),
            }
        )

    results.sort(key=lambda entry: (entry["score"], len(entry["relative_paths"])), reverse=True)
    return results[:max_groups]


_GPU_INTENSIVE_PIPELINE_STEPS = {"transcribe", "avatar_commentary", "render"}


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_inventory_item_settled(item: dict[str, Any], *, settle_seconds: int) -> bool:
    path = Path(str(item.get("path") or ""))
    if not path.exists():
        return False
    now = datetime.now(timezone.utc).timestamp()
    stat = path.stat()
    modified_at = max(float(stat.st_mtime), _to_unix_timestamp(str(item.get("modified_at") or "")))
    return (now - modified_at) >= max(5, int(settle_seconds))


def _normalize_inventory_payload_status(payload: dict[str, Any]) -> dict[str, Any]:
    inventory = payload.get("inventory") or {}
    payload["inventory"] = {
        "pending": list(inventory.get("pending") or []),
        "deduped": list(inventory.get("deduped") or []),
    }
    payload["pending_count"] = len(payload["inventory"]["pending"])
    payload["deduped_count"] = len(payload["inventory"]["deduped"])
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    if payload.get("status") in {None, "", "idle"}:
        payload["status"] = "done"
    return payload


def _mark_inventory_items_as_dispatched(
    payload: dict[str, Any],
    selected_items: list[dict[str, Any]],
    *,
    job_ids_by_path: dict[str, str | None],
    dedupe_reason: str,
) -> tuple[dict[str, Any], list[str]]:
    inventory = payload.get("inventory") or {}
    pending = list(inventory.get("pending") or [])
    deduped = list(inventory.get("deduped") or [])
    selected_path_set = {str(item.get("path") or "") for item in selected_items}
    remaining_pending = [item for item in pending if str(item.get("path") or "") not in selected_path_set]
    created_job_ids: list[str] = []
    seen_job_ids: set[str] = set()
    for item in selected_items:
        path = str(item.get("path") or "")
        job_id = job_ids_by_path.get(path)
        if job_id and job_id not in seen_job_ids:
            seen_job_ids.add(job_id)
            created_job_ids.append(job_id)
        deduped.append(
            {
                **item,
                "status": "deduped",
                "dedupe_reason": dedupe_reason if job_id else "job:existing",
                "matched_job_id": job_id,
            }
        )
    payload["inventory"] = {
        "pending": remaining_pending,
        "deduped": deduped,
    }
    return _normalize_inventory_payload_status(payload), created_job_ids


async def _load_auto_scheduler_state(session) -> dict[str, int]:
    from sqlalchemy import func, select
    from roughcut.db.models import JobStep

    active_jobs_result = await session.execute(
        select(func.count(Job.id)).where(Job.status.in_(["pending", "processing"]))
    )
    gpu_steps_result = await session.execute(
        select(func.count(JobStep.id)).where(
            JobStep.status == "running",
            JobStep.step_name.in_(sorted(_GPU_INTENSIVE_PIPELINE_STEPS)),
        )
    )
    return {
        "active_jobs": int(active_jobs_result.scalar() or 0),
        "running_gpu_steps": int(gpu_steps_result.scalar() or 0),
    }


def _available_auto_slots(state: dict[str, int], settings) -> int:
    if int(state.get("running_gpu_steps") or 0) > 0:
        return 0
    return max(0, int(getattr(settings, "watch_auto_max_active_jobs", 2)) - int(state.get("active_jobs") or 0))


def _should_auto_scan_root(root: WatchRoot, *, settings) -> bool:
    active = get_watch_root_inventory_scan_status(root.path, include_inventory=False)
    if active and active.get("status") == "running":
        return False
    if root.inventory_cache_updated_at is None:
        return True
    age = datetime.now(timezone.utc) - root.inventory_cache_updated_at.replace(tzinfo=timezone.utc)
    return age.total_seconds() >= max(15, int(getattr(settings, "watch_auto_scan_interval_sec", 45)))


def _get_cached_inventory_payload(root: WatchRoot) -> dict[str, Any]:
    cached = root.inventory_cache_json if isinstance(root.inventory_cache_json, dict) else {}
    payload = {
        "root_path": root.path,
        "scan_mode": root.scan_mode or "fast",
        "status": cached.get("status") or "idle",
        "started_at": cached.get("started_at") or "",
        "updated_at": cached.get("updated_at") or "",
        "finished_at": cached.get("finished_at"),
        "total_files": int(cached.get("total_files") or 0),
        "processed_files": int(cached.get("processed_files") or 0),
        "pending_count": int(cached.get("pending_count") or 0),
        "deduped_count": int(cached.get("deduped_count") or 0),
        "current_file": cached.get("current_file"),
        "current_phase": cached.get("current_phase"),
        "current_file_size_bytes": cached.get("current_file_size_bytes"),
        "current_file_processed_bytes": cached.get("current_file_processed_bytes"),
        "error": cached.get("error"),
        "inventory": cached.get("inventory") or {"pending": [], "deduped": []},
    }
    return _normalize_inventory_payload_status(payload)


async def _persist_inventory_payload(root: WatchRoot, session, payload: dict[str, Any]) -> None:
    root.inventory_cache_json = payload
    root.inventory_cache_updated_at = datetime.now(timezone.utc)
    await session.flush()
    replace_watch_root_inventory_scan_snapshot(root.path, payload)


def _pick_non_overlapping_merge_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used_paths: set[str] = set()
    for group in groups:
        paths = [str(item) for item in group.get("relative_paths") or [] if str(item)]
        if len(paths) < 2:
            continue
        if any(path in used_paths for path in paths):
            continue
        selected.append({**group, "relative_paths": paths})
        used_paths.update(paths)
    return selected


async def run_watch_root_auto_duty() -> dict[str, Any]:
    from sqlalchemy import select

    settings = get_settings()
    factory = get_session_factory()
    summary = {
        "roots_total": 0,
        "scan_started": 0,
        "auto_merged_jobs": 0,
        "auto_enqueued_jobs": 0,
        "idle_slots": 0,
    }
    async with factory() as session:
        result = await session.execute(
            select(WatchRoot).where(WatchRoot.enabled.is_(True)).order_by(WatchRoot.created_at.asc())
        )
        roots = result.scalars().all()
        summary["roots_total"] = len(roots)
        scheduler_state = await _load_auto_scheduler_state(session)
        summary["idle_slots"] = _available_auto_slots(scheduler_state, settings)

        for root in roots:
            try:
                if _should_auto_scan_root(root, settings=settings):
                    try:
                        start_watch_root_inventory_scan(root.path, scan_mode=root.scan_mode or "fast", force=False)
                        summary["scan_started"] += 1
                    except Exception as exc:
                        logger.warning("auto duty failed to start scan for %s: %s", root.path, exc)
                    continue

                active_status = get_watch_root_inventory_scan_status(root.path, include_inventory=False)
                if active_status and active_status.get("status") == "running":
                    continue

                payload = _get_cached_inventory_payload(root)
                pending = list((payload.get("inventory") or {}).get("pending") or [])
                if not pending:
                    continue

                settled_pending = [
                    item for item in pending
                    if _is_inventory_item_settled(item, settle_seconds=int(getattr(settings, "watch_auto_settle_seconds", 45)))
                ]
                if not settled_pending:
                    continue

                idle_slots = _available_auto_slots(scheduler_state, settings)
                if idle_slots <= 0:
                    continue

                max_jobs_per_root = max(1, int(getattr(settings, "watch_auto_max_jobs_per_root", 1)))

                if bool(getattr(settings, "watch_auto_merge_enabled", True)) and idle_slots > 0:
                    merge_groups = await suggest_merge_groups_for_inventory_items(
                        settled_pending,
                        min_score=float(getattr(settings, "watch_auto_merge_min_score", 0.72)),
                        max_groups=max_jobs_per_root,
                    )
                    for group in _pick_non_overlapping_merge_groups(merge_groups)[: min(idle_slots, max_jobs_per_root)]:
                        selected_items = [
                            item for item in settled_pending
                            if str(item.get("relative_path") or "") in set(group.get("relative_paths") or [])
                        ]
                        if len(selected_items) < 2:
                            continue
                        job_id = await create_merged_job_for_inventory_paths(
                            [str(item.get("path") or "") for item in selected_items],
                            channel_profile=root.channel_profile,
                        )
                        payload, created_ids = _mark_inventory_items_as_dispatched(
                            payload,
                            selected_items,
                            job_ids_by_path={str(item.get("path") or ""): job_id for item in selected_items},
                            dedupe_reason="job:auto_merged",
                        )
                        if created_ids:
                            summary["auto_merged_jobs"] += len(created_ids)
                            scheduler_state["active_jobs"] += len(created_ids)
                            idle_slots -= len(created_ids)
                            settled_pending = [
                                item for item in settled_pending
                                if str(item.get("path") or "") not in {str(sel.get("path") or "") for sel in selected_items}
                            ]
                        logger.info(
                            "auto duty merged root=%s score=%.2f files=%s job_ids=%s",
                            root.path,
                            float(group.get("score") or 0.0),
                            ",".join(group.get("relative_paths") or []),
                            ",".join(created_ids),
                        )
                        if idle_slots <= 0:
                            break

                if (
                    bool(getattr(settings, "watch_auto_enqueue_enabled", True))
                    and idle_slots > 0
                    and settled_pending
                ):
                    eligible = sorted(
                        settled_pending,
                        key=lambda item: _to_unix_timestamp(str(item.get("modified_at") or "")),
                    )
                    selected_items = eligible[: min(idle_slots, max_jobs_per_root)]
                    if selected_items:
                        results = await create_jobs_for_inventory_paths(
                            [str(item.get("path") or "") for item in selected_items],
                            channel_profile=root.channel_profile,
                        )
                        job_ids_by_path = {result["path"]: result["job_id"] for result in results}
                        payload, created_ids = _mark_inventory_items_as_dispatched(
                            payload,
                            selected_items,
                            job_ids_by_path=job_ids_by_path,
                            dedupe_reason="job:auto_enqueued",
                        )
                        if created_ids:
                            summary["auto_enqueued_jobs"] += len(created_ids)
                            scheduler_state["active_jobs"] += len(created_ids)
                            logger.info(
                                "auto duty enqueued root=%s files=%s job_ids=%s",
                                root.path,
                                ",".join(str(item.get("relative_path") or "") for item in selected_items),
                                ",".join(created_ids),
                            )

                await _persist_inventory_payload(root, session, payload)
            except Exception as exc:
                logger.exception("auto duty root failed root=%s error=%s", root.path, exc)

        await session.commit()

    return summary


async def get_watch_root_auto_duty_snapshot() -> dict[str, Any]:
    from sqlalchemy import select

    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(WatchRoot).where(WatchRoot.enabled.is_(True)).order_by(WatchRoot.created_at.asc())
        )
        roots = result.scalars().all()
        scheduler_state = await _load_auto_scheduler_state(session)

    running_scans = 0
    cached_pending_total = 0
    for root in roots:
        status = get_watch_root_inventory_scan_status(root.path, include_inventory=False)
        if status and status.get("status") == "running":
            running_scans += 1
        payload = _get_cached_inventory_payload(root)
        cached_pending_total += len(list((payload.get("inventory") or {}).get("pending") or []))

    return {
        "roots_total": len(roots),
        "running_scans": running_scans,
        "cached_pending_total": cached_pending_total,
        "auto_enqueue_enabled": bool(getattr(settings, "watch_auto_enqueue_enabled", True)),
        "auto_merge_enabled": bool(getattr(settings, "watch_auto_merge_enabled", True)),
        "active_jobs": int(scheduler_state.get("active_jobs") or 0),
        "running_gpu_steps": int(scheduler_state.get("running_gpu_steps") or 0),
        "idle_slots": _available_auto_slots(scheduler_state, settings),
    }


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

    def _submit_job(self, file_path: Path) -> None:
        if file_path.suffix.lower() not in self._settings.allowed_extensions:
            return
        logger.info(f"New file detected: {file_path}")
        future = asyncio.run_coroutine_threadsafe(
            _create_job_for_file(file_path, self._channel_profile, self._language),
            self._loop,
        )

        def _done_callback(task: asyncio.Future[None]) -> None:
            try:
                job_id = task.result()
                if job_id:
                    logger.info(f"Created watch job: {file_path} -> {job_id}")
            except Exception:
                logger.exception(f"Failed to create watch job: {file_path}")

        future.add_done_callback(_done_callback)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._submit_job(Path(str(event.src_path)))

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._submit_job(Path(str(event.dest_path)))


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
            select(WatchRoot).where(WatchRoot.enabled.is_(True))
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
