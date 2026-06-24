from __future__ import annotations

from typing import Any

from roughcut.edit.capability_orchestrator import build_capability_orchestration_payload
from roughcut.edit.local_asset_inventory import build_uploaded_material_inventory
from roughcut.edit.product_controls import build_product_controls_payload
from roughcut.edit.strategy_review_gates import (
    build_strategy_review_gate_status,
    normalize_strategy_review_gate_confirmations,
)
from roughcut.edit.strategy_profile import build_strategy_profile_payload, infer_strategy_type


def extract_content_profile_source_context_from_steps(steps: Any) -> dict[str, Any]:
    for step in list(steps or []):
        if str(getattr(step, "step_name", "") or "").strip() != "content_profile":
            continue
        metadata = getattr(step, "metadata_", None)
        if not isinstance(metadata, dict):
            continue
        source_context = metadata.get("source_context")
        if isinstance(source_context, dict):
            return dict(source_context)
    return {}


def resolve_job_merged_source_names(job: Any) -> list[str]:
    source_context = extract_content_profile_source_context_from_steps(getattr(job, "steps", []) or [])
    return [
        str(item).strip()
        for item in list(source_context.get("merged_source_names") or [])
        if str(item).strip()
    ]


def build_content_profile_local_asset_inventory(
    job: Any | None,
    profile: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = profile if isinstance(profile, dict) else {}
    fallback_merged_source_names = resolve_job_merged_source_names(job) if job is not None else []
    merged_source_candidates = (
        payload.get("merged_source_names")
        if isinstance(payload.get("merged_source_names"), list)
        else None
    )
    merged_source_names = [
        str(item).strip()
        for item in (merged_source_candidates if merged_source_candidates is not None else fallback_merged_source_names)
        if str(item).strip()
    ]
    packaging_snapshot = getattr(job, "packaging_snapshot_json", None) if job is not None else None
    return build_uploaded_material_inventory(
        has_primary_video=job is not None,
        merged_source_names=merged_source_names,
        packaging_snapshot=packaging_snapshot if isinstance(packaging_snapshot, dict) else None,
    )


def attach_content_profile_capability_orchestration(
    profile: dict[str, Any] | None,
    *,
    job: Any | None,
    strategy_review_gate_confirmations: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(profile, dict):
        return profile
    enriched = dict(profile)
    local_asset_inventory = build_content_profile_local_asset_inventory(job, enriched)
    job_source_context = (
        extract_content_profile_source_context_from_steps(getattr(job, "steps", []) or [])
        if job is not None and hasattr(job, "steps")
        else {}
    )
    source_context = enriched.get("source_context") if isinstance(enriched.get("source_context"), dict) else {}
    requested_product_controls = (
        dict(source_context.get("product_controls") or {})
        if isinstance(source_context.get("product_controls"), dict)
        else dict(job_source_context.get("product_controls") or {})
        if isinstance(job_source_context.get("product_controls"), dict)
        else {}
    )
    if job_source_context:
        merged_source_context = dict(source_context)
        for key in ("product_controls", "strategy_classification", "classification"):
            if key not in merged_source_context and isinstance(job_source_context.get(key), dict):
                merged_source_context[key] = dict(job_source_context[key])
        if merged_source_context:
            enriched["source_context"] = merged_source_context
    if "smart_cut_rules" not in enriched and isinstance(job_source_context.get("smart_cut_rules"), dict):
        enriched["smart_cut_rules"] = dict(job_source_context["smart_cut_rules"])
    if "material_enhancement_modes" not in enriched and isinstance(job_source_context.get("material_enhancement_modes"), list):
        enriched["material_enhancement_modes"] = list(job_source_context["material_enhancement_modes"])
    requested_capability_overrides = (
        dict(job_source_context.get("capability_overrides") or {})
        if isinstance(job_source_context.get("capability_overrides"), dict)
        else {}
    )
    strategy_profile = build_strategy_profile_payload(
        strategy_type=infer_strategy_type(
            strategy_profile=enriched.get("strategy_profile")
            if isinstance(enriched.get("strategy_profile"), dict)
            else None,
            workflow_template=str(
                getattr(job, "workflow_template", "") or enriched.get("workflow_template") or ""
            ).strip()
            or None,
            content_profile=enriched,
            local_asset_inventory=local_asset_inventory,
        )
    )
    product_controls = build_product_controls_payload(
        requested_product_controls,
        strategy_type=strategy_profile.get("strategy_type"),
        content_kind=enriched.get("content_kind"),
        local_asset_inventory=local_asset_inventory,
        job_flow_mode=str(getattr(job, "job_flow_mode", "") or "auto"),
    )
    enriched["product_controls"] = product_controls
    orchestration = build_capability_orchestration_payload(
        strategy_profile=strategy_profile,
        workflow_template=str(
            getattr(job, "workflow_template", "") or enriched.get("workflow_template") or ""
        ).strip()
        or None,
        content_profile=enriched,
        local_asset_inventory=local_asset_inventory,
        job_flow_mode=str(getattr(job, "job_flow_mode", "") or "auto"),
        product_controls=product_controls,
        capability_overrides=requested_capability_overrides,
    )
    normalized_confirmations = normalize_strategy_review_gate_confirmations(
        strategy_review_gate_confirmations,
        pipeline_plan=orchestration.get("pipeline_plan") if isinstance(orchestration.get("pipeline_plan"), dict) else {},
        classification=orchestration.get("classification") if isinstance(orchestration.get("classification"), dict) else {},
    )
    if normalized_confirmations:
        orchestration = dict(orchestration)
        orchestration["review_gate_status"] = build_strategy_review_gate_status(
            orchestration.get("pipeline_plan"),
            confirmations=normalized_confirmations,
        )
        orchestration["strategy_review_gate_confirmations"] = normalized_confirmations
    enriched["capability_orchestration"] = orchestration
    return enriched
