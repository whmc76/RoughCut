from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib import request

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from roughcut.publication_platform_matrix import (
    platform_required_cover_slots,
    platform_skips_explicit_visibility_entry,
)
from roughcut.publication import (
    build_publication_plan,
    _resolve_authoritative_publication_cover_contract,
)
from roughcut.publication_intelligence import generate_publication_scheme


TASK_CONTRACT = "browser_agent_publication_v1"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_platform_options(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_value, dict):
            continue
        key = str(raw_key or "").strip().lower().replace("_", "-")
        if key:
            normalized[key] = dict(raw_value)
    return normalized


def _normalize_tags(tags: Any) -> list[str]:
    if not isinstance(tags, list):
        return []
    normalized: list[str] = []
    for item in tags:
        text = str(item or "").strip()
        if text:
            normalized.append(text)
    return normalized


def _display_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for item in tags:
        text = str(item or "").strip()
        if not text:
            continue
        out.append(text if text.startswith("#") else f"#{text}")
    return out


def _normalize_publish_platform_options_payload(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_value, dict):
            continue
        key = str(raw_key or "").strip().lower().replace("_", "-")
        if key:
            normalized[key] = dict(raw_value)
    return normalized


def _creator_profile(profiles: Any, creator_profile_id: str) -> dict[str, Any]:
    if isinstance(profiles, dict):
        items = profiles.get("profiles") or []
    elif isinstance(profiles, list):
        items = profiles
    else:
        items = []
    for item in items:
        if str(item.get("id") or "").strip() == creator_profile_id:
            return item
    raise KeyError(f"creator profile not found: {creator_profile_id}")


def _platform_materials(material_json: dict[str, Any]) -> dict[str, dict[str, Any]]:
    materials: dict[str, dict[str, Any]] = {}
    raw_platforms = material_json.get("platforms")
    if isinstance(raw_platforms, dict):
        for raw_key, raw_value in raw_platforms.items():
            if not isinstance(raw_value, dict):
                continue
            key = str(raw_key or raw_value.get("key") or raw_value.get("platform") or "").strip().lower()
            if not key:
                continue
            materials[key] = dict(raw_value)
            materials[key].setdefault("key", key)
            materials[key].setdefault("platform", key)
        return materials
    for item in raw_platforms or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or item.get("platform") or "").strip().lower()
        if key:
            materials[key] = item
    return materials


def _credential_for_platform(creator_profile: dict[str, Any], platform: str) -> dict[str, Any]:
    publishing = creator_profile.get("creator_profile") or {}
    publishing = publishing.get("publishing") if isinstance(publishing, dict) else {}
    credentials = publishing.get("platform_credentials") if isinstance(publishing, dict) else []
    for item in credentials or []:
        if str(item.get("platform") or "").strip().lower() == platform:
            return item
    raise KeyError(f"platform credential not found for {platform}")


def _coerce_collection(material: dict[str, Any]) -> Any:
    collection = material.get("collection")
    if isinstance(collection, dict):
        name = str(collection.get("name") or collection.get("title") or collection.get("label") or "").strip()
        return {"name": name} if name else None
    if isinstance(collection, str):
        name = collection.strip()
        return {"name": name} if name else None
    collection_name = str(material.get("collection_name") or "").strip()
    if collection_name:
        return {"name": collection_name}
    collection_management = material.get("collection_management")
    if isinstance(collection_management, dict):
        managed_name = str(
            collection_management.get("selected_collection_name")
            or collection_management.get("target_collection_name")
            or collection_management.get("collection_name")
            or ""
        ).strip()
        if managed_name:
            return {"name": managed_name}
    platform_specific_overrides = material.get("platform_specific_overrides")
    if isinstance(platform_specific_overrides, dict):
        nested_collection_management = platform_specific_overrides.get("collection_management")
        if isinstance(nested_collection_management, dict):
            nested_name = str(
                nested_collection_management.get("selected_collection_name")
                or nested_collection_management.get("target_collection_name")
                or nested_collection_management.get("collection_name")
                or ""
            ).strip()
            if nested_name:
                return {"name": nested_name}
    return None


def _scheduled_publish_at(material: dict[str, Any]) -> str | None:
    value = material.get("scheduled_publish_at")
    text = str(value or "").strip()
    return text or None


