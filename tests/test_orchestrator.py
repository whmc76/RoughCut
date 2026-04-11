from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_run_orchestrator_waits_for_single_active_lock(monkeypatch):
    import roughcut.pipeline.orchestrator as orchestrator_mod

    events: list[str] = []

    class FakeLease:
        def __init__(self):
            self._states = [False, True]

        async def try_acquire(self) -> bool:
            state = self._states.pop(0) if self._states else True
            events.append(f"lock:{state}")
            return state

        async def release(self) -> None:
            events.append("release")

    async def fake_recover():
        events.append("recover")

    async def fake_tick():
        events.append("tick")
        raise asyncio.CancelledError

    async def fake_sleep(_interval: float):
        events.append("sleep")

    monkeypatch.setattr(orchestrator_mod, "_SingleActiveOrchestratorLease", FakeLease)
    monkeypatch.setattr(orchestrator_mod, "_recover_incomplete_jobs", fake_recover)
    monkeypatch.setattr(orchestrator_mod, "tick", fake_tick)
    monkeypatch.setattr(orchestrator_mod.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await orchestrator_mod.run_orchestrator(poll_interval=0.01)

    assert events[:4] == ["lock:False", "sleep", "lock:True", "recover"]
    assert "tick" in events
    assert events[-1] == "release"


@pytest.mark.asyncio
async def test_get_orchestrator_lock_snapshot_reports_unsupported_for_non_postgres(monkeypatch):
    import roughcut.pipeline.orchestrator as orchestrator_mod

    monkeypatch.setattr(orchestrator_mod, "_supports_postgres_orchestrator_lock", lambda: False)

    snapshot = await orchestrator_mod.get_orchestrator_lock_snapshot()

    assert snapshot["status"] == "unsupported"
    assert snapshot["leader_active"] is None


def test_augment_orchestrator_lock_snapshot_marks_stale_leader(monkeypatch, tmp_path):
    import roughcut.pipeline.orchestrator as orchestrator_mod

    heartbeat_path = tmp_path / "orchestrator-heartbeat.json"
    stale_at = datetime.now(timezone.utc) - timedelta(minutes=3)
    heartbeat_path.write_text(
        json.dumps(
            {
                "updated_at": stale_at.isoformat(),
                "phase": "tick_running",
                "has_lock": True,
                "poll_interval_sec": 2.0,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(orchestrator_mod, "_ORCHESTRATOR_HEARTBEAT_PATH", heartbeat_path)

    snapshot = orchestrator_mod._augment_orchestrator_lock_snapshot(
        {
            "status": "held",
            "leader_active": True,
            "detail": "An active orchestrator currently holds the single-active lock.",
        }
    )

    assert snapshot["status"] == "stale"
    assert snapshot["leader_active"] is False
    assert snapshot["heartbeat_age_sec"] >= 180
    assert snapshot["heartbeat_stale_after_sec"] == orchestrator_mod._ORCHESTRATOR_HEARTBEAT_MIN_FRESH_SEC


def test_augment_orchestrator_lock_snapshot_keeps_fresh_leader(monkeypatch, tmp_path):
    import roughcut.pipeline.orchestrator as orchestrator_mod

    heartbeat_path = tmp_path / "orchestrator-heartbeat.json"
    fresh_at = datetime.now(timezone.utc) - timedelta(seconds=4)
    heartbeat_path.write_text(
        json.dumps(
            {
                "updated_at": fresh_at.isoformat(),
                "phase": "tick_idle",
                "has_lock": True,
                "poll_interval_sec": 2.0,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(orchestrator_mod, "_ORCHESTRATOR_HEARTBEAT_PATH", heartbeat_path)

    snapshot = orchestrator_mod._augment_orchestrator_lock_snapshot(
        {
            "status": "held",
            "leader_active": True,
            "detail": "An active orchestrator currently holds the single-active lock.",
        }
    )

    assert snapshot["status"] == "held"
    assert snapshot["leader_active"] is True
    assert snapshot["heartbeat_age_sec"] < snapshot["heartbeat_stale_after_sec"]


@pytest.mark.asyncio
async def test_is_step_ready_allows_skipped_optional_predecessor(db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/skipped-predecessor.mp4",
                source_name="skipped-predecessor.mp4",
                status="processing",
                language="zh-CN",
                enhancement_modes=[],
            )
        )
        session.add(JobStep(job_id=job_id, step_name="summary_review", status="done"))
        session.add(JobStep(job_id=job_id, step_name="ai_director", status="skipped"))
        session.add(JobStep(job_id=job_id, step_name="avatar_commentary", status="skipped"))
        session.add(JobStep(job_id=job_id, step_name="edit_plan", status="pending"))
        await session.commit()

    async with factory() as session:
        edit_plan_step = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(
                    JobStep.job_id == job_id,
                    JobStep.step_name == "edit_plan",
                )
            )
        ).scalar_one()
        ready = await orchestrator_mod._is_step_ready(edit_plan_step, session)

    assert ready is True


@pytest.mark.asyncio
async def test_reset_job_for_quality_rerun_increments_review_round_and_clears_notification_fingerprint(db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    factory = get_session_factory()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/review-round.mp4",
                source_name="review-round.mp4",
                status="needs_review",
                language="zh-CN",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="glossary_review",
                status="done",
                metadata_={
                    "review_round": 1,
                    "telegram_review_notifications": {
                        "subtitle_review": {"round": 1, "signature": "old-subtitle"}
                    },
                },
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="final_review",
                status="pending",
                metadata_={
                    "review_round": 1,
                    "telegram_review_notifications": {
                        "final_review": {"round": 1, "signature": "old-final"}
                    },
                },
            )
        )
        await session.commit()

    async with factory() as session:
        job = await session.get(Job, job_id)
        steps = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(JobStep.job_id == job_id)
            )
        ).scalars().all()
        await orchestrator_mod._reset_job_for_quality_rerun(
            session,
            job,
            steps,
            rerun_steps=["glossary_review", "final_review"],
            issue_codes=["subtitle_terms"],
        )
        await session.commit()

    async with factory() as session:
        steps = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(JobStep.job_id == job_id)
            )
        ).scalars().all()
        step_map = {step.step_name: step for step in steps}

        assert step_map["glossary_review"].metadata_["review_round"] == 2
        assert step_map["glossary_review"].metadata_["telegram_review_notifications"] == {}
        assert step_map["final_review"].metadata_["review_round"] == 2
        assert step_map["final_review"].metadata_["telegram_review_notifications"] == {}


