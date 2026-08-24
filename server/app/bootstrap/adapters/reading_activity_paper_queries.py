"""Single-paper reading-insight projections."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.modules.papers.infrastructure.access import require_document_access
from app.modules.papers.infrastructure.document_loading import (
    DOCUMENT_READING_ACTIVITY_COLUMNS,
)
from app.modules.reading_activity.application.contracts import (
    PaperInsightsResponse,
    ReadingInsightsRange,
    ReadingPageInsightResponse,
)
from app.modules.reading_activity.infrastructure.models import (
    ReadingPersonalHourRollup,
    ReadingPersonalPageRollup,
)
from app.modules.reading_activity.infrastructure.insight_aggregates import (
    reading_summary_from_hour_source,
    reading_trend_from_hour_source,
)
from app.modules.reading_activity.infrastructure.shared import (
    ReadingActivityRepositoryBase,
    _aggregate_page_rollups,
    _hour_bucket,
    _range_start,
)
from app.modules.reading_activity.domain import (
    ACTIVE_READING_DEFINITION_VERSION,
    PAGE_VERTICAL_SEGMENT_COUNT,
    SUBSTANTIVE_PAGE_ACTIVE_MS,
)
from app.modules.research.infrastructure.models import AnnotationThread, ResearchItem
from app.shared.application import Actor
from app.shared.domain.enums import ResearchAudienceType, ResearchItemKind


class PaperInsightsRepository(ReadingActivityRepositoryBase):
    def paper_insights(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        insight_range: ReadingInsightsRange,
        time_zone: str,
        project_id: UUID | None = None,
    ) -> PaperInsightsResponse:
        access = require_document_access(
            self._db,
            document_id=document_id,
            user_id=actor.id,
            project_id=project_id,
            document_columns=DOCUMENT_READING_ACTIVITY_COLUMNS,
        )
        now = self._clock.now()
        start = _range_start(insight_range, now, time_zone=time_zone)
        end = _hour_bucket(now)
        hour_source = select(
            ReadingPersonalHourRollup.bucket_start.label("bucket_start"),
            ReadingPersonalHourRollup.active_ms.label("active_ms"),
            ReadingPersonalHourRollup.visible_ms.label("visible_ms"),
            ReadingPersonalHourRollup.session_count.label("session_count"),
        ).where(
            ReadingPersonalHourRollup.user_id == actor.id,
            ReadingPersonalHourRollup.document_id == document_id,
            ReadingPersonalHourRollup.metric_definition_version
            == ACTIVE_READING_DEFINITION_VERSION,
            ReadingPersonalHourRollup.bucket_start <= end,
            *((ReadingPersonalHourRollup.bucket_start >= start,) if start else ()),
        )
        pages = (
            self._page_insights(
                actor=actor,
                document_id=document_id,
                project_id=project_id,
            )
            if insight_range is ReadingInsightsRange.ALL
            else []
        )
        earliest = self._reading_data_since(user_id=actor.id, document_id=document_id)
        page_metrics = pages if insight_range is ReadingInsightsRange.ALL else None
        summary = reading_summary_from_hour_source(
            self._db,
            hour_source=hour_source,
            substantive_pages=(
                sum(
                    page.active_ms >= SUBSTANTIVE_PAGE_ACTIVE_MS
                    for page in page_metrics
                )
                if page_metrics is not None
                else None
            ),
            page_count=access.document.page_count,
            time_zone=time_zone,
        )
        return PaperInsightsResponse(
            document_id=document_id,
            page_count=access.document.page_count,
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
            pages=pages,
        )

    def _page_insights(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> list[ReadingPageInsightResponse]:
        pages = _aggregate_page_rollups(
            list(
                self._db.scalars(
                    select(ReadingPersonalPageRollup).where(
                        ReadingPersonalPageRollup.user_id == actor.id,
                        ReadingPersonalPageRollup.document_id == document_id,
                        ReadingPersonalPageRollup.metric_definition_version
                        == ACTIVE_READING_DEFINITION_VERSION,
                    )
                ).all()
            )
        )
        counts = self._annotation_page_counts(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
        )
        for page in pages:
            page.annotation_count = counts.get(page.page_number, 0)
        present_pages = {page.page_number for page in pages}
        pages.extend(
            ReadingPageInsightResponse(
                page_number=page_number,
                active_ms=0,
                visible_ms=0,
                visit_count=0,
                vertical_segments_ms=[0] * PAGE_VERTICAL_SEGMENT_COUNT,
                annotation_count=annotation_count,
            )
            for page_number, annotation_count in counts.items()
            if page_number not in present_pages
        )
        pages.sort(key=lambda page: page.page_number)
        return pages

    def _annotation_page_counts(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
    ) -> dict[int, int]:
        audience_filter: ColumnElement[bool] = (
            ResearchItem.created_by_id == actor.id
        ) & (ResearchItem.audience_type == ResearchAudienceType.PERSONAL.value)
        if project_id is not None:
            audience_filter = or_(
                audience_filter,
                (ResearchItem.audience_type == ResearchAudienceType.PROJECT.value)
                & (ResearchItem.audience_project_id == project_id),
            )
        rows = self._db.execute(
            select(AnnotationThread.page_number, func.count(ResearchItem.id))
            .join(
                ResearchItem,
                ResearchItem.id == AnnotationThread.research_item_id,
            )
            .where(
                ResearchItem.target_document_id == document_id,
                ResearchItem.kind == ResearchItemKind.ANNOTATION_THREAD.value,
                audience_filter,
                AnnotationThread.page_number.is_not(None),
            )
            .group_by(AnnotationThread.page_number)
        ).all()
        return {int(page): int(count) for page, count in rows if page is not None}
