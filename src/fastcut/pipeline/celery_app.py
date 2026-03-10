from __future__ import annotations

from celery import Celery

from fastcut.config import get_settings


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery(
        "fastcut",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="Asia/Shanghai",
        enable_utc=True,
        task_routes={
            "fastcut.pipeline.tasks.media_*": {"queue": "media_queue"},
            "fastcut.pipeline.tasks.llm_*": {"queue": "llm_queue"},
        },
        worker_prefetch_multiplier=1,
        task_acks_late=True,
    )
    return app


celery_app = create_celery_app()
