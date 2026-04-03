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
    use_resolved = bool(
        allow_entity_resolution
        and candidate.resolved_primary_subject
        and candidate.resolved_entities
        and resolution_confidence >= _RESOLUTION_CONFIDENCE_THRESHOLD
    )
    review_reasons = _merge_unique(
        list(base.review_reasons),
        list(candidate.review_reasons),
        [
            "缺少直接视频证据，外部搜索/内部检索仅作弱佐证" if not has_direct_evidence else "",
            "核验结果与当前视频结论存在冲突，已保守保留原结论" if conflicts else "",
        ],
    )
    uncertainties = _merge_unique(list(base.uncertainties), list(candidate.uncertainties))
    merged_conflicts = _merge_unique(list(base.conflicts), list(candidate.conflicts), conflicts)
    needs_review = bool(base.needs_review or candidate.needs_review or not has_direct_evidence or conflicts)
    primary_subject = candidate.resolved_primary_subject if use_resolved else base.primary_subject
    subject_entities = list(candidate.resolved_entities) if use_resolved else list(base.subject_entities)
    observed_entities = _normalize_observed_entities(base, fallback_subject_entities=subject_entities)
    return replace(
        base,
        primary_subject=primary_subject,
        subject_entities=subject_entities,
        observed_entities=observed_entities,
        resolved_entities=list(candidate.resolved_entities),
        resolved_primary_subject=candidate.resolved_primary_subject,
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
    primary_candidates = [str(item).strip() for item in base.semantic_facts.primary_subject_candidates if str(item).strip()]
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
