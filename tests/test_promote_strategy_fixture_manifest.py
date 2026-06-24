from scripts.promote_strategy_fixture_manifest import promote_strategy_fixture_manifest


def test_promote_strategy_fixture_manifest_adds_real_world_tag_for_ready_strategy() -> None:
    manifest = {
        "real_render_ready_strategy_types": ["information_density"],
        "jobs": [
            {
                "case_id": "info",
                "tags": ["strategy:information_density", "strategy_candidate"],
                "risk_hints": {"expected_strategy_type": "information_density"},
            },
            {
                "case_id": "step",
                "tags": ["strategy:step_demonstration", "strategy_candidate"],
                "risk_hints": {"expected_strategy_type": "step_demonstration"},
            },
        ],
    }

    promoted = promote_strategy_fixture_manifest(manifest, strategy_types=["information_density"])

    jobs = {item["case_id"]: item for item in promoted["jobs"]}
    assert jobs["info"]["tags"] == ["strategy:information_density", "strategy_candidate", "real_world_fixture"]
    assert jobs["step"]["tags"] == ["strategy:step_demonstration", "strategy_candidate"]
    assert promoted["promotion"]["promoted_case_ids"] == ["info"]
    assert promoted["promotion"]["skipped"] == []


def test_promote_strategy_fixture_manifest_skips_not_ready_strategy_by_default() -> None:
    manifest = {
        "real_render_ready_strategy_types": ["information_density"],
        "jobs": [
            {
                "case_id": "step",
                "tags": ["strategy:step_demonstration", "strategy_candidate"],
                "risk_hints": {"expected_strategy_type": "step_demonstration"},
            }
        ],
    }

    promoted = promote_strategy_fixture_manifest(manifest, strategy_types=["step_demonstration"])

    assert promoted["jobs"][0]["tags"] == ["strategy:step_demonstration", "strategy_candidate"]
    assert promoted["promotion"]["promoted_case_ids"] == []
    assert promoted["promotion"]["skipped"] == [
        {
            "case_id": "step",
            "strategy_type": "step_demonstration",
            "reason": "strategy_not_real_render_ready",
        }
    ]
