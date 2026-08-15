"""Authorized application facade for document reflow artifacts."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.modules.papers.application.details import GetPaperDetails
from app.modules.reflows.application.contracts import (
    AuthorizedDocumentReflowBlock,
    DocumentReflowAssetUrlResponse,
    DocumentReflowBlockResponse,
    DocumentReflowResponse,
)
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind

DOCUMENT_REFLOW_REQUESTED = OperationAction("document.reflow_requested")
DOCUMENT_REFLOW_COMPLETED = OperationAction("document.reflow_completed")
DOCUMENT_REFLOW_FAILED = OperationAction("document.reflow_failed")


class DocumentReflowGateway(Protocol):
    def get(self, *, document_id: UUID) -> DocumentReflowResponse: ...

    def get_block(
        self, *, document_id: UUID, block_id: str
    ) -> DocumentReflowBlockResponse | None: ...

    def get_asset_url(
        self, *, document_id: UUID, asset_id: str
    ) -> DocumentReflowAssetUrlResponse | None: ...

    def ensure(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        idempotency_key: str | None,
    ) -> tuple[DocumentReflowResponse, bool]: ...


class ReflowIntegrationAccess(Protocol):
    def __call__(self, actor: Actor) -> None: ...


class DocumentReflows:
    def __init__(
        self,
        *,
        access: GetPaperDetails,
        gateway: DocumentReflowGateway,
        require_mineru: ReflowIntegrationAccess,
        journal: OperationJournal,
    ) -> None:
        self._access = access
        self._gateway = gateway
        self._require_mineru = require_mineru
        self._journal = journal

    def get(self, *, actor: Actor, document_id: UUID) -> DocumentReflowResponse:
        self._access(actor=actor, document_id=document_id)
        return self._gateway.get(document_id=document_id)

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

    def asset_url(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        asset_id: str,
    ) -> DocumentReflowAssetUrlResponse:
        self._access(actor=actor, document_id=document_id)
        result = self._gateway.get_asset_url(document_id=document_id, asset_id=asset_id)
        if result is None:
            raise AppError(
                code="document_reflow_asset_not_found",
                message="Document reflow asset was not found",
                kind=FailureKind.NOT_FOUND,
            )
        return result

    def request_attempt(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        idempotency_key: str | None,
    ) -> DocumentReflowResponse:
        self._access(actor=actor, document_id=document_id)
        current = self._gateway.get(document_id=document_id)
        if current.status in {"pending", "processing", "completed"}:
            return current
        self._require_mineru(actor)
        result, created = self._gateway.ensure(
            actor=actor,
            operation=operation,
            document_id=document_id,
            idempotency_key=idempotency_key,
        )
        if created:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=DOCUMENT_REFLOW_REQUESTED,
                resources=(ResourceRef("document", str(document_id)),),
            )
        return result
