"""Authorized application facade for document reflow artifacts."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.modules.papers.application.details import GetPaperDetails
from app.modules.reflows.application.contracts import (
    AuthorizedDocumentReflowBlock,
    DocumentReflowBlockResponse,
    DocumentReflowResponse,
)
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind

DOCUMENT_REFLOW_REQUESTED = OperationAction("document.reflow_requested")
DOCUMENT_REFLOW_COMPLETED = OperationAction("document.reflow_completed")
DOCUMENT_REFLOW_FAILED = OperationAction("document.reflow_failed")


class DocumentReflowGateway(Protocol):
    def get(self, *, document_id: UUID) -> DocumentReflowResponse | None: ...

    def get_block(
        self, *, document_id: UUID, block_id: str
    ) -> DocumentReflowBlockResponse | None: ...

    def ensure(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        retry_failed: bool,
    ) -> tuple[DocumentReflowResponse, bool]: ...


class ReflowEntitlements(Protocol):
    def has_token_credits(self, *, actor: Actor) -> bool: ...


class DocumentReflows:
    def __init__(
        self,
        *,
        access: GetPaperDetails,
        gateway: DocumentReflowGateway,
        entitlements: ReflowEntitlements,
        journal: OperationJournal,
    ) -> None:
        self._access = access
        self._gateway = gateway
        self._entitlements = entitlements
        self._journal = journal

    def get(self, *, actor: Actor, document_id: UUID) -> DocumentReflowResponse:
        self._access(actor=actor, document_id=document_id)
        result = self._gateway.get(document_id=document_id)
        if result is not None:
            return result
        raise AppError(
            code="document_reflow_not_scheduled",
            message="Document reflow has not been scheduled",
            kind=FailureKind.CONFLICT,
            retryable=True,
        )

    def translation_source(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        block_id: str,
    ) -> AuthorizedDocumentReflowBlock:
        paper = self._access(actor=actor, document_id=document_id)
        block = self._gateway.get_block(
            document_id=document_id,
            block_id=block_id,
        )
        if block is None:
            raise AppError(
                code="document_reflow_block_not_found",
                message="Document reflow block was not found",
                kind=FailureKind.NOT_FOUND,
            )
        return AuthorizedDocumentReflowBlock(
            paper_title=paper.title,
            block=block,
        )

    def retry(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
    ) -> DocumentReflowResponse:
        self._access(actor=actor, document_id=document_id)
        if not self._entitlements.has_token_credits(actor=actor):
            raise AppError(
                code="token_quota_exceeded",
                message="Token Credits are exhausted",
                kind=FailureKind.RATE_LIMITED,
            )
        result, created = self._gateway.ensure(
            actor=actor,
            operation=operation,
            document_id=document_id,
            retry_failed=True,
        )
        if created:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=DOCUMENT_REFLOW_REQUESTED,
                resources=(ResourceRef("document", str(document_id)),),
            )
        return result
