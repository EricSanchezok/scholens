from unittest.mock import MagicMock, patch

from app.modules.jobs.infrastructure.client import JobsClient
from app.helpers.redaction import redact_url


def test_redact_url_removes_credentials_and_sensitive_query_values() -> None:
    redacted = redact_url(
        "amqp://scholens:super-secret@rabbitmq:5672/vhost?token=abc&mode=fast"
    )

    assert "scholens" not in redacted
    assert "super-secret" not in redacted
    assert "abc" not in redacted
    assert "rabbitmq:5672" in redacted
    assert "mode=fast" in redacted


def test_jobs_client_reuses_one_configured_celery_producer() -> None:
    celery_app = MagicMock()
    celery_app.send_task.side_effect = [MagicMock(id="task_pdf")]
    with patch(
        "app.modules.jobs.infrastructure.client.Celery", return_value=celery_app
    ) as celery:
        client = JobsClient(
            celery_broker_url="amqp://user:password@rabbitmq:5672//",
        )
        assert (
            client.publish_task(
                task_name="upload_and_process_file",
                queue="document",
                job_id="job-pdf",
                kwargs={"s3_object_key": "documents/hash/source.pdf"},
                headers={"scholens-correlation-id": "correlation-id"},
            )
            == "task_pdf"
        )

    celery.assert_called_once()
    assert celery_app.send_task.call_count == 1
    assert celery_app.send_task.call_args_list[0].kwargs["task_id"] == "job-pdf"
    assert celery_app.send_task.call_args_list[0].kwargs["headers"] == {
        "scholens-correlation-id": "correlation-id"
    }


def test_jobs_client_uses_predefined_iam_sqs_queues(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AWS_REGION", "ap-southeast-1")
    monkeypatch.setenv("SQS_DOCUMENT_QUEUE_URL", "https://sqs.example/document")
    monkeypatch.setenv("SQS_RESEARCH_QUEUE_URL", "https://sqs.example/research")
    monkeypatch.setenv("SQS_MAINTENANCE_QUEUE_URL", "https://sqs.example/maintenance")
    celery_app = MagicMock()
    with patch(
        "app.modules.jobs.infrastructure.client.Celery", return_value=celery_app
    ):
        JobsClient(celery_broker_url="sqs://")

    options = celery_app.conf.update.call_args.kwargs["broker_transport_options"]
    assert options["visibility_timeout"] == 45 * 60
    assert options["predefined_queues"] == {
        "document": {"url": "https://sqs.example/document"},
        "research": {"url": "https://sqs.example/research"},
        "maintenance": {"url": "https://sqs.example/maintenance"},
    }
