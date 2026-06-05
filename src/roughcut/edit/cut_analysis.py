from __future__ import annotations

from typing import Any

from roughcut.edit.smart_cut_candidates import (
    SMART_CUT_RULE_CANDIDATE_STAGE,
    build_smart_cut_rule_candidates,
)


ARTIFACT_TYPE_CUT_ANALYSIS = "cut_analysis"
CUT_ANALYSIS_SCHEMA_VERSION = "cut_analysis.v1"
_SMART_CUT_RULE_REASONS = {
    "filler_word",
    "catchphrase_phrase",
    "repeated_speech",
    "silence",
}


def _dict_items(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)]


def cut_analysis_accepted_cuts(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    return _dict_items(payload.get("accepted_cuts"))


def cut_analysis_rule_candidates(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("rule_candidates"), list):
        return _dict_items(payload.get("rule_candidates"))
    return _dict_items(payload.get("manual_editor_rule_candidates"))


def cut_analysis_silence_segments(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    return _dict_items(payload.get("silence_segments"))


def build_cut_analysis_payload(
    *,
    editorial_analysis: dict[str, Any] | None,
    source_name: str = "",
    job_flow_mode: str = "auto",
    source_subtitles: list[dict[str, Any]] | None = None,
    smart_cut_rules: dict[str, Any] | None = None,
    content_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    analysis = editorial_analysis if isinstance(editorial_analysis, dict) else {}
    accepted_cuts = _dict_items(analysis.get("accepted_cuts"))
    rule_candidates = _dict_items(
        analysis.get("rule_candidates")
        if str(analysis.get("schema") or "").strip() == CUT_ANALYSIS_SCHEMA_VERSION
        else analysis.get("manual_editor_rule_candidates")
    )
    rule_candidates = [
        item
        for item in rule_candidates
        if (
            str(item.get("candidate_stage") or "").strip() != SMART_CUT_RULE_CANDIDATE_STAGE
            and not (
                str(item.get("candidate_stage") or "").strip() == "manual_editor_full_transcript"
                and str(item.get("reason") or "").strip() in _SMART_CUT_RULE_REASONS
            )
        )
    ]
    silence_segments = _dict_items(analysis.get("silence_segments"))
    smart_cut_rule_candidates = build_smart_cut_rule_candidates(
        source_subtitles,
        smart_cut_rules,
        silence_segments=silence_segments,
        content_profile=content_profile,
    )
    if smart_cut_rule_candidates:
        existing_keys = {
            (
                round(float(item.get("start", 0.0) or 0.0), 3),
                round(float(item.get("end", 0.0) or 0.0), 3),
                str(item.get("reason") or "").strip(),
                str(item.get("source_text") or "").strip(),
                str(item.get("filler_mode") or "").strip(),
            )
            for item in rule_candidates
        }
        for candidate in smart_cut_rule_candidates:
            key = (
                round(float(candidate.get("start", 0.0) or 0.0), 3),
                round(float(candidate.get("end", 0.0) or 0.0), 3),
                str(candidate.get("reason") or "").strip(),
                str(candidate.get("source_text") or "").strip(),
                str(candidate.get("filler_mode") or "").strip(),
            )
            if key in existing_keys:
                continue
            existing_keys.add(key)
            rule_candidates.append(dict(candidate))
    candidate_sources = sorted(
        {
            str(item.get("candidate_stage") or "accepted_cut").strip() or "accepted_cut"
            for item in [*accepted_cuts, *rule_candidates]
        }
    )
    auto_apply_count = sum(1 for item in [*accepted_cuts, *rule_candidates] if bool(item.get("auto_applied")))
    manual_confirm_count = max(0, len(accepted_cuts) + len(rule_candidates) - auto_apply_count)
    return {
        "schema": CUT_ANALYSIS_SCHEMA_VERSION,
        "source_name": str(source_name or ""),
        "job_flow_mode": str(job_flow_mode or "auto"),
        "accepted_cuts": accepted_cuts,
        "rule_candidates": rule_candidates,
        "silence_segments": silence_segments,
        "candidate_count": len(accepted_cuts) + len(rule_candidates),
        "accepted_cut_count": len(accepted_cuts),
        "rule_candidate_count": len(rule_candidates),
        "auto_apply_candidate_count": auto_apply_count,
        "manual_confirm_candidate_count": manual_confirm_count,
        "candidate_sources": candidate_sources,
        "source_timeline_contract": dict(analysis.get("source_timeline_contract") or {}),
        "automatic_gate": dict(analysis.get("automatic_gate") or {}),
        "review_focus": str(analysis.get("review_focus") or ""),
    }


def cut_analysis_candidate_items(payload: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return cut_analysis_accepted_cuts(payload), cut_analysis_rule_candidates(payload)
