from __future__ import annotations

from typing import Any


RAW_SURFACE_LAYER = "raw"
CANONICAL_SURFACE_LAYER = "canonical"
DISPLAY_SURFACE_LAYER = "display"

_RAW_SURFACE_KEYS = (
    "transcript_text_raw",
    "raw_text",
    "text_raw",
    "timing_text",
)
_CANONICAL_SURFACE_KEYS = (
    "transcript_text_canonical",
    "text_canonical",
    "transcript_text",
    "canonical_text",
    "text_norm",
)
_DISPLAY_SURFACE_KEYS = (
    "subtitle_text_display",
    "display_text",
    "display_source_text",
    "projection_text",
)


def _surface_text(item: dict[str, Any] | None, keys: tuple[str, ...]) -> str:
    if not item:
        return ""
    for key in keys:
        text = str(item.get(key) or "").strip()
        if text:
            return text
    transcript_texts = [str(text).strip() for text in (item.get("transcript_texts") or []) if str(text).strip()]
    if transcript_texts:
        return " ".join(transcript_texts).strip()
    return ""


def subtitle_semantic_preview_text(item: dict[str, Any] | None) -> str:
    return subtitle_canonical_rule_text(item)


def subtitle_spoken_rule_text(item: dict[str, Any] | None) -> str:
    return subtitle_raw_rule_text(item)


def subtitle_raw_explicit_text(item: dict[str, Any] | None) -> str:
    return _surface_text(item, _RAW_SURFACE_KEYS)


def subtitle_canonical_explicit_text(item: dict[str, Any] | None) -> str:
    return _surface_text(item, _CANONICAL_SURFACE_KEYS)


def subtitle_raw_rule_text(item: dict[str, Any] | None) -> str:
    text = subtitle_raw_explicit_text(item)
    if text:
        return text
    return _surface_text(item, _CANONICAL_SURFACE_KEYS)


def subtitle_canonical_rule_text(item: dict[str, Any] | None) -> str:
    text = subtitle_canonical_explicit_text(item)
    if text:
        return text
    if item and str(item.get("text_final") or "").strip():
        return str(item.get("text_final") or "").strip()
    return _surface_text(item, _DISPLAY_SURFACE_KEYS) or _surface_text(item, _RAW_SURFACE_KEYS)


def subtitle_display_rule_text(item: dict[str, Any] | None) -> str:
    if str(item.get("display_suppressed_reason") or "").strip():
        return ""
    explicit_display_text = _surface_text(item, _DISPLAY_SURFACE_KEYS)
    if explicit_display_text:
        return explicit_display_text
    if item and "text_final" in item:
        explicit_display_text = str(item.get("text_final") or "").strip()
        if explicit_display_text:
            return explicit_display_text
        if str(item.get("display_suppressed_reason") or "").strip():
            return ""
    return _surface_text(item, _CANONICAL_SURFACE_KEYS) or _surface_text(item, _RAW_SURFACE_KEYS)


def subtitle_surface_item_dict(
    item: dict[str, Any] | None,
    *,
    generic_fallback_text: str = "",
) -> dict[str, str]:
    payload = dict(item or {})
    generic_text = str(generic_fallback_text or "").strip()
    has_explicit_raw = any(key in payload for key in _RAW_SURFACE_KEYS)
    has_explicit_canonical = any(key in payload for key in _CANONICAL_SURFACE_KEYS)
    has_explicit_display = "text_final" in payload or any(key in payload for key in _DISPLAY_SURFACE_KEYS)
    has_any_explicit_surface = has_explicit_raw or has_explicit_canonical or has_explicit_display
    raw_text = subtitle_raw_explicit_text(payload) if has_explicit_raw else ""
    canonical_text = subtitle_canonical_explicit_text(payload) if has_explicit_canonical else ""
    display_text = subtitle_display_rule_text(payload) if has_explicit_display else ""
    if not has_any_explicit_surface:
        return {
            "text_raw": generic_text,
            "text_norm": generic_text,
            "text_final": generic_text,
        }
    return {
        "text_raw": raw_text,
        "text_norm": canonical_text,
        "text_final": display_text,
    }


def subtitle_semantic_item_text(
    item: dict[str, Any] | None,
    *,
    generic_fallback_text: str = "",
) -> str:
    return subtitle_surface_item_dict(item, generic_fallback_text=generic_fallback_text)["text_norm"]
