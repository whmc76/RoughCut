from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.api.schemas import (
    IntelligentCopyGenerateIn,
    IntelligentCopyInspectIn,
    IntelligentCopyInspectOut,
    IntelligentCopyImagegenCompleteIn,
    IntelligentCopyImagegenRequestListOut,
    IntelligentCopyPathSuggestIn,
    IntelligentCopyPathSuggestOut,
    IntelligentCopyPathSuggestionOut,
    IntelligentPublishIn,
    IntelligentPublishSchemeIn,
    IntelligentPublishSchemeModifyIn,
    IntelligentCopyGenerateTaskListOut,
    IntelligentCopyGenerateTaskOut,
    IntelligentCopyResultOut,
    OpenFolderOut,
)
from roughcut.avatar import get_avatar_material_profile, list_avatar_material_profiles
from roughcut.config import get_settings
from roughcut.db.models import Job, RenderOutput
from roughcut.db.session import get_session
from roughcut.pipeline.celery_app import celery_app
from roughcut.publication import (
    active_publication_credentials,
    build_publication_plan,
    check_publication_browser_agent_ready,
    list_publication_attempts,
    submit_publication_attempts,
)
from roughcut.publication_intelligence import generate_publication_scheme, modify_publication_scheme
from roughcut.providers.image_generation import mark_codex_imagegen_request_completed
from roughcut.review.intelligent_copy import generate_intelligent_copy, inspect_intelligent_copy_folder

router = APIRouter(prefix="/intelligent-copy", tags=["intelligent-copy"])
_GENERATION_TASKS: dict[str, asyncio.Task] = {}
_GENERATION_TASK_STORE_LOCK = RLock()
_GENERATION_TASK_STORE_PATH = Path("data/intelligent_copy/generation_tasks.json")
_GENERATION_TASK_HISTORY_LIMIT = 30


