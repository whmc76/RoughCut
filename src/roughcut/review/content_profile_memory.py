from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.db.models import ContentProfileCorrection, ContentProfileKeywordStat, Job
from roughcut.review.entity_graph import (
    add_entity_aliases,
    load_graph_confirmed_entities,
    load_rejected_alias_pairs,
    record_entity_rejection,
    upsert_content_profile_entity,
)
from roughcut.review.domain_glossaries import _DOMAIN_COMPATIBILITY, normalize_subject_domain


CONTENT_PROFILE_MEMORY_FIELDS = (
    "subject_brand",
    "subject_model",
    "subject_type",
    "video_theme",
)

CONTENT_PROFILE_MEMORY_FIELD_LABELS = {
    "subject_brand": "产品品牌",
    "subject_model": "开箱产品型号",
    "subject_type": "主体类型",
    "video_theme": "视频主题",
}


def _normalize_subject_domain_hint(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized in {"edc_tactical"}:
        return "edc"
    if normalized == "food_explore":
        return "food"
    if normalized == "gameplay_highlight":
        return "game"
    return normalize_subject_domain(normalized)


async def load_content_profile_user_memory(
    session: AsyncSession,
    *,
    subject_domain: str | None = None,
    channel_profile: str | None = None,
    strict_subject_domain: bool = False,
    recent_limit: int = 10,
    keyword_limit: int = 12,
    field_limit: int = 4,
) -> dict[str, Any]:
    if subject_domain is None and channel_profile is not None:
        subject_domain = channel_profile
    subject_domain = _normalize_subject_domain_hint(subject_domain)
    if strict_subject_domain and subject_domain is None:
        return {}
    subject_domains = _expand_subject_domain_scope(subject_domain) if subject_domain else set()
    if subject_domain:
        subject_domains.add(subject_domain)
    correction_result = await session.execute(
        select(ContentProfileCorrection).order_by(ContentProfileCorrection.created_at.desc()).limit(240)
    )
    corrections = correction_result.scalars().all()
    rejected_pairs = await load_rejected_alias_pairs(session, subject_domains=subject_domains)
    filtered_corrections = _filter_rejected_corrections(corrections, rejected_pairs=rejected_pairs)

    keyword_result = await session.execute(select(ContentProfileKeywordStat))
    keyword_stats = keyword_result.scalars().all()

    field_preferences = _build_field_preferences(filtered_corrections, subject_domain=subject_domain, limit=field_limit)
    recent_corrections = _build_recent_corrections(filtered_corrections, subject_domain=subject_domain, limit=recent_limit)
    keyword_preferences = _build_keyword_preferences(keyword_stats, subject_domain=subject_domain, limit=keyword_limit)
    phrase_preferences = _build_phrase_preferences(
        filtered_corrections,
        keyword_stats,
        subject_domain=subject_domain,
        limit=keyword_limit,
    )
    style_preferences = _build_style_preferences(filtered_corrections, subject_domain=subject_domain, limit=6)
    confirmed_entities = await load_graph_confirmed_entities(session, subject_domains=subject_domains, limit=6)
    if not confirmed_entities:
        confirmed_entities = _build_confirmed_entities(filtered_corrections, subject_domain=subject_domain, limit=6)

    if not any([field_preferences, recent_corrections, keyword_preferences, phrase_preferences, style_preferences, confirmed_entities]):
        return {}
    return {
        "field_preferences": field_preferences,
        "recent_corrections": recent_corrections,
        "keyword_preferences": keyword_preferences,
        "phrase_preferences": phrase_preferences,
        "style_preferences": style_preferences,
        "confirmed_entities": confirmed_entities,
    }


def summarize_content_profile_user_memory(user_memory: dict[str, Any] | None) -> str:
    del user_memory
    return ""


def build_content_profile_memory_cloud(user_memory: dict[str, Any] | None) -> dict[str, Any]:
    if not user_memory:
        return {"words": [], "recent_corrections": []}

    words: dict[str, dict[str, Any]] = {}
    field_preferences = user_memory.get("field_preferences") or {}
    for field_name, items in field_preferences.items():
        for index, item in enumerate(items):
            label = _clean_memory_value(item.get("value"))
            if not label:
                continue
            count = max(1, int(item.get("count") or 0))
            weight = min(10, count + _field_word_bonus(field_name) - index)
            _remember_cloud_word(
                words,
                label=label,
                count=count,
                weight=weight,
                kind=field_name,
                hint=f"{CONTENT_PROFILE_MEMORY_FIELD_LABELS.get(field_name, field_name)}偏好",
            )

    keyword_preferences = user_memory.get("keyword_preferences") or []
    for index, item in enumerate(keyword_preferences):
        label = _normalize_keyword(item.get("keyword"))
        if not label:
            continue
        count = max(1, int(item.get("count") or 0))
        weight = min(10, count + 2 - min(index, 3))
        _remember_cloud_word(
            words,
            label=label,
            count=count,
            weight=weight,
            kind="keyword",
            hint="高频关键词",
        )

    phrase_preferences = user_memory.get("phrase_preferences") or []
    for index, item in enumerate(phrase_preferences):
        label = _normalize_keyword(item.get("phrase"))
        if not label:
            continue
        count = max(1, int(item.get("count") or 0))
        weight = min(10, count + 3 - min(index, 4))
        _remember_cloud_word(
            words,
            label=label,
            count=count,
            weight=weight,
            kind="phrase",
            hint="已学习短语",
        )

    ranked_words = sorted(
        words.values(),
        key=lambda item: (-int(item["weight"]), -int(item["count"]), item["label"]),
    )
    return {
        "words": ranked_words[:18],
        "recent_corrections": list(user_memory.get("recent_corrections") or [])[:6],
        "phrases": phrase_preferences[:8],
        "styles": list(user_memory.get("style_preferences") or [])[:6],
    }


async def record_content_profile_feedback_memory(
    session: AsyncSession,
    *,
    job: Job,
    draft_profile: dict[str, Any],
    final_profile: dict[str, Any],
    user_feedback: dict[str, Any],
) -> None:
    recorded_pairs: set[tuple[str, str, str]] = set()
    fallback_subject_domain = _normalize_subject_domain_hint(
        str(final_profile.get("subject_domain") or "")
        or str(getattr(job, "workflow_template", None) or getattr(job, "channel_profile", None) or "")
    )

    def remember_correction(field_name: str, original_value: Any, corrected_value: Any) -> None:
        original = _clean_memory_value(original_value)
        corrected = _clean_memory_value(corrected_value)
        if not corrected:
            return
        correction_key = (field_name, original, corrected)
        if correction_key in recorded_pairs:
            return
        recorded_pairs.add(correction_key)
        session.add(
            ContentProfileCorrection(
                job_id=job.id,
                source_name=job.source_name,
                subject_domain=fallback_subject_domain or "",
                field_name=field_name,
                original_value=original or None,
                corrected_value=corrected,
            )
        )

    for field_name in CONTENT_PROFILE_MEMORY_FIELDS:
        if field_name not in user_feedback:
            continue
        corrected_value = _clean_memory_value(user_feedback.get(field_name))
        if not corrected_value:
            continue
        original_value = _clean_memory_value((draft_profile or {}).get(field_name))
        if corrected_value == original_value:
            continue
        remember_correction(field_name, original_value, corrected_value)

    for field_name, alias_value, corrected_value in _extract_identity_alias_feedback_rows(final_profile):
        remember_correction(field_name, alias_value, corrected_value)

    entity = await upsert_content_profile_entity(
        session,
        subject_domain=fallback_subject_domain or "",
        brand=_clean_memory_value((final_profile or {}).get("subject_brand")),
        model=_clean_memory_value((final_profile or {}).get("subject_model")),
        subject_type=_clean_memory_value((final_profile or {}).get("subject_type")),
        job_id=job.id,
        source_name=job.source_name,
        observation_type="manual_confirm",
        payload={"source": "content_profile_feedback"},
    )
    alias_outcomes = _extract_identity_alias_outcomes(final_profile)
    accepted_brand_aliases = [item["alias_value"] for item in alias_outcomes if item["field_name"] == "subject_brand" and item["status"] == "accepted"]
    accepted_model_aliases = [item["alias_value"] for item in alias_outcomes if item["field_name"] == "subject_model" and item["status"] == "accepted"]
    await add_entity_aliases(session, entity=entity, field_name="subject_brand", aliases=accepted_brand_aliases)
    await add_entity_aliases(session, entity=entity, field_name="subject_model", aliases=accepted_model_aliases)
    for outcome in alias_outcomes:
        if outcome["status"] != "rejected":
            continue
        await record_entity_rejection(
            session,
            job_id=job.id,
            subject_domain=fallback_subject_domain or "",
            field_name=outcome["field_name"],
            alias_value=outcome["alias_value"],
            canonical_value=outcome["canonical_value"],
            override_value=outcome["final_value"],
        )

    raw_keywords = user_feedback.get("keywords")
    keywords = raw_keywords if isinstance(raw_keywords, list) and raw_keywords else final_profile.get("search_queries") or []
    normalized_keywords = []
    seen: set[str] = set()
    for item in keywords:
        keyword = _normalize_keyword(item)
        if keyword and keyword not in seen:
            seen.add(keyword)
            normalized_keywords.append(keyword)

    for keyword in normalized_keywords:
        await _increment_keyword_stat(session, scope_type="global", scope_value="", keyword=keyword)
        final_subject_domain = fallback_subject_domain or ""
        if final_subject_domain:
            await _increment_keyword_stat(
                session,
                scope_type="subject_domain",
                scope_value=final_subject_domain,
                keyword=keyword,
            )


def _extract_identity_alias_feedback_rows(final_profile: dict[str, Any]) -> list[tuple[str, str, str]]:
    outcomes = _extract_identity_alias_outcomes(final_profile)
    return [
        (item["field_name"], item["alias_value"], item["canonical_value"])
        for item in outcomes
        if item["status"] == "accepted"
    ]


def _extract_identity_alias_outcomes(final_profile: dict[str, Any]) -> list[dict[str, str]]:
    identity_review = (final_profile or {}).get("identity_review")
    if not isinstance(identity_review, dict):
        return []
    evidence_bundle = identity_review.get("evidence_bundle")
    if not isinstance(evidence_bundle, dict):
        return []
    matched_glossary_aliases = evidence_bundle.get("matched_glossary_aliases")
    if not isinstance(matched_glossary_aliases, dict):
        return []

    alias_rows: list[dict[str, str]] = []
    field_specs = (
        ("subject_brand", "candidate_brand", "brand"),
        ("subject_model", "candidate_model", "model"),
    )
    for field_name, candidate_key, alias_key in field_specs:
        corrected_value = _clean_memory_value((final_profile or {}).get(field_name))
        candidate_value = _clean_memory_value(evidence_bundle.get(candidate_key))
        for alias in matched_glossary_aliases.get(alias_key) or []:
            alias_value = _clean_memory_value(alias)
            if not alias_value:
                continue
            if corrected_value and corrected_value == candidate_value and alias_value != corrected_value:
                alias_rows.append(
                    {
                        "field_name": field_name,
                        "alias_value": alias_value,
                        "canonical_value": corrected_value,
                        "final_value": corrected_value,
                        "status": "accepted",
                    }
                )
            elif corrected_value and candidate_value and corrected_value != candidate_value:
                alias_rows.append(
                    {
                        "field_name": field_name,
                        "alias_value": alias_value,
                        "canonical_value": candidate_value,
                        "final_value": corrected_value,
                        "status": "rejected",
                    }
                )
    return alias_rows


def _build_field_preferences(
    corrections: list[ContentProfileCorrection],
    *,
    subject_domain: str | None,
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, Counter[str]] = defaultdict(Counter)
    for item in corrections:
        weight = _subject_domain_weight(subject_domain, item.subject_domain)
        if weight <= 0:
            continue
        if item.field_name in CONTENT_PROFILE_MEMORY_FIELDS and item.corrected_value:
            buckets[item.field_name][item.corrected_value] += weight

    return {
        field_name: [
            {"value": value, "count": count}
            for value, count in counter.most_common(limit)
        ]
        for field_name, counter in buckets.items()
        if counter
    }


def _build_recent_corrections(
    corrections: list[ContentProfileCorrection],
    *,
    subject_domain: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in corrections:
        if not _subject_domain_visible(subject_domain, item.subject_domain):
            continue
        items.append(
            {
                "field_name": item.field_name,
                "original_value": item.original_value or "",
                "corrected_value": item.corrected_value,
                "source_name": item.source_name,
            }
        )
        if len(items) >= limit:
            break
    return items


def _filter_rejected_corrections(
    corrections: list[ContentProfileCorrection],
    *,
    rejected_pairs: set[tuple[str, str, str]],
) -> list[ContentProfileCorrection]:
    if not rejected_pairs:
        return corrections
    filtered: list[ContentProfileCorrection] = []
    for item in corrections:
        key = (
            _clean_memory_value(item.field_name),
            _clean_memory_value(item.original_value),
            _clean_memory_value(item.corrected_value),
        )
        if key in rejected_pairs:
            continue
        filtered.append(item)
    return filtered


def _build_keyword_preferences(
    stats: list[ContentProfileKeywordStat],
    *,
    subject_domain: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for item in stats:
        if item.scope_type == "global":
            counts[item.keyword] += int(item.usage_count or 0)
            continue
        if item.scope_type != "subject_domain":
            continue
        weight = _subject_domain_weight(subject_domain, item.scope_value)
        if weight <= 0:
            continue
        counts[item.keyword] += int(item.usage_count or 0) * weight

    return [
        {"keyword": keyword, "count": count}
        for keyword, count in counts.most_common(limit)
    ]


def _build_phrase_preferences(
    corrections: list[ContentProfileCorrection],
    stats: list[ContentProfileKeywordStat],
    *,
    subject_domain: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for item in corrections:
        weight = _subject_domain_weight(subject_domain, item.subject_domain)
        if weight <= 0:
            continue
        for phrase in _extract_learning_phrases(item.corrected_value):
            counts[phrase] += weight

    for item in stats:
        weight = 0
        if item.scope_type == "global":
            weight = max(1, int(item.usage_count or 0))
        elif item.scope_type == "subject_domain":
            scope_weight = _subject_domain_weight(subject_domain, item.scope_value)
            if scope_weight > 0:
                weight = max(1, int(item.usage_count or 0)) * scope_weight
        if weight <= 0:
            continue
        for phrase in _extract_learning_phrases(item.keyword):
            counts[phrase] += weight

    return [{"phrase": phrase, "count": count} for phrase, count in counts.most_common(limit)]


def _build_style_preferences(
    corrections: list[ContentProfileCorrection],
    *,
    subject_domain: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    examples: dict[str, str] = {}
    for item in corrections:
        if item.field_name not in {"video_theme"}:
            continue
        weight = _subject_domain_weight(subject_domain, item.subject_domain)
        if weight <= 0:
            continue
        value = _clean_memory_value(item.corrected_value)
        for tag in _infer_style_tags(value):
            counts[tag] += weight
            examples.setdefault(tag, value)
    return [
        {"tag": tag, "count": count, "example": examples.get(tag, "")}
        for tag, count in counts.most_common(limit)
    ]


def _build_confirmed_entities(
    corrections: list[ContentProfileCorrection],
    *,
    subject_domain: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, str]] = {}
    for item in corrections:
        if not _subject_domain_visible(subject_domain, item.subject_domain):
            continue
        normalized_item_domain = _normalize_subject_domain_hint(item.subject_domain)
        key = (str(normalized_item_domain or ""), str(item.source_name or ""))
        bucket = grouped.setdefault(
            key,
            {
                "subject_domain": str(normalized_item_domain or ""),
                "source_name": str(item.source_name or ""),
                "subject_brand": "",
                "subject_model": "",
                "subject_type": "",
            },
        )
        if item.field_name in {"subject_brand", "subject_model", "subject_type"} and item.corrected_value and not bucket[item.field_name]:
            bucket[item.field_name] = item.corrected_value

    entities: list[dict[str, Any]] = []
    for bucket in grouped.values():
        brand = _clean_memory_value(bucket.get("subject_brand"))
        model = _clean_memory_value(bucket.get("subject_model"))
        subject_type = _clean_memory_value(bucket.get("subject_type"))
        if not brand and not model:
            continue
        phrases: list[str] = []
        combined = _normalize_keyword(f"{brand} {model}".strip())
        if combined:
            phrases.append(combined)
        if model:
            phrases.append(model)
        entity = {
            "brand": brand,
            "model": model,
            "phrases": phrases[:6],
            "model_aliases": [],
            "subject_type": subject_type,
            "subject_domain": _normalize_subject_domain_hint(bucket.get("subject_domain")) or "",
        }
        if entity not in entities:
            entities.append(entity)
        if len(entities) >= limit:
            break
    return entities


def _subject_domain_visible(subject_domain: str | None, item_subject_domain: str | None) -> bool:
    if not subject_domain:
        return True
    normalized_item = _normalize_subject_domain_hint(item_subject_domain)
    if normalized_item is None:
        return True
    return normalized_item in _expand_subject_domain_scope(subject_domain)


def _subject_domain_weight(subject_domain: str | None, item_subject_domain: str | None) -> int:
    if not subject_domain:
        return 1
    normalized_item = _normalize_subject_domain_hint(item_subject_domain)
    if normalized_item is None:
        return 1
    if normalized_item == subject_domain:
        return 2
    if normalized_item in _expand_subject_domain_scope(subject_domain):
        return 1
    return 0


def _expand_subject_domain_scope(subject_domain: str | None) -> set[str]:
    normalized = _normalize_subject_domain_hint(subject_domain)
    if not normalized:
        return set()
    return {normalized, *_DOMAIN_COMPATIBILITY.get(normalized, ())}


async def _increment_keyword_stat(
    session: AsyncSession,
    *,
    scope_type: str,
    scope_value: str,
    keyword: str,
) -> None:
    result = await session.execute(
        select(ContentProfileKeywordStat).where(
            ContentProfileKeywordStat.scope_type == scope_type,
            ContentProfileKeywordStat.scope_value == scope_value,
            ContentProfileKeywordStat.keyword == keyword,
        )
    )
    stat = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if stat is None:
        session.add(
            ContentProfileKeywordStat(
                scope_type=scope_type,
                scope_value=scope_value,
                keyword=keyword,
                usage_count=1,
                last_used_at=now,
            )
        )
        return
    stat.usage_count = int(stat.usage_count or 0) + 1
    stat.last_used_at = now


def _normalize_keyword(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:120]


def _clean_memory_value(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _field_word_bonus(field_name: str) -> int:
    if field_name == "subject_brand":
        return 5
    if field_name == "subject_model":
        return 4
    if field_name == "subject_type":
        return 3
    if field_name == "video_theme":
        return 2
    return 1


def _extract_learning_phrases(value: Any) -> list[str]:
    text = _normalize_keyword(value)
    if not text:
        return []
    phrases: list[str] = []
    seen: set[str] = set()
    for fragment in text.replace("/", " ").replace("｜", " ").split():
        cleaned = fragment.strip(" ,，。；;：:")
        if len(cleaned) < 4 or len(cleaned) > 18:
            continue
        if cleaned in seen:
            continue
        if _looks_like_learning_phrase(cleaned):
            seen.add(cleaned)
            phrases.append(cleaned)
    if not phrases and _looks_like_learning_phrase(text):
        phrases.append(text[:18])
    return phrases


def _looks_like_learning_phrase(text: str) -> bool:
    compact = str(text or "").strip()
    if len(compact) < 4:
        return False
    if re.search(r"[A-Z]{2,}[A-Z0-9-]*\s+[A-Z0-9-]{2,}", compact):
        return True
    hits = 0
    for token in ("顶配", "次顶配", "标配", "高配", "低配", "镜面", "雾面", "折刀", "工具钳", "手电", "打火机", "工作流", "提示词", "节点", "接口", "代码", "部署"):
        if token in compact:
            hits += 1
    return hits >= 2


def _infer_style_tags(value: Any) -> list[str]:
    text = _clean_memory_value(value)
    tags: list[str] = []
    if any(token in text for token in ("开箱", "评测", "上手", "对比")):
        tags.append("review")
    if any(token in text for token in ("教程", "流程", "讲解", "实战")):
        tags.append("tutorial")
    if any(token in text for token in ("炸", "拉满", "真香", "太狠", "离谱")):
        tags.append("high_energy")
    if any(token in text for token in ("细节", "质感", "做工", "工艺")):
        tags.append("detail_focused")
    return tags


def _remember_cloud_word(
    words: dict[str, dict[str, Any]],
    *,
    label: str,
    count: int,
    weight: int,
    kind: str,
    hint: str,
) -> None:
    current = words.get(label)
    item = {
        "label": label,
        "count": count,
        "weight": max(1, min(10, weight)),
        "kind": kind,
        "hint": hint,
    }
    if current is None:
        words[label] = item
        return
    if int(item["weight"]) > int(current["weight"]) or int(item["count"]) > int(current["count"]):
        words[label] = item
