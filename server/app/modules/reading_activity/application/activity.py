"""Reading activity use cases shared by the authenticated Web API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.modules.operation_journal.application import OperationJournal
from app.modules.operation_journal.domain import OperationAction, ResourceRef
from app.modules.reading_activity.application.contracts import (
    PaperInsightsResponse,
    ProjectActivityResponse,
    ProjectInsightsResponse,
    ReadingActivityExportResponse,
    ReadingActivityPreferencesResponse,
    ReadingActivityPreferencesUpdateRequest,
    ReadingExportFormat,
    ReadingInsightsRange,
    ReadingPaperSummariesResponse,
    ReadingPaperSummaryRequest,
    ReadingSessionResponse,
    ReadingSessionSnapshotRequest,
    ReadingSessionStartRequest,
    ResearchInsightsResponse,
)
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind


@dataclass(frozen=True, slots=True)
class ReadingMutationResult[T]:
    value: T
    changed: bool


class ReadingActivityGateway(Protocol):
    def get_preferences(
        self, *, user_id: int
    ) -> ReadingActivityPreferencesResponse: ...

    def update_preferences(
        self,
        *,
        user_id: int,
        request: ReadingActivityPreferencesUpdateRequest,
    ) -> ReadingMutationResult[ReadingActivityPreferencesResponse]: ...

    def start_session(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        request: ReadingSessionStartRequest,
    ) -> ReadingMutationResult[ReadingSessionResponse]: ...

    def update_session(
        self,
        *,
        actor: Actor,
        session_id: UUID,
        request: ReadingSessionSnapshotRequest,
    ) -> ReadingMutationResult[ReadingSessionResponse]: ...

    def paper_insights(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
        insight_range: ReadingInsightsRange,
        time_zone: str,
    ) -> PaperInsightsResponse: ...

    def project_insights(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        insight_range: ReadingInsightsRange,
    ) -> ProjectInsightsResponse: ...

    def project_activity(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> ProjectActivityResponse: ...

    def research_insights(
        self,
        *,
        actor: Actor,
        insight_range: ReadingInsightsRange,
        time_zone: str,
    ) -> ResearchInsightsResponse: ...

    def paper_summaries(
        self,
        *,
        actor: Actor,
        request: ReadingPaperSummaryRequest,
    ) -> ReadingPaperSummariesResponse: ...

    def export(
        self,
        *,
        actor: Actor,
        export_format: ReadingExportFormat,
        cursor: str | None,
        limit: int,
    ) -> ReadingActivityExportResponse: ...

    def delete_session(self, *, actor: Actor, session_id: UUID) -> int: ...

    def delete_all(self, *, actor: Actor) -> int: ...

    def delete_paper(self, *, actor: Actor, document_id: UUID) -> int: ...

    def delete_project_contribution(self, *, actor: Actor, project_id: UUID) -> int: ...


READING_ACTIVITY_PREFERENCES_UPDATED = OperationAction(
    "reading_activity.preferences_updated"
)
READING_ACTIVITY_SESSION_DELETED = OperationAction("reading_activity.session_deleted")
READING_ACTIVITY_PAPER_DELETED = OperationAction("reading_activity.paper_deleted")
READING_ACTIVITY_PROJECT_CONTRIBUTION_DELETED = OperationAction(
    "reading_activity.project_contribution_deleted"
)
READING_ACTIVITY_ALL_DELETED = OperationAction("reading_activity.all_deleted")


class ReadingActivity:
    def __init__(
        self,
        gateway: ReadingActivityGateway,
        *,
        journal: OperationJournal,
    ) -> None:
        self._gateway = gateway
        self._journal = journal

    def get_preferences(self, *, actor: Actor) -> ReadingActivityPreferencesResponse:
        return self._gateway.get_preferences(user_id=actor.id)

    def update_preferences(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        request: ReadingActivityPreferencesUpdateRequest,
    ) -> ReadingActivityPreferencesResponse:
        result = self._gateway.update_preferences(user_id=actor.id, request=request)
        if result.changed:
            self._journal.append(
                actor=actor,
                operation=operation,
                action=READING_ACTIVITY_PREFERENCES_UPDATED,
                resources=(ResourceRef("reading_activity_preferences", str(actor.id)),),
            )
        return result.value

    def start_session(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        request: ReadingSessionStartRequest,
    ) -> ReadingSessionResponse:
        _require_time_zone(request.time_zone)
        result = self._gateway.start_session(
            actor=actor,
            document_id=document_id,
            request=request,
        )
        return result.value

    def update_session(
        self,
        *,
        actor: Actor,
        session_id: UUID,
        request: ReadingSessionSnapshotRequest,
    ) -> ReadingSessionResponse:
        # Passive session data remains only in the user-owned reading ledger;
        # high-frequency heartbeats are not Operation Journal entries.
        return self._gateway.update_session(
            actor=actor,
            session_id=session_id,
            request=request,
        ).value

    def paper_insights(
        self,
        *,
        actor: Actor,
        document_id: UUID,
        project_id: UUID | None,
        insight_range: ReadingInsightsRange,
        time_zone: str,
    ) -> PaperInsightsResponse:
        _require_time_zone(time_zone)
        return self._gateway.paper_insights(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
            insight_range=insight_range,
            time_zone=time_zone,
        )

    def project_insights(
        self,
        *,
        actor: Actor,
        project_id: UUID,
        insight_range: ReadingInsightsRange,
    ) -> ProjectInsightsResponse:
        return self._gateway.project_insights(
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
        return self._gateway.project_activity(
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
        _require_time_zone(time_zone)
        return self._gateway.research_insights(
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
        return self._gateway.paper_summaries(actor=actor, request=request)

    def export(
        self,
        *,
        actor: Actor,
        export_format: ReadingExportFormat,
        cursor: str | None,
        limit: int,
    ) -> ReadingActivityExportResponse:
        return self._gateway.export(
            actor=actor,
            export_format=export_format,
            cursor=cursor,
            limit=limit,
        )

    def delete_session(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        session_id: UUID,
    ) -> None:
        if self._gateway.delete_session(actor=actor, session_id=session_id):
            self._journal.append(
                actor=actor,
                operation=operation,
                action=READING_ACTIVITY_SESSION_DELETED,
                resources=(ResourceRef("reading_session", str(session_id)),),
            )

    def delete_all(self, *, actor: Actor, operation: OperationContext) -> None:
        if self._gateway.delete_all(actor=actor):
            self._journal.append(
                actor=actor,
                operation=operation,
                action=READING_ACTIVITY_ALL_DELETED,
                resources=(ResourceRef("reading_activity", str(actor.id)),),
            )

    def delete_paper(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        document_id: UUID,
    ) -> None:
        if self._gateway.delete_paper(actor=actor, document_id=document_id):
            self._journal.append(
                actor=actor,
                operation=operation,
                action=READING_ACTIVITY_PAPER_DELETED,
                resources=(ResourceRef("paper", str(document_id)),),
            )

    def delete_project_contribution(
        self,
        *,
        actor: Actor,
        operation: OperationContext,
        project_id: UUID,
    ) -> None:
        if self._gateway.delete_project_contribution(
            actor=actor,
            project_id=project_id,
        ):
            self._journal.append(
                actor=actor,
                operation=operation,
                action=READING_ACTIVITY_PROJECT_CONTRIBUTION_DELETED,
                resources=(ResourceRef("project", str(project_id)),),
            )


def _require_time_zone(value: str) -> None:
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise AppError(
            code="reading_activity_time_zone_invalid",
            message="time_zone must be a valid IANA time zone",
            kind=FailureKind.INVALID_ARGUMENT,
        ) from exc


__all__ = [
    "ReadingActivity",
    "ReadingActivityGateway",
    "ReadingMutationResult",
]
