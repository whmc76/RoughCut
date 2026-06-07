from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from roughcut.db.models import PublicationAttempt
from roughcut.publication_intelligence import build_cached_publication_scheme
from roughcut.publication import build_publication_browser_profile_id, normalize_publication_browser_binding
from roughcut.publication_packaging import (
    normalize_publication_packaging_payload,
    publication_packaging_entry_publish_ready,
)
from roughcut.publication import (
    CANONICAL_PUBLICATION_ADAPTER,
    _build_request_payload,
    build_browser_agent_task_payload_from_attempt,
    build_publication_plan,
)


def _normalize_platform(value: Any) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _coerce_platform_collection(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        name = str(value.get("name") or value.get("title") or value.get("label") or "").strip()
        return {"name": name} if name else None
    text = str(value or "").strip()
    return {"name": text} if text else None


def _normalize_tags(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := str(item or "").strip())]


def _load_creator_profile(profiles_payload: Any, creator_profile_id: str) -> dict[str, Any]:
    if isinstance(profiles_payload, dict):
        items = profiles_payload.get("profiles") or []
    elif isinstance(profiles_payload, list):
        items = profiles_payload
    else:
        items = []
    for item in items:
        if str((item or {}).get("id") or "").strip() == creator_profile_id:
            return dict(item)
    raise KeyError(f"creator profile not found: {creator_profile_id}")


def _apply_browser_binding_override(
    *,
    creator_profile: dict[str, Any],
    platform: str,
    creator_profile_id: str,
    browser_binding_override: dict[str, Any] | None,
    account_label_override: str | None = None,
    credential_ref_override: str | None = None,
) -> dict[str, Any]:
    if not browser_binding_override and not account_label_override and not credential_ref_override:
        return creator_profile
    publishing = (
        dict(creator_profile.get("creator_profile", {}).get("publishing"))
        if isinstance(creator_profile.get("creator_profile", {}).get("publishing"), dict)
        else {}
    )
    platform_credentials = [
        dict(item) for item in (publishing.get("platform_credentials") or []) if isinstance(item, dict)
    ]
    if not platform_credentials:
        return creator_profile
    normalized_platform = _normalize_platform(platform)
    normalized_binding = normalize_publication_browser_binding(browser_binding_override or {})
    if normalized_binding and not normalized_binding.get("profile_id"):
        normalized_binding["profile_id"] = build_publication_browser_profile_id(
            browser=normalized_binding.get("browser"),
            user_data_dir=normalized_binding.get("user_data_dir"),
            profile_directory=normalized_binding.get("profile_directory"),
        )
    updated_credentials: list[dict[str, Any]] = []
    for credential in platform_credentials:
        if _normalize_platform(credential.get("platform")) != normalized_platform:
            updated_credentials.append(credential)
            continue
        updated = dict(credential)
        if normalized_binding:
            updated["browser_binding"] = dict(normalized_binding)
            if normalized_binding.get("profile_id"):
                updated["browser_profile_id"] = str(normalized_binding.get("profile_id"))
        browser_name = str((normalized_binding or {}).get("browser") or "browser-agent").strip()
        if credential_ref_override:
            updated["credential_ref"] = credential_ref_override
        elif normalized_binding:
            updated["credential_ref"] = f"browser-agent:{browser_name}:{creator_profile_id}:{normalized_platform}"
        if account_label_override:
            updated["account_label"] = account_label_override
        elif normalized_binding:
            browser_label = browser_name.capitalize() if browser_name else "Browser"
            display_name = str(creator_profile.get("display_name") or creator_profile.get("name") or "").strip() or "Creator"
            updated["account_label"] = f"{display_name} · {browser_label}"
        updated_credentials.append(updated)
    publishing["platform_credentials"] = updated_credentials
    creator_profile_payload = (
        dict(creator_profile.get("creator_profile"))
        if isinstance(creator_profile.get("creator_profile"), dict)
        else {}
    )
    creator_profile_payload["publishing"] = publishing
    updated_creator = dict(creator_profile)
    updated_creator["creator_profile"] = creator_profile_payload
    return updated_creator


def _load_platform_packaging_entry(platform_packaging: dict[str, Any], platform: str) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    normalized_packaging = normalize_publication_packaging_payload(
        dict(platform_packaging) if isinstance(platform_packaging, dict) else {},
    ) or {}
    platforms = normalized_packaging.get("platforms") if isinstance(normalized_packaging.get("platforms"), dict) else {}
    entry = platforms.get(normalized_platform)
    if not isinstance(entry, dict):
        raise KeyError(f"platform packaging not found for {normalized_platform}")
    return dict(entry)


