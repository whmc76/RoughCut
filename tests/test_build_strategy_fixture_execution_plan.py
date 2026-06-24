from scripts import build_strategy_fixture_execution_plan as planner


def _manifest() -> dict[str, object]:
    return {
        "schema": "strategy_candidate_golden_manifest.v1",
        "required_strategy_types": [
            "information_density",
            "step_demonstration",
            "narrative_assembly",
        ],
        "real_render_ready_strategy_types": ["information_density"],
        "jobs": [
            {
                "case_id": "strategy_information_density_demo",
                "reference_job_id": "11111111-1111-1111-1111-111111111111",
                "tags": ["strategy:information_density", "strategy_candidate"],
                "required_checks": ["strategy_pipeline_coverage"],
                "risk_hints": {"expected_strategy_type": "information_density"},
            },
            {
                "case_id": "strategy_step_demo",
                "reference_job_id": "22222222-2222-2222-2222-222222222222",
                "tags": ["strategy:step_demonstration", "strategy_candidate"],
                "required_checks": ["strategy_pipeline_coverage"],
                "risk_hints": {"expected_strategy_type": "step_demonstration"},
            },
            {
                "case_id": "strategy_narrative_demo",
                "reference_job_id": "33333333-3333-3333-3333-333333333333",
                "tags": ["strategy:narrative_assembly", "strategy_candidate"],
                "required_checks": [
                    "strategy_pipeline_coverage",
                    "strategy_review_preview_evidence",
                    "strategy_review_preview_media_evidence",
                ],
                "risk_hints": {"expected_strategy_type": "narrative_assembly"},
            },
        ],
    }


def test_build_strategy_fixture_execution_plan_splits_strategy_commands() -> None:
    plan = planner.build_strategy_fixture_execution_plan(
        _manifest(),
        manifest_path="output/test/strategy-fixture-candidates.manifest.v1.json",
    )

    assert plan["ok"] is True
    assert plan["completion_ready"] is False
    assert plan["manifest_ready_strategy_types"] == [
        "information_density",
        "step_demonstration",
        "narrative_assembly",
    ]
    assert plan["real_render_missing_strategy_types"] == ["step_demonstration", "narrative_assembly"]
    by_strategy = {item["strategy_type"]: item for item in plan["strategy_plans"]}
    assert by_strategy["information_density"]["needs_real_render_rerun"] is False
    assert "promote_strategy_fixture_manifest.py" in by_strategy["information_density"]["promotion_command"]
    assert by_strategy["step_demonstration"]["needs_real_render_rerun"] is True
    assert by_strategy["step_demonstration"]["runtime_preflight_required"] is True
    assert "check_strategy_fixture_runtime_preflight.py" in by_strategy["step_demonstration"]["runtime_preflight_command"]
    assert by_strategy["step_demonstration"]["promotion_required_for_real_closure"] is True
    assert by_strategy["step_demonstration"]["promotion_tag"] == "real_world_fixture"
    assert by_strategy["step_demonstration"]["render_fixture_command"] == (
        "uv run python scripts/run_auto_edit_recovery_golden_set.py"
        " --manifest output/test/strategy-fixture-candidates.manifest.v1.json"
        " --case-id strategy_step_demo"
        " --report-dir output/test/strategy-candidate-render-golden/step_demonstration"
        " --stop-after render"
    )
    assert "build_strategy_real_render_reference_report.py" in plan["verification_commands"]["real_render_reference_report"]
    assert "--report output/test/strategy-real-render-reference-report/batch_report.json" in plan["verification_commands"]["real_render_fixture_coverage"]


def test_narrative_plan_keeps_media_backed_preview_as_completion_blocker() -> None:
    plan = planner.build_strategy_fixture_execution_plan(
        _manifest(),
        manifest_path="manifest.json",
    )

    narrative = {item["strategy_type"]: item for item in plan["strategy_plans"]}["narrative_assembly"]
    assert narrative["agent_lane"] == "Narrative Preview Agent"
    assert narrative["blocking_checks_for_completion"] == [
        "real_render_fixture",
        "strategy_review_preview_evidence",
        "strategy_review_preview_media_evidence",
    ]
    assert "--real-render-report output/test/strategy-candidate-render-golden/narrative_assembly/<timestamp>/batch_report.json" in plan["verification_commands"]["integration_closure"]