@pytest.mark.asyncio
async def test_recover_stale_running_steps_records_stuck_step_diagnostic(db_engine, monkeypatch):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    import roughcut.recovery.stuck_step_recovery as recovery_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    factory = get_session_factory()
    calls: list[dict[str, object]] = []

    async def fake_record_stuck_step_diagnostic(session, job, step, *, stale_after_sec, applied_action, now, allow_acp):
        calls.append(
            {
                "job_id": str(job.id),
                "step_name": step.step_name,
                "stale_after_sec": stale_after_sec,
                "applied_action": applied_action,
                "allow_acp": allow_acp,
            }
        )
        step.metadata_ = {
            **(step.metadata_ or {}),
            "recovery_source": "local",
            "recovery_action": applied_action,
            "recovery_summary": "recorded",
            "updated_at": now.isoformat(),
        }
        return {
            "source": "local",
            "recommended_action": {"kind": applied_action},
            "summary": "recorded",
        }

    monkeypatch.setattr(recovery_mod, "record_stuck_step_diagnostic", fake_record_stuck_step_diagnostic)

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/stuck-step.mp4",
                source_name="stuck-step.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="transcribe",
                status="running",
                attempt=1,
                started_at=datetime.now(timezone.utc) - timedelta(hours=2),
                metadata_={
                    "task_id": "stale-task",
                    "worker_started_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                    "updated_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
                },
            )
        )
        await session.commit()

    async with factory() as session:
        await orchestrator_mod._recover_stale_running_steps(session)
        await session.commit()

    async with factory() as session:
        step = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(
                    JobStep.job_id == job_id,
                    JobStep.step_name == "transcribe",
                )
            )
        ).scalar_one()

    assert {
        "job_id": str(job_id),
        "step_name": "transcribe",
        "stale_after_sec": orchestrator_mod._step_stale_timeout_seconds("transcribe"),
        "applied_action": "reset_to_pending",
        "allow_acp": False,
    } in calls
    assert step.status == "pending"
    assert step.metadata_["recovery_action"] == "reset_to_pending"
    assert step.metadata_["recovery_source"] == "local"


