from __future__ import annotations

import uuid
import asyncio
import time
import warnings
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import roughcut.db.session as db_session
from roughcut.db.models import Job, JobStep
from roughcut.db.session import Base
from roughcut.pipeline import orchestrator
from roughcut.pipeline import steps
from roughcut.pipeline import tasks


@pytest.fixture()
def task_status_session_factory(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async def _setup() -> None:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        asyncio.run(_setup())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(db_session, "get_session_factory", lambda: session_factory)
        yield session_factory
    finally:
        asyncio.run(engine.dispose())


def test_update_step_status_ignores_missing_job(task_status_session_factory):
    missing_job_id = str(uuid.uuid4())

    assert not tasks._update_step_status(missing_job_id, "transcribe", "running", task_id="stale-task")


def test_reset_session_state_sync_disposes_cached_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeEngine:
        async def dispose(self) -> None:
            calls.append("disposed")

    async def fake_close_all_sessions() -> None:
        calls.append("close_all_sessions")

    monkeypatch.setattr(db_session, "_engine", FakeEngine())
    monkeypatch.setattr(db_session, "_engine_loop_id", 123)
    monkeypatch.setattr(db_session, "_session_factory", object())
    monkeypatch.setattr(db_session, "close_all_sessions", fake_close_all_sessions)

    db_session.reset_session_state_sync()

    assert calls == ["close_all_sessions", "disposed"]
    assert db_session._engine is None
    assert db_session._engine_loop_id is None
    assert db_session._session_factory is None


def test_update_step_retry_waiting_ignores_missing_job(task_status_session_factory):
    missing_job_id = str(uuid.uuid4())

    assert not tasks._update_step_retry_waiting(
        missing_job_id,
        "transcribe",
        "GPU busy",
        countdown=30,
        task_id="stale-task",
    )


def test_finalize_ignored_dispatched_step_ignores_missing_job(task_status_session_factory):
    missing_job_id = str(uuid.uuid4())

    assert not tasks._finalize_ignored_dispatched_step(missing_job_id, "transcribe", task_id="stale-task")


def test_streamlined_asr_pipeline_skips_legacy_review_steps(monkeypatch):
    job = Job(id=uuid.uuid4(), source_name="source.mp4", status="processing", enhancement_modes=[])
    skipped_step_names = [
        "subtitle_term_resolution",
        "subtitle_consistency_review",
        "glossary_review",
        "transcript_review",
        "subtitle_translation",
        "dialogue_polish",
        "avatar_commentary",
    ]
    job_steps = [
        JobStep(job_id=job.id, step_name=step_name, status="pending")
        for step_name in skipped_step_names
    ]
    monkeypatch.setattr(
        orchestrator,
        "get_settings",
        lambda: SimpleNamespace(streamlined_asr_pipeline_enabled=True),
    )

    orchestrator._reconcile_terminal_steps(job, job_steps)

    assert {step.step_name for step in job_steps if step.status == "skipped"} == set(skipped_step_names)
    assert {
        step.metadata_["skip_reason"]
        for step in job_steps
        if step.step_name
        in {"subtitle_term_resolution", "subtitle_consistency_review", "glossary_review", "transcript_review"}
    } == {"streamlined_asr_pipeline"}
    assert next(step for step in job_steps if step.step_name == "subtitle_translation").metadata_["skip_reason"] == (
        "multilingual_translation_disabled"
    )


def test_streamlined_asr_pipeline_keeps_review_steps_by_default(monkeypatch):
    job = Job(id=uuid.uuid4(), source_name="source.mp4", status="processing", enhancement_modes=[])
    review_step_names = [
        "subtitle_term_resolution",
        "subtitle_consistency_review",
        "glossary_review",
        "transcript_review",
    ]
    job_steps = [
        JobStep(job_id=job.id, step_name=step_name, status="pending")
        for step_name in review_step_names
    ]
    monkeypatch.setattr(orchestrator, "get_settings", lambda: SimpleNamespace())

    orchestrator._reconcile_terminal_steps(job, job_steps)

    assert {step.step_name: step.status for step in job_steps} == {
        step_name: "pending" for step_name in review_step_names
    }


def test_streamlined_asr_pipeline_can_be_disabled(monkeypatch):
    job = Job(id=uuid.uuid4(), source_name="source.mp4", status="processing", enhancement_modes=[])
    legacy_step = JobStep(job_id=job.id, step_name="transcript_review", status="pending")
    translation_step = JobStep(job_id=job.id, step_name="subtitle_translation", status="pending")
    monkeypatch.setattr(
        orchestrator,
        "get_settings",
        lambda: SimpleNamespace(streamlined_asr_pipeline_enabled=False),
    )

    orchestrator._reconcile_terminal_steps(job, [legacy_step, translation_step])

    assert legacy_step.status == "pending"
    assert translation_step.status == "skipped"


def test_reconcile_restores_previously_streamlined_review_step(monkeypatch):
    job = Job(id=uuid.uuid4(), source_name="source.mp4", status="processing", enhancement_modes=[])
    review_step = JobStep(
        job_id=job.id,
        step_name="transcript_review",
        status="skipped",
        attempt=2,
        metadata_={
            "skip_reason": "streamlined_asr_pipeline",
            "detail": "新 ASR 精简链路已跳过旧版转写/字幕兜底审校。",
            "progress": 1.0,
            "last_task_id": "old-task",
        },
    )
    monkeypatch.setattr(orchestrator, "get_settings", lambda: SimpleNamespace())

    orchestrator._reconcile_terminal_steps(job, [review_step])

    assert review_step.status == "pending"
    assert review_step.attempt == 0
    assert review_step.finished_at is None
    assert review_step.error_message is None
    assert review_step.metadata_["progress"] == 0.0
    assert review_step.metadata_["detail"] == "ASR 审阅链路已恢复，等待重新执行。"
    assert "skip_reason" not in review_step.metadata_
    assert "last_task_id" not in review_step.metadata_


def test_task_status_helpers_ignore_invalid_job_ids(task_status_session_factory):
    assert not tasks._update_step_status("not-a-uuid", "transcribe", "running", task_id="stale-task")
    assert not tasks._update_step_retry_waiting(
        "not-a-uuid",
        "transcribe",
        "GPU busy",
        countdown=30,
        task_id="stale-task",
    )
    assert not tasks._finalize_ignored_dispatched_step("not-a-uuid", "transcribe", task_id="stale-task")


def test_non_retryable_quality_gate_failure_marks_step_terminal(
    task_status_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid.uuid4()
    step_id = uuid.uuid4()

    async def _setup() -> None:
        async with task_status_session_factory() as session:
            session.add(
                Job(
                    id=job_id,
                    source_path="source.mp4",
                    source_name="source.mp4",
                    status="processing",
                )
            )
            session.add(
                JobStep(
                    id=step_id,
                    job_id=job_id,
                    step_name="render",
                    status="pending",
                    attempt=1,
                )
            )
            await session.commit()

    class FakeTask:
        max_retries = 2
        request = SimpleNamespace(id="task-render-1", retries=0)

        def retry(self, *, exc, countdown):  # pragma: no cover - should not be reached
            raise AssertionError("non-retryable quality gate failures must not be retried")

    def _raise_blocked(step_name: str, target_job_id: str):
        raise RuntimeError(
            "render_blocked_by_fallback_output: "
            "subtitle_projection_validation_fallback_used"
        )

    async def _load_step() -> JobStep:
        async with task_status_session_factory() as session:
            step = await session.get(JobStep, step_id)
            assert step is not None
            return step

    asyncio.run(_setup())
    monkeypatch.setattr(tasks, "run_step_sync", _raise_blocked)

    with pytest.raises(RuntimeError, match="render_blocked_by_fallback_output"):
        tasks._run_task_step(FakeTask(), str(job_id), "render", retry_countdown=30)

    step = asyncio.run(_load_step())
    assert step.status == "failed"
    assert step.attempt == 3
    assert step.metadata_["terminal_failure"] is True
    assert step.metadata_["retryable"] is False
    assert step.error_message.startswith("render_blocked_by_fallback_output:")


def test_render_variant_sync_failure_marks_step_terminal(
    task_status_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid.uuid4()
    step_id = uuid.uuid4()

    async def _setup() -> None:
        async with task_status_session_factory() as session:
            session.add(
                Job(
                    id=job_id,
                    source_path="source.mp4",
                    source_name="source.mp4",
                    status="processing",
                )
            )
            session.add(
                JobStep(
                    id=step_id,
                    job_id=job_id,
                    step_name="render",
                    status="pending",
                    attempt=1,
                )
            )
            await session.commit()

    class FakeTask:
        max_retries = 2
        request = SimpleNamespace(id="task-render-sync-1", retries=0)

        def retry(self, *, exc, countdown):  # pragma: no cover - should not be reached
            raise AssertionError("render sync quality failures must not be retried")

    def _raise_blocked(step_name: str, target_job_id: str):
        raise RuntimeError(
            "render_variant_sync_blocked: "
            "packaged: subtitle_short_flash_detected; plain: subtitle_short_flash_detected"
        )

    async def _load_step() -> JobStep:
        async with task_status_session_factory() as session:
            step = await session.get(JobStep, step_id)
            assert step is not None
            return step

    asyncio.run(_setup())
    monkeypatch.setattr(tasks, "run_step_sync", _raise_blocked)

    with pytest.raises(RuntimeError, match="render_variant_sync_blocked"):
        tasks._run_task_step(FakeTask(), str(job_id), "render", retry_countdown=30)

    step = asyncio.run(_load_step())
    assert step.status == "failed"
    assert step.attempt == 3
    assert step.metadata_["terminal_failure"] is True
    assert step.metadata_["retryable"] is False
    assert step.error_message.startswith("render_variant_sync_blocked:")


def test_orchestrator_fails_job_for_terminal_failed_step(task_status_session_factory) -> None:
    job_id = uuid.uuid4()
    step_id = uuid.uuid4()

    async def _setup_and_reconcile() -> Job:
        async with task_status_session_factory() as session:
            session.add(
                Job(
                    id=job_id,
                    source_path="source.mp4",
                    source_name="source.mp4",
                    status="processing",
                )
            )
            session.add(
                JobStep(
                    id=step_id,
                    job_id=job_id,
                    step_name="edit_plan",
                    status="failed",
                    attempt=1,
                    error_message=(
                        "edit_plan_blocked_by_projection_fallback: "
                        "subtitle_projection_validation_fallback_used"
                    ),
                    metadata_={},
                )
            )
            await session.commit()

            await orchestrator._update_job_statuses(session)
            await session.commit()

        async with task_status_session_factory() as session:
            job = await session.get(Job, job_id)
            assert job is not None
            return job

    job = asyncio.run(_setup_and_reconcile())
    assert job.status == "failed"
    assert "edit_plan_blocked_by_projection_fallback" in str(job.error_message)


def test_orchestrator_keeps_failed_job_when_terminal_step_was_cancelled(
    task_status_session_factory,
) -> None:
    job_id = uuid.uuid4()
    step_id = uuid.uuid4()

    async def _setup_and_reconcile() -> Job:
        async with task_status_session_factory() as session:
            session.add(
                Job(
                    id=job_id,
                    source_path="source.mp4",
                    source_name="source.mp4",
                    status="failed",
                    error_message="previous failure",
                )
            )
            session.add(
                JobStep(
                    id=step_id,
                    job_id=job_id,
                    step_name="render",
                    status="cancelled",
                    attempt=3,
                    error_message=(
                        "render_blocked_by_fallback_output: "
                        "avatar_avatar_full_track_presenter_missing, cover_cover_export_failed"
                    ),
                    metadata_={"detail": "所属任务已终止，调度器已清理遗留运行步骤。"},
                )
            )
            await session.commit()

            await orchestrator._update_job_statuses(session)
            await session.commit()

        async with task_status_session_factory() as session:
            job = await session.get(Job, job_id)
            assert job is not None
            return job

    job = asyncio.run(_setup_and_reconcile())
    assert job.status == "failed"
    assert job.error_message == "previous failure"


def test_orchestrator_cancels_processing_job_with_terminal_cancelled_step(
    task_status_session_factory,
) -> None:
    job_id = uuid.uuid4()
    step_id = uuid.uuid4()

    async def _setup_and_reconcile() -> Job:
        async with task_status_session_factory() as session:
            session.add(
                Job(
                    id=job_id,
                    source_path="source.mp4",
                    source_name="source.mp4",
                    status="processing",
                )
            )
            session.add(
                JobStep(
                    id=step_id,
                    job_id=job_id,
                    step_name="render",
                    status="cancelled",
                    attempt=3,
                    metadata_={"detail": "任务到达时作业已终止，当前步骤已停止。"},
                )
            )
            await session.commit()

            await orchestrator._update_job_statuses(session)
            await session.commit()

        async with task_status_session_factory() as session:
            job = await session.get(Job, job_id)
            assert job is not None
            return job

    job = asyncio.run(_setup_and_reconcile())
    assert job.status == "cancelled"
    assert "render 步骤已取消" in str(job.error_message)


def test_done_transition_is_idempotent_for_same_task_id() -> None:
    assert tasks._can_transition_step(
        job_status="processing",
        step_status="done",
        target_status="done",
        current_task_id="",
        last_task_id="task-1",
        task_id="task-1",
    )


def test_blocking_step_heartbeat_updates_running_step(tmp_path, monkeypatch):
    db_path = (tmp_path / "heartbeat.db").as_posix()
    database_url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(database_url)
    job_id = uuid.uuid4()
    step_id = uuid.uuid4()

    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            session.add(
                Job(
                    id=job_id,
                    source_path="source.mp4",
                    source_name="source.mp4",
                    status="processing",
                )
            )
            session.add(
                JobStep(
                    id=step_id,
                    job_id=job_id,
                    step_name="subtitle_postprocess",
                    status="running",
                    metadata_={"detail": "old", "progress": 0.1},
                )
            )
            await session.commit()

    async def _load_step() -> JobStep:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            step = await session.get(JobStep, step_id)
            assert step is not None
            return step

    try:
        asyncio.run(_setup())
        monkeypatch.setattr(steps, "get_settings", lambda: SimpleNamespace(database_url=database_url))

        assert steps._write_blocking_step_heartbeat(
            step_id=step_id,
            detail="still splitting subtitles",
            progress=0.55,
        )

        refreshed = asyncio.run(_load_step())
        assert refreshed.metadata_["detail"] == "still splitting subtitles"
        assert refreshed.metadata_["progress"] == 0.55
        assert refreshed.metadata_["updated_at"]
    finally:
        asyncio.run(engine.dispose())


def test_blocking_step_heartbeat_context_writes_immediately(tmp_path, monkeypatch):
    db_path = (tmp_path / "heartbeat-context.db").as_posix()
    database_url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(database_url)
    job_id = uuid.uuid4()
    step_id = uuid.uuid4()

    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            session.add(
                Job(
                    id=job_id,
                    source_path="source.mp4",
                    source_name="source.mp4",
                    status="processing",
                )
            )
            session.add(
                JobStep(
                    id=step_id,
                    job_id=job_id,
                    step_name="subtitle_postprocess",
                    status="running",
                    metadata_={"detail": "old", "progress": 0.1},
                )
            )
            await session.commit()

    async def _load_step() -> JobStep:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            step = await session.get(JobStep, step_id)
            assert step is not None
            return step

    try:
        asyncio.run(_setup())
        monkeypatch.setattr(steps, "get_settings", lambda: SimpleNamespace(database_url=database_url))
        step = asyncio.run(_load_step())

        with steps._maintain_blocking_step_heartbeat(
            step,
            detail="saving subtitles",
            progress=0.82,
        ):
            deadline = time.monotonic() + 2.0
            refreshed = asyncio.run(_load_step())
            while refreshed.metadata_["detail"] != "saving subtitles" and time.monotonic() < deadline:
                time.sleep(0.05)
                refreshed = asyncio.run(_load_step())

            assert refreshed.metadata_["detail"] == "saving subtitles"
            assert refreshed.metadata_["progress"] == 0.82
            assert refreshed.metadata_["updated_at"]
    finally:
        asyncio.run(engine.dispose())


def test_blocking_step_heartbeat_writes_from_running_event_loop(tmp_path, monkeypatch):
    db_path = (tmp_path / "heartbeat-running-loop.db").as_posix()
    database_url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(database_url)
    job_id = uuid.uuid4()
    step_id = uuid.uuid4()

    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            session.add(
                Job(
                    id=job_id,
                    source_path="source.mp4",
                    source_name="source.mp4",
                    status="processing",
                )
            )
            session.add(
                JobStep(
                    id=step_id,
                    job_id=job_id,
                    step_name="subtitle_postprocess",
                    status="running",
                    metadata_={"detail": "old", "progress": 0.1},
                )
            )
            await session.commit()

    async def _load_step() -> JobStep:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            step = await session.get(JobStep, step_id)
            assert step is not None
            return step

    async def _write_inside_running_loop() -> bool:
        return steps._write_blocking_step_heartbeat(
            step_id=step_id,
            detail="running loop heartbeat",
            progress=0.66,
        )

    try:
        asyncio.run(_setup())
        monkeypatch.setattr(steps, "get_settings", lambda: SimpleNamespace(database_url=database_url))

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert asyncio.run(_write_inside_running_loop())

        assert not any("was never awaited" in str(item.message) for item in caught)
        refreshed = asyncio.run(_load_step())
        assert refreshed.metadata_["detail"] == "running loop heartbeat"
        assert refreshed.metadata_["progress"] == 0.66
    finally:
        asyncio.run(engine.dispose())
