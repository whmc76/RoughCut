from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from roughcut.edit.strategy_profile import DEFAULT_STRATEGY_TYPE

_RULE_RISK_LEVELS = ("low", "medium", "high")


@dataclass(frozen=True)
class RuleDefinition:
    reason: str
    kind: str
    risk_level: str
    match_surface_layer: str
    label: str
    auto_apply_in_auto_mode: bool = False
    frontend_managed_auto_cut: bool = False
    speech_explicit_cut: bool = False
    speech_review_cut: bool = False
    pause_cut: bool = False
    multimodal_review_cut: bool = False
    llm_review_cut: bool = False


_RULE_DEFINITIONS: dict[str, RuleDefinition] = {
    "filler_word": RuleDefinition(
        reason="filler_word",
        kind="filler",
        risk_level="low",
        match_surface_layer="raw",
        label="规则候选：口头填充音",
        auto_apply_in_auto_mode=True,
        frontend_managed_auto_cut=True,
        speech_explicit_cut=True,
    ),
    "catchphrase_phrase": RuleDefinition(
        reason="catchphrase_phrase",
        kind="catchphrase",
        risk_level="low",
        match_surface_layer="raw",
        label="规则候选：口头禅",
        auto_apply_in_auto_mode=True,
        frontend_managed_auto_cut=True,
    ),
    "repeated_speech": RuleDefinition(
        reason="repeated_speech",
        kind="repeated",
        risk_level="medium",
        match_surface_layer="raw",
        label="规则候选：重复口误",
        frontend_managed_auto_cut=True,
        speech_explicit_cut=True,
    ),
    "silence": RuleDefinition(
        reason="silence",
        kind="pause",
        risk_level="low",
        match_surface_layer="raw",
        label="规则候选：停顿",
        auto_apply_in_auto_mode=True,
        frontend_managed_auto_cut=True,
        speech_review_cut=True,
        pause_cut=True,
    ),
    "pause": RuleDefinition(
        reason="pause",
        kind="pause",
        risk_level="low",
        match_surface_layer="raw",
        label="规则候选：停顿",
        auto_apply_in_auto_mode=True,
        pause_cut=True,
    ),
    "rollback_instruction": RuleDefinition(
        reason="rollback_instruction",
        kind="smart_delete",
        risk_level="high",
        match_surface_layer="raw",
        label="口播指令回删前段",
        frontend_managed_auto_cut=True,
        speech_explicit_cut=True,
        pause_cut=True,
        llm_review_cut=True,
    ),
    "restart_retake": RuleDefinition(
        reason="restart_retake",
        kind="smart_delete",
        risk_level="high",
        match_surface_layer="raw",
        label="疑似重录废片",
        frontend_managed_auto_cut=True,
        speech_explicit_cut=True,
        llm_review_cut=True,
    ),
    "restart_cue": RuleDefinition(
        reason="restart_cue",
        kind="smart_delete",
        risk_level="high",
        match_surface_layer="raw",
        label="明确重来/口误提示",
        frontend_managed_auto_cut=True,
        speech_explicit_cut=True,
        llm_review_cut=True,
    ),
    "noise_subtitle": RuleDefinition(
        reason="noise_subtitle",
        kind="smart_delete",
        risk_level="medium",
        match_surface_layer="raw",
        label="规则候选：ASR 噪音标记",
        frontend_managed_auto_cut=True,
        speech_explicit_cut=True,
    ),
    "low_signal_subtitle": RuleDefinition(
        reason="low_signal_subtitle",
        kind="smart_delete",
        risk_level="medium",
        match_surface_layer="canonical",
        label="低信息字幕废片",
        frontend_managed_auto_cut=True,
        speech_review_cut=True,
        multimodal_review_cut=True,
        llm_review_cut=True,
    ),
    "long_non_dialogue": RuleDefinition(
        reason="long_non_dialogue",
        kind="smart_delete",
        risk_level="medium",
        match_surface_layer="raw",
        label="长段非口播废片",
        frontend_managed_auto_cut=True,
        speech_review_cut=True,
        pause_cut=True,
        multimodal_review_cut=True,
        llm_review_cut=True,
    ),
    "timing_trim": RuleDefinition(
        reason="timing_trim",
        kind="smart_delete",
        risk_level="medium",
        match_surface_layer="raw",
        label="规则候选：节奏边界修剪",
        frontend_managed_auto_cut=True,
        speech_review_cut=True,
        pause_cut=True,
        multimodal_review_cut=True,
    ),
    "micro_keep": RuleDefinition(
        reason="micro_keep",
        kind="smart_delete",
        risk_level="low",
        match_surface_layer="raw",
        label="规则候选：短空段清理",
        auto_apply_in_auto_mode=True,
        frontend_managed_auto_cut=True,
        speech_review_cut=True,
        pause_cut=True,
    ),
    "micro_keep_bridge": RuleDefinition(
        reason="micro_keep_bridge",
        kind="smart_delete",
        risk_level="low",
        match_surface_layer="raw",
        label="规则候选：碎片桥段清理",
        auto_apply_in_auto_mode=True,
        frontend_managed_auto_cut=True,
        speech_review_cut=True,
    ),
    "gap_fill": RuleDefinition(
        reason="gap_fill",
        kind="smart_delete",
        risk_level="low",
        match_surface_layer="raw",
        label="规则候选：时间线空隙清理",
        auto_apply_in_auto_mode=True,
        frontend_managed_auto_cut=True,
        speech_review_cut=True,
    ),
}

