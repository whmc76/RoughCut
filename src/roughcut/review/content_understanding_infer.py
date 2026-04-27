from __future__ import annotations

from typing import Any

from roughcut.config import get_settings
from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message
from roughcut.review.content_understanding_capabilities import resolve_content_understanding_capabilities
from roughcut.review.content_understanding_evidence import normalize_evidence_bundle
from roughcut.review.content_understanding_facts import (
    _canonicalize_brand_candidate,
    _dominant_product_type_from_text,
    _load_json_object,
    _pick_brand_from_text,
    infer_content_semantic_facts,
)
from roughcut.review.domain_glossaries import list_builtin_glossary_packs
from roughcut.review.content_understanding_schema import (
    ContentSemanticFacts,
    ContentUnderstanding,
    SubjectEntity,
    CONTENT_UNDERSTANDING_FIELD_GUIDELINES,
    parse_content_understanding_payload as parse_content_understanding_payload_from_schema,
)

_GLOSSARY_BRAND_TERMS: list[dict[str, Any]] = [
    term
    for pack in list_builtin_glossary_packs()
    for term in list(pack.get("terms") or [])
    if isinstance(term, dict) and str(term.get("category") or "").strip().lower().endswith("_brand")
]


def parse_content_understanding_payload(data: Any) -> ContentUnderstanding:
    return parse_content_understanding_payload_from_schema(data)


async def infer_content_understanding(evidence_bundle: dict[str, Any]) -> ContentUnderstanding:
    evidence_bundle = normalize_evidence_bundle(evidence_bundle)
    provider = get_reasoning_provider()
    capability_matrix = _resolve_capability_matrix(evidence_bundle)
    orchestration_trace = ["capability_resolution", "fact_extraction", "final_understanding"]
    semantic_facts = await infer_content_semantic_facts(provider, evidence_bundle)
    understanding = await infer_final_understanding(provider, evidence_bundle, semantic_facts)
    semantic_facts = _backfill_semantic_facts_from_understanding(semantic_facts, understanding)
    return _with_staged_semantic_facts(
        understanding,
        semantic_facts,
        capability_matrix=capability_matrix,
        orchestration_trace=orchestration_trace,
    )


async def infer_final_understanding(
    provider: Any,
    evidence_bundle: dict[str, Any],
    semantic_facts: ContentSemanticFacts,
) -> ContentUnderstanding:
    prompt = _build_content_understanding_prompt(evidence_bundle, semantic_facts)

    response = await provider.complete(
        [
            Message(role="system", content="你是内容理解分析器，输出必须是 JSON。"),
            Message(role="user", content=prompt),
        ],
        temperature=0.1,
        max_tokens=1400,
        json_mode=True,
    )
    payload = await _load_json_object(
        provider,
        response,
        required_fields=[
            "video_type",
            "content_domain",
            "primary_subject",
            "subject_entities",
            "observed_entities",
            "resolved_entities",
            "resolved_primary_subject",
            "entity_resolution_map",
            "video_theme",
            "summary",
            "hook_line",
            "engagement_question",
            "search_queries",
            "evidence_spans",
            "uncertainties",
            "confidence",
            "needs_review",
            "review_reasons",
        ],
        empty_object_description=(
            '{"video_type":"","content_domain":"","primary_subject":"","subject_entities":[],'
            '"observed_entities":[],"resolved_entities":[],"resolved_primary_subject":"","entity_resolution_map":[],'
            '"video_theme":"","summary":"","hook_line":"","engagement_question":"","search_queries":[],'
            '"evidence_spans":[],"uncertainties":[],"confidence":{},"needs_review":true,"review_reasons":[]}'
        ),
    )
    understanding = parse_content_understanding_payload(payload)
    if _needs_understanding_repair(understanding, semantic_facts):
        repaired_payload = await _repair_empty_understanding_payload(
            provider=provider,
            response=response,
            evidence_bundle=evidence_bundle,
            semantic_facts=semantic_facts,
        )
        repaired_understanding = parse_content_understanding_payload(repaired_payload)
        if not _needs_understanding_repair(repaired_understanding, semantic_facts):
            understanding = repaired_understanding
    if understanding.semantic_facts == ContentSemanticFacts():
        understanding = ContentUnderstanding(
            video_type=understanding.video_type,
            content_domain=understanding.content_domain,
            primary_subject=understanding.primary_subject,
            semantic_facts=semantic_facts,
            subject_entities=understanding.subject_entities,
            observed_entities=understanding.observed_entities,
            resolved_entities=understanding.resolved_entities,
            resolved_primary_subject=understanding.resolved_primary_subject,
            entity_resolution_map=understanding.entity_resolution_map,
            video_theme=understanding.video_theme,
            summary=understanding.summary,
            hook_line=understanding.hook_line,
            engagement_question=understanding.engagement_question,
            search_queries=understanding.search_queries or semantic_facts.search_expansions[:4],
            evidence_spans=understanding.evidence_spans,
            uncertainties=understanding.uncertainties,
            conflicts=understanding.conflicts,
            confidence=understanding.confidence,
            needs_review=understanding.needs_review,
            review_reasons=understanding.review_reasons,
            capability_matrix=understanding.capability_matrix,
            orchestration_trace=understanding.orchestration_trace,
        )
    return _normalize_understanding_subject_roles(understanding, semantic_facts, evidence_bundle=evidence_bundle)


