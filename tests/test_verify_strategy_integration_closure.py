from scripts import verify_strategy_integration_closure as verifier


def _content_report() -> dict:
    strategies = [
        "information_density",
        "step_demonstration",
        "experience_and_mood",
        "event_highlight",
        "narrative_assembly",
    ]
    rows = []
    for strategy in strategies:
        statuses = {
            "strategy_pipeline_coverage": {
                "passed": True,
                "expected_strategy_types": [strategy],
                "observed_strategy_types": [strategy],
                "missing_strategy_types": [],
            }
        }
        if strategy == "narrative_assembly":
            statuses["strategy_review_preview_evidence"] = {
                "passed": True,
                "strategy_type": "narrative_assembly",
                "storyboard_panel_count": 3,
                "timeline_segment_count": 2,
                "timeline_time_anchor_count": 2,
            }
            statuses["strategy_review_preview_media_evidence"] = {
                "passed": True,
                "strategy_type": "narrative_assembly",
                "source_media_count": 3,
                "readable_media_count": 3,
                "timeline_segment_count": 2,
                "media_backed_segment_count": 2,
            }
        rows.append(
            {
                "case_id": f"case-{strategy}",
                "tags": [f"strategy:{strategy}"],
                "required_check_statuses": statuses,
            }
        )
    return {
        "required_checks": {
            "required_checks_total": 7,
            "required_checks_contract_failed": 0,
            "required_checks_case_failed": 0,
            "required_checks_contract_pass_rate": 1.0,
        },
        "strategy_pipeline_coverage": {
            "evaluated_case_count": 5,
            "declared_strategy_types": strategies,
            "covered_strategy_types": strategies,
            "missing_strategy_types": [],
            "failed_case_ids": [],
        },
        "golden_case_rows": rows,
    }


def _event_render_report() -> dict:
    return {
        "required_checks": {
            "required_checks_total": 2,
            "required_checks_contract_failed": 0,
            "required_checks_case_failed": 0,
            "required_checks_contract_pass_rate": 1.0,
        },
        "golden_case_rows": [
            {
                "case_id": "case-event",
                "tags": ["strategy:event_highlight"],
                "required_check_statuses": {
                    "strategy_boundary_samples": {
                        "passed": True,
                        "strategy_type": "event_highlight",
                        "frame_sample_count": 1,
                        "waveform_sample_count": 1,
                    }
                },
            }
        ],
    }


def _real_render_report(*, narrative_media_preview: bool = False) -> dict:
    strategies = [
        "information_density",
        "step_demonstration",
        "experience_and_mood",
        "event_highlight",
        "narrative_assembly",
    ]
    rows = []
    for strategy in strategies:
        statuses = {
            "strategy_pipeline_coverage": {
                "passed": True,
                "expected_strategy_types": [strategy],
                "observed_strategy_types": [strategy],
                "missing_strategy_types": [],
            }
        }
        if strategy == "narrative_assembly" and narrative_media_preview:
            statuses["strategy_review_preview_media_evidence"] = {
                "passed": True,
                "expected_strategy_types": ["narrative_assembly"],
                "strategy_type": "narrative_assembly",
                "source_media_count": 2,
                "readable_media_count": 2,
                "media_backed_segment_count": 2,
            }
        rows.append(
            {
                "case_id": f"real-{strategy}",
                "tags": [f"strategy:{strategy}", "strategy_fixture"],
                "evaluation_job_id": f"job-{strategy}",
                "status": "partial",
                "required_checks_passed": True,
                "required_check_statuses": statuses,
            }
        )
    return {
        "golden_case_rows": rows,
        "jobs": [
            {
                "job_id": f"job-{strategy}",
                "source_name": f"{strategy}.mp4",
                "status": "partial",
                "output_path": f"E:/{strategy}.mp4",
                "output_duration_sec": 3.0,
            }
            for strategy in strategies
        ],
    }


