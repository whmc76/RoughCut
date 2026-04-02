from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SubjectEntity:
    kind: str
    name: str
    brand: str = ""
    model: str = ""


@dataclass(frozen=True)
class EntityResolution:
    observed_name: str
    resolved_name: str
    confidence: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class ContentSemanticFacts:
    brand_candidates: list[str] = field(default_factory=list)
    model_candidates: list[str] = field(default_factory=list)
    product_name_candidates: list[str] = field(default_factory=list)
    product_type_candidates: list[str] = field(default_factory=list)
    entity_candidates: list[str] = field(default_factory=list)
    collaboration_pairs: list[str] = field(default_factory=list)
    search_expansions: list[str] = field(default_factory=list)
    evidence_sentences: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ContentUnderstanding:
    video_type: str
    content_domain: str
    primary_subject: str
    semantic_facts: ContentSemanticFacts = field(default_factory=ContentSemanticFacts)
    subject_entities: list[SubjectEntity] = field(default_factory=list)
    observed_entities: list[SubjectEntity] = field(default_factory=list)
    resolved_entities: list[SubjectEntity] = field(default_factory=list)
    resolved_primary_subject: str = ""
    entity_resolution_map: list[EntityResolution] = field(default_factory=list)
    video_theme: str = ""
    summary: str = ""
    hook_line: str = ""
    engagement_question: str = ""
    search_queries: list[str] = field(default_factory=list)
    evidence_spans: list[dict[str, Any]] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    confidence: dict[str, float] = field(default_factory=dict)
    needs_review: bool = True
    review_reasons: list[str] = field(default_factory=list)
    capability_matrix: dict[str, Any] = field(default_factory=dict)
    orchestration_trace: list[str] = field(default_factory=list)


