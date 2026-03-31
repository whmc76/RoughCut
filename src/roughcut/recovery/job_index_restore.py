from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import boto3
from sqlalchemy import select

from roughcut.db.models import Job
from roughcut.db.session import get_session_factory
from roughcut.pipeline.orchestrator import PIPELINE_STEPS, create_job_steps

GENERATED_OBJECT_NAMES = {
    "audio.wav",
    "output.mp4",
    "output_plain.mp4",
    "output_ai_effect.mp4",
    "output_avatar.mp4",
    "output_publish.md",
    "output_cover.jpg",
    "output_cover.png",
    "output_title.png",
    "output_subtitles.srt",
}
DONE_OBJECT_NAMES = {
    "output.mp4",
    "output_plain.mp4",
    "output_ai_effect.mp4",
    "output_avatar.mp4",
}


@dataclass(frozen=True)
class ObjectSummary:
    key: str
    size_bytes: int
    last_modified: datetime

    @property
    def name(self) -> str:
        return self.key.split("/", 1)[1] if "/" in self.key else self.key


@dataclass(frozen=True)
class RecoveredJob:
    job_id: str
    source_name: str
    source_path: str
    status: str
    language: str
    workflow_mode: str
    enhancement_modes: list[str]
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    step_statuses: dict[str, str]


def infer_recovered_job(job_id: str, objects: list[ObjectSummary], *, bucket: str) -> RecoveredJob:
    ordered = sorted(
        objects,
        key=lambda item: (_coerce_utc(item.last_modified), item.name.lower()),
    )
    source_candidates = [item for item in ordered if item.name not in GENERATED_OBJECT_NAMES]
    source_object = source_candidates[0] if source_candidates else None
    source_name = source_object.name if source_object is not None else f"recovered-{job_id}.mp4"
    names = {item.name for item in ordered}
    status = "done" if any(name in DONE_OBJECT_NAMES for name in names) else "failed"
    created_at = _coerce_utc(ordered[0].last_modified) if ordered else datetime.now(timezone.utc)
    updated_at = _coerce_utc(ordered[-1].last_modified) if ordered else created_at
    enhancement_modes = ["avatar_commentary"] if "output_avatar.mp4" in names else []
    error_message = None
    if source_object is None and status != "done":
        error_message = "Recovered from object storage without original source object"
    return RecoveredJob(
        job_id=job_id,
        source_name=source_name,
        source_path=f"s3://{bucket}/{job_id}/{source_name}",
        status=status,
        language="zh-CN",
        workflow_mode="standard_edit",
        enhancement_modes=enhancement_modes,
        error_message=error_message,
        created_at=created_at,
        updated_at=updated_at,
        step_statuses=_infer_step_statuses(status=status, object_names=names),
    )


def collect_recovered_jobs(
    *,
    endpoint_url: str,
    access_key_id: str,
    secret_access_key: str,
    bucket: str = "jobs",
    limit: int | None = None,
) -> list[RecoveredJob]:
    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
    )
    paginator = client.get_paginator("list_objects_v2")
    recovered: list[RecoveredJob] = []
    for page in paginator.paginate(Bucket=bucket, Delimiter="/"):
        for prefix_item in page.get("CommonPrefixes", []):
            prefix = str(prefix_item.get("Prefix") or "")
            job_id = prefix.rstrip("/")
            if not job_id:
                continue
            response = client.list_objects_v2(Bucket=bucket, Prefix=prefix, Delimiter="/")
            contents = response.get("Contents") or []
            objects = [
                ObjectSummary(
                    key=str(item.get("Key") or ""),
                    size_bytes=int(item.get("Size") or 0),
                    last_modified=_coerce_utc(item.get("LastModified")),
                )
                for item in contents
                if str(item.get("Key") or "").strip()
            ]
            if not objects:
                continue
            recovered.append(infer_recovered_job(job_id, objects, bucket=bucket))
            if limit is not None and len(recovered) >= max(0, int(limit)):
                return recovered
    return recovered


async def apply_recovered_jobs(candidates: list[RecoveredJob]) -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        existing_ids = {
            str(item)
            for item in (
                await session.execute(select(Job.id))
            ).scalars().all()
        }

        inserted = 0
        skipped = 0
        for candidate in candidates:
            if candidate.job_id in existing_ids:
                skipped += 1
                continue

            job_id = uuid.UUID(candidate.job_id)
            job = Job(
                id=job_id,
                source_path=candidate.source_path,
                source_name=candidate.source_name,
                status=candidate.status,
                language=candidate.language,
                workflow_mode=candidate.workflow_mode,
                enhancement_modes=list(candidate.enhancement_modes),
                error_message=candidate.error_message,
                created_at=candidate.created_at,
                updated_at=candidate.updated_at,
            )
            session.add(job)
            for step in create_job_steps(job_id):
                step.status = candidate.step_statuses.get(step.step_name, "pending")
                if step.status == "done":
                    step.started_at = candidate.created_at
                    step.finished_at = candidate.updated_at
                elif step.status == "failed":
                    step.started_at = candidate.updated_at
                    step.finished_at = candidate.updated_at
                    step.error_message = candidate.error_message or "Recovered as terminal failure"
                session.add(step)
            inserted += 1

        await session.commit()

    return {
        "candidates": len(candidates),
        "inserted": inserted,
        "skipped_existing": skipped,
    }


def _infer_step_statuses(*, status: str, object_names: set[str]) -> dict[str, str]:
    if status == "done":
        return {step_name: "done" for step_name in PIPELINE_STEPS}

    statuses = {step_name: "pending" for step_name in PIPELINE_STEPS}
    if object_names:
        statuses["probe"] = "done"
    if "audio.wav" in object_names:
        statuses["extract_audio"] = "done"
        statuses["transcribe"] = "failed"
    elif object_names:
        statuses["extract_audio"] = "failed"
    else:
        statuses["probe"] = "failed"
    return statuses


def _coerce_utc(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return datetime.now(timezone.utc)
