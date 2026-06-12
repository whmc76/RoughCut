from __future__ import annotations

from typing import Any

from roughcut.edit.packaging_timeline import resolve_packaging_timeline_payload


def resolve_effective_variant_timeline_bundle(bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    if isinstance(bundle, dict) and (
        isinstance(bundle.get("variants"), dict) or isinstance(bundle.get("timeline_rules"), dict)
    ):
        return bundle
    return None


def variant_timeline_rules(bundle: dict[str, Any] | None) -> dict[str, Any]:
    payload = resolve_effective_variant_timeline_bundle(bundle)
    timeline_rules = payload.get("timeline_rules") if isinstance(payload, dict) else None
    return dict(timeline_rules) if isinstance(timeline_rules, dict) else {}


def variant_packaging_timeline(bundle: dict[str, Any] | None) -> dict[str, Any]:
    return resolve_packaging_timeline_payload(variant_timeline_rules(bundle))


def variant_timeline_diagnostics(bundle: dict[str, Any] | None) -> dict[str, Any]:
    timeline_rules = variant_timeline_rules(bundle)
    diagnostics = timeline_rules.get("diagnostics")
    return dict(diagnostics) if isinstance(diagnostics, dict) else {}


def variant_review_flags(bundle: dict[str, Any] | None) -> dict[str, Any]:
    diagnostics = variant_timeline_diagnostics(bundle)
    review_flags = diagnostics.get("review_flags")
    return dict(review_flags) if isinstance(review_flags, dict) else {}


def variant_high_risk_cuts(bundle: dict[str, Any] | None) -> list[dict[str, Any]]:
    diagnostics = variant_timeline_diagnostics(bundle)
    return [dict(item) for item in (diagnostics.get("high_risk_cuts") or []) if isinstance(item, dict)]


def variant_high_energy_keeps(bundle: dict[str, Any] | None) -> list[dict[str, Any]]:
    diagnostics = variant_timeline_diagnostics(bundle)
    return [dict(item) for item in (diagnostics.get("high_energy_keeps") or []) if isinstance(item, dict)]


def variant_cut_evidence_summary(bundle: dict[str, Any] | None) -> dict[str, Any]:
    diagnostics = variant_timeline_diagnostics(bundle)
    cut_evidence_summary = diagnostics.get("cut_evidence_summary")
    return dict(cut_evidence_summary) if isinstance(cut_evidence_summary, dict) else {}


def variant_cut_analysis_summary(bundle: dict[str, Any] | None) -> dict[str, Any]:
    diagnostics = variant_timeline_diagnostics(bundle)
    cut_analysis_summary = diagnostics.get("cut_analysis_summary")
    return dict(cut_analysis_summary) if isinstance(cut_analysis_summary, dict) else {}


def variant_llm_cut_review(bundle: dict[str, Any] | None) -> dict[str, Any]:
    diagnostics = variant_timeline_diagnostics(bundle)
    llm_cut_review = diagnostics.get("llm_cut_review")
    return dict(llm_cut_review) if isinstance(llm_cut_review, dict) else {}


def variant_multimodal_trim_review_summary(bundle: dict[str, Any] | None) -> dict[str, Any]:
    diagnostics = variant_timeline_diagnostics(bundle)
    multimodal_trim_review_summary = diagnostics.get("multimodal_trim_review_summary")
    return dict(multimodal_trim_review_summary) if isinstance(multimodal_trim_review_summary, dict) else {}


def variant_refine_decision_summary(bundle: dict[str, Any] | None) -> dict[str, Any]:
    diagnostics = variant_timeline_diagnostics(bundle)
    refine_decision_summary = diagnostics.get("refine_decision_summary")
    return dict(refine_decision_summary) if isinstance(refine_decision_summary, dict) else {}
