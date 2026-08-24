"""Bounded PostgreSQL retention adapter for session page trajectories."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.modules.reading_activity.application.maintenance import (
    ReadingActivityRetentionResult,
)
from app.modules.reading_activity.infrastructure.models import (
    ReadingSession,
    ReadingSessionPage,
)

MAX_RETENTION_SESSION_BATCH_SIZE = 100
RETENTION_PAGE_ROW_BUDGET = 50_000


class SqlReadingActivityRetention:
    def __init__(self, db: Session) -> None:
        self._db = db

    def purge_session_pages(
        self,
        *,
        cutoff: datetime,
        batch_size: int,
        apply: bool,
    ) -> ReadingActivityRetentionResult:
        candidate_filter = (
            ReadingSession.page_detail_purged_at.is_(None),
            ReadingSession.started_at < cutoff,
        )
        candidates = int(
            self._db.scalar(
                select(func.count(ReadingSession.id)).where(*candidate_filter)
            )
            or 0
        )
        if not apply or candidates == 0:
            return ReadingActivityRetentionResult(
                cutoff=cutoff,
                candidates=candidates,
                purged_sessions=0,
                purged_pages=0,
            )

        locked_session_ids = list(
            self._db.scalars(
                select(ReadingSession.id)
                .where(*candidate_filter)
                # Every path that locks more than one session uses this order.
                .order_by(ReadingSession.id)
                .limit(min(batch_size, MAX_RETENTION_SESSION_BATCH_SIZE))
                .with_for_update(skip_locked=True)
            ).all()
        )
        if not locked_session_ids:
            return ReadingActivityRetentionResult(
                cutoff=cutoff,
                candidates=candidates,
                purged_sessions=0,
                purged_pages=0,
            )
        page_counts = {
            session_id: int(page_count)
            for session_id, page_count in self._db.execute(
                select(
                    ReadingSessionPage.session_id,
                    func.count(ReadingSessionPage.page_number),
                )
                .where(ReadingSessionPage.session_id.in_(locked_session_ids))
                .group_by(ReadingSessionPage.session_id)
            ).all()
        }
        session_ids: list[UUID] = []
        purged_pages = 0
        for session_id in locked_session_ids:
            page_count = page_counts.get(session_id, 0)
            if session_ids and purged_pages + page_count > RETENTION_PAGE_ROW_BUDGET:
                break
            session_ids.append(session_id)
            purged_pages += page_count
        self._db.execute(
            delete(ReadingSessionPage).where(
                ReadingSessionPage.session_id.in_(session_ids)
            )
        )
        self._db.execute(
            update(ReadingSession)
            .where(ReadingSession.id.in_(session_ids))
            .values(
                page_detail_purged_at=func.now(),
                ended_at=func.coalesce(
                    ReadingSession.ended_at,
                    ReadingSession.last_seen_at,
                ),
                updated_at=func.now(),
            )
        )
        return ReadingActivityRetentionResult(
            cutoff=cutoff,
            candidates=candidates,
            purged_sessions=len(session_ids),
            purged_pages=purged_pages,
        )


__all__ = [
    "MAX_RETENTION_SESSION_BATCH_SIZE",
    "RETENTION_PAGE_ROW_BUDGET",
    "SqlReadingActivityRetention",
]
