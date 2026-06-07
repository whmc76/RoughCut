from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from roughcut import publication
from roughcut.api import jobs as jobs_api
from roughcut.api.intelligent_copy import (
    _build_publication_executor_gate_response,
    _build_publication_plan_gate_response,
    _derive_generation_task_terminal_patch,
    _load_intelligent_copy_packaging,
    _normalize_intelligent_copy_payload_as_packaging,
    reconcile_publication_task_payload,
)
from roughcut.api.schemas import IntelligentCopyGenerateTaskOut, IntelligentCopyResultOut
from roughcut.api.jobs import _attach_job_preview
from roughcut.db.models import Artifact, Job, PublicationAttempt
from roughcut.db.session import Base
from roughcut.intelligent_copy_layout import (
    smart_copy_material_json_path,
    smart_copy_platform_packaging_json_path,
)
from roughcut.publication_packaging import (
    filter_publication_packaging_platforms,
    load_publication_packaging_payload,
)


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


class _FakeBrowserAgentHealthClient:
    def __init__(
        self,
        final_publish_platforms,
        *,
        composite_frameworks=None,
        legacy_blocked=True,
        extra_capabilities=None,
        creator_sessions=None,
    ):
        self.final_publish_platforms = final_publish_platforms
        self.composite_frameworks = composite_frameworks or {
            "douyin": "douyin_creator_composite_v1",
            "bilibili": "bilibili_creator_native_composite_v1",
            "youtube": "youtube_studio_composite_v1",
            "xiaohongshu": "xiaohongshu_creator_composite_v1",
            "kuaishou": "kuaishou_creator_composite_v1",
            "toutiao": "toutiao_xigua_composite_v1",
            "wechat-channels": "wechat_channels_composite_v1",
            "x": "x_composer_composite_v1",
        }
        self.legacy_blocked = legacy_blocked
        self.extra_capabilities = extra_capabilities or {}
        self.creator_sessions = creator_sessions or {}
        self.gets = []

    async def get(self, url, *, headers):
        self.gets.append({"url": url, "headers": headers})
        return _FakeBrowserAgentResponse(
            {
                "status": "ok",
                "cdp_status": "ok",
                "capabilities": {
                    "publication_tasks": True,
                    "task_identity_echo": True,
                    "task_identity_contract": publication.PUBLICATION_BROWSER_AGENT_TASK_IDENTITY_CONTRACT,
                    "creator_session_probe": True,
                    "creator_session_contract": publication.PUBLICATION_BROWSER_AGENT_CREATOR_SESSION_CONTRACT,
                    "live_publish": True,
                    "final_publish_executor": True,
                    "final_publish_platforms": self.final_publish_platforms,
                    "platform_composite_frameworks": self.composite_frameworks,
                    "legacy_lightweight_scripts_blocked": self.legacy_blocked,
                    **self.extra_capabilities,
                },
                "creator_sessions": self.creator_sessions,
            }
        )


class _FakeBrowserAgentClientTaskMissing(_FakeBrowserAgentClient):
    async def get(self, url, *, headers):
        self.gets.append({"url": url, "headers": headers})
        request = httpx.Request("GET", url)
        response = httpx.Response(404, request=request, text='{"status":"not_found"}')
        raise httpx.HTTPStatusError("task missing", request=request, response=response)


class _FakeBrowserAgentClientProcessing(_FakeBrowserAgentClient):
    async def get(self, url, *, headers):
        self.gets.append({"url": url, "headers": headers})
        task_id = url.rsplit("/", 1)[-1]
        return _FakeBrowserAgentResponse(
            {
                "task": {
                    "task_id": task_id,
                    "status": "processing",
                    "execution_id": "run-1",
                }
            }
        )


def test_job_queue_preview_marks_publication_task_and_uses_attempt_cover(tmp_path):
    cover_path = tmp_path / "cover.jpg"
    cover_path.write_bytes(b"cover")
    job = Job(id=uuid.uuid4(), source_path="source.mp4", source_name="source.mp4", status="done", workflow_template="intelligent_publish")
    job.publication_attempts = [
        PublicationAttempt(
            id="attempt-1",
            job_id=job.id,
            content_id=str(job.id),
            platform="douyin",
            platform_label="抖音",
            idempotency_key="key-1",
            semantic_fingerprint="fingerprint-1",
            adapter="browser_agent",
            status="queued",
            request_payload={"cover_path": str(cover_path)},
        )
    ]

    _attach_job_preview(job, lightweight=True)

    assert job.queue_task_kind == "publication"
    assert job.queue_thumbnail_source == "cover"


def test_job_queue_preview_prefers_render_cover_for_edit_task(tmp_path):
    cover_path = tmp_path / "render-cover.jpg"
    cover_path.write_bytes(b"cover")
    job = Job(id=uuid.uuid4(), source_path="source.mp4", source_name="source.mp4", status="done")
    job.artifacts = [
        Artifact(
            job_id=job.id,
            artifact_type="render_outputs",
            data_json={"cover": str(cover_path)},
        )
    ]

    _attach_job_preview(job, lightweight=True)

    assert job.queue_task_kind == "edit"
    assert job.queue_thumbnail_source == "cover"


def test_job_queue_preview_uses_publication_response_cover(tmp_path):
    cover_path = tmp_path / "verified-cover.jpg"
    cover_path.write_bytes(b"cover")
    job = Job(id=uuid.uuid4(), source_path="source.mp4", source_name="source.mp4", status="done", workflow_template="intelligent_publish")
    job.publication_attempts = [
        PublicationAttempt(
            id="attempt-response-cover",
            job_id=job.id,
            content_id=str(job.id),
            platform="bilibili",
            platform_label="B站",
            idempotency_key="key-response-cover",
            semantic_fingerprint="fingerprint-response-cover",
            adapter="browser_agent",
            status="published",
            request_payload={},
            response_payload={
                "task": {
                    "result": {
                        "final_publish": {
                            "actions": [
                                {"kind": "cover_verified", "path": str(cover_path)},
                            ],
                        },
                    },
                },
            },
        )
    ]

    _attach_job_preview(job, lightweight=True)

    assert job.queue_task_kind == "publication"
    assert job.queue_thumbnail_source == "cover"


@pytest.mark.asyncio
async def test_list_publication_attempts_serializes_cover_contract(tmp_path):
    cover_path = tmp_path / "attempt-cover.jpg"
    cover_path.write_bytes(b"cover")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        job = Job(id=uuid.uuid4(), source_path="source.mp4", source_name="source.mp4", status="done")
        session.add(job)
        session.add(
            PublicationAttempt(
                id="attempt-cover-contract",
                job_id=job.id,
                content_id=str(job.id),
                creator_profile_id="profile-1",
                creator_profile_name="主账号",
                platform="douyin",
                platform_label="抖音",
                account_label="主号",
                credential_id="cred-1",
                idempotency_key="attempt-cover-contract-key",
                semantic_fingerprint="attempt-cover-contract-fingerprint",
                adapter="browser_agent",
                status="queued",
                request_payload={
                    "copy_material": {
                        "cover_slots": [
                            {"cover_path": str(cover_path)},
                        ],
                    },
                },
            )
        )
        await session.commit()

        attempts = await publication.list_publication_attempts(session, job_id=str(job.id))

    await engine.dispose()

    assert attempts[0]["cover_path"] == str(cover_path)
    assert attempts[0]["cover_slots"][0]["cover_path"] == str(cover_path)


def test_normalize_publication_credentials_filters_to_browser_agent():
    credentials = publication.normalize_publication_credentials(
        [
            {
                "platform": "B站",
                "account_label": "主号",
                "credential_ref": "chrome-profile:main",
                "browser": "chrome",
                "user_data_dir": "C:/Users/test/AppData/Local/Google/Chrome/User Data",
                "profile_directory": "Profile 2",
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
            "browser_profile_id": publication.build_publication_browser_profile_id(
                browser="chrome",
                user_data_dir="C:/Users/test/AppData/Local/Google/Chrome/User Data",
                profile_directory="Profile 2",
            ),
            "browser_binding": {
                "browser": "chrome",
                "user_data_dir": "C:/Users/test/AppData/Local/Google/Chrome/User Data",
                "profile_directory": "Profile 2",
                "profile_name": None,
                "profile_email": None,
                "cdp_base_url": None,
                "profile_id": publication.build_publication_browser_profile_id(
                    browser="chrome",
                    user_data_dir="C:/Users/test/AppData/Local/Google/Chrome/User Data",
                    profile_directory="Profile 2",
                ),
            },
            "status": "logged_in",
            "enabled": True,
            "adapter": "browser_agent",
            "verified_at": None,
            "notes": None,
            "last_error": None,
        }
    ]


def test_build_browser_agent_task_payload_from_attempt_does_not_require_worker_local_path():
    attempt = PublicationAttempt(
        id="attempt-host-path",
        job_id=uuid.uuid4(),
        content_id="job-host-path",
        platform="xiaohongshu",
        platform_label="小红书",
        idempotency_key="key-host-path",
        semantic_fingerprint="fingerprint-host-path",
        adapter="browser_agent",
        status="queued",
        request_payload={
            "title": "标题",
            "body": "正文",
            "media_items": [
                {
                    "kind": "video",
                    "local_path": r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱\MAXACE 美杜莎4 顶配次顶配开箱.mp4",
                }
            ],
            "metadata": {
                "browser_profile_id": "browser-profile:chrome:test",
            },
        },
    )

    payload = publication.build_browser_agent_task_payload_from_attempt(attempt)

    assert payload["task_id"] == "attempt-host-path"
    assert payload["attempt_id"] == "attempt-host-path"
    assert payload["content_id"] == "job-host-path"
    assert payload["profile_id"] == "browser-profile-chrome-test"
    assert payload["content"]["media_items"][0]["local_path"].startswith(r"\\Z4pro-gwil")


def test_build_browser_agent_task_payload_from_attempt_rehydrates_resolved_media_path(tmp_path, monkeypatch):
    unreadable_runtime_path = r"E:\\WorkSpace\\RoughCut\\data\\runtime\\host-intelligent-copy\\missing\\video.mp4"
    real_media_path = tmp_path / "video.mp4"
    real_media_path.write_bytes(b"video")

    def _resolve(raw):
        if str(raw).strip() == unreadable_runtime_path:
            return None
        if str(raw).strip() == str(real_media_path):
            return real_media_path.resolve()
        return None

    monkeypatch.setattr(publication, "resolve_publication_local_media_path", _resolve)

    attempt = PublicationAttempt(
        id="attempt-rehydrate-media",
        job_id=uuid.uuid4(),
        content_id="job-rehydrate-media",
        platform="xiaohongshu",
        platform_label="小红书",
        idempotency_key="key-rehydrate-media",
        semantic_fingerprint="fingerprint-rehydrate-media",
        adapter="browser_agent",
        status="queued",
        request_payload={
            "title": "标题",
            "body": "正文",
            "media_items": [
                {
                    "kind": "video",
                    "local_path": unreadable_runtime_path,
                }
            ],
            "metadata": {
                "browser_profile_id": "browser-profile:chrome:test",
                "requested_media_path": str(real_media_path),
            },
        },
    )

    payload = publication.build_browser_agent_task_payload_from_attempt(attempt)

    assert payload["content"]["media_items"][0]["local_path"] == str(real_media_path.resolve())


def test_build_browser_agent_task_payload_from_attempt_rehydrates_current_browser_profile_binding(monkeypatch, tmp_path):
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"video")
    monkeypatch.setattr(
        publication,
        "_lookup_current_publication_credential",
        lambda **_: {
            "id": "cred-current",
            "platform": "xiaohongshu",
            "credential_ref": "browser-agent:chrome:release-gate-profile:xiaohongshu",
            "account_label": "xiaohongshu release-gate",
            "browser_profile_id": "browser-profile:chrome:5748ec82429e20a77ac7",
            "browser_binding": {
                "browser": "chrome",
                "user_data_dir": "E:/WorkSpace/RoughCut/data/runtime/publication-browser-profile-stable/chrome-user-data",
                "profile_directory": "Profile 2",
                "profile_id": "browser-profile:chrome:5748ec82429e20a77ac7",
            },
        },
    )

    attempt = PublicationAttempt(
        id="attempt-rehydrate-profile",
        job_id=uuid.uuid4(),
        content_id="job-rehydrate-profile",
        creator_profile_id="release-gate-profile",
        creator_profile_name="Release Gate",
        platform="xiaohongshu",
        platform_label="小红书",
        account_label="xiaohongshu release-gate",
        credential_id="cred-legacy",
        idempotency_key="key-rehydrate-profile",
        semantic_fingerprint="fingerprint-rehydrate-profile",
        adapter="browser_agent",
        status="queued",
        request_payload={
            "title": "标题",
            "body": "正文",
            "media_items": [
                {
                    "kind": "video",
                    "local_path": str(media_path),
                }
            ],
            "metadata": {
                "creator_profile_id": "release-gate-profile",
                "credential_id": "cred-legacy",
                "credential_ref": "browser-agent:chrome:release-gate-profile:xiaohongshu:legacy",
                "account_label": "xiaohongshu release-gate",
                "browser_profile_id": "browser-profile:chrome:21104fd69d72ad7267c2",
                "browser_binding": {
                    "profile_id": "browser-profile:chrome:21104fd69d72ad7267c2",
                },
                "session_binding": {
                    "contract": publication.PUBLICATION_BROWSER_SESSION_BINDING_CONTRACT,
                    "platform": "xiaohongshu",
                    "creator_profile_id": "release-gate-profile",
                    "browser_profile_id": "browser-profile:chrome:21104fd69d72ad7267c2",
                    "allowed_profile_ids": ["browser-profile:chrome:21104fd69d72ad7267c2"],
                },
            },
        },
    )

    payload = publication.build_browser_agent_task_payload_from_attempt(attempt)

    assert payload["profile_id"] == "browser-profile-chrome-5748ec82429e20a77ac7"
    assert payload["session_binding"]["browser_profile_id"] == "browser-profile:chrome:5748ec82429e20a77ac7"
    assert payload["session_binding"]["allowed_profile_ids"] == ["browser-profile:chrome:5748ec82429e20a77ac7"]
    assert payload["content"]["metadata"]["credential_id"] == "cred-current"
    assert payload["content"]["metadata"]["browser_binding"]["profile_directory"] == "Profile 2"


