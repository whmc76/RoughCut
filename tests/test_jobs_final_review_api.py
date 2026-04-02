from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select


async def _seed_final_review_job(job_id: uuid.UUID) -> None:
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/final-review.mp4",
                source_name="final-review.mp4",
                status="needs_review",
                language="zh-CN",
                workflow_template="edc_tactical",
                enhancement_modes=["avatar_commentary"],
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="final_review",
                status="pending",
                metadata_={"detail": "等待审核成片后继续。"},
            )
        )
        await session.commit()


async def _seed_job_with_variant_bundle(job_id: uuid.UUID) -> None:
    from roughcut.db.models import Artifact, Job
    from roughcut.db.session import get_session_factory

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/bundle-preview.mp4",
                source_name="bundle-preview.mp4",
                status="done",
                language="zh-CN",
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="quality_assessment",
                data_json={
                    "score": 82.5,
                    "grade": "B",
                    "issue_codes": ["detail_blind", "generic_video_theme"],
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="variant_timeline_bundle",
                data_json={
                    "timeline_rules": {"lead_in_sec": 1.5},
                    "variants": {
                        "packaged": {
                            "media": {"path": "E:/tmp/bundle-preview.mp4"},
                            "subtitle_events": [
                                {
                                    "start_time": 0.0,
                                    "end_time": 2.5,
                                    "text": "FULL RAW SUBTITLE PAYLOAD SHOULD NOT LEAK",
                                },
                                {
                                    "start_time": 3.0,
                                    "end_time": 8.5,
                                    "text": "second event",
                                },
                            ],
                            "overlay_events": [],
                            "quality_checks": {
                                "subtitle_sync": {
                                    "status": "ok",
                                    "message": "bundle packaged timing is aligned",
                                    "warning_codes": [],
                                }
                            },
                        }
                    },
                },
            )
        )
        await session.commit()


async def _seed_job_with_legacy_render_outputs(job_id: uuid.UUID, *, packaged_srt_path: str) -> None:
    from roughcut.db.models import Artifact, Job
    from roughcut.db.session import get_session_factory

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/legacy-preview.mp4",
                source_name="legacy-preview.mp4",
                status="done",
                language="zh-CN",
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="quality_assessment",
                data_json={
                    "score": 88.0,
                    "grade": "B",
                    "issue_codes": ["generic_video_theme"],
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="render_outputs",
                data_json={
                    "packaged_mp4": "E:/tmp/legacy-preview.mp4",
                    "packaged_srt": packaged_srt_path,
                    "quality_checks": {
                        "subtitle_sync": {
                            "status": "ok",
                            "message": "legacy packaged timing is aligned",
                            "warning_codes": [],
                            "video_duration_sec": 8.5,
                        }
                    },
                },
            )
        )
        await session.commit()


async def _seed_job_ready_for_variant_timeline_rerender(job_id: uuid.UUID, *, with_warning: bool) -> None:
    from roughcut.db.models import Artifact, Job
    from roughcut.db.session import get_session_factory
    from roughcut.pipeline.orchestrator import create_job_steps

    async with get_session_factory()() as session:
        job = Job(
            id=job_id,
            source_path="jobs/demo/rerender-preview.mp4",
            source_name="rerender-preview.mp4",
            status="needs_review",
            language="zh-CN",
        )
        session.add(job)
        steps = create_job_steps(job_id)
        for step in steps:
            if step.step_name in {"render", "final_review", "platform_package"}:
                step.status = "pending" if step.step_name != "render" else "done"
            else:
                step.status = "done"
        final_review_step = next(step for step in steps if step.step_name == "final_review")
        final_review_step.status = "pending"
        final_review_step.metadata_ = {"detail": "等待审核成片后继续。"}
        for step in steps:
            session.add(step)

        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="render_outputs",
                data_json={
                    "packaged_mp4": "E:/tmp/rerender-preview.mp4",
                    "packaged_srt": "E:/tmp/missing_packaged.srt" if with_warning else "",
                    "quality_checks": {
                        "subtitle_sync": {
                            "status": "warning" if with_warning else "ok",
                            "message": "legacy packaged timing is off" if with_warning else "legacy packaged timing is aligned",
                            "warning_codes": ["subtitle_timing_gap"] if with_warning else [],
                            "duration_gap_sec": 6.2 if with_warning else 0.0,
                            "video_duration_sec": 42.0,
                        }
                    },
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="variant_timeline_bundle",
                data_json={
                    "timeline_rules": {"source": "legacy_render_outputs" if with_warning else "render"},
                    "variants": {
                        "packaged": {
                            "media": {"path": "E:/tmp/rerender-preview.mp4"},
                            "subtitle_events": [] if with_warning else [{"start_time": 0.0, "end_time": 2.0, "text": "ok"}],
                        }
                    },
                    "validation": {
                        "status": "warning" if with_warning else "ok",
                        "issues": ["packaged: sync metrics indicate a large subtitle gap"] if with_warning else [],
                    },
                },
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_final_review_endpoint_approves_and_resumes_job(client: AsyncClient):
    from roughcut.db.models import Job, JobStep, ReviewAction
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    await _seed_final_review_job(job_id)

    response = await client.post(f"/api/v1/jobs/{job_id}/final-review", json={"decision": "approve"})
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "job_id": str(job_id),
        "decision": "approve",
        "job_status": "processing",
        "review_step_status": "done",
        "rerun_triggered": False,
        "note": None,
    }

    async with get_session_factory()() as session:
        job = await session.get(Job, job_id)
        step = (
            await session.execute(
                select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "final_review")
            )
        ).scalar_one()
        action = (
            await session.execute(select(ReviewAction).where(ReviewAction.job_id == job_id))
        ).scalar_one()

    assert job is not None
    assert job.status == "processing"
    assert step.status == "done"
    assert step.finished_at is not None
    assert step.metadata_["approved_via"] == "web"
    assert action.target_type == "final_review"
    assert action.action == "approve"
    assert action.override_text is None


