from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def build_topic_fact_confirmation_snapshot(
    profile: Mapping[str, Any] | None,
    *,
    verification_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(profile or {})
    understanding = _as_dict(payload.get("content_understanding"))
    verification = _as_dict(verification_evidence) or _as_dict(payload.get("verification_evidence"))

    support_sources = _collect_support_sources(payload, understanding, verification)
    uncertainties = _string_list(understanding.get("uncertainties"))
    conflicts = _string_list(understanding.get("conflicts"))
    review_reasons = _string_list(understanding.get("review_reasons"))

    subject = {
        "domain": _text(payload.get("subject_domain") or understanding.get("content_domain")),
        "brand": _text(payload.get("subject_brand")),
        "model": _text(payload.get("subject_model")),
        "type": _text(payload.get("subject_type") or understanding.get("primary_subject")),
        "theme": _text(payload.get("video_theme") or understanding.get("video_theme")),
        "summary": _text(payload.get("summary") or understanding.get("summary")),
    }
    query_list = _dedupe_strings(
        [
            *_string_list(verification.get("search_queries")),
            *_string_list(payload.get("search_queries")),
            *_string_list(understanding.get("search_queries")),
        ]
    )
    evidence_counts = {
        "online": _int_count(verification.get("online_count"), verification.get("online_results")),
        "database": _int_count(verification.get("database_count"), verification.get("database_results")),
        "entity_catalog": _int_count(
            verification.get("entity_catalog_count"),
            verification.get("entity_catalog_candidates"),
        ),
    }

    fact_confidence = _estimate_fact_confidence(
        understanding=understanding,
        support_sources=support_sources,
        evidence_counts=evidence_counts,
        conflicts=conflicts,
        uncertainties=uncertainties,
    )
    status_reasons = _status_reasons(
        subject=subject,
        support_sources=support_sources,
        evidence_counts=evidence_counts,
        conflicts=conflicts,
        uncertainties=uncertainties,
        review_reasons=review_reasons,
        fact_confidence=fact_confidence,
    )
    confirmed = not status_reasons and fact_confidence >= 0.72

    return {
        "stage_version": "topic_fact_confirmation_v1",
        "confirmed": confirmed,
        "status": "confirmed" if confirmed else "needs_review",
        "subject": subject,
        "support_sources": support_sources,
        "research_expansion": {
            "enabled": bool(query_list),
            "search_queries": query_list[:8],
            "external_evidence_count": evidence_counts["online"],
            "internal_entity_count": evidence_counts["entity_catalog"] or evidence_counts["database"],
        },
        "evidence_counts": evidence_counts,
        "confidence": fact_confidence,
        "uncertainties": uncertainties[:8],
        "conflicts": conflicts[:8],
        "review_reasons": _dedupe_strings([*status_reasons, *review_reasons])[:12],
    }


def topic_fact_confirmation_present(profile: Mapping[str, Any] | None) -> bool:
    return isinstance((profile or {}).get("topic_fact_confirmation"), Mapping)


def topic_fact_is_confirmed(profile: Mapping[str, Any] | None) -> bool:
    confirmation = _as_dict((profile or {}).get("topic_fact_confirmation"))
    if not confirmation:
        return False
    if bool(confirmation.get("confirmed")):
        return True
    return str(confirmation.get("status") or "").strip().lower() == "confirmed"


def topic_fact_allows_automatic_term_rewrites(profile: Mapping[str, Any] | None) -> bool:
    if not topic_fact_confirmation_present(profile):
        return True
    return topic_fact_is_confirmed(profile)


def _collect_support_sources(
    profile: dict[str, Any],
    understanding: dict[str, Any],
    verification: dict[str, Any],
) -> list[str]:
    support_sources: list[str] = []

    def add(source: str, condition: bool) -> None:
        if condition and source not in support_sources:
            support_sources.append(source)

    source_context = _as_dict(profile.get("source_context"))
    add("task_context", bool(source_context))
    add("asr_transcript", bool(_text(profile.get("transcript_excerpt") or profile.get("transcript_source"))))
    add("visual_ocr", bool(_text(profile.get("visible_text")) or _as_dict(profile.get("ocr_profile"))))
    add(
        "visual_semantic",
        bool(_as_dict(profile.get("visual_semantic_evidence")) or _as_dict(profile.get("visual_hints"))),
    )
    add("llm_semantic_evidence", bool(_string_list(understanding.get("evidence_spans"))))
    add(
        "online_research",
        bool(_int_count(verification.get("online_count"), verification.get("online_results"))),
    )
    add(
        "internal_entity_catalog",
        bool(
            _int_count(verification.get("entity_catalog_count"), verification.get("entity_catalog_candidates"))
            or _int_count(verification.get("database_count"), verification.get("database_results"))
        ),
    )
    add("manual_confirmation", _profile_has_manual_confirmation(profile))
    return support_sources


def _status_reasons(
    *,
    subject: dict[str, str],
    support_sources: list[str],
    evidence_counts: dict[str, int],
    conflicts: list[str],
    uncertainties: list[str],
    review_reasons: list[str],
    fact_confidence: float,
) -> list[str]:
    reasons: list[str] = []
    if not subject["theme"]:
        reasons.append("主题事实未确认：缺少具体视频主题")
    if not subject["type"]:
        reasons.append("主题事实未确认：缺少主体类型")
    if not support_sources:
        reasons.append("主题事实未确认：缺少可审计证据来源")
    if conflicts:
        reasons.append("主题事实存在冲突，需要人工确认")
    if uncertainties:
        reasons.append("主题事实仍有不确定项")
    if review_reasons:
        reasons.append("内容理解模型要求复核")
    if fact_confidence < 0.55:
        reasons.append("主题事实置信度不足")
    if (
        (subject["brand"] or subject["model"])
        and not evidence_counts["online"]
        and not evidence_counts["entity_catalog"]
        and "manual_confirmation" not in support_sources
    ):
        reasons.append("品牌/型号缺少深度调研或内部实体库交叉印证")
    return _dedupe_strings(reasons)


def _estimate_fact_confidence(
    *,
    understanding: dict[str, Any],
    support_sources: list[str],
    evidence_counts: dict[str, int],
    conflicts: list[str],
    uncertainties: list[str],
) -> float:
    raw_confidence = _as_dict(understanding.get("confidence"))
    try:
        score = float(raw_confidence.get("overall", raw_confidence.get("topic", 0.0)) or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    score = max(score, 0.28 if support_sources else 0.0)
    score += min(0.28, len(support_sources) * 0.055)
    if evidence_counts["online"]:
        score += 0.10
    if evidence_counts["entity_catalog"] or evidence_counts["database"]:
        score += 0.12
    if conflicts:
        score -= 0.22
    if uncertainties:
        score -= min(0.18, len(uncertainties) * 0.045)
    return round(max(0.0, min(1.0, score)), 3)


def _profile_has_manual_confirmation(profile: dict[str, Any]) -> bool:
    if str(profile.get("review_mode") or "").strip().lower() == "manual_confirmed":
        return True
    if bool(profile.get("manual_confirmed")):
        return True
    source_context = _as_dict(profile.get("source_context"))
    return bool(_text(source_context.get("manual_video_summary")))


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return _dedupe_strings([str(item).strip() for item in value if str(item).strip()])
    if isinstance(value, tuple):
        return _dedupe_strings([str(item).strip() for item in value if str(item).strip()])
    if isinstance(value, dict):
        text = _text(value.get("text") or value.get("value") or value.get("summary"))
        return [text] if text else []
    text = _text(value)
    return [text] if text else []


def _dedupe_strings(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in output:
            output.append(normalized)
    return output


def _int_count(raw_count: Any, raw_items: Any) -> int:
    try:
        count = int(raw_count or 0)
    except (TypeError, ValueError):
        count = 0
    if count > 0:
        return count
    if isinstance(raw_items, list):
        return len(raw_items)
    return 0
