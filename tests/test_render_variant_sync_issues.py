from roughcut.pipeline.steps import _collect_blocking_variant_sync_issues


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