def test_render_unsuitable_report_switches_plan_to_replacement_fixture() -> None:
    rejection_report = {
        "golden_case_rows": [
            {
                "case_id": "strategy_step_demo",
                "job_id": "22222222-2222-2222-2222-222222222222",
                "source_name": "step.mp4",
                "status": "failed",
                "required_checks_passed": True,
                "required_checks_failed": ["strategy_pipeline_coverage"],
                "run_steps": [
                    {
                        "step": "render",
                        "status": "failed",
                        "error": (
                            "RuntimeError: render_subtitle_asr_alignment_blocked: "
                            "rendered_audio_asr_alignment_unstable"
                        ),
                    }
                ],
            }
        ]
    }

    plan = planner.build_strategy_fixture_execution_plan(
        _manifest(),
        manifest_path="manifest.json",
        rejection_reports=[rejection_report],
    )

    by_strategy = {item["strategy_type"]: item for item in plan["strategy_plans"]}
    step = by_strategy["step_demonstration"]
    assert plan["replacement_fixture_needed_strategy_types"] == ["step_demonstration"]
    assert plan["real_render_missing_strategy_types"] == ["step_demonstration", "narrative_assembly"]
    assert plan["real_render_rerun_strategy_types"] == ["narrative_assembly"]
    assert plan["render_unsuitable_case_ids"] == ["strategy_step_demo"]
    assert step["source_status"] == "render_unsuitable_candidate"
    assert step["agent_lane"] == "Fixture Candidate Agent"
    assert step["render_unsuitable"] is True
    assert step["render_unsuitable_evidence"]["reason"] == "strategy_required_checks_failed"
    assert step["render_unsuitable_evidence"]["reason_codes"] == [
        "render_subtitle_asr_alignment_blocked",
        "rendered_audio_asr_alignment_unstable",
        "strategy_required_checks_failed",
    ]
    assert step["render_unsuitable_evidence"]["required_checks_failed"] == ["strategy_pipeline_coverage"]
    assert step["needs_replacement_fixture"] is True
    assert step["needs_real_render_rerun"] is False
    assert step["runtime_preflight_required"] is False
    assert step["render_fixture_command"] == ""
    assert step["blocking_checks_for_completion"] == [
        "replacement_fixture_required",
        "real_render_fixture",
    ]
    assert "ASR" in step["replacement_fixture_guidance"]


def test_candidate_summary_reference_evidence_closes_render_unsuitable_gap() -> None:
    rejection_report = {
        "golden_case_rows": [
            {
                "case_id": "strategy_step_demo",
                "job_id": "failed-step",
                "source_name": "step.mp4",
                "status": "failed",
                "required_checks_failed": [],
                "run_steps": [
                    {
                        "step": "render",
                        "status": "failed",
                        "error": "RuntimeError: render_subtitle_asr_alignment_blocked",
                    }
                ],
            }
        ]
    }
    candidate_summary = {
        "selected_candidates": {
            "step_demonstration": [
                {
                    "job_id": "ready-step-reference",
                    "source_name": "step-reference.mp4",
                    "real_render_readiness": {
                        "ready": True,
                        "reason_codes": ["render_output_done"],
                    },
                    "golden_manifest_case": {
                        "case_id": "strategy_step_reference",
                        "tags": ["strategy:step_demonstration", "strategy_candidate"],
                    },
                }
            ]
        }
    }

    plan = planner.build_strategy_fixture_execution_plan(
        _manifest(),
        manifest_path="manifest.json",
        candidate_summary=candidate_summary,
        candidate_summary_path="output/test/candidates.json",
        rejection_reports=[rejection_report],
    )

    by_strategy = {item["strategy_type"]: item for item in plan["strategy_plans"]}
    step = by_strategy["step_demonstration"]
    assert step["real_render_ready"] is True
    assert step["reference_evidence_ready"] is True
    assert step["source_status"] == "reference_evidence_ready"
    assert step["needs_replacement_fixture"] is False
    assert step["blocking_checks_for_completion"] == []
    assert plan["real_render_missing_strategy_types"] == ["narrative_assembly"]
    assert plan["replacement_fixture_needed_strategy_types"] == []
    assert plan["reference_evidence_ready_strategy_types"] == ["step_demonstration"]
    assert "--candidate-summary output/test/candidates.json" in plan["verification_commands"]["real_render_reference_report"]
    assert "--required-strategy step_demonstration" in plan["verification_commands"]["real_render_reference_report"]


