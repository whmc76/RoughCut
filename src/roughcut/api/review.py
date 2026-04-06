from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.api.schemas import (
    WatchInventoryEnqueueIn,
    WatchInventoryMergeIn,
    WatchInventoryEnqueueOut,
    WatchInventoryOut,
    WatchInventorySmartMergeOut,
    WatchInventoryScanIn,
    WatchInventoryScanStatusOut,
    WatchRootCreate,
    WatchRootOut,
)
from roughcut.db.models import ConfigProfile, WatchRoot
from roughcut.db.session import get_session
from roughcut.watcher.folder_watcher import (
    create_jobs_for_inventory_paths,
    create_merged_job_for_inventory_paths,
    suggest_merge_groups_for_inventory_items,
    ensure_watch_inventory_thumbnail,
    get_watch_root_inventory_scan_status,
    replace_watch_root_inventory_scan_snapshot,
    scan_watch_root_inventory,
    start_watch_root_inventory_scan,
)

router = APIRouter(prefix="/watch-roots", tags=["watch-roots"])


async def _ensure_config_profile_exists(
    session: AsyncSession,
    config_profile_id: uuid.UUID | None,
) -> uuid.UUID | None:
    if config_profile_id is None:
        return None
    profile = await session.get(ConfigProfile, config_profile_id)
    if profile is None:
        raise HTTPException(status_code=422, detail="Config profile not found")
    return profile.id


async def _create_jobs_for_watch_root(
    file_paths: list[str],
    *,
    config_profile_id: uuid.UUID | None,
    workflow_template: str | None,
    output_dir: str | None = None,
):
    return await create_jobs_for_inventory_paths(
        file_paths,
        output_dir=output_dir,
        config_profile_id=config_profile_id,
        workflow_template=workflow_template,
    )


async def _create_merged_job_for_watch_root(
    file_paths: list[str],
    *,
    config_profile_id: uuid.UUID | None,
    workflow_template: str | None,
    output_dir: str | None = None,
):
    return await create_merged_job_for_inventory_paths(
        file_paths,
        output_dir=output_dir,
        config_profile_id=config_profile_id,
        workflow_template=workflow_template,
    )


def _cached_status_payload(root: WatchRoot, *, include_inventory: bool, inventory_limit: int | None) -> dict:
    cached = root.inventory_cache_json or None
    if isinstance(cached, dict):
        payload = {
            **cached,
            "scan_mode": root.scan_mode or "fast",
        }
        if not include_inventory:
            payload["inventory"] = {"pending": [], "deduped": []}
        elif inventory_limit is not None:
            inventory = payload.get("inventory") or {}
            payload["inventory"] = {
                "pending": list(inventory.get("pending") or [])[:inventory_limit],
                "deduped": list(inventory.get("deduped") or [])[:inventory_limit],
            }
        return payload
    return {
        "root_path": root.path,
        "scan_mode": root.scan_mode or "fast",
        "status": "idle",
        "started_at": "",
        "updated_at": "",
        "finished_at": None,
        "total_files": 0,
        "processed_files": 0,
        "pending_count": 0,
        "deduped_count": 0,
        "current_file": None,
        "current_phase": None,
        "current_file_size_bytes": None,
        "current_file_processed_bytes": None,
        "error": None,
        "inventory": {"pending": [], "deduped": []},
    }


def _full_inventory_payload(root: WatchRoot) -> dict:
    payload = get_watch_root_inventory_scan_status(
        root.path,
        include_inventory=True,
        inventory_limit=None,
    )
    if payload is not None:
        return payload
    return _cached_status_payload(root, include_inventory=True, inventory_limit=None)


