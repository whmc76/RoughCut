from datetime import datetime, timezone

from scripts import list_final_evidence_candidates as candidates


def test_iso8601_formats_datetime() -> None:
    value = datetime(2026, 6, 12, 10, 11, 12, tzinfo=timezone.utc)

    assert candidates._iso8601(value) == "2026-06-12T10:11:12+00:00"


def test_render_text_summarizes_both_candidate_surfaces() -> None:
    content = candidates._render_text(
        manual_editor_candidates=[
            {
                "job_id": "job-1",
                "source_name": "demo.mp4",
                "job_status": "done",
                "readiness_status": "ready",
                "can_edit": True,
            }
        ],
        render_failure_candidates=[
            {
                "job_id": "job-2",
                "source_name": "fail.mp4",
                "artifact_type": "render_runtime_diagnostics",
                "matched_reason": "ffmpeg_render_failed",
            }
        ],
    )

    assert "## manual_editor_candidates count=1" in content
    assert "job-1 | demo.mp4 | job_status=done | readiness=ready | can_edit=True" in content
    assert "## render_failure_candidates count=1" in content
    assert "job-2 | fail.mp4 | artifact=render_runtime_diagnostics | matched_reason=ffmpeg_render_failed" in content
