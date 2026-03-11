from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.api.schemas import (
    WatchInventoryOut,
    WatchInventoryScanIn,
    WatchInventoryScanStatusOut,
    WatchRootCreate,
    WatchRootOut,
)
from roughcut.db.models import WatchRoot
from roughcut.db.session import get_session
from roughcut.watcher.folder_watcher import (
    get_watch_root_inventory_scan_status,
    scan_watch_root_inventory,
    start_watch_root_inventory_scan,
)

router = APIRouter(prefix="/watch-roots", tags=["watch-roots"])


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


@router.get("", response_model=list[WatchRootOut])
async def list_watch_roots(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(WatchRoot).order_by(WatchRoot.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=WatchRootOut, status_code=201)
async def create_watch_root(
    body: WatchRootCreate,
    session: AsyncSession = Depends(get_session),
):
    root = WatchRoot(
        path=body.path,
        channel_profile=body.channel_profile,
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
    root.path = body.path
    root.channel_profile = body.channel_profile
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
        payload = await scan_watch_root_inventory(root.path, scan_mode=root.scan_mode or "fast")
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
