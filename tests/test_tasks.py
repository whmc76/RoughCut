from __future__ import annotations

from types import SimpleNamespace

import pytest

import roughcut.db.session as db_session
import roughcut.pipeline.tasks as tasks_mod
from roughcut.pipeline.tasks import _is_gpu_pressure_error, _reset_db_session_state


class _DummyEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


def test_reset_db_session_state_disposes_engine_and_clears_singletons():
    engine = _DummyEngine()
    session_factory = object()
    old_worker_mode = db_session._worker_mode

    db_session._engine = engine
    db_session._session_factory = session_factory
    try:
        _reset_db_session_state()
        assert engine.disposed is True
        assert db_session._engine is None
        assert db_session._session_factory is None
    finally:
        db_session._worker_mode = old_worker_mode


def test_is_gpu_pressure_error_detects_cuda_oom():
    assert _is_gpu_pressure_error(RuntimeError("CUDA out of memory while allocating tensor")) is True
    assert _is_gpu_pressure_error(RuntimeError("device or resource busy")) is True
    assert _is_gpu_pressure_error(RuntimeError("validation failed")) is False


def test_probe_local_gpu_pressure_reports_busy_gpu(monkeypatch):
    monkeypatch.setattr(tasks_mod, "get_settings", lambda: SimpleNamespace(
        gpu_retry_enabled=True,
        transcription_provider="faster_whisper",
        gpu_busy_utilization_threshold=92,
        gpu_busy_memory_threshold=0.92,
    ))
    monkeypatch.setattr(tasks_mod.shutil, "which", lambda name: "nvidia-smi" if name == "nvidia-smi" else None)
    monkeypatch.setattr(
        tasks_mod.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="0, 97, 22000, 24000\n"),
    )

    detail = tasks_mod._probe_local_gpu_pressure("transcribe")

    assert "GPU0" in detail
    assert "繁忙" in detail


def test_probe_local_gpu_pressure_allows_qwen_asr_resident_memory(monkeypatch):
    monkeypatch.setattr(tasks_mod, "get_settings", lambda: SimpleNamespace(
        gpu_retry_enabled=True,
        transcription_provider="qwen3_asr",
        gpu_busy_utilization_threshold=92,
        gpu_busy_memory_threshold=0.92,
    ))
    monkeypatch.setattr(tasks_mod.shutil, "which", lambda name: "nvidia-smi" if name == "nvidia-smi" else None)
    monkeypatch.setattr(
        tasks_mod.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="0, 5, 30780, 32607\n"),
    )

    detail = tasks_mod._probe_local_gpu_pressure("transcribe")

    assert detail is None


def test_run_task_step_retries_when_gpu_pressure_exception_occurs(monkeypatch):
    retry_calls: list[tuple[str, int]] = []
    status_updates: list[tuple[str, str]] = []

    class RetryTriggered(Exception):
        pass

    class DummyTask:
        request = SimpleNamespace(id="task-1", retries=1)

        def retry(self, *, exc, countdown):
            retry_calls.append((str(exc), countdown))
            raise RetryTriggered()

    monkeypatch.setattr(tasks_mod, "_update_step_status", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        tasks_mod,
        "_update_step_retry_waiting",
        lambda job_id, step_name, detail, *, countdown, task_id=None: status_updates.append((step_name, detail)) or True,
    )
    monkeypatch.setattr(tasks_mod, "_probe_local_gpu_pressure", lambda step_name: None)
    monkeypatch.setattr(tasks_mod, "get_settings", lambda: SimpleNamespace(
        gpu_retry_base_delay_sec=90,
        gpu_retry_max_delay_sec=900,
    ))
    monkeypatch.setattr(tasks_mod, "run_step_sync", lambda step_name, job_id: (_ for _ in ()).throw(RuntimeError("CUDA out of memory")))

    with pytest.raises(RetryTriggered):
        tasks_mod._run_task_step(DummyTask(), "job-1", "transcribe", retry_countdown=30)

    assert retry_calls
    assert retry_calls[0][1] == 180
    assert status_updates[0][0] == "transcribe"
    assert "GPU/资源繁忙" in status_updates[0][1]
