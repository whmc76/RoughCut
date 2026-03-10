from __future__ import annotations

import asyncio
from pathlib import Path
from typing import BinaryIO

import boto3
from botocore.exceptions import ClientError

from fastcut.config import get_settings


class S3Storage:
    def __init__(self) -> None:
        settings = get_settings()
        self._bucket = settings.s3_bucket_name
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region,
        )

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            self._client.create_bucket(Bucket=self._bucket)

    def upload_file(self, local_path: Path, key: str) -> str:
        self._client.upload_file(str(local_path), self._bucket, key)
        return key

    def upload_fileobj(self, fileobj: BinaryIO, key: str) -> str:
        self._client.upload_fileobj(fileobj, self._bucket, key)
        return key

    def download_file(self, key: str, local_path: Path) -> Path:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(self._bucket, key, str(local_path))
        return local_path

    def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def delete_object(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def object_exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False

    # Async wrappers using thread pool
    async def async_upload_file(self, local_path: Path, key: str) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.upload_file, local_path, key)

    async def async_download_file(self, key: str, local_path: Path) -> Path:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.download_file, key, local_path)


def job_key(job_id: str, filename: str) -> str:
    return f"jobs/{job_id}/{filename}"


_storage: S3Storage | None = None


def get_storage() -> S3Storage:
    global _storage
    if _storage is None:
        _storage = S3Storage()
    return _storage
