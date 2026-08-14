"""Typed Library tag API bound to personal LibraryPaper references."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.papers.application.contracts.tags import (
    LibraryTagAssignmentRequest,
    LibraryTagAssignmentResponse,
    LibraryTagCreateRequest,
    LibraryTagListResponse,
    LibraryTagRenameRequest,
    LibraryTagResponse,
)
from app.shared.application import Actor, ApplicationExecutor, OperationContext
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, Response, status

library_tags_router = APIRouter()


@library_tags_router.get("/tags", response_model=LibraryTagListResponse)
def list_library_tags(
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
) -> LibraryTagListResponse:
    return executor.query(
        lambda capabilities: capabilities.library_tags.list(actor=current_user)
    )


@library_tags_router.post(
    "/tags",
    response_model=LibraryTagResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_library_tag(
    request: LibraryTagCreateRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> LibraryTagResponse:
    return executor.command(
        lambda capabilities: capabilities.library_tags.create(
            actor=current_user,
            operation=operation,
            request=request,
        )
    )


@library_tags_router.patch(
    "/tags/{tag_id}",
    response_model=LibraryTagResponse,
)
def rename_library_tag(
    tag_id: UUID,
    request: LibraryTagRenameRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> LibraryTagResponse:
    return executor.command(
        lambda capabilities: capabilities.library_tags.rename(
            actor=current_user,
            operation=operation,
            tag_id=tag_id,
            request=request,
        )
    )


@library_tags_router.delete(
    "/tags/{tag_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_library_tag(
    tag_id: UUID,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> Response:
    executor.command(
        lambda capabilities: capabilities.library_tags.delete(
            actor=current_user,
            operation=operation,
            tag_id=tag_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@library_tags_router.put(
    "/tags/assignments",
    response_model=LibraryTagAssignmentResponse,
)
def replace_library_tag_assignments(
    request: LibraryTagAssignmentRequest,
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
    current_user: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> LibraryTagAssignmentResponse:
    return executor.command(
        lambda capabilities: capabilities.library_tags.replace_assignments(
            actor=current_user,
            operation=operation,
            request=request,
        )
    )