@pytest.mark.asyncio
async def test_recover_stale_running_steps_recovers_dispatched_but_unclaimed_step(db_engine, monkeypatch):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.config import Settings
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    factory = get_session_factory()
    dispatched_at = datetime.now(timezone.utc) - timedelta(hours=2)

    monkeypatch.setattr(
        orchestrator_mod,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            step_stale_timeout_sec=900,
            step_dispatch_stale_timeout_sec=3600,
        ),
    )

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/dispatched-only.mp4",
                source_name="dispatched-only.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="content_profile",
                status="running",
                attempt=1,
                started_at=dispatched_at,
                metadata_={
                    "task_id": "queued-task",
                    "queue": "llm_queue",
                    "dispatched_at": dispatched_at.isoformat(),
                    "updated_at": dispatched_at.isoformat(),
                },
            )
        )
        await session.commit()

    async with factory() as session:
        await orchestrator_mod._recover_stale_running_steps(session)
        await session.commit()

    async with factory() as session:
        step = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(
                    JobStep.job_id == job_id,
                    JobStep.step_name == "content_profile",
                )
            )
        ).scalar_one()

    assert step.status == "pending"
    assert "task_id" not in (step.metadata_ or {})
    assert step.metadata_["dispatched_at"] == dispatched_at.isoformat()
    assert step.metadata_["last_task_id"] == "queued-task"
    assert step.metadata_["recovery_action"] == "reset_to_pending"


@pytest.mark.asyncio
async def test_recover_stale_running_steps_keeps_queued_dispatch_below_dispatch_timeout(db_engine, monkeypatch):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.config import Settings
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    factory = get_session_factory()
    dispatched_at = datetime.now(timezone.utc) - timedelta(minutes=20)

    monkeypatch.setattr(
        orchestrator_mod,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            step_stale_timeout_sec=900,
            step_dispatch_stale_timeout_sec=3600,
        ),
    )

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/queued-not-stale.mp4",
                source_name="queued-not-stale.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="content_profile",
                status="running",
                attempt=1,
                started_at=dispatched_at,
                metadata_={
                    "task_id": "queued-task",
                    "queue": "llm_queue",
                    "dispatched_at": dispatched_at.isoformat(),
                    "updated_at": dispatched_at.isoformat(),
                },
            )
        )
        await session.commit()

    async with factory() as session:
        await orchestrator_mod._recover_stale_running_steps(session)
        await session.commit()

    async with factory() as session:
        step = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(
                    JobStep.job_id == job_id,
                    JobStep.step_name == "content_profile",
                )
            )
        ).scalar_one()

    assert step.status == "running"
    assert (step.metadata_ or {}).get("task_id") == "queued-task"


@pytest.mark.asyncio
async def test_recover_stale_running_steps_respects_worker_started_at_fallback_from_started_at(db_engine, monkeypatch):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.config import Settings
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    factory = get_session_factory()
    dispatched_at = datetime.now(timezone.utc) - timedelta(hours=2)
    worker_started_at = datetime.now(timezone.utc) - timedelta(minutes=5)

    monkeypatch.setattr(
        orchestrator_mod,
        "get_settings",
        lambda: Settings(
            _env_file=None,
            step_stale_timeout_sec=900,
            step_dispatch_stale_timeout_sec=3600,
        ),
    )

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/claimed-no-heartbeat-meta.mp4",
                source_name="claimed-no-heartbeat-meta.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="content_profile",
                status="running",
                attempt=1,
                started_at=worker_started_at,
                metadata_={
                    "task_id": "claimed-task",
                    "queue": "llm_queue",
                    "dispatched_at": dispatched_at.isoformat(),
                    "updated_at": dispatched_at.isoformat(),
                },
            )
        )
        await session.commit()

    async with factory() as session:
        await orchestrator_mod._recover_stale_running_steps(session)
        await session.commit()

    async with factory() as session:
        step = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(
                    JobStep.job_id == job_id,
                    JobStep.step_name == "content_profile",
                )
            )
        ).scalar_one()

    assert step.status == "running"
    assert (step.metadata_ or {}).get("task_id") == "claimed-task"


