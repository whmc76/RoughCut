from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from roughcut.api import intelligent_copy as ic_api
from roughcut.api import jobs as jobs_api
from roughcut import publication
from roughcut.db.models import CreatorCard, CreatorPlatformBinding, CreatorPublicationProfile, Job
from roughcut.db.session import Base
from roughcut.publication_platform_matrix import platform_skips_explicit_visibility_entry


class _FakeSession:
    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_create_job_publication_material_task_forces_fresh_material_generation(monkeypatch) -> None:
    captured_body: dict[str, object] = {}

    async def fake_load_publication_inputs(**_kwargs):
        return (
            SimpleNamespace(id="job-material", status="done"),
            SimpleNamespace(output_path="E:/rendered/out/final.mp4"),
            {},
            {"id": "creator-from-plan", "display_name": "FAS"},
        )

    async def fake_create_generate_task(body):
        captured_body["folder_path"] = body.folder_path
        captured_body["platforms"] = list(body.platforms)
        captured_body["platform_options"] = body.platform_options
        captured_body["use_existing_cover"] = body.use_existing_cover
        captured_body["creator_profile_id"] = body.creator_profile_id
        captured_body["force_regenerate"] = body.force_regenerate
        return {
            "id": "task-1",
            "folder_path": body.folder_path,
            "platforms": body.platforms,
            "status": "queued",
            "progress": 0,
            "stage": "queued",
            "message": "queued",
            "created_at": "2026-06-27T00:00:00Z",
            "updated_at": "2026-06-27T00:00:00Z",
        }

    monkeypatch.setattr(jobs_api, "_load_publication_inputs", fake_load_publication_inputs)
    monkeypatch.setattr(ic_api, "create_generate_task", fake_create_generate_task)

    payload = jobs_api.PublicationSubmitIn(
        platforms=["douyin", "xiaohongshu"],
        platform_options={"xiaohongshu": {"topic": "EDC", "cover_ratio": "3:4"}},
    )

    result = await jobs_api.create_job_publication_material_task(
        uuid.uuid4(),
        payload,
        session=_FakeSession(),
    )

    assert result["id"] == "task-1"
    captured_body["folder_path"] = str(captured_body["folder_path"]).replace("\\", "/")
    assert captured_body == {
        "folder_path": "E:/rendered/out",
        "platforms": ["douyin", "xiaohongshu"],
        "platform_options": {"xiaohongshu": {"topic": "EDC", "cover_ratio": "3:4"}},
        "use_existing_cover": False,
        "creator_profile_id": "creator-from-plan",
        "force_regenerate": True,
    }


