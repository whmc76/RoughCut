from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from roughcut.config import VOICE_PROVIDER_OPTIONS, apply_runtime_overrides, get_settings
from roughcut.creative.modes import normalize_enhancement_modes, normalize_workflow_mode
from roughcut.packaging.library import (
    DEFAULT_CONFIG as DEFAULT_PACKAGING_CONFIG,
    _normalize_config,
    list_packaging_assets,
    update_packaging_config,
)

CONFIG_PROFILES_FILE = Path("roughcut_config_profiles.json")

PROFILE_CONFIG_FIELDS: tuple[str, ...] = (
    "default_job_workflow_mode",
    "default_job_enhancement_modes",
    "avatar_presenter_id",
    "avatar_layout_template",
    "avatar_safe_margin",
    "avatar_overlay_scale",
    "voice_provider",
    "voice_clone_voice_id",
    "director_rewrite_strength",
)


def build_current_config_profile_snapshot() -> dict[str, Any]:
    settings = get_settings()
    config_snapshot = {
        key: deepcopy(getattr(settings, key))
        for key in PROFILE_CONFIG_FIELDS
    }
    config_snapshot["default_job_workflow_mode"] = normalize_workflow_mode(
        str(config_snapshot.get("default_job_workflow_mode") or ""),
    )
    config_snapshot["default_job_enhancement_modes"] = normalize_enhancement_modes(
        list(config_snapshot.get("default_job_enhancement_modes") or []),
    )
    config_snapshot["avatar_presenter_id"] = str(config_snapshot.get("avatar_presenter_id") or "").strip()
    config_snapshot["avatar_layout_template"] = str(config_snapshot.get("avatar_layout_template") or "").strip()
    config_snapshot["voice_provider"] = _normalize_voice_provider(config_snapshot.get("voice_provider"))
    config_snapshot["voice_clone_voice_id"] = str(config_snapshot.get("voice_clone_voice_id") or "").strip()
    config_snapshot["avatar_safe_margin"] = round(
        max(0.0, min(0.4, _coerce_float(config_snapshot.get("avatar_safe_margin"), 0.08))),
        4,
    )
    config_snapshot["avatar_overlay_scale"] = round(
        max(0.08, min(0.5, _coerce_float(config_snapshot.get("avatar_overlay_scale"), 0.18))),
        4,
    )
    config_snapshot["director_rewrite_strength"] = round(
        max(0.0, min(1.0, _coerce_float(config_snapshot.get("director_rewrite_strength"), 0.55))),
        4,
    )

    packaging_library = list_packaging_assets()
    assets_by_id = {
        item["id"]: item
        for items in (packaging_library.get("assets") or {}).values()
        for item in items
    }
    packaging_snapshot = _normalize_config(
        dict(packaging_library.get("config") or DEFAULT_PACKAGING_CONFIG),
        assets_by_id,
    )
    return {
        "config": config_snapshot,
        "packaging": packaging_snapshot,
    }


