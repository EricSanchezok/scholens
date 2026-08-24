"""Bounded SQL projections used by project research-activity insights."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Date, case, cast, func, select, union_all

from app.modules.papers.infrastructure.models import Document
from app.modules.projects.infrastructure.models import ProjectCollaborator, ProjectPaper
from app.modules.reading_activity.domain import (
    ACTIVE_READING_DEFINITION_VERSION,
    ANONYMOUS_PROJECT_CONTRIBUTOR_MINIMUM,
    SUBSTANTIVE_PAGE_ACTIVE_MS,
)
from app.modules.reading_activity.infrastructure.insight_aggregates import (
    MAX_READING_TREND_POINTS,
)
from app.modules.reading_activity.infrastructure.models import (
    ReadingProjectHourRollup,
    ReadingProjectPageRollup,
    ReadingSession,
    ReadingSessionHour,
)
from app.modules.reading_activity.infrastructure.shared import (
    _created_since,
    _maximum_datetime,
)
from app.modules.research.infrastructure.models import (
    AnnotationComment,
    AnnotationThread,
    ResearchItem,
)
from app.shared.domain.enums import ResearchItemKind


def project_mine_hour_source(
    *,
    actor_id: int,
    project_id: UUID,
    document_ids: Any,
    start: datetime | None,
    end: datetime,
) -> Any:
    filters = [
        ReadingSession.user_id == actor_id,
        ReadingSession.project_id == project_id,
        ReadingSession.document_id.in_(document_ids),
        ReadingSession.metric_definition_version == ACTIVE_READING_DEFINITION_VERSION,
        ReadingSessionHour.metric_definition_version
        == ACTIVE_READING_DEFINITION_VERSION,
        ReadingSessionHour.bucket_start <= end,
    ]
    if start is not None:
        filters.append(ReadingSessionHour.bucket_start >= start)
    return (
        select(
            ReadingSessionHour.bucket_start.label("bucket_start"),
            ReadingSessionHour.active_ms.label("active_ms"),
            ReadingSessionHour.visible_ms.label("visible_ms"),
            ReadingSessionHour.session_count.label("session_count"),
        )
        .join(ReadingSession, ReadingSession.id == ReadingSessionHour.session_id)
        .where(*filters)
    )


def project_page_total(db: Any, *, project_id: UUID) -> int | None:
    total, known, page_total = db.execute(
        select(
            func.count(ProjectPaper.id),
            func.count(Document.page_count),
            func.coalesce(func.sum(Document.page_count), 0),
        )
        .join(Document, Document.id == ProjectPaper.document_id)
        .where(ProjectPaper.project_id == project_id)
    ).one()
    return complete_page_total_from_counts(
        total=int(total),
        known=int(known),
        page_total=int(page_total),
    )


def complete_page_total_from_counts(
    *, total: int, known: int, page_total: int
) -> int | None:
    return page_total if total > 0 and total == known else None


def project_papers_for_insights_statement(
    *,
    project_id: UUID,
    actor_id: int,
    reading_start: datetime | None,
    reading_end: datetime,
    fact_start: datetime | None,
) -> Any:
    session_filters = [
        ReadingSession.user_id == actor_id,
        ReadingSession.project_id == project_id,
        ReadingSession.document_id == ProjectPaper.document_id,
        ReadingSession.metric_definition_version == ACTIVE_READING_DEFINITION_VERSION,
        ReadingSessionHour.metric_definition_version
        == ACTIVE_READING_DEFINITION_VERSION,
        ReadingSessionHour.bucket_start <= reading_end,
    ]
    if reading_start is not None:
        session_filters.append(ReadingSessionHour.bucket_start >= reading_start)
    reading_at = (
        select(func.max(ReadingSessionHour.bucket_start))
        .join(ReadingSession, ReadingSession.id == ReadingSessionHour.session_id)
        .where(*session_filters)
        .correlate(ProjectPaper)
        .scalar_subquery()
    )
    annotation_filters = [
        ResearchItem.audience_project_id == project_id,
        ResearchItem.target_document_id == ProjectPaper.document_id,
        ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
    ]
    comment_filters = [
        ResearchItem.audience_project_id == project_id,
        ResearchItem.target_document_id == ProjectPaper.document_id,
    ]
    if fact_start is not None:
        annotation_filters.append(ResearchItem.created_at >= fact_start)
        comment_filters.append(AnnotationComment.created_at >= fact_start)
    annotation_at = (
        select(func.max(ResearchItem.updated_at))
        .where(*annotation_filters)
        .correlate(ProjectPaper)
        .scalar_subquery()
    )
    comment_at = (
        select(func.max(AnnotationComment.updated_at))
        .join(ResearchItem, ResearchItem.id == AnnotationComment.thread_id)
        .where(*comment_filters)
        .correlate(ProjectPaper)
        .scalar_subquery()
    )
    paper_at = (
        ProjectPaper.created_at
        if fact_start is None
        else case(
            (ProjectPaper.created_at >= fact_start, ProjectPaper.created_at),
            else_=None,
        )
    )
    last_activity = func.greatest(paper_at, reading_at, annotation_at, comment_at)
    return (
        select(ProjectPaper)
        .where(ProjectPaper.project_id == project_id)
        .order_by(last_activity.desc().nullslast(), ProjectPaper.document_id)
        .limit(100)
    )


def project_mine_papers_with_activity_statement(
    *,
    actor_id: int,
    project_id: UUID,
    document_ids: Any,
    start: datetime | None,
    end: datetime,
) -> Any:
    papers = (
        select(ReadingSession.document_id)
        .join(ReadingSessionHour, ReadingSessionHour.session_id == ReadingSession.id)
        .where(
            ReadingSession.user_id == actor_id,
            ReadingSession.project_id == project_id,
            ReadingSession.document_id.in_(document_ids),
            ReadingSession.metric_definition_version
            == ACTIVE_READING_DEFINITION_VERSION,
            ReadingSessionHour.metric_definition_version
            == ACTIVE_READING_DEFINITION_VERSION,
            ReadingSessionHour.bucket_start <= end,
            *((ReadingSessionHour.bucket_start >= start,) if start else ()),
        )
        .group_by(ReadingSession.document_id)
        .having(func.sum(ReadingSessionHour.active_ms) > 0)
        .subquery()
    )
    return select(func.count()).select_from(papers)


def canonical_project_actor_count_statement(
    *, project_id: UUID, fact_start: datetime | None
) -> Any:
    collaborators = select(ProjectCollaborator.user_id.label("actor_id")).where(
        ProjectCollaborator.project_id == project_id,
        *(_created_since(ProjectCollaborator.joined_at, fact_start)),
    )
    paper_adders = select(ProjectPaper.added_by_id.label("actor_id")).where(
        ProjectPaper.project_id == project_id,
        ProjectPaper.added_by_id.is_not(None),
        *(_created_since(ProjectPaper.created_at, fact_start)),
    )
    research_creators = select(ResearchItem.created_by_id.label("actor_id")).where(
        ResearchItem.audience_project_id == project_id,
        ResearchItem.created_by_id.is_not(None),
        *(_created_since(ResearchItem.created_at, fact_start)),
    )
    commenters = (
        select(AnnotationComment.created_by_id.label("actor_id"))
        .join(ResearchItem, ResearchItem.id == AnnotationComment.thread_id)
        .where(
            ResearchItem.audience_project_id == project_id,
            AnnotationComment.created_by_id.is_not(None),
            *(_created_since(AnnotationComment.created_at, fact_start)),
        )
    )
    resolvers = (
        select(AnnotationThread.resolved_by_id.label("actor_id"))
        .join(ResearchItem, ResearchItem.id == AnnotationThread.research_item_id)
        .where(
            ResearchItem.audience_project_id == project_id,
            AnnotationThread.resolved_by_id.is_not(None),
            AnnotationThread.resolved_at.is_not(None),
            *(_created_since(AnnotationThread.resolved_at, fact_start)),
        )
    )
    actors = collaborators.union(
        paper_adders,
        research_creators,
        commenters,
        resolvers,
    ).subquery()
    return select(func.count()).select_from(actors)


def public_team_reading_since_statement(
    *, project_id: UUID, document_ids: Any, end: datetime
) -> Any:
    day = utc_day(ReadingProjectHourRollup.bucket_start).label("day")
    public_days = (
        select(day)
        .where(
            ReadingProjectHourRollup.project_id == project_id,
            ReadingProjectHourRollup.document_id.in_(document_ids),
            ReadingProjectHourRollup.metric_definition_version
            == ACTIVE_READING_DEFINITION_VERSION,
            ReadingProjectHourRollup.bucket_start <= end,
            ReadingProjectHourRollup.active_ms > 0,
        )
        .group_by(day)
        .having(
            func.count(func.distinct(ReadingProjectHourRollup.user_id))
            >= ANONYMOUS_PROJECT_CONTRIBUTOR_MINIMUM
        )
        .subquery()
    )
    return select(func.min(public_days.c.day))


def utc_day(column: Any) -> Any:
    return cast(func.timezone("UTC", column), Date)


def project_mine_trend_statement(
    *,
    project_id: UUID,
    actor_id: int,
    document_ids: Any,
    start: datetime | None,
    end: datetime,
) -> Any:
    day = utc_day(ReadingSessionHour.bucket_start).label("day")
    return (
        select(day, func.sum(ReadingSessionHour.active_ms))
        .join(ReadingSession, ReadingSession.id == ReadingSessionHour.session_id)
        .where(
            ReadingSession.project_id == project_id,
            ReadingSession.user_id == actor_id,
            ReadingSession.document_id.in_(document_ids),
            ReadingSession.metric_definition_version
            == ACTIVE_READING_DEFINITION_VERSION,
            ReadingSessionHour.metric_definition_version
            == ACTIVE_READING_DEFINITION_VERSION,
            ReadingSessionHour.bucket_start <= end,
            *((ReadingSessionHour.bucket_start >= start,) if start else ()),
        )
        .group_by(day)
        .order_by(day.desc())
        .limit(MAX_READING_TREND_POINTS)
    )


def project_team_trend_statement(
    *,
    project_id: UUID,
    document_ids: Any,
    start: datetime | None,
    end: datetime,
) -> Any:
    day = utc_day(ReadingProjectHourRollup.bucket_start).label("day")
    contributors = func.count(
        func.distinct(
            case(
                (
                    ReadingProjectHourRollup.active_ms > 0,
                    ReadingProjectHourRollup.user_id,
                ),
                else_=None,
            )
        )
    )
    return (
        select(day, func.sum(ReadingProjectHourRollup.active_ms))
        .where(
            ReadingProjectHourRollup.project_id == project_id,
            ReadingProjectHourRollup.document_id.in_(document_ids),
            ReadingProjectHourRollup.metric_definition_version
            == ACTIVE_READING_DEFINITION_VERSION,
            ReadingProjectHourRollup.bucket_start <= end,
            *((ReadingProjectHourRollup.bucket_start >= start,) if start else ()),
        )
        .group_by(day)
        .having(contributors >= ANONYMOUS_PROJECT_CONTRIBUTOR_MINIMUM)
        .order_by(day.desc())
        .limit(MAX_READING_TREND_POINTS)
    )


def project_shared_trend_statement(
    *, project_id: UUID, fact_start: datetime | None
) -> Any:
    collaborator_events = select(
        ProjectCollaborator.joined_at.label("occurred_at")
    ).where(
        ProjectCollaborator.project_id == project_id,
        *(_created_since(ProjectCollaborator.joined_at, fact_start)),
    )
    paper_events = select(ProjectPaper.created_at.label("occurred_at")).where(
        ProjectPaper.project_id == project_id,
        *(_created_since(ProjectPaper.created_at, fact_start)),
    )
    research_events = select(ResearchItem.created_at.label("occurred_at")).where(
        ResearchItem.audience_project_id == project_id,
        *(_created_since(ResearchItem.created_at, fact_start)),
    )
    comment_events = (
        select(AnnotationComment.created_at.label("occurred_at"))
        .join(ResearchItem, ResearchItem.id == AnnotationComment.thread_id)
        .where(
            ResearchItem.audience_project_id == project_id,
            *(_created_since(AnnotationComment.created_at, fact_start)),
        )
    )
    resolved_events = (
        select(AnnotationThread.resolved_at.label("occurred_at"))
        .join(ResearchItem, ResearchItem.id == AnnotationThread.research_item_id)
        .where(
            ResearchItem.audience_project_id == project_id,
            AnnotationThread.resolved_at.is_not(None),
            *(_created_since(AnnotationThread.resolved_at, fact_start)),
        )
    )
    events = union_all(
        collaborator_events,
        paper_events,
        research_events,
        comment_events,
        resolved_events,
    ).subquery()
    day = utc_day(events.c.occurred_at).label("day")
    return (
        select(day, func.count())
        .select_from(events)
        .group_by(day)
        .order_by(day.desc())
        .limit(MAX_READING_TREND_POINTS)
    )


def project_paper_last_activity_at(
    *,
    paper_created_at: datetime,
    session_timestamps: list[datetime],
    annotation_at: datetime | None,
    comment_at: datetime | None,
    start: datetime | None,
) -> datetime | None:
    return _maximum_datetime(
        paper_created_at if start is None or paper_created_at >= start else None,
        *session_timestamps,
        annotation_at,
        comment_at,
    )


def qualified_project_papers_count_statement(
    *, project_id: UUID, document_ids: Any, start: datetime | None, end: datetime
) -> Any:
    filters = [
        ReadingProjectHourRollup.project_id == project_id,
        ReadingProjectHourRollup.document_id.in_(document_ids),
        ReadingProjectHourRollup.active_ms > 0,
        ReadingProjectHourRollup.metric_definition_version
        == ACTIVE_READING_DEFINITION_VERSION,
        ReadingProjectHourRollup.bucket_start <= end,
    ]
    if start is not None:
        filters.append(ReadingProjectHourRollup.bucket_start >= start)
    qualified = (
        select(ReadingProjectHourRollup.document_id)
        .where(*filters)
        .group_by(ReadingProjectHourRollup.document_id)
        .having(
            func.count(func.distinct(ReadingProjectHourRollup.user_id))
            >= ANONYMOUS_PROJECT_CONTRIBUTOR_MINIMUM,
            func.sum(ReadingProjectHourRollup.active_ms) > 0,
        )
        .subquery()
    )
    return select(func.count()).select_from(qualified)


def qualified_project_pages_count_statement(
    *, project_id: UUID, document_ids: Any
) -> Any:
    qualified = (
        select(
            ReadingProjectPageRollup.document_id,
            ReadingProjectPageRollup.page_number,
        )
        .where(
            ReadingProjectPageRollup.project_id == project_id,
            ReadingProjectPageRollup.document_id.in_(document_ids),
            ReadingProjectPageRollup.active_ms > 0,
            ReadingProjectPageRollup.metric_definition_version
            == ACTIVE_READING_DEFINITION_VERSION,
        )
        .group_by(
            ReadingProjectPageRollup.document_id,
            ReadingProjectPageRollup.page_number,
        )
        .having(
            func.count(func.distinct(ReadingProjectPageRollup.user_id))
            >= ANONYMOUS_PROJECT_CONTRIBUTOR_MINIMUM,
            func.sum(ReadingProjectPageRollup.active_ms) >= SUBSTANTIVE_PAGE_ACTIVE_MS,
        )
        .subquery()
    )
    return select(func.count()).select_from(qualified)


__all__ = [
    "canonical_project_actor_count_statement",
    "complete_page_total_from_counts",
    "project_mine_hour_source",
    "project_mine_papers_with_activity_statement",
    "project_mine_trend_statement",
    "project_page_total",
    "project_paper_last_activity_at",
    "project_papers_for_insights_statement",
    "project_shared_trend_statement",
    "project_team_trend_statement",
    "public_team_reading_since_statement",
    "qualified_project_pages_count_statement",
    "qualified_project_papers_count_statement",
]
