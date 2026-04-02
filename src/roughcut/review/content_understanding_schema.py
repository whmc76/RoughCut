from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SubjectEntity:
    kind: str
    name: str
    brand: str = ""
    model: str = ""


@dataclass(frozen=True)
class ContentUnderstanding:
    video_type: str
    content_domain: str
    primary_subject: str
    subject_entities: list[SubjectEntity] = field(default_factory=list)
    video_theme: str = ""
    summary: str = ""
    hook_line: str = ""
    engagement_question: str = ""
    search_queries: list[str] = field(default_factory=list)
    evidence_spans: list[dict[str, Any]] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    confidence: dict[str, float] = field(default_factory=dict)
    needs_review: bool = True
    review_reasons: list[str] = field(default_factory=list)


def map_content_understanding_to_legacy_profile(value: ContentUnderstanding) -> dict[str, Any]:
    subject_brand = ""
    subject_model = ""
    for entity in value.subject_entities:
        normalized_kind = str(entity.kind or "").strip().lower()
        if entity.brand and not subject_brand:
            subject_brand = entity.brand
        if entity.model and not subject_model and (entity.brand or normalized_kind in {"product", "hardware", "device"}):
            subject_model = entity.model
        if subject_brand and subject_model:
            break
    subject_type = value.primary_subject or (value.subject_entities[0].name if value.subject_entities else "")
    return {
        "content_kind": value.video_type,
        "subject_domain": value.content_domain,
        "subject_brand": subject_brand,
        "subject_model": subject_model,
        "subject_type": subject_type,
        "video_theme": value.video_theme,
        "summary": value.summary,
        "hook_line": value.hook_line,
        "engagement_question": value.engagement_question,
        "search_queries": list(value.search_queries),
        "content_understanding": {
            "video_type": value.video_type,
            "content_domain": value.content_domain,
            "primary_subject": value.primary_subject,
            "subject_entities": [entity.__dict__ for entity in value.subject_entities],
            "video_theme": value.video_theme,
            "summary": value.summary,
            "hook_line": value.hook_line,
            "engagement_question": value.engagement_question,
            "search_queries": list(value.search_queries),
            "evidence_spans": list(value.evidence_spans),
            "uncertainties": list(value.uncertainties),
            "confidence": dict(value.confidence),
            "needs_review": value.needs_review,
            "review_reasons": list(value.review_reasons),
        },
    }
