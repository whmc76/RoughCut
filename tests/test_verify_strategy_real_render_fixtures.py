from scripts import verify_strategy_real_render_fixtures as verifier


def _row(
    strategy: str,
    *,
    generated: bool = False,
    candidate: bool = False,
    real_world: bool = False,
    passed: bool = True,
    media_preview: bool = False,
) -> dict:
    tags = [f"strategy:{strategy}", "strategy_fixture"]
    if generated:
        tags.append("generated_fixture")
    if candidate:
        tags.append("strategy_candidate")
    if real_world:
        tags.append("real_world_fixture")
    statuses = {
        "strategy_pipeline_coverage": {
            "passed": passed,
            "expected_strategy_types": [strategy],
            "observed_strategy_types": [strategy] if passed else [],
            "missing_strategy_types": [] if passed else [strategy],
        }
    }
    if media_preview:
        statuses["strategy_review_preview_media_evidence"] = {
            "passed": passed,
            "expected_strategy_types": [strategy],
            "strategy_type": strategy,
            "source_media_count": 2,
            "readable_media_count": 2,
            "media_backed_segment_count": 2,
        }
    return {
        "case_id": f"case-{strategy}",
        "tags": tags,
        "evaluation_job_id": f"job-{strategy}",
        "status": "partial" if passed else "failed",
        "required_checks_passed": passed,
        "required_check_statuses": statuses,
    }


def _job(strategy: str, *, duration: float = 3.0, output_path: str = "E:/out.mp4") -> dict:
    return {
        "job_id": f"job-{strategy}",
        "source_name": f"{strategy}.mp4",
        "status": "partial",
        "output_path": output_path,
        "output_duration_sec": duration,
    }


def test_verify_strategy_real_render_fixtures_accepts_real_render_case() -> None:
    result = verifier.verify_strategy_real_render_fixtures(
        [
            {
                "golden_case_rows": [_row("event_highlight")],
                "jobs": [_job("event_highlight")],
            }
        ],
        required_strategies=["event_highlight"],
    )

    assert result["ok"] is True
    assert result["covered_strategy_types"] == ["event_highlight"]
    assert result["missing_strategy_types"] == []
    assert result["evidence_by_strategy"]["event_highlight"][0]["output_duration_sec"] == 3.0
    assert result["media_backed_preview_validation"]["required"] is False
    assert result["media_backed_preview_validation"]["ok"] is True


def test_verify_strategy_real_render_fixtures_rejects_generated_fixture() -> None:
    result = verifier.verify_strategy_real_render_fixtures(
        [
            {
                "golden_case_rows": [_row("event_highlight", generated=True)],
                "jobs": [_job("event_highlight")],
            }
        ],
        required_strategies=["event_highlight"],
    )

    assert result["ok"] is False
    assert result["missing_strategy_types"] == ["event_highlight"]
    assert result["rejected_generated_case_ids"] == ["case-event_highlight"]
    assert result["evidence_by_strategy"]["event_highlight"] == []


def test_verify_strategy_real_render_fixtures_rejects_unpromoted_strategy_candidate() -> None:
    result = verifier.verify_strategy_real_render_fixtures(
        [
            {
                "golden_case_rows": [_row("step_demonstration", candidate=True)],
                "jobs": [_job("step_demonstration")],
            }
        ],
        required_strategies=["step_demonstration"],
    )

    assert result["ok"] is False
    assert result["missing_strategy_types"] == ["step_demonstration"]
    assert result["rejected_incomplete_cases"] == [
        {
            "case_id": "case-step_demonstration",
            "job_id": "job-step_demonstration",
            "strategy_types": ["step_demonstration"],
            "reasons": ["unpromoted_strategy_candidate"],
        }
    ]


def test_verify_strategy_real_render_fixtures_accepts_promoted_strategy_candidate() -> None:
    result = verifier.verify_strategy_real_render_fixtures(
        [
            {
                "golden_case_rows": [_row("step_demonstration", candidate=True, real_world=True)],
                "jobs": [_job("step_demonstration")],
            }
        ],
        required_strategies=["step_demonstration"],
    )

    assert result["ok"] is True
    assert result["covered_strategy_types"] == ["step_demonstration"]


def test_verify_strategy_real_render_fixtures_reports_incomplete_real_case() -> None:
    result = verifier.verify_strategy_real_render_fixtures(
        [
            {
                "golden_case_rows": [_row("narrative_assembly")],
                "jobs": [_job("narrative_assembly", duration=0.0, output_path="")],
            }
        ],
        required_strategies=["narrative_assembly"],
    )

    assert result["ok"] is False
    assert result["missing_strategy_types"] == ["narrative_assembly"]
    assert result["rejected_incomplete_cases"] == [
        {
            "case_id": "case-narrative_assembly",
            "job_id": "job-narrative_assembly",
            "strategy_types": ["narrative_assembly"],
            "reasons": ["missing_output_path", "missing_output_duration"],
        }
    ]


def test_verify_strategy_real_render_fixtures_tracks_missing_real_narrative_media_preview() -> None:
    result = verifier.verify_strategy_real_render_fixtures(
        [
            {
                "golden_case_rows": [_row("narrative_assembly")],
                "jobs": [_job("narrative_assembly")],
            }
        ],
        required_strategies=["narrative_assembly"],
    )

    assert result["ok"] is True
    preview = result["media_backed_preview_validation"]
    assert preview["required"] is True
    assert preview["ok"] is False
    assert preview["evidence"] == []
    assert preview["rejected_cases"] == [
        {
            "case_id": "case-narrative_assembly",
            "job_id": "job-narrative_assembly",
            "reasons": [
                "missing_strategy_review_preview_media_evidence",
                "missing_source_media_evidence",
                "missing_readable_media_evidence",
                "missing_media_backed_preview_segments",
            ],
        }
    ]


def test_verify_strategy_real_render_fixtures_accepts_real_narrative_media_preview() -> None:
    result = verifier.verify_strategy_real_render_fixtures(
        [
            {
                "golden_case_rows": [_row("narrative_assembly", media_preview=True)],
                "jobs": [_job("narrative_assembly")],
            }
        ],
        required_strategies=["narrative_assembly"],
    )

    preview = result["media_backed_preview_validation"]
    assert result["ok"] is True
    assert preview["ok"] is True
    assert preview["evidence"][0]["source_media_count"] == 2
    assert preview["evidence"][0]["media_backed_segment_count"] == 2


def test_verify_strategy_real_render_fixtures_requires_required_checks_and_pipeline_coverage() -> None:
    result = verifier.verify_strategy_real_render_fixtures(
        [
            {
                "golden_case_rows": [_row("step_demonstration", passed=False)],
                "jobs": [_job("step_demonstration")],
            }
        ],
        required_strategies=["step_demonstration"],
    )

    assert result["ok"] is False
    assert result["rejected_incomplete_cases"][0]["reasons"] == [
        "non_passing_status=failed",
        "required_checks_not_passed",
        "strategy_pipeline_coverage_not_passed",
    ]