@pytest.mark.asyncio
async def test_create_generate_task_persists_and_schedules_platform_options(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_upsert_generation_task(task):
        captured["task"] = task

    def fake_schedule_generation_task(task_id, **kwargs):
        captured["task_id"] = task_id
        captured["schedule"] = kwargs

    monkeypatch.setattr(
        ic_api,
        "inspect_intelligent_copy_folder",
        lambda folder_path: {"folder_path": folder_path, "material_dir": f"{folder_path}/smart-copy"},
    )
    monkeypatch.setattr(ic_api, "_resolve_generation_creator_profile", lambda _profile_id: {"display_name": "FAS"})
    monkeypatch.setattr(ic_api, "_find_active_generation_task", lambda **_kwargs: None)
    monkeypatch.setattr(ic_api, "_upsert_generation_task", fake_upsert_generation_task)
    monkeypatch.setattr(ic_api, "_schedule_generation_task", fake_schedule_generation_task)
    monkeypatch.setattr(ic_api, "_get_generation_task", lambda _task_id: None)

    body = ic_api.IntelligentCopyGenerateIn(
        folder_path="E:/materials/demo",
        platforms=["bilibili"],
        platform_options={"bilibili": {"collection_name": "EDC刀光火工具集"}},
        creator_profile_id="profile-1",
        force_regenerate=True,
    )

    result = await ic_api.create_generate_task(body)

    assert result["platform_options"] == {"bilibili": {"collection_name": "EDC刀光火工具集"}}
    assert captured["task_id"] == result["id"]
    assert captured["task"]["platform_options"] == {"bilibili": {"collection_name": "EDC刀光火工具集"}}
    assert captured["schedule"]["platform_options"] == {"bilibili": {"collection_name": "EDC刀光火工具集"}}


@pytest.mark.asyncio
async def test_generation_task_runner_passes_platform_options_to_generator(monkeypatch) -> None:
    captured: dict[str, object] = {}
    patches: list[dict[str, object]] = []

    async def fake_generate_intelligent_copy(folder_path, **kwargs):
        captured["folder_path"] = folder_path
        captured.update(kwargs)
        return {
            "status": "completed",
            "folder_path": folder_path,
            "material_dir": f"{folder_path}/smart-copy",
            "inspection": {"folder_path": folder_path, "material_dir": f"{folder_path}/smart-copy"},
            "platforms": [],
            "material_contract": {"status": "passed", "one_click_publish_ready": True, "platforms": {}},
            "material_generation_contract": {"status": "passed", "generation_ready": True},
            "publish_ready": True,
            "blocking_reasons": [],
            "manual_handoff_ready": False,
            "manual_handoff_targets": [],
        }

    monkeypatch.setattr(ic_api, "generate_intelligent_copy", fake_generate_intelligent_copy)
    monkeypatch.setattr(ic_api, "_resolve_generation_creator_profile", lambda _profile_id: {"display_name": "FAS"})
    monkeypatch.setattr(ic_api, "_patch_generation_task", lambda _task_id, patch: patches.append(patch) or patch)

    await ic_api._run_generation_task(
        "task-platform-options",
        folder_path="E:/materials/demo",
        copy_style=None,
        platforms=["bilibili"],
        platform_options={"bilibili": {"collection_name": "EDC刀光火工具集"}},
        use_existing_cover=False,
        force_regenerate=True,
        creator_profile_id="profile-1",
        creator_profile_name="FAS",
    )

    assert captured["folder_path"] == "E:/materials/demo"
    assert captured["platform_options"] == {"bilibili": {"collection_name": "EDC刀光火工具集"}}
    assert any(patch.get("status") == "completed" for patch in patches)


@pytest.mark.asyncio
async def test_publish_intelligent_folder_skips_browser_agent_gate_for_social_auto_upload_only(monkeypatch) -> None:
    async def fake_load_inputs(**_kwargs):
        return {
            "job": SimpleNamespace(id="job-1", status="done"),
            "render_output": SimpleNamespace(output_path="E:/video.mp4"),
            "packaging": {"platforms": {"douyin": {}, "kuaishou": {}}},
            "creator_profile": {"creator_profile": {"publishing": {"platform_credentials": []}}},
            "source_video_path": "E:/video.mp4",
        }

    async def fake_resolve_platform_options(**_kwargs):
        return {}

    def fake_build_plan(**_kwargs):
        return {
            "status": "ready",
            "publish_ready": True,
            "job_id": "job-1",
            "creator_profile_id": "creator-1",
            "targets": [
                {"platform": "douyin", "adapter": "social_auto_upload"},
                {"platform": "kuaishou", "adapter": "social_auto_upload"},
            ],
        }

    async def fake_submit_attempts(_session, plan):
        return {"status": "submitted", "created_attempts": [{"platform": target["platform"]} for target in plan["targets"]]}

    async def fail_agent_ready(**_kwargs):
        raise AssertionError("browser-agent gate should not run for social-auto-upload-only plans")

    async def fake_list_attempts(*_args, **_kwargs):
        return []

    monkeypatch.setattr(ic_api, "_load_intelligent_publish_inputs", fake_load_inputs)
    monkeypatch.setattr(ic_api, "_resolve_intelligent_publish_platform_options", fake_resolve_platform_options)
    monkeypatch.setattr(ic_api, "build_publication_plan", fake_build_plan)
    monkeypatch.setattr(ic_api, "publication_plan_is_publishable", lambda _plan: True)
    monkeypatch.setattr(ic_api, "list_publication_attempts", fake_list_attempts)
    monkeypatch.setattr(ic_api, "submit_publication_attempts", fake_submit_attempts)
    monkeypatch.setattr(ic_api, "check_publication_browser_agent_ready", fail_agent_ready)
    monkeypatch.setattr(ic_api, "_dispatch_publication_worker_tick", lambda _count: None)

    body = SimpleNamespace(
        folder_path="E:/materials/maxace",
        creator_profile_id="creator-1",
        platforms=["douyin", "kuaishou"],
        platform_options=None,
    )

    result = await ic_api.publish_intelligent_folder(body, session=_FakeSession())

    assert result["status"] == "submitted"
    assert [item["platform"] for item in result["created_attempts"]] == ["douyin", "kuaishou"]


@pytest.mark.asyncio
async def test_publish_intelligent_folder_uses_browser_cookie_gate_for_x_and_skips_youtube_probe(monkeypatch) -> None:
    captured_ready: dict[str, object] = {}

    async def fake_load_inputs(**_kwargs):
        return {
            "job": SimpleNamespace(id="job-browser-cookie", status="done"),
            "render_output": SimpleNamespace(output_path="E:/video.mp4"),
            "packaging": {"platforms": {"youtube": {}, "x": {}}},
            "creator_profile": {"creator_profile": {"publishing": {"platform_credentials": []}}},
            "source_video_path": "E:/video.mp4",
        }

    async def fake_resolve_platform_options(**_kwargs):
        return {}

    def fake_build_plan(**_kwargs):
        return {
            "status": "ready",
            "publish_ready": True,
            "job_id": "job-browser-cookie",
            "creator_profile_id": "creator-1",
            "targets": [
                {"platform": "youtube", "adapter": "browser_agent", "browser_profile_id": "chrome-main"},
                {"platform": "x", "adapter": "x_link_share", "browser_profile_id": "chrome-main"},
            ],
        }

    async def fake_agent_ready(**kwargs):
        captured_ready.update(kwargs)
        return {"ready": True}

    async def fake_submit_attempts(_session, plan):
        return {"status": "submitted", "created_attempts": [{"platform": target["platform"]} for target in plan["targets"]]}

    async def fake_list_attempts(*_args, **_kwargs):
        return []

    monkeypatch.setattr(ic_api, "_load_intelligent_publish_inputs", fake_load_inputs)
    monkeypatch.setattr(ic_api, "_resolve_intelligent_publish_platform_options", fake_resolve_platform_options)
    monkeypatch.setattr(ic_api, "build_publication_plan", fake_build_plan)
    monkeypatch.setattr(ic_api, "publication_plan_is_publishable", lambda _plan: True)
    monkeypatch.setattr(ic_api, "list_publication_attempts", fake_list_attempts)
    monkeypatch.setattr(ic_api, "submit_publication_attempts", fake_submit_attempts)
    monkeypatch.setattr(ic_api, "check_publication_browser_agent_ready", fake_agent_ready)
    monkeypatch.setattr(ic_api, "_dispatch_publication_worker_tick", lambda _count: None)
    monkeypatch.setattr(
        ic_api,
        "get_settings",
        lambda: SimpleNamespace(
            publication_browser_agent_base_url="http://browser-agent.local",
            publication_browser_agent_auth_token="",
            publication_browser_agent_timeout_sec=60,
        ),
    )

    body = SimpleNamespace(
        folder_path="E:/materials/edc17",
        creator_profile_id="creator-1",
        platforms=["youtube", "x"],
        platform_options=None,
    )

    result = await ic_api.publish_intelligent_folder(body, session=_FakeSession())

    assert result["status"] == "submitted"
    assert captured_ready["target_platforms"] == ["youtube", "x"]
    assert captured_ready["skip_creator_session_platforms"] == ["youtube"]


@pytest.mark.asyncio
async def test_publish_intelligent_folder_auto_heals_cover_block_before_submit(monkeypatch) -> None:
    load_calls = {"count": 0}
    rerender_calls = []

    async def fake_load_inputs(**_kwargs):
        load_calls["count"] += 1
        packaging_ready = load_calls["count"] > 1
        return {
            "job": SimpleNamespace(id="job-cover", status="done"),
            "render_output": SimpleNamespace(output_path="E:/video.mp4"),
            "packaging": {"ready": packaging_ready},
            "creator_profile": {"id": "creator-1", "display_name": "Demo Creator", "creator_profile": {"publishing": {}}},
            "source_video_path": "E:/video.mp4",
        }

    async def fake_resolve_platform_options(**_kwargs):
        return {}

    def fake_build_plan(**kwargs):
        if not kwargs["platform_packaging"].get("ready"):
            return {
                "status": "blocked",
                "publish_ready": False,
                "blocked_reasons": ["平台文案未就绪：封面完整位图标题校验未完成"],
                "warnings": [],
                "targets": [],
            }
        return {
            "status": "ready",
            "publish_ready": True,
            "job_id": "job-cover",
            "creator_profile_id": "creator-1",
            "targets": [{"platform": "douyin", "adapter": "social_auto_upload"}],
        }

    async def fake_rerender(*args, **kwargs):
        rerender_calls.append({"args": args, "kwargs": kwargs})
        return {"publish_ready": True, "material_contract": {"status": "passed"}}

    async def fake_submit_attempts(_session, plan):
        assert plan["cover_auto_heal"]["status"] == "healed"
        return {"status": "submitted", "created_attempts": [{"platform": "douyin"}]}

    async def fake_list_attempts(*_args, **_kwargs):
        return []

    monkeypatch.setattr(ic_api, "_load_intelligent_publish_inputs", fake_load_inputs)
    monkeypatch.setattr(ic_api, "_resolve_intelligent_publish_platform_options", fake_resolve_platform_options)
    monkeypatch.setattr(ic_api, "build_publication_plan", fake_build_plan)
    monkeypatch.setattr(ic_api, "rerender_existing_intelligent_copy_cover_groups", fake_rerender)
    monkeypatch.setattr(ic_api, "publication_plan_is_publishable", lambda plan: bool(plan.get("publish_ready")))
    monkeypatch.setattr(ic_api, "list_publication_attempts", fake_list_attempts)
    monkeypatch.setattr(ic_api, "submit_publication_attempts", fake_submit_attempts)
    monkeypatch.setattr(ic_api, "_dispatch_publication_worker_tick", lambda _count: None)
    monkeypatch.setattr(
        ic_api,
        "get_settings",
        lambda: SimpleNamespace(publication_cover_auto_heal_enabled=True, publication_cover_auto_heal_max_attempts=1),
    )

    body = SimpleNamespace(
        folder_path="E:/materials/sample_show",
        creator_profile_id="creator-1",
        platforms=["douyin"],
        platform_options=None,
    )

    result = await ic_api.publish_intelligent_folder(body, session=_FakeSession())

    assert result["status"] == "submitted"
    assert len(rerender_calls) == 1
    assert rerender_calls[0]["kwargs"]["platforms"] == ["douyin"]


@pytest.mark.asyncio
async def test_publish_intelligent_folder_stops_when_cover_auto_heal_is_exhausted(monkeypatch) -> None:
    async def fake_load_inputs(**_kwargs):
        return {
            "job": SimpleNamespace(id="job-cover", status="done"),
            "render_output": SimpleNamespace(output_path="E:/video.mp4"),
            "packaging": {"ready": False},
            "creator_profile": {"id": "creator-1", "display_name": "Demo Creator", "creator_profile": {"publishing": {}}},
            "source_video_path": "E:/video.mp4",
        }

    async def fake_resolve_platform_options(**_kwargs):
        return {}

    def fake_build_plan(**_kwargs):
        return {
            "status": "blocked",
            "publish_ready": False,
            "blocked_reasons": ["平台文案未就绪：封面主体与参考图一致性不足"],
            "warnings": [],
            "targets": [],
        }

    async def fake_rerender(*_args, **_kwargs):
        return {"publish_ready": False, "material_contract": {"status": "failed"}}

    async def fail_submit_attempts(*_args, **_kwargs):
        raise AssertionError("cover-blocked plans must not be submitted after exhausted auto-heal")

    async def fake_list_attempts(*_args, **_kwargs):
        return []

    monkeypatch.setattr(ic_api, "_load_intelligent_publish_inputs", fake_load_inputs)
    monkeypatch.setattr(ic_api, "_resolve_intelligent_publish_platform_options", fake_resolve_platform_options)
    monkeypatch.setattr(ic_api, "build_publication_plan", fake_build_plan)
    monkeypatch.setattr(ic_api, "rerender_existing_intelligent_copy_cover_groups", fake_rerender)
    monkeypatch.setattr(ic_api, "publication_plan_is_publishable", lambda plan: bool(plan.get("publish_ready")))
    monkeypatch.setattr(ic_api, "list_publication_attempts", fake_list_attempts)
    monkeypatch.setattr(ic_api, "submit_publication_attempts", fail_submit_attempts)
    monkeypatch.setattr(
        ic_api,
        "get_settings",
        lambda: SimpleNamespace(publication_cover_auto_heal_enabled=True, publication_cover_auto_heal_max_attempts=1),
    )

    body = SimpleNamespace(
        folder_path="E:/materials/sample_show",
        creator_profile_id="creator-1",
        platforms=["douyin"],
        platform_options=None,
    )

    result = await ic_api.publish_intelligent_folder(body, session=_FakeSession())

    assert result["status"] == "blocked"
    assert result["plan"]["cover_auto_heal"]["status"] == "needs_human"
    assert "封面自愈重试已耗尽" in "；".join(result["blocked_reasons"])


@pytest.mark.asyncio
async def test_publish_job_auto_generates_materials_before_submit(monkeypatch) -> None:
    job_id = "11111111-1111-1111-1111-111111111111"
    load_calls = {"count": 0}
    generated = {"called": False}

    async def fake_load_publication_inputs(**_kwargs):
        load_calls["count"] += 1
        packaging = None if load_calls["count"] == 1 else {"platforms": {"douyin": {"titles": ["标题"]}}}
        return (
            SimpleNamespace(id=job_id, status="done", source_path="", output_dir="E:/rendered"),
            SimpleNamespace(output_path="E:/rendered/video.mp4"),
            packaging,
            {"id": "creator-1", "display_name": "Demo Creator"},
        )

    async def fake_generate_intelligent_copy(folder_path, **kwargs):
        generated["called"] = True
        assert Path(folder_path) == Path("E:/rendered")
        assert kwargs["platforms"] == ["douyin"]
        return {
            "publish_ready": True,
            "material_dir": "E:/rendered/smart-copy",
            "platform_packaging_json_path": "E:/rendered/smart-copy/_meta/platform-packaging.json",
            "blocking_reasons": [],
        }

    async def fake_list_attempts(*_args, **_kwargs):
        return []

    async def fake_resolve_options(**_kwargs):
        return {}

    def fake_build_plan(**kwargs):
        if kwargs["platform_packaging"] is None:
            return {
                "status": "blocked",
                "publish_ready": False,
                "media_source_contract": {"source": "render_output"},
                "targets": [],
            }
        return {
            "status": "ready",
            "publish_ready": True,
            "targets": [{"platform": "douyin", "adapter": "social_auto_upload"}],
        }

    async def fake_submit_attempts(_session, plan):
        return {"status": "submitted", "created_attempts": [{"platform": plan["targets"][0]["platform"]}]}

    monkeypatch.setattr(jobs_api, "_load_publication_inputs", fake_load_publication_inputs)
    monkeypatch.setattr(jobs_api, "generate_intelligent_copy", fake_generate_intelligent_copy)
    monkeypatch.setattr(jobs_api, "list_publication_attempts", fake_list_attempts)
    monkeypatch.setattr(jobs_api, "_resolve_job_publication_platform_options", fake_resolve_options)
    monkeypatch.setattr(jobs_api, "build_publication_plan", fake_build_plan)
    monkeypatch.setattr(jobs_api, "publication_plan_is_publishable", lambda plan: bool(plan.get("publish_ready")))
    monkeypatch.setattr(jobs_api, "submit_publication_attempts", fake_submit_attempts)
    monkeypatch.setattr(jobs_api, "_dispatch_publication_worker_tick", lambda _count: None)

    result = await jobs_api.publish_job_to_bound_platforms(
        job_id,
        SimpleNamespace(creator_profile_id="creator-1", platforms=["douyin"], platform_options={}),
        session=_FakeSession(),
    )

    assert generated["called"] is True
    assert result["status"] == "submitted"
    assert result["material_generation"]["source"] == "job_one_click_publish"


@pytest.mark.asyncio
async def test_prepare_job_publication_materials_generates_without_submit(monkeypatch) -> None:
    job_id = "22222222-2222-2222-2222-222222222222"
    load_calls = {"count": 0}
    generated = {"called": False}

    async def fake_load_publication_inputs(**_kwargs):
        load_calls["count"] += 1
        packaging = None if load_calls["count"] == 1 else {"platforms": {"bilibili": {"titles": ["标题"]}}}
        return (
            SimpleNamespace(id=job_id, status="done", source_path="", output_dir="E:/rendered"),
            SimpleNamespace(output_path="E:/rendered/video.mp4"),
            packaging,
            {"id": "creator-1", "display_name": "Demo Creator"},
        )

    async def fake_generate_intelligent_copy(folder_path, **kwargs):
        generated["called"] = True
        assert Path(folder_path) == Path("E:/rendered")
        assert kwargs["platforms"] == ["bilibili"]
        return {
            "publish_ready": True,
            "material_dir": "E:/rendered/smart-copy",
            "platform_packaging_json_path": "E:/rendered/smart-copy/_meta/platform-packaging.json",
            "blocking_reasons": [],
        }

    async def fake_list_attempts(*_args, **_kwargs):
        return []

    async def fake_resolve_options(**_kwargs):
        return {}

    def fake_build_plan(**kwargs):
        return {
            "status": "ready",
            "publish_ready": True,
            "targets": [{"platform": "bilibili", "adapter": "browser_agent"}],
            "existing_attempts": kwargs["existing_attempts"],
        }

    async def fail_submit_attempts(*_args, **_kwargs):
        raise AssertionError("prepare materials must not submit publication attempts")

    monkeypatch.setattr(jobs_api, "_load_publication_inputs", fake_load_publication_inputs)
    monkeypatch.setattr(jobs_api, "generate_intelligent_copy", fake_generate_intelligent_copy)
    monkeypatch.setattr(jobs_api, "list_publication_attempts", fake_list_attempts)
    monkeypatch.setattr(jobs_api, "_resolve_job_publication_platform_options", fake_resolve_options)
    monkeypatch.setattr(jobs_api, "build_publication_plan", fake_build_plan)
    monkeypatch.setattr(jobs_api, "publication_plan_is_publishable", lambda plan: bool(plan.get("publish_ready")))
    monkeypatch.setattr(jobs_api, "submit_publication_attempts", fail_submit_attempts)

    result = await jobs_api.prepare_job_publication_materials(
        job_id,
        SimpleNamespace(creator_profile_id="creator-1", platforms=["bilibili"], platform_options={}),
        session=_FakeSession(),
    )

    assert generated["called"] is True
    assert result["status"] == "ready"
    assert result["material_generation"]["source"] == "job_one_click_publish"
    assert result["targets"] == [{"platform": "bilibili", "adapter": "browser_agent"}]


@pytest.mark.asyncio
async def test_prepare_job_publication_materials_force_regenerate_rewrites_existing_platform(monkeypatch) -> None:
    job_id = "33333333-3333-3333-3333-333333333333"
    load_calls = {"count": 0}
    generated: dict[str, object] = {"called": False}

    async def fake_load_publication_inputs(**_kwargs):
        load_calls["count"] += 1
        packaging = {
            "platforms": {
                "xiaohongshu": {
                    "titles": ["旧小红书标题"],
                    "description": "旧正文",
                }
            }
        }
        if load_calls["count"] > 1:
            packaging = {
                "platforms": {
                    "xiaohongshu": {
                        "titles": ["新小红书标题"],
                        "description": "按小红书策略重写正文",
                    }
                }
            }
        return (
            SimpleNamespace(id=job_id, status="done", source_path="", output_dir="E:/rendered"),
            SimpleNamespace(output_path="E:/rendered/video.mp4"),
            packaging,
            {"id": "creator-1", "display_name": "Demo Creator"},
        )

    async def fake_generate_intelligent_copy(folder_path, **kwargs):
        generated["called"] = True
        generated["folder_path"] = str(folder_path).replace("\\", "/")
        generated["platforms"] = kwargs["platforms"]
        generated["force_regenerate"] = kwargs["force_regenerate"]
        return {
            "publish_ready": True,
            "material_dir": "E:/rendered/smart-copy",
            "platform_packaging_json_path": "E:/rendered/smart-copy/_meta/platform-packaging.json",
            "blocking_reasons": [],
        }

    async def fake_list_attempts(*_args, **_kwargs):
        return []

    async def fake_resolve_options(**_kwargs):
        return {}

    def fake_build_plan(**kwargs):
        package = kwargs["platform_packaging"]["platforms"]["xiaohongshu"]
        return {
            "status": "ready",
            "publish_ready": True,
            "material_targets": [
                {
                    "platform": "xiaohongshu",
                    "title": package["titles"][0],
                    "body": package["description"],
                }
            ],
            "existing_attempts": kwargs["existing_attempts"],
        }

    monkeypatch.setattr(jobs_api, "_load_publication_inputs", fake_load_publication_inputs)
    monkeypatch.setattr(jobs_api, "generate_intelligent_copy", fake_generate_intelligent_copy)
    monkeypatch.setattr(jobs_api, "list_publication_attempts", fake_list_attempts)
    monkeypatch.setattr(jobs_api, "_resolve_job_publication_platform_options", fake_resolve_options)
    monkeypatch.setattr(jobs_api, "build_publication_plan", fake_build_plan)

    result = await jobs_api.prepare_job_publication_materials(
        job_id,
        jobs_api.PublicationSubmitIn(platforms=["xiaohongshu"], force_regenerate=True),
        session=_FakeSession(),
    )

    assert generated == {
        "called": True,
        "folder_path": "E:/rendered",
        "platforms": ["xiaohongshu"],
        "force_regenerate": True,
    }
    assert result["material_targets"][0]["title"] == "新小红书标题"
    assert result["material_generation"]["source"] == "job_one_click_publish"


def test_job_publication_packaging_generation_respects_requested_platforms() -> None:
    packaging = {
        "platforms": {
            "bilibili": {
                "titles": ["Demo title"],
                "description": "Demo description",
            }
        }
    }

    assert (
        jobs_api._job_publication_packaging_needs_generation(
            packaging,
            requested_platforms=["bilibili"],
        )
        is False
    )
    assert (
        jobs_api._job_publication_packaging_needs_generation(
            packaging,
            requested_platforms=["douyin"],
        )
        is True
    )


@pytest.mark.asyncio
async def test_publish_job_uses_recovered_materialized_contract_before_regeneration(monkeypatch) -> None:
    job_id = "12345678-1234-1234-1234-123456789abc"
    generated = {"called": False}
    build_calls = []

    async def fake_load_publication_inputs(**_kwargs):
        return (
            SimpleNamespace(id=job_id, status="done", source_path="", output_dir="."),
            SimpleNamespace(output_path="."),
            None,
            {"id": "creator-1", "display_name": "Demo Creator"},
        )

    async def fake_generate_intelligent_copy(*_args, **_kwargs):
        generated["called"] = True
        raise AssertionError("material generation should not run when a materialized attempt contract is publishable")

    async def fake_list_attempts(*_args, **_kwargs):
        return [
            {
                "id": "attempt-1",
                "platform": "douyin",
                "request_payload": {
                    "title": "标题",
                    "body": "正文",
                    "metadata": {"resolved_media_path": "E:/runtime/publication-media/final.mp4"},
                    "media_items": [{"local_path": "E:/runtime/publication-media/final.mp4"}],
                },
            }
        ]

    async def fake_resolve_options(**_kwargs):
        return {}

    def fake_build_plan(**kwargs):
        build_calls.append(kwargs)
        return {
            "status": "ready",
            "publish_ready": True,
            "media_source_contract": {"source": "materialized_attempt_payload"},
            "targets": [{"platform": "douyin", "adapter": "social_auto_upload"}],
        }

    async def fake_submit_attempts(_session, plan):
        return {"status": "submitted", "created_attempts": [{"platform": plan["targets"][0]["platform"]}]}

    monkeypatch.setattr(jobs_api, "_load_publication_inputs", fake_load_publication_inputs)
    monkeypatch.setattr(jobs_api, "generate_intelligent_copy", fake_generate_intelligent_copy)
    monkeypatch.setattr(jobs_api, "list_publication_attempts", fake_list_attempts)
    monkeypatch.setattr(jobs_api, "_resolve_job_publication_platform_options", fake_resolve_options)
    monkeypatch.setattr(jobs_api, "build_publication_plan", fake_build_plan)
    monkeypatch.setattr(jobs_api, "publication_plan_is_publishable", lambda plan: bool(plan.get("publish_ready")))
    monkeypatch.setattr(jobs_api, "submit_publication_attempts", fake_submit_attempts)
    monkeypatch.setattr(jobs_api, "_dispatch_publication_worker_tick", lambda _count: None)

    result = await jobs_api.publish_job_to_bound_platforms(
        job_id,
        SimpleNamespace(creator_profile_id="creator-1", platforms=["douyin"], platform_options={}),
        session=_FakeSession(),
    )

    assert generated["called"] is False
    assert result["status"] == "submitted"
    assert "material_generation" not in result
    assert build_calls[0]["platform_packaging"] is None


def test_job_publication_failed_packaging_needs_regeneration() -> None:
    assert jobs_api._job_publication_packaging_needs_generation(
        {
            "status": "failed",
            "platforms": {"douyin": {"title": "标题"}},
        }
    ) is True
    assert jobs_api._job_publication_packaging_needs_generation(
        {
            "material_contract": {"status": "failed"},
            "platforms": {"douyin": {"title": "标题"}},
        }
    ) is True


def test_job_publication_packaging_must_belong_to_current_render_output() -> None:
    job = SimpleNamespace(output_dir="E:/rendered", source_path="E:/source/input.mp4")
    render_output = SimpleNamespace(output_path="E:/rendered/final.mp4")

    assert jobs_api._publication_packaging_belongs_to_job_render_output(
        {"material_dir": "E:/rendered/smart-copy", "platforms": {"youtube": {"title": "标题"}}},
        job=job,
        render_output=render_output,
    ) is True
    assert jobs_api._publication_packaging_belongs_to_job_render_output(
        {"material_dir": "E:/待发布/smart-copy", "platforms": {"youtube": {"title": "标题"}}},
        job=job,
        render_output=render_output,
    ) is False
    assert jobs_api._publication_packaging_belongs_to_job_render_output(
        {"platforms": {"youtube": {"title": "标题"}}},
        job=job,
        render_output=render_output,
    ) is False


def test_derive_job_publication_folder_path_uses_render_output_parent_for_windows_paths() -> None:
    job = SimpleNamespace(output_dir="Y:/EDC系列/AI粗剪", source_path="jobs/job-1/source.mp4")
    render_output = SimpleNamespace(
        output_path=r"Y:\EDC系列\AI粗剪\20260503_NITECORE_EDC17\20260503_NITECORE_EDC17_横版_成片.mp4"
    )

    folder = jobs_api._derive_job_publication_folder_path(job, render_output)

    assert folder.replace("/", "\\").endswith(r"Y:\EDC系列\AI粗剪\20260503_NITECORE_EDC17")


def test_derive_job_publication_folder_path_rejects_current_directory_fallback() -> None:
    job = SimpleNamespace(output_dir=".", source_path="")
    render_output = SimpleNamespace(output_path=".")

    assert jobs_api._derive_job_publication_folder_path(job, render_output) == ""


def test_load_job_smart_copy_publication_packaging_materializes_host_path(monkeypatch, tmp_path) -> None:
    material_dir = tmp_path / "host-intelligent-copy" / "edc17" / "smart-copy"
    meta_dir = material_dir / "_meta"
    meta_dir.mkdir(parents=True)
    cover_path = material_dir / "01-bilibili-cover.jpg"
    cover_path.write_bytes(b"cover")
    platform_packaging = {
        "platforms": {
            "bilibili": {
                "titles": ["EDC17 三光源超薄手电开箱"],
                "description": "EDC17 手电筒开箱、功能演示和上手体验。",
                "tags": ["EDC17"],
                "cover_path": str(cover_path),
            }
        }
    }
    (meta_dir / "platform-packaging.json").write_text(
        __import__("json").dumps(platform_packaging, ensure_ascii=False),
        encoding="utf-8",
    )

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"folder_path": str(material_dir.parent), "files": []}

    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return FakeResponse()

    monkeypatch.setattr(jobs_api, "resolve_codex_proxy_sibling_url", lambda path: f"http://bridge{path}")
    monkeypatch.setattr(jobs_api, "resolve_codex_proxy_token", lambda: "token-1")
    monkeypatch.setattr(jobs_api.httpx, "post", fake_post)

    job = SimpleNamespace(output_dir=r"Y:\EDC系列\AI粗剪\20260503_NITECORE_EDC17", source_path="")
    render_output = SimpleNamespace(output_path=r"Y:\EDC系列\AI粗剪\20260503_NITECORE_EDC17\final.mp4")

    packaging = jobs_api._load_job_smart_copy_publication_packaging(job=job, render_output=render_output)

    assert captured["url"] == "http://bridge/v1/host/materialize-directory"
    assert captured["json"]["folder_path"].endswith(r"20260503_NITECORE_EDC17")
    assert packaging is not None
    assert packaging["source"] == "platform_packaging"
    assert packaging["material_dir"] == str(material_dir)
    assert packaging["platforms"]["bilibili"]["titles"] == ["EDC17 三光源超薄手电开箱"]