def test_verify_strategy_integration_closure_passes_generated_closure_evidence() -> None:
    result = verifier.verify_strategy_integration_closure(
        content_profile_report=_content_report(),
        event_render_report=_event_render_report(),
    )

    assert result["ok"] is True
    assert result["generated_closure_ok"] is True
    assert result["real_render_fixture_coverage_ok"] is False
    assert result["real_media_backed_preview_validation_ok"] is False
    assert result["completion_ready"] is False
    assert result["failed_generated_checks"] == []
    assert result["checks"]["narrative_review_preview_evidence"]["timeline_time_anchor_count"] == 2
    assert result["checks"]["narrative_review_preview_media_evidence"]["media_backed_segment_count"] == 2
    assert "real_world_render_fixture_per_strategy" in result["remaining_open_items"]
    assert "windows_asyncpg_runner_cleanup_warning" not in result["remaining_open_items"]


def test_verify_strategy_integration_closure_tracks_real_render_coverage_without_claiming_completion() -> None:
    result = verifier.verify_strategy_integration_closure(
        content_profile_report=_content_report(),
        event_render_report=_event_render_report(),
        real_render_reports=[_real_render_report()],
    )

    assert result["ok"] is True
    assert result["generated_closure_ok"] is True
    assert result["real_render_fixture_coverage_ok"] is True
    assert result["real_media_backed_preview_validation_ok"] is False
    assert result["completion_ready"] is False
    assert "real_world_render_fixture_per_strategy" not in result["remaining_open_items"]
    assert "real_world_media_backed_storyboard_timeline_preview_validation" in result["remaining_open_items"]
    assert "windows_asyncpg_runner_cleanup_warning" not in result["remaining_open_items"]


def test_verify_strategy_integration_closure_marks_ready_when_real_render_and_media_preview_pass() -> None:
    result = verifier.verify_strategy_integration_closure(
        content_profile_report=_content_report(),
        event_render_report=_event_render_report(),
        real_render_reports=[_real_render_report(narrative_media_preview=True)],
    )

    assert result["ok"] is True
    assert result["generated_closure_ok"] is True
    assert result["real_render_fixture_coverage_ok"] is True
    assert result["real_media_backed_preview_validation_ok"] is True
    assert result["completion_ready"] is True
    assert result["remaining_open_items"] == []


def test_verify_strategy_integration_closure_fails_missing_narrative_preview() -> None:
    content_report = _content_report()
    narrative_row = content_report["golden_case_rows"][-1]
    narrative_row["required_check_statuses"].pop("strategy_review_preview_evidence")

    result = verifier.verify_strategy_integration_closure(
        content_profile_report=content_report,
        event_render_report=_event_render_report(),
    )

    assert result["ok"] is False
    assert result["failed_generated_checks"] == ["narrative_review_preview_evidence"]
    assert result["checks"]["narrative_review_preview_evidence"]["missing_reasons"] == [
        "missing_strategy_review_preview_evidence"
    ]


def test_verify_strategy_integration_closure_fails_missing_narrative_preview_media() -> None:
    content_report = _content_report()
    narrative_row = content_report["golden_case_rows"][-1]
    narrative_row["required_check_statuses"].pop("strategy_review_preview_media_evidence")

    result = verifier.verify_strategy_integration_closure(
        content_profile_report=content_report,
        event_render_report=_event_render_report(),
    )

    assert result["ok"] is False
    assert result["failed_generated_checks"] == ["narrative_review_preview_media_evidence"]
    assert result["checks"]["narrative_review_preview_media_evidence"]["missing_reasons"] == [
        "missing_strategy_review_preview_media_evidence"
    ]


def test_required_checks_summary_requires_zero_contract_failures() -> None:
    result = verifier.verify_strategy_integration_closure(
        content_profile_report={
            **_content_report(),
            "required_checks": {
                "required_checks_total": 6,
                "required_checks_contract_failed": 1,
                "required_checks_case_failed": 0,
            },
        },
        event_render_report=_event_render_report(),
    )

    assert result["ok"] is False
    assert "content_profile_required_checks" in result["failed_generated_checks"]
