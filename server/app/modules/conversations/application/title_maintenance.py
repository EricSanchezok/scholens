"""Administrator-only repair for legacy default conversation titles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.modules.identity.domain import AccountAccessFacts, require_administrator
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.shared.application import Actor, OperationContext

CONVERSATION_TITLES_BACKFILLED = OperationAction(
    "conversations.default_titles_backfilled"
)


@dataclass(frozen=True, slots=True)
class ConversationTitleBackfillResult:
    candidates: int
    updated_conversations: int


class ConversationTitleBackfillGateway(Protocol):
    def backfill(
        self,
        *,
        batch_size: int,
        apply: bool,
    ) -> ConversationTitleBackfillResult: ...


class ConversationTitleMaintenance:
    def __init__(
        self,
        gateway: ConversationTitleBackfillGateway,
        *,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._journal = journal

    def backfill_default_titles(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        batch_size: int,
        apply: bool,
    ) -> ConversationTitleBackfillResult:
        require_administrator(
            AccountAccessFacts(
                status=actor.status,
                is_blocked=actor.is_blocked,
                is_admin=actor.is_admin,
            )
        )
        result = self._gateway.backfill(batch_size=batch_size, apply=apply)
        if apply and result.updated_conversations:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=CONVERSATION_TITLES_BACKFILLED,
                resources=(ResourceRef("conversation_history", "default_titles"),),
            )
        return result