@pytest.mark.asyncio
async def test_job_publish_merges_creator_card_publication_bindings() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            creator = CreatorCard(name="Demo Creator", status="active")
            session.add(creator)
            await session.flush()
            profile = CreatorPublicationProfile(
                creator_card_id=creator.id,
                status="draft",
                publication_payload_json={},
            )
            session.add(profile)
            await session.flush()
            binding = CreatorPlatformBinding(
                publication_profile_id=profile.id,
                platform="douyin",
                credential_ref="social-auto-upload:creator-demo-douyin:douyin",
                binding_payload_json={
                    "status": "login_confirmed",
                    "enabled": True,
                    "adapter": "social_auto_upload",
                    "account_label": "Demo Creator · 抖音",
                    "browser_profile_id": "browser-agent:chrome:demo:douyin",
                    "browser_binding": {"browser": "chrome", "profile_id": "browser-agent:chrome:demo:douyin"},
                },
            )
            session.add(binding)
            await session.flush()

            merged = await jobs_api._merge_job_creator_card_publication_bindings(
                session=session,
                job=Job(creator_card_id=creator.id),
                creator_profile={"id": "avatar-profile", "display_name": "Demo Creator", "creator_profile": {}},
            )
    finally:
        await engine.dispose()

    credentials = publication.active_publication_credentials(merged)
    assert [item["platform"] for item in credentials] == ["douyin"]
    assert credentials[0]["status"] == "logged_in"
    assert credentials[0]["adapter"] == "browser_agent"
    assert credentials[0]["credential_ref"] == "social-auto-upload:creator-demo-douyin:douyin"


