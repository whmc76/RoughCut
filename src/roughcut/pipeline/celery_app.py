from __future__ import annotations

from celery import Celery

from roughcut.config import get_settings


def _on_worker_init(**kwargs):
    from roughcut.db.session import set_worker_mode
    set_worker_mode(True)


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery(
        "roughcut",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["roughcut.pipeline.tasks"],
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="Asia/Shanghai",
        enable_utc=True,
        task_routes={
            "roughcut.pipeline.tasks.media_*": {"queue": "media_queue"},
            "roughcut.pipeline.tasks.llm_*": {"queue": "llm_queue"},
            "roughcut.pipeline.tasks.agent_*": {"queue": "agent_queue"},
            "roughcut.pipeline.tasks.publication_*": {"queue": "publication_queue"},
        },
        worker_prefetch_multiplier=1,
        task_acks_late=True,
    )
    from celery.signals import worker_init
    worker_init.connect(_on_worker_init)
    return app


celery_app = create_celery_app()
