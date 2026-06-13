from __future__ import annotations

import copy
from typing import Any

from roughcut.edit.presets import normalize_workflow_template_name


def normalize_timed_focus_spans(value: Any) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for item in list(value or []):
        if not isinstance(item, dict):
            continue
        start_time = max(0.0, float(item.get("start_time", 0.0) or 0.0))
        end_time = max(start_time, float(item.get("end_time", start_time) or start_time))
        text = str(item.get("text") or "").strip()
        span_type = str(item.get("type") or "focus").strip().lower() or "focus"
        normalized = {
            "timestamp": str(item.get("timestamp") or "").strip(),
            "text": text,
            "type": span_type,
            "start_time": round(start_time, 3),
            "end_time": round(end_time, 3),
        }
        if not normalized["text"] and not normalized["timestamp"]:
            continue
        spans.append(normalized)
    spans.sort(key=lambda item: (float(item.get("start_time", 0.0) or 0.0), float(item.get("end_time", 0.0) or 0.0)))
    return spans


def build_local_focus_plan(
    *,
    content_profile: dict[str, Any] | None,
    timeline_analysis: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    profile = content_profile if isinstance(content_profile, dict) else {}
    content_understanding = (
        dict(profile.get("content_understanding") or {})
        if isinstance(profile.get("content_understanding"), dict)
        else {}
    )
    if not _focus_plan_runtime_enabled(profile, content_understanding=content_understanding):
        return None
    timed_focus_spans = normalize_timed_focus_spans(content_understanding.get("timed_focus_spans"))
    if not timed_focus_spans:
        return None

    focus_events: list[dict[str, Any]] = []
    chapter_cards: list[dict[str, Any]] = []
    hook_end_sec = float((timeline_analysis or {}).get("hook_end_sec") or 0.0)
    for index, span in enumerate(timed_focus_spans[:6]):
        span_type = str(span.get("type") or "focus").strip().lower()
        focus_events.append(
            {
                "event_type": _focus_event_type(span_type),
                "start_time": float(span.get("start_time", 0.0) or 0.0),
                "end_time": float(span.get("end_time", span.get("start_time", 0.0)) or span.get("start_time", 0.0)),
                "text": str(span.get("text") or "").strip(),
                "anchor": str(span.get("timestamp") or "").strip(),
                "intensity": "high" if span_type in {"hook", "comparison"} else "medium",
                "source": "content_understanding_timed_focus_spans",
            }
        )
        if index >= 4:
            continue
        chapter_cards.append(
            {
                "start_time": float(span.get("start_time", 0.0) or 0.0),
                "end_time": float(span.get("end_time", span.get("start_time", 0.0)) or span.get("start_time", 0.0)),
                "title": _chapter_card_title(span),
                "card_type": "opening" if float(span.get("start_time", 0.0) or 0.0) <= max(0.0, hook_end_sec + 0.15) else "section",
                "source": "content_understanding_timed_focus_spans",
            }
        )
    return {
        "focus_events": focus_events,
        "chapter_cards": chapter_cards,
        "timed_focus_spans": [copy.deepcopy(item) for item in timed_focus_spans[:8]],
        "source": "content_understanding_timed_focus_spans",
    }


def _focus_plan_runtime_enabled(
    profile: dict[str, Any],
    *,
    content_understanding: dict[str, Any] | None = None,
) -> bool:
    resolved_understanding = content_understanding if isinstance(content_understanding, dict) else {}
    content_kind = str(profile.get("content_kind") or "").strip().lower()
    if content_kind == "tutorial":
        return True

    strategy_profile = profile.get("strategy_profile") if isinstance(profile.get("strategy_profile"), dict) else {}
    if str(strategy_profile.get("strategy_type") or "").strip().lower() == "step_demonstration":
        return True

    workflow_template = normalize_workflow_template_name(profile.get("workflow_template"))
    if workflow_template == "tutorial_standard":
        return True

    video_type = str(resolved_understanding.get("video_type") or "").strip().lower()
    if video_type == "tutorial":
        return True

    product_controls = profile.get("product_controls") if isinstance(profile.get("product_controls"), dict) else {}
    effective_controls = product_controls.get("effective") if isinstance(product_controls.get("effective"), dict) else {}
    if str(effective_controls.get("edit_mode") or product_controls.get("edit_mode") or "").strip().lower() == "tutorial":
        return True

    return False


def _focus_event_type(span_type: str) -> str:
    normalized = str(span_type or "").strip().lower()
    if normalized == "hook":
        return "hook_focus"
    if normalized == "comparison":
        return "comparison_focus"
    if normalized in {"step", "action"}:
        return "step_focus"
    return "screen_focus"


def _chapter_card_title(span: dict[str, Any]) -> str:
    text = str(span.get("text") or "").strip()
    span_type = str(span.get("type") or "").strip().lower()
    if text:
        return text[:24]
    if span_type == "hook":
        return "开场重点"
    if span_type == "comparison":
        return "对比重点"
    if span_type in {"step", "action"}:
        return "关键步骤"
    return "重点片段"
