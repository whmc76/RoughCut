from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.db.models import Job, LearnedHotword
from roughcut.review.domain_glossaries import _RELATED_DOMAINS, normalize_subject_domain


_GENERIC_HOTWORD_BLOCKLIST = {
    "开箱",
    "评测",
    "视频",
    "产品",
    "这个",
    "那个",
    "今天",
    "我们",
    "大家",
    "喜欢",
    "关注",
    "点赞",
    "收藏",
}


def normalize_hotword_token(value: Any) -> str:
    return " ".join(str(value or "").strip().split())[:80]


def extract_prompt_hotwords(prompt: str | None) -> list[str]:
    text = str(prompt or "").strip()
    if not text:
        return []
    hotwords: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"热词：([^。]+)", text):
        for token in re.split(r"[,，/]\s*", match.group(1)):
            cleaned = normalize_hotword_token(token)
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                hotwords.append(cleaned)
    return hotwords


def _normalized_subject_domain(value: Any) -> str:
    normalized = normalize_subject_domain(str(value or "").strip())
    return normalized or str(value or "").strip().lower()


def _subject_domain_scope(subject_domain: str | None) -> set[str]:
    normalized = _normalized_subject_domain(subject_domain)
    if not normalized:
        return {""}
    return {"", normalized, *_RELATED_DOMAINS.get(normalized, ())}


def _is_learnable_hotword(value: Any) -> bool:
    token = normalize_hotword_token(value)
    if len(token) < 2 or len(token) > 48:
        return False
    if token in _GENERIC_HOTWORD_BLOCKLIST:
        return False
    if token.isdigit():
        return False
    if not re.search(r"[A-Za-z0-9\u4e00-\u9fff]", token):
        return False
    if len(re.findall(r"[\u4e00-\u9fff]", token)) >= 16 and not re.search(r"[A-Za-z0-9]", token):
        return False
    return True


def _dedupe_aliases(values: list[str], *, term: str, canonical_form: str) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = {term, canonical_form}
    for value in values:
        alias = normalize_hotword_token(value)
        if not alias or alias in seen:
            continue
        seen.add(alias)
        aliases.append(alias)
    return aliases[:12]


async def upsert_learned_hotword(
    session: AsyncSession,
    *,
    subject_domain: str | None,
    term: Any,
    canonical_form: Any = "",
    aliases: list[str] | None = None,
    source: str = "content_profile_feedback",
    confidence: float = 0.65,
    positive: bool = True,
    metadata: dict[str, Any] | None = None,
) -> LearnedHotword | None:
    learned_term = normalize_hotword_token(term)
    canonical = normalize_hotword_token(canonical_form) or learned_term
    if not _is_learnable_hotword(learned_term):
        return None
    if not _is_learnable_hotword(canonical):
        canonical = learned_term

    normalized_domain = _normalized_subject_domain(subject_domain)
    result = await session.execute(
        select(LearnedHotword).where(
            LearnedHotword.subject_domain == normalized_domain,
            LearnedHotword.term == learned_term,
            LearnedHotword.canonical_form == canonical,
            LearnedHotword.source == source,
        )
    )
    row = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    next_confidence = max(0.0, min(1.0, float(confidence or 0.0)))
    merged_aliases = _dedupe_aliases(list(aliases or []), term=learned_term, canonical_form=canonical)
    if row is None:
        row = LearnedHotword(
            subject_domain=normalized_domain,
            term=learned_term,
            canonical_form=canonical,
            aliases=merged_aliases,
            source=source,
            status="active" if positive else "suppressed",
            evidence_count=1,
            positive_count=1 if positive else 0,
            negative_count=0 if positive else 1,
            confidence=next_confidence,
            metadata_json=dict(metadata or {}),
            last_seen_at=now,
        )
        session.add(row)
        return row

    row.evidence_count = int(row.evidence_count or 0) + 1
    if positive:
        row.positive_count = int(row.positive_count or 0) + 1
        if row.status != "rejected":
            row.status = "active"
    else:
        row.negative_count = int(row.negative_count or 0) + 1
        if int(row.negative_count or 0) > int(row.positive_count or 0):
            row.status = "suppressed"
    row.confidence = max(float(row.confidence or 0.0), next_confidence)
    row.aliases = _dedupe_aliases([*(row.aliases or []), *merged_aliases], term=learned_term, canonical_form=canonical)
    row.metadata_json = {**(row.metadata_json or {}), **dict(metadata or {})} or None
    row.last_seen_at = now
    row.updated_at = now
    return row


def _collect_feedback_hotwords(
    *,
    final_profile: dict[str, Any],
    user_feedback: dict[str, Any],
) -> list[tuple[str, str, float]]:
    candidates: list[tuple[str, str, float]] = []

    def append(field: str, value: Any, confidence: float) -> None:
        token = normalize_hotword_token(value)
        if _is_learnable_hotword(token):
            candidates.append((field, token, confidence))

    for field, confidence in (
        ("subject_brand", 0.92),
        ("subject_model", 0.95),
        ("subject_type", 0.78),
    ):
        append(field, final_profile.get(field), confidence)

    raw_keywords = user_feedback.get("keywords")
    keywords = raw_keywords if isinstance(raw_keywords, list) and raw_keywords else final_profile.get("search_queries") or []
    for item in keywords:
        append("keyword", item, 0.72)

    for field in ("visible_text", "video_theme"):
        append(field, final_profile.get(field), 0.66)

    deduped: list[tuple[str, str, float]] = []
    seen: set[str] = set()
    for field, token, confidence in candidates:
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append((field, token, confidence))
    return deduped[:18]