@pytest.mark.asyncio
async def test_job_publication_auto_heals_cover_block_before_submit(monkeypatch) -> None:
    job_id = "11111111-1111-1111-1111-111111111111"
    rerender_calls = []

    async def fake_rerender(folder_path, **kwargs):
        rerender_calls.append({"folder_path": folder_path, "kwargs": kwargs})
        return {"publish_ready": True, "material_contract": {"status": "passed"}}

    async def fake_load_publication_inputs(**_kwargs):
        return (
            SimpleNamespace(id=job_id, status="done", source_path="", output_dir="E:/rendered"),
            SimpleNamespace(output_path="E:/rendered/video.mp4"),
            {"platforms": {"douyin": {"cover_path": "E:/rendered/smart-copy/03-douyin-cover.jpg"}}},
            {"id": "creator-1", "display_name": "Demo Creator"},
        )

    def fake_build_plan(**_kwargs):
        return {
            "status": "ready",
            "publish_ready": True,
            "targets": [{"platform": "douyin", "adapter": "social_auto_upload"}],
        }

    monkeypatch.setattr(jobs_api, "rerender_existing_intelligent_copy_cover_groups", fake_rerender)
    monkeypatch.setattr(jobs_api, "_load_publication_inputs", fake_load_publication_inputs)
    monkeypatch.setattr(jobs_api, "build_publication_plan", fake_build_plan)
    monkeypatch.setattr(jobs_api, "publication_plan_is_publishable", lambda plan: bool(plan.get("publish_ready")))
    monkeypatch.setattr(
        jobs_api,
        "get_settings",
        lambda: SimpleNamespace(publication_cover_auto_heal_enabled=True, publication_cover_auto_heal_max_attempts=1),
    )

    plan, *_rest = await jobs_api._maybe_auto_heal_job_publication_cover_plan(
        plan={
            "status": "blocked",
            "publish_ready": False,
            "blocked_reasons": ["平台文案未就绪：封面当前仅为参考帧占位图，正式生图尚未完成"],
            "warnings": [],
        },
        job=SimpleNamespace(id=job_id, source_path="", output_dir="E:/rendered"),
        render_output=SimpleNamespace(output_path="E:/rendered/video.mp4"),
        packaging=None,
        creator_profile={"id": "creator-1", "display_name": "Demo Creator"},
        creator_profile_id="creator-1",
        requested_platforms=["douyin"],
        platform_options={},
        existing_attempts=[],
        session=_FakeSession(),
    )

    assert plan["publish_ready"] is True
    assert plan["cover_auto_heal"]["status"] == "healed"
    assert Path(rerender_calls[0]["folder_path"]) == Path("E:/rendered")
    assert rerender_calls[0]["kwargs"]["platforms"] == ["douyin"]


