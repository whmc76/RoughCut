from __future__ import annotations

import copy
import json
from typing import Any

from roughcut.config import get_settings
from roughcut.edit.product_controls import MATERIAL_USAGE_ALL_UPLOADED, resolve_product_controls_for_profile
from roughcut.edit.strategy_review_context import strategy_review_timeline_preview_windows
from roughcut.edit.subtitle_surfaces import subtitle_display_rule_text
from roughcut.packaging.library import rank_insert_candidates_for_section
from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message
from roughcut.usage import track_usage_operation


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


def normalize_local_insert_plan(insert_plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(insert_plan, dict) or not insert_plan:
        return None
    normalized = copy.deepcopy(insert_plan)
    candidate_assets = [
        dict(item)
        for item in list(normalized.get("candidate_assets") or [])
        if isinstance(item, dict)
    ]
    if not candidate_assets and normalized.get("asset_id") and normalized.get("path"):
        candidate_assets = [
            {
                "asset_id": str(normalized.get("asset_id") or ""),
                "path": str(normalized.get("path") or ""),
                "original_name": str(normalized.get("original_name") or ""),
                "insert_archetype": str(normalized.get("insert_archetype") or ""),
                "insert_motion_profile": str(normalized.get("insert_motion_profile") or ""),
                "insert_transition_style": str(normalized.get("insert_transition_style") or ""),
                "insert_target_duration_sec": round(float(normalized.get("insert_target_duration_sec", 0.0) or 0.0), 3),
                "selection_score": round(float(normalized.get("selection_score", 0.0) or 0.0), 3),
                "selection_reasons": list(normalized.get("selection_reasons") or []),
            }
        ]
    if candidate_assets:
        normalized["candidate_assets"] = candidate_assets
    if "candidate_asset_ids" in normalized:
        normalized["candidate_asset_ids"] = [str(item) for item in list(normalized.get("candidate_asset_ids") or []) if str(item).strip()]
    if "insert_after_sec" in normalized:
        normalized["insert_after_sec"] = round(max(0.0, float(normalized.get("insert_after_sec", 0.0) or 0.0)), 3)
    if "insert_target_duration_sec" in normalized:
        normalized["insert_target_duration_sec"] = round(float(normalized.get("insert_target_duration_sec", 0.0) or 0.0), 3)
    if isinstance(normalized.get("broll_window"), dict):
        window = dict(normalized.get("broll_window") or {})
        normalized["broll_window"] = {
            "start_sec": round(max(0.0, float(window.get("start_sec", 0.0) or 0.0)), 3),
            "end_sec": round(max(0.0, float(window.get("end_sec", 0.0) or 0.0)), 3),
            "anchor_sec": round(max(0.0, float(window.get("anchor_sec", 0.0) or 0.0)), 3),
            "priority": round(float(window.get("priority", 0.0) or 0.0), 3),
        }
    return normalized


async def plan_local_insert_slot(
    *,
    job_id: str,
    insert_plan: dict[str, Any] | None,
    subtitle_items: list[dict[str, Any]],
    content_profile: dict[str, Any] | None,
    timeline_analysis: dict[str, Any] | None = None,
    allow_llm: bool = True,
) -> dict[str, Any] | None:
    if not insert_plan:
        return None
    resolved_insert = normalize_local_insert_plan(insert_plan)
    if not resolved_insert:
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

    settings = get_settings()
    if not subtitle_items:
        resolved_insert["insert_after_sec"] = 0.0
        resolved_insert["reason"] = "没有可用字幕，默认插入到开头。"
        resolved_insert["timing_summary"] = _build_timing_summary(
            [],
            review_gap=float(settings.packaging_selection_review_gap),
            min_score=float(settings.packaging_selection_min_score),
            low_confidence_reason="缺少字幕节奏信息，建议确认插入位置。",
        )
        return _apply_insert_asset_strategy(
            resolved_insert,
            content_profile=content_profile,
            resolved_editing_skill=(timeline_analysis or {}).get("editing_skill"),
        )

    hook_end_sec = float((timeline_analysis or {}).get("hook_end_sec") or 0.0)
    cta_start_sec = (timeline_analysis or {}).get("cta_start_sec")
    semantic_sections = list((timeline_analysis or {}).get("semantic_sections") or [])
    section_directives = list((timeline_analysis or {}).get("section_directives") or [])
    section_actions = list((timeline_analysis or {}).get("section_actions") or [])
    resolved_editing_skill = (timeline_analysis or {}).get("editing_skill") or {}

    candidates = [
        item
        for item in subtitle_items
        if float(item.get("end_time", 0.0) or 0.0) > max(8.0, hook_end_sec + 0.15)
        and (cta_start_sec is None or float(item.get("end_time", 0.0) or 0.0) < float(cta_start_sec) - 0.4)
    ]
    detail_starts = {
        round(float(section.get("start_sec", 0.0) or 0.0), 2)
        for section in semantic_sections
        if str(section.get("role") or "") in {"detail", "body"}
    }
    allowed_windows = [
        {
            "index": int(section.get("index", -1) or -1),
            "role": str(section.get("role") or ""),
            "start_sec": float(section.get("start_sec", 0.0) or 0.0),
            "end_sec": float(section.get("end_sec", 0.0) or 0.0),
            "priority": float(section.get("insert_priority", 0.0) or 0.0),
            "anchor_sec": float(
                section.get(
                    "anchor_sec",
                    (float(section.get("start_sec", 0.0) or 0.0) + float(section.get("end_sec", 0.0) or 0.0)) / 2.0,
                )
                or 0.0
            ),
        }
        for section in section_directives
        if isinstance(section, dict) and bool(section.get("insert_allowed"))
    ]
    action_windows = [
        {
            "index": int(action.get("index", -1) or -1),
            "role": str(action.get("role") or ""),
            "start_sec": float(action.get("start_sec", 0.0) or 0.0),
            "end_sec": float(action.get("end_sec", 0.0) or 0.0),
            "priority": float(action.get("action_priority", 0.0) or 0.0),
            "anchor_sec": float(action.get("broll_anchor_sec", action.get("start_sec", 0.0)) or 0.0),
            "packaging_intent": str(action.get("packaging_intent") or ""),
        }
        for action in section_actions
        if isinstance(action, dict) and bool(action.get("broll_allowed"))
    ]
    strategy_timeline_windows = strategy_review_timeline_preview_windows(content_profile)

    preferred_insert_windows: list[dict[str, float | int | str]] = []

    if detail_starts:
        prioritized = [
            item
            for item in candidates
            if round(float(item.get("start_time", 0.0) or 0.0), 2) in detail_starts
            or round(float(item.get("end_time", 0.0) or 0.0), 2) in detail_starts
        ]
        if prioritized:
            candidates = prioritized
    elif action_windows:
        action_windows.sort(key=lambda item: (-float(item.get("priority", 0.0) or 0.0), float(item.get("start_sec", 0.0) or 0.0)))
        top_priority = float(action_windows[0].get("priority", 0.0) or 0.0)
        preferred_windows = [
            window
            for window in action_windows
            if abs(float(window.get("priority", 0.0) or 0.0) - top_priority) < 1e-6
        ]
        prioritized = [
            item
            for item in candidates
            if any(
                float(window.get("start_sec", 0.0) or 0.0) - 1e-6
                <= float(item.get("end_time", 0.0) or 0.0)
                <= float(window.get("end_sec", 0.0) or 0.0) + 1e-6
                for window in preferred_windows
            )
        ]
        if prioritized:
            preferred_insert_windows = preferred_windows
            candidates = sorted(
                prioritized,
                key=lambda item: min(
                    abs(float(item.get("end_time", 0.0) or 0.0) - float(window.get("anchor_sec", 0.0) or 0.0))
                    for window in preferred_windows
                ),
            )
    elif strategy_timeline_windows:
        strategy_timeline_windows.sort(key=lambda item: (-float(item.get("priority", 0.0) or 0.0), float(item.get("start_sec", 0.0) or 0.0)))
        prioritized = [
            item
            for item in candidates
            if any(
                float(window.get("start_sec", 0.0) or 0.0) - 1e-6
                <= float(item.get("end_time", 0.0) or 0.0)
                <= float(window.get("end_sec", 0.0) or 0.0) + 1e-6
                for window in strategy_timeline_windows
            )
        ]
        if prioritized:
            top_priority = max(
                (
                    float(window.get("priority", 0.0) or 0.0)
                    for window in strategy_timeline_windows
                    if any(
                        float(window.get("start_sec", 0.0) or 0.0) - 1e-6
                        <= float(item.get("end_time", 0.0) or 0.0)
                        <= float(window.get("end_sec", 0.0) or 0.0) + 1e-6
                        for item in prioritized
                    )
                ),
                default=0.0,
            )
            preferred_insert_windows = [
                window
                for window in strategy_timeline_windows
                if abs(float(window.get("priority", 0.0) or 0.0) - top_priority) < 1e-6
            ]
            candidates = sorted(
                [
                    item
                    for item in prioritized
                    if any(
                        float(window.get("start_sec", 0.0) or 0.0) - 1e-6
                        <= float(item.get("end_time", 0.0) or 0.0)
                        <= float(window.get("end_sec", 0.0) or 0.0) + 1e-6
                        and abs(float(window.get("priority", 0.0) or 0.0) - top_priority) < 1e-6
                        for window in strategy_timeline_windows
                    )
                ]
                or prioritized,
                key=lambda item: min(
                    abs(float(item.get("end_time", 0.0) or 0.0) - float(window.get("anchor_sec", 0.0) or 0.0))
                    for window in preferred_insert_windows
                ),
            )
    elif allowed_windows:
        allowed_windows.sort(key=lambda item: (-float(item.get("priority", 0.0) or 0.0), float(item.get("start_sec", 0.0) or 0.0)))
        prioritized = [
            item
            for item in candidates
            if any(
                float(window.get("start_sec", 0.0) or 0.0) - 1e-6
                <= float(item.get("end_time", 0.0) or 0.0)
                <= float(window.get("end_sec", 0.0) or 0.0) + 1e-6
                for window in allowed_windows
            )
        ]
        if prioritized:
            top_priority = max(
                (
                    float(window.get("priority", 0.0) or 0.0)
                    for window in allowed_windows
                    if any(
                        float(window.get("start_sec", 0.0) or 0.0) - 1e-6
                        <= float(item.get("end_time", 0.0) or 0.0)
                        <= float(window.get("end_sec", 0.0) or 0.0) + 1e-6
                        for item in prioritized
                    )
                ),
                default=0.0,
            )
            preferred_insert_windows = [
                window
                for window in allowed_windows
                if abs(float(window.get("priority", 0.0) or 0.0) - top_priority) < 1e-6
            ]
            candidates = [
                item
                for item in prioritized
                if any(
                    float(window.get("start_sec", 0.0) or 0.0) - 1e-6
                    <= float(item.get("end_time", 0.0) or 0.0)
                    <= float(window.get("end_sec", 0.0) or 0.0) + 1e-6
                    and abs(float(window.get("priority", 0.0) or 0.0) - top_priority) < 1e-6
                    for window in allowed_windows
                )
            ] or prioritized

    if not candidates:
        first = subtitle_items[min(len(subtitle_items) - 1, max(0, len(subtitle_items) // 2))]
        resolved_insert["insert_after_sec"] = float(first.get("end_time", 0.0) or 0.0)
        resolved_insert["reason"] = "字幕太短，回退到中间位置插入。"
        resolved_insert["timing_summary"] = _build_timing_summary(
            [],
            review_gap=float(settings.packaging_selection_review_gap),
            min_score=float(settings.packaging_selection_min_score),
            low_confidence_reason="字幕太短，建议确认插入位置。",
        )
        return _apply_insert_asset_strategy(
            _apply_insert_window(resolved_insert, float(resolved_insert["insert_after_sec"] or 0.0), preferred_insert_windows, action_windows, allowed_windows),
            content_profile=content_profile,
            resolved_editing_skill=resolved_editing_skill,
        )

    transcript_excerpt = "\n".join(
        f"[{float(item.get('start_time', 0.0)):.1f}-{float(item.get('end_time', 0.0)):.1f}] {subtitle_display_rule_text(item)}"
        for item in candidates[:48]
    )
    fallback = candidates[0] if action_windows else candidates[len(candidates) // 2]
    fallback_sec = float(fallback.get("end_time", 0.0) or 0.0)
    fallback_plan = dict(resolved_insert)
    fallback_plan["insert_after_sec"] = fallback_sec
    fallback_plan["reason"] = "回退到中间自然停顿。"
    fallback_plan["selection_source"] = "deterministic_fallback"
    fallback_plan["timing_summary"] = _build_timing_summary(
        [],
        review_gap=float(settings.packaging_selection_review_gap),
        min_score=float(settings.packaging_selection_min_score),
        low_confidence_reason="插入点回退到默认停顿，建议确认。",
    )

    if not allow_llm:
        return _apply_insert_asset_strategy(
            _apply_insert_window(fallback_plan, float(fallback_plan["insert_after_sec"] or 0.0), preferred_insert_windows, action_windows, allowed_windows),
            content_profile=content_profile,
            resolved_editing_skill=resolved_editing_skill,
        )

    try:
        provider = get_reasoning_provider()
        prompt = (
            "你在给一条中文短视频安排一段植入素材的插入点。"
            "请根据字幕节奏和内容结构，找一个最自然、不打断关键论点的位置。"
            "优先选择一句话讲完之后、下一个话题开始之前；不要插在开场 8 秒内，也不要插在结尾收束段。"
            "如果视频主题是开箱评测，优先放在产品基础介绍讲完、进入细节体验之前。"
            "输出 JSON："
            '{"insert_after_sec":0.0,"reason":""}'
            f"\n视频信息：{json.dumps(content_profile or {}, ensure_ascii=False)}"
            f"\n候选字幕（已映射到剪后时间轴）：\n{transcript_excerpt}"
            f"\n如果拿不准，就返回 {fallback_sec:.1f} 附近的自然停顿。"
        )
        with track_usage_operation("render.insert_slot"):
            response = await provider.complete(
                [
                    Message(role="system", content="你是短视频植入编排助手，只输出 JSON。"),
                    Message(role="user", content=prompt),
                ],
                temperature=0.1,
                max_tokens=300,
                json_mode=True,
            )
        data = response.as_json()
        chosen = float(data.get("insert_after_sec", fallback_sec) or fallback_sec)
        max_sec = float(candidates[-1].get("end_time", fallback_sec) or fallback_sec)
        resolved_insert = _apply_insert_window(resolved_insert, chosen, preferred_insert_windows, action_windows, allowed_windows)
        resolved_insert["insert_after_sec"] = round(
            max(8.0, min(float(resolved_insert.get("insert_after_sec", fallback_sec) or fallback_sec), max_sec)),
            3,
        )
        resolved_insert["reason"] = str(data.get("reason") or "").strip() or "LLM 选择了较自然的转场点。"
        resolved_insert["selection_source"] = "llm"
        rankings = [
            {"score": 0.78, "enter_sec": resolved_insert["insert_after_sec"]},
            {"score": 0.7, "enter_sec": fallback_sec},
        ]
        resolved_insert["timing_summary"] = _build_timing_summary(
            rankings,
            review_gap=float(settings.packaging_selection_review_gap),
            min_score=float(settings.packaging_selection_min_score),
            low_confidence_reason="插入点候选分差过小或语义证据不足，建议确认。",
        )
        return _apply_insert_asset_strategy(
            resolved_insert,
            content_profile=content_profile,
            resolved_editing_skill=resolved_editing_skill,
        )
    except Exception:
        fallback_plan["reason"] = "LLM 未返回可靠结果，回退到中间自然停顿。"
        return _apply_insert_asset_strategy(
            _apply_insert_window(fallback_plan, float(fallback_plan["insert_after_sec"] or 0.0), preferred_insert_windows, action_windows, allowed_windows),
            content_profile=content_profile,
            resolved_editing_skill=resolved_editing_skill,
        )


def _windows_containing_time(windows: list[dict[str, float | int | str]], time_sec: float) -> list[dict[str, float | int | str]]:
    return [
        window
        for window in windows
        if float(window.get("start_sec", 0.0) or 0.0) - 1e-6 <= time_sec <= float(window.get("end_sec", 0.0) or 0.0) + 1e-6
    ]


def _nearest_window(windows: list[dict[str, float | int | str]], time_sec: float) -> dict[str, float | int | str] | None:
    if not windows:
        return None
    return sorted(
        windows,
        key=lambda window: (
            -float(window.get("priority", 0.0) or 0.0),
            abs(time_sec - float(window.get("anchor_sec", 0.0) or 0.0)),
            float(window.get("start_sec", 0.0) or 0.0),
        ),
    )[0]


def _apply_insert_window(
    plan: dict[str, Any],
    chosen_sec: float,
    preferred_insert_windows: list[dict[str, float | int | str]],
    action_windows: list[dict[str, float | int | str]],
    allowed_windows: list[dict[str, float | int | str]],
) -> dict[str, Any]:
    primary_windows = preferred_insert_windows or action_windows or allowed_windows
    primary_match = _nearest_window(_windows_containing_time(primary_windows, chosen_sec), chosen_sec)
    selected_window = primary_match or _nearest_window(primary_windows, chosen_sec)
    if not selected_window:
        plan["insert_after_sec"] = round(float(chosen_sec), 3)
        return plan

    window_start = float(selected_window.get("start_sec", chosen_sec) or chosen_sec)
    window_end = float(selected_window.get("end_sec", chosen_sec) or chosen_sec)
    window_anchor = float(selected_window.get("anchor_sec", chosen_sec) or chosen_sec)
    if window_end < window_start:
        window_start, window_end = window_end, window_start
    resolved_sec = float(chosen_sec)
    if resolved_sec < window_start - 1e-6 or resolved_sec > window_end + 1e-6:
        resolved_sec = window_anchor
    resolved_sec = max(window_start, min(resolved_sec, window_end))
    plan["insert_after_sec"] = round(resolved_sec, 3)
    plan["insert_section_role"] = str(selected_window.get("role") or "")
    plan["insert_packaging_intent"] = str(selected_window.get("packaging_intent") or "")
    if str(selected_window.get("source") or "").strip():
        plan["insert_window_source"] = str(selected_window.get("source") or "").strip()
    if str(selected_window.get("segment_id") or "").strip():
        plan["insert_strategy_timeline_segment_id"] = str(selected_window.get("segment_id") or "").strip()
    if int(selected_window.get("index", -1) or -1) >= 0:
        plan["insert_section_index"] = int(selected_window.get("index", -1) or -1)
    plan["broll_window"] = {
        "start_sec": round(window_start, 3),
        "end_sec": round(window_end, 3),
        "anchor_sec": round(max(window_start, min(window_anchor, window_end)), 3),
        "priority": round(float(selected_window.get("priority", 0.0) or 0.0), 3),
    }
    return plan


def _apply_insert_asset_strategy(
    plan: dict[str, Any],
    *,
    content_profile: dict[str, Any] | None,
    resolved_editing_skill: dict[str, Any] | None,
) -> dict[str, Any]:
    candidate_assets = [
        dict(item)
        for item in list(plan.get("candidate_assets") or [])
        if isinstance(item, dict)
    ]
    if not candidate_assets:
        return normalize_local_insert_plan(plan) or plan

    rankings = rank_insert_candidates_for_section(
        candidate_assets,
        section_role=str(plan.get("insert_section_role") or ""),
        packaging_intent=str(plan.get("insert_packaging_intent") or ""),
        content_profile=content_profile,
        editing_skill=resolved_editing_skill if isinstance(resolved_editing_skill, dict) else None,
    )
    if not rankings:
        return normalize_local_insert_plan(plan) or plan

    selected = dict(rankings[0]["candidate"])
    plan["asset_id"] = str(selected.get("asset_id") or plan.get("asset_id") or "")
    plan["path"] = str(selected.get("path") or plan.get("path") or "")
    plan["original_name"] = str(selected.get("original_name") or plan.get("original_name") or "")
    plan["insert_archetype"] = str(selected.get("insert_archetype") or plan.get("insert_archetype") or "generic_broll")
    plan["insert_motion_profile"] = str(selected.get("insert_motion_profile") or plan.get("insert_motion_profile") or "balanced_hold")
    plan["insert_transition_style"] = str(selected.get("insert_transition_style") or plan.get("insert_transition_style") or "straight_cut")
    plan["insert_target_duration_sec"] = round(float(selected.get("insert_target_duration_sec", 0.0) or 0.0), 3)
    plan["insert_strategy_summary"] = {
        "selected_asset_id": plan["asset_id"],
        "selected_score": round(float(rankings[0].get("score", 0.0) or 0.0), 3),
        "reasons": list(rankings[0].get("reasons") or []),
    }
    return normalize_local_insert_plan(plan) or plan
