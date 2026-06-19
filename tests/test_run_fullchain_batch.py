from __future__ import annotations

import time

from scripts import run_fullchain_batch as batch
from roughcut.pipeline.live_readiness import build_live_readiness_summary


def test_run_job_stops_job_after_requested_step(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_collect_job_report(job_id, item, step_runs, status, *, stop_after=None):
        return {
            "job_id": job_id,
            "status": status,
            "step_count": len(step_runs),
        }

    monkeypatch.setattr(batch, "load_step_statuses", lambda job_id: {"probe": "done"})
    monkeypatch.setattr(batch, "PIPELINE_STEPS", ["probe", "content_profile", "render"])
    monkeypatch.setattr(batch, "_resolve_batch_step_timeout_strategy", lambda step_name: "thread")
    monkeypatch.setattr(batch, "mark_step", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch, "run_step_sync", lambda step_name, job_id: {"step": step_name, "job_id": job_id})
    monkeypatch.setattr(batch, "read_step_detail", lambda job_id, step_name: f"{step_name} done")
    monkeypatch.setattr(batch, "finalize_job", lambda job_id, status, **kwargs: calls.append(("finalize", status)))
    monkeypatch.setattr(
        batch,
        "stop_job_after_requested_step",
        lambda job_id, *, stopped_after: calls.append(("stop", stopped_after)),
    )
    monkeypatch.setattr(batch, "collect_job_report", fake_collect_job_report)

    result = batch.run_job("job-1", {"path": "E:/demo.mp4", "source_name": "demo.mp4"}, stop_after="content_profile")

    assert result["status"] == "partial"
    assert result["step_count"] == 1
    assert calls == [("stop", "content_profile")]


def test_configure_local_event_loop_policy_does_not_force_selector_by_default(monkeypatch) -> None:
    calls: list[object] = []

    class DummyPolicy:
        pass

    def fake_set_event_loop_policy(policy: object) -> None:
        calls.append(policy)

    monkeypatch.setenv("ROUGHCUT_FORCE_SELECTOR_EVENT_LOOP", "")
    monkeypatch.setattr(batch.sys, "platform", "win32")
    monkeypatch.setattr(batch.asyncio, "WindowsSelectorEventLoopPolicy", DummyPolicy)
    monkeypatch.setattr(batch.asyncio, "set_event_loop_policy", fake_set_event_loop_policy)
    batch._configure_local_event_loop_policy()
    assert calls == []


def test_configure_local_event_loop_policy_forces_selector_when_enabled(monkeypatch) -> None:
    calls: list[object] = []

    class DummyPolicy:
        pass

    def fake_set_event_loop_policy(policy: object) -> None:
        calls.append(policy)

    monkeypatch.setenv("ROUGHCUT_FORCE_SELECTOR_EVENT_LOOP", "1")
    monkeypatch.setattr(batch.sys, "platform", "win32")
    monkeypatch.setattr(batch.asyncio, "WindowsSelectorEventLoopPolicy", DummyPolicy)
    monkeypatch.setattr(batch.asyncio, "set_event_loop_policy", fake_set_event_loop_policy)
    batch._configure_local_event_loop_policy()
    assert len(calls) == 1
    assert isinstance(calls[0], DummyPolicy)


def test_configure_console_encoding_sets_utf8(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class DummyStream:
        def reconfigure(self, *, encoding: str, errors: str) -> None:
            calls.append((encoding, errors))

    monkeypatch.setattr(batch.sys, "stdout", DummyStream())
    monkeypatch.setattr(batch.sys, "stderr", DummyStream())

    batch._configure_console_encoding()

    assert calls == [("utf-8", "replace"), ("utf-8", "replace")]


def test_render_batch_timeout_uses_render_stale_budget(monkeypatch) -> None:
    class Settings:
        render_step_stale_timeout_sec = 5400

    monkeypatch.delenv("ROUGHCUT_BATCH_STEP_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("ROUGHCUT_BATCH_STEP_TIMEOUT_SECONDS_RENDER", raising=False)
    monkeypatch.setattr(batch, "get_settings", lambda: Settings())

    assert batch._resolve_batch_step_timeout_seconds("render") >= 5400.0


def test_terminal_failed_status_caps_quality_and_adds_render_issue() -> None:
    adjusted = batch._apply_terminal_status_to_quality_assessment(
        {"score": 100.0, "grade": "A", "issue_codes": []},
        status="failed",
        render_diagnostics={
            "render_step": {
                "status": "failed",
                "error": "TimeoutError: 步骤 render 执行超过 1200.0 秒",
                "sync_runner": {"sync_runner_timeout_strategy": "process"},
            }
        },
    )

    assert adjusted["score"] == 0.0
    assert adjusted["grade"] == "E"
    assert "job_failed" in adjusted["issue_codes"]
    assert "render_timeout" in adjusted["issue_codes"]


def test_process_worker_disposes_db_session_state(monkeypatch) -> None:
    calls: list[str] = []

    class DummyQueue:
        def put(self, payload: dict) -> None:
            calls.append(str(payload.get("status")))

    monkeypatch.setattr(batch, "run_step_sync", lambda step_name, job_id: calls.append(f"run:{step_name}:{job_id}"))
    monkeypatch.setattr(batch, "reset_session_state_sync", lambda: calls.append("reset"))

    batch._run_step_sync_process_worker("render", "job-1", DummyQueue())

    assert calls == ["run:render:job-1", "ok", "reset"]


def test_build_live_stage_validations_reports_render_failure_summary() -> None:
    validations = batch.build_live_stage_validations(
        step_statuses={
            "probe": "done",
            "transcribe": "done",
            "subtitle_postprocess": "done",
            "content_profile": "done",
            "summary_review": "done",
            "edit_plan": "done",
            "render": "failed",
        },
        step_details={},
        step_errors={"render": "TimeoutError: 步骤 render 执行超过 1200.0 秒"},
        step_metadata={"render": {"sync_runner_timeout_strategy": "process"}},
        run_status="failed",
        stop_after=None,
        transcript_segment_count=1,
        subtitle_count=1,
        keep_ratio=0.8,
        profile={"review_mode": "auto_confirmed", "summary": "ok"},
        platform_doc=None,
        subtitle_quality_report={},
        subtitle_term_resolution_patch={},
        subtitle_consistency_report={},
        quality_assessment={"issue_codes": []},
    )

    render_validation = next(item for item in validations if item.stage == "render")
    assert render_validation.status == "fail"
    assert render_validation.summary == "导出成片失败：render_timeout_process"
    assert render_validation.issue_codes == ["render_timeout"]


def test_configure_windows_proactor_unraisable_filter_suppresses_only_known_noise(monkeypatch) -> None:
    forwarded: list[object] = []

    def previous_hook(unraisable: object) -> None:
        forwarded.append(unraisable)

    class DummyUnraisable:
        pass

    benign = DummyUnraisable()
    real_error = DummyUnraisable()
    monkeypatch.setattr(batch.sys, "unraisablehook", previous_hook)
    monkeypatch.setattr(
        batch,
        "_is_windows_proactor_closed_pipe_unraisable",
        lambda unraisable: unraisable is benign,
    )

    batch._configure_windows_proactor_unraisable_filter()
    batch.sys.unraisablehook(benign)
    batch.sys.unraisablehook(real_error)

    assert forwarded == [real_error]


def test_run_job_finishes_done_runs_normally(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_collect_job_report(job_id, item, step_runs, status, *, stop_after=None):
        return {
            "job_id": job_id,
            "status": status,
            "step_count": len(step_runs),
        }

    monkeypatch.setattr(batch, "load_step_statuses", lambda job_id: {})
    monkeypatch.setattr(batch, "PIPELINE_STEPS", ["content_profile"])
    monkeypatch.setattr(batch, "_resolve_batch_step_timeout_strategy", lambda step_name: "thread")
    monkeypatch.setattr(batch, "mark_step", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch, "run_step_sync", lambda step_name, job_id: {"step": step_name, "job_id": job_id})
    monkeypatch.setattr(batch, "read_step_detail", lambda job_id, step_name: f"{step_name} done")
    monkeypatch.setattr(
        batch,
        "finalize_job",
        lambda job_id, status, **kwargs: calls.append(("finalize", status)),
    )
    monkeypatch.setattr(
        batch,
        "stop_job_after_requested_step",
        lambda job_id, *, stopped_after: calls.append(("stop", stopped_after)),
    )
    monkeypatch.setattr(batch, "collect_job_report", fake_collect_job_report)

    result = batch.run_job("job-2", {"path": "E:/demo.mp4", "source_name": "demo.mp4"})

    assert result["status"] == "done"
    assert calls == [("finalize", "done")]


def test_build_asr_evidence_summarizes_fallback_attempts() -> None:
    evidence = batch._build_asr_evidence(
        {
            "provider": "local_http_asr",
            "model": "faster-whisper-large-v3-beam5-nohot",
            "language": "zh-CN",
            "attempts": [
                {
                    "provider": "local_http_asr",
                    "model": "qwen3-asr-1.7b-forced-aligner",
                    "error": "asr_quality_gate: rejected suspicious local_http_asr output",
                },
                {
                    "provider": "local_http_asr",
                    "model": "faster-whisper-large-v3-beam5-nohot",
                    "error": "",
                },
            ],
            "segments": [{"text": "large transcript payload should not be copied"}],
        }
    )

    assert evidence["provider"] == "local_http_asr"
    assert evidence["model"] == "faster-whisper-large-v3-beam5-nohot"
    assert evidence["attempt_count"] == 2
    assert evidence["fallback_used"] is True
    assert evidence["attempts"][0]["status"] == "rejected"
    assert evidence["attempts"][1]["status"] == "selected"
    assert len(evidence["quality_gate_rejections"]) == 1
    assert "segments" not in evidence


def test_build_asr_evidence_summarizes_quality_gate_artifact() -> None:
    evidence = batch._build_asr_evidence(
        {},
        {
            "status": "rejected",
            "reason": "asr_quality_gate",
            "message": "All transcription providers failed: local_http_asr/qwen3: asr_quality_gate",
            "language": "zh-CN",
            "rejected_attempts": [
                {
                    "provider": "local_http_asr",
                    "model": "qwen3-asr-1.7b-forced-aligner",
                    "analysis": {
                        "confirmed_noise_duplicate_count": 5,
                        "severe_timing_noise_count": 1,
                    },
                }
            ],
        },
    )

    assert evidence["status"] == "rejected"
    assert evidence["provider"] == "local_http_asr"
    assert evidence["model"] == "qwen3-asr-1.7b-forced-aligner"
    assert evidence["attempt_count"] == 1
    assert evidence["fallback_used"] is False
    assert evidence["quality_gate_rejections"][0]["status"] == "rejected"
    assert "asr_quality_gate" in evidence["error"]


def test_sync_runner_attempt_value_marks_terminal_failures_exhausted() -> None:
    assert batch._sync_runner_attempt_value(0, status="running", terminal_failure=False) == 1
    assert batch._sync_runner_attempt_value(1, status="failed", terminal_failure=False) == 1
    assert batch._sync_runner_attempt_value(1, status="failed", terminal_failure=True) >= 3


def test_run_job_passes_failure_error_into_finalize(monkeypatch) -> None:
    finalize_calls: list[tuple[str, str | None]] = []

    async def fake_collect_job_report(job_id, item, step_runs, status, *, stop_after=None):
        return {
            "job_id": job_id,
            "status": status,
            "step_count": len(step_runs),
        }

    monkeypatch.setattr(batch, "load_step_statuses", lambda job_id: {})
    monkeypatch.setattr(batch, "PIPELINE_STEPS", ["probe"])
    monkeypatch.setattr(batch, "mark_step", lambda *args, **kwargs: None)

    def _boom(step_name, job_id):
        raise FileNotFoundError("E:/missing/demo.mp4")

    monkeypatch.setattr(batch, "run_step_sync", _boom)
    monkeypatch.setattr(batch, "read_step_detail", lambda job_id, step_name: "")
    monkeypatch.setattr(
        batch,
        "finalize_job",
        lambda job_id, status, **kwargs: finalize_calls.append((status, kwargs.get("error"))),
    )
    monkeypatch.setattr(
        batch,
        "stop_job_after_requested_step",
        lambda job_id, *, stopped_after: None,
    )
    monkeypatch.setattr(batch, "collect_job_report", fake_collect_job_report)

    result = batch.run_job("job-fail", {"path": "E:/demo.mp4", "source_name": "demo.mp4"})

    assert result["status"] == "failed"
    assert finalize_calls == [("failed", "FileNotFoundError: E:/missing/demo.mp4")]


def test_resolve_batch_step_timeout_default_and_step_override(monkeypatch) -> None:
    monkeypatch.delenv("ROUGHCUT_BATCH_STEP_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("ROUGHCUT_BATCH_STEP_TIMEOUT_SECONDS_CONTENT_PROFILE", raising=False)
    monkeypatch.delenv("ROUGHCUT_BATCH_STEP_TIMEOUT_SECONDS_RENDER", raising=False)
    assert batch._resolve_batch_step_timeout_seconds("content_profile") == 420.0
    assert batch._resolve_batch_step_timeout_seconds("render") == 1200.0

    monkeypatch.setenv("ROUGHCUT_BATCH_STEP_TIMEOUT_SECONDS", "1200")
    assert batch._resolve_batch_step_timeout_seconds("content_profile") == 1200.0
    assert batch._resolve_batch_step_timeout_seconds("render") == 1200.0

    monkeypatch.setenv("ROUGHCUT_BATCH_STEP_TIMEOUT_SECONDS_CONTENT_PROFILE", "240")
    assert batch._resolve_batch_step_timeout_seconds("content_profile") == 240.0

    monkeypatch.setenv("ROUGHCUT_BATCH_STEP_TIMEOUT_SECONDS_RENDER", "120")
    assert batch._resolve_batch_step_timeout_seconds("render") == 120.0

    monkeypatch.setenv("ROUGHCUT_BATCH_STEP_TIMEOUT_SECONDS_RENDER", "1")
    assert batch._resolve_batch_step_timeout_seconds("render") == 1.0


def test_resolve_batch_step_timeout_strategy(monkeypatch) -> None:
    monkeypatch.setenv("ROUGHCUT_BATCH_STEP_TIMEOUT_STRATEGY", "thread")
    monkeypatch.delenv("ROUGHCUT_BATCH_STEP_TIMEOUT_STRATEGY_RENDER", raising=False)
    assert batch._resolve_batch_step_timeout_strategy("render") == "process"

    monkeypatch.setenv("ROUGHCUT_BATCH_STEP_TIMEOUT_STRATEGY", "process")
    monkeypatch.delenv("ROUGHCUT_BATCH_STEP_TIMEOUT_STRATEGY_RENDER", raising=False)
    assert batch._resolve_batch_step_timeout_strategy("render") == "process"
    assert batch._resolve_batch_step_timeout_strategy("content_profile") == "process"

    monkeypatch.setenv("ROUGHCUT_BATCH_STEP_TIMEOUT_STRATEGY", "invalid")
    monkeypatch.setenv("ROUGHCUT_BATCH_STEP_TIMEOUT_STRATEGY_CONTENT_PROFILE", "thread")
    assert batch._resolve_batch_step_timeout_strategy("content_profile") == "thread"

    monkeypatch.setenv("ROUGHCUT_BATCH_STEP_TIMEOUT_STRATEGY_RENDER", "process")
    assert batch._resolve_batch_step_timeout_strategy("render") == "process"

    monkeypatch.setenv("ROUGHCUT_BATCH_STEP_TIMEOUT_STRATEGY_RENDER", "invalid")
    assert batch._resolve_batch_step_timeout_strategy("render") == "process"


def test_run_job_calls_process_timeout_strategy(monkeypatch) -> None:
    calls: list[str] = []
    async def fake_collect_job_report(job_id, item, step_runs, status, *, stop_after=None):
        return {
            "job_id": job_id,
            "status": status,
            "step_count": len(step_runs),
        }

    monkeypatch.setattr(batch, "load_step_statuses", lambda job_id: {})
    monkeypatch.setattr(batch, "PIPELINE_STEPS", ["render"])
    monkeypatch.setattr(batch, "mark_step", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        batch,
        "_resolve_batch_step_timeout_strategy",
        lambda step_name: "process",
    )
    monkeypatch.setattr(
        batch,
        "_run_step_sync_with_timeout_in_process",
        lambda step_name, job_id, timeout_seconds: calls.append("process"),  # noqa: B008
    )
    monkeypatch.setattr(
        batch,
        "_run_step_sync_with_timeout_in_thread",
        lambda step_name, job_id, timeout_seconds: calls.append("thread"),  # noqa: B008
    )
    monkeypatch.setattr(batch, "read_step_detail", lambda job_id, step_name: "")
    monkeypatch.setattr(batch, "_resolve_batch_step_timeout_seconds", lambda step_name: 10.0)
    monkeypatch.setattr(
        batch,
        "finalize_job",
        lambda job_id, status, **kwargs: calls.append(f"finalize-{status}"),
    )
    monkeypatch.setattr(
        batch,
        "collect_job_report",
        fake_collect_job_report,
    )
    monkeypatch.setattr(
        batch,
        "stop_job_after_requested_step",
        lambda job_id, *, stopped_after: None,
    )

    result = batch.run_job("job-timeout", {"path": "E:/demo.mp4", "source_name": "demo.mp4"})

    assert result["status"] == "done"
    assert calls == ["process", "finalize-done"]


def test_run_job_step_timeout_marks_failed(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_collect_job_report(job_id, item, step_runs, status, *, stop_after=None):
        return {
            "job_id": job_id,
            "status": status,
            "step_count": len(step_runs),
        }

    monkeypatch.setenv("ROUGHCUT_BATCH_STEP_TIMEOUT_SECONDS", "1")
    monkeypatch.setattr(batch, "load_step_statuses", lambda job_id: {})
    monkeypatch.setattr(batch, "PIPELINE_STEPS", ["render"])
    monkeypatch.setattr(batch, "mark_step", lambda *args, **kwargs: calls.append(("mark", args[1], kwargs.get("status"))))
    monkeypatch.setattr(
        batch,
        "run_step_sync",
        lambda step_name, job_id: time.sleep(2),
    )
    monkeypatch.setattr(batch, "read_step_detail", lambda job_id, step_name: "")
    monkeypatch.setattr(
        batch,
        "finalize_job",
        lambda job_id, status, **kwargs: calls.append(("finalize", status)),
    )
    monkeypatch.setattr(
        batch,
        "stop_job_after_requested_step",
        lambda job_id, *, stopped_after: calls.append(("stop", stopped_after)),
    )
    monkeypatch.setattr(batch, "collect_job_report", fake_collect_job_report)

    result = batch.run_job("job-timeout", {"path": "E:/timeout.mp4", "source_name": "timeout.mp4"})

    assert result["status"] == "failed"
    assert any(item[0] == "finalize" and item[1] == "failed" for item in calls)


def test_run_job_step_timeout_records_execution_metadata(monkeypatch) -> None:
    calls: list[tuple[str, str, str | None, bool, dict | None]] = []

    async def fake_collect_job_report(job_id, item, step_runs, status, *, stop_after=None):
        return {
            "job_id": job_id,
            "status": status,
            "step_count": len(step_runs),
        }

    timeout_exc = TimeoutError("步骤 render 执行超过 1.0 秒")
    setattr(
        timeout_exc,
        "__batch_step_execution_metadata__",
        {
            "sync_runner_timeout_strategy": "process",
            "sync_runner_timeout_seconds": 1.0,
            "sync_runner_reap_method": "terminate",
            "sync_runner_worker_pid": 12345,
            "sync_runner_process_exit_code": 123,
        },
    )

    def fake_mark_step(
        job_id: str,
        step_name: str,
        status: str,
        *,
        error: str | None = None,
        terminal_failure: bool = False,
        metadata_updates: dict | None = None,
    ) -> None:
        calls.append((step_name, status, error, terminal_failure, metadata_updates))

    def fake_timeout_runner(step_name: str, job_id: str, timeout_seconds: float) -> None:
        raise timeout_exc

    monkeypatch.setattr(batch, "load_step_statuses", lambda job_id: {})
    monkeypatch.setattr(batch, "PIPELINE_STEPS", ["render"])
    monkeypatch.setattr(batch, "mark_step", fake_mark_step)
    monkeypatch.setattr(batch, "read_step_detail", lambda job_id, step_name: "")
    monkeypatch.setattr(batch, "_run_step_sync_with_timeout", fake_timeout_runner)
    monkeypatch.setattr(
        batch,
        "finalize_job",
        lambda job_id, status, **kwargs: calls.append(("finalize", status, kwargs.get("error"), False, None)),
    )
    monkeypatch.setattr(batch, "collect_job_report", fake_collect_job_report)
    monkeypatch.setattr(batch, "stop_job_after_requested_step", lambda job_id, *, stopped_after: None)

    result = batch.run_job("job-timeout-metadata", {"path": "E:/timeout.mp4", "source_name": "timeout.mp4"})

    assert result["status"] == "failed"
    failed_calls = [item for item in calls if item[0] == "render" and item[1] == "failed"]
    assert len(failed_calls) == 1
    assert failed_calls[0] == (
        "render",
        "failed",
        "TimeoutError: 步骤 render 执行超过 1.0 秒",
        True,
        {
            "sync_runner_timeout_strategy": "process",
            "sync_runner_timeout_seconds": 1.0,
            "sync_runner_reap_method": "terminate",
            "sync_runner_worker_pid": 12345,
            "sync_runner_process_exit_code": 123,
        },
    )


def test_build_step_sync_runner_metadata_filters_sync_fields() -> None:
    class _DummyStep:
        def __init__(self, step_name: str, metadata: dict[str, object]) -> None:
            self.step_name = step_name
            self.metadata_ = metadata

    steps = [
        _DummyStep(
            "render",
            {
                "sync_runner_timeout_strategy": "process",
                "sync_runner_reap_method": "kill",
                "detail": "步骤超时",
            },
        ),
        _DummyStep("probe", {"detail": "ok"}),
        _DummyStep("edit", {"sync_runner_process_exit_code": 123, "other": "ignore"}),
    ]

    assert batch._build_step_sync_runner_metadata(steps) == {
        "render": {
            "sync_runner_timeout_strategy": "process",
            "sync_runner_reap_method": "kill",
        },
        "edit": {
            "sync_runner_process_exit_code": 123,
        },
    }


def test_render_markdown_includes_step_sync_runner_metadata() -> None:
    summary = {
        "created_at": "2026-06-10T00:00:00Z",
        "source_dir": "E:/watch",
        "channel_profile": "edc_tactical",
        "language": "zh-CN",
        "output_dir": None,
        "enhancement_modes": [],
        "job_count": 1,
        "success_count": 1,
        "partial_count": 0,
        "failed_count": 0,
        "jobs": [
            {
                "source_name": "demo.mp4",
                "status": "failed",
                "output_path": None,
                "cover_path": None,
                "output_duration_sec": 0.0,
                "transcript_segment_count": 0,
                "subtitle_count": 0,
                "correction_count": 0,
                "keep_ratio": 0.0,
                "cover_variant_count": 0,
                "quality_score": None,
                "quality_grade": None,
                "quality_issue_codes": [],
                "live_stage_validations": [],
                "content_profile": None,
                "render_diagnostics": {
                    "avatar_result": {
                        "status": "degraded",
                        "reason": "avatar_full_track_call_timeout",
                        "retryable": True,
                        "detail": "数字人超时，已回退普通成片",
                        "error_metadata": {"call_timeout_seconds": 45.0},
                    },
                    "render_step": {
                        "status": "failed",
                        "error": "TimeoutError: 步骤 render 执行超过 1.0 秒",
                        "sync_runner": {
                            "sync_runner_timeout_strategy": "process",
                            "sync_runner_reap_method": "terminate",
                        },
                    },
                },
                "step_sync_runner_metadata": {
                    "render": {
                        "sync_runner_timeout_strategy": "process",
                        "sync_runner_reap_method": "terminate",
                        "sync_runner_process_exit_code": 123,
                    }
                },
                "steps": [
                    {
                        "step": "render",
                        "status": "failed",
                        "elapsed_seconds": 1.0,
                        "detail": "render执行",
                        "error": "TimeoutError: 步骤 render 执行超过 1.0 秒",
                    }
                ],
                "notes": [],
            }
        ],
    }

    content = batch.render_markdown(summary)

    assert "sync_runner={sync_runner_process_exit_code=123, sync_runner_reap_method=terminate, sync_runner_timeout_strategy=process}" in content
    assert "render_avatar: status=degraded" in content
    assert "reason=avatar_full_track_call_timeout" in content
    assert "retryable=True" in content
    assert 'error_metadata={"call_timeout_seconds": 45.0}' in content
    assert 'render_step: status=failed, error=TimeoutError: 步骤 render 执行超过 1.0 秒, sync_runner={"sync_runner_reap_method": "terminate", "sync_runner_timeout_strategy": "process"}' in content


def test_build_render_diagnostics_preserves_avatar_reason_and_sync_runner() -> None:
    class _DummyStep:
        def __init__(self, step_name: str, status: str, error_message: str, metadata: dict[str, object]) -> None:
            self.step_name = step_name
            self.status = status
            self.error_message = error_message
            self.metadata_ = metadata

    diagnostics = batch._build_render_diagnostics(
        {
            "avatar_result": {
                "status": "degraded",
                "reason": "avatar_full_track_busy_exhausted",
                "detail": "busy 重试耗尽",
                "retryable": True,
                "error_metadata": {"busy_wait_seconds": 900.0},
            }
        },
        [
            _DummyStep(
                "render",
                "failed",
                "TimeoutError: render timeout",
                {
                    "detail": "render timeout",
                    "sync_runner_timeout_strategy": "process",
                    "sync_runner_process_exit_code": 123,
                },
            )
        ],
    )

    assert diagnostics == {
        "avatar_result": {
            "status": "degraded",
            "reason": "avatar_full_track_busy_exhausted",
            "reason_category": "busy_exhausted",
            "detail": "busy 重试耗尽",
            "retryable": True,
            "error_metadata": {"busy_wait_seconds": 900.0},
        },
        "render_step": {
            "status": "failed",
            "detail": "render timeout",
            "error": "TimeoutError: render timeout",
            "reason": "render_timeout_process",
            "issue_codes": ["render_timeout"],
            "sync_runner": {
                "sync_runner_timeout_strategy": "process",
                "sync_runner_process_exit_code": 123,
            },
        },
    }


def test_classify_render_failure_reason_distinguishes_thread_timeout() -> None:
    reason, issue_codes = batch._classify_render_failure_reason(
        error="TimeoutError: 步骤 render 执行超过 30.0 秒",
        detail="TimeoutError: 步骤 render 执行超过 30.0 秒",
        sync_runner={"sync_runner_timeout_strategy": "thread", "sync_runner_timeout_seconds": 30.0},
    )

    assert reason == "render_timeout_thread"
    assert issue_codes == ["render_timeout"]


def test_build_render_diagnostics_classifies_non_avatar_render_failures_and_ignores_cover_status() -> None:
    class _DummyStep:
        def __init__(self, step_name: str, status: str, error_message: str, metadata: dict[str, object]) -> None:
            self.step_name = step_name
            self.status = status
            self.error_message = error_message
            self.metadata_ = metadata

    diagnostics = batch._build_render_diagnostics(
        {
            "cover_result": {
                "status": "degraded",
                "reason": "cover_export_failed",
                "detail": "封面导出失败，成片已保留但未产出封面图。",
            }
        },
        [
            _DummyStep(
                "render",
                "failed",
                "RuntimeError: render_variant_sync_blocked: packaged subtitle drift",
                {"detail": "render failed"},
            )
        ],
    )

    assert diagnostics == {
        "render_step": {
            "status": "failed",
            "detail": "render failed",
            "error": "RuntimeError: render_variant_sync_blocked: packaged subtitle drift",
            "reason": "render_variant_sync_blocked",
            "issue_codes": ["subtitle_sync_issue"],
        },
    }


def test_build_render_diagnostics_does_not_mark_done_render_as_failed() -> None:
    class _DummyStep:
        def __init__(self, step_name: str, status: str, error_message: str, metadata: dict[str, object]) -> None:
            self.step_name = step_name
            self.status = status
            self.error_message = error_message
            self.metadata_ = metadata

    diagnostics = batch._build_render_diagnostics(
        {
            "cover_result": {
                "status": "done",
                "detail": "封面图已生成。",
                "variant_count": 5,
            }
        },
        [
            _DummyStep(
                "render",
                "done",
                "",
                {"detail": "检测到已完成渲染输出，调度器已自动收口 render 步骤。"},
            )
        ],
    )

    assert diagnostics == {
        "render_step": {
            "status": "done",
            "detail": "检测到已完成渲染输出，调度器已自动收口 render 步骤。",
        },
    }


def test_normalize_cover_render_result_for_reporting_keeps_current_summary_shape() -> None:
    summary = batch._normalize_cover_render_result_for_reporting(
        {
            "status": "done",
            "detail": "封面图已生成。",
            "cover_path": "E:/cover.png",
            "variant_count": 5,
            "selection_review_recommended": True,
            "ignored": "noop",
        }
    )

    assert summary == {
        "status": "done",
        "detail": "封面图已生成。",
        "cover_path": "E:/cover.png",
        "variant_count": 5,
        "selection_review_recommended": True,
    }


def test_build_render_diagnostics_adds_avatar_reason_category_for_provider_errors() -> None:
    class _DummyStep:
        def __init__(self, step_name: str, status: str, error_message: str, metadata: dict[str, object]) -> None:
            self.step_name = step_name
            self.status = status
            self.error_message = error_message
            self.metadata_ = metadata

    diagnostics = batch._build_render_diagnostics(
        {
            "avatar_result": {
                "status": "degraded",
                "reason": "avatar_full_track_provider_response_error",
                "detail": "provider 500",
                "retryable": False,
            }
        },
        [_DummyStep("render", "done", "", {"detail": "render recovered to plain output"})],
    )

    assert diagnostics["avatar_result"]["reason_category"] == "provider_error"


def test_normalize_render_diagnostics_for_reporting_adds_avatar_reason_category() -> None:
    diagnostics = batch._normalize_render_diagnostics_for_reporting(
        {
            "avatar_result": {
                "status": "degraded",
                "reason": "avatar_full_track_call_timeout",
                "detail": "call timeout",
                "retryable": True,
            }
        }
    )

    assert diagnostics["avatar_result"] == {
        "status": "degraded",
        "reason": "avatar_full_track_call_timeout",
        "reason_category": "call_timeout",
        "detail": "call timeout",
        "retryable": True,
    }


def test_normalize_render_step_summary_for_reporting_classifies_timeout_and_strips_done_fields() -> None:
    failed = batch._normalize_render_step_summary_for_reporting(
        {
            "status": "failed",
            "detail": "TimeoutError: 步骤 render 执行超过 300.0 秒",
            "error": "TimeoutError: 步骤 render 执行超过 300.0 秒",
            "reason": "render_failed",
            "sync_runner": {
                "sync_runner_timeout_strategy": "process",
                "sync_runner_timeout_seconds": 300.0,
            },
        }
    )
    done = batch._normalize_render_step_summary_for_reporting(
        {
            "status": "done",
            "detail": "ok",
            "reason": "render_failed",
            "issue_codes": ["render_failed"],
        }
    )

    assert failed["reason"] == "render_timeout_process"
    assert failed["issue_codes"] == ["render_timeout"]
    assert done == {"status": "done", "detail": "ok"}


def test_merge_render_runtime_payloads_preserves_runtime_avatar_and_ignores_cover_facts() -> None:
    merged = batch._merge_render_runtime_payloads(
        {
            "packaged_mp4": "E:/demo.mp4",
            "avatar_result": {"status": "pending", "detail": "等待渲染阶段处理数字人口播。"},
        },
        {
            "avatar_result": {
                "status": "degraded",
                "reason": "avatar_full_track_call_timeout",
                "detail": "数字人渲染未完成，已自动回退普通成片：avatar_full_track_call_timeout>180.0s",
            },
            "cover_result": {
                "status": "degraded",
                "reason": "cover_export_failed",
                "detail": "封面导出失败，成片已保留但未产出封面图。",
            },
        },
    )

    assert merged == {
        "packaged_mp4": "E:/demo.mp4",
        "avatar_result": {
            "status": "degraded",
            "reason": "avatar_full_track_call_timeout",
            "detail": "数字人渲染未完成，已自动回退普通成片：avatar_full_track_call_timeout>180.0s",
        },
    }


def test_build_live_stage_validations_marks_downstream_stages_skipped_for_partial_stop() -> None:
    validations = batch.build_live_stage_validations(
        step_statuses={
            "probe": "done",
            "transcribe": "done",
            "subtitle_postprocess": "done",
            "content_profile": "done",
            "edit_plan": "pending",
            "render": "pending",
        },
        step_details={},
        step_errors={},
        step_metadata={},
        run_status="partial",
        stop_after="content_profile",
        transcript_segment_count=3,
        subtitle_count=12,
        keep_ratio=0.0,
        profile={"summary": "ok"},
        platform_doc=None,
        subtitle_quality_report=None,
        subtitle_term_resolution_patch=None,
        subtitle_consistency_report=None,
        quality_assessment={},
    )

    by_stage = {item.stage: item for item in validations}
    assert by_stage["content_profile"].status == "pass"
    assert by_stage["edit_plan"].status == "skipped"
    assert by_stage["render"].status == "skipped"
    assert "platform_package" not in by_stage
    assert "final_review" not in by_stage


def test_build_live_stage_validations_accepts_frozen_profile_when_content_profile_step_is_stale() -> None:
    validations = batch.build_live_stage_validations(
        step_statuses={
            "probe": "done",
            "transcribe": "done",
            "subtitle_postprocess": "done",
            "content_profile": "cancelled",
            "summary_review": "done",
            "edit_plan": "done",
        },
        step_details={},
        step_errors={},
        step_metadata={},
        run_status="partial",
        stop_after="edit_plan",
        transcript_segment_count=3,
        subtitle_count=12,
        keep_ratio=1.0,
        profile={"summary": "ok", "review_mode": "manual_confirmed"},
        platform_doc=None,
        subtitle_quality_report=None,
        subtitle_term_resolution_patch=None,
        subtitle_consistency_report=None,
        quality_assessment={},
    )

    by_stage = {item.stage: item for item in validations}
    assert by_stage["content_profile"].status == "pass"
    assert by_stage["content_profile"].issue_codes == []
    assert by_stage["summary_review"].status == "pass"


def test_build_live_stage_validations_treats_no_audio_zero_output_as_pass() -> None:
    validations = batch.build_live_stage_validations(
        step_statuses={
            "probe": "done",
            "transcribe": "done",
            "subtitle_postprocess": "done",
            "content_profile": "done",
        },
        step_details={
            "transcribe": "源视频无音轨，已跳过转写",
            "subtitle_postprocess": "字幕后处理完成，0 段 -> 0 条，纠正 0 条，用时 0.1s",
        },
        step_errors={},
        step_metadata={},
        run_status="partial",
        stop_after="content_profile",
        transcript_segment_count=0,
        subtitle_count=0,
        keep_ratio=0.0,
        profile={"summary": "ok"},
        platform_doc=None,
        subtitle_quality_report=None,
        subtitle_term_resolution_patch=None,
        subtitle_consistency_report=None,
        quality_assessment={},
    )

    by_stage = {item.stage: item for item in validations}
    assert by_stage["transcribe"].status == "pass"
    assert by_stage["subtitle_postprocess"].status == "pass"


def test_build_live_stage_validations_treats_completed_zero_transcript_and_subtitles_as_warning() -> None:
    validations = batch.build_live_stage_validations(
        step_statuses={
            "probe": "done",
            "transcribe": "done",
            "subtitle_postprocess": "done",
            "content_profile": "done",
        },
        step_details={
            "transcribe": "转写完成，共 0 段",
            "subtitle_postprocess": "字幕后处理完成，0 段 -> 0 条，纠正 0 条，用时 0.1s",
        },
        step_errors={},
        step_metadata={},
        run_status="partial",
        stop_after="content_profile",
        transcript_segment_count=0,
        subtitle_count=0,
        keep_ratio=0.0,
        profile={"summary": "ok"},
        platform_doc=None,
        subtitle_quality_report=None,
        subtitle_term_resolution_patch=None,
        subtitle_consistency_report=None,
        quality_assessment={},
    )

    by_stage = {item.stage: item for item in validations}
    assert by_stage["transcribe"].status == "warn"
    assert by_stage["subtitle_postprocess"].status == "warn"


def test_build_live_stage_validations_surfaces_probe_root_cause() -> None:
    validations = batch.build_live_stage_validations(
        step_statuses={
            "probe": "failed",
            "transcribe": "pending",
            "subtitle_postprocess": "pending",
            "content_profile": "pending",
        },
        step_details={
            "probe": "下载源视频并准备探测媒体参数",
        },
        step_errors={
            "probe": "FileNotFoundError: E:/missing/demo.mp4",
        },
        step_metadata={},
        run_status="failed",
        stop_after=None,
        transcript_segment_count=0,
        subtitle_count=0,
        keep_ratio=0.0,
        profile=None,
        platform_doc=None,
        subtitle_quality_report=None,
        subtitle_term_resolution_patch=None,
        subtitle_consistency_report=None,
        quality_assessment={},
    )

    by_stage = {item.stage: item for item in validations}
    assert by_stage["probe"].status == "fail"
    assert "FileNotFoundError" in by_stage["probe"].summary
    assert by_stage["probe"].issue_codes == ["source_file_missing"]
    assert by_stage["transcribe"].status == "skipped"
    assert "上游 probe 失败未执行" in by_stage["transcribe"].summary


def test_build_live_stage_validations_surfaces_edit_plan_audio_rebuild_as_warning() -> None:
    validations = batch.build_live_stage_validations(
        step_statuses={
            "probe": "done",
            "transcribe": "done",
            "subtitle_postprocess": "done",
            "content_profile": "done",
            "summary_review": "done",
            "edit_plan": "done",
        },
        step_details={
            "edit_plan": "音频派生文件缺失，正在从源视频重新提取",
        },
        step_errors={},
        step_metadata={
            "edit_plan": {
                "audio_artifact_rebuilt": True,
            }
        },
        run_status="partial",
        stop_after="edit_plan",
        transcript_segment_count=1,
        subtitle_count=12,
        keep_ratio=1.0,
        profile={"summary": "ok"},
        platform_doc=None,
        subtitle_quality_report=None,
        subtitle_term_resolution_patch=None,
        subtitle_consistency_report=None,
        quality_assessment={},
    )

    by_stage = {item.stage: item for item in validations}
    assert by_stage["edit_plan"].status == "pass"
    assert "音频派生文件缺失" in by_stage["edit_plan"].summary
    assert by_stage["edit_plan"].issue_codes == ["audio_artifact_rebuilt"]


def test_compute_effective_keep_ratio_prefers_refine_plan_keep_segments() -> None:
    ratio = batch.compute_effective_keep_ratio(
        {
            "segments": [
                {"type": "keep", "start": 0.0, "end": 10.0},
            ]
        },
        refine_decision_plan={
            "editorial_timeline_id": "tl-1",
            "editorial_timeline_version": 3,
            "keep_segments": [
                {"start": 0.0, "end": 4.0},
                {"start": 6.0, "end": 10.0},
            ],
        },
        editorial_timeline_id="tl-1",
        editorial_timeline_version=3,
    )

    assert ratio == 0.8


def test_live_readiness_treats_partial_golden_runs_as_non_blocking_when_no_failed_stages() -> None:
    readiness = build_live_readiness_summary(
        {
            "jobs": [
                {
                    "source_name": "demo.mp4",
                    "status": "partial",
                    "output_path": "",
                    "output_duration_sec": 0.0,
                    "quality_score": 88.0,
                    "quality_issue_codes": [],
                    "live_stage_validations": [
                        {"stage": "transcribe", "status": "pass", "summary": "ok", "issue_codes": []},
                        {"stage": "content_profile", "status": "pass", "summary": "ok", "issue_codes": []},
                        {"stage": "edit_plan", "status": "skipped", "summary": "skipped", "issue_codes": []},
                    ],
                }
            ]
        },
        golden_source_names=["demo.mp4"],
        previous_summaries=[],
        required_stable_runs=1,
    )

    assert readiness.checks["golden_success_rate"]["passed"] is True
    assert readiness.checks["p0_blockers"]["passed"] is True


def test_live_readiness_relaxes_stable_run_requirement_for_stop_after_partial_replay() -> None:
    readiness = build_live_readiness_summary(
        {
            "stop_after": "edit_plan",
            "jobs": [
                {
                    "source_name": "demo.mp4",
                    "status": "partial",
                    "output_path": "",
                    "output_duration_sec": 0.0,
                    "quality_score": 88.0,
                    "quality_issue_codes": [],
                    "live_stage_validations": [
                        {"stage": "transcribe", "status": "pass", "summary": "ok", "issue_codes": []},
                        {"stage": "content_profile", "status": "pass", "summary": "ok", "issue_codes": []},
                        {"stage": "edit_plan", "status": "pass", "summary": "ok", "issue_codes": []},
                        {"stage": "render", "status": "skipped", "summary": "render 因 stop_after 未执行", "issue_codes": []},
                    ],
                }
            ],
        },
        golden_source_names=["demo.mp4"],
        previous_summaries=[],
        required_stable_runs=3,
    )

    assert readiness.checks["stable_runs"]["actual"] == 1
    assert readiness.checks["stable_runs"]["required"] == 1
    assert readiness.checks["stable_runs"]["passed"] is True
    assert readiness.required_stable_runs == 1
    assert all("连续稳定批次不足" not in item for item in readiness.failure_reasons)


def test_live_readiness_fails_when_required_checks_contract_not_all_passed() -> None:
    summary = {
        "jobs": [
            {
                "source_name": "demo.mp4",
                "status": "done",
                "output_path": "E:/out.mp4",
                "output_duration_sec": 12.3,
                "quality_score": 90.0,
                "quality_issue_codes": [],
                "live_stage_validations": [
                    {"stage": "manual_editor_ready", "status": "pass", "summary": "ok", "issue_codes": []},
                    {"stage": "subtitle_projection", "status": "warn", "summary": "warn", "issue_codes": []},
                ],
            }
        ],
        "required_checks": {
            "required_checks_contract_passed": 1,
            "required_checks_contract_failed": 1,
            "required_checks_case_passed": 0,
            "required_checks_case_failed": 1,
            "required_checks_total": 2,
            "required_checks_failed_case_ids": ["demo.mp4"],
            "required_checks_contract_pass_rate": 0.5,
        },
    }

    readiness = build_live_readiness_summary(
        summary,
        golden_source_names=["demo.mp4"],
        previous_summaries=[],
        required_stable_runs=1,
        required_success_rate=0.0,
        required_average_quality=0.0,
    )

    assert readiness.checks["required_checks_contract"]["passed"] is False
    assert readiness.checks["required_checks_contract"]["failed_required_checks"] == 1
    assert any("required_checks" in item for item in readiness.failure_reasons)


def test_live_readiness_backfills_required_checks_summary_from_case_rows() -> None:
    summary = {
        "jobs": [
            {
                "source_name": "demo.mp4",
                "status": "done",
                "output_path": "E:/out.mp4",
                "output_duration_sec": 12.3,
                "quality_score": 90.0,
                "quality_issue_codes": [],
                "live_stage_validations": [],
            }
        ],
        "golden_case_rows": [
            {
                "case_id": "case-a",
                "required_checks": ["manual_editor_ready", "subtitle_projection"],
                "required_checks_failed": ["subtitle_projection"],
            }
        ],
    }

    readiness = build_live_readiness_summary(
        summary,
        golden_source_names=["demo.mp4"],
        previous_summaries=[],
        required_stable_runs=1,
        required_success_rate=0.0,
        required_average_quality=0.0,
    )

    assert readiness.checks["required_checks_contract"]["passed"] is False
    assert readiness.checks["required_checks_contract"]["failed_required_checks"] == 1
    assert readiness.checks["required_checks_contract"]["failed_required_case_ids"] == ["case-a"]
    assert any("required_checks" in item for item in readiness.failure_reasons)


def test_live_readiness_fails_when_manual_editor_apply_semantics_contract_not_all_passed() -> None:
    summary = {
        "jobs": [
            {
                "source_name": "demo.mp4",
                "status": "done",
                "output_path": "E:/out.mp4",
                "output_duration_sec": 12.3,
                "quality_score": 90.0,
                "quality_issue_codes": [],
                "live_stage_validations": [],
            }
        ],
        "golden_case_rows": [
            {
                "case_id": "case-a",
                "required_checks": ["manual_editor_apply_semantics"],
                "manual_editor_apply_semantics_ok": False,
            }
        ],
    }

    readiness = build_live_readiness_summary(
        summary,
        golden_source_names=["demo.mp4"],
        previous_summaries=[],
        required_stable_runs=1,
        required_success_rate=0.0,
        required_average_quality=0.0,
    )

    assert readiness.checks["manual_editor_apply_semantics_contract"]["passed"] is False
    assert readiness.checks["manual_editor_apply_semantics_contract"]["failed_case_count"] == 1
    assert any("manual_editor_apply_semantics" in item for item in readiness.failure_reasons)


def test_live_readiness_prefers_case_rows_over_stale_manual_editor_semantics_summary() -> None:
    summary = {
        "jobs": [
            {
                "source_name": "demo.mp4",
                "status": "done",
                "output_path": "E:/out.mp4",
                "output_duration_sec": 12.3,
                "quality_score": 90.0,
                "quality_issue_codes": [],
                "live_stage_validations": [],
            }
        ],
        "manual_editor_apply_semantics_summary": {
            "total_cases": 1,
            "passed_case_count": 1,
            "failed_case_count": 0,
            "failed_case_ids": [],
            "pass_rate": 1.0,
        },
        "golden_case_rows": [
            {
                "case_id": "case-a",
                "required_checks": ["manual_editor_apply_semantics"],
                "manual_editor_apply_semantics_ok": False,
            }
        ],
    }

    readiness = build_live_readiness_summary(
        summary,
        golden_source_names=["demo.mp4"],
        previous_summaries=[],
        required_stable_runs=1,
        required_success_rate=0.0,
        required_average_quality=0.0,
    )

    assert readiness.checks["manual_editor_apply_semantics_contract"]["passed"] is False
    assert readiness.checks["manual_editor_apply_semantics_contract"]["failed_case_count"] == 1
    assert readiness.checks["manual_editor_apply_semantics_contract"]["failed_case_ids"] == ["case-a"]


def test_live_readiness_ignores_manual_editor_apply_semantics_for_cases_without_required_check() -> None:
    summary = {
        "jobs": [
            {
                "source_name": "demo.mp4",
                "status": "done",
                "output_path": "E:/out.mp4",
                "output_duration_sec": 12.3,
                "quality_score": 90.0,
                "quality_issue_codes": [],
                "live_stage_validations": [],
            }
        ],
        "golden_case_rows": [
            {
                "case_id": "case-a",
                "required_checks": ["subtitle_projection"],
                "manual_editor_apply_semantics_ok": False,
            }
        ],
    }

    readiness = build_live_readiness_summary(
        summary,
        golden_source_names=["demo.mp4"],
        previous_summaries=[],
        required_stable_runs=1,
        required_success_rate=0.0,
        required_average_quality=0.0,
    )

    assert "manual_editor_apply_semantics_contract" not in readiness.checks
    assert all("manual_editor_apply_semantics" not in item for item in readiness.failure_reasons)


def test_live_readiness_fails_when_render_end_state_stability_not_met() -> None:
    summary = {
        "jobs": [
            {
                "job_id": "job-render-fail",
                "source_name": "demo.mp4",
                "status": "done",
                "output_path": "E:/out.mp4",
                "output_duration_sec": 12.3,
                "quality_score": 90.0,
                "quality_issue_codes": [],
                "live_stage_validations": [],
                "render_diagnostics": {
                    "render_step": {
                        "status": "failed",
                        "reason": "render_failed",
                    },
                    "cover_result": {
                        "status": "degraded",
                        "reason": "cover_export_failed",
                    },
                },
            }
        ],
    }

    readiness = build_live_readiness_summary(
        summary,
        golden_source_names=["demo.mp4"],
        previous_summaries=[],
        required_stable_runs=1,
        required_success_rate=0.0,
        required_average_quality=0.0,
    )

    assert readiness.checks["render_end_state_stability"]["passed"] is False
    assert readiness.checks["render_end_state_stability"]["actual"] == 1
    assert readiness.checks["render_end_state_stability"]["cover_degraded_job_count"] == 0


def test_live_readiness_extract_render_diagnostics_summary_preserves_reason_counts() -> None:
    readiness = build_live_readiness_summary(
        {
            "job_count": 1,
            "jobs": [],
            "render_diagnostics_summary": {
                "evaluated_job_count": 1,
                "failed_render_job_count": 1,
                "failed_render_job_ids": ["job-render"],
                "failed_render_reasons": {"render_failed": 1},
                "cover_degraded_job_count": 0,
                "cover_degraded_job_ids": [],
                "cover_degraded_reasons": {},
                "avatar_degraded_job_count": 1,
                "avatar_degraded_job_ids": ["job-render"],
                "avatar_degraded_reasons": {"avatar_full_track_call_timeout": 1},
                "avatar_degraded_reason_categories": {"call_timeout": 1},
            },
        }
    )

    assert readiness.checks["render_end_state_stability"]["passed"] is False
    assert readiness.checks["render_end_state_stability"]["failed_render_job_count"] == 1
    assert readiness.checks["render_end_state_stability"]["failed_render_reasons"] == {"render_failed": 1}
    assert readiness.checks["render_end_state_stability"]["avatar_degraded_job_count"] == 1
    assert readiness.checks["render_end_state_stability"]["avatar_degraded_reasons"] == {
        "avatar_full_track_call_timeout": 1
    }
    assert readiness.checks["render_end_state_stability"]["avatar_degraded_reason_categories"] == {
        "call_timeout": 1
    }
    assert any("render 终态稳定性" in item for item in readiness.failure_reasons)
    assert any("数字人降级" in item for item in readiness.warning_reasons)


def test_live_readiness_backfills_render_reason_counts_from_jobs_when_summary_is_legacy() -> None:
    readiness = build_live_readiness_summary(
        {
            "job_count": 1,
            "jobs": [
                {
                    "job_id": "job-render",
                    "source_name": "demo.mp4",
                    "render_diagnostics": {
                        "render_step": {"status": "failed", "reason": "render_failed"},
                        "avatar_result": {
                            "status": "degraded",
                            "reason": "avatar_full_track_call_timeout",
                            "reason_category": "call_timeout",
                        },
                    },
                }
            ],
            "render_diagnostics_summary": {
                "evaluated_job_count": 1,
                "failed_render_job_count": 1,
                "failed_render_job_ids": ["job-render"],
                "cover_degraded_job_count": 0,
                "cover_degraded_job_ids": [],
                "avatar_degraded_job_count": 1,
                "avatar_degraded_job_ids": ["job-render"],
            },
        }
    )

    assert readiness.checks["render_end_state_stability"]["failed_render_reasons"] == {"render_failed": 1}
    assert readiness.checks["render_end_state_stability"]["avatar_degraded_reasons"] == {
        "avatar_full_track_call_timeout": 1
    }
    assert readiness.checks["render_end_state_stability"]["avatar_degraded_reason_categories"] == {
        "call_timeout": 1
    }


def test_live_readiness_normalizes_legacy_timeout_reason_from_job_render_diagnostics() -> None:
    readiness = build_live_readiness_summary(
        {
            "job_count": 1,
            "jobs": [
                {
                    "job_id": "job-render",
                    "source_name": "demo.mp4",
                    "render_diagnostics": {
                        "render_step": {
                            "status": "failed",
                            "reason": "render_failed",
                            "detail": "TimeoutError: 步骤 render 执行超过 300.0 秒",
                            "error": "TimeoutError: 步骤 render 执行超过 300.0 秒",
                            "sync_runner": {
                                "sync_runner_timeout_strategy": "process",
                                "sync_runner_timeout_seconds": 300.0,
                            },
                        },
                    },
                }
            ],
            "render_diagnostics_summary": {
                "evaluated_job_count": 1,
                "failed_render_job_count": 1,
                "failed_render_job_ids": ["job-render"],
                "failed_render_reasons": {"render_failed": 1},
            },
        }
    )

    assert readiness.checks["render_end_state_stability"]["failed_render_reasons"] == {
        "render_timeout_process": 1
    }


def test_live_readiness_normalizes_legacy_ffmpeg_reason_from_job_render_diagnostics() -> None:
    readiness = build_live_readiness_summary(
        {
            "job_count": 1,
            "jobs": [
                {
                    "job_id": "job-ffmpeg-render",
                    "source_name": "demo.mp4",
                    "render_diagnostics": {
                        "render_step": {
                            "status": "failed",
                            "reason": "render_failed",
                            "detail": "FFmpeg render failed: filter graph error",
                            "error": "FFmpeg render failed: filter graph error",
                            "sync_runner": {},
                        },
                    },
                }
            ],
            "render_diagnostics_summary": {
                "evaluated_job_count": 1,
                "failed_render_job_count": 1,
                "failed_render_job_ids": ["job-ffmpeg-render"],
                "failed_render_reasons": {"render_failed": 1},
            },
        }
    )

    assert readiness.checks["render_end_state_stability"]["failed_render_reasons"] == {
        "ffmpeg_render_failed": 1
    }


def test_live_readiness_prefers_normalized_job_render_counts_over_stale_legacy_summary() -> None:
    readiness = build_live_readiness_summary(
        {
            "job_count": 1,
            "jobs": [
                {
                    "job_id": "job-render-done",
                    "source_name": "done.mp4",
                    "render_diagnostics": {
                        "render_step": {
                            "status": "done",
                            "detail": "render recovered",
                            "reason": "render_failed",
                            "issue_codes": ["render_failed"],
                        },
                        "cover_result": {
                            "status": "done",
                            "detail": "cover generated",
                        },
                    },
                }
            ],
            "render_diagnostics_summary": {
                "evaluated_job_count": 1,
                "failed_render_job_count": 1,
                "failed_render_job_ids": ["job-render-done"],
                "failed_render_reasons": {"render_failed": 1},
                "cover_degraded_job_count": 0,
                "cover_degraded_job_ids": [],
                "cover_degraded_reasons": {},
                "avatar_degraded_job_count": 0,
                "avatar_degraded_job_ids": [],
                "avatar_degraded_reasons": {},
                "avatar_degraded_reason_categories": {},
            },
        }
    )

    assert readiness.checks["render_end_state_stability"]["failed_render_job_count"] == 0
    assert readiness.checks["render_end_state_stability"]["failed_render_job_ids"] == []
    assert readiness.checks["render_end_state_stability"]["failed_render_reasons"] == {}


def test_live_readiness_fails_when_blocking_quality_issue_codes_exist() -> None:
    summary = {
        "jobs": [
            {
                "job_id": "job-quality-block",
                "source_name": "demo.mp4",
                "status": "done",
                "output_path": "E:/out.mp4",
                "output_duration_sec": 12.3,
                "quality_score": 90.0,
                "quality_issue_codes": ["missing_subtitles", "subtitle_semantic_contamination"],
                "live_stage_validations": [],
            }
        ],
    }

    readiness = build_live_readiness_summary(
        summary,
        golden_source_names=["demo.mp4"],
        previous_summaries=[],
        required_stable_runs=1,
        required_success_rate=0.0,
        required_average_quality=0.0,
    )

    assert readiness.checks["blocking_quality_issues"]["passed"] is False
    assert readiness.checks["blocking_quality_issues"]["actual"] == 1
    assert readiness.checks["blocking_quality_issues"]["issue_code_counts"] == {
        "missing_subtitles": 1,
        "subtitle_semantic_contamination": 1,
    }
    assert any("blocking quality issues" in item for item in readiness.failure_reasons)


def test_live_readiness_fails_when_reference_risk_contract_is_incomplete() -> None:
    summary = {
        "jobs": [
            {
                "job_id": "job-risk-contract",
                "source_name": "demo.mp4",
                "status": "partial",
                "output_path": "",
                "output_duration_sec": 0.0,
                "quality_score": 90.0,
                "quality_issue_codes": [],
                "live_stage_validations": [],
            }
        ],
        "risk_alignment_summary": {
            "reference_high_risk_case_count": 0,
            "reproduced_case_count": 0,
            "unreproduced_case_count": 0,
            "mismatch_case_ids": ["case-risk"],
            "mismatch_code_counts": {
                "reference_risk_contract_incomplete": 1,
            },
        },
    }

    readiness = build_live_readiness_summary(
        summary,
        golden_source_names=["demo.mp4"],
        previous_summaries=[],
        required_stable_runs=1,
        required_success_rate=0.0,
        required_average_quality=0.0,
    )

    assert readiness.checks["risk_alignment_contract"]["passed"] is False
    assert readiness.checks["risk_alignment_contract"]["actual"] == 1
    assert readiness.checks["risk_alignment_contract"]["mismatch_code_counts"] == {
        "reference_risk_contract_incomplete": 1,
    }
    assert any("reference 风险合同未对齐" in item for item in readiness.failure_reasons)


def test_live_readiness_prefers_case_rows_over_stale_risk_alignment_summary() -> None:
    summary = {
        "jobs": [
            {
                "job_id": "job-risk-contract",
                "source_name": "demo.mp4",
                "status": "partial",
                "output_path": "",
                "output_duration_sec": 0.0,
                "quality_score": 90.0,
                "quality_issue_codes": [],
                "live_stage_validations": [],
            }
        ],
        "risk_alignment_summary": {
            "reference_high_risk_case_count": 0,
            "reproduced_case_count": 0,
            "unreproduced_case_count": 0,
            "mismatch_case_ids": [],
            "mismatch_code_counts": {},
        },
        "golden_case_rows": [
            {
                "case_id": "case-risk",
                "risk_alignment": {
                    "reference_high_risk_case_count": 0,
                    "high_risk_reproduced": False,
                    "mismatch_codes": ["reference_risk_contract_incomplete"],
                },
            }
        ],
    }

    readiness = build_live_readiness_summary(
        summary,
        golden_source_names=["demo.mp4"],
        previous_summaries=[],
        required_stable_runs=1,
        required_success_rate=0.0,
        required_average_quality=0.0,
    )

    assert readiness.checks["risk_alignment_contract"]["passed"] is False
    assert readiness.checks["risk_alignment_contract"]["mismatch_case_ids"] == ["case-risk"]
    assert readiness.checks["risk_alignment_contract"]["mismatch_code_counts"] == {
        "reference_risk_contract_incomplete": 1,
    }