def _build_mainline_platform_packaging(
    *,
    platform_packaging: dict[str, Any],
    platform: str,
    platform_packaging_entry: dict[str, Any],
    title_override: str | None = None,
    body_override: str | None = None,
) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    packaging_payload = dict(platform_packaging) if isinstance(platform_packaging, dict) else {}
    platforms = (
        dict(packaging_payload.get("platforms"))
        if isinstance(packaging_payload.get("platforms"), dict)
        else {}
    )
    mainline_entry = dict(platform_packaging_entry)
    if title_override:
        mainline_entry["titles"] = [title_override]
        copy_material = dict(mainline_entry.get("copy_material")) if isinstance(mainline_entry.get("copy_material"), dict) else {}
        copy_material["primary_title"] = title_override
        existing_titles = copy_material.get("titles")
        if isinstance(existing_titles, list):
            copy_material["titles"] = [title_override, *[str(item) for item in existing_titles if str(item) != title_override]]
        else:
            copy_material["titles"] = [title_override]
        mainline_entry["copy_material"] = copy_material
    if body_override:
        mainline_entry["description"] = body_override
        copy_material = dict(mainline_entry.get("copy_material")) if isinstance(mainline_entry.get("copy_material"), dict) else {}
        copy_material["body"] = body_override
        mainline_entry["copy_material"] = copy_material
    # Mainline executors should derive readiness from concrete required fields for the target
    # platform instead of trusting a stale exported publish_ready flag from the unified pipeline.
    mainline_entry["publish_ready"] = publication_packaging_entry_publish_ready(
        mainline_entry,
        trust_explicit_flag=False,
    )
    platforms = {normalized_platform: mainline_entry}
    packaging_payload["platforms"] = platforms
    return normalize_publication_packaging_payload(packaging_payload) or packaging_payload


