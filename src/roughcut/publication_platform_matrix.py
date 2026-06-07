from __future__ import annotations

import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_MATRIX_PATH = Path(__file__).with_name("publication_platform_matrix.json")
_DEFAULT_PUBLICATION_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _current_publication_platform_now() -> datetime:
    return datetime.now(_DEFAULT_PUBLICATION_TIMEZONE)


def normalize_publication_platform_name(platform: str | None) -> str:
    return str(platform or "").strip().lower().replace("_", "-")


@lru_cache(maxsize=1)
def load_publication_platform_matrix() -> dict[str, Any]:
    return json.loads(_MATRIX_PATH.read_text(encoding="utf-8"))


def publication_platform_capabilities(platform: str | None) -> dict[str, Any]:
    key = normalize_publication_platform_name(platform)
    matrix = load_publication_platform_matrix()
    platforms = matrix.get("platforms") if isinstance(matrix.get("platforms"), dict) else {}
    entry = platforms.get(key) if isinstance(platforms.get(key), dict) else {}
    return dict(entry)


def platform_publish_scheme(platform: str | None) -> dict[str, Any]:
    raw_scheme = publication_platform_capabilities(platform).get("publish_scheme")
    return dict(raw_scheme) if isinstance(raw_scheme, dict) else {}


def publication_collection_policy_skip_values() -> set[str]:
    matrix = load_publication_platform_matrix()
    return {
        str(item).strip().lower()
        for item in (matrix.get("collection_policy_skip_values") or [])
        if str(item).strip()
    }


def publication_cover_policy_skip_values() -> set[str]:
    matrix = load_publication_platform_matrix()
    return {
        str(item).strip().lower()
        for item in (matrix.get("cover_policy_skip_values") or [])
        if str(item).strip()
    }


def platform_requires_explicit_collection_policy(platform: str | None) -> bool:
    return bool(publication_platform_capabilities(platform).get("requires_explicit_collection_policy"))


def platform_requires_custom_cover_policy(platform: str | None) -> bool:
    return bool(publication_platform_capabilities(platform).get("requires_custom_cover_policy"))


def platform_required_cover_slots(platform: str | None) -> list[dict[str, Any]]:
    raw_slots = publication_platform_capabilities(platform).get("required_cover_slots")
    if not isinstance(raw_slots, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw_slots:
        if not isinstance(item, dict):
            continue
        slot = str(item.get("slot") or item.get("key") or item.get("name") or "").strip()
        label = str(item.get("label") or "").strip()
        matrix_key = str(item.get("matrix_key") or item.get("group_key") or "").strip()
        target_size = item.get("target_size") if isinstance(item.get("target_size"), dict) else {}
        try:
            width = int(target_size.get("width") or target_size.get("w") or 0)
            height = int(target_size.get("height") or target_size.get("h") or 0)
        except (TypeError, ValueError):
            width = 0
            height = 0
        normalized_item: dict[str, Any] = {}
        if slot:
            normalized_item["slot"] = slot
        if label:
            normalized_item["label"] = label
        if matrix_key:
            normalized_item["matrix_key"] = matrix_key
        if width > 0 and height > 0:
            normalized_item["target_size"] = {"width": width, "height": height}
        if normalized_item:
            normalized.append(normalized_item)
    return normalized


def platform_default_declaration(platform: str | None) -> str:
    return str(publication_platform_capabilities(platform).get("default_declaration") or "").strip()


def platform_publish_entry_url(platform: str | None) -> str:
    return str(platform_publish_scheme(platform).get("entry_url") or "").strip()


def platform_draft_resume_policy(platform: str | None) -> str:
    return str(platform_publish_scheme(platform).get("draft_resume_policy") or "").strip()


def platform_cover_asset_policy(platform: str | None) -> str:
    return str(platform_publish_scheme(platform).get("cover_asset_policy") or "").strip()


def platform_allows_field_edits_while_processing(platform: str | None) -> bool:
    scheme = platform_publish_scheme(platform)
    if "allow_field_edits_while_processing" not in scheme:
        return False
    return bool(scheme.get("allow_field_edits_while_processing"))


def platform_stop_when_current_page_already_correct(platform: str | None) -> bool:
    scheme = platform_publish_scheme(platform)
    if "stop_when_current_page_already_correct" not in scheme:
        return False
    return bool(scheme.get("stop_when_current_page_already_correct"))


def platform_cover_project_mode(platform: str | None) -> str:
    return str(platform_publish_scheme(platform).get("cover_project_mode") or "").strip()


def platform_upload_processing_blocks_final_publish_only(platform: str | None) -> bool:
    scheme = platform_publish_scheme(platform)
    if "upload_processing_blocks_final_publish_only" not in scheme:
        return False
    return bool(scheme.get("upload_processing_blocks_final_publish_only"))


def platform_publish_projects(platform: str | None) -> list[dict[str, str]]:
    raw_projects = platform_publish_scheme(platform).get("projects")
    if not isinstance(raw_projects, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in raw_projects:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or "").strip()
        result_key = str(item.get("result_key") or "").strip()
        project: dict[str, str] = {}
        if key:
            project["key"] = key
        if label:
            project["label"] = label
        if result_key:
            project["result_key"] = result_key
        if project:
            normalized.append(project)
    return normalized


def platform_supports_scheduled_publish(platform: str | None) -> bool:
    capabilities = publication_platform_capabilities(platform)
    if "supports_scheduled_publish" not in capabilities:
        return False
    return bool(capabilities.get("supports_scheduled_publish"))


def platform_soft_verification_fields(platform: str | None) -> set[str]:
    capabilities = publication_platform_capabilities(platform)
    raw_fields = capabilities.get("soft_verification_fields")
    if not isinstance(raw_fields, list):
        return set()
    return {
        str(item).strip().lower()
        for item in raw_fields
        if str(item).strip()
    }


def platform_skips_explicit_tag_entry(platform: str | None) -> bool:
    return bool(publication_platform_capabilities(platform).get("skip_explicit_tag_entry"))


def platform_skips_explicit_visibility_entry(platform: str | None) -> bool:
    return bool(publication_platform_capabilities(platform).get("skip_explicit_visibility_entry"))


def platform_manual_handoff_only(platform: str | None) -> bool:
    return bool(publication_platform_capabilities(platform).get("manual_handoff_only"))


def platform_manual_publish_entry_url(platform: str | None) -> str:
    return str(publication_platform_capabilities(platform).get("manual_publish_entry_url") or "").strip()


def platform_manual_publish_reason(platform: str | None) -> str:
    return str(publication_platform_capabilities(platform).get("manual_publish_reason") or "").strip()


def platform_minimum_schedule_lead_minutes(platform: str | None) -> int:
    capabilities = publication_platform_capabilities(platform)
    raw_value = capabilities.get("minimum_schedule_lead_minutes")
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def _parse_platform_schedule_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace(" ", "T")
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_DEFAULT_PUBLICATION_TIMEZONE)
    return parsed.astimezone(_DEFAULT_PUBLICATION_TIMEZONE)


