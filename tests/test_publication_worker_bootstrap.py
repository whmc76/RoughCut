from __future__ import annotations

from roughcut.pipeline import celery_app as celery_app_module


class _FakeCeleryApp:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def send_task(self, name: str, kwargs: dict[str, object], queue: str) -> None:
        self.calls.append({
            "name": name,
            "kwargs": kwargs,
            "queue": queue,
        })


def test_schedule_publication_worker_bootstrap_only_for_publication_queue(monkeypatch):
    monkeypatch.setenv("ROUGHCUT_WORKER_QUEUES", "publication_queue")
    monkeypatch.setattr(celery_app_module, "_PUBLICATION_BOOTSTRAP_SENT", False)
    fake_app = _FakeCeleryApp()

    scheduled = celery_app_module.schedule_publication_worker_bootstrap(fake_app)

    assert scheduled is True
    assert fake_app.calls == [{
        "name": "roughcut.pipeline.tasks.publication_worker_tick",
        "kwargs": {"limit": 5, "schedule_followup": True},
        "queue": "publication_queue",
    }]


def test_schedule_publication_worker_bootstrap_is_noop_for_non_publication_worker(monkeypatch):
    monkeypatch.setenv("ROUGHCUT_WORKER_QUEUES", "media_queue")
    monkeypatch.setattr(celery_app_module, "_PUBLICATION_BOOTSTRAP_SENT", False)
    fake_app = _FakeCeleryApp()

    scheduled = celery_app_module.schedule_publication_worker_bootstrap(fake_app)

    assert scheduled is False
    assert fake_app.calls == []


def test_schedule_publication_worker_bootstrap_only_runs_once(monkeypatch):
    monkeypatch.setenv("ROUGHCUT_WORKER_QUEUES", "publication_queue")
    monkeypatch.setattr(celery_app_module, "_PUBLICATION_BOOTSTRAP_SENT", False)
    fake_app = _FakeCeleryApp()

    first = celery_app_module.schedule_publication_worker_bootstrap(fake_app)
    second = celery_app_module.schedule_publication_worker_bootstrap(fake_app)

    assert first is True
    assert second is False
    assert len(fake_app.calls) == 1
