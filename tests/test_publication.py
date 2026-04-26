from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from roughcut import publication
from roughcut.api.jobs import _attach_job_preview
from roughcut.db.models import Job
from roughcut.db.session import Base


class _FakeBrowserAgentResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeBrowserAgentClient:
    def __init__(self):
        self.posts = []
        self.gets = []

    async def post(self, url, *, json, headers):
        self.posts.append({"url": url, "json": json, "headers": headers})
        return _FakeBrowserAgentResponse(
            {
                "task": {
                    "task_id": json["task_id"],
                    "status": "running",
                    "execution_id": "run-1",
                }
            }
        )

    async def get(self, url, *, headers):
        self.gets.append({"url": url, "headers": headers})
        task_id = url.rsplit("/", 1)[-1]
        return _FakeBrowserAgentResponse(
            {
                "task": {
                    "task_id": task_id,
                    "status": "published",
                    "execution_id": "run-1",
                    "result": {
                        "post_id": "post-1",
                        "public_url": "https://www.douyin.com/video/post-1",
                    },
                }
            }
        )


def test_normalize_publication_credentials_filters_to_browser_agent():
    credentials = publication.normalize_publication_credentials(
        [
            {
                "platform": "B站",
                "account_label": "主号",
                "credential_ref": "chrome-profile:main",
                "status": "logged_in",
                "adapter": "browser_agent",
            },
            {
                "platform": "unknown",
                "account_label": "ignored",
                "status": "logged_in",
            },
        ]
    )

    assert credentials == [
        {
            "id": credentials[0]["id"],
            "platform": "bilibili",
            "platform_label": "B站",
            "account_label": "主号",
            "credential_ref": "chrome-profile:main",
            "status": "logged_in",
            "enabled": True,
            "adapter": "browser_agent",
            "verified_at": None,
            "notes": None,
            "last_error": None,
        }
    ]


