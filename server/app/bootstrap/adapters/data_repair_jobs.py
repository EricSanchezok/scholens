"""Composition adapter: enqueue a dispatchable pdf-process reprocess job.

The legacy data-repair gateway lives in ``app.modules.papers`` and must not
reach into ``app.modules.jobs.infrastructure``. Enqueuing a durable job with
its outbox dispatch and upload reservation is composition-layer work, so it
lives here and is injected into the gateway as a plain callable.
"""

from __future__ import annotations

import uuid

from scholens_job_contracts import JobQueue
from sqlalchemy.orm import Session

from app.database.models import (
    Document,
    DocumentProcessingStatus,
    DurableJob,
    UploadReservation,
)
from app.helpers.celery_config import get_webhook_base_url
from app.modules.jobs.infrastructure.repository import EnqueueJob, job_repository
from app.shared.domain.enums import JobOperation


def enqueue_reprocess_job(
    *,
    db: Session,
    source: DurableJob,
    document: Document,
    reservation: UploadReservation | None,
) -> bool:
    """Enqueue one fresh pdf_process job for a contaminated document.

    The new job reuses the original requester, correlation and origin so the
    terminal webhook can resume the same actor, and reuses the document's
    content-addressed source S3 key. A matching upload reservation is created
    with ``reference_created=False`` so the failure path never tears down an
    existing Library/Project membership, and ``reserved_reference_count=0`` so
    no reference quota is consumed. Existing storage is not reserved again.
    The original terminal job row stays immutable; the new job supersedes it
    through the ordinary worker + webhook path.
    """
    new_job_id = uuid.uuid4()
    base_url = get_webhook_base_url().rstrip("/")
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
            payload={
                "content_sha256": document.sha256,
                "original_filename": document.original_filename,
                "input_size_bytes": document.size_bytes,
                "s3_object_key": document.s3_object_key,
                "skip_metadata_extraction": False,
            },
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
        reference_created=False,
    )
    new_reservation.job = persisted.job
    db.add(new_reservation)
    document.processing_status = DocumentProcessingStatus.PROCESSING.value
    document.processing_job_id = new_job_id
    return True


__all__ = ["enqueue_reprocess_job"]