def _reason_set_from_metadata(
    metadata_field: str,
    *,
    extra_reasons: tuple[str, ...] = (),
) -> frozenset[str]:
    return frozenset(
        {
            *extra_reasons,
            *(
                definition.reason
                for definition in _RULE_DEFINITIONS.values()
                if bool(getattr(definition, metadata_field, False))
            ),
        }
    )


def get_rule_definition(reason: str) -> RuleDefinition | None:
    return _RULE_DEFINITIONS.get(str(reason or "").strip())


def rule_kind(reason: str) -> str | None:
    definition = get_rule_definition(reason)
    return definition.kind if definition else None


def rule_default_risk_level(reason: str) -> str | None:
    definition = get_rule_definition(reason)
    return definition.risk_level if definition else None


def normalize_rule_risk_level(value: Any, *, reason: str | None = None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in _RULE_RISK_LEVELS:
        return normalized
    fallback = rule_default_risk_level(str(reason or "").strip()) if reason else None
    if fallback in _RULE_RISK_LEVELS:
        return str(fallback)
    return "medium"


def rule_match_surface_layer(reason: str) -> str | None:
    definition = get_rule_definition(reason)
    return definition.match_surface_layer if definition else None


def rule_label(reason: str) -> str | None:
    definition = get_rule_definition(reason)
    return definition.label if definition else None


def rule_candidate_producer_id(reason: str, *, candidate_stage: Any = None) -> str:
    normalized_reason = str(reason or "").strip()
    definition = get_rule_definition(normalized_reason)
    if definition is not None:
        kind = definition.kind
        if kind == "filler":
            return "speech_filler_candidate_producer"
        if kind == "catchphrase":
            return "speech_catchphrase_candidate_producer"
        if kind == "repeated":
            return "repeated_speech_candidate_producer"
        if kind == "pause":
            return "pause_trim_candidate_producer"
        if kind == "smart_delete":
            return "semantic_trim_candidate_producer"
    normalized_stage = str(candidate_stage or "").strip()
    if normalized_stage == "manual_editor_smart_cut_rules":
        return "smart_cut_rule_candidate_producer"
    if normalized_stage == "manual_editor_full_transcript":
        return "full_transcript_candidate_producer"
    if normalized_stage == "accepted_cut":
        return "accepted_cut_candidate_producer"
    return "generic_candidate_producer"


def rule_strategy_applicability(reason: str, *, candidate_stage: Any = None) -> list[str]:
    _ = reason
    _ = candidate_stage
    return [DEFAULT_STRATEGY_TYPE]


def rule_requires_llm_review(reason: str, *, risk_level: Any = None) -> bool:
    definition = get_rule_definition(reason)
    if definition and definition.llm_review_cut:
        return True
    return normalize_rule_risk_level(risk_level, reason=reason) == "high"


def rule_requires_multimodal_review(reason: str) -> bool:
    definition = get_rule_definition(reason)
    return bool(definition.multimodal_review_cut) if definition else False


def rule_multimodal_review_trigger(
    reason: str,
    *,
    explicit_review_required: bool = False,
) -> str | None:
    if explicit_review_required:
        return "visual_protection"
    if rule_requires_multimodal_review(reason):
        return "semantic_uncertainty"
    return None


def rule_auto_applies_in_auto_mode(reason: str, *, risk_level: Any = None) -> bool:
    definition = get_rule_definition(reason)
    if definition is None:
        return normalize_rule_risk_level(risk_level, reason=reason) == "low"
    if not definition.auto_apply_in_auto_mode:
        return False
    return normalize_rule_risk_level(risk_level, reason=reason) == "low"


def empty_rule_risk_level_counts() -> dict[str, int]:
    return {level: 0 for level in _RULE_RISK_LEVELS}


def summarize_rule_risk_levels(items: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> dict[str, int]:
    counts = empty_rule_risk_level_counts()
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        reason = str(item.get("reason") or "").strip()
        risk_level = normalize_rule_risk_level(item.get("risk_level"), reason=reason)
        counts[risk_level] = counts.get(risk_level, 0) + 1
    return counts


def manual_editor_frontend_managed_auto_cut_reasons() -> frozenset[str]:
    return _reason_set_from_metadata("frontend_managed_auto_cut")


def manual_editor_synthetic_timeline_reasons() -> frozenset[str]:
    return frozenset({"manual_editor_keep", "manual_editor_removed"})


def speech_explicit_cut_reasons() -> frozenset[str]:
    return _reason_set_from_metadata("speech_explicit_cut", extra_reasons=("manual_cut",))


def speech_review_cut_reasons() -> frozenset[str]:
    return _reason_set_from_metadata("speech_review_cut")


def pause_cut_reasons() -> frozenset[str]:
    return _reason_set_from_metadata("pause_cut", extra_reasons=("manual_cut",))


def build_rule_candidate_id(
    *,
    reason: str,
    start: Any,
    end: Any,
    match_surface: Any = "",
) -> str:
    try:
        normalized_start = round(float(start or 0.0), 3)
    except (TypeError, ValueError):
        normalized_start = 0.0
    try:
        normalized_end = round(float(end or normalized_start), 3)
    except (TypeError, ValueError):
        normalized_end = normalized_start
    normalized_surface = str(match_surface or "").strip().replace(":", "：")
    return f"{str(reason or '').strip()}:{normalized_start:.3f}:{normalized_end:.3f}:{normalized_surface}"
