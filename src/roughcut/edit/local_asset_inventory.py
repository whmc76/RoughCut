from __future__ import annotations

from typing import Any

from roughcut.edit.capability_orchestrator import normalize_local_asset_inventory


def packaging_snapshot_asset_inventory(
    packaging_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot = dict(packaging_snapshot or {}) if isinstance(packaging_snapshot, dict) else {}
    insert_asset_ids = {
        str(item).strip()
        for item in (list(snapshot.get("insert_asset_ids") or []) + [snapshot.get("insert_asset_id")])
        if str(item or "").strip()
    }
    music_asset_ids = {
        str(item).strip()
        for item in list(snapshot.get("music_asset_ids") or [])
        if str(item).strip()
    }
    intro_outro_count = sum(
        1
        for value in (snapshot.get("intro_asset_id"), snapshot.get("outro_asset_id"))
        if str(value or "").strip()
    )
    watermark_count = 1 if str(snapshot.get("watermark_asset_id") or "").strip() else 0
    return normalize_local_asset_inventory(
        {
            "image_count": len(insert_asset_ids),
            "audio_count": len(music_asset_ids),
            "intro_outro_count": intro_outro_count,
            "watermark_count": watermark_count,
        }
    )


def build_uploaded_material_inventory(
    *,
    has_primary_video: bool = True,
    merged_source_names: list[str] | None = None,
    packaging_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged_names = [
        str(item).strip()
        for item in list(merged_source_names or [])
        if str(item).strip()
    ]
    packaging_inventory = packaging_snapshot_asset_inventory(packaging_snapshot)
    return normalize_local_asset_inventory(
        {
            "has_primary_video": has_primary_video,
            "auxiliary_video_count": max(0, len(merged_names) - 1),
            "image_count": int(packaging_inventory.get("image_count") or 0),
            "audio_count": int(packaging_inventory.get("audio_count") or 0),
            "intro_outro_count": int(packaging_inventory.get("intro_outro_count") or 0),
            "watermark_count": int(packaging_inventory.get("watermark_count") or 0),
        }
    )