@pytest.mark.asyncio
async def test_recover_stale_running_steps_closes_running_step_on_terminal_job(db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    factory = get_session_factory()
    started_at = datetime.now(timezone.utc) - timedelta(minutes=30)

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/terminal-running.mp4",
                source_name="terminal-running.mp4",
                status="done",
                language="zh-CN",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="subtitle_translation",
                status="running",
                attempt=1,
                started_at=started_at,
                metadata_={
                    "task_id": "orphan-task",
                    "updated_at": started_at.isoformat(),
                },
            )
        )
        await session.commit()

    async with factory() as session:
        await orchestrator_mod._recover_stale_running_steps(session)
        await session.commit()

    async with factory() as session:
        step = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(
                    JobStep.job_id == job_id,
                    JobStep.step_name == "subtitle_translation",
                )
            )
        ).scalar_one()

    assert step.status == "skipped"
    assert step.finished_at is not None
    assert "task_id" not in (step.metadata_ or {})
    assert step.metadata_["last_task_id"] == "orphan-task"


@pytest.mark.asyncio
async def test_tick_does_not_overwrite_fast_worker_step_completion(monkeypatch, db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    import roughcut.runtime_preflight as runtime_preflight_mod
    import roughcut.watcher.folder_watcher as watcher_mod
    import roughcut.pipeline.celery_app as celery_app_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    factory = get_session_factory()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/fast-worker.mp4",
                source_name="fast-worker.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="transcribe", status="pending"))
        await session.commit()

    class FakeAsyncResult:
        id = "task-fast-worker"

    async def fake_runtime_ready(*, reason: str):
        return None

    async def fake_watch_duty():
        return {"roots_total": 0, "scan_started": 0, "auto_merged_jobs": 0, "auto_enqueued_jobs": 0, "idle_slots": 0}

    async def fake_recover_stale(_session):
        return None

    async def fake_count_running_gpu_steps(_session):
        return 0

    async def fake_ensure_job_steps(_job, _session):
        return None

    async def fake_is_step_ready(step, _session):
        return step.job_id == job_id and step.step_name == "transcribe"

    async def fake_update_job_statuses(_session):
        async with factory() as worker_session:
            step = (
                await worker_session.execute(
                    orchestrator_mod.select(JobStep).where(
                        JobStep.job_id == job_id,
                        JobStep.step_name == "transcribe",
                    )
                )
            ).scalar_one()
            step.status = "done"
            step.finished_at = datetime.now(timezone.utc)
            step.metadata_ = {
                "label": "语音转写",
                "detail": "转写完成，共 3 段",
                "progress": 1.0,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "last_task_id": FakeAsyncResult.id,
            }
            await worker_session.commit()

    monkeypatch.setattr(runtime_preflight_mod, "ensure_runtime_services_ready", fake_runtime_ready)
    monkeypatch.setattr(watcher_mod, "run_watch_root_auto_duty", fake_watch_duty)
    monkeypatch.setattr(orchestrator_mod, "_ensure_job_steps", fake_ensure_job_steps)
    monkeypatch.setattr(orchestrator_mod, "_recover_stale_running_steps", fake_recover_stale)
    monkeypatch.setattr(orchestrator_mod, "_count_running_gpu_steps", fake_count_running_gpu_steps)
    monkeypatch.setattr(orchestrator_mod, "_update_job_statuses", fake_update_job_statuses)
    monkeypatch.setattr(orchestrator_mod, "_is_step_ready", fake_is_step_ready)
    monkeypatch.setattr(celery_app_mod.celery_app, "send_task", lambda *args, **kwargs: FakeAsyncResult())

    await orchestrator_mod.tick()

    async with factory() as session:
        step = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(
                    JobStep.job_id == job_id,
                    JobStep.step_name == "transcribe",
                )
            )
        ).scalar_one()

    assert step.status == "done"
    assert step.finished_at is not None
    assert step.metadata_["last_task_id"] == FakeAsyncResult.id
    assert "task_id" not in step.metadata_


