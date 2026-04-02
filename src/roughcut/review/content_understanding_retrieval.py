from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from roughcut.db.models import ContentProfileEntity


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _tokenize(value: object) -> set[str]:
    text = _normalize_text(value)
    if not text:
        return set()
    return {token for token in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", text) if token}


async def search_confirmed_content_entities(session: AsyncSession, *, search_queries: list[str]) -> list[dict[str, Any]]:
    queries = [_normalize_text(query) for query in search_queries if _normalize_text(query)]
    if not queries:
        return []

    result = await session.execute(
        select(ContentProfileEntity).options(selectinload(ContentProfileEntity.aliases))
    )
    entities = result.scalars().all()
    if not entities:
        return []

    scored_results: list[tuple[int, int, dict[str, Any]]] = []
    for entity in entities:
        alias_values = [
            str(alias.alias_value or "").strip()
            for alias in (entity.aliases or [])
            if str(alias.alias_value or "").strip()
        ]
        primary_subject = _primary_subject_for_entity(entity.brand, entity.model, entity.subject_type)
        searchable_parts = [entity.brand, entity.model, entity.subject_type, primary_subject, *alias_values]
        searchable_tokens = set().union(*(_tokenize(part) for part in searchable_parts if _normalize_text(part)))
        if not searchable_tokens:
            continue

        matched_queries: list[str] = []
        for query in queries:
            query_tokens = _tokenize(query)
            if not query_tokens:
                continue
            if query_tokens & searchable_tokens:
                matched_queries.append(query)
                continue
            query_normalized = _normalize_text(query)
            searchable_text = " ".join(_normalize_text(part) for part in searchable_parts if _normalize_text(part))
            if query_normalized in searchable_text or searchable_text in query_normalized:
                matched_queries.append(query)

        if not matched_queries:
            continue

        payload = {
            "brand": str(entity.brand or "").strip(),
            "model": str(entity.model or "").strip(),
            "primary_subject": primary_subject,
            "subject_type": str(entity.subject_type or "").strip(),
            "subject_domain": str(entity.subject_domain or "").strip(),
            "alias_values": alias_values[:6],
            "matched_queries": matched_queries,
            "evidence_strength": "weak",
            "source_type": "confirmed_entity",
        }
        scored_results.append((len(matched_queries), len(searchable_tokens), payload))

    scored_results.sort(key=lambda item: (-item[0], -item[1], item[2]["primary_subject"], item[2]["brand"], item[2]["model"]))
    return [item[2] for item in scored_results[:8]]


def _primary_subject_for_entity(brand: str, model: str, subject_type: str | None) -> str:
    primary_subject = str(subject_type or "").strip()
    if primary_subject:
        return primary_subject
    combined = " ".join(part for part in (str(brand or "").strip(), str(model or "").strip()) if part).strip()
    return combined