async def record_learned_hotwords_from_content_profile_feedback(
    session: AsyncSession,
    *,
    job: Job,
    final_profile: dict[str, Any],
    user_feedback: dict[str, Any],
    subject_domain: str | None,
) -> None:
    metadata = {
        "job_id": str(job.id),
        "source_name": str(job.source_name or ""),
        "feedback_source": "content_profile_feedback",
    }
    for field, term, confidence in _collect_feedback_hotwords(
        final_profile=final_profile or {},
        user_feedback=user_feedback or {},
    ):
        await upsert_learned_hotword(
            session,
            subject_domain=subject_domain,
            term=term,
            canonical_form=term,
            source=f"content_profile:{field}",
            confidence=confidence,
            positive=True,
            metadata=metadata,
        )


def score_learned_hotword(item: dict[str, Any], *, subject_domain: str | None = None) -> float:
    positive_count = int(item.get("positive_count") or 0)
    negative_count = int(item.get("negative_count") or 0)
    evidence_count = int(item.get("evidence_count") or 0)
    confidence = float(item.get("confidence") or 0.0)
    score = confidence * 10.0 + positive_count * 1.5 + min(6, evidence_count) - negative_count * 2.0
    item_domain = _normalized_subject_domain(item.get("subject_domain"))
    current_domain = _normalized_subject_domain(subject_domain)
    if current_domain and item_domain == current_domain:
        score += 3.0
    elif not item_domain:
        score += 0.5
    return round(score, 3)


async def load_learned_hotwords(
    session: AsyncSession,
    *,
    subject_domain: str | None = None,
    limit: int = 24,
) -> list[dict[str, Any]]:
    domains = _subject_domain_scope(subject_domain)
    result = await session.execute(
        select(LearnedHotword).where(
            LearnedHotword.status == "active",
            LearnedHotword.subject_domain.in_(sorted(domains)),
        )
    )
    rows = result.scalars().all()
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        canonical = row.canonical_form or row.term
        key = canonical.casefold()
        current = merged.get(key)
        aliases = list(row.aliases or [])
        if current is not None:
            current["aliases"] = _dedupe_aliases(
                [*(current.get("aliases") or []), *aliases],
                term=str(current.get("term") or row.term),
                canonical_form=str(current.get("canonical_form") or canonical),
            )
            current["sources"] = sorted({*(current.get("sources") or []), row.source})
            current["source"] = ",".join(current["sources"])
            current["evidence_count"] = int(current.get("evidence_count") or 0) + int(row.evidence_count or 0)
            current["positive_count"] = int(current.get("positive_count") or 0) + int(row.positive_count or 0)
            current["negative_count"] = int(current.get("negative_count") or 0) + int(row.negative_count or 0)
            current["prompt_count"] = int(current.get("prompt_count") or 0) + int(row.prompt_count or 0)
            current["confidence"] = max(float(current.get("confidence") or 0.0), float(row.confidence or 0.0))
            current["score"] = score_learned_hotword(current, subject_domain=subject_domain)
            continue
        item = {
            "term": row.term,
            "canonical_form": canonical,
            "aliases": aliases,
            "subject_domain": row.subject_domain,
            "source": row.source,
            "sources": [row.source],
            "evidence_count": int(row.evidence_count or 0),
            "positive_count": int(row.positive_count or 0),
            "negative_count": int(row.negative_count or 0),
            "prompt_count": int(row.prompt_count or 0),
            "confidence": float(row.confidence or 0.0),
        }
        item["score"] = score_learned_hotword(item, subject_domain=subject_domain)
        merged[key] = item
    items = list(merged.values())
    items.sort(key=lambda item: (-float(item["score"]), -len(str(item["term"])), str(item["term"])))
    return items[:limit]


async def record_prompted_hotwords(
    session: AsyncSession,
    *,
    prompt_hotwords: list[str],
) -> None:
    normalized_terms = {
        normalize_hotword_token(item).casefold()
        for item in prompt_hotwords
        if normalize_hotword_token(item)
    }
    if not normalized_terms:
        return
    result = await session.execute(select(LearnedHotword).where(LearnedHotword.status == "active"))
    now = datetime.now(timezone.utc)
    for row in result.scalars().all():
        row_terms = {
            normalize_hotword_token(row.term).casefold(),
            normalize_hotword_token(row.canonical_form).casefold(),
            *(
                normalize_hotword_token(alias).casefold()
                for alias in (row.aliases or [])
                if normalize_hotword_token(alias)
            ),
        }
        if not row_terms & normalized_terms:
            continue
        row.prompt_count = int(row.prompt_count or 0) + 1
        row.last_prompted_at = now
        row.updated_at = now


def select_ranked_hotword_terms(
    *,
    learned_hotwords: list[dict[str, Any]] | None,
    existing_terms: list[str] | None = None,
    limit: int = 12,
) -> list[str]:
    terms: list[str] = []
    seen = {normalize_hotword_token(item).casefold() for item in (existing_terms or []) if normalize_hotword_token(item)}
    for item in learned_hotwords or []:
        for value in (item.get("canonical_form"), item.get("term")):
            token = normalize_hotword_token(value)
            key = token.casefold()
            if not token or key in seen:
                continue
            seen.add(key)
            terms.append(token)
            break
        if len(terms) >= limit:
            break
    return terms


def summarize_hotword_sources(items: list[dict[str, Any]] | None) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for item in items or []:
        source = str(item.get("source") or "unknown").strip() or "unknown"
        counts[source] += 1
    return dict(counts)
