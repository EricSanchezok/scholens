"""Shared Celery producer configuration for the durable Jobs outbox."""

import os

DEFAULT_CELERY_BROKER_URL = "pyamqp://guest@127.0.0.1:55672//"
DEFAULT_WEBHOOK_BASE_URL = "http://127.0.0.1:7301"
SQS_QUEUE_ENVIRONMENT = {
    "conversation": "SQS_CONVERSATION_QUEUE_URL",
    "document": "SQS_DOCUMENT_QUEUE_URL",
    "research": "SQS_RESEARCH_QUEUE_URL",
    "maintenance": "SQS_MAINTENANCE_QUEUE_URL",
}


def get_celery_broker_url(override: str | None = None) -> str:
    """Resolve the Celery broker URL (explicit override > env var > default)."""
    configured = override or os.environ.get("CELERY_BROKER_URL")
    if configured:
        return configured
    if os.environ.get("ENVIRONMENT", "development").casefold() == "production":
        raise RuntimeError("CELERY_BROKER_URL is required in production")
    return DEFAULT_CELERY_BROKER_URL


def get_celery_transport_options(
    broker_url: str,
    *,
    visibility_timeout_seconds: int = 45 * 60,
) -> dict[str, object]:
    """Build IAM-only SQS transport options or local RabbitMQ confirms."""
    if not broker_url.startswith("sqs://"):
        return {"confirm_publish": True}
    missing = [name for name in SQS_QUEUE_ENVIRONMENT.values() if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"missing predefined SQS queues: {', '.join(missing)}")
    return {
        "region": os.getenv("AWS_REGION", "ap-southeast-1"),
        "visibility_timeout": visibility_timeout_seconds,
        "wait_time_seconds": 20,
        "polling_interval": 1,
        "predefined_queues": {
            queue: {"url": os.environ[environment]}
            for queue, environment in SQS_QUEUE_ENVIRONMENT.items()
        },
    }


def get_webhook_base_url(override: str | None = None) -> str:
    """Resolve the base URL the jobs worker calls back for webhooks."""
    return override or os.environ.get("WEBHOOK_BASE_URL") or DEFAULT_WEBHOOK_BASE_URL
