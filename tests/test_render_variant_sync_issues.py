from roughcut.pipeline.steps import _collect_blocking_variant_sync_issues
from roughcut.pipeline.quality import _subtitle_timing_structure_diagnostics


def test_collect_blocking_variant_sync_issues_only_checks_required_variants() -> None:
    issues = _collect_blocking_variant_sync_issues(
        {
            "packaged": {"warning_codes": ["subtitle_out_of_bounds"]},
            "plain": {"warning_codes": ["subtitle_duration_gap_large"]},
            "avatar": {"warning_codes": ["subtitle_out_of_bounds"]},
            "ai_effect": {"warning_codes": ["subtitle_trailing_gap_large"]},
        },
        mandatory_variants={"plain", "packaged"},
    )

    assert issues == [
        "packaged: subtitle_out_of_bounds",
        "plain: subtitle_duration_gap_large",
    ]


def test_collect_blocking_variant_sync_issues_ignores_optional_variant_noise_if_not_required() -> None:
    issues = _collect_blocking_variant_sync_issues(
        {
            "plain": {"warning_codes": ["subtitle_timestamp_disorder"]},
            "avatar": {"warning_codes": ["subtitle_timestamp_disorder"]},
        },
        mandatory_variants={"plain"},
    )

    assert issues == ["plain: subtitle_timestamp_disorder"]


def test_collect_blocking_variant_sync_issues_keeps_default_behavior_without_mandatory_variants() -> None:
    issues = _collect_blocking_variant_sync_issues(
        {
            "avatar": {"warning_codes": ["subtitle_timestamp_disorder"]},
            "plain": {"warning_codes": ["subtitle_timestamp_disorder"]},
        }
    )

    assert set(issues) == {
        "avatar: subtitle_timestamp_disorder",
        "plain: subtitle_timestamp_disorder",
    }


def test_collect_blocking_variant_sync_issues_blocks_subtitle_flash_density() -> None:
    issues = _collect_blocking_variant_sync_issues(
        {
            "packaged": {
                "warning_codes": ["subtitle_burst_density_detected", "subtitle_short_flash_detected"],
                "subtitle_timing_structure": {
                    "short_flash_count": 3,
                    "max_events_per_one_sec": 5,
                    "burst_window_count": 1,
                },
            }
        },
        mandatory_variants={"packaged"},
    )

    assert issues == ["packaged: subtitle_burst_density_detected, subtitle_short_flash_detected"]


def test_subtitle_timing_structure_diagnostics_detects_fast_flash_cluster() -> None:
    diagnostics = _subtitle_timing_structure_diagnostics(
        [
            (1.00, 1.12),
            (1.15, 1.29),
            (1.32, 1.46),
            (1.49, 1.61),
            (4.00, 5.40),
        ],
        video_duration_sec=8.0,
    )

    assert diagnostics["short_flash_count"] == 4
    assert diagnostics["max_events_per_one_sec"] == 4
    assert diagnostics["burst_window_count"] == 1
