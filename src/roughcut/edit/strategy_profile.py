from __future__ import annotations

from typing import Any, Literal, cast


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
