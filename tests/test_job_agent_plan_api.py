from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from roughcut.api.jobs import JOB_AGENT_PLAN_REVISION_ARTIFACT_TYPE, router
from roughcut.api import jobs as jobs_api
from roughcut.db.models import Artifact, CreatorCard, CreatorPublicationProfile, CreatorTaskStrategy, CreatorVisualPlan, Job
from roughcut.db.session import Base, get_session


@pytest.fixture()
def job_agent_plan_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = (tmp_path / "job-agent-plan.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())
    monkeypatch.setenv("ROUGHCUT_OUTPUT_DIR", (tmp_path / "runtime-output").as_posix())

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = _override_session

    try:
        with TestClient(app) as client:
            yield client, session_factory
    finally:
        asyncio.run(engine.dispose())


def test_job_agent_plan_generate_refine_apply_and_decisions(job_agent_plan_client):
    client, session_factory = job_agent_plan_client
    creator_id = uuid.uuid4()
    strategy_id = uuid.uuid4()
    visual_plan_id = uuid.uuid4()
    publication_profile_id = uuid.uuid4()
    job_id = uuid.uuid4()

    async def _seed() -> None:
        async with session_factory() as session:
            creator = CreatorCard(
                id=creator_id,
                name="FAS",
                positioning="专业测评型创作者",
                default_platforms=["bilibili", "douyin"],
                natural_language_profile="克制、可信、结论先行。",
            )
            session.add(creator)
            session.add(
                CreatorTaskStrategy(
                    id=strategy_id,
                    creator_card_id=creator_id,
                    name="专业测评标准成片",
                    strategy_type="product_review",
                    summary="开场先给结论，再展开依据。",
                    strategy_payload_json={"intent": "先给结论，再展开依据"},
                    is_active=True,
                    status="active",
                )
            )
            session.add(
                CreatorVisualPlan(
                    id=visual_plan_id,
                    creator_card_id=creator_id,
                    name="专业测评型",
                    summary="画面干净、标题克制。",
                    visual_payload_json={"cover_direction": "主体特写 + 结论式标题"},
                    is_active=True,
                    status="active",
                )
            )
            session.add(
                CreatorPublicationProfile(
                    id=publication_profile_id,
                    creator_card_id=creator_id,
                    status="active",
                    publication_payload_json={"default_platforms": ["bilibili", "douyin"], "publication_mode": "material_only"},
                )
            )
            session.add(
                Job(
                    id=job_id,
                    source_path="job/source.mp4",
                    source_name="source.mp4",
                    status="pending",
                    language="zh-CN",
                    workflow_mode="standard_edit",
                    enhancement_modes=[],
                    creator_card_id=creator_id,
                    task_brief="新品开箱和老款对比，突出升级点和适合谁",
                    execution_mode="auto",
                    platform_targets_json=["bilibili", "douyin"],
                )
            )
            await session.commit()

    asyncio.run(_seed())

    get_response = client.get(f"/jobs/{job_id}/agent-plan")
    assert get_response.status_code == 200
    plan = get_response.json()
    assert plan["creator_card_id"] == str(creator_id)
    assert plan["task_strategy_id"] == str(strategy_id)
    assert plan["visual_plan_id"] == str(visual_plan_id)
    assert plan["publication_profile_id"] == str(publication_profile_id)
    assert plan["plan_payload_json"]["creator"]["name"] == "FAS"

    refine_response = client.post(
        f"/jobs/{job_id}/agent-plan/refine",
        json={"prompt": "封面不要广告腔，标题更像测评结论。", "target": "visual"},
    )
    assert refine_response.status_code == 200
    refined = refine_response.json()
    assert refined["status"] == "refined"
    assert refined["plan_payload_json"]["adjustments"]["visual"] == ["封面不要广告腔，标题更像测评结论。"]

    apply_response = client.post(
        f"/jobs/{job_id}/agent-plan/apply",
        json={"selected_strategy_id": str(strategy_id), "selected_visual_plan_id": str(visual_plan_id)},
    )
    assert apply_response.status_code == 200
    applied = apply_response.json()
    assert applied["status"] == "applied"
    assert applied["plan_payload_json"]["applied_at"]

    decisions_response = client.get(f"/jobs/{job_id}/agent-decisions")
    assert decisions_response.status_code == 200
    decisions = decisions_response.json()
    assert [item["kind"] for item in decisions] == ["creator", "task_strategy", "visual_plan", "publication_plan"]

    async def _assert_revisions() -> None:
        async with session_factory() as session:
            result = await session.execute(
                select(Artifact).where(
                    Artifact.job_id == job_id,
                    Artifact.artifact_type == JOB_AGENT_PLAN_REVISION_ARTIFACT_TYPE,
                )
            )
            revisions = list(result.scalars())
            assert len(revisions) == 3
            operations = [item.data_json["operation"] for item in revisions]
            assert operations == ["generate", "refine:visual", "apply"]

    asyncio.run(_assert_revisions())


def test_get_job_includes_bound_creator_name(job_agent_plan_client):
    client, session_factory = job_agent_plan_client
    creator_id = uuid.uuid4()
    job_id = uuid.uuid4()

    async def _seed() -> None:
        async with session_factory() as session:
            session.add(
                CreatorCard(
                    id=creator_id,
                    name="FAS",
                    positioning="专业测评型创作者",
                    default_platforms=["bilibili", "douyin"],
                    natural_language_profile="克制、可信、结论先行。",
                )
            )
            session.add(
                Job(
                    id=job_id,
                    source_path="s3://bucket/source.mp4",
                    source_name="source.mp4",
                    status="done",
                    language="zh-CN",
                    workflow_mode="standard",
                    creator_card_id=creator_id,
                )
            )
            await session.commit()

    asyncio.run(_seed())

    response = client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["creator_card_id"] == str(creator_id)
    assert payload["creator_card_name"] == "FAS"


def test_job_agent_plan_generates_for_legacy_job_without_creator_or_video_description(job_agent_plan_client):
    client, session_factory = job_agent_plan_client
    job_id = uuid.uuid4()

    async def _seed() -> None:
        async with session_factory() as session:
            session.add(
                Job(
                    id=job_id,
                    source_path="legacy/source.mp4",
                    source_name="legacy-source.mp4",
                    status="done",
                    language="zh-CN",
                    workflow_mode="standard_edit",
                    enhancement_modes=[],
                )
            )
            await session.commit()

    asyncio.run(_seed())

    response = client.get(f"/jobs/{job_id}/agent-plan")
    assert response.status_code == 200
    payload = response.json()
    assert payload["creator_card_id"] is None
    assert payload["task_strategy_id"] is None
    assert payload["visual_plan_id"] is None
    assert payload["publication_profile_id"] is None
    assert payload["plan_payload_json"]["task_brief"] == ""
    assert payload["plan_payload_json"]["why"][0] == "未绑定创作者，当前任务使用兼容默认路径。"
    assert payload["plan_payload_json"]["why"][2] == "任务想法：未填写"


@pytest.mark.asyncio
async def test_job_agent_plan_first_read_is_safe_under_concurrent_detail_requests(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    db_path = (tmp_path / "job-agent-plan-concurrent.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    job_id = uuid.uuid4()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="legacy/source.mp4",
                source_name="legacy-source.mp4",
                status="done",
                language="zh-CN",
                workflow_mode="standard_edit",
                enhancement_modes=[],
            )
        )
        await session.commit()

    barrier = asyncio.Barrier(2)

    async def _resolve_dependencies_with_barrier(*_args, **_kwargs):
        await barrier.wait()
        return None, None, None, None

    monkeypatch.setattr(jobs_api, "_resolve_job_agent_plan_dependencies", _resolve_dependencies_with_barrier)

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = _override_session

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            plan_response, decisions_response = await asyncio.gather(
                client.get(f"/jobs/{job_id}/agent-plan"),
                client.get(f"/jobs/{job_id}/agent-decisions"),
            )

        assert plan_response.status_code == 200
        assert decisions_response.status_code == 200

        async with session_factory() as session:
            result = await session.execute(select(jobs_api.JobAgentPlan).where(jobs_api.JobAgentPlan.job_id == job_id))
            plans = list(result.scalars())
            assert len(plans) == 1
    finally:
        await engine.dispose()
