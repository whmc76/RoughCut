from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from roughcut.api import jobs as jobs_api
from roughcut.db.session import Base
from roughcut.db.models import Job, JobStep


def test_remix_runtime_path_blocker_accepts_configured_source_mount(tmp_path, monkeypatch) -> None:
    runtime_source = tmp_path / "remix-source"
    runtime_source.mkdir()
    script = runtime_source / "scripts" / "season2-episodes-1-5.md"
    video = runtime_source / "dubbed" / "season2" / "SampleShow.S02E02.mp4"
    video.parent.mkdir(parents=True)
    script.parent.mkdir(parents=True)
    script.write_text("## 第2集《仓储超市》\n测试文案", encoding="utf-8")
    video.write_bytes(b"video")

    monkeypatch.setenv("ROUGHCUT_REMIX_SOURCE_HOST_ROOT", "C:/sample-show-source")
    monkeypatch.setenv("ROUGHCUT_REMIX_SOURCE_CONTAINER_ROOT", str(runtime_source))

    blocker = jobs_api._remix_runtime_path_blocker(
        {
            "source_root": r"C:\sample-show-source",
            "script_path": r"C:\sample-show-source\scripts\season2-episodes-1-5.md",
            "source_video_path": r"C:\sample-show-source\dubbed\season2\SampleShow.S02E02.mp4",
        }
    )

    assert blocker is None


def test_remix_command_uses_runtime_source_mapping_and_container_service_urls(tmp_path, monkeypatch) -> None:
    runtime_source = tmp_path / "remix-source"
    output_dir = tmp_path / "out"
    monkeypatch.setenv("ROUGHCUT_REMIX_SOURCE_HOST_ROOT", "C:/sample-show-source")
    monkeypatch.setenv("ROUGHCUT_REMIX_SOURCE_CONTAINER_ROOT", str(runtime_source))
    monkeypatch.setenv("ROUGHCUT_API_INTERNAL_PORT", "8000")
    monkeypatch.setenv("LOCAL_ASR_API_BASE_URL", "http://host.docker.internal:30230")

    job = Job(output_dir=str(output_dir))
    command, resolved_output_dir = jobs_api._build_remix_production_job_command(
        job,
        {
            "source_root": r"C:\sample-show-source",
            "episode": 2,
            "creator_profile": "demo_creator",
            "task_binding_id": "script_footage_remix",
        },
        force=False,
    )

    source_root_arg = command[command.index("--source-root") + 1]
    assert jobs_api._remix_portable_path(source_root_arg) == jobs_api._remix_portable_path(str(runtime_source))
    assert r"C:\sample-show-source" not in command
    assert command[command.index("--api-base") + 1] == "http://127.0.0.1:8000"
    assert command[command.index("--qwen3-asr-base") + 1] == "http://host.docker.internal:30230"
    assert command[command.index("--tts-timeout-sec") + 1] == str(jobs_api.REMIX_PRODUCTION_TTS_TIMEOUT_SEC)
    assert "--force" not in command
    assert "--force-tts" not in command
    assert resolved_output_dir == output_dir


def test_remix_command_rewrites_legacy_project_output_dir(tmp_path, monkeypatch) -> None:
    runtime_output = tmp_path / "runtime-output"
    monkeypatch.setattr(
        jobs_api,
        "get_settings",
        lambda: SimpleNamespace(output_dir=str(runtime_output), job_storage_dir=str(tmp_path / "jobs")),
    )
    monkeypatch.setenv("ROUGHCUT_REMIX_SOURCE_HOST_ROOT", "C:/sample-show-source")
    monkeypatch.setenv("ROUGHCUT_REMIX_SOURCE_CONTAINER_ROOT", "/app/remix-source")

    legacy_output = jobs_api.DEFAULT_PROJECT_ROOT / "output" / "script-footage-remix-production" / "sample_show" / "s02e02"
    job = Job(output_dir=str(legacy_output))
    command, resolved_output_dir = jobs_api._build_remix_production_job_command(
        job,
        {
            "source_root": r"C:\sample-show-source",
            "episode": 2,
            "creator_profile": "demo_creator",
            "task_binding_id": "sample_show",
        },
        force=False,
    )

    expected_output = runtime_output / "script-footage-remix-production" / "sample_show" / "s02e02"
    assert resolved_output_dir == expected_output
    assert job.output_dir == str(expected_output)
    assert command[command.index("--output-dir") + 1] == str(expected_output)


