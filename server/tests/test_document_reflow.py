from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.bootstrap.adapters.document_reflow_callbacks import (
    _source_hash,
    complete_document_reflow,
)
from app.modules.jobs.application.contracts import DocumentReflowWebhookData
from app.modules.reflows.infrastructure.models import DocumentReflow
from app.shared.application import Actor
from app.shared.domain import AppError
from app.shared.domain.enums import JobOperation, JobStatus


def _actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        status="active",
        email_verified=True,
    )


def _scope(markdown: str = "# Paper\n\nSource paragraph."):
    document_id = uuid4()
    job_id = uuid4()
    job = SimpleNamespace(
        id=job_id,
        operation=JobOperation.DOCUMENT_REFLOW.value,
        requested_by_id=7,
        document_id=document_id,
        status=JobStatus.RUNNING.value,
    )
    artifact = DocumentReflow(
        document_id=document_id,
        job_id=job_id,
        status="pending",
        attempt_count=1,
    )
    artifact.blocks = []
    document = SimpleNamespace(id=document_id, raw_content=markdown)
    db = MagicMock()
    db.get.side_effect = lambda model, key: (
        artifact if model is DocumentReflow and key == document_id else document
    )
    return db, job, artifact, document


def _completed_callback(job_id, document_id, markdown: str):
    return DocumentReflowWebhookData.model_validate(
        {
            "task_id": str(job_id),
            "status": "completed",
            "result": {
                "document_id": str(document_id),
                "source_hash": _source_hash(markdown),
                "prompt_revision": "reflow-layout-v1",
                "profile_revision": "profile-v1",
                "blocks": [
                    {
                        "id": "title-block",
                        "index": 0,
                        "kind": "title",
                        "source_markdown": "# Paper",
                        "heading_level": 1,
                        "page_number": 1,
                    },
                    {
                        "id": "body-block",
                        "index": 1,
                        "kind": "paragraph",
                        "source_markdown": "Source paragraph.",
                        "page_number": 1,
                    },
                ],
            },
            "usage_events": [],
        }
    )


def test_reflow_completion_persists_only_lossless_sequential_blocks() -> None:
    markdown = "# Paper\n\nSource paragraph."
    db, job, artifact, document = _scope(markdown)
    callback = _completed_callback(job.id, document.id, markdown)

    with (
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.job_repository.require",
            return_value=job,
        ),
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.job_repository.complete",
            return_value=(job, True),
        ) as complete,
    ):
        result = complete_document_reflow(
            db,
            actor=_actor(),
            job_id=job.id,
            callback=callback,
        )

    assert result.value == {"accepted": True}
    assert [block.source_markdown for block in artifact.blocks] == [
        "# Paper",
        "Source paragraph.",
    ]
    assert artifact.status == "completed"
    assert artifact.completed_at is not None
    complete.assert_called_once()


def test_reflow_completion_rejects_changed_source_content() -> None:
    markdown = "# Paper\n\nSource paragraph."
    db, job, _artifact, document = _scope(markdown)
    callback = _completed_callback(job.id, document.id, markdown)
    assert callback.result is not None
    callback.result.blocks[1].source_markdown = "Hallucinated paragraph."

    with patch(
        "app.bootstrap.adapters.document_reflow_callbacks.job_repository.require",
        return_value=job,
    ):
        with pytest.raises(AppError) as raised:
            complete_document_reflow(
                db,
                actor=_actor(),
                job_id=job.id,
                callback=callback,
            )

    assert raised.value.code == "document_reflow_result_invalid"


def test_failed_reflow_does_not_change_document_processing_state() -> None:
    db, job, artifact, document = _scope()
    callback = DocumentReflowWebhookData(
        task_id=job.id,
        status="failed",
        error="document_reflow_failed",
    )
    failed_job = SimpleNamespace(status=JobStatus.FAILED.value)
    with (
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.job_repository.require",
            return_value=job,
        ),
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.job_repository.fail",
            return_value=(failed_job, True),
        ),
    ):
        result = complete_document_reflow(
            db,
            actor=_actor(),
            job_id=job.id,
            callback=callback,
        )

    assert result.value == {"accepted": True}
    assert artifact.status == "failed"
    assert artifact.error_code == "document_reflow_failed"
    assert document.raw_content == "# Paper\n\nSource paragraph."
    assert isinstance(artifact.completed_at, datetime)
    assert artifact.completed_at.tzinfo is UTC
