from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from roughcut.review.domain_glossaries import list_builtin_glossary_packs
from roughcut.review.content_profile_field_rules import (
    CONTENT_UNDERSTANDING_FIELD_GUIDELINES,
    SUPPORTED_VIDEO_TYPES,
)


def _normalize_domain_alias(value: str) -> str:
    value = str(value or "").strip().lower()
    return re.sub(r"[\s·*+\-_/]+", "", value)


_GLOSSARY_BRAND_TERMS: list[dict[str, Any]] = [
    term
    for pack in list_builtin_glossary_packs()
    for term in list(pack.get("terms") or [])
    if isinstance(term, dict) and str(term.get("category") or "").strip().lower().endswith("_brand")
]

_GLOSSARY_SUBJECT_DOMAIN_TERMS: dict[str, set[str]] = {}
for pack in list_builtin_glossary_packs():
    pack_domain = str(pack.get("domain") or "").strip().lower()
    if not pack_domain:
        continue
    term_bucket = _GLOSSARY_SUBJECT_DOMAIN_TERMS.setdefault(pack_domain, set())
    for raw_term in list(pack.get("terms") or []):
        if not isinstance(raw_term, dict):
            continue
        aliases = [str(raw_term.get("correct_form") or "").strip()]
        aliases.extend(str(item or "").strip() for item in (raw_term.get("wrong_forms") or []))
        term_domain = str(raw_term.get("domain") or pack_domain).strip().lower()
        if term_domain != pack_domain:
            term_bucket = _GLOSSARY_SUBJECT_DOMAIN_TERMS.setdefault(term_domain, set())
        if not aliases:
            continue
        for alias in aliases:
            normalized = _normalize_domain_alias(alias)
            if len(normalized) >= 2 and normalized.isascii() is False:
                term_bucket.add(normalized)
            elif len(alias.strip()) >= 2:
                term_bucket.add(normalized)


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
    primary_subject_candidates: list[str] = field(default_factory=list)
    supporting_subject_candidates: list[str] = field(default_factory=list)
    comparison_subject_candidates: list[str] = field(default_factory=list)
    supporting_product_candidates: list[str] = field(default_factory=list)
    component_candidates: list[str] = field(default_factory=list)
    aspect_candidates: list[str] = field(default_factory=list)
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