def _with_staged_semantic_facts(
    understanding: ContentUnderstanding,
    semantic_facts: ContentSemanticFacts,
    *,
    capability_matrix: dict[str, Any],
    orchestration_trace: list[str],
) -> ContentUnderstanding:
    return ContentUnderstanding(
        video_type=understanding.video_type,
        content_domain=understanding.content_domain,
        primary_subject=understanding.primary_subject,
        semantic_facts=semantic_facts,
        subject_entities=understanding.subject_entities,
        observed_entities=understanding.observed_entities,
        resolved_entities=understanding.resolved_entities,
        resolved_primary_subject=understanding.resolved_primary_subject,
        entity_resolution_map=understanding.entity_resolution_map,
        video_theme=understanding.video_theme,
        summary=understanding.summary,
        hook_line=understanding.hook_line,
        engagement_question=understanding.engagement_question,
        search_queries=understanding.search_queries or semantic_facts.search_expansions[:4],
        evidence_spans=understanding.evidence_spans,
        uncertainties=understanding.uncertainties,
        conflicts=understanding.conflicts,
        confidence=understanding.confidence,
        needs_review=understanding.needs_review,
        review_reasons=understanding.review_reasons,
        capability_matrix=understanding.capability_matrix or capability_matrix,
        orchestration_trace=understanding.orchestration_trace or orchestration_trace,
    )


def _backfill_semantic_facts_from_understanding(
    semantic_facts: ContentSemanticFacts,
    understanding: ContentUnderstanding,
) -> ContentSemanticFacts:
    if any(
        (
            semantic_facts.primary_subject_candidates,
            semantic_facts.supporting_subject_candidates,
            semantic_facts.comparison_subject_candidates,
            semantic_facts.supporting_product_candidates,
            semantic_facts.component_candidates,
            semantic_facts.aspect_candidates,
            semantic_facts.brand_candidates,
            semantic_facts.model_candidates,
            semantic_facts.product_name_candidates,
            semantic_facts.product_type_candidates,
            semantic_facts.entity_candidates,
            semantic_facts.search_expansions,
        )
    ):
        return semantic_facts

    primary_subject_candidates: list[str] = []
    brand_candidates: list[str] = []
    model_candidates: list[str] = []
    product_name_candidates: list[str] = []
    comparison_subject_candidates: list[str] = []
    supporting_product_candidates: list[str] = []
    search_expansions: list[str] = []

    def _append(target: list[str], value: str) -> None:
        text = str(value or "").strip()
        if text and text not in target:
            target.append(text)

    _append(primary_subject_candidates, understanding.primary_subject)
    _append(product_name_candidates, understanding.primary_subject)

    for entity in understanding.subject_entities:
        kind = str(entity.kind or "").strip().lower()
        _append(brand_candidates, entity.brand)
        _append(model_candidates, entity.model)
        if kind in {"product", "产品", "device", "hardware"}:
            _append(product_name_candidates, entity.name)
        if "comparison" in kind or "对比" in kind:
            _append(comparison_subject_candidates, entity.name)
        if any(marker in kind for marker in ("related", "supporting", "配套", "accessory", "secondary")):
            _append(supporting_product_candidates, entity.name)

    for item in (
        understanding.primary_subject,
        *product_name_candidates,
        *model_candidates[:2],
        *comparison_subject_candidates[:2],
        *supporting_product_candidates[:2],
    ):
        _append(search_expansions, item)

    if not brand_candidates:
        observed_text_blob = " ".join(
            str(entity.name or "").strip()
            for entity in [*understanding.subject_entities, *understanding.observed_entities]
            if str(entity.name or "").strip()
        )
        for term in _GLOSSARY_BRAND_TERMS:
            correct_form = str(term.get("correct_form") or "").strip()
            wrong_forms = [str(raw or "").strip() for raw in (term.get("wrong_forms") or []) if str(raw or "").strip()]
            aliases = [correct_form, *wrong_forms]
            if correct_form and any(alias and alias in observed_text_blob for alias in aliases):
                _append(brand_candidates, correct_form)

    return ContentSemanticFacts(
        primary_subject_candidates=primary_subject_candidates,
        supporting_subject_candidates=list(semantic_facts.supporting_subject_candidates),
        comparison_subject_candidates=comparison_subject_candidates,
        supporting_product_candidates=supporting_product_candidates,
        component_candidates=list(semantic_facts.component_candidates),
        aspect_candidates=list(semantic_facts.aspect_candidates),
        brand_candidates=brand_candidates,
        model_candidates=model_candidates,
        product_name_candidates=product_name_candidates,
        product_type_candidates=list(semantic_facts.product_type_candidates),
        entity_candidates=list(semantic_facts.entity_candidates),
        collaboration_pairs=list(semantic_facts.collaboration_pairs),
        search_expansions=search_expansions,
        evidence_sentences=list(semantic_facts.evidence_sentences),
    )


