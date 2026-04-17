from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import roughcut.telegram.review_notification_service as review_notification_service


def test_build_review_notification_snapshot_surfaces_read_errors(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(
        review_notification_service,
        "get_settings",
        lambda: SimpleNamespace(telegram_agent_state_dir=str(tmp_path)),
    )
    store_file = tmp_path / "review_notifications.json"
    store_file.write_text("{not-json", encoding="utf-8")

    snapshot = review_notification_service.build_review_notification_snapshot()

    assert snapshot["summary"] == {"total": 0, "pending": 0, "due_now": 0, "failed": 0, "delivered": 0}
    assert snapshot["items"] == []
    assert "failed to read review_notifications.json" in snapshot["detail"]


def test_requeue_review_notification_rejects_corrupted_store(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(
        review_notification_service,
        "get_settings",
        lambda: SimpleNamespace(telegram_agent_state_dir=str(tmp_path)),
    )
    (tmp_path / "review_notifications.json").write_text("{not-json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Review notification store is unreadable"):
        review_notification_service.requeue_review_notification("n-1")


def test_build_review_notification_snapshot_filters_summary(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(
        review_notification_service,
        "get_settings",
        lambda: SimpleNamespace(telegram_agent_state_dir=str(tmp_path)),
    )
    payload = [
        {
            "notification_id": "n-1",
            "notification_key": "content_profile:job-1:0",
            "kind": "content_profile",
            "job_id": "job-1",
            "force_full_review": False,
            "status": "pending",
            "created_at": "2026-04-17T00:00:00+00:00",
            "updated_at": "2026-04-17T00:00:00+00:00",
            "next_attempt_at": "2026-04-17T00:00:00+00:00",
            "attempt_count": 1,
            "last_error": "",
            "delivered_at": "",
        },
        {
            "notification_id": "n-2",
            "notification_key": "final_review:job-2:0",
            "kind": "final_review",
            "job_id": "job-2",
            "force_full_review": False,
            "status": "failed",
            "created_at": "2026-04-17T00:00:00+00:00",
            "updated_at": "2026-04-17T00:00:00+00:00",
            "next_attempt_at": "2026-04-17T00:00:00+00:00",
            "attempt_count": 3,
            "last_error": "network down",
            "delivered_at": "",
        },
    ]
    (tmp_path / "review_notifications.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    snapshot = review_notification_service.build_review_notification_snapshot(statuses=["failed"])

    assert snapshot["summary"] == {"total": 1, "pending": 0, "due_now": 0, "failed": 1, "delivered": 0}
    assert [item["notification_id"] for item in snapshot["items"]] == ["n-2"]


def test_build_review_notification_snapshot_filters_by_job_id(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(
        review_notification_service,
        "get_settings",
        lambda: SimpleNamespace(telegram_agent_state_dir=str(tmp_path)),
    )
    payload = [
        {
            "notification_id": "n-1",
            "notification_key": "content_profile:job-1:0",
            "kind": "content_profile",
            "job_id": "job-1",
            "force_full_review": False,
            "status": "pending",
            "created_at": "2026-04-17T00:00:00+00:00",
            "updated_at": "2026-04-17T00:00:00+00:00",
            "next_attempt_at": "2026-04-17T00:00:00+00:00",
            "attempt_count": 1,
            "last_error": "",
            "delivered_at": "",
        },
        {
            "notification_id": "n-2",
            "notification_key": "final_review:job-2:0",
            "kind": "final_review",
            "job_id": "job-2",
            "force_full_review": False,
            "status": "failed",
            "created_at": "2026-04-17T00:00:00+00:00",
            "updated_at": "2026-04-17T00:00:00+00:00",
            "next_attempt_at": "2026-04-17T00:00:00+00:00",
            "attempt_count": 3,
            "last_error": "network down",
            "delivered_at": "",
        },
    ]
    (tmp_path / "review_notifications.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    snapshot = review_notification_service.build_review_notification_snapshot(job_id="job-1")

    assert snapshot["summary"] == {"total": 1, "pending": 1, "due_now": 1, "failed": 0, "delivered": 0}
    assert [item["notification_id"] for item in snapshot["items"]] == ["n-1"]


def test_batch_review_notification_actions_apply_to_selected_ids(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(
        review_notification_service,
        "get_settings",
        lambda: SimpleNamespace(telegram_agent_state_dir=str(tmp_path)),
    )
    payload = [
        {
            "notification_id": "n-1",
            "notification_key": "content_profile:job-1:0",
            "kind": "content_profile",
            "job_id": "job-1",
            "force_full_review": False,
            "status": "failed",
            "created_at": "2026-04-17T00:00:00+00:00",
            "updated_at": "2026-04-17T00:00:00+00:00",
            "next_attempt_at": "2026-04-17T00:00:00+00:00",
            "attempt_count": 2,
            "last_error": "network down",
            "delivered_at": "",
        },
        {
            "notification_id": "n-2",
            "notification_key": "final_review:job-2:0",
            "kind": "final_review",
            "job_id": "job-2",
            "force_full_review": False,
            "status": "pending",
            "created_at": "2026-04-17T00:00:00+00:00",
            "updated_at": "2026-04-17T00:00:00+00:00",
            "next_attempt_at": "2026-04-17T00:00:00+00:00",
            "attempt_count": 1,
            "last_error": "",
            "delivered_at": "",
        },
    ]
    (tmp_path / "review_notifications.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    updated = review_notification_service.requeue_review_notifications(["n-1"])
    dropped = review_notification_service.drop_review_notifications(["n-2"])
    snapshot = review_notification_service.build_review_notification_snapshot()

    assert [item.notification_id for item in updated] == ["n-1"]
    assert dropped == ["n-2"]
    assert snapshot["summary"] == {"total": 1, "pending": 1, "due_now": 1, "failed": 0, "delivered": 0}
    assert snapshot["items"][0]["notification_id"] == "n-1"
