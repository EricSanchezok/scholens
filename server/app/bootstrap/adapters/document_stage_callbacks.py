"""Independent document stage consumers with canonical-source and access fences."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict
from scholens_ai import TokenProjection
from sqlalchemy import false, select
from sqlalchemy.orm import Session

from app.modules.jobs.application.callbacks import JobHandlerResult
from app.modules.jobs.infrastructure.repository import job_repository
from app.modules.papers.infrastructure.models import Document
from app.modules.papers.infrastructure.access import accessible_document_condition
from app.modules.papers.infrastructure.token_projection import TokenProjectionRepository
from app.shared.application import Actor, OperationContext


class DocumentIndexCallback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: UUID
    projection: TokenProjection


class DocumentIndexCompletion:
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
            not isinstance(callback, DocumentIndexCallback)
            or callback.task_id != job_id
        ):
            raise ValueError("document_index_callback_mismatch")
        job = job_repository.require(self._db, job_id=job_id)
        projection = callback.projection
        if (
            job.payload.get("content_digest") != projection.content_digest
            or job.payload.get("model_revision") != projection.model_revision
        ):
            raise ValueError("document_index_snapshot_mismatch")
        document_id = self._db.scalar(
            select(Document.id)
            .where(
                Document.id == job.document_id,
                accessible_document_condition(user_id=actor.id)
                if actor is not None
                else false(),
            )
            .with_for_update()
        )
        if document_id is None or not TokenProjectionRepository(self._db).adopt(
            document_id=document_id,
            projection=projection,
        ):
            job_repository.fail(
                self._db, job_id=job_id, error_code="document_stage_source_changed"
            )
            return JobHandlerResult(value={"accepted": False})
        job_repository.complete(
            self._db,
            job_id=job_id,
            result={
                "document_id": str(document_id),
                "passage_count": len(projection.spans),
                "content_digest": projection.content_digest,
                "model_revision": projection.model_revision,
            },
        )
        return JobHandlerResult(value={"accepted": True})