def _normalize_understanding_value(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("value") or value.get("term") or ""
    normalized = str(value or "").strip()
    if normalized.lower() in {"unknown", "n/a", "none", "null"}:
        return ""
    if normalized in {"未知", "待确认", "内容待确认", "待人工确认", "未识别"}:
        return ""
    return normalized


def normalize_video_type(value: str) -> str:
    normalized = _normalize_understanding_value(value).strip().lower()
    if not normalized:
        return ""

    if normalized in SUPPORTED_VIDEO_TYPES:
        return normalized

    token_map = [
        ("unboxing", ("开箱", "上手", "评测", "测评")),
        ("tutorial", ("教程", "录屏", "教学", "指南", "使用", "演示", "工作流", "workflow")),
        ("vlog", ("vlog", "生活", "日常", "出行", "随手", "出门", "探店", "citywalk", "city walk")),
        ("commentary", ("口播", "观点", "评论", "分析", "复盘", "讨论")),
        ("gameplay", ("游戏", "实况", "对局", "直播", "fps", "吃鸡", "局内", "游戏里")),
        ("food", ("美食", "探店", "餐厅", "试吃", "咖啡", "奶茶", "火锅", "烧烤", "甜品", "零食", "含片", "益生菌", "薄荷糖", "口香糖", "糖果")),
    ]
    for fallback, tokens in token_map:
        if any(token in normalized for token in tokens):
            return fallback
    return ""


def parse_content_semantic_facts_payload(data: Any) -> ContentSemanticFacts:
    payload = data if isinstance(data, dict) else {}

    def _items(name: str) -> list[str]:
        values: list[str] = []
        for item in list(payload.get(name) or []):
            normalized = _normalize_semantic_fact_item(item)
            if normalized and normalized not in values:
                values.append(normalized)
        return values

    return ContentSemanticFacts(
        primary_subject_candidates=_items("primary_subject_candidates"),
        supporting_subject_candidates=_items("supporting_subject_candidates"),
        comparison_subject_candidates=_items("comparison_subject_candidates"),
        supporting_product_candidates=_items("supporting_product_candidates"),
        component_candidates=_items("component_candidates"),
        aspect_candidates=_items("aspect_candidates"),
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

    content_video_type = normalize_video_type(payload.get("video_type"))
    return ContentUnderstanding(
        video_type=content_video_type,
        content_domain=str(payload.get("content_domain") or "").strip(),
        primary_subject=_normalize_understanding_value(payload.get("primary_subject")),
        semantic_facts=parse_content_semantic_facts_payload(payload.get("semantic_facts")),
        subject_entities=_parse_subject_entities_payload(payload.get("subject_entities")),
        observed_entities=_parse_subject_entities_payload(payload.get("observed_entities")),
        resolved_entities=_parse_subject_entities_payload(payload.get("resolved_entities")),
        resolved_primary_subject=_normalize_understanding_value(payload.get("resolved_primary_subject")),
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
        "video_type": normalize_video_type(value.video_type),
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
        if isinstance(item, str):
            parsed = _parse_stringified_mapping(item)
            if isinstance(parsed, dict):
                item = parsed
            elif item.strip():
                subject_entities.append(
                    SubjectEntity(
                        kind="",
                        name=item.strip(),
                        brand="",
                        model="",
                    )
                )
                continue
        if isinstance(item, dict):
            subject_entities.append(
                SubjectEntity(
                    kind=str(item.get("kind") or "").strip(),
                    name=str(item.get("name") or item.get("value") or "").strip(),
                    brand=str(item.get("brand") or "").strip(),
                    model=str(item.get("model") or "").strip(),
                )
            )
            continue
        if isinstance(item, str) and item.strip():
            subject_entities.append(
                SubjectEntity(
                    kind="",
                    name=item.strip(),
                    brand="",
                    model="",
                )
            )
    return subject_entities


def _normalize_semantic_fact_item(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("name") or item.get("value") or item.get("term") or "").strip()
    if isinstance(item, str):
        parsed = _parse_stringified_mapping(item)
        if isinstance(parsed, dict):
            return str(parsed.get("name") or parsed.get("value") or parsed.get("term") or "").strip()
        return item.strip()
    return str(item or "").strip()


def _parse_stringified_mapping(value: str) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if not text or text[0] not in "{[":
        return None
    for loader in (ast.literal_eval,):
        try:
            parsed = loader(text)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def parse_primary_evidence_graph_payload(data: Any) -> dict[str, dict[str, Any]]:
    payload = data if isinstance(data, dict) else {}
    return {
        "audio_semantic_evidence": _as_dict(payload.get("audio_semantic_evidence")),
        "visual_semantic_evidence": _as_dict(payload.get("visual_semantic_evidence")),
        "ocr_semantic_evidence": _as_dict(payload.get("ocr_semantic_evidence")),
    }


def _preferred_subject_entities(value: ContentUnderstanding) -> list[SubjectEntity]:
    return list(value.resolved_entities or value.subject_entities or value.observed_entities)


_COMPARISON_KIND_MARKERS = {
    "comparison",
    "competitor",
    "对比",
    "参考",
    "benchmark",
    "bench",
}


def _subject_alias_candidates(values: list[str]) -> set[str]:
    aliases: set[str] = set()
    for value in values:
        raw = str(value or "").strip()
        if not raw:
            continue
        for part in re.split(r"[\s/，,·+*×xX\-]", raw):
            normalized = _normalize_compact(part)
            if normalized:
                aliases.add(normalized)
                if normalized:
                    aliases.add(normalized.replace(" ", ""))
    return aliases


def _identity_text_matches(entity_value: str, aliases: set[str]) -> bool:
    normalized = _normalize_compact(entity_value)
    if not normalized or not aliases:
        return False
    for alias in aliases:
        if alias in normalized or normalized in alias:
            return True
    return False


def _is_comparison_entity(entity: SubjectEntity, comparison_aliases: set[str]) -> bool:
    normalized_kind = str(entity.kind or "").strip().lower()
    if any(marker in normalized_kind for marker in _COMPARISON_KIND_MARKERS):
        return True
    for field_value in (entity.name, entity.brand, entity.model):
        if _identity_text_matches(field_value, comparison_aliases):
            return True
    return False


def _entity_matches_primary(entity: SubjectEntity, primary_aliases: set[str]) -> bool:
    for field_value in (entity.name, entity.brand, entity.model):
        if _identity_text_matches(field_value, primary_aliases):
            return True
    return False


def _is_product_like_entity(entity: SubjectEntity) -> bool:
    if entity.model:
        return True
    normalized_kind = str(entity.kind or "").strip().lower()
    return normalized_kind in {"product", "产品", "hardware", "device"}


def _normalize_compact(value: str) -> str:
    return "".join(str(value or "").upper().split())


def _infer_subject_domain_hints_from_glossary_text(value_text: str) -> set[str]:
    normalized = _normalize_domain_alias(value_text)
    if not normalized:
        return set()
    hits = set()
    for domain, aliases in _GLOSSARY_SUBJECT_DOMAIN_TERMS.items():
        for alias in aliases:
            alias_normalized = _normalize_domain_alias(alias)
            if not alias_normalized or len(alias_normalized) < 2:
                continue
            if alias_normalized in normalized:
                hits.add(domain)
                break
    return hits


def _infer_subject_domain_from_hinting(value: ContentUnderstanding) -> set[str]:
    semantic_values = [
        value.primary_subject,
        value.resolved_primary_subject,
        value.video_theme,
        value.summary,
        value.hook_line,
        value.engagement_question,
    ]
    for values in (
        value.semantic_facts.primary_subject_candidates,
        value.semantic_facts.product_name_candidates,
        value.semantic_facts.product_type_candidates,
        value.semantic_facts.model_candidates,
        value.semantic_facts.brand_candidates,
        value.semantic_facts.primary_subject_candidates,
        value.semantic_facts.aspect_candidates,
        value.semantic_facts.supporting_subject_candidates,
        value.semantic_facts.supporting_product_candidates,
        value.semantic_facts.comparison_subject_candidates,
        value.semantic_facts.entity_candidates,
    ):
        for item in values:
            text = str(item).strip()
            if text:
                semantic_values.append(text)
    semantic_values.extend(
        entity.name
        for entity in (value.subject_entities or [])
        if str(entity.name or "").strip()
    )
    semantic_values.extend(
        entity.brand
        for entity in (value.subject_entities or [])
        if str(entity.brand or "").strip()
    )
    semantic_values.extend(
        entity.model
        for entity in (value.subject_entities or [])
        if str(entity.model or "").strip()
    )
    semantic_values.extend(
        entity.name
        for entity in (value.resolved_entities or [])
        if str(entity.name or "").strip()
    )
    semantic_values.extend(
        entity.brand
        for entity in (value.resolved_entities or [])
        if str(entity.brand or "").strip()
    )
    semantic_values.extend(
        entity.model
        for entity in (value.resolved_entities or [])
        if str(entity.model or "").strip()
    )
    semantic_values.extend(
        entity.name
        for entity in (value.observed_entities or [])
        if str(entity.name or "").strip()
    )
    semantic_values.extend(
        entity.brand
        for entity in (value.observed_entities or [])
        if str(entity.brand or "").strip()
    )
    semantic_values.extend(
        entity.model
        for entity in (value.observed_entities or [])
        if str(entity.model or "").strip()
    )
    text_blob = " ".join(str(item).strip() for item in semantic_values if str(item or "").strip())
    return _infer_subject_domain_hints_from_glossary_text(text_blob)


def _prefer_subject_domain_from_hints(subject_domain_hints: set[str]) -> str:
    if not subject_domain_hints:
        return ""
    for hint in ("food", "bag", "flashlight", "knife", "functional", "edc", "vlog", "commentary", "gameplay", "tutorial"):
        if hint in subject_domain_hints:
            return hint
    return next(iter(subject_domain_hints))


def _compose_subject_type_label(*, subject_type: str, subject_brand: str, subject_model: str) -> str:
    candidate = _normalize_understanding_value(subject_type)
    brand = _normalize_understanding_value(subject_brand)
    model = _normalize_understanding_value(subject_model)
    if not candidate or not brand:
        return candidate

    normalized_candidate = _normalize_compact(candidate)
    normalized_brand = _normalize_compact(brand)
    normalized_model = _normalize_compact(model)
    if normalized_brand and normalized_brand in normalized_candidate:
        return candidate
    if _subject_type_contains_model(candidate, model):
        return f"{brand} {candidate}".strip()
    return candidate


def _subject_type_contains_model(subject_type: str, subject_model: str) -> bool:
    normalized_candidate = _normalize_compact(subject_type)
    normalized_model = _normalize_compact(subject_model)
    if normalized_model and normalized_model in normalized_candidate:
        return True
    ascii_candidate = "".join(ch for ch in str(subject_type or "").upper() if ch.isascii() and ch.isalnum())
    ascii_model = "".join(ch for ch in str(subject_model or "").upper() if ch.isascii() and ch.isalnum())
    return bool(ascii_model and ascii_model in ascii_candidate)


def _infer_subject_domain_hints(value: ContentUnderstanding) -> set[str]:
    domain_hints: set[str] = set()
    direct = _normalize_understanding_value(value.content_domain).lower()
    if any(token in direct for token in ("food", "snack", "candy", "食品", "零食", "含片", "益生菌", "糖果")):
        domain_hints.add("food")
    if "bag" in direct or "functional" in direct:
        domain_hints.add("bag")
    if "edc" in direct and not domain_hints:
        domain_hints.add("edc")
    if "flashlight" in direct:
        domain_hints.add("flashlight")
    if "knife" in direct:
        domain_hints.add("knife")

    type_blob = "".join(
        str(item or "") + " "
        for item in (
            value.primary_subject,
            value.resolved_primary_subject,
            *value.semantic_facts.primary_subject_candidates,
            *value.semantic_facts.product_type_candidates,
            *value.semantic_facts.aspect_candidates,
            *value.semantic_facts.model_candidates,
            *value.semantic_facts.brand_candidates,
            *value.semantic_facts.product_name_candidates,
        )
    )
    if any(token in type_blob for token in ("双肩包", "机能包", "背包", "背负", "副包", "分仓", "挂点", "收纳")):
        domain_hints.add("bag")
    if any(token in type_blob for token in ("手电", "手电筒", "电筒", "流明", "闪光", "flashlight", "torch")):
        domain_hints.add("flashlight")
    if any(token in type_blob for token in ("刀", "刀具", "折刀", "重力刀", "刀柄", "开刃", "knife")):
        domain_hints.add("knife")
    if any(token in type_blob for token in ("零食", "含片", "益生菌", "薄荷糖", "口香糖", "糖果", "食品", "可食用", "luckykiss", "kisspod", "kissport")):
        domain_hints.add("food")
    glossary_inferred = _infer_subject_domain_from_hinting(value)
    if glossary_inferred:
        domain_hints.update(glossary_inferred)
    return domain_hints


def _entity_domain_alias_matches(entity: SubjectEntity, subject_domain: str) -> bool:
    aliases = _GLOSSARY_SUBJECT_DOMAIN_TERMS.get(_normalize_subject_domain(subject_domain), set())
    if not aliases:
        return False
    searchable = _normalize_domain_alias(f"{entity.name} {entity.brand} {entity.model}")
    for alias in aliases:
        alias_normalized = _normalize_domain_alias(alias)
        if len(alias_normalized) < 2:
            continue
        if alias_normalized in searchable:
            return True
    return False


def _normalize_subject_domain(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "bag":
        return "bag"
    return normalized


def _matches_subject_domain(entity: SubjectEntity, subject_domain_hints: set[str]) -> bool:
    if not subject_domain_hints:
        return True
    if subject_domain_hints == {"edc"}:
        return True
    normalized_name = _normalize_compact(entity.name)
    normalized_brand = _normalize_compact(entity.brand)
    normalized_model = _normalize_compact(entity.model)
    searchable = "".join((entity.kind, " ", normalized_name, " ", normalized_brand, " ", normalized_model))
    if "bag" in subject_domain_hints and any(token in searchable for token in ("BACKPACK", "BAG", "SHOULDER", "FXX1", "FOXBAT", "机能包", "双肩包", "背包", "副包", "分仓", "挂点")):
        return True
    if "bag" in subject_domain_hints and _entity_domain_alias_matches(entity, "bag"):
        return True
    if "flashlight" in subject_domain_hints and any(token in searchable for token in ("TORCH", "FLASHLIGHT", "ILLUM", "LIGHT", "手电", "手电筒", "电筒", "尾按")):
        return True
    if "flashlight" in subject_domain_hints and _entity_domain_alias_matches(entity, "flashlight"):
        return True
    if "knife" in subject_domain_hints and any(token in searchable for token in ("KNIFE", "BLADE", "GRAVITY", "折刀", "重力刀", "刀")):
        return True
    if "knife" in subject_domain_hints and _entity_domain_alias_matches(entity, "knife"):
        return True
    if "food" in subject_domain_hints and any(token in searchable for token in ("SNACK", "CANDY", "FOOD", "LUCKYKISS", "KISSPOD", "KISSPORT", "零食", "含片", "益生菌", "薄荷糖", "口香糖", "糖果")):
        return True
    if "food" in subject_domain_hints and _entity_domain_alias_matches(entity, "food"):
        return True
    return False


def _resolve_subject_brand_and_model(
    value: ContentUnderstanding,
    entities: list[SubjectEntity],
    *,
    subject_domain_hints: set[str] | None = None,
) -> tuple[str, str]:
    comparison_aliases = _subject_alias_candidates(value.semantic_facts.comparison_subject_candidates)
    primary_aliases = _subject_alias_candidates(
        [value.resolved_primary_subject, value.primary_subject] + value.semantic_facts.primary_subject_candidates
    )
    active_domain_hints = set(subject_domain_hints or _infer_subject_domain_hints(value))

    subject_brand = ""
    subject_model = ""

    primary_aligned_entities = [
        entity
        for entity in entities
        if _entity_matches_primary(entity, primary_aliases or set())
        and not _is_comparison_entity(entity, comparison_aliases)
    ]
    if active_domain_hints:
        primary_aligned_entities = [
            entity
            for entity in primary_aligned_entities
            if _matches_subject_domain(entity, active_domain_hints)
        ]
    if not primary_aligned_entities:
        primary_aligned_entities = [
            entity
            for entity in entities
            if not _is_comparison_entity(entity, comparison_aliases)
            and _matches_subject_domain(entity, active_domain_hints)
        ]
    if not primary_aligned_entities:
        return "", ""

    for entity in primary_aligned_entities:
        if not subject_brand and entity.brand:
            subject_brand = entity.brand
        if not subject_model and _is_product_like_entity(entity):
            subject_model = entity.model
        if subject_brand and subject_model:
            break

    if not subject_brand and primary_aligned_entities:
        for entity in primary_aligned_entities:
            if entity.brand:
                subject_brand = entity.brand
                break
    if not subject_model and primary_aligned_entities:
        for entity in primary_aligned_entities:
            if _is_product_like_entity(entity) and entity.model:
                subject_model = entity.model
                break

    return subject_brand, subject_model


def map_content_understanding_to_profile(value: ContentUnderstanding) -> dict[str, Any]:
    preferred_entities = _preferred_subject_entities(value)
    subject_domain_hints = _infer_subject_domain_hints(value)
    if not subject_domain_hints:
        subject_domain_hints = _infer_subject_domain_from_hinting(value)
        if not subject_domain_hints:
            subject_domain_hints = set()
    subject_brand, subject_model = _resolve_subject_brand_and_model(
        value,
        preferred_entities,
        subject_domain_hints=subject_domain_hints,
    )
    if not subject_brand:
        subject_brand = _infer_subject_brand_from_context(value, preferred_entities)
    content_kind = normalize_video_type(value.video_type)
    subject_domain = _normalize_understanding_value(value.content_domain)
    if subject_domain.lower() in {"edc", "gear"} and any(
        hint in subject_domain_hints
        for hint in ("food", "bag", "flashlight", "knife", "functional")
    ):
        subject_domain = _prefer_subject_domain_from_hints(subject_domain_hints)
    if not subject_domain:
        subject_domain = _prefer_subject_domain_from_hints(subject_domain_hints)
    subject_type = _compose_subject_type_label(
        subject_type=_normalize_understanding_value(
        value.resolved_primary_subject
        or value.primary_subject
        or (preferred_entities[0].name if preferred_entities else "")
        ),
        subject_brand=subject_brand,
        subject_model=subject_model,
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


def _infer_subject_brand_from_context(
    value: ContentUnderstanding,
    preferred_entities: list[SubjectEntity],
) -> str:
    has_product_entity = any(
        any(marker in str(entity.kind or "").strip().lower() for marker in ("product", "产品", "hardware", "device"))
        for entity in preferred_entities
    )
    if not has_product_entity:
        return ""
    text_blob = " ".join(
        part
        for part in (
            value.resolved_primary_subject,
            value.primary_subject,
            *[entity.name for entity in preferred_entities],
            *[entity.name for entity in value.observed_entities],
        )
        if str(part or "").strip()
    )
    for term in _GLOSSARY_BRAND_TERMS:
        correct_form = str(term.get("correct_form") or "").strip()
        aliases = [correct_form, *[str(raw or "").strip() for raw in (term.get("wrong_forms") or []) if str(raw or "").strip()]]
        if correct_form and any(alias and alias in text_blob for alias in aliases):
            return correct_form
    return ""
