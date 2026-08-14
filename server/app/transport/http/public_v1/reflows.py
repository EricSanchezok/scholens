"""Authorized document reflow query and retry routes."""

from __future__ import annotations

from uuid import UUID

from app.bootstrap.capabilities import ApplicationCapabilities
from app.bootstrap.execution import get_application_executor
from app.modules.reflows.application import (
    DocumentReflowAssetUrlResponse,
    DocumentReflowResponse,
)
from app.shared.application import Actor, ApplicationExecutor, OperationContext
from app.transport.http.public_v1.auth_dependencies import (
    get_required_operation,
    get_required_user,
)
from fastapi import APIRouter, Depends, status

paper_reflows_router = APIRouter(tags=["reflows"])


@paper_reflows_router.get(
    "/{document_id}/reflow",
    response_model=DocumentReflowResponse,
)
def get_document_reflow(
    document_id: UUID,
    actor: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> DocumentReflowResponse:
    return executor.query(
        lambda capabilities: capabilities.document_reflows.get(
            actor=actor,
            document_id=document_id,
        )
    )


@paper_reflows_router.get(
    "/{document_id}/reflow/assets/{asset_id}/url",
    response_model=DocumentReflowAssetUrlResponse,
)
def get_document_reflow_asset_url(
    document_id: UUID,
    asset_id: str,
    actor: Actor = Depends(get_required_user),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> DocumentReflowAssetUrlResponse:
    return executor.query(
        lambda capabilities: capabilities.document_reflows.asset_url(
            actor=actor,
            document_id=document_id,
            asset_id=asset_id,
        )
    )


@paper_reflows_router.post(
    "/{document_id}/reflow/retries",
    response_model=DocumentReflowResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_document_reflow(
    document_id: UUID,
    actor: Actor = Depends(get_required_user),
    operation: OperationContext = Depends(get_required_operation),
    executor: ApplicationExecutor[ApplicationCapabilities] = Depends(
        get_application_executor
    ),
) -> DocumentReflowResponse:
    return executor.command(
        lambda capabilities: capabilities.document_reflows.retry(
            actor=actor,
            operation=operation,
            document_id=document_id,
        )
    )


__all__ = ["paper_reflows_router"]
