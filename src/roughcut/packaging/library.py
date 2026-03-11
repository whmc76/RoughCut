from __future__ import annotations

import json
import mimetypes
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PACKAGING_ROOT = Path(".artifacts/packaging")
MANIFEST_PATH = PACKAGING_ROOT / "manifest.json"

ASSET_EXTENSIONS: dict[str, set[str]] = {
    "intro": {".mp4", ".mov", ".mkv", ".webm"},
    "outro": {".mp4", ".mov", ".mkv", ".webm"},
    "insert": {".mp4", ".mov", ".mkv", ".webm"},
    "music": {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"},
    "watermark": {".png", ".jpg", ".jpeg", ".webp"},
}

DEFAULT_CONFIG: dict[str, Any] = {
    "intro_asset_id": None,
    "outro_asset_id": None,
    "insert_asset_id": None,
    "insert_asset_ids": [],
    "insert_selection_mode": "manual",
    "insert_position_mode": "llm",
    "watermark_asset_id": None,
    "music_asset_ids": [],
    "music_selection_mode": "random",
    "music_loop_mode": "loop_single",
    "music_volume": 0.22,
    "watermark_position": "top_right",
    "watermark_opacity": 0.82,
    "watermark_scale": 0.16,
    "enabled": True,
}


def list_packaging_assets() -> dict[str, Any]:
    state = _load_state()
    assets = sorted(state["assets"], key=lambda item: item.get("created_at", ""), reverse=True)
    by_type = {
        asset_type: [item for item in assets if item.get("asset_type") == asset_type]
        for asset_type in ASSET_EXTENSIONS
    }
    return {
        "assets": by_type,
        "config": state["config"],
    }


def save_packaging_asset(*, asset_type: str, filename: str, payload: bytes) -> dict[str, Any]:
    asset_type = _normalize_asset_type(asset_type)
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ASSET_EXTENSIONS[asset_type]:
        raise ValueError(f"Unsupported {asset_type} file type: {suffix or 'unknown'}")

    PACKAGING_ROOT.mkdir(parents=True, exist_ok=True)
    asset_id = uuid.uuid4().hex
    stored_name = f"{asset_id}{suffix}"
    asset_dir = PACKAGING_ROOT / asset_type
    asset_dir.mkdir(parents=True, exist_ok=True)
    target = asset_dir / stored_name
    target.write_bytes(payload)

    item = {
        "id": asset_id,
        "asset_type": asset_type,
        "original_name": Path(filename or stored_name).name,
        "stored_name": stored_name,
        "path": str(target.resolve()),
        "size_bytes": len(payload),
        "content_type": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    state = _load_state()
    state["assets"] = [existing for existing in state["assets"] if existing.get("id") != asset_id]
    state["assets"].append(item)

    if asset_type in {"intro", "outro", "watermark"}:
        config_key = f"{asset_type}_asset_id"
        if not state["config"].get(config_key):
            state["config"][config_key] = asset_id
    if asset_type == "insert":
        if not state["config"].get("insert_asset_id"):
            state["config"]["insert_asset_id"] = asset_id
        insert_ids = list(state["config"].get("insert_asset_ids") or [])
        if asset_id not in insert_ids:
            insert_ids.append(asset_id)
        state["config"]["insert_asset_ids"] = insert_ids
    if asset_type == "music":
        music_ids = list(state["config"].get("music_asset_ids") or [])
        if asset_id not in music_ids:
            music_ids.append(asset_id)
        state["config"]["music_asset_ids"] = music_ids

    _save_state(state)
    return item


def delete_packaging_asset(asset_id: str) -> None:
    state = _load_state()
    asset = next((item for item in state["assets"] if item.get("id") == asset_id), None)
    if not asset:
        raise KeyError(asset_id)

    path = Path(asset["path"])
    path.unlink(missing_ok=True)

    state["assets"] = [item for item in state["assets"] if item.get("id") != asset_id]
    config = state["config"]
    for key in ("intro_asset_id", "outro_asset_id", "insert_asset_id", "watermark_asset_id"):
        if config.get(key) == asset_id:
            config[key] = None
    config["insert_asset_ids"] = [item for item in config.get("insert_asset_ids", []) if item != asset_id]
    config["music_asset_ids"] = [item for item in config.get("music_asset_ids", []) if item != asset_id]
    _save_state(state)


def update_packaging_config(patch: dict[str, Any]) -> dict[str, Any]:
    state = _load_state()
    config = state["config"]
    assets_by_id = {item["id"]: item for item in state["assets"]}

    for key, value in patch.items():
        if key not in DEFAULT_CONFIG:
            continue
        config[key] = value

    for asset_key, asset_type in (
        ("intro_asset_id", "intro"),
        ("outro_asset_id", "outro"),
        ("insert_asset_id", "insert"),
        ("watermark_asset_id", "watermark"),
    ):
        asset_id = config.get(asset_key)
        if asset_id and assets_by_id.get(asset_id, {}).get("asset_type") != asset_type:
            raise ValueError(f"{asset_key} does not reference a valid {asset_type} asset")

    insert_ids = [item for item in (config.get("insert_asset_ids") or []) if assets_by_id.get(item, {}).get("asset_type") == "insert"]
    config["insert_asset_ids"] = insert_ids
    config["insert_selection_mode"] = str(config.get("insert_selection_mode") or "manual").strip() or "manual"
    config["insert_position_mode"] = str(config.get("insert_position_mode") or "llm").strip() or "llm"
    music_ids = [item for item in (config.get("music_asset_ids") or []) if assets_by_id.get(item, {}).get("asset_type") == "music"]
    config["music_asset_ids"] = music_ids
    config["music_selection_mode"] = str(config.get("music_selection_mode") or "random").strip() or "random"
    config["music_loop_mode"] = str(config.get("music_loop_mode") or "loop_single").strip() or "loop_single"
    config["music_volume"] = float(config.get("music_volume") or DEFAULT_CONFIG["music_volume"])
    config["watermark_opacity"] = float(config.get("watermark_opacity") or DEFAULT_CONFIG["watermark_opacity"])
    config["watermark_scale"] = float(config.get("watermark_scale") or DEFAULT_CONFIG["watermark_scale"])
    config["watermark_position"] = str(config.get("watermark_position") or "top_right").strip() or "top_right"
    config["enabled"] = bool(config.get("enabled"))

    _save_state(state)
    return config


def resolve_packaging_plan_for_job(job_id: str) -> dict[str, Any]:
    state = _load_state()
    config = dict(DEFAULT_CONFIG)
    config.update(state["config"])
    if not config.get("enabled"):
        return {
            "intro": None,
            "outro": None,
            "insert": None,
            "watermark": None,
            "music": None,
        }

    assets_by_id = {
        item["id"]: item for item in state["assets"]
        if Path(item.get("path") or "").exists()
    }

    intro = _resolve_single_asset(assets_by_id, config.get("intro_asset_id"), expected_type="intro")
    outro = _resolve_single_asset(assets_by_id, config.get("outro_asset_id"), expected_type="outro")
    insert = _resolve_insert_asset(assets_by_id, config, job_id)
    watermark = _resolve_single_asset(assets_by_id, config.get("watermark_asset_id"), expected_type="watermark")
    music = _resolve_music_asset(assets_by_id, config, job_id)

    if watermark:
        watermark.update(
            {
                "position": config["watermark_position"],
                "opacity": config["watermark_opacity"],
                "scale": config["watermark_scale"],
            }
        )
    if music:
        music.update(
            {
                "selection_mode": config["music_selection_mode"],
                "loop_mode": config["music_loop_mode"],
                "volume": config["music_volume"],
            }
        )

    return {
        "intro": intro,
        "outro": outro,
        "insert": insert,
        "watermark": watermark,
        "music": music,
    }


def get_packaging_asset(asset_id: str) -> dict[str, Any]:
    state = _load_state()
    asset = next((item for item in state["assets"] if item.get("id") == asset_id), None)
    if not asset:
        raise KeyError(asset_id)
    return asset


def _resolve_single_asset(
    assets_by_id: dict[str, dict[str, Any]],
    asset_id: str | None,
    *,
    expected_type: str,
) -> dict[str, Any] | None:
    if not asset_id:
        return None
    asset = assets_by_id.get(asset_id)
    if not asset or asset.get("asset_type") != expected_type:
        return None
    return {
        "asset_id": asset["id"],
        "asset_type": expected_type,
        "path": asset["path"],
        "original_name": asset["original_name"],
    }


def _resolve_music_asset(
    assets_by_id: dict[str, dict[str, Any]],
    config: dict[str, Any],
    job_id: str,
) -> dict[str, Any] | None:
    music_ids = [item for item in config.get("music_asset_ids") or [] if item in assets_by_id]
    if not music_ids:
        return None
    if config.get("music_selection_mode") == "random" and len(music_ids) > 1:
        selected_id = random.Random(job_id).choice(music_ids)
    else:
        selected_id = music_ids[0]
    asset = assets_by_id[selected_id]
    return {
        "asset_id": asset["id"],
        "asset_type": "music",
        "path": asset["path"],
        "original_name": asset["original_name"],
        "candidate_asset_ids": music_ids,
    }


def _resolve_insert_asset(
    assets_by_id: dict[str, dict[str, Any]],
    config: dict[str, Any],
    job_id: str,
) -> dict[str, Any] | None:
    insert_ids = [item for item in config.get("insert_asset_ids") or [] if item in assets_by_id]
    if config.get("insert_selection_mode") == "manual":
        selected_id = config.get("insert_asset_id")
        if selected_id not in insert_ids and selected_id in assets_by_id:
            insert_ids = [selected_id]
        if not selected_id:
            selected_id = insert_ids[0] if insert_ids else None
    else:
        selected_id = random.Random(f"insert:{job_id}").choice(insert_ids) if insert_ids else None
    if not selected_id:
        return None
    asset = assets_by_id[selected_id]
    return {
        "asset_id": asset["id"],
        "asset_type": "insert",
        "path": asset["path"],
        "original_name": asset["original_name"],
        "candidate_asset_ids": insert_ids,
        "selection_mode": config.get("insert_selection_mode") or "manual",
        "position_mode": config.get("insert_position_mode") or "llm",
    }


def _normalize_asset_type(asset_type: str) -> str:
    value = str(asset_type or "").strip().lower()
    if value not in ASSET_EXTENSIONS:
        raise ValueError(f"Unsupported asset type: {asset_type}")
    return value


def _load_state() -> dict[str, Any]:
    state = {
        "assets": [],
        "config": dict(DEFAULT_CONFIG),
    }
    if not MANIFEST_PATH.exists():
        return state
    try:
        raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return state
    state["assets"] = list(raw.get("assets") or [])
    state["config"].update(raw.get("config") or {})
    return state


def _save_state(state: dict[str, Any]) -> None:
    PACKAGING_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
