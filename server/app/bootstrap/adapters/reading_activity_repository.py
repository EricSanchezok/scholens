"""Explicitly composed SQLAlchemy reading-activity gateway."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.bootstrap.adapters.reading_activity_mutations import (
    ReadingActivityMutationRepository,
)
from app.bootstrap.adapters.reading_activity_paper_queries import (
    PaperInsightsRepository,
)
from app.bootstrap.adapters.reading_activity_personal_queries import (
    PersonalInsightsRepository,
)
from app.bootstrap.adapters.reading_activity_project_activity_queries import (
    ProjectActivityRepository,
)
from app.bootstrap.adapters.reading_activity_project_queries import (
    ProjectInsightsRepository,
)
from app.modules.reading_activity.application.contracts import (
    PaperInsightsResponse,
    ProjectActivityResponse,
    ProjectInsightsResponse,
    ReadingInsightsRange,
    ReadingPaperSummariesResponse,
    ReadingPaperSummaryRequest,
    ResearchInsightsResponse,
)
from app.shared.application import Actor, Clock, SignedCursorCodec


class SqlAlchemyReadingActivity(ReadingActivityMutationRepository):
    """Canonical gateway with focused query collaborators and one mutation core."""

    def __init__(
        self,
        db: Session,
        *,
        clock: Clock,
        export_cursors: SignedCursorCodec | None = None,
        activity_cursors: SignedCursorCodec | None = None,
    ) -> None:
        super().__init__(
            db,
            clock=clock,
            export_cursors=export_cursors,
            activity_cursors=activity_cursors,
        )
        self._paper_insights = PaperInsightsRepository(db, clock=clock)
        self._personal_insights = PersonalInsightsRepository(db, clock=clock)
        self._project_insights = ProjectInsightsRepository(db, clock=clock)
        self._project_activity = ProjectActivityRepository(
            db,
            clock=clock,
            activity_cursors=activity_cursors,
        )

    def paper_insights(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        insight_range: ReadingInsightsRange,
        time_zone: str,
        project_id: UUID | None = None,
    ) -> PaperInsightsResponse:
        return self._paper_insights.paper_insights(
            actor=actor,
            document_id=document_id,
            insight_range=insight_range,
            time_zone=time_zone,
            project_id=project_id,
        )

    def project_insights(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        insight_range: ReadingInsightsRange,
    ) -> ProjectInsightsResponse:
        return self._project_insights.project_insights(
            actor=actor,
            project_id=project_id,
            insight_range=insight_range,
        )

    def project_activity(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> ProjectActivityResponse:
        return self._project_activity.project_activity(
            actor=actor,
            project_id=project_id,
            limit=limit,
            cursor=cursor,
        )

    def research_insights(
        self,
        *,
        actor: Actor,
        insight_range: ReadingInsightsRange,
        time_zone: str,
    ) -> ResearchInsightsResponse:
        return self._personal_insights.research_insights(
            actor=actor,
            insight_range=insight_range,
            time_zone=time_zone,
        )

    def paper_summaries(
        self,
        *,
        actor: Actor,
        request: ReadingPaperSummaryRequest,
    ) -> ReadingPaperSummariesResponse:
        return self._personal_insights.paper_summaries(
            actor=actor,
            request=request,
        )


__all__ = ["SqlAlchemyReadingActivity"]
