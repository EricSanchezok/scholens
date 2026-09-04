"""Celery worker configuration for local RabbitMQ and production SQS."""

from __future__ import annotations

import os

from celery import Celery
from dotenv import load_dotenv
from scholens_job_contracts import JobQueue, PDF_TEXT_REPAIR_TASK_NAME

from src.observability import configure_jobs_observability
from src.pdf import validate_pdf_runtime_configuration
from src.task_protection import register_task_protection_signals
from src.webhook_signing import callback_base_url

load_dotenv()
configure_jobs_observability()
validate_pdf_runtime_configuration()
callback_base_url()

LOCAL_BROKER_URL = "pyamqp://guest@127.0.0.1:55672//"
QUEUE_ENVIRONMENT = {
    JobQueue.DOCUMENT: "SQS_DOCUMENT_QUEUE_URL",
    JobQueue.RESEARCH: "SQS_RESEARCH_QUEUE_URL",
    JobQueue.MAINTENANCE: "SQS_MAINTENANCE_QUEUE_URL",
}


def _broker_url() -> str:
    configured = os.getenv("CELERY_BROKER_URL")
    if configured:
        return configured
    if os.getenv("ENVIRONMENT", "development").casefold() == "production":
        raise RuntimeError("CELERY_BROKER_URL is required in production")
    return LOCAL_BROKER_URL


def _transport_options(broker_url: str) -> dict[str, object]:
    if not broker_url.startswith("sqs://"):
        return {}
    missing = [name for name in QUEUE_ENVIRONMENT.values() if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"missing predefined SQS queues: {', '.join(missing)}")
    return {
        "region": os.getenv("AWS_REGION", "ap-southeast-1"),
        "visibility_timeout": 45 * 60,
        "wait_time_seconds": 20,
        "polling_interval": 1,
        "predefined_queues": {
            queue: {"url": os.environ[environment]}
            for queue, environment in QUEUE_ENVIRONMENT.items()
        },
    }


BROKER_URL = _broker_url()
celery_app = Celery("scholens_tasks", broker=BROKER_URL, include=["src.tasks"])

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    result_backend=None,
    task_ignore_result=True,
    task_store_errors_even_if_ignored=False,
    task_default_queue=JobQueue.MAINTENANCE,
    task_routes={
        "upload_and_process_file": {"queue": JobQueue.DOCUMENT},
        "ingest_source_and_process": {"queue": JobQueue.DOCUMENT},
        PDF_TEXT_REPAIR_TASK_NAME: {"queue": JobQueue.DOCUMENT},
        "postprocess_pdf": {"queue": JobQueue.DOCUMENT},
        "generate_document_reflow": {"queue": JobQueue.DOCUMENT},
        "generate_audio_overview": {"queue": JobQueue.RESEARCH},
        "process_data_table": {"queue": JobQueue.RESEARCH},
        "collect_document": {"queue": JobQueue.MAINTENANCE},
        "delete_storage_objects": {"queue": JobQueue.MAINTENANCE},
        "import_zotero_items": {"queue": JobQueue.MAINTENANCE},
        "sync_zotero": {"queue": JobQueue.MAINTENANCE},
    },
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_transport_options=_transport_options(BROKER_URL),
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    reject_on_worker_lost=True,
    task_acks_on_failure_or_timeout=True,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    worker_soft_shutdown_timeout=120.0,
    worker_enable_soft_shutdown_on_idle=True,
    worker_max_tasks_per_child=1000,
    worker_send_task_events=False,
    task_send_sent_event=False,
    worker_hijack_root_logger=False,
    worker_log_color=False,
    worker_disable_rate_limits=True,
    worker_max_memory_per_child=500000,
)

register_task_protection_signals()
celery_app.autodiscover_tasks()

if __name__ == "__main__":
    celery_app.start()
