"""Readable content and independently recoverable document stages."""

from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel

from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import ResourceRef
from app.modules.papers.application.actions import DOCUMENT_STAGE_RETRIED
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind

DocumentStage = Literal["index", "enrichment", "bibliography"]
StageStatus = Literal[
    "not_requested", "pending", "running", "completed", "failed", "cancelled", "stale"
]


class DocumentStageStatus(BaseModel):
    stage: DocumentStage
    status: StageStatus
    job_id: UUID | None = None
    can_retry: bool = False
    required_integration: Literal["deepseek"] | None = None


class DocumentProcessingStatusResponse(BaseModel):
    document_id: UUID
    readable: bool
    stages: list[DocumentStageStatus]


class RetryDocumentStage(BaseModel):
    stage: DocumentStage
    job_id: UUID
    acknowledge_provider_charge: bool = False


class DocumentProcessingGateway(Protocol):
    def get(
        self, *, actor: Actor, document_id: UUID
    ) -> DocumentProcessingStatusResponse: ...

    def retry(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        request: RetryDocumentStage,
    ) -> tuple[DocumentStageStatus, bool]: ...


class DocumentProcessing:
    def __init__(
        self,
        gateway: DocumentProcessingGateway,
        *,
        journal: OperationJournal,
        enabled: bool,
    ) -> None:
        self._gateway, self._journal, self._enabled = gateway, journal, enabled

    def get(
        self, *, actor: Actor, document_id: UUID
    ) -> DocumentProcessingStatusResponse:
        return self._gateway.get(actor=actor, document_id=document_id)

    def retry(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        request: RetryDocumentStage,
    ) -> DocumentStageStatus:
        if not self._enabled:
            raise AppError(
                code="document_stage_retry_unavailable",
                message="Stage retry is temporarily unavailable",
                kind=FailureKind.UNAVAILABLE,
            )
        if request.stage == "enrichment" and not request.acknowledge_provider_charge:
            raise AppError(
                code="provider_charge_confirmation_required",
                message="Confirm the provider charge before retrying AI information",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        result, created = self._gateway.retry(
            actor=actor, operation=operation, document_id=document_id, request=request
        )
        if created:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=DOCUMENT_STAGE_RETRIED,
                resources=(
                    ResourceRef("document", str(document_id)),
                    ResourceRef("job", str(result.job_id)),
                ),
            )
        return result
