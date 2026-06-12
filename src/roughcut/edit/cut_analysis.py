from __future__ import annotations

from typing import Any

from roughcut.edit.rule_registry import (
    build_rule_candidate_id,
    rule_candidate_producer_id,
    rule_default_risk_level,
    rule_match_surface_layer,
    rule_strategy_applicability,
    summarize_rule_risk_levels,
)
from roughcut.edit.strategy_decisions import (
    resolve_candidate_strategy_decision,
    strategy_decision_auto_applied,
)
from roughcut.edit.strategy_profile import (
    DEFAULT_STRATEGY_TYPE,
    normalize_strategy_profile_payload,
    normalize_strategy_type,
    payload_strategy_profile,
)
from roughcut.edit.smart_cut_candidates import (
    SMART_CUT_RULE_CANDIDATE_STAGE,
    build_smart_cut_rule_candidates,
)
from roughcut.edit.smart_cut_rules import normalize_smart_cut_rules_payload


ARTIFACT_TYPE_CUT_ANALYSIS = "cut_analysis"
CUT_ANALYSIS_SCHEMA_VERSION = "cut_analysis.v1"


def _safe_float_time(value: Any, default: float = 0.0) -> float:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return default


def _candidate_time_key(item: dict[str, Any]) -> tuple[float, float, str, str, str]:
    return (
        _safe_float_time(item.get("start")),
        _safe_float_time(item.get("end")),
        str(item.get("reason") or "").strip(),
        str(item.get("source_text") or "").strip(),
        str(item.get("filler_mode") or "").strip(),
    )


def _merge_smart_cut_candidate(existing: dict[str, Any], fresh: dict[str, Any]) -> dict[str, Any]:
    merged = dict(fresh)
    preserved_fields = (
        "rule_id",
        "risk_level",
        "match_surface",
        "match_surface_layer",
        "candidate_id",
        "id",
        "filler_mode",
        "evidence",
        "source",
        "auto_applied",
    )
    for field in preserved_fields:
        value = existing.get(field)
        if value is not None:
            merged[field] = value
    if str(existing.get("source_text") or "").strip():
        merged["source_text"] = existing.get("source_text")
    return _normalize_rule_candidate_metadata(merged)


def _candidate_text_match(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("reason") or "").strip(),
        str(item.get("source_text") or "").strip(),
        str(item.get("filler_mode") or "").strip(),
    )


def _candidate_text_match_coarse(item: dict[str, Any]) -> tuple[str, str]:
    return (
        str(item.get("reason") or "").strip(),
        str(item.get("source_text") or "").strip(),
    )


def _candidate_temporal_distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_start = _safe_float_time(left.get("start"))
    left_end = _safe_float_time(left.get("end"))
    right_start = _safe_float_time(right.get("start"))
    right_end = _safe_float_time(right.get("end"))
    return max(abs(left_start - right_start), abs(left_end - right_end))


def _pick_best_temporal_match(
    text_key: tuple[str, ...],
    fresh: dict[str, Any],
    legacy_index: dict[tuple[str, ...], list[dict[str, Any]]],
) -> dict[str, Any] | None:
    candidates = legacy_index.get(text_key)
    if not candidates:
        return None
    best_candidate: dict[str, Any] | None = None
    best_distance = float("inf")
    for index, item in enumerate(candidates):
        distance = _candidate_temporal_distance(fresh, item)
        if distance <= 0.25 and distance < best_distance:
            best_distance = distance
            best_candidate = item
            best_candidate_index = index
    if best_candidate is None:
        return None
    candidates.pop(best_candidate_index)
    if not candidates:
        legacy_index.pop(text_key, None)
    return best_candidate


def _dict_items(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)]


def _candidate_source_text(item: dict[str, Any]) -> str:
    source_text = str(item.get("source_text") or "").strip()
    if source_text:
        return source_text
    if str(item.get("reason") or "").strip() == "silence":
        return "silence"
    if str(item.get("reason") or "").strip() == "filler_word":
        filler_mode = str(item.get("filler_mode") or "").strip()
        if filler_mode:
            return filler_mode
    for signal in list(item.get("signals") or []):
        text = str(signal or "").strip()
        if ":" not in text:
            continue
        prefix, value = text.split(":", 1)
        if prefix in {"unit", "token"} and value.strip():
            return value.strip()
    return ""


