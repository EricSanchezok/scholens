"""Durable, deterministic metadata vectors independent of PDF/AI stages."""

from uuid import UUID, uuid4
import hashlib

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from scholens_ai import (
    EMBEDDING_MODEL_REVISION,
    semantic_document_text,
    semantic_source_digest,
)
from scholens_job_contracts import JobQueue
from sqlalchemy import false, select
from sqlalchemy.orm import Session, load_only

from app.helpers.celery_config import get_webhook_base_url
from app.modules.jobs.application.callbacks import JobHandlerResult
from app.modules.jobs.domain import MAINTENANCE_JOB_VISIBILITY
from app.modules.jobs.infrastructure.repository import (
    EnqueueJob,
    PersistedJob,
    job_repository,
)
from app.modules.papers.application.maintenance import SearchEmbeddingWrite
from app.modules.papers.infrastructure.access import accessible_document_condition
from app.modules.papers.infrastructure.models import Document
from app.modules.papers.infrastructure.search_embedding_maintenance import (
    SqlSearchEmbeddingBackfill,
)
from app.shared.application import Actor, OperationContext
from app.shared.domain.enums import JobOperation


def enqueue_metadata_projection(
    db: Session, *, document: Document, actor: Actor, operation: OperationContext
) -> PersistedJob | None:
    db.flush()
    text = semantic_document_text(
        title=document.title,
        keywords=document.keywords,
        summary=document.summary,
        abstract=document.abstract,
    )
    if not text:
        return None
    digest, job_id = semantic_source_digest(text), uuid4()
    identity = hashlib.sha256(
        f"{EMBEDDING_MODEL_REVISION}:{document.search_revision or 0}:{digest}".encode()
    ).hexdigest()
    return job_repository.enqueue(
        db,
        request=EnqueueJob(
            job_id=job_id,
            operation=JobOperation.DOCUMENT_SEARCH_INDEX,
            requested_by_id=actor.id,
            correlation_id=operation.trace.correlation_id,
            origin_operation_id=operation.trace.operation_id,
            document_id=document.id,
            idempotency_key=f"document-metadata:{document.id}:{identity}",
            payload={
                "source_digest": digest,
                "model_revision": EMBEDDING_MODEL_REVISION,
                "job_visibility": MAINTENANCE_JOB_VISIBILITY,
            },
            task_name="index_document_metadata",
            queue=JobQueue.DOCUMENT_INDEX,
            execution_replay="deterministic",
            task_kwargs={
                "callback_url": f"{get_webhook_base_url().rstrip('/')}/internal/v1/jobs/{job_id}/complete",
                "semantic_text": text,
                "source_digest": digest,
                "model_revision": EMBEDDING_MODEL_REVISION,
            },
        ),
    )


class DocumentSearchIndexCallback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_revision: str = Field(min_length=1, max_length=128)
    embedding: list[FiniteFloat] = Field(min_length=384, max_length=384)


class DocumentSearchIndexCompletion:
    def __init__(self, db: Session) -> None:
        self._db = db

    def complete(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        job_id: UUID,
        callback: BaseModel,
    ) -> JobHandlerResult:
        del operation
        if (
            not isinstance(callback, DocumentSearchIndexCallback)
            or callback.task_id != job_id
        ):
            raise ValueError("document_search_index_callback_mismatch")
        job = job_repository.require(self._db, job_id=job_id)
        if (
            job.payload.get("source_digest") != callback.source_digest
            or job.payload.get("model_revision") != callback.model_revision
        ):
            raise ValueError("document_search_index_snapshot_mismatch")
        document = self._db.scalar(
            select(Document)
            .where(
                Document.id == job.document_id,
                accessible_document_condition(user_id=actor.id) if actor else false(),
            )
            .options(load_only(Document.id))
            .with_for_update()
        )
        applied = 0
        if document is not None:
            applied, _ = SqlSearchEmbeddingBackfill(self._db).apply_embeddings(
                records=(
                    SearchEmbeddingWrite(
                        document_id=document.id,
                        source_digest=callback.source_digest,
                        embedding=tuple(callback.embedding),
                    ),
                ),
                model_revision=callback.model_revision,
            )
        if not applied:
            job_repository.fail(
                self._db, job_id=job_id, error_code="document_metadata_source_changed"
            )
            return JobHandlerResult(value={"accepted": False})
        job_repository.complete(
            self._db,
            job_id=job_id,
            result={
                "source_digest": callback.source_digest,
                "model_revision": callback.model_revision,
            },
        )
        return JobHandlerResult(value={"accepted": True})
