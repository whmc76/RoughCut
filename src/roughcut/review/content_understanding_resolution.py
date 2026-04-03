from __future__ import annotations

from dataclasses import replace
from typing import Any

from roughcut.review.content_understanding_schema import ContentUnderstanding, SubjectEntity


_RESOLUTION_CONFIDENCE_THRESHOLD = 0.7


def should_run_entity_resolution(
    *,
    understanding: ContentUnderstanding,
    candidate: ContentUnderstanding,
    evidence_bundle: dict[str, Any] | None = None,
    verification_bundle: Any | None = None,
) -> bool:
    _ = evidence_bundle, verification_bundle
    return bool(
        _collect_conflict_fields(understanding, candidate)
        or _has_alias_instability(candidate)
    )


def resolve_entities(
    *,
    base: ContentUnderstanding,
    candidate: ContentUnderstanding,
    evidence_bundle: dict[str, Any] | None = None,
    allow_entity_resolution: bool = True,
) -> ContentUnderstanding:
    has_direct_evidence = _has_direct_evidence(evidence_bundle)
    conflicts = _collect_conflict_fields(base, candidate)
    resolution_confidence = float(candidate.confidence.get("resolution") or candidate.confidence.get("overall") or 0.0)
    component_biased_resolved_subject = _is_component_biased_resolved_primary_subject(base, candidate)
    supporting_biased_resolved_subject = _is_supporting_biased_resolved_primary_subject(base, candidate)
    use_resolved = bool(
        allow_entity_resolution
        and candidate.resolved_primary_subject
        and candidate.resolved_entities
        and resolution_confidence >= _RESOLUTION_CONFIDENCE_THRESHOLD
        and not component_biased_resolved_subject
        and not supporting_biased_resolved_subject
    )
    review_reasons = _merge_unique(
        list(base.review_reasons),
        list(candidate.review_reasons),
        [
            "缺少直接视频证据，外部搜索/内部检索仅作弱佐证" if not has_direct_evidence else "",
            "核验结果与当前视频结论存在冲突，已保守保留原结论" if conflicts else "",
            "核验归一化结果更偏向组件或功能描述，已保守保留主产品主体" if component_biased_resolved_subject else "",
            "核验归一化结果混入了次要产品或配套对象名称，已保守保留主产品主体" if supporting_biased_resolved_subject else "",
        ],
    )
    uncertainties = _merge_unique(list(base.uncertainties), list(candidate.uncertainties))
    merged_conflicts = _merge_unique(list(base.conflicts), list(candidate.conflicts), conflicts)
    needs_review = bool(base.needs_review or candidate.needs_review or not has_direct_evidence or conflicts)
    cleaner_resolved_product = _preferred_resolved_product_entity(candidate)
    primary_subject = candidate.resolved_primary_subject if use_resolved else base.primary_subject
    subject_entities = list(candidate.resolved_entities) if use_resolved else list(base.subject_entities)
    if component_biased_resolved_subject and cleaner_resolved_product:
        primary_subject = cleaner_resolved_product.name
        if not any(str(entity.name or "").strip() == cleaner_resolved_product.name for entity in subject_entities):
            subject_entities = [SubjectEntity(kind="product", name=cleaner_resolved_product.name, brand=cleaner_resolved_product.brand, model=cleaner_resolved_product.model), *subject_entities]
    observed_entities = _normalize_observed_entities(base, fallback_subject_entities=subject_entities)
    return replace(
        base,
        primary_subject=primary_subject,
        subject_entities=subject_entities,
        observed_entities=observed_entities,
        resolved_entities=list(candidate.resolved_entities),
        resolved_primary_subject="" if component_biased_resolved_subject or supporting_biased_resolved_subject else candidate.resolved_primary_subject,
        entity_resolution_map=list(candidate.entity_resolution_map),
        uncertainties=uncertainties,
        conflicts=merged_conflicts,
        review_reasons=review_reasons,
        needs_review=needs_review,
        confidence=dict(base.confidence or candidate.confidence),
    )


def _collect_conflict_fields(base: ContentUnderstanding, candidate: ContentUnderstanding) -> list[str]:
    conflict_fields: list[str] = []
    for field_name in (
        "video_type",
        "content_domain",
        "primary_subject",
        "subject_entities",
        "video_theme",
        "summary",
        "hook_line",
        "engagement_question",
    ):
        if getattr(base, field_name) != getattr(candidate, field_name):
            conflict_fields.append(field_name)
    return conflict_fields