def _normalize_rule_candidate_metadata(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    reason = str(normalized.get("reason") or "").strip()
    if not reason:
        return normalized
    source_text = _candidate_source_text(normalized)
    if source_text and not str(normalized.get("source_text") or "").strip():
        normalized["source_text"] = source_text
    match_surface = str(normalized.get("match_surface") or "").strip()
    if not match_surface:
        match_surface = str(normalized.get("filler_mode") or "").strip() or source_text
        if match_surface:
            normalized["match_surface"] = match_surface
    if not str(normalized.get("risk_level") or "").strip():
        risk_level = rule_default_risk_level(reason)
        if risk_level:
            normalized["risk_level"] = risk_level
    if not str(normalized.get("match_surface_layer") or "").strip():
        match_surface_layer = rule_match_surface_layer(reason)
        if match_surface_layer:
            normalized["match_surface_layer"] = match_surface_layer
    if not str(normalized.get("producer_id") or "").strip():
        normalized["producer_id"] = rule_candidate_producer_id(
            reason,
            candidate_stage=normalized.get("candidate_stage"),
        )
    strategy_applicability = normalized.get("strategy_applicability")
    if isinstance(strategy_applicability, list):
        normalized["strategy_applicability"] = [
            str(item).strip()
            for item in strategy_applicability
            if str(item).strip()
        ]
    if not isinstance(normalized.get("strategy_applicability"), list) or not normalized.get("strategy_applicability"):
        normalized["strategy_applicability"] = rule_strategy_applicability(
            reason,
            candidate_stage=normalized.get("candidate_stage"),
        )
    if not str(normalized.get("rule_id") or normalized.get("candidate_id") or normalized.get("id") or "").strip():
        normalized["rule_id"] = build_rule_candidate_id(
            reason=reason,
            start=normalized.get("start"),
            end=normalized.get("end"),
            match_surface=normalized.get("match_surface") or normalized.get("source_text"),
        )
    return normalized


def _candidate_auto_applied_by_mode(
    item: dict[str, Any],
    *,
    job_flow_mode: str,
    explicit_false_authoritative: bool,
    strategy_profile: dict[str, Any] | None = None,
) -> bool:
    return strategy_decision_auto_applied(
        resolve_candidate_strategy_decision(
            item,
            job_flow_mode=job_flow_mode,
            strategy_profile=strategy_profile,
            accepted_cut=explicit_false_authoritative,
        )
    )


def _rule_candidate_auto_applied_by_mode(
    item: dict[str, Any],
    *,
    job_flow_mode: str,
    strategy_profile: dict[str, Any] | None = None,
) -> bool:
    return _candidate_auto_applied_by_mode(
        item,
        job_flow_mode=job_flow_mode,
        explicit_false_authoritative=False,
        strategy_profile=strategy_profile,
    )


def _accepted_cut_auto_applied_by_mode(
    item: dict[str, Any],
    *,
    job_flow_mode: str,
    strategy_profile: dict[str, Any] | None = None,
) -> bool:
    return _candidate_auto_applied_by_mode(
        item,
        job_flow_mode=job_flow_mode,
        explicit_false_authoritative=True,
        strategy_profile=strategy_profile,
    )


def _payload_job_flow_mode(payload: dict[str, Any] | None, *, default: str = "auto") -> str:
    if not isinstance(payload, dict):
        return default
    return str(payload.get("job_flow_mode") or default).strip() or default


def _resolved_candidate_item(
    item: dict[str, Any],
    *,
    job_flow_mode: str,
    accepted_cut: bool,
    strategy_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = _normalize_rule_candidate_metadata(item)
    strategy_decision = resolve_candidate_strategy_decision(
        normalized,
        job_flow_mode=job_flow_mode,
        strategy_profile=strategy_profile,
        accepted_cut=accepted_cut,
    )
    normalized["strategy_decision"] = strategy_decision
    normalized["auto_applied"] = strategy_decision_auto_applied(strategy_decision)
    return normalized


def cut_analysis_accepted_cuts(
    payload: dict[str, Any] | None,
    *,
    resolved: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    accepted_cuts = _dict_items(payload.get("accepted_cuts"))
    if not resolved:
        return accepted_cuts
    job_flow_mode = _payload_job_flow_mode(payload)
    strategy_profile = payload_strategy_profile(payload)
    return [
        _resolved_candidate_item(
            item,
            job_flow_mode=job_flow_mode,
            accepted_cut=True,
            strategy_profile=strategy_profile,
        )
        for item in accepted_cuts
    ]


def cut_analysis_rule_candidates(
    payload: dict[str, Any] | None,
    *,
    resolved: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("rule_candidates"), list):
        rule_candidates = _dict_items(payload.get("rule_candidates"))
    else:
        rule_candidates = _dict_items(payload.get("manual_editor_rule_candidates"))
    if not resolved:
        return rule_candidates
    job_flow_mode = _payload_job_flow_mode(payload)
    strategy_profile = payload_strategy_profile(payload)
    return [
        _resolved_candidate_item(
            item,
            job_flow_mode=job_flow_mode,
            accepted_cut=False,
            strategy_profile=strategy_profile,
        )
        for item in rule_candidates
    ]


def cut_analysis_effective_applied_cuts(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    accepted_cuts = cut_analysis_accepted_cuts(payload, resolved=True)
    auto_rule_candidates = [
        item
        for item in cut_analysis_rule_candidates(payload, resolved=True)
        if isinstance(item, dict) and bool(item.get("auto_applied"))
    ]
    if not accepted_cuts:
        return auto_rule_candidates
    merged = [dict(item) for item in accepted_cuts]
    existing_keys = {_candidate_time_key(item) for item in accepted_cuts if isinstance(item, dict)}
    for item in auto_rule_candidates:
        key = _candidate_time_key(item)
        if key in existing_keys:
            continue
        merged.append(dict(item))
        existing_keys.add(key)
    return merged


def cut_analysis_silence_segments(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    return _dict_items(payload.get("silence_segments"))


def summarize_cut_analysis_candidate_metrics(
    accepted_cuts: list[dict[str, Any]] | None,
    rule_candidates: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    normalized_accepted_cuts = _dict_items(accepted_cuts)
    normalized_rule_candidates = _dict_items(rule_candidates)
    candidate_items = [*normalized_accepted_cuts, *normalized_rule_candidates]
    auto_apply_items = [item for item in candidate_items if bool(item.get("auto_applied"))]
    manual_confirm_items = [item for item in candidate_items if not bool(item.get("auto_applied"))]
    candidate_risk_summary = {
        "total": summarize_rule_risk_levels(candidate_items),
        "auto_apply": summarize_rule_risk_levels(auto_apply_items),
        "manual_confirm": summarize_rule_risk_levels(manual_confirm_items),
    }
    return {
        "candidate_count": len(candidate_items),
        "accepted_cut_count": len(normalized_accepted_cuts),
        "rule_candidate_count": len(normalized_rule_candidates),
        "auto_apply_candidate_count": len(auto_apply_items),
        "manual_confirm_candidate_count": len(manual_confirm_items),
        "candidate_risk_summary": candidate_risk_summary,
    }


def build_cut_analysis_payload(
    *,
    editorial_analysis: dict[str, Any] | None,
    source_name: str = "",
    job_flow_mode: str = "auto",
    source_subtitles: list[dict[str, Any]] | None = None,
    smart_cut_rules: dict[str, Any] | None = None,
    content_profile: dict[str, Any] | None = None,
    strategy_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis = editorial_analysis if isinstance(editorial_analysis, dict) else {}
    normalized_strategy_profile = normalize_strategy_profile_payload(
        strategy_profile,
        default_strategy_type=analysis.get("strategy_type") or DEFAULT_STRATEGY_TYPE,
    )
    strategy_type = normalize_strategy_type(
        normalized_strategy_profile.get("strategy_type") or analysis.get("strategy_type") or DEFAULT_STRATEGY_TYPE
    )
    accepted_cuts = []
    for item in _dict_items(analysis.get("accepted_cuts")):
        normalized_item = _resolved_candidate_item(
            item,
            job_flow_mode=job_flow_mode,
            accepted_cut=True,
            strategy_profile=normalized_strategy_profile,
        )
        accepted_cuts.append(normalized_item)
    normalized_smart_cut_rules = normalize_smart_cut_rules_payload(smart_cut_rules)
    repeated_speech_enabled = bool(normalized_smart_cut_rules.get("repeatedEnabled", True))
    analysis_rule_candidates = _dict_items(
        analysis.get("rule_candidates")
        if str(analysis.get("schema") or "").strip() == CUT_ANALYSIS_SCHEMA_VERSION
        else analysis.get("manual_editor_rule_candidates")
    )
    analysis_rule_candidates = [_normalize_rule_candidate_metadata(item) for item in analysis_rule_candidates]
    if not repeated_speech_enabled:
        analysis_rule_candidates = [
            item
            for item in analysis_rule_candidates
            if not (
                str(item.get("reason") or "").strip() == "repeated_speech"
                and str(item.get("candidate_stage") or "").strip() in {
                    "manual_editor_full_transcript",
                    SMART_CUT_RULE_CANDIDATE_STAGE,
                }
            )
        ]
    normalized_job_flow_mode = str(job_flow_mode or "auto").strip() or "auto"
    retained_rule_candidates: list[dict[str, Any]] = []
    backend_smart_cut_rule_candidates: dict[tuple[float, float, str, str, str], dict[str, Any]] = {}
    backend_smart_cut_rule_candidates_by_text: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    backend_smart_cut_rule_candidates_by_source: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in analysis_rule_candidates:
        if str(item.get("candidate_stage") or "").strip() == SMART_CUT_RULE_CANDIDATE_STAGE:
            backend_smart_cut_rule_candidates[_candidate_time_key(item)] = item
            backend_smart_cut_rule_candidates_by_text.setdefault(_candidate_text_match(item), []).append(item)
            backend_smart_cut_rule_candidates_by_source.setdefault(_candidate_text_match_coarse(item), []).append(item)
        else:
            retained_rule_candidates.append(
                _resolved_candidate_item(
                    item,
                    job_flow_mode=normalized_job_flow_mode,
                    accepted_cut=False,
                    strategy_profile=normalized_strategy_profile,
                )
            )
    silence_segments = _dict_items(analysis.get("silence_segments"))
    smart_cut_rule_candidates = build_smart_cut_rule_candidates(
        source_subtitles,
        normalized_smart_cut_rules,
        silence_segments=silence_segments,
        content_profile=content_profile,
    )
    merged_rule_candidates: list[dict[str, Any]] = []
    existing_keys = {_candidate_time_key(item): 1 for item in retained_rule_candidates}
    for candidate in smart_cut_rule_candidates:
        key = _candidate_time_key(candidate)
        if key in existing_keys:
            continue
        if key in backend_smart_cut_rule_candidates:
            merged_candidate = _merge_smart_cut_candidate(
                backend_smart_cut_rule_candidates[key],
                candidate,
            )
            merged_candidate = _resolved_candidate_item(
                merged_candidate,
                job_flow_mode=normalized_job_flow_mode,
                accepted_cut=False,
                strategy_profile=normalized_strategy_profile,
            )
            merged_rule_candidates.append(merged_candidate)
            del backend_smart_cut_rule_candidates[key]
            # keep text-index in sync with exact-match removal
            text_key = _candidate_text_match(candidate)
            text_candidates = backend_smart_cut_rule_candidates_by_text.get(text_key, [])
            if text_candidates:
                for text_index, item in enumerate(text_candidates):
                    if _candidate_time_key(item) == key:
                        text_candidates.pop(text_index)
                        break
                if not text_candidates:
                    backend_smart_cut_rule_candidates_by_text.pop(text_key, None)
            source_text_key = _candidate_text_match_coarse(candidate)
            source_text_candidates = backend_smart_cut_rule_candidates_by_source.get(source_text_key, [])
            if source_text_candidates:
                for source_text_index, item in enumerate(source_text_candidates):
                    if _candidate_time_key(item) == key:
                        source_text_candidates.pop(source_text_index)
                        break
                if not source_text_candidates:
                    backend_smart_cut_rule_candidates_by_source.pop(source_text_key, None)
        else:
            best_match = _pick_best_temporal_match(
                _candidate_text_match(candidate),
                candidate,
                backend_smart_cut_rule_candidates_by_text,
            )
            if best_match is None:
                best_match = _pick_best_temporal_match(
                    _candidate_text_match_coarse(candidate),
                    candidate,
                    backend_smart_cut_rule_candidates_by_source,
                )
            if best_match is not None and _candidate_time_key(best_match) in backend_smart_cut_rule_candidates:
                merged_candidate = _merge_smart_cut_candidate(best_match, candidate)
                merged_candidate = _resolved_candidate_item(
                    merged_candidate,
                    job_flow_mode=normalized_job_flow_mode,
                    accepted_cut=False,
                    strategy_profile=normalized_strategy_profile,
                )
                merged_rule_candidates.append(merged_candidate)
                best_match_key = _candidate_time_key(best_match)
                del backend_smart_cut_rule_candidates[best_match_key]
                source_text_key = _candidate_text_match_coarse(candidate)
                source_text_candidates = backend_smart_cut_rule_candidates_by_source.get(source_text_key, [])
                if source_text_candidates:
                    for source_text_index, item in enumerate(source_text_candidates):
                        if _candidate_time_key(item) == best_match_key:
                            source_text_candidates.pop(source_text_index)
                            break
                    if not source_text_candidates:
                        backend_smart_cut_rule_candidates_by_source.pop(source_text_key, None)
                exact_text_key = _candidate_text_match(best_match)
                exact_text_candidates = backend_smart_cut_rule_candidates_by_text.get(exact_text_key, [])
                if exact_text_candidates:
                    for exact_text_index, item in enumerate(exact_text_candidates):
                        if _candidate_time_key(item) == best_match_key:
                            exact_text_candidates.pop(exact_text_index)
                            break
                    if not exact_text_candidates:
                        backend_smart_cut_rule_candidates_by_text.pop(exact_text_key, None)
            else:
                normalized_candidate = _resolved_candidate_item(
                    candidate,
                    job_flow_mode=normalized_job_flow_mode,
                    accepted_cut=False,
                    strategy_profile=normalized_strategy_profile,
                )
                merged_rule_candidates.append(normalized_candidate)
        existing_keys[key] = 1
    rule_candidates = [*retained_rule_candidates, *merged_rule_candidates]
    candidate_sources = sorted(
        {
            str(item.get("candidate_stage") or "accepted_cut").strip() or "accepted_cut"
            for item in [*accepted_cuts, *rule_candidates]
        }
    )
    candidate_metrics = summarize_cut_analysis_candidate_metrics(accepted_cuts, rule_candidates)
    return {
        "schema": CUT_ANALYSIS_SCHEMA_VERSION,
        "source_name": str(source_name or ""),
        "job_flow_mode": str(job_flow_mode or "auto"),
        "strategy_type": strategy_type,
        "strategy_profile": normalized_strategy_profile,
        "accepted_cuts": accepted_cuts,
        "rule_candidates": rule_candidates,
        "silence_segments": silence_segments,
        **candidate_metrics,
        "candidate_sources": candidate_sources,
        "source_timeline_contract": dict(analysis.get("source_timeline_contract") or {}),
        "automatic_gate": dict(analysis.get("automatic_gate") or {}),
        "review_focus": str(analysis.get("review_focus") or ""),
    }


def cut_analysis_candidate_items(
    payload: dict[str, Any] | None,
    *,
    resolved: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return cut_analysis_accepted_cuts(payload, resolved=resolved), cut_analysis_rule_candidates(
        payload,
        resolved=resolved,
    )
