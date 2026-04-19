from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select


async def _seed_job_for_rerun_api(
    job_id: uuid.UUID,
    *,
    quality_artifact: dict[str, Any] | None = None,
    step_overrides: dict[str, str] | None = None,
    extra_artifacts: list[dict[str, Any]] | None = None,
) -> None:
    from roughcut.db.models import Artifact, Job
    from roughcut.db.session import get_session_factory
    from roughcut.pipeline.orchestrator import create_job_steps

    overrides = step_overrides or {}
    async with get_session_factory()() as session:
        job = Job(
            id=job_id,
            source_path="jobs/demo/rerun-api.mp4",
            source_name="rerun-api.mp4",
            status="done",
            language="zh-CN",
        )
        session.add(job)
        for step in create_job_steps(job_id):
            step.status = overrides.get(step.step_name, "done")
            session.add(step)

        if quality_artifact is not None:
            session.add(
                Artifact(
                    job_id=job_id,
                    artifact_type="quality_assessment",
                    data_json=quality_artifact,
                )
            )

        for artifact in extra_artifacts or []:
            session.add(
                Artifact(
                    job_id=job_id,
                    artifact_type=str(artifact["artifact_type"]),
                    data_json=artifact.get("data_json"),
                    storage_path=artifact.get("storage_path"),
                )
            )
        await session.commit()


