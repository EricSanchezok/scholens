"""Preference updates and cumulative reading-session ingestion."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select, update

from app.modules.papers.infrastructure.access import (
    get_document_access,
    require_document_access,
)
from app.modules.reading_activity.application.activity import ReadingMutationResult
from app.modules.reading_activity.application.contracts import (
    ReadingActivityExportResponse,
    ReadingActivityPreferencesResponse,
    ReadingActivityPreferencesUpdateRequest,
    ReadingExportFormat,
    ReadingSessionResponse,
    ReadingSessionSnapshotRequest,
    ReadingSessionStartRequest,
)
from app.modules.reading_activity.domain import (
    ACTIVE_READING_DEFINITION_VERSION,
    MAX_READING_SESSION_DURATION_MS,
    SESSION_START_BACKLOG_HOURS,
    SNAPSHOT_FUTURE_CLOCK_SKEW_SECONDS,
    SNAPSHOT_VISIBLE_ELAPSED_TOLERANCE_MS,
)
from app.modules.reading_activity.infrastructure.ledger_management import (
    ReadingLedgerManager,
)
from app.modules.reading_activity.infrastructure.ledger_export import (
    ReadingLedgerExporter,
)
from app.modules.reading_activity.infrastructure.locking import lock_user_activity
from app.modules.reading_activity.infrastructure.models import (
    ReadingActivityPreference,
    ReadingSession,
    ReadingSessionHour,
    ReadingSessionPage,
)
from app.modules.reading_activity.infrastructure.rollup_mutations import (
    ReadingRollupWriter,
)
from app.modules.reading_activity.infrastructure.shared import (
    ReadingActivityRepositoryBase,
    _preferences_response,
    _same_session_start,
    _session_response,
    _snapshot_digest,
)
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind


class ReadingActivityMutationRepository(ReadingActivityRepositoryBase):
    """Persist preferences and authoritative user-owned session snapshots."""

    def get_preferences(self, *, user_id: int) -> ReadingActivityPreferencesResponse:
        model = self._db.get(ReadingActivityPreference, user_id)
        return _preferences_response(model)

    def update_preferences(
        self,
        *,
        user_id: int,
        request: ReadingActivityPreferencesUpdateRequest,
    ) -> ReadingMutationResult[ReadingActivityPreferencesResponse]:
        lock_user_activity(self._db, user_id=user_id)
        current = self._db.get(ReadingActivityPreference, user_id)
        changed = current is None or (
            current.recording_enabled != request.recording_enabled
            or current.contribute_anonymous_project_aggregates
            != request.contribute_anonymous_project_aggregates
        )
        if not changed:
            assert current is not None
            return ReadingMutationResult(_preferences_response(current), False)

        recording_was_enabled = (
            current.recording_enabled if current is not None else True
        )
        contribution_was_enabled = (
            current.contribute_anonymous_project_aggregates
            if current is not None
            else True
        )
        disables_recording = recording_was_enabled and not request.recording_enabled
        contribution_changed = (
            contribution_was_enabled != request.contribute_anonymous_project_aggregates
        )
        if disables_recording or contribution_changed:
            self._close_open_sessions(
                user_id=user_id,
                project_only=not disables_recording,
            )

        if current is None:
            model = ReadingActivityPreference(
                user_id=user_id,
                recording_enabled=request.recording_enabled,
                contribute_anonymous_project_aggregates=(
                    request.contribute_anonymous_project_aggregates
                ),
            )
            self._db.add(model)
        else:
            current.recording_enabled = request.recording_enabled
            current.contribute_anonymous_project_aggregates = (
                request.contribute_anonymous_project_aggregates
            )
            model = current
        self._db.flush()
        return ReadingMutationResult(_preferences_response(model), True)

    def start_session(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        request: ReadingSessionStartRequest,
    ) -> ReadingMutationResult[ReadingSessionResponse]:
        lock_user_activity(self._db, user_id=actor.id)
        replay = self._replay_session_start(
            actor=actor,
            document_id=document_id,
            request=request,
        )
        if replay is not None:
            return replay

        preferences = self.get_preferences(user_id=actor.id)
        if not preferences.recording_enabled:
            raise AppError(
                code="reading_activity_disabled",
                message="Reading activity recording is disabled",
                kind=FailureKind.CONFLICT,
            )
        if request.metric_definition_version != ACTIVE_READING_DEFINITION_VERSION:
            raise AppError(
                code="reading_activity_definition_unsupported",
                message="The reading activity definition is not supported",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        require_document_access(
            self._db,
            document_id=document_id,
            user_id=actor.id,
            project_id=request.project_id,
        )
        now = self._clock.now()
        if request.started_at > now + timedelta(minutes=5):
            raise AppError(
                code="reading_session_time_invalid",
                message="The reading session cannot start in the future",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        if request.started_at < now - timedelta(hours=SESSION_START_BACKLOG_HOURS):
            raise AppError(
                code="reading_session_time_invalid",
                message="The reading session is outside the offline recovery window",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        model = ReadingSession(
            id=request.session_id,
            user_id=actor.id,
            document_id=document_id,
            project_id=request.project_id,
            view_mode=request.view_mode.value,
            time_zone=request.time_zone,
            metric_definition_version=request.metric_definition_version,
            revision=0,
            visible_ms=0,
            active_ms=0,
            started_at=request.started_at,
            last_seen_at=request.started_at,
            ended_at=None,
            last_snapshot_digest=None,
            contribute_to_project_aggregates=(
                request.project_id is not None
                and preferences.contribute_anonymous_project_aggregates
            ),
            page_detail_purged_at=None,
        )
        self._db.add(model)
        self._db.flush()
        return ReadingMutationResult(_session_response(model), True)

    def update_session(
        self,
        *,
        actor: Actor,
        session_id: UUID,
        request: ReadingSessionSnapshotRequest,
    ) -> ReadingMutationResult[ReadingSessionResponse]:
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
            raise AppError(
                code="reading_session_not_found",
                message="Reading session not found",
                kind=FailureKind.NOT_FOUND,
            )
        digest = _snapshot_digest(request)
        if request.revision < model.revision:
            return ReadingMutationResult(_session_response(model), False)
        if request.revision == model.revision:
            if model.last_snapshot_digest == digest:
                return ReadingMutationResult(_session_response(model), False)
            raise AppError(
                code="reading_session_revision_conflict",
                message="This reading session revision has different content",
                kind=FailureKind.CONFLICT,
            )
        if request.revision != model.revision + 1:
            raise AppError(
                code="reading_session_revision_gap",
                message="Reading session revisions must be contiguous",
                kind=FailureKind.CONFLICT,
            )
        if model.ended_at is not None:
            raise AppError(
                code="reading_session_ended",
                message="This reading session has already ended",
                kind=FailureKind.CONFLICT,
            )
        if (
            request.visible_ms < model.visible_ms
            or request.active_ms < model.active_ms
            or request.last_seen_at < model.last_seen_at
            or request.last_seen_at < model.started_at
        ):
            raise AppError(
                code="reading_session_snapshot_regressed",
                message="Reading session cumulative values cannot decrease",
                kind=FailureKind.CONFLICT,
            )

        _snapshot_deltas(
            model=model,
            request=request,
            now=self._clock.now(),
        )
        access = get_document_access(
            self._db,
            document_id=model.document_id,
            user_id=actor.id,
            project_id=model.project_id,
        )
        if access is None:
            raise AppError(
                code="paper_not_found",
                message="Paper not found",
                kind=FailureKind.NOT_FOUND,
            )
        document = access.document
        if document.page_count is not None and any(
            page.page_number > document.page_count for page in request.pages
        ):
            raise AppError(
                code="reading_session_page_invalid",
                message="A reading page exceeds the paper page count",
                kind=FailureKind.INVALID_ARGUMENT,
            )

        rollups = ReadingRollupWriter(self._db)
        rollups.apply_snapshots(
            model=model,
            hours=request.hours,
            pages=request.pages,
            materialize_session_count=model.revision == 0,
        )
        self._db.flush()
        page_visible, page_active = self._db.execute(
            select(
                func.coalesce(func.sum(ReadingSessionPage.visible_ms), 0),
                func.coalesce(func.sum(ReadingSessionPage.active_ms), 0),
            ).where(ReadingSessionPage.session_id == model.id)
        ).one()
        _validate_page_totals(
            page_visible_ms=int(page_visible),
            page_active_ms=int(page_active),
            request=request,
        )
        hour_visible, hour_active = self._db.execute(
            select(
                func.coalesce(func.sum(ReadingSessionHour.visible_ms), 0),
                func.coalesce(func.sum(ReadingSessionHour.active_ms), 0),
            ).where(ReadingSessionHour.session_id == model.id)
        ).one()
        _validate_hour_totals(
            hour_visible_ms=int(hour_visible),
            hour_active_ms=int(hour_active),
            request=request,
        )

        model.revision = request.revision
        model.visible_ms = request.visible_ms
        model.active_ms = request.active_ms
        model.last_seen_at = request.last_seen_at
        model.ended_at = request.ended_at
        model.last_snapshot_digest = digest
        self._db.flush()
        return ReadingMutationResult(_session_response(model), True)

    def export(
        self,
        *,
        actor: Actor,
        export_format: ReadingExportFormat,
        cursor: str | None,
        limit: int,
    ) -> ReadingActivityExportResponse:
        if self._export_cursors is None:
            raise RuntimeError("reading_activity_export_cursors_not_configured")
        return ReadingLedgerExporter(
            self._db,
            clock=self._clock,
            cursors=self._export_cursors,
        ).export(
            actor=actor,
            export_format=export_format,
            cursor=cursor,
            limit=limit,
        )

    def delete_session(self, *, actor: Actor, session_id: UUID) -> int:
        return self._ledger().delete_session(actor=actor, session_id=session_id)

    def delete_all(self, *, actor: Actor) -> int:
        return self._ledger().delete_all(actor=actor)

    def delete_paper(self, *, actor: Actor, document_id: UUID) -> int:
        return self._ledger().delete_paper(actor=actor, document_id=document_id)

    def delete_project_contribution(self, *, actor: Actor, project_id: UUID) -> int:
        return self._ledger().delete_project_contribution(
            actor=actor,
            project_id=project_id,
        )

    def _replay_session_start(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        request: ReadingSessionStartRequest,
    ) -> ReadingMutationResult[ReadingSessionResponse] | None:
        existing = self._db.get(ReadingSession, request.session_id)
        if existing is None:
            return None
        if not _same_session_start(existing, actor.id, document_id, request):
            raise AppError(
                code="reading_session_conflict",
                message="The reading session identifier is already in use",
                kind=FailureKind.CONFLICT,
            )
        return ReadingMutationResult(_session_response(existing), False)

    def _close_open_sessions(self, *, user_id: int, project_only: bool) -> None:
        filters = [
            ReadingSession.user_id == user_id,
            ReadingSession.ended_at.is_(None),
        ]
        if project_only:
            filters.append(ReadingSession.project_id.is_not(None))
        # The user-scoped transaction lock is shared by session creation and
        # ingestion, so one bounded statement is the linearization boundary.
        # Existing accepted contribution remains frozen; any buffered
        # post-toggle delta is dropped conservatively.
        self._db.execute(
            update(ReadingSession)
            .where(*filters)
            .values(ended_at=ReadingSession.last_seen_at)
        )

    def _ledger(self) -> ReadingLedgerManager:
        return ReadingLedgerManager(self._db, clock=self._clock)


def _snapshot_deltas(
    *,
    model: ReadingSession,
    request: ReadingSessionSnapshotRequest,
    now: datetime,
) -> tuple[int, int]:
    future_limit = now + timedelta(seconds=SNAPSHOT_FUTURE_CLOCK_SKEW_SECONDS)
    if request.last_seen_at < now - timedelta(hours=SESSION_START_BACKLOG_HOURS):
        raise AppError(
            code="reading_session_time_invalid",
            message="The reading session snapshot is outside the recovery window",
            kind=FailureKind.INVALID_ARGUMENT,
        )
    if request.last_seen_at > future_limit:
        raise AppError(
            code="reading_session_time_invalid",
            message="The reading session snapshot cannot be in the future",
            kind=FailureKind.INVALID_ARGUMENT,
        )
    if request.ended_at is not None and request.ended_at > future_limit:
        raise AppError(
            code="reading_session_time_invalid",
            message="The reading session cannot end in the future",
            kind=FailureKind.INVALID_ARGUMENT,
        )
    elapsed_ms = int(
        (request.last_seen_at - model.last_seen_at).total_seconds() * 1_000
    )
    session_wall_ms = int(
        (request.last_seen_at - model.started_at).total_seconds() * 1_000
    )
    if session_wall_ms > (
        MAX_READING_SESSION_DURATION_MS + SNAPSHOT_FUTURE_CLOCK_SKEW_SECONDS * 1_000
    ):
        raise AppError(
            code="reading_session_duration_invalid",
            message="Reading session exceeds the maximum wall-clock span",
            kind=FailureKind.INVALID_ARGUMENT,
        )
    visible_delta = request.visible_ms - model.visible_ms
    active_delta = request.active_ms - model.active_ms
    if (
        visible_delta > elapsed_ms + SNAPSHOT_VISIBLE_ELAPSED_TOLERANCE_MS
        or request.visible_ms > session_wall_ms + SNAPSHOT_VISIBLE_ELAPSED_TOLERANCE_MS
        or active_delta > visible_delta
    ):
        raise AppError(
            code="reading_session_duration_invalid",
            message="Reading duration exceeds elapsed wall-clock time",
            kind=FailureKind.INVALID_ARGUMENT,
        )
    bucket_overage_ms = 0
    session_start = model.started_at
    session_end = request.last_seen_at
    for hour in request.hours:
        bucket_end = hour.bucket_start + timedelta(hours=1)
        overlap_start = max(session_start, hour.bucket_start)
        overlap_end = min(session_end, bucket_end)
        capacity_ms = max(
            0,
            int((overlap_end - overlap_start).total_seconds() * 1_000),
        )
        bucket_overage_ms += max(0, hour.visible_ms - capacity_ms)
    if bucket_overage_ms > SNAPSHOT_VISIBLE_ELAPSED_TOLERANCE_MS:
        raise AppError(
            code="reading_session_hour_duration_invalid",
            message="Reading hour duration exceeds its wall-clock bucket",
            kind=FailureKind.INVALID_ARGUMENT,
        )
    return visible_delta, active_delta


def _validate_page_totals(
    *,
    page_visible_ms: int,
    page_active_ms: int,
    request: ReadingSessionSnapshotRequest,
) -> None:
    if page_visible_ms > request.visible_ms or page_active_ms > request.active_ms:
        raise AppError(
            code="reading_session_page_totals_invalid",
            message="Persisted page durations exceed session durations",
            kind=FailureKind.CONFLICT,
        )


def _validate_hour_totals(
    *,
    hour_visible_ms: int,
    hour_active_ms: int,
    request: ReadingSessionSnapshotRequest,
) -> None:
    if hour_visible_ms != request.visible_ms or hour_active_ms != request.active_ms:
        raise AppError(
            code="reading_session_hour_totals_invalid",
            message="Persisted hour durations must equal session durations",
            kind=FailureKind.CONFLICT,
        )


__all__ = [
    "ReadingActivityMutationRepository",
    "_snapshot_deltas",
    "_validate_hour_totals",
    "_validate_page_totals",
]
