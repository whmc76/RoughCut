from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import BinaryIO

from roughcut.config import get_settings


class S3Storage:
    def __init__(self) -> None:
        settings = get_settings()
        self._bucket = settings.s3_bucket_name
        configured_root = getattr(settings, "job_storage_dir", "data/jobs")
        self._root = Path(str(configured_root or "data/jobs")).expanduser().resolve()

    def ensure_bucket(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    def resolve_path(self, key: str) -> Path:
        raw = str(key or "").strip()
        if raw.lower().startswith("s3://"):
            raw = raw[5:]
        candidate = Path(raw).expanduser()
        if candidate.is_absolute():
            if candidate.exists():
                return candidate
            remapped = _remap_windows_job_storage_path(raw, storage_root=self._root)
            return remapped or candidate
        remapped = _remap_windows_job_storage_path(raw, storage_root=self._root)
        if remapped is not None:
            return remapped
        relative = candidate
        if self._root.name.lower() == "jobs" and candidate.parts[:1] == ("jobs",):
            relative = Path(*candidate.parts[1:]) if len(candidate.parts) > 1 else Path()
        return (self._root / relative).resolve()

    def upload_file(self, local_path: Path, key: str) -> str:
        target_path = self.resolve_path(key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, target_path)
        return key

    def upload_fileobj(self, fileobj: BinaryIO, key: str) -> str:
        target_path = self.resolve_path(key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("wb") as handle:
            shutil.copyfileobj(fileobj, handle)
        return key

    def download_file(self, key: str, local_path: Path) -> Path:
        source_path = self.resolve_path(key)
        if source_path.is_dir():
            return self._download_multipart_object(source_path, local_path)
        if not source_path.exists():
            raise FileNotFoundError(str(source_path))
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, local_path)
        return local_path

    def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        del expires_in
        return str(self.resolve_path(key))

    def delete_object(self, key: str) -> None:
        target_path = self.resolve_path(key)
        try:
            target_path.unlink(missing_ok=True)
        except IsADirectoryError:
            shutil.rmtree(target_path, ignore_errors=True)

    def object_exists(self, key: str) -> bool:
        return self.resolve_path(key).exists()

    def delete_prefix(self, prefix: str) -> None:
        prefix_path = self.resolve_path(prefix)
        if prefix_path.exists():
            shutil.rmtree(prefix_path, ignore_errors=True)

    async def async_upload_file(self, local_path: Path, key: str) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.upload_file, local_path, key)

    async def async_download_file(self, key: str, local_path: Path) -> Path:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.download_file, key, local_path)

    def _download_multipart_object(self, source_path: Path, local_path: Path) -> Path:
        part_files = sorted(
            (part for part in source_path.rglob("part.*") if part.is_file()),
            key=_multipart_part_sort_key,
        )
        if not part_files:
            raise FileNotFoundError(str(source_path))

        local_path.parent.mkdir(parents=True, exist_ok=True)
        with local_path.open("wb") as handle:
            for part in part_files:
                with part.open("rb") as source:
                    shutil.copyfileobj(source, handle)
        return local_path


def job_key(job_id: str, filename: str) -> str:
    return f"jobs/{job_id}/{filename}"


_storage: S3Storage | None = None


def get_storage() -> S3Storage:
    global _storage
    if _storage is None:
        _storage = S3Storage()
    return _storage


def _multipart_part_sort_key(path: Path) -> tuple[int, str]:
    suffix = path.name.split(".", 1)[-1]
    if suffix.isdigit():
        return int(suffix), path.name
    return 0, path.name


def _remap_windows_job_storage_path(raw: str, *, storage_root: Path) -> Path | None:
    normalized = str(raw or "").strip().replace("\\", "/")
    if not re.match(r"^[A-Za-z]:/", normalized):
        return None
    marker = "/jobs/"
    index = normalized.lower().find(marker)
    if index < 0:
        return None
    relative = normalized[index + len(marker):].strip("/")
    if not relative:
        return storage_root.resolve()
    return (storage_root / Path(relative)).resolve()