@pytest.mark.asyncio
async def test_intelligent_publish_merges_creator_card_publication_bindings() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            creator = CreatorCard(name="Demo Creator", status="active")
            session.add(creator)
            await session.flush()
            profile = CreatorPublicationProfile(
                creator_card_id=creator.id,
                status="draft",
                publication_payload_json={},
            )
            session.add(profile)
            await session.flush()
            binding = CreatorPlatformBinding(
                publication_profile_id=profile.id,
                platform="bilibili",
                credential_ref="social-auto-upload:creator-demo-bilibili:bilibili",
                binding_payload_json={
                    "status": "login_confirmed",
                    "enabled": True,
                    "adapter": "social_auto_upload",
                    "account_label": "Demo Creator · Chrome",
                    "browser_profile_id": "browser-agent:chrome:demo:bilibili",
                    "browser_binding": {"browser": "chrome", "profile_id": "browser-agent:chrome:demo:bilibili"},
                },
            )
            session.add(binding)
            await session.flush()

            merged = await ic_api._merge_creator_card_publication_bindings(
                session=session,
                creator_profile={"id": "avatar-profile", "display_name": "Demo Creator", "creator_profile": {}},
                creator_profile_id="avatar-profile",
            )
    finally:
        await engine.dispose()

    credentials = publication.active_publication_credentials(merged)
    assert [item["platform"] for item in credentials] == ["bilibili"]
    assert credentials[0]["status"] == "logged_in"
    assert credentials[0]["adapter"] == "browser_agent"
    assert credentials[0]["credential_ref"] == "social-auto-upload:creator-demo-bilibili:bilibili"


