from pathlib import Path

from scripts import compare_live_batch_runs as compare


def test_aggregate_summary_includes_live_readiness_gate_details() -> None:
    summary = compare._aggregate_summary(
        {
            "jobs": [],
            "success_count": 1,
            "failed_count": 0,
            "live_readiness": {
                "gate_passed": False,
                "status": "blocked",
                "checks": {
                    "required_checks_contract": {"passed": False},
                    "risk_alignment_contract": {"passed": True},
                },
                "failure_reasons": ["required_checks 未通过"],
            },
        },
        {"jobs": []},
        {"aggregate_dimension_scores": []},
    )

    assert summary["live_gate_passed"] is False
    assert summary["live_status"] == "blocked"
    assert summary["live_failed_checks"] == ["required_checks_contract"]
    assert summary["live_failure_reasons"] == ["required_checks 未通过"]


def test_render_markdown_includes_live_gate_deltas() -> None:
    content = compare.render_markdown(
        {
            "baseline_report": str(Path("baseline.json")),
            "candidate_report": str(Path("candidate.json")),
            "baseline_summary": {
                "success_count": 1,
                "failed_count": 0,
                "manual_review_required_count": 0,
                "critical_pollution_count": 0,
                "live_gate_passed": True,
                "live_status": "pass",
                "live_failed_checks": [],
                "overall_video_quality": None,
                "subtitle_quality": None,
                "multi_platform_package": None,
                "avatar": None,
                "ai_effects": None,
                "subtitle_effects": None,
                "editing": None,
            },
            "candidate_summary": {
                "success_count": 1,
                "failed_count": 0,
                "manual_review_required_count": 0,
                "critical_pollution_count": 0,
                "live_gate_passed": False,
                "live_status": "blocked",
                "live_failed_checks": ["required_checks_contract"],
                "overall_video_quality": None,
                "subtitle_quality": None,
                "multi_platform_package": None,
                "avatar": None,
                "ai_effects": None,
                "subtitle_effects": None,
                "editing": None,
            },
            "per_source": [],
        }
    )

    assert "- live_gate_passed: True -> False" in content
    assert "- live_status: pass -> blocked" in content
    assert "- live_failed_checks: - -> required_checks_contract" in content