@router.get("", response_model=list[WatchRootOut])
async def list_watch_roots(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(WatchRoot).order_by(WatchRoot.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=WatchRootOut, status_code=201)
async def create_watch_root(
    body: WatchRootCreate,
    session: AsyncSession = Depends(get_session),
):
    config_profile_id = await _ensure_config_profile_exists(session, body.config_profile_id)
    root = WatchRoot(
        path=body.path,
        config_profile_id=config_profile_id,
        workflow_template=body.workflow_template,
        output_dir=body.output_dir,
        enabled=body.enabled,
        scan_mode=body.scan_mode,
    )
    session.add(root)
    await session.commit()
    await session.refresh(root)
    return root


@router.patch("/{root_id}", response_model=WatchRootOut)
async def update_watch_root(
    root_id: uuid.UUID,
    body: WatchRootCreate,
    session: AsyncSession = Depends(get_session),
):
    root = await session.get(WatchRoot, root_id)
    if not root:
        raise HTTPException(status_code=404, detail="Watch root not found")
    config_profile_id = await _ensure_config_profile_exists(session, body.config_profile_id)
    root.path = body.path
    root.config_profile_id = config_profile_id
    root.workflow_template = body.workflow_template
    root.output_dir = body.output_dir
    root.enabled = body.enabled
    root.scan_mode = body.scan_mode
    await session.commit()
    await session.refresh(root)
    return root


@router.delete("/{root_id}", status_code=204)
async def delete_watch_root(root_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    root = await session.get(WatchRoot, root_id)
    if not root:
        raise HTTPException(status_code=404, detail="Watch root not found")
    await session.delete(root)
    await session.commit()


@router.get("/{root_id}/inventory", response_model=WatchInventoryOut)
async def get_watch_root_inventory(root_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    root = await session.get(WatchRoot, root_id)
    if not root:
        raise HTTPException(status_code=404, detail="Watch root not found")
    try:
        payload = await scan_watch_root_inventory(
            root.path,
            scan_mode=root.scan_mode or "fast",
            output_dir=root.output_dir,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return payload


@router.post("/{root_id}/inventory/scan", response_model=WatchInventoryScanStatusOut)
async def start_inventory_scan(
    root_id: uuid.UUID,
    body: WatchInventoryScanIn | None = None,
    session: AsyncSession = Depends(get_session),
):
    root = await session.get(WatchRoot, root_id)
    if not root:
        raise HTTPException(status_code=404, detail="Watch root not found")
    try:
        return start_watch_root_inventory_scan(
            root.path,
            scan_mode=root.scan_mode or "fast",
            output_dir=root.output_dir,
            force=bool(body and body.force),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotADirectoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{root_id}/inventory/status", response_model=WatchInventoryScanStatusOut)
async def get_inventory_scan_status(
    root_id: uuid.UUID,
    include_inventory: bool = False,
    inventory_limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    root = await session.get(WatchRoot, root_id)
    if not root:
        raise HTTPException(status_code=404, detail="Watch root not found")
    payload = get_watch_root_inventory_scan_status(
        root.path,
        include_inventory=include_inventory,
        inventory_limit=inventory_limit if include_inventory else None,
    )
    if payload is None:
        return _cached_status_payload(root, include_inventory=include_inventory, inventory_limit=inventory_limit)
    return payload


@router.post("/{root_id}/inventory/enqueue", response_model=WatchInventoryEnqueueOut)
async def enqueue_inventory_items(
    root_id: uuid.UUID,
    body: WatchInventoryEnqueueIn,
    session: AsyncSession = Depends(get_session),
):
    root = await session.get(WatchRoot, root_id)
    if not root:
        raise HTTPException(status_code=404, detail="Watch root not found")

    active_status = get_watch_root_inventory_scan_status(root.path, include_inventory=False)
    if active_status and active_status.get("status") == "running":
        raise HTTPException(status_code=409, detail="Inventory scan is still running")

    payload = _full_inventory_payload(root)
    inventory = payload.get("inventory") or {}
    pending = list(inventory.get("pending") or [])
    if not pending:
        return WatchInventoryEnqueueOut(
            requested_count=0,
            created_count=0,
            skipped_count=0,
            created_job_ids=[],
        )

    if body.enqueue_all:
        selected_items = pending
    else:
        selected_paths = {path for path in body.relative_paths if path}
        if not selected_paths:
            raise HTTPException(status_code=400, detail="No inventory items selected")
        selected_items = [item for item in pending if item.get("relative_path") in selected_paths]

    if not selected_items:
        raise HTTPException(status_code=404, detail="Selected inventory items not found")

    results = await _create_jobs_for_watch_root(
        [str(item["path"]) for item in selected_items],
        config_profile_id=root.config_profile_id,
        workflow_template=root.workflow_template,
        output_dir=root.output_dir,
    )
    job_ids_by_path = {result["path"]: result["job_id"] for result in results}
    created_job_ids = [job_id for job_id in job_ids_by_path.values() if job_id]
    selected_path_set = {str(item["path"]) for item in selected_items}

    remaining_pending = [item for item in pending if str(item.get("path")) not in selected_path_set]
    deduped = list(inventory.get("deduped") or [])
    for item in selected_items:
        path = str(item["path"])
        job_id = job_ids_by_path.get(path)
        deduped.append(
            {
                **item,
                "status": "deduped",
                "dedupe_reason": "job:pending" if job_id else "job:existing",
                "matched_job_id": job_id,
            }
        )

    payload["inventory"] = {
        "pending": remaining_pending,
        "deduped": deduped,
    }
    payload["pending_count"] = len(remaining_pending)
    payload["deduped_count"] = len(deduped)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    if payload.get("status") in {None, "idle"}:
        payload["status"] = "done"

    root.inventory_cache_json = payload
    root.inventory_cache_updated_at = datetime.now(timezone.utc)
    await session.commit()
    replace_watch_root_inventory_scan_snapshot(root.path, payload)

    return WatchInventoryEnqueueOut(
        requested_count=len(selected_items),
        created_count=len(created_job_ids),
        skipped_count=len(selected_items) - len(created_job_ids),
        created_job_ids=created_job_ids,
    )


@router.post("/{root_id}/inventory/merge", response_model=WatchInventoryEnqueueOut)
async def merge_inventory_items(
    root_id: uuid.UUID,
    body: WatchInventoryMergeIn,
    session: AsyncSession = Depends(get_session),
):
    root = await session.get(WatchRoot, root_id)
    if not root:
        raise HTTPException(status_code=404, detail="Watch root not found")

    active_status = get_watch_root_inventory_scan_status(root.path, include_inventory=False)
    if active_status and active_status.get("status") == "running":
        raise HTTPException(status_code=409, detail="Inventory scan is still running")

    payload = _full_inventory_payload(root)
    inventory = payload.get("inventory") or {}
    pending = list(inventory.get("pending") or [])
    if not pending:
        return WatchInventoryEnqueueOut(
            requested_count=0,
            created_count=0,
            skipped_count=0,
            created_job_ids=[],
        )

    selected_set = {path for path in body.relative_paths if path}
    if len(selected_set) < 2:
        raise HTTPException(status_code=400, detail="At least two inventory items are required to merge")

    pending_map = {str(item.get("relative_path")): item for item in pending if item.get("relative_path") is not None}
    selected_items = [pending_map[path] for path in body.relative_paths if path in pending_map]
    if len(selected_items) < 2:
        raise HTTPException(status_code=404, detail="Selected inventory items not found")

    file_paths = [str(item["path"]) for item in selected_items]
    job_id = await _create_merged_job_for_watch_root(
        file_paths,
        config_profile_id=root.config_profile_id,
        workflow_template=root.workflow_template,
        output_dir=root.output_dir,
    )
    merged_job_ids = [job_id] if job_id else []

    selected_path_set = {str(item["path"]) for item in selected_items}
    remaining_pending = [item for item in pending if str(item.get("path")) not in selected_path_set]
    deduped = list(inventory.get("deduped") or [])
    for item in selected_items:
        deduped.append(
            {
                **item,
                "status": "deduped",
                "dedupe_reason": "job:merged" if job_id else "job:existing",
                "matched_job_id": job_id,
            }
        )

    payload["inventory"] = {
        "pending": remaining_pending,
        "deduped": deduped,
    }
    payload["pending_count"] = len(remaining_pending)
    payload["deduped_count"] = len(deduped)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    if payload.get("status") in {None, "idle"}:
        payload["status"] = "done"

    root.inventory_cache_json = payload
    root.inventory_cache_updated_at = datetime.now(timezone.utc)
    await session.commit()
    replace_watch_root_inventory_scan_snapshot(root.path, payload)

    return WatchInventoryEnqueueOut(
        requested_count=len(selected_items),
        created_count=len(merged_job_ids),
        skipped_count=len(selected_items) - len(merged_job_ids),
        created_job_ids=merged_job_ids,
    )


@router.get("/{root_id}/inventory/smart-groups", response_model=WatchInventorySmartMergeOut)
async def suggest_inventory_merge_groups(
    root_id: uuid.UUID,
    time_window_seconds: int = 480,
    min_score: float = 0.62,
    min_group_size: int = 2,
    max_groups: int = 8,
    session: AsyncSession = Depends(get_session),
):
    root = await session.get(WatchRoot, root_id)
    if not root:
        raise HTTPException(status_code=404, detail="Watch root not found")

    active_status = get_watch_root_inventory_scan_status(root.path, include_inventory=False)
    if active_status and active_status.get("status") == "running":
        raise HTTPException(status_code=409, detail="Inventory scan is still running")

    payload = _full_inventory_payload(root)
    pending = list((payload.get("inventory") or {}).get("pending") or [])
    groups = await suggest_merge_groups_for_inventory_items(
        pending,
        time_window_seconds=time_window_seconds,
        min_score=min_score,
        min_group_size=min_group_size,
        max_groups=max_groups,
    )
    return WatchInventorySmartMergeOut(
        source_count=len(pending),
        groups=groups,
    )


@router.get("/{root_id}/inventory/thumbnail")
async def get_inventory_thumbnail(
    root_id: uuid.UUID,
    relative_path: str,
    session: AsyncSession = Depends(get_session),
):
    root = await session.get(WatchRoot, root_id)
    if not root:
        raise HTTPException(status_code=404, detail="Watch root not found")
    try:
        thumbnail = await ensure_watch_inventory_thumbnail(root.path, relative_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(
        thumbnail,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