def test_job_publication_folder_prefers_render_output_over_windows_source_path() -> None:
    job = Job(
        source_path=r"C:\sample-show-source\SampleShow.S02E03.mp4",
        output_dir="/app/data/output/script-footage-remix-production/example_script_footage_remix/s02e03",
    )
    render_output = SimpleNamespace(
        output_path="/app/data/output/script-footage-remix-production/example_script_footage_remix/s02e03/s02e03_羽毛魔杖/sample_show_s02e03_羽毛魔杖_parenting_remix.mp4",
    )

    folder_path = jobs_api._derive_job_publication_folder_path(job, render_output)

    assert "script-footage-remix-production" in folder_path
    assert folder_path != "."
    assert not folder_path.startswith("F:")


def test_job_publication_render_output_prefers_unified_enhanced_variant(tmp_path) -> None:
    packaged = tmp_path / "sample_成片.mp4"
    enhanced = tmp_path / "sample_增强版.mp4"
    packaged.write_bytes(b"packaged")
    enhanced.write_bytes(b"enhanced")
    job = Job(enhancement_modes=["ai_effects", "avatar_commentary"])
    render_output = SimpleNamespace(output_path=str(packaged), status="done", progress=1.0)

    selected = jobs_api._select_job_publication_render_output(
        job,
        render_output,
        {
            "packaged_mp4": str(packaged),
            "enhanced_mp4": str(enhanced),
            "avatar_result": {"status": "done"},
        },
    )

    assert selected.output_path == str(enhanced.resolve())


def test_job_publication_render_output_prefers_packaged_before_legacy_avatar_fallback(tmp_path) -> None:
    packaged = tmp_path / "sample_成片.mp4"
    avatar = tmp_path / "sample_数字人版.mp4"
    packaged.write_bytes(b"packaged")
    avatar.write_bytes(b"avatar")
    job = Job(enhancement_modes=["ai_effects", "avatar_commentary"])
    render_output = SimpleNamespace(output_path=str(packaged), status="done", progress=1.0)

    selected = jobs_api._select_job_publication_render_output(
        job,
        render_output,
        {
            "packaged_mp4": str(packaged),
            "avatar_mp4": str(avatar),
            "avatar_result": {"status": "done"},
        },
    )

    assert selected is render_output


def test_job_publication_render_output_uses_legacy_avatar_only_without_standard(tmp_path) -> None:
    avatar = tmp_path / "sample_数字人版.mp4"
    avatar.write_bytes(b"avatar")
    job = Job(enhancement_modes=["ai_effects", "avatar_commentary"])

    selected = jobs_api._select_job_publication_render_output(
        job,
        None,
        {
            "avatar_mp4": str(avatar),
            "avatar_result": {"status": "done"},
        },
    )

    assert selected.output_path == str(avatar.resolve())


def test_job_publication_render_output_keeps_packaged_when_avatar_not_ready(tmp_path) -> None:
    packaged = tmp_path / "sample_成片.mp4"
    avatar = tmp_path / "sample_数字人版.mp4"
    packaged.write_bytes(b"packaged")
    avatar.write_bytes(b"avatar")
    job = Job(enhancement_modes=["ai_effects", "avatar_commentary"])
    render_output = SimpleNamespace(output_path=str(packaged), status="done", progress=1.0)

    selected = jobs_api._select_job_publication_render_output(
        job,
        render_output,
        {
            "packaged_mp4": str(packaged),
            "avatar_mp4": str(avatar),
            "avatar_result": {"status": "degraded"},
        },
    )

    assert selected is render_output


def test_done_publication_job_without_pipeline_steps_reports_complete_progress() -> None:
    job = Job(
        status="done",
        workflow_template="intelligent_publish",
        workflow_mode="standard_edit",
    )

    assert jobs_api._calculate_job_progress_percent(job) == 100


