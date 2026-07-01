from __future__ import annotations

from pathlib import Path
from typing import Any

from roughcut.config import DEFAULT_OUTPUT_ROOT, DEFAULT_PROJECT_ROOT, get_settings

CREATOR_ASSET_CATEGORY_ALIASES: dict[str, str] = {
    "digital_human_sample": "digital_human_closeup",
    "watermark": "logo",
    "music": "music_library",
}

_CREATOR_ASSET_DIGITAL_HUMAN_CATEGORIES = {
    "digital_human_closeup",
    "digital_human_full_body",
}


def normalize_creator_asset_category(asset_type: Any) -> str:
    normalized = str(asset_type or "").strip()
    if not normalized:
        return "other"
    return CREATOR_ASSET_CATEGORY_ALIASES.get(normalized, normalized)


def creator_asset_media_kind(content_type: Any, path: Any = "") -> str:
    value = f"{content_type or ''} {path or ''}".lower()
    if "image/" in value or any(value.endswith(ext) or f"{ext}?" in value for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg")):
        return "image"
    if "video/" in value or any(value.endswith(ext) or f"{ext}?" in value for ext in (".mp4", ".mov", ".mkv", ".avi", ".webm")):
        return "video"
    if "audio/" in value or any(value.endswith(ext) or f"{ext}?" in value for ext in (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")):
        return "audio"
    return "file"


def creator_asset_path_candidates(stored_path: Any) -> list[Path]:
    raw = str(stored_path or "").strip()
    if not raw:
        return []

    normalized = raw.replace("\\", "/")
    candidates = [Path(raw).expanduser()]
    if normalized != raw:
        candidates.append(Path(normalized).expanduser())

    marker = "/_creator_assets/"
    if marker in normalized:
        suffix = normalized.split(marker, 1)[1].strip("/")
        if suffix:
            candidates.append(Path(get_settings().output_dir).expanduser().resolve() / "_creator_assets" / Path(suffix))
            candidates.append(DEFAULT_OUTPUT_ROOT / "_creator_assets" / Path(suffix))
            candidates.append(DEFAULT_OUTPUT_ROOT / "output" / "_creator_assets" / Path(suffix))
            candidates.append((DEFAULT_PROJECT_ROOT / "data" / "output") / "_creator_assets" / Path(suffix))
            candidates.append((DEFAULT_PROJECT_ROOT / "data" / "runtime" / "output") / "_creator_assets" / Path(suffix))

    if normalized.startswith("/app/"):
        candidates.append(Path(normalized.removeprefix("/app/")).expanduser())
        if normalized.startswith("/app/data/output/"):
            relative = normalized.removeprefix("/app/data/output/").strip("/")
            if relative:
                candidates.append(Path(get_settings().output_dir).expanduser().resolve() / Path(relative))
                candidates.append(DEFAULT_OUTPUT_ROOT / Path(relative))
                candidates.append(DEFAULT_OUTPUT_ROOT / "output" / Path(relative))
                candidates.append((DEFAULT_PROJECT_ROOT / "data" / "output") / Path(relative))
                candidates.append((DEFAULT_PROJECT_ROOT / "data" / "runtime" / "output") / Path(relative))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key and key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def resolve_creator_asset_path(stored_path: Any) -> Path:
    candidates = creator_asset_path_candidates(stored_path)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    return candidates[0] if candidates else Path("__roughcut_missing_creator_asset__")


def creator_asset_ready(asset: dict[str, Any] | Any, *, category: str | None = None, media_kind: str | None = None) -> bool:
    if not isinstance(asset, dict):
        asset = {
            "asset_type": getattr(asset, "asset_type", None),
            "stored_path": getattr(asset, "stored_path", None),
            "metadata_json": getattr(asset, "metadata_json", None),
        }
    normalized_category = normalize_creator_asset_category(asset.get("asset_type"))
    if category and normalized_category != category:
        return False
    resolved_media_kind = creator_asset_media_kind(
        (asset.get("metadata_json") or {}).get("content_type"),
        asset.get("stored_path"),
    )
    if media_kind and resolved_media_kind != media_kind:
        return False
    resolved_path = resolve_creator_asset_path(asset.get("stored_path"))
    return resolved_path.exists() and resolved_path.is_file()


def creator_packaging_asset_types(assets: list[dict[str, Any] | Any]) -> set[str]:
    packaging_types: set[str] = set()
    for item in list(assets or []):
        asset = item if isinstance(item, dict) else {
            "asset_type": getattr(item, "asset_type", None),
            "stored_path": getattr(item, "stored_path", None),
            "metadata_json": getattr(item, "metadata_json", None),
        }
        if not creator_asset_ready(asset):
            continue
        category = normalize_creator_asset_category(asset.get("asset_type"))
        if category in {"intro", "outro"}:
            packaging_types.add(category)
        elif category == "logo":
            packaging_types.add("watermark")
        elif category == "music_library":
            packaging_types.add("music")
    return packaging_types


def creator_has_complete_packaging_assets(assets: list[dict[str, Any] | Any]) -> bool:
    return {"intro", "outro", "watermark", "music"}.issubset(creator_packaging_asset_types(assets))


def pick_creator_avatar_presenter_asset(assets: list[dict[str, Any] | Any]) -> dict[str, Any] | None:
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for item in assets:
        asset = item if isinstance(item, dict) else {
            "id": getattr(item, "id", None),
            "asset_type": getattr(item, "asset_type", None),
            "stored_path": getattr(item, "stored_path", None),
            "metadata_json": getattr(item, "metadata_json", None),
            "original_name": getattr(item, "original_name", None),
            "created_at": getattr(item, "created_at", None),
            "creator_card_id": getattr(item, "creator_card_id", None),
        }
        category = normalize_creator_asset_category(asset.get("asset_type"))
        if category not in _CREATOR_ASSET_DIGITAL_HUMAN_CATEGORIES:
            continue
        if not creator_asset_ready(asset, media_kind="video"):
            continue
        score = 2 if category == "digital_human_closeup" else 1
        candidates.append((score, str(asset.get("created_at") or ""), asset))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]
