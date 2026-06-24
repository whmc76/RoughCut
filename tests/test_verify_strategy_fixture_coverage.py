import json

from scripts import verify_strategy_fixture_coverage as verifier


def test_verify_strategy_fixture_coverage_passes_complete_strategy_set() -> None:
    result = verifier.verify_strategy_fixture_coverage(
        {
            "strategy_pipeline_coverage": {
                "evaluated_case_count": 5,
                "declared_strategy_types": list(verifier.DEFAULT_REQUIRED_STRATEGIES),
                "covered_strategy_types": list(verifier.DEFAULT_REQUIRED_STRATEGIES),
                "failed_case_ids": [],
            }
        }
    )

    assert result["ok"] is True
    assert result["missing_strategy_types"] == []


def test_verify_strategy_fixture_coverage_reports_missing_and_failed_cases() -> None:
    result = verifier.verify_strategy_fixture_coverage(
        {
            "strategy_pipeline_coverage": {
                "evaluated_case_count": 1,
                "declared_strategy_types": ["information_density"],
                "covered_strategy_types": ["information_density"],
                "failed_case_ids": ["case-bad"],
            }
        }
    )

    assert result["ok"] is False
    assert result["missing_strategy_types"] == [
        "step_demonstration",
        "experience_and_mood",
        "event_highlight",
        "narrative_assembly",
    ]
    assert result["failed_case_ids"] == ["case-bad"]


def test_verify_strategy_fixture_coverage_derives_from_case_rows() -> None:
    result = verifier.verify_strategy_fixture_coverage(
        {
            "golden_case_rows": [
                {
                    "case_id": "case-info",
                    "tags": ["strategy:information_density"],
                    "required_check_statuses": {
                        "strategy_pipeline_coverage": {
                            "passed": True,
                            "expected_strategy_types": ["information_density"],
                            "observed_strategy_types": ["information_density"],
                            "missing_strategy_types": [],
                        }
                    },
                }
            ]
        },
        required_strategies=["information_density"],
    )

    assert result["ok"] is True
    assert result["coverage_source"] == "derived"
    assert result["covered_strategy_types"] == ["information_density"]


def test_verify_strategy_fixture_coverage_observed_job_strategy_is_not_declared_coverage() -> None:
    result = verifier.verify_strategy_fixture_coverage(
        {
            "jobs": [
                {
                    "content_profile": {
                        "capability_orchestration": {
                            "strategy_type": "event_highlight",
                        }
                    }
                }
            ]
        },
        required_strategies=["event_highlight"],
    )

    assert result["ok"] is False
    assert result["observed_strategy_types"] == ["event_highlight"]
    assert result["covered_strategy_types"] == []
    assert result["undeclared_strategy_types"] == ["event_highlight"]


def test_load_batch_report_accepts_report_directory(tmp_path) -> None:
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    (report_dir / "batch_report.json").write_text(
        json.dumps({"strategy_pipeline_coverage": {"evaluated_case_count": 0}}),
        encoding="utf-8",
    )

    assert verifier.load_batch_report(report_dir) == {
        "strategy_pipeline_coverage": {"evaluated_case_count": 0}
    }
