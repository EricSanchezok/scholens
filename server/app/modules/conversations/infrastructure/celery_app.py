"""Dedicated Celery application for durable Conversation generation."""

from __future__ import annotations

from celery import Celery
from scholens_job_contracts import JobQueue

from app.helpers.celery_config import (
    get_celery_broker_url,
    get_celery_transport_options,
)
from app.modules.conversations.infrastructure.task_protection import (
    register_task_protection_signals,
)

BROKER_URL = get_celery_broker_url()
celery_app = Celery(
    "scholens_conversations",
    broker=BROKER_URL,
    include=["app.bootstrap.adapters.conversation_worker"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    result_backend=None,
    task_ignore_result=True,
    task_store_errors_even_if_ignored=False,
    task_default_queue=JobQueue.CONVERSATION,
    task_routes={
        "app.bootstrap.adapters.conversation_worker.generate_conversation_response": {
            "queue": JobQueue.CONVERSATION
        }
    },
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_transport_options=get_celery_transport_options(
        BROKER_URL,
        visibility_timeout_seconds=60 * 60,
    ),
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    reject_on_worker_lost=True,
    task_acks_on_failure_or_timeout=True,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    worker_soft_shutdown_timeout=120.0,
    worker_enable_soft_shutdown_on_idle=True,
    worker_max_tasks_per_child=250,
    worker_send_task_events=False,
    task_send_sent_event=False,
    worker_hijack_root_logger=False,
    worker_log_color=False,
    worker_disable_rate_limits=True,
    worker_max_memory_per_child=750000,
)

register_task_protection_signals()

if __name__ == "__main__":
    celery_app.start()


__all__ = ["celery_app"]
