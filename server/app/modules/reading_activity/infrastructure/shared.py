"""Shared SQL helpers and mappings for reading-activity repositories."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, time, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.reading_activity.application.contracts import (
    ReadingActivityPreferencesResponse,
    ReadingInsightsRange,
    ReadingPageInsightResponse,
    ReadingSessionResponse,
    ReadingSessionSnapshotRequest,
    ReadingSessionStartRequest,
    ReadingViewMode,
)
from app.modules.reading_activity.domain import (
    ACTIVE_READING_DEFINITION_VERSION,
)
from app.modules.reading_activity.infrastructure.models import (
    ReadingActivityPreference,
    ReadingMetricDefinition,
    ReadingPersonalHourRollup,
    ReadingPersonalPageRollup,
    ReadingSession,
)
from app.shared.application import Clock, SignedCursorCodec


class ReadingActivityRepositoryBase:
    def __init__(
        self,
        db: Session,
        *,
        clock: Clock,
        export_cursors: SignedCursorCodec | None = None,
        activity_cursors: SignedCursorCodec | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._export_cursors = export_cursors
        self._activity_cursors = activity_cursors

    def _reading_data_since(
        self,
        *,
        user_id: int,
        document_id: UUID | None = None,
        document_ids: set[UUID] | None = None,
        project_id: UUID | None = None,
    ) -> datetime | None:
        filters: list[Any] = [
            ReadingSession.user_id == user_id,
            ReadingSession.metric_definition_version
            == ACTIVE_READING_DEFINITION_VERSION,
            ReadingSession.started_at <= self._clock.now(),
        ]
        if document_id is not None:
            filters.append(ReadingSession.document_id == document_id)
        if document_ids is not None:
            filters.append(ReadingSession.document_id.in_(document_ids))
        if project_id is not None:
            filters.append(ReadingSession.project_id == project_id)
        return self._db.scalar(
            select(func.min(ReadingSession.started_at)).where(*filters)
        )

    def _count(self, statement: Any) -> int:
        return int(self._db.scalar(statement) or 0)

    def _activity_history_complete_since(self) -> datetime | None:
        definition = self._db.get(
            ReadingMetricDefinition,
            ACTIVE_READING_DEFINITION_VERSION,
        )
        return definition.collection_started_at if definition is not None else None


def _preferences_response(
    model: ReadingActivityPreference | None,
) -> ReadingActivityPreferencesResponse:
    if model is None:
        return ReadingActivityPreferencesResponse()
    return ReadingActivityPreferencesResponse(
        recording_enabled=model.recording_enabled,
        contribute_anonymous_project_aggregates=(
            model.contribute_anonymous_project_aggregates
        ),
    )


def _same_session_start(
    model: ReadingSession,
    user_id: int,
    document_id: UUID,
    request: ReadingSessionStartRequest,
) -> bool:
    return (
        model.user_id == user_id
        and model.document_id == document_id
        and model.project_id == request.project_id
        and model.view_mode == request.view_mode.value
        and model.time_zone == request.time_zone
        and model.metric_definition_version == request.metric_definition_version
        and model.started_at == request.started_at
    )


def _session_response(model: ReadingSession) -> ReadingSessionResponse:
    return ReadingSessionResponse(
        id=model.id,
        document_id=model.document_id,
        project_id=model.project_id,
        view_mode=ReadingViewMode(model.view_mode),
        time_zone=model.time_zone,
        metric_definition_version=model.metric_definition_version,
        revision=model.revision,
        visible_ms=model.visible_ms,
        active_ms=model.active_ms,
        started_at=model.started_at,
        last_seen_at=model.last_seen_at,
        ended_at=model.ended_at,
        project_contribution_enabled=(
            model.project_id is not None and model.contribute_to_project_aggregates
        ),
        page_detail_available=model.page_detail_purged_at is None,
    )


def _snapshot_digest(request: ReadingSessionSnapshotRequest) -> str:
    encoded = json.dumps(
        request.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _hour_bucket(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


def _calendar_range_start(
    insight_range: ReadingInsightsRange,
    now: datetime,
    *,
    time_zone: str,
) -> datetime | None:
    days = {
        ReadingInsightsRange.SEVEN_DAYS: 7,
        ReadingInsightsRange.THIRTY_DAYS: 30,
        ReadingInsightsRange.NINETY_DAYS: 90,
        ReadingInsightsRange.YEAR: 365,
    }.get(insight_range)
    if days is None:
        return None
    zone = ZoneInfo(time_zone)
    first_date = now.astimezone(zone).date() - timedelta(days=days - 1)
    return datetime.combine(first_date, time.min, tzinfo=zone).astimezone(timezone.utc)


def _range_start(
    insight_range: ReadingInsightsRange,
    now: datetime,
    *,
    time_zone: str,
) -> datetime | None:
    """First complete UTC hour within the selected local calendar-day range."""

    calendar_start = _calendar_range_start(
        insight_range,
        now,
        time_zone=time_zone,
    )
    if calendar_start is None:
        return None
    floor = _hour_bucket(calendar_start)
    return floor if floor == calendar_start else floor + timedelta(hours=1)


def _created_since(column: Any, start: datetime | None) -> tuple[Any, ...]:
    return (column >= start,) if start is not None else ()


def _aggregate_page_rollups(
    pages: Sequence[ReadingPersonalPageRollup],
) -> list[ReadingPageInsightResponse]:
    return [
        ReadingPageInsightResponse(
            page_number=page.page_number,
            active_ms=page.active_ms,
            visible_ms=page.visible_ms,
            visit_count=page.visit_count,
            vertical_segments_ms=list(page.vertical_segments_ms),
        )
        for page in sorted(pages, key=lambda item: item.page_number)
    ]


def _apply_page_delta(
    row: ReadingPersonalPageRollup,
    *,
    visible_delta: int,
    active_delta: int,
    visit_delta: int,
    segment_delta: list[int],
) -> None:
    row.visible_ms += visible_delta
    row.active_ms += active_delta
    row.visit_count += visit_delta
    row.vertical_segments_ms = [
        current + addition
        for current, addition in zip(
            row.vertical_segments_ms, segment_delta, strict=True
        )
    ]


def _apply_hour_delta(
    db: Session,
    row: ReadingPersonalHourRollup,
    *,
    visible_delta: int,
    active_delta: int,
    session_delta: int,
) -> None:
    next_visible = row.visible_ms + visible_delta
    next_active = row.active_ms + active_delta
    next_sessions = row.session_count + session_delta
    if min(next_visible, next_active, next_sessions) < 0 or next_active > next_visible:
        raise RuntimeError("reading_hour_rollup_regressed")
    if next_visible == next_active == next_sessions == 0:
        db.delete(row)
        return
    row.visible_ms = next_visible
    row.active_ms = next_active
    row.session_count = next_sessions


def _minimum_datetime(*values: datetime | None) -> datetime | None:
    present = [value for value in values if value is not None]
    return min(present) if present else None


def _maximum_datetime(*values: datetime | None) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None
