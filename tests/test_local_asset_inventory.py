from roughcut.edit.local_asset_inventory import (
    build_uploaded_material_inventory,
    packaging_snapshot_asset_inventory,
)


def test_packaging_snapshot_asset_inventory_normalizes_packaging_assets() -> None:
    inventory = packaging_snapshot_asset_inventory(
        {
            "insert_asset_ids": ["insert-a", "insert-b"],
            "insert_asset_id": "insert-b",
            "music_asset_ids": ["bgm-a"],
            "intro_asset_id": "intro-a",
            "outro_asset_id": "outro-a",
            "watermark_asset_id": "wm-a",
        }
    )

    assert inventory["image_count"] == 2
    assert inventory["audio_count"] == 1
    assert inventory["intro_outro_count"] == 2
    assert inventory["watermark_count"] == 1
    assert inventory["has_visual_inserts"] is True
    assert inventory["has_audio_support"] is True


def test_build_uploaded_material_inventory_combines_primary_auxiliary_and_packaging_assets() -> None:
    inventory = build_uploaded_material_inventory(
        has_primary_video=True,
        merged_source_names=["main.mp4", "cutaway-a.mp4", "cutaway-b.mp4"],
        packaging_snapshot={
            "insert_asset_ids": ["still-a"],
            "music_asset_ids": ["bgm-a", "sfx-a"],
            "watermark_asset_id": "wm-a",
        },
    )

    assert inventory["primary_video_count"] == 1
    assert inventory["auxiliary_video_count"] == 2
    assert inventory["image_count"] == 1
    assert inventory["audio_count"] == 2
    assert inventory["watermark_count"] == 1
    assert inventory["multi_material_ready"] is True
    assert inventory["total_uploaded_material_count"] == 7
