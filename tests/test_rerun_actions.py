from __future__ import annotations

import asyncio
import inspect

from roughcut.pipeline.orchestrator import PIPELINE_STEPS
from roughcut.pipeline.rerun_actions import QUALITY_RERUN_STEPS, rerun_chain_from_step
from roughcut.pipeline import steps, tasks
from roughcut.api import jobs as api_jobs


def test_editing_pipeline_excludes_publication_steps() -> None:
    assert "render" in PIPELINE_STEPS
    assert "final_review" not in PIPELINE_STEPS
    assert "platform_package" not in PIPELINE_STEPS
    assert "final_review" not in QUALITY_RERUN_STEPS
    assert "platform_package" not in QUALITY_RERUN_STEPS


def test_editing_step_runner_rejects_legacy_platform_package_entrypoint() -> None:
    try:
        steps.run_step_sync("platform_package", "00000000-0000-0000-0000-000000000000")
    except ValueError as exc:
        assert "Unknown step" in str(exc)
    else:
        raise AssertionError("platform_package must not be executable through the editing step runner")


def test_run_step_sync_disposes_async_session_state_in_step_event_loop(monkeypatch) -> None:
    events: list[tuple[str, int | None]] = []

    async def fake_run_render(job_id: str) -> dict:
        events.append((f"run:{job_id}", id(asyncio.get_running_loop())))
        return {"ok": True}

    async def fake_reset_session_state() -> None:
        events.append(("async_reset", id(asyncio.get_running_loop())))

    monkeypatch.setattr(steps, "reset_session_state_sync", lambda: events.append(("sync_reset", None)))
    monkeypatch.setattr(steps, "reset_session_state", fake_reset_session_state)
    monkeypatch.setattr(steps, "run_render", fake_run_render)

    assert steps.run_step_sync("render", "job-1") == {"ok": True}

    assert events[0] == ("sync_reset", None)
    assert events[1][0] == "run:job-1"
    assert events[2][0] == "async_reset"
    assert events[1][1] == events[2][1]


def test_run_step_sync_preserves_step_result_when_async_session_dispose_fails(monkeypatch) -> None:
    async def fake_run_render(job_id: str) -> dict:
        return {"job_id": job_id}

    async def fake_reset_session_state() -> None:
        raise RuntimeError("dispose failed")

    monkeypatch.setattr(steps, "reset_session_state_sync", lambda: None)
    monkeypatch.setattr(steps, "reset_session_state", fake_reset_session_state)
    monkeypatch.setattr(steps, "run_render", fake_run_render)

    assert steps.run_step_sync("render", "job-2") == {"job_id": "job-2"}


def test_editing_worker_does_not_expose_legacy_platform_package_task() -> None:
    assert not hasattr(tasks, "llm_platform_package")


def test_editing_render_flow_does_not_consume_publication_cover_hooks() -> None:
    edit_plan_source = inspect.getsource(steps.run_edit_plan)
    render_source = inspect.getsource(steps.run_render)
    runtime_context_source = inspect.getsource(steps._runtime_render_plan_context)
    manual_apply_source = inspect.getsource(api_jobs.apply_manual_editor_timeline)

    assert "render_cover_generation_enabled" not in edit_plan_source
    assert "render_cover_generation_enabled" not in render_source
    assert "render_cover_generation_enabled" not in manual_apply_source
    assert "include_cover=" not in edit_plan_source
    assert "include_cover=" not in manual_apply_source
    assert "extract_cover_frame" not in render_source
    assert "load_cover_selection_summary" not in render_source
    assert '"cover"' not in runtime_context_source


def test_extract_audio_is_supported_recovery_rerun_start() -> None:
    chain = rerun_chain_from_step("extract_audio")

    assert "extract_audio" in QUALITY_RERUN_STEPS
    assert chain[:3] == ["extract_audio", "transcribe", "subtitle_postprocess"]
    assert chain[-2:] == ["edit_plan", "render"]


def test_transcribe_is_supported_recovery_rerun_start() -> None:
    chain = rerun_chain_from_step("transcribe")

    assert "transcribe" in QUALITY_RERUN_STEPS
    assert chain[:2] == ["transcribe", "subtitle_postprocess"]
    assert chain[chain.index("content_profile") + 1] == "summary_review"
    assert chain[-2:] == ["edit_plan", "render"]


def test_content_profile_rerun_revisits_summary_review_gate() -> None:
    chain = rerun_chain_from_step("content_profile")

    assert "summary_review" in QUALITY_RERUN_STEPS
    assert chain[:2] == ["content_profile", "summary_review"]
