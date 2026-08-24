"""Transactional reading-activity rollup mutations.

The user-owned session ledger is canonical. This writer bulk-loads every source
and projection row needed by one mutation before changing any ORM object. The
caller holds the user-scoped transaction lock, so the number of database reads
is bounded by the number of tables involved, not by pages or hour buckets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.reading_activity.application.contracts import (
    ReadingHourSnapshotRequest,
    ReadingPageSnapshotRequest,
)
from app.modules.reading_activity.domain import PAGE_VERTICAL_SEGMENT_COUNT
from app.modules.reading_activity.infrastructure.models import (
    ReadingPersonalHourRollup,
    ReadingPersonalPageRollup,
    ReadingProjectHourRollup,
    ReadingProjectPageRollup,
    ReadingProjectPersonalPageRollup,
    ReadingSession,
    ReadingSessionHour,
    ReadingSessionPage,
)
from app.modules.reading_activity.infrastructure.shared import (
    _apply_hour_delta,
    _apply_page_delta,
    _hour_bucket,
)
from app.shared.domain import AppError, FailureKind


@dataclass
class _HourRows:
    source: dict[datetime, ReadingSessionHour]
    personal: dict[datetime, ReadingPersonalHourRollup]
    project: dict[datetime, ReadingProjectHourRollup]


@dataclass
class _PageRows:
    source: dict[int, ReadingSessionPage]
    personal: dict[int, ReadingPersonalPageRollup]
    project_personal: dict[int, ReadingProjectPersonalPageRollup]
    project_team: dict[int, ReadingProjectPageRollup]


class ReadingRollupWriter:
    """Maintain exact projections with one preload query per involved table."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def apply_snapshots(
        self,
        *,
        model: ReadingSession,
        hours: list[ReadingHourSnapshotRequest],
        pages: list[ReadingPageSnapshotRequest],
        materialize_session_count: bool,
    ) -> None:
        """Apply one cumulative snapshot without per-row database lookups."""
        ordered_hours = sorted(hours, key=lambda item: item.bucket_start)
        ordered_pages = sorted(pages, key=lambda item: item.page_number)
        first_bucket = _hour_bucket(model.started_at)
        if any(request.bucket_start < first_bucket for request in ordered_hours):
            raise AppError(
                code="reading_session_hour_invalid",
                message="An hour bucket precedes the reading session",
                kind=FailureKind.INVALID_ARGUMENT,
            )

        hour_buckets = {request.bucket_start for request in ordered_hours}
        if materialize_session_count:
            hour_buckets.add(first_bucket)
        page_numbers = {request.page_number for request in ordered_pages}

        # Finish all reads before adding or changing ORM rows. Besides bounding
        # query count, this prevents autoflush from turning the next preload
        # into one flush per page.
        hour_rows = self._load_hour_rows(
            model=model,
            buckets=hour_buckets,
            personal=True,
            project_id=(
                model.project_id if model.contribute_to_project_aggregates else None
            ),
        )
        page_rows = self._load_page_rows(
            model=model,
            page_numbers=page_numbers,
            personal=True,
            personal_project_id=model.project_id,
            team_project_id=(
                model.project_id if model.contribute_to_project_aggregates else None
            ),
        )

        if materialize_session_count:
            self._materialize_session_count(
                model=model,
                bucket=first_bucket,
                rows=hour_rows,
            )
        for hour_request in ordered_hours:
            self._apply_hour_snapshot(
                model=model,
                request=hour_request,
                rows=hour_rows,
            )
        for page_request in ordered_pages:
            self._apply_page_snapshot(
                model=model,
                request=page_request,
                rows=page_rows,
            )

    def subtract_session(
        self,
        *,
        model: ReadingSession,
        personal: bool,
        personal_project_id: UUID | None,
        team_project_id: UUID | None,
    ) -> None:
        """Subtract one session using a constant number of preload queries."""
        with self._db.no_autoflush:
            hours = list(
                self._db.scalars(
                    select(ReadingSessionHour)
                    .where(ReadingSessionHour.session_id == model.id)
                    .order_by(ReadingSessionHour.bucket_start)
                ).all()
            )
            pages = list(
                self._db.scalars(
                    select(ReadingSessionPage)
                    .where(ReadingSessionPage.session_id == model.id)
                    .order_by(ReadingSessionPage.page_number)
                ).all()
            )
            hour_rows = self._load_hour_rows(
                model=model,
                buckets={hour.bucket_start for hour in hours},
                personal=personal,
                project_id=team_project_id,
                include_source=False,
            )
            page_rows = self._load_page_rows(
                model=model,
                page_numbers={page.page_number for page in pages},
                personal=personal,
                personal_project_id=personal_project_id,
                team_project_id=team_project_id,
                include_source=False,
            )

        for hour in hours:
            if personal:
                self._adjust_personal_hour(
                    model=model,
                    bucket=hour.bucket_start,
                    visible_delta=-hour.visible_ms,
                    active_delta=-hour.active_ms,
                    session_delta=-hour.session_count,
                    rows=hour_rows,
                )
            if team_project_id is not None:
                self._adjust_project_hour(
                    model=model,
                    project_id=team_project_id,
                    bucket=hour.bucket_start,
                    visible_delta=-hour.visible_ms,
                    active_delta=-hour.active_ms,
                    rows=hour_rows,
                )
        for page in pages:
            if personal:
                self._subtract_page_rollup(
                    row=page_rows.personal.get(page.page_number),
                    visible_ms=page.visible_ms,
                    active_ms=page.active_ms,
                    visit_count=page.visit_count,
                    segment_delta=[-value for value in page.vertical_segments_ms],
                )
            if personal_project_id is not None:
                self._subtract_project_page_rollup(
                    row=page_rows.project_personal.get(page.page_number),
                    active_ms=page.active_ms,
                )
            if team_project_id is not None:
                self._subtract_project_page_rollup(
                    row=page_rows.project_team.get(page.page_number),
                    active_ms=page.active_ms,
                )

    def _load_hour_rows(
        self,
        *,
        model: ReadingSession,
        buckets: set[datetime],
        personal: bool,
        project_id: UUID | None,
        include_source: bool = True,
    ) -> _HourRows:
        if not buckets:
            return _HourRows(source={}, personal={}, project={})
        with self._db.no_autoflush:
            source_rows = (
                list(
                    self._db.scalars(
                        select(ReadingSessionHour).where(
                            ReadingSessionHour.session_id == model.id,
                            ReadingSessionHour.bucket_start.in_(buckets),
                        )
                    ).all()
                )
                if include_source
                else []
            )
            personal_rows = (
                list(
                    self._db.scalars(
                        select(ReadingPersonalHourRollup).where(
                            ReadingPersonalHourRollup.user_id == model.user_id,
                            ReadingPersonalHourRollup.document_id == model.document_id,
                            ReadingPersonalHourRollup.metric_definition_version
                            == model.metric_definition_version,
                            ReadingPersonalHourRollup.bucket_start.in_(buckets),
                        )
                    ).all()
                )
                if personal
                else []
            )
            project_rows = (
                list(
                    self._db.scalars(
                        select(ReadingProjectHourRollup).where(
                            ReadingProjectHourRollup.project_id == project_id,
                            ReadingProjectHourRollup.user_id == model.user_id,
                            ReadingProjectHourRollup.document_id == model.document_id,
                            ReadingProjectHourRollup.metric_definition_version
                            == model.metric_definition_version,
                            ReadingProjectHourRollup.bucket_start.in_(buckets),
                        )
                    ).all()
                )
                if project_id is not None
                else []
            )
        return _HourRows(
            source={row.bucket_start: row for row in source_rows},
            personal={row.bucket_start: row for row in personal_rows},
            project={row.bucket_start: row for row in project_rows},
        )

    def _load_page_rows(
        self,
        *,
        model: ReadingSession,
        page_numbers: set[int],
        personal: bool,
        personal_project_id: UUID | None,
        team_project_id: UUID | None,
        include_source: bool = True,
    ) -> _PageRows:
        if not page_numbers:
            return _PageRows(
                source={},
                personal={},
                project_personal={},
                project_team={},
            )
        with self._db.no_autoflush:
            source_rows = (
                list(
                    self._db.scalars(
                        select(ReadingSessionPage).where(
                            ReadingSessionPage.session_id == model.id,
                            ReadingSessionPage.page_number.in_(page_numbers),
                        )
                    ).all()
                )
                if include_source
                else []
            )
            personal_rows = (
                list(
                    self._db.scalars(
                        select(ReadingPersonalPageRollup).where(
                            ReadingPersonalPageRollup.user_id == model.user_id,
                            ReadingPersonalPageRollup.document_id == model.document_id,
                            ReadingPersonalPageRollup.metric_definition_version
                            == model.metric_definition_version,
                            ReadingPersonalPageRollup.page_number.in_(page_numbers),
                        )
                    ).all()
                )
                if personal
                else []
            )
            project_personal_rows = (
                list(
                    self._db.scalars(
                        select(ReadingProjectPersonalPageRollup).where(
                            ReadingProjectPersonalPageRollup.project_id
                            == personal_project_id,
                            ReadingProjectPersonalPageRollup.user_id == model.user_id,
                            ReadingProjectPersonalPageRollup.document_id
                            == model.document_id,
                            ReadingProjectPersonalPageRollup.metric_definition_version
                            == model.metric_definition_version,
                            ReadingProjectPersonalPageRollup.page_number.in_(
                                page_numbers
                            ),
                        )
                    ).all()
                )
                if personal_project_id is not None
                else []
            )
            project_team_rows = (
                list(
                    self._db.scalars(
                        select(ReadingProjectPageRollup).where(
                            ReadingProjectPageRollup.project_id == team_project_id,
                            ReadingProjectPageRollup.user_id == model.user_id,
                            ReadingProjectPageRollup.document_id == model.document_id,
                            ReadingProjectPageRollup.metric_definition_version
                            == model.metric_definition_version,
                            ReadingProjectPageRollup.page_number.in_(page_numbers),
                        )
                    ).all()
                )
                if team_project_id is not None
                else []
            )
        return _PageRows(
            source={row.page_number: row for row in source_rows},
            personal={row.page_number: row for row in personal_rows},
            project_personal={row.page_number: row for row in project_personal_rows},
            project_team={row.page_number: row for row in project_team_rows},
        )

    def _apply_hour_snapshot(
        self,
        *,
        model: ReadingSession,
        request: ReadingHourSnapshotRequest,
        rows: _HourRows,
    ) -> None:
        source_hour = rows.source.get(request.bucket_start)
        old_visible = source_hour.visible_ms if source_hour is not None else 0
        old_active = source_hour.active_ms if source_hour is not None else 0
        if request.visible_ms < old_visible or request.active_ms < old_active:
            raise AppError(
                code="reading_session_hour_regressed",
                message="Reading hour cumulative values cannot decrease",
                kind=FailureKind.CONFLICT,
            )
        if request.active_ms - old_active > request.visible_ms - old_visible:
            raise AppError(
                code="reading_session_hour_delta_invalid",
                message="Hour active duration cannot exceed its new visible duration",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        if source_hour is None and request.visible_ms == request.active_ms == 0:
            return
        if source_hour is None:
            source_hour = ReadingSessionHour(
                session_id=model.id,
                metric_definition_version=model.metric_definition_version,
                bucket_start=request.bucket_start,
                visible_ms=request.visible_ms,
                active_ms=request.active_ms,
                session_count=0,
            )
            self._db.add(source_hour)
            rows.source[request.bucket_start] = source_hour
        else:
            if source_hour.metric_definition_version != model.metric_definition_version:
                raise RuntimeError("reading_session_hour_version_mismatch")
            source_hour.visible_ms = request.visible_ms
            source_hour.active_ms = request.active_ms
        visible_delta = request.visible_ms - old_visible
        active_delta = request.active_ms - old_active
        if visible_delta == active_delta == 0:
            return
        self._adjust_personal_hour(
            model=model,
            bucket=request.bucket_start,
            visible_delta=visible_delta,
            active_delta=active_delta,
            session_delta=0,
            rows=rows,
        )
        if model.contribute_to_project_aggregates and model.project_id is not None:
            self._adjust_project_hour(
                model=model,
                project_id=model.project_id,
                bucket=request.bucket_start,
                visible_delta=visible_delta,
                active_delta=active_delta,
                rows=rows,
            )

    def _materialize_session_count(
        self,
        *,
        model: ReadingSession,
        bucket: datetime,
        rows: _HourRows,
    ) -> None:
        source_hour = rows.source.get(bucket)
        if source_hour is None:
            source_hour = ReadingSessionHour(
                session_id=model.id,
                metric_definition_version=model.metric_definition_version,
                bucket_start=bucket,
                visible_ms=0,
                active_ms=0,
                session_count=1,
            )
            self._db.add(source_hour)
            rows.source[bucket] = source_hour
        elif source_hour.session_count == 0:
            source_hour.session_count = 1
        else:
            raise RuntimeError("reading_session_count_already_materialized")
        self._adjust_personal_hour(
            model=model,
            bucket=bucket,
            visible_delta=0,
            active_delta=0,
            session_delta=1,
            rows=rows,
        )

    def _apply_page_snapshot(
        self,
        *,
        model: ReadingSession,
        request: ReadingPageSnapshotRequest,
        rows: _PageRows,
    ) -> None:
        page = rows.source.get(request.page_number)
        old_visible = page.visible_ms if page is not None else 0
        old_active = page.active_ms if page is not None else 0
        old_visits = page.visit_count if page is not None else 0
        old_segments = (
            list(page.vertical_segments_ms)
            if page is not None
            else [0] * PAGE_VERTICAL_SEGMENT_COUNT
        )
        if (
            request.visible_ms < old_visible
            or request.active_ms < old_active
            or request.visit_count < old_visits
            or any(
                current < previous
                for current, previous in zip(
                    request.vertical_segments_ms, old_segments, strict=True
                )
            )
        ):
            raise AppError(
                code="reading_session_page_regressed",
                message="Reading page cumulative values cannot decrease",
                kind=FailureKind.CONFLICT,
            )
        if request.active_ms - old_active > request.visible_ms - old_visible:
            raise AppError(
                code="reading_session_page_delta_invalid",
                message="Page active duration cannot exceed its new visible duration",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        if (
            page is None
            and request.visible_ms == 0
            and request.visit_count == 0
            and not any(request.vertical_segments_ms)
        ):
            return
        if page is None:
            page = ReadingSessionPage(
                session_id=model.id,
                metric_definition_version=model.metric_definition_version,
                page_number=request.page_number,
                visible_ms=request.visible_ms,
                active_ms=request.active_ms,
                visit_count=request.visit_count,
                vertical_segments_ms=list(request.vertical_segments_ms),
            )
            self._db.add(page)
            rows.source[request.page_number] = page
        else:
            page.visible_ms = request.visible_ms
            page.active_ms = request.active_ms
            page.visit_count = request.visit_count
            page.vertical_segments_ms = list(request.vertical_segments_ms)
        visible_delta = request.visible_ms - old_visible
        active_delta = request.active_ms - old_active
        visit_delta = request.visit_count - old_visits
        segment_delta = [
            current - previous
            for current, previous in zip(
                request.vertical_segments_ms, old_segments, strict=True
            )
        ]
        self._adjust_personal_page(
            model=model,
            page_number=request.page_number,
            visible_delta=visible_delta,
            active_delta=active_delta,
            visit_delta=visit_delta,
            segment_delta=segment_delta,
            rows=rows,
        )
        if model.project_id is not None:
            self._adjust_project_personal_page(
                model=model,
                project_id=model.project_id,
                page_number=request.page_number,
                active_delta=active_delta,
                rows=rows,
            )
        if model.contribute_to_project_aggregates and model.project_id is not None:
            self._adjust_project_page(
                model=model,
                project_id=model.project_id,
                page_number=request.page_number,
                active_delta=active_delta,
                rows=rows,
            )

    def _adjust_personal_hour(
        self,
        *,
        model: ReadingSession,
        bucket: datetime,
        visible_delta: int,
        active_delta: int,
        session_delta: int,
        rows: _HourRows,
    ) -> None:
        row = rows.personal.get(bucket)
        if row is None:
            if min(visible_delta, active_delta, session_delta) < 0:
                raise RuntimeError("reading_personal_hour_rollup_missing")
            row = ReadingPersonalHourRollup(
                user_id=model.user_id,
                document_id=model.document_id,
                metric_definition_version=model.metric_definition_version,
                bucket_start=bucket,
                visible_ms=visible_delta,
                active_ms=active_delta,
                session_count=session_delta,
            )
            self._db.add(row)
            rows.personal[bucket] = row
            return
        _apply_hour_delta(
            self._db,
            row,
            visible_delta=visible_delta,
            active_delta=active_delta,
            session_delta=session_delta,
        )

    def _adjust_project_hour(
        self,
        *,
        model: ReadingSession,
        project_id: UUID,
        bucket: datetime,
        visible_delta: int,
        active_delta: int,
        rows: _HourRows,
    ) -> None:
        row = rows.project.get(bucket)
        if row is None:
            if visible_delta == active_delta == 0:
                return
            if min(visible_delta, active_delta) < 0:
                raise RuntimeError("reading_project_hour_rollup_missing")
            row = ReadingProjectHourRollup(
                project_id=project_id,
                user_id=model.user_id,
                document_id=model.document_id,
                metric_definition_version=model.metric_definition_version,
                bucket_start=bucket,
                visible_ms=visible_delta,
                active_ms=active_delta,
            )
            self._db.add(row)
            rows.project[bucket] = row
            return
        next_visible = row.visible_ms + visible_delta
        next_active = row.active_ms + active_delta
        if min(next_visible, next_active) < 0 or next_active > next_visible:
            raise RuntimeError("reading_project_hour_rollup_regressed")
        if next_visible == next_active == 0:
            self._db.delete(row)
            return
        row.visible_ms = next_visible
        row.active_ms = next_active

    def _adjust_personal_page(
        self,
        *,
        model: ReadingSession,
        page_number: int,
        visible_delta: int,
        active_delta: int,
        visit_delta: int,
        segment_delta: list[int],
        rows: _PageRows,
    ) -> None:
        row = rows.personal.get(page_number)
        if row is None:
            row = ReadingPersonalPageRollup(
                user_id=model.user_id,
                document_id=model.document_id,
                metric_definition_version=model.metric_definition_version,
                page_number=page_number,
                visible_ms=visible_delta,
                active_ms=active_delta,
                visit_count=visit_delta,
                vertical_segments_ms=list(segment_delta),
            )
            self._db.add(row)
            rows.personal[page_number] = row
            return
        _apply_page_delta(
            row,
            visible_delta=visible_delta,
            active_delta=active_delta,
            visit_delta=visit_delta,
            segment_delta=segment_delta,
        )

    def _adjust_project_page(
        self,
        *,
        model: ReadingSession,
        project_id: UUID,
        page_number: int,
        active_delta: int,
        rows: _PageRows,
    ) -> None:
        row = rows.project_team.get(page_number)
        if row is None:
            if active_delta == 0:
                return
            if active_delta < 0:
                raise RuntimeError("reading_project_page_rollup_missing")
            row = ReadingProjectPageRollup(
                project_id=project_id,
                user_id=model.user_id,
                document_id=model.document_id,
                metric_definition_version=model.metric_definition_version,
                page_number=page_number,
                active_ms=active_delta,
            )
            self._db.add(row)
            rows.project_team[page_number] = row
            return
        row.active_ms += active_delta

    def _adjust_project_personal_page(
        self,
        *,
        model: ReadingSession,
        project_id: UUID,
        page_number: int,
        active_delta: int,
        rows: _PageRows,
    ) -> None:
        row = rows.project_personal.get(page_number)
        if row is None:
            if active_delta == 0:
                return
            if active_delta < 0:
                raise RuntimeError("reading_project_personal_page_rollup_missing")
            row = ReadingProjectPersonalPageRollup(
                project_id=project_id,
                user_id=model.user_id,
                document_id=model.document_id,
                metric_definition_version=model.metric_definition_version,
                page_number=page_number,
                active_ms=active_delta,
            )
            self._db.add(row)
            rows.project_personal[page_number] = row
            return
        row.active_ms += active_delta

    def _subtract_page_rollup(
        self,
        *,
        row: ReadingPersonalPageRollup | None,
        visible_ms: int,
        active_ms: int,
        visit_count: int,
        segment_delta: list[int],
    ) -> None:
        if row is None:
            raise RuntimeError("reading_page_rollup_missing")
        row.visible_ms -= visible_ms
        row.active_ms -= active_ms
        row.visit_count -= visit_count
        row.vertical_segments_ms = [
            current + delta
            for current, delta in zip(
                row.vertical_segments_ms,
                segment_delta,
                strict=True,
            )
        ]
        if (
            row.visible_ms < 0
            or row.active_ms < 0
            or row.visit_count < 0
            or any(value < 0 for value in row.vertical_segments_ms)
        ):
            raise RuntimeError("reading_page_rollup_regressed")
        if (
            row.visible_ms == 0
            and row.active_ms == 0
            and row.visit_count == 0
            and not any(row.vertical_segments_ms)
        ):
            self._db.delete(row)

    def _subtract_project_page_rollup(
        self,
        *,
        row: ReadingProjectPageRollup | ReadingProjectPersonalPageRollup | None,
        active_ms: int,
    ) -> None:
        if row is None:
            if active_ms == 0:
                return
            raise RuntimeError("reading_project_page_rollup_missing")
        row.active_ms -= active_ms
        if row.active_ms < 0:
            raise RuntimeError("reading_project_page_rollup_regressed")
        if row.active_ms == 0:
            self._db.delete(row)


__all__ = ["ReadingRollupWriter"]