@pytest.mark.asyncio
async def test_tick_respects_retry_wait_until_before_redispatch(monkeypatch, db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    import roughcut.watcher.folder_watcher as watcher_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    async def no_watch_duty():
        return {"roots_total": 0, "scan_started": 0, "auto_merged_jobs": 0, "auto_enqueued_jobs": 0, "idle_slots": 0}

    async def no_op(*args, **kwargs):
        return None

    async def ready_true(*args, **kwargs):
        return True

    async def zero(*args, **kwargs):
        return 0

    dispatched: list[tuple[str, str]] = []

    async def fake_dispatch(step, session):
        dispatched.append((str(step.job_id), step.step_name))

    monkeypatch.setattr(watcher_mod, "run_watch_root_auto_duty", no_watch_duty)
    monkeypatch.setattr(orchestrator_mod, "_ensure_job_steps", no_op)
    monkeypatch.setattr(orchestrator_mod, "_update_job_statuses", no_op)
    monkeypatch.setattr(orchestrator_mod, "_is_step_ready", ready_true)
    monkeypatch.setattr(orchestrator_mod, "_dispatch_step", fake_dispatch)
    monkeypatch.setattr(orchestrator_mod, "_count_running_gpu_steps", zero)

    job_id = uuid.uuid4()
    wait_until = datetime.now(timezone.utc) + timedelta(minutes=3)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/demo.mp4",
                source_name="demo.mp4",
                status="pending",
                language="zh-CN",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="transcribe",
                status="pending",
                metadata_={"retry_wait_until": wait_until.timestamp()},
            )
        )
        await session.commit()

    await orchestrator_mod.tick()

    assert (str(job_id), "transcribe") not in dispatched

    async with factory() as session:
        step = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "transcribe")
            )
        ).scalar_one()
        assert step.status == "pending"
        assert "资源等待中" in str((step.metadata_ or {}).get("detail") or "")


@pytest.mark.asyncio
async def test_tick_defers_gpu_sensitive_step_when_dispatch_gpu_guard_blocks(monkeypatch, db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    import roughcut.watcher.folder_watcher as watcher_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    async def no_watch_duty():
        return {"roots_total": 0, "scan_started": 0, "auto_merged_jobs": 0, "auto_enqueued_jobs": 0, "idle_slots": 0}

    async def no_op(*args, **kwargs):
        return None

    async def ready_true(*args, **kwargs):
        return True

    async def zero(*args, **kwargs):
        return 0

    dispatched: list[str] = []

    async def fake_dispatch(step, session):
        dispatched.append(step.step_name)

    monkeypatch.setattr(watcher_mod, "run_watch_root_auto_duty", no_watch_duty)
    monkeypatch.setattr(orchestrator_mod, "_ensure_job_steps", no_op)
    monkeypatch.setattr(orchestrator_mod, "_update_job_statuses", no_op)
    monkeypatch.setattr(orchestrator_mod, "_is_step_ready", ready_true)
    monkeypatch.setattr(orchestrator_mod, "_dispatch_step", fake_dispatch)
    monkeypatch.setattr(orchestrator_mod, "_count_running_gpu_steps", zero)
    monkeypatch.setattr(
        orchestrator_mod,
        "_gpu_dispatch_wait_reason",
        lambda step_name, *, running_gpu_steps: "检测到外部 GPU 占用，当前步骤延后派发。" if step_name == "transcribe" else None,
    )

    job_id = uuid.uuid4()
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/gpu.mp4",
                source_name="gpu.mp4",
                status="pending",
                language="zh-CN",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="transcribe", status="pending"))
        await session.commit()

    await orchestrator_mod.tick()

    assert "transcribe" not in dispatched

    async with factory() as session:
        step = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "transcribe")
            )
        ).scalar_one()
        assert step.status == "pending"
        assert "外部 GPU 占用" in str((step.metadata_ or {}).get("detail") or "")


