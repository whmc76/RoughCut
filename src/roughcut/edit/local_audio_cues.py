from __future__ import annotations

import copy
from typing import Any

from roughcut.config import get_settings
from roughcut.edit.product_controls import MATERIAL_USAGE_ALL_UPLOADED, resolve_product_controls_for_profile
from roughcut.edit.subtitle_surfaces import subtitle_display_rule_text


def score_local_music_entry_candidates(
    subtitle_items: list[dict[str, Any]],
    *,
    content_profile: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    del content_profile
    scored: list[dict[str, Any]] = []
    for index, item in enumerate(subtitle_items):
        end_time = float(item.get("end_time", 0.0) or 0.0)
        if end_time < 1.5 or end_time > 18.0:
            continue
        text = subtitle_display_rule_text(item)
        next_item = subtitle_items[index + 1] if index + 1 < len(subtitle_items) else None
        next_start = float(next_item.get("start_time", end_time) or end_time) if next_item else end_time
        gap = max(0.0, next_start - end_time)

        score = 0.28
        reasons: list[str] = []
        if 3.0 <= end_time <= 8.5:
            score += 0.24
            reasons.append("位于开场钩子之后的自然进入区间")
        elif 2.0 <= end_time <= 12.0:
            score += 0.12
        if gap >= 0.35:
            score += 0.2
            reasons.append("后面有明显停顿")
        elif gap >= 0.18:
            score += 0.1
        if text.endswith(("。", "！", "？", "；", ".", "!", "?", ";")):
            score += 0.14
            reasons.append("句子在这里收束")
        if len(text) >= 10:
            score += 0.08

        scored.append(
            {
                "index": index,
                "enter_sec": round(end_time, 2),
                "score": round(min(score, 0.99), 3),
                "reasons": reasons,
            }
        )

    scored.sort(key=lambda item: (-float(item["score"]), float(item["enter_sec"])))
    return scored


def _build_timing_summary(
    rankings: list[dict[str, Any]],
    *,
    review_gap: float,
    min_score: float,
    low_confidence_reason: str,
) -> dict[str, Any]:
    if not rankings:
        return {
            "selected_score": 0.0,
            "runner_up_score": 0.0,
            "score_gap": 0.0,
            "review_recommended": True,
            "review_reason": low_confidence_reason,
        }
    primary = rankings[0]
    runner_up = rankings[1] if len(rankings) > 1 else None
    primary_score = float(primary.get("score") or 0.0)
    runner_up_score = float(runner_up.get("score") or 0.0) if runner_up else 0.0
    score_gap = round(max(0.0, primary_score - runner_up_score), 3)
    review_recommended = primary_score < min_score or (runner_up is not None and score_gap <= review_gap)
    return {
        "selected_score": round(primary_score, 3),
        "runner_up_score": round(runner_up_score, 3),
        "score_gap": score_gap,
        "review_recommended": review_recommended,
        "review_reason": low_confidence_reason if review_recommended else "",
    }


def _section_directive_for_time(
    timeline_analysis: dict[str, Any] | None,
    time_sec: float,
) -> dict[str, Any] | None:
    for directive in list((timeline_analysis or {}).get("section_directives") or []):
        if not isinstance(directive, dict):
            continue
        start_sec = float(directive.get("start_sec", 0.0) or 0.0)
        end_sec = float(directive.get("end_sec", start_sec) or start_sec)
        if start_sec - 1e-6 <= time_sec <= end_sec + 1e-6:
            return directive
    return None


def normalize_local_music_plan(music_plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(music_plan, dict) or not music_plan:
        return None
    normalized = copy.deepcopy(music_plan)
    enter_sec = max(0.0, float(normalized.get("enter_sec", 0.0) or 0.0))
    entry_reason = str(normalized.get("entry_reason") or "").strip()
    timing_summary = dict(normalized.get("timing_summary") or {})
    cue = {
        "kind": "bgm_entry",
        "time_sec": round(enter_sec, 3),
        "reason": entry_reason,
        "review_recommended": bool(timing_summary.get("review_recommended")),
    }
    existing_cues = [
        dict(item)
        for item in list(normalized.get("audio_cues") or [])
        if isinstance(item, dict)
    ]
    normalized["audio_cues"] = [cue, *[item for item in existing_cues if str(item.get("kind") or "").strip() != "bgm_entry"]]
    return normalized


async def plan_local_music_entry(
    *,
    music_plan: dict[str, Any] | None,
    subtitle_items: list[dict[str, Any]],
    content_profile: dict[str, Any] | None,
    timeline_analysis: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not music_plan:
        return None
    resolved_product_controls = resolve_product_controls_for_profile(
        content_profile,
        strategy_type=(timeline_analysis or {}).get("strategy_type"),
        content_kind=(content_profile or {}).get("content_kind"),
        job_flow_mode=(content_profile or {}).get("job_flow_mode") or "auto",
    )
    effective_controls = (
        resolved_product_controls.get("effective")
        if isinstance(resolved_product_controls.get("effective"), dict)
        else {}
    )
    if str(effective_controls.get("material_usage") or "").strip() != MATERIAL_USAGE_ALL_UPLOADED:
        return None
    resolved = copy.deepcopy(music_plan)
    if not subtitle_items:
        resolved["enter_sec"] = 0.0
        resolved["entry_reason"] = "没有可用字幕，背景音乐从开头进入。"
        resolved["timing_summary"] = {
            "selected_score": 0.0,
            "runner_up_score": 0.0,
            "score_gap": 0.0,
            "review_recommended": True,
            "review_reason": "缺少字幕节奏信息，建议确认 BGM 进入点。",
        }
        return normalize_local_music_plan(resolved)

    settings = get_settings()
    hook_end_sec = float((timeline_analysis or {}).get("hook_end_sec") or 0.0)
    cta_start_sec = (timeline_analysis or {}).get("cta_start_sec")
    rankings = [
        dict(item)
        for item in score_local_music_entry_candidates(subtitle_items, content_profile=content_profile)
        if float(item.get("enter_sec", 0.0) or 0.0) >= max(0.0, hook_end_sec - 0.05)
        and (
            cta_start_sec is None
            or float(item.get("enter_sec", 0.0) or 0.0) <= max(float(hook_end_sec), float(cta_start_sec) - 0.35)
        )
    ]
    allowed_rankings: list[dict[str, Any]] = []
    for item in rankings:
        directive = _section_directive_for_time(timeline_analysis, float(item.get("enter_sec", 0.0) or 0.0))
        if directive is None:
            allowed_rankings.append(item)
            continue
        if not bool(directive.get("music_entry_allowed", True)):
            continue
        item["score"] = round(
            min(0.99, float(item.get("score", 0.0) or 0.0) + float(directive.get("music_entry_bonus", 0.08) or 0.08)),
            3,
        )
        reasons = list(item.get("reasons") or [])
        reasons.append(f"落在 {str(directive.get('role') or '主体')} 段的安全音乐区间")
        item["reasons"] = reasons
        allowed_rankings.append(item)
    if allowed_rankings:
        allowed_rankings.sort(key=lambda item: (-float(item["score"]), float(item["enter_sec"])))
        rankings = allowed_rankings
    if not rankings:
        resolved["enter_sec"] = 0.0
        resolved["entry_reason"] = "缺少可靠停顿点，背景音乐从开头低音量进入。"
        resolved["timing_summary"] = _build_timing_summary(
            [],
            review_gap=float(settings.packaging_selection_review_gap),
            min_score=float(settings.packaging_selection_min_score),
            low_confidence_reason="缺少可靠停顿点，已回退为从开头进入，建议确认 BGM 进入点。",
        )
        return normalize_local_music_plan(resolved)

    chosen = rankings[0]
    resolved["enter_sec"] = float(chosen["enter_sec"])
    resolved["entry_reason"] = "；".join(chosen.get("reasons") or []) or "选择了最自然的语义停顿点进入背景音乐。"
    resolved["timing_summary"] = _build_timing_summary(
        rankings,
        review_gap=float(settings.packaging_selection_review_gap),
        min_score=float(settings.packaging_selection_min_score),
        low_confidence_reason="BGM 候选进入点分差过小或信号不足，建议确认。",
    )
    return normalize_local_music_plan(resolved)
