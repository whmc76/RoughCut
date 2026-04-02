from __future__ import annotations

from typing import Any


def _as_dict(value: object | None) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_text(value: object | None) -> str:
    return str(value).strip() if value is not None else ""


def _as_subtitle_items(value: object | None) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        items.append(dict(item) if isinstance(item, dict) else {"value": item})
    return items


def _collect_subtitle_lines(subtitle_items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in subtitle_items:
        for key in ("text_final", "text", "value"):
            value = _as_text(item.get(key))
            if value and value not in lines:
                lines.append(value)
                break
    return lines


def _collect_hint_candidates(candidate_hints: dict[str, Any], visual_hints: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for source in (candidate_hints, visual_hints):
        for key, raw in source.items():
            if isinstance(raw, list):
                items = raw
            else:
                items = [raw]
            for item in items:
                normalized = _as_text(item)
                if normalized and normalized not in values:
                    values.append(normalized)
    return values


def normalize_evidence_bundle(bundle: object | None) -> dict[str, Any]:
    raw = bundle if isinstance(bundle, dict) else {}
    source_name = _as_text(raw.get("source_name"))
    transcript_excerpt = _as_text(raw.get("transcript_excerpt"))
    subtitle_items = _as_subtitle_items(raw.get("subtitle_items"))
    ocr_profile = _as_dict(raw.get("ocr_profile"))

    visible_text = _as_text(raw.get("visible_text"))
    if not visible_text:
        visible_text = _as_text(ocr_profile.get("visible_text"))

    candidate_hints = _as_dict(raw.get("candidate_hints"))
    visual_hints = _as_dict(raw.get("visual_hints"))
    if not visual_hints:
        visual_hints = _as_dict(candidate_hints.get("visual_hints"))
    if not visible_text:
        visible_text = _as_text(visual_hints.get("visible_text"))
    candidate_hints["visual_hints"] = visual_hints
    subtitle_lines = _collect_subtitle_lines(subtitle_items)
    semantic_fact_inputs = {
        "source_name": source_name,
        "subtitle_lines": subtitle_lines,
        "transcript_text": transcript_excerpt,
        "visible_text": visible_text,
        "hint_candidates": _collect_hint_candidates(candidate_hints, visual_hints),
    }

    normalized: dict[str, Any] = {
        "source_name": source_name,
        "transcript_excerpt": transcript_excerpt,
        "subtitle_items": subtitle_items,
        "visible_text": visible_text,
        "ocr_profile": ocr_profile,
        "candidate_hints": candidate_hints,
        "semantic_fact_inputs": semantic_fact_inputs,
    }
    return normalized


def build_evidence_bundle(
    *,
    source_name: str,
    subtitle_items: list[dict[str, Any]] | None = None,
    transcript_excerpt: str = "",
    visible_text: str = "",
    ocr_profile: dict[str, Any] | None = None,
    visual_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return normalize_evidence_bundle(
        {
            "source_name": source_name,
            "subtitle_items": subtitle_items or [],
            "transcript_excerpt": transcript_excerpt,
            "visible_text": visible_text,
            "ocr_profile": ocr_profile or {},
            "visual_hints": visual_hints or {},
        }
    )
