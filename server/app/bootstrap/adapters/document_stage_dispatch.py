"""Transactionally fan readable documents out to independently recoverable jobs."""

import hashlib
from uuid import UUID, uuid4

from scholens_ai import EMBEDDING_MODEL_REVISION
from scholens_job_contracts import JobQueue
from sqlalchemy.orm import Session

from app.bootstrap.adapters.document_bibliography import bibliography_identity
from app.helpers.celery_config import get_webhook_base_url
from app.modules.jobs.infrastructure.repository import (
    EnqueueJob,
    PersistedJob,
    job_repository,
)
from app.modules.papers.domain.citations import fields_from_paper
from app.modules.papers.infrastructure.models import Document
from app.shared.application import Actor, OperationContext
from app.shared.domain.enums import JobOperation
from app.shared.domain import JsonValue


def enqueue_document_bibliography(
    db: Session,
    *,
    document: Document,
    actor: Actor,
    operation: OperationContext,
    retry_of: UUID | None = None,
) -> PersistedJob:
    job_id = uuid4()
    digest = (
        document.content_digest
        or hashlib.sha256((document.raw_content or "").encode()).hexdigest()
    )
    identity = bibliography_identity(fields_from_paper(document))
    return job_repository.enqueue(
        db,
        request=EnqueueJob(
            job_id=job_id,
            operation=JobOperation.DOCUMENT_BIBLIOGRAPHY,
            requested_by_id=actor.id,
            correlation_id=operation.trace.correlation_id,
            origin_operation_id=operation.trace.operation_id,
            document_id=document.id,
            idempotency_key=(
                f"document-stage-retry:{retry_of}"
                if retry_of
                else f"document-bibliography:{actor.id}:{document.id}:{identity}:{digest[:16]}"
            ),
            payload={"content_digest": digest, "identity_digest": identity},
            task_name="hydrate_document_bibliography",
            queue=JobQueue.DOCUMENT_ENRICHMENT,
            task_kwargs={
                "callback_url": f"{get_webhook_base_url().rstrip('/')}/internal/v1/jobs/{job_id}/complete"
            },
            execution_replay="deterministic",
        ),
    )


def enqueue_document_stages(
    db: Session,
    *,
    document: Document,
    actor: Actor,
    operation: OperationContext,
    ingestion_job_id: UUID,
    enrich: bool,
) -> tuple[PersistedJob, ...]:
    if not document.raw_content or not document.parser_markdown_s3_key:
        return ()
    digest = (
        document.content_digest
        or hashlib.sha256(document.raw_content.encode()).hexdigest()
    )
    jobs = [
        enqueue_document_stage(
            db,
            document=document,
            actor=actor,
            operation=operation,
            kind=JobOperation.DOCUMENT_INDEX,
            source_id=ingestion_job_id,
            digest=digest,
        )
    ]
    if enrich:
        jobs.append(
            enqueue_document_stage(
                db,
                document=document,
                actor=actor,
                operation=operation,
                kind=JobOperation.DOCUMENT_ENRICH,
                source_id=ingestion_job_id,
                digest=digest,
            )
        )
    jobs.append(
        enqueue_document_bibliography(
            db, document=document, actor=actor, operation=operation
        )
    )
    return tuple(jobs)


def enqueue_document_stage(
    db: Session,
    *,
    document: Document,
    actor: Actor,
    operation: OperationContext,
    kind: JobOperation,
    source_id: UUID,
    digest: str,
    retry: bool = False,
) -> PersistedJob:
    """One canonical producer for initial work and explicitly requested retries."""
    if kind not in (JobOperation.DOCUMENT_INDEX, JobOperation.DOCUMENT_ENRICH):
        raise ValueError("unsupported document stage")
    job_id = uuid4()
    payload: dict[str, JsonValue] = {
        "retry_of" if retry else "ingestion_job_id": str(source_id),
        "content_digest": digest,
    }
    kwargs: dict[str, JsonValue] = {
        "callback_url": f"{get_webhook_base_url().rstrip('/')}/internal/v1/jobs/{job_id}/complete",
        "parser_markdown_s3_key": document.parser_markdown_s3_key,
        "content_digest": digest,
    }
    is_index = kind is JobOperation.DOCUMENT_INDEX
    if is_index:
        payload["model_revision"] = kwargs["model_revision"] = EMBEDDING_MODEL_REVISION
    return job_repository.enqueue(
        db,
        request=EnqueueJob(
            job_id=job_id,
            operation=kind,
            requested_by_id=actor.id,
            correlation_id=operation.trace.correlation_id,
            origin_operation_id=operation.trace.operation_id,
            document_id=document.id,
            idempotency_key=f"document-stage-retry:{source_id}"
            if retry
            else f"{kind.value}:{source_id}",
            payload=payload,
            task_name="index_document" if is_index else "enrich_document",
            queue=JobQueue.DOCUMENT_INDEX if is_index else JobQueue.DOCUMENT_ENRICHMENT,
            task_kwargs=kwargs,
            execution_replay="deterministic" if is_index else "checkpoint_only",
        ),
    )