def test_build_browser_agent_task_payload_from_attempt_rehydrates_release_gate_binding(monkeypatch, tmp_path):
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"video")
    monkeypatch.setattr(publication, "DEFAULT_PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("ROUGHCUT_PUBLICATION_BROWSER_USER_DATA_DIR", raising=False)
    monkeypatch.delenv("ROUGHCUT_PUBLICATION_BROWSER_PROFILE_DIRECTORY", raising=False)
    monkeypatch.setattr(publication, "_lookup_current_publication_credential", lambda **_: None)

    attempt = PublicationAttempt(
        id="attempt-release-gate",
        job_id=uuid.uuid4(),
        content_id="job-release-gate",
        creator_profile_id="release-gate-profile",
        creator_profile_name="Publication Real Release Gate",
        platform="xiaohongshu",
        platform_label="小红书",
        account_label="xiaohongshu release-gate",
        credential_id="release-gate-profile-xiaohongshu",
        idempotency_key="key-release-gate",
        semantic_fingerprint="fingerprint-release-gate",
        adapter="browser_agent",
        status="queued",
        request_payload={
            "title": "标题",
            "body": "正文",
            "media_items": [{"kind": "video", "local_path": str(media_path)}],
            "metadata": {
                "creator_profile_id": "release-gate-profile",
                "credential_ref": "browser-profile:chrome:21104fd69d72ad7267c2",
                "account_label": "xiaohongshu release-gate",
                "browser_profile_id": "browser-profile:chrome:21104fd69d72ad7267c2",
            },
        },
    )

    payload = publication.build_browser_agent_task_payload_from_attempt(attempt)
    expected_profile_id = publication.build_publication_browser_profile_id(
        browser="chrome",
        user_data_dir=str(tmp_path / "data" / "runtime" / "publication-browser-profile-stable" / "chrome-user-data"),
        profile_directory="Profile 2",
    )

    assert payload["session_binding"]["browser_profile_id"] == expected_profile_id
    assert payload["session_binding"]["allowed_profile_ids"] == [expected_profile_id]
    assert payload["content"]["metadata"]["credential_ref"] == expected_profile_id
    assert payload["content"]["metadata"]["browser_binding"]["profile_directory"] == "Profile 2"


def test_build_publication_browser_session_binding_does_not_promote_creator_profile_ref_into_browser_binding():
    payload = publication.build_publication_browser_session_binding(
        platform="youtube",
        creator_profile_id="creator-1",
        credential_ref="d2d15bc6d77a47b79cf20a79b56596c2",
        account_label="FAS YouTube",
    )

    assert payload["creator_profile_id"] == "creator-1"
    assert payload["credential_ref"] == "d2d15bc6d77a47b79cf20a79b56596c2"
    assert payload["browser_profile_id"] is None
    assert payload["allowed_profile_ids"] == []


def test_build_request_payload_prefers_stable_source_media_path_for_requested_media_metadata(tmp_path, monkeypatch):
    runtime_media_path = tmp_path / "runtime.publishable.mp4"
    runtime_media_path.write_bytes(b"video")
    source_media_path = tmp_path / "source.mp4"
    source_media_path.write_bytes(b"source-video")

    monkeypatch.setattr(
        publication,
        "resolve_publication_local_media_path",
        lambda raw: runtime_media_path.resolve() if str(raw).strip() == str(runtime_media_path) else None,
    )

    payload = publication._build_request_payload(
        plan={
            "media_path": str(runtime_media_path),
            "source_media_path": str(source_media_path),
            "creator_profile_id": "creator-1",
            "creator_profile_name": "Creator One",
            "publication_guard": {},
        },
        target={
            "platform": "xiaohongshu",
            "title": "标题",
            "body": "正文",
            "tags": ["标签"],
            "adapter": "browser_agent",
            "browser_profile_id": "browser-profile:chrome:test",
        },
    )

    assert payload["media_items"][0]["local_path"] == str(runtime_media_path.resolve())
    assert payload["metadata"]["requested_media_path"] == str(source_media_path)
    assert payload["metadata"]["resolved_media_path"] == str(runtime_media_path.resolve())


def test_build_request_payload_rehydrates_xiaohongshu_cover_from_generation_group_when_explicit_cover_is_suspicious(tmp_path):
    portrait_cover_path = tmp_path / "00-cover-portrait_3_4.jpg"
    portrait_cover_path.write_bytes(b"cover")
    landscape_cover_path = tmp_path / "00-cover-landscape_4_3.jpg"
    landscape_cover_path.write_bytes(b"landscape-cover")
    suspicious_cover_path = tmp_path / "artifacts" / "publish-material-mirror" / "02-xiaohongshu-cover.jpg"
    suspicious_cover_path.parent.mkdir(parents=True, exist_ok=True)
    suspicious_cover_path.write_bytes(b"wrong-cover")

    payload = publication._build_request_payload(
        plan={
            "media_path": str(tmp_path / "video.mp4"),
            "creator_profile_id": "creator-1",
            "creator_profile_name": "Creator One",
            "publication_guard": {},
        },
        target={
            "platform": "xiaohongshu",
            "title": "标题",
            "body": "正文",
            "tags": ["标签"],
            "cover_path": str(suspicious_cover_path),
            "cover_generation": {
                "target_size": {"width": 1080, "height": 1440},
                "cover_group": {
                    "key": "portrait_3_4",
                    "cover_path": str(portrait_cover_path),
                    "members": ["xiaohongshu"],
                },
            },
        },
    )

    assert payload["cover_path"] == str(landscape_cover_path.resolve())
    assert payload["copy_material"]["cover_path"] == str(landscape_cover_path.resolve())
    assert payload["cover_slots"] == [
        {
            "slot": "landscape_4_3",
            "cover_path": str(landscape_cover_path.resolve()),
            "label": "4:3 横版母版",
            "matrix_key": "landscape_4_3",
            "target_size": {"width": 1440, "height": 1080},
        }
    ]


def test_build_browser_agent_task_payload_from_attempt_fails_closed_when_no_local_media_can_be_resolved(monkeypatch):
    monkeypatch.setattr(publication, "resolve_publication_local_media_path", lambda _raw: None)

    attempt = PublicationAttempt(
        id="attempt-unreadable-media",
        job_id=uuid.uuid4(),
        content_id="job-unreadable-media",
        platform="xiaohongshu",
        platform_label="小红书",
        idempotency_key="key-unreadable-media",
        semantic_fingerprint="fingerprint-unreadable-media",
        adapter="browser_agent",
        status="queued",
        request_payload={
            "title": "标题",
            "body": "正文",
            "media_items": [
                {
                    "kind": "video",
                    "local_path": r"E:\\WorkSpace\\RoughCut\\data\\runtime\\host-intelligent-copy\\missing\\video.mp4",
                }
            ],
            "publication_capability": {
                "requires_local_media": True,
            },
                "metadata": {
                    "browser_profile_id": "browser-profile:chrome:test",
                    "requested_media_path": r"\\server\share\video.mp4",
                },
            },
        )

    with pytest.raises(ValueError, match="browser-agent 发布需要至少一个本地文件"):
        publication.build_browser_agent_task_payload_from_attempt(attempt)


def test_build_browser_agent_task_payload_from_attempt_recovers_cover_from_packaging_when_attempt_is_pinned_to_stale_mirror(
    tmp_path,
    monkeypatch,
):
    media_path = tmp_path / "MAXACE 美杜莎4.mp4"
    media_path.write_bytes(b"video")
    portrait_cover_path = tmp_path / "smart-copy" / "00-cover-portrait_3_4.jpg"
    portrait_cover_path.parent.mkdir(parents=True, exist_ok=True)
    portrait_cover_path.write_bytes(b"cover")
    landscape_cover_path = tmp_path / "smart-copy" / "00-cover-landscape_4_3.jpg"
    landscape_cover_path.write_bytes(b"landscape-cover")
    stale_cover_path = tmp_path / "artifacts" / "publish-material-mirror" / "02-xiaohongshu-cover.jpg"
    stale_cover_path.parent.mkdir(parents=True, exist_ok=True)
    stale_cover_path.write_bytes(b"wrong-cover")

    monkeypatch.setattr(
        publication,
        "load_publication_packaging_payload",
        lambda **_kwargs: (
            {
                "platforms": {
                    "xiaohongshu": {
                        "platform": "xiaohongshu",
                        "cover_generation": {
                            "target_size": {"width": 1080, "height": 1440},
                            "cover_group": {
                                "key": "portrait_3_4",
                                "cover_path": str(portrait_cover_path),
                                "members": ["xiaohongshu"],
                            },
                        },
                    }
                }
            },
            {},
        ),
    )

    attempt = PublicationAttempt(
        id="attempt-rehydrate-cover",
        job_id=uuid.uuid4(),
        content_id="job-rehydrate-cover",
        platform="xiaohongshu",
        platform_label="小红书",
        idempotency_key="key-rehydrate-cover",
        semantic_fingerprint="fingerprint-rehydrate-cover",
        adapter="browser_agent",
        status="queued",
        request_payload={
            "title": "标题",
            "body": "正文",
            "cover_path": str(stale_cover_path),
            "copy_material": {
                "cover_path": str(stale_cover_path),
                "cover_slots": [
                    {
                        "slot": "primary",
                        "cover_path": str(stale_cover_path),
                    }
                ],
            },
            "media_items": [{"kind": "video", "local_path": str(media_path)}],
            "metadata": {
                "browser_profile_id": "browser-profile:chrome:test",
                "requested_media_path": str(media_path),
            },
        },
    )

    payload = publication.build_browser_agent_task_payload_from_attempt(attempt)

    assert payload["content"]["cover_path"] == str(landscape_cover_path.resolve())
    assert payload["content"]["copy_material"]["cover_path"] == str(landscape_cover_path.resolve())
    assert payload["content"]["cover_slots"][0]["cover_path"] == str(landscape_cover_path.resolve())


def test_build_browser_agent_task_payload_includes_session_binding_contract():
    plan = {
        "creator_profile_id": "creator-1",
        "creator_profile_name": "Creator One",
        "media_path": r"C:\\tmp\\video.mp4",
    }
    target = {
        "platform": "youtube",
        "title": "标题",
        "body": "正文",
        "browser_profile_id": "browser-profile:chrome:test",
        "credential_ref": "browser-agent:youtube:creator-1",
        "account_label": "Creator One · YouTube",
        "browser_binding": {
            "browser": "chrome",
            "user_data_dir": r"C:\\Users\\tester\\AppData\\Local\\Google\\Chrome\\User Data",
            "profile_directory": "Profile 2",
        },
        "allowed_route_contexts": ["publish_route", "domain:studio.youtube.com"],
    }

    payload = publication.build_browser_agent_task_payload("attempt-1", plan=plan, target=target)

    assert payload["session_binding"]["contract"] == publication.PUBLICATION_BROWSER_SESSION_BINDING_CONTRACT
    assert payload["session_binding"]["platform"] == "youtube"
    assert payload["session_binding"]["creator_profile_id"] == "creator-1"
    assert payload["session_binding"]["browser_profile_id"] == "browser-profile:chrome:test"
    assert payload["content"]["metadata"]["session_binding"]["allowed_route_contexts"] == [
        "domain:studio.youtube.com",
        "publish_route",
    ]


def test_build_request_payload_x_platform_supports_share_link_without_local_media():
    plan = {"media_path": r"C:\\tmp\\video.mp4"}
    target = {
        "platform": "x",
        "adapter": "x_link_share",
        "title": "标题",
        "body": "短视频测试",
        "tags": ["tag1", "tag2"],
        "platform_specific_overrides": {
            "x_share_link": "https://youtu.be/abc123",
        },
        "browser_profile_id": "x-profile",
    }

    payload = publication._build_request_payload(plan=plan, target=target)

    assert payload["publication_capability"]["requires_local_media"] is False
    assert payload["body"] == "短视频测试\nhttps://youtu.be/abc123"
    assert payload["media_items"] == []
    assert payload["media_urls"] == []
    assert payload["publication_content_signature"]["value"]
    assert payload["publication_content_signature"]["fields"]["platform"] == "x"
    assert payload["publication_capability"]["supports_collection_select"] is False
    assert payload["publication_capability"]["supports_scheduled_publish"] is True
    assert payload["publication_capability"]["publish_entry_url"] == "https://x.com/compose/post"
    assert payload["publication_capability"]["cover_asset_policy"] == "upload_prebuilt_asset_only"
    assert payload["publication_capability"]["allow_field_edits_while_processing"] is True


def test_build_request_payload_uses_shared_default_declaration_for_bilibili():
    plan = {"media_path": r"C:\\tmp\\video.mp4"}
    target = {
        "platform": "bilibili",
        "title": "标题",
        "body": "正文",
        "tags": ["tag1"],
        "browser_profile_id": "bili-profile",
    }

    payload = publication._build_request_payload(plan=plan, target=target)

    assert payload["declaration"] == "内容无需标注"
    assert payload["publication_content_signature"]["fields"]["declaration"] == "内容无需标注"
    assert payload["publication_capability"]["publish_entry_url"] == "https://member.bilibili.com/platform/upload/video/frame"
    assert payload["publication_capability"]["draft_resume_policy"] == "discard_existing_draft"
    assert payload["publication_capability"]["publish_projects"][0]["key"] == "media_upload"
    assert payload["publication_capability"]["publish_projects"][-1]["key"] == "final_publish"


def test_build_request_payload_exposes_kuaishou_mainline_publish_contract():
    plan = {"media_path": r"C:\\tmp\\video.mp4"}
    target = {
        "platform": "kuaishou",
        "title": "标题",
        "body": "正文",
        "tags": ["tag1"],
        "browser_profile_id": "kuaishou-profile",
    }

    payload = publication._build_request_payload(plan=plan, target=target)

    capability = payload["publication_capability"]
    assert capability["cover_asset_policy"] == "upload_prebuilt_asset_only"
    assert capability["cover_project_mode"] == "main_cover_only"
    assert capability["allow_field_edits_while_processing"] is True
    assert capability["stop_when_current_page_already_correct"] is True
    assert capability["upload_processing_blocks_final_publish_only"] is True
    assert [item["key"] for item in capability["publish_projects"]] == [
        "media_upload",
        "body",
        "cover_modal_open",
        "cover_slot_select_4_3",
        "cover_upload",
        "cover_confirm",
        "collection",
        "schedule",
        "final_publish",
    ]


def test_build_request_payload_preserves_native_topics():
    payload = publication._build_request_payload(
        plan={"media_path": r"C:\\tmp\\video.mp4"},
        target={
            "platform": "douyin",
            "title": "标题",
            "body": "正文",
            "tags": ["EDC折刀"],
            "native_topics": ["EDC折刀", "#MAXACE美杜莎4", "EDC折刀"],
        },
    )

    assert payload["native_topics"] == ["EDC折刀", "MAXACE美杜莎4"]
    assert payload["publication_plan_signature"]["fields"]["native_topics"] == ["EDC折刀", "MAXACE美杜莎4"]
    assert payload["publication_content_signature"]["fields"]["native_topics"] == ["EDC折刀", "MAXACE美杜莎4"]


def test_build_request_payload_drops_youtube_placeholder_category():
    payload = publication._build_request_payload(
        plan={"media_path": r"C:\\tmp\\video.mp4"},
        target={
            "platform": "youtube",
            "title": "标题",
            "body": "正文",
            "tags": ["EDC折刀"],
            "category": "视频",
            "browser_profile_id": "youtube-profile",
        },
    )

    assert payload["category"] is None
    assert payload["publication_plan_signature"]["fields"]["category"] is None
    assert payload["publication_content_signature"]["fields"]["category"] is None


def test_build_request_payload_defaults_youtube_visibility_to_public():
    payload = publication._build_request_payload(
        plan={"media_path": r"C:\\tmp\\video.mp4"},
        target={
            "platform": "youtube",
            "title": "标题",
            "body": "正文",
            "tags": ["EDC折刀"],
            "browser_profile_id": "youtube-profile",
        },
    )

    assert payload["visibility_or_publish_mode"] == "public"
    assert payload["publication_plan_signature"]["fields"]["visibility_or_publish_mode"] == "public"
    assert payload["publication_content_signature"]["fields"]["visibility_or_publish_mode"] == "public"


def test_build_request_payload_preserves_real_youtube_category():
    payload = publication._build_request_payload(
        plan={"media_path": r"C:\\tmp\\video.mp4"},
        target={
            "platform": "youtube",
            "title": "标题",
            "body": "正文",
            "tags": ["EDC折刀"],
            "category": "娱乐",
            "browser_profile_id": "youtube-profile",
        },
    )

    assert payload["category"] == "娱乐"
    assert payload["publication_plan_signature"]["fields"]["category"] == "娱乐"
    assert payload["publication_content_signature"]["fields"]["category"] == "娱乐"


def test_build_request_payload_resolves_readable_local_media_path(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    plan = {"media_path": str(media_path)}
    target = {
        "platform": "bilibili",
        "title": "标题",
        "body": "正文",
        "browser_profile_id": "bili-profile",
    }

    payload = publication._build_request_payload(plan=plan, target=target)

    assert payload["media_items"][0]["local_path"] == str(media_path.resolve())
    assert payload["metadata"]["requested_media_path"] == str(media_path)
    assert payload["metadata"]["resolved_media_path"] == str(media_path.resolve())
    assert payload["metadata"]["media_path_unreadable"] is False


def test_build_request_payload_drops_unreadable_local_media_path(monkeypatch):
    monkeypatch.setattr(publication, "resolve_publication_local_media_path", lambda _raw: None)
    plan = {"media_path": r"E:\\missing\\video.mp4"}
    target = {
        "platform": "bilibili",
        "title": "标题",
        "body": "正文",
        "browser_profile_id": "bili-profile",
    }

    payload = publication._build_request_payload(plan=plan, target=target)

    assert payload["media_items"] == []
    assert payload["media_urls"] == []
    assert payload["metadata"]["requested_media_path"] == r"E:\\missing\\video.mp4"
    assert payload["metadata"]["resolved_media_path"] is None
    assert payload["metadata"]["media_path_unreadable"] is True


def test_build_browser_agent_task_payload_from_attempt_x_does_not_require_local_media_when_not_configured():
    attempt = PublicationAttempt(
        id="attempt-x-share",
        job_id=uuid.uuid4(),
        content_id="job-x-share",
        platform="x",
        platform_label="X",
        idempotency_key="key-x-share",
        semantic_fingerprint="fingerprint-x-share",
        adapter="browser_agent",
        status="queued",
        request_payload={
            "title": "标题",
            "body": "短视频测试",
            "platform_specific_overrides": {
                "x_share_link": "https://youtu.be/abc123",
            },
            "media_items": [],
            "media_urls": ["https://youtu.be/abc123"],
        },
    )

    payload = publication.build_browser_agent_task_payload_from_attempt(attempt)

    assert payload["task_id"] == "attempt-x-share"
    assert payload["attempt_id"] == "attempt-x-share"
    assert payload["content_id"] == "job-x-share"
    assert payload["content"]["media_items"] == []
    assert payload["content"]["media_urls"] == ["https://youtu.be/abc123"]
    assert payload["content"]["publish_media_source"]["provider"] == "link_only"
    assert payload["content"]["publish_media_source"]["mode"] == "link_only"


def test_build_browser_agent_task_payload_from_attempt_includes_reconcile_callback_url(monkeypatch):
    monkeypatch.setattr(
        publication,
        "_build_publication_reconcile_callback_url",
        lambda: "http://127.0.0.1:38471/api/v1/intelligent-copy/publication/reconcile-task",
    )
    attempt = PublicationAttempt(
        id="attempt-callback",
        job_id=uuid.uuid4(),
        content_id="job-callback",
        platform="x",
        platform_label="X",
        idempotency_key="key-callback",
        semantic_fingerprint="fingerprint-callback",
        adapter="browser_agent",
        status="queued",
        request_payload={
            "title": "标题",
            "body": "短视频测试",
            "platform_specific_overrides": {
                "x_share_link": "https://youtu.be/abc123",
            },
            "media_items": [],
            "media_urls": ["https://youtu.be/abc123"],
        },
    )

    payload = publication.build_browser_agent_task_payload_from_attempt(attempt)

    assert payload["reconcile_callback_url"] == "http://127.0.0.1:38471/api/v1/intelligent-copy/publication/reconcile-task"


def test_build_browser_agent_task_payload_preserves_cover_and_declaration_runtime_fields(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    cover_path = tmp_path / "cover.jpg"
    cover_path.write_bytes(b"cover")
    cover_slots = [
        {
            "slot": "feed_primary",
            "cover_path": str(cover_path),
            "target_size": {"width": 1080, "height": 1440},
        }
    ]
    plan = {"media_path": str(media_path)}
    target = {
        "platform": "xiaohongshu",
        "title": "标题",
        "body": "正文",
        "tags": ["标签"],
        "cover_path": str(cover_path),
        "cover_slots": cover_slots,
        "declaration": "原创声明",
        "copy_material": {
            "cover_path": str(cover_path),
            "cover_slots": cover_slots,
            "declaration": "原创声明",
            "source": "platform_packaging",
        },
        "browser_profile_id": "browser-profile:chrome:test",
    }

    payload = publication.build_browser_agent_task_payload("attempt-runtime-fields", plan=plan, target=target)

    assert payload["content"]["cover_path"] == str(cover_path)
    assert payload["content"]["cover_slots"] == cover_slots
    assert payload["content"]["declaration"] == "原创声明"
    assert payload["content"]["copy_material"]["cover_path"] == str(cover_path)
    assert payload["content"]["copy_material"]["cover_slots"] == cover_slots
    assert payload["content"]["copy_material"]["declaration"] == "原创声明"


def test_build_browser_agent_task_payload_defaults_collection_skip_for_safe_runtime_mode():
    plan = {"media_path": r"C:\\tmp\\video.mp4"}
    target = {
        "platform": "bilibili",
        "title": "标题",
        "body": "正文",
        "tags": ["标签"],
        "platform_specific_overrides": {
            "prepare_only_current_page": True,
            "recovery_mode": "prepublish_resume",
        },
    }

    payload = publication.build_browser_agent_task_payload("attempt-safe-collection-skip", plan=plan, target=target)
    overrides = payload["content"]["platform_specific_overrides"]

    assert overrides["prepare_only_current_page"] is True
    assert overrides["collection_policy"] == "skip"
    assert overrides["skip_collection_select"] is True


def test_build_browser_agent_task_payload_defaults_collection_skip_for_stop_before_final_publish():
    plan = {"media_path": r"C:\\tmp\\video.mp4"}
    target = {
        "platform": "bilibili",
        "title": "标题",
        "body": "正文",
        "tags": ["标签"],
        "platform_specific_overrides": {
            "stop_before_final_publish": True,
        },
    }

    payload = publication.build_browser_agent_task_payload("attempt-stop-before-collection-skip", plan=plan, target=target)
    overrides = payload["content"]["platform_specific_overrides"]

    assert overrides["stop_before_final_publish"] is True
    assert overrides["collection_policy"] == "skip"
    assert overrides["skip_collection_select"] is True


def test_build_browser_agent_task_payload_defaults_cover_skip_for_safe_runtime_mode():
    plan = {"media_path": r"C:\\tmp\\video.mp4"}
    target = {
        "platform": "youtube",
        "title": "标题",
        "body": "正文",
        "platform_specific_overrides": {
            "prepare_only_current_page": True,
            "recovery_mode": "prepublish_resume",
        },
    }

    payload = publication.build_browser_agent_task_payload("attempt-safe-cover-skip", plan=plan, target=target)
    overrides = payload["content"]["platform_specific_overrides"]

    assert overrides["prepare_only_current_page"] is True
    assert overrides["cover_policy"] == "platform_default"
    assert overrides["skip_cover_upload"] is True


def test_build_browser_agent_task_payload_from_attempt_preserves_safe_receipt_rebind_flags(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    attempt = PublicationAttempt(
        id="attempt-safe-receipt-rebind",
        job_id=uuid.uuid4(),
        content_id="job-safe-receipt-rebind",
        platform="douyin",
        platform_label="抖音",
        idempotency_key="key-safe-receipt-rebind",
        semantic_fingerprint="fingerprint-safe-receipt-rebind",
        adapter="browser_agent",
        status="queued",
        request_payload={
            "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
            "body": "正文",
            "hashtags": ["EDC折刀"],
            "display_hashtags": ["#EDC折刀"],
            "structured_tags": ["EDC折刀"],
            "scheduled_publish_at": "2026-05-31 20:30",
            "media_items": [
                {
                    "kind": "video",
                    "local_path": str(media_path),
                }
            ],
            "metadata": {
                "browser_profile_id": "browser-profile:chrome:21104fd69d72ad7267c2",
            },
            "platform_specific_overrides": {
                "verification_only_current_page": True,
                "wait_for_publish_confirmation": True,
                "verify_media_upload": True,
                "clear_draft_context": False,
                "force_publish_page_refresh": True,
                "recovery_mode": "receipt_rebind",
            },
        },
    )

    payload = publication.build_browser_agent_task_payload_from_attempt(attempt)
    overrides = payload["content"]["platform_specific_overrides"]

    assert overrides["verification_only_current_page"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert overrides["verify_media_upload"] is True
    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["recovery_mode"] == "receipt_rebind"


def test_build_browser_agent_task_payload_from_attempt_preserves_cover_and_declaration_runtime_fields(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    cover_path = tmp_path / "cover.jpg"
    cover_path.write_bytes(b"cover")
    cover_slots = [
        {
            "slot": "feed_primary",
            "cover_path": str(cover_path),
            "target_size": {"width": 1080, "height": 1440},
        }
    ]
    attempt = PublicationAttempt(
        id="attempt-runtime-material-fields",
        job_id=uuid.uuid4(),
        content_id="job-runtime-material-fields",
        platform="xiaohongshu",
        platform_label="小红书",
        idempotency_key="key-runtime-material-fields",
        semantic_fingerprint="fingerprint-runtime-material-fields",
        adapter="browser_agent",
        status="queued",
        request_payload={
            "title": "标题",
            "body": "正文",
            "cover_path": str(cover_path),
            "cover_slots": cover_slots,
            "declaration": "原创声明",
            "copy_material": {
                "cover_path": str(cover_path),
                "cover_slots": cover_slots,
                "declaration": "原创声明",
                "source": "platform_packaging",
            },
            "media_items": [
                {
                    "kind": "video",
                    "local_path": str(media_path),
                }
            ],
        },
    )

    payload = publication.build_browser_agent_task_payload_from_attempt(attempt)

    assert payload["content"]["cover_path"] == str(cover_path)
    assert payload["content"]["cover_slots"] == cover_slots
    assert payload["content"]["declaration"] == "原创声明"
    assert payload["content"]["copy_material"]["cover_path"] == str(cover_path)
    assert payload["content"]["copy_material"]["cover_slots"] == cover_slots
    assert payload["content"]["copy_material"]["declaration"] == "原创声明"


def test_build_browser_agent_task_payload_from_attempt_defaults_collection_skip_for_safe_runtime_mode(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    attempt = PublicationAttempt(
        id="attempt-safe-collection-skip-runtime",
        job_id=uuid.uuid4(),
        content_id="job-safe-collection-skip-runtime",
        platform="bilibili",
        platform_label="B站",
        idempotency_key="key-safe-collection-skip-runtime",
        semantic_fingerprint="fingerprint-safe-collection-skip-runtime",
        adapter="browser_agent",
        status="queued",
        request_payload={
            "title": "标题",
            "body": "正文",
            "media_items": [
                {
                    "kind": "video",
                    "local_path": str(media_path),
                }
            ],
            "platform_specific_overrides": {
                "prepare_only_current_page": True,
                "recovery_mode": "prepublish_resume",
            },
        },
    )

    payload = publication.build_browser_agent_task_payload_from_attempt(attempt)
    overrides = payload["content"]["platform_specific_overrides"]

    assert overrides["prepare_only_current_page"] is True
    assert overrides["collection_policy"] == "skip"
    assert overrides["skip_collection_select"] is True


def test_build_browser_agent_task_payload_from_attempt_defaults_collection_skip_for_stop_before_final_publish(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    attempt = PublicationAttempt(
        id="attempt-stop-before-collection-skip-runtime",
        job_id=uuid.uuid4(),
        content_id="job-stop-before-collection-skip-runtime",
        platform="bilibili",
        platform_label="B站",
        idempotency_key="key-stop-before-collection-skip-runtime",
        semantic_fingerprint="fingerprint-stop-before-collection-skip-runtime",
        adapter="browser_agent",
        status="queued",
        request_payload={
            "title": "标题",
            "body": "正文",
            "media_items": [
                {
                    "kind": "video",
                    "local_path": str(media_path),
                }
            ],
            "platform_specific_overrides": {
                "stop_before_final_publish": True,
            },
        },
    )

    payload = publication.build_browser_agent_task_payload_from_attempt(attempt)
    overrides = payload["content"]["platform_specific_overrides"]

    assert overrides["stop_before_final_publish"] is True
    assert overrides["collection_policy"] == "skip"
    assert overrides["skip_collection_select"] is True


def test_build_browser_agent_task_payload_from_attempt_defaults_cover_skip_for_safe_runtime_mode(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    attempt = PublicationAttempt(
        id="attempt-safe-cover-skip-runtime",
        job_id=uuid.uuid4(),
        content_id="job-safe-cover-skip-runtime",
        platform="youtube",
        platform_label="YouTube",
        idempotency_key="key-safe-cover-skip-runtime",
        semantic_fingerprint="fingerprint-safe-cover-skip-runtime",
        adapter="browser_agent",
        status="queued",
        request_payload={
            "title": "标题",
            "body": "正文",
            "media_items": [
                {
                    "kind": "video",
                    "local_path": str(media_path),
                }
            ],
            "platform_specific_overrides": {
                "prepare_only_current_page": True,
                "recovery_mode": "prepublish_resume",
            },
        },
    )

    payload = publication.build_browser_agent_task_payload_from_attempt(attempt)
    overrides = payload["content"]["platform_specific_overrides"]

    assert overrides["prepare_only_current_page"] is True
    assert overrides["cover_policy"] == "platform_default"
    assert overrides["skip_cover_upload"] is True


def test_intelligent_copy_packaging_normalization_preserves_title_audit():
    packaging = _normalize_intelligent_copy_payload_as_packaging(
        {
            "platforms": [
                {
                    "key": "x",
                    "titles": ["只有一个标题"],
                    "body": "推文",
                    "tags": ["tag"],
                }
            ],
            "title_audit": {
                "summary": {"status": "error"},
                "platforms": {
                    "x": {
                        "summary": {"status": "error"},
                        "issues": [{"message": "X 只有 1 个标题，没满足 3 个版本输出要求。"}],
                    }
                },
            },
        }
    )

    assert packaging is not None
    assert packaging["title_audit"]["summary"]["status"] == "error"
    assert packaging["title_audit"]["platforms"]["x"]["summary"]["status"] == "error"


def test_intelligent_copy_packaging_normalization_accepts_platform_packaging_object_shape():
    packaging = _normalize_intelligent_copy_payload_as_packaging(
        {
            "platforms": {
                "youtube": {
                    "primary_title": "真实标题",
                    "description": "真实描述",
                    "declaration": "无需添加自主声明",
                    "live_publish_preflight": {"status": "ready"},
                }
            },
            "title_audit": {
                "platforms": {
                    "youtube": {
                        "summary": {"status": "pass"},
                    }
                }
            },
        },
        material_dir="E:/materials/maxace/smart-copy",
    )

    assert packaging is not None
    assert packaging["platforms"]["youtube"]["declaration"] == "无需添加自主声明"
    assert packaging["platforms"]["youtube"]["live_publish_preflight"]["status"] == "ready"
    assert packaging["material_dir"] == "E:/materials/maxace/smart-copy"
    assert packaging["source"] == "platform_packaging"
    assert packaging["platforms"]["youtube"]["publish_ready"] is True
    assert packaging["publish_ready"] is True


def test_intelligent_copy_packaging_normalization_preserves_manual_handoff_contract_from_smart_copy_shape():
    packaging = _normalize_intelligent_copy_payload_as_packaging(
        {
            "platforms": [
                {
                    "key": "wechat-channels",
                    "titles": [],
                    "body": "正文",
                    "tags": [],
                    "publish_ready": False,
                }
            ],
            "material_contract": {
                "platform_scope": {
                    "requested_platforms": ["wechat-channels"],
                    "covered_platforms": ["wechat-channels"],
                    "missing_requested_platforms": [],
                },
                "platforms": {
                    "wechat-channels": {
                        "manual_handoff_only": True,
                        "manual_publish_entry_url": "https://channels.weixin.qq.com/login.html",
                        "blocking_reasons": ["当前平台仅支持人工登录后继续发布。"],
                    }
                },
            },
        },
        material_dir="E:/materials/maxace/smart-copy",
    )

    assert packaging is not None
    assert packaging["platform_scope"]["covered_platforms"] == ["wechat-channels"]
    assert packaging["platforms"]["wechat-channels"]["manual_handoff_only"] is True
    assert packaging["platforms"]["wechat-channels"]["manual_publish_entry_url"] == "https://channels.weixin.qq.com/login.html"
    assert packaging["platforms"]["wechat-channels"]["blocking_reasons"] == ["当前平台仅支持人工登录后继续发布。"]


def test_intelligent_copy_packaging_normalization_preserves_publication_metadata_from_smart_copy_shape():
    packaging = _normalize_intelligent_copy_payload_as_packaging(
        {
            "platforms": [
                {
                    "key": "xiaohongshu",
                    "titles": ["标题"],
                    "primary_title": "标题",
                    "body": "正文",
                    "tags": ["开箱"],
                    "cover_path": "E:/covers/xhs.jpg",
                    "cover_generation": {
                        "publish_ready": True,
                        "target_size": {"width": 1080, "height": 1440},
                    },
                    "declaration": "原创声明",
                    "category": "数码",
                    "collection_name": "EDC潮玩桌搭",
                    "collection": {"name": "EDC潮玩桌搭"},
                    "visibility_or_publish_mode": "scheduled",
                    "scheduled_publish_at": "2026-06-01T21:00",
                    "copy_material": {"source": "intelligent_copy_material_self_heal"},
                    "live_publish_preflight": {"status": "ready", "required_surfaces": ["topics", "collection"]},
                    "platform_specific_overrides": {"selected_declarations": ["原创声明"]},
                    "publish_ready": True,
                    "blocking_reasons": [],
                }
            ],
        },
        material_dir="E:/materials/maxace/smart-copy",
    )

    assert packaging is not None
    material = packaging["platforms"]["xiaohongshu"]
    assert material["cover_path"] == "E:/covers/xhs.jpg"
    assert material["cover_slots"] == [
        {
            "slot": "primary",
            "cover_path": "E:/covers/xhs.jpg",
            "target_size": {"width": 1080, "height": 1440},
        }
    ]
    assert material["cover_generation"]["publish_ready"] is True
    assert material["declaration"] == "原创声明"
    assert material["category"] == "数码"
    assert material["collection_name"] == "EDC潮玩桌搭"
    assert material["collection"]["name"] == "EDC潮玩桌搭"
    assert material["visibility_or_publish_mode"] == "scheduled"
    assert material["scheduled_publish_at"] == "2026-06-01T21:00"
    assert material["copy_material"]["source"] == "intelligent_copy_material_self_heal"
    assert material["live_publish_preflight"]["status"] == "ready"
    assert material["platform_specific_overrides"]["selected_declarations"] == ["原创声明"]


def test_intelligent_copy_packaging_normalization_projects_required_douyin_cover_slots_from_shared_cover_matrix():
    packaging = _normalize_intelligent_copy_payload_as_packaging(
        {
            "platforms": [
                {
                    "key": "douyin",
                    "titles": ["标题"],
                    "primary_title": "标题",
                    "body": "正文",
                    "tags": ["开箱"],
                    "cover_path": "E:/covers/douyin-derived.jpg",
                    "cover_generation": {
                        "publish_ready": True,
                        "target_size": {"width": 1080, "height": 1920},
                    },
                    "copy_material": {"source": "intelligent_copy_material_self_heal"},
                    "live_publish_preflight": {"status": "ready"},
                    "publish_ready": True,
                    "blocking_reasons": [],
                }
            ],
            "cover_matrix": {
                "landscape_4_3": {
                    "label": "4:3 横版母版",
                    "cover_size": [1440, 1080],
                    "cover_path": "E:/covers/landscape-4-3.jpg",
                },
                "portrait_3_4": {
                    "label": "3:4 竖版母版",
                    "cover_size": [1080, 1440],
                    "cover_path": "E:/covers/portrait-3-4.jpg",
                },
            },
        },
        material_dir="E:/materials/maxace/smart-copy",
    )

    assert packaging is not None
    material = packaging["platforms"]["douyin"]
    assert material["cover_path"] == "E:/covers/landscape-4-3.jpg"
    assert material["cover_slots"] == [
        {
            "slot": "horizontal_4_3",
            "cover_path": "E:/covers/landscape-4-3.jpg",
            "target_size": {"width": 1440, "height": 1080},
            "label": "横封面4:3",
            "matrix_key": "landscape_4_3",
        },
        {
            "slot": "vertical_3_4",
            "cover_path": "E:/covers/portrait-3-4.jpg",
            "target_size": {"width": 1080, "height": 1440},
            "label": "竖封面3:4",
            "matrix_key": "portrait_3_4",
        },
    ]


def test_intelligent_copy_packaging_normalization_projects_bilibili_dual_cover_slots_from_shared_cover_matrix():
    packaging = _normalize_intelligent_copy_payload_as_packaging(
        {
            "platforms": [
                {
                    "key": "bilibili",
                    "titles": ["标题"],
                    "primary_title": "标题",
                    "body": "正文",
                    "tags": ["开箱"],
                    "cover_path": "E:/covers/bilibili-4-3.jpg",
                    "cover_generation": {
                        "publish_ready": True,
                        "target_size": {"width": 1440, "height": 1080},
                    },
                    "copy_material": {"source": "intelligent_copy_material_self_heal"},
                    "live_publish_preflight": {"status": "ready"},
                    "publish_ready": True,
                    "blocking_reasons": [],
                }
            ],
            "cover_matrix": {
                "landscape_4_3": {
                    "label": "4:3 横版母版",
                    "cover_size": [1440, 1080],
                    "cover_path": "E:/covers/bilibili-4-3.jpg",
                },
                "landscape_16_9": {
                    "label": "16:9 横版母版",
                    "cover_size": [1600, 900],
                    "cover_path": "E:/covers/bilibili-16-9.jpg",
                },
            },
        },
        material_dir="E:/materials/maxace/smart-copy",
    )

    assert packaging is not None
    material = packaging["platforms"]["bilibili"]
    assert material["cover_path"] == "E:/covers/bilibili-4-3.jpg"
    assert material["cover_slots"] == [
        {
            "slot": "landscape_4_3",
            "cover_path": "E:/covers/bilibili-4-3.jpg",
            "target_size": {"width": 1440, "height": 1080},
            "label": "首页推荐封面（4:3）",
            "matrix_key": "landscape_4_3",
        },
        {
            "slot": "landscape_16_9",
            "cover_path": "E:/covers/bilibili-16-9.jpg",
            "target_size": {"width": 1600, "height": 900},
            "label": "个人空间封面（16:9）",
            "matrix_key": "landscape_16_9",
        },
    ]


def test_intelligent_copy_packaging_normalization_derives_publish_ready_from_platform_entries_when_root_flag_missing():
    packaging = _normalize_intelligent_copy_payload_as_packaging(
        {
            "platforms": [
                {
                    "key": "douyin",
                    "titles": ["标题"],
                    "primary_title": "标题",
                    "body": "正文",
                    "tags": ["开箱"],
                    "live_publish_preflight": {
                        "status": "ready",
                        "missing_required_surfaces": [],
                    },
                    "blocking_reasons": [],
                }
            ],
        },
        material_dir="E:/materials/maxace/smart-copy",
    )

    assert packaging is not None
    assert packaging["platforms"]["douyin"]["publish_ready"] is True
    assert packaging["publish_ready"] is True


def test_intelligent_copy_packaging_normalization_derives_blocked_publish_ready_when_flags_missing():
    packaging = _normalize_intelligent_copy_payload_as_packaging(
        {
            "platforms": [
                {
                    "key": "douyin",
                    "titles": ["标题"],
                    "primary_title": "标题",
                    "body": "正文",
                    "tags": ["开箱"],
                    "live_publish_preflight": {
                        "status": "blocked",
                        "missing_required_surfaces": ["cover"],
                    },
                    "blocking_reasons": [],
                }
            ],
        },
        material_dir="E:/materials/maxace/smart-copy",
    )

    assert packaging is not None
    assert packaging["platforms"]["douyin"]["publish_ready"] is False
    assert packaging["publish_ready"] is False


def test_intelligent_copy_packaging_normalization_overrides_stale_entry_publish_ready_true_when_preflight_blocked():
    packaging = _normalize_intelligent_copy_payload_as_packaging(
        {
            "platforms": {
                "youtube": {
                    "primary_title": "真实标题",
                    "description": "真实描述",
                    "publish_ready": True,
                    "live_publish_preflight": {
                        "status": "blocked",
                        "missing_required_surfaces": ["editor_surface"],
                    },
                    "blocking_reasons": [],
                }
            },
        },
        material_dir="E:/materials/maxace/smart-copy",
    )

    assert packaging is not None
    assert packaging["platforms"]["youtube"]["publish_ready"] is False
    assert packaging["publish_ready"] is False


def test_intelligent_copy_packaging_normalization_derives_blocking_reasons_from_preflight_when_missing():
    packaging = _normalize_intelligent_copy_payload_as_packaging(
        {
            "platforms": {
                "youtube": {
                    "primary_title": "真实标题",
                    "description": "真实描述",
                    "live_publish_preflight": {
                        "status": "blocked",
                        "missing_required_surfaces": ["editor_surface"],
                    },
                    "blocking_reasons": [],
                }
            },
        },
        material_dir="E:/materials/maxace/smart-copy",
    )

    assert packaging is not None
    assert packaging["platforms"]["youtube"]["publish_ready"] is False
    assert packaging["platforms"]["youtube"]["blocking_reasons"] == ["缺少发布前必要页面能力：editor_surface"]


def test_intelligent_copy_packaging_normalization_blocks_missing_publication_metadata_and_collection_policy():
    packaging = _normalize_intelligent_copy_payload_as_packaging(
        {
            "platforms": {
                "bilibili": {
                    "primary_title": "真实标题",
                    "description": "真实描述",
                    "cover_path": "E:/materials/bilibili-cover.jpg",
                    "declaration": "",
                    "category": "",
                    "collection_name": "",
                    "collection": {},
                    "visibility_or_publish_mode": "",
                    "scheduled_publish_at": "",
                    "platform_specific_overrides": {},
                    "live_publish_preflight": {"status": "ready"},
                    "blocking_reasons": [],
                }
            },
        },
        material_dir="E:/materials/bilibili/smart-copy",
    )

    assert packaging is not None
    assert packaging["platforms"]["bilibili"]["publish_ready"] is False
    assert packaging["publish_ready"] is False
    assert packaging["platforms"]["bilibili"]["blocking_reasons"] == [
        "缺少平台专属发布配置（declaration/category/collection/visibility/schedule）",
        "缺少合集决策（需指定 collection_name 或显式声明跳过合集）",
    ]


def test_load_intelligent_copy_packaging_prefers_platform_packaging_json_object_shape(tmp_path):
    material_dir = tmp_path / "smart-copy"
    material_dir.mkdir()
    (material_dir / "platform-packaging.json").write_text(
        json.dumps(
            {
                "platforms": {
                    "youtube": {
                        "primary_title": "包装标题",
                        "description": "包装描述",
                        "declaration": "无需添加自主声明",
                        "live_publish_preflight": {"status": "ready"},
                    }
                },
                "title_audit": {
                    "platforms": {
                        "youtube": {
                            "summary": {"status": "pass"},
                        }
                    }
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (material_dir / "smart-copy.json").write_text(
        json.dumps(
            {
                "platforms": [
                    {
                        "key": "youtube",
                        "primary_title": "旧标题",
                        "body": "旧描述",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    packaging = _load_intelligent_copy_packaging(tmp_path)

    assert packaging is not None
    assert packaging["platforms"]["youtube"]["primary_title"] == "包装标题"
    assert packaging["platforms"]["youtube"]["declaration"] == "无需添加自主声明"
    assert packaging["platforms"]["youtube"]["live_publish_preflight"]["status"] == "ready"
    assert packaging["material_dir"] == str(material_dir)
    assert packaging["source"] == "platform_packaging"


def test_jobs_platform_packaging_summary_title_accepts_object_shape_payload():
    title = jobs_api._resolve_platform_packaging_summary_title(
        {
            "highlights": {"product": "MAXACE"},
            "platforms": {
                "douyin": {
                    "titles": ["两款同时开！美杜莎4顶配次顶配差别出来了"],
                    "description": "正文",
                },
                "xiaohongshu": {
                    "titles": ["新到的美杜莎4｜两款配置到手，差别一眼就看出来"],
                    "description": "正文",
                },
            },
        }
    )

    assert title == "两款同时开！美杜莎4顶配次顶配差别出来了"


def test_jobs_artifact_event_summary_uses_platform_packaging_title_for_object_shape_payload():
    artifact = Artifact(
        artifact_type="platform_packaging_md",
        storage_path="E:/materials/maxace/platform_packaging_renderless.md",
        data_json={
            "highlights": {"product": "MAXACE"},
            "platforms": {
                "douyin": {
                    "titles": ["两款同时开！美杜莎4顶配次顶配差别出来了"],
                    "description": "正文",
                }
            },
        },
    )

    summary = jobs_api._artifact_event_summary(artifact)

    assert summary is not None
    assert summary["detail"] == "两款同时开！美杜莎4顶配次顶配差别出来了"


def test_extract_publication_field_snapshot_reads_browser_agent_progress_snapshot():
    payload = {
        "task": {
            "task_id": "task-progress-1",
            "status": "processing",
            "progress": {
                "phase": "publish_receipt_poll",
                "publication_field_snapshot": {
                    "platform": "douyin",
                    "title": "进度标题",
                    "visibility_or_publish_mode": "scheduled",
                },
            },
        }
    }

    assert publication._extract_publication_field_snapshot(payload) == {
        "platform": "douyin",
        "title": "进度标题",
        "visibility_or_publish_mode": "scheduled",
    }


def test_extract_publication_field_snapshot_reads_timeout_progress_snapshot():
    payload = {
        "task": {
            "task_id": "task-timeout-1",
            "status": "submitted",
            "result": {
                "timeout_progress": {
                    "publication_field_snapshot": {
                        "platform": "douyin",
                        "title": "超时进度标题",
                    },
                },
            },
        }
    }

    assert publication._extract_publication_field_snapshot(payload) == {
        "platform": "douyin",
        "title": "超时进度标题",
    }


def test_extract_publication_field_snapshot_reads_material_integrity_fields():
    payload = {
        "task": {
            "task_id": "task-material-1",
            "status": "processing",
            "progress": {
                "material_integrity": {
                    "platform": "douyin",
                    "fields": {
                        "title": {"actual": "进度标题", "verified": True},
                        "body": {"actual": "进度正文", "verified": True},
                        "tags": {"actual": ["标签A", "标签B"], "verified": True},
                        "schedule": {"actual": "2026-05-31 20:30", "verified": True},
                    },
                }
            },
        }
    }

    assert publication._extract_publication_field_snapshot(payload) == {
        "platform": "douyin",
        "title": "进度标题",
        "body": "进度正文",
        "hashtags": ["标签A", "标签B"],
        "display_hashtags": ["#标签A", "#标签B"],
        "structured_tags": ["标签A", "标签B"],
        "scheduled_publish_at": "2026-05-31T20:30",
    }


def test_extract_publication_field_snapshot_prefers_richer_progress_integrity_over_sparse_top_level_fields():
    payload = {
        "fields": {
            "title": "进度标题",
            "body": "进度正文",
            "hashtags": ["标签A", "标签B"],
        },
        "task": {
            "task_id": "task-material-priority-1",
            "status": "processing",
            "progress": {
                "material_integrity": {
                    "platform": "douyin",
                    "fields": {
                        "title": {"actual": "进度标题", "verified": True},
                        "body": {"actual": "进度正文", "verified": True},
                        "tags": {"actual": ["标签A", "标签B"], "verified": True},
                        "schedule": {"actual": "2026-05-31 20:30", "verified": True},
                    },
                }
            },
        },
    }

    assert publication._extract_publication_field_snapshot(payload) == {
        "platform": "douyin",
        "title": "进度标题",
        "body": "进度正文",
        "hashtags": ["标签A", "标签B"],
        "display_hashtags": ["#标签A", "#标签B"],
        "structured_tags": ["标签A", "标签B"],
        "scheduled_publish_at": "2026-05-31T20:30",
    }


@pytest.mark.asyncio
async def test_apply_browser_agent_task_state_blocks_success_when_audit_failed(monkeypatch):
    attempt = SimpleNamespace(
        provider_status=None,
        provider_task_id=None,
        provider_execution_id=None,
        response_payload=None,
        status="processing",
        run_status="processing",
        published_at=None,
        scheduled_at=None,
        external_post_id=None,
        external_receipt_id=None,
        external_url=None,
        error_code=None,
        error_message=None,
        operator_summary=None,
    )
    async def _mock_recovery_analysis(*args, **kwargs):
        return {
            "severity": "high",
            "action": "manual_check",
            "retryable": False,
            "next_steps": ["检查封面与账号授权", "重新触发发布任务"],
            "confidence": 0.94,
            "evidence": ["publication_audit_unverified"],
            "rationale": "发布前审计未通过，建议保留内容并补齐素材。",
        }

    monkeypatch.setattr(publication, "_analyze_publication_failure_with_llm", _mock_recovery_analysis)
    run = SimpleNamespace(
        status="processing",
        phase="reconcile",
        heartbeat_at=None,
        provider_task_id=None,
        provider_execution_id=None,
        provider_status=None,
        result_json=None,
        error_message=None,
        completed_at=None,
    )
    task = {
        "task_id": "task-1",
        "status": "published",
        "result": {
            "public_url": "https://youtu.be/example",
            "publication_audit": {
                "verified": False,
                "required_unverified": ["cover", "collection"],
            },
        },
    }

    await publication._apply_browser_agent_task_state(attempt, run, task, response_payload={"task": task})

    assert attempt.status == "needs_human"
    assert attempt.error_code == "publication_audit_unverified"
    assert "cover" in attempt.error_message
    assert "collection" in attempt.error_message
    assert "LLM 异常诊断" in str(attempt.error_message)
    assert run.status == "needs_human"


@pytest.mark.asyncio
async def test_apply_browser_agent_task_state_blocks_published_without_public_url():
    attempt = SimpleNamespace(
        id="attempt-published-no-url",
        adapter="browser_agent",
        platform="douyin",
        provider_status=None,
        provider_task_id="task-1",
        provider_execution_id="run-1",
        response_payload=None,
        status="processing",
        run_status="processing",
        published_at=None,
        scheduled_at=None,
        external_post_id=None,
        external_receipt_id=None,
        external_url=None,
        retry_count=0,
        max_retries=3,
        next_retry_at=None,
        error_code=None,
        error_message=None,
        operator_summary=None,
        request_payload={
            "publication_content_signature": {
                "version": 1,
                "value": "abcd",
                "fields": {},
            }
        },
    )
    run = SimpleNamespace(
        status="processing",
        phase="reconcile",
        heartbeat_at=None,
        provider_task_id="task-1",
        provider_execution_id="run-1",
        provider_status=None,
        result_json=None,
        error_message=None,
        completed_at=None,
    )
    task = {
        "task_id": "task-1",
        "status": "published",
        "result": {
            "publication_audit": {
                "verified": True,
            }
        },
    }

    await publication._apply_browser_agent_task_state(attempt, run, task, response_payload={"task": task})

    assert attempt.status == "needs_human"
    assert attempt.error_code == "publication_public_url_missing"
    assert "未读到可公开访问链接" in attempt.error_message
    assert run.status == "needs_human"


@pytest.mark.asyncio
async def test_apply_browser_agent_task_state_blocks_signature_mismatch_publish():
    attempt = SimpleNamespace(
        id="attempt-published-signature-mismatch",
        adapter="browser_agent",
        platform="xiaohongshu",
        provider_status=None,
        provider_task_id="task-2",
        provider_execution_id="run-2",
        response_payload=None,
        status="processing",
        run_status="processing",
        published_at=None,
        scheduled_at=None,
        external_post_id=None,
        external_receipt_id=None,
        external_url=None,
        retry_count=0,
        max_retries=3,
        next_retry_at=None,
        error_code=None,
        error_message=None,
        operator_summary=None,
        request_payload={
            "publication_content_signature": {
                "version": 1,
                "value": "expected-signature",
                "fields": {},
            }
        },
    )
    run = SimpleNamespace(
        status="processing",
        phase="reconcile",
        heartbeat_at=None,
        provider_task_id="task-2",
        provider_execution_id="run-2",
        provider_status=None,
        result_json=None,
        error_message=None,
        completed_at=None,
    )
    task = {
        "task_id": "task-2",
        "status": "published",
        "result": {
            "public_url": "https://www.xiaohongshu.com/discover/abc",
            "publication_content_signature": {
                "version": 1,
                "value": "different-signature",
                "fields": {},
            },
            "publication_audit": {
                "verified": True,
            },
        },
    }

    await publication._apply_browser_agent_task_state(attempt, run, task, response_payload={"task": task})

    assert attempt.status == "needs_human"
    assert attempt.error_code == "publication_signature_mismatch"
    assert "内容签名" in attempt.error_message
    assert run.status == "needs_human"


@pytest.mark.asyncio
async def test_apply_browser_agent_task_state_accepts_bound_receipt_verification_success():
    attempt = SimpleNamespace(
        id="attempt-xhs-bound-receipt-1",
        adapter="browser_agent",
        platform="xiaohongshu",
        provider_status=None,
        provider_task_id="task-xhs-bound-1",
        provider_execution_id="run-xhs-bound-1",
        response_payload=None,
        status="processing",
        run_status="processing",
        published_at=None,
        scheduled_at=None,
        external_post_id=None,
        external_receipt_id=None,
        external_url=None,
        retry_count=0,
        max_retries=3,
        next_retry_at=None,
        error_code=None,
        error_message=None,
        operator_summary=None,
        request_payload={
            "publication_plan_signature": {
                "version": 1,
                "value": "sig-xhs-bound-1",
                "fields": {"title": "锆合金版本的音叉推牌，质感绝了"},
            }
        },
    )
    run = SimpleNamespace(
        status="processing",
        phase="reconcile",
        heartbeat_at=None,
        provider_task_id="task-xhs-bound-1",
        provider_execution_id="run-xhs-bound-1",
        provider_status=None,
        result_json=None,
        error_message=None,
        completed_at=None,
    )
    task = {
        "task_id": "task-xhs-bound-1",
        "status": "verified",
        "result": {
            "material_integrity": {
                "platform": "xiaohongshu",
                "verified": True,
                "failures": [],
                "platform_extras": {
                    "receipt_like": True,
                    "post_publish_surface": "xiaohongshu_note_manager_receipt",
                    "receipt_target_bound": True,
                    "receipt_binding_source": "xiaohongshu_note_manager_card",
                    "xiaohongshu_note_manager_card": {
                        "matched": True,
                        "title": "锆合金版本的音叉推牌，质感绝了",
                    },
                },
            },
            "publication_audit": {
                "verified": True,
                "required_unverified": [],
                "required_reupload": [],
                "platform_extras": {
                    "receipt_like": True,
                    "post_publish_surface": "xiaohongshu_note_manager_receipt",
                    "receipt_target_bound": True,
                    "receipt_binding_source": "xiaohongshu_note_manager_card",
                    "xiaohongshu_note_manager_card": {
                        "matched": True,
                        "title": "锆合金版本的音叉推牌，质感绝了",
                    },
                },
            },
            "final_publish": {
                "receipt_like": True,
                "post_click_integrity": {
                    "platform_extras": {
                        "receipt_like": True,
                        "post_publish_surface": "xiaohongshu_note_manager_receipt",
                        "receipt_target_bound": True,
                        "receipt_binding_source": "xiaohongshu_note_manager_card",
                        "xiaohongshu_note_manager_card": {
                            "matched": True,
                            "title": "锆合金版本的音叉推牌，质感绝了",
                        },
                    }
                },
            },
        },
    }

    await publication._apply_browser_agent_task_state(attempt, run, task, response_payload={"task": task})

    assert attempt.status == "published"
    assert attempt.run_status == "published"
    assert attempt.error_code is None
    assert attempt.error_message is None
    assert attempt.operator_summary == "已通过发布后回执绑定确认本次作品。"
    assert str(attempt.external_receipt_id or "").startswith("receipt-binding:")
    assert run.status == "published"
    assert run.completed_at is not None


@pytest.mark.asyncio
async def test_apply_browser_agent_task_state_accepts_legacy_published_bound_receipt_success():
    attempt = SimpleNamespace(
        id="attempt-douyin-bound-receipt-legacy-published-1",
        adapter="browser_agent",
        platform="douyin",
        provider_status=None,
        provider_task_id="task-douyin-bound-legacy-1",
        provider_execution_id="run-douyin-bound-legacy-1",
        response_payload=None,
        status="processing",
        run_status="processing",
        published_at=None,
        scheduled_at=None,
        external_post_id=None,
        external_receipt_id=None,
        external_url=None,
        retry_count=0,
        max_retries=3,
        next_retry_at=None,
        error_code=None,
        error_message=None,
        operator_summary=None,
        request_payload={
            "publication_plan_signature": {
                "version": 1,
                "value": "sig-douyin-bound-legacy-1",
                "fields": {"title": "MAXACE美杜莎4双版本开箱，顶配次顶配哪个更值"},
            }
        },
    )
    run = SimpleNamespace(
        status="processing",
        phase="reconcile",
        heartbeat_at=None,
        provider_task_id="task-douyin-bound-legacy-1",
        provider_execution_id="run-douyin-bound-legacy-1",
        provider_status=None,
        result_json=None,
        error_message=None,
        completed_at=None,
    )
    receipt_extras = {
        "receipt_like": True,
        "post_publish_surface": "douyin_content_manage_receipt",
        "receipt_target_bound": True,
        "receipt_binding_source": "douyin_manage_card",
        "douyin_manage_card": {
            "matched": True,
            "title": "MAXACE美杜莎4双版本开箱，顶配次顶配哪个更值",
        },
    }
    task = {
        "task_id": "task-douyin-bound-legacy-1",
        "status": "published",
        "result": {
            "publication_audit": {
                "verified": True,
                "required_unverified": [],
                "required_reupload": [],
                "platform_extras": receipt_extras,
            },
            "final_publish": {
                "receipt_like": True,
                "post_click_integrity": {
                    "platform_extras": receipt_extras,
                },
            },
        },
    }

    await publication._apply_browser_agent_task_state(attempt, run, task, response_payload={"task": task})

    assert attempt.status == "published"
    assert attempt.run_status == "published"
    assert attempt.error_code is None
    assert attempt.error_message is None
    assert attempt.operator_summary == "已通过发布后回执绑定确认本次作品。"
    assert str(attempt.external_receipt_id or "").startswith("receipt-binding:")
    assert run.status == "published"
    assert run.completed_at is not None


@pytest.mark.asyncio
async def test_apply_browser_agent_task_state_preserves_receipt_binding_id_when_task_needs_human_but_receipt_is_bound(monkeypatch):
    async def _no_diagnosis(*args, **kwargs):
        return None

    monkeypatch.setattr(publication, "_analyze_publication_failure_with_llm", _no_diagnosis)
    attempt = SimpleNamespace(
        id="attempt-douyin-bound-receipt-needs-human-1",
        adapter="browser_agent",
        platform="douyin",
        provider_status=None,
        provider_task_id="task-douyin-bound-needs-human-1",
        provider_execution_id="run-douyin-bound-needs-human-1",
        response_payload=None,
        status="processing",
        run_status="processing",
        published_at=None,
        scheduled_at=None,
        external_post_id=None,
        external_receipt_id=None,
        external_url=None,
        retry_count=0,
        max_retries=3,
        next_retry_at=None,
        error_code=None,
        error_message=None,
        operator_summary=None,
        request_payload={
            "publication_plan_signature": {
                "version": 1,
                "value": "sig-douyin-bound-needs-human-1",
                "fields": {"title": "FAS刀帕收纳方法 弹力绳和伞绳绑扣的更换和用法 听说真正的EDC高手 都会用刀帕"},
            }
        },
    )
    run = SimpleNamespace(
        status="processing",
        phase="reconcile",
        heartbeat_at=None,
        provider_task_id="task-douyin-bound-needs-human-1",
        provider_execution_id="run-douyin-bound-needs-human-1",
        provider_status=None,
        result_json=None,
        error_message=None,
        completed_at=None,
    )
    receipt_extras = {
        "receipt_like": True,
        "post_publish_surface": "douyin_content_manage_receipt",
        "receipt_target_bound": True,
        "receipt_binding_source": "douyin_manage_card",
        "douyin_manage_card": {
            "matched": True,
            "title": "FAS刀帕收纳方法 弹力绳和伞绳绑扣的更换和用法 听说真正的EDC高手 都会用刀帕",
        },
    }
    task = {
        "task_id": "task-douyin-bound-needs-human-1",
        "status": "needs_human",
        "result": {
            "verification_reason": "receipt_bound",
            "material_integrity": {
                "platform": "douyin",
                "verified": False,
                "failures": [],
                "verification_reason": "receipt_bound",
                "platform_extras": receipt_extras,
            },
            "publication_audit": {
                "verified": False,
                "required_unverified": ["cover"],
                "required_reupload": [],
                "platform_extras": receipt_extras,
            },
            "final_publish": {
                "receipt_like": True,
                "post_click_integrity": {
                    "platform_extras": receipt_extras,
                },
            },
        },
        "error": {
            "code": "publication_audit_unverified",
            "message": "cover 未通过",
        },
    }

    await publication._apply_browser_agent_task_state(attempt, run, task, response_payload={"task": task})

    assert attempt.status == "needs_human"
    assert attempt.run_status == "needs_human"
    assert attempt.error_code == "publication_audit_unverified"
    assert str(attempt.external_receipt_id or "").startswith("receipt-binding:")
    assert run.status == "needs_human"
    assert run.completed_at is not None


@pytest.mark.asyncio
async def test_apply_browser_agent_task_state_does_not_auto_retry_when_receipt_already_bound_but_audit_is_unverified():
    attempt = SimpleNamespace(
        id="attempt-douyin-bound-receipt-no-retry-1",
        adapter="browser_agent",
        platform="douyin",
        provider_status=None,
        provider_task_id="task-douyin-bound-no-retry-1",
        provider_execution_id="run-douyin-bound-no-retry-1",
        response_payload=None,
        status="processing",
        run_status="processing",
        published_at=None,
        scheduled_at=None,
        external_post_id=None,
        external_receipt_id=None,
        external_url=None,
        retry_count=0,
        max_retries=3,
        next_retry_at=None,
        error_code=None,
        error_message=None,
        operator_summary=None,
        request_payload={
            "publication_plan_signature": {
                "version": 1,
                "value": "sig-douyin-bound-no-retry-1",
                "fields": {"title": "FAS刀帕收纳方法 弹力绳和伞绳绑扣的更换和用法 听说真正的EDC高手 都会用刀帕"},
            }
        },
    )
    run = SimpleNamespace(
        status="processing",
        phase="reconcile",
        heartbeat_at=None,
        provider_task_id="task-douyin-bound-no-retry-1",
        provider_execution_id="run-douyin-bound-no-retry-1",
        provider_status=None,
        result_json=None,
        error_message=None,
        completed_at=None,
    )
    receipt_extras = {
        "receipt_like": True,
        "post_publish_surface": "douyin_content_manage_receipt",
        "receipt_target_bound": True,
        "receipt_binding_source": "douyin_manage_card",
        "douyin_manage_card": {
            "matched": True,
            "title": "FAS刀帕收纳方法 弹力绳和伞绳绑扣的更换和用法 听说真正的EDC高手 都会用刀帕",
        },
    }
    task = {
        "task_id": "task-douyin-bound-no-retry-1",
        "status": "needs_human",
        "result": {
            "verification_reason": "receipt_bound",
            "material_integrity": {
                "platform": "douyin",
                "verified": False,
                "failures": [],
                "verification_reason": "receipt_bound",
                "platform_extras": receipt_extras,
            },
            "publication_audit": {
                "verified": False,
                "required_unverified": ["cover"],
                "required_reupload": [],
                "platform_extras": receipt_extras,
            },
            "final_publish": {
                "receipt_like": True,
                "post_click_integrity": {
                    "platform_extras": receipt_extras,
                },
            },
        },
        "error": {
            "code": "publication_audit_unverified",
            "message": "cover 未通过",
        },
    }

    await publication._apply_browser_agent_task_state(attempt, run, task, response_payload={"task": task})

    assert attempt.status == "needs_human"
    assert attempt.run_status == "needs_human"
    assert attempt.retry_count == 0
    assert attempt.next_retry_at is None
    assert attempt.provider_task_id == "task-douyin-bound-no-retry-1"
    assert str(attempt.external_receipt_id or "").startswith("receipt-binding:")
    assert run.status == "needs_human"


def test_derive_recovery_diagnosis_from_context_does_not_retry_when_receipt_already_bound():
    context = {
        "receipt_binding": {
            "receipt_like": True,
            "receipt_target_bound": True,
            "receipt_binding_source": "douyin_manage_card",
            "post_publish_surface": "douyin_content_manage_receipt",
        },
        "error": {
            "code": "publication_audit_unverified",
            "message": "cover 未通过",
        },
        "recovery": {
            "code": "douyin_verification_only_material_integrity_failed",
            "reason": "字段校验未通过",
        },
    }

    diagnosis = publication._derive_recovery_diagnosis_from_context(context)

    assert diagnosis is not None
    assert diagnosis["resolution_source"] == "rule"
    assert diagnosis["action"] == "manual_check"
    assert diagnosis["retryable"] is False


@pytest.mark.asyncio
async def test_reconcile_publication_attempt_from_browser_agent_payload_accepts_attempt_id_bound_receipt():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            attempt = PublicationAttempt(
                id="attempt-receipt-rebind-1",
                job_id=uuid.uuid4(),
                content_id="job-receipt-rebind-1",
                platform="douyin",
                platform_label="抖音",
                idempotency_key="key-receipt-rebind-1",
                semantic_fingerprint="fingerprint-receipt-rebind-1",
                adapter="browser_agent",
                status="needs_human",
                run_status="needs_human",
                request_payload={
                    "publication_content_signature": {
                        "version": 1,
                        "value": "sig-receipt-rebind-1",
                        "fields": {},
                    }
                },
            )
            session.add(attempt)
            await session.flush()

            receipt_extras = {
                "receipt_like": True,
                "post_publish_surface": "douyin_content_manage_receipt",
                "receipt_target_bound": True,
                "receipt_binding_source": "douyin_manage_card",
                "douyin_manage_card": {
                    "matched": True,
                    "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                },
            }
            payload = {
                "task": {
                    "task_id": "standalone-receipt-rebind-1",
                    "attempt_id": "attempt-receipt-rebind-1",
                    "content_id": "job-receipt-rebind-1",
                    "platform": "douyin",
                    "status": "verified",
                    "result": {
                        "publication_content_signature": {
                            "version": 1,
                            "value": "sig-receipt-rebind-1",
                            "fields": {},
                        },
                        "material_integrity": {
                            "platform": "douyin",
                            "verified": True,
                            "failures": [],
                            "platform_extras": receipt_extras,
                        },
                        "publication_audit": {
                            "verified": True,
                            "required_unverified": [],
                            "required_reupload": [],
                            "platform_extras": receipt_extras,
                        },
                        "final_publish": {
                            "receipt_like": True,
                            "post_click_integrity": {
                                "platform_extras": receipt_extras,
                            },
                        },
                    },
                }
            }

            result = await publication.reconcile_publication_attempt_from_browser_agent_payload(
                session,
                payload,
            )
            await session.refresh(attempt)
    finally:
        await engine.dispose()

    assert result["matched_by"] == "attempt_id"
    assert result["attempt_id"] == "attempt-receipt-rebind-1"
    assert result["status"] == "published"
    assert result["provider_task_id"] == "standalone-receipt-rebind-1"
    assert str(result["external_receipt_id"] or "").startswith("receipt-binding:")
    assert attempt.status == "published"
    assert attempt.provider_task_id == "standalone-receipt-rebind-1"
    assert str(attempt.external_receipt_id or "").startswith("receipt-binding:")


@pytest.mark.asyncio
async def test_reconcile_publication_attempt_from_browser_agent_payload_falls_back_to_content_signature():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            attempt = PublicationAttempt(
                id="attempt-receipt-rebind-2",
                job_id=uuid.uuid4(),
                content_id="job-receipt-rebind-2",
                platform="douyin",
                platform_label="抖音",
                idempotency_key="key-receipt-rebind-2",
                semantic_fingerprint="fingerprint-receipt-rebind-2",
                adapter="browser_agent",
                status="needs_human",
                run_status="needs_human",
                request_payload={
                    "publication_content_signature": {
                        "version": 1,
                        "value": "sig-receipt-rebind-2",
                        "fields": {},
                    }
                },
            )
            session.add(attempt)
            await session.flush()

            receipt_extras = {
                "receipt_like": True,
                "post_publish_surface": "douyin_content_manage_receipt",
                "receipt_target_bound": True,
                "receipt_binding_source": "douyin_manage_card",
                "douyin_manage_card": {
                    "matched": True,
                    "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                },
            }
            payload = {
                "task": {
                    "task_id": "standalone-receipt-rebind-2",
                    "content_id": "job-receipt-rebind-2",
                    "platform": "douyin",
                    "status": "verified",
                    "result": {
                        "publication_content_signature": {
                            "version": 1,
                            "value": "sig-receipt-rebind-2",
                            "fields": {},
                        },
                        "material_integrity": {
                            "platform": "douyin",
                            "verified": True,
                            "failures": [],
                            "platform_extras": receipt_extras,
                        },
                        "publication_audit": {
                            "verified": True,
                            "required_unverified": [],
                            "required_reupload": [],
                            "platform_extras": receipt_extras,
                        },
                        "final_publish": {
                            "receipt_like": True,
                            "post_click_integrity": {
                                "platform_extras": receipt_extras,
                            },
                        },
                    },
                }
            }

            result = await publication.reconcile_publication_attempt_from_browser_agent_payload(
                session,
                payload,
            )
            await session.refresh(attempt)
    finally:
        await engine.dispose()

    assert result["matched_by"] == "content_signature"
    assert result["attempt_id"] == "attempt-receipt-rebind-2"
    assert result["status"] == "published"
    assert result["provider_task_id"] == "standalone-receipt-rebind-2"
    assert str(attempt.external_receipt_id or "").startswith("receipt-binding:")


@pytest.mark.asyncio
async def test_intelligent_copy_reconcile_publication_task_payload_route_persists_bound_receipt():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            attempt = PublicationAttempt(
                id="attempt-receipt-rebind-route-1",
                job_id=uuid.uuid4(),
                content_id="job-receipt-rebind-route-1",
                platform="douyin",
                platform_label="抖音",
                idempotency_key="key-receipt-rebind-route-1",
                semantic_fingerprint="fingerprint-receipt-rebind-route-1",
                adapter="browser_agent",
                status="needs_human",
                run_status="needs_human",
                request_payload={
                    "publication_content_signature": {
                        "version": 1,
                        "value": "sig-receipt-rebind-route-1",
                        "fields": {},
                    }
                },
            )
            session.add(attempt)
            await session.flush()

            receipt_extras = {
                "receipt_like": True,
                "post_publish_surface": "douyin_content_manage_receipt",
                "receipt_target_bound": True,
                "receipt_binding_source": "douyin_manage_card",
                "douyin_manage_card": {
                    "matched": True,
                    "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                },
            }
            payload = {
                "task": {
                    "task_id": "standalone-receipt-rebind-route-1",
                    "attempt_id": "attempt-receipt-rebind-route-1",
                    "content_id": "job-receipt-rebind-route-1",
                    "platform": "douyin",
                    "status": "verified",
                    "result": {
                        "publication_content_signature": {
                            "version": 1,
                            "value": "sig-receipt-rebind-route-1",
                            "fields": {},
                        },
                        "material_integrity": {
                            "platform": "douyin",
                            "verified": True,
                            "failures": [],
                            "platform_extras": receipt_extras,
                        },
                        "publication_audit": {
                            "verified": True,
                            "required_unverified": [],
                            "required_reupload": [],
                            "platform_extras": receipt_extras,
                        },
                        "final_publish": {
                            "receipt_like": True,
                            "post_click_integrity": {
                                "platform_extras": receipt_extras,
                            },
                        },
                    },
                }
            }

            result = await reconcile_publication_task_payload(payload, session=session)
            await session.refresh(attempt)
    finally:
        await engine.dispose()

    assert result["matched_by"] == "attempt_id"
    assert result["status"] == "published"
    assert str(result["external_receipt_id"] or "").startswith("receipt-binding:")
    assert attempt.status == "published"
    assert str(attempt.external_receipt_id or "").startswith("receipt-binding:")


@pytest.mark.asyncio
async def test_reconcile_publication_attempt_from_browser_agent_payload_preserves_bound_receipt_id_when_task_needs_human(monkeypatch):
    async def _no_diagnosis(*args, **kwargs):
        return None

    monkeypatch.setattr(publication, "_analyze_publication_failure_with_llm", _no_diagnosis)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            attempt = PublicationAttempt(
                id="attempt-receipt-rebind-needs-human-1",
                job_id=uuid.uuid4(),
                content_id="job-receipt-rebind-needs-human-1",
                platform="douyin",
                platform_label="抖音",
                idempotency_key="key-receipt-rebind-needs-human-1",
                semantic_fingerprint="fingerprint-receipt-rebind-needs-human-1",
                adapter="browser_agent",
                status="needs_human",
                run_status="needs_human",
                request_payload={
                    "publication_content_signature": {
                        "version": 1,
                        "value": "sig-receipt-rebind-needs-human-1",
                        "fields": {},
                    }
                },
            )
            session.add(attempt)
            await session.flush()

            receipt_extras = {
                "receipt_like": True,
                "post_publish_surface": "douyin_content_manage_receipt",
                "receipt_target_bound": True,
                "receipt_binding_source": "douyin_manage_card",
                "douyin_manage_card": {
                    "matched": True,
                    "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                },
            }
            payload = {
                "task": {
                    "task_id": "standalone-receipt-rebind-needs-human-1",
                    "attempt_id": "attempt-receipt-rebind-needs-human-1",
                    "content_id": "job-receipt-rebind-needs-human-1",
                    "platform": "douyin",
                    "status": "needs_human",
                    "result": {
                        "verification_reason": "receipt_bound",
                        "publication_content_signature": {
                            "version": 1,
                            "value": "sig-receipt-rebind-needs-human-1",
                            "fields": {},
                        },
                        "material_integrity": {
                            "platform": "douyin",
                            "verified": False,
                            "failures": [],
                            "verification_reason": "receipt_bound",
                            "platform_extras": receipt_extras,
                        },
                        "publication_audit": {
                            "verified": False,
                            "required_unverified": ["cover"],
                            "required_reupload": [],
                            "platform_extras": receipt_extras,
                        },
                        "final_publish": {
                            "receipt_like": True,
                            "post_click_integrity": {
                                "platform_extras": receipt_extras,
                            },
                        },
                    },
                    "error": {
                        "code": "publication_audit_unverified",
                        "message": "cover 未通过",
                    },
                }
            }

            result = await publication.reconcile_publication_attempt_from_browser_agent_payload(
                session,
                payload,
            )
            await session.refresh(attempt)
    finally:
        await engine.dispose()

    assert result["matched_by"] == "attempt_id"
    assert result["status"] == "needs_human"
    assert result["provider_task_id"] == "standalone-receipt-rebind-needs-human-1"
    assert str(result["external_receipt_id"] or "").startswith("receipt-binding:")
    assert attempt.status == "needs_human"
    assert attempt.provider_task_id == "standalone-receipt-rebind-needs-human-1"
    assert str(attempt.external_receipt_id or "").startswith("receipt-binding:")


@pytest.mark.asyncio
async def test_apply_browser_agent_task_state_treats_verified_stop_before_final_publish_as_draft_created(monkeypatch):
    async def _mock_recovery_analysis(*args, **kwargs):
        return None

    monkeypatch.setattr(publication, "_analyze_publication_failure_with_llm", _mock_recovery_analysis)
    attempt = SimpleNamespace(
        id="attempt-youtube-stop-before-1",
        adapter="browser_agent",
        platform="youtube",
        provider_status=None,
        provider_task_id="task-youtube-stop-before-1",
        provider_execution_id="run-youtube-stop-before-1",
        response_payload=None,
        status="processing",
        run_status="processing",
        published_at=None,
        scheduled_at=None,
        external_post_id=None,
        external_receipt_id=None,
        external_url=None,
        retry_count=0,
        max_retries=3,
        next_retry_at=None,
        error_code=None,
        error_message=None,
        operator_summary=None,
        request_payload={
            "publication_plan_signature": {
                "version": 1,
                "value": "sig-youtube-stop-before-1",
                "fields": {"title": "MAXACE美杜莎4 顶配 vs 次顶配 开箱对比上手"},
            }
        },
    )
    run = SimpleNamespace(
        status="processing",
        phase="reconcile",
        heartbeat_at=None,
        provider_task_id="task-youtube-stop-before-1",
        provider_execution_id="run-youtube-stop-before-1",
        provider_status=None,
        result_json=None,
        error_message=None,
        completed_at=None,
    )
    task = {
        "task_id": "task-youtube-stop-before-1",
        "status": "verified",
        "result": {
            "material_integrity": {
                "platform": "youtube",
                "verified": False,
                "failures": ["tags"],
                "fields": {
                    "title": {"actual": "MAXACE美杜莎4 顶配 vs 次顶配 开箱对比上手", "verified": True},
                    "body": {"actual": "正文", "verified": True},
                    "tags": {"actual": ["MAXACE美杜莎4"], "verified": False},
                    "upload_ready": {"actual": "ready", "verified": True},
                },
            },
            "publication_audit": {
                "verified": True,
                "required_unverified": [],
                "required_reupload": [],
                "notes": "content_plan_optional_missing:tags:MAXACE美杜莎4,EDC折刀开箱",
            },
            "final_publish": {
                "prepare_only_current_page": True,
                "stop_before_final_publish": True,
            },
        },
    }

    await publication._apply_browser_agent_task_state(attempt, run, task, response_payload={"task": task})

    assert attempt.status == "draft_created"
    assert attempt.run_status == "draft_created"
    assert attempt.error_code is None
    assert attempt.error_message is None
    assert attempt.operator_summary == "已完成发布前验证，并安全停在最终发布前。"
    assert run.status == "draft_created"
    assert run.completed_at is not None


@pytest.mark.asyncio
async def test_apply_browser_agent_task_state_keeps_unbound_receipt_verification_as_needs_human(monkeypatch):
    async def _mock_recovery_analysis(*args, **kwargs):
        return None

    monkeypatch.setattr(publication, "_analyze_publication_failure_with_llm", _mock_recovery_analysis)
    attempt = SimpleNamespace(
        id="attempt-xhs-unbound-receipt-1",
        adapter="browser_agent",
        platform="xiaohongshu",
        provider_status=None,
        provider_task_id="task-xhs-unbound-1",
        provider_execution_id="run-xhs-unbound-1",
        response_payload=None,
        status="processing",
        run_status="processing",
        published_at=None,
        scheduled_at=None,
        external_post_id=None,
        external_receipt_id=None,
        external_url=None,
        retry_count=0,
        max_retries=3,
        next_retry_at=None,
        error_code=None,
        error_message=None,
        operator_summary=None,
        request_payload={
            "publication_plan_signature": {
                "version": 1,
                "value": "sig-xhs-unbound-1",
                "fields": {"title": "锆合金版本的音叉推牌，质感绝了"},
            }
        },
    )
    run = SimpleNamespace(
        status="processing",
        phase="reconcile",
        heartbeat_at=None,
        provider_task_id="task-xhs-unbound-1",
        provider_execution_id="run-xhs-unbound-1",
        provider_status=None,
        result_json=None,
        error_message=None,
        completed_at=None,
    )
    task = {
        "task_id": "task-xhs-unbound-1",
        "status": "needs_human",
        "result": {
            "material_integrity": {
                "platform": "xiaohongshu",
                "verified": False,
                "failures": ["receipt"],
                "platform_extras": {
                    "receipt_like": True,
                    "post_publish_surface": "xiaohongshu_note_manager_receipt",
                    "receipt_target_bound": False,
                    "receipt_binding_source": "xiaohongshu_note_manager_unbound",
                },
            },
            "publication_audit": {
                "verified": False,
                "required_unverified": ["receipt"],
                "required_reupload": [],
                "platform_extras": {
                    "receipt_like": True,
                    "post_publish_surface": "xiaohongshu_note_manager_receipt",
                    "receipt_target_bound": False,
                    "receipt_binding_source": "xiaohongshu_note_manager_unbound",
                },
            },
        },
        "error": {
            "code": "publication_audit_unverified",
            "message": "receipt target missing",
        },
    }

    await publication._apply_browser_agent_task_state(attempt, run, task, response_payload={"task": task})

    assert attempt.status == "needs_human"
    assert attempt.error_code == "publication_audit_unverified"
    assert run.status == "needs_human"


@pytest.mark.asyncio
async def test_apply_browser_agent_task_state_auto_retries_when_llm_recommends_retry(monkeypatch):
    attempt = SimpleNamespace(
        id="attempt-auto-retry",
        provider_status=None,
        provider_task_id="task-old",
        provider_execution_id="exec-old",
        response_payload=None,
        status="processing",
        run_status="processing",
        published_at=None,
        scheduled_at=None,
        external_post_id=None,
        external_receipt_id=None,
        external_url=None,
        retry_count=0,
        max_retries=3,
        next_retry_at=None,
        error_code=None,
        error_message=None,
        operator_summary=None,
    )

    async def _mock_recovery_analysis(*args, **kwargs):
        return {
            "severity": "high",
            "action": "retry",
            "retryable": True,
            "next_steps": ["重新提交任务"],
            "confidence": 0.93,
            "evidence": ["network_error"],
            "rationale": "临时网络抖动，可重试。",
        }

    monkeypatch.setattr(publication, "_analyze_publication_failure_with_llm", _mock_recovery_analysis)
    run = SimpleNamespace(
        status="failed",
        phase="reconcile",
        heartbeat_at=None,
        provider_task_id="task-old",
        provider_execution_id="exec-old",
        provider_status="network_error",
        result_json=None,
        error_message=None,
        completed_at=None,
    )
    task = {
        "task_id": "task-old",
        "status": "network_error",
        "error": {
            "code": "network_error",
            "message": "临时网络波动",
        },
    }

    await publication._apply_browser_agent_task_state(attempt, run, task, response_payload={"task": task})

    assert attempt.status == "queued"
    assert attempt.run_status == "retry_scheduled"
    assert attempt.retry_count == 1
    assert attempt.next_retry_at is not None
    assert attempt.provider_task_id is None
    assert attempt.error_code == "network_error"
    assert "LLM 建议自动恢复" in str(attempt.operator_summary)
    assert run.status == "retry_scheduled"
    assert run.phase == "submit"
    assert run.provider_task_id is None


def test_apply_publication_auto_recovery_adapts_repeat_failure_with_clear_draft_and_refresh():
    attempt = SimpleNamespace(
        id="attempt-repeat-adaptive",
        platform="douyin",
        status="failed",
        run_status="failed",
        provider_status="publication_audit_unverified",
        provider_task_id="task-old",
        provider_execution_id="exec-old",
        response_payload=None,
        published_at=None,
        scheduled_at=None,
        external_post_id=None,
        external_receipt_id=None,
        external_url=None,
        error_code=None,
        error_message=None,
        operator_summary=None,
        retry_count=0,
        next_retry_at=None,
        max_retries=3,
        request_payload={
            "publication_plan_signature": {
                "value": "same-signature",
            },
            "platform_specific_overrides": {
                "source_flag": "baseline",
            },
            "publication_recovery_state": {
                "schema_version": publication.PUBLICATION_RECOVERY_STATE_SCHEMA_VERSION,
                "plan_signature": "same-signature",
                "failure_history": {
                    "douyin:publication_audit_unverified": {
                        "attempt_count": 1,
                        "first_seen": "2026-05-01T01:00:00+00:00",
                        "last_seen": "2026-05-01T01:00:00+00:00",
                        "platform": "douyin",
                        "code": "publication_audit_unverified",
                        "failure_signal_count": 1,
                    }
                },
            },
        },
    )
    run = SimpleNamespace(
        status="failed",
        phase="reconcile",
        heartbeat_at=None,
        provider_task_id="task-old",
        provider_execution_id="exec-old",
        provider_status="publication_audit_unverified",
        result_json=None,
        error_message=None,
        completed_at=None,
    )
    context = {
        "platform": "douyin",
        "error": {"code": "publication_audit_unverified", "message": "内容核验未通过"},
        "audit": {"required_reupload": ["upload_ready"], "required_unverified": ["upload_ready"]},
        "request_recovery_state": {
            "failure_history": {
                "douyin:publication_audit_unverified": {
                    "attempt_count": 1,
                    "failure_signal_count": 1,
                }
            }
        },
    }
    adaptive_overrides = publication._adaptive_recovery_overrides_for_context(
        context=context,
        base_plan={
            "recovery_overrides": {
                "clear_draft_context": False,
                "force_publish_page_refresh": False,
            },
        },
        error_code="publication_audit_unverified",
        diagnosis_action="retry",
    )
    assert adaptive_overrides["clear_draft_context"] is True
    assert adaptive_overrides["force_publish_page_refresh"] is True
    diagnosis = {
        "severity": "medium",
        "action": "retry",
        "retryable": True,
        "next_steps": ["清理草稿并重试"],
        "confidence": 0.91,
        "evidence": ["publication_audit_unverified"],
        "rationale": "内容核验未通过。",
        "recovery_plan": {"recovery_overrides": adaptive_overrides},
        "resolution_source": "rule",
    }

    publication._apply_publication_auto_recovery(
        attempt,
        run,
        now=publication._utc_now(),
        diagnosis=diagnosis,
        mapped_status="failed",
        context=context,
    )

    assert attempt.status == "queued"
    assert attempt.retry_count == 1
    assert attempt.request_payload.get("platform_specific_overrides", {}).get("clear_draft_context") is True
    assert attempt.request_payload.get("platform_specific_overrides", {}).get("force_publish_page_refresh") is True
    assert attempt.request_payload.get("platform_specific_overrides", {}).get("source_flag") == "baseline"
    recovery_state = attempt.request_payload.get("publication_recovery_state") or {}
    assert int(recovery_state.get("failure_history", {}).get("douyin:publication_audit_unverified", {}).get("attempt_count")) == 2
    assert int(recovery_state.get("latest_retry_count") or 0) == 1


def test_build_platform_recovery_overrides_does_not_carry_clear_draft_after_draft_clear_failed():
    attempt = PublicationAttempt(
        id="attempt-draft-clear-failed",
        job_id=uuid.uuid4(),
        content_id="job-draft-clear-failed",
        platform="xiaohongshu",
        platform_label="小红书",
        idempotency_key="key-draft-clear-failed",
        semantic_fingerprint="fingerprint-draft-clear-failed",
        adapter="browser_agent",
        status="needs_human",
        error_code="draft_clear_failed",
        request_payload={
            "publication_plan_signature": {
                "value": "same-signature",
            },
            "platform_specific_overrides": {
                "clear_draft_context": True,
                "force_publish_page_refresh": True,
                "recovery_mode": "draft_reset",
            },
        },
    )

    overrides, _ = publication._build_platform_recovery_overrides(
        attempt=attempt,
        request_plan_signature="same-signature",
    )

    assert overrides == {}


def test_derive_recovery_diagnosis_treats_draft_clear_failed_as_manual_check():
    diagnosis = publication._derive_recovery_diagnosis_from_context(
        {
            "platform": "xiaohongshu",
            "error": {
                "code": "draft_clear_failed",
                "message": "草稿清理失败",
            },
            "recovery": {
                "code": "draft_clear_failed",
            },
            "blockers": [],
        }
    )

    assert diagnosis is not None
    assert diagnosis["action"] == "manual_check"
    assert diagnosis["retryable"] is False
    assert diagnosis["recovery_plan"]["recovery_overrides"]["clear_draft_context"] is False


def test_extract_publication_failure_context_reads_pre_publish_repair_and_repair_evidence_from_result():
    attempt = SimpleNamespace(
        id="attempt-repair-context",
        platform="douyin",
        request_payload={},
        status="needs_human",
    )
    task = {
        "status": "needs_human",
        "result": {
            "actions": [{"kind": "douyin_original_declaration", "clicked": True}],
            "publication_audit": {
                "verified": False,
                "required_unverified": ["upload_ready"],
                "required_reupload": ["upload_ready"],
                "notes": "required_unverified:upload_ready",
            },
            "publication_field_snapshot": {
                "repair_evidence": {
                    "declaration_repaired": True,
                    "schedule_repaired": True,
                }
            },
            "final_publish": {
                "repair_only_current_page": True,
                "pre_publish_repair": {
                    "attempted": True,
                    "before_required_unverified": ["declaration", "schedule", "upload_ready"],
                    "after_required_unverified": ["upload_ready"],
                },
            },
        },
        "error": {
            "code": "publication_audit_unverified",
            "message": "内容核验未通过",
        },
    }

    context = publication._extract_publication_failure_context(
        attempt,
        raw_status="needs_human",
        task=task,
        response_payload={},
    )

    assert context["pre_publish_repair"]["attempted"] is True
    assert context["repair_evidence"]["declaration_repaired"] is True
    assert len(context["action_history"]) == 1


def test_extract_publication_failure_context_reads_flattened_browser_agent_recovery_signal():
    attempt = SimpleNamespace(
        id="attempt-flat-recovery-context",
        platform="youtube",
        request_payload={},
        status="processing",
    )
    task = {
        "status": "processing",
        "result": {
            "code": "youtube_pre_publish_upload_pending",
            "reason": "媒体上传已开始，继续保留现场等待平台进入可编辑上传态。",
            "recovery_overrides": {
                "recovery_mode": "prepublish_resume",
                "clear_draft_context": False,
                "force_publish_page_refresh": True,
                "prepare_only_current_page": True,
                "verify_media_upload": True,
                "wait_for_publish_confirmation": True,
            },
            "blockers": [
                {
                    "code": "youtube_pre_publish_upload_pending",
                    "message": "预发布等待上传完成：upload_in_progress",
                    "details": "verification_reason=upload_in_progress",
                }
            ],
            "route": {
                "url": "https://studio.youtube.com/channel/test/videos/upload?d=ud",
                "title": "频道内容 - YouTube Studio",
            },
            "material_integrity": {
                "platform": "youtube",
                "verified": False,
                "failures": [],
            },
        },
        "error": None,
    }

    context = publication._extract_publication_failure_context(
        attempt,
        raw_status="processing",
        task=task,
        response_payload={},
    )

    assert context["recovery"]["code"] == "youtube_pre_publish_upload_pending"
    assert context["recovery"]["recovery_overrides"]["recovery_mode"] == "prepublish_resume"
    assert context["recovery"]["recovery_overrides"]["prepare_only_current_page"] is True
    assert context["recovery"]["recovery_overrides"]["verify_media_upload"] is True
    assert context["recovery"]["recovery_overrides"]["wait_for_publish_confirmation"] is True


def test_extract_publication_failure_context_reads_visual_evidence_from_result():
    attempt = SimpleNamespace(
        id="attempt-visual-evidence-context",
        platform="douyin",
        request_payload={},
        status="needs_human",
    )
    task = {
        "status": "needs_human",
        "result": {
            "visual_evidence": {
                "artifact_path": "E:/WorkSpace/RoughCut/artifacts/publication-visual-evidence/douyin-pre-publish.png",
                "capture_type": "screenshot",
                "phase": "pre_publish_page_snapshot",
            },
            "publication_audit": {
                "verified": False,
                "required_unverified": ["declaration"],
            },
        },
        "error": {
            "code": "publication_audit_unverified",
            "message": "content verification failed",
        },
    }

    context = publication._extract_publication_failure_context(
        attempt,
        raw_status="needs_human",
        task=task,
        response_payload={},
    )

    assert context["visual_evidence"]["artifact_path"].endswith("douyin-pre-publish.png")
    assert context["visual_evidence"]["capture_type"] == "screenshot"
    assert context["visual_evidence"]["phase"] == "pre_publish_page_snapshot"


def test_extract_publication_failure_context_reads_unbound_receipt_binding_from_result():
    attempt = SimpleNamespace(
        id="attempt-receipt-context",
        platform="douyin",
        request_payload={},
        status="needs_human",
    )
    task = {
        "status": "needs_human",
        "result": {
            "material_integrity": {
                "platform": "douyin",
                "verified": False,
                "failures": ["receipt"],
                "platform_extras": {
                    "receipt_like": True,
                    "post_publish_surface": "douyin_content_manage_receipt",
                    "receipt_target_bound": False,
                    "receipt_binding_source": "unbound_manage_receipt",
                },
            },
        },
        "error": {
            "code": "publication_audit_unverified",
            "message": "内容核验未通过",
        },
    }

    context = publication._extract_publication_failure_context(
        attempt,
        raw_status="needs_human",
        task=task,
        response_payload={},
    )

    assert context["receipt_binding"]["receipt_like"] is True
    assert context["receipt_binding"]["receipt_target_bound"] is False
    assert context["receipt_binding"]["receipt_binding_source"] == "unbound_manage_receipt"


def test_extract_publication_failure_context_reads_bound_receipt_binding_from_result():
    attempt = SimpleNamespace(
        id="attempt-bound-receipt-context",
        platform="douyin",
        request_payload={},
        status="published",
    )
    task = {
        "status": "published",
        "result": {
            "material_integrity": {
                "platform": "douyin",
                "verified": True,
                "failures": [],
                "platform_extras": {
                    "douyin_manage_card": {
                        "matched": True,
                        "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                    },
                    "receipt_like": True,
                    "post_publish_surface": "douyin_content_manage_receipt",
                    "receipt_target_bound": True,
                    "receipt_binding_source": "douyin_manage_card",
                },
            },
        },
    }

    context = publication._extract_publication_failure_context(
        attempt,
        raw_status="published",
        task=task,
        response_payload={},
    )

    assert context["receipt_binding"]["receipt_like"] is True
    assert context["receipt_binding"]["receipt_target_bound"] is True
    assert context["receipt_binding"]["receipt_binding_source"] == "douyin_manage_card"
    assert context["receipt_binding"]["receipt_binding_payload"]["douyin_manage_card"]["matched"] is True


def test_extract_publication_failure_context_rejects_page_shell_douyin_receipt_binding():
    attempt = SimpleNamespace(
        id="attempt-invalid-douyin-receipt-context",
        platform="douyin",
        request_payload={},
        status="published",
    )
    task = {
        "status": "published",
        "result": {
            "publication_audit": {
                "verified": True,
                "platform_extras": {
                    "douyin_manage_card": {
                        "matched": True,
                        "title": "MAXACE美杜莎4双版本开箱，顶配次顶配哪个更值",
                        "text": "高清发布 首页 活动管理 内容管理 作品管理 合集管理 共创中心 10:08 MAXACE美杜莎4双版本开箱，顶配次顶配哪个更值 等了好久的MAXACE美杜莎4终于到货。#EDC折刀 #MAXACE美杜莎4 编辑作品 设置权限 作品置顶 删除作品 2026年06月02日 11:21 已发布 10:08 MAXACE美杜莎4两版本到货了丨直接给你对比 两版本同时开。#美杜莎4 编辑作品 设置权限 作品置顶 删除作品 2026年06月02日 06:28 已发布",
                    },
                    "receipt_like": True,
                    "post_publish_surface": "douyin_content_manage_receipt",
                    "receipt_target_bound": True,
                    "receipt_binding_source": "douyin_manage_card",
                },
            },
        },
    }

    context = publication._extract_publication_failure_context(
        attempt,
        raw_status="published",
        task=task,
        response_payload={},
    )

    assert context["receipt_binding"]["receipt_like"] is True
    assert context["receipt_binding"]["receipt_target_bound"] is False
    assert context["receipt_binding"]["receipt_binding_source"] == "unbound_manage_receipt"
    assert context["receipt_binding"]["receipt_binding_payload"]["douyin_manage_card"]["matched"] is True


def test_extract_publication_failure_context_reads_bound_xiaohongshu_receipt_binding_from_result():
    attempt = SimpleNamespace(
        id="attempt-bound-xiaohongshu-receipt-context",
        platform="xiaohongshu",
        request_payload={},
        status="published",
    )
    task = {
        "status": "published",
        "result": {
            "material_integrity": {
                "platform": "xiaohongshu",
                "verified": True,
                "failures": [],
                "platform_extras": {
                    "receipt_like": True,
                    "post_publish_surface": "xiaohongshu_publish_success_receipt",
                    "receipt_target_bound": True,
                    "receipt_binding_source": "xiaohongshu_publish_success",
                },
            },
        },
    }

    context = publication._extract_publication_failure_context(
        attempt,
        raw_status="published",
        task=task,
        response_payload={},
    )

    assert context["receipt_binding"]["receipt_like"] is True
    assert context["receipt_binding"]["receipt_target_bound"] is True
    assert context["receipt_binding"]["receipt_binding_source"] == "xiaohongshu_publish_success"
    assert context["receipt_binding"]["post_publish_surface"] == "xiaohongshu_publish_success_receipt"


def test_extract_publication_failure_context_reads_bound_xiaohongshu_note_manager_receipt_binding_from_result():
    attempt = SimpleNamespace(
        id="attempt-bound-xiaohongshu-note-manager-receipt-context",
        platform="xiaohongshu",
        request_payload={},
        status="published",
    )
    task = {
        "status": "published",
        "result": {
            "material_integrity": {
                "platform": "xiaohongshu",
                "verified": True,
                "failures": [],
                "platform_extras": {
                    "receipt_like": True,
                    "post_publish_surface": "xiaohongshu_note_manager_receipt",
                    "receipt_target_bound": True,
                    "receipt_binding_source": "xiaohongshu_note_manager_card",
                },
            },
        },
    }

    context = publication._extract_publication_failure_context(
        attempt,
        raw_status="published",
        task=task,
        response_payload={},
    )

    assert context["receipt_binding"]["receipt_like"] is True
    assert context["receipt_binding"]["receipt_target_bound"] is True
    assert context["receipt_binding"]["receipt_binding_source"] == "xiaohongshu_note_manager_card"
    assert context["receipt_binding"]["post_publish_surface"] == "xiaohongshu_note_manager_receipt"


def test_extract_publication_failure_context_reads_bound_toutiao_manage_receipt_binding_from_result():
    attempt = SimpleNamespace(
        id="attempt-bound-toutiao-manage-receipt-context",
        platform="toutiao",
        request_payload={},
        status="published",
    )
    task = {
        "status": "published",
        "result": {
            "material_integrity": {
                "platform": "toutiao",
                "verified": True,
                "failures": [],
                "platform_extras": {
                    "receipt_like": True,
                    "post_publish_surface": "toutiao_content_manage_receipt",
                    "receipt_target_bound": True,
                    "receipt_binding_source": "toutiao_manage_card",
                },
            },
        },
    }

    context = publication._extract_publication_failure_context(
        attempt,
        raw_status="published",
        task=task,
        response_payload={},
    )

    assert context["receipt_binding"]["receipt_like"] is True
    assert context["receipt_binding"]["receipt_target_bound"] is True
    assert context["receipt_binding"]["receipt_binding_source"] == "toutiao_manage_card"
    assert context["receipt_binding"]["post_publish_surface"] == "toutiao_content_manage_receipt"


def test_derive_recovery_diagnosis_preserves_repaired_publish_page_when_only_upload_ready_remains():
    diagnosis = publication._derive_recovery_diagnosis_from_context(
        {
            "platform": "douyin",
            "error": {
                "code": "publication_audit_unverified",
                "message": "内容核验未通过",
            },
            "recovery": {
                "code": "douyin_verification_only_material_integrity_failed",
            },
            "pre_publish_repair": {
                "attempted": True,
                "before_required_unverified": ["declaration", "schedule", "upload_ready"],
                "after_required_unverified": ["upload_ready"],
            },
            "repair_evidence": {
                "declaration_repaired": True,
                "schedule_repaired": True,
            },
            "audit": {
                "required_unverified": ["upload_ready"],
                "required_reupload": ["upload_ready"],
            },
            "blockers": [],
        }
    )

    assert diagnosis is not None
    assert diagnosis["action"] == "retry"
    assert diagnosis["retryable"] is True
    assert diagnosis["recovery_plan"]["recovery_overrides"]["clear_draft_context"] is False
    assert diagnosis["recovery_plan"]["recovery_overrides"]["force_publish_page_refresh"] is True


def test_derive_recovery_diagnosis_does_not_treat_bound_receipt_as_unbound_without_other_recovery_signal():
    diagnosis = publication._derive_recovery_diagnosis_from_context(
        {
            "platform": "douyin",
            "error": {
                "code": "",
                "message": "",
            },
            "receipt_binding": {
                "receipt_like": True,
                "receipt_target_bound": True,
                "receipt_binding_source": "douyin_manage_card",
                "post_publish_surface": "douyin_content_manage_receipt",
            },
            "audit": {
                "required_unverified": [],
                "required_reupload": [],
            },
            "blockers": [],
        }
    )

    assert diagnosis is None


def test_derive_recovery_diagnosis_does_not_treat_bound_xiaohongshu_receipt_as_unbound_without_other_recovery_signal():
    diagnosis = publication._derive_recovery_diagnosis_from_context(
        {
            "platform": "xiaohongshu",
            "error": {
                "code": "",
                "message": "",
            },
            "receipt_binding": {
                "receipt_like": True,
                "receipt_target_bound": True,
                "receipt_binding_source": "xiaohongshu_publish_success",
                "post_publish_surface": "xiaohongshu_publish_success_receipt",
            },
            "audit": {
                "required_unverified": [],
                "required_reupload": [],
            },
            "blockers": [],
        }
    )

    assert diagnosis is None


def test_derive_recovery_diagnosis_does_not_treat_bound_xiaohongshu_note_manager_receipt_as_unbound_without_other_recovery_signal():
    diagnosis = publication._derive_recovery_diagnosis_from_context(
        {
            "platform": "xiaohongshu",
            "error": {
                "code": "",
                "message": "",
            },
            "receipt_binding": {
                "receipt_like": True,
                "receipt_target_bound": True,
                "receipt_binding_source": "xiaohongshu_note_manager_card",
                "post_publish_surface": "xiaohongshu_note_manager_receipt",
            },
            "audit": {
                "required_unverified": [],
                "required_reupload": [],
            },
            "blockers": [],
        }
    )

    assert diagnosis is None


def test_derive_recovery_diagnosis_does_not_treat_bound_toutiao_manage_receipt_as_unbound_without_other_recovery_signal():
    diagnosis = publication._derive_recovery_diagnosis_from_context(
        {
            "platform": "toutiao",
            "error": {
                "code": "",
                "message": "",
            },
            "receipt_binding": {
                "receipt_like": True,
                "receipt_target_bound": True,
                "receipt_binding_source": "toutiao_manage_card",
                "post_publish_surface": "toutiao_content_manage_receipt",
            },
            "audit": {
                "required_unverified": [],
                "required_reupload": [],
            },
            "blockers": [],
        }
    )

    assert diagnosis is None


def test_extract_publication_failure_context_reads_bound_youtube_editor_receipt_binding_from_result():
    attempt = SimpleNamespace(
        id="attempt-youtube-bound-editor-receipt",
        platform="youtube",
        request_payload={},
        status="verified",
    )
    task = {
        "status": "verified",
        "result": {
            "material_integrity": {
                "platform_extras": {
                    "receipt_like": True,
                    "receipt_target_bound": True,
                    "receipt_binding_source": "youtube_studio_editor_link",
                    "post_publish_surface": "youtube_studio_editor_receipt",
                    "youtube_link": "https://youtu.be/T-44KNDKkSQ",
                }
            }
        },
    }
    context = publication._extract_publication_failure_context(
        attempt,
        raw_status="verified",
        task=task,
        response_payload={},
    )

    assert context["receipt_binding"]["receipt_like"] is True
    assert context["receipt_binding"]["receipt_target_bound"] is True
    assert context["receipt_binding"]["receipt_binding_source"] == "youtube_studio_editor_link"
    assert context["receipt_binding"]["post_publish_surface"] == "youtube_studio_editor_receipt"


def test_derive_recovery_diagnosis_does_not_treat_bound_youtube_editor_receipt_as_unbound_without_other_recovery_signal():
    diagnosis = publication._derive_recovery_diagnosis_from_context(
        {
            "platform": "youtube",
            "error": {
                "code": "",
                "message": "",
            },
            "receipt_binding": {
                "receipt_like": True,
                "receipt_target_bound": True,
                "receipt_binding_source": "youtube_studio_editor_link",
                "post_publish_surface": "youtube_studio_editor_receipt",
            },
            "audit": {
                "required_unverified": [],
                "required_reupload": [],
            },
            "blockers": [],
        }
    )

    assert diagnosis is None


def test_adaptive_recovery_overrides_do_not_promote_post_repair_upload_blocker_to_clear_draft():
    overrides = publication._adaptive_recovery_overrides_for_context(
        context={
            "platform": "douyin",
            "error": {"code": "publication_audit_unverified", "message": "内容核验未通过"},
            "audit": {"required_reupload": ["upload_ready"], "required_unverified": ["upload_ready"]},
            "pre_publish_repair": {
                "attempted": True,
                "before_required_unverified": ["declaration", "schedule", "upload_ready"],
                "after_required_unverified": ["upload_ready"],
            },
            "repair_evidence": {
                "declaration_repaired": True,
                "schedule_repaired": True,
            },
            "request_recovery_state": {
                "failure_history": {
                    "douyin:publication_audit_unverified": {
                        "attempt_count": 3,
                        "failure_signal_count": 1,
                    }
                }
            },
        },
        base_plan={
            "recovery_overrides": {
                "clear_draft_context": False,
                "force_publish_page_refresh": False,
            },
        },
        error_code="publication_audit_unverified",
        diagnosis_action="retry",
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True


def test_derive_recovery_diagnosis_preserves_pre_publish_upload_pending_context():
    diagnosis = publication._derive_recovery_diagnosis_from_context(
        {
            "platform": "douyin",
            "error": {
                "code": "douyin_pre_publish_upload_pending",
                "message": "预发布字段已通过，等待上传完成",
            },
            "recovery": {
                "code": "douyin_pre_publish_upload_pending",
            },
            "audit": {
                "required_unverified": ["upload_ready"],
                "required_reupload": ["upload_ready"],
            },
            "blockers": [],
        }
    )

    assert diagnosis is not None
    assert diagnosis["action"] == "retry"
    assert diagnosis["retryable"] is True
    assert diagnosis["recovery_plan"]["recovery_overrides"]["clear_draft_context"] is False
    assert diagnosis["recovery_plan"]["recovery_overrides"]["force_publish_page_refresh"] is True


def test_adaptive_recovery_overrides_keep_pre_publish_upload_pending_refresh_only():
    overrides = publication._adaptive_recovery_overrides_for_context(
        context={
            "platform": "douyin",
            "error": {"code": "douyin_pre_publish_upload_pending", "message": "等待上传完成"},
            "recovery": {"code": "douyin_pre_publish_upload_pending"},
            "audit": {"required_reupload": ["upload_ready"], "required_unverified": ["upload_ready"]},
            "request_recovery_state": {
                "failure_history": {
                    "douyin:douyin_pre_publish_upload_pending": {
                        "attempt_count": 4,
                        "failure_signal_count": 1,
                    }
                }
            },
        },
        base_plan={
            "recovery_overrides": {
                "clear_draft_context": True,
                "force_publish_page_refresh": False,
            },
        },
        error_code="douyin_pre_publish_upload_pending",
        diagnosis_action="retry",
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True


def test_derive_recovery_diagnosis_preserves_upload_not_applied_context():
    diagnosis = publication._derive_recovery_diagnosis_from_context(
        {
            "platform": "kuaishou",
            "error": {
                "code": "kuaishou_media_upload_failed",
                "message": "媒体上传未生效：upload_not_applied",
                "details": {"failure_reason": "upload_not_applied"},
            },
            "recovery": {
                "code": "kuaishou_media_upload_failed",
            },
            "audit": {
                "required_unverified": [],
                "required_reupload": [],
            },
            "blockers": [],
        }
    )

    assert diagnosis is not None
    assert diagnosis["action"] == "retry"
    assert diagnosis["retryable"] is True
    assert diagnosis["recovery_plan"]["recovery_overrides"]["clear_draft_context"] is False
    assert diagnosis["recovery_plan"]["recovery_overrides"]["force_publish_page_refresh"] is True


def test_adaptive_recovery_overrides_keep_upload_not_applied_refresh_only():
    overrides = publication._adaptive_recovery_overrides_for_context(
        context={
            "platform": "kuaishou",
            "error": {
                "code": "kuaishou_media_upload_failed",
                "message": "媒体上传未生效：upload_not_applied",
                "details": {"failure_reason": "upload_not_applied"},
            },
            "recovery": {"code": "kuaishou_media_upload_failed"},
            "request_recovery_state": {
                "failure_history": {
                    "kuaishou:kuaishou_media_upload_failed": {
                        "attempt_count": 4,
                        "failure_signal_count": 1,
                    }
                }
            },
        },
        base_plan={
            "recovery_overrides": {
                "clear_draft_context": True,
                "force_publish_page_refresh": False,
            },
        },
        error_code="kuaishou_media_upload_failed",
        diagnosis_action="retry",
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True


def test_derive_recovery_diagnosis_keeps_route_auth_required_out_of_draft_reset():
    diagnosis = publication._derive_recovery_diagnosis_from_context(
        {
            "platform": "wechat-channels",
            "error": {
                "code": "wechat-channels_route_auth_required",
                "message": "当前页面要求重新登录",
            },
            "recovery": {
                "code": "wechat-channels_route_auth_required",
                "recovery_overrides": {
                    "clear_draft_context": True,
                    "force_publish_page_refresh": True,
                },
            },
            "audit": {},
            "blockers": [],
        }
    )

    assert diagnosis is not None
    assert diagnosis["action"] == "manual_check"
    assert diagnosis["retryable"] is False
    assert diagnosis["recovery_plan"]["recovery_overrides"]["clear_draft_context"] is False
    assert diagnosis["recovery_plan"]["recovery_overrides"]["force_publish_page_refresh"] is False


def test_adaptive_recovery_overrides_keep_route_auth_required_without_clear_draft():
    overrides = publication._adaptive_recovery_overrides_for_context(
        context={
            "platform": "wechat-channels",
            "error": {"code": "wechat-channels_route_auth_required", "message": "登录页"},
            "recovery": {"code": "wechat-channels_route_auth_required"},
            "request_recovery_state": {
                "failure_history": {
                    "wechat-channels:wechat-channels_route_auth_required": {
                        "attempt_count": 4,
                        "failure_signal_count": 1,
                    }
                }
            },
        },
        base_plan={
            "recovery_overrides": {
                "clear_draft_context": True,
                "force_publish_page_refresh": True,
            },
        },
        error_code="wechat-channels_route_auth_required",
        diagnosis_action="manual_check",
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is False


def test_derive_recovery_diagnosis_describes_refresh_only_context_without_draft_reset():
    diagnosis = publication._derive_recovery_diagnosis_from_context(
        {
            "platform": "douyin",
            "error": {
                "code": "douyin_pre_publish_upload_pending",
                "message": "预发布字段已通过，等待上传完成",
            },
            "recovery": {
                "code": "douyin_pre_publish_upload_pending",
                "recovery_overrides": {
                    "clear_draft_context": False,
                    "force_publish_page_refresh": True,
                    "verify_media_upload": True,
                    "wait_for_publish_confirmation": True,
                },
            },
            "audit": {
                "required_unverified": ["upload_ready"],
                "required_reupload": ["upload_ready"],
            },
            "blockers": [],
        }
    )

    assert diagnosis is not None
    assert diagnosis["action"] == "retry"
    assert diagnosis["recovery_plan"]["recovery_overrides"]["clear_draft_context"] is False
    assert diagnosis["next_steps"][0] != "应用恢复上下文，清理草稿并刷新发布页后重试。"


def test_derive_recovery_diagnosis_preserves_unbound_receipt_context():
    diagnosis = publication._derive_recovery_diagnosis_from_context(
        {
            "platform": "douyin",
            "error": {
                "code": "publication_audit_unverified",
                "message": "发布后回执未绑定",
            },
            "recovery": {
                "code": "douyin_final_publish_unconfirmed",
            },
            "receipt_binding": {
                "receipt_like": True,
                "receipt_target_bound": False,
                "receipt_binding_source": "unbound_manage_receipt",
                "post_publish_surface": "douyin_content_manage_receipt",
            },
            "audit": {
                "required_unverified": ["receipt"],
                "required_reupload": [],
            },
            "blockers": [],
        }
    )

    assert diagnosis is not None
    assert diagnosis["action"] == "retry"
    assert diagnosis["retryable"] is True
    assert diagnosis["recovery_plan"]["recovery_overrides"]["clear_draft_context"] is False
    assert diagnosis["recovery_plan"]["recovery_overrides"]["force_publish_page_refresh"] is True


def test_derive_recovery_diagnosis_preserves_unbound_receipt_context_without_recovery_payload():
    diagnosis = publication._derive_recovery_diagnosis_from_context(
        {
            "platform": "douyin",
            "error": {
                "code": "douyin_verification_current_page_target_missing",
                "message": "当前页面不是本次内容对应的发布页/回执页",
            },
            "receipt_binding": {
                "receipt_like": True,
                "receipt_target_bound": False,
                "receipt_binding_source": "unbound_manage_receipt",
                "post_publish_surface": "douyin_content_manage_receipt",
            },
            "audit": {
                "required_unverified": ["receipt"],
                "required_reupload": [],
            },
            "blockers": [],
        }
    )

    assert diagnosis is not None
    assert diagnosis["action"] == "retry"
    assert diagnosis["retryable"] is True
    assert diagnosis["resolution_source"] == "rule"
    assert diagnosis["recovery_plan"]["recovery_overrides"]["clear_draft_context"] is False
    assert diagnosis["recovery_plan"]["recovery_overrides"]["force_publish_page_refresh"] is True


def test_adaptive_recovery_overrides_do_not_promote_unbound_receipt_to_clear_draft():
    overrides = publication._adaptive_recovery_overrides_for_context(
        context={
            "platform": "douyin",
            "error": {"code": "publication_audit_unverified", "message": "发布后回执未绑定"},
            "audit": {"required_reupload": [], "required_unverified": ["receipt"]},
            "receipt_binding": {
                "receipt_like": True,
                "receipt_target_bound": False,
                "receipt_binding_source": "unbound_manage_receipt",
                "post_publish_surface": "douyin_content_manage_receipt",
            },
            "request_recovery_state": {
                "failure_history": {
                    "douyin:publication_audit_unverified": {
                        "attempt_count": 4,
                        "failure_signal_count": 1,
                    }
                }
            },
        },
        base_plan={
            "recovery_overrides": {
                "clear_draft_context": True,
                "force_publish_page_refresh": False,
            },
        },
        error_code="publication_audit_unverified",
        diagnosis_action="retry",
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True


def test_build_platform_recovery_overrides_uses_safe_receipt_rebind_mode_for_unbound_receipt():
    attempt = SimpleNamespace(
        id="attempt-unbound-receipt-requeue",
        platform="douyin",
        status="needs_human",
        provider_status="needs_human",
        error_code="publication_audit_unverified",
        request_payload={
            "publication_plan_signature": {"value": "plan-1"},
            "platform_specific_overrides": {},
        },
        response_payload={
            "result": {
                "material_integrity": {
                    "platform": "douyin",
                    "verified": False,
                    "failures": ["receipt"],
                    "platform_extras": {
                        "receipt_like": True,
                        "post_publish_surface": "douyin_content_manage_receipt",
                        "receipt_target_bound": False,
                        "receipt_binding_source": "unbound_manage_receipt",
                    },
                },
                "publication_audit": {
                    "required_unverified": ["receipt"],
                    "required_reupload": [],
                },
            },
            "error": {
                "code": "publication_audit_unverified",
                "message": "receipt not bound",
            },
        },
    )

    overrides, _ = publication._build_platform_recovery_overrides(
        attempt=attempt,
        request_plan_signature="plan-1",
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["verification_only_current_page"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert overrides["recovery_mode"] == "receipt_rebind"


def test_build_platform_recovery_overrides_uses_safe_receipt_rebind_mode_for_pending_receipt():
    attempt = SimpleNamespace(
        id="attempt-pending-receipt-requeue",
        platform="toutiao",
        status="needs_human",
        provider_status="submitted",
        error_code="publication_public_url_missing",
        request_payload={
            "publication_plan_signature": {"value": "plan-1"},
            "platform_specific_overrides": {},
        },
        response_payload={
            "error": {
                "code": "publication_public_url_missing",
                "message": "public url missing while receipt is still pending",
            },
        },
    )

    overrides, _ = publication._build_platform_recovery_overrides(
        attempt=attempt,
        request_plan_signature="plan-1",
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["verification_only_current_page"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert overrides["recovery_mode"] == "receipt_rebind"


def test_merge_platform_specific_overrides_with_current_target_preserves_explicit_recovery_mode():
    merged = publication._merge_platform_specific_overrides_with_current_target(
        {
            "recovery_mode": "receipt_rebind",
            "verification_only_current_page": True,
            "clear_draft_context": False,
        },
        {
            "recovery_mode": "draft_reset",
            "clear_draft_context": True,
            "force_publish_page_refresh": True,
        },
    )

    assert merged["recovery_mode"] == "receipt_rebind"
    assert merged["verification_only_current_page"] is True
    assert merged["clear_draft_context"] is False
    assert merged["force_publish_page_refresh"] is True


def test_build_platform_recovery_overrides_strips_stale_receipt_rebind_overrides_without_receipt_signal():
    attempt = SimpleNamespace(
        id="attempt-stale-receipt-rebind-overrides",
        platform="xiaohongshu",
        status="needs_human",
        provider_status="needs_human",
        error_code="publication_audit_unverified",
        request_payload={
            "publication_plan_signature": {"value": "plan-1"},
            "platform_specific_overrides": {
                "recovery_mode": "receipt_rebind",
                "verification_only_current_page": True,
                "wait_for_publish_confirmation": True,
                "force_publish_page_refresh": True,
            },
        },
        response_payload={
            "result": {
                "material_integrity": {
                    "platform": "xiaohongshu",
                    "verified": False,
                    "failures": ["title"],
                },
                "publication_audit": {
                    "required_unverified": ["title"],
                    "required_reupload": [],
                },
            },
            "error": {
                "code": "publication_audit_unverified",
                "message": "title mismatch",
            },
        },
    )

    overrides, _ = publication._build_platform_recovery_overrides(
        attempt=attempt,
        request_plan_signature="plan-1",
    )

    assert overrides["clear_draft_context"] is True
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["recovery_mode"] == "draft_reset"
    assert "verification_only_current_page" not in overrides
    assert "wait_for_publish_confirmation" not in overrides


def test_build_platform_recovery_overrides_preserves_receipt_rebind_overrides_for_pending_receipt_signal():
    attempt = SimpleNamespace(
        id="attempt-pending-receipt-carry-over",
        platform="douyin",
        status="needs_human",
        provider_status="published",
        error_code="publication_public_url_missing",
        request_payload={
            "publication_plan_signature": {"value": "plan-1"},
            "platform_specific_overrides": {
                "recovery_mode": "receipt_rebind",
                "verification_only_current_page": True,
                "wait_for_publish_confirmation": True,
                "force_publish_page_refresh": True,
            },
        },
        response_payload={
            "error": {
                "code": "publication_public_url_missing",
                "message": "receipt pending",
            },
        },
    )

    overrides, _ = publication._build_platform_recovery_overrides(
        attempt=attempt,
        request_plan_signature="plan-1",
    )

    assert overrides["recovery_mode"] == "receipt_rebind"
    assert overrides["verification_only_current_page"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert overrides["force_publish_page_refresh"] is True


def test_is_publication_recovery_target_accepts_safe_receipt_rebind_modes():
    assert publication._is_publication_recovery_target({
        "platform_specific_overrides": {
            "recovery_mode": "receipt_rebind",
            "verification_only_current_page": True,
        }
    }) is True
    assert publication._is_publication_recovery_target({
        "platform_specific_overrides": {
            "recovery_mode": "prepublish_resume",
            "prepare_only_current_page": True,
        }
    }) is True


def test_build_platform_recovery_overrides_strips_stale_prepublish_resume_overrides_without_structural_blocker():
    attempt = SimpleNamespace(
        id="attempt-stale-prepublish-resume-overrides",
        platform="douyin",
        status="needs_human",
        provider_status="needs_human",
        error_code="publication_audit_unverified",
        request_payload={
            "publication_plan_signature": {"value": "plan-1"},
            "platform_specific_overrides": {
                "recovery_mode": "prepublish_resume",
                "prepare_only_current_page": True,
                "verify_media_upload": True,
                "wait_for_publish_confirmation": True,
                "force_publish_page_refresh": True,
            },
        },
        response_payload={
            "result": {
                "material_integrity": {
                    "platform": "douyin",
                    "verified": False,
                    "failures": ["title"],
                },
                "publication_audit": {
                    "required_unverified": ["title"],
                    "required_reupload": [],
                },
            },
            "error": {
                "code": "publication_audit_unverified",
                "message": "title mismatch",
            },
        },
    )

    overrides, _ = publication._build_platform_recovery_overrides(
        attempt=attempt,
        request_plan_signature="plan-1",
    )

    assert overrides["clear_draft_context"] is True
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["recovery_mode"] == "draft_reset"
    assert "prepare_only_current_page" not in overrides
    assert "verify_media_upload" not in overrides
    assert "wait_for_publish_confirmation" not in overrides


def test_coerce_recovery_plan_preserves_safe_verification_flags():
    recovery_plan = publication._coerce_recovery_plan({
        "recovery_overrides": {
            "recovery_mode": "receipt_rebind",
            "clear_draft_context": False,
            "force_publish_page_refresh": True,
            "verification_only_current_page": True,
            "wait_for_publish_confirmation": True,
            "verify_media_upload": True,
        }
    })

    assert recovery_plan is not None
    overrides = recovery_plan["recovery_overrides"]
    assert overrides["recovery_mode"] == "receipt_rebind"
    assert overrides["verification_only_current_page"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert overrides["verify_media_upload"] is True


def test_build_platform_recovery_overrides_uses_safe_prepare_mode_for_pre_publish_upload_pending():
    attempt = SimpleNamespace(
        id="attempt-upload-pending-requeue",
        platform="douyin",
        status="needs_human",
        provider_status="needs_human",
        error_code="douyin_pre_publish_upload_pending",
        request_payload={
            "publication_plan_signature": {"value": "plan-1"},
            "platform_specific_overrides": {},
        },
        response_payload={
            "result": {
                "material_integrity": {
                    "platform": "douyin",
                    "verified": False,
                    "failures": ["upload_ready"],
                },
                "publication_audit": {
                    "required_unverified": ["upload_ready"],
                    "required_reupload": ["upload_ready"],
                },
            },
            "error": {
                "code": "douyin_pre_publish_upload_pending",
                "message": "waiting upload",
            },
            "recovery": {
                "code": "douyin_pre_publish_upload_pending",
            },
        },
    )

    overrides, _ = publication._build_platform_recovery_overrides(
        attempt=attempt,
        request_plan_signature="plan-1",
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["prepare_only_current_page"] is True
    assert overrides["verify_media_upload"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert overrides["recovery_mode"] == "prepublish_resume"


def test_build_platform_recovery_overrides_uses_safe_prepare_mode_for_youtube_editor_runtime_pending():
    attempt = SimpleNamespace(
        id="attempt-youtube-editor-runtime-pending",
        platform="youtube",
        status="processing",
        provider_status="processing",
        error_code="youtube_pre_publish_upload_pending",
        request_payload={
            "publication_plan_signature": {"value": "plan-1"},
            "platform_specific_overrides": {},
        },
        response_payload={
            "result": {
                "material_integrity": {
                    "platform": "youtube",
                    "verified": False,
                    "verification_reason": "editor_surface_runtime_timeout",
                    "failures": [],
                    "fields": {
                        "upload_ready": {"actual": "not_ready", "verified": False},
                    },
                },
                "publication_audit": {
                    "verified": False,
                    "required_unverified": ["upload_ready"],
                    "required_reupload": ["upload_ready"],
                },
                "recovery_overrides": {
                    "recovery_mode": "prepublish_resume",
                    "clear_draft_context": False,
                    "force_publish_page_refresh": True,
                    "prepare_only_current_page": True,
                    "verify_media_upload": True,
                    "wait_for_publish_confirmation": True,
                },
            },
            "error": {
                "code": "youtube_pre_publish_upload_pending",
                "message": "页面已进入编辑表面，但 CDP Runtime 暂时无响应，继续保留现场等待页面恢复。",
            },
        },
    )

    overrides, _ = publication._build_platform_recovery_overrides(
        attempt=attempt,
        request_plan_signature="plan-1",
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["prepare_only_current_page"] is True
    assert overrides["verify_media_upload"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert overrides["recovery_mode"] == "prepublish_resume"


def test_build_platform_recovery_overrides_uses_safe_prepare_mode_for_upload_not_applied():
    attempt = SimpleNamespace(
        id="attempt-upload-not-applied-requeue",
        platform="kuaishou",
        status="needs_human",
        provider_status="needs_human",
        error_code="kuaishou_media_upload_failed",
        request_payload={
            "publication_plan_signature": {"value": "plan-1"},
            "platform_specific_overrides": {},
        },
        response_payload={
            "error": {
                "code": "kuaishou_media_upload_failed",
                "message": "媒体上传未生效：upload_not_applied",
                "details": {"failure_reason": "upload_not_applied"},
            },
            "result": {
                "material_integrity": {
                    "platform": "kuaishou",
                    "verified": False,
                    "verification_reason": "upload_failed",
                    "fields": {
                        "upload_ready": {"actual": "prompt_only", "verified": False},
                    },
                },
                "publication_audit": {},
            },
        },
    )

    overrides, _ = publication._build_platform_recovery_overrides(
        attempt=attempt,
        request_plan_signature="plan-1",
    )

    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["prepare_only_current_page"] is True
    assert overrides["verify_media_upload"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert overrides["recovery_mode"] == "prepublish_resume"


def test_build_platform_recovery_overrides_does_not_force_draft_reset_for_route_auth_required():
    attempt = SimpleNamespace(
        id="attempt-route-auth-requeue",
        platform="wechat-channels",
        status="needs_human",
        provider_status="needs_human",
        error_code="wechat-channels_route_auth_required",
        request_payload={
            "publication_plan_signature": {"value": "plan-1"},
            "platform_specific_overrides": {
                "clear_draft_context": True,
                "force_publish_page_refresh": True,
                "recovery_mode": "draft_reset",
            },
        },
        response_payload={
            "error": {
                "code": "wechat-channels_route_auth_required",
                "message": "login required",
            },
            "recovery": {
                "code": "wechat-channels_route_auth_required",
            },
        },
    )

    overrides, _ = publication._build_platform_recovery_overrides(
        attempt=attempt,
        request_plan_signature="plan-1",
    )

    assert overrides.get("clear_draft_context") is not True
    assert overrides.get("recovery_mode") != "draft_reset"


@pytest.mark.asyncio
async def test_apply_browser_agent_task_state_does_not_auto_recover_when_confidence_low(monkeypatch):
    attempt = SimpleNamespace(
        id="attempt-auto-recover-low",
        provider_status=None,
        provider_task_id="task-old",
        provider_execution_id="exec-old",
        response_payload=None,
        status="processing",
        run_status="processing",
        published_at=None,
        scheduled_at=None,
        external_post_id=None,
        external_receipt_id=None,
        external_url=None,
        retry_count=0,
        max_retries=3,
        next_retry_at=None,
        error_code=None,
        error_message=None,
        operator_summary=None,
    )

    async def _mock_recovery_analysis(*args, **kwargs):
        return {
            "severity": "high",
            "action": "retry",
            "retryable": True,
            "next_steps": ["重新提交任务"],
            "confidence": 0.41,
            "evidence": ["network_error"],
            "rationale": "低置信度建议，先观察。",
        }

    monkeypatch.setattr(publication, "_analyze_publication_failure_with_llm", _mock_recovery_analysis)
    run = SimpleNamespace(
        status="failed",
        phase="reconcile",
        heartbeat_at=None,
        provider_task_id="task-old",
        provider_execution_id="exec-old",
        provider_status="network_error",
        result_json=None,
        error_message=None,
        completed_at=None,
    )
    task = {
        "task_id": "task-old",
        "status": "network_error",
        "error": {
            "code": "network_error",
            "message": "临时网络波动",
        },
    }

    await publication._apply_browser_agent_task_state(attempt, run, task, response_payload={"task": task})

    assert attempt.status == "failed"
    assert attempt.run_status == "failed"
    assert attempt.retry_count == 0
    assert attempt.next_retry_at is None
    assert "LLM 建议自动恢复" not in str(attempt.operator_summary)
    assert run.status == "failed"


@pytest.mark.asyncio
async def test_publication_browser_agent_ready_requires_requested_final_publish_platforms():
    result = await publication.check_publication_browser_agent_ready(
        browser_agent_base_url="http://browser-agent",
        target_platforms=["bilibili", "youtube"],
        http_client=_FakeBrowserAgentHealthClient(["bilibili"]),
    )

    assert result["ready"] is False
    assert result["code"] == "browser_agent_live_publish_platform_unsupported"


@pytest.mark.asyncio
async def test_publication_browser_agent_ready_allows_prepare_only_without_live_publish():
    transport = _FakeBrowserAgentHealthClient(
        ["douyin"],
        composite_frameworks={"douyin": "douyin_creator_composite_v1"},
        extra_capabilities={"live_publish": False},
        creator_sessions={
            "douyin": {
                "platform": "douyin",
                "ready": True,
                "status": "ready",
                "message": "创作者会话可用。",
                "route": {
                    "url": "https://creator.douyin.com/creator-micro/content/upload",
                    "title": "抖音创作者中心",
                },
            }
        },
    )

    result = await publication.check_publication_browser_agent_ready(
        browser_agent_base_url="http://127.0.0.1:49310",
        http_client=transport,
        target_platforms=["douyin"],
        require_live_publish=False,
    )

    assert result["ready"] is True


@pytest.mark.asyncio
async def test_publication_browser_agent_ready_requires_composite_frameworks():
    result = await publication.check_publication_browser_agent_ready(
        browser_agent_base_url="http://browser-agent",
        target_platforms=["bilibili", "youtube"],
        http_client=_FakeBrowserAgentHealthClient(["bilibili", "youtube"], composite_frameworks={"youtube": "youtube_studio_composite_v1"}),
    )

    assert result["ready"] is False
    assert result["code"] == "browser_agent_composite_framework_missing"
    assert "B站" in result["message"]


@pytest.mark.asyncio
async def test_publication_browser_agent_ready_requires_legacy_script_block():
    result = await publication.check_publication_browser_agent_ready(
        browser_agent_base_url="http://browser-agent",
        target_platforms=["xiaohongshu"],
        http_client=_FakeBrowserAgentHealthClient(["xiaohongshu"], legacy_blocked=False),
    )

    assert result["ready"] is False
    assert result["code"] == "browser_agent_legacy_lightweight_scripts_not_blocked"
    assert "小红书" in result["message"]


@pytest.mark.asyncio
async def test_publication_browser_agent_ready_requires_declared_profile_reuse():
    result = await publication.check_publication_browser_agent_ready(
        browser_agent_base_url="http://browser-agent",
        target_platforms=["douyin"],
        target_profile_ids=["browser-agent:chrome:fas:douyin"],
        http_client=_FakeBrowserAgentHealthClient(["douyin"]),
    )

    assert result["ready"] is False
    assert result["code"] == "browser_agent_profile_reuse_unverified"
    assert result["profile_reuse"]["code"] == "profile_binding_not_declared"


@pytest.mark.asyncio
async def test_publication_browser_agent_ready_requires_reusable_profile_id_list():
    result = await publication.check_publication_browser_agent_ready(
        browser_agent_base_url="http://browser-agent",
        target_platforms=["douyin"],
        target_profile_ids=["browser-agent:chrome:fas:douyin"],
        http_client=_FakeBrowserAgentHealthClient(
            ["douyin"],
            extra_capabilities={
                "profile_reuse": True,
                "profile_binding_mode": "profile_id",
            },
        ),
    )

    assert result["ready"] is False
    assert result["code"] == "browser_agent_profile_reuse_unverified"
    assert result["profile_reuse"]["code"] == "target_profiles_not_declared"


@pytest.mark.asyncio
async def test_publication_browser_agent_ready_accepts_declared_profile_reuse():
    client = _FakeBrowserAgentHealthClient(
        ["douyin"],
        creator_sessions={
            "douyin": {
                "platform": "douyin",
                "status": "ready",
                "code": "",
                "route": {"url": "https://creator.douyin.com/creator-micro/content/post/video"},
            }
        },
        extra_capabilities={
            "profile_reuse": True,
            "profile_binding_mode": "profile_id",
            "reusable_profile_ids": ["browser-agent:chrome:fas:douyin"],
        },
    )
    result = await publication.check_publication_browser_agent_ready(
        browser_agent_base_url="http://browser-agent",
        target_platforms=["douyin"],
        target_profile_ids=["browser-agent:chrome:fas:douyin"],
        http_client=client,
    )

    assert result["ready"] is True
    assert result["code"] == "ready"
    assert "target_profile_ids=browser-agent%3Achrome%3Afas%3Adouyin" in client.gets[0]["url"]


@pytest.mark.asyncio
async def test_publication_browser_agent_ready_passes_session_binding_query():
    client = _FakeBrowserAgentHealthClient(
        ["youtube"],
        creator_sessions={
            "youtube": {
                "platform": "youtube",
                "status": "ready",
                "code": "",
                "route": {"url": "https://studio.youtube.com/channel/abc/videos/upload"},
            }
        },
        extra_capabilities={
            "profile_reuse": True,
            "profile_binding_mode": "persistent_profile",
            "reusable_profile_ids": ["browser-profile:chrome:test"],
        },
    )
    result = await publication.check_publication_browser_agent_ready(
        browser_agent_base_url="http://browser-agent",
        target_platforms=["youtube"],
        target_profile_ids=["browser-profile:chrome:test"],
        session_bindings={
            "youtube": publication.build_publication_browser_session_binding(
                platform="youtube",
                creator_profile_id="creator-1",
                browser_profile_id="browser-profile:chrome:test",
                credential_ref="browser-agent:youtube:creator-1",
                account_label="Creator One · YouTube",
                allowed_route_contexts=["publish_route"],
            )
        },
        http_client=client,
    )

    assert result["ready"] is True
    assert "session_bindings=" in client.gets[0]["url"]


@pytest.mark.asyncio
async def test_publication_browser_agent_ready_does_not_pass_creator_profile_id_as_browser_profile_target():
    client = _FakeBrowserAgentHealthClient(
        ["youtube"],
        creator_sessions={
            "youtube": {
                "platform": "youtube",
                "status": "ready",
                "code": "",
                "route": {"url": "https://studio.youtube.com/channel/abc/videos/upload"},
            }
        },
        extra_capabilities={
            "profile_reuse": True,
            "profile_binding_mode": "persistent_profile",
            "reusable_profile_ids": ["browser-profile:chrome:test"],
        },
    )
    result = await publication.check_publication_browser_agent_ready(
        browser_agent_base_url="http://browser-agent",
        target_platforms=["youtube"],
        target_profile_ids=["d2d15bc6d77a47b79cf20a79b56596c2"],
        http_client=client,
    )

    assert result["ready"] is True
    assert "target_profile_ids=" not in client.gets[0]["url"]


@pytest.mark.asyncio
async def test_publication_browser_agent_ready_fails_closed_on_session_binding_mismatch():
    result = await publication.check_publication_browser_agent_ready(
        browser_agent_base_url="http://browser-agent",
        target_platforms=["toutiao"],
        target_profile_ids=["browser-profile:chrome:bound"],
        http_client=_FakeBrowserAgentHealthClient(
            ["toutiao"],
            creator_sessions={
                "toutiao": {
                    "platform": "toutiao",
                    "status": "binding_mismatch",
                    "code": "toutiao_session_binding_mismatch",
                    "message": "mismatch",
                    "route": {"url": ""},
                }
            },
            extra_capabilities={
                "profile_reuse": True,
                "profile_binding_mode": "persistent_profile",
                "reusable_profile_ids": ["browser-profile:chrome:bound"],
            },
        ),
    )

    assert result["ready"] is False
    assert result["code"] == "browser_agent_creator_session_binding_mismatch"


@pytest.mark.asyncio
async def test_publication_browser_agent_ready_requires_task_identity_contract():
    result = await publication.check_publication_browser_agent_ready(
        browser_agent_base_url="http://browser-agent",
        target_platforms=["douyin"],
        http_client=_FakeBrowserAgentHealthClient(
            ["douyin"],
            extra_capabilities={
                "task_identity_echo": False,
                "task_identity_contract": "",
            },
        ),
    )

    assert result["ready"] is False
    assert result["code"] == "browser_agent_task_identity_contract_unsupported"


@pytest.mark.asyncio
async def test_publication_browser_agent_ready_detects_runtime_drift(monkeypatch):
    monkeypatch.setattr(
        publication,
        "_local_publication_browser_agent_service_sha256",
        lambda: "expected-runtime-sha",
    )
    client = _FakeBrowserAgentHealthClient(["douyin"])

    original_get = client.get

    async def _get(url, *, headers):
        response = await original_get(url, headers=headers)
        payload = response.json()
        payload["service_script_sha256"] = "stale-runtime-sha"
        return _FakeBrowserAgentResponse(payload)

    client.get = _get
    result = await publication.check_publication_browser_agent_ready(
        browser_agent_base_url="http://browser-agent",
        target_platforms=["douyin"],
        http_client=client,
    )

    assert result["ready"] is False
    assert result["code"] == "browser_agent_runtime_drift"


@pytest.mark.asyncio
async def test_publication_browser_agent_ready_blocks_auth_required_creator_session():
    result = await publication.check_publication_browser_agent_ready(
        browser_agent_base_url="http://browser-agent",
        target_platforms=["douyin"],
        http_client=_FakeBrowserAgentHealthClient(
            ["douyin"],
            creator_sessions={
                "douyin": {
                    "platform": "douyin",
                    "status": "auth_required",
                    "code": "douyin_route_auth_required",
                    "route": {"url": "https://creator.douyin.com/creator-micro/content/post/video"},
                    "visual_evidence": {
                        "artifact_path": "E:/WorkSpace/RoughCut/artifacts/publication-visual-evidence/20260602/douyin/session-auth.png",
                        "capture_type": "screenshot",
                        "phase": "creator_session_probe",
                    },
                }
            },
        ),
    )

    assert result["ready"] is False
    assert result["code"] == "browser_agent_creator_session_auth_required"
    assert "抖音" in result["message"]
    assert result["health"]["creator_sessions"]["douyin"]["visual_evidence"]["capture_type"] == "screenshot"


@pytest.mark.asyncio
async def test_publication_browser_agent_ready_blocks_unverified_creator_session():
    result = await publication.check_publication_browser_agent_ready(
        browser_agent_base_url="http://browser-agent",
        target_platforms=["douyin"],
        http_client=_FakeBrowserAgentHealthClient(
            ["douyin"],
            creator_sessions={
                "douyin": {
                    "platform": "douyin",
                    "status": "route_not_ready",
                    "code": "douyin_prepublish_only_route_not_ready",
                    "route": {"url": "https://creator.douyin.com/creator-micro/content/post/video"},
                }
            },
        ),
    )

    assert result["ready"] is False
    assert result["code"] == "browser_agent_creator_session_unverified"


def test_publication_plan_blocks_unready_smart_copy_platform(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    plan = publication.build_publication_plan(
        job=SimpleNamespace(id="job-1", status="done"),
        render_output=SimpleNamespace(output_path=str(media_path)),
        platform_packaging={
            "publish_ready": False,
            "blocking_reasons": ["抖音：封面等待 Codex 内置 imagegen 执行完成"],
            "platforms": {
                "douyin": {
                    "titles": ["标题"],
                    "description": "简介",
                    "tags": ["tag"],
                    "publish_ready": False,
                    "blocking_reasons": ["封面等待 Codex 内置 imagegen 执行完成"],
                }
            },
        },
        creator_profile={
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
            }
        },
    )

    assert plan["publish_ready"] is False
    assert any("封面等待 Codex 内置 imagegen 执行完成" in reason for reason in plan["blocked_reasons"])
    assert plan["targets"] == []


def test_publication_plan_ignores_root_publish_ready_false_when_requested_platform_is_ready(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    plan = publication.build_publication_plan(
        job=SimpleNamespace(id="job-1", status="done"),
        render_output=SimpleNamespace(output_path=str(media_path)),
        platform_packaging={
            "publish_ready": False,
            "blocking_reasons": ["小红书：封面缺失"],
            "platforms": {
                "douyin": {
                    "titles": ["抖音标题"],
                    "description": "抖音简介",
                    "tags": ["tag"],
                    "publish_ready": True,
                    "blocking_reasons": [],
                    "live_publish_preflight": {
                        "status": "ready",
                        "missing_required_surfaces": [],
                    },
                },
                "xiaohongshu": {
                    "titles": ["小红书标题"],
                    "description": "小红书简介",
                    "tags": ["tag"],
                    "publish_ready": False,
                    "blocking_reasons": ["封面缺失"],
                    "live_publish_preflight": {
                        "status": "blocked",
                        "missing_required_surfaces": ["cover"],
                    },
                },
            },
        },
        creator_profile={
            "creator_profile": {
                "publishing": {
                    "platform_credentials": [
                        {
                            "platform": "douyin",
                            "account_label": "主号",
                            "credential_ref": "chrome-profile:douyin",
                            "status": "logged_in",
                            "enabled": True,
                            "adapter": "browser_agent",
                        },
                        {
                            "platform": "xiaohongshu",
                            "account_label": "主号",
                            "credential_ref": "chrome-profile:xiaohongshu",
                            "status": "logged_in",
                            "enabled": True,
                            "adapter": "browser_agent",
                        },
                    ]
                }
            }
        },
        requested_platforms=["douyin"],
    )

    assert plan["publish_ready"] is True
    assert [target["platform"] for target in plan["targets"]] == ["douyin"]
    assert plan["blocked_reasons"] == []


def test_filter_publication_packaging_platforms_recomputes_root_publish_ready_for_requested_subset() -> None:
    filtered = filter_publication_packaging_platforms(
        {
            "publish_ready": False,
            "blocking_reasons": ["youtube 缺少 live_publish_preflight"],
            "platform_scope": {
                "requested_platforms": ["douyin", "youtube"],
                "covered_platforms": ["douyin", "youtube"],
                "missing_requested_platforms": [],
            },
            "platforms": {
                "douyin": {
                    "title": "抖音标题",
                    "live_publish_preflight": {"status": "ready"},
                    "blocking_reasons": [],
                    "publish_ready": True,
                },
                "youtube": {
                    "title": "YouTube 标题",
                    "live_publish_preflight": {
                        "status": "blocked",
                        "missing_required_surfaces": ["editor_surface"],
                    },
                    "blocking_reasons": ["youtube 缺少 live_publish_preflight"],
                    "publish_ready": False,
                },
            },
        },
        platforms=["douyin"],
    )

    assert filtered is not None
    assert filtered["publish_ready"] is True
    assert filtered["blocking_reasons"] == []


def test_load_publication_packaging_payload_backfills_missing_requested_platform_from_material_json(
    tmp_path,
) -> None:
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text(
        json.dumps(
            {
                "platforms": [
                    {
                        "key": "bilibili",
                        "primary_title": "B站标题",
                        "body": "B站正文",
                        "tags": ["EDC"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    packaging_json = tmp_path / "platform-packaging.json"
    packaging_json.write_text(
        json.dumps(
            {
                "platforms": {
                    "douyin": {
                        "primary_title": "抖音标题",
                        "description": "抖音正文",
                        "publish_ready": True,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    packaging, sources = load_publication_packaging_payload(
        material_json=str(material_json),
        platform_packaging="",
        platforms=["bilibili"],
    )

    assert packaging is not None
    assert sources["source"] == "platform_packaging+material_json"
    assert packaging["platforms"]["douyin"]["primary_title"] == "抖音标题"
    assert packaging["platforms"]["bilibili"]["primary_title"] == "B站标题"


def test_load_publication_packaging_payload_resolves_structured_smart_copy_meta_layout(tmp_path) -> None:
    material_dir = tmp_path / "smart-copy"
    smart_copy_material_json_path(material_dir).parent.mkdir(parents=True)
    smart_copy_material_json_path(material_dir).write_text(
        json.dumps(
            {
                "platforms": [
                    {
                        "key": "xiaohongshu",
                        "primary_title": "小红书标题",
                        "body": "小红书正文",
                        "tags": ["EDC"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    smart_copy_platform_packaging_json_path(material_dir).write_text(
        json.dumps(
            {
                "platforms": {
                    "xiaohongshu": {
                        "primary_title": "小红书标题",
                        "description": "小红书正文",
                        "publish_ready": True,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    packaging, sources = load_publication_packaging_payload(
        material_json=str(material_dir / "smart-copy.json"),
        platform_packaging=str(material_dir / "platform-packaging.json"),
        platforms=["xiaohongshu"],
    )

    assert packaging is not None
    assert packaging["material_dir"] == str(material_dir)
    assert sources["source"] == "platform_packaging"
    assert packaging["platforms"]["xiaohongshu"]["primary_title"] == "小红书标题"


def test_publication_plan_blocks_missing_live_publish_preflight_surfaces(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    plan = publication.build_publication_plan(
        job=SimpleNamespace(id="job-1", status="done"),
        render_output=SimpleNamespace(output_path=str(media_path)),
        platform_packaging={
            "platforms": {
                "kuaishou": {
                    "titles": ["标题"],
                    "description": "简介",
                    "tags": ["tag"],
                }
            }
        },
        creator_profile={
            "creator_profile": {
                "publishing": {
                    "platform_credentials": [
                        {
                            "platform": "kuaishou",
                            "account_label": "主号",
                            "credential_ref": "chrome-profile:main",
                            "status": "logged_in",
                            "enabled": True,
                            "adapter": "browser_agent",
                        }
                    ]
                }
            }
        },
        platform_options={
            "kuaishou": {
                "scheduled_publish_at": "2026-04-26T20:00",
                "visibility_or_publish_mode": "scheduled",
                "live_publish_preflight": {
                    "status": "blocked",
                    "missing_required_surfaces": ["cover", "visibility", "schedule"],
                    "summary": "缺少发布页关键参数面：cover、visibility、schedule",
                },
            }
        },
    )

    assert plan["publish_ready"] is False
    assert plan["targets"] == []
    assert "所有候选平台都未通过发布前页面验证。" in plan["blocked_reasons"]
    assert any("快手 发布前验证未通过" in warning for warning in plan["warnings"])


def test_publication_plan_blocks_packaging_entry_when_publish_ready_flag_missing_but_preflight_blocked(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    plan = publication.build_publication_plan(
        job=SimpleNamespace(id="job-1", status="done"),
        render_output=SimpleNamespace(output_path=str(media_path)),
        platform_packaging={
            "platforms": {
                "douyin": {
                    "titles": ["标题"],
                    "description": "简介",
                    "tags": ["tag"],
                    "blocking_reasons": ["封面缺失"],
                    "live_publish_preflight": {
                        "status": "blocked",
                        "missing_required_surfaces": ["cover"],
                        "summary": "缺少发布页关键参数面：cover",
                    },
                }
            }
        },
        creator_profile={
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
            }
        },
    )

    assert plan["publish_ready"] is False
    assert plan["targets"] == []
    assert any("抖音 未就绪：封面缺失" == warning for warning in plan["warnings"])


def test_publication_plan_blocks_packaging_entry_when_publish_ready_true_but_preflight_blocked(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    plan = publication.build_publication_plan(
        job=SimpleNamespace(id="job-1", status="done"),
        render_output=SimpleNamespace(output_path=str(media_path)),
        platform_packaging={
            "platforms": {
                "douyin": {
                    "titles": ["标题"],
                    "description": "简介",
                    "tags": ["tag"],
                    "publish_ready": True,
                    "blocking_reasons": [],
                    "live_publish_preflight": {
                        "status": "blocked",
                        "missing_required_surfaces": ["cover"],
                        "summary": "缺少发布页关键参数面：cover",
                    },
                }
            }
        },
        creator_profile={
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
            }
        },
    )

    assert plan["publish_ready"] is False
    assert plan["targets"] == []
    assert any("抖音 未就绪" in warning for warning in plan["warnings"])


def test_publication_plan_falls_back_to_package_publication_metadata(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    cover_path = tmp_path / "cover.jpg"
    cover_path.write_bytes(b"cover")
    plan = publication.build_publication_plan(
        job=SimpleNamespace(id="job-1", status="done"),
        render_output=SimpleNamespace(output_path=str(media_path)),
        platform_packaging={
            "platforms": {
                "xiaohongshu": {
                    "titles": ["标题"],
                    "description": "简介",
                    "tags": ["tag"],
                    "cover_path": str(cover_path),
                    "declaration": "原创声明",
                    "collection_name": "EDC潮玩桌搭",
                    "visibility_or_publish_mode": "scheduled",
                    "scheduled_publish_at": "2026-05-31T21:00",
                    "category": "潮玩",
                    "platform_specific_overrides": {
                        "selected_declarations": ["原创声明"],
                    },
                    "copy_material": {
                        "source": "intelligent_copy_material_self_heal",
                    },
                }
            }
        },
        creator_profile={
            "creator_profile": {
                "publishing": {
                    "platform_credentials": [
                        {
                            "platform": "xiaohongshu",
                            "account_label": "主号",
                            "credential_ref": "chrome-profile:main",
                            "status": "logged_in",
                            "enabled": True,
                            "adapter": "browser_agent",
                        }
                    ]
                }
            }
        },
    )

    assert plan["publish_ready"] is True
    target = plan["targets"][0]
    assert target["declaration"] == "原创声明"
    assert target["cover_path"] == str(cover_path)
    assert target["collection"] == {"name": "EDC潮玩桌搭"}
    assert target["visibility_or_publish_mode"] == "scheduled"
    assert target["scheduled_publish_at"] == "2026-05-31T21:00"
    assert target["category"] == "潮玩"
    assert target["platform_specific_overrides"]["selected_declarations"] == ["原创声明"]
    assert target["copy_material"]["source"] == "intelligent_copy_material_self_heal"


def test_publication_plan_drops_youtube_placeholder_category(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    plan = publication.build_publication_plan(
        job=SimpleNamespace(id="job-1", status="done"),
        render_output=SimpleNamespace(output_path=str(media_path)),
        platform_packaging={
            "platforms": {
                "youtube": {
                    "titles": ["标题"],
                    "description": "简介",
                    "tags": ["tag"],
                    "category": "视频",
                }
            }
        },
        creator_profile={
            "creator_profile": {
                "publishing": {
                    "platform_credentials": [
                        {
                            "platform": "youtube",
                            "account_label": "主号",
                            "credential_ref": "chrome-profile:main",
                            "status": "logged_in",
                            "enabled": True,
                            "adapter": "browser_agent",
                        }
                    ]
                }
            }
        },
    )

    assert plan["publish_ready"] is True
    assert plan["targets"][0]["category"] is None


def test_publication_plan_defaults_youtube_visibility_to_public(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    plan = publication.build_publication_plan(
        job=SimpleNamespace(id="job-1", status="done"),
        render_output=SimpleNamespace(output_path=str(media_path)),
        platform_packaging={
            "platforms": {
                "youtube": {
                    "titles": ["标题"],
                    "description": "简介",
                    "tags": ["tag"],
                }
            }
        },
        creator_profile={
            "creator_profile": {
                "publishing": {
                    "platform_credentials": [
                        {
                            "platform": "youtube",
                            "account_label": "主号",
                            "credential_ref": "chrome-profile:main",
                            "status": "logged_in",
                            "enabled": True,
                            "adapter": "browser_agent",
                        }
                    ]
                }
            }
        },
    )

    assert plan["publish_ready"] is True
    assert plan["targets"][0]["visibility_or_publish_mode"] == "public"


def test_publication_plan_projects_collection_management_and_native_topics_from_platform_options(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    plan = publication.build_publication_plan(
        job=SimpleNamespace(id="job-1", status="done"),
        render_output=SimpleNamespace(output_path=str(media_path)),
        platform_packaging={
            "platforms": {
                "douyin": {
                    "titles": ["标题"],
                    "description": "简介",
                    "tags": ["EDC折刀", "MAXACE美杜莎4"],
                    "platform_specific_overrides": {
                        "collection_policy": "skip",
                        "skip_collection_select": True,
                    },
                }
            }
        },
        platform_options={
            "douyin": {
                "scheduled_publish_at": "2026-06-04T20:30",
                "visibility_or_publish_mode": "scheduled",
                "platform_specific_overrides": {
                    "topic_selection_plan": {
                        "mode": "prefer_platform_topic_suggestions_then_fallback_to_tag_input",
                        "requested_topics": ["EDC折刀", "MAXACE美杜莎4"],
                    },
                    "collection_management": {
                        "status": "needs_create",
                        "target_collection_name": "EDC刀光火工具集",
                    },
                },
            }
        },
        creator_profile={
            "creator_profile": {
                "publishing": {
                    "platform_credentials": [
                        {
                            "platform": "douyin",
                            "account_label": "主号",
                            "credential_ref": "chrome-profile:douyin",
                            "status": "logged_in",
                            "enabled": True,
                            "adapter": "browser_agent",
                        }
                    ]
                }
            }
        },
    )

    assert plan["publish_ready"] is True
    target = plan["targets"][0]
    assert target["collection"] == {"name": "EDC刀光火工具集"}
    assert target["scheduled_publish_at"] == "2026-06-04T20:30"
    assert target["visibility_or_publish_mode"] == "scheduled"
    assert target["native_topics"] == ["EDC折刀", "MAXACE美杜莎4"]
    assert "collection_policy" not in target["platform_specific_overrides"]
    assert "skip_collection_select" not in target["platform_specific_overrides"]
    assert target["platform_specific_overrides"]["collection_management"]["target_collection_name"] == "EDC刀光火工具集"
    assert target["platform_specific_overrides"]["topic_selection_plan"]["requested_topics"] == ["EDC折刀", "MAXACE美杜莎4"]


def test_publication_plan_clamps_xiaohongshu_title_to_platform_hard_limit(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    plan = publication.build_publication_plan(
        job=SimpleNamespace(id="job-1", status="done"),
        render_output=SimpleNamespace(output_path=str(media_path)),
        platform_packaging={
            "platforms": {
                "xiaohongshu": {
                    "titles": ["新到的美杜莎4｜两款配置到手，差别一眼就懂"],
                    "description": "简介",
                    "tags": ["EDC折刀"],
                }
            }
        },
        creator_profile={
            "creator_profile": {
                "publishing": {
                    "platform_credentials": [
                        {
                            "platform": "xiaohongshu",
                            "account_label": "主号",
                            "credential_ref": "chrome-profile:xiaohongshu",
                            "status": "logged_in",
                            "enabled": True,
                            "adapter": "browser_agent",
                        }
                    ]
                }
            }
        },
    )

    assert plan["publish_ready"] is True
    target = plan["targets"][0]
    assert target["title"] == "新到的美杜莎4｜两款配置到手，差别一眼就"
    assert target["copy_material"]["primary_title"] == "新到的美杜莎4｜两款配置到手，差别一眼就"


def test_publication_plan_skips_platforms_with_title_audit_errors(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    plan = publication.build_publication_plan(
        job=SimpleNamespace(id="job-1", status="done"),
        render_output=SimpleNamespace(output_path=str(media_path)),
        platform_packaging={
            "platforms": {
                "douyin": {
                    "titles": ["抖音标题 1", "抖音标题 2", "抖音标题 3"],
                    "description": "简介",
                    "tags": ["tag"],
                },
                "x": {
                    "titles": ["只有一个标题"],
                    "description": "推文",
                    "tags": ["tag"],
                },
            },
            "title_audit": {
                "summary": {"status": "error"},
                "platforms": {
                    "douyin": {"summary": {"status": "pass"}, "issues": []},
                    "x": {
                        "summary": {"status": "error"},
                        "issues": [
                            {
                                "severity": "error",
                                "code": "title_count_short",
                                "message": "X 只有 1 个标题，没满足 3 个版本输出要求。",
                            }
                        ],
                    },
                },
            },
        },
        creator_profile={
            "creator_profile": {
                "publishing": {
                    "platform_credentials": [
                        {
                            "platform": "douyin",
                            "account_label": "主号",
                            "credential_ref": "chrome-profile:douyin",
                            "status": "logged_in",
                            "enabled": True,
                            "adapter": "browser_agent",
                        },
                        {
                            "platform": "x",
                            "account_label": "主号",
                            "credential_ref": "chrome-profile:x",
                            "status": "logged_in",
                            "enabled": True,
                            "adapter": "browser_agent",
                        },
                    ]
                }
            }
        },
    )

    assert plan["publish_ready"] is True
    assert [target["platform"] for target in plan["targets"]] == ["douyin"]
    assert any("X 标题审核未通过" in warning for warning in plan["warnings"])


def test_publication_plan_defaults_to_stable_platforms_when_not_explicitly_requested(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    all_platforms = [
        "douyin",
        "xiaohongshu",
        "bilibili",
        "kuaishou",
        "wechat-channels",
        "toutiao",
        "youtube",
        "x",
    ]
    packaging = {
        platform: {
            "titles": ["标题"],
            "description": "简介",
            "tags": ["tag"],
        }
        for platform in all_platforms
    }
    plan = publication.build_publication_plan(
        job=SimpleNamespace(id="job-1", status="done"),
        render_output=SimpleNamespace(output_path=str(media_path)),
        platform_packaging={"platforms": packaging},
        creator_profile={
            "creator_profile": {
                "publishing": {
                    "platform_credentials": [
                        {
                            "platform": platform,
                            "account_label": f"{platform}账号",
                            "credential_ref": f"chrome-profile:{platform}",
                            "status": "logged_in",
                            "enabled": True,
                            "adapter": "browser_agent",
                        }
                        for platform in all_platforms
                    ]
                }
            }
        },
    )

    assert plan["publish_ready"] is True
    assert [target["platform"] for target in plan["targets"]] == [
        "douyin",
        "xiaohongshu",
        "bilibili",
        "kuaishou",
        "toutiao",
        "youtube",
        "x",
    ]


def test_publication_plan_routes_wechat_channels_to_manual_handoff(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    plan = publication.build_publication_plan(
        job=SimpleNamespace(id="job-1", status="done"),
        render_output=SimpleNamespace(output_path=str(media_path)),
        platform_packaging={
            "platforms": {
                "wechat-channels": {
                    "titles": ["标题"],
                    "description": "简介",
                    "tags": ["tag"],
                },
            }
        },
        creator_profile={
            "creator_profile": {
                "publishing": {
                    "platform_credentials": [
                        {
                            "platform": "wechat-channels",
                            "account_label": "视频号账号",
                            "credential_ref": "chrome-profile:wechat",
                            "status": "logged_in",
                            "enabled": True,
                            "adapter": "browser_agent",
                        }
                    ]
                }
            }
        },
        requested_platforms=["wechat-channels"],
    )

    assert plan["status"] == "manual_handoff"
    assert plan["publish_ready"] is False
    assert plan["manual_handoff_ready"] is True
    assert plan["targets"] == []
    assert [target["platform"] for target in plan["manual_handoff_targets"]] == ["wechat-channels"]
    assert plan["manual_handoff_targets"][0]["status"] == "manual_handoff"
    assert plan["manual_handoff_targets"][0]["login_url"] == "https://channels.weixin.qq.com/login.html"
    assert "人工登录" in plan["blocked_reasons"][0]
    assert publication.publication_plan_is_manual_handoff_ready(plan) is True


def test_intelligent_publish_gate_response_preserves_manual_handoff_status():
    plan = {
        "status": "manual_handoff",
        "publish_ready": False,
        "manual_handoff_ready": True,
        "blocked_reasons": ["以下平台已切换为人工登录/人工发布，不再进入自动一键发布：视频号：当前平台仅支持人工登录后继续发布。"],
        "warnings": ["视频号 已切换为人工接管平台：当前平台仅支持人工登录后继续发布。 登录入口：https://channels.weixin.qq.com/login.html"],
        "targets": [],
        "manual_handoff_targets": [
            {
                "platform": "wechat-channels",
                "status": "manual_handoff",
                "login_url": "https://channels.weixin.qq.com/login.html",
            }
        ],
    }

    response = _build_publication_plan_gate_response(plan)

    assert response["status"] == "manual_handoff"
    assert response["publish_ready"] is False
    assert response["manual_handoff_ready"] is True
    assert response["manual_handoff_targets"][0]["login_url"] == "https://channels.weixin.qq.com/login.html"
    assert response["plan"] == plan


def test_publication_plan_helpers_derive_manual_handoff_from_targets_when_root_publish_ready_is_stale_true():
    plan = {
        "publish_ready": True,
        "manual_handoff_ready": False,
        "blocked_reasons": ["以下平台已切换为人工登录/人工发布，不再进入自动一键发布：视频号。"],
        "targets": [],
        "manual_handoff_targets": [
            {
                "platform": "wechat-channels",
                "status": "manual_handoff",
                "login_url": "https://channels.weixin.qq.com/login.html",
            }
        ],
    }

    assert publication.publication_plan_status(plan) == "manual_handoff"
    assert publication.publication_plan_is_manual_handoff_ready(plan) is True
    assert publication.publication_plan_is_publishable(plan) is False


def test_publication_plan_helpers_treat_ready_status_without_targets_as_blocked():
    plan = {
        "status": "ready",
        "publish_ready": True,
        "manual_handoff_ready": False,
        "blocked_reasons": [],
        "targets": [],
        "manual_handoff_targets": [],
    }

    assert publication.publication_plan_status(plan) == "blocked"
    assert publication.publication_plan_is_publishable(plan) is False


def test_intelligent_publish_gate_response_derives_manual_handoff_from_targets_when_root_publish_ready_is_stale_true():
    plan = {
        "publish_ready": True,
        "manual_handoff_ready": False,
        "blocked_reasons": ["以下平台已切换为人工登录/人工发布，不再进入自动一键发布：视频号。"],
        "warnings": [],
        "targets": [],
        "manual_handoff_targets": [
            {
                "platform": "wechat-channels",
                "status": "manual_handoff",
                "login_url": "https://channels.weixin.qq.com/login.html",
            }
        ],
    }

    response = _build_publication_plan_gate_response(plan)

    assert response["status"] == "manual_handoff"
    assert response["publish_ready"] is False
    assert response["manual_handoff_ready"] is True
    assert response["manual_handoff_targets"][0]["login_url"] == "https://channels.weixin.qq.com/login.html"


def test_intelligent_publish_executor_gate_response_preserves_manual_handoff_status():
    plan = {
        "status": "manual_handoff",
        "publish_ready": False,
        "manual_handoff_ready": True,
        "blocked_reasons": ["以下平台已切换为人工登录/人工发布，不再进入自动一键发布：视频号：当前平台仅支持人工登录后继续发布。"],
        "warnings": ["视频号 已切换为人工接管平台：当前平台仅支持人工登录后继续发布。 登录入口：https://channels.weixin.qq.com/login.html"],
        "targets": [],
        "manual_handoff_targets": [
            {
                "platform": "wechat-channels",
                "status": "manual_handoff",
                "login_url": "https://channels.weixin.qq.com/login.html",
            }
        ],
    }

    response = _build_publication_executor_gate_response(
        plan,
        publication_executor_preflight={"ready": False, "message": "browser-agent 不支持正式发布。"},
    )

    assert response["status"] == "manual_handoff"
    assert response["publish_ready"] is False
    assert response["manual_handoff_ready"] is True
    assert response["manual_handoff_targets"][0]["login_url"] == "https://channels.weixin.qq.com/login.html"
    assert response["created_attempts"] == []
    assert response["publication_executor_preflight"]["ready"] is False
    assert response["plan"]["status"] == "manual_handoff"


def test_job_publication_executor_gate_response_derives_manual_handoff_from_targets_when_root_publish_ready_is_stale_true():
    plan = {
        "publish_ready": True,
        "manual_handoff_ready": False,
        "blocked_reasons": ["以下平台已切换为人工登录/人工发布，不再进入自动一键发布：视频号。"],
        "warnings": [],
        "targets": [],
        "manual_handoff_targets": [
            {
                "platform": "wechat-channels",
                "status": "manual_handoff",
                "login_url": "https://channels.weixin.qq.com/login.html",
            }
        ],
    }

    response = jobs_api._build_job_publication_executor_gate_response(
        plan,
        publication_executor_preflight={"ready": False, "message": "browser-agent 不支持正式发布。"},
    )

    assert response["status"] == "manual_handoff"
    assert response["publish_ready"] is False
    assert response["manual_handoff_ready"] is True
    assert response["manual_handoff_targets"][0]["login_url"] == "https://channels.weixin.qq.com/login.html"
    assert response["created_attempts"] == []


def test_job_publication_executor_gate_response_preserves_manual_handoff_status():
    plan = {
        "status": "manual_handoff",
        "publish_ready": False,
        "manual_handoff_ready": True,
        "blocked_reasons": ["以下平台已切换为人工登录/人工发布，不再进入自动一键发布：视频号：当前平台仅支持人工登录后继续发布。"],
        "warnings": ["视频号 已切换为人工接管平台：当前平台仅支持人工登录后继续发布。 登录入口：https://channels.weixin.qq.com/login.html"],
        "targets": [],
        "manual_handoff_targets": [
            {
                "platform": "wechat-channels",
                "status": "manual_handoff",
                "login_url": "https://channels.weixin.qq.com/login.html",
            }
        ],
    }

    response = jobs_api._build_job_publication_executor_gate_response(
        plan,
        publication_executor_preflight={"ready": False, "message": "browser-agent 不支持正式发布。"},
    )

    assert response["status"] == "manual_handoff"
    assert response["publish_ready"] is False
    assert response["manual_handoff_ready"] is True
    assert response["manual_handoff_targets"][0]["login_url"] == "https://channels.weixin.qq.com/login.html"
    assert response["created_attempts"] == []
    assert response["publication_executor_preflight"]["ready"] is False


@pytest.mark.asyncio
async def test_submit_publication_attempts_rejects_blocked_plan_even_when_root_publish_ready_is_stale_true():
    plan = {
        "status": "blocked",
        "publish_ready": True,
        "manual_handoff_ready": False,
        "blocked_reasons": ["缺少 live_publish_preflight"],
        "targets": [
            {
                "platform": "douyin",
                "title": "MAXACE 美杜莎4 顶配次顶配开箱",
            }
        ],
        "manual_handoff_targets": [],
    }

    result = await publication.submit_publication_attempts(None, plan)

    assert publication.publication_plan_is_publishable(plan) is False
    assert result["created_attempts"] == []


def test_generation_task_terminal_patch_preserves_manual_handoff_status():
    patch = _derive_generation_task_terminal_patch(
        {
            "publish_ready": False,
            "blocking_reasons": [],
            "material_contract": {
                "status": "manual_handoff",
                "manual_handoff_platforms": [
                    {
                        "platform": "wechat-channels",
                        "label": "视频号",
                        "login_url": "https://channels.weixin.qq.com/login.html",
                    }
                ],
            },
        }
    )

    assert patch["status"] == "manual_handoff"
    assert patch["stage"] == "manual_handoff"
    assert patch["error"] is None
    assert "人工登录后继续发布" in patch["message"]
    assert "视频号" in patch["message"]


def test_generation_task_terminal_patch_prefers_material_contract_passed_over_stale_root_publish_ready_false():
    patch = _derive_generation_task_terminal_patch(
        {
            "publish_ready": False,
            "blocking_reasons": [],
            "material_contract": {
                "status": "passed",
                "one_click_publish_ready": True,
            },
        }
    )

    assert patch["status"] == "completed"
    assert patch["stage"] == "completed"
    assert patch["error"] is None


def test_generation_task_terminal_patch_prefers_material_contract_failed_over_stale_root_publish_ready_true():
    patch = _derive_generation_task_terminal_patch(
        {
            "publish_ready": True,
            "blocking_reasons": ["小红书：发布前置门禁未通过"],
            "material_contract": {
                "status": "failed",
                "one_click_publish_ready": False,
                "blocking_reasons": ["小红书：发布前置门禁未通过"],
            },
        }
    )

    assert patch["status"] == "blocked"
    assert patch["stage"] == "blocked"
    assert patch["error"] == "小红书：发布前置门禁未通过"


def test_generation_task_terminal_patch_treats_material_generation_success_as_completed_even_when_publish_contract_blocked():
    patch = _derive_generation_task_terminal_patch(
        {
            "publish_ready": False,
            "blocking_reasons": ["B站：缺少合集决策（需指定 collection_name 或显式声明跳过合集）"],
            "material_generation_contract": {
                "status": "passed",
                "generation_ready": True,
            },
            "material_contract": {
                "status": "failed",
                "one_click_publish_ready": False,
                "blocking_reasons": ["B站：缺少合集决策（需指定 collection_name 或显式声明跳过合集）"],
            },
        }
    )

    assert patch["status"] == "completed"
    assert patch["stage"] == "completed"
    assert patch["error"] is None
    assert "一键发布仍有阻断项" in patch["message"]


def test_generation_task_terminal_patch_prefers_material_contract_failed_status_over_stale_one_click_publish_ready_true():
    patch = _derive_generation_task_terminal_patch(
        {
            "publish_ready": True,
            "blocking_reasons": ["小红书：发布前置门禁未通过"],
            "material_contract": {
                "status": "failed",
                "one_click_publish_ready": True,
                "blocking_reasons": ["小红书：发布前置门禁未通过"],
            },
        }
    )

    assert patch["status"] == "blocked"
    assert patch["stage"] == "blocked"
    assert patch["error"] == "小红书：发布前置门禁未通过"


def test_generation_task_terminal_patch_derives_failed_from_platform_statuses_when_root_status_missing():
    patch = _derive_generation_task_terminal_patch(
        {
            "publish_ready": True,
            "blocking_reasons": ["小红书：发布前置门禁未通过"],
            "material_contract": {
                "one_click_publish_ready": True,
                "blocking_reasons": ["小红书：发布前置门禁未通过"],
                "platforms": {
                    "xiaohongshu": {
                        "status": "failed",
                        "one_click_publish_ready": True,
                    }
                },
            },
        }
    )

    assert patch["status"] == "blocked"
    assert patch["stage"] == "blocked"
    assert patch["error"] == "小红书：发布前置门禁未通过"


def test_generation_task_terminal_patch_derives_failed_from_blocking_reasons_when_root_status_missing():
    patch = _derive_generation_task_terminal_patch(
        {
            "publish_ready": True,
            "blocking_reasons": ["小红书：发布前置门禁未通过"],
            "material_contract": {
                "one_click_publish_ready": True,
                "blocking_reasons": ["小红书：发布前置门禁未通过"],
            },
        }
    )

    assert patch["status"] == "blocked"
    assert patch["stage"] == "blocked"
    assert patch["error"] == "小红书：发布前置门禁未通过"


def test_generation_task_terminal_patch_uses_contract_blocking_reasons_when_root_reasons_missing():
    patch = _derive_generation_task_terminal_patch(
        {
            "publish_ready": True,
            "blocking_reasons": [],
            "material_contract": {
                "one_click_publish_ready": True,
                "blocking_reasons": ["小红书：发布前置门禁未通过"],
            },
        }
    )

    assert patch["status"] == "blocked"
    assert patch["stage"] == "blocked"
    assert patch["error"] == "小红书：发布前置门禁未通过"


def test_generation_task_terminal_patch_derives_manual_handoff_from_manual_handoff_targets_when_root_status_missing():
    patch = _derive_generation_task_terminal_patch(
        {
            "publish_ready": True,
            "manual_handoff_ready": False,
            "manual_handoff_targets": [],
            "material_contract": {
                "one_click_publish_ready": True,
                "manual_handoff_platforms": [
                    {
                        "platform": "wechat-channels",
                        "label": "视频号",
                        "login_url": "https://channels.weixin.qq.com/login.html",
                    }
                ],
            },
        }
    )

    assert patch["status"] == "manual_handoff"
    assert patch["stage"] == "manual_handoff"
    assert patch["error"] is None


def test_generation_task_terminal_patch_prefers_manual_handoff_contract_over_stale_root_blocking_reasons_when_one_click_ready():
    patch = _derive_generation_task_terminal_patch(
        {
            "publish_ready": True,
            "blocking_reasons": ["视频号：当前平台仅支持人工登录后继续发布。"],
            "manual_handoff_ready": False,
            "manual_handoff_targets": [],
            "material_contract": {
                "one_click_publish_ready": True,
                "blocking_reasons": ["视频号：当前平台仅支持人工登录后继续发布。"],
                "manual_handoff_platforms": [
                    {
                        "platform": "wechat-channels",
                        "label": "视频号",
                        "login_url": "https://channels.weixin.qq.com/login.html",
                    }
                ],
            },
        }
    )

    assert patch["status"] == "manual_handoff"
    assert patch["stage"] == "manual_handoff"
    assert patch["error"] is None


def test_generation_task_terminal_patch_prefers_manual_handoff_over_stale_root_publish_ready_true():
    patch = _derive_generation_task_terminal_patch(
        {
            "publish_ready": True,
            "manual_handoff_ready": False,
            "manual_handoff_targets": [
                {
                    "platform": "wechat-channels",
                    "label": "视频号",
                    "login_url": "https://channels.weixin.qq.com/login.html",
                }
            ],
            "material_contract": {
                "status": "manual_handoff",
                "one_click_publish_ready": False,
                "manual_handoff_platforms": [
                    {
                        "platform": "wechat-channels",
                        "label": "视频号",
                        "login_url": "https://channels.weixin.qq.com/login.html",
                    }
                ],
            },
        }
    )

    assert patch["status"] == "manual_handoff"
    assert patch["stage"] == "manual_handoff"
    assert patch["error"] is None


def test_generation_task_terminal_patch_blocks_legacy_root_blocking_reasons_even_when_root_publish_ready_is_stale_true():
    patch = _derive_generation_task_terminal_patch(
        {
            "status": "completed",
            "publish_ready": True,
            "blocking_reasons": ["缺少 live_publish_preflight"],
            "manual_handoff_ready": False,
            "manual_handoff_targets": [],
        }
    )

    assert patch["status"] == "blocked"
    assert patch["stage"] == "blocked"
    assert patch["error"] == "缺少 live_publish_preflight"


def test_generation_task_terminal_patch_derives_legacy_manual_handoff_from_targets_even_when_root_publish_ready_is_stale_true():
    patch = _derive_generation_task_terminal_patch(
        {
            "status": "completed",
            "publish_ready": True,
            "blocking_reasons": [],
            "manual_handoff_ready": False,
            "manual_handoff_targets": [
                {
                    "platform": "wechat-channels",
                    "label": "视频号",
                    "login_url": "https://channels.weixin.qq.com/login.html",
                }
            ],
        }
    )

    assert patch["status"] == "manual_handoff"
    assert patch["stage"] == "manual_handoff"
    assert patch["error"] is None
    assert "视频号" in patch["message"]


def test_intelligent_copy_result_schema_preserves_manual_handoff_fields():
    payload = IntelligentCopyResultOut.model_validate(
        {
            "folder_path": "E:/materials/maxace",
            "material_dir": "E:/materials/maxace/smart-copy",
            "markdown_path": "E:/materials/maxace/smart-copy/platform-packaging.md",
            "json_path": "E:/materials/maxace/smart-copy/smart-copy.json",
            "status": "manual_handoff",
            "copy_style": "attention_grabbing",
            "inspection": {
                "folder_path": "E:/materials/maxace",
                "material_dir": "E:/materials/maxace/smart-copy",
                "extra_video_files": [],
                "extra_subtitle_files": [],
                "extra_cover_files": [],
                "warnings": [],
            },
            "highlights": {},
            "content_profile_summary": {},
            "platforms": [],
            "publish_ready": False,
            "manual_handoff_ready": True,
            "manual_handoff_targets": [
                {
                    "platform": "wechat-channels",
                    "label": "视频号",
                    "status": "manual_handoff",
                    "login_url": "https://channels.weixin.qq.com/login.html",
                }
            ],
            "blocking_reasons": [],
            "warnings": [],
        }
    ).model_dump()

    assert payload["status"] == "manual_handoff"
    assert payload["manual_handoff_ready"] is True
    assert payload["manual_handoff_targets"][0]["platform"] == "wechat-channels"
    assert payload["manual_handoff_targets"][0]["login_url"] == "https://channels.weixin.qq.com/login.html"


def test_intelligent_copy_result_schema_preserves_material_contract():
    payload = IntelligentCopyResultOut.model_validate(
        {
            "folder_path": "E:/materials/maxace",
            "material_dir": "E:/materials/maxace/smart-copy",
            "markdown_path": "E:/materials/maxace/smart-copy/platform-packaging.md",
            "json_path": "E:/materials/maxace/smart-copy/smart-copy.json",
            "status": "blocked",
            "copy_style": "attention_grabbing",
            "inspection": {
                "folder_path": "E:/materials/maxace",
                "material_dir": "E:/materials/maxace/smart-copy",
                "extra_video_files": [],
                "extra_subtitle_files": [],
                "extra_cover_files": [],
                "warnings": [],
            },
            "highlights": {},
            "content_profile_summary": {},
            "platforms": [],
            "material_contract": {
                "status": "failed",
                "one_click_publish_ready": False,
                "blocking_reasons": ["缺少封面"],
            },
            "publish_ready": True,
            "manual_handoff_ready": False,
            "blocking_reasons": [],
            "warnings": [],
        }
    ).model_dump()

    assert payload["material_contract"]["status"] == "failed"
    assert payload["material_contract"]["one_click_publish_ready"] is False
    assert payload["material_contract"]["blocking_reasons"] == ["缺少封面"]


def test_intelligent_copy_generate_task_schema_preserves_nested_manual_handoff_result():
    payload = IntelligentCopyGenerateTaskOut.model_validate(
        {
            "id": "task-manual-handoff",
            "folder_path": "E:/materials/maxace",
            "copy_style": "attention_grabbing",
            "use_existing_cover": False,
            "status": "manual_handoff",
            "progress": 100,
            "stage": "manual_handoff",
            "message": "物料生成完成，部分平台需人工登录后继续发布。",
            "created_at": "2026-06-01T12:00:00Z",
            "updated_at": "2026-06-01T12:05:00Z",
            "inspection": {
                "folder_path": "E:/materials/maxace",
                "material_dir": "E:/materials/maxace/smart-copy",
                "extra_video_files": [],
                "extra_subtitle_files": [],
                "extra_cover_files": [],
                "warnings": [],
            },
            "result": {
                "folder_path": "E:/materials/maxace",
                "material_dir": "E:/materials/maxace/smart-copy",
                "markdown_path": "E:/materials/maxace/smart-copy/platform-packaging.md",
                "json_path": "E:/materials/maxace/smart-copy/smart-copy.json",
                "status": "manual_handoff",
                "copy_style": "attention_grabbing",
                "inspection": {
                    "folder_path": "E:/materials/maxace",
                    "material_dir": "E:/materials/maxace/smart-copy",
                    "extra_video_files": [],
                    "extra_subtitle_files": [],
                    "extra_cover_files": [],
                    "warnings": [],
                },
                "highlights": {},
                "content_profile_summary": {},
                "platforms": [],
                "publish_ready": False,
                "manual_handoff_ready": True,
                "manual_handoff_targets": [
                    {
                        "platform": "wechat-channels",
                        "label": "视频号",
                        "status": "manual_handoff",
                        "login_url": "https://channels.weixin.qq.com/login.html",
                    }
                ],
                "blocking_reasons": [],
                "warnings": [],
            },
        }
    ).model_dump()

    assert payload["status"] == "manual_handoff"
    assert payload["result"]["status"] == "manual_handoff"
    assert payload["result"]["manual_handoff_ready"] is True
    assert payload["result"]["manual_handoff_targets"][0]["platform"] == "wechat-channels"


def test_intelligent_copy_platform_material_schema_preserves_publication_metadata_fields():
    payload = IntelligentCopyResultOut.model_validate(
        {
            "folder_path": "E:/materials/maxace",
            "material_dir": "E:/materials/maxace/smart-copy",
            "markdown_path": "E:/materials/maxace/smart-copy/platform-packaging.md",
            "json_path": "E:/materials/maxace/smart-copy/smart-copy.json",
            "status": "completed",
            "copy_style": "attention_grabbing",
            "inspection": {
                "folder_path": "E:/materials/maxace",
                "material_dir": "E:/materials/maxace/smart-copy",
                "extra_video_files": [],
                "extra_subtitle_files": [],
                "extra_cover_files": [],
                "warnings": [],
            },
            "highlights": {},
            "content_profile_summary": {},
            "platforms": [
                {
                    "key": "xiaohongshu",
                    "label": "小红书",
                    "has_title": True,
                    "title_label": "标题",
                    "body_label": "正文",
                    "tag_label": "话题",
                    "constraints": {
                        "title_limit": 20,
                        "body_limit": 1000,
                        "tag_limit": 8,
                        "tag_style": "hashtags_space",
                        "cover_size": {"width": 1080, "height": 1440},
                        "rule_note": "偏分享笔记语气",
                    },
                    "titles": ["标题"],
                    "title_goals": [],
                    "primary_title": "标题",
                    "title_copy_all": "标题",
                    "body": "正文",
                    "tags": ["开箱"],
                    "tags_copy": "#开箱",
                    "full_copy": "正文\n#开箱",
                    "cover_path": "E:/covers/xhs.jpg",
                    "declaration": "原创声明",
                    "collection_name": "EDC潮玩桌搭",
                    "collection": {"name": "EDC潮玩桌搭"},
                    "visibility_or_publish_mode": "scheduled",
                    "scheduled_publish_at": "2026-06-01T21:00",
                    "copy_material": {"source": "intelligent_copy_material_self_heal"},
                    "live_publish_preflight": {"status": "ready", "required_surfaces": ["topics", "collection"]},
                    "platform_specific_overrides": {"selected_declarations": ["原创声明"]},
                    "publish_ready": True,
                    "blocking_reasons": [],
                }
            ],
            "publish_ready": True,
            "blocking_reasons": [],
            "warnings": [],
        }
    ).model_dump()

    material = payload["platforms"][0]
    assert material["cover_path"] == "E:/covers/xhs.jpg"
    assert material["declaration"] == "原创声明"
    assert material["collection_name"] == "EDC潮玩桌搭"
    assert material["collection"]["name"] == "EDC潮玩桌搭"
    assert material["visibility_or_publish_mode"] == "scheduled"
    assert material["scheduled_publish_at"] == "2026-06-01T21:00"
    assert material["copy_material"]["source"] == "intelligent_copy_material_self_heal"
    assert material["live_publish_preflight"]["status"] == "ready"
    assert material["platform_specific_overrides"]["selected_declarations"] == ["原创声明"]


def test_intelligent_copy_platform_material_schema_preserves_manual_handoff_platform_fields():
    payload = IntelligentCopyResultOut.model_validate(
        {
            "folder_path": "E:/materials/maxace",
            "material_dir": "E:/materials/maxace/smart-copy",
            "markdown_path": "E:/materials/maxace/smart-copy/platform-packaging.md",
            "json_path": "E:/materials/maxace/smart-copy/smart-copy.json",
            "status": "manual_handoff",
            "copy_style": "attention_grabbing",
            "inspection": {
                "folder_path": "E:/materials/maxace",
                "material_dir": "E:/materials/maxace/smart-copy",
                "extra_video_files": [],
                "extra_subtitle_files": [],
                "extra_cover_files": [],
                "warnings": [],
            },
            "highlights": {},
            "content_profile_summary": {},
            "platforms": [
                {
                    "key": "wechat-channels",
                    "label": "视频号",
                    "has_title": False,
                    "title_label": "标题",
                    "body_label": "简介",
                    "tag_label": "标签",
                    "constraints": {
                        "title_limit": 20,
                        "body_limit": 1000,
                        "tag_limit": 6,
                        "tag_style": "hashtags_space",
                        "cover_size": {"width": 1080, "height": 1920},
                        "rule_note": "偏稳妥可信",
                    },
                    "titles": [],
                    "primary_title": "",
                    "title_copy_all": "",
                    "body": "正文",
                    "tags": [],
                    "tags_copy": "",
                    "full_copy": "正文",
                    "manual_handoff_only": True,
                    "manual_publish_entry_url": "https://channels.weixin.qq.com/login.html",
                    "publish_ready": False,
                    "blocking_reasons": ["当前平台仅支持人工登录后继续发布。"],
                }
            ],
            "publish_ready": False,
            "manual_handoff_ready": True,
            "manual_handoff_targets": [
                {
                    "platform": "wechat-channels",
                    "label": "视频号",
                    "status": "manual_handoff",
                    "login_url": "https://channels.weixin.qq.com/login.html",
                }
            ],
            "blocking_reasons": [],
            "warnings": [],
        }
    ).model_dump()

    material = payload["platforms"][0]
    assert material["manual_handoff_only"] is True
    assert material["manual_publish_entry_url"] == "https://channels.weixin.qq.com/login.html"


def test_intelligent_copy_platform_material_schema_defaults_publish_ready_to_false_when_missing():
    payload = IntelligentCopyResultOut.model_validate(
        {
            "folder_path": "E:/materials/maxace",
            "material_dir": "E:/materials/maxace/smart-copy",
            "markdown_path": "E:/materials/maxace/smart-copy/platform-packaging.md",
            "json_path": "E:/materials/maxace/smart-copy/smart-copy.json",
            "status": "completed",
            "copy_style": "attention_grabbing",
            "inspection": {
                "folder_path": "E:/materials/maxace",
                "material_dir": "E:/materials/maxace/smart-copy",
                "extra_video_files": [],
                "extra_subtitle_files": [],
                "extra_cover_files": [],
                "warnings": [],
            },
            "highlights": {},
            "content_profile_summary": {},
            "platforms": [
                {
                    "key": "youtube",
                    "label": "YouTube",
                    "has_title": True,
                    "title_label": "标题",
                    "body_label": "描述",
                    "tag_label": "标签",
                    "constraints": {
                        "title_limit": 100,
                        "body_limit": 5000,
                        "tag_limit": 15,
                        "tag_style": "keywords_comma",
                        "cover_size": {"width": 1280, "height": 720},
                        "rule_note": "测试",
                    },
                    "titles": ["标题"],
                    "title_goals": [],
                    "primary_title": "标题",
                    "title_copy_all": "标题",
                    "body": "正文",
                    "tags": [],
                    "tags_copy": "",
                    "full_copy": "正文",
                    "live_publish_preflight": {"status": "ready"},
                    "blocking_reasons": [],
                }
            ],
            "publish_ready": False,
            "blocking_reasons": [],
            "warnings": [],
        }
    ).model_dump()

    assert payload["platforms"][0]["publish_ready"] is False


@pytest.mark.asyncio
async def test_publication_plan_fails_closed_when_external_media_cannot_materialize(monkeypatch):
    monkeypatch.setattr(
        publication,
        "_materialize_publication_media_file",
        lambda raw_path: None,
    )
    plan = publication.build_publication_plan(
        job=SimpleNamespace(id="job-1"),
        render_output=SimpleNamespace(output_path=r"\\server\share\video.mp4"),
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
            "creator_profile": {
                "publishing": {
                    "platform_credentials": [
                        {
                            "platform": "douyin",
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
                "scheduled_publish_at": "2026-04-26T18:30",
                "collection_name": "新品体验",
                "category": "数码",
                "visibility_or_publish_mode": "scheduled",
            }
        },
        existing_attempts=[],
    )

    assert plan["publish_ready"] is False
    assert "缺少本地成片文件，browser-agent 不能上传 remote-only media。" in plan["blocked_reasons"]


def test_materialize_publication_media_file_copies_into_runtime_root(tmp_path, monkeypatch):
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    runtime_root = tmp_path / "runtime-publication-media"
    monkeypatch.setattr(publication, "_publication_media_runtime_root", lambda: runtime_root)

    materialized = publication._materialize_publication_media_file(str(source_path))

    assert materialized is not None
    assert materialized.exists()
    assert materialized.is_file()
    assert materialized.read_bytes() == b"video"
    assert runtime_root in materialized.parents


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


@pytest.mark.asyncio
async def test_publication_worker_requeues_when_browser_agent_task_is_missing(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    fake_client = _FakeBrowserAgentClientTaskMissing()
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
            )
            await publication.submit_publication_attempts(session, plan)
            await publication.run_publication_worker_once(
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

    assert second_tick["reconciled"][0]["status"] == "queued"
    assert "browser-agent 运行态里找不到该 task_id" in second_tick["reconciled"][0]["error"]
    assert attempts[0]["status"] == "queued"
    assert attempts[0]["run_status"] == "awaiting_browser_agent"
    assert attempts[0]["provider_task_id"] is None
    assert attempts[0]["error_code"] == "browser_agent_task_missing"


@pytest.mark.asyncio
async def test_publication_worker_targeted_run_reconciles_claimed_attempts_in_same_tick(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    fake_client = _FakeBrowserAgentClientProcessing()
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
            )
            await publication.submit_publication_attempts(session, plan)
            worker_tick = await publication.run_publication_worker_once(
                session,
                browser_agent_base_url="http://browser-agent.local",
                auth_token="secret",
                worker_id="worker-targeted",
                http_client=fake_client,
                target_content_ids=[str(job.id)],
            )
            attempts = await publication.list_publication_attempts(session, job_id=str(job.id))
    finally:
        await engine.dispose()

    assert worker_tick["claimed"] == 1
    assert worker_tick["reconciled"][0]["status"] == "processing"
    assert attempts[0]["status"] == "processing"
    assert attempts[0]["provider_status"] == "processing"


@pytest.mark.asyncio
async def test_submit_publication_attempts_requeues_failed_attempt_instead_of_inserting_duplicate(tmp_path):
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
            )
            first = await publication.submit_publication_attempts(session, plan)
            await session.flush()
            attempt_id = first["created_attempts"][0]["id"]
            attempt = await session.get(PublicationAttempt, attempt_id)
            assert attempt is not None
            attempt.status = "failed"
            attempt.run_status = "failed"
            attempt.error_message = "old failure"
            await session.flush()

            second = await publication.submit_publication_attempts(session, plan)
            await session.commit()

            attempts = await publication.list_publication_attempts(session, job_id=str(job.id))
    finally:
        await engine.dispose()

    assert len(first["created_attempts"]) == 1
    assert len(second["created_attempts"]) == 1
    assert second["created_attempts"][0]["id"] == attempt_id
    assert second["created_attempts"][0]["status"] == "queued"
    assert second["created_attempts"][0]["run_status"] == "awaiting_browser_agent"
    assert second["created_attempts"][0]["attempt_number"] == 2
    assert "已重新排队" in (second["created_attempts"][0]["operator_summary"] or "")
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_submit_publication_attempts_requeues_needs_human_attempt_instead_of_treating_it_as_active(tmp_path):
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
            )
            first = await publication.submit_publication_attempts(session, plan)
            await session.flush()
            attempt_id = first["created_attempts"][0]["id"]
            attempt = await session.get(PublicationAttempt, attempt_id)
            assert attempt is not None
            attempt.status = "needs_human"
            attempt.run_status = "needs_human"
            attempt.error_message = "open publish page and retry"
            await session.flush()

            second = await publication.submit_publication_attempts(session, plan)
            await session.commit()

            attempts = await publication.list_publication_attempts(session, job_id=str(job.id))
    finally:
        await engine.dispose()

    assert len(first["created_attempts"]) == 1
    assert len(second["created_attempts"]) == 1
    assert second["created_attempts"][0]["id"] == attempt_id
    assert second["created_attempts"][0]["status"] == "queued"
    assert second["created_attempts"][0]["run_status"] == "awaiting_browser_agent"
    assert second["created_attempts"][0]["attempt_number"] == 2
    assert "已重新排队" in (second["created_attempts"][0]["operator_summary"] or "")
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_submit_publication_attempts_requeues_unbound_receipt_attempt_in_safe_verification_mode(tmp_path):
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
            plan = publication.build_publication_plan(
                job=job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging={
                    "platforms": {
                        "douyin": {
                            "titles": ["����"],
                            "description": "���",
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
                                    "account_label": "����",
                                    "credential_ref": "chrome-profile:main",
                                    "status": "logged_in",
                                    "enabled": True,
                                    "adapter": "browser_agent",
                                }
                            ]
                        }
                    },
                },
            )
            first = await publication.submit_publication_attempts(session, plan)
            await session.flush()
            attempt_id = first["created_attempts"][0]["id"]
            attempt = await session.get(PublicationAttempt, attempt_id)
            assert attempt is not None
            attempt.status = "needs_human"
            attempt.run_status = "needs_human"
            attempt.error_code = "publication_audit_unverified"
            attempt.response_payload = {
                "result": {
                    "material_integrity": {
                        "platform": "douyin",
                        "verified": False,
                        "failures": ["receipt"],
                        "platform_extras": {
                            "receipt_like": True,
                            "post_publish_surface": "douyin_content_manage_receipt",
                            "receipt_target_bound": False,
                            "receipt_binding_source": "unbound_manage_receipt",
                        },
                    },
                    "publication_audit": {
                        "required_unverified": ["receipt"],
                        "required_reupload": [],
                    },
                },
                "error": {
                    "code": "publication_audit_unverified",
                    "message": "receipt not bound",
                },
            }
            await session.flush()

            second = await publication.submit_publication_attempts(session, plan)
            await session.commit()

            attempts = await publication.list_publication_attempts(session, job_id=str(job.id))
    finally:
        await engine.dispose()

    assert len(second["created_attempts"]) == 1
    created = second["created_attempts"][0]
    overrides = created["request_payload"]["platform_specific_overrides"]
    assert created["id"] == attempt_id
    assert created["status"] == "queued"
    assert created["run_status"] == "retry_scheduled"
    assert overrides["verification_only_current_page"] is True
    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["wait_for_publish_confirmation"] is True
    assert overrides["recovery_mode"] == "receipt_rebind"
    assert publication._is_publication_recovery_target({"platform_specific_overrides": overrides}) is True
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_submit_publication_attempts_preserves_explicit_receipt_rebind_overrides_over_platform_recovery_history(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
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
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            prior_job = Job(source_path="source-prior.mp4", source_name="source-prior.mp4", status="done")
            session.add(prior_job)
            await session.flush()
            prior_plan = publication.build_publication_plan(
                job=prior_job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging={
                    "platforms": {
                        "douyin": {
                            "titles": ["old-title"],
                            "description": "old-body",
                            "tags": ["tag"],
                        }
                    }
                },
                creator_profile=creator_profile,
            )
            prior_submit = await publication.submit_publication_attempts(session, prior_plan)
            await session.flush()
            prior_attempt_id = prior_submit["created_attempts"][0]["id"]
            prior_attempt = await session.get(PublicationAttempt, prior_attempt_id)
            assert prior_attempt is not None
            prior_attempt.status = "needs_human"
            prior_attempt.run_status = "needs_human"
            prior_attempt.error_code = "publication_audit_unverified"
            prior_attempt.request_payload = {
                **dict(prior_attempt.request_payload or {}),
                "platform_specific_overrides": {
                    "recovery_mode": "draft_reset",
                    "clear_draft_context": True,
                    "force_publish_page_refresh": True,
                },
            }
            prior_attempt.response_payload = {
                "result": {
                    "material_integrity": {
                        "platform": "douyin",
                        "verified": False,
                        "failures": ["title"],
                    },
                    "publication_audit": {
                        "required_unverified": ["title"],
                        "required_reupload": [],
                    },
                },
                "error": {
                    "code": "publication_audit_unverified",
                    "message": "title mismatch",
                },
            }
            await session.flush()

            current_job = Job(source_path="source-current.mp4", source_name="source-current.mp4", status="done")
            session.add(current_job)
            await session.flush()
            current_plan = publication.build_publication_plan(
                job=current_job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging={
                    "platforms": {
                        "douyin": {
                            "titles": ["new-title"],
                            "description": "new-body",
                            "tags": ["tag"],
                            "platform_specific_overrides": {
                                "recovery_mode": "receipt_rebind",
                                "verification_only_current_page": True,
                                "clear_draft_context": False,
                                "force_publish_page_refresh": True,
                                "wait_for_publish_confirmation": True,
                            },
                        }
                    }
                },
                creator_profile=creator_profile,
            )

            current_submit = await publication.submit_publication_attempts(session, current_plan)
            await session.commit()
    finally:
        await engine.dispose()

    assert len(current_submit["created_attempts"]) == 1
    created = current_submit["created_attempts"][0]
    overrides = created["request_payload"]["platform_specific_overrides"]
    assert overrides["recovery_mode"] == "receipt_rebind"
    assert overrides["verification_only_current_page"] is True
    assert overrides["clear_draft_context"] is False
    assert overrides["force_publish_page_refresh"] is True
    assert overrides["wait_for_publish_confirmation"] is True


@pytest.mark.asyncio
async def test_publication_worker_submits_requeued_unbound_receipt_attempt_in_safe_verification_mode(tmp_path):
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
                            "titles": ["����"],
                            "description": "���",
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
                                    "account_label": "����",
                                    "credential_ref": "chrome-profile:main",
                                    "status": "logged_in",
                                    "enabled": True,
                                    "adapter": "browser_agent",
                                }
                            ]
                        }
                    },
                },
            )
            first = await publication.submit_publication_attempts(session, plan)
            await session.flush()
            attempt_id = first["created_attempts"][0]["id"]
            attempt = await session.get(PublicationAttempt, attempt_id)
            assert attempt is not None
            attempt.status = "needs_human"
            attempt.run_status = "needs_human"
            attempt.error_code = "publication_audit_unverified"
            attempt.response_payload = {
                "result": {
                    "material_integrity": {
                        "platform": "douyin",
                        "verified": False,
                        "failures": ["receipt"],
                        "platform_extras": {
                            "receipt_like": True,
                            "post_publish_surface": "douyin_content_manage_receipt",
                            "receipt_target_bound": False,
                            "receipt_binding_source": "unbound_manage_receipt",
                        },
                    },
                    "publication_audit": {
                        "required_unverified": ["receipt"],
                        "required_reupload": [],
                    },
                },
                "error": {
                    "code": "publication_audit_unverified",
                    "message": "receipt not bound",
                },
            }
            await session.flush()

            second = await publication.submit_publication_attempts(session, plan)
            worker_tick = await publication.run_publication_worker_once(
                session,
                browser_agent_base_url="http://browser-agent.local",
                auth_token="secret",
                worker_id="worker-1",
                http_client=fake_client,
            )
            attempts = await publication.list_publication_attempts(session, job_id=str(job.id))
    finally:
        await engine.dispose()

    assert len(second["created_attempts"]) == 1
    assert worker_tick["claimed"] == 1
    assert len(fake_client.posts) == 1
    posted_overrides = fake_client.posts[0]["json"]["content"]["platform_specific_overrides"]
    assert posted_overrides["verification_only_current_page"] is True
    assert posted_overrides["clear_draft_context"] is False
    assert posted_overrides["force_publish_page_refresh"] is True
    assert posted_overrides["wait_for_publish_confirmation"] is True
    assert "verify_media_upload" not in posted_overrides
    assert posted_overrides["recovery_mode"] == "receipt_rebind"
    assert attempts[0]["status"] == "processing"
    assert attempts[0]["provider_task_id"] == attempt_id


@pytest.mark.asyncio
async def test_submit_publication_attempts_does_not_spawn_parallel_active_recovery_attempt(tmp_path):
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
            )
            first = await publication.submit_publication_attempts(session, plan)
            await session.flush()
            attempt_id = first["created_attempts"][0]["id"]
            attempt = await session.get(PublicationAttempt, attempt_id)
            assert attempt is not None
            attempt.status = "processing"
            attempt.run_status = "processing"
            attempt.request_payload = {
                **(attempt.request_payload or {}),
                "platform_specific_overrides": {
                    "clear_draft_context": True,
                    "force_publish_page_refresh": True,
                    "recovery_mode": "auto_recover",
                },
            }
            await session.flush()

            recovery_plan = {
                **plan,
                "targets": [
                    {
                        **plan["targets"][0],
                        "platform_specific_overrides": {
                            "clear_draft_context": True,
                            "force_publish_page_refresh": True,
                            "recovery_mode": "auto_recover",
                        },
                    }
                ],
            }
            second = await publication.submit_publication_attempts(session, recovery_plan)
            await session.commit()

            attempts = await publication.list_publication_attempts(session, job_id=str(job.id))
    finally:
        await engine.dispose()

    assert len(first["created_attempts"]) == 1
    assert len(second["created_attempts"]) == 0
    assert second["skipped_targets"] == [
        {
            "platform": "douyin",
            "reason": "active_attempt_exists",
            "attempt_id": attempt_id,
            "status": "processing",
            "run_status": "processing",
            "error_code": "",
        }
    ]
    assert len(attempts) == 1
    assert attempts[0]["id"] == attempt_id
    assert attempts[0]["status"] == "processing"


@pytest.mark.asyncio
async def test_submit_publication_attempts_reuses_active_attempt_for_safe_receipt_rebind(tmp_path):
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
            plan = publication.build_publication_plan(
                job=job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging={
                    "platforms": {
                        "toutiao": {
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
                                    "platform": "toutiao",
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
            )
            first = await publication.submit_publication_attempts(session, plan)
            await session.flush()
            attempt_id = first["created_attempts"][0]["id"]
            attempt = await session.get(PublicationAttempt, attempt_id)
            assert attempt is not None
            attempt.status = "processing"
            attempt.run_status = "processing"
            attempt.request_payload = {
                **(attempt.request_payload or {}),
                "platform_specific_overrides": {
                    "recovery_mode": "receipt_rebind",
                    "clear_draft_context": False,
                    "force_publish_page_refresh": True,
                    "verification_only_current_page": True,
                    "verify_media_upload": True,
                    "wait_for_publish_confirmation": True,
                },
            }
            await session.flush()

            recovery_plan = {
                **plan,
                "targets": [
                    {
                        **plan["targets"][0],
                        "platform_specific_overrides": {
                            "recovery_mode": "receipt_rebind",
                            "clear_draft_context": False,
                            "force_publish_page_refresh": True,
                            "verification_only_current_page": True,
                            "verify_media_upload": True,
                            "wait_for_publish_confirmation": True,
                        },
                    }
                ],
            }
            second = await publication.submit_publication_attempts(session, recovery_plan)
            await session.flush()
            rebound_attempt = await session.get(PublicationAttempt, attempt_id)
            await session.commit()
    finally:
        await engine.dispose()

    assert len(second["created_attempts"]) == 1
    assert second["created_attempts"][0]["id"] == attempt_id
    assert second["skipped_targets"] == []
    assert rebound_attempt is not None
    assert rebound_attempt.status == "queued"
    assert rebound_attempt.run_status == "retry_scheduled"


@pytest.mark.asyncio
async def test_submit_publication_attempts_treats_schedule_shift_as_same_live_content(tmp_path):
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
            packaging = {
                "platforms": {
                    "douyin": {
                        "titles": ["标题"],
                        "description": "简介",
                        "tags": ["tag"],
                    }
                }
            }
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
            first_plan = publication.build_publication_plan(
                job=job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging=packaging,
                creator_profile=creator_profile,
                platform_options={
                    "douyin": {
                        "scheduled_publish_at": "2026-04-26T18:30",
                    }
                },
            )
            first = await publication.submit_publication_attempts(session, first_plan)
            await session.flush()

            shifted_plan = publication.build_publication_plan(
                job=job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging=packaging,
                creator_profile=creator_profile,
                platform_options={
                    "douyin": {
                        "scheduled_publish_at": "2026-04-26T19:30",
                    }
                },
            )
            second = await publication.submit_publication_attempts(session, shifted_plan)
            await session.commit()

            attempts = await publication.list_publication_attempts(session, job_id=str(job.id))
    finally:
        await engine.dispose()

    assert len(first["created_attempts"]) == 1
    assert len(second["created_attempts"]) == 0
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_submit_publication_attempts_reuses_stale_retry_queued_attempt_instead_of_blocking_new_submit(tmp_path):
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
            plan = publication.build_publication_plan(
                job=job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging={
                    "platforms": {
                        "xiaohongshu": {
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
                                    "platform": "xiaohongshu",
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
            )
            first = await publication.submit_publication_attempts(session, plan)
            await session.flush()
            attempt_id = first["created_attempts"][0]["id"]
            attempt = await session.get(PublicationAttempt, attempt_id)
            assert attempt is not None
            attempt.status = "queued"
            attempt.run_status = "retry_scheduled"
            attempt.error_code = "xiaohongshu_media_upload_failed"
            attempt.error_message = "upload failed"
            await session.flush()

            second = await publication.submit_publication_attempts(session, plan)
            await session.commit()

            attempts = await publication.list_publication_attempts(session, job_id=str(job.id))
    finally:
        await engine.dispose()

    assert len(first["created_attempts"]) == 1
    assert len(second["created_attempts"]) == 1
    assert second["created_attempts"][0]["id"] == attempt_id
    assert second["skipped_targets"] == []
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_submit_publication_attempts_skips_terminal_success_with_same_logical_signature_despite_dedupe_drift(tmp_path):
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
            plan = publication.build_publication_plan(
                job=job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging={
                    "platforms": {
                        "douyin": {
                            "titles": ["同内容重复防护测试"],
                            "description": "同内容正文",
                            "tags": ["tag-a"],
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
            )
            first = await publication.submit_publication_attempts(session, plan)
            await session.flush()
            attempt_id = first["created_attempts"][0]["id"]
            attempt = await session.get(PublicationAttempt, attempt_id)
            assert attempt is not None
            attempt.status = "published"
            attempt.run_status = "published"
            request_payload = dict(attempt.request_payload or {})
            request_payload.pop("publication_dedupe_signature", None)
            metadata = dict(request_payload.get("metadata") or {})
            metadata["browser_profile_id"] = "browser-profile:chrome:legacy"
            metadata["credential_ref"] = "chrome-profile:legacy"
            metadata["account_label"] = "旧主号"
            request_payload["metadata"] = metadata
            attempt.request_payload = request_payload
            await session.flush()

            second = await publication.submit_publication_attempts(session, plan)
            await session.commit()

            attempts = await publication.list_publication_attempts(session, job_id=str(job.id))
    finally:
        await engine.dispose()

    assert second["created_attempts"] == []
    assert len(attempts) == 1
    assert attempts[0]["status"] == "published"


@pytest.mark.asyncio
async def test_submit_publication_attempts_skips_terminal_success_with_same_logical_signature_despite_creator_profile_drift(
    tmp_path,
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            first_job = Job(source_path="source-a.mp4", source_name="source-a.mp4", status="done")
            session.add(first_job)
            await session.flush()
            first_plan = publication.build_publication_plan(
                job=first_job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging={
                    "platforms": {
                        "douyin": {
                            "titles": ["跨 creator 漂移幂等测试"],
                            "description": "同内容正文",
                            "tags": ["tag-a"],
                        }
                    }
                },
                creator_profile={
                    "id": "creator-legacy",
                    "display_name": "creator",
                    "creator_profile": {
                        "publishing": {
                            "platform_credentials": [
                                {
                                    "platform": "douyin",
                                    "account_label": "旧主号",
                                    "credential_ref": "chrome-profile:legacy",
                                    "status": "logged_in",
                                    "enabled": True,
                                    "adapter": "browser_agent",
                                }
                            ]
                        }
                    },
                },
            )
            first = await publication.submit_publication_attempts(session, first_plan)
            await session.flush()
            first_attempt = await session.get(PublicationAttempt, first["created_attempts"][0]["id"])
            assert first_attempt is not None
            first_attempt.status = "published"
            first_attempt.run_status = "published"
            request_payload = dict(first_attempt.request_payload or {})
            request_payload.pop("publication_dedupe_signature", None)
            metadata = dict(request_payload.get("metadata") or {})
            metadata["browser_profile_id"] = "browser-profile:chrome:legacy-drift"
            metadata["credential_ref"] = "chrome-profile:legacy-drift"
            metadata["account_label"] = "更旧主号"
            request_payload["metadata"] = metadata
            first_attempt.request_payload = request_payload
            await session.flush()

            second_job = Job(source_path="source-b.mp4", source_name="source-b.mp4", status="done")
            session.add(second_job)
            await session.flush()
            second_plan = publication.build_publication_plan(
                job=second_job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging={
                    "platforms": {
                        "douyin": {
                            "titles": ["跨 creator 漂移幂等测试"],
                            "description": "同内容正文",
                            "tags": ["tag-a"],
                        }
                    }
                },
                creator_profile={
                    "id": "creator-current",
                    "display_name": "creator",
                    "creator_profile": {
                        "publishing": {
                            "platform_credentials": [
                                {
                                    "platform": "douyin",
                                    "account_label": "新主号",
                                    "credential_ref": "chrome-profile:current",
                                    "status": "logged_in",
                                    "enabled": True,
                                    "adapter": "browser_agent",
                                }
                            ]
                        }
                    },
                },
            )
            second = await publication.submit_publication_attempts(session, second_plan)
            attempts = await publication.list_publication_attempts(session)
            await session.commit()
    finally:
        await engine.dispose()

    assert len(first["created_attempts"]) == 1
    assert second["created_attempts"] == []
    assert len(attempts) == 1
    assert attempts[0]["status"] == "published"


@pytest.mark.asyncio
async def test_submit_publication_attempts_rebinds_reused_attempt_to_current_job(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            first_job = Job(source_path="source-a.mp4", source_name="source-a.mp4", status="done")
            session.add(first_job)
            await session.flush()
            packaging = {
                "platforms": {
                    "douyin": {
                        "titles": ["复用 attempt 重绑 job 测试"],
                        "description": "同内容正文",
                        "tags": ["tag-a"],
                    }
                }
            }
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
            first_plan = publication.build_publication_plan(
                job=first_job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging=packaging,
                creator_profile=creator_profile,
            )
            first = await publication.submit_publication_attempts(session, first_plan)
            await session.flush()

            attempt_id = first["created_attempts"][0]["id"]
            first_attempt = await session.get(PublicationAttempt, attempt_id)
            assert first_attempt is not None
            first_attempt.status = "needs_human"
            first_attempt.run_status = "needs_human"
            await session.flush()

            second_job = Job(source_path="source-b.mp4", source_name="source-b.mp4", status="done")
            session.add(second_job)
            await session.flush()
            second_plan = publication.build_publication_plan(
                job=second_job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging=packaging,
                creator_profile=creator_profile,
                platform_options={
                    "douyin": {
                        "platform_specific_overrides": {
                            "force_republish": True,
                            "recovery_mode": "receipt_rebind",
                        }
                    }
                },
            )

            second = await publication.submit_publication_attempts(session, second_plan)
            await session.flush()
            rebound_attempt = await session.get(PublicationAttempt, attempt_id)
            await session.commit()
    finally:
        await engine.dispose()

    assert len(second["created_attempts"]) == 1
    assert second["created_attempts"][0]["id"] == attempt_id
    assert rebound_attempt is not None
    assert str(rebound_attempt.job_id) == str(second_job.id)
    assert rebound_attempt.content_id == str(second_job.id)
    assert rebound_attempt.status == "queued"
    assert rebound_attempt.run_status == "retry_scheduled"


@pytest.mark.asyncio
async def test_submit_publication_attempts_does_not_carry_platform_recovery_overrides_into_fresh_non_recovery_target(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
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
            prior_job = Job(source_path="source-prior.mp4", source_name="source-prior.mp4", status="done")
            session.add(prior_job)
            await session.flush()
            prior_plan = publication.build_publication_plan(
                job=prior_job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging={
                    "platforms": {
                        "douyin": {
                            "titles": ["old-title"],
                            "description": "old-body",
                            "tags": ["tag"],
                        }
                    }
                },
                creator_profile=creator_profile,
            )
            prior_submit = await publication.submit_publication_attempts(session, prior_plan)
            await session.flush()
            prior_attempt_id = prior_submit["created_attempts"][0]["id"]
            prior_attempt = await session.get(PublicationAttempt, prior_attempt_id)
            assert prior_attempt is not None
            prior_attempt.status = "needs_human"
            prior_attempt.run_status = "needs_human"
            prior_attempt.error_code = "draft_clear_failed"
            prior_attempt.request_payload = {
                **dict(prior_attempt.request_payload or {}),
                "platform_specific_overrides": {
                    "recovery_mode": "draft_reset",
                    "clear_draft_context": True,
                    "force_publish_page_refresh": True,
                },
            }
            await session.flush()

            current_job = Job(source_path="source-current.mp4", source_name="source-current.mp4", status="done")
            session.add(current_job)
            await session.flush()
            current_plan = publication.build_publication_plan(
                job=current_job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging={
                    "platforms": {
                        "douyin": {
                            "titles": ["new-title"],
                            "description": "new-body",
                            "tags": ["tag"],
                        }
                    }
                },
                creator_profile=creator_profile,
            )

            current_submit = await publication.submit_publication_attempts(session, current_plan)
            await session.flush()
            created_attempt_id = current_submit["created_attempts"][0]["id"]
            created_attempt = await session.get(PublicationAttempt, created_attempt_id)
            await session.commit()
    finally:
        await engine.dispose()

    assert created_attempt is not None
    overrides = (created_attempt.request_payload or {}).get("platform_specific_overrides") or {}
    assert overrides.get("clear_draft_context") is not True
    assert overrides.get("recovery_mode") != "draft_reset"
    recovery_state = (created_attempt.request_payload or {}).get("publication_recovery_state") or {}
    assert recovery_state.get("carry_over_from_attempt_id") in ("", None)


@pytest.mark.asyncio
async def test_submit_publication_attempts_prepare_only_current_page_ignores_historical_attempt_reuse(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
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
            prior_job = Job(source_path="source-prior.mp4", source_name="source-prior.mp4", status="done")
            session.add(prior_job)
            await session.flush()
            prior_plan = publication.build_publication_plan(
                job=prior_job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging={
                    "platforms": {
                        "douyin": {
                            "titles": ["old-title"],
                            "description": "old-body",
                            "tags": ["tag"],
                        }
                    }
                },
                creator_profile=creator_profile,
            )
            prior_submit = await publication.submit_publication_attempts(session, prior_plan)
            await session.flush()
            prior_attempt_id = prior_submit["created_attempts"][0]["id"]
            prior_attempt = await session.get(PublicationAttempt, prior_attempt_id)
            assert prior_attempt is not None
            prior_attempt.status = "processing"
            prior_attempt.run_status = "processing"
            prior_attempt.error_code = None
            await session.flush()

            current_job = Job(source_path="source-current.mp4", source_name="source-current.mp4", status="done")
            session.add(current_job)
            await session.flush()
            current_plan = publication.build_publication_plan(
                job=current_job,
                render_output=SimpleNamespace(output_path=str(media_path)),
                platform_packaging={
                    "platforms": {
                        "douyin": {
                            "titles": ["new-title"],
                            "description": "new-body",
                            "tags": ["tag"],
                            "platform_specific_overrides": {
                                "prepare_only_current_page": True,
                                "allow_prepare_without_publish_ready": True,
                            },
                        }
                    }
                },
                creator_profile=creator_profile,
            )

            current_submit = await publication.submit_publication_attempts(session, current_plan)
            await session.flush()
            created_attempt_id = current_submit["created_attempts"][0]["id"]
            created_attempt = await session.get(PublicationAttempt, created_attempt_id)
            await session.commit()
    finally:
        await engine.dispose()

    assert current_submit["skipped_targets"] == []
    assert created_attempt is not None
    assert created_attempt.id != prior_attempt_id
    assert int(created_attempt.attempt_number or 0) == 1
    recovery_state = (created_attempt.request_payload or {}).get("publication_recovery_state") or {}
    assert recovery_state.get("carry_over_from_attempt_id") in ("", None)
    assert int(recovery_state.get("reused_attempt_count") or 0) == 0


def test_publication_plan_prefers_physical_browser_profile_binding(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    profile_id = publication.build_publication_browser_profile_id(
        browser="chrome",
        user_data_dir="C:/Users/28687/AppData/Local/Google/Chrome/User Data",
        profile_directory="Profile 2",
    )
    plan = publication.build_publication_plan(
        job=SimpleNamespace(id="job-1", status="done"),
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
            "creator_profile": {
                "publishing": {
                    "platform_credentials": [
                        {
                            "platform": "douyin",
                            "account_label": "FAS · Chrome",
                            "credential_ref": "browser-agent:chrome:fas:douyin",
                            "browser_binding": {
                                "browser": "chrome",
                                "user_data_dir": "C:/Users/28687/AppData/Local/Google/Chrome/User Data",
                                "profile_directory": "Profile 2",
                                "profile_name": "FAS_EDC",
                                "profile_email": "fas.galactic@gmail.com",
                            },
                            "status": "logged_in",
                            "enabled": True,
                            "adapter": "browser_agent",
                        }
                    ]
                }
            }
        },
    )

    assert plan["publish_ready"] is True
    assert plan["targets"][0]["browser_profile_id"] == profile_id
    assert plan["targets"][0]["browser_binding"]["profile_directory"] == "Profile 2"


def test_publication_plan_uses_function_media_path_for_cover_contract(tmp_path):
    media_path = tmp_path / "output.mp4"
    media_path.write_bytes(b"video")
    cover_path = tmp_path / "cover.jpg"
    cover_path.write_bytes(b"cover")

    plan = publication.build_publication_plan(
        job=SimpleNamespace(id="job-1", status="done"),
        render_output=SimpleNamespace(output_path=str(media_path)),
        source_media_path=str(media_path),
        platform_packaging={
            "platforms": {
                "youtube": {
                    "titles": ["标题"],
                    "description": "简介",
                    "tags": ["tag"],
                    "cover_path": str(cover_path),
                }
            }
        },
        creator_profile={
            "creator_profile": {
                "publishing": {
                    "platform_credentials": [
                        {
                            "platform": "youtube",
                            "account_label": "YouTube",
                            "credential_ref": "browser-agent:chrome:youtube",
                            "status": "logged_in",
                            "enabled": True,
                            "adapter": "browser_agent",
                        }
                    ]
                }
            }
        },
    )

    assert plan["publish_ready"] is True
    assert plan["targets"][0]["cover_path"] == str(cover_path)


def test_extract_publication_logical_signature_falls_back_to_publication_capability_platform() -> None:
    media_path = "E:/media/maxace4.mp4"
    payload = {
        "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
        "body": "正文",
        "hashtags": ["EDC折刀", "刀具装备"],
        "content_kind": "video",
        "media_items": [{"local_path": media_path}],
        "publication_capability": {"platform": "douyin", "adapter": "browser_agent"},
        "publication_content_signature": {
            "fields": {
                "platform": "douyin",
                "media_path": media_path,
            }
        },
    }

    assert publication._extract_publication_logical_signature(payload) == publication._build_publication_logical_signature_payload(
        platform="douyin",
        content_kind="video",
        media_path=media_path,
        title=payload["title"],
        body=payload["body"],
        tags=payload["hashtags"],
    )["value"]


def test_extract_publication_dedupe_signature_falls_back_to_publication_capability_platform_and_adapter() -> None:
    media_path = "E:/media/maxace4.mp4"
    payload = {
        "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
        "body": "正文",
        "hashtags": ["EDC折刀", "刀具装备"],
        "content_kind": "video",
        "media_items": [{"local_path": media_path}],
        "publication_capability": {"platform": "douyin", "adapter": "browser_agent"},
        "metadata": {
            "creator_profile_id": "creator-1",
            "browser_profile_id": "browser-profile:chrome:21104fd69d72ad7267c2",
            "credential_id": "cred-1",
            "credential_ref": "browser-agent:release-gate:douyin",
            "account_label": "douyin release-gate",
        },
        "publication_content_signature": {
            "fields": {
                "platform": "douyin",
                "media_path": media_path,
            }
        },
    }

    assert publication._extract_publication_dedupe_signature(payload) == publication._build_publication_dedupe_signature_payload(
        platform="douyin",
        adapter="browser_agent",
        creator_profile_id="creator-1",
        browser_profile_id="browser-profile:chrome:21104fd69d72ad7267c2",
        credential_id="cred-1",
        credential_ref="browser-agent:release-gate:douyin",
        account_label="douyin release-gate",
        content_kind="video",
        media_path=media_path,
        title=payload["title"],
        body=payload["body"],
        tags=payload["hashtags"],
    )["value"]


def test_publication_parse_naive_schedule_as_china_local_time():
    parsed = publication._parse_datetime("2026-05-23T19:30")

    assert parsed is not None
    assert parsed.isoformat() == "2026-05-23T11:30:00+00:00"
    assert parsed.astimezone(publication.DEFAULT_PUBLICATION_TIMEZONE).isoformat() == "2026-05-23T19:30:00+08:00"
