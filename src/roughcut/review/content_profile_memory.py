from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.db.models import ContentProfileCorrection, ContentProfileKeywordStat, Job


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


async def load_content_profile_user_memory(
    session: AsyncSession,
    *,
    channel_profile: str | None,
    recent_limit: int = 10,
    keyword_limit: int = 12,
    field_limit: int = 4,
) -> dict[str, Any]:
    correction_result = await session.execute(
        select(ContentProfileCorrection).order_by(ContentProfileCorrection.created_at.desc()).limit(240)
    )
    corrections = correction_result.scalars().all()

    keyword_result = await session.execute(select(ContentProfileKeywordStat))
    keyword_stats = keyword_result.scalars().all()

    field_preferences = _build_field_preferences(corrections, channel_profile=channel_profile, limit=field_limit)
    recent_corrections = _build_recent_corrections(corrections, channel_profile=channel_profile, limit=recent_limit)
    keyword_preferences = _build_keyword_preferences(keyword_stats, channel_profile=channel_profile, limit=keyword_limit)
    phrase_preferences = _build_phrase_preferences(
        corrections,
        keyword_stats,
        channel_profile=channel_profile,
        limit=keyword_limit,
    )
    style_preferences = _build_style_preferences(corrections, channel_profile=channel_profile, limit=6)

    if not any([field_preferences, recent_corrections, keyword_preferences, phrase_preferences, style_preferences]):
        return {}
    return {
        "field_preferences": field_preferences,
        "recent_corrections": recent_corrections,
        "keyword_preferences": keyword_preferences,
        "phrase_preferences": phrase_preferences,
        "style_preferences": style_preferences,
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
                channel_profile=job.channel_profile,
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
        if job.channel_profile:
            await _increment_keyword_stat(
                session,
                scope_type="channel_profile",
                scope_value=job.channel_profile,
                keyword=keyword,
            )


def _extract_identity_alias_feedback_rows(final_profile: dict[str, Any]) -> list[tuple[str, str, str]]:
    identity_review = (final_profile or {}).get("identity_review")
    if not isinstance(identity_review, dict):
        return []
    evidence_bundle = identity_review.get("evidence_bundle")
    if not isinstance(evidence_bundle, dict):
        return []
    matched_glossary_aliases = evidence_bundle.get("matched_glossary_aliases")
    if not isinstance(matched_glossary_aliases, dict):
        return []

    alias_rows: list[tuple[str, str, str]] = []
    field_specs = (
        ("subject_brand", "candidate_brand", "brand"),
        ("subject_model", "candidate_model", "model"),
    )
    for field_name, candidate_key, alias_key in field_specs:
        corrected_value = _clean_memory_value((final_profile or {}).get(field_name))
        candidate_value = _clean_memory_value(evidence_bundle.get(candidate_key))
        if not corrected_value or corrected_value != candidate_value:
            continue
        for alias in matched_glossary_aliases.get(alias_key) or []:
            alias_value = _clean_memory_value(alias)
            if not alias_value or alias_value == corrected_value:
                continue
            alias_rows.append((field_name, alias_value, corrected_value))
    return alias_rows


def _build_field_preferences(
    corrections: list[ContentProfileCorrection],
    *,
    channel_profile: str | None,
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, Counter[str]] = defaultdict(Counter)
    for item in corrections:
        weight = 2 if channel_profile and item.channel_profile == channel_profile else 1
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
    channel_profile: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in corrections:
        if channel_profile and item.channel_profile not in {None, channel_profile}:
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


def _build_keyword_preferences(
    stats: list[ContentProfileKeywordStat],
    *,
    channel_profile: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for item in stats:
        if item.scope_type == "global":
            counts[item.keyword] += int(item.usage_count or 0)
        elif channel_profile and item.scope_type == "channel_profile" and item.scope_value == channel_profile:
            counts[item.keyword] += int(item.usage_count or 0) * 2

    return [
        {"keyword": keyword, "count": count}
        for keyword, count in counts.most_common(limit)
    ]


def _build_phrase_preferences(
    corrections: list[ContentProfileCorrection],
    stats: list[ContentProfileKeywordStat],
    *,
    channel_profile: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for item in corrections:
        if channel_profile and item.channel_profile not in {None, channel_profile}:
            continue
        for phrase in _extract_learning_phrases(item.corrected_value):
            counts[phrase] += 2 if channel_profile and item.channel_profile == channel_profile else 1

    for item in stats:
        weight = 0
        if item.scope_type == "global":
            weight = max(1, int(item.usage_count or 0))
        elif channel_profile and item.scope_type == "channel_profile" and item.scope_value == channel_profile:
            weight = max(1, int(item.usage_count or 0)) * 2
        if weight <= 0:
            continue
        for phrase in _extract_learning_phrases(item.keyword):
            counts[phrase] += weight

    return [{"phrase": phrase, "count": count} for phrase, count in counts.most_common(limit)]


def _build_style_preferences(
    corrections: list[ContentProfileCorrection],
    *,
    channel_profile: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    examples: dict[str, str] = {}
    for item in corrections:
        if item.field_name not in {"video_theme"}:
            continue
        if channel_profile and item.channel_profile not in {None, channel_profile}:
            continue
        value = _clean_memory_value(item.corrected_value)
        for tag in _infer_style_tags(value):
            counts[tag] += 2 if channel_profile and item.channel_profile == channel_profile else 1
            examples.setdefault(tag, value)
    return [
        {"tag": tag, "count": count, "example": examples.get(tag, "")}
        for tag, count in counts.most_common(limit)
    ]


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
