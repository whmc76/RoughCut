from __future__ import annotations

import json

from roughcut.pipeline.live_readiness import build_live_readiness_summary, collect_job_issue_codes, load_live_readiness_snapshot


def _job(
    *,
    source_name: str,
    status: str = "done",
    quality_score: float = 85.0,
    output_path: str = "F:/out/final.mp4",
    output_duration_sec: float = 10.0,
    quality_issue_codes: list[str] | None = None,
    live_stage_validations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "source_name": source_name,
        "status": status,
        "quality_score": quality_score,
        "output_path": output_path,
        "output_duration_sec": output_duration_sec,
        "quality_issue_codes": quality_issue_codes or [],
        "live_stage_validations": live_stage_validations
        or [
            {"stage": "transcribe", "status": "pass", "issue_codes": []},
            {"stage": "subtitle_postprocess", "status": "pass", "issue_codes": []},
            {"stage": "content_profile", "status": "pass", "issue_codes": []},
            {"stage": "render", "status": "pass", "issue_codes": []},
            {"stage": "final_review", "status": "pass", "issue_codes": []},
            {"stage": "platform_package", "status": "pass", "issue_codes": []},
        ],
    }


def test_collect_job_issue_codes_merges_quality_and_stage_codes():
    codes = collect_job_issue_codes(
        {
            "quality_issue_codes": ["detail_blind", "generic_summary"],
            "live_stage_validations": [
                {"stage": "render", "status": "fail", "issue_codes": ["subtitle_sync_issue", "generic_summary"]}
            ],
        }
    )

    assert codes == ["detail_blind", "generic_summary", "subtitle_sync_issue"]


def test_build_live_readiness_summary_passes_for_three_stable_runs():
    current = {
        "jobs": [_job(source_name="golden-a.mp4"), _job(source_name="golden-b.mp4", quality_score=82.0)],
    }
    previous = [
        {"jobs": [_job(source_name="golden-a.mp4", quality_score=88.0), _job(source_name="golden-b.mp4", quality_score=81.0)]},
        {"jobs": [_job(source_name="golden-a.mp4", quality_score=84.0), _job(source_name="golden-b.mp4", quality_score=83.0)]},
    ]

    readiness = build_live_readiness_summary(
        current,
        golden_source_names=["golden-a.mp4", "golden-b.mp4"],
        previous_summaries=previous,
    )

    assert readiness.gate_passed is True
    assert readiness.ready_for_live_dry_run is True
    assert readiness.stable_run_count == 3
    assert readiness.failure_reasons == []


def test_build_live_readiness_summary_flags_false_success_and_unstable_runs():
    current = {
        "jobs": [
            _job(
                source_name="golden-a.mp4",
                output_path="",
                live_stage_validations=[
                    {"stage": "render", "status": "fail", "issue_codes": ["subtitle_sync_issue"]},
                ],
            ),
            _job(source_name="golden-b.mp4", status="failed", quality_score=72.0, quality_issue_codes=["render_failed"]),
        ],
    }

    readiness = build_live_readiness_summary(
        current,
        golden_source_names=["golden-a.mp4", "golden-b.mp4"],
        previous_summaries=[],
    )

    assert readiness.gate_passed is False
    assert "golden-a.mp4" in readiness.false_success_jobs
    assert readiness.checks["false_successes"]["passed"] is False
    assert readiness.checks["stable_runs"]["passed"] is False
    assert readiness.issue_code_counts["subtitle_sync_issue"] == 1
    assert readiness.issue_code_counts["render_failed"] == 1


def test_load_live_readiness_snapshot_reads_batch_report(tmp_path):
    report_path = tmp_path / "batch_report.json"
    report_path.write_text(
        json.dumps(
            {
                "created_at": "2026-04-17T00:00:00+00:00",
                "live_readiness": {
                    "status": "pass",
                    "gate_passed": True,
                    "summary": "满足 live dry run 准入门槛",
                    "stable_run_count": 3,
                    "required_stable_runs": 3,
                    "failure_reasons": [],
                    "warning_reasons": ["warning-a"],
                    "golden_job_count": 4,
                    "evaluated_job_count": 4,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    snapshot = load_live_readiness_snapshot(report_path)

    assert snapshot["status"] == "pass"
    assert snapshot["gate_passed"] is True
    assert snapshot["stable_run_count"] == 3
    assert snapshot["warning_reasons"] == ["warning-a"]
    assert snapshot["report_created_at"] == "2026-04-17T00:00:00+00:00"


def test_load_live_readiness_snapshot_returns_unknown_when_report_missing(tmp_path):
    snapshot = load_live_readiness_snapshot(tmp_path / "missing.json")

    assert snapshot["status"] == "unknown"
    assert snapshot["gate_passed"] is False
    assert snapshot["detail"] == "batch_report.json not found"