def _cover_slots(material: dict[str, Any]) -> list[dict[str, Any]]:
    slots = material.get("cover_slots")
    if not isinstance(slots, list):
        copy_material = material.get("copy_material")
        if isinstance(copy_material, dict):
            slots = copy_material.get("cover_slots")
    if not isinstance(slots, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in slots:
        if isinstance(item, dict):
            normalized.append(dict(item))
    return normalized


def _cover_matrix(material_json: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = material_json.get("cover_matrix")
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        matrix_key = str(key or value.get("key") or "").strip()
        cover_path = str(value.get("cover_path") or "").strip()
        if not matrix_key or not cover_path:
            continue
        target_size: dict[str, int] | None = None
        cover_size = value.get("cover_size")
        if isinstance(cover_size, list) and len(cover_size) >= 2:
            try:
                width = int(cover_size[0] or 0)
                height = int(cover_size[1] or 0)
            except (TypeError, ValueError):
                width = 0
                height = 0
            if width > 0 and height > 0:
                target_size = {"width": width, "height": height}
        elif isinstance(cover_size, dict):
            try:
                width = int(cover_size.get("width") or cover_size.get("w") or 0)
                height = int(cover_size.get("height") or cover_size.get("h") or 0)
            except (TypeError, ValueError):
                width = 0
                height = 0
            if width > 0 and height > 0:
                target_size = {"width": width, "height": height}
        normalized[matrix_key] = {
            "key": matrix_key,
            "label": str(value.get("label") or "").strip(),
            "cover_path": cover_path,
            "target_size": target_size or {},
        }
    return normalized


def _load_cover_matrix_from_payload(payload: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    return _cover_matrix(payload)


def _recover_cover_matrix_from_media_path(requested_media_path: str) -> dict[str, dict[str, Any]]:
    media_path = Path(str(requested_media_path or "").strip())
    if not str(media_path):
        return {}
    candidate_dirs: list[Path] = []
    for candidate in (
        media_path.parent,
        media_path.parent.parent if media_path.parent != media_path else None,
        media_path.parent.parent.parent if media_path.parent.parent != media_path.parent else None,
    ):
        if isinstance(candidate, Path) and candidate not in candidate_dirs:
            candidate_dirs.append(candidate)
    candidate_files: list[Path] = []
    for directory in candidate_dirs:
        for name in ("platform-packaging.json", "smart-copy.json"):
            candidate = directory / name
            if candidate.exists() and candidate not in candidate_files:
                candidate_files.append(candidate)
    for candidate in candidate_files:
        try:
            payload = _load_json(candidate)
        except Exception:
            continue
        recovered = _load_cover_matrix_from_payload(payload)
        if recovered:
            return recovered
    return {}


def _resolved_cover_matrix(material_json: dict[str, Any], *, requested_media_path: str = "") -> dict[str, dict[str, Any]]:
    direct = _cover_matrix(material_json)
    if direct:
        return direct
    return _recover_cover_matrix_from_media_path(requested_media_path)


def _resolve_cover_slots_for_platform(
    *,
    platform: str,
    material: dict[str, Any],
    material_json: dict[str, Any],
    requested_media_path: str = "",
) -> list[dict[str, Any]]:
    explicit_slots = _cover_slots(material)
    required_specs = platform_required_cover_slots(platform)
    if not required_specs:
        return explicit_slots
    explicit_cover_path = str(
        material.get("cover_path")
        or (material.get("copy_material") or {}).get("cover_path")
        or ""
    ).strip()
    explicit_by_matrix = {
        str(item.get("matrix_key") or "").strip(): dict(item)
        for item in explicit_slots
        if str(item.get("matrix_key") or "").strip()
    }
    explicit_by_slot = {
        str(item.get("slot") or "").strip(): dict(item)
        for item in explicit_slots
        if str(item.get("slot") or "").strip()
    }
    matrix = _resolved_cover_matrix(material_json, requested_media_path=requested_media_path)
    resolved: list[dict[str, Any]] = []
    seen: set[str] = set()
    for spec in required_specs:
        matrix_key = str(spec.get("matrix_key") or "").strip()
        slot_key = str(spec.get("slot") or "").strip()
        existing = explicit_by_matrix.get(matrix_key) or explicit_by_slot.get(slot_key)
        matrix_entry = matrix.get(matrix_key) if matrix_key else None
        cover_path = str(
            (existing or {}).get("cover_path")
            or (explicit_cover_path if len(required_specs) == 1 else "")
            or (matrix_entry or {}).get("cover_path")
            or ""
        ).strip()
        if not cover_path:
            continue
        signature = json.dumps(
            {"slot": slot_key, "matrix_key": matrix_key, "cover_path": cover_path},
            ensure_ascii=False,
            sort_keys=True,
        )
        if signature in seen:
            continue
        seen.add(signature)
        payload = dict(existing or {})
        payload["slot"] = slot_key or str(payload.get("slot") or "").strip() or matrix_key or "primary"
        payload["label"] = str(spec.get("label") or payload.get("label") or (matrix_entry or {}).get("label") or "").strip()
        payload["matrix_key"] = matrix_key or str(payload.get("matrix_key") or "").strip()
        payload["cover_path"] = cover_path
        if isinstance(spec.get("target_size"), dict):
            payload["target_size"] = dict(spec["target_size"])
        elif isinstance((matrix_entry or {}).get("target_size"), dict):
            payload["target_size"] = dict(matrix_entry["target_size"])
        resolved.append(payload)
    if resolved:
        return resolved
    authoritative_cover_path, authoritative_cover_slots = _resolve_authoritative_publication_cover_contract(
        material,
        platform=platform,
        requested_media_path=requested_media_path,
    )
    if authoritative_cover_slots:
        return [dict(item) for item in authoritative_cover_slots if isinstance(item, dict)]
    if authoritative_cover_path:
        return [{
            "slot": str(required_specs[0].get("slot") or "primary").strip() or "primary",
            "label": str(required_specs[0].get("label") or "").strip(),
            "matrix_key": str(required_specs[0].get("matrix_key") or "").strip(),
            "target_size": dict(required_specs[0].get("target_size") or {}) if isinstance(required_specs[0].get("target_size"), dict) else {},
            "cover_path": str(authoritative_cover_path).strip(),
        }]
    return explicit_slots


def _content_for_platform(
    *,
    creator_profile: dict[str, Any],
    credential: dict[str, Any],
    platform: str,
    material: dict[str, Any],
    material_json: dict[str, Any],
    platform_options: dict[str, Any],
    media_path: str,
    current_page_only: bool,
) -> dict[str, Any]:
    title = str(material.get("primary_title") or "").strip()
    if not title:
        titles = material.get("titles")
        if isinstance(titles, list) and titles:
            title = str(titles[0] or "").strip()
    body = str(material.get("body") or material.get("description") or "").strip()
    tags = _normalize_tags(material.get("tags"))
    option_overrides = dict(platform_options.get("platform_specific_overrides") or {})
    material_overrides = dict(material.get("platform_specific_overrides") or {})
    platform_specific_overrides = {**option_overrides, **material_overrides}
    collection = _coerce_collection(material) or _coerce_collection(platform_options)
    scheduled_publish_at = _scheduled_publish_at(material) or _scheduled_publish_at(platform_options)
    visibility_or_publish_mode = (
        str(material.get("visibility_or_publish_mode") or "").strip()
        or str(platform_options.get("visibility_or_publish_mode") or "").strip()
    )
    if not visibility_or_publish_mode and not platform_skips_explicit_visibility_entry(platform):
        visibility_or_publish_mode = "public"
    cover_slots = _resolve_cover_slots_for_platform(
        platform=platform,
        material=material,
        material_json=material_json,
        requested_media_path=media_path,
    )
    cover_path = str(material.get("cover_path") or "").strip()
    if cover_slots:
        cover_path = str(cover_slots[0].get("cover_path") or cover_path).strip()
    content: dict[str, Any] = {
        "platform": platform,
        "title": title,
        "body": body,
        "content_kind": "video",
        "hashtags": tags,
        "display_hashtags": _display_tags(tags),
        "structured_tags": tags,
        "native_topics": [],
        "cover_path": cover_path,
        "cover_slots": cover_slots,
        "copy_material": dict(material.get("copy_material") or {}),
        "declaration": str(material.get("declaration") or platform_options.get("declaration") or "").strip(),
        "visibility_or_publish_mode": visibility_or_publish_mode,
        "media_items": [
            {
                "kind": "video",
                "local_path": media_path,
                "source_url": None,
                "uploaded_url": None,
                "mime_type": "video/mp4",
            }
        ],
        "publication_recovery_state": {
            "schema_version": 1,
            "recovery_overrides": {
                "prepare_only_current_page": bool(current_page_only),
                "force_publish_page_refresh": False if current_page_only else True,
                "clear_draft_context": False,
                "verify_media_upload": False,
                "wait_for_publish_confirmation": False,
                "recovery_mode": "prepublish_resume" if current_page_only else "prepare_only",
            },
        },
        "metadata": {
            "platform": platform,
            "creator_profile_id": str(creator_profile.get("id") or "").strip(),
            "creator_profile_name": str(creator_profile.get("name") or "").strip(),
            "credential_ref": str(credential.get("credential_ref") or "").strip(),
            "account_label": str(credential.get("account_label") or "").strip(),
            "browser_profile_id": str(credential.get("browser_profile_id") or "").strip(),
            "browser_binding": dict(credential.get("browser_binding") or {}),
            "session_binding": {
                "platform": platform,
                "browser_profile_id": str(credential.get("browser_profile_id") or "").strip(),
                "credential_ref": str(credential.get("credential_ref") or "").strip(),
                "account_label": str(credential.get("account_label") or "").strip(),
                "creator_profile_id": str(creator_profile.get("id") or "").strip(),
                "browser_binding": dict(credential.get("browser_binding") or {}),
            },
        },
    }
    if collection:
        content["collection"] = collection
    if scheduled_publish_at:
        content["scheduled_publish_at"] = scheduled_publish_at
    if platform_specific_overrides:
        content["platform_specific_overrides"] = platform_specific_overrides
    return content


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str) -> dict[str, Any]:
    with request.urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


@dataclass
class TaskResult:
    platform: str
    task_id: str
    task: dict[str, Any]


def _submit_prepare_only_task(
    *,
    browser_agent_base_url: str,
    creator_profile: dict[str, Any],
    credential: dict[str, Any],
    platform: str,
    material: dict[str, Any],
    material_json: dict[str, Any],
    platform_options: dict[str, Any],
    media_path: str,
    current_page_only: bool,
) -> TaskResult:
    task_id = f"{platform}-prepare-only-{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    payload = {
        "contract": TASK_CONTRACT,
        "task_id": task_id,
        "platform": platform,
        "profile_id": str(creator_profile.get("id") or "").strip(),
        "session_binding": {
            "platform": platform,
            "browser_profile_id": str(credential.get("browser_profile_id") or "").strip(),
            "credential_ref": str(credential.get("credential_ref") or "").strip(),
            "account_label": str(credential.get("account_label") or "").strip(),
            "creator_profile_id": str(creator_profile.get("id") or "").strip(),
            "browser_binding": dict(credential.get("browser_binding") or {}),
        },
        "content": _content_for_platform(
            creator_profile=creator_profile,
            credential=credential,
            platform=platform,
            material=material,
            material_json=material_json,
            platform_options=platform_options,
            media_path=media_path,
            current_page_only=current_page_only,
        ),
    }
    started = _post_json(f"{browser_agent_base_url.rstrip('/')}/tasks", payload)
    return TaskResult(platform=platform, task_id=task_id, task=started.get("task") or {})


def _poll_task(browser_agent_base_url: str, task_id: str, timeout_seconds: int, poll_interval: int) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last: dict[str, Any] = {}
    while time.time() < deadline:
        payload = _get_json(f"{browser_agent_base_url.rstrip('/')}/tasks/{task_id}")
        task = payload.get("task") or {}
        last = task
        status = str(task.get("status") or "").strip().lower()
        if status and status not in {"queued", "processing", "submitted"}:
            return payload
        time.sleep(poll_interval)
    return {"task": last, "timeout": True}


def _write_output(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def _resolve_scheme_platform_options(
    *,
    media_path: str,
    material_json: dict[str, Any],
    creator_profile: dict[str, Any],
    requested_platforms: list[str],
    folder_path: str,
) -> dict[str, dict[str, Any]]:
    platform_packaging = material_json if isinstance(material_json, dict) else {}
    base_plan = build_publication_plan(
        job=SimpleNamespace(status="done"),
        render_output=SimpleNamespace(output_path=str(media_path or "").strip()),
        source_media_path=str(media_path or "").strip() or None,
        platform_packaging=platform_packaging,
        creator_profile=creator_profile,
        requested_platforms=requested_platforms,
        platform_options=None,
        existing_attempts=[],
    )
    if not list(base_plan.get("targets") or []):
        return {}
    scheme = await generate_publication_scheme(
        plan=base_plan,
        creator_profile=creator_profile,
        folder_path=str(folder_path or ""),
        browser="chrome",
        force_probe=False,
    )
    return _normalize_publish_platform_options_payload(scheme.get("platform_options"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run browser-agent prepare-only publication tasks from current material.")
    parser.add_argument("--target-profile-id", required=True)
    parser.add_argument("--material-json", required=True)
    parser.add_argument("--profiles-json", default="data/avatar_materials/profiles.json")
    parser.add_argument("--browser-agent-base-url", default="http://127.0.0.1:49310")
    parser.add_argument("--media-path", required=True, help="Use the real source video path.")
    parser.add_argument("--publication-scheme-json", help="Optional publication scheme JSON; inject scheme platform_options into content.")
    parser.add_argument("--platform-options-json", help="Optional raw platform_options JSON file; overrides scheme options.")
    parser.add_argument("--platform", action="append", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=360)
    parser.add_argument("--poll-interval", type=int, default=5)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--current-page-only",
        action="store_true",
        help="Resume from the already-open publish editor surface instead of re-entering from the platform publish route.",
    )
    args = parser.parse_args()

    material_json = _load_json(Path(args.material_json))
    profiles_json = _load_json(Path(args.profiles_json))
    scheme_platform_options: dict[str, dict[str, Any]] = {}
    if args.publication_scheme_json:
        scheme_payload = _load_json(Path(args.publication_scheme_json))
        scheme_platform_options = _normalize_platform_options(scheme_payload.get("platform_options"))
    raw_platform_options: dict[str, dict[str, Any]] = {}
    if args.platform_options_json:
        raw_platform_options = _normalize_platform_options(_load_json(Path(args.platform_options_json)))
    creator_profile = _creator_profile(profiles_json, args.target_profile_id)
    requested_platforms = [str(platform or "").strip().lower() for platform in args.platform if str(platform or "").strip()]
    auto_scheme_platform_options: dict[str, dict[str, Any]] = {}
    if not args.publication_scheme_json and not args.platform_options_json:
        auto_scheme_platform_options = asyncio.run(
            _resolve_scheme_platform_options(
                media_path=args.media_path,
                material_json=material_json,
                creator_profile=creator_profile,
                requested_platforms=requested_platforms,
                folder_path=str(Path(args.material_json).resolve().parent),
            )
        )
    merged_platform_options = {**auto_scheme_platform_options, **scheme_platform_options, **raw_platform_options}
    platform_materials = _platform_materials(material_json)
    output_path = Path(args.output)
    output: dict[str, Any] = {
        "creator_profile_id": args.target_profile_id,
        "media_path": args.media_path,
        "browser_agent_base_url": args.browser_agent_base_url,
        "platforms": {},
    }

    for platform in args.platform:
        normalized_platform = str(platform or "").strip().lower()
        material = platform_materials.get(normalized_platform)
        if not material:
            output["platforms"][normalized_platform] = {
                "status": "missing_material",
                "error": f"platform material not found: {normalized_platform}",
            }
            continue
        credential = _credential_for_platform(creator_profile, normalized_platform)
        platform_options = merged_platform_options.get(normalized_platform, {})
        content = _content_for_platform(
            creator_profile=creator_profile,
            credential=credential,
            platform=normalized_platform,
            material=material,
            material_json=material_json,
            platform_options=platform_options,
            media_path=args.media_path,
            current_page_only=args.current_page_only,
        )
        if args.dry_run:
            output["platforms"][normalized_platform] = {
                "status": "dry_run",
                "content": content,
            }
            _write_output(output_path, output)
            continue
        started = _submit_prepare_only_task(
            browser_agent_base_url=args.browser_agent_base_url,
            creator_profile=creator_profile,
            credential=credential,
            platform=normalized_platform,
            material=material,
            material_json=material_json,
            platform_options=platform_options,
            media_path=args.media_path,
            current_page_only=args.current_page_only,
        )
        output["platforms"][normalized_platform] = {
            "status": "started",
            "task_id": started.task_id,
            "task": started.task,
        }
        _write_output(output_path, output)
        print(f"{normalized_platform}: {started.task_id}", file=sys.stderr)
        result = _poll_task(args.browser_agent_base_url, started.task_id, args.timeout_seconds, args.poll_interval)
        output["platforms"][normalized_platform] = result
        _write_output(output_path, output)
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