def test_real_render_reports_close_execution_plan_missing_strategies() -> None:
    real_report = {
        "jobs": [
            {
                "job_id": "22222222-2222-2222-2222-222222222222",
                "source_name": "step.mp4",
                "status": "partial",
                "output_path": "step-out.mp4",
                "output_duration_sec": 8.0,
            },
            {
                "job_id": "33333333-3333-3333-3333-333333333333",
                "source_name": "narrative.mp4",
                "status": "partial",
                "output_path": "narrative-out.mp4",
                "output_duration_sec": 24.0,
            },
        ],
        "golden_case_rows": [
            {
                "case_id": "strategy_step_demo",
                "evaluation_job_id": "22222222-2222-2222-2222-222222222222",
                "source_name": "step.mp4",
                "status": "partial",
                "tags": ["strategy:step_demonstration", "real_world_fixture"],
                "required_checks_passed": True,
                "required_check_statuses": {
                    "strategy_pipeline_coverage": {
                        "passed": True,
                        "expected_strategy_types": ["step_demonstration"],
                    }
                },
            },
            {
                "case_id": "strategy_narrative_demo",
                "evaluation_job_id": "33333333-3333-3333-3333-333333333333",
                "source_name": "narrative.mp4",
                "status": "partial",
                "tags": ["strategy:narrative_assembly", "real_world_fixture"],
                "required_checks_passed": True,
                "required_check_statuses": {
                    "strategy_pipeline_coverage": {
                        "passed": True,
                        "expected_strategy_types": ["narrative_assembly"],
                    },
                    "strategy_review_preview_media_evidence": {
                        "passed": True,
                        "source_media_count": 3,
                        "readable_media_count": 3,
                        "media_backed_segment_count": 2,
                    },
                },
            },
        ],
    }

    plan = planner.build_strategy_fixture_execution_plan(
        _manifest(),
        manifest_path="manifest.json",
        real_render_reports=[real_report],
        real_render_report_paths=["output/test/real-report/batch_report.json"],
    )

    assert plan["completion_ready"] is True
    assert plan["real_render_missing_strategy_types"] == []
    assert plan["replacement_fixture_needed_strategy_types"] == []
    assert plan["real_render_report_ready_strategy_types"] == ["narrative_assembly", "step_demonstration"]
    assert plan["effective_real_render_ready_strategy_types"] == [
        "information_density",
        "narrative_assembly",
        "step_demonstration",
    ]
    assert plan["verification_commands"]["real_render_fixture_coverage"] == (
        "uv run python scripts/verify_strategy_real_render_fixtures.py"
        " --report output/test/real-report/batch_report.json"
    )
    by_strategy = {item["strategy_type"]: item for item in plan["strategy_plans"]}
    assert by_strategy["step_demonstration"]["source_status"] == "real_render_report_ready"
    assert by_strategy["step_demonstration"]["promotion_required_for_real_closure"] is False
    assert by_strategy["narrative_assembly"]["source_status"] == "real_render_report_ready"
    assert by_strategy["narrative_assembly"]["blocking_checks_for_completion"] == []


def test_build_strategy_fixture_execution_plan_reports_missing_manifest_strategy() -> None:
    manifest = _manifest()
    manifest["required_strategy_types"] = ["information_density", "event_highlight"]

    plan = planner.build_strategy_fixture_execution_plan(manifest, manifest_path="manifest.json")

    assert plan["ok"] is False
    assert plan["missing_manifest_strategy_types"] == ["event_highlight"]
    event = {item["strategy_type"]: item for item in plan["strategy_plans"]}["event_highlight"]
    assert event["agent_lane"] == "Fixture Candidate Agent"
    assert event["needs_replacement_fixture"] is True
    assert event["blocking_checks_for_completion"] == ["replacement_fixture_required", "real_render_fixture"]


def test_render_execution_plan_markdown_includes_commands() -> None:
    plan = planner.build_strategy_fixture_execution_plan(_manifest(), manifest_path="manifest.json")

    content = planner.render_execution_plan_markdown(plan)

    assert "# Strategy Fixture Execution Plan" in content
    assert "strategy_step_demo" in content
    assert "runtime_preflight_required" in content
    assert "promotion_required_for_real_closure" in content
    assert "real_render_reference_report" in content
    assert "verify_strategy_real_render_fixtures.py" in content