@pytest.mark.asyncio
async def test_update_job_statuses_triggers_quality_rerun_for_generic_low_detail_profile(monkeypatch, db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.db.models import Artifact, Job, SubtitleItem
    from roughcut.db.session import get_session_factory

    settings = orchestrator_mod.get_settings()
    object.__setattr__(settings, "quality_auto_rerun_enabled", True)
    object.__setattr__(settings, "quality_auto_rerun_below_score", 75.0)
    object.__setattr__(settings, "quality_auto_rerun_max_attempts", 1)

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/quality.mp4",
                source_name="quality.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        for step in orchestrator_mod.create_job_steps(job_id):
            step.status = "done"
            step.finished_at = now
            session.add(step)
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_type": "开箱产品",
                    "video_theme": "开箱评测",
                    "summary": "围绕开箱产品展开，偏产品开箱与上手体验，适合后续做搜索校验、字幕纠错和剪辑包装。",
                    "engagement_question": "你觉得值不值？",
                    "preset_name": "edc_tactical",
                    "automation_review": {"score": 0.62},
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="render_outputs",
                data_json={
                    "packaged_mp4": "E:/tmp/quality.mp4",
                    "plain_mp4": "E:/tmp/quality_plain.mp4",
                    "ai_effect_mp4": "E:/tmp/quality_fx.mp4",
                    "avatar_result": {"status": "done", "detail": "ok"},
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="platform_packaging_md",
                storage_path="E:/tmp/quality_publish.md",
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=4.0,
                text_raw="Loop露普SK05二代UV版和一代做对比，亮度提升1000lm，续航三小时。",
            )
        )
        await session.commit()

    async with factory() as session:
        await orchestrator_mod._update_job_statuses(session)
        await session.commit()

    async with factory() as session:
        job = (await session.execute(orchestrator_mod.select(Job).where(Job.id == job_id))).scalar_one()
        steps = (
            await session.execute(orchestrator_mod.select(orchestrator_mod.JobStep).where(orchestrator_mod.JobStep.job_id == job_id))
        ).scalars().all()
        artifacts = (
            await session.execute(
                orchestrator_mod.select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "quality_assessment")
            )
        ).scalars().all()

        step_map = {step.step_name: step for step in steps}
        latest_quality = next(item for item in artifacts if "auto_rerun_triggered" in (item.data_json or {}))

        assert job.status == "processing"
        assert step_map["probe"].status == "done"
        assert step_map["content_profile"].status == "pending"
        assert step_map["render"].status == "pending"
        assert step_map["final_review"].status == "pending"
        assert step_map["platform_package"].status == "pending"
        assert latest_quality.data_json["auto_rerun_triggered"] is True
        assert latest_quality.data_json["auto_rerun_step"] == "content_profile"


@pytest.mark.asyncio
async def test_update_job_statuses_reconciles_pending_job_steps_from_progress_metadata(db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.db.models import Job
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    factory = get_session_factory()

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/manual-sync.mp4",
                source_name="manual-sync.mp4",
                status="pending",
                language="zh-CN",
                enhancement_modes=[],
            )
        )
        for step in orchestrator_mod.create_job_steps(job_id):
            if step.step_name == "content_profile":
                step.status = "pending"
                step.started_at = now - timedelta(minutes=1)
                step.metadata_ = {
                    "detail": "已生成内容摘要：待人工确认",
                    "progress": 1.0,
                    "updated_at": now.isoformat(),
                }
            elif step.step_name == "summary_review":
                step.status = "pending"
            else:
                step.status = "pending"
            session.add(step)
        await session.commit()

    async with factory() as session:
        await orchestrator_mod._update_job_statuses(session)
        await session.commit()

    async with factory() as session:
        job = (await session.execute(orchestrator_mod.select(Job).where(Job.id == job_id))).scalar_one()
        steps = (
            await session.execute(
                orchestrator_mod.select(orchestrator_mod.JobStep).where(orchestrator_mod.JobStep.job_id == job_id)
            )
        ).scalars().all()
        step_map = {step.step_name: step for step in steps}

    assert step_map["content_profile"].status == "done"
    assert step_map["content_profile"].finished_at is not None
    assert job.status == "needs_review"


