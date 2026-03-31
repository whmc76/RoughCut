from __future__ import annotations

from datetime import datetime, timezone

from roughcut.recovery.job_index_restore import ObjectSummary, infer_recovered_job


def _ts(day: int) -> datetime:
    return datetime(2026, 3, day, 12, 0, tzinfo=timezone.utc)


def test_infer_completed_job_uses_source_name_and_marks_done():
    job = infer_recovered_job(
        "0096943d-7768-48fb-9ee6-ee6752af487e",
        [
            ObjectSummary(key="0096943d-7768-48fb-9ee6-ee6752af487e/20260301-162038.mp4", size_bytes=10, last_modified=_ts(16)),
            ObjectSummary(key="0096943d-7768-48fb-9ee6-ee6752af487e/audio.wav", size_bytes=11, last_modified=_ts(16)),
            ObjectSummary(key="0096943d-7768-48fb-9ee6-ee6752af487e/output.mp4", size_bytes=12, last_modified=_ts(17)),
            ObjectSummary(key="0096943d-7768-48fb-9ee6-ee6752af487e/output_plain.mp4", size_bytes=13, last_modified=_ts(17)),
        ],
        bucket="jobs",
    )

    assert job.source_name == "20260301-162038.mp4"
    assert job.source_path == "s3://jobs/0096943d-7768-48fb-9ee6-ee6752af487e/20260301-162038.mp4"
    assert job.status == "done"
    assert job.created_at == _ts(16)
    assert job.updated_at == _ts(17)
    assert job.enhancement_modes == []
    assert set(job.step_statuses.values()) == {"done"}


def test_infer_failed_job_without_source_uses_fallback_terminal_name():
    job = infer_recovered_job(
        "07255c55-99ea-44d7-802b-d874153f2c7d",
        [
            ObjectSummary(key="07255c55-99ea-44d7-802b-d874153f2c7d/audio.wav", size_bytes=11, last_modified=_ts(18)),
        ],
        bucket="jobs",
    )

    assert job.source_name == "recovered-07255c55-99ea-44d7-802b-d874153f2c7d.mp4"
    assert job.source_path == "s3://jobs/07255c55-99ea-44d7-802b-d874153f2c7d/recovered-07255c55-99ea-44d7-802b-d874153f2c7d.mp4"
    assert job.status == "failed"
    assert job.error_message == "Recovered from object storage without original source object"
    assert job.step_statuses["probe"] == "done"
    assert job.step_statuses["extract_audio"] == "done"
    assert job.step_statuses["transcribe"] == "failed"


def test_infer_avatar_outputs_enable_avatar_commentary_mode():
    job = infer_recovered_job(
        "00aebbdd-2d0c-4db7-a855-134f713295d2",
        [
            ObjectSummary(key="00aebbdd-2d0c-4db7-a855-134f713295d2/audio.wav", size_bytes=11, last_modified=_ts(18)),
            ObjectSummary(key="00aebbdd-2d0c-4db7-a855-134f713295d2/output.mp4", size_bytes=12, last_modified=_ts(19)),
            ObjectSummary(key="00aebbdd-2d0c-4db7-a855-134f713295d2/output_avatar.mp4", size_bytes=13, last_modified=_ts(19)),
            ObjectSummary(key="00aebbdd-2d0c-4db7-a855-134f713295d2/output_plain.mp4", size_bytes=14, last_modified=_ts(19)),
        ],
        bucket="jobs",
    )

    assert job.status == "done"
    assert job.enhancement_modes == ["avatar_commentary"]
