"""Cloud-authenticated management of user-owned external integrations."""

from __future__ import annotations

from app.bootstrap.execution import get_integration_workflow
from app.bootstrap.workflows.integrations import IntegrationWorkflow
from app.modules.integrations.connections.application import (
    IntegrationConnectRequest,
    IntegrationUpdateRequest,
)
from app.modules.integrations.connections.domain import IntegrationProvider
from app.transport.http.public_v1.legacy_integrations import (
    LegacyIntegrationConnectionResponse,
    LegacyIntegrationListResponse,
    legacy_connection,
)
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
        provider = IntegrationProvider(value)
        if provider is IntegrationProvider.DEEPSEEK:
            raise ValueError("Use the connections catalog for model providers")
        return provider
    except ValueError as exc:
        raise AppError(
            code="integration_not_supported",
            message="Integration provider is not supported",
            kind=FailureKind.NOT_FOUND,
        ) from exc


@integrations_router.get(
    "", response_model=LegacyIntegrationListResponse, deprecated=True
)
def list_integrations(
    workflow: IntegrationWorkflow = Depends(get_integration_workflow),
    actor: Actor = Depends(get_required_user),
) -> LegacyIntegrationListResponse:
    return LegacyIntegrationListResponse(
        items=[
            legacy_connection(item)
            for item in workflow.list(actor=actor).items
            if item.provider is not IntegrationProvider.DEEPSEEK
        ]
    )


@integrations_router.put(
    "/{provider}", response_model=LegacyIntegrationConnectionResponse, deprecated=True
)
async def connect_integration(
    provider: str,
    request: IntegrationConnectRequest,
    workflow: IntegrationWorkflow = Depends(get_integration_workflow),
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> LegacyIntegrationConnectionResponse:
    result = await workflow.connect(
        actor=actor,
        operation=operation,
        provider=_integration_provider(provider),
        credential=request.credential.get_secret_value(),
    )
    return legacy_connection(result)


@integrations_router.patch(
    "/{provider}", response_model=LegacyIntegrationConnectionResponse, deprecated=True
)
async def update_integration(
    provider: str,
    request: IntegrationUpdateRequest,
    workflow: IntegrationWorkflow = Depends(get_integration_workflow),
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
) -> LegacyIntegrationConnectionResponse:
    result = await workflow.set_enabled(
        actor=actor,
        operation=operation,
        provider=_integration_provider(provider),
        enabled=request.enabled,
    )
    return legacy_connection(result)


@integrations_router.delete(
    "/{provider}", status_code=status.HTTP_204_NO_CONTENT, deprecated=True
)
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
