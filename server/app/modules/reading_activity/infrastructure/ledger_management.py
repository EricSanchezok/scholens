"""Linearizable, actor-scoped erasure of retained reading activity."""

from __future__ import annotations

from uuid import UUID
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import CTE

from app.modules.reading_activity.infrastructure.locking import lock_user_activity
from app.modules.reading_activity.infrastructure.models import (
    ReadingPersonalHourRollup,
    ReadingPersonalPageRollup,
    ReadingProjectHourRollup,
    ReadingProjectPageRollup,
    ReadingProjectPersonalPageRollup,
    ReadingSession,
)
from app.modules.reading_activity.infrastructure.rollup_mutations import (
    ReadingRollupWriter,
)
from app.modules.reading_activity.domain import SESSION_PAGE_DETAIL_RETENTION_DAYS
from app.shared.application import Actor, Clock
from app.shared.domain import AppError, FailureKind


class ReadingLedgerManager:
    """Erase ledger scopes under the same user lock used by ingest."""

    def __init__(self, db: Session, *, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    def delete_session(self, *, actor: Actor, session_id: UUID) -> int:
        lock_user_activity(self._db, user_id=actor.id)
        model = self._db.scalar(
            select(ReadingSession)
            .where(
                ReadingSession.id == session_id,
                ReadingSession.user_id == actor.id,
            )
            .with_for_update()
        )
        if model is None:
            return 0
        if (
            model.page_detail_purged_at is not None
            or model.started_at
            < self._clock.now() - timedelta(days=SESSION_PAGE_DETAIL_RETENTION_DAYS)
        ):
            raise AppError(
                code="reading_session_detail_expired",
                message=(
                    "This session's page detail has expired; delete the paper, "
                    "project contribution, or all reading activity instead"
                ),
                kind=FailureKind.CONFLICT,
            )
        project_id = model.project_id
        ReadingRollupWriter(self._db).subtract_session(
            model=model,
            personal=True,
            personal_project_id=project_id,
            team_project_id=(
                project_id if model.contribute_to_project_aggregates else None
            ),
        )
        self._db.delete(model)
        self._db.flush()
        return 1

    def delete_all(self, *, actor: Actor) -> int:
        lock_user_activity(self._db, user_id=actor.id)
        filters = _session_filters(user_id=actor.id)
        count = self._session_count(filters=filters)
        locked_session_ids = _ordered_locked_session_ids(filters=filters)
        self._db.execute(
            delete(ReadingSession).where(
                ReadingSession.id.in_(select(locked_session_ids.c.id))
            )
        )
        self._delete_user_rollups(user_id=actor.id)
        return count

    def delete_paper(self, *, actor: Actor, document_id: UUID) -> int:
        lock_user_activity(self._db, user_id=actor.id)
        filters = _session_filters(
            user_id=actor.id,
            document_id=document_id,
        )
        count = self._session_count(filters=filters)
        locked_session_ids = _ordered_locked_session_ids(filters=filters)
        self._db.execute(
            delete(ReadingSession).where(
                ReadingSession.id.in_(select(locked_session_ids.c.id))
            )
        )
        for model in _ROLLUP_MODELS:
            self._db.execute(
                delete(model).where(
                    model.user_id == actor.id,
                    model.document_id == document_id,
                )
            )
        return count

    def delete_project_contribution(self, *, actor: Actor, project_id: UUID) -> int:
        lock_user_activity(self._db, user_id=actor.id)
        filters = _session_filters(
            user_id=actor.id,
            project_id=project_id,
        )
        count = self._session_count(filters=filters)
        locked_session_ids = _ordered_locked_session_ids(filters=filters)
        self._db.execute(
            update(ReadingSession)
            .where(ReadingSession.id.in_(select(locked_session_ids.c.id)))
            .values(
                ended_at=func.coalesce(
                    ReadingSession.ended_at,
                    ReadingSession.last_seen_at,
                ),
                project_id=None,
                contribute_to_project_aggregates=False,
            )
        )
        for model in _PROJECT_ROLLUP_MODELS:
            self._db.execute(
                delete(model).where(
                    model.user_id == actor.id,
                    model.project_id == project_id,
                )
            )
        return count

    def _session_count(
        self,
        *,
        filters: tuple[ColumnElement[bool], ...],
    ) -> int:
        return int(
            self._db.scalar(select(func.count(ReadingSession.id)).where(*filters)) or 0
        )

    def _delete_user_rollups(self, *, user_id: int) -> None:
        for model in _ROLLUP_MODELS:
            self._db.execute(delete(model).where(model.user_id == user_id))


def _session_filters(
    *,
    user_id: int,
    document_id: UUID | None = None,
    project_id: UUID | None = None,
) -> tuple[ColumnElement[bool], ...]:
    filters: list[ColumnElement[bool]] = [ReadingSession.user_id == user_id]
    if document_id is not None:
        filters.append(ReadingSession.document_id == document_id)
    if project_id is not None:
        filters.append(ReadingSession.project_id == project_id)
    return tuple(filters)


def _ordered_locked_session_ids(*, filters: tuple[ColumnElement[bool], ...]) -> CTE:
    """Lock a broad erasure scope in the same stable order as retention."""

    return (
        select(ReadingSession.id)
        .where(*filters)
        .order_by(ReadingSession.id)
        .with_for_update()
        .cte("locked_reading_sessions")
    )


_PROJECT_ROLLUP_MODELS = (
    ReadingProjectPageRollup,
    ReadingProjectPersonalPageRollup,
    ReadingProjectHourRollup,
)
_ROLLUP_MODELS = (
    ReadingPersonalPageRollup,
    ReadingPersonalHourRollup,
    *_PROJECT_ROLLUP_MODELS,
)


__all__ = ["ReadingLedgerManager"]
