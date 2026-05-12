from __future__ import annotations

import json
import subprocess
import uuid
from types import SimpleNamespace
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.api.schemas import (
    IntelligentCopyGenerateIn,
    IntelligentCopyInspectIn,
    IntelligentCopyInspectOut,
    IntelligentPublishIn,
    IntelligentCopyResultOut,
    OpenFolderOut,
)
from roughcut.avatar import get_avatar_material_profile, list_avatar_material_profiles
from roughcut.db.models import Job, RenderOutput
from roughcut.db.session import get_session
from roughcut.pipeline.celery_app import celery_app
from roughcut.publication import (
    active_publication_credentials,
    build_publication_plan,
    list_publication_attempts,
    submit_publication_attempts,
)
from roughcut.review.intelligent_copy import generate_intelligent_copy, inspect_intelligent_copy_folder

router = APIRouter(prefix="/intelligent-copy", tags=["intelligent-copy"])


@router.post("/inspect", response_model=IntelligentCopyInspectOut)
def inspect_folder(body: IntelligentCopyInspectIn):
    try:
        return inspect_intelligent_copy_folder(body.folder_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/generate", response_model=IntelligentCopyResultOut)
async def generate_folder_materials(body: IntelligentCopyGenerateIn):
    try:
        return await generate_intelligent_copy(body.folder_path, copy_style=body.copy_style)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/publication/plan")
async def get_intelligent_publish_plan(body: IntelligentPublishIn, session: AsyncSession = Depends(get_session)):
    try:
        plan_inputs = await _load_intelligent_publish_inputs(
            folder_path=body.folder_path,
            creator_profile_id=body.creator_profile_id,
            session=session,
            materialize_job=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    existing_attempts = await _list_existing_intelligent_publish_attempts(session, plan_inputs["job"])
    return build_publication_plan(
        job=plan_inputs["job"],
        render_output=plan_inputs["render_output"],
        platform_packaging=plan_inputs["packaging"],
        creator_profile=plan_inputs["creator_profile"],
        requested_platforms=body.platforms,
        platform_options=body.platform_options,
        existing_attempts=existing_attempts,
    )


@router.post("/publication/publish")
async def publish_intelligent_folder(body: IntelligentPublishIn, session: AsyncSession = Depends(get_session)):
    try:
        plan_inputs = await _load_intelligent_publish_inputs(
            folder_path=body.folder_path,
            creator_profile_id=body.creator_profile_id,
            session=session,
            materialize_job=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    plan = build_publication_plan(
        job=plan_inputs["job"],
        render_output=plan_inputs["render_output"],
        platform_packaging=plan_inputs["packaging"],
        creator_profile=plan_inputs["creator_profile"],
        requested_platforms=body.platforms,
        platform_options=body.platform_options,
        existing_attempts=await list_publication_attempts(session, job_id=str(plan_inputs["job"].id)),
    )
    if not plan.get("publish_ready"):
        return plan
    result = await submit_publication_attempts(session, plan)
    await session.commit()
    _dispatch_publication_worker_tick(len(result.get("created_attempts") or []))
    return result


@router.post("/open-folder", response_model=OpenFolderOut)
def open_folder(body: IntelligentCopyInspectIn):
    target_path = Path(str(body.folder_path or "").strip()).expanduser()
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="目录不存在。")
    try:
        _open_in_file_manager(target_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"打开文件夹失败：{exc}") from exc
    kind = "file" if target_path.is_file() else "folder"
    return OpenFolderOut(path=str(target_path.resolve()), kind=kind)


def _open_in_file_manager(target_path: Path) -> None:
    resolved = target_path.resolve()
    if resolved.is_file():
        subprocess.Popen(["explorer", "/select,", str(resolved)])
        return
    subprocess.Popen(["explorer", str(resolved)])


async def _load_intelligent_publish_inputs(
    *,
    folder_path: str,
    creator_profile_id: str | None,
    session: AsyncSession,
    materialize_job: bool,
) -> dict[str, Any]:
    inspection = inspect_intelligent_copy_folder(folder_path)
    video_path = Path(str(inspection.get("video_file") or ""))
    if not video_path.exists() or not video_path.is_file():
        raise ValueError("目录内未找到可用成片视频。")
    packaging = _load_intelligent_copy_packaging(Path(str(inspection["folder_path"])))
    creator_profile = _resolve_intelligent_publish_creator_profile(creator_profile_id)
    if materialize_job:
        job = await _get_or_create_intelligent_publish_job(session, video_path=video_path, folder_path=Path(str(inspection["folder_path"])))
        render_output = await _get_or_create_intelligent_publish_render_output(session, job=job, video_path=video_path)
    else:
        job = await _find_existing_intelligent_publish_job(session, video_path=video_path)
        if job is None:
            job = SimpleNamespace(
                id=uuid.uuid5(uuid.NAMESPACE_URL, f"roughcut:intelligent-publish:{video_path.resolve()}"),
                status="done",
                source_name=video_path.name,
            )
        render_output = SimpleNamespace(output_path=str(video_path.resolve()))
    return {
        "job": job,
        "render_output": render_output,
        "packaging": packaging,
        "creator_profile": creator_profile,
    }


def _load_intelligent_copy_packaging(folder_path: Path) -> dict[str, Any] | None:
    json_path = folder_path / "smart-copy" / "smart-copy.json"
    if not json_path.exists():
        return None
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    platforms: dict[str, dict[str, Any]] = {}
    for item in payload.get("platforms") if isinstance(payload.get("platforms"), list) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        platforms[key] = {
            "titles": [str(title).strip() for title in (item.get("titles") or []) if str(title).strip()],
            "primary_title": str(item.get("primary_title") or "").strip(),
            "description": str(item.get("body") or "").strip(),
            "body": str(item.get("body") or "").strip(),
            "tags": [str(tag).strip().lstrip("#") for tag in (item.get("tags") or []) if str(tag).strip()],
        }
    if not platforms:
        return None
    return {"platforms": platforms, "source": "intelligent_publish", "material_dir": str(folder_path / "smart-copy")}


def _resolve_intelligent_publish_creator_profile(creator_profile_id: str | None) -> dict[str, Any] | None:
    profile_id = str(creator_profile_id or "").strip()
    if profile_id:
        try:
            return get_avatar_material_profile(profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Creator profile not found") from exc
    profiles = list_avatar_material_profiles()
    return next((profile for profile in profiles if active_publication_credentials(profile)), profiles[0] if profiles else None)


async def _find_existing_intelligent_publish_job(session: AsyncSession, *, video_path: Path) -> Job | None:
    result = await session.execute(
        select(Job)
        .where(Job.source_path == str(video_path.resolve()), Job.status == "done")
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_or_create_intelligent_publish_job(session: AsyncSession, *, video_path: Path, folder_path: Path) -> Job:
    existing = await _find_existing_intelligent_publish_job(session, video_path=video_path)
    if existing is not None:
        return existing
    job = Job(
        source_path=str(video_path.resolve()),
        source_name=video_path.name,
        status="done",
        workflow_template="intelligent_publish",
        output_dir=str(folder_path.resolve()),
        job_flow_mode="auto",
        workflow_mode="standard_edit",
        language="zh-CN",
    )
    session.add(job)
    await session.flush()
    return job


async def _get_or_create_intelligent_publish_render_output(
    session: AsyncSession,
    *,
    job: Job,
    video_path: Path,
) -> RenderOutput:
    resolved_video_path = str(video_path.resolve())
    result = await session.execute(
        select(RenderOutput)
        .where(RenderOutput.job_id == job.id, RenderOutput.output_path == resolved_video_path, RenderOutput.status == "done")
        .order_by(RenderOutput.created_at.desc())
        .limit(1)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        return existing
    render_output = RenderOutput(job_id=job.id, output_path=resolved_video_path, status="done", progress=1.0)
    session.add(render_output)
    await session.flush()
    return render_output


async def _list_existing_intelligent_publish_attempts(session: AsyncSession, job: Any) -> list[dict[str, Any]]:
    if not isinstance(job, Job):
        return []
    return await list_publication_attempts(session, job_id=str(job.id))


def _dispatch_publication_worker_tick(created_count: int) -> None:
    if created_count <= 0:
        return
    try:
        celery_app.send_task(
            "roughcut.pipeline.tasks.publication_worker_tick",
            kwargs={"limit": max(1, min(20, int(created_count)))},
            queue="publication_queue",
        )
    except Exception:
        pass
