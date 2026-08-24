"""Bounded database-side aggregates shared by reading insight projections."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.orm import Session

from app.modules.reading_activity.application.contracts import (
    ReadingSummaryResponse,
    ReadingTrendPointResponse,
)

MAX_READING_TREND_POINTS = 3_660


def reading_summary_from_hour_source(
    db: Session,
    *,
    hour_source: Any,
    time_zone: str,
    substantive_pages: int | None,
    page_count: int | None,
) -> ReadingSummaryResponse:
    """Aggregate an arbitrary normalized hour SELECT without materializing rows."""

    source = hour_source.subquery()
    local_day = cast(func.timezone(time_zone, source.c.bucket_start), Date)
    row = db.execute(
        select(
            func.coalesce(func.sum(source.c.active_ms), 0),
            func.coalesce(func.sum(source.c.visible_ms), 0),
            func.coalesce(func.sum(source.c.session_count), 0),
            func.count(
                func.distinct(case((source.c.active_ms > 0, local_day), else_=None))
            ),
        ).select_from(source)
    ).one()
    return ReadingSummaryResponse(
        active_ms=int(row[0]),
        visible_ms=int(row[1]),
        session_count=int(row[2]),
        active_days=int(row[3]),
        substantive_pages=substantive_pages,
        coverage_percent=(
            min(100.0, substantive_pages * 100.0 / page_count)
            if substantive_pages is not None and page_count
            else None
        ),
    )


def reading_trend_from_hour_source(
    db: Session,
    *,
    hour_source: Any,
    time_zone: str,
) -> list[ReadingTrendPointResponse]:
    """Return at most ten years of daily points, ordered oldest to newest."""

    source = hour_source.subquery()
    local_day = cast(func.timezone(time_zone, source.c.bucket_start), Date).label(
        "local_day"
    )
    rows = db.execute(
        select(
            local_day,
            func.sum(source.c.active_ms),
            func.sum(source.c.visible_ms),
            func.sum(source.c.session_count),
        )
        .select_from(source)
        .group_by(local_day)
        .order_by(local_day.desc())
        .limit(MAX_READING_TREND_POINTS)
    ).all()
    return [
        ReadingTrendPointResponse(
            date=day,
            active_ms=int(active_ms or 0),
            visible_ms=int(visible_ms or 0),
            session_count=int(session_count or 0),
        )
        for day, active_ms, visible_ms, session_count in reversed(rows)
    ]


def substantive_page_count(
    db: Session,
    *,
    model: Any,
    filters: list[Any],
    substantive_threshold_ms: int,
) -> int:
    """Count substantive page rows without loading the heatmap."""

    value = db.scalar(
        select(func.count())
        .select_from(model)
        .where(*filters, model.active_ms >= substantive_threshold_ms)
    )
    return int(value or 0)


__all__ = [
    "MAX_READING_TREND_POINTS",
    "substantive_page_count",
    "reading_summary_from_hour_source",
    "reading_trend_from_hour_source",
]
