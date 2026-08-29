from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery = Celery(
    "nexora",
    broker=settings.celery_broker_url.get_secret_value(),
    backend=settings.celery_result_backend.get_secret_value(),
    # Without `include` the worker registers no tasks and drains nothing, while
    # appearing to start correctly.
    include=["app.workers.tasks.outbox"],
)
celery.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)
