"""Administrator-only, one-document-at-a-time token index repair."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from scholens_ai import TokenProjection

from app.modules.identity.domain import AccountAccessFacts, require_administrator
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.shared.application import Actor, OperationContext


@dataclass(frozen=True, slots=True)
class TokenIndexRepairPage:
    scanned: int
    document_ids: tuple[UUID, ...]
    skipped_limits: int
    next_cursor: UUID | None


@dataclass(frozen=True, slots=True)
class TokenIndexSource:
    document_id: UUID
    raw_content: str


class TokenIndexRepairGateway(Protocol):
    def candidates(
        self, *, batch_size: int, after_document_id: UUID | None
    ) -> TokenIndexRepairPage: ...
    def source(self, *, document_id: UUID) -> TokenIndexSource | None: ...
    def apply_projection(
        self, *, document_id: UUID, projection: TokenProjection
    ) -> bool: ...


class TokenIndexMaintenance:
    def __init__(
        self, gateway: TokenIndexRepairGateway, *, journal: OperationJournal
    ) -> None:
        self._gateway, self._journal = gateway, journal

    @staticmethod
    def _authorize(actor: Actor) -> None:
        require_administrator(
            AccountAccessFacts(
                status=actor.status,
                is_blocked=actor.is_blocked,
                is_admin=actor.is_admin,
            )
        )

    def candidates(
        self, *, actor: Actor, batch_size: int, after_document_id: UUID | None
    ) -> TokenIndexRepairPage:
        self._authorize(actor)
        return self._gateway.candidates(
            batch_size=batch_size, after_document_id=after_document_id
        )

    def source(self, *, actor: Actor, document_id: UUID) -> TokenIndexSource | None:
        self._authorize(actor)
        return self._gateway.source(document_id=document_id)

    def apply_projection(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
        projection: TokenProjection,
    ) -> bool:
        self._authorize(actor)
        applied = self._gateway.apply_projection(
            document_id=document_id, projection=projection
        )
        if applied:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=OperationAction("papers.token_index_backfilled"),
                resources=(ResourceRef("paper", str(document_id)),),
            )
        return applied