def _build_mainline_platform_options(
    *,
    platform_packaging_entry: dict[str, Any],
    current_page_only: bool,
    stop_before_final_publish: bool,
    collection_override: Any = None,
    scheduled_publish_at_override: str | None = None,
    derived_platform_option: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    platform = _normalize_platform(platform_packaging_entry.get("platform") or platform_packaging_entry.get("key"))
    derived_option = dict(derived_platform_option) if isinstance(derived_platform_option, dict) else {}
    overrides = (
        dict(platform_packaging_entry.get("platform_specific_overrides"))
        if isinstance(platform_packaging_entry.get("platform_specific_overrides"), dict)
        else {}
    )
    derived_overrides = (
        dict(derived_option.get("platform_specific_overrides"))
        if isinstance(derived_option.get("platform_specific_overrides"), dict)
        else {}
    )
    if derived_overrides:
        merged_overrides = dict(derived_overrides)
        merged_overrides.update(overrides)
        overrides = merged_overrides
    if current_page_only:
        overrides["prepare_only_current_page"] = True
        overrides.setdefault("recovery_mode", "prepublish_resume")
    if stop_before_final_publish:
        overrides["stop_before_final_publish"] = True

    options: dict[str, Any] = {
        "platform_specific_overrides": overrides,
    }
    if category := str(platform_packaging_entry.get("category") or derived_option.get("category") or "").strip():
        options["category"] = category
    if declaration := str(platform_packaging_entry.get("declaration") or "").strip():
        options["declaration"] = declaration
    if visibility := str(
        platform_packaging_entry.get("visibility_or_publish_mode")
        or derived_option.get("visibility_or_publish_mode")
        or ""
    ).strip():
        options["visibility_or_publish_mode"] = visibility
    scheduled_publish_at = str(scheduled_publish_at_override or "").strip()
    if not scheduled_publish_at:
        scheduled_publish_at = str(
            platform_packaging_entry.get("scheduled_publish_at")
            or derived_option.get("scheduled_publish_at")
            or ""
        ).strip()
    if scheduled_publish_at:
        options["scheduled_publish_at"] = scheduled_publish_at
    collection = _coerce_platform_collection(collection_override)
    if collection is None:
        collection = _coerce_platform_collection(
            platform_packaging_entry.get("collection")
            or platform_packaging_entry.get("collection_name")
            or derived_option.get("collection")
            or derived_option.get("collection_name")
        )
    if collection:
        options["collection"] = collection
    return {platform: options}


def _mainline_requires_derived_platform_option(platform_packaging_entry: dict[str, Any]) -> bool:
    collection = _coerce_platform_collection(
        platform_packaging_entry.get("collection") or platform_packaging_entry.get("collection_name")
    )
    has_schedule = bool(str(platform_packaging_entry.get("scheduled_publish_at") or "").strip())
    has_category = bool(str(platform_packaging_entry.get("category") or "").strip())
    return not (collection and has_schedule and has_category)


async def _derive_mainline_platform_option_async(
    *,
    creator_profile: dict[str, Any],
    platform_packaging: dict[str, Any],
    platform: str,
    media_path: str,
) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    packaging_entry = _load_platform_packaging_entry(platform_packaging, normalized_platform)
    titles = [text for item in (packaging_entry.get("titles") or []) if (text := str(item or "").strip())]
    title = str(packaging_entry.get("primary_title") or packaging_entry.get("title") or (titles[0] if titles else "")).strip()
    tags = [text.lstrip("#") for item in (packaging_entry.get("tags") or []) if (text := str(item or "").strip())]
    target = {
        "platform": normalized_platform,
        "title": title,
        "titles": titles,
        "body": str(packaging_entry.get("body") or packaging_entry.get("description") or "").strip(),
        "tags": tags,
        "cover_path": str(packaging_entry.get("cover_path") or "").strip(),
        "full_copy": str(packaging_entry.get("full_copy") or "").strip(),
        "copy_material": dict(packaging_entry.get("copy_material") or {}) if isinstance(packaging_entry.get("copy_material"), dict) else {},
    }
    if not title and not target["body"] and not tags:
        return {}
    folder_path = str(Path(media_path).resolve().parent)
    scheme = build_cached_publication_scheme(
        creator_profile_id=str(creator_profile.get("id") or "").strip(),
        creator_profile_name=str(creator_profile.get("display_name") or creator_profile.get("name") or "").strip(),
        folder_path=folder_path,
        browser="chrome",
        targets=[target],
    )
    platform_options = scheme.get("platform_options") if isinstance(scheme.get("platform_options"), dict) else {}
    option = platform_options.get(normalized_platform)
    return dict(option) if isinstance(option, dict) else {}


def _derive_mainline_platform_option(
    *,
    creator_profile: dict[str, Any],
    platform_packaging: dict[str, Any],
    platform: str,
    media_path: str,
) -> dict[str, Any]:
    return asyncio.run(
        _derive_mainline_platform_option_async(
            creator_profile=creator_profile,
            platform_packaging=platform_packaging,
            platform=platform,
            media_path=media_path,
        )
    )


def build_platform_mainline_browser_agent_task(
    *,
    creator_profile_id: str,
    profiles_payload: Any,
    platform_packaging: dict[str, Any],
    platform: str,
    media_path: str,
    current_page_only: bool = False,
    stop_before_final_publish: bool = False,
    collection_override: Any = None,
    scheduled_publish_at_override: str | None = None,
    title_override: str | None = None,
    body_override: str | None = None,
    browser_binding_override: dict[str, Any] | None = None,
    account_label_override: str | None = None,
    credential_ref_override: str | None = None,
) -> dict[str, Any]:
    normalized_platform = _normalize_platform(platform)
    creator_profile = _load_creator_profile(profiles_payload, creator_profile_id)
    creator_profile = _apply_browser_binding_override(
        creator_profile=creator_profile,
        platform=normalized_platform,
        creator_profile_id=creator_profile_id,
        browser_binding_override=browser_binding_override,
        account_label_override=account_label_override,
        credential_ref_override=credential_ref_override,
    )
    packaging_entry = _load_platform_packaging_entry(platform_packaging, normalized_platform)
    packaging_entry.setdefault("key", normalized_platform)
    packaging_entry.setdefault("platform", normalized_platform)

    requested_media_path = str(media_path or "").strip()
    if not requested_media_path:
        raise ValueError("media_path is required")

    derived_platform_option: dict[str, Any] = {}
    if _mainline_requires_derived_platform_option(packaging_entry):
        derived_platform_option = _derive_mainline_platform_option(
            creator_profile=creator_profile,
            platform_packaging=platform_packaging,
            platform=normalized_platform,
            media_path=requested_media_path,
        )
    platform_options = _build_mainline_platform_options(
        platform_packaging_entry=packaging_entry,
        current_page_only=current_page_only,
        stop_before_final_publish=stop_before_final_publish,
        collection_override=collection_override,
        scheduled_publish_at_override=scheduled_publish_at_override,
        derived_platform_option=derived_platform_option,
    )
    mainline_platform_packaging = _build_mainline_platform_packaging(
        platform_packaging=platform_packaging,
        platform=normalized_platform,
        platform_packaging_entry=packaging_entry,
        title_override=str(title_override or "").strip() or None,
        body_override=str(body_override or "").strip() or None,
    )
    plan = build_publication_plan(
        job=SimpleNamespace(id=str(uuid.uuid4()), status="done"),
        render_output=SimpleNamespace(output_path=requested_media_path),
        source_media_path=requested_media_path,
        platform_packaging=mainline_platform_packaging,
        creator_profile=creator_profile,
        requested_platforms=[normalized_platform],
        platform_options=platform_options,
        existing_attempts=[],
    )
    targets = [item for item in (plan.get("targets") or []) if isinstance(item, dict)]
    if not targets:
        blocked = "; ".join(str(item).strip() for item in (plan.get("blocked_reasons") or []) if str(item).strip())
        raise ValueError(blocked or f"platform plan not buildable: {normalized_platform}")

    target = dict(targets[0])
    request_payload = _build_request_payload(plan=plan, target=target)
    attempt = PublicationAttempt(
        id=f"{normalized_platform}-mainline-{uuid.uuid4().hex[:12]}",
        job_id=uuid.uuid4(),
        content_id=str(plan.get("job_id") or ""),
        platform=normalized_platform,
        platform_label=str(target.get("platform_label") or normalized_platform),
        idempotency_key=f"mainline:{normalized_platform}:{uuid.uuid4().hex}",
        semantic_fingerprint=f"mainline:{normalized_platform}:{uuid.uuid4().hex}",
        adapter=str(target.get("adapter") or CANONICAL_PUBLICATION_ADAPTER),
        status="queued",
        request_payload=request_payload,
    )
    return build_browser_agent_task_payload_from_attempt(attempt)


def default_profiles_json_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "avatar_materials" / "profiles.json"
