from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.api.schemas import BuiltinGlossaryPackOut, GlossaryTermCreate, GlossaryTermOut, GlossaryTermUpdate
from roughcut.db.models import GlossaryTerm
from roughcut.db.session import get_session
from roughcut.review.domain_glossaries import list_builtin_glossary_packs

router = APIRouter(prefix="/glossary", tags=["glossary"])


@router.get("", response_model=list[GlossaryTermOut])
async def list_terms(
    scope_type: str | None = Query(default=None),
    scope_value: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(GlossaryTerm)
    if scope_type:
        stmt = stmt.where(GlossaryTerm.scope_type == scope_type)
    if scope_value is not None:
        stmt = stmt.where(GlossaryTerm.scope_value == scope_value)
    result = await session.execute(stmt.order_by(GlossaryTerm.created_at.desc()))
    return result.scalars().all()


@router.get("/builtin-packs", response_model=list[BuiltinGlossaryPackOut])
async def list_builtin_packs():
    return list_builtin_glossary_packs()


@router.post("", response_model=GlossaryTermOut, status_code=status.HTTP_201_CREATED)
async def create_term(
    body: GlossaryTermCreate,
    session: AsyncSession = Depends(get_session),
):
    term = GlossaryTerm(
        scope_type=body.scope_type,
        scope_value=body.scope_value,
        wrong_forms=body.wrong_forms,
        correct_form=body.correct_form,
        category=body.category,
        context_hint=body.context_hint,
    )
    session.add(term)
    await session.commit()
    await session.refresh(term)
    return term


@router.get("/{term_id}", response_model=GlossaryTermOut)
async def get_term(term_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    term = await session.get(GlossaryTerm, term_id)
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")
    return term


@router.patch("/{term_id}", response_model=GlossaryTermOut)
async def update_term(
    term_id: uuid.UUID,
    body: GlossaryTermUpdate,
    session: AsyncSession = Depends(get_session),
):
    term = await session.get(GlossaryTerm, term_id)
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")

    if body.wrong_forms is not None:
        term.wrong_forms = body.wrong_forms
    if body.scope_type is not None:
        term.scope_type = body.scope_type
    if body.scope_value is not None:
        term.scope_value = body.scope_value
    if body.correct_form is not None:
        term.correct_form = body.correct_form
    if body.category is not None:
        term.category = body.category
    if body.context_hint is not None:
        term.context_hint = body.context_hint

    await session.commit()
    await session.refresh(term)
    return term


@router.delete("/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_term(term_id: uuid.UUID, session: AsyncSession = Depends(get_session)):
    term = await session.get(GlossaryTerm, term_id)
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")
    await session.delete(term)
    await session.commit()