def load_config_profiles_state() -> dict[str, Any]:
    state: dict[str, Any] = {
        "active_profile_id": None,
        "profiles": [],
    }
    if not CONFIG_PROFILES_FILE.exists():
        return state

    try:
        payload = json.loads(CONFIG_PROFILES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return state

    raw_profiles = payload.get("profiles") if isinstance(payload, dict) else []
    profiles = [
        _normalize_profile_record(item)
        for item in (raw_profiles or [])
        if isinstance(item, dict)
    ]
    active_profile_id = payload.get("active_profile_id") if isinstance(payload, dict) else None
    if active_profile_id not in {profile["id"] for profile in profiles}:
        active_profile_id = None

    state["active_profile_id"] = active_profile_id
    state["profiles"] = _sort_profiles(profiles)
    return state


def save_config_profiles_state(state: dict[str, Any]) -> None:
    CONFIG_PROFILES_FILE.write_text(
        json.dumps(
            {
                "active_profile_id": state.get("active_profile_id"),
                "profiles": _sort_profiles(list(state.get("profiles") or [])),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def build_config_profiles_payload() -> dict[str, Any]:
    state = load_config_profiles_state()
    current_snapshot = build_current_config_profile_snapshot()
    active_profile_id = state.get("active_profile_id")
    profiles = [
        _build_profile_payload(profile, active_profile_id=active_profile_id, current_snapshot=current_snapshot)
        for profile in state.get("profiles") or []
    ]
    return {
        "active_profile_id": active_profile_id,
        "active_profile_dirty": any(profile["is_active"] and profile["is_dirty"] for profile in profiles),
        "profiles": profiles,
    }


def create_config_profile(name: str) -> dict[str, Any]:
    state = load_config_profiles_state()
    timestamp = _utcnow()
    snapshot = build_current_config_profile_snapshot()
    profile = {
        "id": uuid.uuid4().hex,
        "name": _normalize_profile_name(name),
        "created_at": timestamp,
        "updated_at": timestamp,
        "config": snapshot["config"],
        "packaging": snapshot["packaging"],
    }
    state["profiles"] = _sort_profiles([profile, *(state.get("profiles") or [])])
    state["active_profile_id"] = profile["id"]
    save_config_profiles_state(state)
    return build_config_profiles_payload()


def update_config_profile(
    profile_id: str,
    *,
    name: str | None = None,
    capture_current: bool = False,
) -> dict[str, Any]:
    state = load_config_profiles_state()
    profile = _find_profile(state, profile_id)
    updated = False

    if name is not None:
        normalized_name = _normalize_profile_name(name)
        if normalized_name != profile["name"]:
            profile["name"] = normalized_name
            updated = True

    if capture_current:
        snapshot = build_current_config_profile_snapshot()
        if not _snapshots_equal(profile, snapshot):
            profile["config"] = snapshot["config"]
            profile["packaging"] = snapshot["packaging"]
            updated = True

    if updated:
        profile["updated_at"] = _utcnow()

    save_config_profiles_state(state)
    return build_config_profiles_payload()


def activate_config_profile(profile_id: str) -> dict[str, Any]:
    state = load_config_profiles_state()
    profile = _find_profile(state, profile_id)

    apply_runtime_overrides(dict(profile.get("config") or {}))
    update_packaging_config(dict(profile.get("packaging") or {}))

    state["active_profile_id"] = profile["id"]
    current_snapshot = build_current_config_profile_snapshot()
    if not _snapshots_equal(profile, current_snapshot):
        profile["config"] = current_snapshot["config"]
        profile["packaging"] = current_snapshot["packaging"]
        profile["updated_at"] = _utcnow()

    save_config_profiles_state(state)
    return build_config_profiles_payload()


def delete_config_profile(profile_id: str) -> dict[str, Any]:
    state = load_config_profiles_state()
    profile = _find_profile(state, profile_id)
    state["profiles"] = [item for item in state.get("profiles") or [] if item["id"] != profile["id"]]
    if state.get("active_profile_id") == profile["id"]:
        state["active_profile_id"] = None
    save_config_profiles_state(state)
    return build_config_profiles_payload()


def _build_profile_payload(
    profile: dict[str, Any],
    *,
    active_profile_id: str | None,
    current_snapshot: dict[str, Any],
) -> dict[str, Any]:
    config_snapshot = dict(profile.get("config") or {})
    packaging_snapshot = dict(profile.get("packaging") or {})
    is_active = profile["id"] == active_profile_id
    is_dirty = is_active and not _snapshots_equal(profile, current_snapshot)
    return {
        "id": profile["id"],
        "name": profile["name"],
        "created_at": profile["created_at"],
        "updated_at": profile["updated_at"],
        "is_active": is_active,
        "is_dirty": is_dirty,
        "workflow_mode": str(config_snapshot.get("default_job_workflow_mode") or "standard_edit"),
        "enhancement_modes": list(config_snapshot.get("default_job_enhancement_modes") or []),
        "copy_style": str(packaging_snapshot.get("copy_style") or DEFAULT_PACKAGING_CONFIG["copy_style"]),
        "cover_style": str(packaging_snapshot.get("cover_style") or DEFAULT_PACKAGING_CONFIG["cover_style"]),
        "title_style": str(packaging_snapshot.get("title_style") or DEFAULT_PACKAGING_CONFIG["title_style"]),
        "subtitle_style": str(packaging_snapshot.get("subtitle_style") or DEFAULT_PACKAGING_CONFIG["subtitle_style"]),
        "smart_effect_style": str(
            packaging_snapshot.get("smart_effect_style") or DEFAULT_PACKAGING_CONFIG["smart_effect_style"]
        ),
        "avatar_presenter_id": str(config_snapshot.get("avatar_presenter_id") or ""),
        "packaging_enabled": bool(packaging_snapshot.get("enabled")),
        "insert_pool_size": len(list(packaging_snapshot.get("insert_asset_ids") or [])),
        "music_pool_size": len(list(packaging_snapshot.get("music_asset_ids") or [])),
    }


def _normalize_profile_record(raw: dict[str, Any]) -> dict[str, Any]:
    timestamp = _utcnow()
    snapshot = _normalize_profile_snapshot(
        {
            "config": raw.get("config") or {},
            "packaging": raw.get("packaging") or {},
        }
    )
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex),
        "name": _normalize_profile_name(raw.get("name")),
        "created_at": str(raw.get("created_at") or timestamp),
        "updated_at": str(raw.get("updated_at") or raw.get("created_at") or timestamp),
        "config": snapshot["config"],
        "packaging": snapshot["packaging"],
    }


def _normalize_profile_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    current_snapshot = build_current_config_profile_snapshot()
    config_snapshot = dict(current_snapshot["config"])
    config_snapshot.update(dict(snapshot.get("config") or {}))
    packaging_snapshot = dict(DEFAULT_PACKAGING_CONFIG)
    packaging_snapshot.update(dict(snapshot.get("packaging") or {}))

    config_snapshot["default_job_workflow_mode"] = normalize_workflow_mode(
        str(config_snapshot.get("default_job_workflow_mode") or ""),
    )
    config_snapshot["default_job_enhancement_modes"] = normalize_enhancement_modes(
        list(config_snapshot.get("default_job_enhancement_modes") or []),
    )
    config_snapshot["avatar_presenter_id"] = str(config_snapshot.get("avatar_presenter_id") or "").strip()
    config_snapshot["avatar_layout_template"] = str(config_snapshot.get("avatar_layout_template") or "").strip()
    config_snapshot["avatar_safe_margin"] = round(
        max(
            0.0,
            min(
                0.4,
                _coerce_float(
                    config_snapshot.get("avatar_safe_margin"),
                    current_snapshot["config"]["avatar_safe_margin"],
                ),
            ),
        ),
        4,
    )
    config_snapshot["avatar_overlay_scale"] = round(
        max(
            0.08,
            min(
                0.5,
                _coerce_float(
                    config_snapshot.get("avatar_overlay_scale"),
                    current_snapshot["config"]["avatar_overlay_scale"],
                ),
            ),
        ),
        4,
    )
    config_snapshot["voice_provider"] = _normalize_voice_provider(
        config_snapshot.get("voice_provider") or current_snapshot["config"]["voice_provider"]
    )
    config_snapshot["voice_clone_voice_id"] = str(config_snapshot.get("voice_clone_voice_id") or "").strip()
    config_snapshot["director_rewrite_strength"] = round(
        max(
            0.0,
            min(
                1.0,
                _coerce_float(
                    config_snapshot.get("director_rewrite_strength"),
                    current_snapshot["config"]["director_rewrite_strength"],
                ),
            ),
        ),
        4,
    )

    assets_by_id = {
        item["id"]: item
        for items in (list_packaging_assets().get("assets") or {}).values()
        for item in items
    }
    packaging_snapshot = _normalize_config(packaging_snapshot, assets_by_id)
    return {
        "config": config_snapshot,
        "packaging": packaging_snapshot,
    }


def _normalize_profile_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("配置方案名称不能为空")
    return name[:60]


def _normalize_voice_provider(value: Any) -> str:
    provider = str(value or "").strip().lower()
    if provider not in VOICE_PROVIDER_OPTIONS:
        return get_settings().voice_provider
    return provider


def _coerce_float(value: Any, fallback: float) -> float:
    if value is None:
        return float(fallback)
    try:
        return float(value)
    except Exception:
        return float(fallback)


def _snapshots_equal(profile: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    return _stable_json(profile.get("config") or {}) == _stable_json(snapshot.get("config") or {}) and _stable_json(
        profile.get("packaging") or {}
    ) == _stable_json(snapshot.get("packaging") or {})


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _find_profile(state: dict[str, Any], profile_id: str) -> dict[str, Any]:
    for profile in state.get("profiles") or []:
        if profile["id"] == profile_id:
            return profile
    raise KeyError(profile_id)


def _sort_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        profiles,
        key=lambda item: (
            str(item.get("updated_at") or ""),
            str(item.get("created_at") or ""),
            str(item.get("name") or ""),
        ),
        reverse=True,
    )


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