@pytest.mark.asyncio
async def test_final_review_endpoint_rejects_without_note_and_records_freeform_feedback(client: AsyncClient):
    from roughcut.db.models import Job, JobStep, ReviewAction
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    await _seed_final_review_job(job_id)

    missing_note = await client.post(f"/api/v1/jobs/{job_id}/final-review", json={"decision": "reject"})
    assert missing_note.status_code == 400
    assert "note is required" in missing_note.text

    note = "整体观感再确认一次"
    response = await client.post(
        f"/api/v1/jobs/{job_id}/final-review",
        json={"decision": "reject", "note": note},
    )
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "job_id": str(job_id),
        "decision": "reject",
        "job_status": "needs_review",
        "review_step_status": "pending",
        "rerun_triggered": False,
        "note": note,
    }

    async with get_session_factory()() as session:
        job = await session.get(Job, job_id)
        step = (
            await session.execute(
                select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "final_review")
            )
        ).scalar_one()
        action = (
            await session.execute(select(ReviewAction).where(ReviewAction.job_id == job_id))
        ).scalar_one()

    assert job is not None
    assert job.status == "needs_review"
    assert step.status == "pending"
    assert step.started_at is not None
    assert step.metadata_["latest_feedback"] == note
    assert step.metadata_["feedback_history"][-1]["text"] == note
    assert action.target_type == "final_review"
    assert action.action == "reject"
    assert action.override_text == note


@pytest.mark.asyncio
async def test_job_detail_quality_summary_prefers_variant_bundle_timing_summary(client: AsyncClient):
    job_id = uuid.uuid4()
    await _seed_job_with_variant_bundle(job_id)

    response = await client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["quality_summary"] == "B 82.5 · 2 个扣分项 · packaged 2 条字幕 · 0.0-8.5s"
    assert "FULL RAW SUBTITLE PAYLOAD" not in data["quality_summary"]


@pytest.mark.asyncio
async def test_job_detail_quality_summary_falls_back_to_legacy_render_outputs_timing_summary(client: AsyncClient, tmp_path):
    job_id = uuid.uuid4()
    packaged_srt = tmp_path / "legacy_packaged.srt"
    packaged_srt.write_text(
        "\n".join(
            [
                "1",
                "00:00:01,000 --> 00:00:03,000",
                "legacy-start",
                "",
                "2",
                "00:00:04,000 --> 00:00:08,500",
                "legacy-end",
                "",
            ]
        ),
        encoding="utf-8",
    )
    await _seed_job_with_legacy_render_outputs(job_id, packaged_srt_path=str(packaged_srt))

    response = await client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["quality_summary"] == "B 88.0 · 1 个扣分项 · packaged 2 条字幕 · 1.0-8.5s"


@pytest.mark.asyncio
async def test_job_detail_quality_summary_includes_variant_timeline_warning_for_legacy_outputs(client: AsyncClient):
    job_id = uuid.uuid4()
    await _seed_job_with_legacy_render_outputs(job_id, packaged_srt_path="E:/tmp/missing_legacy_packaged.srt")

    response = await client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()
    assert "时间轴告警 1 项" in data["quality_summary"]


@pytest.mark.asyncio
async def test_final_review_variant_timeline_rerender_resets_render_chain(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, JobStep, ReviewAction
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    await _seed_job_ready_for_variant_timeline_rerender(job_id, with_warning=True)

    response = await client.post(f"/api/v1/jobs/{job_id}/final-review/rerender-variant-timeline")
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "job_id": str(job_id),
        "job_status": "processing",
        "rerun_steps": ["render", "final_review", "platform_package"],
        "validation_status": "warning",
        "validation_issue_count": 1,
    }

    async with get_session_factory()() as session:
        job = await session.get(Job, job_id)
        steps = (
            await session.execute(select(JobStep).where(JobStep.job_id == job_id).order_by(JobStep.id.asc()))
        ).scalars().all()
        artifacts = (
            await session.execute(select(Artifact).where(Artifact.job_id == job_id))
        ).scalars().all()
        action = (
            await session.execute(select(ReviewAction).where(ReviewAction.job_id == job_id))
        ).scalar_one()

    assert job is not None
    assert job.status == "processing"
    step_map = {step.step_name: step for step in steps}
    assert step_map["render"].status == "pending"
    assert step_map["final_review"].status == "pending"
    assert step_map["platform_package"].status == "pending"
    assert "时间轴对齐告警触发重渲染" in str((step_map["render"].metadata_ or {}).get("detail") or "")
    assert not any(artifact.artifact_type == "render_outputs" for artifact in artifacts)
    assert not any(artifact.artifact_type == "variant_timeline_bundle" for artifact in artifacts)
    assert action.target_type == "final_review"
    assert action.action == "rerender_variant_timeline"


@pytest.mark.asyncio
async def test_final_review_variant_timeline_rerender_rejects_jobs_without_warning(client: AsyncClient):
    job_id = uuid.uuid4()
    await _seed_job_ready_for_variant_timeline_rerender(job_id, with_warning=False)

    response = await client.post(f"/api/v1/jobs/{job_id}/final-review/rerender-variant-timeline")
    assert response.status_code == 409
    assert "No variant timeline warning detected" in response.text
