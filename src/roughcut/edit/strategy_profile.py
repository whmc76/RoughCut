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
STRATEGY_CLASSIFICATION_SCHEMA_VERSION = "strategy_classification.v1"
STRATEGY_PIPELINE_PLAN_SCHEMA_VERSION = "strategy_pipeline_plan.v1"
STRATEGY_POLICY_SCHEMA_VERSION = "strategy_policy.v1"
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

_NARRATIVE_ASSEMBLY_TAGS = {
    "avatar_commentary",
    "digital_human",
    "script_driven",
    "needs_broll",
    "material_insert_required",
    "storyboard_required",
    "remix",
    "multi_material",
}
_STEP_DEMONSTRATION_TAGS = {
    "tutorial",
    "screen_recording",
    "step_by_step",
    "operation_demo",
    "workflow_breakdown",
}
_EVENT_HIGHLIGHT_TAGS = {"gameplay", "highlight", "event_highlight"}
_EVENT_HIGHLIGHT_CONTEXT_TAGS = {"sports", "match", "competition", "race", "performance", "action_peak"}
_EXPERIENCE_TAGS = {"vlog", "food", "travel", "experience", "mood"}
_INFORMATION_DENSITY_TAGS = {
    "talking_head",
    "commentary",
    "single_speaker",
    "speech_dominant",
    "retake_likely",
    "silence_trim_useful",
    "subtitle_important",
}

_STRATEGY_POLICY_REGISTRY: dict[str, dict[str, Any]] = {
    "information_density": {
        "label": "Speech density and smart cleanup",
        "cut_policy": {
            "basis": "audio_word_boundary",
            "snap_to_word_boundary": True,
            "edge_padding_ms": [50, 120],
            "min_silence_cut_ms": 400,
            "preserve_reaction_pause": True,
            "delete_previous_retake": True,
        },
        "review_policy": {
            "strategy_confirmation": "optional",
            "manual_cut_review": "recommended",
            "storyboard_review": "off",
            "timeline_preview": "optional",
        },
        "render_validation_policy": {
            "check_audio_presence": True,
            "check_output_subtitle_timeline": True,
            "check_cut_boundaries": True,
            "check_storyboard_alignment": False,
        },
        "capability_defaults": {
            "speech_density_trim": "auto_apply",
            "source_media_inspection": "auto_apply",
            "delivery_quality_governance": "auto_apply",
        },
    },
    "step_demonstration": {
        "label": "Step demonstration",
        "cut_policy": {
            "basis": "speech_and_screen_steps",
            "snap_to_word_boundary": True,
            "edge_padding_ms": [80, 180],
            "min_silence_cut_ms": 500,
            "preserve_operation_context": True,
        },
        "review_policy": {
            "strategy_confirmation": "optional",
            "manual_cut_review": "recommended",
            "storyboard_review": "off",
            "timeline_preview": "optional",
        },
        "render_validation_policy": {
            "check_audio_presence": True,
            "check_output_subtitle_timeline": True,
            "check_cut_boundaries": True,
            "check_screen_focus_safe_frame": True,
        },
        "capability_defaults": {
            "speech_density_trim": "auto_apply",
            "source_media_inspection": "auto_apply",
            "screen_focus": "auto_apply",
            "chapter_cards": "suggest",
            "delivery_quality_governance": "auto_apply",
        },
    },
    "experience_and_mood": {
        "label": "Experience and mood",
        "cut_policy": {
            "basis": "experience_beats",
            "snap_to_word_boundary": True,
            "edge_padding_ms": [120, 220],
            "min_silence_cut_ms": 650,
            "preserve_atmosphere": True,
        },
        "review_policy": {
            "strategy_confirmation": "optional",
            "manual_cut_review": "optional",
            "storyboard_review": "off",
            "timeline_preview": "optional",
        },
        "render_validation_policy": {
            "check_audio_presence": True,
            "check_output_subtitle_timeline": True,
            "check_cut_boundaries": False,
            "check_music_cue_balance": True,
        },
        "capability_defaults": {
            "reference_style_analysis": "suggest",
            "source_media_inspection": "auto_apply",
            "speech_density_trim": "suggest",
            "soundtrack_audio_mix": "suggest",
            "local_audio_cues": "suggest",
            "delivery_quality_governance": "auto_apply",
        },
    },
    "event_highlight": {
        "label": "Event highlight",
        "cut_policy": {
            "basis": "highlight_window",
            "snap_to_word_boundary": False,
            "edge_padding_ms": [60, 160],
            "preserve_high_energy_peaks": True,
            "protect_visual_action": True,
        },
        "review_policy": {
            "strategy_confirmation": "optional",
            "manual_cut_review": "recommended",
            "storyboard_review": "off",
            "timeline_preview": "optional",
        },
        "render_validation_policy": {
            "check_audio_presence": True,
            "check_output_subtitle_timeline": True,
            "check_highlight_boundary_frames": True,
            "check_cut_boundaries": True,
        },
        "capability_defaults": {
            "reference_style_analysis": "suggest",
            "source_media_inspection": "auto_apply",
            "highlight_window_selection": "suggest",
            "soundtrack_audio_mix": "suggest",
            "local_audio_cues": "suggest",
            "delivery_quality_governance": "auto_apply",
        },
    },
    "narrative_assembly": {
        "label": "Narrative assembly",
        "cut_policy": {
            "basis": "script_segment",
            "align_visuals_to_subtitle_sentences": True,
            "protect_anchor_delivery": True,
            "material_insert_required": True,
        },
        "review_policy": {
            "strategy_confirmation": "required",
            "manual_cut_review": "optional",
            "storyboard_review": "required",
            "timeline_preview": "required",
        },
        "render_validation_policy": {
            "check_audio_presence": True,
            "check_output_subtitle_timeline": True,
            "check_storyboard_alignment": True,
            "check_timeline_preview_alignment": True,
            "check_overlay_subtitle_occlusion": True,
        },
        "capability_defaults": {
            "reference_style_analysis": "suggest",
            "source_media_inspection": "auto_apply",
            "stock_footage_retrieval": "suggest",
            "generative_scene_plan": "suggest",
            "local_broll_insert": "suggest",
            "local_audio_cues": "suggest",
            "soundtrack_audio_mix": "suggest",
            "multi_material_assembly": "manual_required",
            "cost_budget_governance": "manual_required",
            "delivery_quality_governance": "auto_apply",
        },
    },
}


