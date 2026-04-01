from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select


def test_diagnose_stuck_step_falls_back_to_local_reason_when_acp_bridge_is_unavailable(monkeypatch):
    import roughcut.recovery.stuck_step_recovery as recovery_mod

    monkeypatch.setattr(
        recovery_mod,
        "run_bridge",
        lambda payload: (_ for _ in ()).throw(RuntimeError("ACP unavailable")),
    )

    now = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)
    job = SimpleNamespace(id=uuid.UUID("3d7fd6bc-4dcb-4c44-9b1f-fecf8a3f7e11"))
    step = SimpleNamespace(
        id=uuid.UUID("bc2f0d7d-8d44-4f5f-8e9c-7cf6f2db0d2a"),
        step_name="transcribe",
        status="running",
        attempt=2,
        started_at=now - timedelta(hours=2),
        finished_at=None,
        error_message=None,
        metadata_={
            "task_id": "task-123",
            "updated_at": (now - timedelta(hours=2)).isoformat(),
        },
    )

    diagnosis = recovery_mod.build_stuck_step_diagnostic(
        job=job,
        step=step,
        stale_after_sec=900,
        applied_action="reset_to_pending",
        now=now,
    )

    assert diagnosis["source"] == "local"
    assert diagnosis["step_name"] == "transcribe"
    assert diagnosis["recommended_action"]["kind"] == "reset_to_pending"
    assert "transcribe" in diagnosis["summary"]
    assert "heartbeat" in diagnosis["root_cause"].lower()


@pytest.mark.asyncio
async def test_record_stuck_step_diagnostic_persists_artifact_and_step_metadata(db_engine, monkeypatch):
    import roughcut.recovery.stuck_step_recovery as recovery_mod
    from roughcut.db.models import Artifact, Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.UUID("a3e8a5ae-9fb8-4d0c-bb65-4de1aab56ce3")
    step_id = uuid.UUID("c6fdd4d4-1a84-43db-8f71-c21e0842b909")
    now = datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc)
    factory = get_session_factory()

    monkeypatch.setattr(
        recovery_mod,
        "run_bridge",
        lambda payload: {
            "stdout": json.dumps(
                {
                    "summary": "ACP says the worker likely stalled.",
                    "root_cause": "worker heartbeat stopped updating",
                    "confidence": 0.93,
                    "recommended_action": {
                        "kind": "reset_to_pending",
                        "reason": "clear stale task state and requeue the step",
                    },
                },
                ensure_ascii=False,
            )
        },
    )

    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/source.mp4",
                source_name="source.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        session.add(
            JobStep(
                id=step_id,
                job_id=job_id,
                step_name="transcribe",
                status="running",
                attempt=1,
                started_at=now - timedelta(hours=1),
                metadata_={
                    "task_id": "task-abc",
                    "updated_at": (now - timedelta(hours=1)).isoformat(),
                },
            )
        )
        await session.commit()

    async with factory() as session:
        job = await session.get(Job, job_id)
        step = await session.get(JobStep, step_id)
        assert job is not None
        assert step is not None

        diagnosis = await recovery_mod.record_stuck_step_diagnostic(
            session,
            job,
            step,
            stale_after_sec=900,
            applied_action="reset_to_pending",
            now=now,
        )
        await session.commit()

    async with factory() as session:
        artifact = (
            await session.execute(
                select(Artifact).where(
                    Artifact.job_id == job_id,
                    Artifact.artifact_type == recovery_mod.STUCK_STEP_DIAGNOSTIC_ARTIFACT_TYPE,
                )
            )
        ).scalar_one()
        step = await session.get(JobStep, step_id)

    assert diagnosis["source"] == "acp"
    assert artifact.data_json["source"] == "acp"
    assert artifact.data_json["recommended_action"]["kind"] == "reset_to_pending"
    assert artifact.data_json["applied_action"] == "reset_to_pending"
    assert step is not None
    assert step.metadata_["recovery_source"] == "acp"
    assert step.metadata_["recovery_action"] == "reset_to_pending"
    assert step.metadata_["recovery_summary"] == "ACP says the worker likely stalled."
