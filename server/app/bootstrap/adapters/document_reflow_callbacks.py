"""Transactional completion adapter for document reflow jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.modules.jobs.application.callbacks import (
    JobHandlerResult,
    RecordJobTelemetry,
    SettleJobUsage,
)
from app.modules.jobs.application.contracts import DocumentReflowWebhookData
from app.modules.jobs.infrastructure.repository import job_repository
from app.modules.jobs.infrastructure.models import DurableJob
from app.modules.operation_journal.domain import OperationChange, ResourceRef
from app.modules.papers.infrastructure.models import Document
from app.modules.reflows.infrastructure.models import (
    DocumentReflow,
    DocumentReflowAsset,
    DocumentReflowBlock,
)
from app.bootstrap.adapters.storage_cleanup import schedule_storage_deletion
from app.modules.reflows.application.reflows import (
    DOCUMENT_REFLOW_COMPLETED,
    DOCUMENT_REFLOW_FAILED,
)
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import JobOperation, JobStatus
from sqlalchemy.orm import Session


def _require_scope(
    db: Session,
    *,
    actor: Actor,
    job_id: UUID,
) -> tuple[DurableJob, DocumentReflow, Document]:
    job = job_repository.require(db, job_id=job_id)
    if (
        job.operation != JobOperation.DOCUMENT_REFLOW.value
        or job.requested_by_id != actor.id
        or job.document_id is None
    ):
        raise AppError(
            code="job_callback_mismatch",
            message="Document reflow callback does not match its job",
            kind=FailureKind.CONFLICT,
        )
    artifact = db.get(DocumentReflow, job.document_id)
    document = db.get(Document, job.document_id)
    if artifact is None or document is None or artifact.job_id != job_id:
        raise AppError(
            code="job_scope_missing",
            message="Document reflow scope is no longer available",
            kind=FailureKind.CONFLICT,
        )
    return job, artifact, document


def complete_document_reflow(
    db: Session,
    *,
    actor: Actor,
    job_id: UUID,
    callback: DocumentReflowWebhookData,
) -> JobHandlerResult:
    job, artifact, document = _require_scope(db, actor=actor, job_id=job_id)
    if callback.task_id != job_id:
        raise AppError(
            code="job_callback_mismatch",
            message="Document reflow callback ID does not match",
            kind=FailureKind.CONFLICT,
        )
    if job.status in {
        JobStatus.COMPLETED.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
    }:
        return JobHandlerResult(value={"accepted": False})

    usage = tuple(callback.usage_events)
    if callback.status == "failed":
        error_code = callback.error or "document_reflow_failed"
        _, changed = job_repository.fail(
            db,
            job_id=job_id,
            error_code=error_code,
        )
        if changed:
            artifact.status = "failed"
            artifact.error_code = error_code
            artifact.completed_at = datetime.now(UTC)
        return JobHandlerResult(
            value={"accepted": changed},
            changes=(
                OperationChange(
                    action=DOCUMENT_REFLOW_FAILED,
                    resources=(ResourceRef("document", str(document.id)),),
                ),
            )
            if changed
            else (),
            post_commit=(SettleJobUsage(user_id=actor.id, events=usage),)
            if usage
            else (),
        )

    result = callback.result
    if result is None:
        raise RuntimeError("validated_reflow_callback_without_result")
    indexes = [block.index for block in result.blocks]
    block_ids = [block.id for block in result.blocks]
    asset_ids = [asset.id for asset in result.assets]
    asset_id_set = set(asset_ids)
    if (
        result.document_id != document.id
        or result.source_hash != document.sha256
        or indexes != list(range(len(result.blocks)))
        or len(set(block_ids)) != len(block_ids)
        or len(asset_id_set) != len(asset_ids)
        or any(
            block.asset_id is not None and block.asset_id not in asset_id_set
            for block in result.blocks
        )
    ):
        raise AppError(
            code="document_reflow_result_invalid",
            message="Document reflow result failed source validation",
            kind=FailureKind.UNPROCESSABLE,
        )

    old_asset_keys = {asset.object_key for asset in artifact.assets}
    new_asset_keys = {asset.object_key for asset in result.assets}
    artifact.blocks.clear()
    artifact.assets.clear()
    artifact.assets.extend(
        DocumentReflowAsset(
            id=asset.id,
            document_id=document.id,
            object_key=asset.object_key,
            kind=asset.kind,
            content_type=asset.content_type,
            width=asset.width,
            height=asset.height,
            page_number=asset.page_number,
            source_rect=asset.source_rect.model_dump(mode="json"),
            checksum=asset.checksum,
        )
        for asset in result.assets
    )
    db.flush()
    artifact.blocks.extend(
        DocumentReflowBlock(
            id=block.id,
            document_id=document.id,
            block_index=block.index,
            kind=block.kind,
            render_markdown=block.render_markdown,
            group_id=block.group_id,
            heading_level=block.heading_level,
            source_spans=[span.model_dump(mode="json") for span in block.source_spans],
            presentation_status=block.presentation_status,
            asset_id=block.asset_id,
        )
        for block in result.blocks
    )
    schedule_storage_deletion(
        db,
        object_keys=old_asset_keys - new_asset_keys,
        idempotency_key=f"document-reflow:{document.id}:{artifact.attempt_count}",
        origin_operation_id=job.origin_operation_id,
        correlation_id=job.correlation_id,
    )
    artifact.status = "completed"
    artifact.source_hash = result.source_hash
    artifact.pipeline_revision = result.pipeline_revision
    artifact.parser_revision = result.parser_revision
    artifact.warnings = result.warnings
    artifact.error_code = None
    artifact.completed_at = datetime.now(UTC)
    _, changed = job_repository.complete(
        db,
        job_id=job_id,
        result={
            "document_id": str(document.id),
            "block_count": len(result.blocks),
            "warning_count": len(result.warnings),
        },
    )
    return JobHandlerResult(
        value={"accepted": changed},
        changes=(
            OperationChange(
                action=DOCUMENT_REFLOW_COMPLETED,
                resources=(ResourceRef("document", str(document.id)),),
            ),
        )
        if changed
        else (),
        post_commit=(
            *((SettleJobUsage(user_id=actor.id, events=usage),) if usage else ()),
            RecordJobTelemetry(
                actor_id=actor.id,
                event="document_reflow_completed",
                properties=(
                    ("block_count", len(result.blocks)),
                    ("warning_count", len(result.warnings)),
                ),
            ),
        ),
    )