@pytest.mark.asyncio
async def test_resolve_publish_source_media_path_keeps_compatible_source(tmp_path: Path, monkeypatch) -> None:
    source_path = tmp_path / "episode.mp4"
    source_path.write_bytes(b"video")

    async def fake_probe_media(path: Path):
        return SimpleNamespace(
            has_video_stream=True,
            has_audio_stream=True,
            video_codec="h264",
            audio_codec="aac",
            pix_fmt="yuv420p",
            format_name="mp4",
        )

    monkeypatch.setattr(ic_api, "probe_media", fake_probe_media)

    resolved = await ic_api._resolve_publish_source_media_path(video_path=source_path)

    assert resolved == source_path.resolve()


@pytest.mark.asyncio
async def test_resolve_publish_source_media_path_builds_runtime_copy_for_incompatible_source(tmp_path: Path, monkeypatch) -> None:
    source_path = tmp_path / "episode.mp4"
    source_path.write_bytes(b"source-video")
    runtime_path = ic_api._publication_runtime_target_path(source_path)

    async def fake_probe_media(path: Path):
        if Path(path) == source_path:
            return SimpleNamespace(
                has_video_stream=True,
                has_audio_stream=True,
                video_codec="hevc",
                audio_codec="aac",
                pix_fmt="yuv420p10le",
                format_name="mp4",
            )
        return SimpleNamespace(
            has_video_stream=True,
            has_audio_stream=True,
            video_codec="h264",
            audio_codec="aac",
            pix_fmt="yuv420p",
            format_name="mp4",
        )

    async def fake_transcode(**kwargs) -> None:
        target = Path(kwargs["runtime_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"runtime-video")

    monkeypatch.setattr(ic_api, "probe_media", fake_probe_media)
    monkeypatch.setattr(ic_api, "_transcode_publication_runtime_media", fake_transcode)

    resolved = await ic_api._resolve_publish_source_media_path(video_path=source_path)

    assert resolved == runtime_path.resolve()
    assert runtime_path.is_file()


def test_wechat_channels_skips_explicit_visibility_entry() -> None:
    assert platform_skips_explicit_visibility_entry("wechat-channels") is True


def test_publication_plan_option_value_preserves_explicit_blank_override() -> None:
    assert (
        publication._resolve_publication_plan_option_value(
            {"scheduled_publish_at": ""},
            {"scheduled_publish_at": "2026-06-11T20:30"},
            "scheduled_publish_at",
        )
        == ""
    )