def _has_alias_instability(candidate: ContentUnderstanding) -> bool:
    if candidate.resolved_primary_subject and candidate.resolved_primary_subject != candidate.primary_subject:
        return True
    if candidate.resolved_entities and candidate.resolved_entities != candidate.subject_entities:
        return True
    if candidate.observed_entities and candidate.subject_entities and candidate.observed_entities != candidate.subject_entities:
        return True
    return False


def _has_direct_evidence(evidence_bundle: dict[str, Any] | None) -> bool:
    bundle = evidence_bundle or {}
    return bool(_collect_text_fragments(bundle))


def _collect_text_fragments(value: Any) -> list[str]:
    fragments: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            fragments.extend(_collect_text_fragments(item))
        return fragments
    if isinstance(value, (list, tuple, set)):
        for item in value:
            fragments.extend(_collect_text_fragments(item))
        return fragments
    text = str(value or "").strip()
    if text:
        fragments.append(text)
    return fragments


def _merge_unique(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for item in group:
            text = str(item or "").strip()
            if text and text not in merged:
                merged.append(text)
    return merged


def _normalize_observed_entities(
    base: ContentUnderstanding,
    *,
    fallback_subject_entities: list[SubjectEntity],
) -> list[SubjectEntity]:
    observed_entities = list(base.observed_entities or fallback_subject_entities)
    primary_candidates = _preferred_primary_candidates(base)
    component_candidates = {
        str(item).strip().lower()
        for item in [*base.semantic_facts.component_candidates, *base.semantic_facts.aspect_candidates]
        if str(item).strip()
    }
    if not primary_candidates:
        return observed_entities

    observed_names = {
        str(entity.name or "").strip().lower()
        for entity in observed_entities
        if str(entity.name or "").strip()
    }
    if (not observed_entities or observed_names.issubset(component_candidates)) and primary_candidates[0].lower() not in observed_names:
        return [SubjectEntity(kind="product", name=primary_candidates[0])] + observed_entities
    return observed_entities


def _is_component_biased_resolved_primary_subject(
    base: ContentUnderstanding,
    candidate: ContentUnderstanding,
) -> bool:
    resolved_name = str(candidate.resolved_primary_subject or "").strip().lower()
    if not resolved_name:
        return False

    primary_candidates = {item.lower() for item in _preferred_primary_candidates(base)}
    component_candidates = [
        str(item).strip().lower()
        for item in [*base.semantic_facts.component_candidates, *base.semantic_facts.aspect_candidates]
        if str(item).strip()
    ]
    if component_candidates and any(component in resolved_name for component in component_candidates) and not any(
        resolved_name == primary or resolved_name.startswith(primary)
        for primary in primary_candidates
    ):
        return True
    if component_candidates and any(component in resolved_name for component in component_candidates):
        cleaner_primary_candidates = [
            primary
            for primary in primary_candidates
            if primary and primary != resolved_name and primary in resolved_name and not any(component in primary for component in component_candidates)
        ]
        if cleaner_primary_candidates:
            return True

    product_like_resolved_entities = [
        str(entity.name or "").strip().lower()
        for entity in candidate.resolved_entities
        if str(entity.name or "").strip()
        and str(entity.kind or "").strip().lower() in {"product", "产品", "产品类别", "device", "hardware"}
    ]
    component_like_resolved_entities = [
        str(entity.name or "").strip().lower()
        for entity in candidate.resolved_entities
        if str(entity.name or "").strip()
        and str(entity.kind or "").strip().lower() in {"system", "component", "功能系统", "组件", "调节机构", "背负方式", "feature"}
    ]
    if product_like_resolved_entities and component_like_resolved_entities:
        if any(component in resolved_name for component in component_like_resolved_entities) and not any(
            resolved_name == product or resolved_name.startswith(product)
            for product in product_like_resolved_entities
        ):
            return True
    if product_like_resolved_entities and component_candidates and any(component in resolved_name for component in component_candidates):
        if any(product and product != resolved_name and product in resolved_name for product in product_like_resolved_entities):
            return True
    return False


def _preferred_resolved_product_entity(candidate: ContentUnderstanding) -> SubjectEntity | None:
    for entity in candidate.resolved_entities:
        kind = str(entity.kind or "").strip().lower()
        name = str(entity.name or "").strip()
        if not name:
            continue
        if kind in {"product", "产品", "产品类别", "device", "hardware"}:
            return entity
    return None


def _is_supporting_biased_resolved_primary_subject(
    base: ContentUnderstanding,
    candidate: ContentUnderstanding,
) -> bool:
    resolved_name = str(candidate.resolved_primary_subject or "").strip().lower()
    if not resolved_name:
        return False

    secondary_subject_candidates = _secondary_subject_candidates(base)
    secondary_subject_candidates.extend(_secondary_product_entity_names(candidate))
    secondary_subject_candidates = list(dict.fromkeys(item for item in secondary_subject_candidates if item))
    if not secondary_subject_candidates:
        return False

    matched_secondary = [item for item in secondary_subject_candidates if item in resolved_name]
    if not matched_secondary:
        return False

    preferred_primary = [
        item.lower()
        for item in _preferred_primary_candidates(base)
        if not _contains_secondary_subject(item, secondary_subject_candidates)
    ]
    preferred_primary.extend(
        item.lower()
        for item in _resolved_primary_candidates(candidate, secondary_subject_candidates)
        if item
    )
    preferred_primary = list(dict.fromkeys(item for item in preferred_primary if item))
    if not preferred_primary:
        return False
    return any(primary in resolved_name for primary in preferred_primary)


def _preferred_primary_candidates(base: ContentUnderstanding) -> list[str]:
    component_candidates = {
        str(item).strip().lower()
        for item in [*base.semantic_facts.component_candidates, *base.semantic_facts.aspect_candidates]
        if str(item).strip()
    }
    ordered: list[str] = []
    for group in (
        [item for item in base.semantic_facts.primary_subject_candidates if str(item).strip().lower() not in component_candidates],
        [item for item in base.semantic_facts.primary_subject_candidates if str(item).strip().lower() in component_candidates],
        list(base.semantic_facts.product_name_candidates),
        list(base.semantic_facts.product_type_candidates),
    ):
        for item in group:
            text = str(item).strip()
            if text and text not in ordered:
                ordered.append(text)
    return ordered


def _secondary_subject_candidates(base: ContentUnderstanding) -> list[str]:
    semantic_facts = base.semantic_facts
    secondary: list[str] = []
    for item in [*semantic_facts.comparison_subject_candidates, *semantic_facts.supporting_product_candidates]:
        text = str(item).strip().lower()
        if text and text not in secondary:
            secondary.append(text)

    brand_candidates = {
        str(item).strip().lower()
        for item in semantic_facts.brand_candidates
        if str(item).strip()
    }
    collaboration_text = " ".join(
        str(item).strip().lower()
        for item in semantic_facts.collaboration_pairs
        if str(item).strip()
    )
    for item in semantic_facts.supporting_subject_candidates:
        text = str(item).strip().lower()
        if not text:
            continue
        if text in brand_candidates:
            continue
        if collaboration_text and text in collaboration_text:
            continue
        if text not in secondary:
            secondary.append(text)
    return secondary


def _contains_secondary_subject(text: str, secondary_subject_candidates: list[str]) -> bool:
    normalized_text = str(text or "").strip().lower()
    if not normalized_text:
        return False
    return any(len(candidate) >= 2 and candidate in normalized_text for candidate in secondary_subject_candidates)


def _secondary_product_entity_names(candidate: ContentUnderstanding) -> list[str]:
    secondary_kind_markers = ("配套", "accessory", "related", "secondary")
    names: list[str] = []
    for entity in candidate.resolved_entities:
        kind = str(entity.kind or "").strip().lower()
        name = str(entity.name or "").strip().lower()
        if not name:
            continue
        if any(marker in kind for marker in secondary_kind_markers) and name not in names:
            names.append(name)
    return names


def _resolved_primary_candidates(
    candidate: ContentUnderstanding,
    secondary_subject_candidates: list[str],
) -> list[str]:
    candidates: list[str] = []
    for mapping in candidate.entity_resolution_map:
        resolved_name = str(mapping.resolved_name or "").strip()
        if not resolved_name:
            continue
        if _contains_secondary_subject(resolved_name, secondary_subject_candidates):
            continue
        if resolved_name not in candidates:
            candidates.append(resolved_name)
    return candidates
