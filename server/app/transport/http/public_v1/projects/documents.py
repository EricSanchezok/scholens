"""HTTP adapter for documents held by Projects."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.action_confirmations.application import confirmation_digest
from app.modules.action_confirmations.contracts import (
    ActionImpact,
    ConfirmationChallenge,
)
from app.modules.projects.application.contracts import (
    AddPaperToProjectRequest,
    CollectPaperFromProjectRequest,
    ProjectListResponse,
    ProjectPaperCollectedResponse,
    ProjectPaperFileUrlResponse,
    ProjectPaperListResponse,
    ProjectPaperSort,
    ProjectOutputListResponse,
    ProjectPapersAddedResponse,
    ProjectPendingUploadsResponse,
)
from app.modules.papers.application.contracts.documents import LibraryOutputSort
from app.shared.domain import AppError, FailureKind
from app.shared.domain.enums import ResearchItemKind
from app.shared.application import Actor, ApplicationExecutor, OperationContext
from app.shared.domain.enums import PaperStatus
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, Header, Query, Response, status

project_papers_router = APIRouter()
paper_projects_router = APIRouter()
library_project_papers_router = APIRouter()


@library_project_papers_router.post(
    "/papers",
    response_model=ProjectPaperCollectedResponse,
    status_code=status.HTTP_201_CREATED,
)
def collect_paper_from_project(
    request: CollectPaperFromProjectRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> ProjectPaperCollectedResponse:
    return executor.command(
        lambda capabilities: capabilities.projects.collect_document(
            actor=current_user,
            operation=operation,
            request=request,
        )
    )


@project_papers_router.post(
    "/{project_id}/papers",
    response_model=ProjectPapersAddedResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_paper_to_project(
    project_id: UUID,
    request: AddPaperToProjectRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> ProjectPapersAddedResponse:
    return executor.command(
        lambda capabilities: capabilities.projects.add_documents(
            actor=current_user,
            operation=operation,
            project_id=project_id,
            request=request,
        )
    )


@project_papers_router.get(
    "/{project_id}/papers",
    response_model=ProjectPaperListResponse,
)
def get_project_papers(
    project_id: UUID,
    load_urls: bool = False,
    q: str | None = Query(default=None, max_length=240),
    personal_statuses: list[PaperStatus] = Query(default=[]),
    personal_tag_ids: list[UUID] = Query(default=[]),
    sort: ProjectPaperSort = ProjectPaperSort.ADDED_DESC,
    cursor: str | None = Query(default=None, min_length=1, max_length=2048),
    limit: int = Query(default=20, ge=1, le=100),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ProjectPaperListResponse:
    return executor.query(
        lambda capabilities: capabilities.projects.documents(
            actor=current_user,
            project_id=project_id,
            load_urls=load_urls,
            query=q,
            personal_statuses=tuple(personal_statuses),
            personal_tag_ids=tuple(personal_tag_ids),
            sort=sort,
            cursor=cursor,
            limit=limit,
        )
    )


@project_papers_router.get(
    "/{project_id}/outputs",
    response_model=ProjectOutputListResponse,
)
def get_project_outputs(
    project_id: UUID,
    q: str | None = Query(default=None, max_length=240),
    kinds: list[ResearchItemKind] = Query(default=[]),
    sort: LibraryOutputSort = LibraryOutputSort.UPDATED_DESC,
    cursor: str | None = Query(default=None, min_length=1, max_length=2048),
    limit: int = Query(default=20, ge=1, le=100),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ProjectOutputListResponse:
    return executor.query(
        lambda capabilities: capabilities.projects.outputs(
            actor=current_user,
            project_id=project_id,
            query=q,
            kinds=tuple(kinds),
            sort=sort,
            cursor=cursor,
            limit=limit,
        )
    )


@project_papers_router.get(
    "/{project_id}/papers/pending-jobs",
    response_model=ProjectPendingUploadsResponse,
)
def get_project_pending_jobs(
    project_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ProjectPendingUploadsResponse:
    return executor.query(
        lambda capabilities: capabilities.projects.pending_uploads(
            actor=current_user,
            project_id=project_id,
        )
    )


@project_papers_router.get(
    "/{project_id}/papers/{document_id}/download-url",
    response_model=ProjectPaperFileUrlResponse,
)
def get_project_paper_file_url(
    project_id: UUID,
    document_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ProjectPaperFileUrlResponse:
    return executor.query(
        lambda capabilities: capabilities.projects.document_download(
            actor=current_user,
            project_id=project_id,
            document_id=document_id,
        )
    )


@paper_projects_router.get(
    "/{document_id}/projects",
    response_model=ProjectListResponse,
)
def get_projects_from_document_id(
    document_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> ProjectListResponse:
    return executor.query(
        lambda capabilities: capabilities.projects.projects_for_document(
            actor=current_user,
            document_id=document_id,
        )
    )


@project_papers_router.delete(
    "/{project_id}/papers/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_paper_from_project(
    project_id: UUID,
    document_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    confirmation_token: Annotated[
        str | None,
        Header(
            alias="X-Scholens-Confirmation-Token",
            min_length=32,
            max_length=256,
            description=(
                "Short-lived token returned by the first removal attempt. Retry with "
                "unchanged path parameters only after the user approves its impact."
            ),
        ),
    ] = None,
) -> Response:
    def execute(
        capabilities: ApplicationCapabilities,
    ) -> tuple[ConfirmationChallenge, int, int] | None:
        project = capabilities.projects.get(
            actor=current_user,
            project_id=project_id,
        )
        items = capabilities.research_items.list_document(
            actor=current_user,
            document_id=document_id,
            project_id=project_id,
        ).items
        threads = [
            item
            for item in items
            if item.kind is ResearchItemKind.ANNOTATION_THREAD
            and getattr(item.audience, "project_id", None) == project_id
        ]
        comment_count = sum(
            len(item.annotation_thread.comments)
            for item in threads
            if item.annotation_thread is not None
        )
        arguments_hash = confirmation_digest(
            {"project_id": str(project_id), "document_id": str(document_id)}
        )
        state = {"project": project, "threads": threads}
        state_fingerprint = confirmation_digest(state)
        if confirmation_token is None:
            return (
                capabilities.action_confirmations.issue(
                    actor=current_user,
                    operation=operation,
                    action="remove_paper_from_project",
                    arguments_hash=arguments_hash,
                    state_fingerprint=state_fingerprint,
                    impact=ActionImpact(
                        title="Remove paper from Project",
                        summary=f"Remove this paper from '{project.title}'.",
                        consequences=[
                            f"Delete {len(threads)} Project annotation threads and "
                            f"{comment_count} comments anchored to this paper."
                        ],
                        affected_resources=[
                            f"project:{project_id}",
                            f"document:{document_id}",
                        ],
                    ),
                ),
                len(threads),
                comment_count,
            )
        capabilities.action_confirmations.consume(
            actor=current_user,
            operation=operation,
            token=confirmation_token,
            action="remove_paper_from_project",
            arguments_hash=arguments_hash,
            state_fingerprint=state_fingerprint,
        )
        capabilities.projects.remove_document(
            actor=current_user,
            operation=operation,
            project_id=project_id,
            document_id=document_id,
        )
        return None

    preview = executor.command(execute)
    if preview is not None:
        challenge, thread_count, comment_count = preview
        details = challenge.model_dump(mode="json")
        details["thread_count"] = thread_count
        details["comment_count"] = comment_count
        raise AppError(
            code="confirmation_required",
            message="User confirmation is required before removing this Project paper",
            kind=FailureKind.CONFLICT,
            details=details,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