def test_attach_remix_task_job_state_exposes_frontend_progress_percent() -> None:
    job = Job(
        status="done",
        source_path=r"C:\sample-show-source\SampleShow.S02E02.mp4",
        workflow_mode="script_footage_remix",
    )
    job.steps = [
        JobStep(step_name="script_footage_remix", status="done"),
    ]
    task = {
        "source_video_path": r"C:\sample-show-source\SampleShow.S02E02.mp4",
        "season": 2,
        "episode": 2,
        "title": "仓储超市",
    }

    item = jobs_api._attach_remix_task_job_state(task, job)

    assert item["job_progress_percent"] == 100
    assert item["progress_percent"] == 100


def test_default_remix_manifest_discovers_creator_binding(tmp_path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    manifest = project_root / "data" / "remix_production_tasks" / "creator_pending.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"schema":"roughcut.remix.production_tasks.v1","tasks":[]}', encoding="utf-8")
    profile_dir = project_root / "data" / "creator_profiles"
    profile_dir.mkdir(parents=True)
    (profile_dir / "creator.json").write_text(
        """
        {
          "remix_task_bindings": [
            {"production_manifest_path": "data/remix_production_tasks/creator_pending.json"}
          ]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(jobs_api, "DEFAULT_PROJECT_ROOT", project_root)
    monkeypatch.delenv(jobs_api.DEFAULT_REMIX_PRODUCTION_MANIFEST_ENV, raising=False)

    assert jobs_api._resolve_remix_production_manifest_path(None) == manifest.resolve()


def test_refresh_existing_remix_job_metadata_restores_source_context() -> None:
    job = Job(
        source_path=r"C:\old\SampleShow.S02E02.mp4",
        source_name="old",
        workflow_mode="script_footage_remix",
    )
    job.steps = [
        JobStep(step_name="content_profile", status="done", metadata_={}),
        JobStep(step_name="script_footage_remix", status="pending", metadata_={}),
    ]
    payload = {
        "_manifest_path": "data/remix_production_tasks/example_remix_pending.json",
        "id": "example_remix_pending",
        "task_binding_id": "example_script_footage_remix",
        "source_root": r"C:\sample-show-source",
        "creator_profile": "demo_creator",
        "selection_policy": {
            "script_policy": "preserve_full_script",
            "duration_policy": "duration_is_warning_not_script_cut",
        },
    }
    task = {
        "source_video_path": r"C:\sample-show-source\dubbed\season2\SampleShow.S02E02.mp4",
        "script_path": r"C:\sample-show-source\scripts\season2-episodes-1-5.md",
        "season": 2,
        "episode": 2,
        "title": "仓储超市",
    }

    source_context = jobs_api._refresh_remix_production_job_metadata(job, payload, task)

    assert source_context["queue_task_kind"] == "remix_production"
    assert source_context["remix_production"]["episode"] == 2
    assert job.source_name == "S02E02 · 仓储超市"
    assert job.steps[0].metadata_["source_context"] == source_context
    assert job.steps[1].metadata_["source_context"] == source_context


def test_remix_production_cover_artifact_falls_back_to_episode_output_cover(tmp_path, monkeypatch) -> None:
    runtime_output = tmp_path / "runtime-output"
    monkeypatch.setattr(
        jobs_api,
        "get_settings",
        lambda: SimpleNamespace(output_dir=str(runtime_output), job_storage_dir=str(tmp_path / "jobs")),
    )

    payload = {
        "id": "example_remix_pending",
        "task_binding_id": "example_script_footage_remix",
    }
    task = {
        "episode": 5,
        "title": "理发师",
    }
    cover_path = (
        runtime_output
        / "script-footage-remix-production"
        / "example_script_footage_remix"
        / "s02e05"
        / "s02e05_理发师"
        / "s02e05_理发师_cover.jpg"
    )
    cover_path.parent.mkdir(parents=True)
    cover_path.write_bytes(b"cover")

    job = Job(workflow_mode="script_footage_remix")
    job.artifacts = []

    jobs_api._ensure_remix_production_cover_artifact(job, payload, task)

    assert job.artifacts
    assert job.artifacts[0].data_json["cover"] == str(cover_path)
    assert jobs_api._resolve_job_queue_cover_path(job) == cover_path

    existing_job = Job(workflow_mode="script_footage_remix", output_dir=str(cover_path.parent.parent))
    existing_job.steps = [
        JobStep(
            step_name="content_profile",
            metadata_={
                "source_context": {
                    "queue_task_kind": "remix_production",
                    "remix_production": {"episode": 5},
                }
            },
        )
    ]
    existing_job.artifacts = []
    assert jobs_api._resolve_job_queue_cover_path(existing_job) == cover_path


@pytest.mark.asyncio
async def test_startup_recovery_resumes_running_remix_job_without_forcing_tts(tmp_path, monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(jobs_api, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(
        jobs_api,
        "get_settings",
        lambda: SimpleNamespace(startup_recovery_enabled=True, output_dir=str(tmp_path / "runtime-output")),
    )

    source_root = tmp_path / "remix-source"
    script_path = source_root / "scripts" / "season2-episodes-1-5.md"
    video_path = source_root / "dubbed" / "season2" / "SampleShow.S02E02.mp4"
    script_path.parent.mkdir(parents=True)
    video_path.parent.mkdir(parents=True)
    script_path.write_text("## 第2集《仓储超市》\n测试文案", encoding="utf-8")
    video_path.write_bytes(b"video")
    source_context = {
        "queue_task_kind": "remix_production",
        "remix_production": {
            "source_root": str(source_root),
            "script_path": str(script_path),
            "source_video_path": str(video_path),
            "episode": 2,
            "creator_profile": "demo_creator",
            "task_binding_id": "example_script_footage_remix",
        },
    }
    job = Job(
        source_path=str(video_path),
        source_name="S02E02 · 仓储超市",
        status="processing",
        workflow_mode="script_footage_remix",
        output_dir=str(tmp_path / "runtime-output" / "script-footage-remix-production" / "example_script_footage_remix" / "s02e02"),
    )
    job.steps = [
        JobStep(step_name="content_profile", status="done", metadata_={"source_context": source_context}),
        JobStep(
            step_name="script_footage_remix",
            status="running",
            attempt=1,
            metadata_={"source_context": source_context, "progress": 0.4, "command": ["old"]},
        ),
    ]
    async with session_factory() as session:
        session.add(job)
        await session.commit()
        job_id = job.id

    scheduled: list[tuple[str, list[str], str, str]] = []
    recovered = await jobs_api.recover_interrupted_remix_production_jobs_on_startup(
        schedule_task=lambda job_id, command, output_dir, task_id: scheduled.append((job_id, command, output_dir, task_id))
    )

    assert recovered == 1
    assert scheduled and scheduled[0][0] == str(job_id)
    assert "--force" not in scheduled[0][1]
    assert "--force-tts" not in scheduled[0][1]
    assert scheduled[0][1][scheduled[0][1].index("--source-root") + 1] == str(source_root)
    assert scheduled[0][3]
    async with session_factory() as session:
        result = await session.execute(select(Job).options(selectinload(Job.steps)).where(Job.id == job_id))
        restored_job = result.scalar_one()
        remix_step = next(step for step in restored_job.steps if step.step_name == "script_footage_remix")
        assert restored_job.status == "processing"
        assert remix_step.status == "running"
        assert remix_step.attempt == 2
        assert remix_step.metadata_["startup_recovered_at"]
        assert "复用已有中间产物" in remix_step.metadata_["detail"]

    await engine.dispose()


def test_remix_production_dispatch_uses_media_queue_and_preassigned_task_id(monkeypatch) -> None:
    sent: dict[str, object] = {}

    class _FakeCelery:
        def send_task(self, name, *, args, queue, task_id):
            sent.update({"name": name, "args": args, "queue": queue, "task_id": task_id})
            return SimpleNamespace(id=task_id)

    monkeypatch.setattr(jobs_api, "celery_app", _FakeCelery())

    result = jobs_api._send_remix_production_job_task(
        "job-1",
        ["python", "-m", "roughcut.cli"],
        "/app/data/output/remix",
        task_id="task-1",
    )

    assert result.id == "task-1"
    assert sent == {
        "name": jobs_api.REMIX_PRODUCTION_CELERY_TASK_NAME,
        "args": ["job-1", ["python", "-m", "roughcut.cli"], "/app/data/output/remix"],
        "queue": jobs_api.REMIX_PRODUCTION_CELERY_QUEUE,
        "task_id": "task-1",
    }
