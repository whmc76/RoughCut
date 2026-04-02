from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]


def resolve_effective_variant_timeline_bundle(
    bundle: dict[str, Any] | None,
    *,
    render_outputs: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if isinstance(bundle, dict) and isinstance(bundle.get("variants"), dict):
        return bundle
    synthetic = build_legacy_variant_timeline_bundle(render_outputs or {})
    return synthetic or None


def build_legacy_variant_timeline_bundle(render_outputs: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(render_outputs, dict):
        return None

    variants: dict[str, dict[str, Any]] = {}
    quality_checks = render_outputs.get("quality_checks") if isinstance(render_outputs.get("quality_checks"), dict) else {}
    variant_specs = (
        ("packaged", "packaged_mp4", "packaged_srt", "subtitle_sync"),
        ("plain", "plain_mp4", "plain_srt", "plain_subtitle_sync"),
        ("avatar", "avatar_mp4", "avatar_srt", "avatar_subtitle_sync"),
        ("ai_effect", "ai_effect_mp4", "ai_effect_srt", "ai_effect_subtitle_sync"),
    )
    for variant_name, media_key, srt_key, quality_key in variant_specs:
        media_path = str(render_outputs.get(media_key) or "").strip()
        srt_path = str(render_outputs.get(srt_key) or "").strip()
        resolved_media_path = _resolve_runtime_path(media_path)
        resolved_srt_path = _resolve_runtime_path(srt_path)
        if not media_path and not srt_path:
            continue
        subtitle_events = _extract_subtitle_items_from_srt(resolved_srt_path) if resolved_srt_path else []
        variants[variant_name] = {
            "media": {
                "path": str(resolved_media_path or media_path) if (resolved_media_path or media_path) else None,
                "srt_path": str(resolved_srt_path or srt_path) if (resolved_srt_path or srt_path) else None,
                "duration_sec": _coerce_float((quality_checks.get(quality_key) or {}).get("video_duration_sec")),
            },
            "subtitle_events": subtitle_events,
            "overlay_events": {
                "emphasis_overlays": [],
                "sound_effects": [],
            },
            "quality_checks": {
                "subtitle_sync": dict(quality_checks.get(quality_key) or {}) if isinstance(quality_checks.get(quality_key), dict) else {},
            },
        }
    if not variants:
        return None
    bundle = {
        "timeline_rules": {"source": "legacy_render_outputs"},
        "variants": variants,
    }
    bundle["validation"] = _validate_legacy_variant_timeline_bundle(bundle)
    return bundle


def _extract_subtitle_items_from_srt(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    items: list[dict[str, Any]] = []
    for block in re.split(r"\r?\n\r?\n+", text):
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        start_text, end_text = [part.strip() for part in lines[1].split("-->", 1)]
        start_sec = _parse_srt_timestamp(start_text)
        end_sec = _parse_srt_timestamp(end_text)
        if start_sec is None or end_sec is None:
            continue
        items.append(
            {
                "index": len(items) + 1,
                "start_time": start_sec,
                "end_time": end_sec,
                "text": " ".join(lines[2:]).strip(),
            }
        )
    return items


def _parse_srt_timestamp(value: str) -> float | None:
    match = re.match(r"(\d{2}):(\d{2}):(\d{2})[,.:](\d{3})", value.strip())
    if not match:
        return None
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_runtime_path(raw_path: str) -> Path | None:
    value = str(raw_path or "").strip()
    if not value:
        return None
    candidate = Path(value)
    if candidate.exists():
        return candidate
    if value.startswith("/app/data/"):
        mapped = _REPO_ROOT / "data" / value.removeprefix("/app/data/")
        if mapped.exists():
            return mapped
    return None


def _validate_legacy_variant_timeline_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    variants = bundle.get("variants")
    if not isinstance(variants, dict):
        return {"status": "warning", "issues": ["variants payload missing"]}

    for variant_name, variant in variants.items():
        if not isinstance(variant, dict):
            issues.append(f"{variant_name}: variant payload is not a dict")
            continue
        media = variant.get("media") if isinstance(variant.get("media"), dict) else {}
        subtitle_events = variant.get("subtitle_events") if isinstance(variant.get("subtitle_events"), list) else []
        if media.get("srt_path") and not subtitle_events:
            issues.append(f"{variant_name}: srt_path present but subtitle events could not be loaded")

        subtitle_sync = ((variant.get("quality_checks") or {}).get("subtitle_sync") or {})
        duration_gap = _coerce_float(subtitle_sync.get("duration_gap_sec")) or 0.0
        trailing_gap = _coerce_float(subtitle_sync.get("trailing_gap_sec")) or 0.0
        if max(duration_gap, trailing_gap) > 3.0:
            issues.append(f"{variant_name}: sync metrics indicate a large subtitle gap")

    return {"status": "warning" if issues else "ok", "issues": issues}
