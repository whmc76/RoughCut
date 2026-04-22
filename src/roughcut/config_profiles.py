from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from roughcut.config import (
    ENV_MANAGED_SETTINGS,
    PROFILE_BINDABLE_SETTINGS,
    VOICE_PROVIDER_OPTIONS,
    DEFAULT_REASONING_PROVIDER,
    apply_runtime_overrides,
    get_settings,
    normalize_transcription_settings,
)
from roughcut.creative.modes import normalize_enhancement_modes, normalize_workflow_mode
from roughcut.packaging.library import (
    DEFAULT_CONFIG as DEFAULT_PACKAGING_CONFIG,
    _normalize_config,
    list_packaging_assets,
    update_packaging_config,
)
from roughcut.speech.dialects import DEFAULT_TRANSCRIPTION_DIALECT, normalize_transcription_dialect
from roughcut.state_store import ACTIVE_CONFIG_PROFILE_KEY, run_db_operation, set_json_setting

CONFIG_PROFILES_FILE = Path("roughcut_config_profiles.json")
PROFILE_CONFIG_FIELDS: tuple[str, ...] = PROFILE_BINDABLE_SETTINGS


def build_current_config_profile_snapshot() -> dict[str, Any]:
    settings = get_settings()
    config_snapshot = {
        key: deepcopy(getattr(settings, key))
        for key in PROFILE_CONFIG_FIELDS
    }
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
        "config": _normalize_config_snapshot(config_snapshot),
        "packaging": packaging_snapshot,
    }


def load_config_profiles_state() -> dict[str, Any]:
    state = _load_config_profiles_state_from_db()
    if state["profiles"] or state["active_profile_id"]:
        return state

    legacy = _load_legacy_config_profiles_state()
    if legacy["profiles"]:
        try:
            save_config_profiles_state(legacy)
            return _load_config_profiles_state_from_db()
        except Exception:
            return legacy
    return state