@pytest.mark.asyncio
async def test_update_job_statuses_respects_quality_rerun_max_attempts(monkeypatch, db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.db.models import Artifact, Job, SubtitleItem
    from roughcut.db.session import get_session_factory

    settings = orchestrator_mod.get_settings()
    object.__setattr__(settings, "quality_auto_rerun_enabled", True)
    object.__setattr__(settings, "quality_auto_rerun_below_score", 75.0)
    object.__setattr__(settings, "quality_auto_rerun_max_attempts", 1)

    job_id = uuid.uuid4()
    signature = "comparison_blind|detail_blind|generic_question|generic_subject_type|generic_summary|generic_video_theme|low_profile_confidence"
    now = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/quality-repeat.mp4",
                source_name="quality-repeat.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        for step in orchestrator_mod.create_job_steps(job_id):
            step.status = "done"
            step.finished_at = now
            session.add(step)
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_type": "开箱产品",
                    "video_theme": "开箱评测",
                    "summary": "围绕开箱产品展开，偏产品开箱与上手体验，适合后续做搜索校验、字幕纠错和剪辑包装。",
                    "engagement_question": "你觉得值不值？",
                    "preset_name": "edc_tactical",
                    "automation_review": {"score": 0.62},
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="render_outputs",
                data_json={
                    "packaged_mp4": "E:/tmp/quality-repeat.mp4",
                    "plain_mp4": "E:/tmp/quality-repeat_plain.mp4",
                    "ai_effect_mp4": "E:/tmp/quality-repeat_fx.mp4",
                    "avatar_result": {"status": "done", "detail": "ok"},
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="platform_packaging_md",
                storage_path="E:/tmp/quality-repeat_publish.md",
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="quality_assessment",
                data_json={
                    "auto_rerun_count": 1,
                    "auto_rerun_history": [
                        {
                            "step": "content_profile",
                            "signature": signature,
                            "score": 41.0,
                        }
                    ],
                },
            )
        )
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=1,
                item_index=0,
                start_time=0.0,
                end_time=4.0,
                text_raw="Loop露普SK05二代UV版和一代做对比，亮度提升1000lm，续航三小时。",
            )
        )
        await session.commit()

    async with factory() as session:
        await orchestrator_mod._update_job_statuses(session)
        await session.commit()

    async with factory() as session:
        job = (await session.execute(orchestrator_mod.select(Job).where(Job.id == job_id))).scalar_one()
        steps = (
            await session.execute(orchestrator_mod.select(orchestrator_mod.JobStep).where(orchestrator_mod.JobStep.job_id == job_id))
        ).scalars().all()
        artifacts = (
            await session.execute(
                orchestrator_mod.select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "quality_assessment")
            )
        ).scalars().all()

        latest_quality = next(item for item in artifacts if "auto_rerun_triggered" in (item.data_json or {}))

        assert job.status == "done"
        assert all(step.status == "done" for step in steps)
        assert latest_quality.data_json["auto_rerun_triggered"] is False
        assert latest_quality.data_json["auto_rerun_skipped_reason"] == "max_attempts_reached"


