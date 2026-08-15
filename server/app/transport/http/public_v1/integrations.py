"""Cloud-authenticated management of user-owned external integrations."""

from __future__ import annotations

from app.bootstrap.execution import get_integration_workflow
from app.bootstrap.workflows.integrations import IntegrationWorkflow
from app.modules.integrations.connections.application import (
    IntegrationConnectRequest,
    IntegrationConnectionResponse,
    IntegrationListResponse,
    IntegrationUpdateRequest,
)
from app.modules.integrations.connections.domain import IntegrationProvider
from app.shared.application import Actor, OperationContext
from app.shared.domain import AppError, FailureKind
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, Response, status

integrations_router = APIRouter(tags=["integrations"])


def _integration_provider(value: str) -> IntegrationProvider:
    try:
        return IntegrationProvider(value)
    except ValueError as exc:
        raise AppError(
            code="integration_not_supported",
            message="Integration provider is not supported",
            kind=FailureKind.NOT_FOUND,
        ) from exc


@integrations_router.get("", response_model=IntegrationListResponse)
def list_integrations(
    workflow: IntegrationWorkflow = Depends(get_integration_workflow),
    actor: Actor = Depends(get_required_user),
) -> IntegrationListResponse:
    return workflow.list(actor=actor)


@integrations_router.put("/{provider}", response_model=IntegrationConnectionResponse)
async def connect_integration(
    provider: str,
    request: IntegrationConnectRequest,
    workflow: IntegrationWorkflow = Depends(get_integration_workflow),
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> IntegrationConnectionResponse:
    return await workflow.connect(
        actor=actor,
        operation=operation,
        provider=_integration_provider(provider),
        credential=request.credential.get_secret_value(),
    )


@integrations_router.patch("/{provider}", response_model=IntegrationConnectionResponse)
async def update_integration(
    provider: str,
    request: IntegrationUpdateRequest,
    workflow: IntegrationWorkflow = Depends(get_integration_workflow),
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> IntegrationConnectionResponse:
    return await workflow.set_enabled(
        actor=actor,
        operation=operation,
        provider=_integration_provider(provider),
        enabled=request.enabled,
    )


@integrations_router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_integration(
    provider: str,
    workflow: IntegrationWorkflow = Depends(get_integration_workflow),
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> Response:
    workflow.disconnect(
        actor=actor,
        operation=operation,
        provider=_integration_provider(provider),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