@pytest.mark.asyncio
async def test_publication_plan_requires_done_job_local_media_and_bound_credentials(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            job = Job(source_path="source.mp4", source_name="source.mp4", status="done")
            session.add(job)
            await session.flush()
            render_output = SimpleNamespace(output_path=str(media_path))
            creator_profile = {
                "id": "creator-1",
                "display_name": "creator",
                "creator_profile": {
                    "publishing": {
                        "platform_credentials": [
                            {
                                "platform": "douyin",
                                "account_label": "主号",
                                "credential_ref": "chrome-profile:main",
                                "status": "logged_in",
                                "enabled": True,
                                "adapter": "browser_agent",
                            }
                        ]
                    }
                },
            }
            packaging = {
                "platforms": {
                    "douyin": {
                        "titles": ["标题"],
                        "description": "简介",
                        "tags": ["tag"],
                    }
                }
            }

            plan = publication.build_publication_plan(
                job=job,
                render_output=render_output,
                platform_packaging=packaging,
                creator_profile=creator_profile,
                platform_options={
                    "douyin": {
                        "scheduled_publish_at": "2026-04-26T18:30",
                        "collection_name": "新品体验",
                        "category": "数码",
                        "visibility_or_publish_mode": "scheduled",
                    }
                },
                existing_attempts=await publication.list_publication_attempts(session, job_id=str(job.id)),
            )
            result = await publication.submit_publication_attempts(session, plan)
            duplicate = await publication.submit_publication_attempts(session, plan)
            await session.commit()
            job_with_attempts = (
                await session.execute(
                    select(Job)
                    .options(
                        selectinload(Job.steps),
                        selectinload(Job.artifacts),
                        selectinload(Job.publication_attempts),
                    )
                    .where(Job.id == job.id)
                )
            ).scalar_one()
            _attach_job_preview(job_with_attempts, lightweight=True)
    finally:
        await engine.dispose()

    assert plan["publish_ready"] is True
    assert [target["platform"] for target in plan["targets"]] == ["douyin"]
    assert len(result["created_attempts"]) == 1
    assert result["created_attempts"][0]["status"] == "queued"
    assert result["created_attempts"][0]["adapter"] == "browser_agent"
    assert result["created_attempts"][0]["request_payload"]["content_kind"] == "video"
    assert result["created_attempts"][0]["request_payload"]["media_items"] == [
        {
            "kind": "video",
            "local_path": str(media_path.resolve()),
            "source_url": None,
            "uploaded_url": None,
            "mime_type": "video/mp4",
        }
    ]
    assert result["created_attempts"][0]["request_payload"]["metadata"]["browser_profile_id"] == "chrome-profile:main"
    assert result["created_attempts"][0]["request_payload"]["scheduled_publish_at"] == "2026-04-26T18:30"
    assert result["created_attempts"][0]["request_payload"]["collection"] == {"name": "新品体验"}
    assert result["created_attempts"][0]["request_payload"]["category"] == "数码"
    assert result["created_attempts"][0]["request_payload"]["visibility_or_publish_mode"] == "scheduled"
    assert result["created_attempts"][0]["runs"][0]["metadata"]["contract"] == "browser_agent_publication_v1"
    assert len(duplicate["created_attempts"]) == 0
    assert job_with_attempts.publication_status == "published"
    assert job_with_attempts.publication_summary == "已提交发布：抖音"


@pytest.mark.asyncio
async def test_publication_worker_submits_and_reconciles_browser_agent_attempt(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    fake_client = _FakeBrowserAgentClient()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            job = Job(source_path="source.mp4", source_name="source.mp4", status="done")
            session.add(job)
            await session.flush()
            plan = publication.build_publication_plan(
                job=job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging={
                    "platforms": {
                        "douyin": {
                            "titles": ["标题"],
                            "description": "简介",
                            "tags": ["tag"],
                        }
                    }
                },
                creator_profile={
                    "id": "creator-1",
                    "display_name": "creator",
                    "creator_profile": {
                        "publishing": {
                            "platform_credentials": [
                                {
                                    "platform": "douyin",
                                    "account_label": "主号",
                                    "credential_ref": "chrome-profile:main",
                                    "status": "logged_in",
                                    "enabled": True,
                                    "adapter": "browser_agent",
                                }
                            ]
                        }
                    },
                },
                platform_options={
                    "douyin": {
                        "scheduled_publish_at": "2026-04-26T19:00",
                        "collection_id": "col-1",
                        "collection_name": "测评合集",
                    }
                },
            )
            await publication.submit_publication_attempts(session, plan)
            first_tick = await publication.run_publication_worker_once(
                session,
                browser_agent_base_url="http://browser-agent.local",
                auth_token="secret",
                worker_id="worker-1",
                http_client=fake_client,
            )
            second_tick = await publication.run_publication_worker_once(
                session,
                browser_agent_base_url="http://browser-agent.local",
                auth_token="secret",
                worker_id="worker-1",
                http_client=fake_client,
            )
            attempts = await publication.list_publication_attempts(session, job_id=str(job.id))
    finally:
        await engine.dispose()

    assert first_tick["claimed"] == 1
    assert fake_client.posts[0]["json"]["content"]["publish_media_source"]["local_file_count"] == 1
    assert fake_client.posts[0]["json"]["content"]["scheduled_publish_at"] == "2026-04-26T19:00"
    assert fake_client.posts[0]["json"]["content"]["collection"] == {"id": "col-1", "name": "测评合集"}
    assert fake_client.posts[0]["json"]["profile_id"] == "chrome-profile-main"
    assert fake_client.posts[0]["headers"]["Authorization"] == "Bearer secret"
    assert second_tick["reconciled"][0]["status"] == "published"
    assert attempts[0]["status"] == "published"
    assert attempts[0]["provider_task_id"]
    assert attempts[0]["external_post_id"] == "post-1"
    assert attempts[0]["public_url"] == "https://www.douyin.com/video/post-1"
