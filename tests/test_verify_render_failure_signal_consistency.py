import json

from scripts import verify_render_failure_signal_consistency as verify


def _write_json(path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_verify_render_failure_signal_consistency_passes_on_aligned_report_dir(tmp_path) -> None:
    report_dir = tmp_path / "report"
    audit_dir = report_dir / "audit_packs"
    audit_dir.mkdir(parents=True)
    _write_json(
        report_dir / "batch_report.json",
        {
            "jobs": [
                {
                    "job_id": "job-1",
                    "source_name": "demo.mp4",
                    "render_diagnostics": {
                        "render_step": {
                            "status": "failed",
                            "reason": "ffmpeg_render_failed",
                            "issue_codes": ["ffmpeg_render_failed"],
                        }
                    },
                }
            ],
            "render_diagnostics_summary": {"failed_render_job_ids": ["job-1"]},
            "live_readiness": {
                "checks": {
                    "render_end_state_stability": {
                        "failed_render_job_ids": ["job-1"],
                    }
                }
            },
        },
    )
    _write_json(
        report_dir / "detailed_output_scorecard.json",
        {
            "jobs": [
                {
                    "job_id": "job-1",
                    "live_stage_scores": [{"stage": "render", "status": "fail"}],
                }
            ],
            "live_readiness": {"failed_checks": ["render_end_state_stability"]},
        },
    )
    _write_json(audit_dir / "demo.job-1.snapshot.json", {"job": {"id": "job-1", "status": "failed"}})

    result = verify.verify_render_failure_signal_consistency(report_dir)

    assert result["ok"] is True
    assert result["checks"]["batch_summary_matches_job_failures"] is True
    assert result["checks"]["live_readiness_matches_job_failures"] is True


def test_verify_render_failure_signal_consistency_detects_drift(tmp_path) -> None:
    report_dir = tmp_path / "report"
    report_dir.mkdir(parents=True)
    _write_json(
        report_dir / "batch_report.json",
        {
            "jobs": [
                {
                    "job_id": "job-1",
                    "source_name": "demo.mp4",
                    "render_diagnostics": {
                        "render_step": {
                            "status": "failed",
                            "reason": "render_ffprobe_failed",
                            "issue_codes": ["media_probe_failed"],
                        }
                    },
                }
            ],
            "render_diagnostics_summary": {"failed_render_job_ids": []},
            "live_readiness": {
                "checks": {
                    "render_end_state_stability": {
                        "failed_render_job_ids": ["job-x"],
                    }
                }
            },
        },
    )
    _write_json(
        report_dir / "detailed_output_scorecard.json",
        {
            "jobs": [
                {
                    "job_id": "job-1",
                    "live_stage_scores": [{"stage": "render", "status": "pass"}],
                }
            ],
            "live_readiness": {"failed_checks": []},
        },
    )

    result = verify.verify_render_failure_signal_consistency(report_dir)

    assert result["ok"] is False
    assert result["checks"]["batch_summary_matches_job_failures"] is False
    assert result["checks"]["live_readiness_matches_job_failures"] is False
    assert result["checks"]["scorecard_failed_checks_mentions_render_gate"] is False
