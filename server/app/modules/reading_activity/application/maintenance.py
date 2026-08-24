"""Administrator-only retention maintenance for fine-grained reading detail."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from app.modules.identity.domain import AccountAccessFacts, require_administrator
from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.modules.reading_activity.domain import SESSION_PAGE_DETAIL_RETENTION_DAYS
from app.shared.application import Actor, Clock, OperationContext


READING_SESSION_PAGES_PURGED = OperationAction("reading_activity.session_pages_purged")
SCHEDULED_RETENTION_HEADROOM = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class ReadingActivityRetentionResult:
    cutoff: datetime
    candidates: int
    purged_sessions: int
    purged_pages: int


class ReadingActivityRetentionGateway(Protocol):
    def purge_session_pages(
        self,
        *,
        cutoff: datetime,
        batch_size: int,
        apply: bool,
    ) -> ReadingActivityRetentionResult: ...


class ReadingActivityRetention:
    def __init__(
        self,
        gateway: ReadingActivityRetentionGateway,
        *,
        journal: OperationJournal,
        clock: Clock,
    ) -> None:
        self._gateway = gateway
        self._journal = journal
        self._clock = clock

    def purge_session_pages(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        retention_days: int = SESSION_PAGE_DETAIL_RETENTION_DAYS,
        batch_size: int,
        apply: bool,
    ) -> ReadingActivityRetentionResult:
        require_administrator(
            AccountAccessFacts(
                status=actor.status,
                is_blocked=actor.is_blocked,
                is_admin=actor.is_admin,
            )
        )
        if not 1 <= retention_days <= SESSION_PAGE_DETAIL_RETENTION_DAYS:
            raise ValueError(
                "retention_days must preserve the 90-day maximum detail window"
            )
        return self._purge_session_pages(
            actor=actor,
            operation=operation,
            retention_days=retention_days,
            batch_size=batch_size,
            apply=apply,
        )

    def purge_scheduled_session_pages(
        self,
        *,
        operation: OperationContext,
        batch_size: int,
    ) -> ReadingActivityRetentionResult:
        """Apply one bounded system-scheduled batch for the hourly drain."""

        return self._purge_session_pages(
            actor=None,
            operation=operation,
            retention_days=SESSION_PAGE_DETAIL_RETENTION_DAYS,
            batch_size=batch_size,
            apply=True,
            cutoff_headroom=SCHEDULED_RETENTION_HEADROOM,
        )

    def _purge_session_pages(
        self,
        *,
        actor: Actor | None,
        operation: OperationContext,
        retention_days: int,
        batch_size: int,
        apply: bool,
        cutoff_headroom: timedelta = timedelta(0),
    ) -> ReadingActivityRetentionResult:
        result = self._gateway.purge_session_pages(
            cutoff=(
                self._clock.now() - timedelta(days=retention_days) + cutoff_headroom
            ),
            batch_size=batch_size,
            apply=apply,
        )
        if apply and result.purged_sessions:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=READING_SESSION_PAGES_PURGED,
                resources=(ResourceRef("reading_activity", "session_pages"),),
            )
        return result


__all__ = [
    "ReadingActivityRetention",
    "ReadingActivityRetentionGateway",
    "ReadingActivityRetentionResult",
]