def save_config_profiles_state(state: dict[str, Any]) -> None:
    profiles = _sort_profiles([_normalize_profile_record(item) for item in (state.get("profiles") or [])])
    active_profile_id = state.get("active_profile_id")
    active_profile_id = active_profile_id if active_profile_id in {profile["id"] for profile in profiles} else None

    async def _operation(session: Any) -> None:
        from roughcut.db.models import ConfigProfile

        existing = {
            row.id.hex: row
            for row in (await session.execute(select(ConfigProfile))).scalars().all()
        }
        keep_ids = {profile["id"] for profile in profiles}

        for profile in profiles:
            profile_uuid = _parse_profile_uuid(profile["id"])
            row = existing.get(profile["id"])
            if row is None:
                row = ConfigProfile(
                    id=profile_uuid,
                    name=profile["name"],
                    description=profile.get("description"),
                    settings_json=dict(profile.get("config") or {}),
                    packaging_json=dict(profile.get("packaging") or {}),
                    created_at=_parse_timestamp(profile["created_at"]),
                    updated_at=_parse_timestamp(profile["updated_at"]),
                )
                session.add(row)
            else:
                row.name = profile["name"]
                row.description = profile.get("description")
                row.settings_json = dict(profile.get("config") or {})
                row.packaging_json = dict(profile.get("packaging") or {})
                row.created_at = _parse_timestamp(profile["created_at"])
                row.updated_at = _parse_timestamp(profile["updated_at"])

        for profile_id, row in existing.items():
            if profile_id not in keep_ids:
                await session.delete(row)

        await session.commit()

    try:
        run_db_operation(_operation)
        set_json_setting(ACTIVE_CONFIG_PROFILE_KEY, active_profile_id)
    except Exception:
        CONFIG_PROFILES_FILE.write_text(
            json.dumps(
                {
                    "active_profile_id": active_profile_id,
                    "profiles": profiles,
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
    active_profile = next((profile for profile in profiles if profile["is_active"]), None)
    return {
        "active_profile_id": active_profile_id,
        "active_profile_dirty": any(profile["is_active"] and profile["is_dirty"] for profile in profiles),
        "active_profile_dirty_keys": list(active_profile.get("dirty_keys") or []) if active_profile else [],
        "active_profile_dirty_details": list(active_profile.get("dirty_details") or []) if active_profile else [],
        "profiles": profiles,
    }


def create_config_profile(name: str, description: str | None = None) -> dict[str, Any]:
    snapshot = build_current_config_profile_snapshot()
    normalized_name = _normalize_profile_name(name)
    normalized_description = _normalize_profile_description(description)
    timestamp = datetime.now(timezone.utc)

    async def _operation(session: Any) -> str:
        from roughcut.db.models import ConfigProfile

        existing = await session.execute(select(ConfigProfile).where(ConfigProfile.name == normalized_name))
        if existing.scalar_one_or_none() is not None:
            raise ValueError("配置方案名称已存在")

        profile = ConfigProfile(
            id=uuid.uuid4(),
            name=normalized_name,
            description=normalized_description,
            settings_json=snapshot["config"],
            packaging_json=snapshot["packaging"],
            created_at=timestamp,
            updated_at=timestamp,
        )
        session.add(profile)
        await session.flush()
        await session.commit()
        return profile.id.hex

    profile_id = run_db_operation(_operation)
    set_json_setting(ACTIVE_CONFIG_PROFILE_KEY, profile_id)
    return build_config_profiles_payload()


def update_config_profile(
    profile_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    capture_current: bool = False,
) -> dict[str, Any]:
    normalized_name = _normalize_profile_name(name) if name is not None else None
    normalized_description = _normalize_profile_description(description) if description is not None else None
    snapshot = build_current_config_profile_snapshot() if capture_current else None

    async def _operation(session: Any) -> None:
        from roughcut.db.models import ConfigProfile

        row = await session.get(ConfigProfile, _parse_profile_uuid(profile_id))
        if row is None:
            raise KeyError(profile_id)

        updated = False
        if normalized_name is not None and normalized_name != row.name:
            existing = await session.execute(
                select(ConfigProfile).where(ConfigProfile.name == normalized_name, ConfigProfile.id != row.id)
            )
            if existing.scalar_one_or_none() is not None:
                raise ValueError("配置方案名称已存在")
            row.name = normalized_name
            updated = True

        if description is not None and normalized_description != (row.description or None):
            row.description = normalized_description
            updated = True

        if snapshot is not None and not _snapshots_equal(
            {"config": row.settings_json, "packaging": row.packaging_json},
            snapshot,
        ):
            row.settings_json = snapshot["config"]
            row.packaging_json = snapshot["packaging"]
            updated = True

        if updated:
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()

    run_db_operation(_operation)
    return build_config_profiles_payload()


def activate_config_profile(profile_id: str) -> dict[str, Any]:
    state = load_config_profiles_state()
    profile = _find_profile(state, profile_id)

    apply_runtime_overrides(dict(profile.get("config") or {}))
    update_packaging_config(dict(profile.get("packaging") or {}))

    current_snapshot = build_current_config_profile_snapshot()
    if not _snapshots_equal(profile, current_snapshot):
        profile["config"] = current_snapshot["config"]
        profile["packaging"] = current_snapshot["packaging"]
        profile["updated_at"] = _utcnow()

    state["active_profile_id"] = profile["id"]
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
    dirty_keys = _diff_snapshot_keys(profile, current_snapshot) if is_dirty else []
    dirty_details = _build_dirty_details(profile, current_snapshot, dirty_keys) if dirty_keys else []
    return {
        "id": profile["id"],
        "name": profile["name"],
        "description": str(profile.get("description") or ""),
        "created_at": profile["created_at"],
        "updated_at": profile["updated_at"],
        "is_active": is_active,
        "is_dirty": is_dirty,
        "dirty_keys": dirty_keys,
        "dirty_details": dirty_details,
        "llm_mode": str(config_snapshot.get("llm_mode") or "performance"),
        "transcription_provider": str(config_snapshot.get("transcription_provider") or "openai"),
        "transcription_model": str(config_snapshot.get("transcription_model") or ""),
        "transcription_dialect": str(config_snapshot.get("transcription_dialect") or DEFAULT_TRANSCRIPTION_DIALECT),
        "reasoning_provider": str(config_snapshot.get("reasoning_provider") or DEFAULT_REASONING_PROVIDER),
        "reasoning_model": str(config_snapshot.get("reasoning_model") or ""),
        "workflow_mode": str(config_snapshot.get("default_job_workflow_mode") or "standard_edit"),
        "enhancement_modes": list(config_snapshot.get("default_job_enhancement_modes") or []),
        "auto_confirm_content_profile": bool(config_snapshot.get("auto_confirm_content_profile")),
        "content_profile_review_threshold": float(
            config_snapshot.get("content_profile_review_threshold") or get_settings().content_profile_review_threshold
        ),
        "packaging_selection_min_score": float(
            config_snapshot.get("packaging_selection_min_score") or get_settings().packaging_selection_min_score
        ),
        "quality_auto_rerun_enabled": bool(config_snapshot.get("quality_auto_rerun_enabled")),
        "quality_auto_rerun_below_score": float(
            config_snapshot.get("quality_auto_rerun_below_score") or get_settings().quality_auto_rerun_below_score
        ),
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


def _load_config_profiles_state_from_db() -> dict[str, Any]:
    async def _operation(session: Any) -> dict[str, Any]:
        from roughcut.db.models import AppSetting, ConfigProfile

        rows = (await session.execute(select(ConfigProfile))).scalars().all()
        active_setting = await session.get(AppSetting, ACTIVE_CONFIG_PROFILE_KEY)
        active_profile_id = active_setting.value_json if active_setting is not None else None
        profiles = _sort_profiles([_serialize_profile_row(row) for row in rows])
        if active_profile_id not in {profile["id"] for profile in profiles}:
            active_profile_id = None
        return {
            "active_profile_id": active_profile_id,
            "profiles": profiles,
        }

    try:
        return run_db_operation(_operation)
    except Exception:
        return {
            "active_profile_id": None,
            "profiles": [],
        }


def _load_legacy_config_profiles_state() -> dict[str, Any]:
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


def _serialize_profile_row(row: Any) -> dict[str, Any]:
    return _normalize_profile_record(
        {
            "id": row.id.hex,
            "name": row.name,
            "description": row.description,
            "created_at": _timestamp_to_str(row.created_at),
            "updated_at": _timestamp_to_str(row.updated_at),
            "config": dict(row.settings_json or {}),
            "packaging": dict(row.packaging_json or {}),
        }
    )


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
        "description": _normalize_profile_description(raw.get("description")),
        "created_at": str(raw.get("created_at") or timestamp),
        "updated_at": str(raw.get("updated_at") or raw.get("created_at") or timestamp),
        "config": snapshot["config"],
        "packaging": snapshot["packaging"],
    }


def _normalize_profile_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    config_snapshot = {
        key: deepcopy(getattr(settings, key))
        for key in PROFILE_CONFIG_FIELDS
    }
    config_snapshot.update(dict(snapshot.get("config") or {}))
    packaging_snapshot = dict(DEFAULT_PACKAGING_CONFIG)
    packaging_snapshot.update(dict(snapshot.get("packaging") or {}))

    assets_by_id = {
        item["id"]: item
        for items in (list_packaging_assets().get("assets") or {}).values()
        for item in items
    }
    return {
        "config": _normalize_config_snapshot(config_snapshot),
        "packaging": _normalize_config(packaging_snapshot, assets_by_id),
    }


def _normalize_config_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    normalized = {
        key: deepcopy(getattr(settings, key))
        for key in PROFILE_CONFIG_FIELDS
    }
    normalized.update(dict(config or {}))
    for key in ENV_MANAGED_SETTINGS:
        normalized.pop(key, None)

    provider, model = normalize_transcription_settings(
        normalized.get("transcription_provider"),
        normalized.get("transcription_model"),
    )
    normalized["transcription_provider"] = provider
    normalized["transcription_model"] = model
    normalized["transcription_dialect"] = normalize_transcription_dialect(
        normalized.get("transcription_dialect") or DEFAULT_TRANSCRIPTION_DIALECT
    )
    normalized["local_asr_api_base_url"] = str(
        normalized.get("local_asr_api_base_url") or settings.local_asr_api_base_url
    ).strip()
    normalized["local_asr_model_name"] = str(
        normalized.get("local_asr_model_name") or settings.local_asr_model_name
    ).strip()
    normalized["local_asr_display_name"] = str(
        normalized.get("local_asr_display_name") or settings.local_asr_display_name
    ).strip()
    normalized["llm_mode"] = str(normalized.get("llm_mode") or settings.llm_mode).strip().lower() or settings.llm_mode
    normalized["llm_routing_mode"] = str(
        normalized.get("llm_routing_mode") or settings.llm_routing_mode
    ).strip().lower() or settings.llm_routing_mode
    normalized["reasoning_provider"] = str(normalized.get("reasoning_provider") or settings.reasoning_provider).strip().lower()
    normalized["reasoning_model"] = str(normalized.get("reasoning_model") or settings.reasoning_model).strip()
    normalized["reasoning_effort"] = str(normalized.get("reasoning_effort") or settings.reasoning_effort).strip().lower()
    normalized["llm_backup_enabled"] = bool(normalized.get("llm_backup_enabled", settings.llm_backup_enabled))
    normalized["backup_reasoning_provider"] = str(
        normalized.get("backup_reasoning_provider") or settings.backup_reasoning_provider
    ).strip().lower()
    normalized["backup_reasoning_model"] = str(
        normalized.get("backup_reasoning_model") or settings.backup_reasoning_model
    ).strip()
    normalized["backup_reasoning_effort"] = str(
        normalized.get("backup_reasoning_effort") or settings.backup_reasoning_effort
    ).strip().lower()
    normalized["backup_vision_model"] = str(
        normalized.get("backup_vision_model") or settings.backup_vision_model
    ).strip()
    normalized["backup_search_provider"] = str(
        normalized.get("backup_search_provider") or settings.backup_search_provider
    ).strip().lower()
    normalized["backup_search_fallback_provider"] = str(
        normalized.get("backup_search_fallback_provider") or settings.backup_search_fallback_provider
    ).strip().lower()
    normalized["backup_model_search_helper"] = str(
        normalized.get("backup_model_search_helper") or settings.backup_model_search_helper
    ).strip()
    normalized["local_reasoning_model"] = str(
        normalized.get("local_reasoning_model") or settings.local_reasoning_model
    ).strip()
    normalized["local_vision_model"] = str(normalized.get("local_vision_model") or settings.local_vision_model).strip()
    normalized["hybrid_analysis_provider"] = str(
        normalized.get("hybrid_analysis_provider") or settings.hybrid_analysis_provider
    ).strip().lower()
    normalized["hybrid_analysis_model"] = str(
        normalized.get("hybrid_analysis_model") or settings.hybrid_analysis_model
    ).strip()
    normalized["hybrid_analysis_effort"] = str(
        normalized.get("hybrid_analysis_effort") or settings.hybrid_analysis_effort
    ).strip().lower()
    normalized["hybrid_analysis_search_mode"] = str(
        normalized.get("hybrid_analysis_search_mode") or settings.hybrid_analysis_search_mode
    ).strip().lower()
    normalized["hybrid_copy_provider"] = str(
        normalized.get("hybrid_copy_provider") or settings.hybrid_copy_provider
    ).strip().lower()
    normalized["hybrid_copy_model"] = str(
        normalized.get("hybrid_copy_model") or settings.hybrid_copy_model
    ).strip()
    normalized["hybrid_copy_effort"] = str(
        normalized.get("hybrid_copy_effort") or settings.hybrid_copy_effort
    ).strip().lower()
    normalized["hybrid_copy_search_mode"] = str(
        normalized.get("hybrid_copy_search_mode") or settings.hybrid_copy_search_mode
    ).strip().lower()
    normalized["multimodal_fallback_provider"] = str(
        normalized.get("multimodal_fallback_provider") or settings.multimodal_fallback_provider
    ).strip().lower()
    normalized["multimodal_fallback_model"] = str(
        normalized.get("multimodal_fallback_model") or settings.multimodal_fallback_model
    ).strip()
    normalized["search_provider"] = str(normalized.get("search_provider") or settings.search_provider).strip().lower()
    normalized["search_fallback_provider"] = str(
        normalized.get("search_fallback_provider") or settings.search_fallback_provider
    ).strip().lower()
    normalized["model_search_helper"] = str(normalized.get("model_search_helper") or settings.model_search_helper).strip()
    normalized["avatar_provider"] = str(normalized.get("avatar_provider") or settings.avatar_provider).strip().lower()
    normalized["avatar_presenter_id"] = str(normalized.get("avatar_presenter_id") or "").strip()
    normalized["avatar_layout_template"] = str(
        normalized.get("avatar_layout_template") or settings.avatar_layout_template
    ).strip()
    normalized["avatar_safe_margin"] = round(
        max(0.0, min(0.4, _coerce_float(normalized.get("avatar_safe_margin"), settings.avatar_safe_margin))),
        4,
    )
    normalized["avatar_overlay_scale"] = round(
        max(0.08, min(0.5, _coerce_float(normalized.get("avatar_overlay_scale"), settings.avatar_overlay_scale))),
        4,
    )
    normalized["voice_provider"] = _normalize_voice_provider(normalized.get("voice_provider"))
    normalized["voice_clone_voice_id"] = str(normalized.get("voice_clone_voice_id") or "").strip()
    normalized["director_rewrite_strength"] = round(
        max(0.0, min(1.0, _coerce_float(normalized.get("director_rewrite_strength"), settings.director_rewrite_strength))),
        4,
    )
    normalized["default_job_workflow_mode"] = normalize_workflow_mode(
        str(normalized.get("default_job_workflow_mode") or settings.default_job_workflow_mode),
    )
    normalized["default_job_enhancement_modes"] = normalize_enhancement_modes(
        list(normalized.get("default_job_enhancement_modes") or settings.default_job_enhancement_modes or []),
    )
    normalized["fact_check_enabled"] = bool(normalized.get("fact_check_enabled"))
    normalized["auto_confirm_content_profile"] = bool(normalized.get("auto_confirm_content_profile"))
    normalized["content_profile_review_threshold"] = round(
        max(
            0.0,
            min(
                1.0,
                _coerce_float(
                    normalized.get("content_profile_review_threshold"),
                    settings.content_profile_review_threshold,
                ),
            ),
        ),
        4,
    )
    normalized["content_profile_auto_review_min_accuracy"] = round(
        max(
            0.0,
            min(
                1.0,
                _coerce_float(
                    normalized.get("content_profile_auto_review_min_accuracy"),
                    settings.content_profile_auto_review_min_accuracy,
                ),
            ),
        ),
        4,
    )
    normalized["content_profile_auto_review_min_samples"] = max(
        1,
        min(
            10000,
            _coerce_int(
                normalized.get("content_profile_auto_review_min_samples"),
                settings.content_profile_auto_review_min_samples,
            ),
        ),
    )
    normalized["auto_accept_glossary_corrections"] = bool(normalized.get("auto_accept_glossary_corrections"))
    normalized["glossary_correction_review_threshold"] = round(
        max(
            0.0,
            min(
                1.0,
                _coerce_float(
                    normalized.get("glossary_correction_review_threshold"),
                    settings.glossary_correction_review_threshold,
                ),
            ),
        ),
        4,
    )
    normalized["auto_select_cover_variant"] = bool(normalized.get("auto_select_cover_variant"))
    normalized["cover_selection_review_gap"] = round(
        max(0.0, min(1.0, _coerce_float(normalized.get("cover_selection_review_gap"), settings.cover_selection_review_gap))),
        4,
    )
    normalized["packaging_selection_review_gap"] = round(
        max(
            0.0,
            min(
                1.0,
                _coerce_float(
                    normalized.get("packaging_selection_review_gap"),
                    settings.packaging_selection_review_gap,
                ),
            ),
        ),
        4,
    )
    normalized["packaging_selection_min_score"] = round(
        max(
            0.0,
            min(
                1.0,
                _coerce_float(
                    normalized.get("packaging_selection_min_score"),
                    settings.packaging_selection_min_score,
                ),
            ),
        ),
        4,
    )
    normalized["subtitle_filler_cleanup_enabled"] = bool(normalized.get("subtitle_filler_cleanup_enabled"))
    normalized["quality_auto_rerun_enabled"] = bool(normalized.get("quality_auto_rerun_enabled"))
    normalized["quality_auto_rerun_below_score"] = round(
        max(
            0.0,
            min(
                100.0,
                _coerce_float(
                    normalized.get("quality_auto_rerun_below_score"),
                    settings.quality_auto_rerun_below_score,
                ),
            ),
        ),
        4,
    )
    normalized["quality_auto_rerun_max_attempts"] = max(
        0,
        min(
            5,
            _coerce_int(
                normalized.get("quality_auto_rerun_max_attempts"),
                settings.quality_auto_rerun_max_attempts,
            ),
        ),
    )
    return normalized


def _normalize_profile_name(value: Any) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("配置方案名称不能为空")
    return name[:60]


def _normalize_profile_description(value: Any) -> str | None:
    description = str(value or "").strip()
    if not description:
        return None
    return description[:160]


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


def _coerce_int(value: Any, fallback: int) -> int:
    if value is None:
        return int(fallback)
    try:
        return int(value)
    except Exception:
        return int(fallback)


def _snapshots_equal(profile: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    return _stable_json(profile.get("config") or {}) == _stable_json(snapshot.get("config") or {}) and _stable_json(
        profile.get("packaging") or {}
    ) == _stable_json(snapshot.get("packaging") or {})


def _diff_snapshot_keys(profile: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    profile_config = dict(profile.get("config") or {})
    current_config = dict(snapshot.get("config") or {})
    profile_packaging = dict(profile.get("packaging") or {})
    current_packaging = dict(snapshot.get("packaging") or {})

    diff_keys: list[str] = []
    for key in PROFILE_CONFIG_FIELDS:
        if _stable_value(profile_config.get(key)) != _stable_value(current_config.get(key)):
            diff_keys.append(key)

    packaging_order = list(DEFAULT_PACKAGING_CONFIG.keys())
    packaging_order.extend(
        key for key in sorted(set(profile_packaging) | set(current_packaging)) if key not in DEFAULT_PACKAGING_CONFIG
    )
    for key in packaging_order:
        if _stable_value(profile_packaging.get(key)) != _stable_value(current_packaging.get(key)):
            diff_keys.append(f"packaging.{key}")

    return diff_keys


def _build_dirty_details(profile: dict[str, Any], snapshot: dict[str, Any], diff_keys: list[str]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    profile_config = dict(profile.get("config") or {})
    current_config = dict(snapshot.get("config") or {})
    profile_packaging = dict(profile.get("packaging") or {})
    current_packaging = dict(snapshot.get("packaging") or {})

    for key in diff_keys:
        if key.startswith("packaging."):
            field = key.split(".", 1)[1]
            saved_value = deepcopy(profile_packaging.get(field))
            current_value = deepcopy(current_packaging.get(field))
        else:
            saved_value = deepcopy(profile_config.get(key))
            current_value = deepcopy(current_config.get(key))
        details.append(
            {
                "key": key,
                "saved_value": saved_value,
                "current_value": current_value,
            }
        )

    return details


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _stable_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


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


def _parse_profile_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return uuid.UUID(hex=str(value))


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _timestamp_to_str(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or _utcnow())


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
