from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.api.schemas import LearnedHotwordOut, LearnedHotwordUpdate
from roughcut.db.models import LearnedHotword
from roughcut.db.session import get_session
from roughcut.review.domain_glossaries import _DOMAIN_COMPATIBILITY, normalize_subject_domain
from roughcut.review.hotword_learning import normalize_hotword_token

router = APIRouter(prefix="/learned-hotwords", tags=["learned-hotwords"])


def _normalize_subject_domain(value: str | None) -> str:
    text = str(value or "").strip()
    return normalize_subject_domain(text) or text.lower()


def _domain_filter_values(subject_domain: str | None) -> list[str]:
    normalized = _normalize_subject_domain(subject_domain)
    if not normalized:
        return []
    return sorted({"", normalized, *_DOMAIN_COMPATIBILITY.get(normalized, ())})


def _sanitize_aliases(values: list[str] | None, *, term: str, canonical_form: str) -> list[str]:
    aliases: list[str] = []
    seen = {normalize_hotword_token(term), normalize_hotword_token(canonical_form)}
    for value in values or []:
        alias = normalize_hotword_token(value)
        if not alias or alias in seen:
            continue
        seen.add(alias)
        aliases.append(alias)
    return aliases[:12]


@router.get("", response_model=list[LearnedHotwordOut])
async def list_learned_hotwords(
    subject_domain: str | None = Query(default=None),
    status: Literal["active", "suppressed", "rejected", "all"] = "active",
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(LearnedHotword)
    if status != "all":
        stmt = stmt.where(LearnedHotword.status == status)
    domains = _domain_filter_values(subject_domain)
    if domains:
        stmt = stmt.where(LearnedHotword.subject_domain.in_(domains))
    result = await session.execute(
        stmt.order_by(
            LearnedHotword.confidence.desc(),
            LearnedHotword.positive_count.desc(),
            LearnedHotword.evidence_count.desc(),
            LearnedHotword.last_seen_at.desc(),
        ).limit(limit)
    )
    return result.scalars().all()


@router.patch("/{hotword_id}", response_model=LearnedHotwordOut)
async def update_learned_hotword(
    hotword_id: uuid.UUID,
    body: LearnedHotwordUpdate,
    session: AsyncSession = Depends(get_session),
):
    hotword = await session.get(LearnedHotword, hotword_id)
    if hotword is None:
        raise HTTPException(status_code=404, detail="Learned hotword not found")

    if body.status is not None:
        hotword.status = body.status
    if body.aliases is not None:
        hotword.aliases = _sanitize_aliases(
            body.aliases,
            term=hotword.term,
            canonical_form=hotword.canonical_form or hotword.term,
        )
    if body.confidence is not None:
        hotword.confidence = max(0.0, min(1.0, float(body.confidence)))
    hotword.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(hotword)
    return hotword
