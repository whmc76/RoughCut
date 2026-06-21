from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roughcut.intelligent_copy_layout import (
    resolve_smart_copy_material_json_path,
    resolve_smart_copy_platform_packaging_json_path,
    smart_copy_material_root,
)
from roughcut.publication_platform_matrix import (
    publication_collection_policy_skip_values,
    normalize_publication_platform_name,
    platform_requires_explicit_collection_policy,
    platform_required_cover_slots,
    platform_manual_handoff_only,
    platform_manual_publish_entry_url,
)


def normalize_publication_packaging_platform_key(value: Any) -> str:
    return normalize_publication_platform_name(str(value or "").strip())


def resolve_publication_packaging_input_paths(
    *,
    material_json: str = "",
    platform_packaging: str = "",
) -> tuple[Path | None, Path | None]:
    material_json_path = Path(str(material_json or "").strip()) if str(material_json or "").strip() else None
    if material_json_path and not material_json_path.is_file():
        nested = resolve_smart_copy_material_json_path(smart_copy_material_root(material_json_path))
        material_json_path = nested if nested.is_file() else None

    packaging_path = Path(str(platform_packaging or "").strip()) if str(platform_packaging or "").strip() else None
    if packaging_path and not packaging_path.is_file():
        nested = resolve_smart_copy_platform_packaging_json_path(smart_copy_material_root(packaging_path))
        packaging_path = nested if nested.is_file() else None

    if packaging_path is None and material_json_path is not None:
        sibling = resolve_smart_copy_platform_packaging_json_path(smart_copy_material_root(material_json_path))
        if sibling.is_file():
            packaging_path = sibling
    if material_json_path is None and packaging_path is not None:
        sibling = resolve_smart_copy_material_json_path(smart_copy_material_root(packaging_path))
        if sibling.is_file():
            material_json_path = sibling
        else:
            nested = packaging_path.parent / "smart-copy" / "smart-copy.json"
            if nested.is_file():
                material_json_path = nested
    return material_json_path, packaging_path


def load_json_payload(path: Path | None) -> Any:
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normalize_requested_publication_packaging_platforms(platforms: list[str] | None = None) -> list[str]:
    normalized: list[str] = []
    for item in (platforms or []):
        platform = normalize_publication_packaging_platform_key(item)
        if platform and platform not in normalized:
            normalized.append(platform)
    return normalized


