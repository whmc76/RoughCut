from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import traceback
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path
from threading import RLock
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from roughcut.api.schemas import (
    IntelligentCopyGenerateIn,
    IntelligentCopyUpgradeIn,
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
from roughcut.host.codex_proxy import resolve_codex_proxy_sibling_url, resolve_codex_proxy_token
from roughcut.db.models import CreatorCard, CreatorPublicationProfile, Job, RenderOutput
from roughcut.db.session import get_session
from roughcut.host.file_manager import can_open_in_file_manager, describe_file_manager_target, open_in_file_manager
from roughcut.intelligent_copy_layout import (
    resolve_smart_copy_material_json_path,
    resolve_smart_copy_platform_packaging_json_path,
    smart_copy_cover_dir,
)
from roughcut.media.probe import probe as probe_media
from roughcut.media.probe import publication_upload_compatibility
from roughcut.pipeline.celery_app import celery_app
from roughcut.publication import (
    active_publication_credentials,
    build_publication_plan,
    check_publication_browser_agent_ready,
    list_publication_attempts,
    publication_adapter_requires_browser_agent,
    publication_plan_is_publishable,
    publication_plan_is_manual_handoff_ready,
    publication_plan_status,
    reconcile_publication_attempt_from_browser_agent_payload,
    resolve_publication_local_cover_path,
    submit_publication_attempts,
)
from roughcut.publication_packaging import (
    load_publication_packaging_payload,
    normalize_publication_packaging_payload,
)
from roughcut.publication_intelligence import generate_publication_scheme, modify_publication_scheme
from roughcut.providers.image_generation import (
    codex_imagegen_result_path_is_allowed,
    mark_codex_imagegen_request_completed,
)
from roughcut.review.intelligent_copy import (
    generate_intelligent_copy,
    inspect_intelligent_copy_folder,
    rerender_existing_intelligent_copy_cover_groups,
    upgrade_existing_intelligent_copy_result,
)

router = APIRouter(prefix="/intelligent-copy", tags=["intelligent-copy"])
logger = logging.getLogger(__name__)
_GENERATION_TASKS: dict[str, asyncio.Task] = {}
_GENERATION_TASK_STORE_LOCK = RLock()
_GENERATION_TASK_STORE_PATH = Path("data/intelligent_copy/generation_tasks.json")
_GENERATION_TASK_HISTORY_LIMIT = 30
_GENERATION_TASK_STALE_AFTER_SECONDS = 6 * 60 * 60
_GENERATION_TASK_ORPHAN_GRACE_SECONDS = 45
_LOCAL_IMAGE_ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_LOCAL_IMAGE_MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
_PUBLICATION_COVER_AUTO_HEAL_BLOCK_TOKENS = (
    "封面",
    "cover",
    "codex",
    "imagegen",
    "位图",
    "bitmap",
)


def _build_publication_plan_gate_response(plan: dict[str, Any], **extra: Any) -> dict[str, Any]:
    plan_status = publication_plan_status(plan)
    response = {
        "status": "manual_handoff" if plan_status == "manual_handoff" else "blocked",
        "publish_ready": False,
        "blocked_reasons": plan.get("blocked_reasons") or ["当前物料或账号暂不满足发布条件。"],
        "warnings": plan.get("warnings") or [],
        "manual_handoff_ready": publication_plan_is_manual_handoff_ready(plan),
        "manual_handoff_targets": plan.get("manual_handoff_targets") or [],
        "platform_options": {},
        "items": [],
        "plan": plan,
    }
    response.update(extra)
    return response


def _build_publication_executor_gate_response(
    plan: dict[str, Any],
    *,
    blocked_reasons: list[str] | None = None,
    publication_executor_preflight: dict[str, Any] | None = None,
    created_attempts: list[Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    gated_plan = dict(plan)
    if blocked_reasons is not None:
        gated_plan["blocked_reasons"] = [str(item).strip() for item in blocked_reasons if str(item).strip()]
    response = _build_publication_plan_gate_response(gated_plan)
    response["created_attempts"] = list(created_attempts or [])
    if publication_executor_preflight is not None:
        response["publication_executor_preflight"] = publication_executor_preflight
    response.update(extra)
    return response


def _material_contract_status(result_contract: dict[str, Any]) -> str:
    if not isinstance(result_contract, dict):
        return ""
    status = str(result_contract.get("status") or "").strip().lower()
    if status in {"passed", "manual_handoff", "failed", "blocked"}:
        return status
    platform_contracts = result_contract.get("platforms") if isinstance(result_contract.get("platforms"), dict) else {}
    has_root_blocking_reasons = bool(
        [str(item).strip() for item in (result_contract.get("blocking_reasons") or []) if str(item).strip()]
    )
    has_manual_handoff_platforms = bool(result_contract.get("manual_handoff_platforms"))
    if platform_contracts:
        platform_statuses = {
            str(item.get("status") or "").strip().lower()
            for item in platform_contracts.values()
            if isinstance(item, dict) and str(item.get("status") or "").strip()
        }
        if "failed" in platform_statuses or "blocked" in platform_statuses:
            return "failed"
        if "manual_handoff" in platform_statuses:
            return "manual_handoff"
        if any(
            bool(item.get("manual_handoff_only"))
            for item in platform_contracts.values()
            if isinstance(item, dict)
        ):
            return "manual_handoff"
        if platform_statuses and platform_statuses <= {"passed"}:
            return "passed"
    if has_manual_handoff_platforms and bool(result_contract.get("one_click_publish_ready")):
        return "manual_handoff"
    if has_root_blocking_reasons:
        return "failed"
    if has_manual_handoff_platforms:
        return "manual_handoff"
    return ""


def _derive_generation_task_terminal_patch(result: dict[str, Any]) -> dict[str, Any]:
    material_generation_contract = (
        result.get("material_generation_contract")
        if isinstance(result.get("material_generation_contract"), dict)
        else {}
    )
    generation_contract_status = str(material_generation_contract.get("status") or "").strip().lower()
    generation_ready = (
        bool(material_generation_contract.get("generation_ready"))
        if material_generation_contract
        else bool(result.get("material_generation_ready"))
    )
    material_contract = result.get("material_contract") if isinstance(result.get("material_contract"), dict) else {}
    contract_status = _material_contract_status(material_contract)
    contract_present = bool(material_contract)
    contract_blocking_reasons = [
        str(item).strip()
        for item in (material_contract.get("blocking_reasons") or [])
        if str(item).strip()
    ]
    root_blocking_reasons = [
        str(item).strip()
        for item in (result.get("blocking_reasons") or [])
        if str(item).strip()
    ]
    blocking_reasons = list(dict.fromkeys([*contract_blocking_reasons, *root_blocking_reasons]))
    manual_handoff_targets = list(result.get("manual_handoff_targets") or material_contract.get("manual_handoff_platforms") or [])
    root_status = str(result.get("status") or "").strip().lower()
    manual_handoff_ready = (
        (contract_status == "manual_handoff")
        if contract_present
        else (
            bool(result.get("manual_handoff_ready"))
            or root_status == "manual_handoff"
            or bool(manual_handoff_targets)
        )
    )
    contract_publish_ready = (
        True
        if contract_status == "passed"
        else False
        if contract_status in {"manual_handoff", "failed", "blocked"}
        else bool(material_contract.get("one_click_publish_ready"))
    )
    publish_ready = (
        contract_publish_ready
        if contract_present
        else (
            False
            if manual_handoff_ready or blocking_reasons or root_status in {"blocked", "failed"}
            else bool(result.get("publish_ready"))
        )
    )
    if generation_ready and generation_contract_status in {"", "passed", "completed"} and not publish_ready and not manual_handoff_ready:
        message = "物料生成完成，但一键发布仍有阻断项。"
        if blocking_reasons:
            message = f"{message} 当前阻断：{'；'.join(blocking_reasons[:3])}。"
        return {
            "status": "completed",
            "stage": "completed",
            "message": message,
            "error": None,
        }
    if publish_ready:
        return {
            "status": "completed",
            "stage": "completed",
            "message": "物料生成完成。",
            "error": None,
        }
    if manual_handoff_ready:
        labels = [str(item.get("label") or item.get("platform") or "").strip() for item in manual_handoff_targets if isinstance(item, dict)]
        target_summary = "、".join([label for label in labels if label])
        message = "物料生成完成，部分平台需人工登录后继续发布。"
        if target_summary:
            message = f"{message} 需人工接管平台：{target_summary}。"
        return {
            "status": "manual_handoff",
            "stage": "manual_handoff",
            "message": message,
            "error": None,
        }
    return {
        "status": "blocked",
        "stage": "blocked",
        "message": "物料生成完成，但仍有阻断项，不能发布。",
        "error": "；".join(blocking_reasons[:5]) if blocking_reasons else "物料仍有阻断项。",
    }


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
    creator_profile = _resolve_generation_creator_profile(body.creator_profile_id)
    try:
        return await generate_intelligent_copy(
            body.folder_path,
            copy_style=body.copy_style,
            platforms=body.platforms,
            use_existing_cover=body.use_existing_cover,
            force_regenerate=body.force_regenerate,
            creator_profile_id=str(body.creator_profile_id or "").strip() or None,
            creator_profile_name=str((creator_profile or {}).get("display_name") or "").strip() or None,
            creator_profile=creator_profile,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/upgrade", response_model=IntelligentCopyResultOut)
async def upgrade_folder_materials(body: IntelligentCopyUpgradeIn):
    creator_profile = _resolve_generation_creator_profile(body.creator_profile_id)
    try:
        return upgrade_existing_intelligent_copy_result(
            body.folder_path,
            platforms=body.platforms,
            platform_options=body.platform_options,
            publication_scheme=body.publication_scheme,
            publication_scheme_path=str(body.publication_scheme_path or "").strip() or None,
            creator_profile_id=str(body.creator_profile_id or "").strip() or None,
            creator_profile_name=str((creator_profile or {}).get("display_name") or "").strip() or None,
            browser=str(body.browser or "chrome").strip() or "chrome",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/generate-tasks", response_model=IntelligentCopyGenerateTaskOut)
async def create_generate_task(body: IntelligentCopyGenerateIn):
    creator_profile = _resolve_generation_creator_profile(body.creator_profile_id)
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
        force_regenerate=body.force_regenerate,
        creator_profile_id=str(body.creator_profile_id or "").strip() or None,
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
        "force_regenerate": bool(body.force_regenerate),
        "platforms": requested_platforms,
        "creator_profile_id": str(body.creator_profile_id or "").strip() or None,
        "creator_profile_name": str((creator_profile or {}).get("display_name") or "").strip() or None,
        "status": "queued",
        "progress": 0,
        "stage": "queued",
        "message": "任务已创建，等待开始生成物料。",
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
        "worker_owner_pid": os.getpid(),
        "worker_claimed_at": None,
        "last_heartbeat_at": now,
        "worker_log_path": "",
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
        force_regenerate=body.force_regenerate,
        creator_profile_id=str(body.creator_profile_id or "").strip() or None,
        creator_profile_name=str((creator_profile or {}).get("display_name") or "").strip() or None,
    )
    return _get_generation_task(task_id) or task


@router.get("/generate-tasks/recent", response_model=IntelligentCopyGenerateTaskListOut)
async def list_recent_generate_tasks(limit: int = 12):
    _recover_generation_task_runtime_state()
    safe_limit = max(1, min(int(limit or 12), _GENERATION_TASK_HISTORY_LIMIT))
    tasks = _sorted_generation_tasks()
    return {"tasks": tasks[:safe_limit]}


@router.get("/generate-tasks/{task_id}", response_model=IntelligentCopyGenerateTaskOut)
async def get_generate_task(task_id: str):
    _recover_generation_task_runtime_state()
    task = _get_generation_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="生成任务不存在。")
    if task.get("status") in {"queued", "running"} and task_id not in _GENERATION_TASKS and _generation_task_is_stale(task):
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
    if not codex_imagegen_result_path_is_allowed(result_path, output_path=output_path):
        raise HTTPException(status_code=400, detail="Codex 生成图片路径不属于当前输出文件或 Codex generated_images 目录。")
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


@router.post("/publication/reconcile-task")
async def reconcile_publication_task_payload(
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
):
    result = await reconcile_publication_attempt_from_browser_agent_payload(session, payload)
    await session.commit()
    return result


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
    platform_options = await _resolve_intelligent_publish_platform_options(
        requested_platform_options=body.platform_options,
        plan_inputs=plan_inputs,
        requested_platforms=body.platforms,
        existing_attempts=existing_attempts,
        folder_path=body.folder_path,
    )
    return build_publication_plan(
        job=plan_inputs["job"],
        render_output=plan_inputs["render_output"],
        source_media_path=plan_inputs.get("source_video_path"),
        platform_packaging=plan_inputs["packaging"],
        creator_profile=plan_inputs["creator_profile"],
        requested_platforms=body.platforms,
        platform_options=platform_options,
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
    if not publication_plan_is_publishable(plan):
        return _build_publication_plan_gate_response(plan)
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
    existing_attempts = await list_publication_attempts(session, job_id=str(plan_inputs["job"].id))
    platform_options = await _resolve_intelligent_publish_platform_options(
        requested_platform_options=body.platform_options,
        plan_inputs=plan_inputs,
        requested_platforms=body.platforms,
        existing_attempts=existing_attempts,
        folder_path=body.folder_path,
    )
    plan = build_publication_plan(
        job=plan_inputs["job"],
        render_output=plan_inputs["render_output"],
        source_media_path=plan_inputs.get("source_video_path"),
        platform_packaging=plan_inputs["packaging"],
        creator_profile=plan_inputs["creator_profile"],
        requested_platforms=body.platforms,
        platform_options=platform_options,
        existing_attempts=existing_attempts,
    )
    plan, plan_inputs = await _maybe_auto_heal_publication_cover_plan(
        plan=plan,
        plan_inputs=plan_inputs,
        folder_path=body.folder_path,
        creator_profile_id=body.creator_profile_id,
        requested_platforms=body.platforms,
        platform_options=platform_options,
        existing_attempts=existing_attempts,
        session=session,
        materialize_job=True,
    )
    if not publication_plan_is_publishable(plan):
        return _build_publication_executor_gate_response(plan)
    browser_agent_targets = [
        target
        for target in (plan.get("targets") or [])
        if isinstance(target, dict) and publication_adapter_requires_browser_agent(target.get("adapter"))
    ]
    if browser_agent_targets:
        settings = get_settings()
        agent_ready = await check_publication_browser_agent_ready(
            browser_agent_base_url=str(getattr(settings, "publication_browser_agent_base_url", "") or ""),
            auth_token=str(getattr(settings, "publication_browser_agent_auth_token", "") or ""),
            target_platforms=[str(target.get("platform") or "") for target in browser_agent_targets],
            target_profile_ids=[
                str(target.get("browser_profile_id") or target.get("credential_ref") or "")
                for target in browser_agent_targets
            ],
            skip_creator_session_platforms=[
                str(target.get("platform") or "")
                for target in browser_agent_targets
                if str(target.get("platform") or "").strip().lower() == "youtube"
            ],
            request_timeout_sec=max(5, int(getattr(settings, "publication_browser_agent_timeout_sec", 60) or 60)),
        )
        if not agent_ready.get("ready"):
            return _build_publication_executor_gate_response(
                plan,
                blocked_reasons=[
                    *(plan.get("blocked_reasons") or []),
                    str(agent_ready.get("message") or "browser-agent 不支持正式发布。"),
                ],
                publication_executor_preflight=agent_ready,
            )
    result = await submit_publication_attempts(session, plan)
    await session.commit()
    _dispatch_publication_worker_tick(len(result.get("created_attempts") or []))
    return result


def _publication_plan_cover_auto_heal_reasons(plan: dict[str, Any] | None) -> list[str]:
    if not isinstance(plan, dict):
        return []
    candidates = [
        *[str(item).strip() for item in (plan.get("blocked_reasons") or []) if str(item).strip()],
        *[str(item).strip() for item in (plan.get("warnings") or []) if str(item).strip()],
    ]
    reasons: list[str] = []
    for reason in candidates:
        normalized = reason.lower()
        if any(token in normalized for token in _PUBLICATION_COVER_AUTO_HEAL_BLOCK_TOKENS):
            reasons.append(reason)
    return list(dict.fromkeys(reasons))


def _attach_cover_auto_heal_status(plan: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    updated = dict(plan)
    updated["cover_auto_heal"] = status
    status_kind = str(status.get("status") or "").strip().lower()
    if status_kind in {"failed", "needs_human"}:
        blocked_reasons = [str(item).strip() for item in (updated.get("blocked_reasons") or []) if str(item).strip()]
        summary = str(status.get("summary") or "封面自愈未能恢复发布计划，需人工处理。").strip()
        if summary and summary not in blocked_reasons:
            blocked_reasons.append(summary)
        updated["blocked_reasons"] = blocked_reasons
        updated["status"] = "blocked"
        updated["publish_ready"] = False
    return updated


async def _maybe_auto_heal_publication_cover_plan(
    *,
    plan: dict[str, Any],
    plan_inputs: dict[str, Any],
    folder_path: str,
    creator_profile_id: str | None,
    requested_platforms: list[str] | None,
    platform_options: dict[str, Any],
    existing_attempts: list[dict[str, Any]],
    session: AsyncSession,
    materialize_job: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    reasons = _publication_plan_cover_auto_heal_reasons(plan)
    if not reasons or publication_plan_is_publishable(plan):
        return plan, plan_inputs
    settings = get_settings()
    if not bool(getattr(settings, "publication_cover_auto_heal_enabled", True)):
        return plan, plan_inputs
    try:
        max_attempts = int(getattr(settings, "publication_cover_auto_heal_max_attempts", 1) or 1)
    except (TypeError, ValueError):
        max_attempts = 1
    max_attempts = max(0, min(3, max_attempts))
    if max_attempts <= 0:
        return plan, plan_inputs

    current_plan = plan
    current_inputs = plan_inputs
    attempts: list[dict[str, Any]] = []
    creator_profile = current_inputs.get("creator_profile") if isinstance(current_inputs, dict) else {}
    creator_profile_name = str((creator_profile or {}).get("display_name") or "").strip()
    for attempt_index in range(1, max_attempts + 1):
        before_reasons = _publication_plan_cover_auto_heal_reasons(current_plan)
        try:
            healed_result = await rerender_existing_intelligent_copy_cover_groups(
                str(folder_path or ""),
                platforms=requested_platforms,
                refresh_cover_source=False,
                creator_profile_name=creator_profile_name or None,
            )
            current_inputs = await _load_intelligent_publish_inputs(
                folder_path=folder_path,
                creator_profile_id=creator_profile_id,
                session=session,
                materialize_job=materialize_job,
            )
            current_plan = build_publication_plan(
                job=current_inputs["job"],
                render_output=current_inputs["render_output"],
                source_media_path=current_inputs.get("source_video_path"),
                platform_packaging=current_inputs["packaging"],
                creator_profile=current_inputs["creator_profile"],
                requested_platforms=requested_platforms,
                platform_options=platform_options,
                existing_attempts=existing_attempts,
            )
            after_reasons = _publication_plan_cover_auto_heal_reasons(current_plan)
            healed_ready = publication_plan_is_publishable(current_plan)
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "healed" if healed_ready else "still_blocked",
                    "before_reasons": before_reasons,
                    "after_reasons": after_reasons,
                    "publish_ready": bool(healed_result.get("publish_ready")) if isinstance(healed_result, dict) else None,
                    "material_contract_status": (
                        str((healed_result.get("material_contract") or {}).get("status") or "").strip()
                        if isinstance(healed_result, dict) and isinstance(healed_result.get("material_contract"), dict)
                        else ""
                    ),
                }
            )
            if healed_ready or not after_reasons:
                return _attach_cover_auto_heal_status(
                    current_plan,
                    {
                        "status": "healed" if healed_ready else "rechecked",
                        "attempts": attempts,
                        "summary": "封面质量门失败后已自动重生并重新构建发布计划。",
                    },
                ), current_inputs
        except Exception as exc:
            attempts.append(
                {
                    "attempt": attempt_index,
                    "status": "failed",
                    "before_reasons": before_reasons,
                    "error": str(exc),
                }
            )
            return _attach_cover_auto_heal_status(
                current_plan,
                {
                    "status": "failed",
                    "attempts": attempts,
                    "summary": f"封面自愈执行失败，需人工处理：{exc}",
                },
            ), current_inputs

    return _attach_cover_auto_heal_status(
        current_plan,
        {
            "status": "needs_human",
            "attempts": attempts,
            "summary": f"封面自愈重试已耗尽（{max_attempts} 次），需人工处理后再发布。",
        },
    ), current_inputs


def _normalize_publish_platform_options_payload(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_value, dict):
            continue
        key = str(raw_key or "").strip().lower().replace("_", "-")
        if key:
            normalized[key] = dict(raw_value)
    return normalized


async def _resolve_intelligent_publish_platform_options(
    *,
    requested_platform_options: Any,
    plan_inputs: dict[str, Any],
    requested_platforms: list[str] | None,
    existing_attempts: list[dict[str, Any]],
    folder_path: str,
) -> dict[str, dict[str, Any]]:
    explicit_options = _normalize_publish_platform_options_payload(requested_platform_options)
    if explicit_options:
        return explicit_options
    base_plan = build_publication_plan(
        job=plan_inputs["job"],
        render_output=plan_inputs["render_output"],
        source_media_path=plan_inputs.get("source_video_path"),
        platform_packaging=plan_inputs["packaging"],
        creator_profile=plan_inputs["creator_profile"],
        requested_platforms=requested_platforms,
        platform_options=None,
        existing_attempts=existing_attempts,
    )
    if not list(base_plan.get("targets") or []):
        return {}
    scheme = await generate_publication_scheme(
        plan=base_plan,
        creator_profile=plan_inputs["creator_profile"],
        folder_path=str(folder_path or ""),
        browser="chrome",
        force_probe=False,
    )
    return _normalize_publish_platform_options_payload(scheme.get("platform_options"))


@router.post("/open-folder", response_model=OpenFolderOut)
def open_folder(body: IntelligentCopyInspectIn):
    target_path = str(body.folder_path or "").strip()
    if not can_open_in_file_manager(target_path):
        raise HTTPException(status_code=404, detail="目录不存在。")
    try:
        open_in_file_manager(target_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"打开文件夹失败：{exc}") from exc
    resolved_path, kind = describe_file_manager_target(target_path)
    return OpenFolderOut(path=resolved_path, kind=kind)


@router.get("/local-image")
def local_image_preview(path: str):
    resolved = _resolve_frontend_local_image_path(path)
    suffix = resolved.suffix.lower()
    if suffix not in _LOCAL_IMAGE_ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="不支持的图片格式。")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="图片文件不存在。")
    return FileResponse(resolved, media_type=_LOCAL_IMAGE_MEDIA_TYPES.get(suffix, "application/octet-stream"))


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
        pruned = _dedupe_generation_tasks_by_target(
            sorted(
                tasks,
                key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
                reverse=True,
            )
        )[:_GENERATION_TASK_HISTORY_LIMIT]
        _GENERATION_TASK_STORE_PATH.write_text(
            json.dumps({"tasks": pruned}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _dedupe_generation_tasks_by_target(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, int] = {}
    deduped: list[dict[str, Any]] = []
    for item in tasks:
        key = _generation_task_target_key(item)
        if key and key in seen:
            existing_index = seen[key]
            existing = deduped[existing_index]
            if _generation_task_is_currently_active(item) and not _generation_task_is_currently_active(existing):
                deduped[existing_index] = item
            continue
        if key:
            seen[key] = len(deduped)
        deduped.append(item)
    return deduped


def _generation_task_is_currently_active(item: dict[str, Any]) -> bool:
    return item.get("status") in {"queued", "running"} and _generation_task_has_live_executor(item)


def _generation_task_target_key(item: dict[str, Any]) -> str:
    material_dir = str(item.get("material_dir") or "").strip()
    if not material_dir:
        inspection = item.get("inspection") if isinstance(item.get("inspection"), dict) else {}
        material_dir = str(inspection.get("material_dir") or "").strip()
    if material_dir:
        normalized_material = material_dir.replace("\\", "/").rstrip("/")
        if normalized_material.endswith("/smart-copy"):
            return normalized_material[: -len("/smart-copy")].rstrip("/").lower()
        return normalized_material.lower()
    return _normalize_publish_folder_key(item.get("folder_path"))


def _remove_generation_tasks_for_target(task: dict[str, Any]) -> None:
    target_key = _generation_task_target_key(task)
    if not target_key:
        return
    active_ids = set(_GENERATION_TASKS)
    tasks = [
        item
        for item in _load_generation_tasks()
        if str(item.get("id") or "") in active_ids or _generation_task_target_key(item) != target_key
    ]
    _save_generation_tasks(tasks)


def _sorted_generation_tasks() -> list[dict[str, Any]]:
    return _dedupe_generation_tasks_by_target(
        sorted(
            _load_generation_tasks(),
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        )
    )


def _upsert_generation_task(task: dict[str, Any]) -> None:
    _remove_generation_tasks_for_target(task)
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
    request_paths: list[Path] = []
    seen: set[Path] = set()
    for search_dir in (smart_copy_cover_dir(material_dir), material_dir):
        if not search_dir.exists() or not search_dir.is_dir():
            continue
        for path in sorted(search_dir.glob("*.codex-imagegen.json")):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            request_paths.append(path)
    for path in request_paths:
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
    force_regenerate: bool = False,
    creator_profile_id: str | None = None,
) -> dict[str, Any] | None:
    normalized_style = str(copy_style or "").strip()
    normalized_platforms = _normalize_generation_platforms(platforms)
    normalized_creator_profile_id = str(creator_profile_id or "").strip()
    for item in _load_generation_tasks():
        if item.get("folder_path") != folder_path:
            continue
        if str(item.get("copy_style") or "").strip() != normalized_style:
            continue
        if _normalize_generation_platforms(item.get("platforms") or []) != normalized_platforms:
            continue
        if bool(item.get("use_existing_cover")) != bool(use_existing_cover):
            continue
        if bool(item.get("force_regenerate")) != bool(force_regenerate):
            continue
        if str(item.get("creator_profile_id") or "").strip() != normalized_creator_profile_id:
            continue
        if item.get("status") in {"queued", "running"} and _generation_task_has_live_executor(item):
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
            if not _generation_task_is_stale(item):
                continue
            _mark_generation_task_failed(task_id, "生成任务已中断，请重新生成。")


def _recover_generation_task_runtime_state() -> None:
    for item in _load_generation_tasks():
        task_id = str(item.get("id") or "")
        if item.get("status") not in {"queued", "running"}:
            continue
        if _generation_task_has_live_executor(item):
            continue
        if _generation_task_is_orphaned(item):
            _mark_generation_task_failed(task_id, "生成任务未找到存活执行器，请重新生成。")
            continue
        if _generation_task_is_stale(item):
            _mark_generation_task_failed(task_id, "生成任务已中断，请重新生成。")


def _generation_task_is_stale(item: dict[str, Any]) -> bool:
    timestamp = str(item.get("updated_at") or item.get("started_at") or item.get("created_at") or "").strip()
    if not timestamp:
        return False
    try:
        updated_at = datetime.fromisoformat(timestamp)
    except ValueError:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - updated_at).total_seconds() > _GENERATION_TASK_STALE_AFTER_SECONDS


def _generation_task_is_orphaned(item: dict[str, Any]) -> bool:
    task_id = str(item.get("id") or "").strip()
    if not task_id or item.get("status") not in {"queued", "running"}:
        return False
    if _generation_task_has_live_executor(item):
        return False
    if not _generation_task_exceeded_orphan_grace(item):
        return False
    owner_pid = _generation_task_owner_pid(item)
    if owner_pid is None:
        return True
    if owner_pid == os.getpid():
        return True
    return not _pid_is_alive(owner_pid)


def _generation_task_exceeded_orphan_grace(item: dict[str, Any]) -> bool:
    timestamp = str(
        item.get("last_heartbeat_at")
        or item.get("worker_claimed_at")
        or item.get("updated_at")
        or item.get("started_at")
        or item.get("created_at")
        or ""
    ).strip()
    if not timestamp:
        return False
    try:
        updated_at = datetime.fromisoformat(timestamp)
    except ValueError:
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - updated_at).total_seconds() > _GENERATION_TASK_ORPHAN_GRACE_SECONDS


def _generation_task_owner_pid(item: dict[str, Any]) -> int | None:
    try:
        pid = int(item.get("worker_owner_pid"))
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _generation_task_has_live_executor(item: dict[str, Any]) -> bool:
    task_id = str(item.get("id") or "").strip()
    if task_id and task_id in _GENERATION_TASKS:
        return True
    owner_pid = _generation_task_owner_pid(item)
    return owner_pid is not None and _pid_is_alive(owner_pid)


def _schedule_generation_task(
    task_id: str,
    *,
    folder_path: str,
    copy_style: str | None,
    platforms: list[str] | None,
    use_existing_cover: bool,
    force_regenerate: bool,
    creator_profile_id: str | None,
    creator_profile_name: str | None,
) -> None:
    command = [
        sys.executable,
        "-m",
        "roughcut.cli",
        "intelligent-copy-task-runner",
        "--task-id",
        task_id,
        "--folder-path",
        folder_path,
        "--use-existing-cover" if use_existing_cover else "--no-use-existing-cover",
    ]
    if force_regenerate:
        command.append("--force-regenerate")
    if copy_style:
        command.extend(["--copy-style", str(copy_style)])
    for platform in platforms or []:
        command.extend(["--platform", str(platform)])
    if creator_profile_id:
        command.extend(["--creator-profile-id", str(creator_profile_id)])
    if creator_profile_name:
        command.extend(["--creator-profile-name", str(creator_profile_name)])

    creationflags = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags |= subprocess.CREATE_NO_WINDOW
    log_path = _GENERATION_TASK_STORE_PATH.parent / f"{task_id}.runner.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("ab")
    process = subprocess.Popen(
        command,
        cwd=str(Path(__file__).resolve().parents[3]),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    log_handle.close()
    _patch_generation_task(
        task_id,
        {
            "worker_owner_pid": process.pid,
            "last_heartbeat_at": _now_iso(),
            "worker_log_path": str(log_path),
        },
    )


def _run_generation_task_thread(
    task_id: str,
    folder_path: str,
    copy_style: str | None,
    platforms: list[str] | None,
    use_existing_cover: bool,
    force_regenerate: bool,
    creator_profile_id: str | None,
    creator_profile_name: str | None,
) -> None:
    asyncio.run(
        _run_generation_task(
            task_id,
            folder_path=folder_path,
            copy_style=copy_style,
            platforms=platforms,
            use_existing_cover=use_existing_cover,
            force_regenerate=force_regenerate,
            creator_profile_id=creator_profile_id,
            creator_profile_name=creator_profile_name,
        )
    )


async def _run_generation_task(
    task_id: str,
    *,
    folder_path: str,
    copy_style: str | None,
    platforms: list[str] | None,
    use_existing_cover: bool,
    force_regenerate: bool,
    creator_profile_id: str | None,
    creator_profile_name: str | None,
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
                "worker_owner_pid": os.getpid(),
                "worker_claimed_at": _now_iso(),
                "last_heartbeat_at": _now_iso(),
                "error": None,
            },
        )

        async def progress_callback(update: dict[str, Any]) -> None:
            patch: dict[str, Any] = {
                "status": "running",
                "progress": max(0, min(99, int(update.get("progress") or 0))),
                "stage": str(update.get("stage") or "running"),
                "message": str(update.get("message") or ""),
                "last_heartbeat_at": _now_iso(),
            }
            for key in ("folder_path", "material_dir", "inspection", "partial_result"):
                if key in update:
                    patch[key] = update[key]
            _patch_generation_task(task_id, patch)

        creator_profile = _resolve_generation_creator_profile(creator_profile_id)
        result = await generate_intelligent_copy(
            folder_path,
            copy_style=copy_style,
            platforms=platforms,
            use_existing_cover=use_existing_cover,
            force_regenerate=force_regenerate,
            creator_profile_id=creator_profile_id,
            creator_profile_name=creator_profile_name,
            creator_profile=creator_profile,
            progress_callback=progress_callback,
        )
        terminal_patch = _derive_generation_task_terminal_patch(result)
        _patch_generation_task(
            task_id,
            {
                **terminal_patch,
                "progress": 100,
                "completed_at": _now_iso(),
                "material_dir": str(result.get("material_dir") or ""),
                "inspection": result.get("inspection"),
                "partial_result": result,
                "result": result,
            },
        )
    except Exception as exc:
        logger.exception("Intelligent copy generation task failed", extra={"task_id": task_id, "folder_path": folder_path})
        traceback.print_exc()
        _mark_generation_task_failed(task_id, str(exc))
    finally:
        _GENERATION_TASKS.pop(task_id, None)


def suggest_directory_paths(query: str, *, limit: int = 12) -> list[IntelligentCopyPathSuggestionOut]:
    raw_query = str(query or "").strip().strip('"')
    safe_limit = max(1, min(int(limit or 12), 30))
    if not raw_query:
        return []

    local_suggestions = _suggest_directory_paths_local(raw_query, limit=safe_limit)
    if local_suggestions:
        return local_suggestions
    return _suggest_directory_paths_from_host_bridge(raw_query, limit=safe_limit)


def _suggest_directory_paths_local(query: str, *, limit: int) -> list[IntelligentCopyPathSuggestionOut]:
    base_dir, prefix = _split_directory_suggestion_query(query)
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
        if len(suggestions) >= limit:
            break
    return suggestions


def _suggest_directory_paths_from_host_bridge(query: str, *, limit: int) -> list[IntelligentCopyPathSuggestionOut]:
    url = _resolve_host_path_suggestions_url()
    if not url:
        return []

    headers = {"Content-Type": "application/json"}
    token = resolve_codex_proxy_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = httpx.post(
            url,
            json={"query": query, "limit": limit},
            headers=headers,
            timeout=float(os.getenv("ROUGHCUT_HOST_PATH_SUGGESTIONS_TIMEOUT_SEC", "4") or "4"),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    raw_suggestions = payload.get("suggestions") if isinstance(payload, dict) else None
    if not isinstance(raw_suggestions, list):
        return []

    suggestions: list[IntelligentCopyPathSuggestionOut] = []
    seen: set[str] = set()
    for item in raw_suggestions:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        key = path.casefold()
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(
            IntelligentCopyPathSuggestionOut(
                path=path,
                label=str(item.get("label") or Path(path).name or path),
                parent=str(item.get("parent") or ""),
                kind=str(item.get("kind") or "folder"),
            )
        )
        if len(suggestions) >= limit:
            break
    return suggestions


def _resolve_host_path_suggestions_url() -> str:
    explicit = str(os.getenv("ROUGHCUT_HOST_PATH_SUGGESTIONS_URL", "") or "").strip()
    if explicit:
        return explicit
    return resolve_codex_proxy_sibling_url("/v1/host/path-suggestions")


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
    processing_folder = Path(str(inspection.get("material_dir") or "")).parent
    if not str(processing_folder) or str(processing_folder) == ".":
        processing_folder = Path(str(inspection["folder_path"]))
    publish_video_path = await _resolve_publish_source_media_path(video_path=video_path)
    packaging = _load_intelligent_copy_packaging(processing_folder)
    if packaging is None and task_snapshot is not None:
        packaging = _load_intelligent_copy_packaging_from_task_snapshot(task_snapshot)
    creator_profile = _resolve_intelligent_publish_creator_profile(creator_profile_id)
    creator_profile = await _merge_creator_card_publication_bindings(
        session=session,
        creator_profile=creator_profile,
        creator_profile_id=creator_profile_id,
    )
    if materialize_job:
        job = await _get_or_create_intelligent_publish_job(session, video_path=publish_video_path, folder_path=processing_folder)
        render_output = await _get_or_create_intelligent_publish_render_output(session, job=job, video_path=publish_video_path)
    else:
        job = await _find_existing_intelligent_publish_job(session, video_path=publish_video_path)
        if job is None:
            job = SimpleNamespace(
                id=uuid.uuid5(uuid.NAMESPACE_URL, f"roughcut:intelligent-publish:{_stable_publish_path(publish_video_path)}"),
                status="done",
                source_name=publish_video_path.name,
            )
        render_output = SimpleNamespace(output_path=_stable_publish_path(publish_video_path))
    return {
        "job": job,
        "render_output": render_output,
        "packaging": packaging,
        "creator_profile": creator_profile,
        "publish_video_path": str(publish_video_path),
        "source_video_path": str(video_path),
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


def _publication_runtime_dir_for_source(source_path: Path) -> Path:
    return source_path.parent / "smart-copy" / "_publication_runtime"


def _publication_runtime_target_path(source_path: Path) -> Path:
    return _publication_runtime_dir_for_source(source_path) / f"{source_path.stem}.publication-runtime.mp4"


def _publication_runtime_copy_is_fresh(*, source_path: Path, runtime_path: Path) -> bool:
    try:
        if not runtime_path.exists() or not runtime_path.is_file():
            return False
        return runtime_path.stat().st_mtime >= source_path.stat().st_mtime
    except OSError:
        return False


async def _transcode_publication_runtime_media(*, source_path: Path, runtime_path: Path) -> None:
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-c:v",
        "libx264",
        "-preset",
        str(getattr(settings, "render_cpu_preset", "veryfast") or "veryfast"),
        "-crf",
        str(int(getattr(settings, "render_crf", 19) or 19)),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        str(getattr(settings, "render_audio_bitrate", "192k") or "192k"),
        "-movflags",
        "+faststart",
        str(runtime_path),
    ]
    result = await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(30, int(getattr(settings, "ffmpeg_timeout_sec", 600) or 600)),
    )
    if result.returncode != 0:
        stderr = str(result.stderr or "").strip()
        stdout = str(result.stdout or "").strip()
        detail = stderr or stdout or "ffmpeg transcode failed"
        raise RuntimeError(f"publication runtime 转码失败：{detail[-800:]}")


async def _resolve_publish_source_media_path(*, video_path: Path) -> Path:
    source_path = video_path.expanduser()
    source_meta = await probe_media(source_path)
    compatibility = publication_upload_compatibility(source_meta)
    if bool(compatibility.get("compatible")):
        return source_path.resolve()

    runtime_path = _publication_runtime_target_path(source_path)
    if _publication_runtime_copy_is_fresh(source_path=source_path, runtime_path=runtime_path):
        runtime_meta = await probe_media(runtime_path)
        runtime_compatibility = publication_upload_compatibility(runtime_meta)
        if bool(runtime_compatibility.get("compatible")):
            return runtime_path.resolve()

    try:
        await _transcode_publication_runtime_media(source_path=source_path, runtime_path=runtime_path)
    except RuntimeError as exc:
        reasons = "；".join(str(item).strip() for item in (compatibility.get("reasons") or []) if str(item).strip())
        detail = str(exc or "").strip()
        suffix = f"；转码失败：{detail}" if detail else ""
        raise RuntimeError(f"发布源媒体不满足发布兼容要求：{reasons or '无法生成兼容发布副本'}{suffix}") from exc
    runtime_meta = await probe_media(runtime_path)
    runtime_compatibility = publication_upload_compatibility(runtime_meta)
    if not bool(runtime_compatibility.get("compatible")):
        reasons = "；".join(str(item).strip() for item in (runtime_compatibility.get("reasons") or []) if str(item).strip())
        raise RuntimeError(f"publication runtime 副本仍不满足上传兼容要求：{reasons}")
    return runtime_path.resolve()


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


def _resolve_generation_creator_profile(creator_profile_id: str | None) -> dict[str, Any] | None:
    profile_id = str(creator_profile_id or "").strip()
    if not profile_id:
        return None
    try:
        return get_avatar_material_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Creator profile not found") from exc


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
    material_dir = folder_path / "smart-copy"
    packaging, _sources = load_publication_packaging_payload(
        material_json=str(resolve_smart_copy_material_json_path(material_dir)),
        platform_packaging=str(resolve_smart_copy_platform_packaging_json_path(material_dir)),
    )
    return packaging


def _normalize_intelligent_copy_payload_as_packaging(payload: dict[str, Any], material_dir: str | None = None) -> dict[str, Any] | None:
    return normalize_publication_packaging_payload(payload, material_dir=material_dir)


def _resolve_intelligent_publish_creator_profile(creator_profile_id: str | None) -> dict[str, Any] | None:
    profile_id = str(creator_profile_id or "").strip()
    if profile_id:
        try:
            return get_avatar_material_profile(profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Creator profile not found") from exc
    profiles = list_avatar_material_profiles()
    return next((profile for profile in profiles if active_publication_credentials(profile)), profiles[0] if profiles else None)


async def _merge_creator_card_publication_bindings(
    *,
    session: AsyncSession,
    creator_profile: dict[str, Any] | None,
    creator_profile_id: str | None,
) -> dict[str, Any] | None:
    base_profile = dict(creator_profile or {})
    creator = await _find_publication_creator_card_for_profile(
        session=session,
        creator_profile=base_profile,
        creator_profile_id=creator_profile_id,
    )
    if creator is None or creator.publication_profile is None:
        return creator_profile
    bindings = _creator_card_publication_credentials(creator.publication_profile)
    if not bindings:
        return creator_profile

    creator_payload = (
        dict(base_profile.get("creator_profile"))
        if isinstance(base_profile.get("creator_profile"), dict)
        else {}
    )
    publishing = (
        dict(creator_payload.get("publishing"))
        if isinstance(creator_payload.get("publishing"), dict)
        else {}
    )
    existing_credentials = [
        item
        for item in (publishing.get("platform_credentials") or [])
        if isinstance(item, dict)
    ]
    merged_by_platform = {
        str(item.get("platform") or "").strip().lower(): dict(item)
        for item in existing_credentials
        if str(item.get("platform") or "").strip()
    }
    for binding in bindings:
        platform = str(binding.get("platform") or "").strip().lower()
        if platform:
            merged_by_platform[platform] = binding
    publishing["platform_credentials"] = list(merged_by_platform.values())
    if "active_platforms" not in publishing:
        publishing["active_platforms"] = [item["platform"] for item in bindings if item.get("platform")]
    creator_payload["publishing"] = publishing
    base_profile["creator_profile"] = creator_payload
    if not str(base_profile.get("id") or "").strip():
        base_profile["id"] = str(creator.id)
    if not str(base_profile.get("display_name") or "").strip():
        base_profile["display_name"] = creator.name
    base_profile["creator_card_id"] = str(creator.id)
    return base_profile


async def _find_publication_creator_card_for_profile(
    *,
    session: AsyncSession,
    creator_profile: dict[str, Any],
    creator_profile_id: str | None,
) -> CreatorCard | None:
    normalized_id = str(creator_profile_id or "").strip()
    candidate_uuid = None
    if normalized_id:
        try:
            candidate_uuid = uuid.UUID(normalized_id)
        except ValueError:
            candidate_uuid = None
    if candidate_uuid is not None:
        result = await session.execute(
            select(CreatorCard)
            .where(CreatorCard.id == candidate_uuid)
            .options(selectinload(CreatorCard.publication_profile).selectinload(CreatorPublicationProfile.bindings))
        )
        creator = result.scalar_one_or_none()
        if creator is not None:
            return creator

    candidate_names = [
        str(creator_profile.get("display_name") or "").strip(),
        str(creator_profile.get("name") or "").strip(),
    ]
    compatible = creator_profile.get("creator_card_compatible")
    if isinstance(compatible, dict):
        candidate_names.append(str(compatible.get("name") or "").strip())
    for name in dict.fromkeys(item for item in candidate_names if item):
        result = await session.execute(
            select(CreatorCard)
            .where(CreatorCard.name == name)
            .options(selectinload(CreatorCard.publication_profile).selectinload(CreatorPublicationProfile.bindings))
            .limit(1)
        )
        creator = result.scalar_one_or_none()
        if creator is not None:
            return creator
    return None


def _creator_card_publication_credentials(profile: CreatorPublicationProfile) -> list[dict[str, Any]]:
    credentials: list[dict[str, Any]] = []
    for binding in profile.bindings or []:
        payload = binding.binding_payload_json if isinstance(binding.binding_payload_json, dict) else {}
        platform = str(binding.platform or payload.get("platform") or "").strip().lower()
        credential_ref = str(binding.credential_ref or payload.get("credential_ref") or "").strip()
        if not platform or not credential_ref:
            continue
        status = str(payload.get("status") or "").strip().lower().replace("-", "_")
        if status == "login_confirmed":
            status = "logged_in"
        credentials.append(
            {
                "id": str(binding.id),
                "platform": platform,
                "credential_ref": credential_ref,
                "account_label": str(payload.get("account_label") or platform).strip(),
                "browser_profile_id": str(payload.get("browser_profile_id") or "").strip() or credential_ref,
                "browser_binding": payload.get("browser_binding") if isinstance(payload.get("browser_binding"), dict) else {},
                "status": status or "unverified",
                "enabled": bool(payload.get("enabled", True)),
                "adapter": str(payload.get("adapter") or "").strip() or ("social_auto_upload" if credential_ref.startswith("social-auto-upload:") else ""),
                "notes": str(payload.get("notes") or "").strip() or None,
            }
        )
    return credentials


def _resolve_frontend_local_image_path(raw_path: str) -> Path:
    text = str(raw_path or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="缺少图片路径。")
    publication_cover_path = resolve_publication_local_cover_path(text)
    if publication_cover_path is not None:
        return publication_cover_path
    normalized = text.replace("\\", "/")
    container_prefix = "/app/data/"
    if normalized.startswith(container_prefix):
        container_path = Path(normalized)
        try:
            if container_path.exists():
                return container_path.resolve()
        except OSError:
            pass
        repo_root = Path(__file__).resolve().parents[3]
        host_output_root = Path(
            os.getenv("ROUGHCUT_OUTPUT_HOST_ROOT", "") or (repo_root / "data" / "runtime")
        ).expanduser()
        relative = normalized[len(container_prefix):].lstrip("/")
        return (host_output_root / Path(relative)).resolve()
    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (Path.cwd() / candidate).resolve()


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
