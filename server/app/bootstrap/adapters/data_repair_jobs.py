"""Composition adapter: enqueue a dispatchable pdf-process reprocess job.

The legacy data-repair gateway lives in ``app.modules.papers`` and must not
reach into ``app.modules.jobs.infrastructure``. Enqueuing a durable job with
its outbox dispatch and upload reservation is composition-layer work, so it
lives here and is injected into the gateway as a plain callable.
"""

from __future__ import annotations

import uuid

from scholens_job_contracts import JobQueue
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import (
    Document,
    DocumentProcessingStatus,
    DurableJob,
    JobStatus,
    UploadReservation,
)
from app.helpers.celery_config import get_webhook_base_url
from app.modules.jobs.infrastructure.repository import EnqueueJob, job_repository
from app.shared.domain import JsonValue
from app.shared.domain.enums import JobOperation


def _recovery_attempt(source: DurableJob) -> int:
    value = source.payload.get("recovery_attempt", 0)
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else 0
    )


def enqueue_reprocess_job(
    *,
    db: Session,
    source: DurableJob,
    document: Document,
    reservation: UploadReservation | None,
    source_failure_code: str | None = None,
) -> bool:
    """Enqueue one fresh pdf_process job for an existing canonical document.

    The new job reuses the original requester, correlation and origin so the
    terminal webhook can resume the same actor, and reuses the document's
    content-addressed source S3 key. A matching upload reservation is created
    with ``reference_created=False`` so the failure path never tears down an
    existing Library/Project membership, and ``reserved_reference_count=0`` so
    no reference quota is consumed. Existing storage is not reserved again.
    A terminal source stays immutable. When ``source_failure_code`` is provided,
    the source is an unclaimed pending job: the same transaction fails it,
    supersedes its reservation, and points the document at the replacement.
    """
    new_job_id = uuid.uuid4()
    base_url = get_webhook_base_url().rstrip("/")
    payload: dict[str, JsonValue] = {
        "content_sha256": document.sha256,
        "original_filename": document.original_filename,
        "input_size_bytes": document.size_bytes,
        "s3_object_key": document.s3_object_key,
        "skip_metadata_extraction": False,
    }
    if source_failure_code is not None:
        payload["recovery_attempt"] = _recovery_attempt(source) + 1
    persisted = job_repository.enqueue(
        db,
        request=EnqueueJob(
            operation=JobOperation.PDF_PROCESS,
            requested_by_id=source.requested_by_id,
            correlation_id=source.correlation_id,
            origin_operation_id=source.origin_operation_id,
            project_id=source.project_id,
            document_id=document.id,
            idempotency_key=f"pdf-reprocess:{source.id}",
            payload=payload,
            task_name="upload_and_process_file",
            queue=JobQueue.DOCUMENT,
            task_kwargs={
                "s3_object_key": document.s3_object_key,
                "webhook_url": (f"{base_url}/internal/v1/jobs/{new_job_id}/complete"),
                "claim_url": f"{base_url}/internal/v1/jobs/{new_job_id}/claim",
                "credential_url": (
                    f"{base_url}/internal/v1/jobs/{new_job_id}"
                    "/integration-credentials/mineru"
                ),
                "progress_url": (f"{base_url}/internal/v1/jobs/{new_job_id}/progress"),
                "skip_metadata_extraction": False,
            },
            job_id=new_job_id,
        ),
    )
    if not persisted.created:
        return False
    display_name = (
        reservation.display_name
        if reservation is not None
        else document.original_filename
    )
    source_kind = reservation.source_kind if reservation is not None else "upload"
    new_reservation = UploadReservation(
        id=new_job_id,
        quota_owner_id=(
            reservation.quota_owner_id
            if reservation is not None
            else source.requested_by_id
        ),
        # Reprocessing an existing canonical Document does not reserve new
        # storage; its source object is already charged to the account.
        reserved_size_kb=0,
        reserved_reference_count=0,
        content_sha256=document.sha256,
        original_filename=document.original_filename,
        display_name=display_name,
        source_kind=source_kind,
        add_to_library=(
            reservation.add_to_library if reservation is not None else None
        ),
        reference_created=False,
    )
    new_reservation.job = persisted.job
    db.add(new_reservation)
    if reservation is not None:
        reservation.superseded_by_id = new_job_id
    if source_failure_code is not None:
        _source, failed = job_repository.fail(
            db,
            job_id=source.id,
            error_code=source_failure_code,
            result={"recovered_by_job_id": str(new_job_id)},
        )
        if not failed:
            raise RuntimeError("stale_pdf_source_cannot_fail")
    document.processing_status = DocumentProcessingStatus.PROCESSING.value
    document.processing_job_id = new_job_id
    return True


def recover_unclaimed_pdf_job(db: Session, source: DurableJob) -> None:
    """Recover one stale published PDF job without changing paper membership."""
    if (
        source.operation != JobOperation.PDF_PROCESS.value
        or source.status != JobStatus.PENDING.value
        or source.document_id is None
        or source.requested_by_id is None
    ):
        raise RuntimeError("stale_pdf_job_contract_mismatch")
    document = db.scalar(
        select(Document).where(Document.id == source.document_id).with_for_update()
    )
    if document is None or document.processing_job_id != source.id:
        job_repository.fail(
            db,
            job_id=source.id,
            error_code="paper_ingestion_claim_failed",
        )
        return
    if document.processing_status != DocumentProcessingStatus.PROCESSING.value:
        job_repository.fail(
            db,
            job_id=source.id,
            error_code="paper_ingestion_claim_failed",
        )
        return

    recovery_attempt = _recovery_attempt(source)
    if recovery_attempt >= 1:
        _source, failed = job_repository.fail(
            db,
            job_id=source.id,
            error_code="paper_ingestion_claim_failed",
        )
        if failed:
            document.processing_status = DocumentProcessingStatus.FAILED.value
            document.parser_warning_code = "processing_failed"
        return

    reservation = db.get(UploadReservation, source.id)
    if not enqueue_reprocess_job(
        db=db,
        source=source,
        document=document,
        reservation=reservation,
        source_failure_code="paper_ingestion_claim_failed",
    ):
        raise RuntimeError("stale_pdf_recovery_idempotency_conflict")


__all__ = ["enqueue_reprocess_job", "recover_unclaimed_pdf_job"]
