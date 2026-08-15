from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.bootstrap.adapters.document_reflow_callbacks import (
    complete_document_reflow,
)
from app.modules.jobs.application.contracts import (
    DocumentReflowAssetPayload,
    DocumentReflowWebhookData,
)
from app.modules.reflows.infrastructure.models import (
    DocumentReflow,
    DocumentReflowAsset,
)
from app.modules.reflows.application.contracts import DocumentReflowAssetUrlResponse
from app.modules.reflows.application.reflows import DocumentReflows
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
        origin_operation_id=uuid4(),
        correlation_id=uuid4(),
    )
    artifact = DocumentReflow(
        document_id=document_id,
        job_id=job_id,
        status="pending",
        attempt_count=1,
    )
    artifact.blocks = []
    artifact.assets = []
    document = SimpleNamespace(
        id=document_id,
        raw_content=markdown,
        sha256=hashlib.sha256(b"canonical-pdf").hexdigest(),
    )
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
                "source_hash": hashlib.sha256(b"canonical-pdf").hexdigest(),
                "pipeline_revision": "mineru-continuous-ast-v1",
                "parser_revision": "mineru-cloud-v1",
                "blocks": [
                    {
                        "id": "title-block",
                        "index": 0,
                        "kind": "title",
                        "render_markdown": "# Paper",
                        "heading_level": 1,
                        "source_spans": [
                            {
                                "page_number": 1,
                                "source_rect": {
                                    "x": 0.1,
                                    "y": 0.1,
                                    "width": 0.5,
                                    "height": 0.05,
                                },
                                "source_text": "Paper",
                            }
                        ],
                        "presentation_status": "verbatim",
                    },
                    {
                        "id": "body-block",
                        "index": 1,
                        "kind": "paragraph",
                        "render_markdown": "Source paragraph.",
                        "source_spans": [
                            {
                                "page_number": 1,
                                "source_rect": {
                                    "x": 0.1,
                                    "y": 0.2,
                                    "width": 0.8,
                                    "height": 0.1,
                                },
                                "source_text": "Source paragraph.",
                            }
                        ],
                        "presentation_status": "verbatim",
                    },
                ],
                "assets": [],
            },
            "usage_events": [],
        }
    )


def test_reflow_completion_persists_sequential_evidence_bound_blocks() -> None:
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
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.schedule_storage_deletion",
            return_value=None,
        ),
    ):
        result = complete_document_reflow(
            db,
            actor=_actor(),
            job_id=job.id,
            callback=callback,
        )

    assert result.value == {"accepted": True}
    assert [block.render_markdown for block in artifact.blocks] == [
        "# Paper",
        "Source paragraph.",
    ]
    assert artifact.blocks[0].source_spans[0]["source_text"] == "Paper"
    assert artifact.pipeline_revision == "mineru-continuous-ast-v1"
    assert artifact.parser_revision == "mineru-cloud-v1"
    assert artifact.status == "completed"
    assert artifact.completed_at is not None
    complete.assert_called_once()


def test_reflow_completion_replaces_assets_and_schedules_obsolete_objects() -> None:
    markdown = "# Paper\n\nSource paragraph."
    db, job, artifact, document = _scope(markdown)
    artifact.assets = [
        DocumentReflowAsset(
            id="old-asset",
            document_id=document.id,
            object_key="documents/document-id/reflow/assets/old.png",
            kind="raster",
            content_type="image/png",
            width=100,
            height=100,
            page_number=1,
            source_rect={"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2},
            checksum="b" * 64,
        )
    ]
    callback = _completed_callback(job.id, document.id, markdown)
    assert callback.result is not None
    callback.result.assets = [
        DocumentReflowAssetPayload.model_validate(
            {
                "id": "figure-1",
                "object_key": "documents/document-id/reflow/assets/figure-1.png",
                "kind": "vector",
                "content_type": "image/png",
                "width": 640,
                "height": 480,
                "page_number": 1,
                "source_rect": {
                    "x": 0.1,
                    "y": 0.4,
                    "width": 0.7,
                    "height": 0.3,
                },
                "checksum": "a" * 64,
            }
        )
    ]

    with (
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.job_repository.require",
            return_value=job,
        ),
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.job_repository.complete",
            return_value=(job, True),
        ),
        patch(
            "app.bootstrap.adapters.document_reflow_callbacks.schedule_storage_deletion"
        ) as schedule_deletion,
    ):
        result = complete_document_reflow(
            db,
            actor=_actor(),
            job_id=job.id,
            callback=callback,
        )

    assert result.value == {"accepted": True}
    assert [asset.id for asset in artifact.assets] == ["figure-1"]
    assert artifact.assets[0].object_key.endswith("/figure-1.png")
    schedule_deletion.assert_called_once()
    assert schedule_deletion.call_args.kwargs["object_keys"] == {
        "documents/document-id/reflow/assets/old.png"
    }


def test_reflow_completion_rejects_changed_source_content() -> None:
    markdown = "# Paper\n\nSource paragraph."
    db, job, _artifact, document = _scope(markdown)
    callback = _completed_callback(job.id, document.id, markdown)
    assert callback.result is not None
    callback.result.source_hash = "f" * 64

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


def test_asset_url_reauthorizes_paper_before_signing_derived_asset() -> None:
    document_id = uuid4()
    access = MagicMock(return_value=SimpleNamespace(title="Paper"))
    gateway = MagicMock()
    gateway.get_asset_url.return_value = DocumentReflowAssetUrlResponse(
        asset_id="figure-1",
        url="https://signed.example/figure-1.png",
        expires_in=900,
    )
    reflows = DocumentReflows(
        access=access,
        gateway=gateway,
        entitlements=MagicMock(),
        journal=MagicMock(),
    )

    result = reflows.asset_url(
        actor=_actor(), document_id=document_id, asset_id="figure-1"
    )

    access.assert_called_once_with(actor=_actor(), document_id=document_id)
    gateway.get_asset_url.assert_called_once_with(
        document_id=document_id, asset_id="figure-1"
    )
    assert result.model_dump() == {
        "asset_id": "figure-1",
        "url": "https://signed.example/figure-1.png",
        "expires_in": 900,
    }
    assert "object_key" not in result.model_dump()
