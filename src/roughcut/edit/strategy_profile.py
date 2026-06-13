from __future__ import annotations

from typing import Any, Literal, cast

from roughcut.edit.presets import select_workflow_template
from roughcut.edit.product_controls import (
    EDIT_MODE_AUTO,
    extract_product_controls_from_profile,
    normalize_requested_product_controls,
    strategy_type_for_edit_mode,
)


STRATEGY_PROFILE_SCHEMA_VERSION = "strategy_profile.v1"
DEFAULT_STRATEGY_TYPE = "information_density"
_VALID_STRATEGY_TYPES = {
    "information_density",
    "step_demonstration",
    "experience_and_mood",
    "event_highlight",
    "narrative_assembly",
}

StrategyType = Literal[
    "information_density",
    "step_demonstration",
    "experience_and_mood",
    "event_highlight",
    "narrative_assembly",
]


def normalize_strategy_type(value: Any) -> StrategyType:
    normalized = str(value or "").strip().lower()
    if normalized in _VALID_STRATEGY_TYPES:
        return cast(StrategyType, normalized)
    return DEFAULT_STRATEGY_TYPE


def infer_strategy_content_kind(
    *,
    workflow_template: str | None = None,
    content_profile: dict[str, Any] | None = None,
) -> str:
    profile = dict(content_profile or {}) if isinstance(content_profile, dict) else {}
    content_understanding = (
        profile.get("content_understanding")
        if isinstance(profile.get("content_understanding"), dict)
        else {}
    )
    explicit_kind = str(
        profile.get("content_kind")
        or content_understanding.get("video_type")
        or ""
    ).strip().lower()
    if explicit_kind:
        return explicit_kind
    preset = select_workflow_template(
        workflow_template=workflow_template or str(profile.get("workflow_template") or "").strip() or None,
        content_kind=str(profile.get("content_kind") or "").strip(),
        subject_domain=str(profile.get("subject_domain") or "").strip(),
        subject_model=str(profile.get("subject_model") or "").strip(),
        subject_type=str(profile.get("subject_type") or "").strip(),
        transcript_hint=str(profile.get("summary") or profile.get("video_theme") or "").strip(),
    )
    return str(preset.content_kind or "").strip().lower()


def infer_strategy_type(
    *,
    strategy_profile: dict[str, Any] | None = None,
    workflow_template: str | None = None,
    content_profile: dict[str, Any] | None = None,
    local_asset_inventory: dict[str, Any] | None = None,
) -> StrategyType:
    existing_strategy = strategy_profile if isinstance(strategy_profile, dict) else {}
    explicit_raw = str(existing_strategy.get("strategy_type") or "").strip()
    if explicit_raw:
        return normalize_strategy_type(explicit_raw)

    requested_product_controls = normalize_requested_product_controls(
        extract_product_controls_from_profile(content_profile)
    )
    explicit_edit_mode_strategy = strategy_type_for_edit_mode(requested_product_controls.get("edit_mode"))
    if requested_product_controls.get("edit_mode") != EDIT_MODE_AUTO and explicit_edit_mode_strategy:
        return normalize_strategy_type(explicit_edit_mode_strategy)

    content_kind = infer_strategy_content_kind(
        workflow_template=workflow_template,
        content_profile=content_profile,
    )
    if content_kind == "tutorial":
        return "step_demonstration"
    if content_kind in {"vlog", "food"}:
        return "experience_and_mood"
    if content_kind == "gameplay":
        return "event_highlight"

    inventory = dict(local_asset_inventory or {}) if isinstance(local_asset_inventory, dict) else {}
    if bool(inventory.get("multi_material_ready")) and content_kind in {"commentary", "unboxing"}:
        return "narrative_assembly"
    return DEFAULT_STRATEGY_TYPE


def build_strategy_profile_payload(
    *,
    strategy_type: Any = DEFAULT_STRATEGY_TYPE,
    auto_apply_policy: Any = "current_conservative_default",
    speech_priority: Any = "high",
    visual_priority: Any = "medium",
    silence_policy: Any = "trim_unvoiced_gaps",
    packaging_policy: Any = "current_default",
) -> dict[str, Any]:
    return {
        "schema": STRATEGY_PROFILE_SCHEMA_VERSION,
        "strategy_type": normalize_strategy_type(strategy_type),
        "auto_apply_policy": str(auto_apply_policy or "current_conservative_default").strip()
        or "current_conservative_default",
        "speech_priority": str(speech_priority or "high").strip() or "high",
        "visual_priority": str(visual_priority or "medium").strip() or "medium",
        "silence_policy": str(silence_policy or "trim_unvoiced_gaps").strip() or "trim_unvoiced_gaps",
        "packaging_policy": str(packaging_policy or "current_default").strip() or "current_default",
    }


def normalize_strategy_profile_payload(
    payload: dict[str, Any] | None,
    *,
    default_strategy_type: Any = DEFAULT_STRATEGY_TYPE,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return build_strategy_profile_payload(strategy_type=default_strategy_type)
    normalized = build_strategy_profile_payload(
        strategy_type=payload.get("strategy_type") or default_strategy_type,
        auto_apply_policy=payload.get("auto_apply_policy"),
        speech_priority=payload.get("speech_priority"),
        visual_priority=payload.get("visual_priority"),
        silence_policy=payload.get("silence_policy"),
        packaging_policy=payload.get("packaging_policy"),
    )
    schema = str(payload.get("schema") or "").strip()
    normalized["schema"] = schema or STRATEGY_PROFILE_SCHEMA_VERSION
    return normalized


def payload_strategy_profile(
    payload: dict[str, Any] | None,
    *,
    default_strategy_type: Any = DEFAULT_STRATEGY_TYPE,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return build_strategy_profile_payload(strategy_type=default_strategy_type)
    strategy_profile = payload.get("strategy_profile")
    if isinstance(strategy_profile, dict):
        return normalize_strategy_profile_payload(
            strategy_profile,
            default_strategy_type=payload.get("strategy_type") or default_strategy_type,
        )
    return build_strategy_profile_payload(
        strategy_type=payload.get("strategy_type") or default_strategy_type,
    )


def payload_strategy_type(
    payload: dict[str, Any] | None,
    *,
    default_strategy_type: Any = DEFAULT_STRATEGY_TYPE,
) -> StrategyType:
    if not isinstance(payload, dict):
        return normalize_strategy_type(default_strategy_type)
    return normalize_strategy_type(
        payload_strategy_profile(payload, default_strategy_type=default_strategy_type).get("strategy_type")
    )
