"""Compose authorized Paper state with requester-scoped durable Jobs."""

from typing import cast
from uuid import UUID

from scholens_ai import EMBEDDING_MODEL_REVISION
from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.bootstrap.adapters.document_stage_dispatch import (
    enqueue_document_bibliography,
    enqueue_document_stage,
)
from app.modules.jobs.infrastructure.models import DurableJob
from app.modules.papers.application.processing import (
    DocumentProcessingStatusResponse,
    DocumentStage,
    DocumentStageStatus,
    RetryDocumentStage,
    StageStatus,
)
from app.modules.papers.infrastructure.access import accessible_document_condition
from app.modules.papers.infrastructure.models import Document, DocumentTokenProjection
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import JobOperation

_STAGES: dict[DocumentStage, JobOperation] = {
    "index": JobOperation.DOCUMENT_INDEX,
    "enrichment": JobOperation.DOCUMENT_ENRICH,
    "bibliography": JobOperation.DOCUMENT_BIBLIOGRAPHY,
}
_TERMINAL = {"failed", "cancelled"}


class SqlDocumentProcessing:
    def __init__(self, db: Session, *, enabled: bool) -> None:
        self._db, self._enabled = db, enabled

    def _document(
        self, *, actor: Actor, document_id: UUID, lock: bool = False
    ) -> Document:
        statement = (
            select(Document)
            .where(
                Document.id == document_id,
                accessible_document_condition(user_id=actor.id),
            )
            .options(
                load_only(
                    Document.id,
                    Document.content_digest,
                    Document.processing_status,
                    Document.parser_markdown_s3_key,
                    Document.title,
                    Document.authors,
                    Document.doi,
                    Document.journal,
                    Document.publisher,
                    Document.publish_date,
                    raiseload=True,
                )
            )
        )
        if lock:
            statement = statement.with_for_update(of=Document)
        document = self._db.scalar(statement)
        if document is None:
            raise AppError(
                code="paper_not_found",
                message="Paper not found",
                kind=FailureKind.NOT_FOUND,
            )
        return document

    def _latest(
        self, *, actor: Actor, document_id: UUID, kind: JobOperation
    ) -> DurableJob | None:
        return self._db.scalar(
            select(DurableJob)
            .where(
                DurableJob.document_id == document_id,
                DurableJob.requested_by_id == actor.id,
                DurableJob.operation == kind.value,
            )
            .order_by(DurableJob.created_at.desc(), DurableJob.id.desc())
            .limit(1)
            .options(
                load_only(
                    DurableJob.id,
                    DurableJob.status,
                    DurableJob.payload,
                    DurableJob.error_code,
                    raiseload=True,
                )
            )
        )

    def _present(
        self,
        stage: DocumentStage,
        job: DurableJob | None,
        *,
        digest: str | None,
        readable: bool,
    ) -> DocumentStageStatus:
        if job is None:
            return DocumentStageStatus(stage=stage, status="not_requested")
        current = bool(digest) and job.payload.get("content_digest") == digest
        return DocumentStageStatus(
            stage=stage,
            job_id=job.id,
            status=cast(StageStatus, job.status) if current else "stale",
            can_retry=self._enabled
            and readable
            and current
            and job.status in _TERMINAL,
            required_integration="deepseek"
            if current
            and job.error_code
            in {"deepseek_credential_required", "deepseek_credential_invalid"}
            else None,
        )

    def get(
        self, *, actor: Actor, document_id: UUID
    ) -> DocumentProcessingStatusResponse:
        document = self._document(actor=actor, document_id=document_id)
        readable = document.processing_status == "completed"
        stages = [
            self._present(
                stage,
                self._latest(actor=actor, document_id=document_id, kind=kind),
                digest=document.content_digest,
                readable=readable,
            )
            for stage, kind in _STAGES.items()
        ]
        # The shared search projection is ready even if another authorized
        # reader produced it. Personal enrichment Jobs never cross this boundary.
        ready = (
            self._db.scalar(
                select(DocumentTokenProjection.document_id).where(
                    DocumentTokenProjection.document_id == document_id,
                    DocumentTokenProjection.content_digest == document.content_digest,
                    DocumentTokenProjection.model_revision == EMBEDDING_MODEL_REVISION,
                )
            )
            if document.content_digest
            else None
        )
        if ready is not None:
            stages[0] = DocumentStageStatus(stage="index", status="completed")
        return DocumentProcessingStatusResponse(
            document_id=document_id, readable=readable, stages=stages
        )

    def retry(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        request: RetryDocumentStage,
    ) -> tuple[DocumentStageStatus, bool]:
        kind = _STAGES[request.stage]
        # Match callback lock order (Job -> Document); serialize duplicate
        # submissions before creating the new execution and outbox dispatch.
        source = self._db.scalar(
            select(DurableJob)
            .where(
                DurableJob.id == request.job_id,
                DurableJob.requested_by_id == actor.id,
                DurableJob.document_id == document_id,
                DurableJob.operation == kind.value,
            )
            .with_for_update()
        )
        document = self._document(actor=actor, document_id=document_id, lock=True)
        digest = document.content_digest
        if (
            not self._enabled
            or source is None
            or source.status not in _TERMINAL
            or not digest
            or source.payload.get("content_digest") != digest
            or document.processing_status != "completed"
            or not document.parser_markdown_s3_key
        ):
            raise _not_retryable()
        existing = self._db.scalar(
            select(DurableJob).where(
                DurableJob.idempotency_key == f"document-stage-retry:{source.id}"
            )
        )
        if existing is not None:
            return self._present(
                request.stage, existing, digest=digest, readable=True
            ), False
        latest = self._latest(actor=actor, document_id=document_id, kind=kind)
        if latest is None or latest.id != source.id:
            raise _not_retryable()
        result = (
            enqueue_document_bibliography(
                self._db,
                document=document,
                actor=actor,
                operation=operation,
                retry_of=source.id,
            )
            if kind is JobOperation.DOCUMENT_BIBLIOGRAPHY
            else enqueue_document_stage(
                self._db,
                document=document,
                actor=actor,
                operation=operation,
                kind=kind,
                source_id=source.id,
                digest=digest,
                retry=True,
            )
        )
        return self._present(
            request.stage, result.job, digest=digest, readable=True
        ), result.created


def _not_retryable() -> AppError:
    return AppError(
        code="document_stage_not_retryable",
        message="Stage is not retryable; refresh its current state",
        kind=FailureKind.CONFLICT,
    )
