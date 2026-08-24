"""Project insight, privacy-threshold, and canonical activity projections."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.modules.conversations.infrastructure.models import Conversation
from app.modules.papers.infrastructure.models import Document
from app.modules.projects.infrastructure.access import require_project_access
from app.modules.projects.infrastructure.models import (
    ProjectPaper,
)
from app.modules.reading_activity.application.contracts import (
    ProjectInsightsResponse,
    ProjectMineInsightsResponse,
    ProjectPaperInsightResponse,
    ProjectReadingTrendPointResponse,
    ProjectTeamInsightsResponse,
    ReadingInsightsRange,
)
from app.modules.reading_activity.domain import (
    ACTIVE_READING_DEFINITION_VERSION,
    ANONYMOUS_PROJECT_CONTRIBUTOR_MINIMUM,
    SUBSTANTIVE_PAGE_ACTIVE_MS,
    round_project_reading_ms,
)
from app.modules.reading_activity.infrastructure.models import (
    ReadingProjectHourRollup,
    ReadingProjectPersonalPageRollup,
    ReadingSession,
    ReadingSessionHour,
)
from app.modules.reading_activity.infrastructure.insight_aggregates import (
    reading_summary_from_hour_source,
    substantive_page_count,
)
from app.bootstrap.adapters.reading_activity_project_insight_statements import (
    canonical_project_actor_count_statement as _canonical_project_actor_count_statement,
    project_mine_hour_source as _project_mine_hour_source,
    project_mine_papers_with_activity_statement as _project_mine_papers_with_activity_statement,
    project_mine_trend_statement as _project_mine_trend_statement,
    project_page_total as _project_page_total,
    project_paper_last_activity_at as _project_paper_last_activity_at,
    project_papers_for_insights_statement as _project_papers_for_insights_statement,
    project_shared_trend_statement as _project_shared_trend_statement,
    project_team_trend_statement as _project_team_trend_statement,
    public_team_reading_since_statement as _public_team_reading_since_statement,
    qualified_project_pages_count_statement as _qualified_project_pages_count_statement,
    qualified_project_papers_count_statement as _qualified_project_papers_count_statement,
)
from app.modules.reading_activity.infrastructure.shared import (
    ReadingActivityRepositoryBase,
    _calendar_range_start,
    _created_since,
    _hour_bucket,
    _maximum_datetime,
    _minimum_datetime,
    _range_start,
)
from app.modules.research.infrastructure.models import (
    AnnotationComment,
    AnnotationThread,
    ResearchItem,
)
from app.shared.application import Actor
from app.shared.domain.enums import ResearchItemKind


class ProjectInsightsRepository(ReadingActivityRepositoryBase):
    def project_insights(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        insight_range: ReadingInsightsRange,
    ) -> ProjectInsightsResponse:
        time_zone = "UTC"
        access = require_project_access(
            self._db,
            project_id=project_id,
            user_id=actor.id,
        )
        now = self._clock.now()
        start = _range_start(insight_range, now, time_zone=time_zone)
        fact_start = _calendar_range_start(
            insight_range,
            now,
            time_zone=time_zone,
        )
        end = _hour_bucket(now)
        current_document_ids = select(ProjectPaper.document_id).where(
            ProjectPaper.project_id == project_id
        )
        papers_total_count = self._count(
            select(func.count(ProjectPaper.id)).where(
                ProjectPaper.project_id == project_id
            )
        )
        project_papers = list(
            self._db.scalars(
                _project_papers_for_insights_statement(
                    project_id=project_id,
                    actor_id=actor.id,
                    reading_start=start,
                    reading_end=end,
                    fact_start=fact_start,
                )
            ).all()
        )
        project_documents = {
            document.id: document
            for document in self._db.scalars(
                select(Document).where(
                    Document.id.in_([paper.document_id for paper in project_papers])
                )
            ).all()
        }
        mine_hour_source = _project_mine_hour_source(
            actor_id=actor.id,
            project_id=project_id,
            document_ids=current_document_ids,
            start=start,
            end=end,
        )
        page_total = _project_page_total(self._db, project_id=project_id)
        substantive_pages: int | None = None
        if insight_range is ReadingInsightsRange.ALL:
            substantive_pages = substantive_page_count(
                self._db,
                model=ReadingProjectPersonalPageRollup,
                filters=[
                    ReadingProjectPersonalPageRollup.project_id == project_id,
                    ReadingProjectPersonalPageRollup.user_id == actor.id,
                    ReadingProjectPersonalPageRollup.document_id.in_(
                        current_document_ids
                    ),
                    ReadingProjectPersonalPageRollup.metric_definition_version
                    == ACTIVE_READING_DEFINITION_VERSION,
                ],
                substantive_threshold_ms=SUBSTANTIVE_PAGE_ACTIVE_MS,
            )
        mine_summary = reading_summary_from_hour_source(
            self._db,
            hour_source=mine_hour_source,
            substantive_pages=substantive_pages,
            page_count=page_total,
            time_zone=time_zone,
        )
        private_conversation_count = self._count(
            select(func.count(Conversation.id)).where(
                Conversation.project_id == project_id,
                Conversation.user_id == actor.id,
                *(_created_since(Conversation.created_at, fact_start)),
            )
        )
        actor_annotation_count = self._count(
            select(func.count(ResearchItem.id)).where(
                ResearchItem.audience_project_id == project_id,
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                ResearchItem.created_by_id == actor.id,
                *(_created_since(ResearchItem.created_at, fact_start)),
            )
        )
        team = self._project_team_insights(
            project_id=project_id,
            document_ids=current_document_ids,
            start=start,
            end=end,
            fact_start=fact_start,
        )
        papers = self._project_paper_insights(
            actor=actor,
            project_id=project_id,
            project_papers=project_papers,
            start=start,
            end=end,
            fact_start=fact_start,
            documents=project_documents,
        )
        earliest = self._db.scalar(
            select(func.min(ReadingSession.started_at)).where(
                ReadingSession.user_id == actor.id,
                ReadingSession.project_id == project_id,
                ReadingSession.document_id.in_(current_document_ids),
                ReadingSession.metric_definition_version
                == ACTIVE_READING_DEFINITION_VERSION,
                ReadingSession.started_at <= now,
            )
        )
        public_team_day = self._db.scalar(
            _public_team_reading_since_statement(
                project_id=project_id,
                document_ids=current_document_ids,
                end=end,
            )
        )
        public_team_since = (
            datetime.combine(
                public_team_day,
                datetime.min.time(),
                tzinfo=timezone.utc,
            )
            if public_team_day is not None
            else None
        )
        reading_data_since = _minimum_datetime(earliest, public_team_since)
        complete_since = _maximum_datetime(
            self._activity_history_complete_since(),
            access.project.created_at,
        )
        return ProjectInsightsResponse(
            project_id=project_id,
            reading_data_since=reading_data_since,
            activity_history_complete_since=complete_since,
            time_zone=time_zone,
            range=insight_range,
            mine=ProjectMineInsightsResponse(
                reading=mine_summary,
                papers_with_activity=self._count(
                    _project_mine_papers_with_activity_statement(
                        actor_id=actor.id,
                        project_id=project_id,
                        document_ids=current_document_ids,
                        start=start,
                        end=end,
                    )
                ),
                private_conversation_count=private_conversation_count,
                annotation_count=actor_annotation_count,
            ),
            team=team,
            trend=self._project_trend(
                project_id=project_id,
                actor_id=actor.id,
                document_ids=current_document_ids,
                start=start,
                end=end,
                fact_start=fact_start,
            ),
            papers=papers,
            papers_total_count=papers_total_count,
        )

    def _project_team_insights(
        self,
        *,
        project_id: UUID,
        document_ids: Any,
        start: datetime | None,
        end: datetime,
        fact_start: datetime | None,
    ) -> ProjectTeamInsightsResponse:
        filters = [
            ReadingProjectHourRollup.project_id == project_id,
            ReadingProjectHourRollup.document_id.in_(document_ids),
            ReadingProjectHourRollup.metric_definition_version
            == ACTIVE_READING_DEFINITION_VERSION,
            ReadingProjectHourRollup.bucket_start <= end,
        ]
        if start is not None:
            filters.append(ReadingProjectHourRollup.bucket_start >= start)
        eligible_users = (
            select(
                ReadingProjectHourRollup.user_id,
                func.sum(ReadingProjectHourRollup.active_ms).label("active_ms"),
                func.sum(ReadingProjectHourRollup.visible_ms).label("visible_ms"),
            )
            .where(*filters)
            .group_by(ReadingProjectHourRollup.user_id)
            .having(func.sum(ReadingProjectHourRollup.active_ms) > 0)
            .subquery()
        )
        contributor_count, active_ms, visible_ms = self._db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(eligible_users.c.active_ms), 0),
                func.coalesce(func.sum(eligible_users.c.visible_ms), 0),
            ).select_from(eligible_users)
        ).one()
        available = int(contributor_count) >= ANONYMOUS_PROJECT_CONTRIBUTOR_MINIMUM
        active_ms = int(active_ms)
        visible_ms = int(visible_ms)
        qualified_papers = self._count(
            _qualified_project_papers_count_statement(
                project_id=project_id,
                document_ids=document_ids,
                start=start,
                end=end,
            )
        )
        substantive_pages = None
        if start is None:
            substantive_pages = self._count(
                _qualified_project_pages_count_statement(
                    project_id=project_id,
                    document_ids=document_ids,
                )
            )
        papers_added = self._count(
            select(func.count(ProjectPaper.id)).where(
                ProjectPaper.project_id == project_id,
                *(_created_since(ProjectPaper.created_at, fact_start)),
            )
        )
        shared_annotations = self._count(
            select(func.count(ResearchItem.id)).where(
                ResearchItem.audience_project_id == project_id,
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                *(_created_since(ResearchItem.created_at, fact_start)),
            )
        )
        outputs = self._count(
            select(func.count(ResearchItem.id)).where(
                ResearchItem.audience_project_id == project_id,
                ResearchItem.kind != ResearchItemKind.ANNOTATION_THREAD.value,
                *(_created_since(ResearchItem.created_at, fact_start)),
            )
        )
        project_research = select(ResearchItem.id).where(
            ResearchItem.audience_project_id == project_id
        )
        discussion_message_count = self._count(
            select(func.count(AnnotationComment.id)).where(
                AnnotationComment.thread_id.in_(project_research),
                *(_created_since(AnnotationComment.created_at, fact_start)),
            )
        )
        resolved_filters: list[Any] = [
            AnnotationThread.research_item_id.in_(project_research),
            AnnotationThread.resolved_at.is_not(None),
        ]
        if fact_start is not None:
            resolved_filters.append(AnnotationThread.resolved_at >= fact_start)
        resolved = self._count(
            select(func.count(AnnotationThread.research_item_id)).where(
                *resolved_filters
            )
        )
        active_collaborators = self._count(
            _canonical_project_actor_count_statement(
                project_id=project_id,
                fact_start=fact_start,
            )
        )
        return ProjectTeamInsightsResponse(
            anonymous_reading_available=available,
            active_ms=round_project_reading_ms(active_ms) if available else None,
            visible_ms=(round_project_reading_ms(visible_ms) if available else None),
            papers_with_activity=qualified_papers if available else None,
            substantive_pages=(substantive_pages if available else None),
            papers_added=papers_added,
            shared_annotations=shared_annotations,
            discussion_message_count=discussion_message_count,
            resolved_discussions=resolved,
            outputs=outputs,
            active_collaborators=active_collaborators,
        )

    def _project_paper_insights(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        project_papers: list[ProjectPaper],
        start: datetime | None,
        end: datetime,
        fact_start: datetime | None,
        documents: dict[UUID, Document],
    ) -> list[ProjectPaperInsightResponse]:
        document_ids = [paper.document_id for paper in project_papers]
        current_document_ids = set(document_ids)
        hour_rows = self._db.execute(
            select(
                ReadingSession.document_id,
                func.sum(ReadingSessionHour.active_ms),
                func.max(ReadingSessionHour.bucket_start),
            )
            .join(
                ReadingSessionHour,
                ReadingSessionHour.session_id == ReadingSession.id,
            )
            .where(
                ReadingSession.user_id == actor.id,
                ReadingSession.project_id == project_id,
                ReadingSession.document_id.in_(current_document_ids),
                ReadingSession.metric_definition_version
                == ACTIVE_READING_DEFINITION_VERSION,
                ReadingSessionHour.metric_definition_version
                == ACTIVE_READING_DEFINITION_VERSION,
                ReadingSessionHour.bucket_start <= end,
                *((ReadingSessionHour.bucket_start >= start,) if start else ()),
            )
            .group_by(ReadingSession.document_id)
        ).all()
        reading_by_document = {
            document_id: (int(active_ms or 0), last_bucket)
            for document_id, active_ms, last_bucket in hour_rows
        }
        substantive_by_document: dict[UUID, int] = {}
        if start is None:
            page_rows = self._db.execute(
                select(
                    ReadingProjectPersonalPageRollup.document_id,
                    func.count().filter(
                        ReadingProjectPersonalPageRollup.active_ms
                        >= SUBSTANTIVE_PAGE_ACTIVE_MS
                    ),
                )
                .where(
                    ReadingProjectPersonalPageRollup.project_id == project_id,
                    ReadingProjectPersonalPageRollup.user_id == actor.id,
                    ReadingProjectPersonalPageRollup.document_id.in_(
                        current_document_ids
                    ),
                    ReadingProjectPersonalPageRollup.metric_definition_version
                    == ACTIVE_READING_DEFINITION_VERSION,
                )
                .group_by(ReadingProjectPersonalPageRollup.document_id)
            ).all()
        else:
            page_rows = []
        for document_id, substantive_pages in page_rows:
            substantive_by_document[document_id] = int(substantive_pages or 0)
        annotation_rows = self._db.execute(
            select(
                ResearchItem.target_document_id,
                func.count(ResearchItem.id),
                func.max(ResearchItem.updated_at),
            )
            .where(
                ResearchItem.audience_project_id == project_id,
                ResearchItem.target_document_id.in_(current_document_ids),
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                *(_created_since(ResearchItem.created_at, fact_start)),
            )
            .group_by(ResearchItem.target_document_id)
        ).all()
        annotations = {
            row[0]: (int(row[1]), row[2])
            for row in annotation_rows
            if row[0] is not None
        }
        comment_rows = self._db.execute(
            select(
                ResearchItem.target_document_id,
                func.count(AnnotationComment.id),
                func.max(AnnotationComment.updated_at),
            )
            .join(ResearchItem, ResearchItem.id == AnnotationComment.thread_id)
            .where(
                ResearchItem.audience_project_id == project_id,
                ResearchItem.target_document_id.in_(current_document_ids),
                *(_created_since(AnnotationComment.created_at, fact_start)),
            )
            .group_by(ResearchItem.target_document_id)
        ).all()
        comments = {
            row[0]: (int(row[1]), row[2]) for row in comment_rows if row[0] is not None
        }
        response: list[ProjectPaperInsightResponse] = []
        for paper in project_papers:
            document = documents.get(paper.document_id)
            page_count = document.page_count if document is not None else None
            substantive = substantive_by_document.get(paper.document_id, 0)
            coverage = (
                min(100.0, substantive * 100.0 / page_count)
                if start is None and page_count and page_count > 0
                else None
            )
            annotation_count, annotation_at = annotations.get(
                paper.document_id, (0, None)
            )
            comment_count, comment_at = comments.get(paper.document_id, (0, None))
            last_at = _project_paper_last_activity_at(
                paper_created_at=paper.created_at,
                session_timestamps=[reading_by_document[paper.document_id][1]]
                if paper.document_id in reading_by_document
                else [],
                annotation_at=annotation_at,
                comment_at=comment_at,
                start=fact_start,
            )
            response.append(
                ProjectPaperInsightResponse(
                    document_id=paper.document_id,
                    title=(document.title if document is not None else None),
                    my_active_ms=reading_by_document.get(paper.document_id, (0, None))[
                        0
                    ],
                    my_coverage_percent=coverage,
                    shared_annotation_count=annotation_count,
                    discussion_message_count=comment_count,
                    last_activity_at=last_at,
                )
            )
        response.sort(
            key=lambda item: (
                item.last_activity_at or datetime.min.replace(tzinfo=timezone.utc),
                str(item.document_id),
            ),
            reverse=True,
        )
        return response

    def _project_trend(
        self,
        *,
        project_id: UUID,
        actor_id: int,
        document_ids: Any,
        start: datetime | None,
        end: datetime,
        fact_start: datetime | None,
    ) -> list[ProjectReadingTrendPointResponse]:
        my_values = {
            day: int(active_ms or 0)
            for day, active_ms in self._db.execute(
                _project_mine_trend_statement(
                    project_id=project_id,
                    actor_id=actor_id,
                    document_ids=document_ids,
                    start=start,
                    end=end,
                )
            ).all()
        }
        team_values = {
            day: int(active_ms or 0)
            for day, active_ms in self._db.execute(
                _project_team_trend_statement(
                    project_id=project_id,
                    document_ids=document_ids,
                    start=start,
                    end=end,
                )
            ).all()
        }
        shared_values = {
            day: int(activity_count or 0)
            for day, activity_count in self._db.execute(
                _project_shared_trend_statement(
                    project_id=project_id,
                    fact_start=fact_start,
                )
            ).all()
        }
        days = sorted(set(my_values) | set(team_values) | set(shared_values))
        return [
            ProjectReadingTrendPointResponse(
                date=day,
                my_active_ms=my_values.get(day, 0),
                team_active_ms=(
                    round_project_reading_ms(team_values[day])
                    if day in team_values
                    else None
                ),
                shared_activity_count=shared_values.get(day, 0),
            )
            for day in days
        ]
