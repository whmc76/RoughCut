from __future__ import annotations

from typing import Any

from roughcut.edit.capabilities import (
    CAPABILITY_METADATA,
    CAPABILITY_KEYS,
    build_disabled_capability_map,
    normalize_capability_overrides,
)
from roughcut.edit.capability_policy import resolve_capability_strategy_inputs, resolve_default_capability_states
from roughcut.edit.product_controls import (
    AUTOMATION_LEVEL_CONSERVATIVE,
    MATERIAL_USAGE_MAIN_ONLY,
    MATERIAL_USAGE_SELECTED_UPLOADED,
    build_product_controls_payload,
)


CAPABILITY_ORCHESTRATION_SCHEMA_VERSION = "capability_orchestration.v1"


def normalize_local_asset_inventory(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(payload or {}) if isinstance(payload, dict) else {}

    def _list_count(*keys: str) -> int:
        for key in keys:
            value = source.get(key)
            if isinstance(value, (list, tuple, set)):
                return len([item for item in value if item])
        return 0

    def _int_value(*keys: str) -> int:
        for key in keys:
            value = source.get(key)
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, int):
                return max(0, value)
            try:
                if value is not None and str(value).strip():
                    return max(0, int(value))
            except (TypeError, ValueError):
                continue
        return 0

    auxiliary_video_count = max(
        _int_value("auxiliary_video_count", "uploaded_auxiliary_video_count", "extra_video_file_count"),
        _list_count("auxiliary_videos", "uploaded_auxiliary_videos", "extra_video_files"),
    )
    image_count = max(
        _int_value("image_count", "uploaded_image_count", "extra_image_file_count", "still_image_count"),
        _list_count("images", "uploaded_images", "extra_image_files", "still_images"),
    )
    audio_count = max(
        _int_value("audio_count", "uploaded_audio_count", "music_asset_count", "sfx_asset_count"),
        _list_count("audio_files", "uploaded_audio_files", "music_assets", "sfx_assets"),
    )
    intro_outro_count = max(
        _int_value("intro_outro_count"),
        _list_count("intro_assets", "outro_assets"),
    )
    watermark_count = max(
        _int_value("watermark_count"),
        _list_count("watermark_assets"),
    )
    primary_video_count = max(
        1 if source.get("has_primary_video") else 0,
        _int_value("primary_video_count"),
    )
    visual_insert_count = auxiliary_video_count + image_count
    total_uploaded_material_count = (
        primary_video_count + auxiliary_video_count + image_count + audio_count + intro_outro_count + watermark_count
    )

    return {
        "primary_video_count": primary_video_count,
        "auxiliary_video_count": auxiliary_video_count,
        "image_count": image_count,
        "audio_count": audio_count,
        "intro_outro_count": intro_outro_count,
        "watermark_count": watermark_count,
        "visual_insert_count": visual_insert_count,
        "has_visual_inserts": visual_insert_count > 0,
        "has_audio_support": audio_count > 0,
        "total_uploaded_material_count": total_uploaded_material_count,
        "multi_material_ready": auxiliary_video_count + image_count >= 2,
    }


def build_capability_orchestration_payload(
    *,
    strategy_profile: dict[str, Any] | None = None,
    workflow_template: str | None = None,
    content_profile: dict[str, Any] | None = None,
    local_asset_inventory: dict[str, Any] | None = None,
    job_flow_mode: Any = "auto",
    capability_overrides: dict[str, Any] | None = None,
    product_controls: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_inputs = resolve_capability_strategy_inputs(
        strategy_profile=strategy_profile,
        workflow_template=workflow_template,
        content_profile=content_profile,
    )
    resolved_capabilities = resolve_default_capability_states(
        strategy_profile=resolved_inputs["strategy_profile"],
        workflow_template=workflow_template,
        content_profile=content_profile,
    )
    normalized_inventory = normalize_local_asset_inventory(local_asset_inventory)
    normalized_overrides = normalize_capability_overrides(capability_overrides)
    product_control_payload = build_product_controls_payload(
        product_controls,
        strategy_type=resolved_inputs["strategy_type"],
        content_kind=resolved_inputs["content_kind"],
        local_asset_inventory=normalized_inventory,
        job_flow_mode=job_flow_mode,
    )

    capabilities = build_disabled_capability_map()
    capabilities.update(resolved_capabilities)

    if not normalized_inventory["has_visual_inserts"]:
        capabilities["local_broll_insert"] = "disabled"
    if not normalized_inventory["has_audio_support"]:
        capabilities["local_audio_cues"] = "disabled"
    if not normalized_inventory["multi_material_ready"]:
        capabilities["multi_material_assembly"] = "disabled"

    if str(job_flow_mode or "").strip().lower() != "auto":
        for key, state in list(capabilities.items()):
            if state == "auto_apply":
                capabilities[key] = "suggest"

    effective_controls = dict(product_control_payload.get("effective") or {})
    if str(effective_controls.get("material_usage") or "").strip() == MATERIAL_USAGE_MAIN_ONLY:
        capabilities["local_broll_insert"] = "disabled"
        capabilities["local_audio_cues"] = "disabled"
        capabilities["multi_material_assembly"] = "disabled"
    elif str(effective_controls.get("material_usage") or "").strip() == MATERIAL_USAGE_SELECTED_UPLOADED:
        if capabilities["local_broll_insert"] == "auto_apply":
            capabilities["local_broll_insert"] = "suggest"
        if capabilities["local_audio_cues"] == "auto_apply":
            capabilities["local_audio_cues"] = "suggest"
        if capabilities["multi_material_assembly"] != "disabled":
            capabilities["multi_material_assembly"] = "manual_required"

    if str(effective_controls.get("automation_level") or "").strip() == AUTOMATION_LEVEL_CONSERVATIVE:
        for key in ("screen_focus", "chapter_cards", "highlight_window_selection", "local_broll_insert", "local_audio_cues"):
            if capabilities[key] == "auto_apply":
                capabilities[key] = "suggest"
        if capabilities["multi_material_assembly"] == "auto_apply":
            capabilities["multi_material_assembly"] = "manual_required"

    capabilities.update(normalized_overrides)

    return {
        "schema": CAPABILITY_ORCHESTRATION_SCHEMA_VERSION,
        "strategy_type": resolved_inputs["strategy_type"],
        "strategy_profile": resolved_inputs["strategy_profile"],
        "workflow_template": resolved_inputs["workflow_template"],
        "content_kind": resolved_inputs["content_kind"],
        "job_flow_mode": str(job_flow_mode or "").strip().lower() or "auto",
        "product_controls": product_control_payload,
        "local_asset_inventory": normalized_inventory,
        "capabilities": {key: capabilities[key] for key in CAPABILITY_KEYS},
        "capability_metadata": {key: dict(CAPABILITY_METADATA[key]) for key in CAPABILITY_KEYS},
        "editing_skill_key": str((resolved_inputs["editing_skill"] or {}).get("key") or "").strip(),
    }
