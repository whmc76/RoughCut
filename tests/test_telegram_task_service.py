from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import roughcut.telegram.task_service as task_service_mod


def test_task_store_round_trip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        task_service_mod,
        "get_settings",
        lambda: SimpleNamespace(telegram_agent_state_dir=str(tmp_path)),
    )

    record = task_service_mod.create_task_record(
        chat_id="123",
        provider="claude",
        preset="inspect",
        task_text="检查 telegram 代码",
        status="queued",
        confirmation_required=False,
    )

    loaded = task_service_mod.get_agent_task_record(record.task_id)

    assert loaded is not None
    assert loaded.task_text == "检查 telegram 代码"
    assert loaded.provider == "claude"


def test_confirm_agent_task_submits_celery_job(tmp_path: Path, monkeypatch):
    sent: list[dict] = []

    monkeypatch.setattr(
        task_service_mod,
        "get_settings",
        lambda: SimpleNamespace(telegram_agent_state_dir=str(tmp_path)),
    )
    monkeypatch.setattr(
        task_service_mod.celery_app,
        "send_task",
        lambda name, kwargs, task_id, queue: sent.append(
            {"name": name, "kwargs": kwargs, "task_id": task_id, "queue": queue}
        ),
    )

    record = task_service_mod.create_task_record(
        chat_id="123",
        provider="claude",
        preset="implement",
        task_text="实现任务",
        status="awaiting_confirmation",
        confirmation_required=True,
    )

    updated = task_service_mod.confirm_agent_task(record.task_id)

    assert updated is not None
    assert updated.status == "queued"
    assert sent
    assert sent[0]["task_id"] == record.task_id
    assert sent[0]["queue"] == "agent_queue"


def test_cancel_agent_task_marks_cancelled(tmp_path: Path, monkeypatch):
    revoked: list[str] = []

    monkeypatch.setattr(
        task_service_mod,
        "get_settings",
        lambda: SimpleNamespace(telegram_agent_state_dir=str(tmp_path)),
    )

    class FakeAsyncResult:
        def revoke(self, terminate: bool = False):
            revoked.append("ok")

    monkeypatch.setattr(task_service_mod, "AsyncResult", lambda task_id, app=None: FakeAsyncResult())

    record = task_service_mod.create_task_record(
        chat_id="123",
        provider="claude",
        preset="inspect",
        task_text="实现任务",
        status="queued",
        confirmation_required=False,
    )

    updated = task_service_mod.cancel_agent_task(record.task_id)

    assert updated is not None
    assert updated.status == "cancelled"
    assert revoked == ["ok"]


def test_get_agent_task_status_persists_terminal_result(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        task_service_mod,
        "get_settings",
        lambda: SimpleNamespace(telegram_agent_state_dir=str(tmp_path)),
    )

    record = task_service_mod.create_task_record(
        chat_id="123",
        provider="claude",
        preset="inspect",
        task_text="实现任务",
        status="queued",
        confirmation_required=False,
    )

    class FakeAsyncResult:
        state = "SUCCESS"
        result = {
            "stdout": "done",
            "excerpt": "done",
            "cwd": str(tmp_path / "worktree"),
            "workspace_mode": "git_worktree",
            "workspace_root": str(tmp_path / "worktree"),
        }

    monkeypatch.setattr(task_service_mod, "AsyncResult", lambda task_id, app=None: FakeAsyncResult())

    payload = task_service_mod.get_agent_task_status(record.task_id)

    assert payload["status"] == "success"
    assert payload["result_path"]
    assert payload["workspace_mode"] == "git_worktree"
    assert payload["workspace_root"] == str(tmp_path / "worktree")
    assert payload["execution_cwd"] == str(tmp_path / "worktree")
    persisted = task_service_mod.load_agent_task_result(record.task_id)
    assert persisted is not None
    assert persisted["stdout"] == "done"
