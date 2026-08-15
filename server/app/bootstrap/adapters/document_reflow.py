"""Cross-module SQL/outbox adapter for durable document reflow artifacts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from app.modules.jobs.application.contracts import (
    DocumentReflowTaskPayload,
    ReflowAssetKind,
    ReflowBlockKind,
    ReflowPresentationStatus,
    ReflowSourceRectPayload,
    ReflowSourceSpanPayload,
)
from app.modules.jobs.application.jobs import EnqueueJobCommand
from app.modules.jobs.application.failures import actionable_job_failure
from app.modules.jobs.infrastructure.application_gateway import SqlAlchemyJobsGateway
from app.modules.papers.infrastructure.models import Document
from app.modules.reflows.application.contracts import (
    DocumentReflowBlockResponse,
    DocumentReflowAssetResponse,
    DocumentReflowAssetUrlResponse,
    DocumentReflowResponse,
    DocumentReflowStatus,
)
from app.modules.reflows.infrastructure.models import (
    DocumentReflow,
    DocumentReflowAsset,
    DocumentReflowBlock,
)
from app.helpers.s3 import s3_service
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind, JsonValue
from app.shared.domain.enums import DocumentProcessingStatus, JobOperation, JobStatus
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class SqlDocumentReflowGateway:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._jobs = SqlAlchemyJobsGateway(db)

    def _load(self, document_id: UUID, *, lock: bool = False) -> DocumentReflow | None:
        statement = (
            select(DocumentReflow)
            .where(DocumentReflow.document_id == document_id)
            .options(
                selectinload(DocumentReflow.blocks),
                selectinload(DocumentReflow.assets),
                selectinload(DocumentReflow.job),
            )
        )
        if lock:
            statement = statement.with_for_update()
        return self._db.scalar(statement)

    def _lock_source(self, document_id: UUID) -> Document | None:
        return self._db.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )

    @staticmethod
    def _response(artifact: DocumentReflow) -> DocumentReflowResponse:
        status: DocumentReflowStatus
        if artifact.status == "completed":
            status = "completed"
        elif (
            artifact.status == "failed" or artifact.job.status == JobStatus.FAILED.value
        ):
            status = "failed"
        elif artifact.job.status == JobStatus.RUNNING.value:
            status = "processing"
        else:
            status = "pending"
        expose_artifact = status == "completed"
        return DocumentReflowResponse(
            document_id=artifact.document_id,
            status=status,
            job_id=artifact.job_id,
            attempt_count=artifact.attempt_count,
            failure=actionable_job_failure(
                artifact.error_code or artifact.job.error_code
            ),
            pipeline_revision=artifact.pipeline_revision,
            parser_revision=artifact.parser_revision,
            warnings=list(artifact.warnings or []),
            blocks=[
                DocumentReflowBlockResponse(
                    id=block.id,
                    index=block.block_index,
                    kind=cast(ReflowBlockKind, block.kind),
                    render_markdown=block.render_markdown,
                    group_id=block.group_id,
                    heading_level=block.heading_level,
                    source_spans=[
                        ReflowSourceSpanPayload.model_validate(span)
                        for span in block.source_spans
                    ],
                    presentation_status=cast(
                        ReflowPresentationStatus, block.presentation_status
                    ),
                    asset_id=block.asset_id,
                )
                for block in artifact.blocks
            ]
            if expose_artifact
            else [],
            assets=[
                DocumentReflowAssetResponse(
                    id=asset.id,
                    kind=cast(ReflowAssetKind, asset.kind),
                    content_type=asset.content_type,
                    width=asset.width,
                    height=asset.height,
                    page_number=asset.page_number,
                    source_rect=ReflowSourceRectPayload.model_validate(
                        asset.source_rect
                    ),
                    checksum=asset.checksum,
                )
                for asset in artifact.assets
            ]
            if expose_artifact
            else [],
            updated_at=artifact.updated_at,
        )

    def get(self, *, document_id: UUID) -> DocumentReflowResponse:
        artifact = self._load(document_id)
        if artifact is not None:
            return self._response(artifact)
        return DocumentReflowResponse(
            document_id=document_id,
            status="not_requested",
            job_id=None,
            attempt_count=0,
            failure=None,
            pipeline_revision=None,
            parser_revision=None,
            warnings=[],
            blocks=[],
            assets=[],
            updated_at=None,
        )

    def get_block(
        self,
        *,
        document_id: UUID,
        block_id: str,
    ) -> DocumentReflowBlockResponse | None:
        block = self._db.scalar(
            select(DocumentReflowBlock)
            .join(DocumentReflow)
            .where(
                DocumentReflowBlock.document_id == document_id,
                DocumentReflowBlock.id == block_id,
                DocumentReflow.status == "completed",
            )
        )
        if block is None:
            return None
        return DocumentReflowBlockResponse(
            id=block.id,
            index=block.block_index,
            kind=cast(ReflowBlockKind, block.kind),
            render_markdown=block.render_markdown,
            group_id=block.group_id,
            heading_level=block.heading_level,
            source_spans=[
                ReflowSourceSpanPayload.model_validate(span)
                for span in block.source_spans
            ],
            presentation_status=cast(
                ReflowPresentationStatus, block.presentation_status
            ),
            asset_id=block.asset_id,
        )

    def get_asset_url(
        self, *, document_id: UUID, asset_id: str
    ) -> DocumentReflowAssetUrlResponse | None:
        asset = self._db.scalar(
            select(DocumentReflowAsset)
            .join(DocumentReflow)
            .where(
                DocumentReflowAsset.document_id == document_id,
                DocumentReflowAsset.id == asset_id,
                DocumentReflow.status == "completed",
            )
        )
        if asset is None:
            return None
        expires_in = 900
        return DocumentReflowAssetUrlResponse(
            asset_id=asset.id,
            url=s3_service.generate_presigned_url(asset.object_key, expires_in),
            expires_in=expires_in,
        )

    def ensure(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        idempotency_key: str | None,
    ) -> tuple[DocumentReflowResponse, bool]:
        return self.ensure_causality(
            actor=actor,
            correlation_id=operation.trace.correlation_id,
            origin_operation_id=operation.trace.operation_id,
            document_id=document_id,
            idempotency_key=idempotency_key,
        )

    def ensure_causality(
        self,
        *,
        actor: Actor,
        correlation_id: UUID,
        origin_operation_id: UUID,
        document_id: UUID,
        idempotency_key: str | None,
    ) -> tuple[DocumentReflowResponse, bool]:
        # The Document row exists before the first reflow attempt, so it is the
        # stable serialization point for both first creation and retries. A
        # missing DocumentReflow row cannot itself be locked.
        document = self._lock_source(document_id)
        if (
            document is None
            or document.processing_status != DocumentProcessingStatus.COMPLETED.value
            or not document.s3_object_key
        ):
            raise AppError(
                code="document_reflow_source_not_ready",
                message="The parsed paper is not ready for reflow",
                kind=FailureKind.CONFLICT,
            )

        # Re-read only after the stable source lock is held. Concurrent callers
        # then observe the attempt committed by the lock winner and reuse it.
        artifact = self._load(document_id)
        if artifact is not None and (
            artifact.status == "completed"
            or artifact.job.status in {JobStatus.PENDING.value, JobStatus.RUNNING.value}
        ):
            return self._response(artifact), False

        attempt = (artifact.attempt_count + 1) if artifact is not None else 1
        durable_idempotency_key = (
            f"document-reflow:{document.id}:request:{idempotency_key}"
            if idempotency_key
            else f"document-reflow:{document.id}:{attempt}"
        )
        existing = self._jobs.find_by_idempotency_key(key=durable_idempotency_key)
        if existing is not None:
            if artifact is not None and existing.id == artifact.job_id:
                return self._response(artifact), False
            raise AppError(
                code="idempotency_key_reused",
                message="The idempotency key was already used for another reflow attempt",
                kind=FailureKind.CONFLICT,
            )
        job_id = uuid4()
        payload_model = DocumentReflowTaskPayload(
            document_id=document.id,
            title=document.title or document.original_filename,
            pdf_s3_key=document.s3_object_key,
            mineru_archive_s3_key=(
                document.parser_archive_s3_key
                if document.parser_backend == "mineru"
                else None
            ),
            mineru_archive_parser_revision=(
                document.parser_version if document.parser_backend == "mineru" else None
            ),
        )
        payload = _JSON_OBJECT.validate_python(payload_model.model_dump(mode="json"))
        enqueued = self._jobs.enqueue(
            command=EnqueueJobCommand(
                job_id=job_id,
                operation=JobOperation.DOCUMENT_REFLOW,
                requested_by_id=actor.id,
                correlation_id=correlation_id,
                origin_operation_id=origin_operation_id,
                idempotency_key=durable_idempotency_key,
                payload=payload,
                task_name="generate_document_reflow",
                queue="reflow",
                document_id=document.id,
            )
        )
        if artifact is None:
            artifact = DocumentReflow(
                document_id=document.id,
                job_id=enqueued.job.id,
                attempt_count=attempt,
            )
            self._db.add(artifact)
        else:
            artifact.job_id = enqueued.job.id
            artifact.status = "pending"
            artifact.attempt_count = attempt
            artifact.source_hash = None
            artifact.pipeline_revision = None
            artifact.parser_revision = None
            artifact.warnings = []
            artifact.error_code = None
            artifact.completed_at = None
            artifact.updated_at = datetime.now(UTC)
        self._db.flush()
        refreshed = self._load(document_id)
        if refreshed is None:
            raise RuntimeError("document_reflow_insert_failed")
        return self._response(refreshed), enqueued.created