def _normalize_understanding_subject_roles(
    understanding: ContentUnderstanding,
    semantic_facts: ContentSemanticFacts,
    *,
    evidence_bundle: dict[str, Any] | None = None,
) -> ContentUnderstanding:
    primary_candidates = _preferred_primary_candidates(semantic_facts)
    supporting_candidates = [str(item).strip() for item in semantic_facts.supporting_subject_candidates if str(item).strip()]
    secondary_subject_candidates = _secondary_subject_candidates(semantic_facts)
    component_candidates = {
        str(item).strip().lower()
        for item in [*semantic_facts.component_candidates, *semantic_facts.aspect_candidates]
        if str(item).strip()
    }
    primary_candidates = _merge_entity_primary_candidates(
        primary_candidates,
        understanding=understanding,
        secondary_subject_candidates=secondary_subject_candidates,
        component_candidates=component_candidates,
    )
    if not primary_candidates:
        return understanding

    normalized_primary_subject = str(understanding.primary_subject or "").strip().lower()
    effective_primary_subject = understanding.primary_subject
    if (
        not effective_primary_subject
        or normalized_primary_subject in component_candidates
        or _looks_component_like_name(effective_primary_subject)
    ):
        effective_primary_subject = primary_candidates[0]
    effective_primary_subject = _normalize_primary_subject_label(
        effective_primary_subject,
        primary_candidates=primary_candidates,
        secondary_subject_candidates=secondary_subject_candidates,
        component_candidates=list(component_candidates),
    )
    preferred_opening_primary = _preferred_opening_primary_subject(
        semantic_facts,
        current_primary_subject=effective_primary_subject,
        secondary_subject_candidates=secondary_subject_candidates,
        evidence_bundle=evidence_bundle,
    )
    if preferred_opening_primary:
        effective_primary_subject = preferred_opening_primary

    preferred_primary_brand = _preferred_primary_brand(
        effective_primary_subject,
        semantic_facts=semantic_facts,
        evidence_bundle=evidence_bundle,
    )

    def _entity_name(entity: SubjectEntity) -> str:
        return str(entity.name or "").strip()

    observed_entities = list(understanding.observed_entities)
    observed_names = {_entity_name(entity).lower() for entity in observed_entities if _entity_name(entity)}
    if (not observed_entities or observed_names.issubset(component_candidates)) and primary_candidates[0].lower() not in observed_names:
        observed_entities = [SubjectEntity(kind="product", name=primary_candidates[0])] + observed_entities
        observed_names = {_entity_name(entity).lower() for entity in observed_entities if _entity_name(entity)}

    subject_entities = list(understanding.subject_entities)
    subject_names = {_entity_name(entity).lower() for entity in subject_entities if _entity_name(entity)}
    if (not subject_entities or subject_names.issubset(component_candidates)) and primary_candidates[0].lower() not in subject_names:
        subject_entities = [SubjectEntity(kind="product", name=primary_candidates[0])] + subject_entities
        subject_names = {_entity_name(entity).lower() for entity in subject_entities if _entity_name(entity)}
    if effective_primary_subject:
        normalized_effective_primary = effective_primary_subject.lower()
        if normalized_effective_primary not in subject_names:
            original_primary_subject = str(understanding.primary_subject or "").strip().lower()
            if (
                subject_entities
                and original_primary_subject
                and _entity_name(subject_entities[0]).strip().lower() == original_primary_subject
            ):
                subject_entities[0] = SubjectEntity(
                    kind="product",
                    name=effective_primary_subject,
                    brand=preferred_primary_brand or subject_entities[0].brand,
                    model=subject_entities[0].model,
                )
            else:
                subject_entities = [
                    SubjectEntity(kind="product", name=effective_primary_subject, brand=preferred_primary_brand)
                ] + subject_entities
            subject_names = {_entity_name(entity).lower() for entity in subject_entities if _entity_name(entity)}
        elif subject_entities:
            first_entity = subject_entities[0]
            if (
                _entity_name(first_entity).strip().lower() == normalized_effective_primary
                and preferred_primary_brand
                and str(first_entity.brand or "").strip() != preferred_primary_brand
            ):
                subject_entities[0] = SubjectEntity(
                    kind=first_entity.kind or "product",
                    name=first_entity.name,
                    brand=preferred_primary_brand,
                    model=first_entity.model,
                )
            elif _entity_name(first_entity).strip().lower() != normalized_effective_primary:
                matching_index = next(
                    (
                        index
                        for index, entity in enumerate(subject_entities)
                        if _entity_name(entity).strip().lower() == normalized_effective_primary
                    ),
                    -1,
                )
                if matching_index > 0:
                    matching_entity = subject_entities.pop(matching_index)
                    if preferred_primary_brand and not str(matching_entity.brand or "").strip():
                        matching_entity = SubjectEntity(
                            kind=matching_entity.kind or "product",
                            name=matching_entity.name,
                            brand=preferred_primary_brand,
                            model=matching_entity.model,
                        )
                    subject_entities = [matching_entity, *subject_entities]
        if observed_entities:
            observed_matching_index = next(
                (
                    index
                    for index, entity in enumerate(observed_entities)
                    if _entity_name(entity).strip().lower() == normalized_effective_primary
                ),
                -1,
            )
            if observed_matching_index > 0:
                observed_entities = [observed_entities[observed_matching_index], *observed_entities[:observed_matching_index], *observed_entities[observed_matching_index + 1 :]]
            elif observed_matching_index < 0:
                observed_entities = [SubjectEntity(kind="product", name=effective_primary_subject), *observed_entities]
    related_subject_candidates = secondary_subject_candidates or supporting_candidates
    for candidate in related_subject_candidates:
        if candidate.lower() not in subject_names:
            subject_entities.append(SubjectEntity(kind="related", name=candidate))

    return ContentUnderstanding(
        video_type=understanding.video_type,
        content_domain=understanding.content_domain,
        primary_subject=effective_primary_subject,
        semantic_facts=understanding.semantic_facts,
        subject_entities=subject_entities,
        observed_entities=observed_entities,
        resolved_entities=understanding.resolved_entities,
        resolved_primary_subject=understanding.resolved_primary_subject,
        entity_resolution_map=understanding.entity_resolution_map,
        video_theme=understanding.video_theme,
        summary=understanding.summary,
        hook_line=understanding.hook_line,
        engagement_question=understanding.engagement_question,
        search_queries=understanding.search_queries,
        evidence_spans=understanding.evidence_spans,
        uncertainties=understanding.uncertainties,
        conflicts=understanding.conflicts,
        confidence=understanding.confidence,
        needs_review=understanding.needs_review,
        review_reasons=understanding.review_reasons,
        capability_matrix=understanding.capability_matrix,
        orchestration_trace=understanding.orchestration_trace,
    )