def normalize_strategy_type(value: Any) -> StrategyType:
    normalized = str(value or "").strip().lower()
    if normalized in _VALID_STRATEGY_TYPES:
        return cast(StrategyType, normalized)
    return DEFAULT_STRATEGY_TYPE


def _copy_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    copied: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict):
            copied[key] = _copy_dict(item)
        elif isinstance(item, list):
            copied[key] = list(item)
        else:
            copied[key] = item
    return copied


def resolve_strategy_policy(strategy_type: Any) -> dict[str, Any]:
    normalized_strategy_type = normalize_strategy_type(strategy_type)
    source = _STRATEGY_POLICY_REGISTRY.get(normalized_strategy_type) or _STRATEGY_POLICY_REGISTRY[DEFAULT_STRATEGY_TYPE]
    return {
        "schema": STRATEGY_POLICY_SCHEMA_VERSION,
        "strategy_type": normalized_strategy_type,
        "label": str(source.get("label") or normalized_strategy_type).strip() or normalized_strategy_type,
        "cut_policy": _copy_dict(source.get("cut_policy")),
        "review_policy": _copy_dict(source.get("review_policy")),
        "render_validation_policy": _copy_dict(source.get("render_validation_policy")),
        "capability_defaults": _copy_dict(source.get("capability_defaults")),
    }


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: Any, *, limit: int = 24) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        items = [str(item or "").strip().lower() for item in value]
    else:
        text = str(value or "").strip().lower()
        items = [text] if text else []
    deduped: list[str] = []
    for item in items:
        if item and item not in deduped:
            deduped.append(item)
    return deduped[:limit]