def evaluate_platform_schedule_window(
    platform: str | None,
    scheduled_publish_at: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    scheduled_text = str(scheduled_publish_at or "").strip()
    minimum_lead_minutes = platform_minimum_schedule_lead_minutes(platform)
    if not scheduled_text or not platform_supports_scheduled_publish(platform):
        return {
            "configured": bool(scheduled_text),
            "valid": True,
            "minimum_lead_minutes": minimum_lead_minutes,
            "scheduled_publish_at": scheduled_text,
        }
    scheduled_dt = _parse_platform_schedule_datetime(scheduled_text)
    if scheduled_dt is None:
        return {
            "configured": True,
            "valid": False,
            "minimum_lead_minutes": minimum_lead_minutes,
            "scheduled_publish_at": scheduled_text,
            "reason": "invalid_schedule_format",
        }
    now_local = (now or _current_publication_platform_now()).astimezone(_DEFAULT_PUBLICATION_TIMEZONE)
    minimum_ready_at = now_local + timedelta(minutes=minimum_lead_minutes)
    valid = scheduled_dt >= minimum_ready_at
    return {
        "configured": True,
        "valid": valid,
        "minimum_lead_minutes": minimum_lead_minutes,
        "scheduled_publish_at": scheduled_dt.isoformat(timespec="minutes"),
        "minimum_ready_at": minimum_ready_at.isoformat(timespec="minutes"),
        "reason": "" if valid else "schedule_too_soon",
    }


def suggest_platform_schedule_window_repair(
    platform: str | None,
    scheduled_publish_at: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    evaluation = evaluate_platform_schedule_window(platform, scheduled_publish_at, now=now)
    if evaluation.get("valid") or str(evaluation.get("reason") or "") != "schedule_too_soon":
        return {
            "repaired": False,
            "reason": str(evaluation.get("reason") or ""),
            "scheduled_publish_at": str(scheduled_publish_at or "").strip(),
            "minimum_ready_at": str(evaluation.get("minimum_ready_at") or "").strip(),
        }
    scheduled_dt = _parse_platform_schedule_datetime(scheduled_publish_at)
    if scheduled_dt is None:
        return {
            "repaired": False,
            "reason": "invalid_schedule_format",
            "scheduled_publish_at": str(scheduled_publish_at or "").strip(),
            "minimum_ready_at": str(evaluation.get("minimum_ready_at") or "").strip(),
        }
    now_local = (now or _current_publication_platform_now()).astimezone(_DEFAULT_PUBLICATION_TIMEZONE)
    minimum_ready_at = now_local + timedelta(minutes=platform_minimum_schedule_lead_minutes(platform))
    candidate = minimum_ready_at.replace(
        hour=scheduled_dt.hour,
        minute=scheduled_dt.minute,
        second=0,
        microsecond=0,
    )
    if candidate < minimum_ready_at:
        candidate = candidate + timedelta(days=1)
    return {
        "repaired": True,
        "reason": "schedule_too_soon",
        "scheduled_publish_at": candidate.strftime("%Y-%m-%dT%H:%M"),
        "minimum_ready_at": minimum_ready_at.isoformat(timespec="minutes"),
    }
