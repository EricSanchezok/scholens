"""Account-level research insight projections."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Integer, cast, func, or_, select

from app.modules.conversations.infrastructure.models import Conversation
from app.modules.papers.infrastructure.access import accessible_document_condition
from app.modules.papers.infrastructure.models import Document
from app.modules.projects.infrastructure.models import Project, ProjectCollaborator
from app.modules.reading_activity.application.contracts import (
    ReadingInsightsRange,
    ReadingPageBucketResponse,
    ReadingPaperSummariesResponse,
    ReadingPaperSummaryItemResponse,
    ReadingPaperSummaryRequest,
    ResearchInsightsResponse,
    ResearchPaperBreakdownResponse,
    ResearchProjectBreakdownResponse,
)
from app.modules.reading_activity.domain import (
    ACTIVE_READING_DEFINITION_VERSION,
    SUBSTANTIVE_PAGE_ACTIVE_MS,
)
from app.modules.reading_activity.infrastructure.models import (
    ReadingSession,
    ReadingSessionHour,
    ReadingPersonalHourRollup,
    ReadingPersonalPageRollup,
)
from app.modules.reading_activity.infrastructure.insight_aggregates import (
    substantive_page_count,
    reading_summary_from_hour_source,
    reading_trend_from_hour_source,
)
from app.modules.reading_activity.infrastructure.shared import (
    ReadingActivityRepositoryBase,
    _calendar_range_start,
    _created_since,
    _hour_bucket,
    _range_start,
)
from app.modules.research.infrastructure.models import ResearchItem
from app.shared.application import Actor
from app.shared.domain.enums import ResearchItemKind


class PersonalInsightsRepository(ReadingActivityRepositoryBase):
    def paper_summaries(
        self,
        *,
        actor: Actor,
        request: ReadingPaperSummaryRequest,
    ) -> ReadingPaperSummariesResponse:
        documents = {
            document.id: document
            for document in self._db.scalars(
                select(Document).where(
                    Document.id.in_(request.document_ids),
                    accessible_document_condition(user_id=actor.id),
                )
            ).all()
        }
        duration_rows = self._db.execute(
            select(
                ReadingPersonalHourRollup.document_id,
                func.sum(ReadingPersonalHourRollup.active_ms),
                func.sum(ReadingPersonalHourRollup.visible_ms),
            )
            .where(
                ReadingPersonalHourRollup.user_id == actor.id,
                ReadingPersonalHourRollup.document_id.in_(documents),
                ReadingPersonalHourRollup.metric_definition_version
                == ACTIVE_READING_DEFINITION_VERSION,
                ReadingPersonalHourRollup.bucket_start
                <= _hour_bucket(self._clock.now()),
            )
            .group_by(ReadingPersonalHourRollup.document_id)
        ).all()
        durations = {
            document_id: (int(active_ms or 0), int(visible_ms or 0))
            for document_id, active_ms, visible_ms in duration_rows
        }
        page_filters = (
            ReadingPersonalPageRollup.user_id == actor.id,
            ReadingPersonalPageRollup.document_id.in_(documents),
            ReadingPersonalPageRollup.metric_definition_version
            == ACTIVE_READING_DEFINITION_VERSION,
        )
        page_stat_rows = self._db.execute(
            select(
                ReadingPersonalPageRollup.document_id,
                func.max(ReadingPersonalPageRollup.page_number),
                func.count().filter(
                    ReadingPersonalPageRollup.active_ms >= SUBSTANTIVE_PAGE_ACTIVE_MS
                ),
            )
            .where(*page_filters)
            .group_by(ReadingPersonalPageRollup.document_id)
        ).all()
        page_stats = {
            document_id: (int(maximum_page), int(substantive_pages))
            for document_id, maximum_page, substantive_pages in page_stat_rows
        }
        maxima = (
            select(
                ReadingPersonalPageRollup.document_id.label("document_id"),
                func.max(ReadingPersonalPageRollup.page_number).label("maximum_page"),
            )
            .where(*page_filters)
            .group_by(ReadingPersonalPageRollup.document_id)
            .subquery()
        )
        maximum_page = func.coalesce(Document.page_count, maxima.c.maximum_page)
        bucket_count = func.least(20, maximum_page)
        bucket_index = cast(
            func.floor(
                (ReadingPersonalPageRollup.page_number - 1)
                * bucket_count
                * 1.0
                / maximum_page
            ),
            Integer,
        ).label("bucket_index")
        bucket_rows = self._db.execute(
            select(
                ReadingPersonalPageRollup.document_id,
                bucket_index,
                func.sum(ReadingPersonalPageRollup.active_ms),
            )
            .join(
                maxima,
                maxima.c.document_id == ReadingPersonalPageRollup.document_id,
            )
            .join(Document, Document.id == ReadingPersonalPageRollup.document_id)
            .where(
                ReadingPersonalPageRollup.user_id == actor.id,
                ReadingPersonalPageRollup.document_id.in_(documents),
                ReadingPersonalPageRollup.metric_definition_version
                == ACTIVE_READING_DEFINITION_VERSION,
            )
            .group_by(ReadingPersonalPageRollup.document_id, bucket_index)
        ).all()
        buckets: dict[UUID, dict[int, int]] = defaultdict(dict)
        for document_id, index, active_ms in bucket_rows:
            buckets[document_id][int(index)] = int(active_ms or 0)
        items: list[ReadingPaperSummaryItemResponse] = []
        for document_id in request.document_ids:
            document = documents.get(document_id)
            if document is None:
                continue
            active_ms, visible_ms = durations.get(document_id, (0, 0))
            observed_maximum, substantive = page_stats.get(document_id, (0, 0))
            items.append(
                ReadingPaperSummaryItemResponse(
                    document_id=document_id,
                    active_ms=active_ms,
                    visible_ms=visible_ms,
                    coverage_percent=(
                        min(100.0, substantive * 100.0 / document.page_count)
                        if document.page_count
                        else None
                    ),
                    page_buckets=_page_buckets(
                        maximum_page=document.page_count or observed_maximum,
                        bucket_values=buckets.get(document_id, {}),
                    ),
                )
            )
        return ReadingPaperSummariesResponse(items=items)

    def research_insights(
        self,
        *,
        actor: Actor,
        insight_range: ReadingInsightsRange,
        time_zone: str,
    ) -> ResearchInsightsResponse:
        now = self._clock.now()
        start = _range_start(insight_range, now, time_zone=time_zone)
        fact_start = _calendar_range_start(
            insight_range,
            now,
            time_zone=time_zone,
        )
        end = _hour_bucket(now)
        hour_source = _personal_hour_source(
            user_id=actor.id,
            start=start,
            end=end,
        )
        substantive_pages: int | None = None
        if insight_range is ReadingInsightsRange.ALL:
            substantive_pages = substantive_page_count(
                self._db,
                model=ReadingPersonalPageRollup,
                filters=[
                    ReadingPersonalPageRollup.user_id == actor.id,
                    ReadingPersonalPageRollup.metric_definition_version
                    == ACTIVE_READING_DEFINITION_VERSION,
                ],
                substantive_threshold_ms=SUBSTANTIVE_PAGE_ACTIVE_MS,
            )
        summary = reading_summary_from_hour_source(
            self._db,
            hour_source=hour_source,
            substantive_pages=substantive_pages,
            page_count=None,
            time_zone=time_zone,
        )
        annotation_count = self._count(
            select(func.count(ResearchItem.id)).where(
                ResearchItem.created_by_id == actor.id,
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                *(_created_since(ResearchItem.created_at, fact_start)),
            )
        )
        conversation_count = self._count(
            select(func.count(Conversation.id)).where(
                Conversation.user_id == actor.id,
                *(_created_since(Conversation.created_at, fact_start)),
            )
        )
        output_count = self._count(
            select(func.count(ResearchItem.id)).where(
                ResearchItem.created_by_id == actor.id,
                ResearchItem.kind != ResearchItemKind.ANNOTATION_THREAD.value,
                *(_created_since(ResearchItem.created_at, fact_start)),
            )
        )
        projects = self._research_project_breakdown(
            actor=actor,
            start=start,
            end=end,
        )
        papers = self._research_paper_breakdown(
            actor=actor,
            start=start,
            end=end,
        )
        earliest = self._reading_data_since(user_id=actor.id)
        return ResearchInsightsResponse(
            reading_data_since=earliest,
            activity_history_complete_since=(self._activity_history_complete_since()),
            time_zone=time_zone,
            range=insight_range,
            summary=summary,
            trend=reading_trend_from_hour_source(
                self._db,
                hour_source=hour_source,
                time_zone=time_zone,
            ),
            projects=projects,
            top_papers=papers,
            papers_with_activity=self._count(
                _papers_with_activity_count_statement(
                    user_id=actor.id,
                    start=start,
                    end=end,
                )
            ),
            annotation_count=annotation_count,
            conversation_count=conversation_count,
            output_count=output_count,
        )

    def _research_project_breakdown(
        self,
        *,
        actor: Actor,
        start: datetime | None,
        end: datetime,
    ) -> list[ResearchProjectBreakdownResponse]:
        rows = self._db.execute(
            _project_breakdown_hours_statement(
                user_id=actor.id,
                start=start,
                end=end,
            )
        ).all()
        return [
            ResearchProjectBreakdownResponse(
                project_id=project_id,
                title=title,
                active_ms=int(active_ms or 0),
                session_count=int(session_count or 0),
            )
            for project_id, title, active_ms, session_count in rows
        ]

    def _research_paper_breakdown(
        self,
        *,
        actor: Actor,
        start: datetime | None,
        end: datetime,
    ) -> list[ResearchPaperBreakdownResponse]:
        rows = self._db.execute(
            _paper_breakdown_hours_statement(
                user_id=actor.id,
                start=start,
                end=end,
            )
        ).all()
        return [
            ResearchPaperBreakdownResponse(
                document_id=document_id,
                title=title,
                active_ms=int(active_ms or 0),
                session_count=int(session_count or 0),
                last_read_at=last_read_at,
            )
            for document_id, title, active_ms, session_count, last_read_at in rows
        ]


def _page_buckets(
    *,
    maximum_page: int,
    bucket_values: dict[int, int],
) -> list[ReadingPageBucketResponse]:
    if maximum_page == 0:
        return []
    bucket_count = min(20, maximum_page)
    response: list[ReadingPageBucketResponse] = []
    for index in range(bucket_count):
        start = (index * maximum_page + bucket_count - 1) // bucket_count + 1
        end = ((index + 1) * maximum_page + bucket_count - 1) // bucket_count
        response.append(
            ReadingPageBucketResponse(
                start_page=start,
                end_page=end,
                active_ms=bucket_values.get(index, 0),
            )
        )
    return response


def _project_breakdown_hours_statement(
    *, user_id: int, start: datetime | None, end: datetime
) -> Any:
    filters = [
        ReadingSession.user_id == user_id,
        ReadingSession.project_id.is_not(None),
        ReadingSession.metric_definition_version == ACTIVE_READING_DEFINITION_VERSION,
        ReadingSessionHour.metric_definition_version
        == ACTIVE_READING_DEFINITION_VERSION,
        ReadingSessionHour.bucket_start <= end,
    ]
    if start is not None:
        filters.append(ReadingSessionHour.bucket_start >= start)
    active_total = func.sum(ReadingSessionHour.active_ms)
    return (
        select(
            ReadingSession.project_id,
            Project.title,
            active_total,
            func.sum(ReadingSessionHour.session_count),
        )
        .join(
            ReadingSessionHour,
            ReadingSessionHour.session_id == ReadingSession.id,
        )
        .join(Project, Project.id == ReadingSession.project_id)
        .outerjoin(
            ProjectCollaborator,
            (ProjectCollaborator.project_id == Project.id)
            & (ProjectCollaborator.user_id == user_id),
        )
        .where(*filters)
        .where(
            or_(
                Project.owner_id == user_id,
                ProjectCollaborator.user_id == user_id,
            )
        )
        .group_by(ReadingSession.project_id, Project.title)
        .having(active_total > 0)
        .order_by(active_total.desc(), ReadingSession.project_id)
        .limit(10)
    )


def _paper_breakdown_hours_statement(
    *, user_id: int, start: datetime | None, end: datetime
) -> Any:
    filters = [
        ReadingPersonalHourRollup.user_id == user_id,
        ReadingPersonalHourRollup.metric_definition_version
        == ACTIVE_READING_DEFINITION_VERSION,
        ReadingPersonalHourRollup.bucket_start <= end,
    ]
    if start is not None:
        filters.append(ReadingPersonalHourRollup.bucket_start >= start)
    active_total = func.sum(ReadingPersonalHourRollup.active_ms)
    return (
        select(
            ReadingPersonalHourRollup.document_id,
            Document.title,
            active_total,
            func.sum(ReadingPersonalHourRollup.session_count),
            func.max(ReadingPersonalHourRollup.bucket_start),
        )
        .join(Document, Document.id == ReadingPersonalHourRollup.document_id)
        .where(
            *filters,
            accessible_document_condition(user_id=user_id),
        )
        .group_by(ReadingPersonalHourRollup.document_id, Document.title)
        .having(active_total > 0)
        .order_by(active_total.desc(), ReadingPersonalHourRollup.document_id)
        .limit(10)
    )


def _personal_hour_source(
    *, user_id: int, start: datetime | None, end: datetime
) -> Any:
    filters = [
        ReadingPersonalHourRollup.user_id == user_id,
        ReadingPersonalHourRollup.metric_definition_version
        == ACTIVE_READING_DEFINITION_VERSION,
        ReadingPersonalHourRollup.bucket_start <= end,
    ]
    if start is not None:
        filters.append(ReadingPersonalHourRollup.bucket_start >= start)
    return select(
        ReadingPersonalHourRollup.bucket_start.label("bucket_start"),
        ReadingPersonalHourRollup.active_ms.label("active_ms"),
        ReadingPersonalHourRollup.visible_ms.label("visible_ms"),
        ReadingPersonalHourRollup.session_count.label("session_count"),
    ).where(*filters)


def _papers_with_activity_count_statement(
    *, user_id: int, start: datetime | None, end: datetime
) -> Any:
    filters = [
        ReadingPersonalHourRollup.user_id == user_id,
        ReadingPersonalHourRollup.metric_definition_version
        == ACTIVE_READING_DEFINITION_VERSION,
        ReadingPersonalHourRollup.bucket_start <= end,
    ]
    if start is not None:
        filters.append(ReadingPersonalHourRollup.bucket_start >= start)
    papers = (
        select(ReadingPersonalHourRollup.document_id)
        .where(*filters)
        .group_by(ReadingPersonalHourRollup.document_id)
        .having(func.sum(ReadingPersonalHourRollup.active_ms) > 0)
        .subquery()
    )
    return select(func.count()).select_from(papers)