def _normalize_cover_size(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        width = int(value.get("width") or value.get("w") or 0)
        height = int(value.get("height") or value.get("h") or 0)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return {"width": width, "height": height}


def _normalize_cover_slot_entry(value: Any, *, index: int = 0) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    slot = (
        str(value.get("slot") or value.get("key") or value.get("name") or value.get("slot_key") or "").strip()
        or f"slot_{index + 1}"
    )
    cover_path = str(
        value.get("cover_path")
        or value.get("path")
        or value.get("output_path")
        or value.get("file")
        or ""
    ).strip()
    target_size = _normalize_cover_size(
        value.get("target_size")
        or value.get("cover_size")
        or value.get("size")
    )
    label = str(value.get("label") or value.get("title") or "").strip()
    source = str(value.get("source") or "").strip()
    matrix_key = str(
        value.get("matrix_key")
        or value.get("group_key")
        or value.get("cover_group_key")
        or ""
    ).strip()
    members = [
        normalize_publication_packaging_platform_key(item)
        for item in (value.get("members") or value.get("platforms") or [])
        if normalize_publication_packaging_platform_key(item)
    ]
    upload_required = value.get("upload_required")
    optional = value.get("optional")
    normalized: dict[str, Any] = {"slot": slot}
    if cover_path:
        normalized["cover_path"] = cover_path
    if label:
        normalized["label"] = label
    if source:
        normalized["source"] = source
    if target_size:
        normalized["target_size"] = target_size
    if matrix_key:
        normalized["matrix_key"] = matrix_key
    if members:
        normalized["members"] = members
    if isinstance(upload_required, bool):
        normalized["upload_required"] = upload_required
    if isinstance(optional, bool):
        normalized["optional"] = optional
    if len(normalized) == 1 and "cover_path" not in normalized and "target_size" not in normalized:
        return None
    return normalized


def normalize_publication_cover_slots(
    raw_slots: Any,
    *,
    cover_path: str = "",
    target_size: dict[str, Any] | None = None,
    slot: str = "primary",
    label: str = "",
    source: str = "",
    matrix_key: str = "",
    members: list[str] | None = None,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_slots if isinstance(raw_slots, list) else []):
        slot_entry = _normalize_cover_slot_entry(item, index=index)
        if not slot_entry:
            continue
        signature = json.dumps(slot_entry, ensure_ascii=False, sort_keys=True)
        if signature in seen:
            continue
        seen.add(signature)
        normalized.append(slot_entry)
    fallback_size = _normalize_cover_size(target_size)
    fallback_cover_path = str(cover_path or "").strip()
    if not normalized and (fallback_cover_path or fallback_size):
        fallback_slot: dict[str, Any] = {"slot": str(slot or "primary").strip() or "primary"}
        if fallback_cover_path:
            fallback_slot["cover_path"] = fallback_cover_path
        if fallback_size:
            fallback_slot["target_size"] = fallback_size
        if label:
            fallback_slot["label"] = str(label).strip()
        if source:
            fallback_slot["source"] = str(source).strip()
        if matrix_key:
            fallback_slot["matrix_key"] = str(matrix_key).strip()
        normalized_members = [
            normalize_publication_packaging_platform_key(item)
            for item in (members or [])
            if normalize_publication_packaging_platform_key(item)
        ]
        if normalized_members:
            fallback_slot["members"] = normalized_members
        normalized.append(fallback_slot)
    return normalized


def _normalize_cover_matrix_slot_entry(matrix_key: str, value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    cover_path = str(
        value.get("cover_path")
        or value.get("path")
        or value.get("output_path")
        or value.get("file")
        or ""
    ).strip()
    cover_size = value.get("target_size")
    if not isinstance(cover_size, dict):
        raw_size = value.get("cover_size")
        if isinstance(raw_size, (list, tuple)) and len(raw_size) >= 2:
            cover_size = {"width": raw_size[0], "height": raw_size[1]}
        else:
            cover_size = raw_size
    target_size = _normalize_cover_size(cover_size)
    if not cover_path and not target_size:
        return None
    normalized: dict[str, Any] = {"slot": str(matrix_key or "").strip() or "primary"}
    if cover_path:
        normalized["cover_path"] = cover_path
    if target_size:
        normalized["target_size"] = target_size
    label = str(value.get("label") or "").strip()
    if label:
        normalized["label"] = label
    matrix_key_value = str(matrix_key or value.get("matrix_key") or value.get("group_key") or "").strip()
    if matrix_key_value:
        normalized["matrix_key"] = matrix_key_value
    members = [
        normalize_publication_packaging_platform_key(item)
        for item in (value.get("members") or value.get("platforms") or [])
        if normalize_publication_packaging_platform_key(item)
    ]
    if members:
        normalized["members"] = members
    return normalized


def _project_required_cover_slots_from_cover_matrix(
    *,
    platform: str,
    explicit_slots: list[dict[str, Any]],
    cover_matrix: dict[str, Any],
    cover_path: str,
    target_size: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    required_specs = platform_required_cover_slots(platform)
    if not required_specs:
        return explicit_slots

    explicit_by_slot: dict[str, dict[str, Any]] = {}
    explicit_by_matrix_key: dict[str, dict[str, Any]] = {}
    for item in explicit_slots:
        slot_key = str(item.get("slot") or "").strip()
        matrix_key = str(item.get("matrix_key") or "").strip()
        if slot_key:
            explicit_by_slot.setdefault(slot_key, item)
        if matrix_key:
            explicit_by_matrix_key.setdefault(matrix_key, item)

    has_explicit_required_mapping = any(
        str(spec.get("slot") or "").strip() in explicit_by_slot
        or str(spec.get("matrix_key") or "").strip() in explicit_by_matrix_key
        for spec in required_specs
    )
    if explicit_slots and not cover_matrix and not has_explicit_required_mapping:
        return explicit_slots

    projected: list[dict[str, Any]] = []
    for index, spec in enumerate(required_specs):
        slot_key = str(spec.get("slot") or "").strip()
        matrix_key = str(spec.get("matrix_key") or "").strip()
        source_slot = explicit_by_slot.get(slot_key) or explicit_by_matrix_key.get(matrix_key)
        matrix_slot = _normalize_cover_matrix_slot_entry(matrix_key, cover_matrix.get(matrix_key)) if matrix_key else None
        if source_slot is not None and matrix_slot is not None:
            merged_slot = dict(source_slot)
            merged_slot.update(
                {
                    key: value
                    for key, value in matrix_slot.items()
                    if str(value or "").strip() and key in {"cover_path", "target_size", "label", "matrix_key"}
                }
            )
            source_slot = merged_slot
        if source_slot is None and matrix_key:
            source_slot = matrix_slot
        if source_slot is None and len(required_specs) == 1 and (cover_path or target_size):
            source_slot = {}
        if source_slot is None:
            continue
        normalized_slot: dict[str, Any] = {
            "slot": slot_key or str(source_slot.get("slot") or "").strip() or f"slot_{index + 1}",
        }
        matrix_cover_path = str(matrix_slot.get("cover_path") or "").strip() if matrix_slot is not None else ""
        single_slot_primary_cover = (
            str(cover_path or "").strip()
            if len(required_specs) == 1 and not matrix_cover_path
            else ""
        )
        resolved_cover_path = str(
            matrix_cover_path or single_slot_primary_cover or source_slot.get("cover_path") or cover_path or ""
        ).strip()
        if resolved_cover_path:
            normalized_slot["cover_path"] = resolved_cover_path
        resolved_target_size = _normalize_cover_size(source_slot.get("target_size")) or target_size
        if resolved_target_size:
            normalized_slot["target_size"] = resolved_target_size
        label = str(spec.get("label") or source_slot.get("label") or "").strip()
        if label:
            normalized_slot["label"] = label
        matrix_key_value = matrix_key or str(source_slot.get("matrix_key") or "").strip()
        if matrix_key_value:
            normalized_slot["matrix_key"] = matrix_key_value
        members = [
            normalize_publication_packaging_platform_key(item)
            for item in (source_slot.get("members") or [])
            if normalize_publication_packaging_platform_key(item)
        ]
        if members:
            normalized_slot["members"] = members
        projected.append(normalized_slot)
    return projected or explicit_slots


def derive_publication_cover_slots(entry: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(entry, dict):
        return []
    cover_generation = entry.get("cover_generation") if isinstance(entry.get("cover_generation"), dict) else {}
    constraints = entry.get("constraints") if isinstance(entry.get("constraints"), dict) else {}
    copy_material = entry.get("copy_material") if isinstance(entry.get("copy_material"), dict) else {}
    cover_matrix = entry.get("cover_matrix") if isinstance(entry.get("cover_matrix"), dict) else {}
    cover_group = cover_generation.get("cover_group") if isinstance(cover_generation.get("cover_group"), dict) else {}
    group_generation = (
        cover_generation.get("group_generation")
        if isinstance(cover_generation.get("group_generation"), dict)
        else {}
    )
    if not cover_group and isinstance(group_generation.get("cover_group"), dict):
        cover_group = group_generation.get("cover_group") or {}
    members = [
        normalize_publication_packaging_platform_key(item)
        for item in (
            cover_group.get("members")
            or copy_material.get("cover_slot_members")
            or copy_material.get("cover_group_members")
            or []
        )
        if normalize_publication_packaging_platform_key(item)
    ]
    normalized_slots = normalize_publication_cover_slots(
        entry.get("cover_slots") if isinstance(entry.get("cover_slots"), list) else copy_material.get("cover_slots"),
        cover_path=str(entry.get("cover_path") or copy_material.get("cover_path") or "").strip(),
        target_size=(
            cover_generation.get("target_size")
            if isinstance(cover_generation.get("target_size"), dict)
            else constraints.get("cover_size")
            if isinstance(constraints.get("cover_size"), dict)
            else copy_material.get("target_size")
            if isinstance(copy_material.get("target_size"), dict)
            else copy_material.get("cover_size")
            if isinstance(copy_material.get("cover_size"), dict)
            else None
        ),
        slot=str(copy_material.get("cover_slot") or entry.get("cover_slot") or "primary").strip() or "primary",
        label=str(copy_material.get("cover_slot_label") or entry.get("label") or "").strip(),
        source=str(cover_generation.get("source") or copy_material.get("cover_slot_source") or "").strip(),
        matrix_key=str(
            cover_group.get("key")
            or copy_material.get("cover_matrix_key")
            or copy_material.get("cover_group_key")
            or ""
        ).strip(),
        members=members,
    )
    return _project_required_cover_slots_from_cover_matrix(
        platform=normalize_publication_packaging_platform_key(entry.get("platform") or entry.get("key")),
        explicit_slots=normalized_slots,
        cover_matrix=cover_matrix,
        cover_path=str(entry.get("cover_path") or copy_material.get("cover_path") or "").strip(),
        target_size=(
            cover_generation.get("target_size")
            if isinstance(cover_generation.get("target_size"), dict)
            else constraints.get("cover_size")
            if isinstance(constraints.get("cover_size"), dict)
            else copy_material.get("target_size")
            if isinstance(copy_material.get("target_size"), dict)
            else copy_material.get("cover_size")
            if isinstance(copy_material.get("cover_size"), dict)
            else None
        ),
    )


def publication_primary_cover_path(entry: dict[str, Any] | None) -> str:
    if isinstance(entry, dict):
        platform = normalize_publication_packaging_platform_key(entry.get("platform") or entry.get("key"))
        explicit_cover_path = str(entry.get("cover_path") or "").strip()
        if (
            explicit_cover_path
            and len(platform_required_cover_slots(platform)) == 1
            and not isinstance(entry.get("cover_matrix"), dict)
        ):
            return explicit_cover_path
    slots = derive_publication_cover_slots(entry)
    for slot in slots:
        path = str(slot.get("cover_path") or "").strip()
        if path:
            return path
    if isinstance(entry, dict):
        return str(entry.get("cover_path") or "").strip()
    return ""


def normalize_publication_packaging_payload(
    payload: dict[str, Any],
    *,
    material_dir: str | None = None,
) -> dict[str, Any] | None:
    raw_platforms = payload.get("platforms")
    if isinstance(raw_platforms, dict):
        shared_cover_matrix = payload.get("cover_matrix") if isinstance(payload.get("cover_matrix"), dict) else {}
        normalized_platforms: dict[str, dict[str, Any]] = {}
        for raw_platform, raw_entry in raw_platforms.items():
            if not isinstance(raw_entry, dict):
                continue
            platform = normalize_publication_packaging_platform_key(raw_platform)
            if not platform:
                continue
            entry = dict(raw_entry)
            entry.setdefault("platform", platform)
            entry.setdefault("key", platform)
            entry.setdefault("manual_handoff_only", platform_manual_handoff_only(platform))
            entry.setdefault("manual_publish_entry_url", platform_manual_publish_entry_url(platform))
            if shared_cover_matrix and not isinstance(entry.get("cover_matrix"), dict):
                entry["cover_matrix"] = dict(shared_cover_matrix)
            entry["cover_slots"] = derive_publication_cover_slots(entry)
            primary_cover_path = publication_primary_cover_path(entry)
            if primary_cover_path:
                entry["cover_path"] = primary_cover_path
            entry["blocking_reasons"] = publication_packaging_entry_blocking_reasons(entry)
            entry["publish_ready"] = publication_packaging_entry_publish_ready(entry)
            normalized_platforms[platform] = entry
        packaging = dict(payload)
        packaging["platforms"] = normalized_platforms
        if material_dir and not str(packaging.get("material_dir") or "").strip():
            packaging["material_dir"] = str(material_dir)
        if not str(packaging.get("source") or "").strip():
            packaging["source"] = "platform_packaging"
        packaging["publish_ready"] = publication_packaging_payload_publish_ready(packaging)
        return packaging

    platforms: dict[str, dict[str, Any]] = {}
    shared_cover_matrix = payload.get("cover_matrix") if isinstance(payload.get("cover_matrix"), dict) else {}
    material_contract = payload.get("material_contract") if isinstance(payload.get("material_contract"), dict) else {}
    contract_platforms = material_contract.get("platforms") if isinstance(material_contract.get("platforms"), dict) else {}
    for item in raw_platforms if isinstance(raw_platforms, list) else []:
        if not isinstance(item, dict):
            continue
        key = normalize_publication_packaging_platform_key(item.get("key") or item.get("platform") or item.get("platform_name"))
        if not key:
            continue
        contract_entry = contract_platforms.get(key) if isinstance(contract_platforms.get(key), dict) else {}
        entry: dict[str, Any] = {
            "manual_handoff_only": bool(contract_entry.get("manual_handoff_only")) or platform_manual_handoff_only(key),
            "manual_publish_entry_url": str(contract_entry.get("manual_publish_entry_url") or "").strip()
            or platform_manual_publish_entry_url(key),
            "platform": key,
            "key": key,
            "blocking_reasons": [
                str(reason).strip()
                for reason in ((item.get("blocking_reasons") or []) or (contract_entry.get("blocking_reasons") or []))
                if str(reason).strip()
            ],
        }
        titles = [str(title).strip() for title in (item.get("titles") or []) if str(title).strip()]
        tags = [str(tag).strip().lstrip("#") for tag in (item.get("tags") or []) if str(tag).strip()]
        primary_title = str(item.get("primary_title") or "").strip()
        body = str(item.get("body") or "").strip()
        cover_path = str(item.get("cover_path") or "").strip()
        declaration = str(item.get("declaration") or "").strip()
        category = str(item.get("category") or "").strip()
        collection_name = str(item.get("collection_name") or "").strip()
        visibility_or_publish_mode = str(item.get("visibility_or_publish_mode") or "").strip()
        scheduled_publish_at = str(item.get("scheduled_publish_at") or "").strip()
        if titles:
            entry["titles"] = titles
        if primary_title:
            entry["primary_title"] = primary_title
        if body:
            entry["description"] = body
            entry["body"] = body
        if tags:
            entry["tags"] = tags
        if cover_path:
            entry["cover_path"] = cover_path
        if isinstance(item.get("cover_generation"), dict) and item.get("cover_generation"):
            entry["cover_generation"] = dict(item.get("cover_generation") or {})
        if declaration:
            entry["declaration"] = declaration
        if category:
            entry["category"] = category
        if collection_name:
            entry["collection_name"] = collection_name
        if isinstance(item.get("collection"), dict) and item.get("collection"):
            entry["collection"] = dict(item.get("collection") or {})
        if visibility_or_publish_mode:
            entry["visibility_or_publish_mode"] = visibility_or_publish_mode
        if scheduled_publish_at:
            entry["scheduled_publish_at"] = scheduled_publish_at
        if isinstance(item.get("copy_material"), dict) and item.get("copy_material"):
            entry["copy_material"] = dict(item.get("copy_material") or {})
        if isinstance(item.get("live_publish_preflight"), dict) and item.get("live_publish_preflight"):
            entry["live_publish_preflight"] = dict(item.get("live_publish_preflight") or {})
        if isinstance(item.get("platform_specific_overrides"), dict) and item.get("platform_specific_overrides"):
            entry["platform_specific_overrides"] = dict(item.get("platform_specific_overrides") or {})
        if shared_cover_matrix:
            entry["cover_matrix"] = dict(shared_cover_matrix)
        entry["cover_slots"] = derive_publication_cover_slots(entry)
        primary_cover_path = publication_primary_cover_path(entry)
        if primary_cover_path:
            entry["cover_path"] = primary_cover_path
        entry["blocking_reasons"] = publication_packaging_entry_blocking_reasons(entry)
        entry["publish_ready"] = publication_packaging_entry_publish_ready(entry)
        platforms[key] = entry
    if not platforms:
        return None
    title_audit = payload.get("title_audit") if isinstance(payload.get("title_audit"), dict) else {}
    platform_scope = material_contract.get("platform_scope") if isinstance(material_contract.get("platform_scope"), dict) else {}
    packaging = {
        "platforms": platforms,
        "source": "intelligent_publish",
        "material_dir": str(material_dir or payload.get("material_dir") or ""),
        "blocking_reasons": [str(reason).strip() for reason in (payload.get("blocking_reasons") or []) if str(reason).strip()],
        "title_audit": dict(title_audit),
        "platform_scope": dict(platform_scope),
    }
    packaging["publish_ready"] = publication_packaging_payload_publish_ready(packaging)
    return packaging


def load_publication_packaging_payload(
    *,
    material_json: str = "",
    platform_packaging: str = "",
    platforms: list[str] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    material_json_path, packaging_path = resolve_publication_packaging_input_paths(
        material_json=material_json,
        platform_packaging=platform_packaging,
    )
    packaging_payload = load_json_payload(packaging_path)
    smart_copy_payload = load_json_payload(material_json_path)

    normalized_packaging = (
        normalize_publication_packaging_payload(
            packaging_payload,
            material_dir=str(smart_copy_material_root(packaging_path)) if packaging_path is not None else "",
        )
        if isinstance(packaging_payload, dict)
        else None
    )
    normalized_material_packaging = (
        normalize_publication_packaging_payload(
            smart_copy_payload,
            material_dir=str(smart_copy_material_root(material_json_path)) if material_json_path is not None else "",
        )
        if isinstance(smart_copy_payload, dict)
        else None
    )
    requested_platforms = _normalize_requested_publication_packaging_platforms(platforms)
    source = ""
    if normalized_packaging is not None:
        source = "platform_packaging"
        packaging_platforms = normalized_packaging.get("platforms") if isinstance(normalized_packaging.get("platforms"), dict) else {}
        material_platforms = (
            normalized_material_packaging.get("platforms")
            if isinstance(normalized_material_packaging, dict) and isinstance(normalized_material_packaging.get("platforms"), dict)
            else {}
        )
        missing_requested_platforms = [
            platform
            for platform in requested_platforms
            if platform not in packaging_platforms and isinstance(material_platforms.get(platform), dict)
        ]
        if missing_requested_platforms:
            merged_packaging = dict(normalized_packaging)
            merged_platforms = {
                platform: dict(entry)
                for platform, entry in packaging_platforms.items()
                if isinstance(entry, dict)
            }
            for platform in missing_requested_platforms:
                merged_platforms[platform] = dict(material_platforms.get(platform) or {})
            merged_packaging["platforms"] = merged_platforms
            scope = extract_publication_packaging_scope(merged_packaging)
            covered_platforms = [
                platform for platform in requested_platforms if isinstance(merged_platforms.get(platform), dict)
            ]
            missing_platforms = [
                platform for platform in requested_platforms if not isinstance(merged_platforms.get(platform), dict)
            ]
            if scope or requested_platforms:
                merged_packaging["platform_scope"] = {
                    "requested_platforms": requested_platforms,
                    "covered_platforms": covered_platforms,
                    "missing_requested_platforms": missing_platforms,
                }
            merged_packaging["publish_ready"] = publication_packaging_payload_publish_ready(merged_packaging)
            if merged_packaging["publish_ready"]:
                merged_packaging["blocking_reasons"] = []
            else:
                blocking_reasons: list[str] = []
                for platform in requested_platforms or sorted(merged_platforms):
                    entry = merged_platforms.get(platform) if isinstance(merged_platforms.get(platform), dict) else {}
                    if not entry:
                        blocking_reasons.append(f"{platform} 平台文案未就绪。")
                        continue
                    entry_reasons = publication_packaging_entry_blocking_reasons(entry)
                    if entry_reasons:
                        blocking_reasons.extend(entry_reasons)
                    elif not publication_packaging_entry_publish_ready(entry):
                        blocking_reasons.append(f"{platform} 平台文案未就绪。")
                merged_packaging["blocking_reasons"] = list(dict.fromkeys(blocking_reasons))
            normalized_packaging = merged_packaging
            source = "platform_packaging+material_json"
    elif normalized_material_packaging is not None:
        normalized_packaging = normalized_material_packaging
        source = "material_json"

    return normalized_packaging, {
        "source": source,
        "material_json_path": str(material_json_path) if material_json_path is not None else "",
        "platform_packaging_path": str(packaging_path) if packaging_path is not None else "",
    }


def filter_publication_packaging_platforms(
    packaging: dict[str, Any] | None,
    *,
    platforms: list[str] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(packaging, dict):
        return None
    requested_platforms = {
        normalize_publication_packaging_platform_key(item)
        for item in (platforms or [])
        if normalize_publication_packaging_platform_key(item)
    }
    if not requested_platforms:
        return dict(packaging)
    normalized_platforms = packaging.get("platforms") if isinstance(packaging.get("platforms"), dict) else {}
    filtered_platforms = {
        platform: dict(entry)
        for platform, entry in normalized_platforms.items()
        if platform in requested_platforms and isinstance(entry, dict)
    }
    if not filtered_platforms:
        return None
    filtered = dict(packaging)
    filtered["platforms"] = filtered_platforms
    raw_scope = packaging.get("platform_scope") if isinstance(packaging.get("platform_scope"), dict) else {}
    if raw_scope:
        def _filter_scope_values(values: Any) -> list[str]:
            normalized: list[str] = []
            for item in (values or []):
                platform = normalize_publication_packaging_platform_key(item)
                if platform and platform in requested_platforms and platform not in normalized:
                    normalized.append(platform)
            return normalized

        filtered["platform_scope"] = {
            "requested_platforms": _filter_scope_values(raw_scope.get("requested_platforms")),
            "covered_platforms": _filter_scope_values(raw_scope.get("covered_platforms")),
            "missing_requested_platforms": _filter_scope_values(raw_scope.get("missing_requested_platforms")),
        }
    filtered["publish_ready"] = publication_packaging_payload_publish_ready(filtered)
    if filtered["publish_ready"]:
        filtered["blocking_reasons"] = []
    else:
        blocking_reasons: list[str] = []
        for platform in sorted(filtered_platforms):
            entry = filtered_platforms.get(platform) if isinstance(filtered_platforms.get(platform), dict) else {}
            entry_reasons = publication_packaging_entry_blocking_reasons(entry)
            if entry_reasons:
                blocking_reasons.extend(entry_reasons)
            else:
                blocking_reasons.append(f"{platform} 平台文案未就绪。")
        filtered["blocking_reasons"] = list(dict.fromkeys(blocking_reasons))
    return filtered


def extract_publication_packaging_scope(raw_packaging: Any) -> dict[str, list[str]]:
    if not isinstance(raw_packaging, dict):
        return {}
    raw_scope = raw_packaging.get("platform_scope") if isinstance(raw_packaging.get("platform_scope"), dict) else {}
    if not raw_scope:
        return {}

    def _normalize_platform_list(values: Any) -> list[str]:
        normalized: list[str] = []
        for item in (values or []):
            platform = normalize_publication_packaging_platform_key(item)
            if platform and platform not in normalized:
                normalized.append(platform)
        return normalized

    requested_platforms = _normalize_platform_list(raw_scope.get("requested_platforms"))
    covered_platforms = _normalize_platform_list(raw_scope.get("covered_platforms"))
    missing_requested_platforms = _normalize_platform_list(raw_scope.get("missing_requested_platforms"))
    if not (requested_platforms or covered_platforms or missing_requested_platforms):
        return {}
    return {
        "requested_platforms": requested_platforms,
        "covered_platforms": covered_platforms,
        "missing_requested_platforms": missing_requested_platforms,
    }


def publication_packaging_missing_platform_messages(
    packaging: dict[str, Any] | None,
    *,
    platforms: list[str] | None = None,
) -> dict[str, dict[str, str]]:
    requested_platforms = _normalize_requested_publication_packaging_platforms(platforms)
    if not requested_platforms:
        return {}
    normalized_platforms = packaging.get("platforms") if isinstance(packaging, dict) and isinstance(packaging.get("platforms"), dict) else {}
    packaging_scope = extract_publication_packaging_scope(packaging)
    covered_platforms = packaging_scope.get("covered_platforms") or sorted(
        normalize_publication_packaging_platform_key(platform)
        for platform, entry in normalized_platforms.items()
        if isinstance(entry, dict) and normalize_publication_packaging_platform_key(platform)
    )
    scope_requested_platforms = packaging_scope.get("requested_platforms") or covered_platforms
    covered_platforms_text = ", ".join(covered_platforms) if covered_platforms else "无"
    messages: dict[str, dict[str, str]] = {}
    for platform in requested_platforms:
        if isinstance(normalized_platforms.get(platform), dict):
            continue
        if scope_requested_platforms and platform not in scope_requested_platforms:
            messages[platform] = {
                "message": f"该平台不在本期物料合同覆盖范围内。当前仅覆盖平台 -> {covered_platforms_text}",
                "failure": f"发布范围不匹配：{platform} 不在本期物料生成范围内。当前仅覆盖平台 -> {covered_platforms_text}",
            }
            continue
        messages[platform] = {
            "message": "未提供该平台的发布文案。",
            "failure": f"发布文案缺失：未提供以下平台的发布文案: {platform}",
        }
    return messages


def publication_packaging_entry_blocking_reasons(entry: dict[str, Any]) -> list[str]:
    platform = normalize_publication_packaging_platform_key(
        entry.get("platform") or entry.get("key") or entry.get("platform_key")
    )
    preflight = entry.get("live_publish_preflight") if isinstance(entry.get("live_publish_preflight"), dict) else {}
    preflight_status = str(preflight.get("status") or "").strip().lower()
    missing_required_surfaces = [
        str(item).strip()
        for item in (preflight.get("missing_required_surfaces") or [])
        if str(item).strip()
    ]
    blocking_reasons = [
        str(item).strip()
        for item in ((entry.get("blocking_reasons") or []) or (preflight.get("blocking_reasons") or []))
        if str(item).strip()
    ]
    manual_handoff_only = bool(entry.get("manual_handoff_only")) or platform_manual_handoff_only(platform)
    if manual_handoff_only:
        return list(dict.fromkeys(blocking_reasons))
    if not _publication_packaging_entry_has_title(entry):
        blocking_reasons.append("标题为空，不能自动发布。")
    metadata_contract_fields = (
        "declaration",
        "category",
        "collection_name",
        "visibility_or_publish_mode",
        "scheduled_publish_at",
    )
    metadata_contract_present = any(field in entry for field in metadata_contract_fields)
    metadata_fields_present = [
        field
        for field in metadata_contract_fields
        if str(entry.get(field) or "").strip()
    ]
    collection_contract_present = "collection_name" in entry or "collection" in entry
    if isinstance(entry.get("collection"), dict) and str(entry.get("collection", {}).get("name") or "").strip():
        if "collection_name" not in metadata_fields_present:
            metadata_fields_present.append("collection_name")
    platform_specific_overrides = (
        dict(entry.get("platform_specific_overrides"))
        if isinstance(entry.get("platform_specific_overrides"), dict)
        else {}
    )
    metadata_override_keys = {
        "declaration",
        "category",
        "visibility_or_publish_mode",
        "scheduled_publish_at",
        "schedule_publish",
    }
    if any(key in platform_specific_overrides for key in metadata_override_keys):
        metadata_contract_present = True
    collection_management = (
        dict(platform_specific_overrides.get("collection_management"))
        if isinstance(platform_specific_overrides.get("collection_management"), dict)
        else {}
    )
    if collection_management:
        collection_contract_present = True
    explicit_collection_name = str(entry.get("collection_name") or "").strip()
    if not explicit_collection_name and isinstance(entry.get("collection"), dict):
        explicit_collection_name = str(entry.get("collection", {}).get("name") or "").strip()
    if not explicit_collection_name:
        explicit_collection_name = str(
            collection_management.get("target_collection_name")
            or collection_management.get("collection_name")
            or ""
        ).strip()
    collection_policy = str(platform_specific_overrides.get("collection_policy") or "").strip().lower()
    explicit_collection_skip = bool(platform_specific_overrides.get("skip_collection_select")) or collection_policy in publication_collection_policy_skip_values()
    if not explicit_collection_name:
        explicit_collection_skip = True
    collection_policy_ready = (
        not platform_requires_explicit_collection_policy(platform)
        or bool(explicit_collection_name)
        or explicit_collection_skip
    )
    if not blocking_reasons and missing_required_surfaces:
        blocking_reasons.append(
            f"缺少发布前必要页面能力：{'、'.join(missing_required_surfaces)}"
        )
    if not blocking_reasons and preflight_status in {"blocked", "missing_required_surfaces"}:
        summary = str(preflight.get("summary") or "").strip()
        if summary:
            blocking_reasons.append(summary)
        else:
            blocking_reasons.append("发布前页面验证未通过。")
    if metadata_contract_present and not metadata_fields_present:
        blocking_reasons.append("缺少平台专属发布配置（declaration/category/collection/visibility/schedule）")
    if collection_contract_present and not collection_policy_ready:
        blocking_reasons.append("缺少合集决策（需指定 collection_name 或显式声明跳过合集）")
    return list(dict.fromkeys(blocking_reasons))


def _publication_packaging_entry_has_title(entry: dict[str, Any]) -> bool:
    for key in ("primary_title", "title"):
        if str(entry.get(key) or "").strip():
            return True
    titles = entry.get("titles")
    if isinstance(titles, list):
        return any(str(title or "").strip() for title in titles)
    return False


def publication_packaging_entry_publish_ready(
    entry: dict[str, Any],
    *,
    trust_explicit_flag: bool = True,
) -> bool:
    raw_publish_ready = entry.get("publish_ready")
    preflight = entry.get("live_publish_preflight") if isinstance(entry.get("live_publish_preflight"), dict) else {}
    preflight_status = str(preflight.get("status") or "").strip().lower()
    missing_required_surfaces = [
        str(item).strip()
        for item in (preflight.get("missing_required_surfaces") or [])
        if str(item).strip()
    ]
    blocking_reasons = publication_packaging_entry_blocking_reasons(entry)
    derived_publish_ready = (
        preflight_status not in {"blocked", "missing_required_surfaces"}
        and not missing_required_surfaces
        and not blocking_reasons
    )
    if trust_explicit_flag and isinstance(raw_publish_ready, bool):
        if raw_publish_ready is False:
            return False
        return derived_publish_ready
    return derived_publish_ready


def publication_packaging_payload_publish_ready(packaging: dict[str, Any] | None) -> bool:
    if not isinstance(packaging, dict):
        return False
    platforms = packaging.get("platforms") if isinstance(packaging.get("platforms"), dict) else {}
    auto_publish_platform_present = False
    for raw_platform, raw_entry in platforms.items():
        if not isinstance(raw_entry, dict):
            continue
        platform = normalize_publication_packaging_platform_key(raw_platform)
        manual_handoff_only = bool(raw_entry.get("manual_handoff_only")) or platform_manual_handoff_only(platform)
        if manual_handoff_only:
            continue
        auto_publish_platform_present = True
        if not publication_packaging_entry_publish_ready(raw_entry):
            return False
    return auto_publish_platform_present
