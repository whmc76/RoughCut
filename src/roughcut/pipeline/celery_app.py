from __future__ import annotations

import logging
import os

from celery import Celery

from roughcut.config import get_settings

logger = logging.getLogger(__name__)
_PUBLICATION_BOOTSTRAP_SENT = False


def _on_worker_init(**kwargs):
    from roughcut.db.session import set_worker_mode
    set_worker_mode(True)


def _worker_queue_names_from_env() -> set[str]:
    return {
        item.strip()
        for item in str(os.getenv("ROUGHCUT_WORKER_QUEUES", "")).split(",")
        if item.strip()
    }


def should_bootstrap_publication_worker_tick() -> bool:
    queue_names = _worker_queue_names_from_env()
    return "publication_queue" in queue_names or "all" in queue_names


def schedule_publication_worker_bootstrap(app: Celery) -> bool:
    global _PUBLICATION_BOOTSTRAP_SENT
    if _PUBLICATION_BOOTSTRAP_SENT:
        return False
    if not should_bootstrap_publication_worker_tick():
        return False
    settings = get_settings()
    limit = max(1, int(getattr(settings, "publication_worker_batch_limit", 5) or 5))
    app.send_task(
        "roughcut.pipeline.tasks.publication_worker_tick",
        kwargs={"limit": limit, "schedule_followup": True},
        queue="publication_queue",
    )
    _PUBLICATION_BOOTSTRAP_SENT = True
    logger.info("Bootstrapped publication worker tick on startup (limit=%s)", limit)
    return True


def _on_worker_ready(sender=None, **kwargs):
    app = getattr(sender, "app", None)
    if app is None:
        return
    try:
        schedule_publication_worker_bootstrap(app)
    except Exception:
        logger.exception("Failed to bootstrap publication worker tick on startup")


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
    from celery.signals import worker_ready
    worker_init.connect(_on_worker_init)
    worker_ready.connect(_on_worker_ready)
    return app


celery_app = create_celery_app()
