"""Cross-module delayed, reference-safe cleanup for canonical documents."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from heapq import merge

from scholens_job_contracts import JobQueue, require_storage_delete_key
from sqlalchemy import exists, func, literal, or_, select, tuple_, update
from sqlalchemy.orm import Session, load_only

from app.bootstrap.adapters.document_repair_artifacts import (
    UNICODE_REPAIR_KIND,
    bounded_unicode_repair_audit_result,
    unicode_repair_artifact_keys,
)
from app.bootstrap.adapters.storage_cleanup import (
    ScheduledStorageDeletion,
    schedule_storage_deletion,
)
from app.database.models import (
    Conversation,
    ConversationScopeType,
    Document,
    DurableJob,
    JobOperation,
    JobStatus,
    LibraryPaper,
    ProjectPaper,
    ResearchAudioOverview,
    ResearchItem,
)
from app.helpers.celery_config import get_webhook_base_url
from app.modules.jobs.infrastructure.repository import EnqueueJob, job_repository
from app.modules.reflows.infrastructure.models import DocumentReflowAsset
from app.shared.domain import AppError, FailureKind

DOCUMENT_GC_GRACE_PERIOD = timedelta(hours=24)
DOCUMENT_GC_STORAGE_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class ScheduledDocumentGc:
    job_id: uuid.UUID
    created: bool


def _has_references(db: Session, *, document_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(
            select(
                or_(
                    exists(
                        select(LibraryPaper.id).where(
                            LibraryPaper.document_id == document_id
                        )
                    ),
                    exists(
                        select(ProjectPaper.id).where(
                            ProjectPaper.document_id == document_id
                        )
                    ),
                )
            )
        )
    )


def schedule_document_gc(
    db: Session,
    *,
    document_id: uuid.UUID,
    origin_operation_id: uuid.UUID,
    correlation_id: uuid.UUID,
    now: datetime | None = None,
) -> ScheduledDocumentGc | None:
    document = db.scalar(
        select(Document).where(Document.id == document_id).with_for_update()
    )
    if document is None:
        return None
    if _has_references(db, document_id=document_id):
        document.gc_after = None
        return None
    document.gc_after = (now or datetime.now(timezone.utc)) + DOCUMENT_GC_GRACE_PERIOD
    job_id = uuid.uuid4()
    base_url = get_webhook_base_url().rstrip("/")
    persisted = job_repository.enqueue(
        db,
        request=EnqueueJob(
            operation=JobOperation.DOCUMENT_GC,
            requested_by_id=None,
            correlation_id=correlation_id,
            origin_operation_id=origin_operation_id,
            document_id=document.id,
            idempotency_key=(
                f"document-gc:{document.id}:{document.gc_after.isoformat()}"
            ),
            payload={"document_id": str(document.id)},
            task_name="collect_document",
            queue=JobQueue.MAINTENANCE,
            task_kwargs={
                "callback_url": (f"{base_url}/internal/v1/jobs/{job_id}/complete"),
                "claim_url": f"{base_url}/internal/v1/jobs/{job_id}/claim",
            },
            job_id=job_id,
            available_at=document.gc_after,
        ),
    )
    return ScheduledDocumentGc(
        job_id=persisted.job.id,
        created=persisted.created,
    )


@dataclass(frozen=True, slots=True)
class DocumentGcResult:
    document_id: uuid.UUID
    deleted: bool
    cancelled: bool
    storage_deletion: ScheduledStorageDeletion | None = None


def _primary_document_storage_keys(document: Document) -> Iterator[str]:
    for raw_key in sorted(
        key
        for key in (
            document.s3_object_key,
            document.preview_s3_key,
            document.parser_markdown_s3_key,
            document.parser_archive_s3_key,
        )
        if key is not None
    ):
        yield require_storage_delete_key(raw_key)


def _reflow_storage_keys(db: Session, *, document_id: uuid.UUID) -> Iterator[str]:
    after_key: str | None = None
    while True:
        statement = (
            select(DocumentReflowAsset.object_key)
            .where(DocumentReflowAsset.document_id == document_id)
            .distinct()
            .order_by(DocumentReflowAsset.object_key)
            .limit(DOCUMENT_GC_STORAGE_PAGE_SIZE)
        )
        if after_key is not None:
            statement = statement.where(DocumentReflowAsset.object_key > after_key)
        page = tuple(db.scalars(statement).all())
        if not page:
            return
        for raw_key in page:
            key = require_storage_delete_key(raw_key)
            yield key
            after_key = key


def _audio_storage_keys(db: Session, *, document_id: uuid.UUID) -> Iterator[str]:
    after_key: str | None = None
    while True:
        statement = (
            select(ResearchAudioOverview.s3_object_key)
            .join(
                ResearchItem,
                ResearchItem.id == ResearchAudioOverview.research_item_id,
            )
            .where(
                or_(
                    ResearchItem.audience_document_id == document_id,
                    ResearchItem.target_document_id == document_id,
                )
            )
            .distinct()
            .order_by(ResearchAudioOverview.s3_object_key)
            .limit(DOCUMENT_GC_STORAGE_PAGE_SIZE)
        )
        if after_key is not None:
            statement = statement.where(ResearchAudioOverview.s3_object_key > after_key)
        page = tuple(db.scalars(statement).all())
        if not page:
            return
        for raw_key in page:
            key = require_storage_delete_key(raw_key)
            yield key
            after_key = key


def _sanitize_repair_job_results(db: Session, *, document_id: uuid.UUID) -> None:
    """Shrink legacy repair results one locked row at a time."""

    after_id: uuid.UUID | None = None
    while True:
        statement = (
            select(DurableJob)
            .options(load_only(DurableJob.id, DurableJob.payload, DurableJob.result))
            .where(
                DurableJob.document_id == document_id,
                DurableJob.payload["repair_kind"].as_string() == UNICODE_REPAIR_KIND,
            )
            .order_by(DurableJob.id)
            .limit(1)
            .with_for_update()
        )
        if after_id is not None:
            statement = statement.where(DurableJob.id > after_id)
        repair_job = db.scalar(statement)
        if repair_job is None:
            return
        repair_job.result = bounded_unicode_repair_audit_result(repair_job.result)
        db.flush([repair_job])
        after_id = repair_job.id
        db.expunge(repair_job)


def _lock_repair_jobs_or_raise(db: Session, *, document_id: uuid.UUID) -> None:
    """Avoid Document-to-Job deadlocks with an in-flight repair callback."""

    repair_filter = (
        DurableJob.document_id == document_id,
        DurableJob.payload["repair_kind"].as_string() == UNICODE_REPAIR_KIND,
    )
    expected_count = int(
        db.scalar(select(func.count(DurableJob.id)).where(*repair_filter)) or 0
    )
    locked_count = 0
    for _job_id in db.scalars(
        select(DurableJob.id)
        .where(*repair_filter)
        .order_by(DurableJob.id)
        .with_for_update(skip_locked=True)
        .execution_options(yield_per=DOCUMENT_GC_STORAGE_PAGE_SIZE)
    ):
        locked_count += 1
    if locked_count != expected_count:
        raise AppError(
            code="document_gc_repair_busy",
            message="Document repair is still being finalized",
            kind=FailureKind.UNAVAILABLE,
        )


def _raise_if_active_document_work(db: Session, *, document_id: uuid.UUID) -> None:
    active_count = int(
        db.scalar(
            select(func.count(DurableJob.id)).where(
                DurableJob.document_id == document_id,
                DurableJob.operation != JobOperation.DOCUMENT_GC.value,
                DurableJob.status.in_(
                    (JobStatus.PENDING.value, JobStatus.RUNNING.value)
                ),
            )
        )
        or 0
    )
    if active_count:
        raise AppError(
            code="document_gc_has_active_jobs",
            message="Document processing is still active",
            kind=FailureKind.UNAVAILABLE,
        )


def _repair_storage_keys(
    db: Session,
    *,
    document_id: uuid.UUID,
    content_sha256: str,
) -> Iterator[str]:
    """Yield valid repair artifacts in lexicographic namespace order."""

    content_field = DurableJob.payload["content_sha256"].as_string()
    revision_field = DurableJob.payload["repair_revision"].as_string()
    after: tuple[str, str, uuid.UUID] | None = None
    while True:
        statement = (
            select(DurableJob.id, content_field, revision_field)
            .where(
                DurableJob.document_id == document_id,
                DurableJob.payload["repair_kind"].as_string() == UNICODE_REPAIR_KIND,
                content_field == content_sha256,
                revision_field.op("~")(r"^[a-z0-9][a-z0-9-]{0,63}$"),
            )
            .order_by(content_field, revision_field, DurableJob.id)
            .limit(DOCUMENT_GC_STORAGE_PAGE_SIZE)
        )
        if after is not None:
            statement = statement.where(
                tuple_(content_field, revision_field, DurableJob.id)
                > tuple_(literal(after[0]), literal(after[1]), literal(after[2]))
            )
        page = tuple(db.execute(statement))
        if not page:
            return
        for job_id, row_content_sha256, repair_revision in page:
            if row_content_sha256 != content_sha256:
                raise RuntimeError("document_gc_repair_scope_mismatch")
            artifact_keys = unicode_repair_artifact_keys(
                job_id=job_id,
                payload={
                    "repair_kind": UNICODE_REPAIR_KIND,
                    "repair_revision": repair_revision,
                    "content_sha256": row_content_sha256,
                },
            )
            if not artifact_keys:
                raise RuntimeError("document_gc_repair_namespace_invalid")
            for artifact_key in artifact_keys:
                yield require_storage_delete_key(artifact_key)
            after = (row_content_sha256, repair_revision, job_id)


def _document_storage_keys(
    db: Session,
    *,
    document: Document,
) -> Iterator[str]:
    previous_key: str | None = None
    streams = (
        _primary_document_storage_keys(document),
        _reflow_storage_keys(db, document_id=document.id),
        _audio_storage_keys(db, document_id=document.id),
        _repair_storage_keys(
            db,
            document_id=document.id,
            content_sha256=document.sha256,
        ),
    )
    for key in merge(*streams):
        if key == previous_key:
            continue
        if previous_key is not None and key < previous_key:
            raise RuntimeError("document_gc_storage_key_order_invalid")
        yield key
        previous_key = key


def collect_document_if_due(
    db: Session,
    *,
    document_id: uuid.UUID,
    origin_operation_id: uuid.UUID,
    correlation_id: uuid.UUID,
    now: datetime | None = None,
) -> DocumentGcResult:
    current_time = now or datetime.now(timezone.utc)
    document = db.scalar(
        select(Document).where(Document.id == document_id).with_for_update()
    )
    if document is None:
        return DocumentGcResult(document_id, deleted=True, cancelled=False)
    if _has_references(db, document_id=document_id):
        document.gc_after = None
        return DocumentGcResult(document_id, deleted=False, cancelled=True)
    if document.gc_after is None or document.gc_after > current_time:
        return DocumentGcResult(document_id, deleted=False, cancelled=False)

    # Repair callbacks lock DurableJob before Document. We already hold the
    # Document, so skip any locked repair row and retry the whole callback
    # instead of waiting in the reverse order and forming a deadlock.
    _raise_if_active_document_work(db, document_id=document_id)
    _lock_repair_jobs_or_raise(db, document_id=document_id)
    _sanitize_repair_job_results(db, document_id=document_id)
    storage_deletion = schedule_storage_deletion(
        db,
        object_keys=_document_storage_keys(db, document=document),
        idempotency_key=f"document:{document_id}",
        origin_operation_id=origin_operation_id,
        correlation_id=correlation_id,
    )

    db.execute(
        update(Conversation)
        .where(
            Conversation.scope_type == ConversationScopeType.PAPER.value,
            Conversation.document_id == document_id,
        )
        .values(
            scope_label_snapshot=func.coalesce(
                Conversation.scope_label_snapshot,
                document.title,
                document.original_filename,
            ),
            context_deleted_at=current_time,
        )
    )
    db.delete(document)
    db.flush()
    return DocumentGcResult(
        document_id,
        deleted=True,
        cancelled=False,
        storage_deletion=storage_deletion,
    )


def list_due_document_ids(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> list[uuid.UUID]:
    current_time = now or datetime.now(timezone.utc)
    return list(
        db.scalars(
            select(Document.id)
            .where(
                Document.gc_after.isnot(None),
                Document.gc_after <= current_time,
            )
            .order_by(Document.gc_after.asc())
            .limit(limit)
        ).all()
    )


__all__ = [
    "DOCUMENT_GC_GRACE_PERIOD",
    "DocumentGcResult",
    "ScheduledDocumentGc",
    "collect_document_if_due",
    "list_due_document_ids",
    "schedule_document_gc",
]
