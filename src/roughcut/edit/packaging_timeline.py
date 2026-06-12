from __future__ import annotations

import copy
from typing import Any


def _normalize_packaging_timeline_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    packaging_assets = source.get("packaging") if isinstance(source.get("packaging"), dict) else {}
    return {
        "timeline_analysis": copy.deepcopy(source.get("timeline_analysis") or {}),
        "editing_skill": copy.deepcopy(source.get("editing_skill") or {}),
        "section_choreography": copy.deepcopy(source.get("section_choreography") or {}),
        "subtitles": copy.deepcopy(source.get("subtitles") or {}),
        "packaging": {
            "intro": copy.deepcopy(packaging_assets.get("intro")),
            "outro": copy.deepcopy(packaging_assets.get("outro")),
            "insert": copy.deepcopy(packaging_assets.get("insert")),
            "watermark": copy.deepcopy(packaging_assets.get("watermark")),
            "music": copy.deepcopy(packaging_assets.get("music")),
        },
        "editing_accents": copy.deepcopy(source.get("editing_accents") or {}),
    }


def build_packaging_timeline_payload(render_plan: dict[str, Any] | None) -> dict[str, Any]:
    payload = render_plan if isinstance(render_plan, dict) else {}
    return {
        "timeline_analysis": copy.deepcopy(payload.get("timeline_analysis") or {}),
        "editing_skill": copy.deepcopy(payload.get("editing_skill") or {}),
        "section_choreography": copy.deepcopy(payload.get("section_choreography") or {}),
        "subtitles": copy.deepcopy(payload.get("subtitles") or {}),
        "packaging": {
            "intro": copy.deepcopy(payload.get("intro")),
            "outro": copy.deepcopy(payload.get("outro")),
            "insert": copy.deepcopy(payload.get("insert")),
            "watermark": copy.deepcopy(payload.get("watermark")),
            "music": copy.deepcopy(payload.get("music")),
        },
        "editing_accents": copy.deepcopy(payload.get("editing_accents") or {}),
    }


def resolve_packaging_timeline_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    packaging_timeline = source.get("packaging_timeline")
    if isinstance(packaging_timeline, dict):
        return _normalize_packaging_timeline_payload(packaging_timeline)
    if any(
        key in source
        for key in ("timeline_analysis", "editing_skill", "section_choreography", "subtitles", "packaging", "editing_accents")
    ):
        return _normalize_packaging_timeline_payload(source)
    return _normalize_packaging_timeline_payload(
        {
            "timeline_analysis": source.get("timeline_analysis"),
            "editing_skill": source.get("editing_skill"),
            "section_choreography": source.get("section_choreography"),
            "subtitles": source.get("subtitles"),
            "editing_accents": source.get("editing_accents"),
            "packaging": {
                "intro": source.get("intro"),
                "outro": source.get("outro"),
                "insert": source.get("insert"),
                "watermark": source.get("watermark"),
                "music": source.get("music"),
            },
        }
    )


def packaging_timeline_analysis(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(resolve_packaging_timeline_payload(payload).get("timeline_analysis") or {})


def packaging_timeline_editing_skill(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(resolve_packaging_timeline_payload(payload).get("editing_skill") or {})


def packaging_timeline_section_choreography(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(resolve_packaging_timeline_payload(payload).get("section_choreography") or {})


def packaging_timeline_subtitles(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(resolve_packaging_timeline_payload(payload).get("subtitles") or {})


def packaging_timeline_assets(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(resolve_packaging_timeline_payload(payload).get("packaging") or {})


def packaging_timeline_asset_plan(
    payload: dict[str, Any] | None,
    asset_name: str,
) -> Any:
    asset_key = str(asset_name or "").strip()
    if not asset_key:
        return None
    packaging = dict(resolve_packaging_timeline_payload(payload).get("packaging") or {})
    return copy.deepcopy(packaging.get(asset_key))


def packaging_timeline_editing_accents(payload: dict[str, Any] | None) -> dict[str, Any]:
    return dict(resolve_packaging_timeline_payload(payload).get("editing_accents") or {})


def packaging_timeline_transitions(payload: dict[str, Any] | None) -> dict[str, Any]:
    editing_accents = dict(resolve_packaging_timeline_payload(payload).get("editing_accents") or {})
    return copy.deepcopy(editing_accents.get("transitions") or {})


def packaging_timeline_has_packaging_assets(payload: dict[str, Any] | None) -> bool:
    packaging = dict(resolve_packaging_timeline_payload(payload).get("packaging") or {})
    return any(packaging.get(key) for key in ("intro", "outro", "insert", "watermark", "music"))


def packaging_timeline_has_editing_accents(payload: dict[str, Any] | None) -> bool:
    accents = packaging_timeline_editing_accents(payload)
    transitions = copy.deepcopy(accents.get("transitions") or {})
    return bool(
        transitions.get("boundary_indexes")
        or accents.get("emphasis_overlays")
        or accents.get("sound_effects")
    )
