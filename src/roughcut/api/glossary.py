from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.api.schemas import GlossaryTermCreate, GlossaryTermOut, GlossaryTermUpdate
from roughcut.db.models import GlossaryTerm
from roughcut.db.session import get_session

router = APIRouter(prefix="/glossary", tags=["glossary"])


@router.get("", response_model=list[GlossaryTermOut])
async def list_terms(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(GlossaryTerm).order_by(GlossaryTerm.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=GlossaryTermOut, status_code=status.HTTP_201_CREATED)
async def create_term(
    body: GlossaryTermCreate,
    session: AsyncSession = Depends(get_session),
):
    term = GlossaryTerm(
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
