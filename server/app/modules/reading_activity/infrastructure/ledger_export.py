"""Bounded, actor-scoped export of the retained reading ledger."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import literal, select, tuple_
from sqlalchemy.orm import Session

from app.modules.reading_activity.application.contracts import (
    ReadingActivityExportRecordResponse,
    ReadingActivityExportResponse,
    ReadingExportFormat,
)
from app.modules.reading_activity.infrastructure.models import (
    ReadingActivityPreference,
    ReadingPersonalHourRollup,
    ReadingPersonalPageRollup,
    ReadingProjectHourRollup,
    ReadingProjectPageRollup,
    ReadingProjectPersonalPageRollup,
    ReadingSession,
    ReadingSessionHour,
    ReadingSessionPage,
)
from app.shared.application import Actor, Clock, SignedCursorCodec
from app.shared.domain import AppError, FailureKind, JsonValue


_PAGE_DETAIL_RETENTION = timedelta(days=90)
_EXPORT_LIMIT_MAXIMUM = 1_000
_CURSOR_ARITY = 6
_RECORD_TYPES = (
    "preferences",
    "session",
    "session_hour",
    "session_page",
    "personal_page_rollup",
    "personal_hour_rollup",
    "project_personal_page_rollup",
    "project_contributed_page_rollup",
    "project_contributed_hour_rollup",
)


@dataclass(frozen=True, slots=True)
class _ExportEntry:
    record_type: str
    key: tuple[str, ...]
    payload: dict[str, JsonValue]


class ReadingLedgerExporter:
    """Page through each source in native primary-key order.

    Every source query is independently actor-scoped and limited. The signed
    cursor freezes the export timestamp and position, but the privacy cutoff
    advances with wall time so an old cursor cannot disclose expired raw page
    detail. The export is intentionally not a cross-request database snapshot:
    concurrent writes can update records not yet visited, and page detail may
    expire between pages.
    """

    def __init__(
        self,
        db: Session,
        *,
        clock: Clock,
        cursors: SignedCursorCodec,
    ) -> None:
        self._db = db
        self._clock = clock
        self._cursors = cursors

    def export(
        self,
        *,
        actor: Actor,
        export_format: ReadingExportFormat,
        cursor: str | None,
        limit: int,
    ) -> ReadingActivityExportResponse:
        if not 1 <= limit <= _EXPORT_LIMIT_MAXIMUM:
            raise AppError(
                code="reading_activity_export_limit_invalid",
                message="Reading activity export limit must be between 1 and 1000",
                kind=FailureKind.INVALID_ARGUMENT,
            )
        fingerprint = _fingerprint(
            actor_id=actor.id,
            export_format=export_format,
        )
        if cursor is None:
            exported_at = self._clock.now()
            first_type = _RECORD_TYPES[0]
            first_key: tuple[str, ...] | None = None
        else:
            exported_at, first_type, first_key = _decode_position(
                self._cursors.decode_keyset(
                    cursor=cursor,
                    fingerprint=fingerprint,
                    arity=_CURSOR_ARITY,
                )
            )

        target = limit + 1
        entries: list[_ExportEntry] = []
        first_index = _RECORD_TYPES.index(first_type)
        page_detail_cutoff = _effective_page_detail_cutoff(
            exported_at=exported_at,
            now=self._clock.now(),
        )
        for index in range(first_index, len(_RECORD_TYPES)):
            record_type = _RECORD_TYPES[index]
            remaining = target - len(entries)
            if remaining <= 0:
                break
            entries.extend(
                self._batch(
                    record_type=record_type,
                    actor_id=actor.id,
                    page_detail_cutoff=page_detail_cutoff,
                    after=(first_key if index == first_index else None),
                    limit=remaining,
                )
            )

        has_more = len(entries) > limit
        page = entries[:limit]
        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = self._cursors.encode_keyset(
                fingerprint=fingerprint,
                values=_encode_position(
                    exported_at=exported_at,
                    record_type=last.record_type,
                    key=last.key,
                ),
            )
        return ReadingActivityExportResponse(
            exported_at=exported_at,
            records=[
                ReadingActivityExportRecordResponse(
                    record_type=entry.record_type,
                    payload=entry.payload,
                )
                for entry in page
            ],
            next_cursor=next_cursor,
        )

    def _batch(
        self,
        *,
        record_type: str,
        actor_id: int,
        page_detail_cutoff: datetime,
        after: tuple[str, ...] | None,
        limit: int,
    ) -> list[_ExportEntry]:
        if record_type == "preferences":
            return self._preference(actor_id=actor_id, after=after)
        if record_type == "session":
            return self._sessions(
                actor_id=actor_id,
                page_detail_cutoff=page_detail_cutoff,
                after=after,
                limit=limit,
            )
        if record_type == "session_hour":
            return self._session_hours(actor_id=actor_id, after=after, limit=limit)
        if record_type == "session_page":
            return self._session_pages(
                actor_id=actor_id,
                page_detail_cutoff=page_detail_cutoff,
                after=after,
                limit=limit,
            )
        if record_type == "personal_page_rollup":
            return self._personal_pages(actor_id=actor_id, after=after, limit=limit)
        if record_type == "personal_hour_rollup":
            return self._personal_hours(actor_id=actor_id, after=after, limit=limit)
        if record_type == "project_personal_page_rollup":
            return self._project_personal_pages(
                actor_id=actor_id,
                after=after,
                limit=limit,
            )
        if record_type == "project_contributed_page_rollup":
            return self._project_pages(actor_id=actor_id, after=after, limit=limit)
        if record_type == "project_contributed_hour_rollup":
            return self._project_hours(actor_id=actor_id, after=after, limit=limit)
        raise RuntimeError("reading_activity_export_record_type_unknown")

    def _preference(
        self, *, actor_id: int, after: tuple[str, ...] | None
    ) -> list[_ExportEntry]:
        if after is not None:
            _require_key(after, arity=1)
            return []
        model = self._db.get(ReadingActivityPreference, actor_id)
        payload: dict[str, JsonValue] = {
            "recording_enabled": model.recording_enabled if model else True,
            "contribute_anonymous_project_aggregates": (
                model.contribute_anonymous_project_aggregates if model else True
            ),
            "updated_at": _timestamp(model.updated_at) if model else None,
        }
        return [_ExportEntry("preferences", ("default",), payload)]

    def _sessions(
        self,
        *,
        actor_id: int,
        page_detail_cutoff: datetime,
        after: tuple[str, ...] | None,
        limit: int,
    ) -> list[_ExportEntry]:
        statement = select(ReadingSession).where(ReadingSession.user_id == actor_id)
        if after is not None:
            key = _uuid_key(after)
            statement = statement.where(ReadingSession.id > key)
        rows = self._db.scalars(
            statement.order_by(ReadingSession.id).limit(limit)
        ).all()
        return [
            _ExportEntry(
                "session",
                (str(row.id),),
                {
                    "id": str(row.id),
                    "document_id": str(row.document_id),
                    "project_id": str(row.project_id) if row.project_id else None,
                    "view_mode": row.view_mode,
                    "time_zone": row.time_zone,
                    "metric_definition_version": row.metric_definition_version,
                    "revision": row.revision,
                    "visible_ms": row.visible_ms,
                    "active_ms": row.active_ms,
                    "started_at": _timestamp(row.started_at),
                    "last_seen_at": _timestamp(row.last_seen_at),
                    "ended_at": _timestamp(row.ended_at),
                    "project_contribution_enabled": (
                        row.project_id is not None
                        and row.contribute_to_project_aggregates
                    ),
                    "page_detail_available": (
                        row.page_detail_purged_at is None
                        and row.started_at >= page_detail_cutoff
                    ),
                },
            )
            for row in rows
        ]

    def _session_hours(
        self, *, actor_id: int, after: tuple[str, ...] | None, limit: int
    ) -> list[_ExportEntry]:
        statement = (
            select(ReadingSessionHour)
            .join(ReadingSession, ReadingSession.id == ReadingSessionHour.session_id)
            .where(ReadingSession.user_id == actor_id)
        )
        if after is not None:
            session_id, bucket = _uuid_datetime_key(after)
            statement = statement.where(
                tuple_(
                    ReadingSessionHour.session_id,
                    ReadingSessionHour.bucket_start,
                )
                > _sql_key(session_id, bucket)
            )
        rows = self._db.scalars(
            statement.order_by(
                ReadingSessionHour.session_id,
                ReadingSessionHour.bucket_start,
            ).limit(limit)
        ).all()
        return [
            _ExportEntry(
                "session_hour",
                (str(row.session_id), _required_timestamp(row.bucket_start)),
                {
                    "session_id": str(row.session_id),
                    "metric_definition_version": row.metric_definition_version,
                    "bucket_start": _required_timestamp(row.bucket_start),
                    "visible_ms": row.visible_ms,
                    "active_ms": row.active_ms,
                },
            )
            for row in rows
        ]

    def _session_pages(
        self,
        *,
        actor_id: int,
        page_detail_cutoff: datetime,
        after: tuple[str, ...] | None,
        limit: int,
    ) -> list[_ExportEntry]:
        statement = (
            select(ReadingSessionPage)
            .join(ReadingSession, ReadingSession.id == ReadingSessionPage.session_id)
            .where(
                ReadingSession.user_id == actor_id,
                ReadingSession.page_detail_purged_at.is_(None),
                ReadingSession.started_at >= page_detail_cutoff,
            )
        )
        if after is not None:
            session_id, page_number = _uuid_int_key(after)
            statement = statement.where(
                tuple_(
                    ReadingSessionPage.session_id,
                    ReadingSessionPage.page_number,
                )
                > _sql_key(session_id, page_number)
            )
        rows = self._db.scalars(
            statement.order_by(
                ReadingSessionPage.session_id,
                ReadingSessionPage.page_number,
            ).limit(limit)
        ).all()
        return [
            _ExportEntry(
                "session_page",
                (str(row.session_id), str(row.page_number)),
                {
                    "session_id": str(row.session_id),
                    "metric_definition_version": row.metric_definition_version,
                    "page_number": row.page_number,
                    "visible_ms": row.visible_ms,
                    "active_ms": row.active_ms,
                    "visit_count": row.visit_count,
                    "vertical_segments_ms": list(row.vertical_segments_ms),
                },
            )
            for row in rows
        ]

    def _personal_pages(
        self, *, actor_id: int, after: tuple[str, ...] | None, limit: int
    ) -> list[_ExportEntry]:
        statement = select(ReadingPersonalPageRollup).where(
            ReadingPersonalPageRollup.user_id == actor_id
        )
        if after is not None:
            document_id, version, page_number = _uuid_str_int_key(after)
            statement = statement.where(
                tuple_(
                    ReadingPersonalPageRollup.document_id,
                    ReadingPersonalPageRollup.metric_definition_version,
                    ReadingPersonalPageRollup.page_number,
                )
                > _sql_key(document_id, version, page_number)
            )
        rows = self._db.scalars(
            statement.order_by(
                ReadingPersonalPageRollup.document_id,
                ReadingPersonalPageRollup.metric_definition_version,
                ReadingPersonalPageRollup.page_number,
            ).limit(limit)
        ).all()
        return [
            _ExportEntry(
                "personal_page_rollup",
                (
                    str(row.document_id),
                    row.metric_definition_version,
                    str(row.page_number),
                ),
                {
                    "document_id": str(row.document_id),
                    "metric_definition_version": row.metric_definition_version,
                    "page_number": row.page_number,
                    "visible_ms": row.visible_ms,
                    "active_ms": row.active_ms,
                    "visit_count": row.visit_count,
                    "vertical_segments_ms": list(row.vertical_segments_ms),
                },
            )
            for row in rows
        ]

    def _personal_hours(
        self, *, actor_id: int, after: tuple[str, ...] | None, limit: int
    ) -> list[_ExportEntry]:
        statement = select(ReadingPersonalHourRollup).where(
            ReadingPersonalHourRollup.user_id == actor_id
        )
        if after is not None:
            document_id, version, bucket = _uuid_str_datetime_key(after)
            statement = statement.where(
                tuple_(
                    ReadingPersonalHourRollup.document_id,
                    ReadingPersonalHourRollup.metric_definition_version,
                    ReadingPersonalHourRollup.bucket_start,
                )
                > _sql_key(document_id, version, bucket)
            )
        rows = self._db.scalars(
            statement.order_by(
                ReadingPersonalHourRollup.document_id,
                ReadingPersonalHourRollup.metric_definition_version,
                ReadingPersonalHourRollup.bucket_start,
            ).limit(limit)
        ).all()
        return [
            _ExportEntry(
                "personal_hour_rollup",
                (
                    str(row.document_id),
                    row.metric_definition_version,
                    _required_timestamp(row.bucket_start),
                ),
                {
                    "document_id": str(row.document_id),
                    "metric_definition_version": row.metric_definition_version,
                    "bucket_start": _required_timestamp(row.bucket_start),
                    "visible_ms": row.visible_ms,
                    "active_ms": row.active_ms,
                    "session_count": row.session_count,
                },
            )
            for row in rows
        ]

    def _project_personal_pages(
        self, *, actor_id: int, after: tuple[str, ...] | None, limit: int
    ) -> list[_ExportEntry]:
        statement = select(ReadingProjectPersonalPageRollup).where(
            ReadingProjectPersonalPageRollup.user_id == actor_id
        )
        if after is not None:
            project_id, document_id, version, page_number = _project_page_key(after)
            statement = statement.where(
                tuple_(
                    ReadingProjectPersonalPageRollup.project_id,
                    ReadingProjectPersonalPageRollup.document_id,
                    ReadingProjectPersonalPageRollup.metric_definition_version,
                    ReadingProjectPersonalPageRollup.page_number,
                )
                > _sql_key(project_id, document_id, version, page_number)
            )
        rows = self._db.scalars(
            statement.order_by(
                ReadingProjectPersonalPageRollup.project_id,
                ReadingProjectPersonalPageRollup.document_id,
                ReadingProjectPersonalPageRollup.metric_definition_version,
                ReadingProjectPersonalPageRollup.page_number,
            ).limit(limit)
        ).all()
        return [
            _project_page_entry(
                record_type="project_personal_page_rollup",
                row=row,
            )
            for row in rows
        ]

    def _project_pages(
        self, *, actor_id: int, after: tuple[str, ...] | None, limit: int
    ) -> list[_ExportEntry]:
        statement = select(ReadingProjectPageRollup).where(
            ReadingProjectPageRollup.user_id == actor_id
        )
        if after is not None:
            project_id, document_id, version, page_number = _project_page_key(after)
            statement = statement.where(
                tuple_(
                    ReadingProjectPageRollup.project_id,
                    ReadingProjectPageRollup.document_id,
                    ReadingProjectPageRollup.metric_definition_version,
                    ReadingProjectPageRollup.page_number,
                )
                > _sql_key(project_id, document_id, version, page_number)
            )
        rows = self._db.scalars(
            statement.order_by(
                ReadingProjectPageRollup.project_id,
                ReadingProjectPageRollup.document_id,
                ReadingProjectPageRollup.metric_definition_version,
                ReadingProjectPageRollup.page_number,
            ).limit(limit)
        ).all()
        return [
            _project_page_entry(
                record_type="project_contributed_page_rollup",
                row=row,
            )
            for row in rows
        ]

    def _project_hours(
        self, *, actor_id: int, after: tuple[str, ...] | None, limit: int
    ) -> list[_ExportEntry]:
        statement = select(ReadingProjectHourRollup).where(
            ReadingProjectHourRollup.user_id == actor_id
        )
        if after is not None:
            project_id, document_id, version, bucket = _project_hour_key(after)
            statement = statement.where(
                tuple_(
                    ReadingProjectHourRollup.project_id,
                    ReadingProjectHourRollup.document_id,
                    ReadingProjectHourRollup.metric_definition_version,
                    ReadingProjectHourRollup.bucket_start,
                )
                > _sql_key(project_id, document_id, version, bucket)
            )
        rows = self._db.scalars(
            statement.order_by(
                ReadingProjectHourRollup.project_id,
                ReadingProjectHourRollup.document_id,
                ReadingProjectHourRollup.metric_definition_version,
                ReadingProjectHourRollup.bucket_start,
            ).limit(limit)
        ).all()
        return [
            _ExportEntry(
                "project_contributed_hour_rollup",
                (
                    str(row.project_id),
                    str(row.document_id),
                    row.metric_definition_version,
                    _required_timestamp(row.bucket_start),
                ),
                {
                    "project_id": str(row.project_id),
                    "document_id": str(row.document_id),
                    "metric_definition_version": row.metric_definition_version,
                    "bucket_start": _required_timestamp(row.bucket_start),
                    "visible_ms": row.visible_ms,
                    "active_ms": row.active_ms,
                },
            )
            for row in rows
        ]


def _project_page_entry(*, record_type: str, row: Any) -> _ExportEntry:
    return _ExportEntry(
        record_type,
        (
            str(row.project_id),
            str(row.document_id),
            row.metric_definition_version,
            str(row.page_number),
        ),
        {
            "project_id": str(row.project_id),
            "document_id": str(row.document_id),
            "metric_definition_version": row.metric_definition_version,
            "page_number": row.page_number,
            "active_ms": row.active_ms,
        },
    )


def _encode_position(
    *, exported_at: datetime, record_type: str, key: tuple[str, ...]
) -> tuple[str, ...]:
    if len(key) > 4:
        raise RuntimeError("reading_activity_export_key_too_wide")
    return (
        _required_timestamp(exported_at),
        record_type,
        *key,
        *("" for _ in range(4 - len(key))),
    )


def _decode_position(
    values: tuple[str, ...],
) -> tuple[datetime, str, tuple[str, ...]]:
    try:
        exported_at = datetime.fromisoformat(values[0])
        record_type = values[1]
        if exported_at.tzinfo is None or record_type not in _RECORD_TYPES:
            raise ValueError
        expected = _key_arity(record_type)
        key = tuple(values[2 : 2 + expected])
        if any(not value for value in key) or any(values[2 + expected :]):
            raise ValueError
        _validate_key(record_type=record_type, key=key)
    except (ValueError, IndexError) as exc:
        raise AppError(
            code="reading_activity_export_cursor_invalid",
            message="The reading activity export cursor is invalid",
            kind=FailureKind.INVALID_ARGUMENT,
        ) from exc
    return exported_at, record_type, key


def _key_arity(record_type: str) -> int:
    return {
        "preferences": 1,
        "session": 1,
        "session_hour": 2,
        "session_page": 2,
        "personal_page_rollup": 3,
        "personal_hour_rollup": 3,
        "project_personal_page_rollup": 4,
        "project_contributed_page_rollup": 4,
        "project_contributed_hour_rollup": 4,
    }[record_type]


def _validate_key(*, record_type: str, key: tuple[str, ...]) -> None:
    if record_type == "preferences":
        if key != ("default",):
            raise ValueError
    elif record_type == "session":
        _uuid_key(key)
    elif record_type == "session_hour":
        _uuid_datetime_key(key)
    elif record_type == "session_page":
        _uuid_int_key(key)
    elif record_type == "personal_page_rollup":
        _uuid_str_int_key(key)
    elif record_type == "personal_hour_rollup":
        _uuid_str_datetime_key(key)
    elif record_type in {
        "project_personal_page_rollup",
        "project_contributed_page_rollup",
    }:
        _project_page_key(key)
    else:
        _project_hour_key(key)


def _uuid_key(values: tuple[str, ...]) -> UUID:
    _require_key(values, arity=1)
    return UUID(values[0])


def _uuid_datetime_key(values: tuple[str, ...]) -> tuple[UUID, datetime]:
    _require_key(values, arity=2)
    return UUID(values[0]), _aware_datetime(values[1])


def _uuid_int_key(values: tuple[str, ...]) -> tuple[UUID, int]:
    _require_key(values, arity=2)
    return UUID(values[0]), _positive_int(values[1])


def _uuid_str_int_key(values: tuple[str, ...]) -> tuple[UUID, str, int]:
    _require_key(values, arity=3)
    if not values[1]:
        raise ValueError
    return UUID(values[0]), values[1], _positive_int(values[2])


def _uuid_str_datetime_key(values: tuple[str, ...]) -> tuple[UUID, str, datetime]:
    _require_key(values, arity=3)
    if not values[1]:
        raise ValueError
    return UUID(values[0]), values[1], _aware_datetime(values[2])


def _project_page_key(values: tuple[str, ...]) -> tuple[UUID, UUID, str, int]:
    _require_key(values, arity=4)
    if not values[2]:
        raise ValueError
    return UUID(values[0]), UUID(values[1]), values[2], _positive_int(values[3])


def _project_hour_key(
    values: tuple[str, ...],
) -> tuple[UUID, UUID, str, datetime]:
    _require_key(values, arity=4)
    if not values[2]:
        raise ValueError
    return UUID(values[0]), UUID(values[1]), values[2], _aware_datetime(values[3])


def _require_key(values: tuple[str, ...], *, arity: int) -> None:
    if len(values) != arity:
        raise ValueError


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise ValueError
    return parsed


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _required_timestamp(value: datetime) -> str:
    return value.isoformat()


def _sql_key(*values: object) -> Any:
    return tuple_(*(literal(value) for value in values))


def _fingerprint(*, actor_id: int, export_format: ReadingExportFormat) -> str:
    return f"actor={actor_id};format={export_format.value}"


def _effective_page_detail_cutoff(*, exported_at: datetime, now: datetime) -> datetime:
    return max(
        exported_at - _PAGE_DETAIL_RETENTION,
        now - _PAGE_DETAIL_RETENTION,
    )


__all__ = ["ReadingLedgerExporter"]
