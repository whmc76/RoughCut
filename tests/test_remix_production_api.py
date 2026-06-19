from pathlib import Path
from types import SimpleNamespace

from roughcut.api import jobs as jobs_api
from roughcut.db.models import Job, JobStep


def test_remix_runtime_path_blocker_accepts_configured_source_mount(tmp_path, monkeypatch) -> None:
    runtime_source = tmp_path / "remix-source"
    runtime_source.mkdir()
    script = runtime_source / "scripts" / "season2-episodes-1-5.md"
    video = runtime_source / "dubbed" / "season2" / "Bluey.S02E02.mp4"
    video.parent.mkdir(parents=True)
    script.parent.mkdir(parents=True)
    script.write_text("## 第2集《仓储超市》\n测试文案", encoding="utf-8")
    video.write_bytes(b"video")

    monkeypatch.setenv("ROUGHCUT_REMIX_SOURCE_HOST_ROOT", "F:/bluey-source")
    monkeypatch.setenv("ROUGHCUT_REMIX_SOURCE_CONTAINER_ROOT", str(runtime_source))

    blocker = jobs_api._remix_runtime_path_blocker(
        {
            "source_root": r"F:\bluey-source",
            "script_path": r"F:\bluey-source\scripts\season2-episodes-1-5.md",
            "source_video_path": r"F:\bluey-source\dubbed\season2\Bluey.S02E02.mp4",
        }
    )

    assert blocker is None


def test_remix_command_uses_runtime_source_mapping_and_container_service_urls(tmp_path, monkeypatch) -> None:
    runtime_source = tmp_path / "remix-source"
    output_dir = tmp_path / "out"
    monkeypatch.setenv("ROUGHCUT_REMIX_SOURCE_HOST_ROOT", "F:/bluey-source")
    monkeypatch.setenv("ROUGHCUT_REMIX_SOURCE_CONTAINER_ROOT", str(runtime_source))
    monkeypatch.setenv("ROUGHCUT_API_INTERNAL_PORT", "8000")
    monkeypatch.setenv("LOCAL_ASR_API_BASE_URL", "http://host.docker.internal:30230")

    job = Job(output_dir=str(output_dir))
    command, resolved_output_dir = jobs_api._build_remix_production_job_command(
        job,
        {
            "source_root": r"F:\bluey-source",
            "episode": 2,
            "creator_profile": "jenny_baby",
            "task_binding_id": "script_footage_remix",
        },
        force=False,
    )

    source_root_arg = command[command.index("--source-root") + 1]
    assert jobs_api._remix_portable_path(source_root_arg) == jobs_api._remix_portable_path(str(runtime_source))
    assert r"F:\bluey-source" not in command
    assert command[command.index("--api-base") + 1] == "http://127.0.0.1:8000"
    assert command[command.index("--qwen3-asr-base") + 1] == "http://host.docker.internal:30230"
    assert command[command.index("--tts-timeout-sec") + 1] == str(jobs_api.REMIX_PRODUCTION_TTS_TIMEOUT_SEC)
    assert "--force" not in command
    assert "--force-tts" not in command
    assert resolved_output_dir == output_dir


def test_remix_command_rewrites_legacy_project_output_dir(tmp_path, monkeypatch) -> None:
    runtime_output = tmp_path / "runtime-output"
    monkeypatch.setattr(jobs_api, "get_settings", lambda: SimpleNamespace(output_dir=str(runtime_output)))
    monkeypatch.setenv("ROUGHCUT_REMIX_SOURCE_HOST_ROOT", "F:/bluey-source")
    monkeypatch.setenv("ROUGHCUT_REMIX_SOURCE_CONTAINER_ROOT", "/app/remix-source")

    legacy_output = jobs_api.DEFAULT_PROJECT_ROOT / "output" / "script-footage-remix-production" / "bluey" / "s02e02"
    job = Job(output_dir=str(legacy_output))
    command, resolved_output_dir = jobs_api._build_remix_production_job_command(
        job,
        {
            "source_root": r"F:\bluey-source",
            "episode": 2,
            "creator_profile": "jenny_baby",
            "task_binding_id": "bluey",
        },
        force=False,
    )

    expected_output = runtime_output / "script-footage-remix-production" / "bluey" / "s02e02"
    assert resolved_output_dir == expected_output
    assert job.output_dir == str(expected_output)
    assert command[command.index("--output-dir") + 1] == str(expected_output)


def test_job_publication_folder_prefers_render_output_over_windows_source_path() -> None:
    job = Job(
        source_path=r"F:\bluey-source\Bluey.S02E03.mp4",
        output_dir="/app/data/output/script-footage-remix-production/bluey_script_footage_remix/s02e03",
    )
    render_output = SimpleNamespace(
        output_path="/app/data/output/script-footage-remix-production/bluey_script_footage_remix/s02e03/s02e03_羽毛魔杖/bluey_s02e03_羽毛魔杖_parenting_remix.mp4",
    )

    folder_path = jobs_api._derive_job_publication_folder_path(job, render_output)

    assert "script-footage-remix-production" in folder_path
    assert folder_path != "."
    assert not folder_path.startswith("F:")


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
        source_path=r"F:\bluey-source\Bluey.S02E02.mp4",
        workflow_mode="script_footage_remix",
    )
    job.steps = [
        JobStep(step_name="script_footage_remix", status="done"),
    ]
    task = {
        "source_video_path": r"F:\bluey-source\Bluey.S02E02.mp4",
        "season": 2,
        "episode": 2,
        "title": "仓储超市",
    }

    item = jobs_api._attach_remix_task_job_state(task, job)

    assert item["job_progress_percent"] == 100
    assert item["progress_percent"] == 100
