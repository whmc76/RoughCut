from __future__ import annotations

from typing import Any

from roughcut.edit.rule_registry import (
    normalize_rule_risk_level,
    rule_auto_applies_in_auto_mode,
    rule_multimodal_review_trigger,
)
from roughcut.edit.strategy_profile import (
    DEFAULT_STRATEGY_TYPE,
    normalize_strategy_profile_payload,
    normalize_strategy_type,
)


STRATEGY_CANDIDATE_DECISION_SCHEMA_VERSION = "strategy_candidate_decision.v1"


def resolve_candidate_strategy_decision(
    item: dict[str, Any] | None,
    *,
    job_flow_mode: Any,
    strategy_profile: dict[str, Any] | None = None,
    accepted_cut: bool = False,
) -> dict[str, Any]:
    payload = dict(item or {}) if isinstance(item, dict) else {}
    normalized_strategy_profile = normalize_strategy_profile_payload(
        strategy_profile,
        default_strategy_type=payload.get("strategy_type") or DEFAULT_STRATEGY_TYPE,
    )
    strategy_type = normalize_strategy_type(
        normalized_strategy_profile.get("strategy_type")
        or payload.get("strategy_type")
        or DEFAULT_STRATEGY_TYPE
    )
    normalized_job_flow_mode = str(job_flow_mode or "").strip() or "auto"
    reason = str(payload.get("reason") or "").strip()
    risk_level = normalize_rule_risk_level(payload.get("risk_level"), reason=reason)
    explicit_auto_applied = "auto_applied" in payload
    explicit_auto_applied_value = bool(payload.get("auto_applied"))
    review_trigger = None
    if isinstance(payload.get("multimodal_review"), dict):
        review_trigger = "multimodal_review_present"
    elif reason:
        review_trigger = rule_multimodal_review_trigger(
            reason,
            explicit_review_required=bool(payload.get("multimodal_review_required")),
        )
    decision = "manual_confirm"
    if explicit_auto_applied_value:
        decision = "auto_apply"
    elif accepted_cut and explicit_auto_applied:
        decision = "manual_confirm"
    elif normalized_job_flow_mode != "auto":
        decision = "manual_confirm"
    elif not reason:
        decision = "ignore"
    elif review_trigger is not None:
        decision = "manual_confirm"
    elif rule_auto_applies_in_auto_mode(reason, risk_level=risk_level):
        decision = "auto_apply"
    return {
        "schema": STRATEGY_CANDIDATE_DECISION_SCHEMA_VERSION,
        "decision": decision,
        "auto_applied": decision == "auto_apply",
        "strategy_type": strategy_type,
        "accepted_cut": bool(accepted_cut),
        "job_flow_mode": normalized_job_flow_mode,
        "risk_level": risk_level,
        "review_trigger": review_trigger,
        "explicit_auto_applied": explicit_auto_applied,
        "auto_apply_policy": str(normalized_strategy_profile.get("auto_apply_policy") or "").strip()
        or "current_conservative_default",
    }


def strategy_decision_auto_applied(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("auto_applied")) or str(payload.get("decision") or "").strip() == "auto_apply"
