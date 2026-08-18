"""PDF completion stores paper-owned metadata without manufacturing chats."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.bootstrap.adapters import document_job_callbacks
from app.modules.jobs.application.contracts import (
    PDFProcessingResult,
    PdfProcessingWebhookData,
)
from app.modules.jobs.infrastructure.repository import PersistedJob
from app.modules.papers.application.contracts.extraction import (
    PaperMetadataExtraction,
    ResponseCitation,
)
from app.shared.application import (
    Actor,
    OperationContextFactory,
    OperationInitiator,
    SchedulerOrigin,
)
from app.shared.domain.enums import (
    DocumentProcessingStatus,
    JobOperation,
    JobStatus,
)


class _AvailableLock:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.released = False

    def acquire(self) -> bool:
        return True

    def release(self) -> None:
        self.released = True


def _actor() -> Actor:
    return Actor(
        id=7,
        email="reader@example.com",
        display_name="Reader",
        status="active",
        email_verified=True,
    )


@pytest.mark.parametrize(
    ("reason", "progress_code", "expected"),
    [
        (
            "paper_ingestion_metadata_failed",
            "parsing",
            "paper_ingestion_metadata_failed",
        ),
        ("pdf_content_insufficient", "parsing", "pdf_content_insufficient"),
        ("mineru_response_unsafe", "parsing", "mineru_response_unsafe"),
        (
            "provider leaked a private diagnostic",
            "indexing",
            "paper_ingestion_indexing_failed",
        ),
        (
            "provider leaked a private diagnostic",
            None,
            "paper_ingestion_parsing_failed",
        ),
    ],
)
def test_pdf_failure_code_preserves_safe_codes_and_hides_private_diagnostics(
    reason: str,
    progress_code: str | None,
    expected: str,
) -> None:
    assert (
        document_job_callbacks._safe_pdf_failure_code(
            reason=reason,
            progress_code=progress_code,
        )
        == expected
    )


@pytest.mark.asyncio
async def test_pdf_completion_persists_summary_without_creating_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    document_id = uuid4()
    actor = _actor()
    upload_job = SimpleNamespace(id=job_id, created_at=datetime.now(UTC))
    durable_job = SimpleNamespace(
        operation=JobOperation.PDF_PROCESS.value,
        requested_by_id=actor.id,
        status=JobStatus.RUNNING.value,
    )
    existing_paper = SimpleNamespace(
        id=document_id,
        title="upload.pdf",
        processing_status=DocumentProcessingStatus.PROCESSING.value,
        s3_object_key=f"documents/{'a' * 64}/source.pdf",
    )
    completed_paper = SimpleNamespace(
        id=document_id,
        title="Canonical paper title",
        processing_status=DocumentProcessingStatus.COMPLETED.value,
    )
    update_canonical = MagicMock(return_value=completed_paper)

    monkeypatch.setattr(document_job_callbacks, "AdvisoryLock", _AvailableLock)
    monkeypatch.setattr(
        document_job_callbacks.upload_reservation_repository,
        "get_by",
        MagicMock(return_value=upload_job),
    )
    monkeypatch.setattr(
        document_job_callbacks.job_repository,
        "require",
        MagicMock(return_value=durable_job),
    )
    monkeypatch.setattr(
        document_job_callbacks.zotero_import_repository,
        "get_by_upload_job_id",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        document_job_callbacks.document_repository,
        "find_by_upload_job",
        MagicMock(return_value=existing_paper),
    )
    monkeypatch.setattr(
        document_job_callbacks.document_repository,
        "update_canonical",
        update_canonical,
    )
    monkeypatch.setattr(
        document_job_callbacks,
        "_complete_pdf_job",
        MagicMock(return_value=True),
    )
    monkeypatch.setattr(
        document_job_callbacks,
        "_enqueue_pdf_postprocess",
        MagicMock(
            return_value=PersistedJob(
                job=SimpleNamespace(id=uuid4()),
                created=False,
            )
        ),
    )
    citation = ResponseCitation(index=1, text="Supporting passage")
    result = PDFProcessingResult(
        success=True,
        job_id=str(job_id),
        raw_content="Parsed paper content",
        page_offset_map={1: [0, 20]},
        s3_object_key=f"documents/{'a' * 64}/source.pdf",
        metadata=PaperMetadataExtraction(
            title="Canonical paper title",
            summary="The paper's canonical summary.[^1]",
            summary_citations=[citation],
        ),
        parser_backend="pymupdf4llm",
        parser_quality="full",
        parser_version="test-parser",
    )
    callback = PdfProcessingWebhookData(
        task_id=str(job_id),
        status="completed",
        result=result,
    )
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin("pdf_callback_test", uuid4()),
        credential=None,
    )
    db = MagicMock()

    handled = await document_job_callbacks.handle_paper_processing_webhook(
        str(job_id),
        callback,
        db,
        actor=actor,
        operation=operation,
    )

    update = update_canonical.call_args.kwargs["update"]
    assert update.summary == result.metadata.summary
    assert update.summary_citations == [citation]
    assert handled.value == {
        "status": "webhook processed",
        "document_id": str(document_id),
    }
    assert all(
        not str(change.action).startswith("conversation.") for change in handled.changes
    )


@pytest.mark.asyncio
async def test_terminal_pdf_callback_does_not_rewrite_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    actor = _actor()
    update_canonical = MagicMock()
    monkeypatch.setattr(
        document_job_callbacks.upload_reservation_repository,
        "get_by",
        MagicMock(return_value=SimpleNamespace(id=job_id)),
    )
    monkeypatch.setattr(
        document_job_callbacks.job_repository,
        "require",
        MagicMock(
            return_value=SimpleNamespace(
                operation=JobOperation.PDF_PROCESS.value,
                requested_by_id=actor.id,
                status=JobStatus.COMPLETED.value,
            )
        ),
    )
    monkeypatch.setattr(
        document_job_callbacks.document_repository,
        "update_canonical",
        update_canonical,
    )
    result = PDFProcessingResult(
        success=True,
        job_id=str(job_id),
        raw_content="Parsed paper content",
        page_offset_map={1: [0, 20]},
        metadata=PaperMetadataExtraction(title="Paper"),
        parser_backend="pymupdf4llm",
        parser_quality="full",
        parser_version="test-parser",
    )
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin("pdf_callback_test", uuid4()),
        credential=None,
    )

    handled = await document_job_callbacks.handle_paper_processing_webhook(
        str(job_id),
        PdfProcessingWebhookData(
            task_id=str(job_id),
            status="completed",
            result=result,
        ),
        MagicMock(),
        actor=actor,
        operation=operation,
    )

    assert handled.value == {"status": "webhook ignored - job is terminal"}
    update_canonical.assert_not_called()


@pytest.mark.asyncio
async def test_pdf_completion_rejects_mismatched_object_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    document_id = uuid4()
    actor = _actor()
    upload_job = SimpleNamespace(id=job_id, created_at=datetime.now(UTC))
    durable_job = SimpleNamespace(
        operation=JobOperation.PDF_PROCESS.value,
        requested_by_id=actor.id,
        status=JobStatus.RUNNING.value,
    )
    existing_paper = SimpleNamespace(
        id=document_id,
        title="upload.pdf",
        processing_status=DocumentProcessingStatus.PROCESSING.value,
        s3_object_key=f"documents/{'a' * 64}/source.pdf",
    )
    update_canonical = MagicMock()
    fail_job = MagicMock()

    monkeypatch.setattr(document_job_callbacks, "AdvisoryLock", _AvailableLock)
    monkeypatch.setattr(
        document_job_callbacks.upload_reservation_repository,
        "get_by",
        MagicMock(return_value=upload_job),
    )
    monkeypatch.setattr(
        document_job_callbacks.upload_reservation_repository,
        "get",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        document_job_callbacks.job_repository,
        "require",
        MagicMock(return_value=durable_job),
    )
    monkeypatch.setattr(
        document_job_callbacks.job_repository,
        "fail",
        fail_job,
    )
    monkeypatch.setattr(
        document_job_callbacks.zotero_import_repository,
        "get_by_upload_job_id",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        document_job_callbacks.document_repository,
        "find_by_upload_job",
        MagicMock(return_value=existing_paper),
    )
    monkeypatch.setattr(
        document_job_callbacks.document_repository,
        "update_canonical",
        update_canonical,
    )
    result = PDFProcessingResult(
        success=True,
        job_id=str(job_id),
        raw_content="Parsed paper content",
        page_offset_map={1: [0, 20]},
        s3_object_key=f"documents/{'b' * 64}/source.pdf",
        metadata=PaperMetadataExtraction(title="Canonical paper title"),
        parser_backend="pymupdf4llm",
        parser_quality="full",
        parser_version="test-parser",
    )
    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin("pdf_callback_test", uuid4()),
        credential=None,
    )

    handled = await document_job_callbacks.handle_paper_processing_webhook(
        str(job_id),
        PdfProcessingWebhookData(
            task_id=str(job_id),
            status="completed",
            result=result,
        ),
        MagicMock(),
        actor=actor,
        operation=operation,
    )

    update_canonical.assert_not_called()
    assert fail_job.call_args.kwargs["error_code"] == "job_result_key_mismatch"
    assert handled.value == {
        "status": "webhook processed - failed due to object key mismatch"
    }


def test_failed_upload_compensates_only_memberships_this_job_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    document_id = uuid4()
    project_id = uuid4()
    actor = _actor()
    upload_job = SimpleNamespace(
        id=job_id,
        reference_created=False,
        reference_created_library=True,
        reference_created_project=True,
    )
    durable_job = SimpleNamespace(
        operation=JobOperation.PDF_PROCESS.value,
        requested_by_id=actor.id,
        project_id=project_id,
        document_id=document_id,
        status=JobStatus.RUNNING.value,
        progress_code="parsing",
    )
    document = SimpleNamespace(
        id=document_id,
        processing_job_id=job_id,
        processing_status=DocumentProcessingStatus.PROCESSING.value,
    )
    db = MagicMock()
    db.scalar.return_value = document

    monkeypatch.setattr(
        document_job_callbacks.upload_reservation_repository,
        "get",
        MagicMock(return_value=SimpleNamespace(job=durable_job, **vars(upload_job))),
    )
    monkeypatch.setattr(
        document_job_callbacks.job_repository,
        "fail",
        MagicMock(),
    )
    monkeypatch.setattr(
        document_job_callbacks.zotero_import_repository,
        "get_by_upload_job_id",
        MagicMock(return_value=None),
    )
    gc_schedule = MagicMock()
    monkeypatch.setattr(
        document_job_callbacks,
        "schedule_document_gc",
        gc_schedule,
    )

    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin("pdf_callback_test", uuid4()),
        credential=None,
    )

    changes = document_job_callbacks.handle_failed_upload(
        db,
        str(job_id),
        actor,
        operation=operation,
        reason="pdf_content_insufficient",
    )

    assert any(str(change.action) == "document.processing_failed" for change in changes)
    delete_calls = [call.args[0] for call in db.execute.call_args_list]
    assert len(delete_calls) == 2
    gc_schedule.assert_called_once_with(
        db,
        document_id=document_id,
        origin_operation_id=operation.trace.operation_id,
        correlation_id=operation.trace.correlation_id,
    )


def test_failed_upload_keeps_pre_existing_memberships_when_nothing_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid4()
    document_id = uuid4()
    actor = _actor()
    upload_job = SimpleNamespace(
        id=job_id,
        reference_created=False,
        reference_created_library=False,
        reference_created_project=False,
    )
    durable_job = SimpleNamespace(
        operation=JobOperation.PDF_PROCESS.value,
        requested_by_id=actor.id,
        project_id=None,
        document_id=document_id,
        status=JobStatus.RUNNING.value,
        progress_code="parsing",
    )
    document = SimpleNamespace(
        id=document_id,
        processing_job_id=job_id,
        processing_status=DocumentProcessingStatus.PROCESSING.value,
    )
    db = MagicMock()
    db.scalar.return_value = document

    monkeypatch.setattr(
        document_job_callbacks.upload_reservation_repository,
        "get",
        MagicMock(return_value=SimpleNamespace(job=durable_job, **vars(upload_job))),
    )
    monkeypatch.setattr(
        document_job_callbacks.job_repository,
        "fail",
        MagicMock(),
    )
    monkeypatch.setattr(
        document_job_callbacks.zotero_import_repository,
        "get_by_upload_job_id",
        MagicMock(return_value=None),
    )
    gc_schedule = MagicMock()
    monkeypatch.setattr(
        document_job_callbacks,
        "schedule_document_gc",
        gc_schedule,
    )

    operation = OperationContextFactory().root(
        initiated_by=OperationInitiator.SYSTEM,
        origin=SchedulerOrigin("pdf_callback_test", uuid4()),
        credential=None,
    )

    document_job_callbacks.handle_failed_upload(
        db,
        str(job_id),
        actor,
        operation=operation,
        reason="pdf_content_insufficient",
    )

    assert db.execute.call_args_list == []
    gc_schedule.assert_not_called()