@pytest.mark.asyncio
async def test_job_rerun_endpoint_resolves_explicit_issue_code_via_latest_quality_assessment(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, JobStep, ReviewAction
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    await _seed_job_for_rerun_api(
        job_id,
        quality_artifact={
            "score": 72.0,
            "grade": "C",
            "issue_codes": ["detail_blind", "generic_video_theme"],
            "recommended_rerun_step": "content_profile",
            "recommended_rerun_steps": [
                "content_profile",
                "ai_director",
                "avatar_commentary",
                "edit_plan",
                "render",
                "final_review",
                "platform_package",
            ],
        },
        extra_artifacts=[
            {
                "artifact_type": "content_profile_final",
                "data_json": {"summary": "过于泛化的摘要"},
            }
        ],
    )

    response = await client.post(
        f"/api/v1/jobs/{job_id}/rerun",
        json={"issue_code": "detail_blind", "note": "摘要要补足具体参数"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "job_id": str(job_id),
        "job_status": "processing",
        "rerun_start_step": "content_profile",
        "rerun_steps": [
            "content_profile",
            "ai_director",
            "avatar_commentary",
            "edit_plan",
            "render",
            "final_review",
            "platform_package",
        ],
        "issue_codes": ["detail_blind"],
        "note": "摘要要补足具体参数",
        "detail": "已接受重跑请求，等待调度器从 content_profile 接管。问题：detail_blind；链路：content_profile -> ai_director -> avatar_commentary -> edit_plan -> render -> final_review -> platform_package。备注：摘要要补足具体参数",
    }

    async with get_session_factory()() as session:
        job = await session.get(Job, job_id)
        steps = (
            await session.execute(select(JobStep).where(JobStep.job_id == job_id).order_by(JobStep.id.asc()))
        ).scalars().all()
        artifacts = (
            await session.execute(select(Artifact).where(Artifact.job_id == job_id).order_by(Artifact.id.asc()))
        ).scalars().all()
        action = (
            await session.execute(select(ReviewAction).where(ReviewAction.job_id == job_id))
        ).scalar_one()

    assert job is not None
    assert job.status == "processing"
    step_map = {step.step_name: step for step in steps}
    assert step_map["probe"].status == "done"
    assert step_map["content_profile"].status == "pending"
    assert step_map["render"].status == "pending"
    assert step_map["content_profile"].metadata_["rerun_requested_via"] == "web"
    assert step_map["content_profile"].metadata_["rerun_issue_codes"] == ["detail_blind"]
    assert step_map["content_profile"].metadata_["rerun_request_note"] == "摘要要补足具体参数"
    assert not any(artifact.artifact_type == "quality_assessment" for artifact in artifacts)
    assert not any(artifact.artifact_type == "content_profile_final" for artifact in artifacts)
    assert action.target_type == "quality_rerun"
    assert action.action == "content_profile"
    assert action.override_text == "摘要要补足具体参数"


@pytest.mark.asyncio
async def test_job_rerun_endpoint_defaults_to_latest_quality_assessment_recommendation(client: AsyncClient):
    from roughcut.db.models import Artifact, Job, JobStep, ReviewAction
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    await _seed_job_for_rerun_api(
        job_id,
        quality_artifact={
            "score": 84.0,
            "grade": "B",
            "issue_codes": ["subtitle_sync_issue"],
            "recommended_rerun_step": "render",
            "recommended_rerun_steps": ["render", "final_review", "platform_package"],
        },
        extra_artifacts=[
            {
                "artifact_type": "render_outputs",
                "data_json": {"packaged_mp4": "E:/tmp/rerun-api.mp4"},
            }
        ],
    )

    response = await client.post(f"/api/v1/jobs/{job_id}/rerun", json={})
    assert response.status_code == 200
    assert response.json() == {
        "job_id": str(job_id),
        "job_status": "processing",
        "rerun_start_step": "render",
        "rerun_steps": ["render", "final_review", "platform_package"],
        "issue_codes": ["subtitle_sync_issue"],
        "note": None,
        "detail": "已接受重跑请求，等待调度器从 render 接管。问题：subtitle_sync_issue；链路：render -> final_review -> platform_package",
    }

    async with get_session_factory()() as session:
        job = await session.get(Job, job_id)
        steps = (
            await session.execute(select(JobStep).where(JobStep.job_id == job_id).order_by(JobStep.id.asc()))
        ).scalars().all()
        artifacts = (
            await session.execute(select(Artifact).where(Artifact.job_id == job_id).order_by(Artifact.id.asc()))
        ).scalars().all()
        action = (
            await session.execute(select(ReviewAction).where(ReviewAction.job_id == job_id))
        ).scalar_one()

    assert job is not None
    assert job.status == "processing"
    step_map = {step.step_name: step for step in steps}
    assert step_map["content_profile"].status == "done"
    assert step_map["render"].status == "pending"
    assert step_map["final_review"].status == "pending"
    assert step_map["platform_package"].status == "pending"
    assert step_map["render"].metadata_["rerun_requested_via"] == "web"
    assert step_map["render"].metadata_["rerun_issue_codes"] == ["subtitle_sync_issue"]
    assert not any(artifact.artifact_type == "quality_assessment" for artifact in artifacts)
    assert not any(artifact.artifact_type == "render_outputs" for artifact in artifacts)
    assert action.target_type == "quality_rerun"
    assert action.action == "render"
    assert action.override_text == "subtitle_sync_issue"


@pytest.mark.asyncio
async def test_job_rerun_endpoint_rejects_unsupported_issue_without_quality_context(client: AsyncClient):
    from roughcut.db.models import Job, JobStep, ReviewAction
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    await _seed_job_for_rerun_api(job_id)

    response = await client.post(
        f"/api/v1/jobs/{job_id}/rerun",
        json={"issue_code": "unknown_issue"},
    )
    assert response.status_code == 400
    assert "Unsupported issue_code" in response.text

    async with get_session_factory()() as session:
        job = await session.get(Job, job_id)
        steps = (
            await session.execute(select(JobStep).where(JobStep.job_id == job_id).order_by(JobStep.id.asc()))
        ).scalars().all()
        actions = (
            await session.execute(select(ReviewAction).where(ReviewAction.job_id == job_id))
        ).scalars().all()

    assert job is not None
    assert job.status == "done"
    assert all(step.status == "done" for step in steps)
    assert actions == []


@pytest.mark.asyncio
async def test_job_rerun_endpoint_rejects_semantic_contamination_default_rerun(client: AsyncClient):
    job_id = uuid.uuid4()
    await _seed_job_for_rerun_api(
        job_id,
        quality_artifact={
            "score": 52.0,
            "grade": "D",
            "issue_codes": ["subtitle_semantic_contamination"],
            "recommended_rerun_step": None,
            "recommended_rerun_steps": [],
        },
    )

    response = await client.post(f"/api/v1/jobs/{job_id}/rerun", json={})
    assert response.status_code == 409
    assert "manual review before rerun" in response.text
    assert "subtitle_semantic_contamination" in response.text


@pytest.mark.asyncio
async def test_job_rerun_endpoint_rejects_semantic_contamination_issue_code(client: AsyncClient):
    job_id = uuid.uuid4()
    await _seed_job_for_rerun_api(
        job_id,
        quality_artifact={
            "score": 52.0,
            "grade": "D",
            "issue_codes": ["subtitle_semantic_contamination"],
            "recommended_rerun_step": None,
            "recommended_rerun_steps": [],
        },
    )

    response = await client.post(
        f"/api/v1/jobs/{job_id}/rerun",
        json={"issue_code": "subtitle_semantic_contamination"},
    )
    assert response.status_code == 409
    assert "manual review before rerun" in response.text
    assert "subtitle_semantic_contamination" in response.text
