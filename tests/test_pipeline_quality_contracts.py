from roughcut.pipeline.quality import _resolve_packaged_variant_subtitle_sync_check


def test_resolve_packaged_variant_subtitle_sync_check_accepts_current_direct_quality_check_shape() -> None:
    sync_check = {
        "status": "warning",
        "message": "subtitle drift",
        "warning_codes": ["subtitle_out_of_bounds"],
    }

    result = _resolve_packaged_variant_subtitle_sync_check(
        {
            "variants": {
                "packaged": {
                    "quality_checks": sync_check,
                }
            }
        }
    )

    assert result == sync_check


def test_resolve_packaged_variant_subtitle_sync_check_keeps_legacy_nested_shape_compatible() -> None:
    sync_check = {
        "status": "ok",
        "message": "subtitle aligned",
        "warning_codes": [],
    }

    result = _resolve_packaged_variant_subtitle_sync_check(
        {
            "variants": {
                "packaged": {
                    "quality_checks": {
                        "subtitle_sync": sync_check,
                    }
                }
            }
        }
    )

    assert result == sync_check