def _confidence(value: Any, *, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return round(max(0.0, min(parsed, 1.0)), 3)


def _classification_source(profile: dict[str, Any] | None) -> dict[str, Any]:
    payload = _as_dict(profile)
    direct = _as_dict(payload.get("classification") or payload.get("strategy_classification"))
    if direct:
        return direct
    source_context = _as_dict(payload.get("source_context"))
    return _as_dict(source_context.get("classification") or source_context.get("strategy_classification"))


def strategy_classification_source(profile: dict[str, Any] | None) -> dict[str, Any]:
    return _classification_source(profile)


def normalize_strategy_classification_payload(
    payload: dict[str, Any] | None,
    *,
    content_profile: dict[str, Any] | None = None,
    local_asset_inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = _as_dict(payload)
    profile = _as_dict(content_profile)
    content_understanding = _as_dict(profile.get("content_understanding"))
    video_understanding = _as_dict(profile.get("video_understanding"))
    global_understanding = _as_dict(video_understanding.get("global_understanding"))
    style_profile = _as_dict(global_understanding.get("style_profile"))
    automation_hints = _as_dict(video_understanding.get("automation_hints"))
    editing_bias = _as_dict(automation_hints.get("editing_bias"))
    source_context = _as_dict(profile.get("source_context"))
    inventory = _as_dict(local_asset_inventory)
    requested_product_controls = normalize_requested_product_controls(
        extract_product_controls_from_profile(profile)
    )

    content_kind = str(
        profile.get("content_kind")
        or content_understanding.get("video_type")
        or global_understanding.get("video_type")
        or ""
    ).strip().lower()
    product_edit_mode = str(requested_product_controls.get("edit_mode") or "").strip().lower()
    production_mode = str(
        source.get("production_mode")
        or source_context.get("production_mode")
        or source_context.get("workflow_mode")
        or source_context.get("edit_mode")
        or (product_edit_mode if product_edit_mode != EDIT_MODE_AUTO else "")
        or ""
    ).strip().lower()
    primary_type = str(source.get("primary_type") or content_kind or "unknown").strip().lower()

    content_tags = _string_list(source.get("content_tags"))
    media_tags = _string_list(source.get("media_tags"))
    editing_signals = _string_list(source.get("editing_signals"))
    asset_tags = _string_list(source.get("asset_tags"))

    for tag in (content_kind, primary_type):
        if tag and tag != "unknown" and tag not in content_tags:
            content_tags.append(tag)
    if production_mode:
        media_tags.append(production_mode)
    if product_edit_mode and product_edit_mode != EDIT_MODE_AUTO:
        edit_mode_tags = {
            "talking_head": ["talking_head", "speech_dominant"],
            "tutorial": ["tutorial", "step_by_step"],
            "vlog": ["vlog", "experience"],
            "highlight": ["highlight", "event_highlight"],
            "multi_material": ["multi_material", "material_insert_required"],
        }.get(product_edit_mode, [product_edit_mode])
        for tag in edit_mode_tags:
            if tag in {"speech_dominant", "step_by_step", "event_highlight", "material_insert_required"}:
                editing_signals.append(tag)
            elif tag in {"experience"}:
                media_tags.append(tag)
            else:
                content_tags.append(tag)
    if str(style_profile.get("pace") or "").strip().lower() == "fast":
        editing_signals.append("high_energy")
    if str(style_profile.get("information_density") or "").strip().lower() == "high":
        editing_signals.append("subtitle_important")
    for role in _string_list(editing_bias.get("protect_roles"), limit=12):
        if role in {"demo", "comparison", "detail_showcase"}:
            editing_signals.append("visual_keep_priority")
    if inventory.get("multi_material_ready"):
        asset_tags.append("multi_material_ready")
    if inventory.get("has_visual_inserts"):
        asset_tags.append("visual_inserts_available")
    if inventory.get("has_audio_support"):
        asset_tags.append("audio_support_available")

    confidence = _confidence(source.get("confidence"), default=0.0)
    if confidence <= 0.0:
        review_confidence = _as_dict(_as_dict(video_understanding.get("review")).get("confidence"))
        confidence = _confidence(review_confidence.get("overall"), default=0.0)
    if confidence <= 0.0 and (content_tags or media_tags or editing_signals or asset_tags):
        confidence = 0.62

    return {
        "schema": str(source.get("schema") or STRATEGY_CLASSIFICATION_SCHEMA_VERSION).strip()
        or STRATEGY_CLASSIFICATION_SCHEMA_VERSION,
        "primary_type": primary_type,
        "production_mode": production_mode or "source_cut",
        "content_tags": _string_list(content_tags),
        "media_tags": _string_list(media_tags),
        "editing_signals": _string_list(editing_signals),
        "asset_tags": _string_list(asset_tags),
        "confidence": confidence,
    }


def strategy_classification_tags(classification: dict[str, Any] | None) -> set[str]:
    payload = _as_dict(classification)
    tags = {
        str(payload.get("primary_type") or "").strip().lower(),
        str(payload.get("production_mode") or "").strip().lower(),
    }
    for key in ("content_tags", "media_tags", "editing_signals", "asset_tags"):
        tags.update(_string_list(payload.get(key)))
    tags.discard("")
    tags.discard("unknown")
    return tags


def infer_strategy_type_from_classification(classification: dict[str, Any] | None) -> StrategyType | None:
    tags = strategy_classification_tags(classification)
    if not tags:
        return None
    if tags & _NARRATIVE_ASSEMBLY_TAGS:
        return "narrative_assembly"
    if tags & _STEP_DEMONSTRATION_TAGS:
        return "step_demonstration"
    if tags & _EVENT_HIGHLIGHT_TAGS or ("high_energy" in tags and tags & _EVENT_HIGHLIGHT_CONTEXT_TAGS):
        return "event_highlight"
    if tags & _EXPERIENCE_TAGS:
        return "experience_and_mood"
    if tags & _INFORMATION_DENSITY_TAGS:
        return "information_density"
    return None


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

    explicit_classification = _classification_source(content_profile)
    classification = normalize_strategy_classification_payload(
        explicit_classification,
        content_profile=content_profile,
        local_asset_inventory=local_asset_inventory,
    )
    classification_strategy = infer_strategy_type_from_classification(classification)
    if explicit_classification and classification_strategy is not None:
        return classification_strategy

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
    if classification_strategy is not None:
        return classification_strategy
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


def build_strategy_pipeline_plan(
    *,
    strategy_type: Any,
    classification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_strategy_type = normalize_strategy_type(strategy_type)
    normalized_classification = normalize_strategy_classification_payload(classification)
    strategy_policy = resolve_strategy_policy(normalized_strategy_type)
    review_policy = dict(strategy_policy.get("review_policy") or {})
    capability_defaults = dict(strategy_policy.get("capability_defaults") or {})
    tags = strategy_classification_tags(normalized_classification)
    gates: list[str] = []
    features: list[str] = list(capability_defaults)
    reason_codes: list[str] = []

    if str(review_policy.get("strategy_confirmation") or "").strip() == "required":
        gates.append("strategy_confirmation_required")
    if str(review_policy.get("storyboard_review") or "").strip() == "required":
        gates.append("storyboard_review_required")
    if str(review_policy.get("timeline_preview") or "").strip() == "required":
        gates.append("timeline_preview_required")
    elif str(review_policy.get("timeline_preview") or "").strip() == "optional":
        gates.append("timeline_preview_optional")
    if str(review_policy.get("manual_cut_review") or "").strip() == "recommended":
        gates.append("manual_cut_review_recommended")
    elif str(review_policy.get("manual_cut_review") or "").strip() == "optional":
        gates.append("manual_cut_review_optional")

    if normalized_strategy_type == "information_density":
        features.append("subtitle_timeline_projection")
        features.append("source_media_review")
        features.append("post_render_self_review")
        if tags & {"retake_likely", "silence_trim_useful", "talking_head", "single_speaker"}:
            features.append("retake_and_silence_review")
            reason_codes.append("speech_cleanup_signals")
    elif normalized_strategy_type == "step_demonstration":
        features.extend(["source_media_review", "operation_focus_preview", "post_render_self_review"])
        reason_codes.append("step_demonstration_tags")
    elif normalized_strategy_type == "experience_and_mood":
        features.extend(["reference_pacing_analysis", "soundtrack_audio_mix", "post_render_self_review"])
        reason_codes.append("experience_mood_tags")
    elif normalized_strategy_type == "event_highlight":
        features.extend(["reference_pacing_analysis", "source_media_review", "soundtrack_audio_mix"])
        gates.append("highlight_review_recommended")
        reason_codes.append("event_highlight_tags")
    elif normalized_strategy_type == "narrative_assembly":
        features.extend([
            "budget_cost_estimate",
            "generative_scene_plan",
            "material_insert_plan",
            "reference_pacing_analysis",
            "stock_footage_retrieval",
            "storyboard_review",
            "soundtrack_audio_mix",
            "timeline_preview",
        ])
        reason_codes.append("assembly_or_remix_tags")

    if "subtitle_important" in tags and "subtitle_timeline_projection" not in features:
        features.append("subtitle_timeline_projection")
    if "digital_human" in tags or "avatar_commentary" in tags:
        features.extend(["tts_generation", "avatar_render"])
        if "strategy_confirmation_required" not in gates:
            gates.append("strategy_confirmation_required")
        reason_codes.append("avatar_commentary_tags")
    if "material_insert_required" in tags and "material_insert_plan" not in features:
        features.append("material_insert_plan")
    if "storyboard_required" in tags and "storyboard_review_required" not in gates:
        gates.append("storyboard_review_required")

    confidence = _confidence(normalized_classification.get("confidence"), default=0.0)
    requires_confirmation = confidence > 0.0 and confidence < 0.65
    if requires_confirmation and "strategy_confirmation_required" not in gates:
        gates.append("strategy_confirmation_required")
        reason_codes.append("low_classification_confidence")

    return {
        "schema": STRATEGY_PIPELINE_PLAN_SCHEMA_VERSION,
        "strategy_type": normalized_strategy_type,
        "production_mode": normalized_classification.get("production_mode") or "source_cut",
        "primary_type": normalized_classification.get("primary_type") or "unknown",
        "enabled_features": sorted(set(features)),
        "review_gates": sorted(set(gates)),
        "strategy_policy": strategy_policy,
        "reason_codes": sorted(set(reason_codes)),
        "classification_confidence": confidence,
        "requires_operator_confirmation": requires_confirmation,
    }
