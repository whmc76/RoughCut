from __future__ import annotations

from scripts.build_strategy_real_render_reference_report import build_reference_report, manifest_from_candidate_summary


def test_build_reference_report_accepts_promoted_real_world_fixture() -> None:
    manifest = {
        "jobs": [
            {
                "case_id": "strategy_event_case",
                "reference_job_id": "job-1",
                "required_checks": ["strategy_pipeline_coverage"],
                "risk_hints": {"expected_strategy_type": "event_highlight"},
                "tags": ["strategy:event_highlight", "strategy_candidate", "real_world_fixture"],
            }
        ]
    }
    records = {
        "job-1": {
            "source_name": "event.mp4",
            "output_path": "out.mp4",
            "output_duration_sec": 3.2,
            "observed_strategy_types": ["event_highlight"],
        }
    }

    report = build_reference_report(manifest=manifest, job_records=records)

    assert report["job_count"] == 1
    assert report["failed_count"] == 0
    row = report["golden_case_rows"][0]
    assert row["required_checks_passed"] is True
    assert row["required_check_statuses"]["strategy_pipeline_coverage"]["passed"] is True
    assert report["jobs"][0]["output_duration_sec"] == 3.2


def test_build_reference_report_rejects_unpromoted_and_mismatched_strategy() -> None:
    manifest = {
        "jobs": [
            {
                "case_id": "unpromoted",
                "reference_job_id": "job-1",
                "tags": ["strategy:event_highlight", "strategy_candidate"],
            },
            {
                "case_id": "mismatched",
                "reference_job_id": "job-2",
                "required_checks": ["strategy_pipeline_coverage"],
                "risk_hints": {"expected_strategy_type": "narrative_assembly"},
                "tags": ["strategy:narrative_assembly", "strategy_candidate", "real_world_fixture"],
            },
        ]
    }
    records = {
        "job-1": {
            "source_name": "event.mp4",
            "output_path": "out.mp4",
            "output_duration_sec": 3.2,
            "observed_strategy_types": ["event_highlight"],
        },
        "job-2": {
            "source_name": "narrative.mp4",
            "output_path": "out2.mp4",
            "output_duration_sec": 4.0,
            "observed_strategy_types": ["information_density"],
        },
    }

    report = build_reference_report(manifest=manifest, job_records=records)

    assert report["job_count"] == 1
    assert report["failed_count"] == 1
    assert report["golden_case_rows"][0]["case_id"] == "mismatched"
    assert report["golden_case_rows"][0]["required_checks_passed"] is False
    assert report["golden_case_rows"][0]["required_checks_failed"] == ["strategy_pipeline_coverage"]


def test_manifest_from_candidate_summary_adds_reference_only_ready_candidates() -> None:
    summary = {
        "schema": "strategy_fixture_candidates.v1",
        "required_strategy_types": ["experience_and_mood", "narrative_assembly"],
        "selected_candidates": {
            "experience_and_mood": [
                {
                    "job_id": "job-experience",
                    "real_render_readiness": {"ready": True},
                    "golden_manifest_case": {
                        "case_id": "experience_case",
                        "required_checks": ["strategy_pipeline_coverage"],
                        "tags": ["strategy:experience_and_mood", "strategy_candidate"],
                    },
                }
            ],
            "narrative_assembly": [
                {
                    "job_id": "job-narrative",
                    "real_render_readiness": {"ready": False},
                    "golden_manifest_case": {
                        "case_id": "narrative_case",
                        "tags": ["strategy:narrative_assembly", "strategy_candidate"],
                    },
                }
            ],
        },
    }

    manifest = manifest_from_candidate_summary(summary)

    assert len(manifest["jobs"]) == 1
    job = manifest["jobs"][0]
    assert job["case_id"] == "experience_case"
    assert job["reference_job_id"] == "job-experience"
    assert "real_world_fixture" in job["tags"]
    assert "reference_evidence_only" in job["tags"]
    assert job["risk_hints"]["expected_strategy_type"] == "experience_and_mood"