def _preferred_primary_candidates(semantic_facts: ContentSemanticFacts) -> list[str]:
    component_candidates = {
        str(item).strip().lower()
        for item in [*semantic_facts.component_candidates, *semantic_facts.aspect_candidates]
        if str(item).strip()
    }
    ordered: list[str] = []
    for group in (
        [item for item in semantic_facts.primary_subject_candidates if str(item).strip().lower() not in component_candidates],
        [item for item in semantic_facts.primary_subject_candidates if str(item).strip().lower() in component_candidates],
        list(semantic_facts.product_name_candidates),
        list(semantic_facts.product_type_candidates),
    ):
        for item in group:
            text = str(item).strip()
            if text and text not in ordered:
                ordered.append(text)
    return ordered


def _merge_entity_primary_candidates(
    primary_candidates: list[str],
    *,
    understanding: ContentUnderstanding,
    secondary_subject_candidates: list[str],
    component_candidates: set[str],
) -> list[str]:
    ordered: list[str] = []
    for entity in [*understanding.subject_entities, *understanding.observed_entities]:
        text = str(entity.name or "").strip()
        kind = str(entity.kind or "").strip().lower()
        normalized_text = text.lower()
        if not text:
            continue
        if normalized_text in component_candidates:
            continue
        if _looks_component_like_name(text):
            continue
        if _contains_secondary_subject(text, secondary_subject_candidates):
            continue
        if any(
            marker in kind
            for marker in ("related", "supporting", "配套", "accessory", "secondary", "comparison", "对比", "component", "process", "工艺")
        ):
            continue
        if any(marker in kind for marker in ("product", "产品", "品类", "hardware", "device")) and text not in ordered:
            ordered.append(text)

    merged: list[str] = []
    for item in [*ordered, *primary_candidates]:
        text = str(item).strip()
        if text and text not in merged:
            merged.append(text)
    return merged


