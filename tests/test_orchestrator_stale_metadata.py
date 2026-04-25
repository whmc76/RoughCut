from __future__ import annotations

from datetime import datetime, timedelta, timezone

from roughcut.db.models import JobStep
from roughcut.pipeline.orchestrator import _step_last_heartbeat_at, _step_worker_started_at


def test_stale_worker_started_at_before_dispatch_is_ignored() -> None:
    dispatched = datetime(2026, 4, 26, 1, 0, tzinfo=timezone.utc)
    step = JobStep(
        step_name="edit_plan",
        status="running",
        started_at=dispatched,
        metadata_={
            "dispatched_at": dispatched.isoformat(),
            "worker_started_at": (dispatched - timedelta(hours=1)).isoformat(),
            "updated_at": dispatched.isoformat(),
        },
    )

    assert _step_worker_started_at(step) is None
    assert _step_last_heartbeat_at(step) == dispatched


def test_worker_started_at_after_dispatch_is_runtime_heartbeat() -> None:
    dispatched = datetime(2026, 4, 26, 1, 0, tzinfo=timezone.utc)
    worker_started = dispatched + timedelta(seconds=10)
    step = JobStep(
        step_name="edit_plan",
        status="running",
        started_at=dispatched,
        metadata_={
            "dispatched_at": dispatched.isoformat(),
            "worker_started_at": worker_started.isoformat(),
            "updated_at": dispatched.isoformat(),
        },
    )

    assert _step_worker_started_at(step) == worker_started
    assert _step_last_heartbeat_at(step) == worker_started
