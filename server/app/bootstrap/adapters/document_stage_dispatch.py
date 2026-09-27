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
    db: Session, *, document: Document, actor: Actor, operation: OperationContext
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
            idempotency_key=f"document-bibliography:{actor.id}:{document.id}:{identity}:{digest[:16]}",
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
    jobs = []
    stages = [(JobOperation.DOCUMENT_INDEX, "index_document", "deterministic")]
    if enrich:
        stages.append(
            (JobOperation.DOCUMENT_ENRICH, "enrich_document", "checkpoint_only")
        )
    for kind, task_name, replay in stages:
        job_id = uuid4()
        payload: dict[str, JsonValue] = {
            "ingestion_job_id": str(ingestion_job_id),
            "content_digest": digest,
        }
        kwargs: dict[str, JsonValue] = {
            "callback_url": f"{get_webhook_base_url().rstrip('/')}/internal/v1/jobs/{job_id}/complete",
            "parser_markdown_s3_key": document.parser_markdown_s3_key,
            "content_digest": digest,
        }
        if kind is JobOperation.DOCUMENT_INDEX:
            payload["model_revision"] = kwargs["model_revision"] = (
                EMBEDDING_MODEL_REVISION
            )
        jobs.append(
            job_repository.enqueue(
                db,
                request=EnqueueJob(
                    job_id=job_id,
                    operation=kind,
                    requested_by_id=actor.id,
                    correlation_id=operation.trace.correlation_id,
                    origin_operation_id=operation.trace.operation_id,
                    document_id=document.id,
                    idempotency_key=f"{kind.value}:{ingestion_job_id}",
                    payload=payload,
                    task_name=task_name,
                    queue=JobQueue.DOCUMENT_INDEX
                    if kind is JobOperation.DOCUMENT_INDEX
                    else JobQueue.DOCUMENT_ENRICHMENT,
                    task_kwargs=kwargs,
                    execution_replay="checkpoint_only"
                    if replay == "checkpoint_only"
                    else "deterministic",
                ),
            )
        )
    jobs.append(
        enqueue_document_bibliography(
            db, document=document, actor=actor, operation=operation
        )
    )
    return tuple(jobs)
