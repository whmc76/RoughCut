from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.db.models import (
    ContentProfileEntity,
    ContentProfileEntityAlias,
    ContentProfileEntityObservation,
    ContentProfileEntityRejection,
)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


async def upsert_content_profile_entity(
    session: AsyncSession,
    *,
    subject_domain: str,
    brand: str,
    model: str,
    subject_type: str = "",
    job_id=None,
    source_name: str = "",
    observation_type: str = "manual_confirm",
    payload: dict[str, Any] | None = None,
) -> ContentProfileEntity | None:
    subject_domain = _clean(subject_domain)
    brand = _clean(brand)
    model = _clean(model)
    subject_type = _clean(subject_type)
    if not brand and not model:
        return None

    result = await session.execute(
        select(ContentProfileEntity).where(
            ContentProfileEntity.subject_domain == subject_domain,
            ContentProfileEntity.brand == brand,
            ContentProfileEntity.model == model,
        )
    )
    entity = result.scalar_one_or_none()
    if entity is None:
        entity = ContentProfileEntity(
            subject_domain=subject_domain,
            brand=brand,
            model=model,
            subject_type=subject_type or None,
        )
        session.add(entity)
        await session.flush()
    elif subject_type and not _clean(entity.subject_type):
        entity.subject_type = subject_type

    session.add(
        ContentProfileEntityObservation(
            entity_id=entity.id,
            job_id=job_id,
            source_name=_clean(source_name) or None,
            observation_type=observation_type,
            payload_json=dict(payload or {}),
        )
    )
    return entity


async def add_entity_aliases(
    session: AsyncSession,
    *,
    entity: ContentProfileEntity | None,
    field_name: str,
    aliases: list[str],
) -> None:
    if entity is None:
        return
    canonical = _clean(entity.brand if field_name == "subject_brand" else entity.model)
    for alias in aliases:
        alias_value = _clean(alias)
        if not alias_value or alias_value == canonical:
            continue
        existing = await session.execute(
            select(ContentProfileEntityAlias).where(
                ContentProfileEntityAlias.entity_id == entity.id,
                ContentProfileEntityAlias.field_name == field_name,
                ContentProfileEntityAlias.alias_value == alias_value,
            )
        )
        if existing.scalar_one_or_none() is None:
            session.add(
                ContentProfileEntityAlias(
                    entity_id=entity.id,
                    field_name=field_name,
                    alias_value=alias_value,
                )
            )


async def record_entity_rejection(
    session: AsyncSession,
    *,
    job_id,
    subject_domain: str,
    field_name: str,
    alias_value: str,
    canonical_value: str,
    override_value: str,
) -> None:
    subject_domain = _clean(subject_domain)
    field_name = _clean(field_name)
    alias_value = _clean(alias_value)
    canonical_value = _clean(canonical_value)
    override_value = _clean(override_value)
    if not all((field_name, alias_value, canonical_value, override_value)):
        return
    existing = await session.execute(
        select(ContentProfileEntityRejection).where(
            ContentProfileEntityRejection.subject_domain == subject_domain,
            ContentProfileEntityRejection.field_name == field_name,
            ContentProfileEntityRejection.alias_value == alias_value,
            ContentProfileEntityRejection.canonical_value == canonical_value,
            ContentProfileEntityRejection.override_value == override_value,
        )
    )
    if existing.scalar_one_or_none() is None:
        session.add(
            ContentProfileEntityRejection(
                job_id=job_id,
                subject_domain=subject_domain,
                field_name=field_name,
                alias_value=alias_value,
                canonical_value=canonical_value,
                override_value=override_value,
            )
        )


async def load_graph_confirmed_entities(
    session: AsyncSession,
    *,
    subject_domains: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    if not subject_domains:
        return []
    result = await session.execute(
        select(ContentProfileEntity).where(ContentProfileEntity.subject_domain.in_(sorted(subject_domains)))
    )
    entities = result.scalars().all()
    if not entities:
        return []

    alias_result = await session.execute(
        select(ContentProfileEntityAlias).where(
            ContentProfileEntityAlias.entity_id.in_([entity.id for entity in entities])
        )
    )
    aliases = alias_result.scalars().all()
    alias_map: dict[Any, dict[str, list[str]]] = defaultdict(lambda: {"subject_brand": [], "subject_model": []})
    for alias in aliases:
        alias_map[alias.entity_id][alias.field_name].append(_clean(alias.alias_value))

    observation_result = await session.execute(
        select(ContentProfileEntityObservation).where(
            ContentProfileEntityObservation.entity_id.in_([entity.id for entity in entities])
        )
    )
    observations = observation_result.scalars().all()
    observation_counts: dict[Any, int] = defaultdict(int)
    for observation in observations:
        observation_counts[observation.entity_id] += 1

    items: list[dict[str, Any]] = []
    for entity in sorted(
        entities,
        key=lambda item: (-observation_counts.get(item.id, 0), item.subject_domain, item.brand, item.model),
    ):
        brand_aliases = [alias for alias in alias_map[entity.id]["subject_brand"] if alias]
        model_aliases = [alias for alias in alias_map[entity.id]["subject_model"] if alias]
        phrases: list[str] = []
        combined = _clean(f"{entity.brand} {entity.model}".strip())
        if combined:
            phrases.append(combined)
        if entity.model:
            phrases.append(_clean(entity.model))
        phrases.extend(brand_aliases)
        phrases.extend(model_aliases)
        deduped_phrases: list[str] = []
        seen: set[str] = set()
        for phrase in phrases:
            cleaned = _clean(phrase)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            deduped_phrases.append(cleaned)
        items.append(
            {
                "brand": _clean(entity.brand),
                "model": _clean(entity.model),
                "phrases": deduped_phrases[:6],
                "brand_aliases": brand_aliases[:6],
                "model_aliases": model_aliases[:6],
                "subject_type": _clean(entity.subject_type),
                "subject_domain": _clean(entity.subject_domain),
            }
        )
        if len(items) >= limit:
            break
    return items


async def load_rejected_alias_pairs(
    session: AsyncSession,
    *,
    subject_domains: set[str],
) -> set[tuple[str, str, str]]:
    if not subject_domains:
        return set()
    result = await session.execute(
        select(ContentProfileEntityRejection).where(
            ContentProfileEntityRejection.subject_domain.in_(sorted(subject_domains))
        )
    )
    rejections = result.scalars().all()
    return {
        (_clean(item.field_name), _clean(item.alias_value), _clean(item.canonical_value))
        for item in rejections
        if _clean(item.alias_value) and _clean(item.canonical_value)
    }
