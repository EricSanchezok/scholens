"""Administrator-only paper index maintenance."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.modules.identity.domain import AccountAccessFacts, require_administrator
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.shared.application import Actor, OperationContext

PASSAGES_BACKFILLED = OperationAction("papers.passages_backfilled")


@dataclass(frozen=True, slots=True)
class PassageBackfillResult:
    candidates: int
    indexed_documents: int
    indexed_passages: int


class PassageBackfillGateway(Protocol):
    def backfill(self, *, batch_size: int, apply: bool) -> PassageBackfillResult: ...


class PassageMaintenance:
    def __init__(
        self,
        gateway: PassageBackfillGateway,
        *,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._journal = journal

    def backfill_passages(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        batch_size: int,
        apply: bool,
    ) -> PassageBackfillResult:
        require_administrator(
            AccountAccessFacts(
                status=actor.status,
                is_blocked=actor.is_blocked,
                is_admin=actor.is_admin,
            )
        )
        result = self._gateway.backfill(batch_size=batch_size, apply=apply)
        if apply and result.indexed_documents:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=PASSAGES_BACKFILLED,
                resources=(ResourceRef("paper_search_index", "document_passages"),),
            )
        return result


__all__ = ["PassageBackfillResult", "PassageMaintenance"]
