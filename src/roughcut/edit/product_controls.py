from __future__ import annotations

from typing import Any

PRODUCT_CONTROLS_SCHEMA_VERSION = "product_controls.v1"

EDIT_MODE_AUTO = "auto"
EDIT_MODE_TALKING_HEAD = "talking_head"
EDIT_MODE_TUTORIAL = "tutorial"
EDIT_MODE_VLOG = "vlog"
EDIT_MODE_HIGHLIGHT = "highlight"
EDIT_MODE_MULTI_MATERIAL = "multi_material"
EDIT_MODES = {
    EDIT_MODE_AUTO,
    EDIT_MODE_TALKING_HEAD,
    EDIT_MODE_TUTORIAL,
    EDIT_MODE_VLOG,
    EDIT_MODE_HIGHLIGHT,
    EDIT_MODE_MULTI_MATERIAL,
}

AUTOMATION_LEVEL_CONSERVATIVE = "conservative"
AUTOMATION_LEVEL_STANDARD = "standard"
AUTOMATION_LEVEL_RICHER = "richer"
AUTOMATION_LEVELS = {
    AUTOMATION_LEVEL_CONSERVATIVE,
    AUTOMATION_LEVEL_STANDARD,
    AUTOMATION_LEVEL_RICHER,
}

MATERIAL_USAGE_MAIN_ONLY = "main_only"
MATERIAL_USAGE_ALL_UPLOADED = "all_uploaded"
MATERIAL_USAGE_SELECTED_UPLOADED = "selected_uploaded"
MATERIAL_USAGES = {
    MATERIAL_USAGE_MAIN_ONLY,
    MATERIAL_USAGE_ALL_UPLOADED,
    MATERIAL_USAGE_SELECTED_UPLOADED,
}

_EDIT_MODE_ALIASES = {
    "commentary": EDIT_MODE_TALKING_HEAD,
    "talkinghead": EDIT_MODE_TALKING_HEAD,
    "talking_head_commentary": EDIT_MODE_TALKING_HEAD,
    "screen_tutorial": EDIT_MODE_TUTORIAL,
    "gameplay": EDIT_MODE_HIGHLIGHT,
    "gameplay_highlight": EDIT_MODE_HIGHLIGHT,
    "multi": EDIT_MODE_MULTI_MATERIAL,
    "narrative_assembly": EDIT_MODE_MULTI_MATERIAL,
}
_AUTOMATION_LEVEL_ALIASES = {
    "safe": AUTOMATION_LEVEL_CONSERVATIVE,
    "strict": AUTOMATION_LEVEL_CONSERVATIVE,
    "default": AUTOMATION_LEVEL_STANDARD,
    "balanced": AUTOMATION_LEVEL_STANDARD,
    "aggressive": AUTOMATION_LEVEL_RICHER,
    "rich": AUTOMATION_LEVEL_RICHER,
}
_MATERIAL_USAGE_ALIASES = {
    "primary_only": MATERIAL_USAGE_MAIN_ONLY,
    "uploaded_only": MATERIAL_USAGE_ALL_UPLOADED,
    "all": MATERIAL_USAGE_ALL_UPLOADED,
    "selected": MATERIAL_USAGE_SELECTED_UPLOADED,
}
_EDIT_MODE_TEMPLATE_MAP = {
    EDIT_MODE_TALKING_HEAD: "commentary_focus",
    EDIT_MODE_TUTORIAL: "tutorial_standard",
    EDIT_MODE_VLOG: "vlog_daily",
    EDIT_MODE_HIGHLIGHT: "gameplay_highlight",
}
_EDIT_MODE_STRATEGY_MAP = {
    EDIT_MODE_TALKING_HEAD: "information_density",
    EDIT_MODE_TUTORIAL: "step_demonstration",
    EDIT_MODE_VLOG: "experience_and_mood",
    EDIT_MODE_HIGHLIGHT: "event_highlight",
    EDIT_MODE_MULTI_MATERIAL: "narrative_assembly",
}


def normalize_edit_mode(value: Any) -> str:
    normalized = str(value or EDIT_MODE_AUTO).strip().lower()
    normalized = _EDIT_MODE_ALIASES.get(normalized, normalized)
    if normalized not in EDIT_MODES:
        raise ValueError(f"edit_mode must be one of: {', '.join(sorted(EDIT_MODES))}")
    return normalized


def normalize_automation_level(value: Any) -> str:
    normalized = str(value or AUTOMATION_LEVEL_STANDARD).strip().lower()
    normalized = _AUTOMATION_LEVEL_ALIASES.get(normalized, normalized)
    if normalized not in AUTOMATION_LEVELS:
        raise ValueError(f"automation_level must be one of: {', '.join(sorted(AUTOMATION_LEVELS))}")
    return normalized


