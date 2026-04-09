from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from roughcut.db.models import ContentProfileEntity
from roughcut.review.domain_glossaries import list_builtin_glossary_packs


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _tokenize(value: object) -> set[str]:
    text = _normalize_text(value)
    if not text:
        return set()
    return {token for token in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+", text) if token}


@dataclass(frozen=True)
class EntityCatalogCandidate:
    brand: str = ""
    model: str = ""
    primary_subject: str = ""
    subject_type: str = ""
    subject_domain: str = ""
    source_type: str = "entity_catalog"
    source_origins: list[str] | None = None
    matched_queries: list[str] | None = None
    matched_evidence_texts: list[str] | None = None
    matched_aliases: dict[str, list[str]] | None = None
    matched_fields: list[str] | None = None
    evidence_strength: str = "weak"
    support_score: float = 0.0
    confidence: float = 0.0


async def search_confirmed_content_entities(
    session: AsyncSession,
    *,
    search_queries: list[str],
    subject_domain: str | None = None,
    evidence_texts: list[str] | None = None,
    glossary_terms: list[dict[str, Any]] | None = None,
    confirmed_entities: list[dict[str, Any]] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    queries = [_normalize_text(query) for query in search_queries if _normalize_text(query)]
    evidence_fragments = [
        str(fragment).strip()
        for fragment in (evidence_texts or [])
        if str(fragment).strip()
    ]
    if not queries and not evidence_fragments:
        return []

    result = await session.execute(
        select(ContentProfileEntity).options(selectinload(ContentProfileEntity.aliases))
    )
    entities = result.scalars().all()
    raw_candidates = _build_graph_candidates(entities)
    raw_candidates.extend(_build_confirmed_entity_candidates(confirmed_entities))

    glossary_library = _collect_glossary_terms(glossary_terms, subject_domain=subject_domain)
    glossary_hits = _match_glossary_terms(
        glossary_library,
        search_queries=search_queries,
        evidence_texts=evidence_fragments,
    )

    candidate_map: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for raw_candidate in raw_candidates:
        scored = _score_entity_candidate(
            raw_candidate,
            search_queries=search_queries,
            normalized_queries=queries,
            evidence_texts=evidence_fragments,
            subject_domain=subject_domain,
            glossary_hits=glossary_hits,
        )
        if scored is None:
            continue
        _merge_candidate(candidate_map, scored)

    for scored in _build_glossary_only_candidates(
        glossary_hits,
        subject_domain=subject_domain,
        search_queries=search_queries,
        evidence_texts=evidence_fragments,
    ):
        _merge_candidate(candidate_map, scored)

    ranked_results = sorted(
        candidate_map.values(),
        key=lambda item: (
            -float(item.get("support_score") or 0.0),
            -len(item.get("matched_evidence_texts") or []),
            -len(item.get("matched_queries") or []),
            item.get("primary_subject") or "",
            item.get("brand") or "",
            item.get("model") or "",
        ),
    )
    return ranked_results[:limit]


def _primary_subject_for_entity(brand: str, model: str, subject_type: str | None) -> str:
    primary_subject = str(subject_type or "").strip()
    if primary_subject:
        return primary_subject
    combined = " ".join(part for part in (str(brand or "").strip(), str(model or "").strip()) if part).strip()
    return combined


def _build_graph_candidates(entities: list[ContentProfileEntity]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for entity in entities:
        brand_aliases: list[str] = []
        model_aliases: list[str] = []
        for alias in entity.aliases or []:
            alias_value = str(alias.alias_value or "").strip()
            if not alias_value:
                continue
            if str(alias.field_name or "").strip() == "subject_brand":
                brand_aliases.append(alias_value)
            elif str(alias.field_name or "").strip() == "subject_model":
                model_aliases.append(alias_value)
        primary_subject = _primary_subject_for_entity(entity.brand, entity.model, entity.subject_type)
        candidates.append(
            {
                "brand": str(entity.brand or "").strip(),
                "model": str(entity.model or "").strip(),
                "primary_subject": primary_subject,
                "subject_type": str(entity.subject_type or "").strip(),
                "subject_domain": str(entity.subject_domain or "").strip(),
                "phrases": [item for item in [primary_subject, f"{entity.brand} {entity.model}".strip(), entity.model] if str(item).strip()],
                "brand_aliases": brand_aliases,
                "model_aliases": model_aliases,
                "source_type": "confirmed_entity",
                "source_origins": ["entity_graph"],
            }
        )
    return candidates


def _build_confirmed_entity_candidates(confirmed_entities: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in confirmed_entities or []:
        if not isinstance(item, dict):
            continue
        brand = str(item.get("brand") or "").strip()
        model = str(item.get("model") or "").strip()
        subject_type = str(item.get("subject_type") or "").strip()
        primary_subject = _primary_subject_for_entity(brand, model, subject_type)
        candidates.append(
            {
                "brand": brand,
                "model": model,
                "primary_subject": primary_subject,
                "subject_type": subject_type,
                "subject_domain": str(item.get("subject_domain") or "").strip(),
                "phrases": [str(value).strip() for value in list(item.get("phrases") or []) if str(value).strip()],
                "brand_aliases": [str(value).strip() for value in list(item.get("brand_aliases") or []) if str(value).strip()],
                "model_aliases": _normalize_model_aliases(item.get("model_aliases")),
                "source_type": "memory_confirmed_entity",
                "source_origins": ["content_profile_memory"],
            }
        )
    return candidates


def _normalize_model_aliases(value: Any) -> list[str]:
    aliases: list[str] = []
    for item in list(value or []):
        if isinstance(item, dict):
            wrong = str(item.get("wrong") or item.get("alias") or item.get("value") or "").strip()
            if wrong:
                aliases.append(wrong)
            correct = str(item.get("correct") or "").strip()
            if correct:
                aliases.append(correct)
            continue
        text = str(item or "").strip()
        if text:
            aliases.append(text)
    return list(dict.fromkeys(aliases))


def _collect_glossary_terms(
    glossary_terms: list[dict[str, Any]] | None,
    *,
    subject_domain: str | None,
) -> list[dict[str, Any]]:
    terms: list[dict[str, Any]] = []
    builtin_packs = list_builtin_glossary_packs()
    visible_domains = {str(pack.get("domain") or "").strip().lower() for pack in builtin_packs}
    normalized_subject_domain = str(subject_domain or "").strip().lower()
    for pack in builtin_packs:
        pack_domain = str(pack.get("domain") or "").strip().lower()
        if normalized_subject_domain and normalized_subject_domain in visible_domains and pack_domain and pack_domain != normalized_subject_domain:
            continue
        for item in list(pack.get("terms") or []):
            if isinstance(item, dict):
                terms.append(dict(item))
    for item in glossary_terms or []:
        if isinstance(item, dict):
            terms.append(dict(item))
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for term in terms:
        correct_form = str(term.get("correct_form") or "").strip()
        category = str(term.get("category") or "").strip().lower()
        if not correct_form:
            continue
        deduped[(correct_form, category)] = term
    return list(deduped.values())


def _match_glossary_terms(
    glossary_terms: list[dict[str, Any]],
    *,
    search_queries: list[str],
    evidence_texts: list[str],
) -> dict[str, dict[str, Any]]:
    fragments = [str(item).strip() for item in [*search_queries, *evidence_texts] if str(item).strip()]
    matched_brands: dict[str, dict[str, Any]] = {}
    matched_models: dict[str, dict[str, Any]] = {}
    for term in glossary_terms:
        correct_form = str(term.get("correct_form") or "").strip()
        category = str(term.get("category") or "").strip().lower()
        if not correct_form or not category.endswith(("_brand", "_model")):
            continue
        aliases = [correct_form]
        aliases.extend(str(item).strip() for item in list(term.get("wrong_forms") or []) if str(item).strip())
        matched_fragments: list[str] = []
        matched_aliases: list[str] = []
        for fragment in fragments:
            normalized_fragment = _normalize_text(fragment)
            if not normalized_fragment:
                continue
            for alias in aliases:
                normalized_alias = _normalize_text(alias)
                if not normalized_alias:
                    continue
                if normalized_alias in normalized_fragment or normalized_fragment in normalized_alias:
                    matched_fragments.append(fragment)
                    matched_aliases.append(alias)
                    break
        if not matched_fragments:
            continue
        payload = {
            "canonical": correct_form,
            "category": category,
            "domain": str(term.get("domain") or "").strip(),
            "matched_aliases": list(dict.fromkeys(matched_aliases)),
            "matched_fragments": list(dict.fromkeys(matched_fragments)),
        }
        target = matched_brands if category.endswith("_brand") else matched_models
        target[correct_form] = payload
    return {"brands": matched_brands, "models": matched_models}


def _score_entity_candidate(
    candidate: dict[str, Any],
    *,
    search_queries: list[str],
    normalized_queries: list[str],
    evidence_texts: list[str],
    subject_domain: str | None,
    glossary_hits: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    brand = str(candidate.get("brand") or "").strip()
    model = str(candidate.get("model") or "").strip()
    subject_type = str(candidate.get("subject_type") or "").strip()
    subject_domain_value = str(candidate.get("subject_domain") or "").strip()
    primary_subject = _primary_subject_for_entity(brand, model, subject_type)
    phrases = [str(item).strip() for item in list(candidate.get("phrases") or []) if str(item).strip()]
    brand_aliases = [str(item).strip() for item in list(candidate.get("brand_aliases") or []) if str(item).strip()]
    model_aliases = [str(item).strip() for item in list(candidate.get("model_aliases") or []) if str(item).strip()]
    searchable_parts = [brand, model, subject_type, primary_subject, *phrases, *brand_aliases, *model_aliases]
    searchable_tokens = set().union(*(_tokenize(part) for part in searchable_parts if _normalize_text(part)))
    searchable_text = " ".join(_normalize_text(part) for part in searchable_parts if _normalize_text(part))
    if not searchable_tokens and not searchable_text:
        return None

    matched_queries: list[str] = []
    for query, normalized_query in zip(search_queries, normalized_queries):
        query_tokens = _tokenize(normalized_query)
        if query_tokens and query_tokens & searchable_tokens:
            matched_queries.append(query)
            continue
        if normalized_query and (normalized_query in searchable_text or searchable_text in normalized_query):
            matched_queries.append(query)

    matched_evidence_texts = [
        fragment
        for fragment in evidence_texts
        if _fragment_matches_candidate(fragment, searchable_parts)
    ]

    matched_aliases = {
        "brand": [alias for alias in brand_aliases if _alias_hits_fragments(alias, evidence_texts, search_queries)],
        "model": [alias for alias in model_aliases if _alias_hits_fragments(alias, evidence_texts, search_queries)],
    }
    if brand and brand in glossary_hits["brands"]:
        matched_aliases["brand"].extend(glossary_hits["brands"][brand]["matched_aliases"])
    if model and model in glossary_hits["models"]:
        matched_aliases["model"].extend(glossary_hits["models"][model]["matched_aliases"])
    matched_aliases = {
        key: list(dict.fromkeys(value))
        for key, value in matched_aliases.items()
        if value
    }

    query_score = min(0.3, 0.08 * len(matched_queries))
    evidence_score = min(0.35, 0.1 * len(matched_evidence_texts))
    alias_score = min(0.2, 0.06 * sum(len(value) for value in matched_aliases.values()))
    source_bonus = 0.18 if "entity_graph" in list(candidate.get("source_origins") or []) else 0.14
    domain_bonus = 0.08 if subject_domain and subject_domain_value and subject_domain_value == str(subject_domain).strip() else 0.0
    exact_bonus = 0.0
    for fragment in [*search_queries, *evidence_texts]:
        normalized_fragment = _normalize_text(fragment)
        combined = _normalize_text(f"{brand} {model}".strip())
        if combined and combined in normalized_fragment:
            exact_bonus = 0.18
            break
        if primary_subject and _normalize_text(primary_subject) in normalized_fragment:
            exact_bonus = max(exact_bonus, 0.14)
    support_score = min(0.99, source_bonus + query_score + evidence_score + alias_score + domain_bonus + exact_bonus)
    if support_score < 0.18:
        return None

    matched_fields: list[str] = []
    if matched_queries:
        matched_fields.append("search_queries")
    if matched_evidence_texts:
        matched_fields.append("video_evidence")
    if matched_aliases.get("brand"):
        matched_fields.append("brand_alias")
    if matched_aliases.get("model"):
        matched_fields.append("model_alias")
    if subject_domain and subject_domain_value == str(subject_domain).strip():
        matched_fields.append("subject_domain")

    evidence_strength = "strong" if support_score >= 0.78 else "moderate" if support_score >= 0.48 else "weak"
    payload = EntityCatalogCandidate(
        brand=brand,
        model=model,
        primary_subject=primary_subject,
        subject_type=subject_type,
        subject_domain=subject_domain_value,
        source_type=str(candidate.get("source_type") or "entity_catalog"),
        source_origins=list(dict.fromkeys(str(item).strip() for item in list(candidate.get("source_origins") or []) if str(item).strip())),
        matched_queries=list(dict.fromkeys(matched_queries)),
        matched_evidence_texts=list(dict.fromkeys(matched_evidence_texts))[:6],
        matched_aliases=matched_aliases,
        matched_fields=matched_fields,
        evidence_strength=evidence_strength,
        support_score=round(support_score, 3),
        confidence=round(min(0.99, support_score + (0.06 if exact_bonus else 0.0)), 3),
    )
    return asdict(payload)


def _fragment_matches_candidate(fragment: str, searchable_parts: list[str]) -> bool:
    normalized_fragment = _normalize_text(fragment)
    if not normalized_fragment:
        return False
    for part in searchable_parts:
        normalized_part = _normalize_text(part)
        if not normalized_part:
            continue
        if normalized_part in normalized_fragment or normalized_fragment in normalized_part:
            return True
    return False


def _alias_hits_fragments(alias: str, evidence_texts: list[str], search_queries: list[str]) -> bool:
    normalized_alias = _normalize_text(alias)
    if not normalized_alias:
        return False
    for fragment in [*evidence_texts, *search_queries]:
        normalized_fragment = _normalize_text(fragment)
        if normalized_alias and normalized_fragment and normalized_alias in normalized_fragment:
            return True
    return False


def _build_glossary_only_candidates(
    glossary_hits: dict[str, dict[str, Any]],
    *,
    subject_domain: str | None,
    search_queries: list[str],
    evidence_texts: list[str],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    brands = glossary_hits.get("brands") or {}
    models = glossary_hits.get("models") or {}
    if not brands and not models:
        return []

    matched_pairs: set[tuple[str, str]] = set()
    fragments = [str(item).strip() for item in [*search_queries, *evidence_texts] if str(item).strip()]
    for fragment in fragments:
        normalized_fragment = _normalize_text(fragment)
        if not normalized_fragment:
            continue
        fragment_brands = [
            canonical
            for canonical, item in brands.items()
            if any(_normalize_text(alias) in normalized_fragment for alias in item.get("matched_aliases") or [canonical])
        ]
        fragment_models = [
            canonical
            for canonical, item in models.items()
            if any(_normalize_text(alias) in normalized_fragment for alias in item.get("matched_aliases") or [canonical])
        ]
        for brand in fragment_brands or [""]:
            for model in fragment_models or [""]:
                if brand or model:
                    matched_pairs.add((brand, model))

    for brand, model in matched_pairs:
        brand_payload = brands.get(brand, {}) if brand else {}
        model_payload = models.get(model, {}) if model else {}
        matched_queries = [
            fragment
            for fragment in search_queries
            if _fragment_matches_candidate(fragment, [brand, model, f"{brand} {model}".strip()])
        ]
        matched_evidence_texts = [
            fragment
            for fragment in evidence_texts
            if _fragment_matches_candidate(fragment, [brand, model, f"{brand} {model}".strip()])
        ]
        matched_aliases = {
            "brand": list(brand_payload.get("matched_aliases") or []),
            "model": list(model_payload.get("matched_aliases") or []),
        }
        matched_aliases = {key: value for key, value in matched_aliases.items() if value}
        support_score = 0.24
        support_score += min(0.18, 0.08 * len(matched_queries))
        support_score += min(0.2, 0.1 * len(matched_evidence_texts))
        support_score += min(0.18, 0.06 * sum(len(value) for value in matched_aliases.values()))
        if brand and model:
            support_score += 0.12
        payload = EntityCatalogCandidate(
            brand=brand,
            model=model,
            primary_subject=_primary_subject_for_entity(brand, model, ""),
            subject_type="",
            subject_domain=str(subject_domain or model_payload.get("domain") or brand_payload.get("domain") or "").strip(),
            source_type="glossary_entity_candidate",
            source_origins=["builtin_glossary"],
            matched_queries=list(dict.fromkeys(matched_queries)),
            matched_evidence_texts=list(dict.fromkeys(matched_evidence_texts))[:6],
            matched_aliases=matched_aliases,
            matched_fields=["glossary_alias", *([ "search_queries"] if matched_queries else []), *([ "video_evidence"] if matched_evidence_texts else [])],
            evidence_strength="moderate" if support_score >= 0.52 else "weak",
            support_score=round(min(0.99, support_score), 3),
            confidence=round(min(0.99, support_score + (0.04 if brand and model else 0.0)), 3),
        )
        candidates.append(asdict(payload))
    return candidates


def _merge_candidate(candidate_map: dict[tuple[str, str, str, str], dict[str, Any]], candidate: dict[str, Any]) -> None:
    key = (
        str(candidate.get("brand") or "").strip(),
        str(candidate.get("model") or "").strip(),
        str(candidate.get("subject_type") or "").strip(),
        str(candidate.get("subject_domain") or "").strip(),
    )
    existing = candidate_map.get(key)
    if existing is None:
        candidate_map[key] = candidate
        return
    for field_name in ("matched_queries", "matched_evidence_texts", "matched_fields", "source_origins"):
        merged = list(dict.fromkeys([*list(existing.get(field_name) or []), *list(candidate.get(field_name) or [])]))
        existing[field_name] = merged
    merged_aliases: dict[str, list[str]] = {}
    for field_name in ("brand", "model"):
        merged_aliases[field_name] = list(
            dict.fromkeys(
                [
                    *list((existing.get("matched_aliases") or {}).get(field_name) or []),
                    *list((candidate.get("matched_aliases") or {}).get(field_name) or []),
                ]
            )
        )
    existing["matched_aliases"] = {key: value for key, value in merged_aliases.items() if value}
    existing["support_score"] = round(max(float(existing.get("support_score") or 0.0), float(candidate.get("support_score") or 0.0)), 3)
    existing["confidence"] = round(max(float(existing.get("confidence") or 0.0), float(candidate.get("confidence") or 0.0)), 3)
    strength_rank = {"weak": 0, "moderate": 1, "strong": 2}
    current_strength = str(existing.get("evidence_strength") or "weak")
    new_strength = str(candidate.get("evidence_strength") or "weak")
    if strength_rank.get(new_strength, 0) > strength_rank.get(current_strength, 0):
        existing["evidence_strength"] = new_strength