@pytest.mark.asyncio
async def test_update_job_statuses_reruns_subtitle_chain_for_subtitle_quality_issue(monkeypatch, db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    from roughcut.db.models import Artifact, Job
    from roughcut.db.session import get_session_factory

    settings = orchestrator_mod.get_settings()
    object.__setattr__(settings, "quality_auto_rerun_enabled", True)
    object.__setattr__(settings, "quality_auto_rerun_below_score", 90.0)
    object.__setattr__(settings, "quality_auto_rerun_max_attempts", 1)

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/subtitle-only.mp4",
                source_name="subtitle-only.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        for step in orchestrator_mod.create_job_steps(job_id):
            step.status = "done"
            step.finished_at = now
            session.add(step)
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="content_profile_final",
                data_json={
                    "subject_brand": "Loop露普",
                    "subject_model": "SK05二代UV版",
                    "subject_type": "EDC手电",
                    "video_theme": "SK05二代UV版与一代亮度续航对比",
                    "summary": "围绕 Loop露普 SK05二代UV版 和一代做亮度、续航与 UV 功能差异对比。",
                    "engagement_question": "你更在意二代的 UV 功能还是亮度升级？",
                    "preset_name": "edc_tactical",
                    "review_mode": "auto_confirmed",
                    "automation_review": {"score": 0.95},
                },
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="subtitle_translation",
                data_json={"item_count": 12, "target_language": "en"},
            )
        )
        session.add(
            Artifact(
                job_id=job_id,
                artifact_type="platform_packaging_md",
                storage_path="E:/tmp/subtitle-only_publish.md",
            )
        )
        await session.commit()

    async with factory() as session:
        await orchestrator_mod._update_job_statuses(session)
        await session.commit()

    async with factory() as session:
        job = (await session.execute(orchestrator_mod.select(Job).where(Job.id == job_id))).scalar_one()
        steps = (
            await session.execute(orchestrator_mod.select(orchestrator_mod.JobStep).where(orchestrator_mod.JobStep.job_id == job_id))
        ).scalars().all()
        step_map = {step.step_name: step for step in steps}
        artifacts = (
            await session.execute(
                orchestrator_mod.select(Artifact).where(Artifact.job_id == job_id, Artifact.artifact_type == "quality_assessment")
            )
        ).scalars().all()
        latest_quality = next(item for item in artifacts if "auto_rerun_triggered" in (item.data_json or {}))

        assert job.status == "processing"
        assert step_map["subtitle_postprocess"].status == "pending"
        assert step_map["glossary_review"].status == "pending"
        assert step_map["subtitle_translation"].status == "pending"
        assert step_map["content_profile"].status == "pending"
        assert step_map["edit_plan"].status == "pending"
        assert step_map["ai_director"].status == "pending"
        assert step_map["avatar_commentary"].status == "pending"
        assert step_map["render"].status == "pending"
        assert step_map["final_review"].status == "pending"
        assert step_map["platform_package"].status == "pending"
        assert latest_quality.data_json["auto_rerun_triggered"] is True
        assert latest_quality.data_json["auto_rerun_steps"] == [
            "subtitle_postprocess",
            "glossary_review",
            "subtitle_translation",
            "content_profile",
            "ai_director",
            "avatar_commentary",
            "edit_plan",
            "render",
            "final_review",
            "platform_package",
        ]


def test_artifact_types_for_quality_rerun_gates_multisource_artifacts_by_feature_flags(monkeypatch):
    import roughcut.pipeline.orchestrator as orchestrator_mod

    monkeypatch.setattr(
        orchestrator_mod,
        "get_settings",
        lambda: SimpleNamespace(
            ocr_enabled=False,
            entity_graph_enabled=False,
            asr_evidence_enabled=False,
            research_verifier_enabled=False,
        ),
    )

    disabled_cleanup = orchestrator_mod._artifact_types_for_quality_rerun(
        {"transcribe", "content_profile", "glossary_review"}
    )

    assert "transcript_evidence" not in disabled_cleanup
    assert "content_profile_ocr" not in disabled_cleanup
    assert "entity_resolution_trace" not in disabled_cleanup

    monkeypatch.setattr(
        orchestrator_mod,
        "get_settings",
        lambda: SimpleNamespace(
            ocr_enabled=True,
            entity_graph_enabled=True,
            asr_evidence_enabled=True,
            research_verifier_enabled=False,
        ),
    )

    enabled_cleanup = orchestrator_mod._artifact_types_for_quality_rerun(
        {"transcribe", "content_profile", "glossary_review"}
    )

    assert "transcript_evidence" in enabled_cleanup
    assert "content_profile_ocr" in enabled_cleanup
    assert "entity_resolution_trace" in enabled_cleanup
