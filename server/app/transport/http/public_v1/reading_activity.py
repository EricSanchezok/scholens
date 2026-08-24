"""Authenticated HTTP adapters for reading activity and research insights."""

from __future__ import annotations

import csv
import json
from io import StringIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
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
from app.shared.application import Actor, ApplicationExecutor, OperationContext
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)


reading_activity_preferences_router = APIRouter(tags=["reading-activity"])
reading_activity_papers_router = APIRouter(tags=["reading-activity"])
reading_activity_sessions_router = APIRouter(tags=["reading-activity"])
reading_activity_projects_router = APIRouter(tags=["reading-activity"])
reading_activity_me_router = APIRouter(tags=["reading-activity"])


@reading_activity_preferences_router.get(
    "/reading-activity-preferences",
    response_model=ReadingActivityPreferencesResponse,
)
def get_reading_activity_preferences(
    actor: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ReadingActivityPreferencesResponse:
    return executor.query(
        lambda capabilities: capabilities.reading_activity.get_preferences(actor=actor)
    )


@reading_activity_preferences_router.put(
    "/reading-activity-preferences",
    response_model=ReadingActivityPreferencesResponse,
)
def update_reading_activity_preferences(
    request: ReadingActivityPreferencesUpdateRequest,
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ReadingActivityPreferencesResponse:
    return executor.command(
        lambda capabilities: capabilities.reading_activity.update_preferences(
            actor=actor,
            operation=operation,
            request=request,
        )
    )


@reading_activity_papers_router.post(
    "/{document_id}/reading-sessions",
    response_model=ReadingSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_reading_session(
    document_id: UUID,
    request: ReadingSessionStartRequest,
    actor: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ReadingSessionResponse:
    return executor.command(
        lambda capabilities: capabilities.reading_activity.start_session(
            actor=actor,
            document_id=document_id,
            request=request,
        )
    )


@reading_activity_sessions_router.put(
    "/{session_id}",
    response_model=ReadingSessionResponse,
)
def update_reading_session(
    session_id: UUID,
    request: ReadingSessionSnapshotRequest,
    actor: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ReadingSessionResponse:
    return executor.command(
        lambda capabilities: capabilities.reading_activity.update_session(
            actor=actor,
            session_id=session_id,
            request=request,
        )
    )


@reading_activity_papers_router.get(
    "/{document_id}/insights",
    response_model=PaperInsightsResponse,
)
def get_paper_insights(
    document_id: UUID,
    project_id: UUID | None = None,
    insight_range: Annotated[
        ReadingInsightsRange, Query(alias="range")
    ] = ReadingInsightsRange.THIRTY_DAYS,
    time_zone: Annotated[str, Query(min_length=1, max_length=64)] = "UTC",
    actor: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> PaperInsightsResponse:
    return executor.query(
        lambda capabilities: capabilities.reading_activity.paper_insights(
            actor=actor,
            document_id=document_id,
            project_id=project_id,
            insight_range=insight_range,
            time_zone=time_zone,
        )
    )


@reading_activity_projects_router.get(
    "/{project_id}/insights",
    response_model=ProjectInsightsResponse,
)
def get_project_insights(
    project_id: UUID,
    insight_range: Annotated[
        ReadingInsightsRange, Query(alias="range")
    ] = ReadingInsightsRange.THIRTY_DAYS,
    actor: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ProjectInsightsResponse:
    return executor.query(
        lambda capabilities: capabilities.reading_activity.project_insights(
            actor=actor,
            project_id=project_id,
            insight_range=insight_range,
        )
    )


@reading_activity_projects_router.get(
    "/{project_id}/activity",
    response_model=ProjectActivityResponse,
)
def get_project_activity(
    project_id: UUID,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None,
    actor: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ProjectActivityResponse:
    return executor.query(
        lambda capabilities: capabilities.reading_activity.project_activity(
            actor=actor,
            project_id=project_id,
            limit=limit,
            cursor=cursor,
        )
    )


@reading_activity_me_router.get(
    "/research-insights",
    response_model=ResearchInsightsResponse,
)
def get_research_insights(
    insight_range: Annotated[
        ReadingInsightsRange, Query(alias="range")
    ] = ReadingInsightsRange.YEAR,
    time_zone: Annotated[str, Query(min_length=1, max_length=64)] = "UTC",
    actor: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ResearchInsightsResponse:
    return executor.query(
        lambda capabilities: capabilities.reading_activity.research_insights(
            actor=actor,
            insight_range=insight_range,
            time_zone=time_zone,
        )
    )


@reading_activity_me_router.post(
    "/reading-activity/paper-summaries",
    response_model=ReadingPaperSummariesResponse,
)
def get_reading_paper_summaries(
    request: ReadingPaperSummaryRequest,
    actor: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ReadingPaperSummariesResponse:
    return executor.query(
        lambda capabilities: capabilities.reading_activity.paper_summaries(
            actor=actor,
            request=request,
        )
    )


@reading_activity_me_router.get(
    "/reading-activity/export",
    response_model=ReadingActivityExportResponse,
    responses={
        200: {
            "content": {"text/csv": {}},
            "description": "JSON or CSV reading activity export",
        }
    },
)
def export_reading_activity(
    export_format: Annotated[
        ReadingExportFormat, Query(alias="format")
    ] = ReadingExportFormat.JSON,
    cursor: Annotated[str | None, Query(min_length=1, max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 1000,
    include_header: bool = True,
    actor: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> ReadingActivityExportResponse | Response:
    exported = executor.query(
        lambda capabilities: capabilities.reading_activity.export(
            actor=actor,
            export_format=export_format,
            cursor=cursor,
            limit=limit,
        )
    )
    if export_format is ReadingExportFormat.JSON:
        return exported
    headers = {
        "Content-Disposition": 'attachment; filename="scholens-reading-activity.csv"'
    }
    if exported.next_cursor is not None:
        headers["X-Next-Cursor"] = exported.next_cursor
    return Response(
        content=_export_csv(exported, include_header=include_header),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@reading_activity_sessions_router.delete(
    "/{session_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_reading_session(
    session_id: UUID,
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.reading_activity.delete_session(
            actor=actor,
            operation=operation,
            session_id=session_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@reading_activity_me_router.delete(
    "/reading-activity", status_code=status.HTTP_204_NO_CONTENT
)
def delete_all_reading_activity(
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.reading_activity.delete_all(
            actor=actor,
            operation=operation,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@reading_activity_papers_router.delete(
    "/{document_id}/reading-activity", status_code=status.HTTP_204_NO_CONTENT
)
def delete_paper_reading_activity(
    document_id: UUID,
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.reading_activity.delete_paper(
            actor=actor,
            operation=operation,
            document_id=document_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@reading_activity_projects_router.delete(
    "/{project_id}/me/reading-activity",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_project_reading_contribution(
    project_id: UUID,
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.reading_activity.delete_project_contribution(
            actor=actor,
            operation=operation,
            project_id=project_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _export_csv(
    exported: ReadingActivityExportResponse,
    *,
    include_header: bool,
) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    if include_header:
        writer.writerow(("record_type", "payload_json"))
    for record in exported.records:
        writer.writerow(
            (
                record.record_type,
                json.dumps(
                    record.payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
        )
    return buffer.getvalue()


__all__ = [
    "reading_activity_me_router",
    "reading_activity_papers_router",
    "reading_activity_preferences_router",
    "reading_activity_projects_router",
    "reading_activity_sessions_router",
]
