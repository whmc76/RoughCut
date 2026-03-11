from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.api.schemas import WatchRootCreate, WatchRootOut
from roughcut.db.models import WatchRoot
from roughcut.db.session import get_session

router = APIRouter(prefix="/watch-roots", tags=["watch-roots"])


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