def normalize_material_usage(value: Any) -> str:
    normalized = str(value or MATERIAL_USAGE_ALL_UPLOADED).strip().lower()
    normalized = _MATERIAL_USAGE_ALIASES.get(normalized, normalized)
    if normalized not in MATERIAL_USAGES:
        raise ValueError(f"material_usage must be one of: {', '.join(sorted(MATERIAL_USAGES))}")
    return normalized


def workflow_template_for_edit_mode(edit_mode: Any) -> str | None:
    return _EDIT_MODE_TEMPLATE_MAP.get(normalize_edit_mode(edit_mode))


def strategy_type_for_edit_mode(edit_mode: Any) -> str | None:
    normalized = normalize_edit_mode(edit_mode)
    if normalized == EDIT_MODE_AUTO:
        return None
    return _EDIT_MODE_STRATEGY_MAP.get(normalized)


def extract_product_controls_from_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(profile or {}) if isinstance(profile, dict) else {}
    direct = payload.get("product_controls")
    if isinstance(direct, dict) and direct:
        return dict(direct)
    source_context = payload.get("source_context")
    if isinstance(source_context, dict):
        source_controls = source_context.get("product_controls")
        if isinstance(source_controls, dict) and source_controls:
            return dict(source_controls)
    return {}


def normalize_requested_product_controls(payload: dict[str, Any] | None) -> dict[str, str]:
    source = dict(payload or {}) if isinstance(payload, dict) else {}
    requested = source.get("requested") if isinstance(source.get("requested"), dict) else {}
    effective = source.get("effective") if isinstance(source.get("effective"), dict) else {}
    return {
        "edit_mode": normalize_edit_mode(
            source.get("edit_mode") or requested.get("edit_mode") or effective.get("edit_mode")
        ),
        "automation_level": normalize_automation_level(
            source.get("automation_level") or requested.get("automation_level") or effective.get("automation_level")
        ),
        "material_usage": normalize_material_usage(
            source.get("material_usage") or requested.get("material_usage") or effective.get("material_usage")
        ),
    }


def build_product_controls_payload(
    payload: dict[str, Any] | None = None,
    *,
    strategy_type: Any = "",
    content_kind: Any = "",
    local_asset_inventory: dict[str, Any] | None = None,
    job_flow_mode: Any = "auto",
) -> dict[str, Any]:
    requested = normalize_requested_product_controls(payload)
    inventory = dict(local_asset_inventory or {}) if isinstance(local_asset_inventory, dict) else {}
    normalized_strategy_type = str(strategy_type or "").strip().lower()
    normalized_content_kind = str(content_kind or "").strip().lower()

    recommended_edit_mode = EDIT_MODE_AUTO
    if normalized_strategy_type == "step_demonstration" or normalized_content_kind == "tutorial":
        recommended_edit_mode = EDIT_MODE_TUTORIAL
    elif normalized_strategy_type == "event_highlight" or normalized_content_kind == "gameplay":
        recommended_edit_mode = EDIT_MODE_HIGHLIGHT
    elif normalized_strategy_type == "experience_and_mood" or normalized_content_kind in {"vlog", "food"}:
        recommended_edit_mode = EDIT_MODE_VLOG
    elif normalized_strategy_type == "narrative_assembly":
        recommended_edit_mode = EDIT_MODE_MULTI_MATERIAL
    elif normalized_content_kind == "commentary":
        recommended_edit_mode = EDIT_MODE_TALKING_HEAD

    effective_automation_level = requested["automation_level"]
    if str(job_flow_mode or "").strip().lower() != "auto" and effective_automation_level == AUTOMATION_LEVEL_RICHER:
        effective_automation_level = AUTOMATION_LEVEL_STANDARD

    return {
        "schema": PRODUCT_CONTROLS_SCHEMA_VERSION,
        "requested": requested,
        "recommended": {
            "edit_mode": recommended_edit_mode,
            "automation_level": AUTOMATION_LEVEL_STANDARD,
            "material_usage": MATERIAL_USAGE_ALL_UPLOADED,
        },
        "effective": {
            "edit_mode": recommended_edit_mode if requested["edit_mode"] == EDIT_MODE_AUTO else requested["edit_mode"],
            "automation_level": effective_automation_level,
            "material_usage": requested["material_usage"],
        },
        "multi_material_ready": bool(inventory.get("multi_material_ready")),
        "has_visual_inserts": bool(inventory.get("has_visual_inserts")),
        "has_audio_support": bool(inventory.get("has_audio_support")),
    }


def resolve_product_controls_for_profile(
    profile: dict[str, Any] | None,
    *,
    strategy_type: Any = "",
    content_kind: Any = "",
    local_asset_inventory: dict[str, Any] | None = None,
    job_flow_mode: Any = "auto",
) -> dict[str, Any]:
    return build_product_controls_payload(
        extract_product_controls_from_profile(profile),
        strategy_type=strategy_type,
        content_kind=content_kind,
        local_asset_inventory=local_asset_inventory,
        job_flow_mode=job_flow_mode,
    )