def _normalize_understanding_value(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized.lower() in {"unknown", "n/a", "none", "null"}:
        return ""
    if normalized in {"未知", "待确认", "内容待确认", "待人工确认", "未识别"}:
        return ""
    return normalized


def parse_content_semantic_facts_payload(data: Any) -> ContentSemanticFacts:
    payload = data if isinstance(data, dict) else {}

    def _items(name: str) -> list[str]:
        values: list[str] = []
        for item in list(payload.get(name) or []):
            normalized = str(item or "").strip()
            if normalized and normalized not in values:
                values.append(normalized)
        return values

    return ContentSemanticFacts(
        brand_candidates=_items("brand_candidates"),
        model_candidates=_items("model_candidates"),
        product_name_candidates=_items("product_name_candidates"),
        product_type_candidates=_items("product_type_candidates"),
        entity_candidates=_items("entity_candidates"),
        collaboration_pairs=_items("collaboration_pairs"),
        search_expansions=_items("search_expansions"),
        evidence_sentences=_items("evidence_sentences"),
    )


def parse_entity_resolution_payload(data: Any) -> list[EntityResolution]:
    values: list[EntityResolution] = []
    for item in list(data or []):
        if not isinstance(item, dict):
            continue
        observed_name = str(item.get("observed_name") or "").strip()
        resolved_name = str(item.get("resolved_name") or "").strip()
        if not observed_name and not resolved_name:
            continue
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        values.append(
            EntityResolution(
                observed_name=observed_name,
                resolved_name=resolved_name,
                confidence=confidence,
                reason=str(item.get("reason") or "").strip(),
            )
        )
    return values


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            items.append(text)
    return items


def parse_content_understanding_payload(data: Any) -> ContentUnderstanding:
    payload = data if isinstance(data, dict) else {}

    confidence: dict[str, float] = {}
    raw_confidence = payload.get("confidence")
    if isinstance(raw_confidence, dict):
        for key, value in raw_confidence.items():
            try:
                confidence[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
    else:
        try:
            confidence["overall"] = float(raw_confidence)
        except (TypeError, ValueError):
            pass

    capability_matrix = payload.get("capability_matrix")
    orchestration_trace = payload.get("orchestration_trace")

    return ContentUnderstanding(
        video_type=str(payload.get("video_type") or "").strip(),
        content_domain=str(payload.get("content_domain") or "").strip(),
        primary_subject=str(payload.get("primary_subject") or "").strip(),
        semantic_facts=parse_content_semantic_facts_payload(payload.get("semantic_facts")),
        subject_entities=_parse_subject_entities_payload(payload.get("subject_entities")),
        observed_entities=_parse_subject_entities_payload(payload.get("observed_entities")),
        resolved_entities=_parse_subject_entities_payload(payload.get("resolved_entities")),
        resolved_primary_subject=str(payload.get("resolved_primary_subject") or "").strip(),
        entity_resolution_map=parse_entity_resolution_payload(payload.get("entity_resolution_map")),
        video_theme=str(payload.get("video_theme") or "").strip(),
        summary=str(payload.get("summary") or "").strip(),
        hook_line=str(payload.get("hook_line") or "").strip(),
        engagement_question=str(payload.get("engagement_question") or "").strip(),
        search_queries=[str(item).strip() for item in list(payload.get("search_queries") or []) if str(item).strip()],
        evidence_spans=[dict(item) for item in list(payload.get("evidence_spans") or []) if isinstance(item, dict)],
        uncertainties=[str(item).strip() for item in list(payload.get("uncertainties") or []) if str(item).strip()],
        conflicts=[str(item).strip() for item in list(payload.get("conflicts") or []) if str(item).strip()],
        confidence=confidence,
        needs_review=bool(payload.get("needs_review", True)),
        review_reasons=[str(item).strip() for item in list(payload.get("review_reasons") or []) if str(item).strip()],
        capability_matrix=_as_dict(capability_matrix),
        orchestration_trace=_as_string_list(orchestration_trace),
    )


def serialize_content_understanding_payload(value: ContentUnderstanding) -> dict[str, Any]:
    return {
        "video_type": _normalize_understanding_value(value.video_type),
        "content_domain": _normalize_understanding_value(value.content_domain),
        "primary_subject": _normalize_understanding_value(value.primary_subject),
        "semantic_facts": asdict(value.semantic_facts),
        "subject_entities": [asdict(entity) for entity in value.subject_entities],
        "observed_entities": [asdict(entity) for entity in value.observed_entities],
        "resolved_entities": [asdict(entity) for entity in value.resolved_entities],
        "resolved_primary_subject": _normalize_understanding_value(value.resolved_primary_subject),
        "entity_resolution_map": [asdict(item) for item in value.entity_resolution_map],
        "video_theme": _normalize_understanding_value(value.video_theme),
        "summary": value.summary,
        "hook_line": value.hook_line,
        "engagement_question": value.engagement_question,
        "search_queries": list(value.search_queries),
        "evidence_spans": list(value.evidence_spans),
        "uncertainties": list(value.uncertainties),
        "conflicts": list(value.conflicts),
        "confidence": dict(value.confidence),
        "needs_review": value.needs_review,
        "review_reasons": list(value.review_reasons),
        "capability_matrix": dict(value.capability_matrix),
        "orchestration_trace": list(value.orchestration_trace),
    }


def _parse_subject_entities_payload(data: Any) -> list[SubjectEntity]:
    subject_entities: list[SubjectEntity] = []
    for item in list(data or []):
        if isinstance(item, str) and item.strip():
            subject_entities.append(
                SubjectEntity(
                    kind="",
                    name=item.strip(),
                    brand="",
                    model="",
                )
            )
            continue
        if not isinstance(item, dict):
            continue
        subject_entities.append(
            SubjectEntity(
                kind=str(item.get("kind") or "").strip(),
                name=str(item.get("name") or "").strip(),
                brand=str(item.get("brand") or "").strip(),
                model=str(item.get("model") or "").strip(),
            )
        )
    return subject_entities


def parse_primary_evidence_graph_payload(data: Any) -> dict[str, dict[str, Any]]:
    payload = data if isinstance(data, dict) else {}
    return {
        "audio_semantic_evidence": _as_dict(payload.get("audio_semantic_evidence")),
        "visual_semantic_evidence": _as_dict(payload.get("visual_semantic_evidence")),
        "ocr_semantic_evidence": _as_dict(payload.get("ocr_semantic_evidence")),
    }


def _preferred_subject_entities(value: ContentUnderstanding) -> list[SubjectEntity]:
    return list(value.resolved_entities or value.subject_entities or value.observed_entities)


def map_content_understanding_to_legacy_profile(value: ContentUnderstanding) -> dict[str, Any]:
    subject_brand = ""
    subject_model = ""
    preferred_entities = _preferred_subject_entities(value)
    for entity in preferred_entities:
        normalized_kind = str(entity.kind or "").strip().lower()
        if entity.brand and not subject_brand:
            subject_brand = entity.brand
        if entity.model and not subject_model and (entity.brand or normalized_kind in {"product", "hardware", "device"}):
            subject_model = entity.model
        if subject_brand and subject_model:
            break
    content_kind = _normalize_understanding_value(value.video_type)
    subject_domain = _normalize_understanding_value(value.content_domain)
    subject_type = _normalize_understanding_value(
        value.resolved_primary_subject
        or value.primary_subject
        or (preferred_entities[0].name if preferred_entities else "")
    )
    video_theme = _normalize_understanding_value(value.video_theme)
    return {
        "content_kind": content_kind,
        "subject_domain": subject_domain,
        "subject_brand": subject_brand,
        "subject_model": subject_model,
        "subject_type": subject_type,
        "video_theme": video_theme,
        "summary": value.summary,
        "hook_line": value.hook_line,
        "engagement_question": value.engagement_question,
        "search_queries": list(value.search_queries),
        "content_understanding": {
            **serialize_content_understanding_payload(
                ContentUnderstanding(
                    video_type=content_kind,
                    content_domain=subject_domain,
                    primary_subject=subject_type,
                    semantic_facts=value.semantic_facts,
                    subject_entities=value.subject_entities,
                    observed_entities=value.observed_entities,
                    resolved_entities=value.resolved_entities,
                    resolved_primary_subject=value.resolved_primary_subject,
                    entity_resolution_map=value.entity_resolution_map,
                    video_theme=video_theme,
                    summary=value.summary,
                    hook_line=value.hook_line,
                    engagement_question=value.engagement_question,
                    search_queries=value.search_queries,
                    evidence_spans=value.evidence_spans,
                    uncertainties=value.uncertainties,
                    conflicts=value.conflicts,
                    confidence=value.confidence,
                    needs_review=value.needs_review,
                    review_reasons=value.review_reasons,
                    capability_matrix=value.capability_matrix,
                    orchestration_trace=value.orchestration_trace,
                )
            ),
        },
    }