@router.post("/inspect", response_model=IntelligentCopyInspectOut)
def inspect_folder(body: IntelligentCopyInspectIn):
    try:
        return inspect_intelligent_copy_folder(body.folder_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/path-suggestions", response_model=IntelligentCopyPathSuggestOut)
def suggest_folder_paths(body: IntelligentCopyPathSuggestIn):
    return IntelligentCopyPathSuggestOut(suggestions=suggest_directory_paths(body.query, limit=body.limit))


@router.post("/generate", response_model=IntelligentCopyResultOut)
async def generate_folder_materials(body: IntelligentCopyGenerateIn):
    try:
        return await generate_intelligent_copy(
            body.folder_path,
            copy_style=body.copy_style,
            platforms=body.platforms,
            use_existing_cover=body.use_existing_cover,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/generate-tasks", response_model=IntelligentCopyGenerateTaskOut)
async def create_generate_task(body: IntelligentCopyGenerateIn):
    try:
        inspection = inspect_intelligent_copy_folder(body.folder_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    folder_path = str(inspection["folder_path"])
    requested_platforms = _normalize_generation_platforms(body.platforms)
    active_task = _find_active_generation_task(
        folder_path=folder_path,
        copy_style=body.copy_style,
        platforms=requested_platforms,
        use_existing_cover=body.use_existing_cover,
    )
    if active_task is not None:
        return active_task

    task_id = uuid.uuid4().hex
    now = _now_iso()
    task = {
        "id": task_id,
        "folder_path": folder_path,
        "copy_style": str(body.copy_style or "").strip() or None,
        "use_existing_cover": bool(body.use_existing_cover),
        "platforms": requested_platforms,
        "status": "queued",
        "progress": 0,
        "stage": "queued",
        "message": "任务已创建，等待开始生成物料。",
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
        "material_dir": str(inspection.get("material_dir") or ""),
        "error": None,
        "inspection": inspection,
        "partial_result": None,
        "result": None,
    }
    _upsert_generation_task(task)
    _schedule_generation_task(
        task_id,
        folder_path=folder_path,
        copy_style=body.copy_style,
        platforms=requested_platforms,
        use_existing_cover=body.use_existing_cover,
    )
    return _get_generation_task(task_id) or task


@router.get("/generate-tasks/recent", response_model=IntelligentCopyGenerateTaskListOut)
async def list_recent_generate_tasks(limit: int = 12):
    _mark_stale_generation_tasks()
    safe_limit = max(1, min(int(limit or 12), _GENERATION_TASK_HISTORY_LIMIT))
    tasks = sorted(
        _load_generation_tasks(),
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )
    return {"tasks": tasks[:safe_limit]}


@router.get("/generate-tasks/{task_id}", response_model=IntelligentCopyGenerateTaskOut)
async def get_generate_task(task_id: str):
    task = _get_generation_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="生成任务不存在。")
    if task.get("status") in {"queued", "running"} and task_id not in _GENERATION_TASKS:
        task = _mark_generation_task_failed(task_id, "生成任务已中断，请重新生成。") or task
    return task


@router.post("/imagegen-requests", response_model=IntelligentCopyImagegenRequestListOut)
def list_imagegen_requests(body: IntelligentCopyInspectIn):
    try:
        inspection = inspect_intelligent_copy_folder(body.folder_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    material_dir = Path(str(inspection.get("material_dir") or ""))
    return {
        "folder_path": str(inspection.get("folder_path") or ""),
        "material_dir": str(material_dir),
        "requests": _list_codex_imagegen_requests(material_dir),
    }


@router.post("/imagegen-requests/complete", response_model=IntelligentCopyImagegenRequestListOut)
def complete_imagegen_request(body: IntelligentCopyImagegenCompleteIn):
    try:
        inspection = inspect_intelligent_copy_folder(body.folder_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    material_dir = Path(str(inspection.get("material_dir") or ""))
    request_path = _resolve_material_child_path(material_dir, body.request_path)
    result_path = Path(str(body.result_path or "")).expanduser()
    if not result_path.exists() or not result_path.is_file():
        raise HTTPException(status_code=400, detail="Codex 生成图片不存在。")
    try:
        payload = json.loads(request_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="图像生成请求 JSON 无法读取。") from exc
    output_path = Path(str(payload.get("output_path") or "")).expanduser()
    if not output_path.is_absolute():
        output_path = material_dir / output_path
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result_path, output_path)
        mark_codex_imagegen_request_completed(request_path=request_path, output_path=output_path, result_path=result_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"标记 Codex 图像生成完成失败：{exc}") from exc
    return {
        "folder_path": str(inspection.get("folder_path") or ""),
        "material_dir": str(material_dir),
        "requests": _list_codex_imagegen_requests(material_dir),
    }


@router.get("/publication/attempts/recent")
async def list_recent_publication_attempts(
    limit: int = 24,
    creator_profile_id: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    safe_limit = max(1, min(int(limit or 24), 100))
    attempts = await list_publication_attempts(
        session,
        creator_profile_id=str(creator_profile_id or "").strip() or None,
        limit=safe_limit,
    )
    return {"attempts": attempts}


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


@router.post("/publication/scheme")
async def get_intelligent_publish_scheme(body: IntelligentPublishSchemeIn, session: AsyncSession = Depends(get_session)):
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
    plan = build_publication_plan(
        job=plan_inputs["job"],
        render_output=plan_inputs["render_output"],
        platform_packaging=plan_inputs["packaging"],
        creator_profile=plan_inputs["creator_profile"],
        requested_platforms=body.platforms,
        platform_options=body.platform_options,
        existing_attempts=existing_attempts,
    )
    if not plan.get("publish_ready"):
        return {
            "status": "blocked",
            "blocked_reasons": plan.get("blocked_reasons") or ["当前物料或账号暂不满足发布条件。"],
            "warnings": plan.get("warnings") or [],
            "platform_options": {},
            "items": [],
            "plan": plan,
        }
    scheme = await generate_publication_scheme(
        plan=plan,
        creator_profile=plan_inputs["creator_profile"],
        folder_path=str(body.folder_path or ""),
        browser=body.browser,
        force_probe=body.force_probe,
    )
    scheme["plan"] = plan
    return scheme


@router.post("/publication/scheme/modify")
async def modify_intelligent_publish_scheme(body: IntelligentPublishSchemeModifyIn):
    return await modify_publication_scheme(scheme=body.scheme, instruction=body.instruction)


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
    settings = get_settings()
    agent_ready = await check_publication_browser_agent_ready(
        browser_agent_base_url=str(getattr(settings, "publication_browser_agent_base_url", "") or ""),
        auth_token=str(getattr(settings, "publication_browser_agent_auth_token", "") or ""),
        target_platforms=[str(target.get("platform") or "") for target in (plan.get("targets") or []) if isinstance(target, dict)],
        request_timeout_sec=max(5, int(getattr(settings, "publication_browser_agent_timeout_sec", 60) or 60)),
    )
    if not agent_ready.get("ready"):
        return {
            **plan,
            "status": "blocked",
            "publish_ready": False,
            "blocked_reasons": [*(plan.get("blocked_reasons") or []), str(agent_ready.get("message") or "browser-agent 不支持正式发布。")],
            "publication_executor_preflight": agent_ready,
            "created_attempts": [],
        }
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_generation_tasks() -> list[dict[str, Any]]:
    with _GENERATION_TASK_STORE_LOCK:
        try:
            payload = json.loads(_GENERATION_TASK_STORE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
        tasks = payload.get("tasks") if isinstance(payload, dict) else payload
        if not isinstance(tasks, list):
            return []
        return [item for item in tasks if isinstance(item, dict) and str(item.get("id") or "").strip()]


def _save_generation_tasks(tasks: list[dict[str, Any]]) -> None:
    with _GENERATION_TASK_STORE_LOCK:
        _GENERATION_TASK_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        pruned = sorted(
            tasks,
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        )[:_GENERATION_TASK_HISTORY_LIMIT]
        _GENERATION_TASK_STORE_PATH.write_text(
            json.dumps({"tasks": pruned}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _upsert_generation_task(task: dict[str, Any]) -> None:
    tasks = _load_generation_tasks()
    task_id = str(task.get("id") or "").strip()
    next_tasks = [item for item in tasks if str(item.get("id") or "") != task_id]
    next_tasks.insert(0, task)
    _save_generation_tasks(next_tasks)


def _patch_generation_task(task_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    tasks = _load_generation_tasks()
    updated_task: dict[str, Any] | None = None
    now = _now_iso()
    for item in tasks:
        if str(item.get("id") or "") == task_id:
            item.update(patch)
            item["updated_at"] = now
            updated_task = item
            break
    if updated_task is not None:
        _save_generation_tasks(tasks)
    return updated_task


def _get_generation_task(task_id: str) -> dict[str, Any] | None:
    normalized = str(task_id or "").strip()
    return next((item for item in _load_generation_tasks() if str(item.get("id") or "") == normalized), None)


def _list_codex_imagegen_requests(material_dir: Path) -> list[dict[str, Any]]:
    if not material_dir.exists() or not material_dir.is_dir():
        return []
    requests: list[dict[str, Any]] = []
    for path in sorted(material_dir.glob("*.codex-imagegen.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            requests.append(
                {
                    "request_path": str(path),
                    "status": "invalid",
                    "error": str(exc),
                }
            )
            continue
        payload = payload if isinstance(payload, dict) else {}
        requests.append(
            {
                "request_path": str(path),
                "status": str(payload.get("status") or "pending_codex_imagegen"),
                "backend": str(payload.get("backend") or ""),
                "source_image_path": str(payload.get("source_image_path") or ""),
                "output_path": str(payload.get("output_path") or ""),
                "target_size": payload.get("target_size") if isinstance(payload.get("target_size"), dict) else {},
                "created_at": str(payload.get("created_at") or ""),
                "completed_at": str(payload.get("completed_at") or "") or None,
                "error": str(payload.get("error") or "") or None,
            }
        )
    return requests


def _resolve_material_child_path(material_dir: Path, raw_path: str) -> Path:
    raw = str(raw_path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="缺少请求文件路径。")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = material_dir / path
    try:
        resolved = path.resolve()
        material_root = material_dir.resolve()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="请求文件路径无效。") from exc
    if material_root != resolved and material_root not in resolved.parents:
        raise HTTPException(status_code=400, detail="请求文件必须位于 smart-copy 目录内。")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="图像生成请求不存在。")
    if resolved.suffix.lower() != ".json" or not resolved.name.endswith(".codex-imagegen.json"):
        raise HTTPException(status_code=400, detail="不是 Codex imagegen 请求文件。")
    return resolved


def _normalize_generation_platforms(platforms: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for platform in platforms or []:
        item = str(platform or "").strip()
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _find_active_generation_task(
    *,
    folder_path: str,
    copy_style: str | None,
    platforms: list[str] | None,
    use_existing_cover: bool,
) -> dict[str, Any] | None:
    normalized_style = str(copy_style or "").strip()
    normalized_platforms = _normalize_generation_platforms(platforms)
    for item in _load_generation_tasks():
        task_id = str(item.get("id") or "")
        if item.get("folder_path") != folder_path:
            continue
        if str(item.get("copy_style") or "").strip() != normalized_style:
            continue
        if _normalize_generation_platforms(item.get("platforms") or []) != normalized_platforms:
            continue
        if bool(item.get("use_existing_cover")) != bool(use_existing_cover):
            continue
        if item.get("status") in {"queued", "running"} and task_id in _GENERATION_TASKS:
            return item
    return None


def _mark_generation_task_failed(task_id: str, error: str) -> dict[str, Any] | None:
    return _patch_generation_task(
        task_id,
        {
            "status": "failed",
            "progress": 100,
            "stage": "failed",
            "message": "生成任务失败。",
            "completed_at": _now_iso(),
            "error": error,
        },
    )


def _mark_stale_generation_tasks() -> None:
    for item in _load_generation_tasks():
        task_id = str(item.get("id") or "")
        if item.get("status") in {"queued", "running"} and task_id not in _GENERATION_TASKS:
            _mark_generation_task_failed(task_id, "生成任务已中断，请重新生成。")


def _schedule_generation_task(
    task_id: str,
    *,
    folder_path: str,
    copy_style: str | None,
    platforms: list[str] | None,
    use_existing_cover: bool,
) -> None:
    async def runner() -> None:
        await asyncio.to_thread(_run_generation_task_thread, task_id, folder_path, copy_style, platforms, use_existing_cover)

    _GENERATION_TASKS[task_id] = asyncio.create_task(runner())


def _run_generation_task_thread(
    task_id: str,
    folder_path: str,
    copy_style: str | None,
    platforms: list[str] | None,
    use_existing_cover: bool,
) -> None:
    asyncio.run(
        _run_generation_task(
            task_id,
            folder_path=folder_path,
            copy_style=copy_style,
            platforms=platforms,
            use_existing_cover=use_existing_cover,
        )
    )


async def _run_generation_task(
    task_id: str,
    *,
    folder_path: str,
    copy_style: str | None,
    platforms: list[str] | None,
    use_existing_cover: bool,
) -> None:
    try:
        _patch_generation_task(
            task_id,
            {
                "status": "running",
                "progress": 2,
                "stage": "starting",
                "message": "开始生成物料。",
                "started_at": _now_iso(),
                "error": None,
            },
        )

        async def progress_callback(update: dict[str, Any]) -> None:
            patch: dict[str, Any] = {
                "status": "running",
                "progress": max(0, min(99, int(update.get("progress") or 0))),
                "stage": str(update.get("stage") or "running"),
                "message": str(update.get("message") or ""),
            }
            for key in ("folder_path", "material_dir", "inspection", "partial_result"):
                if key in update:
                    patch[key] = update[key]
            _patch_generation_task(task_id, patch)

        result = await generate_intelligent_copy(
            folder_path,
            copy_style=copy_style,
            platforms=platforms,
            use_existing_cover=use_existing_cover,
            progress_callback=progress_callback,
        )
        publish_ready = bool(result.get("publish_ready"))
        blocking_reasons = [str(item).strip() for item in (result.get("blocking_reasons") or []) if str(item).strip()]
        _patch_generation_task(
            task_id,
            {
                "status": "completed" if publish_ready else "blocked",
                "progress": 100,
                "stage": "completed" if publish_ready else "blocked",
                "message": "物料生成完成。" if publish_ready else "物料生成完成，但仍有阻断项，不能发布。",
                "completed_at": _now_iso(),
                "material_dir": str(result.get("material_dir") or ""),
                "inspection": result.get("inspection"),
                "partial_result": result,
                "result": result,
                "error": None if publish_ready else "；".join(blocking_reasons[:5]),
            },
        )
    except Exception as exc:
        _mark_generation_task_failed(task_id, str(exc))
    finally:
        _GENERATION_TASKS.pop(task_id, None)


def suggest_directory_paths(query: str, *, limit: int = 12) -> list[IntelligentCopyPathSuggestionOut]:
    raw_query = str(query or "").strip().strip('"')
    safe_limit = max(1, min(int(limit or 12), 30))
    if not raw_query:
        return []

    base_dir, prefix = _split_directory_suggestion_query(raw_query)
    if base_dir is None:
        return []

    try:
        if not base_dir.exists() or not base_dir.is_dir():
            return []
    except OSError:
        return []

    prefix_lower = prefix.casefold()
    starts_with: list[Path] = []
    contains: list[Path] = []
    try:
        with os.scandir(base_dir) as entries:
            for entry in entries:
                try:
                    if not entry.is_dir():
                        continue
                except OSError:
                    continue
                name_lower = entry.name.casefold()
                if not prefix_lower or name_lower.startswith(prefix_lower):
                    starts_with.append(Path(entry.path))
                elif prefix_lower in name_lower:
                    contains.append(Path(entry.path))
    except OSError:
        return []

    suggestions: list[IntelligentCopyPathSuggestionOut] = []
    for item in sorted(starts_with, key=lambda path: path.name.casefold()) + sorted(contains, key=lambda path: path.name.casefold()):
        try:
            resolved = item.resolve()
        except OSError:
            resolved = item.absolute()
        suggestions.append(
            IntelligentCopyPathSuggestionOut(
                path=str(resolved),
                label=item.name,
                parent=str(base_dir),
            )
        )
        if len(suggestions) >= safe_limit:
            break
    return suggestions


def _split_directory_suggestion_query(raw_query: str) -> tuple[Path | None, str]:
    drive_match = re.fullmatch(r"([A-Za-z]):", raw_query)
    if drive_match:
        return Path(f"{drive_match.group(1)}:\\"), ""

    query_path = Path(raw_query).expanduser()
    has_trailing_separator = raw_query.endswith(("\\", "/"))
    try:
        if has_trailing_separator or (query_path.exists() and query_path.is_dir()):
            return query_path, ""
    except OSError:
        pass

    parent = query_path.parent
    if str(parent) == "":
        return None, ""
    return parent, query_path.name


async def _load_intelligent_publish_inputs(
    *,
    folder_path: str,
    creator_profile_id: str | None,
    session: AsyncSession,
    materialize_job: bool,
) -> dict[str, Any]:
    task_snapshot: dict[str, Any] | None = None
    try:
        inspection = inspect_intelligent_copy_folder(folder_path)
    except ValueError:
        task_snapshot = _find_generation_task_snapshot(folder_path)
        inspection = _inspection_from_generation_task_snapshot(task_snapshot)
        if inspection is None:
            raise
    video_path = Path(str(inspection.get("video_file") or ""))
    video_path_raw = str(inspection.get("video_file") or "").strip()
    if not _is_publish_media_path_usable(video_path_raw):
        raise ValueError("目录内未找到可用成片视频。")
    packaging = _load_intelligent_copy_packaging(Path(str(inspection["folder_path"])))
    if packaging is None and task_snapshot is not None:
        packaging = _load_intelligent_copy_packaging_from_task_snapshot(task_snapshot)
    creator_profile = _resolve_intelligent_publish_creator_profile(creator_profile_id)
    if materialize_job:
        job = await _get_or_create_intelligent_publish_job(session, video_path=video_path, folder_path=Path(str(inspection["folder_path"])))
        render_output = await _get_or_create_intelligent_publish_render_output(session, job=job, video_path=video_path)
    else:
        job = await _find_existing_intelligent_publish_job(session, video_path=video_path)
        if job is None:
            job = SimpleNamespace(
                id=uuid.uuid5(uuid.NAMESPACE_URL, f"roughcut:intelligent-publish:{_stable_publish_path(video_path)}"),
                status="done",
                source_name=video_path.name,
            )
        render_output = SimpleNamespace(output_path=_stable_publish_path(video_path))
    return {
        "job": job,
        "render_output": render_output,
        "packaging": packaging,
        "creator_profile": creator_profile,
    }


def _is_publish_media_path_usable(raw_path: str) -> bool:
    raw = str(raw_path or "").strip()
    if not raw:
        return False
    path = Path(raw)
    try:
        if path.exists() and path.is_file():
            return True
    except OSError:
        pass
    return raw.startswith("\\\\") or raw.startswith("//")


def _stable_publish_path(path: Path) -> str:
    try:
        if path.exists():
            return str(path.resolve())
    except OSError:
        pass
    return str(path)


def _find_generation_task_snapshot(folder_path: str) -> dict[str, Any] | None:
    requested = _normalize_publish_folder_key(folder_path)
    candidates = sorted(
        _load_generation_tasks(),
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )
    for task in candidates:
        if _normalize_publish_folder_key(task.get("folder_path")) == requested:
            return task
        inspection = task.get("inspection") if isinstance(task.get("inspection"), dict) else {}
        if _normalize_publish_folder_key(inspection.get("folder_path")) == requested:
            return task
        material = task.get("result") if isinstance(task.get("result"), dict) else task.get("partial_result")
        material = material if isinstance(material, dict) else {}
        if _normalize_publish_folder_key(material.get("folder_path")) == requested:
            return task
    return None


def _normalize_publish_folder_key(value: Any) -> str:
    return re.sub(r"[\\/]+$", "", str(value or "").strip()).lower()


def _inspection_from_generation_task_snapshot(task: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(task, dict):
        return None
    inspection = task.get("inspection") if isinstance(task.get("inspection"), dict) else None
    if inspection and inspection.get("folder_path") and inspection.get("video_file"):
        return inspection
    for key in ("result", "partial_result"):
        material = task.get(key) if isinstance(task.get(key), dict) else None
        material_inspection = material.get("inspection") if isinstance(material, dict) and isinstance(material.get("inspection"), dict) else None
        if material_inspection and material_inspection.get("folder_path") and material_inspection.get("video_file"):
            return material_inspection
    return None


def _load_intelligent_copy_packaging_from_task_snapshot(task: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("result", "partial_result"):
        material = task.get(key) if isinstance(task.get(key), dict) else None
        if not material:
            continue
        packaging = _normalize_intelligent_copy_payload_as_packaging(material)
        if packaging:
            return packaging
    return None


def _load_intelligent_copy_packaging(folder_path: Path) -> dict[str, Any] | None:
    json_path = folder_path / "smart-copy" / "smart-copy.json"
    if not json_path.exists():
        return None
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return _normalize_intelligent_copy_payload_as_packaging(payload, material_dir=str(folder_path / "smart-copy"))


def _normalize_intelligent_copy_payload_as_packaging(payload: dict[str, Any], material_dir: str | None = None) -> dict[str, Any] | None:
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
            "cover_path": str(item.get("cover_path") or "").strip(),
            "publish_ready": bool(item.get("publish_ready", True)),
            "blocking_reasons": [str(reason).strip() for reason in (item.get("blocking_reasons") or []) if str(reason).strip()],
        }
    if not platforms:
        return None
    return {
        "platforms": platforms,
        "source": "intelligent_publish",
        "material_dir": str(material_dir or payload.get("material_dir") or ""),
        "publish_ready": bool(payload.get("publish_ready", False)),
        "blocking_reasons": [str(reason).strip() for reason in (payload.get("blocking_reasons") or []) if str(reason).strip()],
    }


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
        .where(Job.source_path == _stable_publish_path(video_path), Job.status == "done")
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_or_create_intelligent_publish_job(session: AsyncSession, *, video_path: Path, folder_path: Path) -> Job:
    existing = await _find_existing_intelligent_publish_job(session, video_path=video_path)
    if existing is not None:
        return existing
    job = Job(
        source_path=_stable_publish_path(video_path),
        source_name=video_path.name,
        status="done",
        workflow_template="intelligent_publish",
        output_dir=_stable_publish_path(folder_path),
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
    resolved_video_path = _stable_publish_path(video_path)
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
