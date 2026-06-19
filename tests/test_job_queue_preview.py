from __future__ import annotations

import uuid

from roughcut.api.jobs import _collapse_jobs_for_primary_queue, _reconcile_job_preview_terminal_status
from roughcut.db.models import Artifact, Job, JobStep


def _build_job(*, source_name: str, file_hash: str | None, status: str) -> Job:
    job = Job(
        id=uuid.uuid4(),
        source_path=f"E:/watch/{source_name}",
        source_name=source_name,
        file_hash=file_hash,
        status=status,
        workflow_template="edc_tactical",
        output_dir="E:/output/provider_compare_manual",
        job_flow_mode="auto",
        workflow_mode="standard_edit",
        enhancement_modes=[],
        platform_targets_json=[],
        language="zh-CN",
    )
    job.queue_task_kind = "edit"
    return job


def test_collapse_jobs_for_primary_queue_keeps_latest_attempt_per_family() -> None:
    latest = _build_job(source_name="noc_mt34_90s.mp4", file_hash="hash-1", status="failed")
    older = _build_job(source_name="noc_mt34_90s.mp4", file_hash="hash-1", status="cancelled")
    other = _build_job(source_name="noc_mt34_25s.mp4", file_hash="hash-2", status="done")

    collapsed = _collapse_jobs_for_primary_queue([latest, older, other])

    assert collapsed == [latest, other]


def test_reconcile_job_preview_terminal_status_prefers_successful_outputs_over_stale_failed_status() -> None:
    job = _build_job(source_name="noc_mt34_90s.mp4", file_hash="hash-1", status="failed")
    job.error_message = "stale failure"
    job.steps = [
        JobStep(job_id=job.id, step_name="avatar_commentary", status="failed"),
        JobStep(job_id=job.id, step_name="edit_plan", status="failed"),
        JobStep(job_id=job.id, step_name="render", status="done"),
        JobStep(job_id=job.id, step_name="platform_package", status="pending"),
    ]
    job.artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="render_outputs",
            data_json={"packaged_mp4": "E:/output/20260614_NOC_MT34_手感展示_横版_成片.mp4"},
        ),
        Artifact(
            job_id=job.id,
            artifact_type="platform_packaging_md",
            storage_path="E:/output/20260614_NOC_MT34_手感展示_横版_成片_publish.md",
        ),
    ]

    _reconcile_job_preview_terminal_status(job)

    assert job.status == "done"
    assert job.error_message is None


def test_reconcile_job_preview_terminal_status_ignores_stale_platform_package_step() -> None:
    job = _build_job(source_name="noc_mt34_90s.mp4", file_hash="hash-1", status="failed")
    job.error_message = "stale publication wait"
    job.steps = [
        JobStep(job_id=job.id, step_name="render", status="done"),
        JobStep(job_id=job.id, step_name="platform_package", status="pending"),
    ]
    job.artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="render_outputs",
            data_json={"packaged_mp4": "E:/output/20260614_NOC_MT34_手感展示_横版_成片.mp4"},
        ),
    ]

    _reconcile_job_preview_terminal_status(job)

    assert job.status == "done"
    assert job.error_message is None
