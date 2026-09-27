"""Fail an ownerless import without impersonating a user or applying its result."""

from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.bootstrap.adapters.document_gc import schedule_document_gc
from app.modules.jobs.infrastructure.repository import job_repository
from app.modules.jobs.application.callbacks import (
    JobHandlerResult,
    ReleaseJobConcurrency,
)
from app.modules.papers.infrastructure.models import Document
from app.modules.papers.application.actions import DOCUMENT_PROCESSING_FAILED
from app.modules.operation_journal.domain import OperationChange, ResourceRef
from app.shared.application import OperationContext


def fail_orphaned_document_job(
    db: Session, *, job_id: UUID, operation: OperationContext, error_code: str
) -> JobHandlerResult:
    job = job_repository.require(db, job_id=job_id)
    document = db.scalar(
        select(Document).where(Document.id == job.document_id).with_for_update()
    )
    changes = []
    if (
        document is not None
        and document.processing_job_id == job_id
        and document.processing_status in {"pending", "processing"}
    ):
        document.processing_status = "failed"
        document.parser_warning_code = "processing_failed"
        changes.append(
            OperationChange(
                action=DOCUMENT_PROCESSING_FAILED,
                resources=(ResourceRef("document", str(document.id)),),
            )
        )
        schedule_document_gc(
            db,
            document_id=document.id,
            origin_operation_id=operation.trace.operation_id,
            correlation_id=operation.trace.correlation_id,
        )
    _, changed = job_repository.fail(db, job_id=job_id, error_code=error_code)
    effects = (
        (
            ReleaseJobConcurrency(
                user_id=job.requested_by_id, category="background", job_id=job_id
            ),
        )
        if job.requested_by_id is not None
        else ()
    )
    return JobHandlerResult(
        value={"accepted": changed}, changes=changes, post_commit=effects
    )