def _looks_component_like_name(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return any(marker in normalized for marker in ("系统", "装置", "模块", "节点"))


def _secondary_subject_candidates(semantic_facts: ContentSemanticFacts) -> list[str]:
    secondary: list[str] = []
    for item in [*semantic_facts.comparison_subject_candidates, *semantic_facts.supporting_product_candidates]:
        text = str(item).strip()
        if text and text not in secondary:
            secondary.append(text)

    brand_candidates = {
        str(item).strip().lower()
        for item in semantic_facts.brand_candidates
        if str(item).strip()
    }
    collaboration_text = " ".join(str(item).strip().lower() for item in semantic_facts.collaboration_pairs if str(item).strip())
    for item in semantic_facts.supporting_subject_candidates:
        text = str(item).strip()
        lowered = text.lower()
        if not text:
            continue
        if lowered in brand_candidates:
            continue
        if collaboration_text and lowered in collaboration_text:
            continue
        if text not in secondary:
            secondary.append(text)
    return secondary


def _normalize_primary_subject_label(
    primary_subject: str,
    *,
    primary_candidates: list[str],
    secondary_subject_candidates: list[str],
    component_candidates: list[str],
) -> str:
    text = str(primary_subject or "").strip()
    if not text:
        return str(primary_candidates[0]).strip() if primary_candidates else ""

    clean_primary_candidates = [
        candidate
        for candidate in primary_candidates
        if not _contains_secondary_subject(candidate, secondary_subject_candidates)
    ]
    if not _contains_secondary_subject(text, secondary_subject_candidates):
        return _strip_component_biased_primary_subject(
            text,
            primary_candidates=clean_primary_candidates or primary_candidates,
            component_candidates=component_candidates,
        ) or text
    if not clean_primary_candidates:
        return text
    normalized_text = _normalize_subject_text(text)
    for candidate in clean_primary_candidates:
        normalized_candidate = _normalize_subject_text(candidate)
        if normalized_candidate and (
            normalized_text.startswith(normalized_candidate)
            or normalized_candidate in normalized_text
        ):
            return _strip_component_biased_primary_subject(
                candidate,
                primary_candidates=clean_primary_candidates,
                component_candidates=component_candidates,
            ) or candidate
    fallback = clean_primary_candidates[0]
    return _strip_component_biased_primary_subject(
        fallback,
        primary_candidates=clean_primary_candidates,
        component_candidates=component_candidates,
    ) or fallback


def _contains_secondary_subject(text: str, secondary_subject_candidates: list[str]) -> bool:
    normalized_text = _normalize_subject_text(text)
    if not normalized_text:
        return False
    for candidate in secondary_subject_candidates:
        normalized_candidate = _normalize_subject_text(candidate)
        if len(normalized_candidate) < 2:
            continue
        if normalized_candidate and normalized_candidate in normalized_text:
            return True
    return False


def _preferred_opening_primary_subject(
    semantic_facts: ContentSemanticFacts,
    *,
    current_primary_subject: str,
    secondary_subject_candidates: list[str],
    evidence_bundle: dict[str, Any] | None,
) -> str:
    opening_text = _opening_focus_text(evidence_bundle)
    if not opening_text:
        return ""
    current_text = str(current_primary_subject or "").strip()
    opening_brand = _pick_brand_from_text(opening_text, list(semantic_facts.brand_candidates))
    dominant_type = _dominant_product_type_from_text(opening_text, list(semantic_facts.product_type_candidates))
    current_score = _opening_primary_candidate_score(
        current_text,
        opening_text=opening_text,
        opening_brand=opening_brand,
        dominant_type=dominant_type,
        semantic_facts=semantic_facts,
        secondary_subject_candidates=secondary_subject_candidates,
    )
    if not _is_generic_primary_subject(current_text, semantic_facts):
        return ""

    best_candidate = ""
    best_score = current_score
    for candidate in _preferred_primary_candidates(semantic_facts):
        score = _opening_primary_candidate_score(
            candidate,
            opening_text=opening_text,
            opening_brand=opening_brand,
            dominant_type=dominant_type,
            semantic_facts=semantic_facts,
            secondary_subject_candidates=secondary_subject_candidates,
        )
        if score > best_score:
            best_candidate = candidate
            best_score = score
    return best_candidate


def _opening_primary_candidate_score(
    candidate: str,
    *,
    opening_text: str,
    opening_brand: str,
    dominant_type: str,
    semantic_facts: ContentSemanticFacts,
    secondary_subject_candidates: list[str],
) -> int:
    text = str(candidate or "").strip()
    if not text:
        return 0
    score = 0
    if text in opening_text:
        score += 6
    if not _contains_secondary_subject(text, secondary_subject_candidates):
        score += 1
    if opening_brand and _text_mentions_brand(text, opening_brand, semantic_facts.brand_candidates):
        score += 4
    if dominant_type and dominant_type in text:
        score += 3
    if opening_brand and dominant_type and _text_mentions_brand(opening_text, opening_brand, semantic_facts.brand_candidates) and dominant_type in opening_text:
        if _text_mentions_brand(text, opening_brand, semantic_facts.brand_candidates) and dominant_type in text:
            score += 2
    return score


def _preferred_primary_brand(
    primary_subject: str,
    *,
    semantic_facts: ContentSemanticFacts,
    evidence_bundle: dict[str, Any] | None,
) -> str:
    subject_text = str(primary_subject or "").strip()
    if not subject_text:
        return ""
    opening_text = _opening_focus_text(evidence_bundle)
    opening_brand = _pick_brand_from_text(opening_text, list(semantic_facts.brand_candidates)) if opening_text else ""
    if opening_brand and _text_mentions_brand(subject_text, opening_brand, semantic_facts.brand_candidates):
        return opening_brand
    for brand in semantic_facts.brand_candidates:
        canonical, _aliases = _canonicalize_brand_candidate(str(brand or "").strip())
        if canonical and _text_mentions_brand(subject_text, canonical, semantic_facts.brand_candidates):
            return canonical
    return ""


def _is_generic_primary_subject(text: str, semantic_facts: ContentSemanticFacts) -> bool:
    subject_text = str(text or "").strip()
    if not subject_text:
        return True
    for brand in semantic_facts.brand_candidates:
        canonical, aliases = _canonicalize_brand_candidate(str(brand or "").strip())
        for alias in aliases or (canonical,):
            candidate = str(alias or "").strip()
            if candidate and candidate in subject_text:
                return False
    dominant_type = _dominant_product_type_from_text(subject_text, list(semantic_facts.product_type_candidates))
    return bool(dominant_type)


def _text_mentions_brand(
    text: str,
    brand: str,
    brand_candidates: list[str],
) -> bool:
    normalized_text = str(text or "").strip()
    if not normalized_text:
        return False
    aliases: list[str] = []
    for raw in brand_candidates:
        canonical, raw_aliases = _canonicalize_brand_candidate(str(raw or "").strip())
        if canonical != brand:
            continue
        aliases.extend(raw_aliases or (canonical,))
    if not aliases:
        aliases.append(brand)
    return any(alias and alias in normalized_text for alias in aliases)


def _opening_focus_text(evidence_bundle: dict[str, Any] | None) -> str:
    if not isinstance(evidence_bundle, dict):
        return ""
    semantic_inputs = evidence_bundle.get("semantic_fact_inputs")
    semantic_inputs = semantic_inputs if isinstance(semantic_inputs, dict) else {}
    opening_focus_lines = [
        str(item).strip()
        for item in (semantic_inputs.get("opening_focus_lines") or [])
        if str(item).strip()
    ]
    return " ".join(opening_focus_lines)


def _normalize_subject_text(text: str) -> str:
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _strip_component_biased_primary_subject(
    text: str,
    *,
    primary_candidates: list[str],
    component_candidates: list[str],
) -> str:
    normalized_text = _normalize_subject_text(text)
    if not normalized_text:
        return ""
    normalized_components = [
        _normalize_subject_text(item)
        for item in component_candidates
        if _normalize_subject_text(item)
    ]
    if not any(component in normalized_text for component in normalized_components):
        return ""

    for candidate in primary_candidates:
        candidate_text = str(candidate or "").strip()
        normalized_candidate = _normalize_subject_text(candidate_text)
        if not normalized_candidate or normalized_candidate == normalized_text:
            continue
        if normalized_candidate in normalized_text and not any(
            component in normalized_candidate for component in normalized_components
        ):
            return candidate_text
    return ""


def _build_content_understanding_prompt(
    evidence_bundle: dict[str, Any],
    semantic_facts: ContentSemanticFacts,
) -> str:
    transcript_excerpt = str(evidence_bundle.get("transcript_excerpt") or "").strip()
    compact_evidence = _build_compact_evidence_payload(evidence_bundle)
    prompt = (
        "你是严谨的视频内容理解引擎。根据证据包和已抽取的语义事实，推断一个通用内容理解结果，"
        "只输出一个 JSON 对象，不要 Markdown，不要代码块，不要解释。"
        "字段必须包括 video_type, content_domain, primary_subject, subject_entities, observed_entities, "
        "resolved_entities, resolved_primary_subject, entity_resolution_map, "
        "video_theme, summary, hook_line, engagement_question, search_queries, evidence_spans, "
        "uncertainties, confidence, needs_review, review_reasons。"
        "约束："
        "文件名、视频说明、人工摘要属于创作者给出的先验线索；ASR 转写、字幕、OCR、画面语义属于实际内容证据；"
        "必须综合两类证据判断这一期到底在讲什么，不允许只按文件名/说明机械覆盖，也不允许只按 ASR 里的孤立型号覆盖；"
        "如果标题/视频说明和 ASR 大体一致，应优先形成稳定主体；"
        "如果标题/视频说明与 ASR 冲突，要判断 ASR 中冲突对象是主讲、对比、附件、背景提及还是误识别，并在 uncertainties 或 review_reasons 说明；"
        "只有当 ASR/画面持续围绕另一个对象展开，且标题/说明证据明显不足或疑似错误时，才允许推翻标题/说明主体；"
        "primary_subject 必须优先表示视频真正围绕的主对象或主产品；"
        "优先参考 semantic_facts.primary_subject_candidates；"
        "如果 semantic_facts.component_candidates 或 semantic_facts.aspect_candidates 非空，这些内容默认只能作为组件、系统、评价点或总结素材，不能抢占 primary_subject；"
        "如果 semantic_facts.supporting_subject_candidates、comparison_subject_candidates 或 supporting_product_candidates 非空，它们优先进入 subject_entities 或 observed_entities，而不是覆盖主主体；"
        "comparison_subject_candidates 表示对比/参照产品，supporting_product_candidates 表示配套或顺带发布的次要产品；"
        "不要把功能系统、部件、工艺过程或服务方误当成 primary_subject，除非视频明确就是在讲它们本身；"
        "如果视频既展示主产品又讨论部件/配件/工艺，把主产品放在 primary_subject，把其他内容放进 subject_entities、observed_entities 或 summary；"
        "如果视频里既出现主对象原始称呼，也出现组件/系统称呼，observed_entities 应优先保留主对象原始称呼，组件/系统可作为补充实体或写进 summary；"
        "如果 opening_focus_lines 前半段持续围绕一个具体产品，而 closing_focus_lines 只是在结尾宣布另一条系列、桌布、周边或配套产品，后者默认只能作为 supporting_product 或 comparison，不要顶替 primary_subject；"
        "subject_entities 必须是对象数组，每项包含 kind,name,brand,model；"
        "observed_entities 必须保留视频里原始看到或听到的主体称呼；"
        "resolved_entities、resolved_primary_subject、entity_resolution_map 在首轮推断可为空；"
        f"{CONTENT_UNDERSTANDING_FIELD_GUIDELINES}\n"
        "search_queries 最多 4 条，优先结合 semantic_facts.search_expansions 生成；"
        "evidence_spans 最多 4 条，字段只允许 timestamp,text,type；"
        "confidence 必须是对象，例如 {\"overall\":0.78}；"
        "信息不足时字段留空或空数组，不要编造。"
        f"\n紧凑证据包: {compact_evidence}"
        f"\n语义事实: {semantic_facts.__dict__}"
    )
    if transcript_excerpt:
        prompt += f"\n转写片段: {transcript_excerpt}"
    return prompt


def _build_compact_evidence_payload(evidence_bundle: dict[str, Any]) -> dict[str, Any]:
    semantic_fact_inputs = evidence_bundle.get("semantic_fact_inputs")
    raw_semantic_inputs = semantic_fact_inputs if isinstance(semantic_fact_inputs, dict) else {}
    compact_semantic_inputs = {
        "source_name": str(raw_semantic_inputs.get("source_name") or "").strip(),
        "source_context": raw_semantic_inputs.get("source_context") if isinstance(raw_semantic_inputs.get("source_context"), dict) else {},
        "editorial_context_lines": [
            str(item).strip()
            for item in (raw_semantic_inputs.get("editorial_context_lines") or [])
            if str(item).strip()
        ][:12],
        "cue_lines": [
            str(item).strip()
            for item in (raw_semantic_inputs.get("cue_lines") or [])
            if str(item).strip()
        ][:8],
        "opening_focus_lines": [
            str(item).strip()
            for item in (raw_semantic_inputs.get("opening_focus_lines") or [])
            if str(item).strip()
        ][:6],
        "closing_focus_lines": [
            str(item).strip()
            for item in (raw_semantic_inputs.get("closing_focus_lines") or [])
            if str(item).strip()
        ][:6],
        "relation_hints": [
            {
                str(key): str(value).strip()
                for key, value in item.items()
                if str(value).strip()
            }
            for item in (raw_semantic_inputs.get("relation_hints") or [])
            if isinstance(item, dict)
        ][:8],
        "transcript_text": str(raw_semantic_inputs.get("transcript_text") or "").strip(),
        "visible_text": str(raw_semantic_inputs.get("visible_text") or "").strip(),
        "hint_candidates": [
            str(item).strip()
            for item in (raw_semantic_inputs.get("hint_candidates") or [])
            if str(item).strip()
        ][:12],
        "entity_like_tokens": [
            str(item).strip()
            for item in (raw_semantic_inputs.get("entity_like_tokens") or [])
            if str(item).strip()
        ][:20],
    }
    candidate_hints = evidence_bundle.get("candidate_hints")
    compact_candidate_hints = candidate_hints if isinstance(candidate_hints, dict) else {}
    visual_semantic_evidence = evidence_bundle.get("visual_semantic_evidence")
    raw_visual_semantic_evidence = visual_semantic_evidence if isinstance(visual_semantic_evidence, dict) else {}
    compact_visual_semantic_evidence = {
        "object_categories": [
            str(item).strip()
            for item in (raw_visual_semantic_evidence.get("object_categories") or [])
            if str(item).strip()
        ][:8],
        "visible_brands": [
            str(item).strip()
            for item in (raw_visual_semantic_evidence.get("visible_brands") or [])
            if str(item).strip()
        ][:8],
        "visible_models": [
            str(item).strip()
            for item in (raw_visual_semantic_evidence.get("visible_models") or [])
            if str(item).strip()
        ][:8],
        "subject_candidates": [
            str(item).strip()
            for item in (raw_visual_semantic_evidence.get("subject_candidates") or [])
            if str(item).strip()
        ][:8],
        "interaction_type": str(raw_visual_semantic_evidence.get("interaction_type") or "").strip(),
        "scene_context": str(raw_visual_semantic_evidence.get("scene_context") or "").strip(),
        "evidence_notes": [
            str(item).strip()
            for item in (raw_visual_semantic_evidence.get("evidence_notes") or [])
            if str(item).strip()
        ][:8],
    }
    return {
        "source_name": str(evidence_bundle.get("source_name") or "").strip(),
        "source_context": evidence_bundle.get("source_context") if isinstance(evidence_bundle.get("source_context"), dict) else {},
        "transcript_excerpt": str(evidence_bundle.get("transcript_excerpt") or "").strip(),
        "visible_text": str(evidence_bundle.get("visible_text") or "").strip(),
        "visual_semantic_evidence": compact_visual_semantic_evidence,
        "semantic_fact_inputs": compact_semantic_inputs,
        "candidate_hints": compact_candidate_hints,
    }




def _needs_understanding_repair(
    understanding: ContentUnderstanding,
    semantic_facts: ContentSemanticFacts,
) -> bool:
    informative_semantic_facts = any(
        (
            semantic_facts.brand_candidates,
            semantic_facts.primary_subject_candidates,
            semantic_facts.supporting_subject_candidates,
            semantic_facts.comparison_subject_candidates,
            semantic_facts.supporting_product_candidates,
            semantic_facts.component_candidates,
            semantic_facts.aspect_candidates,
            semantic_facts.model_candidates,
            semantic_facts.product_name_candidates,
            semantic_facts.product_type_candidates,
            semantic_facts.entity_candidates,
            semantic_facts.collaboration_pairs,
            semantic_facts.search_expansions,
            semantic_facts.evidence_sentences,
        )
    )
    if not informative_semantic_facts:
        return False
    role_conflict = _has_subject_role_conflict(understanding, semantic_facts)
    has_core_output = any(
        (
            understanding.video_type,
            understanding.content_domain,
            understanding.primary_subject,
            understanding.subject_entities,
            understanding.video_theme,
            understanding.summary,
            understanding.hook_line,
            understanding.engagement_question,
            understanding.search_queries,
            understanding.review_reasons,
        )
    )
    return (not has_core_output) or role_conflict


def _has_subject_role_conflict(
    understanding: ContentUnderstanding,
    semantic_facts: ContentSemanticFacts,
) -> bool:
    primary_candidates = {
        item.strip().lower()
        for item in semantic_facts.primary_subject_candidates
        if str(item).strip()
    }
    component_candidates = {
        item.strip().lower()
        for item in [*semantic_facts.component_candidates, *semantic_facts.aspect_candidates]
        if str(item).strip()
    }
    if not primary_candidates or not component_candidates:
        return False

    normalized_primary_subject = str(understanding.primary_subject or "").strip().lower()
    if normalized_primary_subject and normalized_primary_subject in component_candidates:
        return True

    observed_names = {
        str(entity.name or "").strip().lower()
        for entity in understanding.observed_entities
        if str(entity.name or "").strip()
    }
    if observed_names and observed_names.issubset(component_candidates) and primary_candidates.isdisjoint(observed_names):
        return True
    return False


async def _repair_empty_understanding_payload(
    *,
    provider: Any,
    response: Any,
    evidence_bundle: dict[str, Any],
    semantic_facts: ContentSemanticFacts,
) -> dict[str, Any]:
    repair_prompt = (
        "下面这个内容理解结果虽然是 JSON，但核心字段为空。"
        "请基于原始输出、语义事实和紧凑证据，重写成一个严格 JSON 对象。"
        "不要输出 Markdown，不要代码块，不要解释。"
        "字段必须包括 video_type, content_domain, primary_subject, subject_entities, observed_entities, "
        "resolved_entities, resolved_primary_subject, entity_resolution_map, "
        "video_theme, summary, hook_line, engagement_question, search_queries, evidence_spans, "
        "uncertainties, confidence, needs_review, review_reasons。"
        "要求："
        "1. 如果证据足够，就补全最合理的内容理解结果；"
        "2. 如果证据不足，也必须明确写出 review_reasons，不能整包留空；"
        "3. 不要编造未被证据支持的品牌/型号；"
        "4. 允许保守，但不能忽略 semantic_facts 已经明确给出的候选；"
        "5. 如果 semantic_facts 已区分 primary_subject_candidates、comparison_subject_candidates、supporting_product_candidates、component_candidates、aspect_candidates，必须优先让主对象候选成为 primary_subject，对比产品和配套产品不要顶替主主体。"
        f"{CONTENT_UNDERSTANDING_FIELD_GUIDELINES}\n"
        f"\n原始输出:\n{getattr(response, 'content', '')}"
        f"\n语义事实:\n{semantic_facts.__dict__}"
        f"\n紧凑证据包:\n{_build_compact_evidence_payload(evidence_bundle)}"
    )
    repaired = await provider.complete(
        [
            Message(role="system", content="你是内容理解 JSON 修复器，只输出严格 JSON。"),
            Message(role="user", content=repair_prompt),
        ],
        temperature=0.0,
        max_tokens=1400,
        json_mode=True,
    )
    payload = repaired.as_json()
    return payload if isinstance(payload, dict) else {}


def _resolve_capability_matrix(evidence_bundle: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    candidate_hints = evidence_bundle.get("candidate_hints")
    nested_visual_hints = candidate_hints.get("visual_hints") if isinstance(candidate_hints, dict) else {}
    has_visual_inputs = bool(evidence_bundle.get("visual_semantic_evidence") or nested_visual_hints)
    visual_provider = str(settings.active_reasoning_provider or settings.reasoning_provider or "").strip() if has_visual_inputs else ""
    return resolve_content_understanding_capabilities(
        reasoning_provider=str(settings.active_reasoning_provider or settings.reasoning_provider or "").strip(),
        visual_provider=visual_provider,
        visual_mcp_provider="",
    )
